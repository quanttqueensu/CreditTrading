"""`ops.prod_state` says which machine is prod and whether it is armed.

WHY THIS FILE EXISTS
--------------------
From 2026-09-28 three surfaces told every session "no live book, nothing
trades" from string constants, through the first armed session on 2026-09-29
and every trading day after it (`docs/ROADMAP.md` 4.8). Their replacement is a
measurement, and a measurement can be wrong in the two ways that matter on this
desk: it can call a machine safe that is not (two armed schedulers on one
Alpaca account double the book, `CLAUDE.md` order-path rule 2), or it can
invent a state it could not read. These tests pin both directions:

  * armed, per-day, dry and off are told apart by the gates the runner uses
    (`docs/RUNNER.md` gates 1 and 2), not by what a document says;
  * a machine that cannot be read is UNMEASURED with the reason, and is never
    counted as safe (one armed + one unreadable says "not ruled out");
  * two armed machines raise the WARNING.

The OFF case is a real reading: on 2026-10-08, mid cut-over, the laptop's jobs
were unloaded and disabled while its plists still said DRY_RUN=0. A first
version of this module called that armed and raised a false two-schedulers
WARNING; `test_unloaded_and_disabled_is_off_with_a_caution` is that day.

HERMETIC. Every command is a fake `run`; the laptop is built under tmp_path;
the VM's reply is a canned string. No launchctl, git or ssh runs, and no figure
here is about the market: the equity values are synthetic and only test that
the file's own header is what gets read.
"""
from __future__ import annotations

import plistlib
import subprocess

import pytest

from ops import prod_state as ps
from quantt.deploy import install_prod as ip

LABELS = [j.label for j in ip.JOBS]
SESSION_LABEL = next(j.label for j in ip.JOBS if j.log_stem == "session")


# ------------------------------------------------------------------ fakes --
class FakeRun:
    """Stands in for subprocess.run. Answers by command; records every argv."""

    def __init__(self, **answers):
        self.answers = answers
        self.calls = []

    def __call__(self, cmd, **kw):
        cmd = [str(c) for c in cmd]
        self.calls.append((cmd, kw))
        key = cmd[0] if cmd[0] != "launchctl" else f"launchctl {cmd[1]}"
        ans = self.answers.get(key.replace(" ", "_").replace("-", "_"))
        if ans is None:
            raise AssertionError(f"unexpected command {cmd}")
        if isinstance(ans, BaseException):
            raise ans
        rc, out, err = ans
        return subprocess.CompletedProcess(cmd, rc, out, err)


def launchctl_list(loaded=LABELS):
    rows = ["PID\tStatus\tLabel"] + [f"-\t0\t{lab}" for lab in loaded]
    return (0, "\n".join(rows) + "\n", "")


def print_disabled(disabled=()):
    body = "".join(f'\t"{lab}" => disabled\n' for lab in disabled)
    return (0, f"disabled services = {{\n{body}\t\"com.apple.x\" => enabled\n}}\n", "")


def laptop_run(loaded=LABELS, disabled=(), tag="release-test-1"):
    return FakeRun(git=(0, tag + "\n", ""), launchctl_list=launchctl_list(loaded),
                   launchctl_print_disabled=print_disabled(disabled))


# A header deliberately NOT in the collector's column order: the reader must
# use the file's own header, never a remembered layout.
EQUITY = ("read_at_utc,cash,equity,date,n_positions\n"
          "2026-01-05T21:10:00+00:00,1.0,111.11,2026-01-05,3\n"
          "2026-01-06T21:10:00+00:00,2.0,222.22,2026-01-06,4\n")


def make_laptop(home, dry_run="0", auto_armed=True, plists=True, equity=EQUITY):
    lay = ip.Layout(home)
    lay.prod_dir.mkdir(parents=True)
    lay.state_dir.mkdir(parents=True)
    if plists:
        lay.agents_dir.mkdir(parents=True)
        for job in ip.JOBS:
            env = {"QUANTT_STATE_DIR": str(lay.state_dir),
                   "QUANTT_ENV_FILE": "/nonexistent/never-read.env"}
            if dry_run is not None:
                env["DRY_RUN"] = dry_run
            lay.plist_path(job).write_bytes(
                plistlib.dumps({"Label": job.label, "EnvironmentVariables": env}))
    if auto_armed:
        (lay.state_dir / "AUTO_ARMED").write_text("test\n")
    (lay.state_dir / "verify.log").write_text(
        "2026-01-05 FAIL cef something\n2026-01-06 PASS cef traded 2 order(s), 2 filled\n")
    if equity is not None:
        (lay.state_dir / "equity.csv").write_text(equity)
    return lay


