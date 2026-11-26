#!/bin/sh
# The system packages and the port filter the twin's IB Gateway needs on the prod VM. THE TEAM LEAD
# RUNS IT (sudo):
#
#   sudo sh bootstrap_ibgw.sh --tree <the twin's code tree> --admin-user azureuser
#
# Agents never run sudo (CLAUDE.md; docs/RUNBOOK.md §9.2). Safe to repeat: every step checks first.
#
# WHAT IT INSTALLS, AND WHY EACH
#   xvfb, x11vnc       the Gateway has a GUI and IBKR supports no headless mode (October §2.9 [V]);
#                      Xvfb is its display, x11vnc the on-demand fallback login (127.0.0.1 only).
#                      Pinned to the versions apt offered on this VM on 2026-11-25 (coordinator's
#                      read): a different candidate refuses, naming it, rather than install an
#                      unread version.
#   unzip              to unpack the pinned IBC release.
#   nftables           the port filter below.
#   libxtst6 libxi6 libxrender1 fontconfig fonts-dejavu-core
#                      the X libraries and a font set a Java GUI needs to draw under Xvfb [S: the
#                      usual set for Java AWT on a minimal Ubuntu]; not pinned (not read).
#   NO JAVA. The standalone Gateway installer bundles its own JRE: its archive holds jre.tar.gz and
#                      its parameters name JRE 25.0.5.0.3 [V: read from the installer of 2026-11-25,
#                      sha256 1352b9f1..., without running it], and IBC's ibcstart.sh uses the
#                      Gateway's own JRE first (its "Determine the location of java" block).
#
# THE PORT FILTER (review of the build, finding 6). Loopback is open to every local user, so only
# uid quantt may connect to the paper API ports (4002, 7497), and quantt or the admin login user
# (ssh -L is opened by sshd as that user) to the VNC port 5947. The ruleset is rendered by
# quantt/deploy/ibgw_firewall.py into /etc/quantt/ibgw.nft and loaded at every boot, before the
# Gateway, by quantt-ibgw-firewall.service. install_twin_vm.sh refuses unless it is loaded.
#
# SWAP. The VM already has a 2 GB /swapfile from quantt/deploy/vm/bootstrap.sh (73 MB used on
# 2026-11-25). This script CHECKS that swap is on and never creates a second file; with no swap at
# all it refuses and says to re-run bootstrap.sh's swap step.
set -eu

die() { echo "REFUSED: $*" >&2; exit 2; }
step() { echo "== $*"; }

XVFB_VERSION="2:21.1.12-1ubuntu1.9"
X11VNC_VERSION="0.9.16-10"
OTHERS="unzip nftables libxtst6 libxi6 libxrender1 fontconfig fonts-dejavu-core"
NFT_FILE="/etc/quantt/ibgw.nft"
FW_UNIT="/etc/systemd/system/quantt-ibgw-firewall.service"
TREE=""; ADMIN=""

while [ $# -gt 0 ]; do
  case "$1" in
    --tree) TREE="$2"; shift 2 ;;
    --admin-user) ADMIN="$2"; shift 2 ;;
    *) die "unknown argument '$1'" ;;
  esac
done
[ "$(id -u)" -eq 0 ] || die "run as root (sudo)"
[ -n "${TREE}" ] && [ -f "${TREE}/quantt/deploy/ibgw_firewall.py" ] || die "--tree <the twin's code tree> holding quantt/deploy/ibgw_firewall.py is required"
[ -n "${ADMIN}" ] || die "--admin-user <the login user who reaches VNC through ssh -L> is required"
id -u quantt >/dev/null 2>&1 || die "user quantt does not exist"
id -u "${ADMIN}" >/dev/null 2>&1 || die "user ${ADMIN} does not exist"
[ "$(uname -m)" = "aarch64" ] || [ "$(uname -m)" = "x86_64" ] || die "unknown machine $(uname -m)"

step "swap"
if [ -z "$(swapon --show=NAME --noheadings)" ]; then
  die "no swap is active; run the swap step of quantt/deploy/vm/bootstrap.sh (2 GB /swapfile) first"
fi
swapon --show

step "apt candidates"
apt-get update -qq
for pair in "xvfb ${XVFB_VERSION}" "x11vnc ${X11VNC_VERSION}"; do
  set -- ${pair}
  cand="$(apt-cache policy "$1" | awk '/Candidate:/ {print $2}')"
  inst="$(dpkg-query -W -f='${Version}' "$1" 2>/dev/null || true)"
  if [ "${inst}" = "$2" ]; then echo "   $1 $2 installed"; continue; fi
  [ "${cand}" = "$2" ] || die "$1: apt's candidate is ${cand}, not the pinned $2; read the change, then update the pin in this script"
done

step "install"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q "xvfb=${XVFB_VERSION}" "x11vnc=${X11VNC_VERSION}" ${OTHERS}
command -v Xvfb >/dev/null || die "Xvfb is not on PATH after the install"
command -v x11vnc >/dev/null || die "x11vnc is not on PATH after the install"
command -v nft >/dev/null || die "nft is not on PATH after the install"

step "the port filter (${NFT_FILE}, loaded by quantt-ibgw-firewall.service at boot)"
install -d -o root -g root -m 755 /etc/quantt
python3 -I -B "${TREE}/quantt/deploy/ibgw_firewall.py" --quantt-uid "$(id -u quantt)" --admin-uid "$(id -u "${ADMIN}")" > "${NFT_FILE}.new"
nft -c -f "${NFT_FILE}.new" || die "nft rejects the rendered ruleset ${NFT_FILE}.new"
mv "${NFT_FILE}.new" "${NFT_FILE}"
chmod 644 "${NFT_FILE}"
cat > "${FW_UNIT}" <<UNIT
# quantt-ibgw-firewall.service : only uid quantt reaches the Gateway's API ports on loopback (and the
# admin user its VNC port). WRITTEN by quantt/deploy/vm/bootstrap_ibgw.sh; re-run it to change.
[Unit]
Description=QUANTT IB Gateway port filter (nftables table inet quantt_ibgw)
Before=quantt-ibgw.service
DefaultDependencies=no
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f ${NFT_FILE}
ExecStop=/usr/sbin/nft delete table inet quantt_ibgw

[Install]
WantedBy=multi-user.target
UNIT
chmod 644 "${FW_UNIT}"
systemctl daemon-reload
systemctl enable quantt-ibgw-firewall.service >/dev/null
systemctl restart quantt-ibgw-firewall.service
nft list table inet quantt_ibgw | grep -q "meta skuid $(id -u quantt) accept" || die "the quantt_ibgw table did not load"
echo "done: Xvfb $(dpkg-query -W -f='${Version}' xvfb), x11vnc $(dpkg-query -W -f='${Version}' x11vnc); port filter loaded"
