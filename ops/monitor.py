"""Gate S — the divergence check, plus the S1 crowding light.

    python3 ops/monitor.py                  # grade the live path
    python3 ops/monitor.py --rebuild-bands  # recompute the bootstrap bands
    python3 ops/monitor.py --refresh-crowding

TWO SEPARATE THINGS LIVE HERE, and they must not be blended.

(1) GATE S, from PREREGISTRATION.md:

      "Bands set from block-bootstrap of the audited backtest (10th-90th
       percentile of 3-month return and Sharpe). Live-sim inside the band ->
       continue; below 10th pct -> halve size and review; drawdown > 1.25x
       backtest maxDD -> suspend, written review."

    All three are encoded below. The bands come from a moving-block bootstrap
    with 6-month blocks of the frozen spec's own backtest path, restricted to
    the TRADEABLE ERA (2017+) because results/S1_FALLEN_ANGEL.md recommendation
    3 says so in terms: bands built on 14-year returns "will be far too
    generous to catch a sleeve that is already earning zero."

    Gate S is not graded until there are 3 months of live days. Before that it
    reports INSUFFICIENT_DATA. A comfortable-looking CONTINUE off two weeks of
    data would be worse than no reading at all.

(2) THE S1 CROWDING KILL CRITERION, from scripts/s1_crowding_monitor.py.

    This is NOT a hypothetical. At the time this file was written the light was
    RED and the kill criterion had ALREADY FIRED: 36-month ANGL-vs-HYG alpha
    -0.77%/yr against a +1.06%/yr planning floor, 36 consecutive months below
    it against a trigger of 6. The encoded action is CUT SIZE. This monitor
    surfaces that on every single run, and it says so at the top of the output,
    whatever Gate S happens to think.

    If the crowding light cannot be read at all, it is reported as UNREADABLE
    and treated as RED. A monitor that goes quiet is not a monitor that is
    happy.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops import common, ledger as ledger_mod  # noqa: E402
from src.backtest import engine, tearsheet as ts  # noqa: E402

BANDS_FILE = "gate_s_bands.json"
STATUS_FILE = "monitor_status.json"

CONTINUE = "CONTINUE"
HALVE = "HALVE_SIZE_AND_REVIEW"
SUSPEND = "SUSPEND"
INSUFFICIENT = "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------------
# (1a) the audited backtest path for the frozen book
# ---------------------------------------------------------------------------

def backtest_path(spec, verbose=True):
    """Run the FROZEN spec through the audited engine over the Gate S window.

    Same conventions as scripts/p5_portfolio.py: month-end rebalance applied
    T+1, dollar volume passed so book size binds, costs from
    config/costs.yaml, info_dates passed so the look-ahead guard is live.
    """
    raw = pd.read_parquet(common.PANEL_PATH)
    raw["date"] = pd.to_datetime(raw["date"])
    panel, _ = engine.load_panel(verbose=False)
    dv = (raw.assign(dollar_vol=raw["volume"] * raw["prc_adj"])
             .pivot(index="date", columns="ticker", values="dollar_vol"))
    costs = engine.load_costs()

    weights = spec["allocation"]["weights"]
    cols = sorted(set(weights) | {spec["risk_free_ticker"]})
    start = pd.Timestamp(spec["gate_s"]["backtest_window_start"])
    rets = panel.loc[start:, :].dropna(subset=cols)

    marks = common.month_end_dates(rets.index)
    marks = pd.DatetimeIndex(sorted(set(marks) | {rets.index[0]}))
    w = pd.DataFrame({t: v for t, v in weights.items()}, index=marks)
    info = pd.Series(w.index, index=w.index)

    res = engine.run_backtest(
        w, rets, costs, book_usd=float(spec["book_usd"]), dollar_volume=dv,
        info_dates=info, name=f"{spec['spec_id']} gate-S reference",
        verbose=verbose)
    return res


# ---------------------------------------------------------------------------
# (1b) block bootstrap
# ---------------------------------------------------------------------------

def block_bootstrap_bands(net, rf, gate_s, verbose=True):
    """Moving-block bootstrap of the backtest path -> 3-month bands.

    Blocks are 126 trading days (6 months, as pre-registered). Each replication
    stitches randomly-drawn contiguous blocks into a synthetic path the same
    length as the real one, then that path is cut into non-overlapping 63-day
    windows and each window's return and Sharpe recorded. Pooling the windows
    across replications gives the distribution the bands are read off.

    The risk-free leg is carried through the SAME block draws, so a resampled
    Sharpe never pairs a 2020 return with a 2023 bill rate.
    """
    r = np.asarray(net, dtype=float)
    f = np.asarray(rf, dtype=float)
    n = len(r)
    block = int(gate_s["block_days"])
    horizon = int(gate_s["horizon_days"])
    n_boot = int(gate_s["n_bootstrap"])
    if n < block + horizon:
        raise ValueError(
            f"backtest path is {n} days, too short for {block}-day blocks")

    rng = np.random.default_rng(int(gate_s["seed"]))
    n_blocks = int(np.ceil(n / block))
    max_start = n - block
    n_win = n // horizon

    all_ret, all_sharpe = [], []
    for _ in range(n_boot):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        take = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        pr = r[take][:n_win * horizon].reshape(n_win, horizon)
        pf = f[take][:n_win * horizon].reshape(n_win, horizon)
        all_ret.append(np.prod(1.0 + pr, axis=1) - 1.0)
        ex = pr - pf
        sd = ex.std(axis=1, ddof=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            sh = np.where(sd > 0, ex.mean(axis=1) / sd * np.sqrt(common.TRADING_DAYS),
                          np.nan)
        all_sharpe.append(sh)

    rets = np.concatenate(all_ret)
    shs = np.concatenate(all_sharpe)
    shs = shs[np.isfinite(shs)]
    lo, hi = float(gate_s["band_lo_pct"]), float(gate_s["band_hi_pct"])

    bands = {
        "return_3m": {"p10": float(np.percentile(rets, lo)),
                      "p50": float(np.percentile(rets, 50)),
                      "p90": float(np.percentile(rets, hi))},
        "sharpe_3m": {"p10": float(np.percentile(shs, lo)),
                      "p50": float(np.percentile(shs, 50)),
                      "p90": float(np.percentile(shs, hi))},
        "n_windows_pooled": int(len(rets)),
    }
    if verbose:
        print(f"[gate-s] bootstrap: {n_boot} replications x {n_win} "
              f"non-overlapping {horizon}-day windows = {len(rets):,} pooled "
              f"3-month experiences, {block}-day blocks, seed "
              f"{gate_s['seed']}")
    return bands


def build_bands(spec, state_dir, verbose=True):
    """Compute and STORE the Gate S bands. Run once, and again only if the
    frozen spec's weights change."""
    common.banner("GATE S — building bands from the audited backtest")
    res = backtest_path(spec, verbose=verbose)
    net, rf = res.net.dropna(), res.rf.reindex(res.net.index)
    gate_s = spec["gate_s"]
    print(f"[gate-s] reference path: {res.start.date()}..{res.end.date()} "
          f"N={res.n_days} days ({res.n_days/common.TRADING_DAYS:.1f}y), "
          f"window chosen per spec.gate_s.backtest_window_start "
          f"({gate_s['backtest_window_start']})")
    print(f"[gate-s] why that window: {gate_s['backtest_window_start_why']}")

    mdd, peak, trough = ts.max_drawdown(net)
    bands = block_bootstrap_bands(net, rf, gate_s, verbose=verbose)

    out = {
        "spec_id": spec["spec_id"],
        "weights": spec["allocation"]["weights"],
        "book_usd": spec["book_usd"],
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "backtest": {
            "start": str(res.start.date()), "end": str(res.end.date()),
            "n_days": int(res.n_days),
            "cagr": float(ts.cagr(net)), "ann_vol": float(ts.ann_vol(net)),
            "sharpe": float(ts.sharpe_ratio(net, rf)),
            "annual_turnover": float(
                ts.avg_annual_turnover(res.turnover, res.n_days)),
            "max_drawdown": float(mdd),
            "max_drawdown_peak": str(peak.date()) if peak is not None else None,
            "max_drawdown_trough": str(trough.date()) if trough is not None else None,
        },
        "gate_s_params": gate_s,
        "bands": bands,
        "suspend_drawdown": float(mdd) * float(gate_s["drawdown_multiple"]),
    }
    path = Path(state_dir) / BANDS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")

    b = bands
    print(f"[gate-s] backtest reference: CAGR {out['backtest']['cagr']:+.2%} | "
          f"vol {out['backtest']['ann_vol']:.2%} | Sharpe "
          f"{out['backtest']['sharpe']:+.4f} | maxDD {mdd:+.2%}")
    print(f"[gate-s] 3-month RETURN band  p10 {b['return_3m']['p10']:+.2%}  "
          f"median {b['return_3m']['p50']:+.2%}  p90 {b['return_3m']['p90']:+.2%}")
    print(f"[gate-s] 3-month SHARPE band  p10 {b['sharpe_3m']['p10']:+.3f}  "
          f"median {b['sharpe_3m']['p50']:+.3f}  p90 {b['sharpe_3m']['p90']:+.3f}")
    print(f"[gate-s] SUSPEND if live drawdown is worse than "
          f"{out['suspend_drawdown']:+.2%} "
          f"({gate_s['drawdown_multiple']}x the backtest maxDD of {mdd:+.2%})")
    print(f"[gate-s] written to {path}")
    return out