def vm_reply(dry="DRY_RUN=0", auto="present", timers="active active active",
             enabled="enabled enabled enabled", end=True, load="loaded"):
    rows = [("tag", 0, "release-vm-1"), ("load_state", 0, load), ("dry_run", 0, dry),
            ("timers", 0 if timers == "active active active" else 3, timers),
            ("timers_enabled", 0, enabled), ("auto_armed", 0, auto),
            ("verify", 0, "2026-01-06 PASS cef traded 2 order(s), 2 filled"),
            ("equity_header", 0, "date,equity,read_at_utc"),
            ("equity_last", 0, "2026-01-06,333.33,2026-01-06T21:10:00+00:00")]
    if end:
        rows.append(("END", 0, "quantt-prod-state"))
    return "".join(f"{k}\t{rc}\t{v}\n" for k, rc, v in rows)


@pytest.fixture
def ssh_config(tmp_path):
    # 203.0.113.0/24 is RFC 5737's documentation range: not the VM's address,
    # which never goes in a tracked file (docs/RUNBOOK.md section 8).
    p = tmp_path / "ssh_config"
    p.write_text(f"Host {ps.VM_ALIAS}\n    HostName 203.0.113.9\n    User someone\n")
    return p


def vm_run(stdout="", rc=0, stderr="", exc=None):
    return FakeRun(ssh=exc if exc is not None else (rc, stdout, stderr))


# ----------------------------------------------------------------- laptop --
class TestLaptop:
    def test_laptop_armed(self, tmp_path):
        make_laptop(tmp_path)
        m = ps.laptop(home=tmp_path, run=laptop_run(), uid=501)
        assert m["arming"] == ps.ARMED
        assert m["tag"] == {"value": "release-test-1"}
        assert m["auto_armed"]["value"] is True

    def test_laptop_disarmed(self, tmp_path):
        make_laptop(tmp_path, dry_run="1")
        m = ps.laptop(home=tmp_path, run=laptop_run(), uid=501)
        assert m["arming"] == ps.DRY and "DRY_RUN=1" in m["arming_why"]

    def test_unset_dry_run_is_dry_not_armed(self, tmp_path):
        """Gate 1: only exactly "0" transmits; unset is dry."""
        make_laptop(tmp_path, dry_run=None)
        m = ps.laptop(home=tmp_path, run=laptop_run(), uid=501)
        assert m["arming"] == ps.DRY and "unset" in m["arming_why"]

    def test_dry_run_0_without_auto_armed_is_per_day_approval_only(self, tmp_path):
        make_laptop(tmp_path, auto_armed=False)
        m = ps.laptop(home=tmp_path, run=laptop_run(), uid=501)
        assert m["arming"] == ps.PER_DAY

    def test_unloaded_and_disabled_is_off_with_a_caution(self, tmp_path):
        """2026-10-08, mid cut-over: jobs booted out and disabled, plists
        still DRY_RUN=0. Not armed -- but the leftover is said."""
        make_laptop(tmp_path, auto_armed=False)
        m = ps.laptop(home=tmp_path, run=laptop_run(loaded=(), disabled=LABELS), uid=501)
        assert m["arming"] == ps.OFF
        assert any("DRY_RUN=0" in c for c in m["cautions"])

    def test_unloaded_but_not_disabled_still_counts(self, tmp_path):
        """RUNBOOK 8.5 step 1: launchd loads it again at the next login."""
        make_laptop(tmp_path)
        m = ps.laptop(home=tmp_path, run=laptop_run(loaded=()), uid=501)
        assert m["arming"] == ps.ARMED
        assert "next login" in m["arming_why"]

    def test_unreadable_launchd_is_never_assumed_safe(self, tmp_path):
        make_laptop(tmp_path)
        run = FakeRun(git=(0, "t\n", ""),
                      launchctl_list=FileNotFoundError("launchctl"),
                      launchctl_print_disabled=FileNotFoundError("launchctl"))
        m = ps.laptop(home=tmp_path, run=run, uid=501)
        assert m["arming"] == ps.ARMED
        assert "counts as scheduled" in m["arming_why"]
        assert ps.UNMEASURED in m["jobs"]["session"]["loaded"]

    def test_no_plists_is_not_installed(self, tmp_path):
        make_laptop(tmp_path, plists=False)
        m = ps.laptop(home=tmp_path, run=laptop_run(), uid=501)
        assert m["arming"] == ps.NOT_INSTALLED

    def test_tag_failure_is_unmeasured_with_the_command(self, tmp_path):
        make_laptop(tmp_path)
        run = laptop_run()
        run.answers["git"] = (128, "", "fatal: No names found, cannot describe anything.")
        m = ps.laptop(home=tmp_path, run=run, uid=501)
        assert ps.UNMEASURED in m["tag"] and "describe --tags" in m["tag"][ps.UNMEASURED]

    def test_equity_is_read_by_the_files_own_header(self, tmp_path):
        make_laptop(tmp_path)
        e = ps.laptop(home=tmp_path, run=laptop_run(), uid=501)["equity"]["value"]
        assert (e["date"], e["equity"]) == ("2026-01-06", "222.22")
        assert e["read_at_utc"] == "2026-01-06T21:10:00+00:00"

    def test_equity_without_an_equity_column_is_unmeasured(self, tmp_path):
        make_laptop(tmp_path, equity="date,cash\n2026-01-06,1.0\n")
        e = ps.laptop(home=tmp_path, run=laptop_run(), uid=501)["equity"]
        assert ps.UNMEASURED in e and "equity" in e[ps.UNMEASURED]

    def test_missing_equity_file_is_absent_not_zero(self, tmp_path):
        make_laptop(tmp_path, equity=None)
        e = ps.laptop(home=tmp_path, run=laptop_run(), uid=501)["equity"]
        assert "absent" in e and "value" not in e

    def test_never_touches_the_retired_ibkr_tree(self, tmp_path):
        """`~/prod/QUANTT` is the retired IBKR tree, not the Alpaca prod."""
        make_laptop(tmp_path)
        (tmp_path / "prod" / "QUANTT").mkdir()
        run = laptop_run()
        ps.laptop(home=tmp_path, run=run, uid=501)
        assert not any(str(tmp_path / "prod" / "QUANTT") in " ".join(c) for c, _ in run.calls)

    def test_only_read_only_launchctl_verbs(self, tmp_path):
        make_laptop(tmp_path)
        run = laptop_run()
        ps.laptop(home=tmp_path, run=run, uid=501)
        verbs = {c[1] for c, _ in run.calls if c[0] == "launchctl"}
        assert verbs <= {"list", "print-disabled"}


