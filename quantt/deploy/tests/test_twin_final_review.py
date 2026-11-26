"""The twin's final review (2026-11-25): run-time limits, the X display, the probe's filter record,
one mode at a time. The scripts are read as text and their Python helper is run on fakes."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

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


def test_every_twin_job_is_time_bounded_and_the_send_dies_before_its_backup():
    t = INSTALL.read_text()
    send = int(re.search(r"^SEND_TIMEOUT_S=(\d+)$", t, re.M).group(1))
    read = int(re.search(r"^READ_TIMEOUT_S=(\d+)$", t, re.M).group(1))
    from quantt.twin import config
    gap = (config.SEND_SLOT_MIN[0] - config.SEND_SLOT_MIN[1]) * 60
    assert send < gap, "a hung send must be killed before the backup slot"
    assert read <= 600
    body = t[t.index("job_service() {"):t.index("timer() {")]
    assert "TimeoutStartSec=${limit}" in body
    assert "STARTED is written, exclusively" in t                 # why a killed send never sends twice
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
    assert 'runuser -u "${SHADOW_USER}" -- /usr/bin/python3 -I -B "${BIN}/ibgw_check_display.py" 47' in t
    assert "xauth" in code_lines(BOOT)


def test_the_display_check_refuses_an_open_display_and_passes_a_closed_one(monkeypatch):
    D = display_module()
    assert D.setup_refused(b"\x00") and D.setup_refused(b"\x02") and not D.setup_refused(b"\x01")

    class Sock:
        replies: dict = {}

        def __init__(self, *a):
            self.address = None

        def settimeout(self, s):
            pass

        def connect(self, address):
            self.address = address
            if address not in self.replies:
                raise ConnectionRefusedError

        def sendall(self, b):
            assert b == D.SETUP

        def recv(self, n):
            return self.replies[self.address]

        def close(self):
            pass
    monkeypatch.setattr(D.socket, "socket", Sock)
    Sock.replies = {"/tmp/.X11-unix/X47": b"\x00"}                 # file socket open, setup refused
    assert D.main(["47"]) == 0
    Sock.replies = {"\0/tmp/.X11-unix/X47": b"\x01"}               # the abstract socket open
    assert D.main(["47"]) == 1
    Sock.replies = {"/tmp/.X11-unix/X47": b"\x01"}                 # no cookie needed
    assert D.main(["47"]) == 1


def test_the_probe_unit_records_the_filter():
    t = INSTALL.read_text()
    assert 'fw_check="ExecStartPre=-+/bin/sh ${BIN}/ibgw_check_firewall.sh' in t
    assert "--status ${STATE}/firewall.json" in t
    chk = CHECK.read_text()
    assert "--status) " in chk and "record true" in chk and "record false" in chk


def test_the_probe_reads_the_filter_record_and_never_assumes_it(tmp_path):
    import datetime as dt
    import json
    from quantt.twin import run
    now = dt.datetime(2026, 11, 27, 17, 0, tzinfo=dt.timezone.utc)
    assert run.firewall_record(tmp_path, now)["in_force"] is None
    (tmp_path / "firewall.json").write_text(json.dumps({"in_force": True, "detail": "ok",
                                                        "checked_utc": "2026-11-27T16:59:00Z"}))
    assert run.firewall_record(tmp_path, now)["in_force"] is True
    assert run.firewall_record(tmp_path, now + dt.timedelta(hours=1))["in_force"] is None     # stale
    (tmp_path / "firewall.json").write_text("{broken")
    assert run.firewall_record(tmp_path, now)["in_force"] is None


def test_hand_runs_refuse_the_mode_the_units_are_not_in():
    c = code_lines(WRAP)
    assert "/etc/systemd/system/quantt-twin-send.service" in c and "would hold a different Gateway lock" in c
