#!/bin/bash
# Double-click this in Finder to open the dashboard.
#
# Safe to run twice: if the server is already up (started by hand or by the
# com.quantt.dashboard launchd agent) this just opens the browser at it rather
# than starting a second one and fighting over the port.
PORT=8787
REPO="/Users/simonjarvis/Desktop/2027/QUANTT/2027"
PY="/opt/anaconda3/bin/python3"

if nc -z 127.0.0.1 $PORT 2>/dev/null; then
  echo "Dashboard already running."
else
  echo "Starting dashboard…"
  cd "$REPO" || exit 1
  nohup "$PY" dashboard/server.py > "$REPO/dashboard/server.log" 2>&1 &
  for i in $(seq 1 30); do
    nc -z 127.0.0.1 $PORT 2>/dev/null && break
    sleep 0.5
  done
fi

if nc -z 127.0.0.1 $PORT 2>/dev/null; then
  open "http://127.0.0.1:$PORT"
  echo "Open at http://127.0.0.1:$PORT — you can close this window."
else
  echo "FAILED to start. Last 20 lines of dashboard/server.log:"
  tail -20 "$REPO/dashboard/server.log"
  echo; read -n 1 -s -r -p "Press any key to close…"
fi
