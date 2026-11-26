#!/bin/sh
# Refuse unless the ONE port filter (nftables table inet quantt_ibgw) is loaded with its rules.
#
#   ibgw_check_firewall.sh <quantt uid> <shadow uid> [--prove <host> <port>] [--status]
#
#   --prove   also show a live connection to the Gateway as quantt-shadow is refused BY THE FILTER
#             (its counter moves): B10's install-time proof
#   --status  also write the verdict, {"in_force", "detail", "checked_utc"}, to
#             /run/quantt-ibgw-status/firewall.json: the probe's record of the filter (final review 3).
#             ROOT WRITES ONLY WHERE ROOT ALONE CAN (final check, 2026-11-25): that directory is root's
#             (0755, under root's /run), the file is made by mktemp in it and renamed, and nothing is
#             chowned. A path in a directory quantt owns would let quantt plant a symlink (to
#             /etc/shadow, say) that root's write and chown would follow.
#
# Run as root: by bootstrap_ibgw.sh after loading it, by quantt-ibgw.service as `ExecStartPre=+` (the
# Gateway does not start without the filter; re-review N2), by the probe (`--status`), and by
# install_twin_vm.sh, which adds --prove once the Gateway is up. `nft` prints a set's elements in its
# own order, so each port is checked alone.
set -eu
usage() { echo "usage: $0 <quantt uid> <shadow uid> [--prove <host> <port>] [--status]" >&2; exit 2; }
STATUS_DIR="/run/quantt-ibgw-status"
[ $# -ge 2 ] || usage
UID_Q="$1"; UID_S="$2"; shift 2
PROVE_HOST=""; PROVE_PORT=""; STATUS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --prove) [ $# -ge 3 ] || usage; PROVE_HOST="$2"; PROVE_PORT="$3"; shift 3 ;;
    --status) STATUS=1; shift ;;
    *) usage ;;
  esac
done
record() {
  # $1 true|false, $2 detail (quotes and backslashes removed, so the JSON stays JSON)
  [ -n "${STATUS}" ] || return 0
  [ ! -L "${STATUS_DIR}" ] || { echo "REFUSED: ${STATUS_DIR} is a symlink" >&2; exit 3; }
  install -d -o root -g root -m 755 "${STATUS_DIR}"
  [ "$(stat -c '%u %a %F' "${STATUS_DIR}")" = "0 755 directory" ] \
    || { echo "REFUSED: ${STATUS_DIR} is not root's 0755 directory" >&2; exit 3; }
  d="$(printf '%s' "$2" | tr -d '"\\')"
  tmp="$(mktemp "${STATUS_DIR}/firewall.XXXXXX")"
  printf '{"in_force": %s, "detail": "%s", "checked_utc": "%s"}\n' "$1" "${d}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${tmp}"
  chmod 644 "${tmp}"
  mv -f "${tmp}" "${STATUS_DIR}/firewall.json"
}
fail() { record false "$*"; echo "REFUSED: the port filter is not in force: $*" >&2; exit 3; }
out="$(nft list chain inet quantt_ibgw output 2>/dev/null)" || fail "no chain inet quantt_ibgw output (run bootstrap_ibgw.sh)"
gate="$(nft list chain inet quantt_ibgw gate 2>/dev/null)" || fail "no chain inet quantt_ibgw gate"
echo "${out}" | grep -q 'hook output' || fail "the chain is not on the output hook"
line="$(echo "${out}" | grep 'jump gate' || true)"
[ -n "${line}" ] || fail "the output hook does not jump to the gate"
for port in 4001 4002 7496 7497 5947; do
  echo "${line}" | grep -q "${port}" || fail "port ${port} is not sent to the gate"
done
echo "${out}" | grep "meta skuid ${UID_S}" | grep 'reject with tcp reset' | grep -q '53' \
  || fail "no rule refusing the shadow user (uid ${UID_S}) every loopback TCP port but DNS"
echo "${gate}" | grep -q "meta skuid ${UID_Q} accept" || fail "no accept rule for uid ${UID_Q}"
[ "$(echo "${gate}" | grep -c 'reject with tcp reset')" -ge 2 ] || fail "the reject rules are missing"
for port in 4001 4002 7496 7497; do
  echo "${gate}" | grep 'reject with tcp reset' | grep -q "${port}" || fail "API port ${port} is not rejected for other users"
done
echo "${gate}" | grep 'reject with tcp reset' | grep -q '5947' || fail "the VNC port is not rejected for other users"

if [ -n "${PROVE_HOST}" ]; then
  host="${PROVE_HOST}"; port="${PROVE_PORT}"
  shadow="$(getent passwd "${UID_S}" | cut -d: -f1)"
  [ -n "${shadow}" ] || fail "no user with uid ${UID_S}"
  count() { nft list table inet quantt_ibgw | awk '/reject/ {for (i = 1; i < NF; i++) if ($i == "packets") s += $(i + 1)} END {print s + 0}'; }
  before="$(count)"
  runuser -u "${shadow}" -- /usr/bin/python3 -I -c 'import socket, sys
s = socket.socket(); s.settimeout(3)
sys.exit(0 if s.connect_ex((sys.argv[1], int(sys.argv[2]))) else 1)' "${host}" "${port}" \
    || fail "${shadow} OPENED a connection to ${host}:${port}. Stop quantt-ibgw.service NOW"
  after="$(count)"
  [ "${after}" -gt "${before}" ] || fail "${shadow}'s connection failed, but not at the filter (its counters stayed at ${before})"
  echo "proved: ${shadow}'s connection to ${host}:${port} was refused by the filter (counters ${before} -> ${after})"
fi
record true "in force: accept uid ${UID_Q}, reject the rest, shadow uid ${UID_S} refused but DNS"
echo "port filter in force (uid ${UID_Q}; shadow uid ${UID_S} refused)"
