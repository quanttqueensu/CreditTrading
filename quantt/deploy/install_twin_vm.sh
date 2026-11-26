#!/bin/sh
# Root install of the IBKR twin (quantt/twin) and its IB Gateway on the prod VM. PAPER ONLY.
#
#   sudo sh install_twin_vm.sh --vault <vault> --order-precautions keep|bypass            (release)
#   sudo sh install_twin_vm.sh --vault <vault> --order-precautions keep|bypass \
#        --staging /home/quantt/twin-staging/tree --python /home/quantt/twin-staging/venv/bin/python
#   sudo sh install_twin_vm.sh uninstall
#
# The team lead runs it (sudo). IT NEVER ARMS: every twin job unit carries DRY_RUN=1 and it writes
# no AUTO_ARMED. In --staging mode the units also set QUANTT_TWIN_STAGING=1 and force DRY_RUN=1 on
# the command line itself, so not even a hand edit of the unit can let staging transmit (the
# runner refuses whenever QUANTT_TWIN_STAGING is set: quantt/twin/run.py, STAGING).
#
# TWO MODES (team lead 2026-11-25: build and test locally, stage on the VM from a local copy, push once)
#   release  the code is the PROD CLONE (/home/quantt/prod/quantt-alpaca), which must be a clean
#            checkout of a release-* tag that is on origin at HEAD (install_vm.py's clone_origin and
#            remote_tag_commit, called, not copied), and the prod venv.
#   staging  the code is a COPY of the local tree at --staging (rsync'ed there by hand), run with
#            the --python given (a venv built from that copy's requirements.txt, so the prod venv is
#            untouched), state in <staging>/../state/twin. Same units, same secrets, never sends.
# Re-running in either mode rewrites the units with DRY_RUN=1; it never touches a book's state.
#
# WHAT IT MAKES (nothing of any Alpaca book's is written or restarted)
#   /var/cache/quantt-ibgw/            the two downloads, kept only if their sha256 is the pinned one
#   /home/quantt/Jts/ibgateway/<major> the IB Gateway, installed unattended as quantt (install4j -q -dir)
#   /opt/ibc-<version>                 IBC, unpacked, root-owned and read-only to quantt
#   /opt/quantt-ibgw/bin/              ibgw_run.sh and ibc_config.py copied from the code, root-owned
#   <state>/twin                       the twin's state directory (0700, quantt)
#   quantt-ibgw-secret.service         vault -> /run/quantt-ibgw/login.env (paper username, password)
#   quantt-twin-secret.service         vault -> /run/quantt-twin/ibkr.env (the expected account id)
#   quantt-ibgw.service                Xvfb + IBC + the Gateway; config.ini generated into tmpfs
#   quantt-ibgw-vnc.service            ON DEMAND only: x11vnc on 127.0.0.1:5947 for a manual login
#   quantt-twin-send / -verify / -probe .service + .timer
#   quantt-ibgw-guard.service          THE GUARD (below): nftables, loaded before the Gateway, which Requires= it
#   /srv/quantt-ibkr-feed[-staging]    B10's feed directory (quantt:quantt-shadow 2750) and its requests/
#                                      (quantt-shadow:quantt 2750); <state>/twin/.gateway.lock (0600, quantt)
#   quantt-twin-feed-close / -evening .service + .timer   B10's READ-ONLY market-data producer, sandboxed
#
# B10, THE FEED (team lead 2026-11-25: "we can trade/interacti with ibrk quotes to run shadow books / test
# ideas"; quantt/twin/feed.py). The trading user's read-only producer writes IBKR's daily bars into the feed
# directory, which the shadow user (quantt-shadow, docs/RUNBOOK.md 8.10) reads; the shadow user asks for
# symbols by writing files into requests/. Staging writes /srv/quantt-ibkr-feed-staging, never the release
# directory the shadow books read. Its units are sandboxed in the plan feed's pattern (RUNBOOK 8.15): /home
# hidden but for the code, the venv and the books' state (read-only) and the Gateway lock; one writable
# directory; requests/ read-only; every key directory but the core's Alpaca market-data key (/run/quantt)
# inaccessible (the IBKR account id reaches it through EnvironmentFile=, read by systemd before the
# sandbox). It needs the network for Alpaca's calendar, so it is not IP-restricted; the GUARD is what keeps
# every other user off the Gateway. It has no RestrictSUIDSGID: its session directories are setgid (2750).
#
# THE GUARD. File permissions cannot stop a local process from opening a loopback TCP connection, and the
# Gateway trusts 127.0.0.1, so without this any user on the VM (the shadow runner included, whose unit has
# full network) could connect to the API port and send orders. quantt-ibgw-guard.service loads an nftables
# table that rejects, for every local user but quantt, a TCP connection to the Gateway's API ports (4001,
# 4002, 7496, 7497) on the Gateway's host, and rejects every loopback TCP connection the shadow user makes
# except DNS (port 53): that also covers the on-demand VNC and any API port a GUI change could open.
# quantt-ibgw.service Requires= the guard, so the Gateway does not run without it. The install proves it:
# a connection attempt as quantt-shadow must be refused AND the guard's counter must move.
#
# THE TIMES (New York; the runner, not the timer, knows holidays and early closes: quantt/twin/config.py)
#   send     12:30 12:40 15:30 15:40 Mon-Fri. On a 16:00 close the 12:3x/12:4x runs idle; on a
#            13:00 close (2026-11-27, the first armed session) the 15:3x/15:4x runs idle.
#   verify   17:45 Mon-Fri, after the books' 17:30/17:35 verifies, and same-day (IBKR keeps only today's
#            executions).
#   probe    09:00 12:00 15:15 Mon-Fri and 19:30 Sunday (after IBC's 18:00 Sunday cold restart): read-only,
#            so a logged-out Gateway shows on the daily page before a send would miss.
#   The Gateway restarts itself daily at 03:00 (IBC AutoRestartTime), outside 12:20-13:00, 15:20-16:00,
#   17:30-18:00 and the 22:00-01:00 decides.
#
# MEMORY (free hosting: Standard_B2pts_v2, 944 MB, about 634 MB available, 2 GB swap; 2026-11-25).
#   JVM heap -Xmx${HEAP_MB}m in the Gateway's ibgateway.vmoptions. IBKR's "4000 MB" is a heap
#   ceiling for heavy market-data users, and its pages disagree on it [U]; the twin requests no
#   market data and places a few hundred orders a day. 320 MB is a first setting, not a measurement:
#   one public reading of a logged-in paper Gateway is 459-494 MB resident [U] at a larger heap.
#   MemoryHigh=${MEM_HIGH} throttles the Gateway's cgroup (Xvfb included) and MemoryMax=${MEM_MAX}
#   kills it; OOMScoreAdjust=900 makes the kernel pick it before any Alpaca runner. The first
#   sessions measure `systemctl show quantt-ibgw -p MemoryPeak`; resize only by the team lead's ruling.
#   A second free-size VM (B2ats_v2, x64) for the Gateway needs only --gateway-host/--gateway-port here.
set -eu

