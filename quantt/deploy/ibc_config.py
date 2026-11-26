"""Write IBC's config.ini for the twin's IB Gateway from the tmpfs login file, into tmpfs. Stdlib only.

    python -m quantt.deploy.ibc_config --login-env /run/quantt-ibgw/login.env \\
        --out /run/quantt-ibgw-ibc/config.ini --api-port 4002 --order-precautions bypass

Run by `quantt-ibgw.service` (ExecStartPre) at every Gateway start, as user quantt.

WHY A STORED PAPER LOGIN (team lead 2026-11-25: "Yes, store the paper login"). The October design
kept every IBKR password off the VM and had the team lead log in through VNC each week
(results/ops/IBKR_SECOND_BROKER_2026-10-19.md §2.9). With the first armed session on Friday
2026-11-27 and "No phone", a logged-out Gateway would simply miss sessions. The ruling reverses
that design for the PAPER username only: the team lead sets a paper-only password in Client
Portal and stores it in the vault (`SECRET_USERNAME`, `SECRET_PASSWORD` below; the account id is
`SECRET_ACCOUNT`, read by the twin, not here). The live username's password is never stored.

WHY IBC, AND ITS RISK. IBC (IbcAlpha/IBC) fills the Gateway's login dialog from config.ini and
handles its other dialogs. Its repository was ARCHIVED on 2026-09-01 ("This project has been
retired"; October §2.9 [V]); 3.24.2 is its last release (2026-08-21), still bundled by the active
gnzsnz/ib-gateway-docker image [S: the coordinator's read, 2026-11-25]. So: no fixes will come,
and an IBKR Gateway change that breaks its dialog handling would leave the Gateway logged out
until a person logs in through VNC (kept, on demand: `quantt-ibgw-vnc.service`). It is pinned by
version and sha256 at install (install_twin_vm.sh), and IBKR does not support it (October §2.9).
IBC cannot approve a two-factor prompt: if the paper login asks for one, the Gateway stays
logged out, the twin's probe says so on the daily page and in orient, and nothing is sent.

THE CREDENTIALS NEVER TOUCH A DISK OR A COMMAND LINE. IBC accepts `--user=`/`--pw=` on its start
script, where `ps` would show them to every user: not used. This module reads the login file the
vault fetch wrote under /run (tmpfs, `quantt.deploy.boot_secrets`) and writes config.ini only under
`TMPFS_ROOT` (`--out` anywhere else is refused), in a directory of mode 0700 that this user owns,
as a 0600 file, by temp file and rename. Nothing it prints or raises holds a value: the login file
is described by its variable NAMES, as boot_secrets does.

THE SETTINGS (every key was read in 3.24.2's own config.ini by the coordinator, 2026-11-25, and
install_twin_vm.sh refuses to start if one is missing from the pinned copy):
  TradingMode=paper, FIX=no                 the paper account, by the paper username
  AcceptNonBrokerageAccountWarning=yes      the paper "not a brokerage account" dialog blocks API
                                            connections until accepted (config.ini's own text)
  ExistingSessionDetectedAction=primary     the Gateway's session is never displaced by another
                                            login of the paper username; a person who must take
                                            over stops quantt-ibgw.service first
  AcceptIncomingConnectionAction=reject     only the API clients the Gateway trusts connect;
                                            127.0.0.1 is always permitted (config.ini)
  OverrideTwsApiPort=<--api-port>           the paper port, explicit (4002, quantt/broker/ibkr.py)
  ReadOnlyLogin=no, ReadOnlyApi=no          the twin's send must be able to place; its probe and
                                            verify connect read-only from their side
  BypassOrderPrecautions=<yes|no>           the installer's REQUIRED --order-precautions choice
                                            (below): never defaulted
  AllowBlindTrading=yes                     the paper username has no market data subscription
                                            (contract §8 N4); with "no" each order waits on a
                                            warning dialog nobody is there to click
  AutoRestartTime=03:00 AM                  the daily restart (no re-login), outside every window
                                            the desk runs in: 12:20-13:00, 15:20-16:00, 17:30-18:00,
                                            the 22:00-01:00 decides, and the 06:00 morning backstop
  ColdRestartTime=18:00                     IBC's Sunday full restart and re-login after the
                                            weekly server reset (it must be after 01:00 ET)
  ReloginAfterSecondFactorAuthenticationTimeout=no   a 2FA prompt is not retried in a loop
  CommandServerPort=0, BindAddress=127.0.0.1   IBC's command server is off
  StoreSettingsOnServer=no, MinimizeMainWindow=no

BypassOrderPrecautions, THE TRADE-OFF (flagged for the team lead's review). IBKR's "Precautions"
are its own size and price checks; for an API order that trips one, the Gateway holds the order
for a click ("unless user click[s] Transmit", October §2.10 [V]). "keep" leaves them on: IBKR's
checks stay, and an order that trips one is never acknowledged, so the twin's batch stops there
and the rest of the session is missed (never resent). "bypass" turns them off for API orders:
every order goes, and the only size checks are the books' own (their plans' limits) and the
twin's buying-power check. The IBKR-era book traded MOC with no data subscription by bypassing
(October §2.10, [S]). Paper only: a live account needs this re-ruled.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

# The vault secret names (team lead's, through the coordinator, 2026-11-25). Values never go in
# a tracked file, a log or a message.
SECRET_USERNAME = "ibkr-paper-username"
SECRET_PASSWORD = "ibkr-paper-password"
SECRET_ACCOUNT = "ibkr-paper-account-id"
ENV_USERNAME = "IBKR_PAPER_USERNAME"
ENV_PASSWORD = "IBKR_PAPER_PASSWORD"
ENV_ACCOUNT = "QUANTT_IBKR_ACCOUNT"          # = quantt.broker.ibkr.ENV_ACCOUNT, pinned by a test

TMPFS_ROOT = Path("/run")
AUTO_RESTART = "03:00 AM"
COLD_RESTART = "18:00"
PRECAUTIONS = {"keep": "no", "bypass": "yes"}

FIXED = (("FIX", "no"), ("TradingMode", "paper"), ("AcceptNonBrokerageAccountWarning", "yes"),
         ("ExistingSessionDetectedAction", "primary"), ("AcceptIncomingConnectionAction", "reject"),
         ("ReadOnlyLogin", "no"), ("ReadOnlyApi", "no"), ("AllowBlindTrading", "yes"),
         ("AutoRestartTime", AUTO_RESTART), ("ColdRestartTime", COLD_RESTART),
         ("ReloginAfterSecondFactorAuthenticationTimeout", "no"), ("CommandServerPort", "0"),
         ("BindAddress", "127.0.0.1"), ("StoreSettingsOnServer", "no"), ("MinimizeMainWindow", "no"))
KEYS = ("IbLoginId", "IbPassword", "OverrideTwsApiPort", "BypassOrderPrecautions") + tuple(k for k, _ in FIXED)


class IBCConfigError(RuntimeError):
    """The config cannot be written safely. The message names what, never a value."""


def read_login(path: Path) -> dict:
    """{ENV_USERNAME, ENV_PASSWORD} from the boot_secrets file: unquoted NAME=value lines, which
    boot_secrets has already proved read back unchanged. Exactly those two names, each non-empty."""
    out = {}
    try:
        text = Path(path).read_text()
    except OSError as e:
        raise IBCConfigError(f"cannot read the login file {path} ({type(e).__name__})") from None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        k, sep, v = line.partition("=")
        if not sep or k not in (ENV_USERNAME, ENV_PASSWORD) or k in out:
            raise IBCConfigError(f"{path} line {n} is not one of {ENV_USERNAME}, {ENV_PASSWORD} (or repeats it)")
        out[k] = v
    missing = [k for k in (ENV_USERNAME, ENV_PASSWORD) if not out.get(k)]
    if missing:
        raise IBCConfigError(f"{path} lacks {missing}")
    for k, v in out.items():
        # IBC reads config.ini as key=value lines; a backslash may be read as an escape, and a
        # value with surrounding space or a line break would not be the password typed.
        if "\\" in v or v != v.strip() or any(c in v for c in "\r\n\0"):
            raise IBCConfigError(f"{k} holds a backslash, surrounding whitespace or a line break; set a paper "
                                 "password without them (its value is not shown)")
    return out


def render(login: dict, *, api_port: int, order_precautions: str) -> str:
    if order_precautions not in PRECAUTIONS:
        raise IBCConfigError(f"order precautions {order_precautions!r} must be one of {sorted(PRECAUTIONS)}")
    if isinstance(api_port, bool) or not isinstance(api_port, int) or not 1024 <= api_port <= 65535:
        raise IBCConfigError(f"api port {api_port!r} is not a port number")
    lines = ["# GENERATED at Gateway start by quantt.deploy.ibc_config into tmpfs; never on disk, never edited.",
             f"IbLoginId={login[ENV_USERNAME]}", f"IbPassword={login[ENV_PASSWORD]}",
             f"OverrideTwsApiPort={api_port}", f"BypassOrderPrecautions={PRECAUTIONS[order_precautions]}"]
    lines += [f"{k}={v}" for k, v in FIXED]
    return "\n".join(lines) + "\n"


def write(path: Path, text: str, *, tmpfs_root: Path | None = None) -> None:
    """Atomically write `text` to `path`, mode 0600, refusing any path outside `tmpfs_root` and any
    directory that is not this user's own mode-0700 directory."""
    tmpfs_root = TMPFS_ROOT if tmpfs_root is None else tmpfs_root
    path = Path(path)
    if not path.is_absolute():
        raise IBCConfigError(f"--out {path} must be absolute")
    real_parent = Path(os.path.realpath(path.parent))
    root = Path(os.path.realpath(tmpfs_root))
    if real_parent != root and root not in real_parent.parents:
        raise IBCConfigError(f"--out {path} is not under {tmpfs_root}: the config holds the paper password "
                             "and is written to tmpfs only")
    st = os.stat(real_parent)
    if st.st_mode & 0o077:
        raise IBCConfigError(f"{real_parent} is mode {oct(st.st_mode & 0o777)}; it must be 0700")
    if st.st_uid != os.getuid():
        raise IBCConfigError(f"{real_parent} is not owned by this user")
    fd, tmp = tempfile.mkstemp(prefix=".config.", dir=real_parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, real_parent / path.name)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m quantt.deploy.ibc_config", description=__doc__.split("\n")[0])
    ap.add_argument("--login-env", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--api-port", required=True, type=int)
    ap.add_argument("--order-precautions", required=True, choices=sorted(PRECAUTIONS))
    a = ap.parse_args(argv)
    try:
        login = read_login(a.login_env)
        write(a.out, render(login, api_port=a.api_port, order_precautions=a.order_precautions))
    except IBCConfigError as e:
        print(f"REFUSED ibc_config: {e}", file=sys.stderr)
        return 2
    print(f"wrote {a.out} (IBC config: {', '.join(KEYS)}); credentials from {a.login_env} "
          f"({ENV_USERNAME}, {ENV_PASSWORD}; values not shown)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
