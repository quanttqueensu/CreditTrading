"""Full-sample KILL-AWARE backtest of the v2 duration-hedged overlay and book.

Runs the SHIPPED MarginPortfolioOrchestrator (the exact machinery run_book_v2.py
drives) over the full sample with the frozen risk ladder ACTIVELY GOVERNING, and
A/Bs it against the counterfactual ALWAYS-LIVE path (ladder off). Three arms:

    always_live   apply_risk_ladder=False   (overlay never de-rated: the -39% path)
    kill_floor    ladder on, re-adjudication OFF   (permanent-kill CONSERVATIVE FLOOR)
    readjudicated ladder on, re-adjudication AUTO   (realistic desk path)

Two books:
  (i)  overlay STANDALONE ($60k, no vol-target)         2002-10-28 -> 2026-07-20
  (ii) BOOK v2 at the 6% point (k=1.70, netted, A1)     2012-04-12 -> 2026-07-20
       (ANGL inception 2012-04-12 bounds the credit-base leg -> the book window)

Also reports an A1-consistent reduced-form overlay sensitivity (ladder driven by
the A1 drawdown, the reporting standard) alongside the shipped-orchestrator path
(whose kill DECISION reads the as-if-siloed 150bp v1 shadow, per netting.py).

Reproduce:
    /opt/anaconda3/bin/python3 src/deploy/v2/kill_aware_backtest.py

Deterministic; prints sample start/end + N (standing rule); writes
results/refine/OVERLAY_KILL_AWARE.md and results/refine/overlay_kill_aware.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from ops import common as ops_common                                   # noqa: E402
from ops.ledger import Ledger                                          # noqa: E402
from src.deploy.exec_ledger import DerivativesLedger                   # noqa: E402
from src.deploy.lib.broker.margin_broker import MarginBroker            # noqa: E402
from src.deploy.lib.margin import MarginBook                            # noqa: E402
from src.deploy.lib.portfolio_v2 import MarginPortfolioOrchestrator     # noqa: E402
from src.deploy.lib.vol_target import VolTargetOverlay                  # noqa: E402
from src.deploy.lib.financing import FinancingModel                     # noqa: E402

TRADING_DAYS = 252
OVERLAY_START = "2002-10-28"      # both duration legs live (h4_netting_summary)
BOOK_START = "2012-04-12"         # ANGL inception -> credit-base leg live
END = "2026-07-20"

READJUD_AUTO = {"enabled": True, "manual_confirmation_required": False,
                "kill_reenable_shadow_dd_pct": -8.0, "kill_reenable_min_months": 6,
                "halve_restore_shadow_dd_pct": -6.0}


# ---------------------------------------------------------------------------
# fast in-memory price loader + save-suppression (a backtest needs no ledger IO)
# ---------------------------------------------------------------------------

def _preload(tickers, start, end):
    p = ops_common.fetch_local(list(tickers), start, end)
    p["date"] = pd.to_datetime(p["date"])
    return p


def _loader(panel):
    def load(instruments, asof, warmup):
        asof = pd.Timestamp(asof)
        lo = asof - pd.Timedelta(days=int(max(warmup, 10) * 1.7) + 25)
        return panel[(panel["ticker"].isin(list(instruments)))
                     & (panel["date"] >= lo) & (panel["date"] <= asof)
                     ].reset_index(drop=True)
    return load


def _suppress_saves():
    """A backtest needs no ledger IO and no per-day book-limit rollup — those
    are O(N)/day (=> O(N^2) over the full sample). The harness reads only the
    final MarginBook NAV series + orch.disabled/risk_scale, never the per-day
    view, so stubbing them is exact for what we measure and ~10x faster."""
    Ledger.save = lambda self: None
    DerivativesLedger.save = lambda self: None
    MarginBook.save = lambda self: None
    MarginPortfolioOrchestrator._persist = lambda self, view: None
    from src.deploy import risk as _risk
    _risk.check_book_limits = lambda *a, **k: {}


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def _metrics(nav: pd.Series, capital: float) -> dict:
    nav = nav.dropna().astype(float)
    if len(nav) < 3:
        return {"n": len(nav)}
    dd = (nav / nav.cummax() - 1.0)
    r = nav.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * np.sqrt(TRADING_DAYS)) if r.std() > 0 else np.nan
    monthly = nav.resample("ME").last()
    wm = float(monthly.diff().dropna().min()) if len(monthly) > 1 else np.nan
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1.0) if years > 0 else np.nan
    return {"start": str(nav.index[0].date()), "end": str(nav.index[-1].date()),
            "n": int(len(nav)), "maxDD_pct": round(float(dd.min()) * 100, 2),
            "maxDD_date": str(dd.idxmin().date()),
            "sharpe": round(sharpe, 3), "ann_vol_pct": round(float(r.std() * np.sqrt(TRADING_DAYS)) * 100, 2),
            "cagr_pct": round(cagr * 100, 2) if cagr == cagr else None,
            "worst_month_usd": round(wm, 0) if wm == wm else None,
            "end_nav_usd": round(float(nav.iloc[-1]), 0)}


# ---------------------------------------------------------------------------
# orchestrator runner
# ---------------------------------------------------------------------------

def _spec_overlay():
    return {
        "book_id": "OVERLAY-STANDALONE",
        "margin": {"model": "reg_t", "house_factor": 0.25, "max_gross_leverage": 3.0},
        "sleeves": [
            {"name": "dur_hedged_overlay",
             "spec_path": str(REPO / "ops/books/dur_hedged_overlay/frozen_spec.json"),
             "capital_usd": 60000, "enabled": True}],
        "limits": {"max_gross_exposure_usd": 900000, "book_drawdown_suspend_pct": 100.0,
                   "per_sleeve_capital_band": [25000, 100000], "book_worst_month_usd": 1e9},
    }


def _spec_book():
    spec = json.loads((REPO / "ops/books/v2/book_v2.json").read_text())
    # keep only the enabled real-capital sleeves; drop the paper sleeves so the
    # backtest is the $180k core (FOMC/short-vol carry no capital here anyway).
    spec["sleeves"] = [s for s in spec["sleeves"] if s.get("enabled")]
    return spec


def run_orch(spec, start, end, panel, *, apply_risk_ladder, readjud, vol_target,
             tag):
    broker = MarginBroker(books_root=f"/tmp/ka/{tag}", margin_spec=spec["margin"],
                          costs=ops_common.load_costs())
    vt = None
    if vol_target:
        v = spec.get("vol_target", {})
        vt = VolTargetOverlay(annual_vol_target=float(v.get("annual_vol_target", 0.06)),
                              vol_window_days=int(v.get("vol_window_days", 63)),
                              k_max=v.get("k_max"))
    orch = MarginPortfolioOrchestrator(
        spec, broker, books_root=f"/tmp/ka/{tag}", price_loader=_loader(panel),
        costs=ops_common.load_costs(), vol_target=vt,
        apply_risk_ladder=apply_risk_ladder, readjud=readjud, verbose=False)
    days = [d for d in sorted(panel["date"].unique())
            if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    kill_events, halve_events, reenable_events = [], [], []
    prev_state = {}
    for d in days:
        orch.advance(d, source="local")
        for name in orch.sleeves:
            dis = name in orch.disabled
            rs = orch.risk_scale.get(name, 1.0)
            ps = prev_state.get(name, (False, 1.0))
            if dis and not ps[0]:
                kill_events.append((str(d.date()), name))
            if (not dis) and ps[0]:
                reenable_events.append((str(d.date()), name))
            if rs < 1.0 and ps[1] >= 1.0 and not dis:
                halve_events.append((str(d.date()), name))
            prev_state[name] = (dis, rs)
    nav = broker.ledger().nav_series()
    return nav, {"kills": kill_events, "halves": halve_events,
                 "reenables": reenable_events}


# ---------------------------------------------------------------------------
# A1-consistent reduced-form overlay (ladder driven by the A1 drawdown itself —
# the reporting standard; transparent cross-check on the shipped path whose
# kill decision reads the 150bp v1 shadow)
# ---------------------------------------------------------------------------

def reduced_form_overlay(panel, start, end):
    """Reconstruct the overlay full-size daily P&L, re-price financing at A1, and
    apply the ladder on the A1 full-size drawdown. Returns dict of NAV paths."""
    from src.deploy.broker.simulator import Simulator
    from src.deploy.sleeve import MarketState
    from src.deploy.sleeves.duration_hedged_overlay import DurationHedgedOverlaySleeve
    from src.deploy import risk as riskmod

    spec = json.loads((REPO / "ops/books/dur_hedged_overlay/frozen_spec.json").read_text())
    cap = float(spec["capital_usd"])
    sim = Simulator(books_root="/tmp/ka/rf_shadow", verbose=False)
    sleeve = DurationHedgedOverlaySleeve(spec, cap)
    sim.register_sleeve("ovl", sleeve.alloc_type, sleeve.spec,
                        ops_common.load_costs(), cap, sleeve.instruments())
    load = _loader(panel)
    alldates = [d for d in sorted(panel["date"].unique()) if d <= pd.Timestamp(end)]
    for d in alldates:
        ms = MarketState(asof=d, prices=load(sleeve.instruments(), d, 68),
                         holdings=sim.sync_positions("ovl"))
        sim.place_targets("ovl", sleeve.target_positions(d, ms), d, ms)
    nav = sim.ledger("ovl").nav.sort_values("date").set_index("date")
    navser = nav["nav"].astype(float)
    price_pnl = navser.diff() + nav["financing_usd"].astype(float)   # pre-financing
    margin = nav["margin"].astype(float)
    neg_cash = (-nav["cash"].astype(float)).clip(lower=0.0)
    pos_cash = nav["cash"].astype(float).clip(lower=0.0)
    fm = FinancingModel()
    # CORRECTED 2026-07-23: match the fixed ledger convention — a short pays only
    # its fee SPREAD over base, positive cash earns base, neg cash pays the all-in
    # margin rate. (Was: short charged all-in base+50, no cash credit — the bug.)
    fee_short = pd.Series([fm.daily_rate(d, "short_etf") - fm.daily_rate(d, "cash")
                           for d in nav.index], index=nav.index)
    base_rate = pd.Series([fm.daily_rate(d, "cash") for d in nav.index], index=nav.index)
    mdebit = pd.Series([fm.daily_rate(d, "margin_debit") for d in nav.index], index=nav.index)
    fin_a1 = fee_short * margin + mdebit * neg_cash - base_rate * pos_cash
    dpnl = (price_pnl - fin_a1)
    seg = dpnl[(dpnl.index >= pd.Timestamp(start)) & (dpnl.index <= pd.Timestamp(end))].copy()
    seg.iloc[0] = 0.0

    def path(x):
        x = x.copy(); x.iloc[0] = 0.0
        return cap + x.cumsum()

    def ladder(sticky):
        full = path(seg)
        ddf = (full / full.cummax() - 1.0)
        scale, realized, state, kd = 1.0, [], "OK", None
        for d in seg.index:
            realized.append(scale * seg.loc[d])
            v = ddf.loc[d]
            if state != "KILL":
                if v <= -0.25:
                    state, scale, kd = "KILL", 0.0, d
                elif v <= -0.12:
                    state, scale = "HALVE", 0.5
                elif state == "HALVE" and v > -0.06:
                    state, scale = "OK", 1.0
            elif not sticky and kd is not None:
                months = (d.year - kd.year) * 12 + (d.month - kd.month)
                if v > -0.08 and months >= 6:
                    state, scale, kd = "HALVE", 0.5, None
        return pd.Series(realized, index=seg.index)

    return {"always_live": path(seg),
            "kill_floor": path(ladder(True)),
            "readjudicated": path(ladder(False)), "capital": cap}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    _suppress_saves()
    t0 = time.time()
    print("[kill-aware] preloading panels ...")
    panel = _preload(["LQD", "IEF", "ANGL", "BIL"], "2002-01-01", END)
    out = {"generated": str(pd.Timestamp.utcnow()), "end": END}

    # ---- (i) overlay standalone (shipped orchestrator: kill decision = v1 shadow)
    print("[kill-aware] (i) overlay standalone 2002-10-28 -> 2026-07-20 ...")
    ov = {}
    ov_events = {}
    for tag, (ladder, rj) in {"always_live": (False, None),
                              "kill_floor": (True, None),
                              "readjudicated": (True, READJUD_AUTO)}.items():
        nav, ev = run_orch(_spec_overlay(), OVERLAY_START, END, panel,
                           apply_risk_ladder=ladder, readjud=rj, vol_target=False,
                           tag=f"ov_{tag}")
        ov[tag] = _metrics(nav, 60000)
        ov_events[tag] = ev
        print(f"    {tag:14s}: maxDD {ov[tag]['maxDD_pct']}%  Sharpe {ov[tag]['sharpe']}  "
              f"endNAV {ov[tag]['end_nav_usd']}  kills={len(ev['kills'])} halves={len(ev['halves'])}")
    out["overlay_standalone_shipped"] = {"arms": ov, "events": ov_events}

    # ---- (i') overlay standalone A1-consistent reduced form
    print("[kill-aware] (i') overlay standalone A1 reduced-form ...")
    rf = reduced_form_overlay(panel, OVERLAY_START, END)
    out["overlay_standalone_a1_reduced"] = {
        k: _metrics(rf[k], rf["capital"]) for k in ("always_live", "kill_floor", "readjudicated")}
    for k in ("always_live", "kill_floor", "readjudicated"):
        m = out["overlay_standalone_a1_reduced"][k]
        print(f"    {k:14s}: maxDD {m['maxDD_pct']}%  Sharpe {m['sharpe']}  endNAV {m['end_nav_usd']}")

    # ---- (ii) BOOK v2 at 6% (netted, A1, vol-target)  2012-04-12 -> 2026-07-20
    print("[kill-aware] (ii) BOOK v2 @6% 2012-04-12 -> 2026-07-20 ...")
    bk = {}
    bk_events = {}
    for tag, (ladder, rj) in {"always_live": (False, None),
                              "kill_floor": (True, None),
                              "readjudicated": (True, READJUD_AUTO)}.items():
        nav, ev = run_orch(_spec_book(), BOOK_START, END, panel,
                           apply_risk_ladder=ladder, readjud=rj, vol_target=True,
                           tag=f"bk_{tag}")
        bk[tag] = _metrics(nav, 180000)
        bk_events[tag] = ev
        print(f"    {tag:14s}: maxDD {bk[tag]['maxDD_pct']}%  Sharpe {bk[tag]['sharpe']}  "
              f"worstM {bk[tag]['worst_month_usd']}  endNAV {bk[tag]['end_nav_usd']}  "
              f"kills={len(ev['kills'])} halves={len(ev['halves'])}")
    out["book_v2_6pct"] = {"arms": bk, "events": bk_events}

    out["runtime_sec"] = round(time.time() - t0, 1)
    (REPO / "results/refine/overlay_kill_aware.json").write_text(json.dumps(out, indent=2))
    _write_memo(out)
    print(f"[kill-aware] done in {out['runtime_sec']}s -> results/refine/OVERLAY_KILL_AWARE.md")
    return out


def _row(m):
    return (f"{m.get('maxDD_pct')}% ({m.get('maxDD_date','')}) | {m.get('sharpe')} | "
            f"{m.get('ann_vol_pct')}% | {m.get('worst_month_usd')} | {m.get('end_nav_usd')}")


def _write_memo(out):
    ov = out["overlay_standalone_shipped"]["arms"]
    rf = out["overlay_standalone_a1_reduced"]
    bk = out["book_v2_6pct"]["arms"]
    ovk = out["overlay_standalone_shipped"]["events"]["kill_floor"]["kills"]
    lines = []
    A = lines.append
    A("# OVERLAY_KILL_AWARE — the honest kill-aware book (2026-07-21)\n")
    A("*Produced by `src/deploy/v2/kill_aware_backtest.py` running the SHIPPED "
      "`MarginPortfolioOrchestrator` with the frozen risk ladder ACTIVELY GOVERNING, "
      "A/B'd against the counterfactual always-live path. Deterministic; sample "
      "start/end + N printed per table.*\n")
    A("## Why this memo exists\n")
    A("The v2 REFINE numbers (overlay −39.1% full-sample maxDD; book Sharpe 0.738 / "
      "maxDD −18.1%) were computed with the overlay run at FULL size IGNORING its own "
      "frozen ladder. This memo reports the ladder-governed truth: the honest tail "
      "(DD capped) and its return cost (halving/killing gives up upside), under the "
      "**permanent-kill CONSERVATIVE FLOOR** and the **re-adjudicated realistic path**.\n")
    A("## Convention\n")
    A("- **A1 real financing is the reporting standard** (short_etf = term SOFR/EFFR + "
      "50bp; margin_debit +100bp), per the RUNBOOK A1 standard.\n")
    A("- The SHIPPED orchestrator's kill DECISION reads the as-if-siloed **v1 (150bp) "
      "shadow** (netting.py: the frozen kills fire on un-levered v1 economics), while "
      "the book P&L is A1. The A1-consistent reduced-form (kill driven by the A1 "
      "drawdown itself) is shown as a cross-check.\n")
    A("- **Frozen ladder unchanged**: −12% HALVE / −25% KILL / 300bp financing-SUSPEND. "
      "Re-adjudication is an OPERATIONAL addition (book_v2.json `risk_readjudication`), "
      "never a signal change.\n")

    A("\n## (i) Overlay STANDALONE ($60k, native size, no vol-target)\n")
    A(f"Sample {ov['always_live'].get('start')} → {ov['always_live'].get('end')}, "
      f"N={ov['always_live'].get('n')}. Ladder events (floor): "
      f"{', '.join(f'{d} {n}' for d, n in ovk) or 'none'}.\n")
    A("**Shipped orchestrator (kill decision = v1 150bp shadow, book P&L = A1):**\n")
    A("| arm | maxDD (date) | Sharpe | vol | worst-month $ | end NAV |")
    A("|---|---|---|---|---|---|")
    for tag, name in (("always_live", "ALWAYS-LIVE (ladder off)"),
                      ("kill_floor", "KILL-AWARE — permanent-kill FLOOR"),
                      ("readjudicated", "KILL-AWARE — re-adjudicated")):
        A(f"| {name} | {_row(ov[tag])} |")
    A("\n**A1-consistent reduced-form (kill driven by the A1 drawdown = reporting standard):**\n")
    A("| arm | maxDD (date) | Sharpe | vol | worst-month $ | end NAV |")
    A("|---|---|---|---|---|---|")
    for tag, name in (("always_live", "ALWAYS-LIVE (ladder off)"),
                      ("kill_floor", "KILL-AWARE — permanent-kill FLOOR"),
                      ("readjudicated", "KILL-AWARE — re-adjudicated")):
        A(f"| {name} | {_row(rf[tag])} |")

    A("\n## (ii) BOOK v2 at the 6% point (k=1.70, netted IEF legs, A1, one MarginBook)\n")
    A(f"Sample {bk['always_live'].get('start')} → {bk['always_live'].get('end')}, "
      f"N={bk['always_live'].get('n')} (ANGL inception 2012-04-12 bounds the credit-base "
      f"leg). Core = credit_base + eom_ief + dur_hedged_overlay ($180k); FOMC/short-vol "
      f"carry no capital.\n")
    A("| arm | maxDD (date) | Sharpe | vol | worst-month $ | end NAV |")
    A("|---|---|---|---|---|---|")
    for tag, name in (("always_live", "ALWAYS-LIVE (ladder off)"),
                      ("kill_floor", "KILL-AWARE — permanent-kill FLOOR"),
                      ("readjudicated", "KILL-AWARE — re-adjudicated")):
        A(f"| {name} | {_row(bk[tag])} |")
    bkk = out["book_v2_6pct"]["events"]["kill_floor"]
    A(f"\nBook ladder events (floor): kills={bkk['kills'] or 'none'}; "
      f"halves={bkk['halves'] or 'none'}.\n")

    A("\n## Reproduce\n")
    A("```bash\n/opt/anaconda3/bin/python3 src/deploy/v2/kill_aware_backtest.py\n```\n")
    (REPO / "results/refine/OVERLAY_KILL_AWARE.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
