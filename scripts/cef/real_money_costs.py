"""Plan item 0.5 -- THE GATE: the deployed book net of measured real-money costs.

    python3 scripts/cef/real_money_costs.py                        # offline sections only
    python3 scripts/cef/real_money_costs.py --refresh-snapshots    # + today's IBKR fee file, Alpaca flags
    python3 scripts/cef/real_money_costs.py --state ~/quantt_state/cef --state <VM state copy>
                                                                   # + the execution section

`--refresh-snapshots` and `--state` need QUANTT_ENV_FILE naming the key file. Every
call they make is READ-ONLY: Alpaca market data (closing-auction prints, SIP
quotes), asset flags, and the account's fill activities (a second read of fills
the records already hold). Nothing is sent, cancelled or changed.

Item 0.5 of results/cef/RESEARCH_PLAN_2026-10-09.md: "If the live book is not
positive net after measured costs, real capital waits, and C1/C2 come before any
new sleeve." The write-up is results/cef/REAL_MONEY_COSTS_2026-10-12.md; the run
behind it is results/cef/real_money_costs/real_money_costs_output.txt.

WHAT THIS IS
------------
Report only. ZERO trials: it tests no new signal or policy, chooses nothing, and
moves no counter. It scores the DEPLOYED policy -- `band_gross_capped(T,
BAND_WIDTH, MAX_GROSS_STRESS)` on the frozen spec's 13 names, all read through
`scripts/cef/spec.py` -- exactly as W4 did, then subtracts the costs a real
account pays and the paper account does not:

  1. distributions: total returns (`total_returns()`), so a short PAYS its
     distribution and a long receives it, as at a real broker;
  2. borrow: `borrow_charge()` (band_frontier.py, added for this item) on the
     short book `evaluate()` holds, under every borrow proxy the data supports,
     each labelled -- none is picked silently;
  3. execution: the measured paper-fill vs official-auction-print slippage,
     split into the half-spread paid and the drift to the print, from the
     broker-confirmed sessions; plus the regulatory fees a live Alpaca account
     pays; plus the 5/15/30bp grid, labelled, beside the gross headline.

There is one book and one turnover path, so every comparison is turnover-matched
by construction (H2): only the cost assumption changes between rows.

HOLDOUT (H13)
-------------
Every RETURN statistic stops at 2022-12-30: T and R are truncated by `fit_only`
before the policy runs, and `_assert_fit` checks each frame that reaches a
statistic. Borrow FEES after 2022 are read as cost inputs (the per-name level
of a proxy schedule, and a description of the fee history); no 2023+ position,
P&L or return is computed. The 27 untouched names are not read.

NO SILENT FALLBACKS
-------------------
A missing fee is a gap, reported with its share of the short book, never a zero.
A fill with no SIP quote in the minute before it is reported unmeasured. An
absent snapshot cache prints UNMEASURED for the proxies that need it. The
execution section does not run without records; the net table then shows only
the columns it can measure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.cef.band_frontier import (  # noqa: E402
    BORROW_COLLATERAL_MARKUP, BORROW_DAY_COUNT, HOLDOUT_START, band_gross_capped,
    borrow_charge, build_panel, build_targets, distribution_yield, evaluate,
    fit_only, total_returns,
)
from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS, UNIVERSE, summary  # noqa: E402
from scripts.cef.w4_artifacts import _assert_fit, block_boot_t, nw_t  # noqa: E402

CACHE = REPO / "results" / "cef" / "real_money_costs" / "_cache_rmc"   # gitignored
PROBE_DIR = REPO / "results" / "ops" / "alpaca_probe"
FIT_END = "2022-12-30"                     # last session before the sealed holdout
assert pd.Timestamp(FIT_END) < HOLDOUT_START
ERAS = [("2005-09", "2005-01-01", "2009-12-31"), ("2010-14", "2010-01-01", "2014-12-31"),
        ("2015-19", "2015-01-01", "2019-12-31"), ("2020-22", "2020-01-01", "2022-12-31"),
        ("fit 2005-22", "2005-01-01", "2022-12-31")]
COSTS = (5, 15, 30)
RECENT = 63            # "today's fee": the last quarter (63 sessions) of the fee history
QUOTE_LOOKBACK_S = 60  # the NBBO a paper fill is decomposed against: last quote <= 60s before it

# Alpaca brokerage fee schedule, revised 2026-10-01 (docs/REFERENCES.md §12g [V]).
# Pass-through regulatory fees on equities; commissions are $0 for this account type.
SEC_FEE_PER_DOLLAR_SOLD = 0.0000206     # SEC transaction fee, sells only
CAT_FEE_PER_SHARE = 0.000003            # FINRA CAT, buys and sells
TAF_PER_SHARE_SOLD = 0.0                # FINRA TAF, sells: "$0 per share"


def hr(title: str) -> None:
    print("\n" + "=" * 100 + f"\n{title}\n" + "=" * 100)


# --------------------------------------------------------------------------- §0 panels

def panel_dates() -> dict:
    out = {}
    for name, col in (("cef_prices.parquet", "date"), ("cef_nav.parquet", "date"),
                      ("cef_distributions.parquet", "ex_date"),
                      ("cef_borrow_history.parquet", "date")):
        d = pd.read_parquet(REPO / "data/cef" / name, columns=[col])
        out[name] = (pd.to_datetime(d[col]).min().date(), pd.to_datetime(d[col]).max().date())
    b = pd.read_csv(REPO / "data/cef/cef_borrow.csv", parse_dates=["date"])
    out["cef_borrow.csv"] = (b.date.min().date(), b.date.max().date())
    return out


# --------------------------------------------------------------------------- §1 the book

class Book:
    """The deployed v7 book on the fit period, scored only through evaluate()."""

    def __init__(self):
        T, R_px = build_targets()
        T, R_px = fit_only(T, R_px)            # truncate BEFORE the policy runs (H13)
        self.T, self.R_px = T, R_px
        self.R_tr = total_returns(R_px)
        cap = MAX_GROSS_STRESS if MAX_GROSS_STRESS is not None else np.inf
        self.H = band_gross_capped(T, BAND_WIDTH, cap)
        _assert_fit(self.T, self.R_px, self.R_tr, self.H)
        self.tr = evaluate(self.H, self.R_tr)
        self.px = evaluate(self.H, self.R_px)
        self.pnl, self.turn = self.tr["pnl"], self.tr["turn_series"]
        self.live0 = self.pnl.index[self.pnl.ne(0)].min()
        held = self.H.shift(2).fillna(0.0)     # the book evaluate() earns on
        self.short_held = (-held).clip(lower=0).sum(axis=1)
        self.gross_held = held.abs().sum(axis=1)
        y = distribution_yield(self.R_px.index, self.R_px.columns).reindex_like(self.R_px)
        self.dist_long = (held.clip(lower=0) * y).sum(axis=1)     # received on longs
        self.dist_short = (held.clip(upper=0) * y).sum(axis=1)    # paid on shorts (<= 0)
        # sell share of turnover: what the SEC fee (sells only) applies to
        dH = self.H.diff().fillna(0.0)
        self.sell_share = float((-dH.clip(upper=0)).sum().sum() / dH.abs().sum().sum())

    def windows(self, measured_start):
        w = [(lab, a, b) for lab, a, b in ERAS]
        w += [("live 2013-06..2014", self.live0, "2014-12-31"),
              ("live fit 2013-06..2022", self.live0, FIT_END),
              ("measured-borrow window", measured_start, FIT_END)]
        return w


def stats(x: pd.Series) -> dict:
    ann, vol = x.mean() * 252, x.std() * np.sqrt(252)
    return dict(ann=ann, vol=vol, sr=ann / vol if vol > 0 else np.nan)


def sec_book(B: Book, wins) -> None:
    hr("§1 THE DEPLOYED BOOK: gross headline, total vs price returns, the distribution leg")
    print(summary())
    print(f"fit period {B.T.index[0].date()} .. {B.T.index[-1].date()} ({len(B.T)} sessions); "
          f"first position (live0) {B.live0.date()}; 2023+ is the sealed H13 holdout and is "
          "not computed.")
    print("Reproduces W4 (results/cef/W4_ARTIFACTS_2026-10-11.md, §1) when the fit and "
          "'live fit' rows read gross SR 0.69/0.96 on total returns.\n")
    print(f"{'window':<26}{'grossSR':>8}{'pxSR':>7}{'ann%':>7}{'vol%':>7}{'turn/yr':>8}"
          f"{'dist%/yr':>9}{'long+':>7}{'short-':>7}{'avgShort':>9}{'avgGross':>9}")
    eras_turn = []
    for lab, a, b in wins:
        p = B.pnl.loc[a:b]
        if p.abs().sum() == 0:
            print(f"{lab:<26}{'book flat: no position in this window':>50}")
            continue
        s, sp = stats(p), stats(B.px["pnl"].loc[a:b])
        t = B.turn.loc[a:b].mean() * 252
        dl = (B.pnl - B.px["pnl"]).loc[a:b].mean() * 252
        print(f"{lab:<26}{s['sr']:8.2f}{sp['sr']:7.2f}{s['ann'] * 100:7.2f}{s['vol'] * 100:7.2f}"
              f"{t:8.1f}{dl * 100:9.2f}{B.dist_long.loc[a:b].mean() * 252 * 100:7.2f}"
              f"{B.dist_short.loc[a:b].mean() * 252 * 100:7.2f}"
              f"{B.short_held.loc[a:b].mean():9.3f}{B.gross_held.loc[a:b].mean():9.3f}")
        if lab in ("live 2013-06..2014", "2015-19", "2020-22"):
            eras_turn.append(t)
    et = np.array(eras_turn)
    print(f"\nera turnover sd/mean (live 2013-06..2014, 2015-19, 2020-22): {et.std() / et.mean():.1%}")
    print("dist%/yr = total-return P&L minus price-return P&L on the same holdings; long+ is "
          "the yield received on longs, short- the yield paid on shorts (D/P_{t-1} on ex-dates).")


# --------------------------------------------------------------------------- §2 borrow inputs

def fee_history() -> pd.DataFrame:
    b = pd.read_parquet(REPO / "data/cef/cef_borrow_history.parquet")
    b["date"] = pd.to_datetime(b["date"])
    missing = sorted(set(UNIVERSE) - set(b.ticker))
    if missing:
        raise ValueError(f"cef_borrow_history.parquet has no fee series for {missing}")
    return b.pivot(index="date", columns="ticker", values="fee_rate_pct")[list(UNIVERSE)]


def newest(pattern: str) -> Path | None:
    c = sorted(CACHE.glob(pattern))
    return c[-1] if c else None


def ibkr_file_snapshot() -> tuple[pd.DataFrame | None, str]:
    p = newest("ibkr_shortstock_*.csv")
    if p is None:
        return None, "UNMEASURED: no cached IBKR shortstock snapshot (run --refresh-snapshots)"
    d = pd.read_csv(p).set_index("symbol")
    return d, p.name


def alpaca_flags() -> list[tuple[str, dict]]:
    """(label, {symbol: borrow_status}) from the committed probe snapshots and any
    fresh read cached by --refresh-snapshots. Each is true on its date only."""
    out = []
    for p in sorted(PROBE_DIR.glob("*_cef.json")):
        a = json.loads(p.read_text()).get("assets") or {}
        out.append((f"probe {p.name[:10]}", {s: v.get("borrow_status") for s, v in a.items()
                                            if isinstance(v, dict)}))
    for p in sorted(CACHE.glob("alpaca_assets_*.json")):
        a = json.loads(p.read_text())
        out.append((f"read {a['read_at_utc'][:10]}", {s: v["borrow_status"]
                                                    for s, v in a["assets"].items()}))
    return sorted(out, key=lambda x: x[0].split()[-1])     # oldest first, newest last


def sec_borrow_inputs(F: pd.DataFrame) -> None:
    hr("§2 BORROW INPUTS: what is measured, where, and to when")
    first, last = F.index.min().date(), F.index.max().date()
    print(f"data/cef/cef_borrow_history.parquet: IBKR TWS reqHistoricalData(whatToShow="
          f"'FEE_RATE', 1 day), built by the deleted fetch_borrow_history.py (tag "
          f"pre-clean-slate). Deployed names {len(F.columns)}/13; {first} .. {last}.")
    fit = F.loc[:FIT_END]
    rec = F.tail(RECENT)
    print(f"Fit-period part: {fit.index.min().date()} .. {fit.index.max().date()} "
          f"({len(fit)} dates). Recent = the last {RECENT} dates: {rec.index.min().date()} .. "
          f"{rec.index.max().date()}.\n")
    print(f"{'name':<6}{'n fit':>6}{'fit mean':>9}{'fit med':>9}{'all mean':>9}{'all med':>9}"
          f"{'rec mean':>9}{'rec med':>9}{'max':>8}")
    for c in F.columns:
        print(f"{c:<6}{fit[c].notna().sum():6d}{fit[c].mean():9.2f}{fit[c].median():9.2f}"
              f"{F[c].mean():9.2f}{F[c].median():9.2f}{rec[c].mean():9.2f}{rec[c].median():9.2f}"
              f"{F[c].max():8.2f}")
    print("\nCross-name mean fee (%/yr, unweighted, IBKR FEE_RATE) by calendar year -- a "
          "description of the input, not a holdings-weighted cost:")
    yr = F.groupby(F.index.year).mean().mean(axis=1)
    print("  " + "  ".join(f"{y}: {v:5.2f}" for y, v in yr.items()))

    c = pd.read_csv(REPO / "data/cef/cef_borrow.csv", parse_dates=["date"])
    full = c[c.rebate_rate_pct.notna()]
    print(f"\ndata/cef/cef_borrow.csv: {c.date.min().date()} .. {c.date.max().date()}, "
          f"{c.ticker.nunique()} names. Rows with rebate/availability "
          f"({sorted(full.date.dt.date.astype(str).unique())}) are IBKR's public shortstock "
          "file (the deleted fetch_borrow_rates.py); fee-only rows have no recorded source.")
    hist = F.stack().rename("h").reset_index().rename(columns={"level_1": "ticker"})
    m = c.merge(hist, on=["date", "ticker"], how="inner")
    for day, g in m.groupby("date"):
        kind = "shortstock-file rows" if g.rebate_rate_pct.notna().all() else "fee-only rows"
        d = (g.fee_rate_pct - g.h).abs()
        print(f"  {day.date()} {kind:<21} vs FEE_RATE same date: max |diff| {d.max():.4f} "
              f"pct-pts on {len(g)} names")
    if full.date.nunique() > 1:
        a_, b_ = sorted(full.date.unique())[:2]
        same = (full[full.date == a_].set_index("ticker").fee_rate_pct
                .equals(full[full.date == b_].set_index("ticker").fee_rate_pct))
        print(f"  shortstock rows {pd.Timestamp(a_).date()} and {pd.Timestamp(b_).date()} are "
              f"{'IDENTICAL (the same file content read twice)' if same else 'different'}")
    # the shortstock file's 2026-09-06 snapshot (stamped 2026-09-04 23:46) vs FEE_RATE on 09-04
    snap = full[full.date == full.date.min()].set_index("ticker").fee_rate_pct
    prev = F.index[F.index < full.date.min()].max()
    common = [t for t in snap.index if t in F.columns]
    if len(common) and pd.notna(prev):
        d = (snap[common] - F.loc[prev, common]).abs()
        print(f"  shortstock rows of {full.date.min().date()} vs FEE_RATE of {prev.date()}, the "
              f"last FEE_RATE date before them: max |diff| {d.max():.4f} on "
              f"{len(common)} names -- the scale check (percent per year)")

    snapf, lab = ibkr_file_snapshot()
    print(f"\nIBKR public shortstock file, today: {lab}")
    if snapf is not None:
        print(f"  {'name':<6}{'fee%':>8}{'rebate%':>9}{'available':>12}")
        for s in UNIVERSE:
            r = snapf.loc[s] if s in snapf.index else None
            print(f"  {s:<6}" + ("   not in file" if r is None else
                                 f"{r.fee_rate_pct:8.2f}{r.rebate_rate_pct:9.2f}{r.available:12,.0f}"))
    flags = alpaca_flags()
    print("\nAlpaca borrow_status (asset flags; true on their date only):")
    names = sorted(set().union(*[set(f) for _, f in flags])) if flags else []
    print(f"  {'name':<6}" + "".join(f"{lab:>18}" for lab, _ in flags))
    for s in names:
        print(f"  {s:<6}" + "".join(f"{(f.get(s) or '-'):>18}" for _, f in flags))
    # cross-tab: Alpaca flag on the first probe vs the IBKR fee on the last cef_borrow.csv date before it
    if flags:
        lab0, f0 = flags[0]
        d0 = pd.Timestamp(lab0.split()[-1])
        last_c = c[c.date < d0].date.max()
        fee0 = c[c.date == last_c].set_index("ticker").fee_rate_pct
        print(f"\n  {lab0} flag vs IBKR fee on {last_c.date()} (cef_borrow.csv):")
        for st in ("easy_to_borrow", "hard_to_borrow"):
            nm = [s for s, v in f0.items() if v == st and s in fee0.index]
            if nm:
                v = fee0[nm]
                print(f"    {st:<15} {len(nm):2d} names, IBKR fee {v.min():.2f} .. {v.max():.2f} "
                      f"(median {v.median():.2f})")


# --------------------------------------------------------------------------- §3 borrow proxies

def const_fee(index, values: dict) -> pd.DataFrame:
    return pd.DataFrame({k: float(v) for k, v in values.items()}, index=index)


MEASURED_ONLY = {"P0", "P0+"}     # defined only where the FEE_RATE history exists


def in_domain(key: str, window_label: str) -> bool:
    """P0/P0+ are measurements, so they are scored only on the window the history
    covers; every other proxy is a schedule and applies to every window."""
    return key not in MEASURED_ONLY or window_label == "measured-borrow window"


def proxies(B: Book, F: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame | None]]:
    """(key, label, fee frame) for every borrow proxy the data supports. None = UNMEASURED.

    WHY SEVERAL, AND WHY NONE IS PICKED. The fee is the input the gate turns on, and
    it is measured by name and date only from 2021-09-13 -- eight of the book's
    nine and a half live years have none. Each proxy answers a different question:

      P0   what the book paid where it was measured (the only measurement);
      P0+  the same, with the 1% of short name-days that lack a fee carried
           forward -- an assumption, shown so the reader can see it does not matter;
      P1   "what if 2021-22's fee level had held throughout";
      P2   the 2021-26 mean by name: the rule docs/BRIEF.md H4 prescribes for rows
           before the history starts, labelled there as an assumption;
      P3   today's level from the same history (its last RECENT dates);
      P3f  today's level from IBKR's public file, a second capture of IBKR data;
      P4   a live Alpaca account on today's flags: ETB is free (fee schedule), HTB
           is unpriced because Alpaca publishes no rate -- a gap, so P4 is a LOWER
           bound on cost and says so through its coverage;
      P4+  P4 with the HTB names at today's IBKR fee, a labelled stand-in;
      P5   zero, which is what the paper account scores.

    The gate is reported under every one. Choosing among them would be choosing
    the answer."""
    idx = B.H.index
    out = [("P0", "IBKR FEE_RATE by name-date [measured; window only]",
            F.reindex(columns=B.H.columns)),
           ("P0+", "P0 with gaps carried from the last measured fee [assumption]",
            F.reindex(columns=B.H.columns).reindex(F.index.union(idx)).ffill()
             .loc[F.index.min():]),
           ("P1", "const: name's FEE_RATE mean 2021-09..2022 [counterfactual]",
            const_fee(idx, F.loc[:FIT_END].mean().to_dict())),
           ("P2", "const: name's FEE_RATE mean 2021-09..2026-09 [counterfactual]",
            const_fee(idx, F.mean().to_dict())),
           ("P3", f"const: name's FEE_RATE mean, last {RECENT} dates [today, IBKR]",
            const_fee(idx, F.tail(RECENT).mean().to_dict()))]
    snapf, lab = ibkr_file_snapshot()
    out.append(("P3f", f"const: IBKR shortstock file today ({lab[16:26] if snapf is not None else '-'})",
                None if snapf is None else const_fee(idx, snapf.fee_rate_pct.reindex(UNIVERSE).to_dict())))
    flags = alpaca_flags()
    if flags:
        lab_a, fa = flags[-1]
        etb = {s: (0.0 if fa.get(s) == "easy_to_borrow" else np.nan) for s in UNIVERSE}
        out.append(("P4", f"Alpaca live, {lab_a} flags: ETB $0, HTB unpriced (gap)",
                    const_fee(idx, etb)))
        stand = (snapf.fee_rate_pct.reindex(UNIVERSE) if snapf is not None
                 else F.tail(RECENT).mean())
        out.append(("P4+", "P4 with HTB names at today's IBKR fee [stand-in, labelled]",
                    const_fee(idx, {s: (0.0 if fa.get(s) == "easy_to_borrow" else stand[s])
                                    for s in UNIVERSE})))
    else:
        out.append(("P4", "Alpaca live: UNMEASURED (no flag snapshot)", None))
    out.append(("P5", "zero: the paper account's score (no borrow)",
                const_fee(idx, {s: 0.0 for s in UNIVERSE})))
    return out


def sec_borrow(B: Book, F, wins, P) -> dict:
    hr("§3 BORROW DRAG BY ERA, under each proxy (%/yr of capital; coverage = share of the "
       "short book with a fee)")
    print(f"Charged by borrow_charge(): short held = H.shift(2) (evaluate's book), fee of "
          f"session t-1, calendar days/{BORROW_DAY_COUNT}, collateral x{BORROW_COLLATERAL_MARKUP}.")
    print("P0 exists only where the FEE_RATE history exists; before it P0 is a gap, not a zero, "
          "and its rows say so. P1-P4 apply one level per name to every session: "
          "counterfactuals, H4.\n")
    charges = {}
    hdr = f"{'proxy':<6}{'window':<26}{'drag%/yr':>9}{'avgShort':>9}{'covered':>9}"
    print(hdr)
    print("-" * len(hdr))
    for key, lab, fee in P:
        if fee is None:
            print(f"{key:<6}{lab}")
            continue
        ch = borrow_charge(B.H, fee)
        charges[key] = ch
        print(f"{key:<6}{lab}")
        for wl, a, b in wins:
            if B.pnl.loc[a:b].abs().sum() == 0:
                continue
            s = ch["short"].loc[a:b]
            u = ch["uncovered"].loc[a:b]
            cov = 1 - u.sum() / s.sum() if s.sum() > 0 else 1.0
            note = "" if cov > 0.999 else ("  <- no fee data: NOT a cost estimate" if cov < 0.01
                                             else "  <- lower bound (gaps not charged)")
            print(f"{'':<6}{wl:<26}{ch['cost'].loc[a:b].mean() * 252 * 100:9.2f}"
                  f"{s.mean():9.3f}{cov:9.1%}{note}")
    # where the measured drag goes
    m0 = wins[-1][1]
    ch = charges["P0"]
    held = (-B.H.shift(2).fillna(0.0)).clip(lower=0).loc[m0:FIT_END]
    fee = F.reindex(index=B.H.index, columns=B.H.columns).shift(1).loc[m0:FIT_END]
    days = pd.Series(B.H.index, index=B.H.index).diff().dt.days.loc[m0:FIT_END]
    per = (held * fee / 100).mul(days, axis=0) * BORROW_COLLATERAL_MARKUP / BORROW_DAY_COUNT
    print(f"\nP0 measured window {pd.Timestamp(m0).date()} .. {FIT_END}, by name:")
    print(f"  {'name':<6}{'avgShort':>9}{'meanFee%':>9}{'drag bp/yr':>11}")
    for c in B.H.columns:
        print(f"  {c:<6}{held[c].mean():9.3f}{fee[c].mean():9.2f}{per[c].mean() * 252 * 1e4:11.1f}")
    return charges


# --------------------------------------------------------------------------- §4 execution

def make_client():
    from quantt.broker.alpaca import AlpacaClient
    return AlpacaClient.from_environment("cef")


def read_records(states: list[Path]) -> tuple[pd.DataFrame, dict, dict]:
    """Fills (deduplicated by fill id), each session's execution mode, and the slippage
    verify itself recorded. Read in place; nothing from the records is written anywhere."""
    rows, modes, recorded = [], {}, {}

    def add(day, fills, src):
        for f in fills or []:
            if str(f.get("transaction_time", ""))[:10] != day:
                continue
            rows.append(dict(day=day, fill_id=f["id"], order_id=f["order_id"],
                             symbol=f["symbol"], side=f["side"], qty=float(f["qty"]),
                             price=float(f["price"]), t=f["transaction_time"], src=src))
    for st in states:
        for p in sorted(st.glob("2026-*/plan.json")):
            plan = json.loads(p.read_text())
            modes[p.parent.name] = plan.get("execution") or "cls"
        for p in sorted(st.glob("2026-*/reconcile.json")):
            d = json.loads(p.read_text())
            add(p.parent.name, d.get("fills"), "reconcile")
            m = re.search(r"fill vs auction ([+-]?\d+(?:\.\d+)?)bp", str(d.get("verdict", "")))
            if m:
                recorded[p.parent.name] = float(m.group(1))
        for p in sorted(st.glob("data/2026-*/account.json")):
            d = json.loads(p.read_text())
            add(d["date"], d.get("fills"), "account")
        tca = st / "tca.csv"
        if tca.exists():
            for _, r in pd.read_csv(tca).iterrows():
                if pd.notna(r.get("slip_bp_all")):
                    recorded[str(r["date"])] = float(r["slip_bp_all"])
    if not rows:
        raise ValueError(f"no fills found under {[str(s) for s in states]}")
    F = pd.DataFrame(rows).drop_duplicates("fill_id")
    return F, modes, recorded


def last_quote(client, symbol: str, t: str) -> dict | None:
    """The last SIP NBBO at or before `t` within QUOTE_LOOKBACK_S, or None.

    Uses the client's read-only GET helper on the market-data host: AlpacaClient has
    no public quotes method and this research script must not add one to the live
    package."""
    end = pd.Timestamp(t)
    start = end - pd.Timedelta(seconds=QUOTE_LOOKBACK_S)
    params = {"symbols": symbol, "start": start.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
              "end": end.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "feed": "sip", "limit": 10000}
    qs, token = [], None
    for _ in range(20):
        if token:
            params["page_token"] = token
        body = client._get(client._data, "/v2/stocks/quotes", params)
        qs += (body.get("quotes") or {}).get(symbol) or []
        token = body.get("next_page_token")
        if not token:
            break
    qs = [q for q in qs if q.get("bp", 0) > 0 and q.get("ap", 0) >= q.get("bp", 0)]
    return qs[-1] if qs else None


def sec_execution(states: list[Path]) -> dict:
    """Measured execution from the broker-confirmed paper sessions.

    WHAT IT CAN AND CANNOT SAY. Paper runs no closing auction (CLAUDE.md landmine
    1) and, under the recorded `late_market` exception, sends market orders 8 to 2
    minutes before the close. So the measured slippage against the official print
    is the cost of THAT execution mode: the half-spread crossed at the quote, plus
    the drift from the quote to the print. Both parts are reported separately,
    because only the first is a cost (the second has no expected sign) and only
    the first is precise at n = 4. A live account sends MOC and fills AT the
    print, so neither part applies to it; its cost relative to the backtest is
    regulatory fees plus its own auction impact, which nothing here can measure.

    The fills are read from the records in place and then re-read from the
    broker; a disagreement raises, because the broker is the fact."""
    hr("§4 EXECUTION: broker-confirmed paper fills against the official closing-auction print")
    F, modes, recorded = read_records(states)
    client = make_client()
    ex = client.stock_exchanges()
    codes = {}
    # second read of the fills, from the broker (read-only activity endpoint)
    print("Fills: records (reconcile.json / data/<day>/account.json, read in place) vs a "
          "fresh broker read (GET /v2/account/activities/FILL):")
    for day, g in F.groupby("day"):
        b = client.activities_fills(dt.date.fromisoformat(day))
        bid = {a["id"]: (float(a["qty"]), float(a["price"])) for a in b}
        rec = {r.fill_id: (r.qty, r.price) for r in g.itertuples()}
        same = bid == rec
        print(f"  {day}  mode {modes.get(day, '?'):<12} records {len(rec):3d} fills, broker "
              f"{len(bid):3d}  {'MATCH' if same else 'DIFFER'}")
        if not same:
            raise ValueError(f"{day}: recorded fills differ from the broker's; the broker is "
                             "the fact -- reconcile the records before using them")
    # every day folder, so the census counts sessions that did NOT fill too
    days = sorted({p.parent.name for st in states for p in st.glob("2026-*/plan.json")})
    print("\nSession census (every day folder with a plan):")
    for d in days:
        n = len(F[F.day == d])
        print(f"  {d}  {modes.get(d, '?'):<12} {'fills ' + str(n) if n else 'no fills'}")
    rows = []
    for day, g in F.groupby("day"):
        syms = sorted(g.symbol.unique())
        for s in syms:
            if s not in codes:
                codes[s] = client.primary_sip_code(s, ex)
        prints = client.closing_auction_prints(syms, dt.date.fromisoformat(day),
                                               exchange_codes=codes, condition="M")
        for r in g.itertuples():
            q = last_quote(client, r.symbol, r.t)
            a = prints[r.symbol]["price"]
            sgn = 1.0 if r.side == "buy" else -1.0       # sell and sell_short are sells
            mid = (q["bp"] + q["ap"]) / 2 if q else np.nan
            rows.append(dict(day=day, order_id=r.order_id, symbol=r.symbol, notional=r.qty * a,
                             qty=r.qty, slip=sgn * (r.price - a) / a * 1e4,
                             hs=sgn * (r.price - mid) / mid * 1e4 if q else np.nan,
                             drift=sgn * (mid - a) / a * 1e4 if q else np.nan,
                             quoted_hs=(q["ap"] - q["bp"]) / mid / 2 * 1e4 if q else np.nan,
                             sell=sgn < 0))
    X = pd.DataFrame(rows)
    nq = int(X.hs.isna().sum())

    def w(g, c):
        g = g[g[c].notna()]
        return float((g[c] * g.notional).sum() / g.notional.sum()) if len(g) else np.nan

    # ADV for participation (the panel's own 63-day ADV through its last date)
    adv = build_panel()["adv"].ffill().iloc[-1]
    O = X.groupby(["day", "order_id", "symbol"]).agg(notional=("notional", "sum")).reset_index()
    O["part"] = O.notional / O.symbol.map(adv)
    print(f"\nPer session (bp of notional, notional-weighted; + = worse than the print). "
          f"{nq} fill(s) had no SIP quote in the {QUOTE_LOOKBACK_S}s before them (unmeasured "
          "for the split):")
    print(f"  {'day':<11}{'mode':<12}{'orders':>7}{'fills':>6}{'slip':>8}{'= half-sprd':>12}"
          f"{'+ drift':>9}{'quoted hs':>10}{'verify said':>12}{'part med':>9}{'part max':>9}")
    S = []
    for day, g in X.groupby("day"):
        o = O[O.day == day]
        rec = recorded.get(day)
        S.append(dict(day=day, mode=modes.get(day, "?"), slip=w(g, "slip"), hs=w(g, "hs"),
                      drift=w(g, "drift")))
        print(f"  {day:<11}{modes.get(day, '?'):<12}{g.order_id.nunique():7d}{len(g):6d}"
              f"{w(g, 'slip'):8.2f}{w(g, 'hs'):12.2f}{w(g, 'drift'):9.2f}{w(g, 'quoted_hs'):10.2f}"
              f"{('%+.2f' % rec) if rec is not None else '-':>12}"
              f"{o.part.median():9.2%}{o.part.max():9.2%}")
    S = pd.DataFrame(S)
    L = S[S["mode"] == "late_market"]
    XL = X[X.day.isin(L.day)]
    from scipy import stats as st
    res = dict(n_sessions=len(L), n_orders=int(XL.order_id.nunique()), n_fills=len(XL))
    print(f"\nlate_market sessions: n = {len(L)}, {res['n_orders']} orders, {res['n_fills']} fills")
    print(f"  {'':<26}{'pooled':>8}{'sess mean':>10}{'sess sd':>8}{'95% CI (t, n-1 df)':>22}")
    for c, lab in (("slip", "slippage vs print"), ("hs", "half-spread paid"),
                   ("drift", "drift, quote -> print")):
        m, sd, n = L[c].mean(), L[c].std(ddof=1), len(L)
        tc = st.t.ppf(0.975, n - 1) if n > 1 else np.nan
        lo, hi = m - tc * sd / np.sqrt(n), m + tc * sd / np.sqrt(n)
        res[c] = dict(pooled=w(XL, c), mean=m, sd=sd, lo=lo, hi=hi)
        print(f"  {lab:<26}{w(XL, c):8.2f}{m:10.2f}{sd:8.2f}{'[' + f'{lo:.1f}, {hi:.1f}' + ']':>22}")
    # order-level dispersion (orders within a session share the market's move, so this
    # is NOT the standard error; shown to say how wide one order's outcome is)
    OL = XL.groupby("order_id").apply(lambda g: w(g, "slip"), include_groups=False)
    print(f"  order-level slippage: median {OL.median():.1f}bp, sd {OL.std():.1f}bp over {len(OL)} "
          "orders (correlated within a session: not a standard error)")
    return res


def reg_fee_bp(sell_share: float, price: float) -> float:
    """Regulatory fees per unit of turnover, in bp: SEC fee on the sell share of turnover
    plus CAT on every share, at a representative share price. TAF is $0 (fee schedule)."""
    return (SEC_FEE_PER_DOLLAR_SOLD * sell_share + CAT_FEE_PER_SHARE / price
            + TAF_PER_SHARE_SOLD * sell_share / price) * 1e4


# --------------------------------------------------------------------------- §5/§6 net and gate

def net_series(B: Book, borrow_cost: pd.Series, c_bp: float) -> pd.Series:
    """Daily net P&L: total-return gross, less borrow, less c_bp per unit turnover.

    Execution cost is booked on the FILL day (turnover decided at t, filled at the
    close of t+1), the convention W4's factor regressions used. Annual means equal
    the harness's `_stats` grid to rounding; only the day a cost lands moves."""
    return B.pnl - borrow_cost - B.turn.shift(1).fillna(0.0) * c_bp / 1e4


