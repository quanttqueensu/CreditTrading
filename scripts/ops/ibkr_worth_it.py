"""Is IBKR worth opening for the shorts Alpaca will not lend? The core-book benefit, measured.

    python3 scripts/ops/ibkr_worth_it.py            # prints every table; writes results/ops/ibkr_worth_it/
    python3 -m pytest scripts/ops/tests/test_ibkr_worth_it.py scripts/cef/tests/test_band_gross_capped.py

WHY (team lead, 2026-10-19, after hearing that only MHD (always), PHK and MQY
(sometimes) of the 13 spec names need IBKR, that IBKR's weekly login is manual
and that the VM would need 4 GB: "Figure out if it's worth it"). The note is
`results/ops/IBKR_WORTH_IT_2026-10-19.md`; this script is its §1, the benefit
to the core book. The costs and the option value are in the note.

ZERO TRIALS. A diagnostic: nothing here is adopted, and no variant is a
candidate for the spec. THE 2023-01-01 TIME HOLDOUT IS NOT READ: the four
panels the harness reads are copied, cut at the last session before
`band_frontier.HOLDOUT_START`, into a temporary directory, and
`band_frontier.DATA_DIR` points there for the whole run (the C5 pattern,
`scripts/cef/c5_open_auction.py::frozen`). The cut is exact, not an
approximation, because `build_targets`, `band` and `evaluate` are causal
(`scripts/cef/tests/test_pnl_series.py` tests the no-lookahead end to end), and
every frame is asserted to end before 2023-01-01.

WHAT IS COMPARED, on the canonical harness (`build_targets` -> the deployed
`band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)` -> `evaluate`, shift(2)),
every parameter read through `scripts/cef/spec.py`:

* **base**: every name lendable every day (what a book with IBKR behind Alpaca
  could hold, if IBKR always lends: an upper bound on access);
* **skip X**: name X never lendable, under the LIVE rule (gate 7 skips an order
  that opens or enlarges a short, lets reductions through; the book is left
  net long by the missing short). `band_gross_capped(..., unshortable=...)`,
  added beside the loop for this note, with its no-op proved;
* **re-neutral X** (a policy the book does NOT run; report only): X's short
  target is removed and the other names' shorts are scaled up to the same
  short total, so the book stays dollar-neutral at the same gross. It answers
  "is the value in the muni short, or only in not being net long?".

X is each name that needed IBKR on a committed record (derived from
`results/ops/ibkr_second_broker/names_2026-10-19.csv`, never typed here), and
the three together. "Never lendable" is the f = 1 end; a synthetic block test
(section 7) checks how the benefit scales when only a fraction f of sessions is
blocked. Synthetic flags are a statement about how the POLICY responds, not
about how often Alpaca refuses.

CONVENTIONS. Gross P&L is the headline (D19/D20). The 5/15/30bp grid on
turnover sits beside it, labelled, never mixed in. Borrow at IBKR's fee on the
names file's stamp is its own column, charged by `band_frontier.borrow_charge`
on the X shorts only (an easy-to-borrow Alpaca short is free, REFERENCES §12l,
so the IBKR fee is the increment). IBKR's Pro Fixed commission on the
IBKR-routed trades is its own column too. TOTAL returns (splits and
distributions: a short pays the distribution) are the headline convention;
price returns, which is what Alpaca paper scores because it books no dividends,
are printed beside the headline pair. Era rows follow landmine 8 (pre-2013 is
flat).

NO SILENT FALLBACKS. A name missing from the names file, a probe snapshot
without a mark for a name, a fee panel gap: each raises or is reported as
coverage, never filled.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

NAMES_CSV = REPO / "results" / "ops" / "ibkr_second_broker" / "names_2026-10-19.csv"
PROBE_DIR = REPO / "results" / "ops" / "alpaca_probe"
OUT = REPO / "results" / "ops" / "ibkr_worth_it"
LIVE_CEF = REPO / "data" / "cef"
PANELS = (("cef_prices", "date"), ("cef_nav", "date"),
          ("cef_distributions", "ex_date"), ("cef_splits", "ex_date"))

# Era rows. The headline is the traded era: before 2013 too few names clear the
# ADV floor and the book is flat (CLAUDE.md landmine 8), so a full-sample row
# dilutes everything. These are reporting windows, not choices that move a result.
ERAS = (("fit 2005-22", "2005-01-01", "2022-12-31"),
        ("2013-06..2022", "2013-06-01", "2022-12-31"),
        ("2015-19", "2015-01-01", "2019-12-31"),
        ("2020-22", "2020-01-01", "2022-12-31"))
HEADLINE = "2013-06..2022"
MATCH_TOL = 0.05            # H2: turnover within 5%
COSTS = (5, 15, 30)         # the desk's grid, bp per unit of turnover

# IBKR Pro Fixed, US stocks [V 2026-10-19, docs/REFERENCES.md §12af and §12ag]:
# USD 0.005 a share, minimum USD 1.00, maximum 1% of trade value. Published
# schedule constants, not estimates; the test pins IBKR's own worked examples.
IBKR_PER_SHARE, IBKR_MIN, IBKR_MAX_PCT = 0.005, 1.00, 0.01

# Synthetic blocking (section 7): fractions of sessions blocked and episode
# lengths in sessions. Declared grid points to show the SHAPE of benefit(f);
# nothing is selected from them. Seeds fixed for reproducibility.
EPISODE_F = (0.25, 0.5)
EPISODE_L = (5, 21)
EPISODE_SEEDS = range(10)


# ---------------------------------------------------------------------------
# pure helpers (tested in scripts/ops/tests/test_ibkr_worth_it.py)
# ---------------------------------------------------------------------------
def names_needing_ibkr(names: pd.DataFrame) -> list[str]:
    """Spec names that were not lendable at Alpaca on at least one committed
    record: a probe snapshot (`probe_unshortable` > 0) or the 2026-10-18 flag
    read (`alpaca_20261018_shortable` False). Derived, never typed, so the list
    moves when the records do (H14)."""
    need = {"symbol", "in_spec", "probe_unshortable", "alpaca_20261018_shortable"}
    miss = need - set(names.columns)
    if miss:
        raise ValueError(f"names file lacks columns {sorted(miss)}")
    n = names[names["in_spec"].astype(bool)]
    flag = (n["probe_unshortable"] > 0) | (~n["alpaca_20261018_shortable"].astype(bool))
    return sorted(n.loc[flag, "symbol"].tolist())


def ibkr_fixed_commission(notional, price):
    """IBKR Pro Fixed commission in USD for one order of `notional` USD at
    `price`: max(USD 1.00, USD 0.005 x shares), capped at 1% of trade value.
    Shares are notional / price (whole-share rounding is ignored, as the
    harness ignores it). Zero notional costs nothing (no order is sent)."""
    notional = np.asarray(notional, dtype=float)
    if (notional < 0).any():
        raise ValueError("notional must be >= 0")
    if not np.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a positive number, got {price}")
    shares = notional / price
    c = np.minimum(np.maximum(IBKR_MIN, IBKR_PER_SHARE * shares), IBKR_MAX_PCT * notional)
    return np.where(notional > 0, c, 0.0)


def ibkr_routed_trades(H: pd.DataFrame) -> pd.DataFrame:
    """Weight traded at IBKR under the sticky routing of the IBKR design
    (`results/ops/IBKR_SECOND_BROKER_2026-10-19.md` §2.2): a short of a name
    Alpaca will not lend is opened at IBKR and every later trade in it goes
    there until it is closed; longs stay at Alpaca. So the IBKR leg trades the
    change in the NEGATIVE part of the held weight, |min(h_t,0) - min(h_t-1,0)|,
    and a long->short flip splits into a close at Alpaca and an open at IBKR.
    Row t is the trade decided at t (filled at t+1); the first row trades from
    flat, as `band` starts from flat."""
    neg = H.clip(upper=0.0)
    return neg.diff().abs().fillna(neg.abs())


def block_flags(index, columns, f, L, rng) -> pd.DataFrame:
    """Synthetic unshortable flags: for each column independently, the index is
    cut into consecutive blocks of L sessions and each block is blocked with
    probability f. A statement about the policy's response to episodes of a
    given length and frequency, never about Alpaca's lending."""
    if not 0.0 <= f <= 1.0 or L < 1:
        raise ValueError("need 0 <= f <= 1 and L >= 1")
    n = len(index)
    out = {}
    for c in columns:
        nb = -(-n // L)
        b = rng.random(nb) < f
        out[c] = np.repeat(b, L)[:n]
    return pd.DataFrame(out, index=index).astype(bool)


def reneutral_targets(T: pd.DataFrame, blocked: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Report-only policy: on a blocked (t, i) with a short target, set the
    target to 0 and scale the other names' shorts up so the short total (and so
    gross and dollar-neutrality) is unchanged. Rows where every short is
    blocked cannot be re-neutralised; they keep the zeroed target and are
    counted (returned), never silently patched."""
    A = T.to_numpy(copy=True)
    B = blocked.reindex(index=T.index, columns=T.columns, fill_value=False).to_numpy(dtype=bool)
    stuck = 0
    for t in range(len(A)):
        hit = B[t] & (A[t] < 0)
        if not hit.any():
            continue
        s_all = -A[t][A[t] < 0].sum()
        A[t][hit] = 0.0
        others = A[t] < 0
        s_oth = -A[t][others].sum()
        if s_oth > 0:
            A[t][others] *= s_all / s_oth
        else:
            stuck += 1
    return pd.DataFrame(A, index=T.index, columns=T.columns), stuck


def nw_t(x: pd.Series, lags: int = 5) -> float:
    """Newey-West t of the mean (Bartlett kernel), the house HAC convention."""
    x = pd.Series(x).dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 2:
        return float("nan")
    e = x - x.mean()
    s = e @ e / n
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(s / n)) if s > 0 else float("nan")


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def fit_cut_panels():
    """Point band_frontier at a copy of the four panels, spec names only, cut
    strictly before HOLDOUT_START. Restores DATA_DIR on exit."""
    from scripts.cef import band_frontier as bf
    from scripts.cef.spec import UNIVERSE
    tmp = Path(tempfile.mkdtemp(prefix="ibkr_worth_fit_"))
    try:
        for name, col in PANELS:
            d = pd.read_parquet(LIVE_CEF / f"{name}.parquet")
            d = d[d.ticker.isin(UNIVERSE)]
            d = d[pd.to_datetime(d[col]) < bf.HOLDOUT_START].reset_index(drop=True)
            if len(d) and pd.to_datetime(d[col]).max() >= bf.HOLDOUT_START:
                raise AssertionError(f"{name}: the cut leaked a holdout row")
            d.to_parquet(tmp / f"{name}.parquet", index=False)
        old = bf.DATA_DIR
        bf.DATA_DIR = tmp
        try:
            yield tmp
        finally:
            bf.DATA_DIR = old
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def latest_marks(names: list[str]) -> dict:
    """{name: (price, snapshot date)}: the broker's own mark (market value /
    qty) in the newest committed probe snapshot that holds the name. Used only
    to turn a weight into shares for the commission schedule (a cost input,
    not a return). Raises if no snapshot holds a name."""
    out = {}
    for p in sorted(PROBE_DIR.glob("*_cef.json")):
        d = json.loads(p.read_text())
        for pos in d.get("positions", []):
            s = pos["symbol"]
            if s in names:
                q = float(pos["qty"])
                out[s] = (abs(float(pos["market_value"]) / q), p.name[:10])
    miss = sorted(set(names) - set(out))
    if miss:
        raise ValueError(f"no committed probe snapshot holds {miss}; no price to size a commission")
    return out


def era_slice(s, a, b):
    return s.loc[a:b]


def stats(pnl, turn):
    from scripts.cef.band_frontier import _stats
    return _stats(pnl, turn)


def fmt_row(lab, era, s, extra=""):
    n5, n15, n30 = s["nets"]
    flip = "YES" if np.sign(n5) != np.sign(n30) else "no"
    return (f"{lab:<26}{era:<15}{s['sr']:7.2f}{s['ann'] * 100:7.2f}{s['vol'] * 100:7.2f}"
            f"{s['turn']:8.1f}{n5:8.2f}{n15:8.2f}{n30:8.2f}{flip:>6}{extra}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-write", action="store_true", help="print only; write no CSV")
    args = ap.parse_args(argv)

    from scripts.cef import band_frontier as bf
    from scripts.cef.spec import (BAND_WIDTH, CAPITAL_USD, MAX_GROSS_STRESS, MIN_ADV_USD,
                                  UNIVERSE, summary)
    import statsmodels.api as sm

    names = pd.read_csv(NAMES_CSV)
    X = names_needing_ibkr(names)
    fee_now = names.set_index("symbol")["ibkr_fee_pct"]
    stamp = names["ibkr_file_stamp"].iloc[0]
    if fee_now.reindex(X).isna().any():
        raise ValueError(f"names file has no IBKR fee for {X}")
    marks = latest_marks(X)
    cap = MAX_GROSS_STRESS if MAX_GROSS_STRESS is not None else np.inf
    tables = {}

    print(summary())
    print(f"names needing IBKR on a committed record (derived from {NAMES_CSV.name}): {X}")
    print(f"IBKR fee on the file stamped {stamp}: " + ", ".join(f"{x} {fee_now[x]:.4f}%/yr" for x in X))
    print("broker marks for the commission schedule: "
          + ", ".join(f"{x} ${p:.2f} ({d})" for x, (p, d) in marks.items()))
    print(f"capital for dollar figures: CAPITAL_USD = {CAPITAL_USD:,.0f} (spec)\n")

    with fit_cut_panels():
        books = {}
        for lab, floor in (("deployed", None), ("WIDE", 0)):
            T, R = bf.build_targets(min_adv=floor)
            T, R = bf.fit_only(T, R)
            Rtr = bf.total_returns(R)
            p = bf.build_panel()
            for fr in (T, R, Rtr, p["z"]):
                assert fr.index.max() < bf.HOLDOUT_START, "holdout leak"
            elig = p["z"].notna() & (p["adv"] >= (MIN_ADV_USD if floor is None else 0))
            elig = elig.reindex(index=T.index, columns=T.columns, fill_value=False)
            # equal-weight total return of the names priced that day: the "beta"
            # the skip book picks up by going net long. NaN where a name has no
            # price, so the mean is over the names that exist.
            ew_px = p["ret"].reindex(index=T.index, columns=T.columns)
            ew = bf.total_returns(ew_px).where(ew_px.notna()).mean(axis=1)
            books[lab] = dict(T=T, R=R, Rtr=Rtr, elig=elig, ew=ew)
        print(f"fit-cut panels: T {books['deployed']['T'].index[0].date()} .. "
              f"{books['deployed']['T'].index[-1].date()} ({len(books['deployed']['T'])} sessions); "
              f"nothing on or after {bf.HOLDOUT_START.date()} was read into the harness.\n")

        # ---------------------------------------------------------------- [1]
        print("=" * 110)
        print("[1] HOW OFTEN AND HOW MUCH THE BAND WANTS EACH NAME SHORT (held book H, the deployed band + cap)")
        print("=" * 110)
        print("eligible = has a z-score and clears the ADV floor (deployed) / has a z-score (WIDE).")
        print("short share = the name's share of the book's summed short weight in the era.\n")
        rows = []
        print(f"{'set':<9}{'era':<15}{'name':<6}{'eligible':>9}{'held short':>11}{'held long':>10}"
              f"{'mean w | short':>15}{'mean |short|':>13}{'short share':>12}")
        for lab, bk in books.items():
            H = bf.band_gross_capped(bk["T"], BAND_WIDTH, cap)
            bk["H"] = H
            for era, a, b in ERAS:
                h, el = H.loc[a:b], bk["elig"].loc[a:b]
                tot_short = (-h.clip(upper=0)).sum().sum()
                for x in X:
                    s = h[x]
                    r = dict(set=lab, era=era, name=x, eligible=el[x].mean(),
                             held_short=(s < 0).mean(), held_long=(s > 0).mean(),
                             mean_w_when_short=s[s < 0].mean() if (s < 0).any() else np.nan,
                             mean_abs_short=(-s.clip(upper=0)).mean(),
                             short_share=(-s.clip(upper=0)).sum() / tot_short if tot_short > 0 else np.nan)
                    rows.append(r)
                    print(f"{lab:<9}{era:<15}{x:<6}{r['eligible']:9.1%}{r['held_short']:11.1%}"
                          f"{r['held_long']:10.1%}{r['mean_w_when_short']:15.3f}{r['mean_abs_short']:13.4f}"
                          f"{r['short_share']:12.1%}")
        tables["holdings_freq"] = pd.DataFrame(rows)

        # ---------------------------------------------------------------- [2]
        print("\n" + "=" * 110)
        print("[2] GROSS P&L OF EACH NAME'S SHORT LEG IN THE BASE BOOK (total returns; %/yr of capital; NW t, 5 lags)")
        print("=" * 110)
        print("contribution_t = H[t-2, x] * R[t, x] where H[t-2, x] < 0 (the shift(2) of evaluate()).\n")
        rows = []
        print(f"{'set':<9}{'era':<15}{'name':<6}{'short leg %/yr':>15}{'t':>7}{'long leg %/yr':>14}{'t':>7}"
              f"{'book %/yr':>10}")
        for lab, bk in books.items():
            held = bk["H"].shift(2).fillna(0.0)
            contrib = held * bk["Rtr"]
            book = bf.evaluate(bk["H"], bk["Rtr"])["pnl"]
            for era, a, b in ERAS:
                for x in X:
                    c, hx = contrib[x].loc[a:b], held[x].loc[a:b]
                    sl, ll = c.where(hx < 0, 0.0), c.where(hx > 0, 0.0)
                    r = dict(set=lab, era=era, name=x, short_leg_ann=sl.mean() * 252, short_leg_t=nw_t(sl),
                             long_leg_ann=ll.mean() * 252, long_leg_t=nw_t(ll),
                             book_ann=book.loc[a:b].mean() * 252)
                    rows.append(r)
                    print(f"{lab:<9}{era:<15}{x:<6}{r['short_leg_ann'] * 100:15.3f}{r['short_leg_t']:7.2f}"
                          f"{r['long_leg_ann'] * 100:14.3f}{r['long_leg_t']:7.2f}{r['book_ann'] * 100:10.2f}")
        tables["short_leg_pnl"] = pd.DataFrame(rows)

        # ---------------------------------------------------------------- [3]
        print("\n" + "=" * 110)
        print("[3] WITH vs WITHOUT: each name (and all together) NEVER lendable, live skip rule; plus re-neutral (report only)")
        print("=" * 110)
        print("GROSS is the headline (SR, %/yr, vol%). net@5/15/30 = Sharpe after bp x turnover, the real-money grid,")
        print("labelled, not mixed in. 'IBKR borrow' = the X shorts at IBKR's fee on the file stamp (its own column);")
        print("'IBKR comm' = Pro Fixed on the IBKR-routed trades at CAPITAL_USD and the broker marks above.\n")
        configs = [("base (all lendable)", None, None)]
        for x in X:
            configs.append((f"skip {x}", [x], "skip"))
        configs.append(("skip " + "+".join(X), list(X), "skip"))
        configs.append(("re-neutral " + "+".join(X), list(X), "reneutral"))
        rows, diffs = [], []
        for lab, bk in books.items():
            T, Rtr, R = bk["T"], bk["Rtr"], bk["R"]
            res = {}
            for cl, xs, mode in configs:
                if xs is None:
                    H = bk["H"]
                    stuck = 0
                else:
                    blk = pd.DataFrame(False, index=T.index, columns=xs)
                    blk[:] = True
                    if mode == "skip":
                        H, stuck = bf.band_gross_capped(T, BAND_WIDTH, cap, unshortable=blk), 0
                        assert (H[xs] >= 0).all().all(), "a never-lendable name was shorted"
                    else:
                        T2, stuck = reneutral_targets(T, blk)
                        H = bf.band_gross_capped(T2, BAND_WIDTH, cap, unshortable=blk)
                ev = bf.evaluate(H, Rtr)
                evp = bf.evaluate(H, R)
                res[cl] = dict(H=H, pnl=ev["pnl"], turn=ev["turn_series"], pnl_px=evp["pnl"], stuck=stuck)
            bk["res"] = res
            base = res["base (all lendable)"]
            # The base book's X shorts at IBKR's fee on the file stamp, and the Pro
            # Fixed commission on its IBKR-routed trades, PER NAME, so a without-book
            # that blocks only some names is netted against only their costs.
            trades = ibkr_routed_trades(base["H"][X])
            cost_by = {}
            for x in X:
                bx = bf.borrow_charge(base["H"][[x]], pd.DataFrame({x: fee_now[x]}, index=T.index))
                assert bx["covered_share"] == 1.0
                cx = pd.Series(ibkr_fixed_commission(trades[x].to_numpy() * CAPITAL_USD, marks[x][0])
                               / CAPITAL_USD, index=T.index)
                cost_by[x] = (bx["cost"], cx)
            borrow = {"cost": sum(cost_by[x][0] for x in X)}
            comm = sum(cost_by[x][1] for x in X)
            bk["cost_by"] = cost_by
            print(f"--- {lab} ---")
            print(f"{'book':<26}{'era':<15}{'grossSR':>7}{'ann%':>7}{'vol%':>7}{'turn/yr':>8}"
                  f"{'net@5':>8}{'net@15':>8}{'net@30':>8}{'flips':>6}{'net exp':>9}{'beta EW':>9}"
                  f"{'IBKR borrow %/yr':>18}{'IBKR comm %/yr':>16}")
            for era, a, b in ERAS:
                for cl, *_ in configs:
                    r_ = res[cl]
                    s = stats(r_["pnl"].loc[a:b], r_["turn"].loc[a:b])
                    netexp = r_["H"].sum(axis=1).loc[a:b].mean()
                    y, xx = r_["pnl"].loc[a:b], bk["ew"].loc[a:b]
                    ok = xx.notna()
                    beta = float(np.polyfit(xx[ok], y[ok], 1)[0]) if ok.sum() > 10 and xx[ok].std() > 0 else np.nan
                    is_base = cl.startswith("base")
                    b_ann = borrow["cost"].loc[a:b].mean() * 252 if is_base else np.nan
                    c_ann = comm.loc[a:b].mean() * 252 if is_base else np.nan
                    extra = (f"{netexp:9.3f}{beta:9.3f}"
                             + (f"{b_ann * 100:18.3f}{c_ann * 100:16.3f}" if is_base else f"{'':>18}{'':>16}"))
                    print(fmt_row(cl, era, s, extra))
                    rows.append(dict(set=lab, era=era, book=cl, gross_sr=s["sr"], ann=s["ann"], vol=s["vol"],
                                     turn=s["turn"], net5_sr=s["nets"][0], net15_sr=s["nets"][1],
                                     net30_sr=s["nets"][2], net_exposure=netexp, beta_ew=beta,
                                     ibkr_borrow_ann=b_ann, ibkr_comm_ann=c_ann,
                                     rows_not_reneutralisable=r_["stuck"]))
                print()
            # the differences: base minus each without-book, gross and on the grid
            print(f"  {lab}: BENEFIT OF ACCESS = base minus the without-book (%/yr of capital; + favours IBKR)")
            print(f"  {'without-book':<26}{'era':<15}{'d gross':>8}{'NW t':>7}{'d@5':>7}{'d@15':>7}{'d@30':>7}"
                  f"{'flips':>6}{'d turn':>8}{'turn gap':>9}{'alpha vs EW':>12}{'t':>6}{'d beta':>8}"
                  f"{'d px-ret':>9}{'d - IBKR borrow - comm':>24}")
            for era, a, b in ERAS:
                for cl, *_ in configs[1:]:
                    d = (base["pnl"] - res[cl]["pnl"]).loc[a:b]
                    dpx = (base["pnl_px"] - res[cl]["pnl_px"]).loc[a:b]
                    tb, tw = base["turn"].loc[a:b].mean() * 252, res[cl]["turn"].loc[a:b].mean() * 252
                    dt_ = tb - tw
                    g = d.mean() * 252
                    grid = [g - dt_ * c / 1e4 for c in COSTS]
                    flip = "YES" if np.sign(grid[0]) != np.sign(grid[2]) or np.sign(g) != np.sign(grid[2]) else "no"
                    xx = bk["ew"].loc[a:b]
                    ok = xx.notna()
                    ols = sm.OLS(d[ok].to_numpy(), sm.add_constant(xx[ok].to_numpy())).fit(
                        cov_type="HAC", cov_kwds={"maxlags": 5})
                    alpha, at, dbeta = ols.params[0] * 252, ols.tvalues[0], ols.params[1]
                    xs_ = [x for x in X if x in cl.split(" ", 1)[1].split("+")]
                    cost_x = sum((cost_by[x][0].loc[a:b].mean() + cost_by[x][1].loc[a:b].mean()) * 252
                                 for x in xs_)
                    gap = tw / tb - 1 if tb > 0 else np.nan
                    print(f"  {cl:<26}{era:<15}{g * 100:8.3f}{nw_t(d):7.2f}"
                          + "".join(f"{v * 100:7.3f}" for v in grid)
                          + f"{flip:>6}{dt_:8.2f}{gap:9.1%}{alpha * 100:12.3f}{at:6.2f}{dbeta:8.3f}"
                          + f"{dpx.mean() * 252 * 100:9.3f}{(g - cost_x) * 100:24.3f}")
                    diffs.append(dict(set=lab, era=era, without=cl, d_gross_ann=g, d_nw_t=nw_t(d),
                                      d_net5=grid[0], d_net15=grid[1], d_net30=grid[2], d_turn=dt_,
                                      turn_gap=gap, alpha_vs_ew=alpha, alpha_t=at, d_beta=dbeta,
                                      d_price_ret_ann=dpx.mean() * 252,
                                      ibkr_borrow_plus_comm_ann=cost_x, d_after_ibkr_costs=g - cost_x))
            print()
        tables["with_without"] = pd.DataFrame(rows)
        tables["benefit"] = pd.DataFrame(diffs)

        # A second method for the number that drives the decision: the gross P&L
        # of the blocked names' short legs IN the base book (section 2), summed,
        # against the book difference above. They differ by what the band and the
        # ceiling do with the freed gross, and should agree in sign and size.
        print("CROSS-CHECK (two methods for the f = 1 benefit, %/yr, total returns):")
        sl = tables["short_leg_pnl"]
        for lab in books:
            for era, a_, b_ in ERAS:
                legs = sl[(sl["set"] == lab) & (sl["era"] == era)]["short_leg_ann"].sum()
                d = tables["benefit"]
                dd = d[(d["set"] == lab) & (d["era"] == era) & (d["without"] == "skip " + "+".join(X))]["d_gross_ann"].iloc[0]
                print(f"  {lab:<9}{era:<15} sum of short legs {legs * 100:+.3f}   book difference {dd * 100:+.3f}")
        print()

        # ---------------------------------------------------------------- [4]
        print("=" * 110)
        print(f"[4] H2 TURNOVER MATCHING on the headline era ({HEADLINE}): pairs more than {MATCH_TOL:.0%} apart get a")
        print("    base book at a band width bisected on TURNOVER ALONE to the without-book's turnover (never on P&L).")
        print("=" * 110)
        a, b = [(e[1], e[2]) for e in ERAS if e[0] == HEADLINE][0]
        rows = []
        for lab, bk in books.items():
            res = bk["res"]
            base = res["base (all lendable)"]
            tb = base["turn"].loc[a:b].mean() * 252
            for cl, *_ in configs[1:]:
                tw = res[cl]["turn"].loc[a:b].mean() * 252
                gap = tw / tb - 1
                if abs(gap) <= MATCH_TOL:
                    print(f"  {lab:<9}{cl:<26} turnover {tw:6.2f} vs base {tb:6.2f} (gap {gap:+.1%}): matched as it stands")
                    rows.append(dict(set=lab, without=cl, matched=True, width=BAND_WIDTH, d_gross_ann=np.nan))
                    continue
                f = lambda w: bf.evaluate(bf.band_gross_capped(bk["T"], w, cap), bk["Rtr"])["turn_series"].loc[a:b].mean() * 252
                lo, hi = BAND_WIDTH / 8, BAND_WIDTH * 8
                if not (f(hi) <= tw <= f(lo)):
                    print(f"  {lab:<9}{cl:<26} turnover {tw:.2f} outside the bracket; NOT matched")
                    rows.append(dict(set=lab, without=cl, matched=False, width=np.nan, d_gross_ann=np.nan))
                    continue
                for _ in range(30):
                    mid = 0.5 * (lo + hi)
                    lo, hi = (mid, hi) if f(mid) > tw else (lo, mid)
                w = 0.5 * (lo + hi)
                Hm = bf.band_gross_capped(bk["T"], w, cap)
                evm = bf.evaluate(Hm, bk["Rtr"])
                tm = evm["turn_series"].loc[a:b].mean() * 252
                d = (evm["pnl"] - res[cl]["pnl"]).loc[a:b]
                g = d.mean() * 252
                grid = [g - (tm - tw) * c / 1e4 for c in COSTS]
                print(f"  {lab:<9}{cl:<26} turnover {tw:6.2f} vs base {tb:6.2f} (gap {gap:+.1%}) -> base at width "
                      f"{w:.4f} turns {tm:6.2f}: d gross {g * 100:+.3f}%/yr (NW t {nw_t(d):.2f}); "
                      f"d@5/15/30 " + "/".join(f"{v * 100:+.3f}" for v in grid))
                rows.append(dict(set=lab, without=cl, matched=True, width=w, matched_turn=tm, d_gross_ann=g,
                                 d_nw_t=nw_t(d), d_net5=grid[0], d_net15=grid[1], d_net30=grid[2]))
        tables["turnover_matched"] = pd.DataFrame(rows)

        # ---------------------------------------------------------------- [5]
        print("\n" + "=" * 110)
        print("[5] BORROW SENSITIVITY: the base book's X shorts at IBKR's HISTORICAL daily FEE_RATE, the only")
        print("    pre-2023 fee record (data/cef/cef_borrow_history.parquet, cut at 2022-12-30), beside today's file fee")
        print("=" * 110)
        bh = pd.read_parquet(LIVE_CEF / "cef_borrow_history.parquet")
        bh["date"] = pd.to_datetime(bh["date"])
        bh = bh[(bh.ticker.isin(X)) & (bh.date < bf.HOLDOUT_START)]
        fee_hist = bh.pivot_table(index="date", columns="ticker", values="fee_rate_pct").reindex(columns=X)
        w0, w1 = fee_hist.index.min(), fee_hist.index.max()
        print(f"  FEE_RATE panel for {X}, {w0.date()} .. {w1.date()} (pre-2023 part only)")
        rows = []
        for lab, bk in books.items():
            H = bk["res"]["base (all lendable)"]["H"]
            win = (H.index > w0) & (H.index <= w1)
            fh = fee_hist.reindex(H.index)
            bc = bf.borrow_charge(H[X].loc[win], fh.loc[win])
            bn = bf.borrow_charge(H[X].loc[win], pd.DataFrame({x: fee_now[x] for x in X}, index=H.index[win]))
            per = {}
            for x in X:
                per[x] = bf.borrow_charge(H[[x]].loc[win], fh[[x]].loc[win])["cost"].mean() * 252
            print(f"  {lab:<9} window {H.index[win][0].date()}..{H.index[win][-1].date()}: historical "
                  f"{bc['cost'].mean() * 252 * 100:.3f}%/yr (coverage {bc['covered_share']:.1%}) vs today's fee "
                  f"{bn['cost'].mean() * 252 * 100:.3f}%/yr; by name (historical): "
                  + ", ".join(f"{x} {v * 100:.3f}" for x, v in per.items()))
            med = fee_hist.median()
            rows.append(dict(set=lab, window_start=str(H.index[win][0].date()), window_end=str(H.index[win][-1].date()),
                             hist_borrow_ann=bc["cost"].mean() * 252, hist_coverage=bc["covered_share"],
                             todays_fee_borrow_ann=bn["cost"].mean() * 252,
                             **{f"median_fee_{x}": med[x] for x in X}))
        print("  median historical fee %/yr in that window: "
              + ", ".join(f"{x} {fee_hist[x].median():.2f}" for x in X))
        tables["borrow_sensitivity"] = pd.DataFrame(rows)

        # ---------------------------------------------------------------- [6]
        print("\n" + "=" * 110)
        print("[6] IBKR COMMISSIONS AT OUR TICKET SIZES (base book, IBKR-routed trades only, CAPITAL_USD, broker marks)")
        print("=" * 110)
        rows = []
        for lab, bk in books.items():
            H = bk["res"]["base (all lendable)"]["H"]
            tr = ibkr_routed_trades(H[X]).loc["2013-06-01":"2022-12-31"]
            yrs = len(tr) / 252
            for x in X:
                n = tr[x][tr[x] > 0] * CAPITAL_USD
                c = ibkr_fixed_commission(n.to_numpy(), marks[x][0])
                bp = (c / n.to_numpy() * 1e4) if len(n) else np.array([np.nan])
                r = dict(set=lab, name=x, orders_per_yr=len(n) / yrs,
                         median_ticket_usd=float(n.median()) if len(n) else np.nan,
                         median_bp=float(np.median(bp)), usd_per_yr=float(c.sum()) / yrs,
                         min_binds_share=float((c <= IBKR_MIN + 1e-12).mean()) if len(n) else np.nan)
                rows.append(r)
                print(f"  {lab:<9}{x:<5} {r['orders_per_yr']:6.1f} IBKR orders/yr, median ticket "
                      f"${r['median_ticket_usd']:,.0f}, median {r['median_bp']:.1f}bp, ${r['usd_per_yr']:,.0f}/yr, "
                      f"the USD 1 minimum binds on {r['min_binds_share']:.0%}")
        tables["commissions"] = pd.DataFrame(rows)

        # ---------------------------------------------------------------- [7]
        print("\n" + "=" * 110)
        print("[7] SYNTHETIC BLOCKING: does the benefit scale like f x benefit(f=1)? (all X together, live skip rule)")
        print("    Flags are random blocks of L sessions blocked with probability f, per name; 10 seeds. A claim about")
        print("    the POLICY, never about Alpaca. ratio = benefit(f, L) / (f x benefit(1)), headline era.")
        print("=" * 110)
        rows = []
        for lab, bk in books.items():
            res = bk["res"]
            base = res["base (all lendable)"]
            full = (base["pnl"] - res["skip " + "+".join(X)]["pnl"]).loc[a:b].mean() * 252
            for f_ in EPISODE_F:
                for L in EPISODE_L:
                    v = []
                    for seed in EPISODE_SEEDS:
                        rng = np.random.default_rng(seed)
                        blk = block_flags(bk["T"].index, X, f_, L, rng)
                        H = bf.band_gross_capped(bk["T"], BAND_WIDTH, cap, unshortable=blk)
                        v.append((base["pnl"] - bf.evaluate(H, bk["Rtr"])["pnl"]).loc[a:b].mean() * 252)
                    v = np.array(v)
                    ratio = v / (f_ * full) if full != 0 else np.full_like(v, np.nan)
                    rows.append(dict(set=lab, f=f_, L=L, benefit_mean=v.mean(), benefit_min=v.min(),
                                     benefit_max=v.max(), benefit_full=full, ratio_mean=ratio.mean(),
                                     ratio_min=ratio.min(), ratio_max=ratio.max()))
                    print(f"  {lab:<9} f={f_:.2f} L={L:>2}: benefit {v.mean() * 100:+.3f}%/yr "
                          f"[{v.min() * 100:+.3f}, {v.max() * 100:+.3f}] vs f x full {f_ * full * 100:+.3f}; "
                          f"ratio {ratio.mean():.2f} [{ratio.min():.2f}, {ratio.max():.2f}]")
        tables["episodes"] = pd.DataFrame(rows)

    if not args.no_write:
        OUT.mkdir(parents=True, exist_ok=True)
        for k, v in tables.items():
            v.to_csv(OUT / f"{k}.csv", index=False, float_format="%.6g")
        print(f"\nwrote {', '.join(sorted(tables))} to {OUT.relative_to(REPO)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
