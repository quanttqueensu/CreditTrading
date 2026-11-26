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
    assert '"Mon..Fri *-*-* 17:45:00"' in t
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



# -- B10: the feed's units, its directories, and THE GUARD ----------------------------------

def _shell_functions(names, text):
    """The named shell functions of the installer, as text a test can run with chosen variables."""
    out = []
    for n in names:
        start = text.index(f"\n{n}() {{") + 1
        end = text.index("\n}\n", start) + 3
        out.append(text[start:end])
    return "\n".join(out)


def _render(tmp_path, fn, args, env):
    t = INSTALL.read_text()
    script = tmp_path / "render.sh"
    script.write_text("set -eu\n" + 'die() { echo "REFUSED: $*" >&2; exit 2; }\n'
                      + _shell_functions(["unit_file", fn], t) + f"\n{fn} {args}\n")
    r = subprocess.run(["sh", str(script)], capture_output=True, text=True, env={**os.environ, **env})
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_the_feed_units_are_dry_listed_and_timed_after_the_close_and_in_the_evening():
    t = INSTALL.read_text()
    for u in ("quantt-twin-feed-close.service", "quantt-twin-feed-evening.service"):
        assert u in t[t.index("JOB_SERVICES="):t.index("ALL_UNITS=")]           # the DRY_RUN=1 check covers them
    assert "quantt-twin-feed-close.timer quantt-twin-feed-evening.timer" in t
    assert 'feed_service close after-close "$4"' in t and 'feed_service evening evening "$4"' in t
    assert 'IDS="31 32 33 34"' in t and 'IDS="41 42 43 44"' in t                  # its own client id
    assert 'FEED="/srv/quantt-ibkr-feed"' in t and 'FEED="/srv/quantt-ibkr-feed-staging"' in t


def test_the_feed_unit_is_sandboxed_like_the_c4_feed_and_sees_only_what_it_needs(tmp_path):
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    env = {"UNIT_DIR": str(unit_dir), "STAGING": "", "PY": "/home/quantt/venv/bin/python", "TAG": "release-x",
           "RUN_USER": "quantt", "CODE": "/home/quantt/prod/quantt-alpaca", "STATE": "/home/quantt/quantt_state/twin",
           "BOOK_LINES": "Environment=QUANTT_TWIN_CEF_STATE=/home/quantt/quantt_state/cef\n",
           "BOOK_DIRS": " /home/quantt/quantt_state/cef", "CORE_ENV_FILE": "/run/quantt/alpaca.env", "DATA_BOOK": "cef",
           "GW_HOST": "127.0.0.1", "GW_PORT": "4002", "FEED": "/srv/quantt-ibkr-feed", "TWIN_RUN": "/run/quantt-twin",
           "LOGS": "/home/quantt/quantt_state/twin/logs", "VENV_DIR": "/home/quantt/venv", "LOCK_NAME": ".gateway.lock",
           "FEED_HIDDEN": re.search(r'^FEED_HIDDEN_FIXED="([^"]+)"', INSTALL.read_text(), re.M).group(1)
           + " /run/quantt-events /run/quantt-site"}
    _render(tmp_path, "feed_service", "close after-close 34", env)
    u = (unit_dir / "quantt-twin-feed-close.service").read_text()
    lines = set(u.splitlines())
    for want in ("User=quantt", "Environment=DRY_RUN=1", "ProtectSystem=strict", "ProtectHome=tmpfs",
                 "NoNewPrivileges=yes", "PrivateTmp=yes", "PrivateDevices=yes", "ProtectProc=invisible",
                 "CapabilityBoundingSet=", "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
                 "ReadWritePaths=/srv/quantt-ibkr-feed", "ReadOnlyPaths=/srv/quantt-ibkr-feed/requests",
                 "BindPaths=/home/quantt/quantt_state/twin/.gateway.lock",
                 "BindReadOnlyPaths=/home/quantt/prod/quantt-alpaca /home/quantt/venv /home/quantt/quantt_state/cef",
                 "Environment=QUANTT_IBKR_CLIENT_ID=34", "Environment=QUANTT_IBKR_FEED_DIR=/srv/quantt-ibkr-feed",
                 "SuccessExitStatus=3 5",
                 "ExecStart=/home/quantt/venv/bin/python -B -m quantt.twin feed --slot after-close --require-sandbox"):
        assert want in lines, want
    hidden = next(x for x in lines if x.startswith("InaccessiblePaths="))
    for d in ("/run/quantt-ibgw", "/run/quantt-twin", "/run/quantt-ibgw-ibc", "/run/quantt-shadow", "/run/quantt-events"):
        assert f"-{d}" in hidden.split("=", 1)[1].split()
    assert "-/run/quantt" not in hidden.split("=", 1)[1].split()          # the core's market-data key stays
    assert "RestrictSUIDSGID" not in u                                    # its session directories are setgid
    assert "ReadWritePaths=/home" not in u and "STATE}" not in u


def test_staging_forces_dry_and_staging_on_the_feeds_command_line(tmp_path):
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    env = {k: "x" for k in ("TAG", "RUN_USER", "CODE", "STATE", "CORE_ENV_FILE", "DATA_BOOK", "GW_HOST", "GW_PORT",
                            "TWIN_RUN", "LOGS", "VENV_DIR", "LOCK_NAME")}
    env.update({"UNIT_DIR": str(unit_dir), "STAGING": "/home/quantt/twin-staging/tree", "PY": "/s/venv/bin/python",
                "BOOK_LINES": "", "BOOK_DIRS": "", "FEED": "/srv/quantt-ibkr-feed-staging", "FEED_HIDDEN": "/run/quantt-twin"})
    _render(tmp_path, "feed_service", "evening evening 44", env)
    u = (unit_dir / "quantt-twin-feed-evening.service").read_text()
    assert "ExecStart=/usr/bin/env DRY_RUN=1 QUANTT_TWIN_STAGING=1 /s/venv/bin/python -B -m quantt.twin feed " \
           "--slot evening --require-sandbox" in u
    assert "Environment=QUANTT_TWIN_STAGING=1" in u and "ReadWritePaths=/srv/quantt-ibkr-feed-staging" in u


