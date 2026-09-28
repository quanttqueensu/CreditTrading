"""Flatten the whole IBKR paper account in one closing auction, then prove it is flat.

HUMAN-RUN ONLY. This can transmit orders (CLAUDE.md order-path rule 1): an agent
wrote it and tested it against a fake broker, and never ran it. The team lead
runs it with `!`.

WHY IT EXISTS
-------------
Team lead, 2026-09-28: retire IBKR entirely -- "flatten everything, archive it,
forget about it" -- and move to Alpaca (results/ops/ALPACA_MIGRATION_MANIFEST_
2026-09-28.md §5). Every book goes, so the target is the ACCOUNT NET. This is
the one tool in the repo where reading a symbol from the account net is right:
the per-sleeve attribution rule (CLAUDE.md landmine 7) exists to stop one book
trading another's shares, and after this there are no books.

WHY IT LOOKS LIKE THIS
----------------------
- **MOC, never a market order** (order-path rule 3). A market order sent outside
  the session rests and fills at the next open; on 2026-07-31 that cost 100.5bp
  against a 32.6bp breakeven. MOC fills in the closing auction.
- **Dry run is the default and connects read-only** (`readonly=True`), so the
  default invocation cannot transmit even by a bug in this file. `--transmit`
  is required to send, `DRY_RUN=1` in the environment always wins over it
  (order-path rule 4), and `--account` must name the account the broker reports,
  so the send is a deliberate act about a specific account.
- **Not idempotent, so it refuses a second run** (order-path rule 2). The broker
  does not dedupe, and positions do not include unfilled MOC orders: a second
  run before the close would send the same set again and the auction would
  fill both -- turning "flat" into "the whole book, reversed". Two guards:
  any open order at the broker (any client) refuses, and a local record marked
  `transmit_started` for today refuses. The record is written BEFORE the first
  order goes, so a crash mid-send still blocks the rerun.
- **Refuses what it cannot close by MOC** rather than doing part of it silently:
  non-stock positions (options, bonds), non-USD positions, fractional share
  counts, and more than one account in the session. It lists them; a human
  closes those by hand.
- **Refuses after the MOC cutoff.** NYSE stops accepting MOC entries at 15:50 ET
  and will not cancel one after it; the cutoff here is 15:40 ET (12:40 on the
  standard early-close days), leaving room to read the plan. It also refuses on
  a non-trading day (`ops/schedule/nyse_calendar.py`).
- **Client id 131**, unused by any caller in docs/INFRASTRUCTURE.md §6.2 --
  a collision silently evicts the other session.

USAGE (the team lead, with `!`)
-------------------------------
    python3 -m ops.flatten_ibkr_account                        # dry run: read-only, prints the plan
    python3 -m ops.flatten_ibkr_account --transmit --account DU1234567
    python3 -m ops.flatten_ibkr_account --verify               # next morning: flat? any open orders?

Every run writes `results/ops/ibkr_flatten/<date>.json`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "results" / "ops" / "ibkr_flatten"
CLIENT_ID = 131
ET = ZoneInfo("America/New_York")
CUTOFF = dt.time(15, 40)
EARLY_CUTOFF = dt.time(12, 40)


class Refused(RuntimeError):
    """The flatten will not proceed. The message says why and what to do."""


# ---------------------------------------------------------------------------
# calendar
# ---------------------------------------------------------------------------

def _is_early_close(d: dt.date) -> bool:
    """NYSE's standard 13:00 closes: Jul 3, the day after Thanksgiving, Dec 24
    (each only when it is itself a trading day). Not in nyse_calendar, which
    treats them as ordinary trading days because its jobs ran after 1pm."""
    if (d.month, d.day) in ((7, 3), (12, 24)):
        return True
    if d.month == 11 and d.weekday() == 4:          # a Friday in November
        thursdays = [x for x in range(1, 31) if dt.date(d.year, 11, x).weekday() == 3]
        return d.day == thursdays[3] + 1             # day after the 4th Thursday
    return False


def check_window(now_et: dt.datetime) -> None:
    from ops.schedule import nyse_calendar
    d = now_et.date()
    if not nyse_calendar.is_trading_day(d):
        raise Refused(f"{d} is not an NYSE trading day; there is no closing auction.")
    cutoff = EARLY_CUTOFF if _is_early_close(d) else CUTOFF
    if now_et.time() >= cutoff:
        raise Refused(
            f"it is {now_et:%H:%M} ET, past this tool's {cutoff:%H:%M} cutoff for "
            f"{d} (NYSE takes no MOC entries after 15:50, and cancels none). "
            f"Run it tomorrow before the cutoff.")


# ---------------------------------------------------------------------------
# the plan -- pure, so it is testable without a broker
# ---------------------------------------------------------------------------

def build_plan(positions) -> dict:
    """ib.positions() -> {account, orders, refused}. Raises Refused if anything
    in the account cannot be closed by a whole-share USD stock MOC."""
    accounts = sorted({p.account for p in positions})
    if len(accounts) > 1:
        raise Refused(f"the session sees {len(accounts)} accounts {accounts}; "
                      f"this tool flattens exactly one. Log in to the paper account only.")
    orders, problems = [], []
    for p in positions:
        c, qty = p.contract, float(p.position)
        if qty == 0:
            continue                     # IBKR can report a closed row as 0
        tag = f"{c.symbol} ({c.secType}, {c.currency}) qty {qty:g}"
        if c.secType != "STK":
            problems.append(f"{tag}: not a stock -- close by hand")
        elif c.currency != "USD":
            problems.append(f"{tag}: not USD -- close by hand")
        elif qty != int(qty):
            problems.append(f"{tag}: fractional share count -- close by hand")
        else:
            orders.append({"symbol": c.symbol, "conId": int(c.conId),
                           "position": int(qty),
                           "action": "SELL" if qty > 0 else "BUY",
                           "quantity": abs(int(qty))})
    if problems:
        raise Refused("positions this tool will not close by MOC:\n  "
                      + "\n  ".join(problems))
    orders.sort(key=lambda o: o["symbol"])
    return {"account": accounts[0] if accounts else None, "orders": orders}


def check_no_open_orders(open_trades) -> None:
    live = [t for t in open_trades
            if t.orderStatus.status not in ("Cancelled", "ApiCancelled", "Filled", "Inactive")]
    if live:
        desc = [f"{t.contract.symbol} {t.order.action} {t.order.totalQuantity:g} "
                f"{t.order.orderType} ({t.orderStatus.status}, client {t.order.clientId})"
                for t in live]
        raise Refused(
            "the broker shows open orders, so a flatten now could stack on them in "
            "the same auction:\n  " + "\n  ".join(desc)
            + "\nWait for them to fill or expire, or cancel them by hand, then re-run.")


def check_not_already_sent(record_path: Path) -> None:
    if record_path.exists():
        rec = json.loads(record_path.read_text())
        if rec.get("transmit_started"):
            raise Refused(
                f"{record_path.relative_to(REPO)} says a flatten was already "
                f"transmitted today ({rec['transmit_started']}). Positions do not "
                f"include unfilled MOC orders, so sending again would double it. "
                f"Check tomorrow with --verify.")


# ---------------------------------------------------------------------------
# broker I/O
# ---------------------------------------------------------------------------

def _ib_module():
    """ib_async, never bare ib_insync (CLAUDE.md landmine 8)."""
    try:
        import ib_async as ibi
    except ImportError:
        import ib_insync as ibi
    return ibi


def _connect(readonly: bool):
    ibi = _ib_module()
    sys.path.insert(0, str(REPO))
    from src.deploy.broker.ibkr import IBKRConfig
    cfg = IBKRConfig.from_env(REPO)
    ib = ibi.IB()
    ib.connect(cfg.host, cfg.port, clientId=CLIENT_ID, readonly=readonly, timeout=20)
    return ibi, ib


def moc_order(ibi, action: str, quantity: int):
    """The same MOC shape the live path used (`IBKRBroker._order`)."""
    o = ibi.Order()
    o.action = action
    o.totalQuantity = quantity
    o.orderType = "MOC"
    o.tif = "DAY"            # IB rejects an MOC with an empty TIF
    return o


def transmit(ib, ibi, plan: dict, record: dict, record_path: Path) -> None:
    record["transmit_started"] = dt.datetime.now(ET).isoformat()
    record["sent"] = []
    _write(record_path, record)                  # BEFORE the first order
    trades = []
    for o in plan["orders"]:
        contract = ibi.Contract(conId=o["conId"], exchange="SMART")
        trade = ib.placeOrder(contract, moc_order(ibi, o["action"], o["quantity"]))
        trades.append(trade)
        record["sent"].append({**o, "orderId": trade.order.orderId,
                               "status": trade.orderStatus.status})
        _write(record_path, record)
    ib.sleep(2)
    # A rejected MOC shows here, not at placeOrder; the human reads this line.
    for s, t in zip(record["sent"], trades):
        s["status_after_2s"] = t.orderStatus.status
    _write(record_path, record)


def _write(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, default=str))
    tmp.replace(path)


def _print_plan(plan: dict) -> None:
    print(f"account: {plan['account']}   orders: {len(plan['orders'])}")
    for o in plan["orders"]:
        print(f"  {o['action']:<4} {o['quantity']:>8} {o['symbol']:<6} MOC   "
              f"(holding {o['position']:+d})")


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--transmit", action="store_true",
                   help="send the MOC orders (requires --account; DRY_RUN=1 blocks it)")
    g.add_argument("--verify", action="store_true",
                   help="read-only: is the account flat with no open orders?")
    ap.add_argument("--account", help="the account id the broker reports; required with --transmit")
    args = ap.parse_args(argv)

    now = dt.datetime.now(ET)
    record_path = OUT_DIR / f"{now.date()}.json"

    if args.verify:
        _, ib = _connect(readonly=True)
        try:
            pos = [p for p in ib.positions() if float(p.position) != 0]
            opn = ib.reqAllOpenOrders()
        finally:
            ib.disconnect()
        rec = {"verified_at": now.isoformat(),
               "positions": [{"account": p.account, "symbol": p.contract.symbol,
                              "secType": p.contract.secType, "position": float(p.position)}
                             for p in pos],
               "open_orders": len(opn)}
        _write(OUT_DIR / f"{now.date()}_verify.json", rec)
        flat = not pos and not opn
        print("FLAT, no open orders" if flat else
              f"NOT FLAT: {len(pos)} position(s), {len(opn)} open order(s)")
        for p in rec["positions"]:
            print(f"  {p['symbol']:<8} {p['secType']:<4} {p['position']:+g}")
        return 0 if flat else 1

    if args.transmit:
        if os.environ.get("DRY_RUN") == "1":
            print("REFUSED: DRY_RUN=1 is set; a human hard halt always wins.")
            return 3
        if not args.account:
            print("REFUSED: --transmit needs --account <the id the dry run printed>.")
            return 3

    try:
        check_window(now)
        check_not_already_sent(record_path)
        ibi, ib = _connect(readonly=not args.transmit)
        try:
            check_no_open_orders(ib.reqAllOpenOrders())
            plan = build_plan(ib.positions())
            _print_plan(plan)
            record = {"planned_at": now.isoformat(), "mode": "transmit" if args.transmit else "dry_run",
                      "client_id": CLIENT_ID, **plan}
            if not args.transmit:
                _write(OUT_DIR / f"{now.date()}_dryrun.json", record)
                print("\nDRY RUN -- nothing sent. To send:  python3 -m ops.flatten_ibkr_account "
                      f"--transmit --account {plan['account']}")
                return 0
            if args.account != plan["account"]:
                raise Refused(f"--account {args.account} is not the account the broker "
                              f"reports ({plan['account']}).")
            if not plan["orders"]:
                print("already flat -- nothing to send.")
                return 0
            transmit(ib, ibi, plan, record, record_path)
        finally:
            ib.disconnect()
    except Refused as e:
        print(f"REFUSED: {e}")
        return 2
    print(f"\nSENT {len(record['sent'])} MOC orders -> {record_path.relative_to(REPO)}")
    print("They fill in today's closing auction. Tomorrow: python3 -m ops.flatten_ibkr_account --verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
