"""Validation battery for the CEF discount sleeve, before any capital moves.

Four things are tested here, in the order they could kill the strategy:

1. POINT-IN-TIME UNIVERSE. Every result so far selected 18 funds using TODAY's
   average daily volume. That is look-ahead twice over: it picks funds that still
   exist in 2026, and it picks ones that grew liquid. The universe is rebuilt here
   so that on each date it contains only funds that were ALREADY trading and
   ALREADY liquid on that date. If the edge is an artifact of hindsight in the
   universe, it dies at this step.

2. PURGED, EMBARGOED WALK-FORWARD. Fit nothing, but evaluate out-of-sample in
   sequential blocks with a gap between train and test so that overlapping
   holding periods cannot leak across the boundary. The embargo is EMBARGO_BD
   sessions dropped from each end of every block.

3. BLOCK BOOTSTRAP. Resample in contiguous blocks to preserve autocorrelation and
   volatility clustering, and report where zero sits in the Sharpe distribution.
   An i.i.d. bootstrap would overstate significance on a serially-dependent series.

4. DEFLATED SHARPE. Haircut for the number of specifications actually tried on
   this data source -- passed as --trials, never defaulted. See N_SPECS_TRIED.

EXECUTION CONVENTION. Everything below is scored at shift(2): decide at t, MOC
fill at t+1's close, earn the t+2 return. See EXEC_LAG. This file scored shift(1)
from the day it was written until 2026-09-10, which is an unobtainable entry
price -- the signal needs t's NAV and the fund publishes that after t's close.

WHERE THE RESULTS GO. This script PRINTS sections 1-4 and persists only
cef_validated_daily.parquet, so until 2026-09-10 no run of this battery had ever
left a record: every walk-forward and deflated-Sharpe figure in the repo existed
as prose transcribed by hand into a document, which is how "9/9 blocks positive"
outlived its own reproduction in five files. The correcting run is stored, with
all three measurements verbatim and the band_frontier control beside it:

    results/cef/EXECUTION_CONVENTION_2026-09-10.md    the record and what it means
    results/cef/runs/validate_2026-09-10_*.txt        raw stdout, A/B/C
    results/cef/runs/band_frontier_2026-09-10_*.txt   the untouched control

If you re-run this battery and the numbers move, ADD a dated file there rather
than editing that one -- it records what was measured on its date, the way
ops/specs/*.frozen.json records what was believed on its.

WHAT THIS SCRIPT DOES NOT MEASURE. HOLD = 5 below: this is a 5-day-hold CALENDAR
sleeve, RETIRED 2026-09-06. The deployed policy is band 4.8% and it is scored by
band_frontier.py, not here. The band has never been walk-forwarded, bootstrapped
or deflated by anything. Do not quote a number from this file as the live book's.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.strategies.credit_rv.costs import SCENARIOS  # noqa: E402
from src.backtest.guard import LookaheadError  # noqa: E402

OUT = REPO / "results/cef"
CM = SCENARIOS["base"]
WIN, HOLD, MIN_ADV = 252, 5, 3.0e6

# EXECUTION LAG. Decide at t, MOC fill at t+1's close, earn the t+2 return.
# This is harness rule H1 and it is not a tuning knob -- _assert_exec_lag()
# refuses to run at any other value. The canonical implementation is
# band_frontier.evaluate(), which applies H.shift(2); anything scored
# differently is not comparable to any other number in this repo.
EXEC_LAG = 2

# Sessions dropped from each end of every walk-forward block. A position is held
# up to HOLD sessions, so without a gap the last trade of one block is still open
# inside the next one and the blocks are not independent. Section 2's header has
# claimed this embargo since the file was written; until 2026-09-10 it was a
# claim in a print() and nothing in the code applied it.
EMBARGO_BD = HOLD

# The deflated-Sharpe haircut needs the number of specs tried on THIS source, and
# there is no safe default for it -- so there isn't one. Pass --trials.
#
# WHY THIS IS NOT A LITERAL ANY MORE. It was `N_SPECS_TRIED = 10` from the day
# this script was written. The CEF counter reached 48 (docs/RESEARCH_STATE.md's
# counter table, which CLAUDE.md declares canonical), and nothing connected the
# two, so section 4 kept haircutting for ten trials and printing PASS. Measured
# 2026-09-10 on T=5,455 days, observed net Sharpe 0.832, varying only N:
#
#     N=10  (the old literal)   bar sqrt(2lnN) 2.146   DSR 0.963   PASS
#     N=48  (the CEF counter)   bar            2.783   DSR 0.870   FAIL
#     N=162 (LEGACY, for scale) bar            3.190   DSR 0.760   FAIL
#
# The verdict does not merely weaken at the true count, it FLIPS -- straight
# through MARGINAL. So the single most optimistic number this script printed was
# an artifact of a stale constant, on the project's headline validation. That is
# the `fee.fillna(fee.median())` failure mode exactly: a confident-looking total
# with an invented input, dormant for months.
#
# A default would reintroduce it silently the next time the counter moves, which
# is why this RAISES instead (CLAUDE.md: NO SILENT FALLBACKS -- raise, naming what
# was missing). The caller must state the count and therefore has to go and look
# it up. Reading RESEARCH_STATE.md from here would be worse, not better: rule H14
# says no decision rule may key on a number written in a document, and the
# deflated-Sharpe bar is a decision rule.
N_SPECS_TRIED = None    # set from --trials; see above. Never give this a default.


def load_raw():
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet")
    d = P.merge(N, on=["date", "ticker"], how="inner")
    d = d[(d.nav > 0.5) & (d.close > 0.5)].sort_values(["ticker", "date"])
    px = d.pivot_table(index="date", columns="ticker", values="close")
    nav = d.pivot_table(index="date", columns="ticker", values="nav")
    vol = d.pivot_table(index="date", columns="ticker", values="volume")
    return px, nav, vol


def signals(px, nav, vol):
    disc = 100.0 * (px - nav) / nav
    mu = disc.rolling(WIN, min_periods=120).mean().shift(1)
    sd = disc.rolling(WIN, min_periods=120).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    adv = (px * vol).rolling(63, min_periods=21).mean().shift(1)
    return disc, z, adv


def _assert_exec_lag(W, held):
    """Refuse to score unless `held` is `W` lagged by exactly EXEC_LAG sessions.

    WHY THIS IS NOT src/backtest/guard.py::assert_lagged. That guard encodes the
    Phase-2 engine's T+1 rule: it checks info_dates[t] <= t, which shift(1)
    satisfies just as well as shift(2). It is structurally unable to see this
    defect, because this defect IS T+1 -- the signal needs t's NAV, the fund
    publishes it after t's close, so entering at t's close buys at a price that
    did not exist. Reusing that guard here would have printed a green check over
    the exact bug it was meant to catch, which is worse than no guard.

    WHY A RUNTIME CHECK AND NOT A COMMENT. There was already a comment. From
    2026-07-31 this file scored shift(1) while every other number in the repo was
    scored shift(2); docs/RESEARCH_STATE.md named the line and measured the cost
    (gross 1.26 -> 0.95, net at hold=5 0.82 -> 0.51) and the line survived
    unchanged through a 2026-09-10 commit that edited the file for another reason.
    The positional probe below fires if anyone edits EXEC_LAG or the .shift() and
    not both.
    """
    if EXEC_LAG != 2:
        raise LookaheadError(
            f"EXEC_LAG is {EXEC_LAG}, must be 2. H1: decide at t, MOC fill at "
            f"t+1's close, earn the t+2 return. The signal needs t's NAV, which "
            f"publishes after t's close, so shift(1) prices an unreachable fill "
            f"and shift(0) is pure lookahead. This is not a tuning knob.")
    if not held.index.equals(W.index):
        raise ValueError("held and W must share an index exactly")
    if len(W) <= EXEC_LAG:
        raise ValueError(f"need more than {EXEC_LAG} rows to verify the lag, "
                         f"got {len(W)}")
    # Probe positionally: held at index[k] must be the weights decided at
    # index[k - EXEC_LAG]. Checks the offset against the index, so a resample or
    # a reindex that silently changes the spacing is caught too.
    for k in (EXEC_LAG, len(W) // 2, len(W) - 1):
        got = held.iloc[k].to_numpy(dtype=float)
        want = W.iloc[k - EXEC_LAG].to_numpy(dtype=float)
        if not np.allclose(got, want, rtol=0, atol=0, equal_nan=True):
            raise LookaheadError(
                f"row {W.index[k].date()} holds weights that are not the ones "
                f"decided {EXEC_LAG} sessions earlier on "
                f"{W.index[k - EXEC_LAG].date()}. The execution lag is wrong.")


def run(px, z, adv, vol_target=0.06, start="2005-01-01"):
    """PIT universe: a fund is eligible on date t only if it is trading and
    liquid AS OF t. No knowledge of which funds survive to 2026."""
    idx = px.index[px.index >= start]
    z, px, adv = z.reindex(idx), px.reindex(idx), adv.reindex(idx)
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    eligible = adv.fillna(0.0) >= MIN_ADV           # <- evaluated per date

    W = pd.DataFrame(0.0, index=idx, columns=px.columns)
    for t in idx[::HOLD]:
        row = z.loc[t][eligible.loc[t]].dropna()
        if len(row) < 6:
            continue
        v = -(row - row.mean())
        if v.abs().sum() < 1e-9:
            continue
        W.loc[t, v.index] = (v / v.abs().sum()).values
    W = W.replace(0.0, np.nan).ffill(limit=HOLD - 1).fillna(0.0)

    if vol_target:
        # ALIGNMENT. W.loc[t] is the weight DECIDED at t, from t's close and t's
        # NAV -- which the fund publishes only AFTER that close. The earliest
        # auction reachable is t+1's, so the position is held from t+1's close and
        # first earns the t+2 return: shift(EXEC_LAG), EXEC_LAG == 2.
        #
        # This pre-pass must use the SAME convention it is sizing for. Scoring the
        # vol scalar on a shift(1) stream while trading shift(2) sizes the book
        # against a return series that was never earned.
        raw = (W.shift(EXEC_LAG).fillna(0.0) * ret).sum(axis=1)
        # rv at row t uses raw only through t-1, so the scalar applied to the
        # decision made at t is computable at t. This shift(1) is CORRECT and is a
        # different thing from the execution lag above -- do not "fix" it to match.
        rv = raw.shift(1).rolling(63, min_periods=30).std() * np.sqrt(252)
        W = W.mul((vol_target / rv.replace(0, np.nan)).clip(0.2, 2.5).fillna(1.0),
                  axis=0)

    held = W.shift(EXEC_LAG).fillna(0.0)
    _assert_exec_lag(W, held)
    gross = (held * ret).sum(axis=1)
    hs = pd.DataFrame(
        {c: [CM.half_spread_bp(p, a) for p, a in
             zip(px[c].values, adv[c].fillna(0).values)] for c in px.columns},
        index=idx)
    dw = held.diff().abs().fillna(held.abs())
    cost = (dw * hs / 1e4).sum(axis=1)
    n_uni = eligible.sum(axis=1)
    return pd.DataFrame({"gross": gross, "net": gross - cost, "cost": cost,
                         "turn": dw.sum(axis=1), "n_uni": n_uni},
                        index=idx).dropna()


def sr(s):
    return s.mean() / s.std() * np.sqrt(252) if len(s) > 30 and s.std() > 0 else np.nan


def _verdict(dsr):
    return "PASS" if dsr > 0.95 else "MARGINAL" if dsr > 0.90 else "FAIL"


def _dsr(obs, T, sk, ku, n_trials):
    """Deflated Sharpe (Bailey & Lopez de Prado) at a given trial count.

    Factored out of section 4 so the N-sensitivity can be COMPUTED and printed
    rather than pasted as literal text. Returns (dsr, sr0, e_max), where sr0 is
    the Sharpe a no-edge source is expected to produce as the best of n_trials
    and e_max is the sqrt(2 ln N) bar. The verdict is a function of n_trials, so
    it must never be quoted without it.
    """
    from math import erf
    e_max = np.sqrt(2 * np.log(n_trials))
    sr0 = e_max / np.sqrt(T / 252)                     # expected best-of-N under null
    denom = np.sqrt(1 - sk * obs / np.sqrt(252) +
                    (ku - 1) / 4 * (obs / np.sqrt(252)) ** 2)
    z = (obs - sr0) * np.sqrt(T - 1) / (np.sqrt(252) * max(denom, 1e-9))
    return 0.5 * (1 + erf(z / np.sqrt(2))), sr0, e_max


def main(argv=None) -> int:
    global N_SPECS_TRIED
    import argparse
    ap = argparse.ArgumentParser(
        description="Validate the CEF discount edge. --trials is REQUIRED: the "
                    "deflated-Sharpe haircut is meaningless without the real "
                    "number of specs tried on this source, and a default is how "
                    "this script came to print PASS for months at N=10 while the "
                    "CEF counter stood at 48.")
    ap.add_argument("--trials", type=int, required=True, metavar="N",
                    help="specs tried on THIS source. Read it off the counter "
                         "table in docs/RESEARCH_STATE.md (canonical); for the "
                         "CEF source that is the CEF row, not LEGACY.")
    a = ap.parse_args(argv)
    if a.trials < 1:
        raise ValueError(f"--trials must be >= 1, got {a.trials}; one spec tried "
                         f"is still one spec")
    N_SPECS_TRIED = a.trials

    px, nav, vol = load_raw()
    disc, z, adv = signals(px, nav, vol)
    print(f"raw universe {px.shape[1]} CEFs, {px.index.min().date()} -> "
          f"{px.index.max().date()}")

    d = run(px, z, adv)
    print(f"\n{'='*84}\n1. POINT-IN-TIME UNIVERSE (no hindsight on survival or liquidity)\n{'='*84}")
    print(f"  eligible funds per day: min {d.n_uni.min():.0f}  "
          f"median {d.n_uni.median():.0f}  max {d.n_uni.max():.0f}")
    print(f"  gross Sharpe {sr(d.gross):.2f}   net Sharpe {sr(d.net):.2f}   "
          f"vol {d.net.std()*np.sqrt(252)*100:.2f}%")
    eq = (1 + d.net).cumprod()
    print(f"  CAGR {100*(eq.iloc[-1]**(252/len(d))-1):.2f}%   "
          f"maxDD {100*(eq/eq.cummax()-1).min():.1f}%")
    print("  by era:")
    for lo, hi in [(2005, 2009), (2010, 2014), (2015, 2019), (2020, 2022), (2023, 2026)]:
        s = d[(d.index.year >= lo) & (d.index.year <= hi)]
        if len(s) < 200:
            continue
        print(f"    {lo}-{hi}: gross {sr(s.gross):>5.2f}  net {sr(s.net):>5.2f}  "
              f"universe {s.n_uni.mean():>4.1f} funds")

    # 2. purged, embargoed walk-forward
    #
    # THE EMBARGO IS APPLIED HERE, not merely announced in the header. A position
    # is held up to HOLD sessions, so the last trades of one block are still open
    # inside the next; without a gap the blocks share P&L and are not independent.
    # Until 2026-09-10 this section printed "5d embargo either side" over a bare
    # array_split whose blocks touched -- the header asserted a control the code
    # did not apply, which is the same defect class as a deflated Sharpe printed
    # without its trial count.
    print(f"\n{'='*84}\n2. PURGED WALK-FORWARD (10 blocks, {EMBARGO_BD}d embargo either side)\n{'='*84}")
    blocks = np.array_split(d.index, 10)
    rows = []
    for i, b in enumerate(blocks):
        # Drop EMBARGO_BD sessions from each end. Interior ends only: nothing
        # precedes the first block and nothing follows the last, so trimming
        # those outer edges would discard live data to guard a boundary that
        # does not exist.
        lo = EMBARGO_BD if i > 0 else 0
        hi = len(b) - EMBARGO_BD if i < len(blocks) - 1 else len(b)
        b = b[lo:hi]
        s = d.net.loc[b]
        if len(s) < 100:
            continue
        v = sr(s)
        if np.isfinite(v):
            rows.append((f"{b[0].date()}..{b[-1].date()}", len(s), v))
    for lab, n, v in rows:
        bar = "+" * max(0, int(v * 10)) if v > 0 else "-" * max(0, int(-v * 10))
        print(f"  {lab:<26}{n:>6}{v:>8.2f}  {bar}")
    vals = np.array([v for _, _, v in rows])
    print(f"  {int((vals > 0).sum())}/{len(vals)} blocks positive, "
          f"median {np.median(vals):.2f}, worst {vals.min():.2f}")

    # 3. block bootstrap
    print(f"\n{'='*84}\n3. BLOCK BOOTSTRAP (5,000 draws, 21-day blocks)\n{'='*84}")
    r = d.net.values
    rng = np.random.default_rng(20260731)
    bl, nb = 21, int(np.ceil(len(r) / 21))
    boot = []
    for _ in range(5000):
        st = rng.integers(0, len(r) - bl, nb)
        samp = np.concatenate([r[s0:s0 + bl] for s0 in st])[:len(r)]
        boot.append(samp.mean() / samp.std() * np.sqrt(252))
    boot = np.array(boot)
    print(f"  observed net Sharpe   {sr(d.net):.2f}")
    print(f"  bootstrap mean        {boot.mean():.2f}")
    print(f"  5th / 95th pct        {np.percentile(boot,5):.2f} / {np.percentile(boot,95):.2f}")
    print(f"  P(Sharpe <= 0)        {(boot <= 0).mean():.3%}")

    # 4. deflated Sharpe
    print(f"\n{'='*84}\n4. DEFLATED SHARPE (haircut for {N_SPECS_TRIED} specs tried on this source)\n{'='*84}")
    T = len(d)
    obs = sr(d.net)
    sk = pd.Series(r).skew(); ku = pd.Series(r).kurt() + 3.0
    dsr, sr0, e_max = _dsr(obs, T, sk, ku, N_SPECS_TRIED)
    print(f"  observed Sharpe {obs:.2f}   null best-of-{N_SPECS_TRIED} {sr0:.2f}   "
          f"skew {sk:+.2f}  kurt {ku:.1f}")
    if obs < sr0:
        print(f"  ^ the observed Sharpe is BELOW the best-of-{N_SPECS_TRIED} null. "
              f"On this many trials a no-edge source is expected to throw up a "
              f"{sr0:.2f}; we measured {obs:.2f}.")
    print(f"  trials N = {N_SPECS_TRIED} (from --trials)   "
          f"deflated-Sharpe bar sqrt(2 ln N) = {e_max:.3f}")
    print(f"  DEFLATED SHARPE RATIO (prob the edge is real): {dsr:.3f}   "
          f"{_verdict(dsr)}")
    # The verdict is a function of N, and N is a governance fact that moves. Print
    # the sensitivity COMPUTED, never as a literal: this footer used to carry
    # "at N=10 ... 0.963 PASS, at N=48 ... 0.870 FAIL" as hardcoded text, and those
    # two numbers silently stopped describing this series the moment the execution
    # convention was corrected on 2026-09-10. A stale number in an output is worse
    # than one in a document, because it wears the authority of a fresh run.
    print(f"  ^ this verdict is AT N={N_SPECS_TRIED}. It is not a property of the "
          f"edge alone. The same series at other counts:")
    for n in sorted({10, 48, 49, 162, N_SPECS_TRIED}):
        d_n, _, bar_n = _dsr(obs, T, sk, ku, n)
        mark = "  <- as run" if n == N_SPECS_TRIED else ""
        print(f"      N={n:<5} bar {bar_n:.3f}   DSR {d_n:.3f}   "
              f"{_verdict(d_n)}{mark}")
    print(f"  Quote N whenever you quote the verdict.")
    d.to_parquet(OUT / "cef_validated_daily.parquet")
    print(f"\nwrote {OUT/'cef_validated_daily.parquet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