def test_the_guard_admits_only_the_trading_user_to_the_api_ports_and_the_gateway_requires_it(tmp_path):
    t = INSTALL.read_text()
    me = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
    uid = str(os.getuid())
    out = _render(tmp_path, "render_guard", "", {"GUARD_NFT": "/opt/x/ibgw_guard.nft", "TAG": "t",
                                                 "GUARD_TABLE": "quantt_ibgw_guard", "API_PORTS": "4001, 4002, 7496, 7497",
                                                 "GW_HOST": "127.0.0.1", "RUN_USER": me, "SHADOW_USER": me,
                                                 "UNIT_DIR": str(tmp_path)})
    assert f"ip daddr 127.0.0.0/8 tcp dport {{ 4001, 4002, 7496, 7497 }} meta skuid != {uid} counter reject with tcp reset" in out
    assert f"ip6 daddr ::1 tcp dport {{ 4001, 4002, 7496, 7497 }} meta skuid != {uid} counter reject" in out
    assert f'oifname "lo" meta skuid {uid} tcp dport != 53 counter reject' in out
    assert out.index("table inet quantt_ibgw_guard\n") < out.index("delete table inet quantt_ibgw_guard") \
        < out.index("table inet quantt_ibgw_guard {")                     # one transaction, idempotent
    gw = t[t.index("unit_file quantt-ibgw.service <<UNIT"):t.index("unit_file quantt-ibgw-vnc.service")]
    assert "Requires=quantt-ibgw-guard.service" in gw and "quantt-ibgw-guard.service" in gw.split("After=")[1].split("\n")[0]
    assert '"${NFT_BIN}" -c -f "${GUARD_NFT}.new"' in t                     # checked before it is installed
    assert "quantt-ibgw-guard.service" in t[t.index("ALL_UNITS="):t.index("\n", t.index("ALL_UNITS="))]
    case = re.search(r'case "\$\{GW_HOST\}" in ([^)]+)\)', t).group(1)
    assert "*[!0-9.]*" in case                                           # a host name cannot reach the rule


def test_the_install_proves_the_access_both_ways_and_that_the_guard_refused_the_shadow_user():
    t = INSTALL.read_text()
    chk = t[t.index("check_feed_and_guard() {"):t.index("summary() {")]
    assert '"${RUN_USER}:${SHADOW_USER} 2750"' in chk and '"${SHADOW_USER}:${RUN_USER} 2750"' in chk
    assert 'if as_reader test -w "${FEED}"; then die' in chk
    assert 'as_reader test -w "${FEED}/requests" || die' in chk
    assert 'if as_quantt test -w "${FEED}/requests"; then die' in chk
    assert 'if as_reader test -x "${STATE}"; then die' in chk and 'if as_reader test -x "${RUN_HOME}"; then die' in chk
    assert "connect_ex" in chk and '[ "${after}" -gt "${before}" ]' in chk
    main = t[t.index("\nmain() {"):]
    order = [main.index(f"\n  {s}\n") for s in ("make_state", "make_feed_dirs", "write_units", "enable_units",
                                                "check_feed_and_guard")]
    assert order == sorted(order)
    md = t[t.index("make_feed_dirs() {"):t.index("# ---------------------------------------------------------------- units")]
    assert 'chmod 2750 "${FEED}"' in md and 'chmod 2750 "${FEED}/requests"' in md
    ms = t[t.index("make_state() {"):t.index("make_feed_dirs() {")]
    assert 'if [ ! -e "${lockf}" ]; then' in ms                          # the lock's inode is never replaced


def test_the_hidden_list_is_every_runtime_key_directory_present_and_never_the_cores(tmp_path):
    t = INSTALL.read_text()
    fn = _shell_functions(["feed_hidden"], t).replace("/run/quantt-*", f"{tmp_path}/run/quantt-*")
    for d in ("quantt", "quantt-a", "quantt-b"):
        (tmp_path / "run" / d).mkdir(parents=True)
    (tmp_path / "run" / "quantt-file").write_text("")
    script = tmp_path / "h.sh"
    script.write_text(f'FEED_HIDDEN_FIXED="/run/quantt-twin /run/quantt-ibgw"\n{fn}\nfeed_hidden\n')
    out = subprocess.run(["sh", str(script)], capture_output=True, text=True).stdout.split()
    assert out == sorted([f"{tmp_path}/run/quantt-a", f"{tmp_path}/run/quantt-b", "/run/quantt-ibgw", "/run/quantt-twin"])
    assert 'FEED_HIDDEN="$(feed_hidden)"' in t and "/run/quantt " not in t.split("FEED_HIDDEN_FIXED=")[1].split("\n")[0]
    from quantt.twin import feed
    assert feed.KEY_GLOB == "/run/quantt-*"                    # the run-time check covers what appears later


def test_bootstrap_installs_nftables_for_the_guard():
    c = code_lines(BOOT)
    assert "nftables" in c and "command -v nft" in c


def test_the_hand_run_wrapper_offers_the_feed_with_its_own_directory_per_mode():
    c = code_lines(WRAP)
    assert "probe|epoch|approve|verify|compare|feed)" in c
    assert 'FEED="/srv/quantt-ibkr-feed"' in c and 'FEED="/srv/quantt-ibkr-feed-staging"' in c
    assert 'QUANTT_IBKR_FEED_DIR="${FEED}"' in c
