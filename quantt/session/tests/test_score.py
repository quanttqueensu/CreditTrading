"""`quantt/session/score.py`: the two gross P&Ls and the fill-versus-auction slippage.

Every number here is synthetic and tests the ARITHMETIC of our code, never a
claim about the market (CLAUDE.md data rules). What each test pins is a way
the score could go quietly wrong: a flipped sign on a short or a sell, a
missing print filled with something, a partial total passed off as the total,
or a caller bug disguised as UNMEASURED.
"""
import math
import random

import pytest

from quantt.session import score as sc
from quantt.session.score import AuctionPrints, Fill, score_day


def P(prices=None, gaps=None):
    return AuctionPrints(prices=prices or {}, gaps=gaps or {})


def run(held=None, fills=(), d=None, prev=None, equity=100_000.0, last_equity=100_000.0):
    return score_day(held=held or {}, fills=list(fills), auction_d=d or P(),
                     auction_prev=prev or P(), equity=equity, last_equity=last_equity)


# ------------------------------------------------------------- hold P&L signs

def test_a_long_gains_and_a_short_gains_when_their_prices_move_their_way():
    s = run(held={"AAA": 100, "BBB": -200},
            d=P({"AAA": 10.5, "BBB": 19.0}), prev=P({"AAA": 10.0, "BBB": 20.0}))
    rows = {r["symbol"]: r for r in s.per_symbol}
    assert rows["AAA"]["hold_pnl"] == pytest.approx(50.0)
    assert rows["BBB"]["hold_pnl"] == pytest.approx(200.0)      # short, price fell: a gain
    assert s.auction_pnl == pytest.approx(250.0)
    assert s.auction_hold_pnl == pytest.approx(250.0)
    assert s.auction_fill_pnl == 0.0
    assert s.measured and s.unmeasured == []


# ---------------------------------------------------- fill vs auction signs

def test_paying_above_the_auction_on_a_buy_is_positive_bp_and_a_loss():
    s = run(fills=[Fill("AAA", "buy", 10, 10.2, "o1")], d=P({"AAA": 10.0}))
    side = s.per_symbol[0]["sides"][0]
    assert side["bp_vs_auction"] == pytest.approx(200.0)       # worse for us -> positive
    assert s.auction_fill_pnl == pytest.approx(-2.0)            # 10 * (10.0 - 10.2)


def test_selling_below_the_auction_is_positive_bp_and_a_loss():
    s = run(fills=[Fill("AAA", "sell", 10, 9.9, "o1")], d=P({"AAA": 10.0}))
    side = s.per_symbol[0]["sides"][0]
    assert side["bp_vs_auction"] == pytest.approx(100.0)       # received less -> positive
    assert s.auction_fill_pnl == pytest.approx(-1.0)            # -10 * (10.0 - 9.9)


def test_selling_above_the_auction_is_negative_bp_and_a_gain():
    s = run(fills=[Fill("AAA", "sell", 10, 10.1, "o1")], d=P({"AAA": 10.0}))
    assert s.per_symbol[0]["sides"][0]["bp_vs_auction"] == pytest.approx(-100.0)
    assert s.auction_fill_pnl == pytest.approx(1.0)


def test_partial_fills_are_combined_into_one_vwap_per_symbol_and_side():
    s = run(fills=[Fill("AAA", "buy", 30, 10.0, "o1"), Fill("AAA", "buy", 10, 10.4, "o1")],
            d=P({"AAA": 10.0}))
    side = s.per_symbol[0]["sides"][0]
    assert side["qty"] == 40
    assert side["vwap"] == pytest.approx(10.1)
    assert side["bp_vs_auction"] == pytest.approx(100.0)
    assert side["order_ids"] == ["o1"]


def test_the_day_bp_is_notional_weighted():
    # AAA: 100 sh @ A=10 (notional 1000), +100bp; BBB: 10 sh @ A=100 (notional 1000), +300bp
    s = run(fills=[Fill("AAA", "buy", 100, 10.1, "a"), Fill("BBB", "sell", 10, 97.0, "b")],
            d=P({"AAA": 10.0, "BBB": 100.0}))
    assert s.fill_vs_auction_bp == pytest.approx(200.0)


def test_no_fills_means_no_bp_not_zero():
    s = run(held={"AAA": 5}, d=P({"AAA": 10.0}), prev=P({"AAA": 10.0}))
    assert s.fill_vs_auction_bp is None


# ------------------------------------------------------ the whole-book identity

def test_auction_pnl_equals_end_book_at_auction_minus_start_book_minus_cash():
    """The formula in the module docstring is the P&L of the end-of-D book at
    auction marks: q_end*A_D - q0*A_prev - sum(signed_qty * fill_price). A
    random book checks the two agree (a test of our arithmetic, nothing more)."""
    rng = random.Random(7)
    syms = [f"S{i}" for i in range(12)]
    held = {s: rng.choice([-1, 1]) * rng.randint(1, 500) for s in syms[:8]}
    fills = []
    for s in syms[4:]:
        for _ in range(rng.randint(1, 3)):
            fills.append(Fill(s, rng.choice(["buy", "sell"]), rng.randint(1, 300),
                              round(rng.uniform(5, 30), 2), f"o-{s}"))
    a_d = {s: round(rng.uniform(5, 30), 2) for s in syms}
    a_prev = {s: round(rng.uniform(5, 30), 2) for s in held}
    s = run(held=held, fills=fills, d=P(a_d), prev=P(a_prev))
    q_end = dict(held)
    cash = 0.0
    for f in fills:
        q_end[f.symbol] = q_end.get(f.symbol, 0) + f.signed_qty()
        cash -= f.signed_qty() * f.price
    expect = (sum(q * a_d[k] for k, q in q_end.items())
              - sum(q * a_prev[k] for k, q in held.items()) + cash)
    assert s.auction_pnl == pytest.approx(expect, abs=1e-6)