def load_bands(state_dir):
    path = Path(state_dir) / BANDS_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# (1c) grade the live path
# ---------------------------------------------------------------------------

def grade_live(spec, lg, prices, bands, verbose=True):
    gate_s = spec["gate_s"]
    horizon = int(gate_s["horizon_days"])
    min_days = int(gate_s["min_live_days"])

    live = lg.daily_returns()
    nav = lg.nav_series()
    out = {"n_live_days": int(len(live)),
           "min_live_days": min_days,
           "live_start": str(nav.index.min().date()) if len(nav) else None,
           "live_end": str(nav.index.max().date()) if len(nav) else None}

    # drawdown is graded from day one — a suspend rule that waits three months
    # is not a suspend rule.
    if len(nav) >= 2:
        eq = nav / float(nav.iloc[0])
        dd = float((eq / eq.cummax() - 1.0).min())
    else:
        dd = 0.0
    out["live_max_drawdown"] = dd
    out["suspend_threshold"] = bands["suspend_drawdown"]
    out["drawdown_breached"] = bool(dd < bands["suspend_drawdown"])

    if len(live) < min_days:
        out["status"] = INSUFFICIENT
        out["reason"] = (f"{len(live)} live trading days, Gate S needs "
                         f"{min_days} (about 3 months). "
                         f"{min_days - len(live)} to go.")
        out["return_3m"] = None
        out["sharpe_3m"] = None
    else:
        window = live.iloc[-horizon:]
        rf_live = live_rf(spec, prices).reindex(window.index)
        r3 = float((1.0 + window).prod() - 1.0)
        ex = (window - rf_live.fillna(0.0))
        sd = float(ex.std(ddof=1))
        s3 = (float(ex.mean() / sd * np.sqrt(common.TRADING_DAYS))
              if sd > 0 else np.nan)
        out["return_3m"] = r3
        out["sharpe_3m"] = s3
        out["window_start"] = str(window.index[0].date())
        out["window_end"] = str(window.index[-1].date())
        out["rf_days_missing"] = int(rf_live.isna().sum())

        b = bands["bands"]
        below = (r3 < b["return_3m"]["p10"]) or (
            np.isfinite(s3) and s3 < b["sharpe_3m"]["p10"])
        above = (r3 > b["return_3m"]["p90"]) and (
            np.isfinite(s3) and s3 > b["sharpe_3m"]["p90"])
        if below:
            out["status"] = HALVE
            out["reason"] = ("3-month return and/or Sharpe is below the 10th "
                            "percentile of the bootstrapped backtest.")
        else:
            out["status"] = CONTINUE
            out["reason"] = ("3-month return and Sharpe are inside the "
                            "10th-90th percentile band."
                            if not above else
                            "Above the 90th percentile on both measures. Not a "
                            "problem, but check the ledger for a pricing or "
                            "distribution error before celebrating.")

    if out["drawdown_breached"]:
        out["status"] = SUSPEND
        out["reason"] = (
            f"live drawdown {dd:+.2%} is worse than "
            f"{bands['suspend_drawdown']:+.2%} "
            f"({gate_s['drawdown_multiple']}x the backtest maxDD). "
            "PREREGISTRATION.md Gate S: suspend and write a review.")
    return out