def exec_columns(B: Book, X: dict | None) -> list[tuple[str, float]]:
    px_med = float(build_panel()["px"].ffill().iloc[-1].median())
    cols = [("MOC", reg_fee_bp(B.sell_share, px_med))]
    if X is not None:
        cols += [("hs", X["hs"]["pooled"]), ("slipHi", X["slip"]["hi"])]
    cols += [(f"{c}bp", float(c)) for c in COSTS]
    return cols


def sec_net(B: Book, wins, P, charges, X) -> None:
    hr("§5 NET OF MEASURED COSTS, by era and proxy: net SR (net %/yr)")
    cols = exec_columns(B, X)
    print("Gross SR (total returns) is the headline. Execution columns, bp per unit of turnover:")
    print(f"  MOC    = a live MOC fills AT the print: regulatory fees only, {cols[0][1]:.3f}bp "
          f"(SEC {SEC_FEE_PER_DOLLAR_SOLD * 1e4:.3f}bp on the {B.sell_share:.0%} of turnover that "
          "sells, CAT per share, TAF $0, commission $0). Own auction impact: UNMEASURED.")
    if X is not None:
        print(f"  hs     = measured paper half-spread paid, pooled over {X['n_sessions']} "
              f"late_market sessions: {X['hs']['pooled']:.2f}bp")
        print(f"  slipHi = upper 95% bound of the measured paper slippage vs print "
              f"(session t-interval): {X['slip']['hi']:.2f}bp")
    else:
        print("  hs, slipHi: UNMEASURED in this run (no --state records given)")
    print("  5/15/30bp = the real-money cost grid, labelled, beside the measured columns.")
    print("Borrow is charged separately per proxy; 'flips?' is YES if gross and the net "
          "columns do not all share a sign. 2023-26: sealed (H13), not computed.\n")
    keep = [w for w in wins if w[0] not in ("2005-09",)]
    for key, lab, fee in P:
        if key not in charges:
            print(f"{key}: {lab}\n")
            continue
        ch = charges[key]
        print(f"{key}: {lab}")
        print(f"  {'window':<26}{'grossSR':>8}{'gross%':>8}{'borrow%':>8}{'cov':>6}"
              + "".join(f"{c:>13}" for c, _ in cols) + f"{'flips?':>7}")
        for wl, a, b in keep:
            g = B.pnl.loc[a:b]
            if g.abs().sum() == 0 or not in_domain(key, wl):
                continue
            s_ = ch["short"].loc[a:b]
            cov = 1 - ch["uncovered"].loc[a:b].sum() / s_.sum() if s_.sum() > 0 else 1.0
            if cov < 0.01:
                continue                      # no fee data in this window for this proxy
            gs = stats(g)
            cells, signs = [], [np.sign(gs["ann"])]
            for _, c in cols:
                n = stats(net_series(B, ch["cost"], c).loc[a:b])
                cells.append(f"{n['sr']:6.2f}({n['ann'] * 100:5.1f})")
                signs.append(np.sign(n["ann"]))
            flip = "YES" if len(set(signs)) > 1 else "no"
            print(f"  {wl:<26}{gs['sr']:8.2f}{gs['ann'] * 100:8.2f}"
                  f"{ch['cost'].loc[a:b].mean() * 252 * 100:8.2f}{cov:6.0%}"
                  + "".join(f"{x:>13}" for x in cells) + f"{flip:>7}")
        print()


