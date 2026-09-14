#!/bin/bash
# Repo cleanup, staged 2026-09-10 from a four-agent audit.
#
#   bash ops/cleanup_20260910.sh              # DRY RUN — prints, deletes nothing
#   bash ops/cleanup_20260910.sh --commit     # actually delete
#
# READ THIS FIRST
# ---------------
# data/ is GITIGNORED (.gitignore:11). Nothing under data/ is recoverable from
# git history. Every deletion below is PERMANENT. results/ and ops/ are tracked
# and therefore recoverable.
#
# Each entry was verified to have ZERO inbound references across src/, scripts/,
# ops/, dashboard/ and docs/, and to not be the sole evidence behind any number
# cited in docs/RESEARCH_STATE.md or results/*.md.
#
# NOT INCLUDED, DELIBERATELY:
#   data/forced_flow2/  (3.02 GB) — the TRACE bond-day panel is LICENSED and
#   non-reconstructible (docs/INFRASTRUCTURE.md:68 lists it as one of two
#   datasets that must be copied from the team lead). It is 238 days stale and
#   no active prompt touches it, so it should be MOVED to cold storage — not
#   deleted. Do that by hand, with a README saying who holds the licensed copy.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMIT="${1:-}"
[ "$COMMIT" = "--commit" ] && DO=1 || DO=0
[ $DO -eq 1 ] && echo "=== COMMITTING ===" || echo "=== DRY RUN (add --commit to delete) ==="

say() { if [ -e "$1" ]; then
          sz=$(du -sh "$1" 2>/dev/null | cut -f1)
          echo "  ${2}: $1 ($sz)"
          [ $DO -eq 1 ] && rm -rf "$1"
        fi; }

echo
echo "--- confirmed duplicates ---"
# 389,135 rows identical to marks_SPY.parquet except 129 px values at 5.7e-14
say data/vrp/marks_SPY_full.parquet "duplicate"
# same 5,832 x 16 as vrp_series.parquet; the CSV has zero references
say data/vrp/vrp_series.csv "duplicate"

echo
echo "--- gitignored build caches (.gitignore: results/**/_cache_*) ---"
for f in results/s3/_cache_*.parquet; do say "$f" "cache"; done

echo
echo "--- refetchable raw (0 refs; parsed product ishares_nav_daily.parquet is current) ---"
say data/holdings/raw_nav "refetchable"

echo
echo "--- legacy eras, zero references ---"
say data/interim "E2 era, 10 files, 0 refs"
say data/structural_stack "DISP era, 0 refs"
say data/dispersion_staged "DISP era, 0 refs"
say data/trace_month_end_prices.parquet "superseded twice"
for f in data/event_confirmation_17g7.parquet data/event_equity_screen.parquet \
         data/lqd_daily.parquet data/capacity_adv.parquet data/permno_map.csv \
         data/trace_price_coverage.csv data/fallen_angel_filter_attrition.csv \
         data/vrp/c2a_prices.parquet; do say "$f" "orphan"; done

echo
echo "--- empty legacy stub directories under ops/books ---"
for d in bench_b1_hyg bench_b3_agg bench_b4_60_40 bench_b5_shy bench_b6_ew_credit \
         cef_discount credit_rv null_trader phase0_preflight; do
  p="ops/books/$d"
  if [ -d "$p" ] && [ -z "$(ls -A "$p" 2>/dev/null)" ]; then
    echo "  empty stub: $p"
    [ $DO -eq 1 ] && rmdir "$p"
  fi
done

echo
echo "--- NOT deleted, review by hand ---"
echo "  data/forced_flow2/   3.02 GB  LICENSED, non-reconstructible -> move to cold storage"
echo "  data/forced_flow/    53 MB    v1 era; 9 files still referenced, rest is 0-ref"
echo "  data/holdings/nport_raw/  12 MB  SEC-refetchable but slow; cited in RESEARCH_STATE"

echo
if [ $DO -eq 1 ]; then
  echo "=== verifying the live inputs still load ==="
  python3 - <<'PY'
import pandas as pd
for f in ['data/cef/cef_prices.parquet','data/cef/cef_nav.parquet',
          'data/vrp/marks_SPY.parquet','data/holdings/ishares_nav_daily.parquet']:
    try: print(f"  ok {f}: {len(pd.read_parquet(f)):,} rows")
    except Exception as e: print(f"  FAIL {f}: {e}")
PY
fi
