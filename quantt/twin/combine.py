"""Per-strategy targets -> one combined target per symbol -> one MOC order per symbol (two at a change of side). Pure.

THE ARITHMETIC (contract §4.1-4.2)
    slug target    a decided slug: its plan's whole shares; a held slug: the twin ledger's shares
    combined(sym)  = sum over slugs of their targets
    order(sym)     = combined(sym) - IBKR position(sym): buy if > 0, sell if < 0
Whole shares throughout (CLAUDE.md landmine 3), and NEVER BOTH SIDES of one symbol: the account can
never wash-trade with itself (contract §8 N7).

A CHANGE OF SIDE IS TWO ORDERS ON THE SAME SIDE (review of the build, 2026-11-25, finding 2; a
change to the contract's "one MOC order a symbol"). When the net order takes a symbol through
zero (long to short or short to long), the twin sends leg 1 to zero (`-1`) and leg 2 to open the
other side (`-2`), both the same side, leg 2 after leg 1 (`transmit_sequence` keeps that order).
Why: IBKR may refuse the short that opens (all short sales are subject to approval), and a
refused short must never block the reduction in front of it. The books' own flip rule
(decide.FLIP_SAME_SESSION, close today and open later) is kept in spirit: the closing leg goes
whatever happens to the opening one, and if leg 1 is refused leg 2 is not sent. The ledger books
the SUM of a symbol's fills (`ledger.apply`), as before.

HOLDS (review, finding 8). An events sleeve the plan marks `hold` is held at the TWIN ledger's
shares for that slug, not at the Alpaca events ledger's (the plan's targets for it describe the
Alpaca book's holdings, which the twin's need not equal); `flatten` is flattened; `decided` takes
the plan's targets.

THE EVENTS BOOK'S MINIMUM ORDER (the coordinator, 2026-11-25). The events runner sends no net order
under `min_order_usd` (ops/sleeves/events_sleeves.json). Where the events slugs' change in a symbol
is non-zero and below that many dollars at the plans' close, the events slugs HOLD their twin
shares in that symbol, so the twin trades what the events book trades. Core and C4 have no such
minimum here: the twin trades their targets to the share.

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

from quantt.twin.books import EVENTS_PREFIX, LEGACY, BookRead, SlugPlan, TwinRefused, slug_book

ORDER_TYPE = "MOC"
TIF = "DAY"


@dataclasses.dataclass(frozen=True)
class TwinOrder:
    symbol: str
    side: str            # buy | sell
    qty: int             # positive whole shares
    order_ref: str       # twin-<YYYYMMDD>-<SYMBOL>-<leg>
    current: int         # the position this leg starts from
    target: int          # the position this leg ends at
    est_price: float     # the plans' as-of close (an estimate; never sent)
    leg: int = 1         # 1, or 2 for the opening leg of a change of side

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


def order_ref(session_date: dt.date, symbol: str, leg: int = 1) -> str:
    return f"twin-{session_date:%Y%m%d}-{symbol}-{leg}"


def slug_plans(reads: dict, ledger_shares: dict) -> list:
    """Every slug's resolved targets for the session. `reads` is {book: BookRead}; `ledger_shares`
    is `ledger.shares_of(ledger)`. A held slug takes the twin ledger's shares; a slug the ledger
    holds that its book's decided plan does not list is flattened (its Alpaca book holds nothing
    there); `legacy` is flattened. Every slug the ledger holds must belong to a known book."""
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
            if sp.action == "hold" and sp.slug.startswith(EVENTS_PREFIX):
                sp = SlugPlan(sp.slug, "hold", sp.why or "the plan holds this sleeve",
                              dict(sorted(held.get(sp.slug, {}).items())), sp.dropped)
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


def apply_events_minimum(plans: list, ledger_shares: dict, prices: dict, min_usd: float) -> tuple:
    """(plans, held symbols): the events slugs held at their twin shares in every symbol whose
    events change is non-zero and below `min_usd` at `prices`. A symbol with no price whose events
    change is non-zero raises: whether it is under the minimum cannot be told."""
    ev = [p for p in plans if p.slug.startswith(EVENTS_PREFIX)]
    change: dict = {}
    for p in ev:
        h = ledger_shares.get(p.slug, {})
        for sym in set(p.targets) | set(h):
            change[sym] = change.get(sym, 0) + p.targets.get(sym, 0) - h.get(sym, 0)
    small = []
    for sym, d in sorted(change.items()):
        if d == 0:
            continue
        if sym not in prices:
            raise TwinRefused(f"events change {d:+d} in {sym} and no close to judge its minimum order")
        if abs(d) * prices[sym] < min_usd:
            small.append(sym)
    if not small:
        return plans, []
    out = []
    for p in plans:
        if not p.slug.startswith(EVENTS_PREFIX):
            out.append(p)
            continue
        h = ledger_shares.get(p.slug, {})
        t = dict(p.targets)
        for sym in small:
            t.pop(sym, None)
            if h.get(sym, 0):
                t[sym] = h[sym]
        out.append(SlugPlan(p.slug, p.action, p.why, dict(sorted(t.items())), p.dropped))
    return out, small


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
        side = "buy" if d > 0 else "sell"
        if cur != 0 and want != 0 and (cur > 0) != (want > 0):
            orders.append(TwinOrder(sym, side, abs(cur), order_ref(session_date, sym, 1), cur, 0, float(px), 1))
            orders.append(TwinOrder(sym, side, abs(want), order_ref(session_date, sym, 2), 0, want, float(px), 2))
        else:
            orders.append(TwinOrder(sym, side, abs(d), order_ref(session_date, sym, 1), cur, want, float(px), 1))
    if unpriced:
        raise TwinRefused(f"no as-of close for {unpriced}, which need an order; nothing is sent")
    seq = transmit_sequence(orders)
    sides: dict = {}
    for o in seq:
        if sides.setdefault(o.symbol, o.side) != o.side:
            raise AssertionError(f"both sides of {o.symbol}")
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
