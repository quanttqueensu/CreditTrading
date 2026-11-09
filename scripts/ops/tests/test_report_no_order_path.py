"""No import path runs from the nightly report scripts to anything that can place an order.

Walks the imports (AST, not by running them) from each report entry point, through the
repository's own modules, and fails on any module that can send, or any broker client.
Fails on origin/main, where the scripts do not exist.

THE WALK IS MEANT TO BE HARD TO FOOL. It reads function-level imports the same as
module-level ones (that is why `scripts/rv/alpaca_daily`, which imports the broker client
inside `make_client`, may not be in a report job's closure at all), it follows relative
imports and the package `__init__.py` files a module's import runs, and it follows
`importlib.import_module` and `__import__` when they name a literal module. A dynamic
import of a computed name cannot be read, so it fails the test (2026-11-09: added with
the P&L report job, whose reader `scripts/ops/alpaca_read.py` exists to keep this clean).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
ENTRY = ["scripts/ops/data_qa.py", "scripts/ops/risk_daily.py", "scripts/ops/report_notify.py"]
# The daily P&L report's modules: the GET-only reader, and the two research tools it drives,
# whose fetch path is injectable so that none of them imports the broker client
# (docs: scripts/ops/alpaca_read.py; the job, scripts/ops/pnl_report.py, joins with its commit).
JOB_ENTRY = ["scripts/ops/alpaca_read.py", "scripts/cef/live_attribution.py", "scripts/cef/exposure_readout.py"]
FORBIDDEN_MODULES = ("quantt.broker", "quantt.session.run", "quantt.session.__main__", "quantt.session.gate",
                     "quantt.collect", "ops.preflight", "ib_async", "ib_insync", "alpaca_trade_api", "alpaca",
                     "requests")
FORBIDDEN_CALLS = ("submit_order", "cancel_order", "close_position", "close_all_positions")


def module_file(name: str, importer: Path) -> Path | None:
    parts = name.split(".")
    for base in (REPO, importer.parent):
        for p in (base.joinpath(*parts).with_suffix(".py"), base.joinpath(*parts) / "__init__.py"):
            if p.is_file():
                return p
    return None


def _package_of(path: Path, level: int) -> str | None:
    """The dotted package a relative import in `path` resolves against, or None outside REPO."""
    try:
        rel = path.parent.relative_to(REPO)
    except ValueError:
        return None
    parts = list(rel.parts)
    if level > 1:
        parts = parts[:-(level - 1)]
    return ".".join(parts)


def imports_of(path: Path) -> list[str]:
    """Every module this file imports, wherever the statement sits: module level, inside a
    function, `from x import y` (as x and x.y), relative imports (resolved against the
    file's package), `importlib.import_module("x")` and `__import__("x")` with a literal
    name. A dynamic import of a computed name raises: it cannot be followed, and a
    report module has no business doing one."""
    tree = ast.parse(path.read_text())
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                module = node.module
            else:
                base = _package_of(path, node.level)
                if base is None:
                    continue
                module = ".".join(x for x in (base, node.module) if x)
            if module:
                out.append(module)
                out += [f"{module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Call):
            f = node.func
            dotted = (f"{getattr(f.value, 'id', '')}.{f.attr}" if isinstance(f, ast.Attribute)
                      else getattr(f, "id", ""))
            if dotted in ("importlib.import_module", "__import__"):
                arg = node.args[0] if node.args else None
                assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), \
                    f"{path.relative_to(REPO)}:{node.lineno}: a dynamic import of a computed name cannot be walked"
                out.append(arg.value)
    return out


def closure(entry: str):
    """Every repository file an import of `entry` can execute, each with what it imports:
    the imported modules and, for each, the package `__init__.py` files above it (importing
    a.b.c runs a and a.b first)."""
    seen, stack = {}, [REPO / entry]
    while stack:
        f = stack.pop()
        if f in seen:
            continue
        names = imports_of(f)
        seen[f] = names
        for name in names:
            m = module_file(name, f)
            if m is None:
                continue
            for pkg in [m, *[p / "__init__.py" for p in m.parents if p != REPO and REPO in p.parents
                             and (p / "__init__.py").is_file()]]:
                if pkg not in seen and pkg not in stack:
                    stack.append(pkg)
    return seen


def names_called(path: Path) -> set[str]:
    """Every name or attribute that is called in `path`'s code (docstrings do not count)."""
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call):
            f = node.func
            out.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


