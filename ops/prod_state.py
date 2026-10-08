#!/usr/bin/env python3
"""Which machine is prod, and is it armed? Measured on every call, never written.

    python3 -m ops.prod_state            # the readout (orient's PROD section)
    python3 -m ops.prod_state --json
    python3 -m ops.prod_state --no-vm    # the laptop only: no SSH

WHY THIS FILE EXISTS
--------------------
On 2026-09-28 IBKR was retired and three surfaces were rewritten to say so:
`ops.orient` printed "prod none ... the Alpaca prod (cloud VM) is not built"
and "live book NONE -- nothing trades", the SessionStart banner "NO LIVE BOOK
... Nothing trades", and the status line "no live book" in red. Each was a
string constant. The first armed session was 2026-09-29 (the laptop's
`~/quantt_state/cef/verify.log`) and the book has traded since, while all three
went on saying it did not, because a constant cannot notice that it has become
false. That is the failure the IBKR-era reader existed to prevent (a 21-session
outage under surfaces that read "ok") with the sign reversed.

The answer to "which machine is prod" is also about to move: prod goes from the
laptop (launchd) to an Azure VM (systemd) by `docs/RUNBOOK.md` section 8. A
written answer would be wrong within the week. So this module measures, and
orient, the banner and the status line all read it (`docs/ROADMAP.md` 4.8).

WHAT "ARMED" MEANS HERE (`docs/RUNNER.md`, gates 1 and 2)
--------------------------------------------------------
  ARMED          the scheduler will fire the session job, DRY_RUN is exactly
                 "0" in its environment, AND `<state>/AUTO_ARMED` exists: every
                 decided plan is sent.
  PER_DAY        as ARMED but with no AUTO_ARMED: a scheduled send transmits
                 only a plan that carries a recorded per-day approval.
  DRY            the scheduler fires it, and DRY_RUN is anything but "0" (unset
                 included): gate 1 sends nothing.
  OFF            installed, but the scheduler will not fire the session job:
                 launchd has it unloaded AND disabled, or systemd has its timer
                 inactive AND not enabled. What its files say is kept, and a
                 DRY_RUN=0 or an AUTO_ARMED left behind is raised as a caution.
  NOT_INSTALLED  that machine has no session job.
  UNMEASURED     a reading the call needs failed; the reason is kept.

The scheduler's environment is read where the scheduler reads it: the laptop's
plist `EnvironmentVariables`, and systemd's LOADED `Environment` on the VM, not
the unit file (`quantt/deploy/install_vm.py` records why the loaded copy is the
truth). "Will fire" is not "is loaded right now": `docs/RUNBOOK.md` 8.5 step 1
records that launchd loads a plist in `~/Library/LaunchAgents` again at the
next login, so an unloaded job that is NOT disabled still counts as scheduled,
and a stopped timer that is still enabled starts again at boot. Only unloaded
and disabled (or inactive and not enabled) is OFF.

MEASURED 2026-10-08, mid cut-over: the laptop's three jobs were unloaded and
disabled with AUTO_ARMED removed, but its plists still said DRY_RUN=0 (8.5
step 1a not yet run). A first version of this module read "DRY_RUN=0 in the
plist" as armed and printed the two-schedulers WARNING over a scheduler that
could not fire. That false alarm is why OFF exists, and why the plists'
DRY_RUN=0 is still reported (as a caution, not a hazard).

TWO ARMED SCHEDULERS ON ONE ACCOUNT
-----------------------------------
Both machines trade one Alpaca paper account. Each checks gate 6 against its
own state dir, so two schedulers with DRY_RUN=0 would each send, and only the
Alpaca-side `client_order_id` prefix check would stand between them and a
doubled book (`CLAUDE.md` order-path rule 2). `verdict()` raises a WARNING
whenever both machines are ARMED or PER_DAY. A machine that cannot be measured
is never assumed safe: one armed machine beside an UNMEASURED one is reported
as "a second armed scheduler is not ruled out".

READ-ONLY, AND WHAT IT NEVER TOUCHES
------------------------------------
On the laptop: `launchctl list` and `launchctl print-disabled` (read-only verbs;
the only ones the test harness lets through), `git describe`, and file reads.
On the VM: one `ssh` call that runs `REMOTE_SCRIPT`, a fixed read-only script.
It never reads `QUANTT_ENV_FILE` or `config/.env`, never reads `/run/quantt`
(the keys), and cuts systemd's Environment down to DRY_RUN on the VM so not
even the key file's path crosses the wire. It never touches `~/prod/QUANTT`,
the retired IBKR tree, which is not the Alpaca prod.

THE REPO IS PUBLIC
------------------
The VM is reached only by the ssh alias `quantt-vm`. Its address lives in
`~/.ssh/config` and nowhere in this repository. ssh's own errors name the
address ("connect to host <ip> port 22"), and readouts get pasted into tracked
notes, so stderr is scrubbed of IP addresses before it is returned.

STDLIB ONLY
-----------
The SessionStart hook and the status line import this on every session, so it
imports only the standard library, the NYSE calendar, and the two installers,
which are stdlib-only themselves and are the single owners of the labels, unit
names and paths read here. A path written twice drifts; one imported does not.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from quantt.deploy import install_prod as ip  # noqa: E402
from quantt.deploy import install_vm as iv  # noqa: E402

ARMED, PER_DAY, DRY, OFF = "ARMED", "PER_DAY", "DRY", "OFF"
NOT_INSTALLED, UNMEASURED = "NOT_INSTALLED", "UNMEASURED"
HOT = (ARMED, PER_DAY)          # scheduled with DRY_RUN=0: can transmit

VM_ALIAS = "quantt-vm"
SSH_CONNECT_TIMEOUT_S = 3
# orient's budget for the whole ssh call (connect, every read in REMOTE_SCRIPT,
# teardown). Measured 2026-10-08 from the laptop: ~1 s end to end. The banner
# passes its own, shorter budget (`.claude/hooks/book_state.py`).
VM_TIMEOUT_S = 10
LOCAL_TIMEOUT_S = 5

_VM_LAYOUT = iv.Layout(Path("/home") / iv.SERVICE_USER)
_VM_SESSION = next(j for j in iv.VM_JOBS if j.job.log_stem == "session")
VM_TIMERS = tuple(j.timer for j in iv.VM_JOBS)

Run = Callable[..., subprocess.CompletedProcess]


# --------------------------------------------------------------- readings --
# Every reading is a dict with exactly one of three keys, so a renderer can
# never print a gap as if it were a value:
#   {"value": v}          measured (v may be None, e.g. DRY_RUN unset)
#   {"absent": why}       measured, and the thing does not exist
#   {"UNMEASURED": why}   could not be measured; `why` names what was tried
def _val(v, **extra) -> dict:
    return {"value": v, **extra}


def _absent(why: str) -> dict:
    return {"absent": why}


def _unm(why: str) -> dict:
    return {UNMEASURED: why}


def show(r: dict | None) -> str:
    """One reading as text. A gap always reads as a gap."""
    if not isinstance(r, dict):
        return "UNMEASURED — no reading"
    if UNMEASURED in r:
        return f"UNMEASURED — {r[UNMEASURED]}"
    if "absent" in r:
        return f"none ({r['absent']})"
    return str(r["value"])


_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
# Four or more groups, or a `::` form. Three groups is left alone: that is what
# an HH:MM:SS timestamp looks like, and an error's time is worth keeping.
_IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b"
                   r"|(?:\b[0-9a-fA-F]{1,4})?(?::[0-9a-fA-F]{1,4})*::(?:[0-9a-fA-F]{1,4}\b)?"
                   r"(?::[0-9a-fA-F]{1,4}\b)*")


def scrub(text: str) -> str:
    """ssh's stderr with any IP address replaced, first line only, short.
    The repo is public and readouts get pasted (module docstring)."""
    first = (text or "").strip().splitlines()[0:1]
    line = first[0] if first else ""
    return _IPV6.sub("<address>", _IPV4.sub("<address>", line))[:160]


def _cmd(cmd: list) -> str:
    return " ".join(shlex.quote(str(c)) for c in cmd)


def _call(run: Run, cmd: list, timeout: float, **kw):
    """(CompletedProcess, None) or (None, why). Never raises for the usual
    ways a read-only command fails: missing binary, timeout."""
    try:
        return run(cmd, capture_output=True, text=True, timeout=timeout, **kw), None
    except subprocess.TimeoutExpired:
        return None, f"`{_cmd(cmd)}` did not finish within {timeout}s"
    except OSError as e:
        return None, f"`{_cmd(cmd)}` could not run: {type(e).__name__}: {e}"


# ----------------------------------------------------------------- shared --
VERDICT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (PASS|FAIL)\b")


def verdict_line(line: str) -> dict:
    """A verify.log line: `<date> PASS|FAIL <book> <reason>` (quantt/session/verify.py).
    A line in another shape is kept whole, with no date or verdict invented."""
    m = VERDICT_RE.match(line)
    return {"date": m.group(1) if m else None,
            "verdict": m.group(2) if m else None, "line": line}


def equity_row(header_line: str, last_line: str, where: str) -> dict:
    """The last equity.csv row, by the file's OWN header.

    The collector writes it (`quantt/collect/collect.py`, step
    account_snapshot): Alpaca's account equity at D's close, read after the
    close. That makes it the broker-confirmed figure, unlike the probe
    snapshot. The columns are read from the header, not assumed, so a reordered
    or renamed file is a named gap instead of a confident wrong number.
    """
    cols = next(csv.reader([header_line]), [])
    missing = [c for c in ("date", "equity") if c not in cols]
    if missing:
        return _unm(f"{where} header is {cols}: no {missing} column")
    if last_line.strip() == header_line.strip():
        return _absent(f"{where} has a header and no rows yet")
    row = next(csv.reader([last_line]), [])
    if len(row) != len(cols):
        return _unm(f"{where} last row has {len(row)} fields for {len(cols)} columns")
    rec = dict(zip(cols, row))
    return _val({"date": rec["date"], "equity": rec["equity"],
                 "read_at_utc": rec.get("read_at_utc"), "source": where})


def _gate(dry_run: dict, auto_armed: dict) -> tuple[str, str]:
    """(ARMED|PER_DAY|DRY|UNMEASURED, why) from the readings gates 1 and 2 use."""
    if UNMEASURED in dry_run:
        return UNMEASURED, f"DRY_RUN {show(dry_run)}"
    d = dry_run.get("value")
    if d != "0":
        return DRY, ("DRY_RUN unset (gate 1: only exactly \"0\" transmits)"
                     if d is None else f"DRY_RUN={d}")
    if UNMEASURED in auto_armed:
        return UNMEASURED, f"DRY_RUN=0 but AUTO_ARMED {show(auto_armed)}"
    if auto_armed.get("value") is True:
        return ARMED, "DRY_RUN=0 + AUTO_ARMED: every decided plan is sent"
    return PER_DAY, ("DRY_RUN=0, no AUTO_ARMED: sends only a plan with a "
                     "recorded per-day approval")


def _arming(dry_run: dict, auto_armed: dict, scheduled: dict) -> tuple[str, str, list]:
    """(state, why, cautions). `scheduled` is a reading of whether the
    scheduler will fire the session job; UNMEASURED there is counted as
    scheduled, because a machine that cannot be measured is never assumed safe.
    """
    gate, why = _gate(dry_run, auto_armed)
    cautions = []
    if scheduled.get("value") is False:
        left = []
        if (dry_run.get("value") == "0"):
            left.append("its files still say DRY_RUN=0")
        if auto_armed.get("value") is True:
            left.append("AUTO_ARMED is still present")
        if left:
            cautions.append(f"scheduler off ({scheduled.get('why')}), but {' and '.join(left)}"
                            f": docs/RUNBOOK.md 8.5 step 1 sets DRY_RUN=1 and removes AUTO_ARMED")
        files = (f"DRY_RUN={_dry_text(dry_run)}, AUTO_ARMED "
                 + (show(auto_armed) if "value" not in auto_armed
                    else "present" if auto_armed["value"] else "absent"))
        return OFF, f"scheduler off ({scheduled.get('why')}); its files say {files}", cautions
    if UNMEASURED in scheduled:
        why += f"; whether the scheduler fires it is {show(scheduled)}, so it counts as scheduled"
    else:
        why += f"; {scheduled.get('why')}"
    return gate, why, cautions


def trading_days_since(date_iso: str | None, today: dt.date | None = None) -> int | None:
    """Trading days after `date_iso` up to and including today, by the NYSE
    calendar. None when the date is missing or unparseable: an age is shown
    only when it was computed."""
    if not date_iso:
        return None
    try:
        d = dt.date.fromisoformat(date_iso)
        from ops.schedule import nyse_calendar as cal
    except (ValueError, ImportError):
        return None
    today = today or dt.date.today()
    n, cur = 0, d
    while cur < today and n < 4000:
        cur += dt.timedelta(days=1)
        if cal.is_trading_day(cur):
            n += 1
    return n


# ----------------------------------------------------------------- laptop --
def _exists(p: Path) -> bool:
    """True/False, raising on anything but "not there" (a permission error is
    a gap, not an absence)."""
    try:
        p.stat()
        return True
    except (FileNotFoundError, NotADirectoryError):
        return False


def _git_tag(run: Run, clone: Path) -> dict:
    if not clone.is_dir():
        return _absent(f"no clone at {clone}")
    cmd = ["git", "-C", str(clone), "describe", "--tags"]
    r, why = _call(run, cmd, LOCAL_TIMEOUT_S)
    if why:
        return _unm(why)
    if r.returncode != 0 or not r.stdout.strip():
        return _unm(f"`{_cmd(cmd)}` exited {r.returncode}: {scrub(r.stderr)}")
    return _val(r.stdout.strip())


def _launchctl_loaded(run: Run) -> dict:
    """{label: {"pid", "last_exit"}} for every job launchd has loaded in this
    GUI session, from `launchctl list` (PID, Status, Label, tab-separated)."""
    r, why = _call(run, ["launchctl", "list"], LOCAL_TIMEOUT_S)
    if why:
        return _unm(why)
    if r.returncode != 0:
        return _unm(f"`launchctl list` exited {r.returncode}: {scrub(r.stderr)}")
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2] != "Label":
            out[parts[2]] = {"pid": None if parts[0] == "-" else parts[0],
                             "last_exit": parts[1]}
    return _val(out)


_DISABLED_RE = re.compile(r'"([^"]+)"\s*=>\s*(\w+)')


def _launchctl_disabled(run: Run, uid: int) -> dict:
    """{label: True if disabled} from launchd's override database. A label that
    is not listed has no override; then the plist's own `Disabled` key governs
    (launchd's default). macOS has printed both `disabled`/`enabled` and
    `true`/`false` here; any other word is a gap, not a guess."""
    cmd = ["launchctl", "print-disabled", f"gui/{uid}"]
    r, why = _call(run, cmd, LOCAL_TIMEOUT_S)
    if why:
        return _unm(why)
    if r.returncode != 0:
        return _unm(f"`{_cmd(cmd)}` exited {r.returncode}: {scrub(r.stderr)}")
    out = {}
    for label, word in _DISABLED_RE.findall(r.stdout):
        w = word.lower()
        if w in ("disabled", "true"):
            out[label] = True
        elif w in ("enabled", "false"):
            out[label] = False
        else:
            out[label] = None
    return _val(out)


def _read_last_line(p: Path) -> str | None:
    lines = [ln for ln in p.read_text(errors="replace").splitlines() if ln.strip()]
    return lines[-1] if lines else None


def _local_verify(p: Path) -> dict:
    try:
        if not _exists(p):
            return _absent(f"no {p.name} yet")
        last = _read_last_line(p)
    except OSError as e:
        return _unm(f"reading {p}: {type(e).__name__}: {e}")
    return _val(verdict_line(last)) if last else _absent(f"{p.name} is empty")


def _local_equity(p: Path) -> dict:
    try:
        if not _exists(p):
            return _absent(f"no {p.name} yet")
        lines = [ln for ln in p.read_text(errors="replace").splitlines() if ln.strip()]
    except OSError as e:
        return _unm(f"reading {p}: {type(e).__name__}: {e}")
    if not lines:
        return _unm(f"{p} is empty: no header to read columns from")
    return equity_row(lines[0], lines[-1], str(p))


def laptop(home: Path | None = None, run: Run | None = None,
           uid: int | None = None) -> dict:
    """The laptop prod (launchd), read from this machine's files and launchd.

    Paths and labels come from `quantt.deploy.install_prod` (its `Layout` and
    `JOBS`), the code that installs them. `home` and `run` are parameters so
    the tests build a home under tmp_path and fake every command.
    """
    run = run or subprocess.run
    home = Path(home) if home is not None else Path.home()
    uid = os.getuid() if uid is None else uid
    lay = ip.Layout(home)
    out = {"machine": "laptop", "scheduler": "launchd",
           "reproducer": "plistlib on ~/Library/LaunchAgents/com.quantt.alpaca.cef.*.plist"
                         "  ·  launchctl list / print-disabled  ·  git describe --tags",
           "clone": str(lay.prod_dir), "state_dir": str(lay.state_dir)}
    out["tag"] = _git_tag(run, lay.prod_dir)

    loaded = _launchctl_loaded(run)
    disabled = _launchctl_disabled(run, uid)
    jobs = {}
    for job in ip.JOBS:
        plist = lay.plist_path(job)
        j = {"label": job.label, "plist": str(plist)}
        try:
            present = _exists(plist)
            data = plistlib.loads(plist.read_bytes()) if present else None
        except Exception as e:  # unreadable or not a plist: a named gap
            j["dry_run"] = _unm(f"reading {plist}: {type(e).__name__}: {e}")
            jobs[job.log_stem] = j
            continue
        if not present:
            j["dry_run"] = _absent(f"no {plist.name}")
            jobs[job.log_stem] = j
            continue
        env = data.get("EnvironmentVariables") or {}
        j["dry_run"] = _val(env.get("DRY_RUN"))
        j["plist_state_dir"] = env.get("QUANTT_STATE_DIR")
        if UNMEASURED in loaded:
            j["loaded"] = loaded
        else:
            hit = loaded["value"].get(job.label)
            j["loaded"] = _val(hit is not None, **({"last_exit": hit["last_exit"]} if hit else {}))
        if UNMEASURED in disabled:
            j["disabled"] = disabled
        elif job.label in disabled["value"]:
            flag = disabled["value"][job.label]
            j["disabled"] = (_val(flag) if flag is not None else
                             _unm(f"launchctl print-disabled printed an unknown word for {job.label}"))
        else:
            j["disabled"] = _val(data.get("Disabled") is True, source="plist Disabled key")
        jobs[job.log_stem] = j
    out["jobs"] = jobs

    session = jobs.get("session") or {}
    sd = session.get("plist_state_dir")
    if sd and Path(sd) != lay.state_dir:
        out["state_dir_mismatch"] = (f"the session plist runs with QUANTT_STATE_DIR={sd}, "
                                     f"not the installer's {lay.state_dir}")
    try:
        out["auto_armed"] = _val(_exists(lay.state_dir / "AUTO_ARMED"))
    except OSError as e:
        out["auto_armed"] = _unm(f"stat {lay.state_dir / 'AUTO_ARMED'}: {type(e).__name__}: {e}")
    out["verify_last"] = _local_verify(lay.state_dir / "verify.log")
    out["equity"] = _local_equity(lay.state_dir / "equity.csv")

    dry = session.get("dry_run") or _unm("no session job reading")
    out["cautions"] = []
    if "absent" in dry:
        out["arming"], out["arming_why"] = NOT_INSTALLED, f"no session job ({dry['absent']})"
    else:
        out["scheduled"] = _launchd_scheduled(session)
        out["arming"], out["arming_why"], out["cautions"] = _arming(
            dry, out["auto_armed"], out["scheduled"])
    return out


def _launchd_scheduled(job: dict) -> dict:
    """Will launchd fire this job? Loaded: yes. Unloaded and not disabled: yes,
    at the next login (RUNBOOK 8.5 step 1). Unloaded and disabled: no."""
    lo, di = job.get("loaded") or {}, job.get("disabled") or {}
    if lo.get("value") is True:
        return _val(True, why="launchd has the session job loaded")
    if "value" not in lo or "value" not in di:
        return _unm(f"loaded {show(lo)}; disabled {show(di)}")
    if di["value"]:
        return _val(False, why="launchd session job unloaded and disabled")
    return _val(True, why="session job unloaded but not disabled: launchd loads it at the next login")


# --------------------------------------------------------------------- vm --
# Run on the VM as the admin user, who has passwordless sudo; /home/quantt is
# mode 750, so the state reads go through `sudo -n` (never prompt: -n fails
# instead, and the failure is reported). One line per reading:
#   <key> TAB <exit code> TAB <output, tabs/newlines flattened, cut to 400>
# then an END line, so a reply cut short is seen as cut short. Nothing here
# reads /run/quantt, and the Environment line is filtered to DRY_RUN ON THE
# VM, so the key file's path never leaves it.
_REMOTE_TEMPLATE = r"""q() { k=$1; shift; o=$("$@" 2>&1); r=$?; printf '%s\t%s\t%s\n' "$k" "$r" "$(printf '%s' "$o" | tr '\t\n' '  ' | cut -c1-400)"; }
S=@STATE@
q tag sudo -n -u @USER@ git -C @PROD@ describe --tags
q load_state systemctl show -p LoadState --value @SESSION@
q dry_run sh -c "systemctl show -p Environment --value @SESSION@ | tr ' ' '\n' | grep '^DRY_RUN=' || true"
q timers systemctl is-active @TIMERS@
q timers_enabled systemctl is-enabled @TIMERS@
q auto_armed sudo -n sh -c "if [ -e $S/AUTO_ARMED ]; then echo present; elif [ -d $S ]; then echo absent; else echo no-state-dir; fi"
q verify sudo -n sh -c "if [ -e $S/verify.log ]; then tail -n1 $S/verify.log; else echo NO-FILE; fi"
q equity_header sudo -n sh -c "if [ -e $S/equity.csv ]; then head -n1 $S/equity.csv; else echo NO-FILE; fi"
q equity_last sudo -n sh -c "if [ -e $S/equity.csv ]; then tail -n1 $S/equity.csv; else echo NO-FILE; fi"
printf 'END\t0\tquantt-prod-state\n'
"""
REMOTE_SCRIPT = (_REMOTE_TEMPLATE
                 .replace("@STATE@", shlex.quote(str(_VM_LAYOUT.state_dir)))
                 .replace("@PROD@", shlex.quote(str(_VM_LAYOUT.prod_dir)))
                 .replace("@USER@", iv.SERVICE_USER)
                 .replace("@SESSION@", _VM_SESSION.service)
                 .replace("@TIMERS@", " ".join(VM_TIMERS)))


def ssh_alias_present(alias: str, config: Path) -> bool:
    """Is there a `Host` line naming exactly this alias? Patterns are not
    expanded: the runbook sets the alias up by name, and a wildcard that
    happened to match would send this somewhere nobody chose."""
    for line in config.read_text(errors="replace").splitlines():
        m = re.match(r"^\s*Host\s+(.+?)\s*$", line, re.I)
        if m and alias in m.group(1).split():
            return True
    return False


def vm_unmeasured(why: str, alias: str = VM_ALIAS) -> dict:
    return {"machine": "vm", "scheduler": "systemd", "alias": alias,
            UNMEASURED: why, "arming": UNMEASURED, "arming_why": why, "cautions": []}


def vm(alias: str = VM_ALIAS, ssh_config: Path | None = None,
       timeout: float = VM_TIMEOUT_S, run: Run | None = None) -> dict:
    """The VM prod (systemd), read over ONE ssh call with a hard time budget.

    Only when `~/.ssh/config` names the alias: without it there is no
    sanctioned way to reach the VM, and guessing an address is out (the repo is
    public). BatchMode: a key that needs a passphrase or an unknown host key
    fails instead of prompting, because a prompt inside a hook hangs a session.

    Refuses under netguard. ssh is a child process, so the test harness's
    socket guard cannot see it (`conftest.py`); a test that reached this with
    the real `subprocess.run` would open a real connection to the VM. Tests
    pass a fake `run`, and only then does this proceed under the guard.
    """
    if run is None:
        from ops import netguard
        if netguard.is_active():
            return vm_unmeasured("netguard is active in this process (a test run): "
                                 "no ssh to the VM; pass a fake `run`", alias)
    run = run or subprocess.run
    config = ssh_config if ssh_config is not None else Path.home() / ".ssh" / "config"
    try:
        if not _exists(config):
            return vm_unmeasured(f"no {config}, so no `Host {alias}` alias to reach the VM by")
        if not ssh_alias_present(alias, config):
            return vm_unmeasured(f"{config} has no `Host {alias}`")
    except OSError as e:
        return vm_unmeasured(f"reading {config}: {type(e).__name__}: {e}")

    cmd = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT_S}",
           alias, "sh -s"]
    r, why = _call(run, cmd, timeout, input=REMOTE_SCRIPT)
    if why:
        return vm_unmeasured(why, alias)
    if r.returncode == 255:
        return vm_unmeasured(f"ssh {alias} failed (exit 255): {scrub(r.stderr)}")
    got = {}
    for line in r.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and re.fullmatch(r"-?\d+", parts[1]):
            got[parts[0]] = (int(parts[1]), parts[2].strip())
    if "END" not in got:
        return vm_unmeasured(f"ssh {alias} exited {r.returncode} and its reply was cut short "
                             f"(no END line; {len(got)} reading(s)): {scrub(r.stderr)}")
    return _vm_from_readings(got, alias)


def _vm_from_readings(got: dict, alias: str) -> dict:
    out = {"machine": "vm", "scheduler": "systemd", "alias": alias,
           "reproducer": f"ssh -o BatchMode=yes -o ConnectTimeout={SSH_CONNECT_TIMEOUT_S} "
                         f"{alias} 'sh -s' < ops.prod_state.REMOTE_SCRIPT",
           "clone": str(_VM_LAYOUT.prod_dir), "state_dir": str(_VM_LAYOUT.state_dir)}

    def reading(key: str):
        return got.get(key, (None, None))

    rc, v = reading("tag")
    out["tag"] = (_val(v) if rc == 0 and v else
                  _unm(f"`sudo -u {iv.SERVICE_USER} git -C {_VM_LAYOUT.prod_dir} describe --tags`"
                       f" exited {rc}: {scrub(v or '')}"))

    rc, v = reading("load_state")
    if rc != 0 or not v:
        installed = _unm(f"`systemctl show -p LoadState {_VM_SESSION.service}` exited {rc}: {scrub(v or '')}")
    else:
        installed = _val(v == "loaded", load_state=v)
    out["session_unit"] = installed

    rc, v = reading("dry_run")
    if rc != 0:
        dry = _unm(f"`systemctl show -p Environment {_VM_SESSION.service}` exited {rc}: {scrub(v or '')}")
    else:
        vals = [t.split("=", 1)[1] for t in (v or "").split() if t.startswith("DRY_RUN=")]
        dry = (_val(None) if not vals else _val(vals[0]) if len(vals) == 1 else
               _unm(f"systemd reports {len(vals)} DRY_RUN assignments: {vals}"))
    out["dry_run"] = dry

    # is-active / is-enabled print one word per unit, in argument order, and
    # exit non-zero when any unit is not active/enabled; the words are the data.
    for key, verb in (("timers", "is-active"), ("timers_enabled", "is-enabled")):
        rc, v = reading(key)
        words = (v or "").split()
        out[key] = (_val(dict(zip(VM_TIMERS, words)))
                    if rc is not None and len(words) == len(VM_TIMERS) else
                    _unm(f"`systemctl {verb} {' '.join(VM_TIMERS)}` exited {rc}: {scrub(v or '')}"))

    rc, v = reading("auto_armed")
    out["auto_armed"] = ({"present": _val(True), "absent": _val(False),
                          "no-state-dir": _val(False, note=f"no {_VM_LAYOUT.state_dir}")}.get(v)
                         if rc == 0 and v in ("present", "absent", "no-state-dir") else
                         _unm(f"`sudo -n test -e {_VM_LAYOUT.state_dir}/AUTO_ARMED` exited {rc}: {scrub(v or '')}"))

    rc, v = reading("verify")
    out["verify_last"] = (_absent("no verify.log yet") if rc == 0 and v == "NO-FILE" else
                          _val(verdict_line(v)) if rc == 0 and v else
                          _absent("verify.log is empty") if rc == 0 else
                          _unm(f"`sudo -n tail -n1 {_VM_LAYOUT.state_dir}/verify.log` exited {rc}: {scrub(v or '')}"))

    rh, hv = reading("equity_header")
    rl, lv = reading("equity_last")
    where = f"{alias}:{_VM_LAYOUT.state_dir}/equity.csv"
    if rh == 0 and hv == "NO-FILE":
        out["equity"] = _absent("no equity.csv yet")
    elif rh == 0 and rl == 0 and hv:
        out["equity"] = equity_row(hv, lv or "", where)
    else:
        out["equity"] = _unm(f"`sudo -n head/tail {_VM_LAYOUT.state_dir}/equity.csv` exited "
                             f"{rh}/{rl}: {scrub(hv or lv or '')}")

    out["cautions"] = []
    if UNMEASURED in installed:
        out["arming"], out["arming_why"] = UNMEASURED, show(installed)
    elif installed["value"] is not True:
        out["arming"], out["arming_why"] = (NOT_INSTALLED,
                                            f"{_VM_SESSION.service} LoadState={installed['load_state']}")
    else:
        out["scheduled"] = _systemd_scheduled(out["timers"], out["timers_enabled"])
        out["arming"], out["arming_why"], out["cautions"] = _arming(
            dry, out["auto_armed"], out["scheduled"])
    return out


# `systemctl is-enabled` words that mean the timer starts again at boot, and
# those that mean it does not (systemctl(1)). Any other word is a gap.
_ENABLED_WORDS = frozenset({"enabled", "enabled-runtime", "alias", "indirect",
                            "generated", "linked", "linked-runtime"})
_NOT_ENABLED_WORDS = frozenset({"disabled", "masked", "masked-runtime", "static"})


def _systemd_scheduled(active: dict, enabled: dict) -> dict:
    """Will systemd fire the session job? Its timer active: yes. Stopped but
    enabled: yes, at the next boot (RUNBOOK 8.5 step 2 only stops them).
    Inactive and not enabled: no."""
    t = _VM_SESSION.timer
    a = (active.get("value") or {}).get(t)
    if a == "active":
        return _val(True, why=f"{t} active")
    e = (enabled.get("value") or {}).get(t)
    if a is None or e is None:
        return _unm(f"{t} is-active {show(active) if a is None else a}; "
                    f"is-enabled {show(enabled) if e is None else e}")
    if e in _ENABLED_WORDS:
        return _val(True, why=f"{t} {a} but {e}: it starts again at boot")
    if e in _NOT_ENABLED_WORDS:
        return _val(False, why=f"{t} {a} and {e}")
    return _unm(f"{t} is-enabled printed {e!r}, a word this reader does not know")


# ---------------------------------------------------------------- verdict --
NAMES = {"laptop": "the laptop", "vm": "the VM"}
WORDS = {ARMED: "ARMED", PER_DAY: "armed for a per-day approval only", DRY: "DRY",
         OFF: "OFF", NOT_INSTALLED: "not installed", UNMEASURED: "UNMEASURED"}


def verdict(machines: dict) -> dict:
    """Which machine is prod, from the per-machine arming states.

    prod is the one machine whose scheduler fires the session job with
    DRY_RUN=0. Two is the doubled-book hazard and gets a WARNING; none means
    nothing is sent. Live equity is the prod machine's last equity.csv row, and
    only that: another machine's row is a different ledger of the same account
    (a shadow's, or the laptop's after cut-over), so it is shown under that
    machine, not here. Cautions (an OFF machine whose files would arm it if
    re-enabled) are collected from every machine and always shown.
    """
    hot = {n: m["arming"] for n, m in machines.items() if m.get("arming") in HOT}
    unknown = [n for n, m in machines.items() if m.get("arming") == UNMEASURED]
    out = {"hot": hot, "unmeasured": unknown, "prod": None, "warning": None,
           "equity": None,
           "cautions": [f"{n}: {c}" for n, m in machines.items() for c in m.get("cautions") or []]}
    if len(hot) >= 2:
        both = ", ".join(f"{n} {WORDS[a]}" for n, a in hot.items())
        out["warning"] = (f"WARNING: TWO ARMED SCHEDULERS ON ONE ALPACA ACCOUNT ({both}). "
                          f"Each passes gate 6 on its own state dir, so both send: the "
                          f"doubled-book hazard (CLAUDE.md order-path rule 2). Disarm one "
                          f"now (docs/RUNBOOK.md 8.5).")
        out["line"] = out["warning"]
        return out
    if len(hot) == 1:
        (name, state), = hot.items()
        out["prod"] = name
        out["equity"] = machines[name].get("equity")
        line = (f"prod is {NAMES.get(name, name)}: {WORDS[state]} "
                f"({machines[name].get('arming_why')})")
        if unknown:
            line += (f"; {', '.join(unknown)} UNMEASURED, so a second armed scheduler "
                     f"is not ruled out")
        out["line"] = line
        return out
    states = ", ".join(f"{n} {WORDS.get(m.get('arming'), m.get('arming'))}"
                       for n, m in machines.items())
    out["line"] = (f"no machine is measured armed ({states}): nothing is sent"
                   + (f" -- but {', '.join(unknown)} is UNMEASURED, so that is not established"
                      if unknown else ""))
    return out


def measure(include_vm: bool = True, vm_timeout: float = VM_TIMEOUT_S,
            run: Run | None = None, home: Path | None = None,
            ssh_config: Path | None = None, vm_skip_reason: str | None = None) -> dict:
    machines = {"laptop": laptop(home=home, run=run)}
    machines["vm"] = (vm(timeout=vm_timeout, run=run, ssh_config=ssh_config) if include_vm
                      else vm_unmeasured(vm_skip_reason or "not measured in this call "
                                         "(run python3 -m ops.orient)"))
    return {"reproducer": "python3 -m ops.prod_state",
            "measured_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "machines": machines, "verdict": verdict(machines)}


# ----------------------------------------------------------------- render --
def equity_text(r: dict | None) -> str:
    """`$101,181.06 at the 2026-10-07 close (broker-confirmed; <source>, read ...)`."""
    if not isinstance(r, dict) or "value" not in r:
        return show(r)
    e = r["value"]
    try:
        amount = f"${float(e['equity']):,.2f}"
    except (TypeError, ValueError):
        amount = f"{e['equity']!r} (not a number)"
    age = trading_days_since(e.get("date"))
    return (f"{amount} at the {e['date']} close — broker-confirmed (Alpaca account, "
            f"{e['source']}" + (f", read {e['read_at_utc']}" if e.get("read_at_utc") else "")
            + ")" + (f", {age} trading day(s) ago" if age is not None else ""))


def verify_text(r: dict | None) -> str:
    if not isinstance(r, dict) or "value" not in r:
        return show(r)
    v = r["value"]
    age = trading_days_since(v.get("date"))
    return (v["line"][:150] + ("…" if len(v["line"]) > 150 else "")
            + (f"   ({age} trading day(s) ago)" if age is not None else ""))


def render_lines(d: dict, p: Callable[[str, str], None]) -> None:
    """Print the PROD block through `p(label, value)` (orient's `_p`)."""
    ms = d["machines"]
    lap, v = ms["laptop"], ms["vm"]

    p("laptop  (launchd)", f"{WORDS.get(lap['arming'], lap['arming'])} — {lap['arming_why']}")
    p("  clone", f"{lap['clone']} at {show(lap['tag'])}")
    jobs = lap.get("jobs") or {}
    p("  DRY_RUN in each plist", ", ".join(f"{s} {_dry_text(j.get('dry_run'))}"
                                           for s, j in jobs.items()))
    p("  launchd", ", ".join(_job_state(s, j) for s, j in jobs.items()))
    p("  AUTO_ARMED", _bool_text(lap.get("auto_armed"), f"{lap['state_dir']}/AUTO_ARMED"))
    if lap.get("state_dir_mismatch"):
        p("  WARNING", lap["state_dir_mismatch"])
    p("  last verdict", verify_text(lap.get("verify_last")))
    p("  equity.csv last row", equity_text(lap.get("equity")))

    p(f"VM  (systemd, ssh {v.get('alias')})",
      f"{WORDS.get(v['arming'], v['arming'])} — {v['arming_why']}")
    if UNMEASURED not in v:
        p("  clone", f"{v['clone']} at {show(v['tag'])}")
        p("  DRY_RUN (systemd, loaded)", _dry_text(v.get("dry_run")))
        ta, te = v.get("timers") or {}, v.get("timers_enabled") or {}
        if "value" in ta and "value" in te:
            p("  timers (active/enabled)", ", ".join(f"{_stem(k)} {a}/{te['value'].get(k)}"
                                                     for k, a in ta["value"].items()))
        else:
            p("  timers", f"is-active {show(ta)}; is-enabled {show(te)}")
        p("  AUTO_ARMED", _bool_text(v.get("auto_armed"), f"{v['state_dir']}/AUTO_ARMED"))
        p("  last verdict", verify_text(v.get("verify_last")))
        p("  equity.csv last row", equity_text(v.get("equity")))
    vd = d["verdict"]
    for c in vd.get("cautions") or []:
        p("  caution", c)
    p("!!" if vd.get("warning") else "=>", vd["line"])


def _stem(unit: str) -> str:
    """quantt-cef-session.timer -> session."""
    return unit.rsplit(".", 1)[0].rsplit("-", 1)[-1]


def _dry_text(r: dict | None) -> str:
    if not isinstance(r, dict) or "value" not in r:
        return show(r)
    return "unset" if r["value"] is None else str(r["value"])


def _bool_text(r: dict | None, path: str) -> str:
    if not isinstance(r, dict) or "value" not in r:
        return show(r)
    return ("present" if r["value"] else "absent") + f"  ({path})" + (
        f" — {r['note']}" if r.get("note") else "")


def _job_state(stem: str, j: dict) -> str:
    if "absent" in (j.get("dry_run") or {}):
        return f"{stem} not installed"
    lo, di = j.get("loaded") or {}, j.get("disabled") or {}
    s = stem + " " + ("UNMEASURED" if "value" not in lo else
                      ("loaded" + (f" (last exit {lo['last_exit']})" if lo.get("last_exit") is not None else ""))
                      if lo["value"] else "NOT loaded")
    if "value" not in di:
        s += ", disabled UNMEASURED"
    elif di["value"]:
        s += ", DISABLED"
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-vm", action="store_true", help="skip the ssh call")
    a = ap.parse_args(argv)
    d = measure(include_vm=not a.no_vm)
    if a.json:
        json.dump(d, sys.stdout, indent=2, default=str)
        print()
        return 0

    def p(label, value=""):
        print(f"  {label:<30}{value}" if len(label) <= 30 else f"  {label}\n  {'':<30}{value}")
    print(f"PROD — measured {d['measured_at']}")
    render_lines(d, p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