# --------------------------------------------------------------------- vm --
class TestVM:
    def test_vm_armed(self, ssh_config):
        m = ps.vm(ssh_config=ssh_config, run=vm_run(vm_reply()))
        assert m["arming"] == ps.ARMED
        assert m["tag"] == {"value": "release-vm-1"}
        assert m["equity"]["value"]["equity"] == "333.33"

    def test_vm_shadow_is_dry(self, ssh_config):
        m = ps.vm(ssh_config=ssh_config, run=vm_run(vm_reply(dry="DRY_RUN=1", auto="absent")))
        assert m["arming"] == ps.DRY

    def test_vm_timers_stopped_but_enabled_still_count(self, ssh_config):
        """RUNBOOK 8.5 step 2 stops the timers; enabled ones start at boot."""
        m = ps.vm(ssh_config=ssh_config, run=vm_run(vm_reply(
            timers="inactive inactive inactive")))
        assert m["arming"] == ps.ARMED and "starts again at boot" in m["arming_why"]

    def test_vm_timers_inactive_and_disabled_is_off(self, ssh_config):
        m = ps.vm(ssh_config=ssh_config, run=vm_run(vm_reply(
            timers="inactive inactive inactive", enabled="disabled disabled disabled")))
        assert m["arming"] == ps.OFF

    def test_vm_unreachable_is_unmeasured(self, ssh_config):
        run = vm_run(exc=subprocess.TimeoutExpired(["ssh"], 3))
        m = ps.vm(ssh_config=ssh_config, run=run, timeout=3)
        assert m["arming"] == ps.UNMEASURED
        assert "did not finish within 3s" in m[ps.UNMEASURED]
        assert run.calls[0][1]["timeout"] == 3

    def test_vm_ssh_failure_is_unmeasured_and_never_names_the_address(self, ssh_config):
        """The repo is public; ssh's error names the VM's address."""
        run = vm_run(rc=255, stderr="ssh: connect to host 203.0.113.9 port 22: Operation timed out\n")
        m = ps.vm(ssh_config=ssh_config, run=run)
        assert m["arming"] == ps.UNMEASURED
        assert "203.0.113.9" not in str(m) and "<address>" in m[ps.UNMEASURED]

    def test_scrub_removes_addresses_and_keeps_a_timestamp(self):
        s = ps.scrub("connect to host 203.0.113.9 or 2001:db8:0:1::5 or fe80::1 at 12:05:59\nmore")
        assert "203.0.113.9" not in s and "2001:db8" not in s and "fe80::1" not in s
        assert "12:05:59" in s and "more" not in s

    def test_vm_reply_cut_short_is_unmeasured(self, ssh_config):
        m = ps.vm(ssh_config=ssh_config, run=vm_run(vm_reply(end=False)))
        assert m["arming"] == ps.UNMEASURED and "cut short" in m[ps.UNMEASURED]

    def test_no_alias_means_no_ssh_at_all(self, tmp_path):
        cfg = tmp_path / "ssh_config"
        cfg.write_text("Host somewhere-else\n")
        run = vm_run(vm_reply())
        m = ps.vm(ssh_config=cfg, run=run)
        assert m["arming"] == ps.UNMEASURED and "has no `Host quantt-vm`" in m[ps.UNMEASURED]
        assert run.calls == []

    def test_real_ssh_is_refused_under_netguard(self, ssh_config):
        """ssh is a child process: netguard cannot see it. A test that forgot
        to pass a fake `run` would otherwise connect to the real VM."""
        m = ps.vm(ssh_config=ssh_config)
        assert m["arming"] == ps.UNMEASURED and "netguard" in m[ps.UNMEASURED]

    def test_one_ssh_call_batch_mode_with_a_connect_timeout(self, ssh_config):
        run = vm_run(vm_reply())
        ps.vm(ssh_config=ssh_config, run=run)
        assert len(run.calls) == 1
        cmd, kw = run.calls[0]
        assert cmd[0] == "ssh" and "BatchMode=yes" in cmd
        assert f"ConnectTimeout={ps.SSH_CONNECT_TIMEOUT_S}" in cmd
        assert kw["input"] == ps.REMOTE_SCRIPT

    def test_remote_script_never_reads_the_key_files(self):
        """/run/quantt holds the keys (RUNBOOK 8). The Environment line is cut
        to DRY_RUN on the VM, so even the key file's path stays there."""
        assert "/run/quantt" not in ps.REMOTE_SCRIPT
        assert "QUANTT_ENV_FILE" not in ps.REMOTE_SCRIPT
        env_line = next(ln for ln in ps.REMOTE_SCRIPT.splitlines() if "-p Environment" in ln)
        assert "grep '^DRY_RUN='" in env_line

    def test_two_dry_run_assignments_are_a_gap_not_a_pick(self, ssh_config):
        m = ps.vm(ssh_config=ssh_config, run=vm_run(vm_reply(dry="DRY_RUN=1 DRY_RUN=0")))
        assert m["arming"] == ps.UNMEASURED


