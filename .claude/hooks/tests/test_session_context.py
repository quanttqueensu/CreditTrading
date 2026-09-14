"""The SessionStart banner must always hand a new session its two owners.

WHY THIS FILE EXISTS
--------------------
On 2026-09-13 six documents each presented themselves as the place to start, and
an agent that began from any of them read figures that had been wrong for days.
The fix gave every question an owner -- `ops.orient` for numbers, `docs/SYSTEM.md`
for the system -- and put superseded documents in `_archive/`. The banner is the
one thing every session reads before any document, so that is where the pointer
has to be, and a refactor of the banner must not quietly drop it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "session_context_undertest", HOOKS / "session_context.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_banner_points_at_orient_system_and_the_archive(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod, "collect", lambda: {})
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "python3 -m ops.orient" in out
    assert "docs/SYSTEM.md" in out
    assert "_archive/" in out


def test_pointer_survives_a_halted_book(monkeypatch, capsys):
    """The state lines above it vary; the pointer must not depend on them."""
    mod = _load()
    monkeypatch.setattr(mod, "collect", lambda: {
        "halt": {"active": True, "reason": "test", "scoped": [
            {"book": "x", "reason": "r", "path": "p"}]},
        "fills": {"date": "2026-09-08", "gap_sessions": 4}})
    mod.main()
    assert mod.POINTER in capsys.readouterr().out
