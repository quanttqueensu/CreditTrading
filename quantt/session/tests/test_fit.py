"""run.fit_to_buying_power: it keeps the largest neutral share of the plan that fits.

Release-check 2026-10-11, follow-up B (the execution desk's finding). The fit as
released searched four scale factors on a 0.05 grid refined on 0.01, ranked by
the post-trade net's distance from the full plan's rounded to the cent, then by
traded notional. On the 2026-10-07 plan with equity 0.5% lower at send it kept
72% of the traded notional where about 98.7% fits. It failed safe (never above
a limit, never a refusal, never the wrong side), so the cost was trade, not
safety. Since 2026-10-13 the same objectives are solved exactly.

What these tests hold the fit to, on every case:
  * the plan it returns passes gate 8 term for term (`gate.gate_exposure`);
  * every order stays wholly opening or wholly reducing, on its own side, no
    larger than the plan's: each name ends between where it is now and where
    the full plan would put it, so nothing flips side;
  * it keeps at least as much of the plan as the released fit
    (`fit_release_20261011`, a verbatim copy, for reference only), except
    where it buys at least as much neutrality as it gives up in trade (the
    2026-10-07 rule puts the full plan's net first; 3 of 1,741 scaled draws in
    the 2026-10-13 run of 2,400, each the grid too coarse to trim a large
    reduction, all within 0.37 points of kept);
  * it keeps all but whole-share rounding of the best fractional plan found by an
    INDEPENDENT solver (scipy's linear program over the four bucket factors),
    at that plan's neutrality, again within rounding.
The cases are synthetic (seeded draws): they test our code, not a claim about
the market. `QUANTT_FIT_CASES=<n>` runs more of them (the default keeps the
suite fast; the released fit takes ~0.3 s a case).
"""
import os
import random

import pytest

from quantt.session import gate as gt
from quantt.session import run as rn
from quantt.session.decide import Order
from quantt.session.tests.fit_release_20261011 import fit_release_20261011

M = gt.SHORT_ORDER_BP_MULTIPLIER


def _o(sym, side, qty, cur, px):
    return Order(symbol=sym, side=side, qty=qty, leg=1, client_order_id=f"cef-20261007-{sym}-1",
                 current=cur, target=cur + (qty if side == "buy" else -qty), est_price=px,
                 reason="t", time_in_force="day")


def _kept(out, orders, closes) -> float:
    full = sum(o.qty * closes[o.symbol] for o in orders)
    return sum(o.qty * closes[o.symbol] for o in out) / full


def _net(orders, pos, closes) -> float:
    return sum(q * closes[s] for s, q in gt.projected_positions(orders, pos).items())


def _gate(out, pos, closes, kw):
    return gt.gate_exposure(out, pos, closes, kw["equity"], kw["buying_power"], 1e18,
                            kw["max_gross_stress"], sized_equity=kw["sized_equity"],
                            current_gross=kw["current_gross"],
                            maintenance_margin=kw["maintenance_margin"])


# ---------------------------------------------------- the 2026-10-07 plan (recorded)

# The plan the laptop prod decided at 22:00 ET on 2026-10-06 for 2026-10-07
# (state dir 2026-10-07/plan.json, plan_sha e0d92f17..., as-of 2026-10-06), and
# the account that decide measured (runs/20261007T020005Z-run.json). Positions
# equal the plan's `current`. (symbol, side, qty, current position)
P1007_ORDERS = (
    ("PDI", "sell", 3, 214), ("PTY", "buy", 4, -321), ("PDO", "sell", 10, 335),
    ("MHD", "buy", 22, -1931), ("PHK", "sell", 45, 4019), ("PFN", "buy", 108, 1995),
    ("MQY", "sell", 130, -1774), ("PCN", "buy", 85, 428), ("AWF", "sell", 254, 0),
    ("JFR", "sell", 2340, -3067), ("BIT", "buy", 1944, 809), ("DSL", "buy", 2382, 0),
)
P1007_POSITIONS = {"BIT": 809, "JFR": -3067, "MHD": -1931, "MQY": -1774, "PCN": 428,
                   "PDI": 214, "PDO": 335, "PFN": 1995, "PHK": 4019, "PTY": -321}
