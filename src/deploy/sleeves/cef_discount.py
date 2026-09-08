"""Credit closed-end fund discount reversion.

THE TRADE, IN ONE PARAGRAPH. A closed-end fund publishes what its portfolio is
worth (net asset value) every day, and its shares trade at whatever the market
pays. Unlike an ETF, a CEF's share count is FIXED -- there are no authorised
participants who can create or redeem shares against the basket, so nothing
mechanically drags the price back to NAV. Credit CEFs therefore sit at discounts
averaging -3.2% with a standard deviation near 6%, against roughly 0.04% for an
ETF. Those discounts wander and come back. We buy the funds trading unusually
cheap against their OWN history and sell the ones trading unusually rich, in
equal dollars, so a market-wide move in credit cancels out.

WHY AGAINST THEIR OWN HISTORY AND NOT EACH OTHER. A leveraged municipal CEF
structurally trades wider than a multi-sector one -- different fee, different
buyer, different leverage. Ranking on the raw discount would just be a permanent
long-muni/short-multisector bet dressed up as a signal. Ranking each fund against
its own normal level removes that and leaves the dislocation.

RISK SIZING IS VOLATILITY-TARGETED, and this is a measured decision, not a
default. Sorted by how dislocated the market is, this strategy's net Sharpe runs
1.24 / 0.59 / 0.80 / -0.23 / 0.68 from calm to stressed: it is BEST in calm
markets, because in stress the returns get bigger but the volatility grows faster.
A constant-notional book therefore takes its worst losses exactly when each unit
of risk pays least -- that is what produced a -31.5% drawdown at 35.8% volatility
in 2008. Scaling to constant risk on trailing realised volatility cut the
full-sample drawdown from -27% to -12%.

STALE NAV IS THE ONE THING THAT SILENTLY BREAKS THIS. The whole signal is
price-minus-NAV, so a fund whose NAV has not updated is not a cheap fund, it is a
blind one. Any fund whose NAV is older than `max_nav_age_bd` business days is
dropped for the day rather than traded.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from ..registry import register
from ..sleeve import ETF, FLAT, LONG, OK, SHORT, HALVE, KILL
from ..sleeve import MarketState, PositionTarget, RiskVerdict, Sleeve

REPO = Path(__file__).resolve().parents[3]
PX_PATH = REPO / "data/cef/cef_prices.parquet"
NAV_PATH = REPO / "data/cef/cef_nav.parquet"


@register
class CEFDiscountSleeve(Sleeve):
    """Dollar-neutral, cross-sectional discount reversion in credit CEFs."""

    alloc_type = "cef_discount"

    # ---- config ------------------------------------------------------------
    @property
    def _win(self) -> int:
        return int(self.frozen.get("z_window", 252))

    @property
    def _min_adv(self) -> float:
        return float(self.frozen.get("min_adv_usd", 3.0e6))

    @property
    def _vol_target(self) -> float:
        return float(self.frozen.get("vol_target_annual", 0.06))

    @property
    def _band_width(self) -> "float | None":
        """No-trade band half-width, in weight units. ABSENT MEANS OFF.

        When set, this REPLACES the `rebalance_days` calendar: the signal is
        computed every session and a position is left alone unless it is more
        than `band_width` from its target, in which case it is traded back to
        the BAND EDGE -- not to target. Constantinides (1986), Davis & Norman
        (1990): under proportional cost the optimal policy is a band, and the
        boundary is where you stop, not where you aim.

        Absent, this sleeve behaves exactly as before. That is deliberate --
        the code change alone must be a no-op, so that turning the policy on is
        a single visible edit to the frozen spec and nothing else.
        """
        v = self.frozen.get("band_width")
        return None if v in (None, "") else float(v)

    @property
    def _rebal_days(self) -> int:
        return max(1, int(self.frozen.get("rebalance_days", 2)))

    def instruments(self) -> list[str]:
        return sorted(self.frozen.get("universe", []))

    def history_warmup_trading_days(self) -> int:
        return self._win + 80

    # ---- data --------------------------------------------------------------
    def _panel(self, asof) -> tuple[pd.DataFrame, ...] | None:
        """Price / NAV / ADV panels up to and including `asof`.

        Read from the staged parquet rather than MarketState because NAV is not
        a price and the book's loader has no concept of it.
        """
        if not (PX_PATH.exists() and NAV_PATH.exists()):
            return None
        P = pd.read_parquet(PX_PATH)
        N = pd.read_parquet(NAV_PATH)
        uni = set(self.instruments())
        P, N = P[P.ticker.isin(uni)], N[N.ticker.isin(uni)]
        d = P.merge(N, on=["date", "ticker"], how="inner")
        d["date"] = pd.to_datetime(d["date"])
        d = d[(d.date <= pd.Timestamp(asof)) & (d.nav > 0.5) & (d.close > 0.5)]
        if d.empty:
            return None
        px = d.pivot_table(index="date", columns="ticker", values="close")
        nav = d.pivot_table(index="date", columns="ticker", values="nav")
        vol = d.pivot_table(index="date", columns="ticker", values="volume")
        return px.sort_index(), nav.sort_index(), vol.sort_index()

    # ---- signal ------------------------------------------------------------
    def target_positions(self, asof, market_state: MarketState) -> list[PositionTarget]:
        panel = self._panel(asof)
        uni = self.instruments()
        if panel is None:
            return [PositionTarget(instrument=t, side=FLAT, kind=ETF,
                                   reason="cef: no price/NAV panel") for t in uni]
        px, nav, vol = panel
        if len(px) < self._win + 20:
            return [PositionTarget(instrument=t, side=FLAT, kind=ETF,
                                   reason="cef: insufficient history") for t in uni]

        disc = 100.0 * (px - nav) / nav
        mu = disc.rolling(self._win, min_periods=120).mean().shift(1)
        sd = disc.rolling(self._win, min_periods=120).std().shift(1)
        z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
        adv = (px * vol).rolling(63, min_periods=21).mean().shift(1)

        # REBALANCE CADENCE. The cross-sectional weights are refreshed only every
        # `rebalance_days` trading days; on the days in between we re-derive the
        # SAME weight vector from the last rebalance date and let the executor
        # trade nothing. This reproduces the backtest exactly, which builds
        # weights on `idx[::HOLD]` and forward-fills them
        # (`scripts/cef/validate.py`, W.ffill(limit=HOLD-1)).
        #
        # Anchoring to position-in-the-trading-day-index rather than to a stored
        # last-rebalance date keeps this stateless and reproducible: the same
        # asof always yields the same signal date, so a re-run or a replay cannot
        # silently trade a different book.
        #
        # Deriving the weights from the signal date instead of persisting them
        # matters for a second reason -- a persisted vector would go stale if the
        # panel were ever revised, and we would have no way to detect it.
        #
        # Audited 2026-07-31 (`results/AUDIT_2026-07-31.md`): before this gate the
        # sleeve had NO cadence control and recomputed every session, while the
        # frozen spec declared 5 days -- spec, code and optimum were three
        # different things. Measured net Sharpe under real (MOC, T+1) execution:
        # hold=1 0.62, hold=2 0.73, hold=5 0.51, hold=21 0.20.
        pos = len(z.index) - 1
        # A band and a calendar are two answers to the same question, and running
        # both would compound them: the calendar would freeze the signal for k
        # days and the band would then refuse to close the gap it had just let
        # open. Under a band the signal is recomputed every session; the band
        # alone decides whether anything trades.
        band_w = self._band_width
        sig_pos = pos if band_w is not None else pos - (pos % self._rebal_days)
        last = z.index[sig_pos]
        max_age = int(self.frozen.get("max_nav_age_bd", 3))
        row, dropped = {}, []
        for tk in px.columns:
            zi = z.loc[last, tk]
            if not np.isfinite(zi):
                continue
            if float(adv.loc[last, tk] or 0.0) < self._min_adv:
                dropped.append((tk, "illiquid")); continue
            # a NAV that has not moved is a blind signal, not a cheap fund
            nav_tk = nav[tk].dropna()
            if nav_tk.empty:
                dropped.append((tk, "no NAV")); continue
            age = len(pd.bdate_range(nav_tk.index[-1], last)) - 1
            if age > max_age:
                dropped.append((tk, f"NAV {age}bd stale")); continue
            row[tk] = float(zi)

        if len(row) < int(self.frozen.get("min_names", 6)):
            return [PositionTarget(instrument=t, side=FLAT, kind=ETF,
                                   reason=f"cef: only {len(row)} eligible names")
                    for t in uni]

        s = pd.Series(row)
        w = -(s - s.mean())                       # cheap -> long, rich -> short
        w = w / w.abs().sum()

        # constant-risk sizing off the sleeve's own trailing realised vol
        ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
        hist = (ret[list(row)].mul(w, axis=1)).sum(axis=1).tail(63)
        rv = hist.std() * np.sqrt(252)
        scal = float(np.clip(self._vol_target / rv, 0.2, 2.5)) if rv > 0 else 1.0
        w = w * scal * float(self.frozen.get("gross_leverage", 1.0))

        # Drop sub-threshold names FIRST, then re-neutralise and re-normalise on
        # the survivors. Filtering after neutralising leaves a small net
        # directional position -- the first dry run came out 0.37% net short --
        # which is exactly the credit beta this book exists to avoid carrying.
        minw = float(self.frozen.get("min_abs_weight", 0.005))
        keep = w[w.abs() >= minw]
        if len(keep) >= int(self.frozen.get("min_names", 6)):
            keep = keep - keep.mean()
            denom = keep.abs().sum()
            if denom > 0:
                w = keep / denom * scal * float(
                    self.frozen.get("gross_leverage", 1.0))

        # ---- NO-TRADE BAND ---------------------------------------------------
        # Applied HERE and not earlier: the min-weight block above re-neutralises
        # and re-normalises to unit gross, which would silently undo the band.
        #
        # Policy (Constantinides 1986; Davis & Norman 1990): hold unless a name
        # is more than `band_width` from target, then trade back to the BAND
        # EDGE, not to target. Measured over 5,452 sessions the band dominates
        # the rebalance calendar at every width tested AND at matched turnover
        # -- net Sharpe 0.33 -> 0.66 at 15bp on 43% less trading -- because a
        # calendar's information loss compounds with its interval while a band
        # only ever discards small moves. See docs/PLAN.md Part 2.
        #
        # THE COMPARISON IS AGAINST WHAT WE ACTUALLY HOLD, not against a stored
        # previous target. That is the deliberate difference from the backtest,
        # which has no failed fills. It makes the policy self-correcting: if a
        # session does not arm, or an order does not fill, the real position
        # simply sits further from target and the band closes it on a later day
        # rather than the sleeve believing in a book it never got.
        band_w = self._band_width
        band_note = {}
        held_q = {}          # ticker -> signed held qty, for the HOLD targets below
        if band_w is not None:
            nav_now = float((getattr(market_state, "extras", None) or {})
                            .get("sleeve_nav", 0.0))
            if nav_now <= 0:
                # No denominator, no band. Refusing is correct: sizing the band
                # off a guessed NAV would move real money on an invented number.
                return [PositionTarget(instrument=t, side=FLAT, kind=ETF,
                                       reason="cef: band on but sleeve NAV unknown")
                        for t in uni]
            holds = getattr(market_state, "holdings", None) or {}
            held_w = {}
            for tk in uni:
                q = float(holds.get(tk, 0.0) or 0.0)
                pr = float(px[tk].iloc[-1]) if tk in px.columns else float("nan")
                if q and np.isfinite(pr) and pr > 0:
                    held_w[tk] = q * pr / nav_now
                    held_q[tk] = q
            banded = {}
            for tk in set(w.index) | set(held_w):
                tgt = float(w.get(tk, 0.0))
                cur = float(held_w.get(tk, 0.0))
                gap = tgt - cur
                if abs(gap) > band_w:
                    banded[tk] = tgt - math.copysign(band_w, gap)   # to the EDGE
                    band_note[tk] = "trade"
                else:
                    banded[tk] = cur                                # leave alone
                    band_note[tk] = "hold"
            w = pd.Series(banded)

        out = []
        for tk in uni:
            wt = float(w.get(tk, 0.0))
            # A banded HOLD must survive the min-weight filter, or a small held
            # position would be flattened by the very rule that decided not to
            # trade it -- turning "leave it alone" into "sell all of it".
            #
            # A HOLD IS EXPRESSED IN SHARES, NOT IN WEIGHT (fixed 2026-09-08,
            # results/cef/DUST_ORDERS_2026-09.md). "Leave it alone" is a
            # statement about the position, and only a share count says it
            # exactly. Emitting the held WEIGHT instead sent the decision on a
            # round trip through two different prices: the band computes
            # cur = q * px[-1] / nav from the last close in the SIGNAL panel,
            # and the executor converts that weight back with
            # floor(nav * |w| / price) using the close it reads on the SIZING
            # date -- routinely one session newer, because price and NAV are
            # inner-joined and a fund's NAV publishes later than its close.
            # Different price, different floor, and a name the band told us to
            # leave alone emitted a few shares of rounding drift as a live MOC
            # order. Measured on the 2026-09-03 signal sized off the 09-04
            # close: 12 orders, $3,019 gross, ~$15/session in commission and
            # half-spread = ~0.75%/yr of a $500k book against a policy whose
            # whole expectation is ~2.3%/yr -- and every one of them counted as
            # turnover against the band's pre-registered primary readout.
            #
            # Expressed as qty the executor's diff is EXACTLY zero whatever
            # close it sizes on (`_resolve_qty` / `_target_shares_for` return a
            # qty target unchanged, never touching a price), which is the only
            # tolerance that is honest here: any tolerance in shares would be a
            # threshold below which we still trade.
            if band_note.get(tk) == "hold" and wt != 0.0:
                q = float(held_q.get(tk, 0.0))
                if q == 0.0:
                    # Cannot happen: wt != 0 for a HOLD means banded[tk] = cur =
                    # q*pr/nav_now was non-zero, so q was non-zero. Raise rather
                    # than emit a zero qty, which the executor would read as
                    # "sell the whole position" -- the exact opposite of a hold.
                    raise ValueError(
                        f"cef band HOLD for {tk} carries weight {wt:+.6f} but no "
                        f"held quantity; refusing to emit a zero-qty target")
                out.append(PositionTarget(
                    instrument=tk, side=LONG if q > 0 else SHORT, kind=ETF,
                    qty=q,
                    meta={"order_type": str(
                        self.frozen.get("order_type", "MOC")).upper()},
                    reason=f"cef band hold: |gap|<={band_w:.4f} w={wt:+.4f}"))
                continue
            # KNOWN INTERACTION, band mode: if the band EDGE lands inside
            # min_abs_weight the dust filter flattens the name instead, which
            # trades slightly more than the band asked for and lands outside the
            # band. The window is narrow (|edge| < min_abs_weight) and going flat
            # rather than holding a few hundred dollars of a $4 fund is the
            # behaviour we want, so the filter deliberately wins. Worth knowing
            # that it is a small, bounded divergence from the backtested policy,
            # which models no minimum weight at all.
            if abs(wt) < minw:
                why = dict(dropped).get(tk, "below min weight")
                out.append(PositionTarget(instrument=tk, side=FLAT, kind=ETF,
                                          reason=f"cef: {why}"))
                continue
            out.append(PositionTarget(
                instrument=tk, side=LONG if wt > 0 else SHORT, kind=ETF,
                weight=wt,
                # The signal is only computable after the close (the fund's NAV
                # does not exist until then), so this sleeve necessarily decides
                # in the evening. A plain market order would then rest overnight
                # and fill at the next open -- the worst liquidity of the day in
                # instruments trading $3-45m. MOC executes in the closing
                # auction instead, which is what the research measured.
                meta={"order_type": str(
                    self.frozen.get("order_type", "MOC")).upper()},
                reason=f"cef discount z={row.get(tk, float('nan')):+.2f} "
                       f"w={wt:+.4f} volscal={scal:.2f}"))
        return out

    # ---- risk --------------------------------------------------------------
    def risk_check(self, ledger_view) -> RiskVerdict:
        """OBSERVE-ONLY. This sleeve is never auto-killed or auto-halved.

        Standing instruction (2026-07-31): the paper deployment exists to
        GENERATE DATA, and a sleeve that suspends itself stops producing the
        very evidence we deployed it to collect. There is no real capital at
        risk, so the usual reason to cut a losing book does not apply.

        Drawdown is therefore reported loudly and acted on by a human, not by
        this function. The thresholds below are retained purely as labels on
        the message so the severity is still visible in the daily log.
        """
        try:
            dd = float(getattr(ledger_view, "drawdown", 0.0) or 0.0)
        except Exception:
            return RiskVerdict(OK, ["ledger drawdown unreadable; no action"])
        note = "backtested worst was -12.0%"
        if abs(dd) >= 0.18:
            return RiskVerdict(OK, [
                f"WATCH: CEF drawdown {dd:.1%} is past the -18% level that would "
                f"once have stopped it ({note}). Observe-only mode: NOT halted, "
                f"continuing to collect data. Human review warranted."])
        if abs(dd) >= 0.12:
            return RiskVerdict(OK, [
                f"WATCH: CEF drawdown {dd:.1%} past -12% ({note}). "
                f"Observe-only: NOT halted."])
        return RiskVerdict(OK, [f"CEF sleeve drawdown {dd:.1%}"])