def live_rf(spec, prices):
    """Daily risk-free return for the live window, from the price store."""
    rf_ticker = spec["risk_free_ticker"]
    tr = common.total_returns(prices)
    if rf_ticker not in tr.columns:
        return pd.Series(dtype=float)
    return tr[rf_ticker].dropna()


# ---------------------------------------------------------------------------
# (2) crowding
# ---------------------------------------------------------------------------

def crowding_status(spec, refresh=False, verbose=True):
    """Re-apply the S1 crowding kill criterion to the monitor's own output.

    This does not re-derive the alpha path — scripts/s1_crowding_monitor.py
    owns that. It reads that script's rolling-alpha CSV and applies that
    script's own threshold constants, so the two can never quietly disagree.
    """
    cfg = spec["crowding"]
    roll_path = common.REPO_ROOT / cfg["rolling_alpha_csv"]
    md_path = common.REPO_ROOT / cfg["verdict_md"]
    out = {"source_script": cfg["source_script"],
           "rolling_alpha_csv": cfg["rolling_alpha_csv"]}

    if refresh:
        print("[crowd] re-running scripts/s1_crowding_monitor.py --offline ...")
        p = subprocess.run(
            [sys.executable, "scripts/s1_crowding_monitor.py", "--offline"],
            cwd=str(common.REPO_ROOT), capture_output=True, text=True)
        if p.returncode != 0:
            print(f"[crowd] refresh FAILED (exit {p.returncode}):\n"
                  f"{p.stderr[-1500:]}")
        else:
            print("[crowd] refresh OK")

    try:
        from scripts import s1_crowding_monitor as crowd
        floor = float(crowd.HAIRCUT_FLOOR)
        kill_n = int(crowd.KILL_N_MONTHS)
        kill_fn = crowd.kill_criterion
        out["constants_from"] = "scripts/s1_crowding_monitor.py"
    except Exception as exc:                                  # noqa: BLE001
        out.update({
            "light": "UNREADABLE", "fired": True,
            "error": f"{type(exc).__name__}: {exc}",
            "action": "TREAT AS RED",
            "note": ("could not import scripts/s1_crowding_monitor.py, so the "
                     "kill criterion cannot be evaluated. results/"
                     "S1_FALLEN_ANGEL.md records that statsmodels 0.14.4 is "
                     "broken against scipy 1.16.3 — try `pip3 install --user "
                     "--upgrade statsmodels`. Until it reads, assume RED."),
        })
        return out

    if not roll_path.exists():
        out.update({"light": "UNREADABLE", "fired": True,
                    "action": "TREAT AS RED",
                    "note": f"{cfg['rolling_alpha_csv']} is missing; re-run "
                            f"{cfg['source_script']}."})
        return out

    roll = pd.read_csv(roll_path, parse_dates=["end", "start"]).set_index("end")
    kill = kill_fn(roll)
    latest = float(roll["alpha_ann"].iloc[-1])
    last_window = roll.index.max()
    age_days = (pd.Timestamp.today().normalize() - last_window).days
    stale_after = int(cfg.get("stale_after_days", 45))

    verdict = None
    if md_path.exists():
        for line in md_path.read_text().splitlines():
            if line.startswith("**Verdict:"):
                verdict = line.split(":", 1)[1].strip().strip("*").strip()
                break

    out.update({
        "light": "RED" if kill["fired"] else ("AMBER" if latest < floor else "GREEN"),
        "monitor_md_verdict": verdict,
        "latest_36m_alpha": latest,
        "planning_floor": floor,
        "kill_n_months": kill_n,
        "current_run_months": int(kill["current_run"]),
        "fired": bool(kill["fired"]),
        "share_windows_below_floor": float(kill["share_below"]),
        "last_window_end": str(last_window.date()),
        "age_days": int(age_days),
        "stale": bool(age_days > stale_after),
        "action": "CUT SIZE" if kill["fired"] else "none",
    })
    if out["stale"]:
        out["note"] = (f"the rolling-alpha file is {age_days} days old "
                       f"(stale after {stale_after}). Re-run "
                       f"{cfg['source_script']} — a stale green is not a green.")
    return out