RUN_USER="quantt"
RUN_HOME="/home/${RUN_USER}"
PROD="${RUN_HOME}/prod/quantt-alpaca"
PROD_PY="${RUN_HOME}/venv/bin/python"
STATE_ROOT="${RUN_HOME}/quantt_state"
UNIT_DIR="/etc/systemd/system"
TZ_NAME="America/New_York"
CORE_ENV_FILE="/run/quantt/alpaca.env"      # = install_vm.py's quantt-secret.service file (core keys: market data only)
DATA_BOOK="cef"

# THE PINS (read and hashed by the coordinator, 2026-11-25 23:15 ET). The "stable" URL changes its
# content when IBKR moves stable: a mismatch refuses, naming both hashes, and nothing is installed.
GW_URL="https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-arm.sh"
GW_VERSION="10.50.1h"
GW_MAJOR="1050"
GW_SHA256="1352b9f119c194409084a7081e629aba63a3eabb177777ec372a0f2d3bac6537"
IBC_URL="https://github.com/IbcAlpha/IBC/releases/download/3.24.2/IBCLinux-3.24.2.zip"
IBC_VERSION="3.24.2"
IBC_SHA256="cc097ca1dfa75413a5fbe02e4743050af15f3308eb6a97c769b3cff9850c80c5"
CACHE="/var/cache/quantt-ibgw"
JTS="${RUN_HOME}/Jts"
GW_DIR="${JTS}/ibgateway/${GW_MAJOR}"
IBC_DIR="/opt/ibc-${IBC_VERSION}"
BIN="/opt/quantt-ibgw/bin"
IBC_RUN="/run/quantt-ibgw-ibc"
LOGIN_RUN="/run/quantt-ibgw"
TWIN_RUN="/run/quantt-twin"

HEAP_MB=320
MEM_HIGH="520M"
MEM_MAX="600M"
GW_HOST="127.0.0.1"
GW_PORT="4002"

JOB_TIMERS="quantt-twin-send.timer quantt-twin-verify.timer quantt-twin-probe.timer quantt-twin-feed-close.timer quantt-twin-feed-evening.timer"
JOB_SERVICES="quantt-twin-send.service quantt-twin-verify.service quantt-twin-probe.service quantt-twin-feed-close.service quantt-twin-feed-evening.service"
ALL_UNITS="${JOB_TIMERS} ${JOB_SERVICES} quantt-twin-secret.service quantt-ibgw-secret.service quantt-ibgw-guard.service quantt-ibgw.service quantt-ibgw-vnc.service"

# B10: the feed's reader, its directories, the guard. SHADOW_USER = shadow/deploy/install_shadow_vm.sh SVC_USER.
SHADOW_USER="quantt-shadow"
GUARD_NFT="${BIN}/ibgw_guard.nft"
GUARD_TABLE="quantt_ibgw_guard"
API_PORTS="4001, 4002, 7496, 7497"
# The runtime directories that hold a key or a login are hidden from the feed: every /run/quantt-* present at
# install (feed_hidden) and these, but never the core's /run/quantt (the feed reads Alpaca's calendar with that
# market-data key, as the twin does). One that appears later is caught at run time: the feed's own check
# (--require-sandbox) refuses while any /run/quantt-* directory is reachable, until this script is re-run.
FEED_HIDDEN_FIXED="/run/quantt-twin /run/quantt-ibgw /run/quantt-ibgw-ibc /run/quantt-shadow"

MODE="install"; VAULT=""; PRECAUTIONS=""; STAGING=""; PY=""; TAG=""
die() { echo "REFUSED: $*" >&2; exit 2; }
step() { echo "== $*"; }
as_quantt() { runuser -u "${RUN_USER}" -- env HOME="${RUN_HOME}" "$@"; }

parse() {
  while [ $# -gt 0 ]; do
    case "$1" in
      uninstall) MODE="uninstall"; shift ;;
      --vault) VAULT="$2"; shift 2 ;;
      --order-precautions) PRECAUTIONS="$2"; shift 2 ;;
      --staging) STAGING="$2"; shift 2 ;;
      --python) PY="$2"; shift 2 ;;
      --gateway-host) GW_HOST="$2"; shift 2 ;;
      --gateway-port) GW_PORT="$2"; shift 2 ;;
      --heap-mb) HEAP_MB="$2"; shift 2 ;;
      *) die "unknown argument '$1'" ;;
    esac
  done
  [ "${MODE}" = "uninstall" ] && return 0
  [ -n "${VAULT}" ] || die "--vault <vault-name> is required"
  case "${VAULT}" in *[!A-Za-z0-9-]*|-*) die "vault '${VAULT}' is not a plain vault name" ;; esac
  case "${PRECAUTIONS}" in keep|bypass) ;; *) die "--order-precautions keep|bypass is required (no default; quantt/deploy/ibc_config.py explains the trade-off)" ;; esac
  case "${GW_PORT}" in 4002|7497) ;; *) die "--gateway-port ${GW_PORT} is not a paper API port (4002, 7497)" ;; esac
  case "${HEAP_MB}" in *[!0-9]*|"") die "--heap-mb must be a number of megabytes" ;; esac
  # THE GUARD is an nftables rule on the Gateway's address, so the host must be an IPv4 literal.
  case "${GW_HOST}" in *[!0-9.]*|""|.*|*.) die "--gateway-host ${GW_HOST} must be an IPv4 address (the guard's rule names it)" ;; esac
  if [ -n "${STAGING}" ]; then
    [ -n "${PY}" ] || die "--staging needs --python <the staging venv's python>"
    CODE="${STAGING}"
    STATE="$(dirname "${STAGING}")/state/twin"
    IDS="41 42 43 44"
    FEED="/srv/quantt-ibkr-feed-staging"
  else
    [ -z "${PY}" ] || die "--python is for --staging only; a release runs the prod venv"
    PY="${PROD_PY}"
    CODE="${PROD}"
    STATE="${STATE_ROOT}/twin"
    IDS="31 32 33 34"
    FEED="/srv/quantt-ibkr-feed"
  fi
  LOGS="${STATE}/logs"
  VENV_DIR="$(dirname "$(dirname "${PY}")")"
}

