"""REPORT-ONLY (zero trials): the spike-and-revert guard at every call of `yf_total_returns` in
C4's script, against the formula as it stood before the guard (832aeaa), on identical inputs.

    python3 results/cef/data_guards/c4_callsites_noop.py   # ~1 min; panels and committed tables only, no CRSP

For each call site -- Stage 0's `primary_returns` (pool), the fit's R-yf row (pool, fit window), the
holdout's `assemble` (ruled, uncorrected and R-ADX actions) -- it prints the sha256 of
`pd.util.hash_pandas_object` of the old and the guarded frame, every cell that differs, and the hash
with IGR's eight touched cells masked. It then rebuilds the fit's R-yf row on the guarded code and
compares it with the committed `c4_fit_tables_2026-10-14.csv`, and sizes the second defect class the
scan exposed (a recorded split applied to an already split-adjusted close; not guarded). Output:
results/cef/data_guards/c4_callsites_noop_output_2026-10-19.txt.

Amended 2026-10-20. That second class has been guarded since this date
(`data_guards.guard_split_basis`, inside `band_frontier.total_returns`). Every call below
therefore passes `c4.SPLIT_RULINGS` (book_as_is), which keeps this script's computation, and its
output file, as they were on 2026-10-19; re-run and diffed on 2026-10-20. The printed line
"NOT guarded" was true on 2026-10-19 and is kept as it was. The guard's own proof is
`split_basis_callsites.py`."""
import contextlib
import hashlib
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
from scripts.cef import data_guards as dg  # noqa: E402
from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS  # noqa: E402

OUT = REPO / "results" / "cef" / "data_guards" / "c4_callsites_noop_output_2026-10-19.txt"
BAD = pd.to_datetime(["2026-07-29", "2026-07-30", "2026-08-04", "2026-08-05", "2026-08-07", "2026-08-10",
                      "2026-08-11", "2026-08-12"])


def old(px, cols, index, actions=None):
    """`yf_total_returns` at 832aeaa, verbatim in substance."""
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    rpx = close.pct_change(fill_method=None).reindex(index=index, columns=list(cols))
    return bf.total_returns(rpx, actions=c4.FAM_DIR / "cef_actions.parquet" if actions is None else actions,
                            prices=c4.FAM_DIR / "cef_prices.parquet", split_rulings=c4.SPLIT_RULINGS)


def h(df) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()[:16]


def compare(label, a, b):
    d = (a.fillna(-999.0) != b.fillna(-999.0)).stack()
    d = d[d]
    ma, mb = a.copy(), b.copy()
    if "IGR" in a.columns:
        rows = [x for x in BAD if x in a.index]
        ma.loc[rows, "IGR"] = mb.loc[rows, "IGR"] = 0.0
    print(f"{label}: {a.shape[0]} sessions x {a.shape[1]} funds, {a.index[0].date()}..{a.index[-1].date()}")
    print(f"   sha256 old {h(a)}  guarded {h(b)}  -> {'IDENTICAL' if h(a) == h(b) else 'DIFFER'}; "
          f"{len(d)} cell(s) differ; with IGR's 8 touched cells masked: {h(ma)} vs {h(mb)} -> "
          f"{'IDENTICAL' if h(ma) == h(mb) else 'DIFFER'}")
    for x, t in d.index:
        print(f"      {x.date()} {t}: {a.loc[x, t]:+.6f} -> {b.loc[x, t]:+.6f}")


