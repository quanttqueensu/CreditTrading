"""The IBKR twin's read-only readers: ops.prod_state.twin_vm (orient's IBKR TWIN) and the daily page.

"No phone" (team lead, 2026-11-25): these and nothing else show a logged-out Gateway. Fake ssh only."""
from __future__ import annotations

import json
import subprocess

from ops import daily_page as dp
from ops import orient
from ops import prod_state as ps

STATUS = {"version": 1, "gateway": {"logged_in": False, "why": "NotConnected: refused", "at": "2026-11-27T14:00:00+00:00"},
          "last_send": {"session_date": "2026-11-27", "exit": "REFUSED", "orders": 0, "refusals": ["gateway"]},
          "tally": {"cef": {"sessions": 1, "both_traded": 0, "twin_full": 0, "twin_orders": 0, "alpaca_full": 5,
                            "alpaca_orders": 5, "twin_bp": None, "alpaca_bp": 9.1, "reconciled": 0, "double_sends": 0,
                            "refused_shorts": 0}}}


class FakeRun:
    def __init__(self, stdout, rc=0):
        self.stdout, self.rc, self.calls = stdout, rc, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, self.rc, self.stdout, "")


def reply(status_text):
    return (f"twin.units\t0\tquantt-ibgw.service=active quantt-twin-send.timer=active \n"
            f"twin.status\t0\t{status_text}\ntwin.END\t0\tquantt-prod-state\n")


def ssh_config(tmp_path):
    p = tmp_path / "config"
    p.write_text(f"Host {ps.VM_ALIAS}\n  HostName example.invalid\n")
    return p


def test_twin_vm_reads_the_gateway_state_and_the_tally(tmp_path):
    run = FakeRun(reply(json.dumps(STATUS, indent=1).replace("\n", " ")))
    tw = ps.twin_vm(ssh_config=ssh_config(tmp_path), run=run)
    assert run.calls[0][1]["input"] == ps.TWIN_SCRIPT
    text = "\n".join(f"{a} {b}" for a, b in ps.twin_lines(tw))
    assert "LOGGED OUT" in text and "side-by-side cef" in text


def test_the_twin_script_only_reads():
    body = ps.TWIN_SCRIPT
    for w in (" rm ", " mv ", "tee", "curl", "python", "/run/", "alpaca.env", "ibkr.env", "login.env"):
        assert w not in body, w
    assert "systemctl is-active" in body and "cat" in body
    assert "systemctl stop" not in body and "systemctl start" not in body


def test_twin_vm_refuses_under_netguard():
    assert ps.UNMEASURED in ps.twin_vm()


def test_a_twin_that_never_ran_is_absent_not_logged_in(tmp_path):
    tw = ps.twin_vm(ssh_config=ssh_config(tmp_path), run=FakeRun(reply("NO-FILE")))
    assert "absent" in json.dumps(tw["status"]).lower() or ps.UNMEASURED not in tw


def test_orient_has_an_ibkr_twin_section():
    assert "IBKR TWIN" in [n for n, _ in orient.SECTIONS]


def test_the_daily_page_shows_a_logged_out_gateway():
    raw = (f"{dp.MISSING}eod_cef x\n{dp.MISSING}risk_cef x\n{dp.MISSING}eod_c4 x\n{dp.MISSING}risk_c4 x\n"
           f"{dp.MISSING}shadow x\n{dp.BEGIN}twin\n{json.dumps(STATUS)}\n{dp.END}twin\n{dp.DONE}\n")
    page = dp.build(raw)
    assert page["twin"]["logged_in"] is False
    md = dp.render(page)
    assert "LOGGED OUT" in md and "## IBKR twin" in md
    assert f"emit twin {dp.TWIN_STATUS}" in dp.REMOTE_SCRIPT
