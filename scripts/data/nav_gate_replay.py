"""Replay the decide-time stale-NAV gate on the laptop's recorded paper sessions. Report only.

    QUANTT_ENV_FILE is not needed (no Alpaca call). Network: CEFConnect and yfinance.
    python3 scripts/data/nav_gate_replay.py --state-dir /Users/simonjarvis/quantt_state/cef

WHAT IT ASKS. Had `quantt/session/nav_gate.py` (team lead 2026-10-13, "Use
CEFConnect, else drop") run at each laptop decide, as-of 2026-09-28 ->
2026-10-07, which names would it have replaced, which dropped, and would the
drops have left fewer than `min_names` eligible names -- the case in which the
sleeve's existing rule emits every name FLAT and decide closes the whole book?

WHAT THE DECIDE SAW, WHERE IT CAN BE KNOWN.
  * The decide record. The FIRST evening decide (22:00-01:00 ET) for the as-of
    date, from `<state>/<session>/runs/*-run.json` (slot "evening", phase
    "decide"), because the evening is where the book decides when the machine
    is up. Where no evening decide ran (the laptop was offline: every evening
    run of that night failed on Alpaca's clock), the plan the session actually
    decided on (`plan.json`, morning backstop or the opening session), labelled.
  * The NAV(D) it used. Each target reason prints the z the session computed;
    inverting it with the mean and sd the sleeve rolled
    (`scripts/data/live_nav_quality.py::implied_nav`, the 2026-10-12 note's own
    method and tolerance) identifies whether it used yfinance's final NAV(D) or
    NAV(D-1). mu, sd and the final NAVs are the note's table
    (`results/cef/live_nav_quality/live_period_2026-10-12.csv`, yfinance as
    served 2026-10-12); the close is the decide record's own.
  * A repeat at decide time. Used NAV(D-1) -> a repeat (Yahoo's D row was a
    copy of its D-1 row). Used the final NAV(D) and final NAV(D) = NAV(D-1) ->
    a repeat (genuine). No z printed (band hold, below min weight, clipped):
    a repeat if final NAV(D) = NAV(D-1) (either value then equals it), else
    UNKNOWN -- it may have been a stale copy. Assumed, and labelled [U]: the
    panel's D-1 row at decide time was yfinance's final NAV(D-1).
  * CEFConnect at decide time. Only the collector measured it: its
    `nav_crosscheck` time and whether CEFConnect had a row for D
    (`<state>/data/<D>/status.json`). It is used only when it ran within
    COLLECTOR_WINDOW of the decide, and the label gives the lag; otherwise
    "unknown". An "absent" read before the decide stands for the decide on the
    evidence of the same records: no row for D was ever seen by 00:10 ET on D+1
    (10-05), one was there by 11:41 ET (10-01), and Friday's was still missing at
    09:40 ET on Saturday (10-02). CEFConnect's publication time is [U].
  * CEFConnect as served now: one `nav_gate.cefconnect_nav` call per name that
    repeated or may have, the reader the gate uses.

Two scenarios per date: A, CEFConnect has no row for D (what the collector saw
on every evening it ran) -- every repeat is dropped; B, CEFConnect as served
now -- stale copies replaced, genuine repeats kept. The date's "at decide"
column says which one the measured CEFConnect state supports.

Writes results/cef/nav_gate_replay/nav_gate_replay_{names,dates}_<today>.csv.
Reads the state dir read-only; writes nothing under data/.
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


def repeat_status(used: str, nav_final: float, nav_prev: float) -> str:
    """yes_stale | yes_genuine | no | unknown: was NAV(D) = NAV(D-1) at decide time?"""
    from quantt.session.nav_gate import differs
    same = not differs(nav_final, nav_prev)
    if used == "prev":
        return "yes_stale"
    if used in ("final", "equal"):
        return "yes_genuine" if same else "no"
    if used == "no z":
        return "yes_genuine" if same else "unknown"
    return "unknown"                                     # other / ambiguous


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


def fetch_cc_now(pairs) -> dict:
    """{(ticker, asof): (value or None, status)} via the gate's own reader."""
    from quantt.session.nav_gate import CefConnectError, cefconnect_nav
    out = {}
    for tk, asof in sorted(pairs):
        try:
            v = cefconnect_nav(tk, dt.date.fromisoformat(asof))
            out[(tk, asof)] = (v, "present" if v is not None else "absent")
        except CefConnectError as e:
            out[(tk, asof)] = (None, f"error: {e}")
        time.sleep(0.3)
    return out


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