def sec_gate(B: Book, wins, P, charges, X, F) -> None:
    hr("§6 THE GATE: is the deployed book positive net after measured costs?")
    cols = exec_columns(B, X)
    pick = [c for c in cols if c[0] in ("MOC", "hs", "15bp", "30bp")]
    gate_w = [w for w in wins if w[0] in ("live fit 2013-06..2022", "measured-borrow window")]
    print("Net %/yr with three standard errors of the mean: iid t, Newey-West(5) t, and a "
          "moving-block bootstrap (20 sessions, 2,000 reps) 95% interval of the annualised "
          "mean. 'POS' = point estimate > 0; 'CI>0' = the bootstrap interval excludes zero.\n")
    print(f"  {'proxy':<6}{'window':<26}{'exec':>7}{'net%/yr':>9}{'t iid':>7}{'t NW':>7}"
          f"{'boot 95% CI':>18}{'verdict':>13}")
    for key, lab, fee in P:
        if key not in charges:
            continue
        for wl, a, b in gate_w:
            if not in_domain(key, wl):
                continue
            for cl, c in pick:
                x = net_series(B, charges[key]["cost"], c).loc[a:b]
                ti = x.mean() / x.std() * np.sqrt(len(x))
                tb, lo, hi = block_boot_t(x)
                v = ("POS" if x.mean() > 0 else "NOT POS") + (" CI>0" if lo > 0 else
                                                              (" CI<0" if hi < 0 else ""))
                print(f"  {key:<6}{wl:<26}{cl:>7}{x.mean() * 252 * 100:9.2f}{ti:7.2f}"
                      f"{nw_t(x):7.2f}{'[' + f'{lo * 252 * 100:.1f}, {hi * 252 * 100:.1f}' + ']':>18}"
                      f"{v:>13}")
        print()
    # breakevens: no number from a document, both computed here
    print("Breakevens (computed now, H14):")
    one = borrow_charge(B.H, const_fee(B.H.index, {s: 1.0 for s in UNIVERSE}))["cost"]
    print(f"  {'window':<26}{'gross%':>8}{'turn/yr':>8}{'drag per 1%fee':>15}"
          f"{'f* @MOC':>9}{'f* @15bp':>9}   (f* = uniform borrow fee, %/yr, at which net = 0)")
    for wl, a, b in gate_w:
        g = B.pnl.loc[a:b].mean() * 252
        t = B.turn.loc[a:b].mean() * 252
        d1 = one.loc[a:b].mean() * 252
        fm = (g - t * cols[0][1] / 1e4) / d1
        f15 = (g - t * 15 / 1e4) / d1
        print(f"  {wl:<26}{g * 100:8.2f}{t:8.1f}{d1 * 100:15.3f}{fm:9.2f}{f15:9.2f}")
    # the fee the measured window actually paid, per unit of short book
    m0 = [w for w in gate_w if w[0] == "measured-borrow window"][0][1]
    paid = charges["P0"]["cost"].loc[m0:FIT_END].mean() / one.loc[m0:FIT_END].mean()
    print(f"\n  measured window: short-weighted IBKR fee actually charged (P0 drag / drag per "
          f"1% fee) = {paid:.2f}%/yr, against f* above")
    # How often, across the whole fee history, would the book's TYPICAL short book have
    # paid more than the live-fit breakeven? Composition = each name's share of the short
    # book over live fit 2013-06..2022 (pre-holdout positions only); fees are cost inputs.
    a, b = B.live0, FIT_END
    held = (-B.H.shift(2).fillna(0.0)).clip(lower=0).loc[a:b].mean()
    wgt = held / held.sum()
    use = wgt[wgt > 0].index
    full = F[use].dropna()
    idx_fee = (full * wgt[use]).sum(axis=1)
    g = B.pnl.loc[a:b].mean() * 252
    t = B.turn.loc[a:b].mean() * 252
    d1 = one.loc[a:b].mean() * 252
    fstar = {"MOC": (g - t * cols[0][1] / 1e4) / d1, "15bp": (g - t * 15 / 1e4) / d1}
    print(f"\n  The live-fit short book's composition ({len(use)} names, weights = average short "
          f"share 2013-06..2022) priced at the FEE_RATE history, {full.index.min().date()} .. "
          f"{full.index.max().date()} ({len(full)} of {len(F)} dates have a fee for every name):")
    print(f"  {'year':<6}{'dates':>6}{'mean fee%':>10}{'> f*@MOC':>10}{'> f*@15bp':>10}"
          f"   (f*@MOC {fstar['MOC']:.2f}%, f*@15bp {fstar['15bp']:.2f}%)")
    for y, v in idx_fee.groupby(idx_fee.index.year):
        print(f"  {y:<6}{len(v):6d}{v.mean():10.2f}{(v > fstar['MOC']).mean():10.0%}"
              f"{(v > fstar['15bp']).mean():10.0%}")
    print(f"  {'all':<6}{len(idx_fee):6d}{idx_fee.mean():10.2f}{(idx_fee > fstar['MOC']).mean():10.0%}"
          f"{(idx_fee > fstar['15bp']).mean():10.0%}")

    print(f"\n  {'proxy':<6}{'window':<26}{'c* bp/unit turnover (net = 0 after this borrow)':>50}")
    for key, lab, fee in P:
        if key not in charges:
            continue
        for wl, a, b in gate_w:
            if not in_domain(key, wl):
                continue
            g = B.pnl.loc[a:b].mean() * 252
            bor = charges[key]["cost"].loc[a:b].mean() * 252
            t = B.turn.loc[a:b].mean() * 252
            print(f"  {key:<6}{wl:<26}{(g - bor) / t * 1e4:50.1f}")


