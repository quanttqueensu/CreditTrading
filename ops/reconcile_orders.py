"""Reconcile what the LEDGER did against what the BROKER was actually told.

    python3 -m ops.reconcile_orders --book ops/books/cef_discount_book.json \
        --books-root ops/books/cef_live [--asof 2026-09-01] [--check-broker]

WHY THIS EXISTS
---------------
On 2026-09-01 the cef_discount ledger reported NAV $490,808 (-1.84% since
funding). The account's real book was worth $496,545 (-0.69%). The $5,738 gap
was not a pricing error: the account traded ONCE, on 2026-07-31, and then sat
untouched for 21 business days while TWS was down -- but the first armed run
walked the shadow ledger forward through every one of those days, booking 349
modelled trades that were never transmitted, including $366k of turnover on
2026-08-04.

Nothing caught it. Every existing guard compares the account to the TAG BOOK
(`_live_positions`), and `arm()` overwrites the tag book from `ib.positions()`
at the start of every session -- so `_check_drift` was comparing the broker to
itself and reporting OK. The LEDGER, which `AUTOMATION.md` names as the sole
P&L source, was never in that comparison at all.

Two things are therefore checked here, and they are different questions:

  POSITIONS  ledger vs broker.  Catches a ledger that has simulated trades the
             account never made (or missed ones it did). This is the check that
             was missing.

  ORDERS     ledger's orders.csv vs the adapter's _order_map.csv.  These are
             NOT the same quantity and were never meant to be: orders.csv
             records the ledger's own step from ITS position, while the order
             map records what was transmitted, diffed against BROKER truth.
             On 2026-08-31 orders.csv said AWF delta +7 while the broker was
             sent SELL 3,549; PFN said delta 0 against a transmitted BUY 1,160,
             a sign flip. Both records are correct about their own subject. The
             failure was that only one of them looked like an order log.

Read-only. It reports and exits non-zero; it never edits state.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

TOL = 1e-6

# Every book in the account. The position check sums across all of them,
# because they share tickers and one account nets them together.
ALL_BOOKS = [
    ("ops/books/cef_discount_book.json", "ops/books/cef_live"),
    ("ops/books/phase0_book.json", "ops/books/phase0_live"),
    ("ops/books/benchmarks_book.json", "ops/books/benchmarks_live"),
]


def _sleeves(book_path):
    spec = json.loads(Path(book_path).read_text())
    return [s["name"] for s in spec.get("sleeves", []) if s.get("enabled", True)]


def ledger_positions(books_root, sleeve, asof=None) -> dict:
    """{instrument: shares} from the shadow sub-ledger's last row on/before asof."""
    p = Path(books_root) / "_ibkr_shadow" / sleeve / "positions.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    if df.empty:
        return {}
    df = df[df["ticker"] != "CASH"]
    df["date"] = pd.to_datetime(df["date"])
    if asof is not None:
        df = df[df["date"] <= pd.Timestamp(asof)]
    if df.empty:
        return {}
    last = df[df["date"] == df["date"].max()]
    return {r.ticker: float(r.shares) for r in last.itertuples()
            if pd.notna(r.shares)}


def transmitted_orders(books_root, asof=None) -> pd.DataFrame:
    """What the adapter actually sent, from _order_map.csv."""
    p = Path(books_root) / "_ibkr_shadow" / "_order_map.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    if df.empty:
        return df
    df["asof"] = pd.to_datetime(df["asof"])
    if asof is not None:
        df = df[df["asof"] == pd.Timestamp(asof)]
    return df


def ledger_orders(books_root, sleeve, asof=None) -> pd.DataFrame:
    p = Path(books_root) / "_ibkr_shadow" / sleeve / "orders.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    if df.empty:
        return df
    df["decision_date"] = pd.to_datetime(df["decision_date"])
    if asof is not None:
        df = df[df["decision_date"] == pd.Timestamp(asof)]
    return df


def broker_positions(client_id=None) -> dict:
    """{symbol: shares} from the account. Requires a live TWS session."""
    import ib_async as ibapi

    from src.deploy.broker.ibkr import IBKRConfig
    cfg = IBKRConfig.from_env()
    app = ibapi.IB()
    app.connect(cfg.host, int(cfg.port),
                clientId=int(client_id or (cfg.client_id + 70)),
                readonly=True, timeout=30)
    try:
        out = {}
        for p in app.positions():
            out[p.contract.symbol] = out.get(p.contract.symbol, 0.0) + float(p.position)
        return out
    finally:
        app.disconnect()


