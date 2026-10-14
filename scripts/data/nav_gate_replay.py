"""Replay the decide-time stale-NAV gate on the laptop's recorded paper sessions. Report only.

    python3 scripts/data/nav_gate_replay.py --state-dir /Users/simonjarvis/quantt_state/cef
    (network: CEFConnect and yfinance; no Alpaca call, no key file)

WHAT IT ASKS. Had `quantt/session/nav_gate.py` run in `on` mode (team lead
2026-10-13, the redesign) at each laptop decide, as-of 2026-09-28 -> 2026-10-07:
which names would it have checked, would the evening decide have DEFERRED to
the morning backstop, and at the final pre-send check (close - 90 min) which
names would it have replaced, kept or HELD at their current shares -- and could
any date flatten the book? It replaces the replay of the first version (drop at
the evening decide), which is kept, superseded, in docs/REFERENCES.md §12s.

WHAT THE DECIDE SAW, WHERE IT CAN BE KNOWN.
  * The decide record. The FIRST evening decide (22:00-01:00 ET) for the as-of
    date, from `<state>/<session>/runs/*-run.json`; where none ran (the laptop
    was offline), the plan the session actually decided on (`plan.json`),
    labelled.
  * The NAV(D) it used. Each target reason prints the z the session computed;
    inverting it with the mean and sd the sleeve rolled
    (`scripts/data/live_nav_quality.py::implied_nav`, the 2026-10-12 note's
    method and tolerance) says whether it used yfinance's final NAV(D) or
    NAV(D-1). mu, sd and the final NAVs are the note's table
    (`results/cef/live_nav_quality/live_period_2026-10-12.csv`); the close is
    the decide record's own. No z printed (band hold, below min weight,
    clipped): the NAV used is one of the two, unknown which.
  * The trigger. NAV(D) used = the panel's previous NAV, or = CEFConnect's
    NAV(D-1) (as served now). Assumed and labelled [U]: the panel's D-1 row at
    decide time was yfinance's final NAV(D-1). For a no-z name: triggered if
    its final NAV(D) triggers (then either candidate does), else UNKNOWN (it
    triggers only if the session used the stale copy).
  * CEFConnect at the decide: the collector's checks (`<state>/data/<D>/
    status.json`), within 3 hours, else unknown. CEFConnect's D row as served
    now resolves a triggered name: different -> replaced, equal -> kept.
  * The final check. When CEFConnect publishes D is [U] (three readings; the
    collector now logs it). So two bounds: BEST, CEFConnect has D by the final
    check -> nothing held; WORST, it still has none -> every triggered name is
    held at its current shares and leaves the cross-section. The sleeve's rule
    (`cef_discount._nav_hold`): if the holds leave fewer than `min_names`
    eligible names, the whole book holds; the min_names FLAT applies only when
    the cross-section is short without the holds.

Writes results/cef/nav_gate_replay/nav_gate_replay_{names,dates}_<today>.csv
(no share counts: held / outside-the-band flags only). Reads the state dir
read-only; writes nothing under data/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ET = ZoneInfo("America/New_York")
OUT_DIR = REPO / "results" / "cef" / "nav_gate_replay"
LIVE_PERIOD = REPO / "results" / "cef" / "live_nav_quality" / "live_period_2026-10-12.csv"
# The sleeve's own drop reasons (src/deploy/sleeves/cef_discount.py): a name
# with one of these was not eligible before any gate.
SLEEVE_DROPS = ("cef: illiquid", "cef: ADV unmeasured", "cef: no NAV", "cef: NAV ")
COLLECTOR_WINDOW = dt.timedelta(hours=3)   # one evening slot (22:00-01:00 ET)


class ReplayError(RuntimeError):
    """A required input is missing or inconsistent. The message names it."""


# ---------------------------------------------------------------- pure

def identify(z, close, mu, sd, nav_final, nav_prev) -> str:
    """Which NAV a printed z says the session used: final | prev | equal | ambiguous
    | other | no z. The 2026-10-12 note's rule (live_nav_quality.live_period)."""
    from scripts.data.live_nav_quality import FLOAT_EPS, IMPLIED_TOL, implied_nav
    if not (np.isfinite(z) and np.isfinite(mu) and np.isfinite(sd) and np.isfinite(close)) \
            or abs(abs(z) - 4) < 1e-9:
        return "no z"
    _, lo, hi = implied_nav(close, z, mu, sd)
    dist = lambda v: max(lo - v, 0.0, v - hi)            # noqa: E731
    fin, prv = dist(nav_final) <= IMPLIED_TOL, dist(nav_prev) <= IMPLIED_TOL
    if abs(nav_final - nav_prev) < FLOAT_EPS:
        return "equal" if fin else "other"
    return {(True, False): "final", (False, True): "prev",
            (True, True): "ambiguous"}.get((fin, prv), "other")