# ---------------------------------------------------------------------------

def run(spec, state_dir, rebuild=False, refresh_crowding=False, verbose=True):
    state_dir = Path(state_dir)
    bands = load_bands(state_dir)
    if bands is None or rebuild:
        bands = build_bands(spec, state_dir, verbose=verbose)
    elif bands.get("weights") != spec["allocation"]["weights"]:
        print("[gate-s] stored bands were built for DIFFERENT weights "
              f"({bands.get('weights')}) than the frozen spec "
              f"({spec['allocation']['weights']}) — rebuilding.")
        bands = build_bands(spec, state_dir, verbose=verbose)

    lg = ledger_mod.Ledger(state_dir)
    prices = common.read_prices(state_dir)
    gate = grade_live(spec, lg, prices, bands, verbose=verbose)
    crowd = crowding_status(spec, refresh=refresh_crowding, verbose=verbose)

    status = {
        "asof": datetime.now().isoformat(timespec="seconds"),
        "spec_id": spec["spec_id"], "spec_status": spec["status"],
        "gate_s": gate, "bands": bands["bands"],
        "backtest": bands["backtest"], "crowding": crowd,
    }
    actions = []
    if gate["status"] == SUSPEND:
        actions.append("SUSPEND the sleeve and write the Gate S review.")
    elif gate["status"] == HALVE:
        actions.append("HALVE the book and review before the next period.")
    if crowd.get("fired"):
        actions.append(
            "CUT SIZE — the S1 crowding kill criterion has fired "
            f"({crowd.get('current_run_months', '?')} consecutive months of "
            f"36-month alpha below the "
            f"{crowd.get('planning_floor', float('nan')):+.2%}/yr planning floor).")
    if crowd.get("stale"):
        actions.append(f"Re-run {crowd['source_script']} — its output is "
                       f"{crowd.get('age_days')} days old.")
    status["actions"] = actions or ["Continue at the frozen size."]

    (state_dir / STATUS_FILE).write_text(json.dumps(status, indent=2) + "\n")

    if verbose:
        _print_status(status)
        print(f"\n  written to {state_dir / STATUS_FILE}")
    return status


