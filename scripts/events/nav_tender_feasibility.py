"""Zero-trial counts for the NAV-tender pre-registration (EVENTS; draft 2026-10-19).

    python3 scripts/events/nav_tender_feasibility.py
    python3 scripts/events/nav_tender_feasibility.py --ibkr /abs/path/usa.txt   # + IBKR's public shortstock file

`--ibkr` takes a copy of https://www.interactivebrokers.com/shortstock/usa.txt
(public, no login; fetch it yourself, e.g. with curl). The script opens no
network connection of its own.

WHAT THIS IS FOR
----------------
`results/events/PREREG_NAV_TENDER_2026-10-19.md` (a DRAFT awaiting the team
lead) fixes the NAV-tender sleeve's event set, periods, hedge, sizing, kill
tests and bar before anything runs. The census that admitted the idea
(`results/events/CEF_CORP_ACTION_CENSUS_2026-10-15.md`, REFERENCES §12ab)
counted events and terms. This script re-counts what the DECLARATION needs,
from tracked EDGAR facts only:

* NAV-tender events per period under the declared partition (fit, gap,
  holdout, after CRSP), with the 44 `cef_universe.csv` funds excluded and
  counted, and independent groups (sponsor x day 0, the census's unit);
* the strata the declaration names: asset class, the day-0 form, a day 0
  more than 60 days before the offer document (a possible programme
  announcement, which Stage 0 must re-date), a triggered discount-programme
  origin (the N1 census), a merger episode open at day 0 (excluded so this
  sample and E1's are disjoint), pro-ration read or not, an episode whose
  last filing is far from the offer's expiry;
* the hedge route each asset class would take TODAY: the first ETF in the
  census's declared order (HEDGE_ETF, then HEDGE_ALTERNATES) that Alpaca
  listed as shortable on the census read (2026-10-18, tracked in the census
  summary JSON), else one IBKR's public file shows available, with its fee;
* arithmetic on the bar: the Sharpe `validate._dsr` needs at each candidate
  EVENTS N over the fit's P&L sessions, and the power of the declared
  per-event test at stated, LABELLED assumptions.

WHAT IT DOES NOT DO (zero trials)
---------------------------------
It reads no price, no return and no CRSP table. Every input is a tracked
EDGAR-derived CSV/JSON (the census's per-event table, the fetcher's episode
table, the N1 census) or IBKR's public availability file. It computes no
P&L, no spread and no discount. The holdout rows are counts of dates and
identities, which the E2 draft also counted.

THE PERIOD RULE (declared in the prereg §7; this is its proxy)
-------------------------------------------------------------
The trial's exit for an event is decided on session F = the later of (the
session of the results filing's `observed_at`) and (the pricing session + 5
sessions), and filled at the close of F + 1 -- the event's last P&L session.
Here the results filing's date is proxied by the tender episode's LAST
EDGAR filing date (`last_date` in the episode table; median 6 days after the
parsed expiry) and the pricing session by the parsed expiry. Stage 0 replaces
both with the dates read from the filings. An event is

* fit      if day 0 >= 2010-01-01 and its last P&L session <= 2022-12-30;
* gap      if day 0 < 2023-01-01 but its last P&L session is later (in neither);
* holdout  if day 0 >= 2023-01-01 and its last P&L session <= 2024-12-31
           (CRSP's last row; the declared default holdout end);
* after_crsp if day 0 >= 2023-01-01 and its last P&L session is later.

ENVIRONMENT: `compute.use_numexpr` off, as every script in scripts/events/
(scripts/events/numexpr_fault.py).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

pd.set_option("compute.use_numexpr", False)

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

EVENTS_CSV = REPO / "results/events/cef_corp_action_events.csv"
EPISODES_CSV = REPO / "results/events/edgar_cef_bdc_episodes.csv"
COND_CSV = REPO / "results/events/conditional_tender_census.csv"
SUMMARY_JSON = REPO / "results/events/cef_corp_action_summary.json"
OUT = REPO / "results/events/nav_tender_feasibility_2026-10-19.txt"

SCOPE_START = pd.Timestamp("2010-01-01")
HOLDOUT_START = pd.Timestamp("2023-01-01")
FIT_LAST_SESSION = pd.Timestamp("2022-12-30")
HOLDOUT_LAST_SESSION = pd.Timestamp("2024-12-31")   # CRSP's last row (census data note)
RESIDUAL_LAG = 5          # sessions after pricing before the residual can be decided (prereg §5, decision 6)
PROGRAMME_LAG_DAYS = 60   # day 0 this far before the offer document is flagged for re-dating at Stage 0
COND_WINDOW_DAYS = 180    # a tender filed within this many days after a triggered window's end is that window's tender
EPISODE_FAR_DAYS = 60     # an episode whose last filing is this far from the expiry spans more than one offer
CREDIT_CLASSES = ("high_yield", "loans", "muni", "multisector", "preferred", "em_debt", "convertible")

NEED = ("type", "cik", "ann_date", "ann_form", "ann_accession", "doc_date", "sponsor", "asset_class",
        "in_universe", "expire", "proration", "proration_xcheck", "result_accession", "size_pct", "k_pct")


class FeasibilityError(RuntimeError):
    pass


# ----------------------------------------------------------------- calendar

def _session_on_or_after(d) -> pd.Timestamp:
    from ops.schedule.nyse_calendar import is_trading_day, next_trading_day
    d = pd.Timestamp(d).date()
    return pd.Timestamp(d if is_trading_day(d) else next_trading_day(d))


def _add_sessions(d, n: int) -> pd.Timestamp:
    from ops.schedule.nyse_calendar import next_trading_day
    x = pd.Timestamp(d).date()
    for _ in range(n):
        x = next_trading_day(x)
    return pd.Timestamp(x)


def last_pnl_session(results_date, pricing_date, lag: int = RESIDUAL_LAG) -> pd.Timestamp:
    """F + 1, where F = max(session of the results filing, pricing session + lag).

    The residual is sold at the close of F + 1 (decided at F under shift(2)), so
    F + 1 is the event's last P&L session. Raises on a missing date: an event
    with no expiry or no results date cannot be placed in a period, and placing
    it by default would be a silent fallback."""
    if pd.isna(results_date) or pd.isna(pricing_date):
        raise FeasibilityError(f"missing date: results {results_date}, pricing {pricing_date}")
    f = max(_session_on_or_after(results_date), _add_sessions(_session_on_or_after(pricing_date), lag))
    return _add_sessions(f, 1)


def assign_period(day0, last_session) -> str:
    """fit / gap / holdout / after_crsp (module docstring). Raises before 2010."""
    day0 = pd.Timestamp(day0)
    if day0 < SCOPE_START:
        raise FeasibilityError(f"day 0 {day0.date()} is before the census scope")
    if day0 < HOLDOUT_START:
        return "fit" if last_session <= FIT_LAST_SESSION else "gap"
    return "holdout" if last_session <= HOLDOUT_LAST_SESSION else "after_crsp"


# ----------------------------------------------------------------- inputs

def load_events(path: Path = EVENTS_CSV) -> pd.DataFrame:
    ev = pd.read_csv(path, parse_dates=["ann_date", "expire", "doc_date"])
    miss = [c for c in NEED if c not in ev.columns]
    if miss:
        raise FeasibilityError(f"{path.name} lacks columns {miss}")
    nt = ev[ev["type"] == "nav_tender"].copy()
    if nt.empty:
        raise FeasibilityError("no nav_tender rows")
    return nt


def attach_episodes(nt: pd.DataFrame, ep: pd.DataFrame) -> pd.DataFrame:
    """The tender episode's last filing date (the results-date proxy), joined on the
    day-0 accession. Every NAV tender must find its episode; a miss raises."""
    t = ep[ep["kind"] == "tender"][["cik", "first_accession", "last_date"]]
    m = nt.merge(t, left_on=["cik", "ann_accession"], right_on=["cik", "first_accession"], how="left")
    if m["last_date"].isna().any():
        bad = m.loc[m["last_date"].isna(), "ann_accession"].tolist()
        raise FeasibilityError(f"no tender episode for day-0 accession(s) {bad[:5]}")
    if len(m) != len(nt):
        raise FeasibilityError("episode join duplicated rows")
    return m


def merger_open(nt: pd.DataFrame, ep: pd.DataFrame) -> pd.Series:
    """True where the same CIK has a merger episode with first_date <= day 0 <= last_date."""
    mg = ep[ep["kind"] == "merger"][["cik", "first_date", "last_date"]]
    out = []
    for r in nt.itertuples():
        g = mg[mg["cik"] == r.cik]
        out.append(bool(((g["first_date"] <= r.ann_date) & (r.ann_date <= g["last_date"])).any()))
    return pd.Series(out, index=nt.index)


def triggered_programme(nt: pd.DataFrame, cond: pd.DataFrame, days: int = COND_WINDOW_DAYS) -> pd.Series:
    """True where the fund (by CIK) had a TRIGGERED discount-programme window that
    ended on or before day 0 and no more than `days` before it: the tender is that
    window's, so its day 0 must be the triggered-tender filing, never the
    programme's announcement (prereg §1, the line against N1)."""
    trig = cond[cond["outcome"].astype(str).str.startswith("triggered")].dropna(subset=["cik", "window_end"])
    out = []
    for r in nt.itertuples():
        g = trig[trig["cik"].astype(int) == int(r.cik)]
        lag = (r.ann_date - g["window_end"]).dt.days
        out.append(bool(((lag >= 0) & (lag <= days)).any()))
    return pd.Series(out, index=nt.index)


