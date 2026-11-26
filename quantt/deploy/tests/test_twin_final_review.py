"""The twin's final review (2026-11-25): run-time limits, the X display, the probe's filter record,
one mode at a time. The scripts are read as text and their Python helper is run on fakes."""
from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
INSTALL = REPO / "quantt/deploy/install_twin_vm.sh"
RUN = REPO / "quantt/deploy/vm/ibgw_run.sh"
WRAP = REPO / "quantt/deploy/vm/run_twin.sh"
BOOT = REPO / "quantt/deploy/vm/bootstrap_ibgw.sh"
CHECK = REPO / "quantt/deploy/vm/ibgw_check_firewall.sh"
DISPLAY = REPO / "quantt/deploy/vm/ibgw_check_display.py"


def code_lines(p: Path) -> str:
    return "\n".join(ln for ln in p.read_text().splitlines() if not ln.lstrip().startswith("#"))


def display_module():
    spec = importlib.util.spec_from_file_location("ibgw_check_display", DISPLAY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_every_twin_job_is_time_bounded_and_the_send_is_killed_just_after_its_own_deadline():
    t = INSTALL.read_text()
    send = int(re.search(r"^SEND_TIMEOUT_S=(\d+)$", t, re.M).group(1))
    read = int(re.search(r"^READ_TIMEOUT_S=(\d+)$", t, re.M).group(1))
    from quantt.twin import config
    assert send == config.SEND_RUN_LIMIT_S
    lead = config.SEND_SLOT_MIN[0] * 60                    # the first slot, in seconds before the close
    place_by = config.STOP_BATCH_MIN * 60 + config.SEND_PLACE_MARGIN_S
    assert lead - place_by < send < lead - config.CANCEL_REFUSE_MIN * 60     # after place_by, before the freeze
    assert "merged into the running" in t                                    # why the backup never doubles
    assert read <= 600
    body = t[t.index("job_service() {"):t.index("timer() {")]
    assert "TimeoutStartSec=${limit}" in body
    assert "written exclusively" in t                             # why a killed send never sends twice
    assert "TimeoutStartSec=6000" in t                            # the feed: its own, by design
    from quantt.broker import ibkr
    assert 0 < ibkr.REQUEST_TIMEOUT_S < config.TWIN_LOCK_WAIT_S
    assert 'timeout -k 30 "${LIMIT}"' in code_lines(WRAP)


def test_the_display_needs_a_cookie_and_has_no_abstract_socket():
    c = code_lines(RUN)
    xvfb = next(ln for ln in c.splitlines() if ln.startswith("Xvfb "))
    assert "-auth" in xvfb and "-nolisten tcp" in xvfb and "-nolisten local" in xvfb
    assert "export XAUTHORITY=" in c and "xauth -q -f" in c and "source -" in c
    assert not re.search(r"xauth[^|\n]*add[^|\n]*COOKIE", c)       # never the cookie as an argument
    t = INSTALL.read_text()
    assert "-auth ${IBC_RUN}/Xauthority" in t                      # the on-demand VNC
    pos = t.index('as_quantt /usr/bin/python3 -I -B "${BIN}/ibgw_check_display.py" owner 47 "${IBC_RUN}/Xauthority"')
    neg = t.index('runuser -u "${SHADOW_USER}" -- /usr/bin/python3 -I -B "${BIN}/ibgw_check_display.py" refused 47 '
                  '"${IBC_RUN}/Xauthority"')
    assert pos < neg                                              # the display is shown up FIRST
    assert "xauth" in code_lines(BOOT)


def xauthority(path, display="47", cookie=b"\x11" * 16):
    import struct

    def f(b):
        return struct.pack(">H", len(b)) + b
    path.write_bytes(struct.pack(">H", 256) + f(b"vm") + f(display.encode()) + f(b"MIT-MAGIC-COOKIE-1") + f(cookie))
    return cookie


class FakeX:
    """Unix sockets by address: `listening` maps an address to the cookie its X server wants (None: any
    setup is accepted); an address absent refuses the connection."""
    listening: dict = {}
    denied: set = set()

    def __init__(self, *a):
        self.address = None

    def settimeout(self, s):
        pass

    def connect(self, address):
        self.address = address
        if address in self.denied:
            raise PermissionError
        if address not in self.listening:
            raise ConnectionRefusedError

    def sendall(self, b):
        self.sent = b

    def recv(self, n):
        want = self.listening[self.address]
        return b"\x01" if want is None or want in self.sent else b"\x00"

    def close(self):
        pass


FILE = "/tmp/.X11-unix/X47"


@pytest.fixture
def display(monkeypatch, tmp_path):
    D = display_module()
    monkeypatch.setattr(D.socket, "socket", FakeX)
    sockets = {FILE}
    monkeypatch.setattr(D, "is_socket", lambda p: p in sockets)
    xa = tmp_path / "Xauthority"
    cookie = xauthority(xa)
    FakeX.denied = set()
    return D, xa, cookie, sockets


def test_the_owner_check_needs_the_display_up_and_its_cookie_to_work(display):
    D, xa, cookie, sockets = display
    assert D.setup_refused(b"\x00") and D.setup_refused(b"\x02") and not D.setup_refused(b"\x01")
    assert D.read_cookie(str(xa), "47") == cookie
    FakeX.listening = {FILE: cookie}
    assert D.main(["owner", "47", str(xa)]) == 0
    FakeX.listening = {FILE: b"another cookie"}                       # the server wants a different one
    assert D.main(["owner", "47", str(xa)]) == 1
    sockets.clear()                                                    # Xvfb is not up: no socket
    assert D.main(["owner", "47", str(xa)]) == 1


def test_the_refused_check_passes_only_a_display_that_answers_and_refuses(display):
    D, xa, cookie, sockets = display
    xa.chmod(0)                                                        # the shadow user cannot read it
    try:
        FakeX.listening = {FILE: cookie}                               # up, wants the cookie
        assert D.main(["refused", "47", str(xa)]) == 0
        FakeX.listening = {}                                           # the socket file, nobody answering
        assert D.main(["refused", "47", str(xa)]) == 1                 # nothing proved
        sockets.clear()                                                # no socket file (whatever answers)
        FakeX.listening = {FILE: cookie}
        assert D.main(["refused", "47", str(xa)]) == 1                 # no socket: nothing proved
        sockets.add(FILE)
        FakeX.listening = {FILE: None}                                 # no cookie needed
        assert D.main(["refused", "47", str(xa)]) == 1
        FakeX.listening = {FILE: cookie, "\0" + FILE: cookie}          # the abstract socket listens
        assert D.main(["refused", "47", str(xa)]) == 1
        FakeX.listening, FakeX.denied = {}, {FILE}                     # the socket's permissions refuse
        assert D.main(["refused", "47", str(xa)]) == 0
    finally:
        xa.chmod(0o600)
    FakeX.listening, FakeX.denied = {FILE: cookie}, set()
    assert D.main(["refused", "47", str(xa)]) == 1                     # the cookie file is readable


def test_the_probe_unit_records_the_filter():
    t = INSTALL.read_text()
    line = next(x for x in t.splitlines() if x.lstrip().startswith('fw_check="ExecStartPre=-+'))
    assert line.rstrip().endswith('--status"') and "STATE" not in line
    chk = CHECK.read_text()
    assert "--status) " in chk and "record true" in chk and "record false" in chk
    assert 'STATUS_DIR="/run/quantt-ibgw-status"' in chk and 'mktemp "${STATUS_DIR}/' in chk
    assert "chown" not in code_lines(CHECK)


def test_the_probe_reads_the_filter_record_and_never_assumes_it(tmp_path):
    import datetime as dt
    import json
    from quantt.twin import run
    now = dt.datetime(2026, 11, 27, 17, 0, tzinfo=dt.timezone.utc)
    f = tmp_path / "firewall.json"
    assert run.firewall_record(f, now)["in_force"] is None
    f.write_text(json.dumps({"in_force": True, "detail": "ok", "checked_utc": "2026-11-27T16:59:00Z"}))
    assert run.firewall_record(f, now)["in_force"] is True
    assert run.firewall_record(f, now + dt.timedelta(hours=1))["in_force"] is None     # stale
    f.write_text("{broken")
    assert run.firewall_record(f, now)["in_force"] is None
    from quantt.twin import config
    assert str(config.FIREWALL_STATUS).startswith("/run/quantt-ibgw-status/")


def test_hand_runs_refuse_the_mode_the_units_are_not_in():
    c = code_lines(WRAP)
    assert "/etc/systemd/system/quantt-twin-send.service" in c and "would hold a different Gateway lock" in c


# -- final check 1: root never writes into a directory quantt owns -------------------------------------

QUANTT_PATHS = re.compile(r"\$\{(STATE|STATE_ROOT|RUN_HOME|JTS|GW_DIR|marker|vm|lockf|parent)\}|/home/quantt|"
                          r"\$\{FEED\}/requests")
ROOT_WRITE = re.compile(r"(^|[\s;|&(])(>>?|chown|chmod|chgrp|cp|mv|ln|tee|touch|mkdir|rm|install|sed -i)(\s|$)"
                        r"|[^0-9&<]>>?\s*\"|[^0-9&<]>>?\s*\$")


def root_lines(path: Path):
    """The lines a root script runs as root: comments, heredoc bodies (unit files and messages) and lines
    that hand the work to quantt (as_quantt, runuser) dropped."""
    out, in_doc, end = [], False, None
    for n, ln in enumerate(path.read_text().splitlines(), 1):
        s = ln.strip()
        if in_doc:
            if s == end:
                in_doc = False
            continue
        m = re.search(r"<<-?\s*'?([A-Z_]+)'?", ln)
        if m:
            in_doc, end = True, m.group(1)
        s = re.split(r"\bas_quantt\b|\bas_reader\b|\brunuser -u\b", s)[0].strip()   # the part root runs
        if not s or s.startswith("#"):
            continue
        out.append((n, s))
    return out


@pytest.mark.parametrize("script", [INSTALL, BOOT, CHECK, WRAP])
def test_no_root_step_writes_chowns_or_moves_in_a_directory_quantt_owns(script):
    bad = [(n, s) for n, s in root_lines(script) if QUANTT_PATHS.search(s) and ROOT_WRITE.search(s)
           and "own_dir.py" not in s]
    assert bad == [], bad


def test_the_rendered_units_open_and_write_nothing_as_root_in_the_twins_state(tmp_path):
    """systemd opens StandardOutput=append: files and runs ExecStartPre=+ lines as root: neither may name
    the twin's state or quantt's home, in any unit the installer renders."""
    t = INSTALL.read_text()
    logs = re.findall(r'LOGS="(/var/log/[^"]+)"', t)
    assert logs == ["/var/log/quantt-twin-staging", "/var/log/quantt-twin"]
    assert 'LOGS="${STATE}' not in t
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    me = __import__("getpass").getuser()
    env = {"UNIT_DIR": str(unit_dir), "STAGING": "", "PY": "/home/quantt/venv/bin/python", "TAG": "release-x",
           "RUN_USER": me, "SHADOW_USER": me, "CODE": "/home/quantt/prod/quantt-twin", "PROD": "/home/quantt/prod/q",
           "STATE": "/home/quantt/quantt_state/twin", "BOOK_LINES": "", "BOOK_DIRS": "", "CORE_ENV_FILE": "/run/q/a.env",
           "DATA_BOOK": "cef", "GW_HOST": "127.0.0.1", "GW_PORT": "4002", "FEED": "/srv/quantt-ibkr-feed",
           "TWIN_RUN": "/run/quantt-twin", "LOGS": "/var/log/quantt-twin", "VENV_DIR": "/home/quantt/venv",
           "LOCK_NAME": ".gateway.lock", "BIN": "/opt/quantt-ibgw/bin", "VAULT": "v", "FEED_HIDDEN": "/run/quantt-twin"}
    from quantt.deploy.tests.test_install_twin_vm import _render
    for fn, args in (("job_service", 'probe 33 "# x" "probe"'), ("job_service", 'send 31 "SuccessExitStatus=3" "send"'),
                     ("feed_service", "close after-close 34"),
                     ("secret_service", "quantt-twin-secret.service quantt-twin ibkr.env --secret a=b")):
        _render(tmp_path, fn, args, {**env, "SEND_TIMEOUT_S": "1080", "READ_TIMEOUT_S": "600"})
    units = {p.name: p.read_text() for p in unit_dir.iterdir()}
    assert {"quantt-twin-probe.service", "quantt-twin-send.service", "quantt-twin-feed-close.service",
            "quantt-twin-secret.service"} <= set(units)
    for name, u in units.items():
        for ln in u.splitlines():
            if ln.startswith(("StandardOutput=", "StandardError=", "ExecStartPre=+", "ExecStartPre=-+")):
                assert "/home/quantt" not in ln and "quantt_state" not in ln, (name, ln)
    probe = units["quantt-twin-probe.service"]
    assert any(x.startswith("ExecStartPre=-+") and x.endswith("--status") for x in probe.splitlines())


def test_own_dir_refuses_a_planted_symlink_and_owns_a_real_directory(tmp_path):
    spec = importlib.util.spec_from_file_location("own_dir", REPO / "quantt/deploy/vm/own_dir.py")
    O = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(O)
    target = tmp_path / "etc"
    target.mkdir()
    target.chmod(0o755)
    planted = tmp_path / "requests"
    planted.symlink_to(target)
    with pytest.raises(OSError):
        O.own_dir(str(planted), os.getuid(), os.getgid(), 0o2750)
    assert oct(target.stat().st_mode & 0o7777) == "0o755"             # the link's target is untouched
    real = tmp_path / "real"
    O.own_dir(str(real), os.getuid(), os.getgid(), 0o750)
    assert real.is_dir() and oct(real.stat().st_mode & 0o777) == "0o750"
