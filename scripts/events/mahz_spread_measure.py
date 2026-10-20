"""MA-HZ before any trial: quoted spreads by event week, the completion hump on 2001-22,
turnover and capacity at our size, and D4's power on the larger sample. ZERO TRIALS.

    python3 scripts/events/mahz_spread_measure.py                      # after the staging run
    python3 -m pytest scripts/events/tests/test_mahz_spread_measure.py

It reads what `scripts/data/stage_crsp_merger_targets.py` staged under
`data/events/merger_targets/` (the team lead's run; this script loads no
credential and opens no connection) and writes AGGREGATES ONLY to
`results/events/merger_arb_v2/mahz_measure/`: tables by event week, window,
era, size half, exchange and year. CRSP is licensed and this repository is
public, so no per-deal row leaves `data/`.

WHY THIS EXISTS
---------------
`results/events/MERGER_ARB_V2_2026-10-19.md` §2.6 item 1 names the cheapest
kill, still zero trials: the measured half-spread times the design's turnover,
against the gross the published late-sample alphas imply. If the measured drag
reaches that gross, D2 is predicted and the trial should not be spent. The team
lead asked on 2026-10-19 for the CRSP pull "so its spreads can be measured
before any trial is spent". This script is that measurement, plus three things
the same data settles without a return: whether the completion hump holds on
2001-09 (deals the note never saw), what the book turns over and whether it
fits at our size, and D4's power on the longer sample.

WHAT IT MUST NEVER DO
---------------------
Read a return or compute a price change. It loads only `MEASURE_COLS` from the
staged `dsf` file (no `ret`, `retx`; the delisting file, which holds `dlret`, is
not opened), and `load_staged` raises if a return column reaches it. `prc` is
read for dollar volume (|prc| x vol) and size (|prc| x shrout) only. The deal
(arbitrage) spread, offer minus price, is NOT computed: it needs the offer
terms (the reading problem, §3) and it is the trade's return. "Spread" here is
the quoted bid-ask spread, a cost. Every date is before 2023-01-01
(`assert_fit_only`, H13).

DEFINITIONS (stated once, here)
-------------------------------
* HALF-SPREAD on a session = (ask - bid) / (ask + bid), in bp: half the quoted
  spread over the midpoint, from CRSP's closing `bid`/`ask`. A session counts
  as QUOTED only if 0 < bid <= ask; otherwise it is unquoted, counted, never
  filled. CRSP's own guide (1999 edition) documents `bid`/`ask` for Nasdaq
  issues only (REFERENCES §12au), so `quote_coverage.csv` reports the quoted
  share by exchange and year before any spread is read: a spread table that is
  Nasdaq-only would say so there.
* EXITS (`crsp_exits`): a CRSP merger delisting (dlstcd 200-299) attributed to
  the deal by the stage is a COMPLETION at its dlstdt; a non-merger delisting is
  an OBSERVED FAILURE at its dlstdt; a deal the EDGAR census saw complete after
  the censor is open at the censor; any other deal fails by the note's brackets
  (A: its last anchor; B: announcement + 52 weeks). Censor 2022-12-30.
* WINDOWS: Giglio & Shue's cash windows (Low 1 weeks 1-10, High 12-35, Low 2
  37-45) for both universes, as the note (`merger_arb_v2_feasibility.GS_WINDOWS`).
  The trial will use a rolling prior-data rule instead (§2.4); these fixed
  windows make the turnover comparable to the note's `turnover.csv`.
* TRADES (H1): a window boundary on date b is decided on the first session
  >= b and filled on the next session; the fill session's half-spread is the
  trade's measured cost. A completion is a free exit; a window end or a
  failure is paid; a position open at the censor is neither
  (`merger_arb_v2_feasibility.window_spells`). An exit after a non-merger
  delisting has no exchange price: unmeasured, counted.
* CAPACITY at our size: the book's capital is the frozen spec's `capital_usd`
  (`scripts/cef/spec.py`), at 1x gross, half per side, equal weight within a
  leg, so a position is capital / 2 / (deals in the leg on the decision day,
  the trading deal included). An assumption for this check, not a sizing rule:
  the pre-registration fixes MA-HZ's sizing.
  It fits if it is at most PARTICIPATION (5%) of the median dollar volume over
  the ADV_SESSIONS (63) sessions STRICTLY BEFORE the decision day (H7); both
  are the merger census's conventions. Shown at 1x, 10x and 50x the capital.
* SIZE HALF: market value |prc| x shrout on the last staged session before the
  announcement, split at the median within (universe, announcement year): the
  paper's "small" targets (Table 8).
* ERAS by announcement: 2001-09 (new to this desk), 2010-22 (the note's
  sample). The cost verdict is read on 2010-22: modern costs, not 2000s
  illiquidity (research-harness note on D2).

THE PRE-DECLARED READINGS (H14: every input is re-measured at run time)
-----------------------------------------------------------------------
COST (`cost_verdict`), CASH_1STEP, 2010-22, per bracket: the measured L/S drag
per unit of total gross per year against the gross implied by Giglio & Shue's
cash alphas, recomputed here exactly as the note does (late sample; full
sample x 0.42).
  * UNMEASURED if fewer than MIN_QUOTED_SHARE of either leg's paid trades carry
    a quoted fill: the spread cannot decide.
  * D2_PREDICTED if the drag reaches the late-sample gross under BOTH brackets:
    do not spend the trial. The half-spread is a LOWER bound on cost (no
    impact, no borrow), so this reading is robust.
  * COSTS_DO_NOT_DECIDE if the drag is below the decayed gross under both:
    costs do not kill MA-HZ before the trial. Not proof that it nets positive.
  * MARGINAL otherwise: the trial's K6 decides, and the pre-registration says so.
HUMP (`hump_verdict`), CASH_1STEP, 2001-09: HOLDS if the mean weekly
completion hazard in the paper's High weeks exceeds its Low-1 weeks under both
brackets, else FAILS (the mechanism's precondition, K1, on deals the note never
saw).
POWER: reported, for the team lead's ruling 2 (accept the power).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.data import stage_crsp_merger_targets as S  # noqa: E402
from scripts.events import merger_arb_v2_feasibility as V  # noqa: E402
from scripts.events.merger_arb_feasibility import ADV_SESSIONS, PARTICIPATION  # noqa: E402

OUT = REPO / "results" / "events" / "merger_arb_v2" / "mahz_measure"
MEASURE_COLS = ("permno", "date", "prc", "bid", "ask", "vol", "shrout")
DEAL_COLS = ("deal_id", "universe", "link_status", "permno", "ann", "a1", "d0", "exchcd_at_d0", "crsp_outcome",
             "dlstdt", "completed_edgar", "delist_date_edgar", "fetch_lo", "rows")
UNIVERSES = ("CASH_1STEP", "TENDER_CASH")
ERAS = {"2001-09": (pd.Timestamp("2001-01-01"), pd.Timestamp("2009-12-31")),
        "2010-22": (pd.Timestamp("2010-01-01"), V.ADMIN_CENSOR)}
POOLED = ("2001-22", (pd.Timestamp("2001-01-01"), V.ADMIN_CENSOR))
DECIDING_ERA = "2010-22"
WINDOWS = V.GS_WINDOWS["cash"]
LEGS = {"high": ("high",), "low": ("low1", "low2")}
MIN_QUOTED_SHARE = 0.5
SCALES = (1, 10, 50)
BRACKETS = ("A", "B")


class MeasureError(RuntimeError):
    pass


# =========================================================================== loading
def load_staged(stage_dir: Path = S.OUT_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The staged deals (linked, with rows) and the dsf columns this script may read."""
    pd_, pp = Path(stage_dir) / S.DEALS_CSV, Path(stage_dir) / S.DSF_PARQUET
    for p in (pd_, pp):
        if not p.exists():
            raise FileNotFoundError(f"{p} does not exist: the staging run comes first (the team lead's; "
                                    f"results/events/MERGER_ARB_V2_2026-10-19.md §5)")
    deals = pd.read_csv(pd_, parse_dates=["ann", "a1", "d0", "dlstdt", "delist_date_edgar", "fetch_lo"])
    miss = [c for c in DEAL_COLS if c not in deals.columns]
    if miss:
        raise MeasureError(f"{S.DEALS_CSV} lacks {miss}")
    px = pd.read_parquet(pp, columns=list(MEASURE_COLS))
    assert_no_returns(px)
    px["date"] = pd.to_datetime(px["date"])
    V.assert_fit_only(px["date"], "staged dsf")
    deals = deals[deals["link_status"].eq("linked") & (deals["rows"].fillna(0) > 0)].copy()
    if deals["completed_edgar"].isna().any():
        raise MeasureError(f"{S.DEALS_CSV}: completed_edgar is missing for some deals")
    deals["permno"] = deals["permno"].astype("int64")
    deals["completed_edgar"] = deals["completed_edgar"].astype(bool)
    return deals.reset_index(drop=True), px


