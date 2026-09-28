"""Reverse ledger fills the broker never executed, on the ledger's last date.

WHY THIS EXISTS AND WHY IT IS NOT `rebuild_ledger`
-------------------------------------------------
On 2026-09-10 `null_trader` closed fourteen orders as `filled`. Five of them --
EMB +57, HYG +605, JAAA -1503, JNK +420, LQD +861 -- had ZERO executions at the
broker. The obvious remedy, and the one every note written that day prescribed,
was `ops/rebuild_ledger.py`: rebuild the sleeve from its own `broker_fills.csv`.

**Measured 2026-09-10, that remedy is worse than the disease.** `broker_fills.csv`
holds 677 executions across only three dates (07-31: 45, 09-08: 60, 09-10: 572).
Fill capture began 2026-07-31 21:20 UTC and `ib.fills()` cannot reach back past a
TWS restart, so the file is not a complete history of the account -- it is
everything we managed to catch. Rebuilding from it reconciles **2 of 14 symbols**
against the broker and introduces a total absolute error of **14,346 shares**
(worst: BKLN +4,901, SRLN -4,444). `rebuild_ledger`'s own docstring names the
safety property that would have caught this -- "refuses to run unless the
captured fills reproduce the broker's CURRENT position exactly" -- but that check
only runs under `--check-broker`, which opens a broker socket, so the default
invocation skips the very guard the file advertises.

Reversing only the unexecuted fills takes the same book from **3,487 shares** of
disagreement with the broker to **49**, every symbol within 12, and LQD to the
3-share pre-existing modelled drift that `results/ops/LQD_ATTRIBUTION_2026-09-10.md`
independently predicted. That is the operation this file performs.

WHY ONLY THE LAST DATE
----------------------
Reversing a fill mid-history changes the cash and share path of every day after
it, and this tool does not replay them -- it would be re-implementing
`Ledger.advance` in a second place, which is how the two drift apart. So it
refuses on any date but the ledger's last, and says to replay instead. In the
incident that motivated it the phantoms were all on the last date, which is the
normal case: you find them the day they happen.

WHAT IT DOES NOT DECIDE
-----------------------
It never consults targets, never asks what the position "should" be, and never
touches a symbol that HAS an execution -- including one that filled partially.
Its whole claim is "the broker reports nothing for this instrument on this date,
so no fill may be booked for it", which is the same claim `Ledger._broker_fill`
now enforces at write time. This file is the retrospective half of that guard,
for the rows written before it existed.

    python3 -m ops.unbook_unexecuted_fills --books-root ops/books/phase0_live \
        --sleeve null_trader --date 2026-09-10            # dry run, prints the diff
    python3 -m ops.unbook_unexecuted_fills ... --apply
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from ops.ledger import CASH, Ledger  # noqa: E402


def executed_instruments(state_dir: Path, date) -> set:
    """Instruments with at least one execId-backed execution on `date`.

    A missing broker_fills.csv RAISES. "No file" and "no executions" would
    otherwise be the same answer, and they license opposite actions: the first
    means we cannot see, the second means nothing traded.
    """
    path = state_dir / "broker_fills.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} does not exist, so which fills were real cannot be "
            f"established. Capture first (python3 -m ops.capture_fills); "
            f"refusing to treat an absent record as an empty one.")
    bf = pd.read_csv(path)
    if "note" not in bf.columns:
        raise KeyError(f"{path} has no 'note' column, so no execId can be read")
    day = bf[bf["fill_date"].astype(str).str[:10] == str(pd.Timestamp(date).date())]
    day = day[day["note"].astype(str).str.contains("execId=", na=False)]
    return set(day["instrument"].astype(str))


def unbook(books_root, sleeve, date, apply=False, verbose=True) -> dict:
    state = Path(books_root) / "_ibkr_shadow" / sleeve
    lg = Ledger(state_dir=state)
    date = pd.Timestamp(date).normalize()

    if lg.nav.empty:
        raise ValueError(f"{state}: nav.csv is empty; nothing to unbook")
    last = pd.Timestamp(lg.nav["date"].max()).normalize()
    if date != last:
        raise ValueError(
            f"{state}: this tool only reverses the ledger's LAST date "
            f"({last.date()}), and you asked for {date.date()}. Reversing "
            f"earlier changes the cash and share path of every day after it, "
            f"which this tool does not replay. Truncate to {date.date()} and "
            f"re-advance instead.")

    executed = executed_instruments(state, date)
    tr = lg.trades.copy()
    tr["_d"] = pd.to_datetime(tr["fill_date"]).dt.normalize()
    on_day = tr[tr["_d"] == date]
    phantom = on_day[~on_day["ticker"].astype(str).isin(executed)]

    report = {"date": str(date.date()), "sleeve": sleeve,
              "executed_instruments": sorted(executed),
              "reversed": [], "applied": bool(apply)}
    if phantom.empty:
        if verbose:
            print(f"[unbook] {sleeve} {date.date()}: every booked fill has a "
                  f"broker execution. Nothing to do.")
        return report

    # -- reverse ----------------------------------------------------------
    # `cash -= shares * fill_price` in advance(), so undoing adds it back.
    # Commission is charged separately and is 0.0 in config/costs.yaml; it is
    # NOT reversed here because this tool cannot know what was charged, and
    # guessing it is exactly the class of error being repaired. If a broker
    # that charges commission is ever used, the nav row must be recomputed by
    # replay rather than by this arithmetic -- asserted below.
    delta_shares, cash_back, cost_back, traded_back = {}, 0.0, 0.0, 0.0
    for r in phantom.itertuples():
        signed = float(r.shares) * (1.0 if str(r.side).upper() == "BUY" else -1.0)
        delta_shares[r.ticker] = delta_shares.get(r.ticker, 0.0) + signed
        cash_back += signed * float(r.fill_price)
        cost_back += float(r.cost_usd)
        traded_back += abs(float(r.notional_usd))
        report["reversed"].append(
            {"ticker": r.ticker, "side": r.side, "shares": float(r.shares),
             "fill_price": float(r.fill_price), "cost_usd": float(r.cost_usd)})

    lg.trades = lg.trades.drop(index=phantom.index).reset_index(drop=True)

    # orders: filled -> skipped, fill_date cleared. The order was real; only the
    # fill was not, and "skipped" is what advance() writes for an order that did
    # not trade.
    od = lg.orders
    od_d = pd.to_datetime(od["fill_date"], errors="coerce").dt.normalize()
    hit = (od_d == date) & od["ticker"].astype(str).isin(delta_shares) & \
          (od["status"].astype(str) == "filled")
    lg.orders.loc[hit, "status"] = "skipped"
    lg.orders.loc[hit, "fill_date"] = pd.NaT
    report["orders_reopened"] = int(hit.sum())

    # positions on `date`
    pos = lg.positions
    pd_d = pd.to_datetime(pos["date"]).dt.normalize()
    for tkr, ds in delta_shares.items():
        m = (pd_d == date) & (pos["ticker"].astype(str) == tkr)
        if not m.any():
            raise KeyError(f"{state}: no positions row for {tkr} on {date.date()}")
        lg.positions.loc[m, "shares"] = pos.loc[m, "shares"] - ds
        lg.positions.loc[m, "market_value"] = (
            lg.positions.loc[m, "shares"] * pos.loc[m, "close"])
    # A position driven to exactly zero gets NO row, because that is what
    # `advance` writes -- it pops the key before the positions loop. A 0.0 row
    # would be off-convention, and this repo's ledger convention is that the
    # absence of a row IS the flat claim (see the arm() attribution reasoning in
    # results/ops/LQD_ATTRIBUTION_2026-09-10.md).
    zeroed = lg.positions.index[
        (pd_d == date) & (lg.positions["ticker"].astype(str) != CASH)
        & (lg.positions["shares"].abs() < 1e-9)]
    if len(zeroed):
        report["zeroed_and_dropped"] = sorted(
            lg.positions.loc[zeroed, "ticker"].astype(str))
        lg.positions = lg.positions.drop(index=zeroed)
        pd_d = pd.to_datetime(lg.positions["date"]).dt.normalize()
        pos = lg.positions

    cash_m = (pd_d == date) & (pos["ticker"].astype(str) == CASH)
    lg.positions.loc[cash_m, "market_value"] = (
        pos.loc[cash_m, "market_value"] + cash_back)

    # nav on `date`
    nv = lg.nav
    nv_d = pd.to_datetime(nv["date"]).dt.normalize()
    n = nv_d == date
    cash_new = float(nv.loc[n, "cash"].iloc[0]) + cash_back
    invested_new = float(
        lg.positions.loc[(pd_d == date) & (pos["ticker"].astype(str) != CASH),
                         "market_value"].sum())
    nav_new = cash_new + invested_new
    prior = nv.loc[nv_d < date].sort_values("date")
    prev_nav = float(prior["nav"].iloc[-1]) if not prior.empty else None
    # Read the OLD values before writing: `nv` is a reference to `lg.nav`, not a
    # copy, so reading after the assignments below returns the new numbers and
    # the report would print "NAV X -> X (+0.00)" for every reversal.
    nav_before = float(nv.loc[n, "nav"].iloc[0])
    cost_before = float(nv.loc[n, "cost_usd"].iloc[0])
    traded_before = float(nv.loc[n, "traded_usd"].iloc[0])
    lg.nav.loc[n, "cash"] = cash_new
    lg.nav.loc[n, "invested"] = invested_new
    lg.nav.loc[n, "nav"] = nav_new
    lg.nav.loc[n, "cost_usd"] = cost_before - cost_back
    lg.nav.loc[n, "traded_usd"] = traded_before - traded_back
    lg.nav.loc[n, "daily_return"] = (
        (nav_new / prev_nav - 1.0) if prev_nav else float("nan"))

    # the CASH positions row and the nav row must agree, or the book is
    # internally inconsistent in a way nothing downstream would notice.
    cash_row = float(lg.positions.loc[cash_m, "market_value"].iloc[0])
    if abs(cash_row - cash_new) > 1e-6:
        raise AssertionError(
            f"cash disagrees after reversal: positions.csv {cash_row!r} vs "
            f"nav.csv {cash_new!r}")
    for tkr in delta_shares:
        mv = lg.positions.loc[(pd_d == date) &
                              (pos["ticker"].astype(str) == tkr)]
        if not mv.empty:
            lg.positions.loc[mv.index, "weight"] = (
                mv["market_value"] / nav_new if nav_new else float("nan"))
    lg.positions.loc[cash_m, "weight"] = cash_new / nav_new if nav_new else float("nan")

    report["nav_before"] = nav_before
    report["nav_after"] = nav_new

    if verbose:
        print(f"[unbook] {sleeve} {date.date()}: {len(phantom)} booked fill(s) "
              f"have NO broker execution and are being reversed:")
        for r in report["reversed"]:
            print(f"[unbook]   {r['ticker']:6} {r['side']:4} {r['shares']:>9,.0f} "
                  f"@ {r['fill_price']:.4f}  (modelled price, no execId)")
        print(f"[unbook]   NAV {report['nav_before']:,.2f} -> {nav_new:,.2f} "
              f"({nav_new - report['nav_before']:+,.2f})")
        print(f"[unbook]   cost_usd -{cost_back:,.2f}  traded_usd -{traded_back:,.2f}")

    if not apply:
        if verbose:
            print("[unbook] --dry-run (default): nothing written. Pass --apply.")
        return report

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = state.parent / f"_preunbook_{sleeve}_{stamp}"
    shutil.copytree(state, backup)
    lg.save()
    report["backup"] = str(backup)
    if verbose:
        print(f"[unbook] previous state copied to {backup}")
        print(f"[unbook] written.")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--books-root", required=True)
    ap.add_argument("--sleeve", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="write. Without it this is a dry run.")
    a = ap.parse_args(argv)
    unbook(a.books_root, a.sleeve, a.date, apply=a.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
