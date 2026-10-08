"""The SessionStart banner must always hand a new session its two owners.

WHY THIS FILE EXISTS
--------------------
On 2026-09-13 six documents each presented themselves as the place to start, and
an agent that began from any of them read figures that had been wrong for days.
The fix gave every question an owner -- `ops.orient` for numbers, `docs/SYSTEM.md`
for the system -- and, since 2026-09-28, git tag `pre-clean-slate` for anything
older (`docs/HISTORY.md`). The banner is the
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


def test_banner_points_at_orient_system_roadmap_and_history(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod, "collect", lambda **k: {})
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "python3 -m ops.orient" in out
    assert "docs/SYSTEM.md" in out
    assert "docs/ROADMAP.md" in out
    assert "pre-clean-slate" in out


def test_pointer_survives_any_state(monkeypatch, capsys):
    """The state lines above it vary; the pointer must not depend on them --
    not even on a state shaped the way this banner no longer expects (the
    pre-2026-10-08 `live_book` / string-probe shape below)."""
    mod = _load()
    monkeypatch.setattr(mod, "collect", lambda **k: {
        "live_book": None, "probes": {"cef": None, "b6": "2026-09-29_b6.json"},
        "git": {"branch": "x", "dirty": 0}})
    mod.main()
    out = capsys.readouterr().out
    assert mod.POINTER in out and "UNMEASURED" in out


def test_nothing_armed_is_said_out_loud(monkeypatch, capsys):
    """Silence must never read as success: with no machine armed, the banner
    says so, rather than printing nothing about the book. (Until 2026-10-08
    this said "NO LIVE BOOK" from a constant, armed or not.)"""
    mod = _load()
    monkeypatch.setattr(mod, "collect", lambda **k: {"prod": {"machines": {}, "verdict": {
        "line": "no machine is measured armed (laptop DRY, vm DRY): nothing is sent",
        "prod": None, "warning": None, "cautions": []}}})
    mod.main()
    out = capsys.readouterr().out
    assert "No machine is measured armed" in out and "NO LIVE BOOK" not in out


def test_a_broken_reader_still_prints_the_warning(monkeypatch, capsys):
    mod = _load()
    def boom(**k):
        raise RuntimeError("x")
    monkeypatch.setattr(mod, "collect", boom)
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "PROD UNMEASURED" in out and mod.POINTER in out
