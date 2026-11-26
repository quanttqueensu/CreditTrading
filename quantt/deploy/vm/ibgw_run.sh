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

DISPLAY_NUM=":47"
Xvfb "${DISPLAY_NUM}" -nolisten tcp -screen 0 1024x768x16 &
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
  --on2fatimeout=exit
