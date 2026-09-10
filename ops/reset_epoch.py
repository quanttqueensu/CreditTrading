"""Restart a book's track record from a clean, REAL state.

WHY
---
Two different things produce a modelled fill in this system and only one of them
is legitimate.

  1. BY DESIGN. IBKR *paper* fills are generated against top-of-book with no
     dealer layer, so they are unrealistically kind. The shadow ledger therefore
     charges a measured cost model instead of booking the paper print
     (FORCED_FLOW_PREREG locked decision 1, `src/deploy/lib/odd_lot.py`). That
     makes the record MORE conservative than the broker, and it stays.

  2. BY ACCIDENT. Between 2026-08-03 and 2026-09-03 the ledger advanced through
     22 sessions in which NOTHING was transmitted -- `config/.env` pointed at
     port 7497 while the gateway served 4002, so preflight correctly refused to
     arm and the book dry-ran. The ledger walked forward anyway. That is
     $700,249 of turnover, 48.2% of the ledger, recording trades the account
     never made. It is not conservative modelling; it is fabrication.

You cannot repair (2) by re-deriving it -- there is nothing to derive from. The
only honest fix is to declare an epoch: archive the contaminated history, re-seed
from the positions the BROKER actually reports, and run forward where every
session is armed and every fill is captured.

WHAT IT DOES
------------
  * archives the whole sub-ledger to `_pre_epoch_<stamp>/` (nothing deleted),
  * writes a fresh nav/positions/trades/orders set whose first row is the epoch:
    the broker's real positions, marked at the staged close, at a declared NAV,
  * leaves `broker_fills.csv` and `slippage.csv` untouched -- they are the real
    execution record and are the reason any of this is checkable.

WHAT IT DOES NOT DO
-------------------
It does not trade. It does not touch the account. It changes ACCOUNTING only:
after it runs the account holds exactly what it held before.

    python3 -m ops.reset_epoch --book ops/books/cef_discount_book.json \
        --books-root ops/books/cef_live --sleeve cef_discount \
        --nav 500000 --asof 2026-09-08            # add --commit to write
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402


def broker_positions(universe, client_id=120):
    # 120, not 96. 96 is `capture_fills` for the benchmarks book (its session
    # id 46, + 50). IB allows one session per client id, so the second connect
    # evicts the first -- and this tool runs during exactly the recovery window
    # where capture is most likely to be running too. Full inventory of the
    # ids this repo uses: docs/INFRASTRUCTURE.md 6.2.
    """What the ACCOUNT actually holds, with the broker's own marks.

    Returns (positions, marks). The marks matter: the staged parquet stores are
    research artefacts (data/rv/etf_ohlc.parquet was last written 2026-07-29)
    while the account is marked continuously, so for a broker-sourced seed the
    broker's price is both fresher and the one the position is actually worth.
    """
    from ib_insync import IB, util
    util.logToConsole(50)
    ib = IB()
    ib.connect("127.0.0.1", 4002, clientId=client_id, readonly=True, timeout=20)
    try:
        pos, mk = {}, {}
        for i in ib.portfolio():
            sym = i.contract.symbol
            if sym in universe and float(i.position):
                pos[sym] = float(i.position)
                if i.marketPrice and float(i.marketPrice) > 0:
                    mk[sym] = float(i.marketPrice)
        return pos, mk
    finally:
        ib.disconnect()


def marks(universe, asof):
    """Last close per name on or before `asof`, from whichever store has it.

    The CEF panel and the ETF panel are separate; benchmark books trade ETFs
    and the strategy book trades CEFs, so both are consulted. A name present in
    neither raises at the call site rather than being seeded unpriced.
    """
    frames = []
    for path in (REPO / "data/cef/cef_prices.parquet",
                 REPO / "data/rv/etf_ohlc.parquet"):
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["date", "ticker", "close"])
        df = df[df.ticker.isin(universe)]
        if len(df):
            frames.append(df)
    if not frames:
        raise SystemExit("no price store carries any of: " + ", ".join(sorted(universe)))
    px = pd.concat(frames, ignore_index=True)
    px["date"] = pd.to_datetime(px["date"])
    px = px[px["date"] <= pd.Timestamp(asof)]
    piv = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    if piv.empty:
        raise SystemExit(f"no marks on or before {asof}")
    return piv.ffill().iloc[-1], piv.index[-1].date()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--books-root", required=True)
    ap.add_argument("--sleeve", default="cef_discount")
    ap.add_argument("--nav", type=float, required=True,
                    help="declared NAV at the epoch")
    ap.add_argument("--asof", required=True)
    ap.add_argument("--from-ledger", action="store_true",
                    help="seed positions from the sleeve's own ledger instead of "
                         "the broker. REQUIRED when books share tickers: the "
                         "account nets HYG across b1_hyg and b6_ew_credit, so the "
                         "broker cannot say which book owns what. The share COUNTS "
                         "are still real -- only the attribution comes from the "
                         "ledger, which is the sole record of it.")
    ap.add_argument("--commit", action="store_true",
                    help="actually write; without it this is a dry run")
    a = ap.parse_args(argv)

    root = Path(a.books_root).resolve() / "_ibkr_shadow" / a.sleeve
    if not root.exists():
        raise SystemExit(f"no sub-ledger at {root}")

    spec_path = REPO / "ops/specs" / f"{a.sleeve}.frozen.json"
    universe = set(json.loads(spec_path.read_text())["frozen"]["universe"])

    ledger_marks = {}
    if a.from_ledger:
        pos = pd.read_csv(root / "positions.csv")
        pos = pos[(pos.ticker != "CASH") & pos.shares.notna()]
        if pos.empty:
            raise SystemExit(f"{root/'positions.csv'} has no positions to seed from")
        pos["date"] = pd.to_datetime(pos["date"])
        pos = pos[pos["date"] == pos["date"].max()]
        held = {r.ticker: float(r.shares) for r in pos.itertuples()
                if float(r.shares)}
        # Marks come from the SAME ledger row as the positions. The staged
        # parquet stores are research artefacts -- data/rv/etf_ohlc.parquet was
        # last written 2026-07-29 -- while the books mark to yfinance at runtime,
        # so the ledger's own close is the fresh number and the parquet is not.
        ledger_marks = {r.ticker: float(r.close) for r in pos.itertuples()
                        if pd.notna(r.close) and float(r.close) > 0}
        # The ledger supplies ATTRIBUTION, never existence. A name the account
        # holds none of is not this book's position no matter what the ledger
        # says -- seeding it would re-create the phantom the epoch exists to
        # clear (b6 carried 87 ANGL against a broker position of zero).
        acct, _ = broker_positions(set(held))
        phantom = [t for t in held if abs(acct.get(t, 0.0)) < 1]
        for t in phantom:
            held.pop(t)
        if phantom:
            print(f"  dropped {len(phantom)} phantom position(s) the account "
                  f"does not hold: {', '.join(sorted(phantom))}")
        src = "ledger (attribution-preserving)"
    else:
        held, ledger_marks = broker_positions(universe)
        src = "broker"
    if not held:
        raise SystemExit("broker reports no positions in this sleeve's universe; "
                         "refusing to seed an epoch from an unknown state")
    if ledger_marks:
        px = pd.Series(ledger_marks)
        mark_date = (str(pos["date"].max().date()) if a.from_ledger
                     else "broker live marks")
    else:
        px, mark_date = marks(universe, a.asof)

    rows, invested = [], 0.0
    for t in sorted(held):
        if t not in px or not pd.notna(px[t]):
            raise SystemExit(f"no mark for {t}; refusing to seed a position we "
                             f"cannot value")
        mv = held[t] * float(px[t])
        invested += mv
        rows.append({"date": a.asof, "ticker": t, "shares": held[t],
                     "close": float(px[t]), "market_value": mv,
                     "weight": mv / a.nav})
    cash = a.nav - invested

    old_nav = pd.read_csv(root / "nav.csv")
    old_tr = pd.read_csv(root / "trades.csv")
    print(f"EPOCH RESET — {a.sleeve}  ({'COMMIT' if a.commit else 'DRY RUN'})")
    print(f"  archiving : {len(old_nav)} nav row(s), {len(old_tr)} trade row(s)")
    print(f"  epoch date: {a.asof}   marks from {mark_date}")
    print(f"  declared NAV ${a.nav:,.0f} = cash ${cash:,.0f} + invested ${invested:,.0f}")
    print(f"  gross ${sum(abs(r['market_value']) for r in rows):,.0f}  "
          f"net ${invested:,.0f}  ({len(rows)} names, from the {src.upper()})\n")
    print(f"  {'ticker':<8}{'shares':>10}{'close':>9}{'mkt value':>13}{'weight':>9}")
    for r in sorted(rows, key=lambda x: -abs(x["market_value"])):
        print(f"  {r['ticker']:<8}{r['shares']:>10,.0f}{r['close']:>9.2f}"
              f"{r['market_value']:>13,.0f}{r['weight']:>9.4f}")

    if not a.commit:
        print("\n  DRY RUN — nothing written. Re-run with --commit.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arch = root.parent / f"_pre_epoch_{a.sleeve}_{stamp}"
    shutil.copytree(root, arch)
    print(f"\n  archived -> {arch}")

    # A fresh set. broker_fills.csv / slippage.csv are NOT rewritten: they are
    # the real execution record and the only independent check on all of this.
    pd.DataFrame(rows).to_csv(root / "positions.csv", index=False)
    pd.DataFrame([{
        "date": a.asof, "nav": a.nav, "cash": cash, "invested": invested,
        "distributions_usd": 0.0, "cost_usd": 0.0, "traded_usd": 0.0,
        "daily_return": "", "decision": "epoch",
    }]).to_csv(root / "nav.csv", index=False)
    for f, cols in (("trades.csv", list(old_tr.columns)),
                    ("orders.csv", list(pd.read_csv(root / "orders.csv").columns))):
        pd.DataFrame(columns=cols).to_csv(root / f, index=False)

    man = root / "manifest.json"
    m = json.loads(man.read_text()) if man.exists() else {}
    # The manifest's row counts MUST describe the files just written.
    # 2026-09-08: this block carried the archived book's counts forward
    # (orders 425, file 0 ...), so ops/ledger.py::_verify_manifest refused
    # every re-seeded book at the next session -- the cef run at 22:44 and
    # the five benchmark books at 17:25 all crashed in register_sleeve,
    # armed, before placing anything. Same shape as LongOnlySleeveLedger.save.
    m["files"] = {}
    for f in ("orders.csv", "trades.csv", "positions.csv", "nav.csv"):
        df = pd.read_csv(root / f)
        m["files"][f] = {"rows": int(len(df)),
                         "last_date": (str(df["date"].max())[:10]
                                       if len(df) and "date" in df else None)}
    m["version"] = m.get("version", 1)
    m["written_utc"] = pd.Timestamp.utcnow().isoformat()
    m.update({"epoch": a.asof, "epoch_nav": a.nav,
              "epoch_reason": "pre-epoch ledger booked 22 sessions of fills the "
                              "account never made (broker port misconfigured "
                              "2026-08-03..2026-09-03); archived, not deleted",
              "epoch_archive": arch.name, "epoch_written_utc": stamp})
    man.write_text(json.dumps(m, indent=2))
    print("  ledger re-seeded. broker_fills.csv and slippage.csv untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
