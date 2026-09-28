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

TWO CONSTRAINTS SIT ON TOP OF THE SIGNAL, and both are OFF unless the frozen spec
turns them on. Neither is a return idea; each removes a way this book has been
measured to go wrong.

  `group_cap`         The cross-sectional demeaning above removes the market,
                      not the MANDATE. Measured on the live book at 2026-09-11,
                      92.5%-style concentration had become literal: the
                      rolling-252 R^2 of the book's own P&L to the in-panel
                      muni-minus-taxable spread was 0.746 (beta -0.62, NW
                      t -11.8) and effective breadth had fallen to 2.27 bets on
                      a nominal 17 names. `group_cap` bounds |sum(muni w) -
                      sum(taxable w)|. It buys risk and breadth, not return --
                      the paired return difference is statistically zero on
                      every window measured. `ng/05_research_group_neutrality.md`
                      (GN-N2, CEF trial 55).

  `max_gross_stress`  The vol scalar targets 6% of volatility; nothing targets
                      MARGIN, and margin is what this account is actually short
                      of. At the 2026-09-15 16:50 ET account read the fundable
                      gross under a worst-week buffer was 1.931x the $500k book,
                      and the book as it runs exceeds that on 17.0% of traded
                      days with nothing on the live path stopping it.
                      `max_gross_stress` scales the held book down -- never up,
                      never flat -- until it fits.
                      `ng/05_research_no_borrow_rescore.md` §6.2, §8.2.
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

# The group axis is read from the SAME file the prices come from, because it is
# the same column the research harness read (`gn_common.load_groups()` ->
# `cef_prices.parquet` `grp`, itself the security master's STATIC_ASSUMED
# attribute, `ng/data/secmaster.py:142`). A second source for the grouping is a
# second thing to disagree; the point of naming it here is that it is one path,
# patchable in tests exactly like PX_PATH.
GRP_PATH = PX_PATH

# Float dust, not a parameter. A dollar-neutral target row where one group is
# entirely unheld has net group weight 0 - 0 == 0 in exact arithmetic and ~1e-17
# in floating point; without this the k=0 identity check reports hundreds of
# "breaches" that are all 1e-17. Same constant, same reason, as the research
# harness (`gn_common.soft_cap`).
_GROUP_TOL = 1e-12


