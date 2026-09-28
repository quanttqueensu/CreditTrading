"""alloc_type -> Sleeve-class map + per-type spec validation.

  * `validate_spec(spec)` — structural accept/reject of a frozen spec.
    `ops.common.load_spec` delegates here.
  * `build_sleeve(spec, capital)` — instantiate the concrete Sleeve. Sleeve
    modules register themselves with `@register`.

TRIMMED 2026-09-28 (clean slate before the Alpaca build). Only the two types the
Alpaca system runs remain: `cef_discount` (the strategy) and `static_weights`
(the b6 benchmark). The credit_rv, null_trader, forced-flow tracker and
declared-but-unimplemented types went with their sleeves; the full file is at
tag `pre-clean-slate`.
"""

CEF_DISCOUNT_ALLOC_TYPE = "cef_discount"

ALLOWED_ALLOC_TYPES = {"static_weights", CEF_DISCOUNT_ALLOC_TYPE}

WEIGHT_EXPRESSIBLE = {"static_weights"}

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


_TYPE_VALIDATORS = {
    CEF_DISCOUNT_ALLOC_TYPE: _validate_cef_discount,
    "static_weights": _validate_static_weights,
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
    """Instantiate the Sleeve for this spec. Validates first. The import is
    not wrapped: a sleeve module that fails to import must fail loudly here,
    not degrade into a misleading "not implemented" message."""
    validate_spec(spec)
    t = spec["allocation"]["type"]
    from . import sleeves  # noqa: F401  (imports register the built sleeves)
    cls = _REGISTRY.get(t)
    if cls is None:
        raise NotImplementedError(
            f"allocation type {t!r} validates but no sleeve class registers "
            f"under it. Registered: {sorted(_REGISTRY)}.")
    return cls(spec, capital_usd)