# ---------------------------------------------------------------- verdict --
def machine(arming, cautions=()):
    return {"arming": arming, "arming_why": f"because {arming}", "cautions": list(cautions),
            "equity": {"value": {"date": "2026-01-06", "equity": "1", "source": "x"}}}


class TestVerdict:
    def test_both_armed_warns(self):
        v = ps.verdict({"laptop": machine(ps.ARMED), "vm": machine(ps.ARMED)})
        assert v["warning"].startswith("WARNING: TWO ARMED SCHEDULERS")
        assert v["prod"] is None and "order-path rule 2" in v["warning"]

    def test_armed_beside_per_day_also_warns(self):
        """A per-day approval on one machine plus AUTO_ARMED on the other is
        two sends for that day."""
        v = ps.verdict({"laptop": machine(ps.ARMED), "vm": machine(ps.PER_DAY)})
        assert v["warning"]

    def test_one_armed_is_prod_and_its_equity_is_live(self):
        v = ps.verdict({"laptop": machine(ps.OFF), "vm": machine(ps.ARMED)})
        assert v["prod"] == "vm" and not v["warning"]
        assert v["equity"]["value"]["equity"] == "1"

    def test_one_armed_beside_unmeasured_is_not_ruled_out(self):
        v = ps.verdict({"laptop": machine(ps.ARMED), "vm": machine(ps.UNMEASURED)})
        assert v["prod"] == "laptop" and "not ruled out" in v["line"]

    def test_nothing_armed_is_said_and_carries_no_equity(self):
        v = ps.verdict({"laptop": machine(ps.DRY), "vm": machine(ps.OFF)})
        assert v["prod"] is None and "nothing is sent" in v["line"] and v["equity"] is None

    def test_cautions_are_collected_from_every_machine(self):
        v = ps.verdict({"laptop": machine(ps.OFF, ["left DRY_RUN=0"]), "vm": machine(ps.ARMED)})
        assert v["cautions"] == ["laptop: left DRY_RUN=0"]


# ------------------------------------------------------------- end to end --
def test_measure_and_render_end_to_end(tmp_path, ssh_config):
    """laptop OFF + VM ARMED, through measure() and the renderer orient uses."""
    make_laptop(tmp_path, auto_armed=False)
    lap_run = laptop_run(loaded=(), disabled=LABELS)
    run = FakeRun(**lap_run.answers, ssh=(0, vm_reply(), ""))
    d = ps.measure(run=run, home=tmp_path, ssh_config=ssh_config)
    assert d["verdict"]["prod"] == "vm"
    lines = []
    ps.render_lines(d, lambda label, value="": lines.append(f"{label} {value}"))
    out = "\n".join(lines)
    assert "prod is the VM: ARMED" in out and "caution" in out