def test_a_name_bought_today_needs_no_previous_print():
    s = run(fills=[Fill("NEW", "buy", 10, 10.0, "o1")], d=P({"NEW": 10.5}))
    assert s.auction_pnl == pytest.approx(5.0)
    assert s.per_symbol[0]["held_qty"] == 0


def test_a_short_covered_today_scores_hold_and_fill_legs():
    # held -100 into D; bought 100 back at 19.5; auction 19.0 (prev 20.0)
    s = run(held={"AAA": -100}, fills=[Fill("AAA", "buy", 100, 19.5, "o1")],
            d=P({"AAA": 19.0}), prev=P({"AAA": 20.0}))
    r = s.per_symbol[0]
    assert r["hold_pnl"] == pytest.approx(100.0)       # -100 * (19 - 20)
    assert r["fill_pnl"] == pytest.approx(-50.0)       # +100 * (19 - 19.5)
    assert s.auction_pnl == pytest.approx(50.0)


# ------------------------------------------------ Alpaca's number, as read

def test_alpaca_official_is_equity_minus_last_equity():
    s = run(equity=101_234.5, last_equity=100_000.0)
    assert s.alpaca_equity_change == pytest.approx(1_234.5)
    assert s.alpaca_equity == 101_234.5 and s.alpaca_last_equity == 100_000.0


def test_every_score_says_it_is_gross_with_no_borrow_or_dividends():
    s = run()
    assert "gross" in s.cost_basis and "no borrow" in s.cost_basis
    assert "no dividends" in s.cost_basis


# -------------------------------------------- missing prints are never filled

def test_a_held_name_without_todays_print_is_unmeasured_and_so_is_the_total():
    s = run(held={"AAA": 100, "BBB": 50},
            d=P({"AAA": 10.5}, gaps={"BBB": "MissingAuctionPrint: none"}),
            prev=P({"AAA": 10.0, "BBB": 20.0}))
    rows = {r["symbol"]: r for r in s.per_symbol}
    assert rows["AAA"]["auction_pnl"] == pytest.approx(50.0)     # the measured name still is
    assert rows["BBB"]["auction_pnl"] is None
    assert s.auction_pnl is None and s.auction_hold_pnl is None and s.auction_fill_pnl is None
    assert s.unmeasured == ["BBB: D print: MissingAuctionPrint: none"]
    assert not s.measured


def test_a_held_name_without_the_previous_print_is_unmeasured():
    s = run(held={"AAA": 100}, d=P({"AAA": 10.5}),
            prev=P(gaps={"AAA": "AmbiguousAuctionPrint: P vs Q"}))
    assert s.auction_pnl is None
    assert s.unmeasured == ["AAA: previous-session print: AmbiguousAuctionPrint: P vs Q"]


def test_a_filled_name_without_todays_print_has_no_bp():
    s = run(fills=[Fill("AAA", "buy", 10, 10.0, "o1")], d=P(gaps={"AAA": "none"}))
    assert s.per_symbol[0]["sides"][0]["bp_vs_auction"] is None
    assert s.fill_vs_auction_bp is None
    assert s.auction_pnl is None


def test_a_name_never_fetched_is_a_caller_bug_not_unmeasured():
    with pytest.raises(ValueError, match="never fetched"):
        run(held={"AAA": 100}, d=P({"AAA": 10.0}), prev=P())
    with pytest.raises(ValueError, match="never fetched"):
        run(fills=[Fill("AAA", "buy", 1, 10.0, "o")], d=P())


def test_a_gap_without_a_reason_is_refused():
    with pytest.raises(ValueError, match="no reason"):
        run(held={"AAA": 1}, d=P(gaps={"AAA": " "}), prev=P({"AAA": 1.0}))


# ------------------------------------------------------------ bad inputs raise

@pytest.mark.parametrize("q", [0, 1.0, True, "5"])
def test_held_must_be_a_nonzero_int(q):
    with pytest.raises(ValueError, match="held"):
        run(held={"AAA": q}, d=P({"AAA": 1.0}), prev=P({"AAA": 1.0}))


@pytest.mark.parametrize("f", [Fill("AAA", "short", 1, 1.0, "o"), Fill("AAA", "buy", 0, 1.0, "o"),
                               Fill("AAA", "buy", 1.0, 1.0, "o"), Fill("AAA", "buy", 1, 0.0, "o"),
                               Fill("AAA", "buy", 1, math.nan, "o")])
def test_bad_fills_raise(f):
    with pytest.raises(ValueError):
        run(fills=[f], d=P({"AAA": 1.0}))


@pytest.mark.parametrize("px", [0.0, -1.0, math.inf, math.nan, None, True])
def test_bad_auction_prices_raise(px):
    with pytest.raises(ValueError):
        run(held={"AAA": 1}, d=P({"AAA": px}), prev=P({"AAA": 1.0}))


def test_non_finite_equity_raises():
    with pytest.raises(ValueError, match="equity"):
        run(equity=math.nan)


def test_score_module_does_no_io():
    """Pure by contract: no network, file, clock or environment access."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(sc))
    imported = {a.name.split(".")[0] for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [ast.alias(n.module or "")])}
    assert imported <= {"__future__", "math", "dataclasses", "typing"}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"open", "print", "input"}
