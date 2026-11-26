#!/bin/sh
# Run one twin command BY HAND on the VM, as user quantt, with the installed units' environment and
# DRY_RUN=1 ALWAYS (CLAUDE.md order-path rules 1 and 4).
#
#   sudo sh run_twin.sh probe                              read the account (read-only)
#   sudo sh run_twin.sh epoch                              once: seed the ledger
#   sudo sh run_twin.sh send --dry [--session D]           everything but the transmission, any day
#   sudo sh run_twin.sh approve --sha <plan_sha>           the team lead's per-day approval
#   sudo sh run_twin.sh verify | compare [--aggregates] | cancel-open (list only)
#   sudo sh run_twin.sh --staging <dir> --python <py> <command ...>   the same against a staging install
#
# It refuses a bare `send` (orders go only from quantt-twin-send.service, armed by the team lead) and
# `cancel-open --confirm` (a cancel is the team lead's own command, with DRY_RUN=0 typed by hand:
# docs/RUNBOOK.md §9.6). It cannot transmit: it sets DRY_RUN=1, and the twin sends only on exactly 0.
set -eu

RUN_USER="quantt"
RUN_HOME="/home/${RUN_USER}"
STATE_ROOT="${RUN_HOME}/quantt_state"
CODE="${RUN_HOME}/prod/quantt-alpaca"
PY="${RUN_HOME}/venv/bin/python"
STATE="${STATE_ROOT}/twin"
STAGE_ENV=""
die() { echo "REFUSED: $*" >&2; exit 2; }

[ "$(id -u)" -eq 0 ] || die "run as root (sudo); it switches to ${RUN_USER} itself"
if [ "${1:-}" = "--staging" ]; then
  [ $# -ge 4 ] && [ "$3" = "--python" ] || die "usage: --staging <dir> --python <py> <command>"
  CODE="$2"; PY="$4"; STATE="$(dirname "$2")/state/twin"; STAGE_ENV="QUANTT_TWIN_STAGING=1"; shift 4
fi
[ $# -ge 1 ] || die "usage: sudo sh $0 probe|epoch|send --dry|approve|verify|compare|cancel-open"
case "$1" in
  probe|epoch|approve|verify|compare) ;;
  send)
    dry=0; for a in "$@"; do [ "${a}" = "--dry" ] && dry=1; done
    [ "${dry}" -eq 1 ] || die "a hand-run send is not offered; use 'send --dry'. Orders go only from quantt-twin-send.service"
    ;;
  cancel-open)
    for a in "$@"; do [ "${a}" = "--confirm" ] && die "cancel-open --confirm is the team lead's own command (docs/RUNBOOK.md §9.6)"; done
    ;;
  *) die "unknown command '$1'" ;;
esac
[ -d "${STATE}" ] || die "${STATE} does not exist; run install_twin_vm.sh first"
[ -f /run/quantt-twin/ibkr.env ] || die "/run/quantt-twin/ibkr.env is absent: sudo systemctl start quantt-twin-secret.service"
cd "${CODE}"
# The books' state directories, by the twin's own table (quantt/twin/books.py BOOKS).
BOOK_ENV=""
for pair in $(runuser -u "${RUN_USER}" -- "${PY}" -B -c 'from quantt.twin.books import BOOKS; print(" ".join(b.state_env + "=" + b.name for b in BOOKS))'); do
  BOOK_ENV="${BOOK_ENV} ${pair%%=*}=${STATE_ROOT}/${pair#*=}"
done
[ -n "${BOOK_ENV}" ] || die "cannot read the twin's book table from ${CODE}"
# The account id comes from the tmpfs file into this one process's environment, never a command line.
# shellcheck disable=SC2086
exec runuser -u "${RUN_USER}" -- sh -c '
  set -a; . /run/quantt-twin/ibkr.env; set +a
  exec "$@"' sh env HOME="${RUN_HOME}" DRY_RUN=1 ${STAGE_ENV} \
  QUANTT_STATE_DIR="${STATE}" ${BOOK_ENV} QUANTT_ENV_FILE=/run/quantt/alpaca.env \
  QUANTT_TWIN_ALPACA_DATA_BOOK=cef QUANTT_IBKR_HOST=127.0.0.1 QUANTT_IBKR_PORT=4002 QUANTT_IBKR_CLIENT_ID=39 \
  PYTHONUNBUFFERED=1 "${PY}" -B -m quantt.twin "$@"
