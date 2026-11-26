#!/bin/sh
# Refuse unless the ONE port filter (nftables table inet quantt_ibgw) is loaded with its rules.
#
#   ibgw_check_firewall.sh <quantt uid> <shadow uid>                      the rules are in force
#   ibgw_check_firewall.sh <quantt uid> <shadow uid> --prove <host> <port>   and a live connection to the
#                                                                         Gateway as quantt-shadow is
#                                                                         refused BY THE FILTER (its
#                                                                         counter moves): B10's proof
#
# Run as root: by bootstrap_ibgw.sh after loading it, by quantt-ibgw.service as `ExecStartPre=+` (the
# Gateway does not start without the filter; re-review N2), and by install_twin_vm.sh, which adds
# --prove once the Gateway is up. `nft` prints a set's elements in its own order, so each port is
# checked alone.
set -eu
[ $# -eq 2 ] || [ $# -eq 5 ] || { echo "usage: $0 <quantt uid> <shadow uid> [--prove <host> <port>]" >&2; exit 2; }
UID_Q="$1"; UID_S="$2"
fail() { echo "REFUSED: the port filter is not in force: $*" >&2; exit 3; }
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

if [ $# -eq 5 ]; then
  [ "$3" = "--prove" ] || { echo "usage: $0 <quantt uid> <shadow uid> [--prove <host> <port>]" >&2; exit 2; }
  host="$4"; port="$5"
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
echo "port filter in force (uid ${UID_Q}; shadow uid ${UID_S} refused)"
