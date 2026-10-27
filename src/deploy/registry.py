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


# ---------------------------------------------------------------------------
# cef_discount: the four optional keys that let a second spec reuse the sleeve
# ---------------------------------------------------------------------------
#
# WHY THEY EXIST (C4 deployment plan, results/cef/C4_DEPLOY_PLAN_2026-10-27.md
# §1 row 1). Trial C4 ran THIS sleeve's z-score on 74 other funds through
# `band_frontier.build_targets(universe=, source=, mask=)`, and the plan reuses
# the sleeve with a second frozen spec rather than writing a second copy of the
# z-score (two copies of a signal agree until one of them is edited). The trial
# differs from the sleeve in exactly three ways the sleeve could not express:
# where its panels live, two masks on the discount (PREREG_C4_FAMILIES §4.3),
# and what it does below `min_names` (`build_targets` holds; the sleeve
# flattens). These keys express them.
#
# ABSENT IS TODAY'S BEHAVIOUR, BYTE FOR BYTE, for every one of them, and the
# live spec carries none (`quantt/session/tests/test_c4_keys_noop.py` pins the
# 13's plan.json and plan_sha against the code before the keys existed). The
# parse lives HERE, once: `_validate_cef_discount` calls it on the spec, and the
# sleeve calls it again on its own `frozen` block, so a sleeve built without the
# registry still cannot read a value the registry would refuse.
#
# NO NULL, NO TRUTHINESS. Unlike `band_width`, whose null means off, a present
# key must hold one of its declared values: `null`, `1`, `"true"` or a typo
# raises, naming the key and the value. A key that decides whether a fund has a
# discount, or whether the book is closed, must not be decided by Python
# truthiness or by a spelling.

CEF_PANEL_SOURCE_KEYS = ("prices", "nav")
CEF_MASK_KEYS = ("nav_repeat_mask", "zero_volume_mask")
CEF_BELOW_MIN_NAMES = ("flatten", "hold")       # the first is the default


def cef_panel_source(frozen):
    """`panel_source` as (prices, nav) repo-relative POSIX strings, or None when absent.

    The value is `{"prices": "<path>", "nav": "<path>"}`, each relative to the
    repository root -- the root of the prod clone, so one spec names the same
    file on the laptop and on the VM. An absolute path would name one machine's
    disk inside a governance object, and `..` would let a spec read outside
    the clone; both raise. Each must be a `.parquet` in the live panels' schema
    (`date ... close volume ticker grp` / `date nav ticker`, as `data/cef/` and
    `data/cef_families/` are built), and the two must differ: a price file read
    as NAV would give every fund a discount of zero, which is a book, not an
    error.
    """
    if "panel_source" not in frozen:
        return None
    v = frozen["panel_source"]
    if not isinstance(v, dict):
        raise ValueError(f"cef_discount panel_source must be an object "
                         f"{{'prices': <path>, 'nav': <path>}}, got {v!r}")
    unknown = sorted(set(v) - set(CEF_PANEL_SOURCE_KEYS))
    missing = [k for k in CEF_PANEL_SOURCE_KEYS if k not in v]
    if unknown or missing:
        raise ValueError(f"cef_discount panel_source has unknown key(s) {unknown} and lacks "
                         f"{missing}; it takes exactly {list(CEF_PANEL_SOURCE_KEYS)}")
    from pathlib import PurePosixPath
    out = []
    for k in CEF_PANEL_SOURCE_KEYS:
        p = v[k]
        if not isinstance(p, str) or not p.strip() or p != p.strip():
            raise ValueError(f"cef_discount panel_source[{k!r}] must be a non-empty path "
                             f"string without surrounding space, got {p!r}")
        pp = PurePosixPath(p)
        if pp.is_absolute() or "\\" in p or ".." in pp.parts:
            raise ValueError(f"cef_discount panel_source[{k!r}] = {p!r}: must be relative to "
                             f"the repository root, with '/' and no '..'")
        if pp.suffix != ".parquet":
            raise ValueError(f"cef_discount panel_source[{k!r}] = {p!r}: not a .parquet file")
        out.append(str(pp))
    if out[0] == out[1]:
        raise ValueError(f"cef_discount panel_source names {out[0]!r} for both prices and nav")
    return tuple(out)


def cef_mask_flag(frozen, key):
    """`nav_repeat_mask` / `zero_volume_mask`: exactly true or false; absent is false."""
    if key not in CEF_MASK_KEYS:
        raise KeyError(f"{key!r} is not a cef_discount mask key {CEF_MASK_KEYS}")
    if key not in frozen:
        return False
    v = frozen[key]
    if v is not True and v is not False:
        raise ValueError(f"cef_discount {key} must be exactly true or false, got {v!r} "
                         f"({type(v).__name__})")
    return v


def cef_below_min_names(frozen):
    """`below_min_names`: "flatten" (absent; today's rule) or "hold" (trial C4's)."""
    if "below_min_names" not in frozen:
        return CEF_BELOW_MIN_NAMES[0]
    v = frozen["below_min_names"]
    if not isinstance(v, str) or v not in CEF_BELOW_MIN_NAMES:
        raise ValueError(f"cef_discount below_min_names {v!r} is not one of "
                         f"{list(CEF_BELOW_MIN_NAMES)}")
    return v


def cef_optional_keys(frozen) -> dict:
    """All four C4 keys parsed, each to its default when absent. Raises on the
    first malformed one. Called by `_validate_cef_discount` and by the sleeve's
    constructor, so a bad `below_min_names` refuses on every day and not only on
    the first day the book falls below `min_names`."""
    return {"panel_source": cef_panel_source(frozen),
            **{k: cef_mask_flag(frozen, k) for k in CEF_MASK_KEYS},
            "below_min_names": cef_below_min_names(frozen)}


def _validate_cef_discount(spec):
    """The CEF sleeve's whole signal is price minus NAV, so the things that can
    silently break it are a missing universe, a NAV staleness tolerance wide
    enough to trade blind, and an unbounded volatility scalar. The four
    optional C4 keys (above) are parsed here too, so a malformed one refuses
    the spec at load rather than at the first decide."""
    f = _require_dict(spec, "frozen")
    cef_optional_keys(f)
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