def assert_no_returns(frame: pd.DataFrame) -> None:
    hit = [c for c in frame.columns if c in S.RETURN_FIELDS]
    if hit:
        raise MeasureError(f"return column(s) {hit} reached the zero-trial measurement; it reads none")


def half_spread_bp(bid: pd.Series, ask: pd.Series) -> pd.Series:
    """(ask - bid) / (ask + bid) x 1e4 where 0 < bid <= ask, else NaN (unquoted)."""
    b, a = bid.astype(float), ask.astype(float)
    ok = (b > 0) & (a > 0) & (a >= b)
    return ((a - b) / (a + b) * 1e4).where(ok)


# =========================================================================== exits and weeks
def crsp_exits(deals: pd.DataFrame, bracket: str) -> pd.DataFrame:
    """exit, kind and `how` per deal (module docstring, EXITS), through the note's `exits`."""
    d = deals.copy()
    merger = d["crsp_outcome"].eq("merger") & d["dlstdt"].notna()
    late = d["completed_edgar"] & d["delist_date_edgar"].notna() & (d["delist_date_edgar"] > V.ADMIN_CENSOR) & ~merger
    d["completed"] = merger | late
    d["delist_date"] = d["dlstdt"].where(merger, d["delist_date_edgar"].where(late))
    ex = V.exits(d[["ann", "a1", "completed", "delist_date"]], bracket)
    ex["how"] = np.where(ex["kind"].eq("complete"), "crsp_merger",
                         np.where(ex["kind"].eq("admin"), "open_at_censor", f"bracket_{bracket}"))
    other = d["crsp_outcome"].eq("other_delist") & d["dlstdt"].notna() & (d["dlstdt"] <= V.ADMIN_CENSOR)
    ex.loc[other, "exit"] = d.loc[other, "dlstdt"].where(d.loc[other, "dlstdt"] >= d.loc[other, "ann"],
                                                        d.loc[other, "ann"])
    ex.loc[other, "kind"] = "fail"
    ex.loc[other, "how"] = "crsp_other_delist"
    edgar_only = d["completed_edgar"] & d["delist_date_edgar"].notna() & \
        (d["delist_date_edgar"] <= V.ADMIN_CENSOR) & ~merger & ~other
    ex.loc[edgar_only, "how"] = f"bracket_{bracket}|edgar_completed_crsp_not"
    V.assert_fit_only(ex["exit"], f"crsp_exits({bracket})")
    return ex


