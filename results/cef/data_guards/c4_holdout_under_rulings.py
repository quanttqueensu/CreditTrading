"""REPORT-ONLY (zero trials; the holdout is NOT reopened): C4's holdout return assembly and book,
rebuilt on the guarded `yf_total_returns` under each recorded rulings file.

    python3 results/cef/data_guards/c4_holdout_under_rulings.py --cache <C4's _cache_c4 directory>

C4's `holdout()` refuses a second run (its marker exists), so this follows the review's
`results/cef/c4/holdout_review_2026-10-18/repro.py`: the same calls (`build_book`, `crsp_pivot`,
`igr_fill`, `yf_total_returns`, `band_gross_capped`, `check_held`, `evaluate`) in the same order. It
needs the gitignored C4 cache (CRSP returns, the Alpaca bars, the committed holdout P&L), which is
read and never written; it prints aggregates only (CRSP is licensed).
  * under `repro_bar_rulings.json` (book_as_is) it must reproduce the committed P&L exactly;
  * under `c4_bar_rulings_2026-10-19.json` (rebase; the verdict) it gives the corrected book.
Output: results/cef/data_guards/c4_holdout_under_rulings_output_2026-10-19.txt."""
import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True
import pandas as pd  # noqa: E402

from scripts.cef import band_frontier as bf  # noqa: E402
from scripts.cef import c4_families as c4  # noqa: E402
from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS, SPEC_ID  # noqa: E402

OUT = REPO / "results" / "cef" / "data_guards" / "c4_holdout_under_rulings_output_2026-10-19.txt"
RULINGS = {"book_as_is (repro_bar_rulings.json)": REPO / "results/cef/c4/holdout_review_2026-10-18/repro_bar_rulings.json",
           "rebase, the verdict (c4_bar_rulings_2026-10-19.json)": c4.BAR_RULINGS}


def main(cache: Path):
    c4.CACHE = cache
    c4.CRSP_RET = cache / "crsp_ret_families.parquet"
    c4.ALP_POOL = cache / "alpaca_bars_c4pool_2024-12-02_2026-09-30.parquet"
    c4.ALP_POOL_META = cache / "alpaca_bars_c4pool_2024-12-02_2026-09-30_meta.json"
    print(f"{SPEC_ID}; band {BAND_WIDTH}, gross cap {MAX_GROSS_STRESS}; C4 cache read from the --cache directory")
    U = c4.universes()
    UF, snap = U["frozen"], U["snap68"]
    px, _ = c4.load_panels(U["pool"])
    crsp = c4.crsp_returns(U["pool"])
    qr = c4.qqqx_rule(crsp, px)
    RT = pd.read_csv(c4.RESOLUTION_TABLE, parse_dates=["date"])
    excluded = json.loads(c4.EXCLUSIONS_A4.read_text())["excluded"]
    UH = [t for t in UF if t not in excluded]
    T = c4.build_book(UH)
    sess = T.index[T.index <= c4.HOLDOUT_END]
    cols = sorted(set(UF) | set(snap))
    yfa = pd.read_parquet(c4.FAM_DIR / "cef_actions.parquet")
    yfa["date"] = pd.to_datetime(yfa["date"])
    ruled = c4.ruled_actions(yfa, RT, excluded)
    com_act = pd.read_parquet(cache / "c4_holdout_actions_ruled_2026-10-18.parquet")
    print("ruled actions equal the committed cache:", ruled.reset_index(drop=True).equals(com_act.reset_index(drop=True)))
    cr = c4.crsp_pivot(crsp, cols, sess, qr, "ret", px=px)
    fill, _ = c4.igr_fill(c4.alpaca_pool(), px, sess)
    H = bf.band_gross_capped(T.loc[:c4.HOLDOUT_END], BAND_WIDTH, MAX_GROSS_STRESS)
    Pc = pd.read_parquet(cache / "c4_holdout_pnl_2026-10-18.parquet")["c4_holdout_gross_pnl"]
    lo, hi = c4.HOLDOUT_START, c4.HOLDOUT_END
    with tempfile.TemporaryDirectory() as td:
        act = Path(td) / "ruled_actions.parquet"
        ruled.to_parquet(act, index=False)
        for lab, rp in RULINGS.items():
            yf = c4.yf_total_returns(px, cols, sess, actions=act, rulings=rp)
            for d, v in fill.items():
                assert pd.isna(yf.loc[d, "IGR"])
                yf.loc[d, "IGR"] = v
            R = pd.concat([cr.loc[:c4.CRSP_END], yf.loc[c4.YF_START:]])
            R0 = c4.check_held(H, R[UH].reindex(index=H.index), lab)
            r = bf.evaluate(H, R0)
            P, TU = r["pnl"].loc[lo:hi], r["turn_series"].loc[lo:hi]
            s = c4.row_stats(P, TU)
            print(f"[{lab}] {len(P)} sessions; max |P - committed P| = {float((P - Pc).abs().max()):.3g}; gross SR "
                  f"{s['sr']:.3f}, ann {s['ann_pct']:+.2f}%, vol {s['vol_pct']:.2f}%, turn {s['turn']:.1f}; net @5 "
                  f"{s['net5']:.3f} @15 {s['net15']:+.3f} @30 {s['net30']:.3f}; flips: {s['flips']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=c4.CACHE)
    a = ap.parse_args()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(a.cache.resolve())
    OUT.write_text(buf.getvalue())
    print(buf.getvalue())
