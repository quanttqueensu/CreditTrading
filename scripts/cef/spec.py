"""The single reader of the frozen CEF spec. Nothing else opens that JSON.

WHY THIS FILE EXISTS
--------------------
Analysis scripts kept hardcoding parameters the spec owns, and the failure mode
is the worst kind: nothing errors, nothing looks wrong, and the comparison is
simply against a book that is not live.

The specific instance that prompted this (verified 2026-09-10): four analysis
scripts baselined against `band(T, 0.064)` -- the 6.4% width that was
DELIBERATELY NOT CHOSEN on 2026-09-06, because it topped a swept column and
picking the argmax of a sweep is how `z_window=63` was selected and failed out
of sample. The live band is 4.8%. Every one of those four scripts is named in a
prompt as something to extend:

    joint_cost_optimiser.py    -> W11, W12
    covariance_construction.py -> W12, W8, F3
    borrow_impact.py           -> W8
    ou_score.py                -> F2

An agent following those instructions inherits a 6.4% baseline and measures its
work against the wrong reference -- off by the difference between two policies,
which is precisely the size of the effects those prompts exist to detect.

`band_frontier.py`, the canonical harness, was doing the same thing with six
more values: universe, z_window, vol_target_annual, min_adv_usd, min_names and
gross_leverage were all module constants that happened to agree with the spec.
"Happened to agree" is not a property you can rely on after the next spec bump.

THE RULE
--------
A *baseline* that hardcodes a value the spec owns is a bug. A *sweep* that
deliberately varies a parameter is not -- that is the point of the sweep -- and
it should say so in a comment. `band_frontier.py`'s width sweep is the
legitimate case; its baseline rows are not.

NO SILENT FALLBACKS
-------------------
Every accessor raises `SpecError` naming the missing key. A default here would
reintroduce exactly the bug this module exists to remove, one layer down: the
script would run, produce a number, and the number would be against a policy
nobody deployed.

USAGE
-----
    from scripts.cef.spec import BAND_WIDTH, UNIVERSE, Z_WINDOW, frozen

    H = band(T, BAND_WIDTH)          # the live policy, whatever it currently is
    for w in (0.024, 0.048, 0.096):  # a deliberate sweep -- fine, and say so
        ...
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO / "ops/specs/cef_discount.frozen.json"


class SpecError(RuntimeError):
    """The frozen spec is missing, malformed, or missing a key that was asked for."""


def _load() -> dict:
    if not SPEC_PATH.exists():
        raise SpecError(
            f"frozen spec not found at {SPEC_PATH}. Every analysis baseline in "
            "this repo is defined against it; without it a script cannot know "
            "what the live book is doing and must not guess.")
    try:
        return json.loads(SPEC_PATH.read_text())
    except json.JSONDecodeError as exc:
        raise SpecError(f"frozen spec at {SPEC_PATH} is not valid JSON: {exc}") from exc


_SPEC: dict = _load()


def spec() -> dict:
    """The whole spec document."""
    return _SPEC


def frozen(key: str) -> Any:
    """One key from the `frozen` block. Raises naming the key if absent."""
    block = _SPEC.get("frozen")
    if block is None:
        raise SpecError(f"{SPEC_PATH} has no 'frozen' block")
    if key not in block:
        available = ", ".join(sorted(k for k in block if not k.startswith("_")))
        raise SpecError(
            f"frozen spec has no key '{key}'. Present: {available}. "
            "If this parameter was retired, the script that asks for it needs "
            "updating deliberately -- do not substitute a default.")
    return block[key]


def note(key: str) -> str | None:
    """The `_<key>_note` sibling, where one exists.

    These carry the derivation, the alternative that was rejected, and the
    revert path. Worth printing at the top of any table that depends on the key.
    """
    return (_SPEC.get("frozen") or {}).get(f"_{key}_note")


def rebalance(key: str) -> Any:
    block = _SPEC.get("rebalance")
    if block is None or key not in block:
        raise SpecError(f"{SPEC_PATH} has no rebalance.{key}")
    return block[key]


def risk(key: str) -> Any:
    block = _SPEC.get("risk")
    if block is None or key not in block:
        raise SpecError(f"{SPEC_PATH} has no risk.{key}")
    return block[key]


# ---------------------------------------------------------------------------
# The parameters analysis code shares with the live book. Import these rather
# than writing a literal -- they follow the spec when it moves.
# ---------------------------------------------------------------------------
SPEC_ID: str = _SPEC.get("spec_id", "<unknown>")

UNIVERSE: list[str] = list(frozen("universe"))
BAND_WIDTH: float = float(frozen("band_width"))
Z_WINDOW: int = int(frozen("z_window"))
VOL_TARGET: float = float(frozen("vol_target_annual"))
MIN_ADV_USD: float = float(frozen("min_adv_usd"))
MIN_NAMES: int = int(frozen("min_names"))
MIN_ABS_WEIGHT: float = float(frozen("min_abs_weight"))
MAX_NAV_AGE_BD: int = int(frozen("max_nav_age_bd"))
GROSS_LEVERAGE: float = float(frozen("gross_leverage"))
WARMUP_DAYS: int = int(frozen("warmup_days"))
ORDER_TYPE: str = str(frozen("order_type"))
REBALANCE_DAYS: int = int(frozen("rebalance_days"))
MIN_TRADE_USD: float = float(rebalance("min_trade_usd"))

# The calendar interval is INERT while band_width is set -- a band and a
# calendar are two answers to the same question and running both compounds
# them. It is retained in the spec so that deleting band_width restores v5
# exactly. Analysis code comparing the two policies wants both.
BAND_IS_LIVE: bool = "band_width" in (_SPEC.get("frozen") or {})

# The live policy label, for table headers, so a chart cannot silently claim to
# show a policy the book is not running.
LIVE_POLICY: str = (f"band {BAND_WIDTH:.1%}" if BAND_IS_LIVE
                    else f"calendar {REBALANCE_DAYS}d")


def summary() -> str:
    """One line naming the spec and the live policy, for a table header."""
    return f"{SPEC_ID} | live policy: {LIVE_POLICY} | universe {len(UNIVERSE)}"


if __name__ == "__main__":
    print(summary())
    for name in ("universe", "band_width", "z_window", "vol_target_annual",
                 "min_adv_usd", "min_names", "min_abs_weight",
                 "max_nav_age_bd", "gross_leverage", "rebalance_days"):
        value = frozen(name)
        if isinstance(value, list):
            value = f"[{len(value)} names] {' '.join(value)}"
        print(f"  {name:<20} {value}" + ("   [has _note]" if note(name) else ""))
