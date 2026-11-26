"""The twin's VM scripts, read as text and syntax-checked: never run here (they need root and a VM).

What is pinned: the download pins, DRY_RUN=1 in every twin job unit, staging's forced environment,
the timers (the 12:30/12:40 early-close slots among them), the Gateway's memory limits, VNC on
loopback only and on demand, credentials never on a command line, and the generated IBC config's
keys and tmpfs-only write (quantt/deploy/ibc_config.py)."""
from __future__ import annotations

import io
import os
import re
import stat
import subprocess
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

from quantt.deploy import ibc_config as C

REPO = Path(__file__).resolve().parents[3]
INSTALL = REPO / "quantt/deploy/install_twin_vm.sh"
RUN = REPO / "quantt/deploy/vm/ibgw_run.sh"
WRAP = REPO / "quantt/deploy/vm/run_twin.sh"
BOOT = REPO / "quantt/deploy/vm/bootstrap_ibgw.sh"
STUB_PASSWORD = "Stub-Paper-Pw-7c1e"          # a test value; never a real one
STUB_USER = "stubpaperuser"


def code_lines(p: Path) -> str:
    return "\n".join(ln for ln in p.read_text().splitlines() if not ln.lstrip().startswith("#"))


@pytest.mark.parametrize("p", [INSTALL, RUN, WRAP, BOOT], ids=lambda p: p.name)
def test_the_scripts_parse(p):
    r = subprocess.run(["sh", "-n", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_pins_are_the_coordinators_reads_of_2026_11_25():
    t = INSTALL.read_text()
    assert 'GW_SHA256="1352b9f119c194409084a7081e629aba63a3eabb177777ec372a0f2d3bac6537"' in t
    assert 'GW_VERSION="10.50.1h"' in t and 'GW_MAJOR="1050"' in t
    assert 'IBC_SHA256="cc097ca1dfa75413a5fbe02e4743050af15f3308eb6a97c769b3cff9850c80c5"' in t
    assert 'IBC_VERSION="3.24.2"' in t
    assert "is not the pinned" in t and "Nothing was installed" in t     # a mismatch refuses, naming both


def test_every_twin_job_unit_is_dry_and_staging_is_forced():
    t = INSTALL.read_text()
    body = t[t.index("job_service() {"):t.index("timer() {")]
    assert "Environment=DRY_RUN=1" in body
    assert 'run="/usr/bin/env DRY_RUN=1 QUANTT_TWIN_STAGING=1 ${PY} -B -m quantt.twin $4"' in body
    assert "Environment=QUANTT_TWIN_STAGING=1" in body
    assert "does not carry exactly one Environment=DRY_RUN=1" in t
    assert "STAGING state directory" in t                    # an AUTO_ARMED in staging refuses
    assert not re.search(r"(touch|>)\s*\S*AUTO_ARMED", code_lines(INSTALL))   # it never arms


def test_the_timers_carry_the_slots_of_both_closes_and_the_verify():
    t = INSTALL.read_text()
    for hm in ("12:30", "12:40", "15:30", "15:40"):
        assert f'"Mon..Fri *-*-* {hm}:00"' in t
    for hm in ("17:45", "18:30", "20:30", "23:00"):                   # review finding 1: retry slots
        assert f'"Mon..Fri *-*-* {hm}:00"' in t
    from quantt.twin import verify
    assert verify.LAST_SLOT.strftime("%H:%M") == "23:00"
    from quantt.twin import config
    assert config.SEND_SLOT_MIN == (30, 20)                  # 16:00 - 30/20 and 13:00 - 30/20


def test_the_gateway_is_bounded_in_memory_and_killed_first():
    t = INSTALL.read_text()
    assert re.search(r"^MemoryMax=\$\{MEM_MAX\}$", t, re.M) and re.search(r"^MemoryHigh=\$\{MEM_HIGH\}$", t, re.M)
    assert "OOMScoreAdjust=900" in t and "-Xmx${HEAP_MB}m" in t


def test_vnc_is_loopback_and_on_demand_only():
    t = INSTALL.read_text()
    vnc = t[t.index("unit_file quantt-ibgw-vnc.service"):t.index("set -- ${IDS}")]
    assert "-localhost" in vnc and "[Install]" not in vnc        # never enabled at boot
    assert "x11vnc" not in code_lines(RUN)
    assert "-nolisten tcp" in code_lines(RUN)


def test_no_credential_is_ever_a_command_line_argument():
    for p in (RUN, INSTALL, WRAP):
        c = code_lines(p)
        assert "--pw=" not in c and "--user=" not in c, p.name
    assert "IbPassword" not in code_lines(INSTALL)


def test_the_secret_names_are_the_vaults():
    t = INSTALL.read_text()
    assert "--secret ibkr-paper-username=IBKR_PAPER_USERNAME --secret ibkr-paper-password=IBKR_PAPER_PASSWORD" in t
    assert "--secret ibkr-paper-account-id=QUANTT_IBKR_ACCOUNT" in t
    assert (C.SECRET_USERNAME, C.SECRET_PASSWORD, C.SECRET_ACCOUNT) == \
        ("ibkr-paper-username", "ibkr-paper-password", "ibkr-paper-account-id")
    from quantt.broker import ibkr
    assert C.ENV_ACCOUNT == ibkr.ENV_ACCOUNT


def test_the_wrapper_refuses_a_bare_send_and_a_confirmed_cancel():
    c = code_lines(WRAP)
    assert "a hand-run send is not offered" in c and "cancel-open --confirm is the team lead" in c
    assert "DRY_RUN=1" in c


# -- the IBC config generator -------------------------------------------------------------

def login_file(d: Path) -> Path:
    p = d / "login.env"
    p.write_text(f"{C.ENV_USERNAME}={STUB_USER}\n{C.ENV_PASSWORD}={STUB_PASSWORD}\n")
    os.chmod(p, 0o600)
    return p


def private_dir(d: Path) -> Path:
    d.mkdir(mode=0o700)
    os.chmod(d, 0o700)
    return d


def test_the_config_is_paper_with_an_explicit_port_and_no_command_server():
    text = C.render({C.ENV_USERNAME: STUB_USER, C.ENV_PASSWORD: STUB_PASSWORD}, api_port=4002,
                    order_precautions="bypass")
    kv = dict(ln.split("=", 1) for ln in text.splitlines() if "=" in ln and not ln.startswith("#"))
    assert kv["TradingMode"] == "paper" and kv["OverrideTwsApiPort"] == "4002" and kv["CommandServerPort"] == "0"
    assert kv["AcceptIncomingConnectionAction"] == "reject" and kv["ExistingSessionDetectedAction"] == "primary"
    assert kv["AutoRestartTime"] == "03:00 AM" and kv["BypassOrderPrecautions"] == "yes"
    assert set(kv) == set(C.KEYS)


def test_the_keys_written_exist_in_ibc_3_24_2_as_the_coordinator_read_them():
    read = {"IbLoginId", "IbPassword", "TradingMode", "ExistingSessionDetectedAction", "AcceptIncomingConnectionAction",
            "OverrideTwsApiPort", "ReadOnlyApi", "BypassOrderPrecautions", "TrustedTwsApiClientIPs", "AutoRestartTime",
            "ColdRestartTime", "CommandServerPort", "BindAddress", "ReloginAfterSecondFactorAuthenticationTimeout",
            "SecondFactorAuthenticationExitInterval", "AllowBlindTrading",
            # read in the pinned config.ini's text by this build (not run): sections 2, 3 and 6
            "FIX", "AcceptNonBrokerageAccountWarning", "ReadOnlyLogin", "StoreSettingsOnServer", "MinimizeMainWindow"}
    assert set(C.KEYS) <= read


def test_the_config_lands_only_under_the_tmpfs_root_and_is_0600(tmp_path):
    run_root = private_dir(tmp_path / "run")
    out_dir = private_dir(run_root / "quantt-ibgw-ibc")
    text = C.render(C.read_login(login_file(tmp_path)), api_port=4002, order_precautions="keep")
    C.write(out_dir / "config.ini", text, tmpfs_root=run_root)
    assert stat.S_IMODE((out_dir / "config.ini").stat().st_mode) == 0o600
    disk = private_dir(tmp_path / "disk")
    with pytest.raises(C.IBCConfigError, match="not under"):
        C.write(disk / "config.ini", text, tmpfs_root=run_root)
    loose = run_root / "loose"
    loose.mkdir()
    os.chmod(loose, 0o755)
    with pytest.raises(C.IBCConfigError, match="0700"):
        C.write(loose / "config.ini", text, tmpfs_root=run_root)
    assert not (disk / "config.ini").exists() and not (loose / "config.ini").exists()


def test_no_password_reaches_stdout_stderr_or_an_error(tmp_path, monkeypatch):
    run_root = private_dir(tmp_path / "run")
    out_dir = private_dir(run_root / "ibc")
    monkeypatch.setattr(C, "TMPFS_ROOT", run_root)
    lf = login_file(tmp_path)
    o, e = io.StringIO(), io.StringIO()
    with redirect_stdout(o), redirect_stderr(e):
        assert C.main(["--login-env", str(lf), "--out", str(out_dir / "config.ini"), "--api-port", "4002",
                       "--order-precautions", "keep"]) == 0
        assert C.main(["--login-env", str(lf), "--out", str(tmp_path / "config.ini"), "--api-port", "4002",
                       "--order-precautions", "keep"]) == 2
        bad = tmp_path / "bad.env"
        bad.write_text(f"{C.ENV_USERNAME}={STUB_USER}\n{C.ENV_PASSWORD}=has\\backslash{STUB_PASSWORD}\n")
        assert C.main(["--login-env", str(bad), "--out", str(out_dir / "c2.ini"), "--api-port", "4002",
                       "--order-precautions", "keep"]) == 2
    printed = o.getvalue() + e.getvalue()
    assert STUB_PASSWORD not in printed and STUB_USER not in printed
    assert "REFUSED" in printed and C.ENV_PASSWORD in printed       # names, not values


def test_the_staging_wrapper_carries_the_same_secrets_and_forces_dry():
    c = code_lines(WRAP)
    assert 'STAGE_ENV="QUANTT_TWIN_STAGING=1"' in c and "/run/quantt-twin/ibkr.env" in c and "DRY_RUN=1" in c


# -- review findings 6, 7 and (c) ----------------------------------------------------------------

def test_the_port_filter_lets_only_quantt_reach_the_api_and_the_admin_reach_vnc():
    from quantt.deploy import ibgw_firewall as fw
    text = fw.render(1001, 1000)
    assert "table inet quantt_ibgw" in text and "delete table inet quantt_ibgw" in text
    assert "type filter hook output priority 0; policy accept;" in text
    out = text[text.index("chain output"):text.index("chain gate")]
    assert "        tcp dport { 4002, 7497, 5947 } jump gate\n" in out
    assert "daddr" not in text          # re-review 4: no address condition, so no way round it
    gate = text[text.index("chain gate"):]
    assert gate.index("meta skuid 1001 accept") < gate.index("reject")
    assert "tcp dport 5947 meta skuid 1000 accept" in gate
    assert "tcp dport { 4002, 7497 } counter reject with tcp reset" in gate
    assert "meta skuid 1000 accept\n" not in gate.replace("tcp dport 5947 meta skuid 1000 accept\n", "")
    for bad in ((0, 1000), (1001, 1001), (True, 1000)):
        with pytest.raises(ValueError):
            fw.render(*bad)


def test_the_installer_refuses_without_the_port_filter_and_the_gateway_requires_it():
    t = INSTALL.read_text()
    assert "quantt-ibgw-firewall.service is not enabled" in t
    assert 'sh "${CODE}/quantt/deploy/vm/ibgw_check_firewall.sh" "$(id -u "${RUN_USER}")"' in t
    assert "Requires=quantt-ibgw-firewall.service" in t
    assert 'ExecStartPre=+/bin/sh ${BIN}/ibgw_check_firewall.sh $(id -u "${RUN_USER}")' in t   # N2
    chk = (REPO / "quantt/deploy/vm/ibgw_check_firewall.sh").read_text()
    assert "meta skuid ${UID_Q} accept" in chk and "reject with tcp reset" in chk
    for port in ("4002", "7497", "5947"):
        assert port in chk
    boot = code_lines(BOOT)
    assert boot.index("inside a twin window") < boot.index("systemctl restart quantt-ibgw-firewall.service")   # N2
    b = BOOT.read_text()
    assert "ibgw_firewall.py" in b and "nft -c -f" in b and "WantedBy=multi-user.target" in b


def test_memory_limits_are_installer_flags():
    t = INSTALL.read_text()
    for flag in ("--heap-mb", "--memory-high", "--memory-max"):
        assert f"{flag})" in t


def test_release_mode_runs_from_its_own_clone_and_venv():
    t = INSTALL.read_text()
    assert '--tree <the twin\'s code tree> is required' in t and "--python <that tree's venv python> is required" in t
    assert "is the clone the Alpaca books run from" in t
    rel = t[t.index("check_code_release() {"):t.index("# ---------------------------------------------------------------- downloads")]
    assert '"${PROD}"' not in rel and "iv.clone_origin" in rel and "iv.remote_tag_commit" in rel
    assert "--order-precautions bypass" in t


def test_the_firewall_check_script_parses():
    r = subprocess.run(["sh", "-n", str(REPO / "quantt/deploy/vm/ibgw_check_firewall.sh")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_units_name_the_books_clone():
    t = INSTALL.read_text()
    assert "Environment=QUANTT_BOOKS_CLONE=${PROD}" in t and "ReadOnlyPaths=${CODE} ${PROD}" in t
    assert 'QUANTT_BOOKS_CLONE="${RUN_HOME}/prod/quantt-alpaca"' in WRAP.read_text()
    assert '"Mon..Fri *-*-* 07:00:00"' in t                   # the catch-up slot
