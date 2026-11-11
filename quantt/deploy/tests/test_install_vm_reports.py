"""`install_vm --reports`: the report-only units, and proof they change nothing else.

The team lead's ruling of 2026-11-08 gives the nightly data QA and risk report to VM
timers. The contract the installer must keep: the new units are checked as hard as
every other (clean clone, templates at the tag, drop-in scan, nothing busy, loaded as
written); they carry no broker key file and no panel lock; an install of them touches
no book's unit; and with report units on the machine, a book install neither refuses nor
disarms because of them. The core's and C4's plans are compared against origin/main's
installer (a5b94c8), read from git, byte for byte: every rendered unit and step.

Hermetic: test_install_vm's fake VM. Fails on origin/main: no `--reports`.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from quantt.deploy import install_vm as iv
from quantt.deploy.tests.test_install_vm import REAL_REPO, git
from quantt.deploy.tests.test_install_vm_books import C4World, EOD, _run_with, _unit_bytes

BASE = "a5b94c8"          # origin/main when this mode was added: the book installs must equal it
SESSION_UNITS = ("quantt-cef-session", "quantt-cef-verify", "quantt-cef-collect", "quantt-secret",
                 "quantt-c4-session", "quantt-c4-verify", "quantt-c4-collect", "quantt-c4-secret")


class ReportsWorld(C4World):
    """The C4 world with the report units' files at the tag too."""

    def _make_repo(self):
        d = self.dev
        d.mkdir()
        git("init", "-q", "-b", "main", cwd=d)
        (d / ".gitignore").write_text("/data/\n__pycache__/\n")
        for rel in dict.fromkeys(iv.C4_VM.required_at_tag + iv.REPORT_VM.required_at_tag):
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            if rel.startswith(iv.TEMPLATE_DIR):
                (d / rel).write_text((REAL_REPO / rel).read_text())
            else:
                (d / rel).write_text(f"# stub {rel}\n")
        git("add", "-A", cwd=d)
        git("commit", "-q", "-m", "v1", cwd=d)
        git("tag", "-a", "v1", "-m", "release v1", cwd=d)
        subprocess.run(["git", "clone", "-q", "--bare", str(d), str(self.origin)], check=True, capture_output=True)
        git("remote", "add", "origin", str(self.origin), cwd=d)

    def reports(self, *extra, capsys=None, **kw):
        return self.run("--reports", *extra, seed=False, capsys=capsys, **kw)


@pytest.fixture
def rw(tmp_path):
    return ReportsWorld(tmp_path)


def _mutating_calls(rw):
    return [c for c in rw.cmds.calls if c[:1] == ["systemctl"] and c[1] in ("stop", "start", "enable", "disable", "restart")]


def test_reports_dry_run_renders_every_unit_and_writes_nothing(rw, capsys):
    rc, out = rw.reports(capsys=capsys)
    assert rc == 0, out
    for f in iv.REPORT_UNIT_FILES:
        assert f"{rw.layout.unit_path(f)} (rendered, not written)" in out
    assert not rw.layout.units_dir.exists() or not list(rw.layout.units_dir.iterdir())
    assert "alert-smtp-pass" in out and "team lead" in out           # the warning names the TL's step


def test_reports_apply_writes_units_as_contracted(rw, capsys):
    rc, out = rw.reports("--apply", capsys=capsys)
    assert rc == 0, out
    assert set(p.name for p in rw.layout.units_dir.iterdir()) == set(iv.REPORT_UNIT_FILES)
    for job, memmax in ((j, iv.REPORT_MEMORY_MAX) for j in iv.REPORT_JOBS):
        text = rw.layout.unit_path(job.service).read_text()
        body = "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
        assert f"MemoryMax={memmax}" in body and "TimeoutStartSec=480" in body and "Nice=10" in body
        assert f"ReadOnlyPaths={rw.layout.prod_dir}" in body
        assert "QUANTT_ENV_FILE" not in body and "alpaca.env" not in body and "DRY_RUN" not in body
        book = job.unit.split("-")[1]
        assert f"QUANTT_STATE_DIR={rw.layout.state_root / book}" in body
        assert f"--book {book}" in body
        assert ("EnvironmentFile=-/run/quantt-reports/alert.env" in body) == job.unit.endswith("risk")
    for p in ("cef", "c4"):
        assert (rw.layout.state_root / p / "reports").is_dir() and (rw.layout.state_root / p / "logs").is_dir()
    timer = rw.layout.unit_path("quantt-cef-dataqa.timer").read_text()
    assert "OnCalendar=Mon,Tue,Wed,Thu,Fri *-*-* 21:45:00" in timer


