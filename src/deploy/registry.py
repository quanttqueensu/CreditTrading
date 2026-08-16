"""alloc_type -> Sleeve-class map + per-type spec validation.

Two responsibilities, both framework-level (they do NOT depend on the four quant
sleeves being implemented yet):

  * `validate_spec(spec)` — structural accept/reject of a frozen spec for any
    allowed `allocation.type`. `ops.common.load_spec` delegates here for every
    non-`static_weights` type. This runs today, before any sleeve exists.
  * `build_sleeve(spec, capital)` — instantiate the concrete Sleeve. Sleeve
    modules register themselves with `@register`; until a sleeve lands,
    `build_sleeve` raises a clear "not yet implemented" error rather than a
    KeyError. The framework ships only `StaticWeightsSleeve` registered.

`is_weight_expressible(alloc_type)` is True ONLY for `static_weights` — the sole
type the standalone `ops/daily_run.py` path can serve (EOM/FOMC/etc. are
calendar-timed and carry the §1 spec shape; they run under PortfolioOrchestrator).
"""

# Forced-flow ZERO-CAPITAL paper trackers (build B1, 2026-07-26 cycle).
# Additive widen, same pattern as the FUTURES kind widen: no existing type's
# validation or error strings change. Trackers carry capital_usd == 0 and an
# all-FLAT target book by construction (src/deploy/v2/ff_sleeves/); they are
# NOT weight-expressible and never run on the standalone ops path.
FF_TRACKER_ALLOC_TYPES = {"ff_t1_seasonal_tracker", "ff_t2_firesale_tracker",
                          "ff_t3_downgrade_tracker",
                          # cycle-2 close 2026-07-26 (ADDITIVE widen): M3
                          # month-end MOC residue on STRICT counts, zero cap
                          "ff_t4_m3_moc_strict_tracker"}

# Credit ETF relative value (2026-07-30, ADDITIVE widen). A long/short,
# factor-neutral, weight-expressed sleeve; see src/deploy/sleeves/credit_rv.py.
# No existing type's validation or error strings change.
CREDIT_RV_ALLOC_TYPE = "credit_rv_statarb"

# Phase 0 control experiment (workflow §9). A random-signal trader at the real
# strategy's cadence and size, used to prove the fill/P&L path does not flatter
# results. Registered like any sleeve so it runs through the IDENTICAL code path
# — that is the entire point of it.
NULL_TRADER_ALLOC_TYPE = "null_trader"
CEF_DISCOUNT_ALLOC_TYPE = "cef_discount"

ALLOWED_ALLOC_TYPES = {"static_weights", "eom_duration", "fomc_event",
                       "short_vol_straddle", "duration_hedged_overlay",
                       CREDIT_RV_ALLOC_TYPE, NULL_TRADER_ALLOC_TYPE,
                       CEF_DISCOUNT_ALLOC_TYPE} \
                      | FF_TRACKER_ALLOC_TYPES

WEIGHT_EXPRESSIBLE = {"static_weights"}

# Populated by @register on each concrete Sleeve subclass.
_REGISTRY = {}


def register(cls):
    """Class decorator: register a Sleeve subclass under its `alloc_type`."""
    at = getattr(cls, "alloc_type", "")
    if at not in ALLOWED_ALLOC_TYPES:
        raise ValueError(f"cannot register sleeve with unknown alloc_type {at!r}")
    _REGISTRY[at] = cls
    return cls


def registered_types():
    return set(_REGISTRY)


def is_weight_expressible(alloc_type) -> bool:
    return alloc_type in WEIGHT_EXPRESSIBLE


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _require(spec, key, where="spec"):
    if key not in spec:
        raise ValueError(f"{where} missing required key {key!r}")
    return spec[key]


def _require_dict(spec, key, where="spec"):
    v = _require(spec, key, where)
    if not isinstance(v, dict):
        raise ValueError(f"{where}[{key!r}] must be an object, got {type(v).__name__}")
    return v


def _validate_capital(spec):
    cap = spec.get("capital_usd", spec.get("book_usd"))
    if cap is None:
        raise ValueError("spec missing capital_usd (or book_usd)")
    cap = float(cap)
    band = spec.get("capital_band") or spec.get("book_usd_band")
    if band is not None:
        lo, hi = float(band[0]), float(band[1])
        if not (lo <= cap <= hi):
            raise ValueError(
                f"capital_usd {cap:.0f} outside capital_band [{lo:.0f}, {hi:.0f}]")
    return cap