def _print_status(s):
    c = s["crowding"]
    common.banner("CROWDING LIGHT — read this first")
    print(f"  light                 : {c.get('light')}"
          + (f"   (monitor file says: {c['monitor_md_verdict']})"
             if c.get("monitor_md_verdict") else ""))
    if "latest_36m_alpha" in c:
        print(f"  latest 36-month alpha : {c['latest_36m_alpha']:+.2%}/yr "
              f"against a planning floor of {c['planning_floor']:+.2%}/yr")
        print(f"  kill criterion        : {c['current_run_months']} consecutive "
              f"months below the floor, trigger is {c['kill_n_months']} -> "
              f"{'*** FIRED: CUT SIZE ***' if c['fired'] else 'not fired'}")
        print(f"  data as of            : {c['last_window_end']} "
              f"({c['age_days']}d old{', STALE' if c['stale'] else ''})")
    if c.get("note"):
        print(f"  note                  : {c['note']}")

    g, b, bt = s["gate_s"], s["bands"], s["backtest"]
    common.banner("GATE S — live simulated path vs the audited backtest")
    print(f"  reference backtest : {bt['start']}..{bt['end']} N={bt['n_days']} "
          f"days | CAGR {bt['cagr']:+.2%} | Sharpe {bt['sharpe']:+.4f} | "
          f"maxDD {bt['max_drawdown']:+.2%}")
    print(f"  live sim           : {g['live_start']}..{g['live_end']} "
          f"N={g['n_live_days']} days")
    print()
    print(f"  {'measure':<22}{'live':>12}{'p10':>12}{'p90':>12}   verdict")
    if g["return_3m"] is None:
        print(f"  {'3-month return':<22}{'-':>12}{b['return_3m']['p10']:>11.2%}"
              f"{b['return_3m']['p90']:>12.2%}   not graded yet")
        print(f"  {'3-month Sharpe':<22}{'-':>12}{b['sharpe_3m']['p10']:>11.3f}"
              f"{b['sharpe_3m']['p90']:>12.3f}   not graded yet")
    else:
        rv = ("below p10" if g["return_3m"] < b["return_3m"]["p10"]
              else "above p90" if g["return_3m"] > b["return_3m"]["p90"]
              else "inside")
        sv = ("below p10" if g["sharpe_3m"] < b["sharpe_3m"]["p10"]
              else "above p90" if g["sharpe_3m"] > b["sharpe_3m"]["p90"]
              else "inside")
        print(f"  {'3-month return':<22}{g['return_3m']:>11.2%}"
              f"{b['return_3m']['p10']:>11.2%}{b['return_3m']['p90']:>12.2%}"
              f"   {rv}")
        print(f"  {'3-month Sharpe':<22}{g['sharpe_3m']:>12.3f}"
              f"{b['sharpe_3m']['p10']:>11.3f}{b['sharpe_3m']['p90']:>12.3f}"
              f"   {sv}")
    print(f"  {'drawdown':<22}{g['live_max_drawdown']:>11.2%}"
          f"{'suspend at':>12}{g['suspend_threshold']:>11.2%}   "
          f"{'BREACHED' if g['drawdown_breached'] else 'ok'}")
    print()
    print(f"  GATE S STATUS: {g['status']}")
    print(f"  {g['reason']}")
    print()
    print("  ACTIONS:")
    for a in s["actions"]:
        print(f"    - {a}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state-dir", default=str(common.DEFAULT_STATE_DIR))
    ap.add_argument("--spec", default=str(common.SPEC_PATH))
    ap.add_argument("--rebuild-bands", action="store_true",
                    help="recompute and overwrite the stored Gate S bands")
    ap.add_argument("--refresh-crowding", action="store_true",
                    help="re-run scripts/s1_crowding_monitor.py first")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    spec = common.load_spec(args.spec)
    run(spec, args.state_dir, rebuild=args.rebuild_bands,
        refresh_crowding=args.refresh_crowding, verbose=not args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