def run(book_path, books_root, asof=None, check_broker=False, client_id=None):
    sleeves = _sleeves(book_path)
    problems = []

    print(f"[reconcile] book={book_path}")
    print(f"[reconcile] root={books_root}  asof={asof or 'latest'}  "
          f"sleeves={', '.join(sleeves)}")

    # -- ORDERS: ledger step vs transmitted --------------------------------
    tx = transmitted_orders(books_root, asof)
    print(f"\n=== TRANSMITTED vs LEDGER ORDERS ===")
    if tx.empty:
        print("  no _order_map.csv rows for this date — nothing was transmitted, "
              "or the adapter predates order-attribution recording (2026-08-31).")
    else:
        for sleeve in sleeves:
            lo = ledger_orders(books_root, sleeve, asof)
            t = tx[tx["sleeve"] == sleeve]
            if t.empty and lo.empty:
                continue
            print(f"\n  {sleeve}:")
            print(f"    {'ticker':<8}{'sent':>12}{'ledger_delta':>14}{'ledger_from':>13}")
            syms = sorted(set(t["instrument"]) | set(lo.get("ticker", [])))
            for s in syms:
                ts = t[t["instrument"] == s]
                ls = lo[lo["ticker"] == s] if not lo.empty else lo
                sent = ""
                if not ts.empty:
                    r = ts.iloc[0]
                    sent = f"{r['action']} {abs(float(r['qty'])):,.0f}"
                delta = f"{float(ls.iloc[0]['delta_shares']):+,.0f}" if not ls.empty else ""
                frm = f"{float(ls.iloc[0]['current_shares']):,.0f}" if not ls.empty else ""
                print(f"    {s:<8}{sent:>12}{delta:>14}{frm:>13}")
            print("    (these measure different things — see module docstring)")

    # -- POSITIONS: ledger vs broker ---------------------------------------
    #
    # This MUST be summed across every book in the account, never per sleeve.
    # All three books run as separate processes against ONE paper account, and
    # they share tickers: the account's 823 HYG is bench_b1_hyg 251 +
    # bench_b6_ew_credit 31 + null_trader 541. Comparing one sleeve's ledger to
    # the account net reports a 791-share "divergence" that is really just the
    # other two books, which is the same mistake arm()'s shared-symbol branch
    # made until 2026-08-31. The real question is whether the sum of everything
    # every ledger claims equals what the account holds.
    print(f"\n=== LEDGER vs BROKER POSITIONS (whole account) ===")
    if not check_broker:
        print("  skipped (pass --check-broker; needs a live TWS session)")
    else:
        try:
            acct = broker_positions(client_id)
        except Exception as exc:
            print(f"  BROKER UNREACHABLE: {exc!r}")
            problems.append("broker unreachable — ledger/broker divergence unchecked")
            acct = None
        if acct is not None:
            claimed, owners = {}, {}
            for bpath, broot in ALL_BOOKS:
                bpath, broot = REPO_ROOT / bpath, REPO_ROOT / broot
                if not bpath.exists():
                    continue
                for sl in _sleeves(bpath):
                    for s, q in ledger_positions(broot, sl, asof).items():
                        claimed[s] = claimed.get(s, 0.0) + q
                        owners.setdefault(s, []).append(sl)
            rows, worst = [], 0.0
            for s in sorted(set(claimed) | set(acct)):
                c, b = claimed.get(s, 0.0), acct.get(s, 0.0)
                if abs(c - b) > TOL:
                    rows.append((s, c, b, b - c, owners.get(s, [])))
                    worst = max(worst, abs(b - c))
            print(f"  {len(claimed)} symbol(s) claimed by ledgers, "
                  f"{len(acct)} held, {len(rows)} divergent")
            if rows:
                print(f"    {'ticker':<8}{'ledgers':>11}{'broker':>11}"
                      f"{'diff':>11}  claimed_by")
                for s, c, b, d, who in rows:
                    print(f"    {s:<8}{c:>11,.0f}{b:>11,.0f}{d:>+11,.0f}  "
                          f"{', '.join(who) or '(nobody)'}")
                problems.append(
                    f"{len(rows)} symbol(s) where the ledgers in total disagree "
                    f"with the account (worst {worst:,.0f} shares)")

    print()
    if problems:
        print("[reconcile] PROBLEMS")
        for p in problems:
            print(f"  - {p}")
        print("\n  A ledger that disagrees with the account is not cosmetic: the")
        print("  ledger is the sole P&L source, so every NAV, drawdown and Gate S")
        print("  reading is computed from it. Rebuild it from real fills")
        print("  (ops/rebuild_ledger.py) rather than letting it drift further.")
        return 1
    print("[reconcile] OK — ledger and account agree")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--book", required=True)
    ap.add_argument("--books-root", required=True)
    ap.add_argument("--asof", default=None)
    ap.add_argument("--check-broker", action="store_true",
                    help="also compare the ledger to ib.positions()")
    ap.add_argument("--client-id", type=int, default=None)
    a = ap.parse_args(argv)
    return run(a.book, a.books_root, asof=a.asof,
               check_broker=a.check_broker, client_id=a.client_id)


if __name__ == "__main__":
    sys.exit(main())