P1007_CLOSES = {"AWF": 9.630000114440918, "BIT": 11.239999771118164,
                "DSL": 9.899999618530273, "HYT": 7.809999942779541, "JFR": 7.380000114440918,
                "MHD": 10.229999542236328, "MQY": 9.9399995803833, "PCN": 10.789999961853027,
                "PDI": 14.399999618530273, "PDO": 12.079999923706055,
                "PFN": 6.320000171661377, "PHK": 4.199999809265137, "PTY": 10.890000343322754}
P1007_SIZED = 100_735.22
P1007_ACCOUNT = dict(buying_power=187_344.34, current_gross=50_247.5 + 63_514.63,
                     maintenance_margin=53_899.13, max_gross_stress=1.8, sized_equity=P1007_SIZED)


def test_the_2026_10_07_plan_after_a_half_percent_dip_keeps_what_fits():
    """The reviewer's case: the recorded plan (gross 1.7994x the sized equity, the
    sleeve's cap binding) sent on equity 0.5% lower, so the stress cap on live
    equity binds by ~$850. The released fit kept 72.0%; cutting both sides
    equally keeps ~98.7%. The dip is hypothetical: that day's equity rose."""
    orders = tuple(_o(s, side, q, cur, P1007_CLOSES[s]) for s, side, q, cur in P1007_ORDERS)
    kw = dict(P1007_ACCOUNT, equity=P1007_SIZED * 0.995)
    out, kept, why = rn.fit_to_buying_power(orders, P1007_POSITIONS, P1007_CLOSES, **kw)
    assert why == "max_gross_stress (on the lower of sized and live equity)"
    assert _gate(out, P1007_POSITIONS, P1007_CLOSES, kw) == []
    assert _kept(out, orders, P1007_CLOSES) >= 0.98
    assert kept == pytest.approx(_kept(out, orders, P1007_CLOSES))   # whole shares, as sent
    old, _, _ = fit_release_20261011(orders, P1007_POSITIONS, P1007_CLOSES, **kw)
    assert _kept(old, orders, P1007_CLOSES) < 0.75                  # the finding, reproduced
    # and no less neutral than the released fit, to within one share of the dearest name
    full = _net(orders, P1007_POSITIONS, P1007_CLOSES)
    assert abs(_net(out, P1007_POSITIONS, P1007_CLOSES) - full) <= \
        abs(_net(old, P1007_POSITIONS, P1007_CLOSES) - full) + max(P1007_CLOSES.values())


def test_a_book_above_the_cap_with_a_plan_that_only_adds_trades_nothing():
    """Held 1.88x live equity, past the 1.8 cap; every order adds gross. Only adding
    nothing passes (gate.stress_breach), exactly on that edge. The released fit
    returned the empty plan; so must this one, not the unscaled plan."""
    pos = {"L": 5_000, "S": -4_400}
    closes = {"L": 10.0, "S": 10.0, "B": 10.0}
    kw = dict(equity=50_000.0, buying_power=1e9, current_gross=94_000.0,
              maintenance_margin=28_200.0, max_gross_stress=1.8, sized_equity=50_000.0)
    orders = (_o("B", "buy", 100, 0, 10.0), _o("S", "sell", 50, -4_400, 10.0))
    out, kept, why = rn.fit_to_buying_power(orders, pos, closes, **kw)
    assert out == () and kept == 0.0 and why.startswith("max_gross_stress")
    assert _gate(out, pos, closes, kw) == []
    assert fit_release_20261011(orders, pos, closes, **kw)[0] == ()


def test_a_plan_that_takes_gross_down_is_never_scaled_for_the_cap():
    """Team lead 2026-10-11: a plan that does not add gross always passes the cap,
    even with the book above it, so the fit leaves it whole."""
    pos = {"L": 10_000, "S": -10_000}
    closes = {"L": 10.0, "S": 10.0}
    orders = (_o("L", "sell", 500, 10_000, 10.0), _o("S", "buy", 500, -10_000, 10.0))
    out, kept, why = rn.fit_to_buying_power(orders, pos, closes, equity=100_000.0,
                                            buying_power=1e9, current_gross=200_000.0,
                                            maintenance_margin=60_000.0, max_gross_stress=1.8,
                                            sized_equity=100_000.0)
    assert out == orders and kept == 1.0 and why is None


# ------------------------------------------- property: many synthetic plans (seeded)