def main():
    U = c4.universes()
    pool, UF, snap = U["pool"], U["frozen"], U["snap68"]
    px, _ = c4.load_panels(pool)
    print(f"C4 call sites of yf_total_returns, old formula against the guarded one; rulings {c4.BAR_RULINGS.name}")
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    s0 = close.index[(close.index >= c4.SAMPLE_START) & (close.index <= c4.HOLDOUT_END)]
    compare("[stage0 primary_returns, pool]", old(px, pool, s0), c4.yf_total_returns(px, pool, s0, rulings=c4.BAR_RULINGS,
                                                                                       split_rulings=c4.SPLIT_RULINGS))
    try:
        c4.yf_total_returns(px, pool, s0)
        print("   without a rulings file: NO RAISE (unexpected)")
    except dg.SpikeRevertError as e:
        print(f"   without a rulings file it raises: {str(e)[:330]}...")
    T74 = c4.fit_slice(c4.build_book(UF))
    idx = T74.index
    yfR = c4.yf_total_returns(px, pool, idx, rulings=c4.BAR_RULINGS, split_rulings=c4.SPLIT_RULINGS)
    compare("[fit R-yf, pool, fit window]", old(px, pool, idx), yfR)
    RT = pd.read_csv(c4.RESOLUTION_TABLE, parse_dates=["date"])
    excluded = json.loads(c4.EXCLUSIONS_A4.read_text())["excluded"]
    UH = [t for t in UF if t not in excluded]
    T = c4.build_book(UH)
    sess = T.index[T.index <= c4.HOLDOUT_END]
    cols = sorted(set(UF) | set(snap))
    yfa = pd.read_parquet(c4.FAM_DIR / "cef_actions.parquet")
    yfa["date"] = pd.to_datetime(yfa["date"])
    RT_adx = RT.copy()
    m = (RT_adx["ticker"] == "ADX") & (RT_adx["date"] == pd.Timestamp("2025-01-27"))
    RT_adx.loc[m, "resolved"], RT_adx.loc[m, "resolved_amount"] = "Alpaca", RT_adx.loc[m, "alpaca"]
    with tempfile.TemporaryDirectory() as td:
        paths = {}
        for k, tbl in (("ruled", RT), ("radx", RT_adx)):
            paths[k] = Path(td) / f"actions_{k}.parquet"
            c4.ruled_actions(yfa, tbl, excluded).to_parquet(paths[k], index=False)
        for k, p in (("ruled", paths["ruled"]), ("uncorrected", None), ("R-ADX", paths["radx"])):
            compare(f"[holdout assemble({k}), {len(cols)} funds]", old(px, cols, sess, p),
                    c4.yf_total_returns(px, cols, sess, actions=p, rulings=c4.BAR_RULINGS,
                                        split_rulings=c4.SPLIT_RULINGS))

    H = bf.band_gross_capped(T74, BAND_WIDTH, MAX_GROSS_STRESS)

    def row(R):
        R0 = c4.check_held(H, R[UF].reindex(idx), "R-yf")
        r = bf.evaluate(H, R0)
        held = H.shift(2).abs().sum(axis=1)
        p0 = held.index[held > 0][0]
        return c4.row_stats(r["pnl"].loc[p0:c4.FIT_END], r["turn_series"].loc[p0:c4.FIT_END])

    com = pd.read_csv(c4.FIT_TABLES)
    com = com[com["book"] == "R-yf (yfinance-built total returns)"].iloc[0]
    s = row(yfR)
    same = all(abs(float(s[k]) - float(com[k])) <= 1e-12 for k in ("sr", "ann_pct", "turn", "net5", "net15", "net30"))
    print(f"\n[fit R-yf row rebuilt on the guarded code] gross SR {float(s['sr'])!r} net@15 {float(s['net15'])!r}; "
          f"committed {float(com['sr'])!r} {float(com['net15'])!r} -> {'EQUAL' if same else 'DIFFER'} on sr, ann, turn "
          "and the three net columns to 1e-12 (the CSV keeps 16 digits)")
    print("\n[a second defect class, NOT guarded] a recorded split applied to a close yfinance had already split-"
          "adjusted: the formula books k again. In the fit window (pool):")
    fix = yfR.copy()
    held = H.shift(2)
    for t, d in (("BTO", "2008-12-30"), ("TYG", "2020-05-01"), ("NXG", "2020-06-15"), ("EMO", "2020-07-28")):
        d = pd.Timestamp(d)
        k = float(yfa.loc[(yfa["ticker"] == t) & (yfa["date"] == d), "stock_splits"].iloc[0])
        raw = float(close.loc[d, t] / close[t].dropna().loc[:d].iloc[-2])
        w = f"held weight {float(held.loc[d, t]):+.5f}" if t in held.columns else "not in the 74 (R-yf books the 74)"
        print(f"   {t} {d.date()}: k {k:.4f}, raw close ratio {raw:.4f}, booked {yfR.loc[d, t]:+.4f}; {w}")
        if t in UF:
            fix.loc[d, t] = (1 + yfR.loc[d, t]) / k - 1
    s2 = row(fix)
    print(f"   R-yf with k not applied on those three 74-fund days: gross SR {s2['sr']:.3f} (committed "
          f"{com['sr']:.3f}), net@15 {s2['net15']:.3f} ({com['net15']:.3f}), net@30 {s2['net30']:.3f} "
          f"({com['net30']:.3f}). The CRSP primary return is not affected.")


if __name__ == "__main__":
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main()
    OUT.write_text(buf.getvalue())
    print(buf.getvalue())