def hedge_routes(summary: dict, ibkr: pd.DataFrame | None) -> dict:
    """Per asset class: (symbol, route, ibkr fee %/yr or None). Route is 'alpaca'
    (shortable on the census's 2026-10-18 read), 'ibkr' (not shortable at Alpaca,
    available > 0 in IBKR's file), or 'none'. Declared order is the census's."""
    from scripts.events.cef_corp_action_census import HEDGE_ETF, HEDGE_ALTERNATES
    flags = {h["symbol"]: bool(h.get("shortable")) for h in summary["hedges"]}
    routes = {}
    for cls, primary in HEDGE_ETF.items():
        order = (primary,) + tuple(HEDGE_ALTERNATES.get(cls, ()))
        pick = None
        for s in order:
            if s not in flags:
                raise FeasibilityError(f"{s} has no Alpaca read in the census summary")
            if flags[s]:
                pick = (s, "alpaca", None)
                break
        if pick is None and ibkr is not None:
            for s in order:
                row = ibkr[ibkr["symbol"] == s]
                if len(row) and float(row["available"].iloc[0]) > 0:
                    pick = (s, "ibkr", float(row["fee_rate_pct"].iloc[0]))
                    break
        routes[cls] = pick or (None, "none", None)
    return routes


# ----------------------------------------------------------------- the bar

