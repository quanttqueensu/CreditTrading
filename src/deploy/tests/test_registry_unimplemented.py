"""An alloc type must not validate and then fail in-session.

WHY
---
Audited 2026-09-10: eight of the twelve entries in `ALLOWED_ALLOC_TYPES` had no
registered Sleeve class. A book spec naming one of them passed every check the
governance path applies -- `validate_spec` said yes -- and then raised when the
orchestrator tried to build the sleeve.

That ordering is the problem. Governance exists so a spec is approved *before*
it reaches a session; a spec that clears governance and cannot run has had its
failure moved from the safe place to the dangerous one. Four of the eight were
FF trackers whose package (`src/deploy/v2/ff_sleeves/`) no longer exists at all.

These tests pin the invariant rather than the current membership, so they keep
working as sleeves get built: the rule is "everything ALLOWED is either
registered or explicitly listed as unimplemented", not "these eight names".
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Importing the sleeve modules runs the @register decorators.
for _mod in ("cef_discount", "credit_rv", "null_trader", "static_weights"):
    importlib.import_module(f"src.deploy.sleeves.{_mod}")

from src.deploy import registry  # noqa: E402


def test_every_allowed_type_is_registered_or_declared_unimplemented():
    """No silent third category.

    A type that is neither registered nor listed is one that validates and then
    fails in-session -- exactly the state this audit found.
    """
    unaccounted = (set(registry.ALLOWED_ALLOC_TYPES)
                   - set(registry._REGISTRY)
                   - set(registry.UNIMPLEMENTED_ALLOC_TYPES))
    assert not unaccounted, (
        f"these alloc types validate but have no Sleeve class and are not "
        f"declared unimplemented: {sorted(unaccounted)}. Either register a "
        "sleeve, or add an entry to UNIMPLEMENTED_ALLOC_TYPES naming the prompt "
        "that will build it (or marking it a fossil).")


def test_no_type_is_both_registered_and_unimplemented():
    """A contradiction here would make the error message a lie."""
    both = set(registry._REGISTRY) & set(registry.UNIMPLEMENTED_ALLOC_TYPES)
    assert not both, f"registered AND declared unimplemented: {sorted(both)}"


@pytest.mark.parametrize("alloc_type", sorted(registry.UNIMPLEMENTED_ALLOC_TYPES))
def test_unimplemented_types_are_refused_at_validation(alloc_type):
    """The refusal must happen in validate_spec, not in the orchestrator."""
    spec = {"spec_id": "test", "status": "TEST",
            "allocation": {"type": alloc_type}, "capital_usd": 1000.0}
    with pytest.raises(ValueError) as exc:
        registry.validate_spec(spec)
    msg = str(exc.value)
    assert "NOT IMPLEMENTED" in msg, msg
    assert alloc_type in msg, "the message must name the type"


@pytest.mark.parametrize("alloc_type", sorted(registry.UNIMPLEMENTED_ALLOC_TYPES))
def test_every_unimplemented_type_says_why(alloc_type):
    """Owner or fossil -- W0 Part C's rule, made checkable.

    'Unused scaffolding with a dated owner is not dead code; unused scaffolding
    with no owner is.' A reason string that says neither leaves the next reader
    exactly where this audit started.
    """
    reason = registry.UNIMPLEMENTED_ALLOC_TYPES[alloc_type]
    assert reason.strip(), f"{alloc_type} has an empty reason"
    assert ("FOSSIL" in reason or "docs/prompts" in reason), (
        f"{alloc_type}: reason must either name an owning prompt or say FOSSIL. "
        f"Got: {reason!r}")


def test_the_live_specs_all_still_validate():
    """The whole point is that this change is invisible to real books."""
    import json
    specs = sorted((REPO / "ops/specs").glob("*.frozen.json"))
    assert specs, "no frozen specs found"
    for path in specs:
        registry.validate_spec(json.loads(path.read_text()))
