#!/bin/sh
# Refuse unless the twin's port filter (nftables table inet quantt_ibgw) is loaded with its rules.
#
#   ibgw_check_firewall.sh <quantt uid>
#
# Run as root: by quantt-ibgw.service as `ExecStartPre=+` (the Gateway does not start without the
# filter; re-review N2), and by install_twin_vm.sh before it writes a unit (re-review 4). It checks
# the ACCEPT rule for quantt AND both REJECT rules, and that the output hook sends every one of the
# three ports to them; `nft` prints a set's elements in its own order, so each port is checked alone.
set -eu
[ $# -eq 1 ] || { echo "usage: $0 <quantt uid>" >&2; exit 2; }
UID_Q="$1"
fail() { echo "REFUSED: the port filter is not in force: $*" >&2; exit 3; }
out="$(nft list chain inet quantt_ibgw output 2>/dev/null)" || fail "no chain inet quantt_ibgw output (run bootstrap_ibgw.sh)"
gate="$(nft list chain inet quantt_ibgw gate 2>/dev/null)" || fail "no chain inet quantt_ibgw gate"
line="$(echo "${out}" | grep 'jump gate' || true)"
[ -n "${line}" ] || fail "the output hook does not jump to the gate"
for port in 4002 7497 5947; do
  echo "${line}" | grep -q "${port}" || fail "port ${port} is not sent to the gate"
done
echo "${out}" | grep -q 'hook output' || fail "the chain is not on the output hook"
echo "${gate}" | grep -q "meta skuid ${UID_Q} accept" || fail "no accept rule for uid ${UID_Q}"
[ "$(echo "${gate}" | grep -c 'reject with tcp reset')" -ge 2 ] || fail "the reject rules are missing"
echo "${gate}" | grep 'reject with tcp reset' | grep -q '4002' || fail "the API ports are not rejected for other users"
echo "${gate}" | grep 'reject with tcp reset' | grep -q '5947' || fail "the VNC port is not rejected for other users"
echo "port filter in force (uid ${UID_Q})"