# ---------------------------------------------------------------- checks (RUNBOOK §8.3 shape)

check_root_zone_window() {
  [ "$(id -u)" -eq 0 ] || die "run as root (sudo)"
  command -v systemctl >/dev/null 2>&1 || die "systemctl not found"
  command -v runuser >/dev/null 2>&1 || die "runuser not found"
  [ "$(timedatectl show -p Timezone --value)" = "${TZ_NAME}" ] || die "system zone is not ${TZ_NAME}"
  dow="$(date +%u)"; hm="$(date +%H%M)"
  if [ "${dow}" -le 5 ]; then
    for w in "1220 1300" "1520 1600" "1730 1800"; do
      set -- ${w}
      if [ "${hm}" -ge "$1" ] && [ "${hm}" -lt "$2" ]; then
        die "it is ${hm} New York on a weekday, inside a twin window ($1-$2); a timer restarted now could replay a slot"
      fi
    done
  fi
  running="$(systemctl list-units --type=service --state=activating,running --no-legend 'quantt-twin-*' | awk '{print $1}' | tr '\n' ' ')"
  [ -z "$(echo "${running}" | tr -d ' ')" ] || die "a twin job is running: ${running}"
}

check_layout() {
  step "users, code, Python, packages, swap, drop-ins"
  id -u "${RUN_USER}" >/dev/null 2>&1 || die "user ${RUN_USER} does not exist"
  [ -d "${STATE_ROOT}" ] || die "${STATE_ROOT} does not exist; prod is not installed here"
  [ -x "${PY}" ] || die "${PY} is not an executable interpreter"
  for f in quantt/twin/run.py quantt/broker/ibkr.py quantt/deploy/ibc_config.py quantt/deploy/vm/ibgw_run.sh ops/twin/ibkr_twin.json \
           quantt/twin/feed.py quantt/broker/ibkr_market.py ops/twin/ibkr_feed.json; do
    [ -f "${CODE}/${f}" ] || die "${CODE}/${f} is missing"
  done
  # The books the twin reads, and the variable naming each one's state directory, from the twin's
  # own table (quantt/twin/books.py BOOKS): one owner, never a list written again here.
  BOOK_ENV="$(cd "${CODE}" && as_quantt "${PY}" -B -c 'from quantt.twin.books import BOOKS; print(" ".join(b.state_env + "=" + b.name for b in BOOKS))')" \
    || die "cannot read the twin's book table from ${CODE}"
  BOOK_LINES=""; BOOK_DIRS=""
  for pair in ${BOOK_ENV}; do
    b="${pair#*=}"
    [ -d "${STATE_ROOT}/${b}" ] || die "${STATE_ROOT}/${b} does not exist: the twin reads every book's plans"
    BOOK_LINES="${BOOK_LINES}Environment=${pair%%=*}=${STATE_ROOT}/${b}
"
    BOOK_DIRS="${BOOK_DIRS} ${STATE_ROOT}/${b}"
  done
  (cd "${CODE}" && as_quantt "${PY}" -B -c 'import ib_async, sys; v = ib_async.__version__; sys.exit(0 if v == "2.1.0" else "ib_async is " + v + ", not the pinned 2.1.0")') \
    || die "${PY} cannot import ib_async 2.1.0 (rebuild the venv from ${CODE}/requirements.txt)"
  command -v Xvfb >/dev/null 2>&1 || die "Xvfb not installed; the team lead runs quantt/deploy/vm/bootstrap_ibgw.sh first"
  command -v x11vnc >/dev/null 2>&1 || die "x11vnc not installed; run bootstrap_ibgw.sh first"
  command -v unzip >/dev/null 2>&1 || die "unzip not installed; run bootstrap_ibgw.sh first"
  command -v curl >/dev/null 2>&1 || die "curl not installed"
  NFT_BIN="$(command -v nft)" || die "nft not installed (nftables); run bootstrap_ibgw.sh first: THE GUARD needs it"
  id -u "${SHADOW_USER}" >/dev/null 2>&1 || die "user ${SHADOW_USER} does not exist; install the shadow runner first (docs/RUNBOOK.md 8.10): the feed is written for it"
  getent group "${SHADOW_USER}" >/dev/null || die "group ${SHADOW_USER} does not exist"
  for g in $(id -nG "${SHADOW_USER}"); do
    [ "${g}" != "${RUN_USER}" ] || die "${SHADOW_USER} is in group ${RUN_USER}: it could enter ${RUN_HOME}; remove it"
  done
  LOCK_NAME="$(cd "${CODE}" && as_quantt "${PY}" -B -c 'from quantt.twin.config import GATEWAY_LOCK_NAME as n; print(n)')" \
    || die "cannot read the Gateway lock's name from ${CODE}/quantt/twin/config.py"
  case "${LOCK_NAME}" in *[!A-Za-z0-9._-]*|""|*/*) die "the Gateway lock name '${LOCK_NAME}' is not a plain file name" ;; esac
  [ -n "$(swapon --show=NAME --noheadings)" ] || die "no swap is active (bootstrap.sh makes a 2 GB /swapfile)"
  for u in ${ALL_UNITS}; do
    for d in "${UNIT_DIR}/${u}.d" "/run/systemd/system/${u}.d" "/usr/lib/systemd/system/${u}.d"; do
      [ ! -e "${d}" ] || die "${d} exists: a drop-in would override what this script writes (DRY_RUN among it)"
    done
  done
  for d in "${UNIT_DIR}/quantt-twin-.service.d" "${UNIT_DIR}/quantt-.service.d" "${UNIT_DIR}/service.d" "${UNIT_DIR}/timer.d"; do
    [ ! -e "${d}" ] || die "${d} exists: a prefix drop-in would apply to the twin's units"
  done
}

check_code_release() {
  if [ -n "${STAGING}" ]; then
    step "staging code at ${CODE} (a copy of the local tree; it never sends)"
    [ ! -e "${CODE}/.git" ] || echo "   note: ${CODE} is a git checkout; staging runs it as a copy all the same"
    if as_quantt test -w "${CODE}/quantt/twin/run.py"; then
      die "${RUN_USER} can write ${CODE}/quantt/twin/run.py; the runner must not be able to edit the code it runs (chown root, chmod a-w)"
    fi
    TAG="staging"
    return 0
  fi
  step "the prod clone is a clean checkout of a release tag that is on origin at HEAD"
  [ -z "$(as_quantt git -C "${PROD}" status --porcelain)" ] || die "${PROD} has local modifications"
  for t in $(as_quantt git -C "${PROD}" tag --points-at HEAD); do
    case "${t}" in release-[0-9]*) TAG="${t}" ;; esac
  done
  [ -n "${TAG}" ] || die "${PROD} HEAD is not at a release-* tag"
  (cd "${PROD}" && as_quantt "${PY}" -B -c '
import subprocess, sys
from pathlib import Path
from quantt.deploy import install_vm as iv
prod, tag = Path(sys.argv[1]), sys.argv[2]
def git(*a, allow_fail=False):
    r = subprocess.run(["git", "-C", str(prod), *a], capture_output=True, text=True)
    if r.returncode and not allow_fail:
        raise SystemExit("git " + " ".join(a) + " failed: " + r.stderr.strip())
    return r.stdout if r.returncode == 0 else None
url = iv.clone_origin(git, prod, iv.ORIGIN_URLS)
commit = iv.remote_tag_commit(git, url, tag)
head = git("rev-parse", "HEAD").strip()
if head != commit:
    raise SystemExit(f"{tag} is {commit} on origin, HEAD is {head}")
print("   origin", url, "tag", tag, "at", commit[:12])
' "${PROD}" "${TAG}") || die "the release check failed (above)"
}

# ---------------------------------------------------------------- downloads and installs

fetch_verified() {
  # $1 url, $2 file name, $3 pinned sha256. Never installs a file whose hash is not the pin.
  install -d -o root -g root -m 755 "${CACHE}"
  f="${CACHE}/$2"
  if [ -f "${f}" ] && [ "$(sha256sum "${f}" | awk '{print $1}')" = "$3" ]; then
    echo "   $2: cached, sha256 matches"; return 0
  fi
  tmp="${CACHE}/.$2.part"
  rm -f "${tmp}"
  curl --fail --silent --show-error --location --proto '=https' --output "${tmp}" "$1" || die "download of $1 failed"
  got="$(sha256sum "${tmp}" | awk '{print $1}')"
  if [ "${got}" != "$3" ]; then
    rm -f "${tmp}"
    die "$2: sha256 ${got} is not the pinned $3; the file at $1 has changed. Nothing was installed. Read what changed, then update the pin in this script"
  fi
  mv "${tmp}" "${f}"
  chmod 644 "${f}"
  echo "   $2: downloaded, sha256 ${got} = the pin"
}

install_gateway() {
  step "IB Gateway ${GW_VERSION} (major ${GW_MAJOR}) under ${GW_DIR}"
  fetch_verified "${GW_URL}" "ibgateway-${GW_VERSION}-linux-arm.sh" "${GW_SHA256}"
  marker="${GW_DIR}/.quantt-installed"
  if [ -f "${marker}" ] && [ "$(cat "${marker}")" = "${GW_VERSION} ${GW_SHA256}" ]; then
    echo "   already installed from the pinned file"
  else
    install -d -o "${RUN_USER}" -g "${RUN_USER}" -m 700 "${JTS}"
    # install4j's unattended mode: -q (quiet) and -dir <installation directory> [S: install4j's
    # command-line options; the installer's header does not print them]. Runs as quantt, from the
    # verified cached copy; the bundled JRE (jre.tar.gz in its archive) is used.
    as_quantt sh "${CACHE}/ibgateway-${GW_VERSION}-linux-arm.sh" -q -dir "${GW_DIR}" \
      || die "the Gateway installer failed; read its output above"
    [ -d "${GW_DIR}/jars" ] || die "no ${GW_DIR}/jars after the install: IBC needs the offline Gateway"
    echo "${GW_VERSION} ${GW_SHA256}" > "${marker}"
    chown "${RUN_USER}:${RUN_USER}" "${marker}"
  fi
  vm="${GW_DIR}/ibgateway.vmoptions"
  [ -f "${vm}" ] || die "${vm} is missing: IBC reads the JVM options from it"
  grep -v '^-Xmx' "${vm}" > "${vm}.new"
  echo "-Xmx${HEAP_MB}m" >> "${vm}.new"
  chown "${RUN_USER}:${RUN_USER}" "${vm}.new"
  mv "${vm}.new" "${vm}"
  [ "$(grep -c '^-Xmx' "${vm}")" = "1" ] || die "${vm} does not carry exactly one -Xmx"
  echo "   JVM heap: $(grep '^-Xmx' "${vm}")"
}

install_ibc() {
  step "IBC ${IBC_VERSION} in ${IBC_DIR} (archived upstream on 2026-09-01; pinned)"
  fetch_verified "${IBC_URL}" "IBCLinux-${IBC_VERSION}.zip" "${IBC_SHA256}"
  if [ ! -f "${IBC_DIR}/.quantt-installed" ]; then
    rm -rf "${IBC_DIR}.new"
    install -d -o root -g root -m 755 "${IBC_DIR}.new"
    unzip -q "${CACHE}/IBCLinux-${IBC_VERSION}.zip" -d "${IBC_DIR}.new"
    find "${IBC_DIR}.new" -name '*.sh' -exec chmod 755 {} +
    echo "${IBC_VERSION} ${IBC_SHA256}" > "${IBC_DIR}.new/.quantt-installed"
    chown -R root:root "${IBC_DIR}.new"
    chmod -R go-w "${IBC_DIR}.new"
    rm -rf "${IBC_DIR}"
    mv "${IBC_DIR}.new" "${IBC_DIR}"
  fi
  [ -x "${IBC_DIR}/scripts/ibcstart.sh" ] || die "${IBC_DIR}/scripts/ibcstart.sh is missing"
  # Every key the generator writes must be a key of THIS IBC's config.ini, or IBC would ignore it.
  keys="$(cd "${CODE}" && "${PY}" -B -c 'from quantt.deploy import ibc_config as c; print(" ".join(c.KEYS))')"
  for k in ${keys}; do
    grep -Eq "^#?${k}=" "${IBC_DIR}/config.ini" || die "IBC ${IBC_VERSION}'s config.ini has no key ${k}; the generator and the pinned IBC disagree"
  done
  echo "   all $(echo "${keys}" | wc -w | tr -d ' ') generated keys exist in the pinned config.ini"
}

install_bin() {
  step "the Gateway's start files and THE GUARD's rules, root-owned, in ${BIN}"
  install -d -o root -g root -m 755 "${BIN}"
  install -o root -g root -m 755 "${CODE}/quantt/deploy/vm/ibgw_run.sh" "${BIN}/ibgw_run.sh"
  install -o root -g root -m 644 "${CODE}/quantt/deploy/ibc_config.py" "${BIN}/ibc_config.py"
  render_guard > "${GUARD_NFT}.new"
  chmod 644 "${GUARD_NFT}.new"
  "${NFT_BIN}" -c -f "${GUARD_NFT}.new" || die "nft rejects the guard's rules (${GUARD_NFT}.new); nothing was loaded"
  mv "${GUARD_NFT}.new" "${GUARD_NFT}"
  echo "   ${GUARD_NFT}: only uid $(id -u "${RUN_USER}") (${RUN_USER}) may connect to ${GW_HOST} ports ${API_PORTS}"
}

render_guard() {
  # One nft transaction: create-if-absent, delete, define. Re-loading it replaces the table atomically.
  quid="$(id -u "${RUN_USER}")"; suid="$(id -u "${SHADOW_USER}")"
  if [ "${GW_HOST}" = "127.0.0.1" ]; then dst4="127.0.0.0/8"; else dst4="${GW_HOST}"; fi
  echo "# ${GUARD_NFT}: WRITTEN by quantt/deploy/install_twin_vm.sh (THE GUARD, ${TAG}). Loaded by"
  echo "# quantt-ibgw-guard.service; quantt-ibgw.service Requires= it. Re-run the installer rather than editing."
  echo "table inet ${GUARD_TABLE}"
  echo "delete table inet ${GUARD_TABLE}"
  echo "table inet ${GUARD_TABLE} {"
  echo "  chain output {"
  echo "    type filter hook output priority 0; policy accept;"
  echo "    ip daddr ${dst4} tcp dport { ${API_PORTS} } meta skuid != ${quid} counter reject with tcp reset"
  if [ "${GW_HOST}" = "127.0.0.1" ]; then
    echo "    ip6 daddr ::1 tcp dport { ${API_PORTS} } meta skuid != ${quid} counter reject with tcp reset"
  fi
  echo "    oifname \"lo\" meta skuid ${suid} tcp dport != 53 counter reject with tcp reset"
  echo "  }"
  echo "}"
}

make_state() {
  step "state directory ${STATE} (0700, ${RUN_USER})"
  install -d -o "${RUN_USER}" -g "${RUN_USER}" -m 700 "$(dirname "${STATE}")" "${STATE}" "${LOGS}"
  # The Gateway session lock (quantt/broker/ibkr.py). Created once and never replaced: a new inode
  # under a held lock would let a second process connect beside the first.
  lockf="${STATE}/${LOCK_NAME}"
  [ ! -L "${lockf}" ] || die "${lockf} is a symlink"
  if [ ! -e "${lockf}" ]; then
    install -o "${RUN_USER}" -g "${RUN_USER}" -m 600 /dev/null "${lockf}"
  fi
  [ "$(stat -c '%U:%G %a' "${lockf}")" = "${RUN_USER}:${RUN_USER} 600" ] || die "${lockf} is $(stat -c '%U:%G %a' "${lockf}"), not ${RUN_USER}:${RUN_USER} 600"
  [ ! -e "${STATE}/AUTO_ARMED" ] || echo "   WARNING: ${STATE}/AUTO_ARMED exists (kept); the units are DRY_RUN=1"
  if [ -n "${STAGING}" ] && [ -e "${STATE}/AUTO_ARMED" ]; then
    die "${STATE}/AUTO_ARMED exists in a STAGING state directory; remove it (staging never sends)"
  fi
}

make_feed_dirs() {
  step "B10 feed directory ${FEED} (${RUN_USER}:${SHADOW_USER} 2750) and ${FEED}/requests (${SHADOW_USER}:${RUN_USER} 2750)"
  # /srv, not /home/quantt (the plan feed's reason, RUNBOOK 8.15): a feed under prod's home would need the
  # shadow user let into it. Setgid, so the producer's files take the reader's group (the producer also
  # checks every file it writes). requests/ is the shadow user's, setgid to quantt's group, so the files
  # it drops are readable by the producer and by nobody else; the producer's unit sees it read-only.
  install -d -m 0755 -o root -g root /srv
  [ ! -L "${FEED}" ] && [ ! -L "${FEED}/requests" ] || die "${FEED} or its requests directory is a symlink"
  install -d -m 2750 -o "${RUN_USER}" -g "${SHADOW_USER}" "${FEED}"
  chown "${RUN_USER}:${SHADOW_USER}" "${FEED}"
  chmod 2750 "${FEED}"
  install -d -m 2750 -o "${SHADOW_USER}" -g "${RUN_USER}" "${FEED}/requests"
  chown "${SHADOW_USER}:${RUN_USER}" "${FEED}/requests"
  chmod 2750 "${FEED}/requests"
}

# ---------------------------------------------------------------- units

unit_file() {
  case "$1" in quantt-twin-*|quantt-ibgw*) ;; *) die "internal: $1 is not a twin unit" ;; esac
  cat > "${UNIT_DIR}/$1"
  chmod 644 "${UNIT_DIR}/$1"
  echo "   ${UNIT_DIR}/$1"
}

secret_service() {
  # $1 unit, $2 runtime dir name, $3 out file, $4.. --secret pairs. boot_secrets' pattern exactly
  # (quantt-reports-secret.service): its own 0700 tmpfs directory, RemainAfterExit, pulled in with
  # Wants= + After=, a 0600 file, NAMES only in the log.
  u="$1"; rd="$2"; outf="$3"; shift 3
  unit_file "${u}" <<UNIT
# ${u} : vault -> ${outf} (tmpfs), once per boot when the fetch succeeds. Mode ${TAG}.
# WRITTEN by quantt/deploy/install_twin_vm.sh; re-run it rather than hand-editing.
[Unit]
Description=QUANTT twin secrets into /run/${rd} (${TAG})
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=${RUN_USER}
Group=${RUN_USER}
RuntimeDirectory=${rd}
RuntimeDirectoryMode=0700
WorkingDirectory=${CODE}
Environment=PYTHONUNBUFFERED=1
ExecStart=${PY} -B -m quantt.deploy.boot_secrets --provider azure-keyvault --config vault=${VAULT} $* --out ${outf}
StandardOutput=append:${LOGS}/${u%.service}.out.log
StandardError=append:${LOGS}/${u%.service}.err.log

[Install]
WantedBy=multi-user.target
UNIT
}

job_service() {
  # $1 phase, $2 client id, $3 SuccessExitStatus line, $4 command words after "-m quantt.twin"
  if [ -n "${STAGING}" ]; then
    run="/usr/bin/env DRY_RUN=1 QUANTT_TWIN_STAGING=1 ${PY} -B -m quantt.twin $4"
    stage_env="Environment=QUANTT_TWIN_STAGING=1"
  else
    run="${PY} -B -m quantt.twin $4"
    stage_env="# release mode: QUANTT_TWIN_STAGING unset"
  fi
  unit_file "quantt-twin-$1.service" <<UNIT
# quantt-twin-$1.service : the IBKR twin's $1 (PAPER ONLY), ${TAG}.
# WRITTEN by quantt/deploy/install_twin_vm.sh. DRY_RUN=1 as installed; the send transmits only with
# DRY_RUN exactly 0 AND ${STATE}/AUTO_ARMED or that day's APPROVED plan_sha, never in staging.
[Unit]
Description=QUANTT IBKR twin $1 (${TAG})
Wants=quantt-secret.service quantt-twin-secret.service quantt-ibgw.service
After=quantt-secret.service quantt-twin-secret.service quantt-ibgw.service

[Service]
Type=oneshot
User=${RUN_USER}
Group=${RUN_USER}
WorkingDirectory=${CODE}
Environment=DRY_RUN=1
${stage_env}
Environment=QUANTT_STATE_DIR=${STATE}
${BOOK_LINES}Environment=QUANTT_ENV_FILE=${CORE_ENV_FILE}
Environment=QUANTT_TWIN_ALPACA_DATA_BOOK=${DATA_BOOK}
Environment=QUANTT_IBKR_HOST=${GW_HOST}
Environment=QUANTT_IBKR_PORT=${GW_PORT}
Environment=QUANTT_IBKR_CLIENT_ID=$2
EnvironmentFile=${TWIN_RUN}/ibkr.env
Environment=PYTHONUNBUFFERED=1
ExecStart=${run}
ReadOnlyPaths=${CODE}${BOOK_DIRS}
$3
StandardOutput=append:${LOGS}/$1.out.log
StandardError=append:${LOGS}/$1.err.log
UNIT
}

feed_hidden() {
  # every /run/quantt-* directory present now, and the fixed list; never /run/quantt itself
  { for d in /run/quantt-*; do [ -d "${d}" ] && echo "${d}"; done; for d in ${FEED_HIDDEN_FIXED}; do echo "${d}"; done; } \
    | sort -u | tr '\n' ' ' | sed 's/ $//'
}

feed_service() {
  # $1 unit stem (close|evening), $2 slot, $3 client id. B10's READ-ONLY producer, sandboxed (header, B10).
  if [ -n "${STAGING}" ]; then
    run="/usr/bin/env DRY_RUN=1 QUANTT_TWIN_STAGING=1 ${PY} -B -m quantt.twin feed --slot $2 --require-sandbox"
    stage_env="Environment=QUANTT_TWIN_STAGING=1"
  else
    run="${PY} -B -m quantt.twin feed --slot $2 --require-sandbox"
    stage_env="# release mode: QUANTT_TWIN_STAGING unset"
  fi
  hidden="$(for d in ${FEED_HIDDEN}; do printf -- '-%s ' "${d}"; done | sed 's/ $//')"
  unit_file "quantt-twin-feed-$1.service" <<UNIT
# quantt-twin-feed-$1.service : B10, IBKR's daily bars for the shadow books ($2), READ ONLY, ${TAG}.
# WRITTEN by quantt/deploy/install_twin_vm.sh. It sends nothing (a read client; quantt/twin/feed.py);
# DRY_RUN=1 is set all the same. It writes only ${FEED}; the shadow user reads it.
[Unit]
Description=QUANTT IBKR market-data feed, $2, read only (${TAG})
Wants=quantt-secret.service quantt-twin-secret.service quantt-ibgw.service
After=quantt-secret.service quantt-twin-secret.service quantt-ibgw.service

[Service]
Type=oneshot
User=${RUN_USER}
Group=${RUN_USER}
UMask=0027
WorkingDirectory=${CODE}
Environment=DRY_RUN=1
${stage_env}
Environment=QUANTT_STATE_DIR=${STATE}
${BOOK_LINES}Environment=QUANTT_ENV_FILE=${CORE_ENV_FILE}
Environment=QUANTT_TWIN_ALPACA_DATA_BOOK=${DATA_BOOK}
Environment=QUANTT_IBKR_HOST=${GW_HOST}
Environment=QUANTT_IBKR_PORT=${GW_PORT}
Environment=QUANTT_IBKR_CLIENT_ID=$3
Environment=QUANTT_IBKR_FEED_DIR=${FEED}
EnvironmentFile=${TWIN_RUN}/ibkr.env
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=${run}
SuccessExitStatus=3 5
ProtectSystem=strict
ProtectHome=tmpfs
BindReadOnlyPaths=${CODE} ${VENV_DIR}${BOOK_DIRS}
BindPaths=${STATE}/${LOCK_NAME}
ReadWritePaths=${FEED}
ReadOnlyPaths=${FEED}/requests
InaccessiblePaths=${hidden}
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
PrivateTmp=yes
PrivateDevices=yes
ProtectProc=invisible
ProcSubset=pid
NoNewPrivileges=yes
CapabilityBoundingSet=
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
LockPersonality=yes
MemoryMax=200M
Nice=10
TimeoutStartSec=6000
StandardOutput=append:${LOGS}/feed-$1.out.log
StandardError=append:${LOGS}/feed-$1.err.log
UNIT
}

timer() {
  # $1 phase, $2.. OnCalendar lines
  ph="$1"; shift
  {
    echo "# quantt-twin-${ph}.timer : New York wall-clock time. Persistent=false: a missed run is not replayed."
    echo "[Unit]"; echo "Description=QUANTT IBKR twin ${ph} schedule"; echo; echo "[Timer]"
    for c in "$@"; do echo "OnCalendar=${c}"; done
    echo "AccuracySec=1s"; echo "Persistent=false"; echo "Unit=quantt-twin-${ph}.service"
    echo; echo "[Install]"; echo "WantedBy=timers.target"
  } | unit_file "quantt-twin-${ph}.timer"
}

write_units() {
  step "systemd units (DRY_RUN=1 in every twin job unit)"
  secret_service quantt-ibgw-secret.service quantt-ibgw "${LOGIN_RUN}/login.env" \
    --secret ibkr-paper-username=IBKR_PAPER_USERNAME --secret ibkr-paper-password=IBKR_PAPER_PASSWORD
  secret_service quantt-twin-secret.service quantt-twin "${TWIN_RUN}/ibkr.env" \
    --secret ibkr-paper-account-id=QUANTT_IBKR_ACCOUNT
  unit_file quantt-ibgw-guard.service <<UNIT
# quantt-ibgw-guard.service : THE GUARD (header). Only ${RUN_USER} may connect to the Gateway's API ports.
# WRITTEN by quantt/deploy/install_twin_vm.sh; the rules are ${GUARD_NFT}. Stopping it stops the Gateway.
[Unit]
Description=QUANTT IB Gateway API guard (nftables; ${TAG})
Before=quantt-ibgw.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=${NFT_BIN} -f ${GUARD_NFT}
ExecStop=${NFT_BIN} delete table inet ${GUARD_TABLE}

[Install]
WantedBy=multi-user.target
UNIT
  unit_file quantt-ibgw.service <<UNIT
# quantt-ibgw.service : Xvfb + IBC + the IB Gateway ${GW_VERSION} (paper), as ${RUN_USER}. ${TAG}.
# WRITTEN by quantt/deploy/install_twin_vm.sh. The IBC config holding the paper password is generated
# into ${IBC_RUN} (tmpfs, 0700) at every start and removed with the directory at every stop.
[Unit]
Description=QUANTT IB Gateway (paper) under Xvfb and IBC (${TAG})
Wants=network-online.target quantt-ibgw-secret.service
Requires=quantt-ibgw-guard.service
After=network-online.target quantt-ibgw-secret.service quantt-ibgw-guard.service

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_USER}
RuntimeDirectory=quantt-ibgw-ibc
RuntimeDirectoryMode=0700
WorkingDirectory=${JTS}
Environment=HOME=${RUN_HOME}
ExecStartPre=/usr/bin/python3 -I -B ${BIN}/ibc_config.py --login-env ${LOGIN_RUN}/login.env --out ${IBC_RUN}/config.ini --api-port ${GW_PORT} --order-precautions ${PRECAUTIONS}
ExecStart=/bin/sh ${BIN}/ibgw_run.sh ${GW_MAJOR} ${JTS} ${IBC_DIR} ${IBC_RUN}/config.ini
Restart=on-failure
RestartSec=300
MemoryHigh=${MEM_HIGH}
MemoryMax=${MEM_MAX}
OOMScoreAdjust=900
StandardOutput=append:${LOGS}/ibgw.out.log
StandardError=append:${LOGS}/ibgw.err.log

[Install]
WantedBy=multi-user.target
UNIT
  unit_file quantt-ibgw-vnc.service <<UNIT
# quantt-ibgw-vnc.service : ON DEMAND ONLY (never enabled). x11vnc on 127.0.0.1:5947 to the Gateway's
# display, for a person who reaches it through ssh -L when IBC cannot log in. -once: it exits after
# the first viewer leaves; -timeout 900: or after 15 minutes with no viewer. Any local user can reach a
# loopback port while it runs, which is why it runs only while someone is logging in.
[Unit]
Description=QUANTT IB Gateway VNC on 127.0.0.1 (on demand)
Requires=quantt-ibgw.service
After=quantt-ibgw.service

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_USER}
ExecStart=/usr/bin/x11vnc -display :47 -localhost -rfbport 5947 -once -timeout 900 -nopw -noxdamage -quiet
StandardOutput=append:${LOGS}/vnc.out.log
StandardError=append:${LOGS}/vnc.err.log
UNIT
  set -- ${IDS}
  job_service send "$1" "SuccessExitStatus=3 5 10" "send"
  job_service verify "$2" "# verify exits 0 PASS or 1 FAIL; a FAIL shows as a failed unit" "verify"
  job_service probe "$3" "# probe exits 0 logged in, 2 logged out (shown failed, on purpose)" "probe"
  FEED_HIDDEN="$(feed_hidden)"
  feed_service close after-close "$4"
  feed_service evening evening "$4"
  timer send "Mon..Fri *-*-* 12:30:00" "Mon..Fri *-*-* 12:40:00" "Mon..Fri *-*-* 15:30:00" "Mon..Fri *-*-* 15:40:00"
  timer verify "Mon..Fri *-*-* 17:45:00"
  timer probe "Mon..Fri *-*-* 09:00:00" "Mon..Fri *-*-* 12:00:00" "Mon..Fri *-*-* 15:15:00" "Sun *-*-* 19:30:00"
  # B10: after the close (13:20 runs on a 13:00 close, 16:20 on a 16:00 close; the runner idles the other),
  # and once in the evening, after the shadow runner's 18:50 run has written its requests.
  timer feed-close "Mon..Fri *-*-* 13:20:00" "Mon..Fri *-*-* 16:20:00"
  timer feed-evening "Mon..Fri *-*-* 20:20:00"
  for u in ${JOB_SERVICES}; do
    n="$(grep -c '^Environment=DRY_RUN=1$' "${UNIT_DIR}/${u}")" || true
    [ "${n}" = "1" ] || die "${UNIT_DIR}/${u} does not carry exactly one Environment=DRY_RUN=1"
    if [ -n "${STAGING}" ]; then
      grep -q '^ExecStart=/usr/bin/env DRY_RUN=1 QUANTT_TWIN_STAGING=1 ' "${UNIT_DIR}/${u}" \
        || die "${UNIT_DIR}/${u}: staging must force DRY_RUN=1 and QUANTT_TWIN_STAGING=1 on its command line"
    fi
  done
  for t in ${JOB_TIMERS}; do
    for c in $(grep '^OnCalendar=' "${UNIT_DIR}/${t}" | sed 's/^OnCalendar=//; s/ /_/g'); do
      systemd-analyze calendar "$(echo "${c}" | tr '_' ' ')" >/dev/null || die "${t}: systemd rejects OnCalendar ${c}"
    done
  done
}

enable_units() {
  step "load and enable (the timers run DRY; the Gateway starts and IBC logs in)"
  # shellcheck disable=SC2086
  systemctl stop ${JOB_TIMERS} 2>/dev/null || true
  systemctl daemon-reload
  systemctl enable quantt-ibgw-secret.service quantt-twin-secret.service quantt-ibgw-guard.service quantt-ibgw.service >/dev/null
  systemctl restart quantt-ibgw-guard.service || die "quantt-ibgw-guard.service failed: the Gateway does not start without THE GUARD"
  systemctl restart quantt-ibgw-secret.service || die "quantt-ibgw-secret.service failed; read ${LOGS}/quantt-ibgw-secret.err.log (names only)"
  systemctl restart quantt-twin-secret.service || die "quantt-twin-secret.service failed; read ${LOGS}/quantt-twin-secret.err.log"
  systemctl restart quantt-ibgw.service || die "quantt-ibgw.service failed to start; read ${LOGS}/ibgw.err.log"
  # shellcheck disable=SC2086
  systemctl enable --now ${JOB_TIMERS} >/dev/null
}

check_listeners() {
  step "nothing the Gateway runs listens beyond loopback"
  sleep 20
  bad="$(ss -ltnH 2>/dev/null | awk '{print $4}' | grep -E ':(4001|4002|7496|7497|5947)$' | grep -vE '^(127\.0\.0\.1|\[::1\]):' || true)"
  [ -z "${bad}" ] || die "a Gateway or VNC port listens beyond loopback: ${bad}. Stop quantt-ibgw.service and fix the Gateway's API settings (docs/RUNBOOK.md §9.3)"
  ss -ltnH 2>/dev/null | awk '{print $4}' | grep -E ':(4002|7497)$' && echo "   the API port is open on loopback (logged in)" \
    || echo "   the API port is not open yet: the Gateway is starting or IBC could not log in (read ${LOGS}/ibgw.out.log; then: sudo -u quantt ... quantt.twin probe)"
}

as_reader() { runuser -u "${SHADOW_USER}" -- "$@"; }

guard_count() {
  "${NFT_BIN}" list table inet "${GUARD_TABLE}" \
    | awk '/dport/ && /skuid !=/ {for (i = 1; i < NF; i++) if ($i == "packets") s += $(i + 1)} END {print s + 0}'
}

check_feed_and_guard() {
  step "B10: the feed's access both ways, and THE GUARD"
  [ "$(stat -c '%U:%G %a' "${FEED}")" = "${RUN_USER}:${SHADOW_USER} 2750" ] || die "${FEED} is $(stat -c '%U:%G %a' "${FEED}")"
  [ "$(stat -c '%U:%G %a' "${FEED}/requests")" = "${SHADOW_USER}:${RUN_USER} 2750" ] || die "${FEED}/requests is $(stat -c '%U:%G %a' "${FEED}/requests")"
  as_reader test -r "${FEED}" && as_reader test -x "${FEED}" || die "${SHADOW_USER} cannot read ${FEED}"
  if as_reader test -w "${FEED}"; then die "${SHADOW_USER} can WRITE ${FEED}"; fi
  as_reader test -w "${FEED}/requests" || die "${SHADOW_USER} cannot write ${FEED}/requests"
  as_quantt test -r "${FEED}/requests" && as_quantt test -x "${FEED}/requests" || die "${RUN_USER} cannot read ${FEED}/requests"
  if as_quantt test -w "${FEED}/requests"; then die "${RUN_USER} can write ${FEED}/requests (it must only read them)"; fi
  if as_reader test -x "${RUN_HOME}"; then die "${SHADOW_USER} can enter ${RUN_HOME}"; fi
  if as_reader test -x "${STATE}"; then die "${SHADOW_USER} can enter the twin's state ${STATE}"; fi
  "${NFT_BIN}" list table inet "${GUARD_TABLE}" >/dev/null || die "THE GUARD's table is not loaded; stop quantt-ibgw.service"
  before="$(guard_count)"
  as_reader /usr/bin/python3 -I -c 'import socket, sys
s = socket.socket(); s.settimeout(3)
sys.exit(0 if s.connect_ex((sys.argv[1], int(sys.argv[2]))) else 1)' "${GW_HOST}" "${GW_PORT}" \
    || die "${SHADOW_USER} OPENED a connection to the Gateway's API port ${GW_HOST}:${GW_PORT}. Stop quantt-ibgw.service NOW and read ${GUARD_NFT}"
  after="$(guard_count)"
  [ "${after}" -gt "${before}" ] || die "the shadow user's connection failed, but not at THE GUARD (its counter stayed at ${before}): read ${GUARD_NFT}"
  echo "   ${SHADOW_USER}: reads ${FEED}, writes only ${FEED}/requests, and its connection to ${GW_HOST}:${GW_PORT} was refused by the guard"
}

summary() {
  cat <<DONE

IBKR twin installed (${TAG}). NOT ARMED: every twin job unit has DRY_RUN=1, no AUTO_ARMED was written$( [ -n "${STAGING}" ] && echo ", and STAGING forces DRY_RUN=1 and QUANTT_TWIN_STAGING=1: it can never send" ).
  state ${STATE}; code ${CODE}; Gateway ${GW_VERSION} (heap ${HEAP_MB} MB, MemoryMax ${MEM_MAX}); IBC ${IBC_VERSION}; order precautions: ${PRECAUTIONS}
  B10 feed: ${FEED} (read by ${SHADOW_USER}); timers 13:20/16:20 after-close and 20:20 evening; THE GUARD ${GUARD_NFT}

NEXT, BY HAND (docs/RUNBOOK.md §9):
 1. Read the login:     sudo tail -n 40 ${LOGS}/ibgw.out.log
 2. Probe (read-only):  sudo sh ${CODE}/quantt/deploy/vm/run_twin.sh $( [ -n "${STAGING}" ] && echo "--staging ${STAGING} --python ${PY} " )probe
 3. The epoch (once):   sudo sh ${CODE}/quantt/deploy/vm/run_twin.sh $( [ -n "${STAGING}" ] && echo "--staging ${STAGING} --python ${PY} " )epoch
 4. The dry check:      sudo sh ${CODE}/quantt/deploy/vm/run_twin.sh $( [ -n "${STAGING}" ] && echo "--staging ${STAGING} --python ${PY} " )send --dry --session <YYYY-MM-DD>
 5. The feed by hand:   sudo sh ${CODE}/quantt/deploy/vm/run_twin.sh $( [ -n "${STAGING}" ] && echo "--staging ${STAGING} --python ${PY} " )feed --slot intraday   (in a session, outside the twin's windows)
DONE
  systemctl list-timers 'quantt-twin-*' --no-pager || true
}

uninstall() {
  check_root_zone_window
  step "stop and remove the twin's units (state, downloads, Gateway and IBC files are kept)"
  for u in ${JOB_TIMERS}; do systemctl disable --now "${u}" 2>/dev/null || true; done
  for u in ${ALL_UNITS}; do systemctl stop "${u}" 2>/dev/null || true; systemctl disable "${u}" 2>/dev/null || true; done
  for u in ${ALL_UNITS}; do
    case "${u}" in quantt-twin-*|quantt-ibgw*) rm -f "${UNIT_DIR}/${u}" ;; *) die "internal: ${u}" ;; esac
  done
  systemctl daemon-reload
  echo "uninstalled. Nothing was sent or cancelled at IBKR; positions and orders there are unchanged."
}

main() {
  parse "$@"
  if [ "${MODE}" = "uninstall" ]; then uninstall; return 0; fi
  check_root_zone_window
  check_layout
  check_code_release
  install_gateway
  install_ibc
  install_bin
  make_state
  make_feed_dirs
  write_units
  enable_units
  check_listeners
  check_feed_and_guard
  summary
}

main "$@"