def _draw(rng):
    """A plan, a book and an account with the shapes that make limits bind: the
    plan at the cap then equity dips, leg rotations under short buying power,
    books above a cap, gross-reducing plans, one-sided plans."""
    kind = rng.choice(["cap", "rot", "bp", "above", "reduce", "mixed", "one"])
    k = rng.randint(1, 13)
    syms = [f"S{i}" for i in range(k + rng.randint(0, 3))]
    closes = {s: round(rng.choice([rng.uniform(2, 8), rng.uniform(8, 30),
                                   rng.uniform(30, 120)]), 2) for s in syms}
    pos = {s: rng.choice([-1, 1]) * rng.randint(10, 8000) for s in syms if rng.random() < 0.75}
    orders = []
    for j, s in enumerate(syms[:k]):
        cur = pos.get(s, 0)
        reduce_ = {"rot": j % 2 == 0, "reduce": rng.random() < 0.8,
                   "one": False}.get(kind, rng.random() < 0.4)
        if cur and reduce_:
            q, side = rng.randint(1, abs(cur)), ("sell" if cur > 0 else "buy")
        else:
            sgn = (1 if cur > 0 else -1) if cur else (rng.choice([-1, 1]) if kind != "one" else 1)
            q, side = rng.randint(1, 5000), ("buy" if sgn > 0 else "sell")
        orders.append(_o(s, side, q, cur, closes[s]))
    held = sum(abs(q) * closes[s] for s, q in pos.items())
    after = sum(abs(q) * closes[s] for s, q in gt.projected_positions(orders, pos).items())
    need = gt.buying_power_needed(orders, pos, closes)
    if kind == "cap":
        sized = after / 1.8 * rng.uniform(1.0, 1.01)
        eq = sized * (1 - rng.uniform(0, 0.06))
    elif kind == "above":
        sized = held / 1.8 * rng.uniform(0.85, 1.0)
        eq = sized * rng.uniform(0.97, 1.03)
    else:
        sized = max(after, held, 1000) / rng.uniform(1.2, 2.4)
        eq = sized * rng.uniform(0.95, 1.05)
    bp = (need * rng.uniform(0.05, 1.1) if kind in ("bp", "rot") or rng.random() < 0.4
          else rng.choice([1e12, need * 2]))
    kw = dict(equity=eq, buying_power=bp, current_gross=held,
              maintenance_margin=rng.uniform(0.25, 0.55) * held,
              max_gross_stress=1.8 if rng.random() < 0.9 else None, sized_equity=sized)
    return tuple(orders), pos, closes, kw


def _lp_best(orders, pos, closes, kw):
    """(traded notional, |net - full net|) of the best FRACTIONAL plan, or None if
    none fits, by scipy's linear program over the four bucket factors (opening /
    reducing x buy / sell), written from the gate's rules and not from the fit's
    two-variable reduction: first the smallest distance from the full plan's net,
    then the most traded notional at that distance."""
    from scipy.optimize import linprog
    n = {b: 0.0 for b in ("ob", "os", "rb", "rs")}
    for o in orders:
        opening = rn._opening_part(o, pos.get(o.symbol, 0)) > 0
        n[("o" if opening else "r") + o.side[0]] += o.qty * closes[o.symbol]
    held = sum(abs(q) * closes[s] for s, q in pos.items())
    eq = kw["equity"]
    caps = [eq / gt.REG_T_INITIAL]
    if kw["current_gross"] > 0:
        caps.append(eq / (kw["maintenance_margin"] / kw["current_gross"]))
    if kw["max_gross_stress"] is not None:
        caps.append(max(kw["max_gross_stress"] * min(kw["sized_equity"], eq), held))
    bs = ("ob", "os", "rb", "rs")
    sign = {"ob": 1, "rb": 1, "os": -1, "rs": -1}           # + buys, - sells
    gross = {"ob": 1, "os": 1, "rb": -1, "rs": -1}           # openings add gross
    a_bp = [n["ob"], M * n["os"], 0.0, 0.0, 0.0]
    a_g = [gross[b] * n[b] for b in bs] + [0.0]
    dev = [sign[b] * n[b] for b in bs]
    a_ub = [a_bp, a_g, dev + [-1.0], [-x for x in dev] + [-1.0]]
    b_ub = [kw["buying_power"], min(caps) - held, sum(dev), -sum(dev)]
    bounds = [(0, 1) if n[b] > 0 else (1, 1) for b in bs] + [(0, None)]
    s1 = linprog([0, 0, 0, 0, 1], A_ub=a_ub, b_ub=b_ub, bounds=bounds, method="highs")
    if s1.status == 2:
        return None
    assert s1.status == 0, s1.message
    tol = 1e-7 * max(1.0, sum(n.values()))
    bounds[-1] = (0, s1.x[-1] + tol)
    s2 = linprog([-n[b] for b in bs] + [0], A_ub=a_ub, b_ub=b_ub, bounds=bounds, method="highs")
    assert s2.status == 0, s2.message
    return -s2.fun, s1.x[-1]