def _cap_net_group_weight(w: pd.Series, side: dict, k: float) -> tuple[pd.Series, bool]:
    """Shrink |net muni-minus-taxable weight| to at most `k`, dollar-neutrally.

    THE OPERATOR, AND WHY IT IS THIS ONE. `g = sum(w over muni) - sum(w over
    taxable)`. Shift every HELD muni weight by `-d_m` and every HELD taxable
    weight by `+d_t`. Dollar neutrality (the row's signed sum must not move)
    forces `n_m*d_m == n_t*d_t`; the cap forces `g - 2*n_m*d_m == sign(g)*k`.
    With `D = |g| - k > 0` that gives::

        d_m = sign(g)*D/(2*n_m)     d_t = sign(g)*D/(2*n_t)

    Rows already inside the cap are returned UNTOUCHED, which is what makes this
    a cap and not a tilt. The shift is uniform within a group because any other
    allocation needs a second parameter (a per-name penalty), and this change is
    allowed one.

    THIS IS NOT A PROPORTIONAL RESCALING OF THE OFFENDING SIDE, and the
    difference is the whole point: a rescaling shrinks the names that carry the
    tilt AND the names that oppose it, so it throws away name selection to buy
    group neutrality. The uniform shift only moves the group's centre. It also
    never drops a name -- a name whose weight crosses zero keeps trading, it
    simply changes side, which is the signal's own instruction once the group
    bet is removed.

    `n_m` / `n_t` count names HELD IN THIS ROW (non-zero weight), not the 6/11
    nominal group sizes: shifting a name the book does not hold would open a
    position the signal never asked for.

    NO SILENT FALLBACK. If the row breaches the cap while one entire side is
    unheld, no dollar-neutral uniform shift exists -- there is nothing to shift
    it against. Raise, rather than leave the row uncapped wearing a capped
    label.

    THE SAME OPERATOR GN-N2 WAS SCORED WITH, and the agreement is measured
    rather than claimed (`ng/store/deploy/gc_score.py` pins 3a/3b/3c, run over
    the full panel before it will print a table):

      * against a ROW-WISE transcription of `gn_common.soft_cap`'s algebra,
        max abs difference **exactly 0.0** -- same arithmetic, same order;
      * against `gn_common.soft_cap` VECTORISED over the frame -- the call
        `gn_score.py` actually made -- **5.551e-17** on 1,608 of 92,769 cells.
        That residual is numpy's summation order, not semantics: `g` is a sum
        of 6 and of 11 floats, and reducing a (17 x 5457) block along axis 1
        orders the additions differently from a 17-element row. Control: the
        identical pandas expression on `build_targets()`'s C-contiguous frame
        and on `T.copy()`'s F-contiguous one disagrees by 4.441e-16.
      * no reported statistic moves (gross SR, annual return, vol, turnover all
        agree to exactly 0.0), and the resulting book reproduces GN-N2's
        published traded row.

    See `ng/08_strategy_change.md` §3 and `src/deploy/tests/test_group_cap.py`.

    Returns `(weights, bound)` where `bound` says whether the cap moved the row.
    """
    if k < 0:
        raise ValueError(f"group_cap must be >= 0, got {k}")
    muni = [t for t in w.index if side[t] == "muni"]
    tax = [t for t in w.index if side[t] == "taxable"]
    g = float(w[muni].sum() - w[tax].sum()) if (muni or tax) else 0.0
    if not np.isfinite(g):
        raise ValueError("cef group_cap: net group weight is not finite; "
                         "refusing to cap a book it cannot measure")
    if abs(g) <= k + _GROUP_TOL:
        return w, False
    held_m = int((w[muni] != 0).sum())
    held_t = int((w[tax] != 0).sum())
    if held_m == 0 or held_t == 0:
        raise ValueError(
            f"cef group_cap: net group weight {g:+.6f} breaches k={k} but "
            f"{'muni' if held_m == 0 else 'taxable'} side is entirely unheld "
            f"({held_m} muni / {held_t} taxable names held); no dollar-neutral "
            f"uniform shift exists. Decide, do not default.")
    D = abs(g) - k
    s = math.copysign(1.0, g)
    d_m = s * D / (2.0 * held_m)
    d_t = s * D / (2.0 * held_t)
    out = w.copy()
    for c in muni:
        if out[c] != 0:
            out[c] = out[c] - d_m
    for c in tax:
        if out[c] != 0:
            out[c] = out[c] + d_t
    return out, True


def _cap_gross(w: pd.Series, cap: float) -> tuple[pd.Series, float]:
    """Scale the whole book down until gross exposure is at most `cap` x NAV.

    WHY A CAP AND NOT A TARGET. This never scales the book UP. At the
    2026-09-15 16:50 ET account read the margin the account can fund is
    G_stress = 1.931x the $500k book, and the book as it runs today exceeds that
    on 17.0% of traded days with NOTHING on the live path enforcing it
    (`ng/05_research_no_borrow_rescore.md` §6.2/§8.2). Levering UP to the cap is
    a different construction -- book (b) in that note, +14.2% CAGR at 8.55% vol
    -- which is a sizing decision with its own evidence and its own trial. This
    key only removes the breach.

    WHY IT SCALES RATHER THAN DROPS NAMES. One uniform multiplier is the only
    reduction that leaves every relative bet, the dollar-neutrality and the net
    group weight's RATIO to gross exactly where the signal put them. Dropping
    names to fit a margin line would silently re-select the book against a
    constraint that has nothing to do with the signal.

    It cannot flatten the book: `f = cap/gross` is in (0, 1) whenever it binds,
    and a zero-gross book returns unscaled. A name can still be dropped
    downstream if scaling takes it under `min_abs_weight` -- that is the
    pre-existing dust rule, its effect here is to reduce gross slightly FURTHER
    (never to increase it), and it is disclosed rather than special-cased.

    Returns `(weights, f)`; `f == 1.0` exactly when the cap did not bind.
    """
    if not (cap > 0):
        raise ValueError(f"max_gross_stress must be > 0, got {cap}")
    gross = float(w.abs().sum())
    if not np.isfinite(gross):
        raise ValueError("cef max_gross_stress: gross exposure is not finite; "
                         "refusing to size against a book it cannot measure")
    if gross <= cap or gross == 0.0:
        return w, 1.0
    f = cap / gross
    return w * f, f


