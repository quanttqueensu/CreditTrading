"""No import path runs from the nightly report scripts to anything that can place an order.

Walks the imports (AST, not by running them) from each report entry point, through the
repository's own modules, and fails on any module that can send, or any broker client.
Fails on origin/main, where the scripts do not exist.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
ENTRY = ["scripts/ops/data_qa.py", "scripts/ops/risk_daily.py", "scripts/ops/report_notify.py"]
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


def imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append(node.module)
            out += [f"{node.module}.{a.name}" for a in node.names]
    return out


def closure(entry: str):
    seen, stack = {}, [REPO / entry]
    while stack:
        f = stack.pop()
        if f in seen:
            continue
        names = imports_of(f)
        seen[f] = names
        for name in names:
            m = module_file(name, f)
            if m is not None and m not in seen:
                stack.append(m)
    return seen


def names_called(path: Path) -> set[str]:
    """Every name or attribute that is called in `path`'s code (docstrings do not count)."""
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call):
            f = node.func
            out.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


@pytest.mark.parametrize("entry", ENTRY)
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