def _validate_common(spec):
    _require(spec, "spec_id")
    _require(spec, "status")
    alloc = _require_dict(spec, "allocation")
    t = _require(alloc, "type", "allocation")
    if t not in ALLOWED_ALLOC_TYPES:
        raise ValueError(f"unsupported allocation type {t!r}")
    _validate_capital(spec)
    return t


def _validate_static_weights(spec):
    alloc = spec["allocation"]
    w = _require_dict(alloc, "weights", "allocation")
    if not w:
        raise ValueError("static_weights allocation has no weights")
    total = 0.0
    for k, v in w.items():
        fv = float(v)
        if fv < 0:
            raise ValueError(
                f"weight for {k!r} is {fv} < 0. This simulator does not short; "
                "a short leg needs the derivatives ledger, not static_weights.")
        total += fv
    if total > 1.0 + 1e-9:
        raise ValueError(
            f"static_weights weights sum to {total:.4f} > 1.0. This path does "
            "not borrow; wire the financing leg first.")


def _validate_cef_discount(spec):
    """The CEF sleeve's whole signal is price minus NAV, so the things that can
    silently break it are a missing universe, a NAV staleness tolerance wide
    enough to trade blind, and an unbounded volatility scalar."""
    f = _require_dict(spec, "frozen")
    uni = f.get("universe")
    if not isinstance(uni, list) or len(uni) < 6:
        raise ValueError("cef_discount needs a frozen universe of >= 6 funds; "
                         "the book is cross-sectional and cannot be formed from fewer")
    vt = float(f.get("vol_target_annual", 0.0))
    if not 0.005 <= vt <= 0.40:
        raise ValueError(f"vol_target_annual {vt} outside a sane 0.5%-40% band")
    age = int(f.get("max_nav_age_bd", 3))
    if not 1 <= age <= 5:
        raise ValueError(
            f"max_nav_age_bd {age} outside 1-5. A fund whose NAV has not "
            "updated is not a cheap fund, it is a blind one.")
    if float(f.get("min_adv_usd", 0.0)) < 1.0e6:
        raise ValueError("min_adv_usd below $1m; CEFs are thin and this book "
                         "cannot assume it can trade names that do not trade")


def _validate_frozen_and_risk(spec):
    _require_dict(spec, "frozen")
    _require_dict(spec, "risk")


def _validate_eom(spec):
    _validate_frozen_and_risk(spec)


def _validate_fomc(spec):
    _validate_frozen_and_risk(spec)


def _validate_short_vol(spec):
    _validate_frozen_and_risk(spec)


def _validate_overlay(spec):
    _validate_frozen_and_risk(spec)
    frozen = spec["frozen"]
    win = frozen.get("rate_beta_window_days", frozen.get("rate_beta_window"))
    if win is not None and int(win) <= 0:
        raise ValueError("duration_hedged_overlay rate_beta_window must be positive")


def _validate_ff_tracker(spec):
    """A forced-flow paper tracker MUST carry zero capital and the tracker
    status — the structural guarantee that the 2026-07 cycle deploys nothing
    (STRATEGY_SPEC.md: deployed set is EMPTY; trackers are measurement-only)."""
    _validate_frozen_and_risk(spec)
    cap = float(spec.get("capital_usd", spec.get("book_usd", 0.0)) or 0.0)
    if cap != 0.0:
        raise ValueError(
            f"forced-flow paper tracker specs must carry capital_usd == 0 "
            f"(got {cap:.0f}). The 2026-07-26 assembly deployed ZERO capital; "
            "promotion requires a fresh pre-registration, not a spec edit.")
    status = str(spec.get("status", ""))
    if status != "PAPER_TRACKER_ZERO_CAPITAL":
        raise ValueError(
            f"forced-flow tracker status must be 'PAPER_TRACKER_ZERO_CAPITAL' "
            f"(got {status!r}) — use src.deploy.lib.ff_sleeves.load_tracker_spec "
            "to wrap the governance draft JSON.")


