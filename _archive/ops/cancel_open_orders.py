"""Cancel the resting orders one book's API client left at the broker.

    python3 ops/cancel_open_orders.py --client-id 45            # list only
    python3 ops/cancel_open_orders.py --client-id 45 --confirm  # cancel them

WHY THIS EXISTS
---------------
An MOC order placed after the close rests at IB until the NEXT session's
auction. On 2026-09-04 17:58 the cef job transmitted 17 of them ($223k, 44.7%
of the book) under the 2-day calendar policy. Over the weekend the band replaced
that policy and the ledger was re-seeded (epoch 2026-09-08), so on Tuesday
morning the account held a full rebalance the live policy had not asked for,
still PreSubmitted, due to fill at 16:00. Letting it fill would have cost a
$223k round trip -- the band wanted $60k of it back the next evening -- and
put a 45% session at the top of the pre-registered turnover readout.

cef.env has said "cancel pending orders before re-running by hand" since
2026-07-31 without there being anything to do it with. This is that tool.

WHAT IT TOUCHES
---------------
Only orders whose `clientId` equals --client-id. Each book has its own id
(cef 45, benchmarks 46, phase0 in phase0.env), so one book's cancel cannot
reach another's. It connects AS that client, because IB lets a client cancel
only its own orders (or a master client everyone's, which we do not configure).
Nothing is transmitted. Without --confirm it lists and exits.

Do not run while that book's session is armed: two clients cannot share an id
and the session would fail to connect.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--client-id", type=int, required=True,
                    help="the book's IBKR_CLIENT_ID from ops/schedule/<job>.env")
    ap.add_argument("--symbols", default="",
                    help="optional comma list; cancel only these symbols")
    ap.add_argument("--confirm", action="store_true",
                    help="actually cancel; without it, list only")
    a = ap.parse_args(argv)

    import ib_async as ibapi
    from src.deploy.broker.ibkr import IBKRConfig
    cfg = IBKRConfig.from_env()
    only = {s.strip().upper() for s in a.symbols.split(",") if s.strip()}

    ib = ibapi.IB()
    try:
        ib.connect(cfg.host, int(cfg.port), clientId=a.client_id,
                   readonly=not a.confirm, timeout=25)
    except Exception as exc:
        print(f"cannot connect to {cfg.host}:{cfg.port} as client "
              f"{a.client_id}: {exc!r}")
        return 2
    try:
        ib.reqAllOpenOrders()
        ib.sleep(3)
        mine = [t for t in ib.openTrades()
                if t.order.clientId == a.client_id
                and (not only or t.contract.symbol in only)]
        others = [t for t in ib.openTrades() if t not in mine]
        print(f"client {a.client_id}: {len(mine)} resting order(s)"
              f"{' matching --symbols' if only else ''}; "
              f"{len(others)} belong to other clients and are left alone")
        for t in sorted(mine, key=lambda t: t.contract.symbol):
            o, s = t.order, t.orderStatus
            print(f"  {t.contract.symbol:<5} {o.action:<4} {o.totalQuantity:>7.0f} "
                  f"{o.orderType:<4} {s.status:<12} permId={o.permId}")
        if not mine:
            return 0
        if not a.confirm:
            print("\nlist only -- re-run with --confirm to cancel these")
            return 0

        for t in mine:
            ib.cancelOrder(t.order)
        ib.sleep(4)
        ib.reqAllOpenOrders()
        ib.sleep(3)
        left = [t for t in ib.openTrades()
                if t.order.clientId == a.client_id
                and (not only or t.contract.symbol in only)]
        if left:
            print(f"\nSTILL OPEN after cancel ({len(left)}):")
            for t in left:
                print(f"  {t.contract.symbol:<5} {t.order.action} "
                      f"{t.order.totalQuantity:.0f} {t.orderStatus.status}")
            return 1
        print(f"\ncancelled {len(mine)}; client {a.client_id} has no resting "
              f"orders. Remaining at the broker: {len(ib.openTrades())}")
        for t in sorted(ib.openTrades(), key=lambda t: t.contract.symbol):
            print(f"  {t.contract.symbol:<5} {t.order.action} "
                  f"{t.order.totalQuantity:.0f} client={t.order.clientId}")
        return 0
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