def sec_second(B: Book, F, wins, charges) -> None:
    hr("§7 SECOND METHODS for the figures that decide the gate")
    m0 = [w for w in wins if w[0] == "measured-borrow window"][0][1]
    ch = charges["P0"]
    drag = ch["cost"].loc[m0:FIT_END].mean() * 252
    # (a) product of means instead of mean of products
    held = (-B.H.shift(2).fillna(0.0)).clip(lower=0).loc[m0:FIT_END]
    fee = F.reindex(index=B.H.index, columns=B.H.columns).shift(1).loc[m0:FIT_END]
    days = pd.Series(B.H.index, index=B.H.index).diff().dt.days.loc[m0:FIT_END]
    pm = float((held.mean() * fee.mean() / 100).sum() * days.mean()
               * BORROW_COLLATERAL_MARKUP / BORROW_DAY_COUNT * 252)
    print(f"(a) P0 drag, mean of daily products {drag * 100:.2f}%/yr; product of per-name "
          f"means {pm * 100:.2f}%/yr (the gap is the short-fee covariance)")
    # (b) alignment: the fee dated t instead of t-1
    alt = borrow_charge(B.H, F.reindex(columns=B.H.columns).shift(-1))
    print(f"(b) P0 with the fee dated t rather than t-1: {alt['cost'].loc[m0:FIT_END].mean() * 252 * 100:.2f}%/yr")
    # (c) spike-robust level: each name's MEDIAN fee in the window, held constant
    med = const_fee(B.H.index, F.loc[F.index.min():FIT_END].median().to_dict())
    cm = borrow_charge(B.H, med)["cost"].loc[m0:FIT_END].mean() * 252
    print(f"(c) P0 window with each name's median window fee, constant: {cm * 100:.2f}%/yr")
    # (d) the gross that every net is built on reproduces W4
    print(f"(d) gross SR, fit / live fit, total returns: {stats(B.pnl)['sr']:.2f} / "
          f"{stats(B.pnl.loc[B.live0:])['sr']:.2f} (W4 2026-10-11: 0.69 / 0.96); price "
          f"returns fit {B.px['gross_sr']:.2f} (W4: 0.70)")
    # (e) the grid convention: my fill-day booking vs the harness's _stats, P5, fit row
    from scripts.cef.band_frontier import _stats
    s = _stats(B.pnl, B.turn)
    mine = [stats(net_series(B, charges["P5"]["cost"], c))["sr"] for c in COSTS]
    print(f"(e) no-borrow grid, harness _stats {['%.3f' % x for x in s['nets']]} vs fill-day "
          f"booking {['%.3f' % x for x in mine]}")


