"""The te4 no-op proof runs every rule the core sleeve's docstring says it proves.

WHY (the quant review of f1d9f62, finding 2). `src/deploy/sleeves/cef_discount.py`'s module
docstring says the core's targets under `below_min_names` ABSENT, "flatten" or "hold" are today's,
byte for byte, "proved on every real-panel decision date ... against ac15d09's code
(results/cef/te4_impl/sleeve_noop_diff.py ...)". As first committed that script ran no "hold"
child. The claim was true (the reviewer re-ran it with a scratch copy: 14,036 of 14,036
identical), but the docstring cited evidence the repository did not contain, and a provenance line
that names a check must name one that exists (CLAUDE.md, data rules: a number without provenance
is a rumour).

These pin the script's table of claims (`COMPARE`) to the docstring's sentence: each rule the
sentence names is a variant of the new code compared byte for byte with ac15d09's code under the
SAME rule ("hold" against ac15d09's "hold", because "hold" is meant to differ from "flatten").
Nothing here runs the proof (it takes about 21 minutes on the real panel); the script imports only
the standard library at module level, so loading it opens nothing.

FAILS ON f1d9f62: the script has no `COMPARE` and no "hold" variant.
"""
import importlib.util
from pathlib import Path

from src.deploy.sleeves import cef_discount as cefmod

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "results" / "cef" / "te4_impl" / "sleeve_noop_diff.py"
# The sentence in the sleeve's module docstring that this pins (whitespace normalised).
CLAIM = "ABSENT, \"flatten\" or \"hold\": byte for byte today's targets"
CLAIMED = {"absent": "base:absent", "flatten": "base:absent", "hold": "base:hold"}


def _script():
    spec = importlib.util.spec_from_file_location("te4_sleeve_noop_diff", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_sleeve_docstring_states_the_claim_and_cites_the_script():
    doc = " ".join(cefmod.__doc__.split())
    assert CLAIM in doc
    assert "results/cef/te4_impl/sleeve_noop_diff.py" in doc


def test_the_script_compares_every_claimed_rule_with_ac15d09_under_the_same_rule():
    """ABSENT and "flatten" are one rule (the registry reads an absent key as "flatten"), so
    both are held to ac15d09's key-absent targets; "hold" to ac15d09's "hold"."""
    mod = _script()
    for rule, against in CLAIMED.items():
        new = f"new:{rule}"
        assert new in mod.VARIANTS and against in mod.VARIANTS, (new, against)
        assert mod.COMPARE.get(new) == against, (new, mod.COMPARE.get(new))
    # every comparison is of two variants the script actually runs
    for v, against in mod.COMPARE.items():
        assert v in mod.VARIANTS and against in mod.VARIANTS, (v, against)
