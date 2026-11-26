#!/bin/sh
# The system packages the twin's IB Gateway needs on the prod VM. THE TEAM LEAD RUNS IT (sudo):
#
#   sudo sh bootstrap_ibgw.sh
#
# Agents never run sudo (CLAUDE.md; docs/RUNBOOK.md §9.1). Safe to repeat: every step checks first.
#
# WHAT IT INSTALLS, AND WHY EACH
#   xvfb, x11vnc       the Gateway has a GUI and IBKR supports no headless mode (October §2.9 [V]);
#                      Xvfb is its display, x11vnc the on-demand fallback login (127.0.0.1 only).
#                      Pinned to the versions apt offered on this VM on 2026-11-25 (coordinator's
#                      read): a different candidate refuses, naming it, rather than install an
#                      unread version.
#   unzip              to unpack the pinned IBC release.
#   libxtst6 libxi6 libxrender1 fontconfig fonts-dejavu-core
#                      the X libraries and a font set a Java GUI needs to draw under Xvfb [S: the
#                      usual set for Java AWT on a minimal Ubuntu]; not pinned (not read).
#   NO JAVA. The standalone Gateway installer bundles its own JRE: its archive holds jre.tar.gz and
#                      its parameters name JRE 25.0.5.0.3 [V: read from the installer of 2026-11-25,
#                      sha256 1352b9f1..., without running it], and IBC's ibcstart.sh uses the
#                      Gateway's own JRE first (its "Determine the location of java" block).
#
# SWAP. The VM already has a 2 GB /swapfile from quantt/deploy/vm/bootstrap.sh (73 MB used on
# 2026-11-25). This script CHECKS that swap is on and never creates a second file; with no swap at
# all it refuses and says to re-run bootstrap.sh's swap step.
set -eu

die() { echo "REFUSED: $*" >&2; exit 2; }
step() { echo "== $*"; }

XVFB_VERSION="2:21.1.12-1ubuntu1.9"
X11VNC_VERSION="0.9.16-10"
OTHERS="unzip libxtst6 libxi6 libxrender1 fontconfig fonts-dejavu-core"

[ "$(id -u)" -eq 0 ] || die "run as root (sudo)"
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
echo "done: Xvfb $(dpkg-query -W -f='${Version}' xvfb), x11vnc $(dpkg-query -W -f='${Version}' x11vnc)"