# --------------------------------------------------------------------------- snapshots

IBKR_URL = "https://www.interactivebrokers.com/shortstock/usa.txt"


def refresh_snapshots() -> None:
    """Today's IBKR public shortstock file (the 13 names and the four dropped munis)
    and today's Alpaca asset flags, cached under _cache_rmc. Read-only."""
    import urllib.request
    CACHE.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with urllib.request.urlopen(IBKR_URL, timeout=60) as r:
        text = r.read().decode("utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#BOF|"):
        raise ValueError(f"{IBKR_URL}: first line {lines[:1]} is not '#BOF|date|time'")
    _, fdate, ftime = lines[0].split("|")[:3]
    hdr = lines[1].lstrip("#").split("|")
    want = set(UNIVERSE) | {"NAD", "NEA", "NVG", "NZF"}
    recs = []
    for ln in lines[2:]:
        f = ln.split("|")
        if len(f) < 8 or f[0] not in want:
            continue
        d = dict(zip(hdr, f))
        recs.append(dict(symbol=d["SYM"], fee_rate_pct=float(d["FEERATE"]),
                         rebate_rate_pct=float(d["REBATERATE"]),
                         available=float(d["AVAILABLE"].lstrip(">")),
                         file_stamp=f"{fdate} {ftime}", fetched_at_utc=now))
    missing = sorted(set(UNIVERSE) - {r["symbol"] for r in recs})
    if missing:
        raise ValueError(f"IBKR shortstock file {fdate} {ftime} has no row for {missing}")
    out = CACHE / f"ibkr_shortstock_{fdate.replace('.', '-')}.csv"
    pd.DataFrame(recs).to_csv(out, index=False)
    print(f"cached {out.relative_to(REPO)} (file stamped {fdate} {ftime})")
    c = make_client()
    assets = {}
    for s in sorted(want):
        a = c.asset(s)
        assets[s] = {k: a.get(k) for k in ("borrow_status", "shortable", "easy_to_borrow",
                                           "marginable", "exchange")}
    out = CACHE / f"alpaca_assets_{now[:10]}.json"
    out.write_text(json.dumps({"read_at_utc": now, "assets": assets}, indent=1))
    print(f"cached {out.relative_to(REPO)}")


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", action="append", default=[], type=Path,
                    help="a runner state directory to read fills from, in place (repeatable)")
    ap.add_argument("--refresh-snapshots", action="store_true",
                    help="fetch today's IBKR shortstock file and Alpaca asset flags first")
    a = ap.parse_args(argv)
    if a.refresh_snapshots:
        refresh_snapshots()
    print(f"real_money_costs.py run {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}")
    hr("§0 PANELS (read-only; stale is a form of wrong)")
    for k, (lo, hi) in panel_dates().items():
        print(f"  data/cef/{k:<28} {lo} .. {hi}")
    B = Book()
    F = fee_history()
    later = B.H.index[B.H.index > F.index.min()]
    measured_start = later[0]                 # first row whose t-1 fee can exist
    wins = B.windows(measured_start)
    sec_book(B, wins)
    sec_borrow_inputs(F)
    P = proxies(B, F)
    charges = sec_borrow(B, F, wins, P)
    X = sec_execution([s.expanduser() for s in a.state]) if a.state else None
    if X is None:
        hr("§4 EXECUTION: UNMEASURED in this run (no --state records given)")
    sec_net(B, wins, P, charges, X)
    sec_gate(B, wins, P, charges, X, F)
    sec_second(B, F, wins, charges)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
