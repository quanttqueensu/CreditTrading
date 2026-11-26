"""Per-strategy targets -> one combined target per symbol -> one MOC order per symbol. Pure.

THE ARITHMETIC (contract §4.1-4.2)
    slug target    a decided slug: its plan's whole shares; a held slug: the twin ledger's shares
    combined(sym)  = sum over slugs of their targets
    order(sym)     = combined(sym) - IBKR position(sym), ONE order, buy if > 0, sell if < 0
Whole shares throughout (CLAUDE.md landmine 3), and never both sides of one symbol: there is one
number per symbol, so the account can never wash-trade with itself (contract §8 N7). A long-to-
short flip is ONE order at IBKR, which allows it; Alpaca's two-order rule (landmine 4) is Alpaca's.

WHO OWNS A FILL is not decided here: `quantt/sleeves/ledger.apply` shares each symbol's fill
between the slugs at verify, by the events book's own rules (the side opposite the net is met in
full inside the account; the net side shares the fill in proportion; a symbol crossed completely
books at the official close).

THE ORDER LIST is put in `quantt.session.decide.transmit_sequence` order, the books' own: the
running net dollar change kept near zero after every order, so a batch stopped part-way leaves the
account as close to neutral as it can. `plan_sha` hashes exactly what is transmitted (order ref,
symbol, side, quantity, MOC, DAY), in that order: what the team lead approves is what goes.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json

from quantt.twin.books import LEGACY, BookRead, SlugPlan, TwinRefused, slug_book

ORDER_TYPE = "MOC"
TIF = "DAY"


@dataclasses.dataclass(frozen=True)
class TwinOrder:
    symbol: str
    side: str            # buy | sell
    qty: int             # positive whole shares
    order_ref: str       # twin-<YYYYMMDD>-<SYMBOL>
    current: int         # IBKR position before
    target: int          # the combined target after
    est_price: float     # the plans' as-of close (an estimate; never sent)
    leg: int = 1         # always 1: one order a symbol (transmit_sequence reads it)

    @property
    def signed_qty(self) -> int:
        return self.qty if self.side == "buy" else -self.qty

    @property
    def est_notional(self) -> float:
        return self.qty * self.est_price

    @property
    def opens_short(self) -> bool:
        after = self.current + self.signed_qty
        return self.side == "sell" and after < min(self.current, 0)

    def wire(self) -> dict:
        return {"order_ref": self.order_ref, "symbol": self.symbol, "side": self.side, "qty": self.qty,
                "order_type": ORDER_TYPE, "tif": TIF}

    def to_dict(self) -> dict:
        return {**dataclasses.asdict(self), "est_notional": self.est_notional}


def order_ref(session_date: dt.date, symbol: str) -> str:
    return f"twin-{session_date:%Y%m%d}-{symbol}"


def slug_plans(reads: dict, ledger_shares: dict) -> list:
    """Every slug's resolved targets for the session. `reads` is {book: BookRead}; `ledger_shares`
    is `ledger.shares_of(ledger)`. A held slug takes the ledger's shares; a slug the ledger holds
    that its book's decided plan does not list is flattened (its Alpaca book holds nothing there);
    `legacy` is flattened. Every slug the ledger holds must belong to a known book."""
    held = {s: dict(q) for s, q in ledger_shares.items()}
    for s in held:
        slug_book(s)
    out = []
    for name in ("cef", "c4", "events"):
        r: BookRead = reads[name]
        mine = sorted(s for s in held if slug_book(s) == name)
        if r.status != "decided":
            for s in mine:
                out.append(SlugPlan(s, "hold", f"{name}: {r.why}", dict(sorted(held[s].items()))))
            continue
        listed = set()
        for sp in r.slugs:
            listed.add(sp.slug)
            out.append(sp)
        for s in mine:
            if s not in listed and any(held[s].values()):
                out.append(SlugPlan(s, "flatten", f"{name}'s plan does not list {s}", {}))
    if any(held.get(LEGACY, {}).values()):
        out.append(SlugPlan(LEGACY, "flatten", "the account's positions at the epoch: no plan, target zero", {}))
    for sp in out:
        if sp.targets is None:
            raise TwinRefused(f"{sp.slug}: unresolved targets")
        for sym, q in sp.targets.items():
            if type(q) is not int:
                raise TwinRefused(f"{sp.slug} target {sym} = {q!r} is not whole shares")
    return out


def combined(plans: list) -> dict:
    tot: dict = {}
    for sp in plans:
        for sym, q in sp.targets.items():
            tot[sym] = tot.get(sym, 0) + q
    return dict(sorted(tot.items()))


def make_orders(plans: list, positions: dict, session_date: dt.date, prices: dict) -> tuple:
    """(orders in transmit order, {symbol: combined target}). `prices` must hold every symbol
    that gets an order; one without raises naming it (an estimate is needed to sequence and to
    judge buying power, and none is invented)."""
    from quantt.session.decide import transmit_sequence
    tgt = combined(plans)
    for s, q in positions.items():
        if type(q) is not int:
            raise TwinRefused(f"IBKR position {s} = {q!r} is not whole shares")
    orders, unpriced = [], []
    for sym in sorted(set(tgt) | set(positions)):
        cur, want = positions.get(sym, 0), tgt.get(sym, 0)
        d = want - cur
        if d == 0:
            continue
        px = prices.get(sym)
        if px is None:
            unpriced.append(sym)
            continue
        orders.append(TwinOrder(sym, "buy" if d > 0 else "sell", abs(d), order_ref(session_date, sym),
                                cur, want, float(px)))
    if unpriced:
        raise TwinRefused(f"no as-of close for {unpriced}, which need an order; nothing is sent")
    seq = transmit_sequence(orders)
    assert len({o.symbol for o in seq}) == len(seq), "two orders in one symbol"
    return tuple(seq), tgt


def plan_sha(orders) -> str:
    payload = json.dumps([o.wire() for o in orders], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def order_table(orders) -> str:
    rows = [f"{'symbol':<8}{'side':<6}{'qty':>8}{'current':>10}{'target':>10}{'est px':>10}{'est $':>12}"]
    for o in orders:
        rows.append(f"{o.symbol:<8}{o.side:<6}{o.qty:>8}{o.current:>10}{o.target:>10}"
                    f"{o.est_price:>10.2f}{o.est_notional:>12,.0f}")
    rows.append(f"{len(orders)} MOC order(s), est. ${sum(o.est_notional for o in orders):,.0f} traded")
    return "\n".join(rows)