def fit_pnl_sessions(first_day0) -> tuple[int, pd.Timestamp]:
    """(P&L sessions, first P&L session): from the first possible P&L (day 0 + 2,
    EXEC_LAG) to 2022-12-30. This T is what the trial passes to `_dsr`."""
    from scripts.cef.validate import EXEC_LAG
    from ops.schedule.nyse_calendar import is_trading_day
    start = _add_sessions(_session_on_or_after(first_day0), EXEC_LAG)
    days = pd.bdate_range(start, FIT_LAST_SESSION)
    return int(sum(is_trading_day(d.date()) for d in days)), start


def per_event_power(mu: float, s: float, groups: int, t_bar: float = 2.0) -> float:
    """P(cluster-t >= t_bar) if the per-event mean is mu with sd s, one event per
    group (design effect 1): Phi(mu/s*sqrt(G) - t_bar). Arithmetic on stated
    assumptions; no data enters."""
    from statistics import NormalDist
    return NormalDist().cdf(mu / s * math.sqrt(groups) - t_bar)


def clusters_needed(mu: float, s: float) -> float:
    """The portfolio framework's N_clusters >= (1.96 + 0.84)^2 (s/mu)^2
    (results/cef/PORTFOLIO_FRAMEWORK_2026-10-15.md §1.4)."""
    return (1.96 + 0.84) ** 2 * (s / mu) ** 2