def eligible(reason: str) -> bool:
    return not any(reason.startswith(p) for p in SLEEVE_DROPS) and \
        not reason.startswith("cef: only")


# ---------------------------------------------------------------- inputs

def decide_records(state_dir: Path) -> list[dict]:
    """One decide per as-of date: the first evening decide, else plan.json."""
    out = []
    for plan_path in sorted(state_dir.glob("2026-*/plan.json")):
        day = plan_path.parent
        plan = json.loads(plan_path.read_text())
        evenings = []
        for f in sorted((day / "runs").glob("*-run.json")):
            r = json.loads(f.read_text())
            if r.get("slot") == "evening" and r.get("phase") == "decide" \
                    and (r.get("decision") or {}).get("targets"):
                evenings.append((f, r))
        if evenings:
            f, r = evenings[0]
            out.append({"asof": r["asof"], "session": r["session_date"], "kind": "evening",
                        "source": str(f.relative_to(state_dir)),
                        "decided_utc": dt.datetime.strptime(r["started_utc"], "%Y%m%dT%H%M%SZ")
                        .replace(tzinfo=dt.timezone.utc),
                        "targets": r["decision"]["targets"],
                        "closes": {t: v["close"] for t, v in r["closes"].items()},
                        "equity": float(r["account"]["equity"])})
        else:
            out.append({"asof": plan["asof"], "session": plan["session_date"],
                        "kind": "not evening (plan.json)", "source": str(plan_path.relative_to(state_dir)),
                        "decided_utc": None, "targets": plan["targets"],
                        "closes": plan.get("closes") or {}, "equity": float(plan["equity"])})
    if not out:
        raise ReplayError(f"no plan.json under {state_dir}")
    return out


def collector_evidence(state_dir: Path, asof: str) -> dict:
    p = state_dir / "data" / asof / "status.json"
    if not p.exists():
        return {"checked_utc": None, "cc_rows": None}
    st = json.loads(p.read_text())["steps"].get("nav_crosscheck") or {}
    if not st.get("ok"):
        return {"checked_utc": None, "cc_rows": None}
    det = st["detail"]
    absent = sum("CEFConnect has no NAV dated" in g["reason"] for g in det.get("gaps", []))
    n = 13
    return {"checked_utc": dt.datetime.fromisoformat(st["at"]), "cc_rows": n - absent}


def cc_at_decide(ev: dict, decided_utc) -> str:
    """CEFConnect's state at the decide, from the collector when it ran within an hour."""
    if ev["checked_utc"] is None or decided_utc is None:
        return "unknown (no collector check near the decide)"
    lag = (decided_utc - ev["checked_utc"]).total_seconds() / 60
    when = f"{abs(lag):.0f} min {'before' if lag >= 0 else 'after'} the decide"
    if abs(lag) > COLLECTOR_WINDOW.total_seconds() / 60:
        return f"unknown (collector checked {when})"
    if ev["cc_rows"] == 0:
        return f"absent (collector, {when})"
    if lag >= 0:
        return f"present for {ev['cc_rows']} names (collector, {when})"
    return f"unknown (present {when}, not known before)"


def fetch_yf_now(tickers) -> pd.DataFrame:
    """yfinance NAV as served now (the live fetcher's call), for the double-check."""
    import yfinance as yf
    rows = []
    for tk in sorted(tickers):
        n = yf.Ticker(f"X{tk}X").history(period="3mo", auto_adjust=False).reset_index()
        if n.empty:
            raise ReplayError(f"yfinance returned no NAV history for X{tk}X")
        n["date"] = pd.to_datetime(n["Date"]).dt.tz_localize(None).dt.normalize()
        n = n.sort_values("date")
        rows.append(pd.DataFrame({"ticker": tk, "date": n["date"], "nav": n["Close"],
                                  "nav_prev": n["Close"].shift(1)}))
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------- the replay

def fetch_cc_history(tickers, days) -> dict:
    """{(ticker, day): CEFConnect NAV or None}, one request per ticker (the gate's
    reader); an unreadable ticker raises -- the replay does not guess."""
    from quantt.session.nav_gate import cefconnect_navs
    out = {}
    for tk in sorted(tickers):
        got = cefconnect_navs(tk, sorted(days))
        out.update({(tk, d): v for d, v in got.items()})
        time.sleep(0.3)
    return out


def trigger_of(nav_d, yf_prev, cc_prev) -> str:
    from quantt.session.nav_gate import TRIGGER_CC, TRIGGER_YF, differs
    t = []
    if not differs(nav_d, yf_prev):
        t.append(TRIGGER_YF)
    if cc_prev is not None and not differs(nav_d, cc_prev):
        t.append(TRIGGER_CC)
    return "+".join(t)


