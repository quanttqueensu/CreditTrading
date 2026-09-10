#!/bin/bash
# One-way copy of PROD's data panels into a DEV checkout, so research reads
# what the sleeve traded on and can never write to it.
#
#   ~/prod/QUANTT/ops/sync_dev_data.sh /Users/simonjarvis/Desktop/2027/QUANTT/2027
#
# rsync --delete: dev's data/ becomes an exact mirror. Anything a research
# script wrote into dev's data/ is REMOVED on the next sync -- by design.
# Research output belongs in results/. ~3.9 GB; incremental after the first.
set -uo pipefail
PROD="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV="${1:?usage: sync_dev_data.sh <dev repo path>}"
[ -d "$DEV/ops" ] || { echo "not a repo checkout: $DEV"; exit 2; }
[ "$(cd "$DEV" && pwd)" != "$PROD" ] || { echo "refusing: dev is prod"; exit 2; }
rsync -a --delete --info=stats1 "$PROD/data/" "$DEV/data/"
echo "[$(date '+%F %T')] dev data <- prod ($PROD/data)"