# ----------------------------------------------------------------- report

def build(ibkr_path: str | None) -> tuple[pd.DataFrame, dict, list[str]]:
    nt = load_events()
    ep = pd.read_csv(EPISODES_CSV, parse_dates=["first_date", "last_date"])
    cond = pd.read_csv(COND_CSV, parse_dates=["window_end"])
    summary = json.loads(SUMMARY_JSON.read_text())
    ibkr, stamp = None, None
    if ibkr_path:
        from scripts.events.g1a_shortability import parse_ibkr_shortstock
        ibkr, stamp = parse_ibkr_shortstock(Path(ibkr_path).read_text())

    m = attach_episodes(nt, ep)
    m["merger_open"] = merger_open(m, ep).values
    m["programme"] = triggered_programme(m, cond).values
    m["late_doc"] = (m["doc_date"] - m["ann_date"]).dt.days > PROGRAMME_LAG_DAYS
    m["episode_far"] = (m["last_date"] - m["expire"]).dt.days.abs() > EPISODE_FAR_DAYS
    m["pi_read"] = m["proration"].notna() | m["proration_xcheck"].notna()
    m["last_session"] = [last_pnl_session(r.last_date, r.expire) for r in m.itertuples()]
    m["period"] = [assign_period(r.ann_date, r.last_session) for r in m.itertuples()]
    routes = hedge_routes(summary, ibkr)
    m["hedge_symbol"] = m["asset_class"].map(lambda c: routes[c][0])
    m["hedge_route"] = m["asset_class"].map(lambda c: routes[c][1])

    L = []
    p = L.append
    p("NAV-tender pre-registration: zero-trial counts (no price, no return, no CRSP)")
    p(f"inputs: {EVENTS_CSV.relative_to(REPO)}, {EPISODES_CSV.relative_to(REPO)}, "
      f"{COND_CSV.relative_to(REPO)}, {SUMMARY_JSON.relative_to(REPO)} (Alpaca read "
      f"{summary['data']['alpaca_read_date']}); EDGAR last filing {summary['data']['edgar_last_filing_in_fetcher']}")
    p(f"IBKR shortstock file: {stamp or 'not given'}")
    p("")
    p(f"NAV tenders (census type nav_tender): {len(m)}; in the 44 (cef_universe.csv): {int(m['in_universe'].sum())}")
    p("")
    out = m[~m["in_universe"].astype(bool)]
    p("== periods, the 44 excluded (proxy dates; Stage 0 re-dates from the filings) ==")
    p(f"{'period':<11}{'events':>7}{'groups':>7}{'merger_open':>12}{'pi_read':>8}{'late_doc':>9}"
      f"{'programme':>10}{'episode_far':>12}{'no_hedge':>9}{'ibkr_hedge':>11}")
    for per in ("fit", "gap", "holdout", "after_crsp"):
        g = out[out["period"] == per]
        grp = g.groupby(["sponsor", g["ann_date"].dt.normalize()]).ngroups if len(g) else 0
        p(f"{per:<11}{len(g):>7}{grp:>7}{int(g['merger_open'].sum()):>12}{int(g['pi_read'].sum()):>8}"
          f"{int(g['late_doc'].sum()):>9}{int(g['programme'].sum()):>10}{int(g['episode_far'].sum()):>12}"
          f"{int((g['hedge_route'] == 'none').sum()):>9}{int((g['hedge_route'] == 'ibkr').sum()):>11}")
    fit = out[out["period"] == "fit"]
    elig = fit[~fit["merger_open"]]
    p("")
    p(f"fit, no merger open at day 0: {len(elig)} events, "
      f"{elig.groupby(['sponsor', elig['ann_date'].dt.normalize()]).ngroups} groups; "
      f"of which pro-ration read {int(elig['pi_read'].sum())}")
    gsz = elig.groupby(["sponsor", elig["ann_date"].dt.normalize()]).size()
    p(f"events per group: max {int(gsz.max())}, groups with more than one event {int((gsz > 1).sum())}")
    p("")
    p("== fit events per day-0 year (44 excluded) ==")
    p("  " + ", ".join(f"{y} {n}" for y, n in fit.groupby(fit["ann_date"].dt.year).size().items()))
    p("")
    p("== fit events by asset class, with today's hedge route ==")
    for cls, n in fit["asset_class"].value_counts().items():
        s, route, fee = routes[cls]
        p(f"  {cls:<12}{n:>4}  hedge {s} via {route}" + (f" (IBKR fee {fee:.2f}%/yr)" if fee is not None else ""))
    p("")
    cr = fit[fit["asset_class"].isin(CREDIT_CLASSES)]
    p(f"credit classes {', '.join(CREDIT_CLASSES)}: {len(cr)} fit events, "
      f"{cr.groupby(['sponsor', cr['ann_date'].dt.normalize()]).ngroups} groups")
    p("")
    p("== fit events by day-0 form ==")
    p("  " + ", ".join(f"{k} {v}" for k, v in fit["ann_form"].value_counts().items()))
    p(f"== fit offers for >= 50% of shares: {int((fit['size_pct'] >= 50).sum())}; "
      f"price basis k% median {fit['k_pct'].median():.1f} ==")
    p("")

    # the bar
    from scripts.xasset.slate_feasibility import required_sharpe, power, alpha_t_bar, p_alpha_t
    T, first_pnl = fit_pnl_sessions(fit["ann_date"].min())
    p(f"== the bar: fit P&L sessions T = {T} (first day 0 {fit['ann_date'].min().date()}, first P&L "
      f"session {first_pnl.date()}, to {FIT_LAST_SESSION.date()}) ==")
    p(f"{'N':>3}{'sqrt(2lnN)':>11}{'SR needed':>10}" + "".join(f"{'P@' + str(x):>8}" for x in (0.4, 0.9, 1.6)))
    for n in range(1, 7):
        e = math.sqrt(2 * math.log(n)) if n > 1 else 0.0
        p(f"{n:>3}{e:>11.3f}{required_sharpe(n, T):>10.3f}"
          + "".join(f"{power(x, n, T):>8.2f}" for x in (0.4, 0.9, 1.6)))
    p(f"D4 alpha-t 3.0 needs an annual IR of {alpha_t_bar(T):.3f}; "
      + ", ".join(f"P(alpha t>=3 | IR {x}) {p_alpha_t(x, T):.2f}" for x in (0.4, 0.9, 1.6)))
    p("")
    G = elig.groupby(["sponsor", elig["ann_date"].dt.normalize()]).ngroups
    p(f"== per-event test power at G = {G} groups (ASSUMED mu and s; labelled [U] in the prereg) ==")
    p(f"{'mu %':>6}{'s %':>6}{'P(t>=2)':>9}{'N_clusters':>12}")
    for mu in (0.5, 1.14, 2.14):
        for s in (3.0, 4.0, 6.0):
            p(f"{mu:>6.2f}{s:>6.1f}{per_event_power(mu, s, G):>9.2f}{clusters_needed(mu, s):>12.0f}")
    ho = out[out["period"] == "holdout"]
    Gh = ho.groupby(["sponsor", ho["ann_date"].dt.normalize()]).ngroups
    p("")
    p(f"== holdout sign rule at G = {Gh} groups: P(holdout mean > 0) under the same ASSUMED mu, s ==")
    for mu in (0.5, 1.14, 2.14):
        p("  mu %.2f: " % mu + ", ".join(f"s {s:.0f}% {per_event_power(mu, s, Gh, 0.0):.2f}" for s in (3.0, 4.0, 6.0)))
    return m, routes, L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ibkr", help="path to a copy of IBKR's public usa.txt shortstock file")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    _, _, lines = build(a.ibkr)
    text = "\n".join(lines) + "\n"
    print(text, end="")
    Path(a.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