def replay(state_dir: Path, live_period: Path):
    from quantt.session.nav_gate import differs
    from scripts.cef.spec import BAND_WIDTH, MIN_NAMES, UNIVERSE
    lp = pd.read_csv(live_period)
    lp["asof"] = lp["asof"].astype(str)
    lp = lp.set_index(["asof", "ticker"])
    recs = decide_records(state_dir)
    rows = []
    for r in recs:
        for tk in sorted(UNIVERSE):
            if (r["asof"], tk) not in lp.index:
                raise ReplayError(f"{live_period} has no row for {r['asof']} {tk}")
            x = lp.loc[(r["asof"], tk)]
            t = r["targets"][tk]
            m = re.search(r"z=([-+]?\d+\.\d+)", t["reason"])
            z = float(m.group(1)) if m else np.nan
            close = float(r["closes"].get(tk, x["close_used"]))
            used = identify(z, close, float(x["mu"]), float(x["sd"]),
                            float(x["nav_now"]), float(x["nav_prev_now"]))
            held_w = t["current"] * close / r["equity"]
            rows.append({"asof": r["asof"], "decide": r["kind"], "ticker": tk, "z": z,
                         "used": used, "nav_final": float(x["nav_now"]),
                         "nav_prev": float(x["nav_prev_now"]),
                         "repeat": repeat_status(used, float(x["nav_now"]), float(x["nav_prev_now"])),
                         # Held / outside the band only: the repo is public and the desk
                         # publishes no positions (docs/RUNNER.md, orient's newest plan).
                         "eligible": eligible(t["reason"]), "held": t["current"] != 0,
                         "outside_band": abs(held_w) > BAND_WIDTH,
                         "nav_cc_20261012": float(x["nav_cc"])})
    names = pd.DataFrame(rows)
    need = names[names["repeat"] != "no"][["ticker", "asof"]].itertuples(index=False)
    cc = fetch_cc_now({(a.ticker, a.asof) for a in need})
    names["cc_now"] = [cc.get((t, a), (np.nan, ""))[0] for t, a in zip(names.ticker, names["asof"])]
    names["cc_status"] = [cc.get((t, a), (None, "not asked"))[1]
                          for t, a in zip(names.ticker, names["asof"])]
    # The decide-time NAV(D) of a repeat is NAV(D-1) (stale) or equal to it (genuine).
    def verdict_b(row):
        if row["repeat"] == "no":
            return ""
        if row["cc_status"] != "present":
            return "dropped (CEFConnect " + row["cc_status"] + ")"
        stale = differs(row["nav_prev"], row["cc_now"])
        if row["repeat"] == "unknown":
            return "replaced if it was a copy" if stale else "kept if it was a repeat"
        return "replaced" if stale else "kept"
    names["verdict_cc_now"] = names.apply(verdict_b, axis=1)

    dates = []
    for r in recs:
        g = names[names["asof"] == r["asof"]]
        rep = g[g["repeat"].str.startswith("yes")]
        unk = g[g["repeat"] == "unknown"]
        elig = int(g.eligible.sum())
        lo = elig - int(rep.eligible.sum()) - int(unk.eligible.sum())
        hi = elig - int(rep.eligible.sum())
        binds = "yes" if hi < MIN_NAMES else ("no" if lo >= MIN_NAMES else "possible")
        cut = rep[rep.held & rep.outside_band]
        ev = collector_evidence(state_dir, r["asof"])
        decided = r["decided_utc"]
        if decided is None:
            dec = lp.xs(r["asof"], level="asof")["decided_at_utc"].iloc[0]
            decided = dt.datetime.strptime(dec, "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
        dates.append({
            "asof": r["asof"], "decide": r["kind"],
            "decided_et": decided.astimezone(ET).strftime("%Y-%m-%d %H:%M"),
            "cefconnect_at_decide": cc_at_decide(ev, decided),
            "eligible_before": elig,
            "repeats": len(rep), "of_which_stale_copies": int((rep["repeat"] == "yes_stale").sum()),
            "unknown": len(unk),
            "A_dropped": f"{len(rep)}" + (f"-{len(rep) + len(unk)}" if len(unk) else ""),
            "A_eligible_after": f"{lo}" + (f"-{hi}" if hi != lo else ""),
            "A_min_names_binds": binds,
            "at_decide": ("A" if cc_at_decide(ev, decided).startswith("absent") else
                          "B" if cc_at_decide(ev, decided).startswith("present") else "unknown"),
            "A_held_cut_to_band_edge": " ".join(cut.ticker),
            "B_replaced": " ".join(rep[rep.verdict_cc_now == "replaced"].ticker),
            "B_kept": " ".join(rep[rep.verdict_cc_now == "kept"].ticker),
            "B_dropped": " ".join(rep[rep.verdict_cc_now.str.startswith("dropped")].ticker),
            "B_unknown_would_be_replaced": " ".join(
                unk[unk.verdict_cc_now == "replaced if it was a copy"].ticker),
        })
    return names, pd.DataFrame(dates), lp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state-dir", required=True, type=Path)
    ap.add_argument("--live-period", default=LIVE_PERIOD, type=Path)
    a = ap.parse_args(argv)
    names, dates, lp = replay(a.state_dir, a.live_period)
    # Double-checks, reported never blended: CEFConnect now vs the 2026-10-12 read,
    # and yfinance now vs the note's final NAV(D) / NAV(D-1).
    asked = names[names.cc_status == "present"]
    cc_diff = asked[(asked.cc_now - asked.nav_cc_20261012).abs() > 0.005]
    yf = (fetch_yf_now(names.ticker.unique())
          .assign(asof=lambda d: d.date.dt.strftime("%Y-%m-%d"))
          .rename(columns={"nav": "yf_nav", "nav_prev": "yf_nav_prev"}))
    j = names.merge(yf[["ticker", "asof", "yf_nav", "yf_nav_prev"]], on=["ticker", "asof"],
                    how="left")
    if j[["yf_nav", "yf_nav_prev"]].isna().any().any():
        raise ReplayError("yfinance now has no NAV row for some replayed (asof, ticker)")
    yf_diff = j[((j.yf_nav - j.nav_final).abs() > 0.005)
                | ((j.yf_nav_prev - j.nav_prev).abs() > 0.005)]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    names.to_csv(OUT_DIR / f"nav_gate_replay_names_{stamp}.csv", index=False)
    dates.to_csv(OUT_DIR / f"nav_gate_replay_dates_{stamp}.csv", index=False)
    print(f"run {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}")
    print(f"CEFConnect now vs the 2026-10-12 read: {len(asked)} compared, {len(cc_diff)} differ "
          f"{cc_diff[['asof', 'ticker', 'cc_now', 'nav_cc_20261012']].values.tolist()}")
    print(f"yfinance now vs the note's NAV(D)/NAV(D-1): {len(j)} rows, {len(yf_diff)} differ "
          f"{yf_diff[['asof', 'ticker']].values.tolist()} (the note's values are used: its mu/sd "
          f"were rolled on them)")
    with pd.option_context("display.width", 250, "display.max_columns", 30,
                           "display.max_colwidth", 60):
        print(dates.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