@pytest.mark.parametrize("entry", ENTRY + JOB_ENTRY)
def test_no_import_path_to_order_code(entry):
    seen = closure(entry)
    assert (REPO / entry) in seen
    for f, names in seen.items():
        for name in names:
            assert not any(name == m or name.startswith(m + ".") for m in FORBIDDEN_MODULES), \
                f"{f.relative_to(REPO)} imports {name}, a path to order code"
        called = names_called(f) & set(FORBIDDEN_CALLS)
        assert not called, f"{f.relative_to(REPO)} calls {called}"


def test_the_scripts_run_no_subprocess():
    """stops.py's closure reaches the broker client, so risk_daily reads its OUTPUT and
    never runs it. A subprocess here would be an import path by other means."""
    for entry in ENTRY:
        tree = ast.parse((REPO / entry).read_text())
        mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert "subprocess" not in mods, entry


@pytest.mark.parametrize("entry", JOB_ENTRY)
def test_the_job_closure_runs_only_git_as_a_subprocess(entry):
    """`live_attribution` and `exposure_readout` use subprocess for one thing, `git
    check-ignore` before a write under the repository. Anything else run as a subprocess
    from the job's closure (a broker tool, a shell) would be an order path by other means."""
    for f in closure(entry):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and getattr(node.func.value, "id", "") == "subprocess"):
                continue
            arg = node.args[0] if node.args else None
            assert isinstance(arg, ast.List) and arg.elts and isinstance(arg.elts[0], ast.Constant) \
                and arg.elts[0].value == "git", f"{f.relative_to(REPO)}:{node.lineno}: runs something other than git"


def test_the_walk_catches_function_level_and_relative_imports(tmp_path, monkeypatch):
    """The walk itself, on files it cannot have seen: a broker import inside a function
    and through a relative import are both reported, and a computed dynamic import fails."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "inner.py").write_text("def later():\n    from quantt.broker.alpaca import AlpacaClient\n")
    (tmp_path / "pkg" / "outer.py").write_text("from . import inner\n")
    monkeypatch.setitem(globals(), "REPO", tmp_path)
    assert "quantt.broker.alpaca" in imports_of(tmp_path / "pkg" / "inner.py")
    assert "pkg.inner" in imports_of(tmp_path / "pkg" / "outer.py")
    (tmp_path / "pkg" / "dyn.py").write_text("import importlib\nname = 'x'\nimportlib.import_module(name)\n")
    with pytest.raises(AssertionError, match="dynamic import"):
        imports_of(tmp_path / "pkg" / "dyn.py")
    (tmp_path / "pkg" / "lit.py").write_text("import importlib\nimportlib.import_module('quantt.broker.alpaca')\n")
    assert "quantt.broker.alpaca" in imports_of(tmp_path / "pkg" / "lit.py")


def test_ops_halt_and_the_notifier_are_what_they_claim():
    """report_notify takes exactly `_email` from ops.halt, which imports only the stdlib
"""
    src = (REPO / "scripts/ops/report_notify.py").read_text()
    tree = ast.parse(src)
    froms = [(n.module, [a.name for a in n.names]) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert [f for f in froms if f[0] == "ops.halt"] == [("ops.halt", ["_email"])]
    assert "write_halt" not in src and "clear_halt" not in src
    third = set()
    for n in ast.walk(ast.parse((REPO / "ops/halt.py").read_text())):
        if isinstance(n, ast.Import):
            third |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            third.add(n.module.split(".")[0])
    assert third <= {"__future__", "json", "os", "shutil", "subprocess", "datetime", "pathlib", "smtplib", "email"}


def test_the_report_units_carry_no_broker_key_file_and_no_order_flags():
    for name in ("quantt-report-dataqa.service.tmpl", "quantt-report-risk.service.tmpl"):
        lines = [ln for ln in (REPO / "quantt/deploy/templates/systemd" / name).read_text().splitlines()
                 if not ln.lstrip().startswith("#")]
        text = "\n".join(lines)
        assert "QUANTT_ENV_FILE" not in text and "alpaca.env" not in text and "DRY_RUN" not in text
        assert "ReadOnlyPaths=${PROD_DIR}" in text and "MemoryMax=" in text