def signed_week(ann: pd.Series, date: pd.Series) -> pd.Series:
    """Event week: days 0-6 after the announcement are week 1 (the note's `event_week`);
    days 1-7 before it are week -1, 8-14 before week -2."""
    days = (date - ann).dt.days
    return pd.Series(np.where(days >= 0, days // 7 + 1, days // 7), index=date.index).astype(int)


def window_of_week(w: pd.Series, windows: dict = WINDOWS) -> pd.Series:
    out = pd.Series("gap", index=w.index, dtype=object)
    out[w < 1] = "pre"
    for name, (lo, hi) in windows.items():
        out[(w >= lo) & (w <= hi)] = name
    out[w > windows["low2"][1]] = "beyond"
    return out


def era_of(dates: pd.Series) -> pd.Series:
    out = pd.Series(None, index=dates.index, dtype=object)
    for name, (lo, hi) in ERAS.items():
        out[(dates >= lo) & (dates <= hi)] = name
    return out


def size_halves(deals: pd.DataFrame, px: pd.DataFrame) -> pd.Series:
    """'small' / 'large' at the within-(universe, announcement year) median of |prc| x shrout
    on the last staged session strictly before the announcement; 'unknown' if none."""
    m = px.merge(deals[["deal_id", "permno", "ann"]], on="permno")
    m = m[m["date"] < m["ann"]].sort_values("date").groupby("deal_id").tail(1)
    mv = (m["prc"].abs() * m["shrout"]).where(m["shrout"] > 0)
    mcap = pd.Series(mv.values, index=m["deal_id"].values)
    d = deals.assign(mcap=deals["deal_id"].map(mcap))
    med = d.groupby([d["universe"], d["ann"].dt.year])["mcap"].transform("median")
    out = pd.Series("unknown", index=d.index, dtype=object)
    out[d["mcap"].notna() & (d["mcap"] < med)] = "small"
    out[d["mcap"].notna() & (d["mcap"] >= med)] = "large"
    return out


# =========================================================================== spreads by event week
def deal_days(deals: pd.DataFrame, px: pd.DataFrame, exits: pd.DataFrame) -> pd.DataFrame:
    """Every staged session of every deal from its pre-announcement window to its exit,
    with event week, window and half-spread. Rows after a deal's exit are not its days."""
    d = deals.assign(exit=exits["exit"].values)
    m = px.merge(d[["deal_id", "permno", "universe", "ann", "exit", "fetch_lo", "era", "size_half",
                    "exchcd_at_d0"]], on="permno")
    m = m[(m["date"] >= m["fetch_lo"]) & (m["date"] <= m["exit"])]
    pre = m[m["date"] < m["ann"]].sort_values("date").groupby("deal_id").tail(S.PRE_SESSIONS)
    m = pd.concat([pre, m[m["date"] >= m["ann"]]])
    m["week"] = signed_week(m["ann"], m["date"])
    m["window"] = window_of_week(m["week"])
    m["hs_bp"] = half_spread_bp(m["bid"], m["ask"])
    return m.drop(columns=["bid", "ask", "fetch_lo"]).reset_index(drop=True)


def _agg(g: pd.DataFrame) -> pd.Series:
    q = g["hs_bp"].dropna()
    return pd.Series({"deal_days": len(g), "deals": g["deal_id"].nunique(), "quoted_share": round(len(q) / len(g), 3),
                      "hs_median_bp": round(float(q.median()), 1) if len(q) else np.nan,
                      "hs_mean_bp": round(float(q.mean()), 1) if len(q) else np.nan,
                      "hs_p75_bp": round(float(q.quantile(0.75)), 1) if len(q) else np.nan})


def spread_tables(days_by_bracket: dict) -> dict:
    by_week, by_window = [], []
    for br, dd in days_by_bracket.items():
        for era_name, sel in ((e, dd["era"].eq(e)) for e in list(ERAS) + [POOLED[0]]):
            x = dd if era_name == POOLED[0] else dd[sel]
            if x.empty:
                continue
            w = x.groupby(["universe", "week"]).apply(_agg, include_groups=False).reset_index()
            by_week.append(w.assign(bracket=br, era=era_name))
            for keys in (["universe", "window"], ["universe", "size_half", "window"]):
                t = x.groupby(keys).apply(_agg, include_groups=False).reset_index()
                if "size_half" not in t.columns:
                    t["size_half"] = "all"
                by_window.append(t.assign(bracket=br, era=era_name))
    return {"by_week": pd.concat(by_week, ignore_index=True), "by_window": pd.concat(by_window, ignore_index=True)}


def quote_coverage(days: pd.DataFrame) -> pd.DataFrame:
    """Rows and quoted share by announcement-era year of the session and exchange (CRSP exchcd on d0)."""
    x = days.assign(year=days["date"].dt.year)
    t = x.groupby(["year", "exchcd_at_d0"]).agg(rows=("hs_bp", "size"), quoted=("hs_bp", "count")).reset_index()
    t["quoted_share"] = (t["quoted"] / t["rows"]).round(3)
    return t


# =========================================================================== hazard
def hazard_tables(deals: pd.DataFrame, exits_by_bracket: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    weekly, summ = [], []
    for u in UNIVERSES:
        for era_name in list(ERAS) + [POOLED[0]]:
            sel = deals["universe"].eq(u) & (deals["era"].eq(era_name) if era_name != POOLED[0] else True)
            g = deals[sel]
            if len(g) == 0:
                continue
            for br, ex in exits_by_bracket.items():
                e = ex.loc[g.index]
                h = V.completion_hazard(g["ann"], e["exit"], e["kind"])
                weekly.append(h.assign(universe=u, era=era_name, bracket=br))
                try:
                    s = V.hazard_summary(h, WINDOWS)
                except ValueError as err:          # too few deals at risk: recorded, not summarised
                    s = {"not_summarised": str(err)}
                s.update(universe=u, era=era_name, bracket=br, deals=int(len(g)),
                         completed_by_censor=int(e["kind"].eq("complete").sum()),
                         failed=int(e["kind"].eq("fail").sum()), open_at_censor=int(e["kind"].eq("admin").sum()),
                         observed_failures=int(e["how"].eq("crsp_other_delist").sum()))
                summ.append(s)
    return pd.concat(weekly, ignore_index=True), pd.DataFrame(summ)


def hump_verdict(hsum: pd.DataFrame) -> dict:
    x = hsum[hsum["universe"].eq("CASH_1STEP") & hsum["era"].eq("2001-09")]
    if len(x) != len(BRACKETS) or "hazard_mean_in_gs_high" not in x or x["hazard_mean_in_gs_high"].isna().any():
        return {"verdict": "UNMEASURED", "why": "no summarised 2001-09 CASH_1STEP hazard under both brackets"}
    ok = bool((x["hazard_mean_in_gs_high"] > x["hazard_mean_in_gs_low1"]).all())
    return {"verdict": "HOLDS" if ok else "FAILS",
            "by_bracket": {r["bracket"]: {"high": round(float(r["hazard_mean_in_gs_high"]), 4),
                                          "low1": round(float(r["hazard_mean_in_gs_low1"]), 4)}
                           for _, r in x.iterrows()}}


# =========================================================================== trades, turnover, capacity
class Book:
    """Per-permno arrays for O(log n) lookups: dates, half-spread, dollar volume."""

    def __init__(self, px: pd.DataFrame):
        x = px.sort_values(["permno", "date"]).reset_index(drop=True)
        dates = x["date"].to_numpy(dtype="datetime64[ns]")
        hs = half_spread_bp(x["bid"], x["ask"]).to_numpy()
        dv = (x["prc"].abs() * x["vol"]).to_numpy(dtype=float)
        self.g = {int(p): (dates[idx], hs[idx], dv[idx]) for p, idx in x.groupby("permno").indices.items()}

    def fill(self, permno: int, day) -> tuple[bool, float]:
        """(the permno has a row on `day`, its half-spread or NaN)."""
        if permno not in self.g:
            return False, np.nan
        d, hs, _ = self.g[permno]
        j = np.searchsorted(d, np.datetime64(day))
        if j < len(d) and d[j] == np.datetime64(day):
            return True, float(hs[j])
        return False, np.nan

    def adv(self, permno: int, decision) -> float:
        """Median dollar volume over the ADV_SESSIONS rows strictly before `decision` (H7);
        NaN if fewer rows or any missing volume."""
        if permno not in self.g:
            return np.nan
        d, _, dv = self.g[permno]
        i = np.searchsorted(d, np.datetime64(decision), side="left")
        if i < ADV_SESSIONS:
            return np.nan
        w = dv[i - ADV_SESSIONS:i]
        return np.nan if np.isnan(w).any() else float(np.median(w))


def leg_spells(deals: pd.DataFrame, ex: pd.DataFrame, leg: str) -> pd.DataFrame:
    """The leg's spells (one per deal and window), with a unique spell index: a deal
    has a Low 1 and a Low 2 spell, which must not share an id."""
    sp = []
    for w in LEGS[leg]:
        lo, hi = WINDOWS[w]
        s = V.window_spells(deals["ann"], ex["exit"], ex["kind"], lo, hi)
        sp.append(s.assign(window=w, deal_idx=s.index))
    s = pd.concat(sp, ignore_index=True)
    s = s.merge(deals[["deal_id", "permno", "universe", "size_half"]], left_on="deal_idx", right_index=True,
                how="left")
    s["era"] = era_of(s["entry"])
    return s


def occupancy(spells: pd.DataFrame, days: pd.DatetimeIndex) -> np.ndarray:
    """Number of spells with entry <= day < end, for each day."""
    e = np.sort(spells["entry"].to_numpy())
    x = np.sort(spells["end"].to_numpy())
    dv = days.to_numpy()
    return np.searchsorted(e, dv, side="right") - np.searchsorted(x, dv, side="right")


def leg_trades(spells: pd.DataFrame, book: Book, cal: pd.DatetimeIndex, capital: float) -> pd.DataFrame:
    """One row per PAID trade: entries, and exits flagged paid (H1 decision/fill sessions)."""
    rows = []
    for i, r in spells.iterrows():
        for kind, b in (("entry", r["entry"]), ("exit", r["end"] if r["paid_exit"] else None)):
            if b is None:
                continue
            k = cal.searchsorted(b)
            if k + 1 >= len(cal):
                raise MeasureError(f"calendar ends before the fill of a {kind} on {pd.Timestamp(b).date()}")
            dec, fill = cal[k], cal[k + 1]
            rows.append({"spell": i, "deal_id": r["deal_id"], "permno": int(r["permno"]), "era": r["era"],
                         "size_half": r["size_half"], "trade": kind, "decision": dec, "fill": fill})
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t = t[t["fill"] < V.HOLDOUT_START].copy()           # a fill in the sealed year is not read
    got = [book.fill(p, f) for p, f in zip(t["permno"], t["fill"])]
    t["fill_row"] = [g[0] for g in got]
    t["hs_bp"] = [g[1] for g in got]
    t["adv_usd"] = [book.adv(p, d) for p, d in zip(t["permno"], t["decision"])]
    # deals in the leg on the decision day, the trading deal included: an entry's spell is
    # already open on its decision day; an exit's has just closed, so it is added back
    occ = occupancy(spells, pd.DatetimeIndex(t["decision"])) + t["trade"].eq("exit").to_numpy()
    t["n_leg"] = np.maximum(occ, 1)
    for s in SCALES:
        pos = capital * s * 0.5 / t["n_leg"]
        t[f"fits_x{s}"] = (pos <= PARTICIPATION * t["adv_usd"]).where(t["adv_usd"].notna())
    return t


def turnover_rows(spells: pd.DataFrame, trades: pd.DataFrame, start, stop) -> dict:
    """The note's `leg_turnover` plus the measured half-spread of the paid trades."""
    s = spells[(spells["entry"] >= start) & (spells["entry"] <= stop)]
    if s.empty:
        return {}
    t = V.leg_turnover(s, start, stop)
    tr = trades[trades["spell"].isin(s.index)] if len(trades) else trades
    q = tr["hs_bp"].dropna() if len(tr) else pd.Series(dtype=float)
    t.update(paid_trades_measured=int(len(q)), paid_trades_seen=int(len(tr)),
             quoted_share=round(len(q) / len(tr), 3) if len(tr) else np.nan,
             hs_mean_bp=round(float(q.mean()), 2) if len(q) else np.nan,
             hs_median_bp=round(float(q.median()), 2) if len(q) else np.nan,
             exit_after_delisting_unpriced=int((~tr["fill_row"]).sum()) if len(tr) else 0)
    t["measured_drag_bp_per_year"] = t["turnover_per_unit_gross_per_year"] * t["hs_mean_bp"] \
        if np.isfinite(t["hs_mean_bp"]) else np.nan
    return t


def capacity_rows(trades: pd.DataFrame) -> list[dict]:
    out = []
    if trades.empty:
        return out
    for (era, leg), g in trades.groupby(["era", "leg"]):
        m = g["adv_usd"].notna()
        row = {"era": era, "leg": leg, "paid_trades": int(len(g)), "adv_measured": int(m.sum()),
               "median_n_leg": float(g["n_leg"].median()), "adv_median_usd": round(float(g.loc[m, "adv_usd"].median()))
               if m.any() else None}
        for s in SCALES:
            row[f"fit_share_x{s}"] = round(float(g.loc[m, f"fits_x{s}"].astype(bool).mean()), 3) if m.any() else None
        out.append(row)
    return out


def published_gross_bp() -> dict:
    """The gross per unit of total gross per year that Giglio & Shue's cash alphas imply
    (High minus Low 1, half each side, x12): the note's arithmetic, recomputed."""
    g = {k: (h - l) / 2 * 12 for k, (h, l) in V.GS_CASH_ALPHA_BP.items()}
    g["full_x0.42"] = g["full"] * V.MCLEAN_PONTIFF_KEEP
    return g


def cost_verdict(ls: pd.DataFrame, gross: dict) -> dict:
    """The pre-declared COST reading (module docstring) on CASH_1STEP, DECIDING_ERA."""
    x = ls[ls["universe"].eq("CASH_1STEP") & ls["era"].eq(DECIDING_ERA)]
    if set(x["bracket"]) != set(BRACKETS):
        return {"verdict": "UNMEASURED", "why": f"no {DECIDING_ERA} CASH_1STEP L/S row under both brackets"}
    if (x[["quoted_share_high", "quoted_share_low"]].fillna(0) < MIN_QUOTED_SHARE).any().any():
        return {"verdict": "UNMEASURED", "why": f"a leg has fewer than {MIN_QUOTED_SHARE:.0%} quoted paid trades",
                "quoted_shares": x[["bracket", "quoted_share_high", "quoted_share_low"]].to_dict("records")}
    drag = x.set_index("bracket")["measured_drag_bp"]
    late, decayed = gross["late"], gross["full_x0.42"]
    if (drag >= late).all():
        v = "D2_PREDICTED"
    elif (drag < decayed).all():
        v = "COSTS_DO_NOT_DECIDE"
    else:
        v = "MARGINAL"
    return {"verdict": v, "measured_drag_bp_by_bracket": {k: round(float(val), 1) for k, val in drag.items()},
            "late_gross_bp": round(late, 1), "decayed_gross_bp": round(decayed, 1)}


# =========================================================================== power
def power_rows(spells_by_leg: dict, cal: pd.DatetimeIndex, first_ann: pd.Timestamp, label: str) -> list[dict]:
    """P(alpha t >= 3) at each published IR over (a) every session from the first P&L a
    two-leg book can earn (both legs non-empty on a decision day, + H1's two sessions)
    to the censor, and (b) only the sessions with both legs non-empty."""
    from scripts.xasset.slate_feasibility import alpha_t_bar, p_alpha_t
    hi, lo = spells_by_leg["high"], spells_by_leg["low"]
    hi, lo = hi[hi["entry"] >= first_ann], lo[lo["entry"] >= first_ann]
    days = cal[(cal >= first_ann) & (cal <= V.ADMIN_CENSOR)]
    both = (occupancy(hi, days) > 0) & (occupancy(lo, days) > 0)
    if not both.any():
        return []
    i0 = cal.searchsorted(days[np.argmax(both)])
    first_pnl = cal[i0 + 2]                     # H1: decide t, fill t+1, earn t+2
    T = int(((cal >= first_pnl) & (cal < V.HOLDOUT_START)).sum())
    T_both = int(both.sum())
    rows = []
    for key, lab, ir, _yrs, src in V.published_irs():
        for scale_name, sc in (("as published", 1.0), ("x0.42 post-publication", V.MCLEAN_PONTIFF_KEEP)):
            r = ir * sc
            rows.append({"census": label, "first_pnl": str(first_pnl.date()), "sessions": T,
                         "sessions_both_legs": T_both, "test": key, "label": lab, "source": src,
                         "scale": scale_name, "ir": round(r, 3),
                         "ir_needed_all_sessions": round(alpha_t_bar(T), 3),
                         "p_alpha_t_ge_3_all_sessions": round(p_alpha_t(r, T), 4),
                         "ir_needed_both_legs": round(alpha_t_bar(T_both), 3),
                         "p_alpha_t_ge_3_both_legs": round(p_alpha_t(r, T_both), 4)})
    return rows


# =========================================================================== run
def measure(deals: pd.DataFrame, px: pd.DataFrame, cal: pd.DatetimeIndex, capital: float) -> dict:
    """Every table and both verdicts. Pure given its inputs (the tests pass synthetic ones)."""
    deals = deals.copy()
    deals["era"] = era_of(deals["ann"])
    deals = deals[deals["era"].notna()].reset_index(drop=True)
    deals["size_half"] = size_halves(deals, px)
    book = Book(px)
    exits = {br: crsp_exits(deals, br) for br in BRACKETS}
    days = {br: deal_days(deals, px, exits[br]) for br in BRACKETS}
    sp = spread_tables(days)
    cov = quote_coverage(days["B"])
    hweekly, hsum = hazard_tables(deals, exits)
    turn, trades_all, ls, cap, pw = [], [], [], [], []
    for u in UNIVERSES:
        du = deals[deals["universe"].eq(u)]
        if du.empty:
            continue
        for br in BRACKETS:
            exu = exits[br].loc[du.index]
            spells = {leg: leg_spells(du, exu, leg) for leg in LEGS}
            tr = {}
            for leg, s in spells.items():
                t = leg_trades(s, book, cal, capital)
                tr[leg] = t.assign(leg=leg, universe=u, bracket=br) if len(t) else t
                trades_all.append(tr[leg])
            for era_name, (lo, hi) in list(ERAS.items()) + [POOLED]:
                per = {}
                for leg, s in spells.items():
                    rr = turnover_rows(s, tr[leg], lo, hi)
                    if rr:
                        rr.update(universe=u, bracket=br, era=era_name, leg=leg)
                        turn.append(rr)
                        per[leg] = rr
                if set(per) == set(LEGS):
                    h, l = per["high"], per["low"]
                    row = {"universe": u, "bracket": br, "era": era_name,
                           "turnover_ls": round(0.5 * h["turnover_per_unit_gross_per_year"]
                                                + 0.5 * l["turnover_per_unit_gross_per_year"], 2),
                           "quoted_share_high": h["quoted_share"], "quoted_share_low": l["quoted_share"],
                           "measured_drag_bp": round(0.5 * h["measured_drag_bp_per_year"]
                                                     + 0.5 * l["measured_drag_bp_per_year"], 1)}
                    for c in V.COST_GRID_BP:
                        row[f"drag_bp_at_{c}"] = round(row["turnover_ls"] * c, 1)
                    ls.append(row)
            if u == "CASH_1STEP":             # power is the trial's; the control has none to compute
                pw += power_rows(spells, cal, deals["ann"].min(), f"{br}|staged_2001")
                pw += power_rows(spells, cal, ERAS["2010-22"][0], f"{br}|staged_2010")
    trades = pd.concat([t for t in trades_all if len(t)], ignore_index=True) if any(len(t) for t in trades_all) \
        else pd.DataFrame()
    for (u, br), g in (trades.groupby(["universe", "bracket"]) if len(trades) else []):
        for r in capacity_rows(g):
            r.update(universe=u, bracket=br)
            cap.append(r)
    lsdf = pd.DataFrame(ls)
    gross = published_gross_bp()
    return {"spread_by_week": sp["by_week"], "spread_by_window": sp["by_window"], "quote_coverage": cov,
            "hazard_weekly": hweekly, "hazard_summary": hsum, "turnover": pd.DataFrame(turn),
            "ls_cost": lsdf, "capacity": pd.DataFrame(cap), "power": pd.DataFrame(pw),
            "gross_bp": gross, "cost_verdict": cost_verdict(lsdf, gross) if len(lsdf) else
            {"verdict": "UNMEASURED", "why": "no L/S rows"}, "hump_verdict": hump_verdict(hsum),
            "counts": {"deals": int(len(deals)), "by_universe_era": {f"{u}|{e}": int(n) for (u, e), n in
                                                                    deals.groupby(["universe", "era"]).size().items()},
                       "size_half": {k: int(v) for k, v in deals["size_half"].value_counts().items()},
                       "exit_how_A": {k: int(v) for k, v in exits["A"]["how"].value_counts().items()},
                       "exit_how_B": {k: int(v) for k, v in exits["B"]["how"].value_counts().items()}}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage-dir", default=str(S.OUT_DIR))
    a = ap.parse_args(argv)
    pd.set_option("display.width", 220)
    from scripts.cef.spec import CAPITAL_USD
    deals, px = load_staged(Path(a.stage_dir))
    cal = V.session_calendar()
    res = measure(deals, px, cal, CAPITAL_USD)
    OUT.mkdir(parents=True, exist_ok=True)
    for k in ("spread_by_week", "spread_by_window", "quote_coverage", "hazard_weekly", "hazard_summary",
              "turnover", "ls_cost", "capacity", "power"):
        res[k].to_csv(OUT / f"{k}.csv", index=False)
    summary = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "zero_trials": True,
               "stage_dir": str(Path(a.stage_dir)), "capital_usd": CAPITAL_USD,
               "dsf_last": str(px["date"].max().date()), "calendar_last": str(cal.max().date()),
               "gross_bp_per_unit_total_gross": res["gross_bp"], "cost_verdict": res["cost_verdict"],
               "hump_verdict": res["hump_verdict"], "counts": res["counts"]}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(res["quote_coverage"].to_string(index=False))
    print("\nL/S cost per unit of total gross, bp/yr (grid and measured half-spread):\n",
          res["ls_cost"].to_string(index=False))
    print("\nhazard summary:\n", res["hazard_summary"].to_string(index=False))
    print("\ncapacity:\n", res["capacity"].to_string(index=False))
    print(json.dumps({"cost": res["cost_verdict"], "hump": res["hump_verdict"]}, indent=1, default=str))
    print(f"\nwrote {OUT.relative_to(REPO)}/ (aggregates only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
