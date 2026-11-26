#!/bin/sh
# The IB Gateway under Xvfb and IBC, as user quantt: quantt-ibgw.service's ExecStart (PAPER ONLY).
#
#   ibgw_run.sh <gateway major version> <Jts dir> <IBC dir> <IBC config.ini under /run>
#
# WRITTEN BY HAND, RUN BY systemd. install_twin_vm.sh copies this file to
# /opt/quantt-ibgw/bin/ibgw_run.sh (root-owned) so the unit never runs a file its own user can edit.
#
# WHAT IT DOES. Starts a virtual display (Xvfb, no TCP listener), then hands the process to IBC's
# ibcstart.sh, which starts the Gateway and fills its login dialog from config.ini. config.ini was
# written into tmpfs by quantt.deploy.ibc_config a moment earlier (ExecStartPre); it holds the
# paper password and is never on persistent disk. THE CREDENTIALS ARE NEVER ARGUMENTS: ibcstart.sh
# accepts --user= and --pw=, which `ps` shows to every user, so neither is passed.
#
# THE DISPLAY IS ITS OWN (final review, 2026-11-25). A user who can open the Gateway's X display can
# drive its GUI, which can send orders. Xvfb gets -nolisten tcp AND -nolisten local (on Linux the
# "local" transport is the ABSTRACT socket @/tmp/.X11-unix/X47, which file permissions and PrivateTmp do
# not cover), and -auth with an MIT-MAGIC-COOKIE generated at every start into the unit's own tmpfs
# directory (0700, quantt; the file 0600). IBC, the Gateway and the on-demand x11vnc get XAUTHORITY.
# The file socket /tmp/.X11-unix/X47 still exists, and without the cookie the server refuses the
# connection; install_twin_vm.sh proves both as quantt-shadow (ibgw_check_display.py).
# NOTHING LISTENS BEYOND THIS MACHINE. Xvfb gets -nolisten tcp. The Gateway's API port is the paper
# port on loopback (the Gateway trusts 127.0.0.1; IBC rejects other incoming connections). VNC is
# NOT started here: quantt-ibgw-vnc.service starts x11vnc on 127.0.0.1 on demand, for a person to
# reach through `ssh -L` when IBC cannot log in (a 2FA prompt, a changed dialog).
#
# MEMORY. The Gateway's JVM heap is set by -Xmx in its ibgateway.vmoptions (the installer writes
# it); the unit's MemoryHigh/MemoryMax and OOMScoreAdjust make the Gateway, never an Alpaca
# runner, the process the kernel stops first (install_twin_vm.sh, MEMORY).
set -eu

[ $# -eq 4 ] || { echo "usage: $0 <major> <jts dir> <ibc dir> <config.ini>" >&2; exit 2; }
MAJOR="$1"; JTS="$2"; IBC="$3"; INI="$4"
case "${INI}" in
  /run/*) ;;
  *) echo "REFUSED: ${INI} is not under /run; the IBC config holds the paper password and lives in tmpfs only" >&2; exit 2 ;;
esac
[ -r "${INI}" ] || { echo "REFUSED: ${INI} is not readable (did ExecStartPre run?)" >&2; exit 2; }
[ -d "${JTS}/ibgateway/${MAJOR}/jars" ] || { echo "REFUSED: no Gateway ${MAJOR} under ${JTS}/ibgateway" >&2; exit 2; }
[ -x "${IBC}/scripts/ibcstart.sh" ] || { echo "REFUSED: no executable ${IBC}/scripts/ibcstart.sh" >&2; exit 2; }
# THE GATEWAY'S OWN JRE, BY PATH (staging, 2026-11-26). Without --java-path, IBC 3.24.2's ibcstart.sh
# reads .install4j/pref_jre.cfg, then inst_jre.cfg, and only then the installation's jre/. install4j
# wrote inst_jre.cfg during the unattended install with the TEMPORARY JRE it unpacked under /tmp
# (/tmp/ibgateway-<version>-linux-arm.sh.<pid>.dir/jre): the VM's "Could not find .../jre/bin/java"
# line. ibcstart.sh then fell through to jre/, but /tmp is writable by every user, so anyone who made
# that path would have chosen the java the Gateway runs. --java-path skips both files.
JAVA_BIN="${JTS}/ibgateway/${MAJOR}/jre/bin"
[ -x "${JAVA_BIN}/java" ] || { echo "REFUSED: no executable ${JAVA_BIN}/java (the Gateway's bundled JRE)" >&2; exit 2; }

DISPLAY_NUM=":47"
RUNDIR="$(dirname "${INI}")"                   # the unit's RuntimeDirectory: tmpfs, 0700, quantt
XAUTH="${RUNDIR}/Xauthority"
umask 077
rm -f "${XAUTH}"
: > "${XAUTH}"
chmod 600 "${XAUTH}"
COOKIE="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
[ "${#COOKIE}" -eq 32 ] || { echo "REFUSED: could not make the display cookie" >&2; exit 3; }
# The cookie goes to xauth on its standard input (`source -`), never as an argument: another user can
# read a process's arguments in /proc while it runs; `printf` is a shell builtin and has none.
printf 'add %s MIT-MAGIC-COOKIE-1 %s\n' "${DISPLAY_NUM}" "${COOKIE}" | xauth -q -f "${XAUTH}" source - \
  || { echo "REFUSED: xauth could not write ${XAUTH}" >&2; exit 3; }
unset COOKIE
export XAUTHORITY="${XAUTH}"
Xvfb "${DISPLAY_NUM}" -auth "${XAUTH}" -nolisten tcp -nolisten local -screen 0 1024x768x16 &
XVFB_PID=$!
i=0
while [ ! -e "/tmp/.X11-unix/X47" ] && [ "${i}" -lt 30 ]; do
  sleep 1; i=$((i + 1))
done
kill -0 "${XVFB_PID}" 2>/dev/null || { echo "REFUSED: Xvfb did not start" >&2; exit 3; }
export DISPLAY="${DISPLAY_NUM}"

# --on2fatimeout=exit: a two-factor prompt nobody answers ends the run; systemd restarts it later
# (Restart=on-failure, RestartSec), and meanwhile the twin's probe reads "logged out".
exec "${IBC}/scripts/ibcstart.sh" "${MAJOR}" --gateway --mode=paper \
  "--tws-path=${JTS}" "--tws-settings-path=${JTS}" "--ibc-path=${IBC}" "--ibc-ini=${INI}" \
  "--java-path=${JAVA_BIN}" \
  --on2fatimeout=exit