def replay(state_dir: Path, live_period: Path):
    from ops.schedule.nyse_calendar import previous_trading_day
    from quantt.session.nav_gate import differs
    from scripts.cef.spec import BAND_WIDTH, MIN_NAMES, UNIVERSE
    lp = pd.read_csv(live_period)
    lp["asof"] = lp["asof"].astype(str)
    lp = lp.set_index(["asof", "ticker"])
    recs = decide_records(state_dir)
    days = set()
    for r in recs:
        a = dt.date.fromisoformat(r["asof"])
        days |= {a, previous_trading_day(a)}
    cc = fetch_cc_history(UNIVERSE, days)
    rows = []
    for r in recs:
        a = dt.date.fromisoformat(r["asof"])
        prev = previous_trading_day(a)
        for tk in sorted(UNIVERSE):
            if (r["asof"], tk) not in lp.index:
                raise ReplayError(f"{live_period} has no row for {r['asof']} {tk}")
            x = lp.loc[(r["asof"], tk)]
            t = r["targets"][tk]
            m = re.search(r"z=([-+]?\d+\.\d+)", t["reason"])
            z = float(m.group(1)) if m else np.nan
            close = float(r["closes"].get(tk, x["close_used"]))
            final, yf_prev = float(x["nav_now"]), float(x["nav_prev_now"])
            used = identify(z, close, float(x["mu"]), float(x["sd"]), final, yf_prev)
            cc_prev, cc_d = cc[(tk, prev)], cc[(tk, a)]
            if used == "prev":
                nav_d, trig = yf_prev, trigger_of(yf_prev, yf_prev, cc_prev)
            elif used in ("final", "equal"):
                nav_d, trig = final, trigger_of(final, yf_prev, cc_prev)
            else:                                   # no z / other: final or the stale copy
                nav_d = final
                trig = trigger_of(final, yf_prev, cc_prev) or "unknown"
            if trig in ("", "unknown") or cc_d is None:
                best = "" if trig == "" else ("unverified" if cc_d is None else
                                              "replace if it was the copy")
            else:
                best = "replace" if differs(nav_d, cc_d) else "keep"
            held_w = t["current"] * close / r["equity"]
            rows.append({"asof": r["asof"], "decide": r["kind"], "ticker": tk, "z": z,
                         "used": used, "nav_used": nav_d if used != "no z" else np.nan,
                         "yf_final": final, "yf_prev": yf_prev, "cc_prev_date": prev.isoformat(),
                         "cc_prev": cc_prev, "cc_d": cc_d, "trigger": trig,
                         "final_check_if_cc_has_d": best,
                         # Held / outside the band only: the repo is public and the desk
                         # publishes no positions (docs/RUNNER.md, orient's newest plan).
                         "eligible": eligible(t["reason"]), "held": t["current"] != 0,
                         "outside_band": abs(held_w) > BAND_WIDTH})
    names = pd.DataFrame(rows)

    dates = []
    for r in recs:
        g = names[names["asof"] == r["asof"]]
        trig = g[~g["trigger"].isin(["", "unknown"])]
        unk = g[g["trigger"] == "unknown"]
        elig = int(g["eligible"].sum())
        ev = collector_evidence(state_dir, r["asof"])
        decided = r["decided_utc"]
        if decided is None:
            dec = lp.xs(r["asof"], level="asof")["decided_at_utc"].iloc[0]
            decided = dt.datetime.strptime(dec, "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
        at = cc_at_decide(ev, decided)
        # Worst case at the final check: every triggered name held.
        lo = elig - int(trig["eligible"].sum()) - int(unk["eligible"].sum())
        hi = elig - int(trig["eligible"].sum())
        holds_book = "yes" if hi < MIN_NAMES else ("no" if lo >= MIN_NAMES else "possible")
        if elig < MIN_NAMES:
            raise ReplayError(f"{r['asof']}: {elig} eligible before any hold -- the "
                              f"pre-existing min_names rule would bind; not modelled here")
        dates.append({
            "asof": r["asof"], "decide": r["kind"],
            "decided_et": decided.astimezone(ET).strftime("%Y-%m-%d %H:%M"),
            "cefconnect_at_decide": at,
            "triggered": len(trig), "of_which_cc_prev_only": int((trig["trigger"] == "cc_prev").sum()),
            "unknown": len(unk),
            "on_at_decide": ("DEFER to the morning" if at.startswith("absent") and len(trig) else
                             "may defer (unknown names)" if at.startswith("absent") and len(unk) else
                             "decide" if at.startswith("present") or not (len(trig) or len(unk)) else
                             "defer if CEFConnect lacked D"),
            "best_replaced": " ".join(trig[trig["final_check_if_cc_has_d"] == "replace"]["ticker"]),
            "best_kept": " ".join(trig[trig["final_check_if_cc_has_d"] == "keep"]["ticker"]),
            "worst_held": " ".join(trig["ticker"]) + (f" (+{len(unk)} unknown)" if len(unk) else ""),
            "worst_held_outside_band": " ".join(trig[trig["held"] & trig["outside_band"]]["ticker"]),
            "worst_eligible_after": f"{lo}" + (f"-{hi}" if hi != lo else ""),
            "worst_book_holds": holds_book,
            "flattens": "never",
        })
    return names, pd.DataFrame(dates), lp


def panel_capture_check(cc_days_fetch=True) -> pd.DataFrame:
    """The gate's own judge on the LOCAL panel's last NAV date (the laptop copy,
    captured 2026-09-28): the reviewer's PDI case and DSL's 11.11 copy are on it.
    CEFConnect as served now. Read-only."""
    from ops.schedule.nyse_calendar import previous_trading_day
    from quantt.session.nav_gate import judge, panel_rows
    from scripts.cef.spec import UNIVERSE
    from src.deploy.sleeves.cef_discount import NAV_PATH
    N = pd.read_parquet(NAV_PATH)
    last = pd.to_datetime(N[N.ticker.isin(UNIVERSE)]["date"]).max().date()
    prev = previous_trading_day(last)
    rows = panel_rows(N, last, UNIVERSE)
    cc = fetch_cc_history(UNIVERSE, {last, prev})
    out = []
    for tk in sorted(UNIVERSE):
        trig, verdict = judge(rows.get(tk), cc[(tk, prev)], cc[(tk, last)], "read")
        if trig:
            out.append({"date": last.isoformat(), "ticker": tk, "panel_nav_d": rows[tk][0],
                        "panel_prev": rows[tk][2], "prev_date": rows[tk][1].isoformat(),
                        "cc_prev": cc[(tk, prev)], "cc_d": cc[(tk, last)], "trigger": trig,
                        "verdict": verdict})
    return pd.DataFrame(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state-dir", required=True, type=Path)
    ap.add_argument("--live-period", default=LIVE_PERIOD, type=Path)
    a = ap.parse_args(argv)
    names, dates, lp = replay(a.state_dir, a.live_period)
    # Double-checks, reported never blended: CEFConnect's D now vs the 2026-10-12
    # read, and yfinance now vs the note's final NAV(D) / NAV(D-1).
    j = names.merge(lp[["nav_cc"]].reset_index(), on=["asof", "ticker"])
    cc_diff = j[j["cc_d"].notna() & ((j["cc_d"] - j["nav_cc"]).abs() > 0.005)]
    yf = (fetch_yf_now(names["ticker"].unique())
          .assign(asof=lambda d: d.date.dt.strftime("%Y-%m-%d"))
          .rename(columns={"nav": "yf_nav", "nav_prev": "yf_nav_prev"}))
    k = names.merge(yf[["ticker", "asof", "yf_nav", "yf_nav_prev"]], on=["ticker", "asof"],
                    how="left")
    if k[["yf_nav", "yf_nav_prev"]].isna().any().any():
        raise ReplayError("yfinance now has no NAV row for some replayed (asof, ticker)")
    yf_diff = k[((k["yf_nav"] - k["yf_final"]).abs() > 0.005)
                | ((k["yf_nav_prev"] - k["yf_prev"]).abs() > 0.005)]
    cap = panel_capture_check()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    names.to_csv(OUT_DIR / f"nav_gate_replay_names_{stamp}.csv", index=False)
    dates.to_csv(OUT_DIR / f"nav_gate_replay_dates_{stamp}.csv", index=False)
    cap.to_csv(OUT_DIR / f"nav_gate_panel_capture_{stamp}.csv", index=False)
    print(f"run {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}")
    print(f"CEFConnect D now vs the 2026-10-12 read: {int(j['cc_d'].notna().sum())} compared, "
          f"{len(cc_diff)} differ {cc_diff[['asof', 'ticker']].values.tolist()}")
    print(f"yfinance now vs the note's NAV(D)/NAV(D-1): {len(k)} rows, {len(yf_diff)} differ "
          f"{yf_diff[['asof', 'ticker']].values.tolist()} (the note's values are used: its mu/sd "
          f"were rolled on them)")
    print("the gate's judge on the local panel's last NAV date (as captured 2026-09-28):")
    print(cap.to_string(index=False))
    with pd.option_context("display.width", 300, "display.max_columns", 30,
                           "display.max_colwidth", 60):
        print(dates.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