def test_report_schedule_is_clear_of_every_runner_slot():
    """Session :00/:30, collect :10/:40, verify 17:30, send 15:52/15:55/12:52/12:55."""
    busy = {(h, m) for h in range(24) for m in (0, 10, 30, 40)} | {(17, 30), (15, 52), (15, 55), (12, 52), (12, 55)}
    times = list(iv.REPORT_SCHEDULE.values())
    assert not (set(times) & busy) and len(set(times)) == len(times)
    for (kind, book), (h, m) in iv.REPORT_SCHEDULE.items():
        before_decide = (h, m) < (22, 0)
        assert before_decide == (kind == "dataqa"), (kind, book)
        end_min = h * 60 + m + iv.REPORT_TIMEOUT_S / 60
        assert end_min < 22 * 60 or (kind == "risk" and end_min < 22 * 60 + 30), (kind, book)


def test_reports_touch_no_books_unit(rw, capsys):
    rc, _ = rw.reports("--apply", "--enable", capsys=capsys)
    assert rc == 0
    for c in _mutating_calls(rw):
        assert not any(u in " ".join(c) for u in SESSION_UNITS), c
    assert "--now" in " ".join(sum((c for c in _mutating_calls(rw) if c[1] == "enable"), []))
    # the units read back as loaded; a failed report fetch would still leave the timers armed by systemd
    assert rw.cmds.timer_active >= {j.timer for j in iv.REPORT_JOBS}


def test_a_failed_report_step_reports_only_report_timers_stopped(rw, capsys):
    assert rw.reports("--apply", "--enable", capsys=capsys)[0] == 0
    rw.cmds.fail[("systemctl", "daemon-reload")] = 1
    rc, out = rw.reports("--apply", capsys=capsys)
    assert rc == 2 and "REFUSED at step" in out and "No session timer was touched" in out
    for c in _mutating_calls(rw):
        assert not any(u in " ".join(c) for u in SESSION_UNITS), c


# ------------------------------------------------------------------ refusals

def test_reports_refuses_a_dirty_clone(rw, capsys):
    (rw.layout.prod_dir / "stray.txt").write_text("x")
    rc, out = rw.reports("--apply", capsys=capsys)
    assert rc == 2 and "local modifications" in out and not list((rw.layout.units_dir).glob("*.service"))


def test_reports_refuses_a_clone_not_at_the_tag(rw, capsys):
    rw.commit_and_tag("v2", lambda d: (d / "x.txt").write_text("x"))
    rc, out = rw.run("--reports", tag="v2", seed=False, capsys=capsys)
    assert rc == 2 and "install the core at v2 first" in out


def test_reports_refuses_a_tag_without_the_files(rw, capsys):
    git("rm", "-q", "scripts/ops/data_qa.py", cwd=rw.dev)
    git("commit", "-q", "-m", "no qa", cwd=rw.dev)
    git("tag", "-a", "v3", "-m", "v3", cwd=rw.dev)
    git("push", "-q", "origin", "main", "v3", cwd=rw.dev)
    git("fetch", "-q", "--tags", "origin", cwd=rw.layout.prod_dir)
    git("checkout", "-q", "--detach", "refs/tags/v3", cwd=rw.layout.prod_dir)
    rc, out = rw.run("--reports", tag="v3", seed=False, capsys=capsys)
    assert rc == 2 and "scripts/ops/data_qa.py" in out


def test_reports_refuses_a_dropin_on_a_report_unit(rw, capsys):
    d = rw.layout.units_dir / "quantt-cef-risk.service.d"
    d.mkdir(parents=True)
    (d / "override.conf").write_text("[Service]\nEnvironment=X=1\n")
    rc, out = rw.reports("--apply", capsys=capsys)
    assert rc == 2 and "override.conf" in out


def test_reports_refuses_while_a_session_job_runs(rw, capsys):
    rw.cmds.active["quantt-cef-session.service"] = "active"
    rc, out = rw.reports("--apply", capsys=capsys)
    assert rc == 2 and "quantt-cef-session.service" in out