def test_the_fit_never_breaks_a_limit_never_flips_and_keeps_at_least_the_released_fit():
    cases = int(os.environ.get("QUANTT_FIT_CASES", "40"))
    problems, scaled = [], 0
    for seed in range(cases):
        orders, pos, closes, kw = _draw(random.Random(20261013 + seed))
        out, kept, why = rn.fit_to_buying_power(orders, pos, closes, **kw)
        old, _, old_why = fit_release_20261011(orders, pos, closes, **kw)
        say = lambda msg: problems.append(f"seed {20261013 + seed}: {msg}")   # noqa: E731
        if why is None:
            if out != orders or old != orders:
                say("a plan that fits was changed")
            continue
        if out == orders:                               # returned unscaled: nothing fits
            if _gate((), pos, closes, kw) == [] or old != orders:
                say(f"returned unscaled although trading nothing fits ({why})")
            if _lp_best(orders, pos, closes, kw) is not None:
                say("returned unscaled although the linear program finds a fit")
            continue
        scaled += 1
        if _gate(out, pos, closes, kw):
            say(f"gate 8 refuses the fitted plan: {[r.detail for r in _gate(out, pos, closes, kw)]}")
        by = {o.client_order_id: o for o in orders}
        for o in out:
            p = by.get(o.client_order_id)
            if p is None or (o.symbol, o.side) != (p.symbol, p.side) or not 0 < o.qty <= p.qty:
                say(f"{o.client_order_id} is not a part of a plan order")
        after, full = gt.projected_positions(out, pos), gt.projected_positions(orders, pos)
        for s in set(pos) | set(full):
            cur, a, t = pos.get(s, 0), after.get(s, 0), full.get(s, 0)
            if not min(cur, t) <= a <= max(cur, t):
                say(f"{s} ends at {a}, outside {cur}..{t}: past the plan or flipped")
        full_net, shares = _net(orders, pos, closes), sum(closes[o.symbol] for o in orders)
        if _kept(out, orders, closes) < _kept(old, orders, closes) - 1e-12:
            # NEUTRALITY FIRST (review 2026-10-07). The one way to keep less than
            # the released fit: it also scales a REDUCTION to hold the full plan's
            # net, where the grid was too coarse to (0.01 of a 5,773-share order
            # is 58 shares) and so sat further off that net. Allowed only when
            # every dollar of trade given up buys at least a dollar of neutrality
            # against the released fit, to within one share per order.
            gave = (sum(o.qty * closes[o.symbol] for o in old)
                    - sum(o.qty * closes[o.symbol] for o in out))
            bought = (abs(_net(old, pos, closes) - full_net)
                      - abs(_net(out, pos, closes) - full_net))
            if gave > bought + shares:
                say(f"keeps {_kept(out, orders, closes):.6f} < released "
                    f"{_kept(old, orders, closes):.6f}, ${gave:,.2f} less traded for "
                    f"${bought:,.2f} nearer the full plan's net")
        best = _lp_best(orders, pos, closes, kw)
        if best is None:
            say("fitted although the linear program finds nothing that fits")
            continue
        traded = sum(o.qty * closes[o.symbol] for o in out)
        floors = sum(closes[o.symbol] for o in orders
                     if rn._opening_part(o, pos.get(o.symbol, 0)) > 0)
        if traded < best[0] - floors - 1.0:
            say(f"trades ${traded:,.2f}, the best fractional plan ${best[0]:,.2f} "
                f"(rounding allows ${floors:,.2f})")
        off = abs(_net(out, pos, closes) - full_net)
        if off > best[1] + shares + 1.0:
            say(f"net ${off:,.2f} from the full plan's; the best fractional plan ${best[1]:,.2f}")
        if kept != pytest.approx(_kept(out, orders, closes)):
            say(f"returned kept {kept} is not what the whole-share orders trade")
    assert not problems, "\n".join(problems[:20])
    assert scaled >= cases // 4                         # the draws do exercise the fit