def _validate_credit_rv(spec):
    """Structural check for the credit RV sleeve.

    The two things worth failing loudly on are the ones that would silently turn
    this into a different strategy than the one that was tested: a signal built
    on the wrong price, and an unbounded gross.
    """
    _validate_frozen_and_risk(spec)
    f = spec.get("frozen", {})

    uni = f.get("universe")
    if not isinstance(uni, list) or len(uni) < 6:
        raise ValueError(
            f"credit_rv frozen.universe must be a list of >=6 tickers "
            f"(got {uni!r}). Below that the factor neutralisation has fewer "
            "names than factors and the book stops being neutral.")

    src = str(f.get("signal_price", ""))
    if src != "hl_mid":
        raise ValueError(
            f"credit_rv frozen.signal_price must be 'hl_mid' (got {src!r}). "
            "Phase 0 (FINDINGS.md §8e) showed a CLOSE-built signal scores "
            "Sharpe -0.41 against mid returns — it predicts its own bid-ask "
            "bounce, not fair value. The close is not an allowed signal price.")

    gl = float(f.get("gross_leverage", 0.0))
    if not (0.0 < gl <= 4.0):
        raise ValueError(
            f"credit_rv frozen.gross_leverage must be in (0, 4] (got {gl}). "
            "The measured Sharpe degrades with leverage; an unbounded gross "
            "buys drawdown, not return.")

    sm = int(f.get("smooth", 0))
    if sm < 1:
        raise ValueError(
            f"credit_rv frozen.smooth must be >=1 (got {sm}). Smoothing is the "
            "only turnover control this sleeve has; it is not optional.")


def _validate_null_trader(spec):
    """The null trader must be recognisable as a control, never as a strategy."""
    _validate_frozen_and_risk(spec)
    f = spec.get("frozen", {})
    uni = f.get("universe")
    if not isinstance(uni, list) or len(uni) < 2:
        raise ValueError(f"null_trader frozen.universe must list >=2 tickers (got {uni!r})")
    if "seed" not in f:
        raise ValueError(
            "null_trader frozen.seed is required — the random book must be "
            "reproducible from the spec (workflow §1.4), not drawn afresh per run.")
    gl = float(f.get("gross_leverage", 0.0))
    if not (0.0 < gl <= 2.0):
        raise ValueError(
            f"null_trader frozen.gross_leverage must be in (0, 2] (got {gl}). "
            "It exists to measure costs, not to take risk.")


_TYPE_VALIDATORS = {
    CEF_DISCOUNT_ALLOC_TYPE: _validate_cef_discount,
    "static_weights": _validate_static_weights,
    CREDIT_RV_ALLOC_TYPE: _validate_credit_rv,
    NULL_TRADER_ALLOC_TYPE: _validate_null_trader,
    "eom_duration": _validate_eom,
    "fomc_event": _validate_fomc,
    "short_vol_straddle": _validate_short_vol,
    "duration_hedged_overlay": _validate_overlay,
    "ff_t1_seasonal_tracker": _validate_ff_tracker,
    "ff_t2_firesale_tracker": _validate_ff_tracker,
    "ff_t3_downgrade_tracker": _validate_ff_tracker,
    "ff_t4_m3_moc_strict_tracker": _validate_ff_tracker,
}


def validate_spec(spec) -> None:
    """Structural accept/reject for any allowed alloc type. Raises ValueError on
    a malformed spec; returns None on accept."""
    t = _validate_common(spec)
    _TYPE_VALIDATORS[t](spec)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def build_sleeve(spec, capital_usd):
    """Instantiate the Sleeve for this spec. Validates first."""
    validate_spec(spec)
    t = spec["allocation"]["type"]
    # Trigger self-registration of the shipped sleeves without a hard dependency
    # on the four quant sleeves existing yet.
    try:
        from . import sleeves  # noqa: F401  (imports register the built sleeves)
    except Exception:
        pass
    try:
        from .v2 import ff_sleeves  # noqa: F401  (registers the FF paper trackers)
    except Exception:
        pass
    cls = _REGISTRY.get(t)
    if cls is None:
        raise NotImplementedError(
            f"allocation type {t!r} is allowed and its spec validates, but the "
            f"sleeve class is not implemented yet (next build phase). Registered "
            f"today: {sorted(_REGISTRY)}.")
    return cls(spec, capital_usd)