def test_reports_flag_takes_no_book_options(rw, capsys):
    with pytest.raises(SystemExit):
        rw.run("--reports", "--book", "c4", seed=False, capsys=capsys)


# ------------------------------------------------------------------ the books' installs, with report units present

def test_a_book_install_refuses_only_at_planning_while_a_report_job_runs(rw, capsys):
    assert rw.reports("--apply", capsys=capsys)[0] == 0
    rw.cmds.active["quantt-cef-dataqa.service"] = "active"
    rc, out = rw.run("--apply", capsys=capsys)
    assert rc == 2 and "quantt-cef-dataqa.service" in out and "report job" in out
    rw.cmds.active.pop("quantt-cef-dataqa.service")
    assert rw.run("--apply", capsys=capsys)[0] == 0


def test_a_report_job_starting_mid_install_cannot_fail_the_book_install(rw, capsys):
    assert rw.reports("--apply", capsys=capsys)[0] == 0
    rw.cmds.start_at_reload = ("quantt-cef-dataqa.service", "4242", {})
    rc, out = rw.run("--apply", capsys=capsys)
    assert rc == 0, out
    assert "ALERT" not in out


def test_c4_install_is_not_refused_by_report_unit_files_on_disk(rw, capsys):
    assert rw.reports("--apply", capsys=capsys)[0] == 0
    rc, out = rw.c4("--apply", capsys=capsys)
    assert rc == 0, out


def test_book_installs_touch_no_report_unit(rw, capsys):
    assert rw.reports("--apply", "--enable", capsys=capsys)[0] == 0
    before = _unit_bytes(rw, iv.REPORT_UNIT_FILES)
    rw.cmds.calls.clear()
    assert rw.run("--apply", capsys=capsys)[0] == 0
    assert rw.c4("--apply", capsys=capsys)[0] == 0
    assert _unit_bytes(rw, iv.REPORT_UNIT_FILES) == before
    for c in _mutating_calls(rw):
        assert not any("dataqa" in x or "risk" in x or "reports" in x for x in c), c


def _load_base(tmp_path, monkeypatch):
    blob = subprocess.run(["git", "-C", str(REAL_REPO), "show", f"{BASE}:quantt/deploy/install_vm.py"],
                          capture_output=True, text=True)
    assert blob.returncode == 0, f"cannot read {BASE}'s installer from git: {blob.stderr}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "install_vm_base.py"
    path.write_text(blob.stdout)
    spec = importlib.util.spec_from_file_location("install_vm_base", path)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)      # dataclasses look their module up there
    spec.loader.exec_module(mod)
    return mod


def test_the_books_rendered_units_are_byte_identical_to_origin_mains(tmp_path, monkeypatch, capsys):
    base = _load_base(tmp_path / "b", monkeypatch)
    w = C4World(tmp_path / "w")
    core_argv = ["--tag", "v1", "--vault", "example-vault-x1", "--seed-from", str(w.seed)]
    rc_b, out_b = _run_with(base, w, core_argv, capsys)
    rc_n, out_n = _run_with(iv, w, core_argv, capsys)
    assert rc_b == rc_n == 0 and out_b == out_n
    assert _run_with(base, w, core_argv + ["--apply"], capsys)[0] == 0
    core_b = _unit_bytes(w, iv.ALL_UNIT_FILES)
    assert _run_with(iv, w, core_argv + ["--apply"], capsys)[0] == 0
    assert _unit_bytes(w, iv.ALL_UNIT_FILES) == core_b
    c4_argv = ["--tag", "v1", "--vault", "example-vault-x1", "--book", "c4", "--eod-from", EOD,
               "--seed-from", str(w.c4_seed)]
    rc_b, out_b = _run_with(base, w, c4_argv, capsys)
    rc_n, out_n = _run_with(iv, w, c4_argv, capsys)
    assert rc_b == rc_n == 0 and out_b == out_n
    assert _run_with(base, w, c4_argv + ["--apply"], capsys)[0] == 0
    c4_b = _unit_bytes(w, iv.C4_VM.unit_files)
    assert _run_with(iv, w, c4_argv + ["--apply"], capsys)[0] == 0
    assert _unit_bytes(w, iv.C4_VM.unit_files) == c4_b
