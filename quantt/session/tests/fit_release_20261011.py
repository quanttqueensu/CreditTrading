"""The send-time fit AS RELEASED in release-20261011-1 (commit cd5082e), verbatim.

A REFERENCE FOR TESTS ONLY, never imported by the live path. The 2026-10-11
release-check found that its 0.05/0.01 grid search, ranked by the post-trade
net's distance from the full plan's rounded to the cent, kept 72% of the
2026-10-07 plan where about 98.7% fits (follow-up B). `run.fit_to_buying_power`
replaced it on 2026-10-13; `test_fit.py` checks the replacement keeps at least
as much as this on every case it draws, and never breaks a limit. The body
below is byte-for-byte the released function, renamed; that was checked
against `git show release-20261011-1:quantt/session/run.py` when this file was
written (2026-10-13).
"""
import itertools  # noqa: F401  (imported inside the released body as well)
import math

from quantt.session import decide as dec
from quantt.session import gate as gt
from quantt.session.run import SessionError, _opening_part


def fit_release_20261011(orders, positions: dict, closes: dict, equity: float,
                        buying_power: float, current_gross: float,
                        maintenance_margin: float, *, max_gross_stress: float | None,
                        sized_equity: float) -> tuple[tuple, float, str | None]:
    """Scale the plan so it fits Alpaca's order-time buying power, the
    overnight margin limits and the spec's stress cap (gate.buying_power_needed /
    gate.margin_limits / gate.stress_breach). Returns (orders, kept, binding
    constraint or None when nothing was scaled); `kept` is the share of the
    plan's traded notional kept.

    THE STRESS CAP (2026-10-09, 2026-10-11). Scaling reductions for neutrality
    (below) can leave more gross than the plan, so a fitted plan could break
    `gate.stress_breach` when the full plan did not. The cap is therefore one of
    the limits fitted to, read exactly as the gate reads it: against the lower
    of the equity the plan was SIZED on and `equity` (live at send), and only
    when the plan adds to the gross held now. So when equity has fallen since
    decide, a plan that adds gross is scaled down here, not refused at the gate.
    All-zero (send nothing) never breaks it.

    NOTHING FITS (2026-10-09 audit). If the book held now already breaks a
    limit and no scaling of the plan fixes that, the plan is returned UNSCALED,
    with the binding limit named. The gate then refuses it with its own
    sentence. Until then `coarse[1]` raised a TypeError on None, and the session
    ended FAIL with a traceback instead of a refusal saying why.

    WHY (team lead 2026-10-07, after the execution-desk review): refusing a plan
    that does not fit leaves yesterday's stale book; skipping names breaks
    neutrality arbitrarily.

    NEUTRALITY (review 2026-10-07): scaling only the openings is NOT neutral
    when a plan rotates a leg -- covering one short in full while opening the
    replacement short scaled ended +$20.9k net long in the review's case. So
    four factors are chosen -- opening buys, opening sells, reducing buys,
    reducing sells -- to (1) satisfy every limit, (2) keep the post-trade net
    closest to the full plan's post-trade net, (3) then keep the most traded
    notional. Searched on a 0.05 grid, then refined on 0.01 around the best.
    Reductions consume no buying power (Alpaca: they do not replenish it until
    executed, and they never use it), so they are scaled only when neutrality
    needs it. Called at DECIDE (as-of closes, evening
    account) and again at SEND on the live account, so a plan sitting on the
    limit at decide is not refused by a small adverse move by 15:52.

    Flips are deferred (decide.FLIP_SAME_SESSION), so every order is wholly
    opening or wholly reducing; a leg-2 order is refused here rather than
    mis-sized. A name without a close is left to the gate's clean refusal.

    WHOLE SHARES (release-check 2026-10-11). The search scales in fractions,
    so each order is then rounded to whole shares, in the direction that can
    only lower gross: an opening order DOWN, a reducing order UP (capped at its
    own quantity, so it never crosses zero). Until 2026-10-11 every order was
    floored, which covers LESS of a reducing order and leaves MORE gross than
    the fractional plan the search accepted. Both reviewers reproduced a fitted
    plan that gate 8 then refused on the very stress cap it was fitted to (about
    1 in 100 synthetic cases where the cap binds): a missed day, the 2026-10-09
    failure. Rounded this way, gross and the buying power needed are never above
    the fractional plan's, and every limit here is monotone in them. The rounded
    plan is still re-checked; if it broke a limit anyway it would be returned
    unscaled for the gate to refuse, never sent above a limit.
    """
    import dataclasses
    import itertools
    if any(o.leg != 1 for o in orders):
        raise SessionError("fit_to_buying_power: same-session flip legs are not supported "
                           "(FLIP_SAME_SESSION is False); refusing to size them")
    names = set(positions) | {o.symbol for o in orders}
    if any(not isinstance(closes.get(s), (int, float)) or closes[s] <= 0 for s in names):
        return tuple(orders), 1.0, None
    ratio = None
    if current_gross > 0:
        if maintenance_margin <= 0:
            raise SessionError(f"maintenance_margin {maintenance_margin} with current gross "
                               f"{current_gross}: the maintenance ratio cannot be measured")
        ratio = maintenance_margin / current_gross

    def bucket(o):
        opening = _opening_part(o, positions.get(o.symbol, 0)) > 0
        return ("o" if opening else "r") + ("b" if o.side == "buy" else "s")
    buckets = ("ob", "os", "rb", "rs")
    by = {o.client_order_id: bucket(o) for o in orders}
    untouched = {s: q for s, q in positions.items() if s not in {o.symbol for o in orders}}
    held = sum(abs(q) * closes[s] for s, q in positions.items())

    def book(f):
        """Post-trade positions with each order scaled by its bucket's factor."""
        after = dict(untouched)
        for o in orders:
            cur = positions.get(o.symbol, 0)
            after[o.symbol] = cur + f[by[o.client_order_id]] * o.signed_qty
        return after

    def breach(after, need):
        """The first limit the post-trade book `after` breaks, or None."""
        gross = sum(abs(q) * closes[s] for s, q in after.items())
        return ("order-time buying_power" if need > buying_power else
                "overnight Reg T initial margin" if gt.REG_T_INITIAL * gross > equity else
                "overnight maintenance (measured ratio)"
                if ratio is not None and ratio * gross > equity else
                "max_gross_stress (on the lower of sized and live equity)"
                if gt.stress_breach(gross, held, max_gross_stress, sized_equity, equity) else None)

    def bp_need(qty_of):
        return sum(qty_of(o) * closes[o.symbol]
                   * (gt.SHORT_ORDER_BP_MULTIPLIER if o.side == "sell" else 1.0)
                   for o in orders if by[o.client_order_id][0] == "o")

    def evaluate(f):
        after = book(f)
        net = sum(q * closes[s] for s, q in after.items())
        why = breach(after, bp_need(lambda o: f[by[o.client_order_id]] * o.qty))
        traded = sum(f[by[o.client_order_id]] * o.qty * closes[o.symbol] for o in orders)
        return why, net, traded

    full = {b: 1.0 for b in buckets}
    binding, full_net, full_traded = evaluate(full)
    if binding is None:
        return tuple(orders), 1.0, None
    present = {b for b in by.values()}

    def search(values):
        best = None
        for combo in itertools.product(*[(values(b) if b in present else (1.0,)) for b in buckets]):
            f = dict(zip(buckets, combo))
            why, net, traded = evaluate(f)
            if why:
                continue
            key = (round(abs(net - full_net), 2), -traded)
            if best is None or key < best[0]:
                best = (key, f)
        return best
    coarse = search(lambda b: [i / 20 for i in range(21)])
    if coarse is None:
        # Even all-zero breaks a limit: the book held NOW is past it (docstring,
        # NOTHING FITS). Unscaled, so the gate refuses it and says which limit.
        return tuple(orders), 1.0, f"{binding} (no scaling fits: the book held now is past it)"
    c0 = coarse[1]
    fine = search(lambda b: sorted({min(1.0, max(0.0, round(c0[b] + d / 100, 2)))
                                    for d in range(-5, 6)}))
    f = (fine or coarse)[1]
    whole = {}                    # client_order_id -> whole shares (docstring, WHOLE SHARES)
    for o in orders:
        k = f[by[o.client_order_id]]
        if k >= 1.0:
            whole[o.client_order_id] = o.qty
        elif by[o.client_order_id][0] == "o":
            whole[o.client_order_id] = math.floor(o.qty * k)
        else:
            whole[o.client_order_id] = min(o.qty, math.ceil(o.qty * k))
    after = dict(untouched)
    for o in orders:
        after[o.symbol] = positions.get(o.symbol, 0) + whole[o.client_order_id] * (1 if o.side == "buy" else -1)
    still = breach(after, bp_need(lambda o: whole[o.client_order_id]))
    if still:
        return tuple(orders), 1.0, (f"{still} (the whole-share fit still breaks it: returned "
                                    f"unscaled for the gate to refuse)")
    out = []
    for o in orders:
        q = whole[o.client_order_id]
        if q == o.qty:
            out.append(o)
        elif q > 0:
            k = f[by[o.client_order_id]]
            out.append(dataclasses.replace(o, qty=q, target=o.current + (q if o.side == "buy" else -q),
                                           reason=f"{o.reason}; scaled x{k:.2f} to fit {binding}"))
    _, _, traded = evaluate(f)
    return dec.transmit_sequence(out), (traded / full_traded if full_traded else 1.0), binding