@register
class CEFDiscountSleeve(Sleeve):
    """Dollar-neutral, cross-sectional discount reversion in credit CEFs."""

    alloc_type = "cef_discount"

    # ---- config ------------------------------------------------------------
    # Every knob below is REQUIRED in the frozen spec, and a missing one raises
    # naming the key. Until 2026-09-14 each was `frozen.get(key, <number>)`: a
    # spec that lost `vol_target_annual` would have sized the book at a 6%
    # target that no document or decision had set, silently, and the same for
    # the z window, the ADV floor, the name floor, leverage and the order type.
    # The live spec carries every one of these keys, so for it this is a
    # proven no-op (sleeve targets diffed byte-for-byte before and after on the
    # last six panel dates). `band_width` is the one deliberate exception:
    # ABSENT MEANS OFF, by design, and it keeps its `.get`.
    def _req(self, key: str):
        if key not in self.frozen:
            raise KeyError(
                f"cef_discount frozen spec has no '{key}'. Every sizing and "
                f"signal knob must be set in ops/specs/cef_discount.frozen.json; "
                f"the sleeve will not invent one (CLAUDE.md, no silent fallbacks).")
        return self.frozen[key]

    @property
    def _win(self) -> int:
        return int(self._req("z_window"))

    @property
    def _min_adv(self) -> float:
        return float(self._req("min_adv_usd"))

    @property
    def _vol_target(self) -> float:
        return float(self._req("vol_target_annual"))

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
    def _group_cap(self) -> "float | None":
        """Max |net muni-minus-taxable weight| on the final target. ABSENT MEANS OFF.

        Absent (or null), this sleeve behaves exactly as before -- the code
        change alone is a no-op, so that turning the constraint on is a single
        visible edit to the frozen spec and nothing else, exactly as
        `band_width` was activated. The no-op is PROVED, not asserted:
        `src/deploy/tests/test_group_cap.py::test_absent_and_null_are_byte_identical`.

        Adopted from GN-N2 (`ng/05_research_group_neutrality.md`), CEF trial 55,
        already spent. What it buys is measured and is NOT a return improvement:
        the paired daily return difference against the uncapped band is
        statistically zero on every window (traded -0.71 %/yr, NW t -1.06). It
        buys lower vol (5.56% vs 6.57%), lower turnover (25.9 vs 28.8), lower
        gross (1.23x vs 1.44x) and two-thirds of the breadth recovery
        (last-12m ENB 2.27 -> 4.38, rolling-252 R^2 to the factor 0.746 -> 0.121).
        """
        v = self.frozen.get("group_cap")
        return None if v in (None, "") else float(v)

    @property
    def _max_gross_stress(self) -> "float | None":
        """Hard ceiling on gross exposure, as a multiple of sleeve NAV. ABSENT MEANS OFF.

        Absent (or null), this sleeve behaves exactly as before. This is a
        MARGIN constraint, not a sizing decision: it only ever scales the book
        down. See `_cap_gross`.

        NOT the same object as `risk.max_gross_exposure_usd` (a dollar limit
        read by the book-level risk layer). This one is a multiple of the
        sleeve's own marked NAV and is applied inside the sleeve, after the
        band, before anything is emitted.
        """
        v = self.frozen.get("max_gross_stress")
        return None if v in (None, "") else float(v)

    @property
    def _rebal_days(self) -> int:
        return max(1, int(self._req("rebalance_days")))

    def _groups(self) -> dict:
        """muni vs taxable by STATED MANDATE, read from the price panel's `grp`.

        ONE SOURCE, THE SAME ONE THE RESEARCH USED. `gn_common.load_groups()`
        read `cef_prices.parquet`'s `grp` column, which is the security master's
        STATIC_ASSUMED `grp` attribute (`ng/data/secmaster.py:142`, basis
        "cef_prices.parquet grp column (current mandate)"). Defining the groups
        by MANDATE rather than by a return clustering is the point: a grouping
        fitted to returns would be fitted to the very thing the cap exists to
        neutralise, and the neutrality would be circular.

        KNOWN CAVEAT, carried from the research and not re-derived here: `grp`
        is the CURRENT mandate applied over all history. Two of the 17 have
        recorded CRSP mandate changes (AWF 2007-01-29, PFN 2010-03-01) and
        NEITHER crosses the muni/taxable line, so the binary split is
        unaffected. A five-group split would not be.

        The axis is muni vs NOT-muni: the panel's `grp` takes the values
        muni / hy / loan / multi, and everything that is not `muni` is taxable.

        NO SILENT FALLBACK, three ways. A missing column, a ticker with two
        different `grp` values, or a universe name with no `grp` row all raise
        naming what is missing. A defaulted mandate would put a name on the
        wrong side of the very constraint being applied, and nothing downstream
        would notice.
        """
        if not GRP_PATH.exists():
            raise FileNotFoundError(
                f"cef group_cap is set but the group source {GRP_PATH} does not "
                f"exist. The muni/taxable axis is read from the price panel's "
                f"`grp` column; there is no second source and no default.")
        try:
            P = pd.read_parquet(GRP_PATH, columns=["ticker", "grp"])
        except Exception as exc:                      # noqa: BLE001 -- re-raised
            raise ValueError(
                f"cef group_cap is set but {GRP_PATH} has no readable "
                f"ticker/grp columns ({exc}). Refusing to guess a mandate."
            ) from exc
        P = P.drop_duplicates()
        n = P.groupby("ticker")["grp"].nunique()
        ambiguous = sorted(n[n != 1].index)
        if ambiguous:
            raise ValueError(
                f"cef group_cap: {GRP_PATH} gives more than one `grp` for "
                f"{ambiguous}; the mandate axis must be unique per name.")
        g = P.groupby("ticker")["grp"].first().to_dict()
        uni = self.instruments()
        missing = sorted(set(uni) - set(g))
        if missing:
            raise ValueError(
                f"cef group_cap: no `grp` for {missing} in {GRP_PATH}; "
                f"refusing to guess a mandate.")
        return {t: ("muni" if g[t] == "muni" else "taxable") for t in uni}

    def instruments(self) -> list[str]:
        return sorted(self._req("universe"))

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
        max_age = int(self._req("max_nav_age_bd"))
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

        if len(row) < int(self._req("min_names")):
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
        w = w * scal * float(self._req("gross_leverage"))

        # Drop sub-threshold names FIRST, then re-neutralise and re-normalise on
        # the survivors. Filtering after neutralising leaves a small net
        # directional position -- the first dry run came out 0.37% net short --
        # which is exactly the credit beta this book exists to avoid carrying.
        minw = float(self._req("min_abs_weight"))
        keep = w[w.abs() >= minw]
        if len(keep) >= int(self._req("min_names")):
            keep = keep - keep.mean()
            denom = keep.abs().sum()
            if denom > 0:
                w = keep / denom * scal * float(
                    self._req("gross_leverage"))

        # ---- GROUP CAP (muni minus taxable) ---------------------------------
        # Applied HERE, to the FINAL target -- after normalisation, after the
        # vol scalar, after the min-weight re-neutralisation -- and BEFORE the
        # band. Two reasons, both load-bearing:
        #
        #  (1) k is DEFINED on the final target. The 0.30 was derived as the
        #      median |net group weight| the live book ran on its own targets
        #      over the traded era before 2023 (0.304953), which is the same
        #      object whose net group weight 05_verify measured at -1.24 over
        #      the last 12 months. Capping an intermediate vector would cap a
        #      different quantity wearing the same name.
        #  (2) It reproduces the scored construction. The research applied
        #      `soft_cap` to the target frame and then `band(.)`; anything else
        #      is not the thing that was measured.
        #
        # The cap is deliberately NOT followed by a re-normalisation: that would
        # undo it. The small change in gross is a consequence, is reported
        # rather than hidden, and is in the direction that helps (mean traded
        # gross 1.44x -> 1.23x).
        #
        # ADOPTION, NOT A NEW SEARCH. CEF trial 55 (GN-N2) is already spent on
        # this operator and this k. What is claimed is risk and breadth, not
        # return: the paired return difference is statistically zero on every
        # window, including -1.13 %/yr (t -1.67) on the only window that is out
        # of sample for k. See results/cef/PREREG_GROUP_CAP_2026-09-16.md.
        group_cap = self._group_cap
        gcap_bound = False
        if group_cap is not None:
            w, gcap_bound = _cap_net_group_weight(w, self._groups(), group_cap)

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

        # ---- GROSS / MARGIN CAP ----------------------------------------------
        # Applied AFTER the band, because the band is what decides what the book
        # will actually HOLD, and margin is charged on what is held, not on what
        # was wanted. A cap applied to the target would let the band carry a
        # stale position over the line and report itself compliant.
        #
        # THE BAND'S HOLDS BECOME TRADES WHEN THIS BINDS, and that is correct
        # rather than a regression of the 2026-09-08 dust fix. A HOLD is
        # expressed in shares precisely because "leave it alone" must cost
        # nothing; when the margin cap binds we are NOT leaving the book alone,
        # we are reducing it, so every line is a genuine order and belongs in
        # weight space where the executor sizes it against the close it trades
        # on. `rebalance.min_trade_usd` ($517) still drops the resize orders too
        # small to be worth sending, which is what keeps a hairline breach from
        # churning the whole book.
        #
        # This can only ever REDUCE exposure (f in (0,1) when it binds, and
        # exactly 1.0 otherwise). Nothing here levers the book up to the cap;
        # that is a different construction with its own evidence and its own
        # trial (`ng/05_research_no_borrow_rescore.md` §6.3 book (b)).
        gross_cap = self._max_gross_stress
        gross_scal = 1.0
        if gross_cap is not None:
            w, gross_scal = _cap_gross(w, gross_cap)
            if gross_scal != 1.0:
                band_note = {tk: "trade" for tk in band_note}

        # Provenance tag on every reason string, and EMPTY when neither cap is
        # configured -- which is what keeps the code change a byte-for-byte
        # no-op with the keys absent.
        cap_tag = ""
        if group_cap is not None:
            cap_tag += f" gcap={group_cap:.4f}{'*' if gcap_bound else ''}"
        if gross_cap is not None:
            cap_tag += f" gmax={gross_cap:.4f}"
            if gross_scal != 1.0:
                cap_tag += f"*x{gross_scal:.4f}"

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
                        self._req("order_type")).upper()},
                    reason=f"cef band hold: |gap|<={band_w:.4f} w={wt:+.4f}"
                           f"{cap_tag}"))
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
                                          reason=f"cef: {why}{cap_tag}"))
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
                    self._req("order_type")).upper()},
                reason=f"cef discount z={row.get(tk, float('nan')):+.2f} "
                       f"w={wt:+.4f} volscal={scal:.2f}{cap_tag}"))
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
