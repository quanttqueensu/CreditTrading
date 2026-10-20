"""REPORT-ONLY (zero trials): the split-basis guard (`data_guards.guard_split_basis`, 2026-10-20) at
every call site that applies a recorded split to a yfinance series, against the formula as it stood
before the guard (392ce57), on identical inputs.

    python3 results/cef/data_guards/split_basis_callsites.py   # ~1 min; panels and committed tables only

No CRSP cache is read; the CRSP-built panel in data/cef_families/ is read for COUNTS only (licensed).
For each site it prints:
  * what the guard raises without a ruling;
  * the sha256 (16 hex) of `pd.util.hash_pandas_object` of the old frame and of the guarded frame
    under `c4_split_rulings_2026-10-20.json` (book_as_is). These must be identical: that file exists
    so that C4's committed paths reproduce exactly;
  * the cells a `drop_split` ruling would change (the correction, which nobody has ruled).
The sites are:
  * the live panel's default `total_returns(R)`, for `build_targets()` default and min_adv=0;
  * C4's `yf_total_returns` at Stage 0 (pool), the fit's R-yf row (pool, fit window) and the
    holdout's `assemble` (ruled, uncorrected and R-ADX actions);
  * the fit's NAV catch-up (`split_factor` on the families NAV).
It then rebuilds the R-yf row and the NAV catch-up slope under both treatments, compares the
book_as_is ones with the committed fit (c4_fit_tables / c4_fit_verdict, 2026-10-14), and counts how
far the CRSP-built panel agrees.
Output: results/cef/data_guards/split_basis_callsites_output_2026-10-20.txt."""
import contextlib
import hashlib
import io
import json
import math
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.cef import band_frontier as bf  # noqa: E402
from scripts.cef import c4_families as c4  # noqa: E402
from scripts.cef import data_guards as dg  # noqa: E402
from scripts.cef import w4_artifacts as w4  # noqa: E402
from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS  # noqa: E402
from scripts.cef.spec import MIN_ADV_USD as MIN_ADV  # noqa: E402

OUT = REPO / "results" / "cef" / "data_guards" / "split_basis_callsites_output_2026-10-20.txt"
NEW_TR = bf.total_returns


def old_total_returns(R, actions=None, prices=None, split_rulings=None):
    """`band_frontier.total_returns` at 392ce57, verbatim but for the guard (the only change).
    `split_rulings` is accepted and ignored, so the new `yf_total_returns` can call it."""
    if (actions is None) != (prices is None):
        raise ValueError("total_returns: give `actions` and `prices` together, or neither")
    if actions is None:
        y = bf.distribution_yield(R.index, R.columns).reindex_like(R)
        k = bf.split_factor(R.index, R.columns).reindex_like(R)
    else:
        dist, sp = bf.load_families_actions(actions)
        y = bf.distribution_yield(R.index, R.columns, dist=dist, prices=prices).reindex_like(R)
        k = bf.split_factor(R.index, R.columns, splits=sp).reindex_like(R)
    clash = ((k != 1.0) & (y != 0.0))
    if clash.any().any():
        raise ValueError("a split and a distribution fall on the same name-date")
    return (1.0 + R) * k - 1.0 + y


@contextlib.contextmanager
def old_formula():
    bf.total_returns = old_total_returns
    try:
        yield
    finally:
        bf.total_returns = NEW_TR


def h(df) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()[:16]


def compare(label, a, b, c=None):
    print(f"{label}: {a.shape[0]} sessions x {a.shape[1]} series, {a.index[0].date()}..{a.index[-1].date()}")
    print(f"   sha256 old {h(a)}  guarded under {c4.SPLIT_RULINGS.name} {h(b)} -> "
          f"{'IDENTICAL' if h(a) == h(b) else 'DIFFER'}")
    if c is not None:
        d = (a.fillna(-999.0) != c.fillna(-999.0)).stack()
        d = d[d]
        print(f"   under drop_split (the correction, NOT ruled): {len(d)} cell(s) differ"
              + "".join(f"; {x.date()} {t} {a.loc[x, t]:+.4f} -> {c.loc[x, t]:+.4f}" for x, t in d.index))


def crsp_comparison(spl) -> pd.DataFrame:
    """Each recorded split applied on both the yfinance and the CRSP-built close, labelled on each.
    `adjusted_vs_crsp`: the gap between the two sources' steps is nearer ln k than 0, i.e. yfinance's
    close carries the split and CRSP's raw print does not. Used for counts only (CRSP is licensed)."""
    cr = dg._wide(pd.read_parquet(c4.FAM_DIR / "cef_prices_crsp.parquet"), "close")
    yw = dg._wide(pd.read_parquet(c4.FAM_DIR / "cef_prices.parquet"), "close")
    sp = spl[spl["ticker"].isin(set(cr.columns) & set(yw.columns))]
    Cy = dg.split_basis_check(*dg._call_site_frames(yw[sorted(set(sp["ticker"]))], sp))
    Cc = dg.split_basis_check(*dg._call_site_frames(cr[sorted(set(sp["ticker"]))], sp))
    J = Cy.merge(Cc, on=["ticker", "ex_date", "factor"], suffixes=("_yf", "_crsp"))
    gap = np.log(J["raw_ratio_yf"].to_numpy()) - np.log(J["raw_ratio_crsp"].to_numpy())
    lk = np.log(J["factor"].to_numpy())
    return J.assign(adjusted_vs_crsp=np.abs(gap - lk) < np.abs(gap))


def raises(label, fn):
    try:
        fn()
        print(f"   without a split ruling: NO RAISE ({label})")
    except dg.SplitBasisError as e:
        print(f"   without a split ruling it raises: {str(e).split('. On each')[0]}")


def main(drop: Path):
    print("Split-basis guard (data_guards.guard_split_basis), every call site; report only, zero trials.")
    print(f"Rule: tau = ln(1.15) = {dg.SPLIT_TOL:.4f}; decidable iff |ln k| > 2 tau; raised iff decidable and the raw "
          "step on the cell k multiplies is within tau of none.\n")

    print("[1] the live panel: default total_returns(R), old (392ce57) against guarded (no rulings file)")
    for lab, kw in (("build_targets()", {}), ("build_targets(min_adv=0.0)", dict(min_adv=0.0))):
        _T, R = bf.build_targets(**kw)
        C = dg.split_basis_check(R, bf.split_factor(R.index, R.columns).reindex_like(R))
        print(f"  {lab}: splits applied {len(C)}, basis {C['basis'].value_counts().to_dict()}; "
              f"sha256 old {h(old_total_returns(R))} guarded {h(bf.total_returns(R))} -> "
              f"{'IDENTICAL' if h(old_total_returns(R)) == h(bf.total_returns(R)) else 'DIFFER'}")

    U = c4.universes()
    pool, UF, snap = U["pool"], U["frozen"], U["snap68"]
    px, _ = c4.load_panels(pool)
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    s0 = close.index[(close.index >= c4.SAMPLE_START) & (close.index <= c4.HOLDOUT_END)]
    print(f"\n[2] C4's yf_total_returns (spike rulings {c4.BAR_RULINGS.name} throughout, as committed)")
    kw_old = dict(rulings=c4.BAR_RULINGS)
    with old_formula():
        a = c4.yf_total_returns(px, pool, s0, **kw_old)
    compare("[stage0 primary_returns, pool]", a, c4.yf_total_returns(px, pool, s0, split_rulings=c4.SPLIT_RULINGS,
                                                                     **kw_old),
            c4.yf_total_returns(px, pool, s0, split_rulings=drop, **kw_old))
    raises("stage0", lambda: c4.yf_total_returns(px, pool, s0, **kw_old))
    T74 = c4.fit_slice(c4.build_book(UF))
    idx = T74.index
    with old_formula():
        a = c4.yf_total_returns(px, pool, idx, **kw_old)
    yfR = c4.yf_total_returns(px, pool, idx, split_rulings=c4.SPLIT_RULINGS, **kw_old)
    yfD = c4.yf_total_returns(px, pool, idx, split_rulings=drop, **kw_old)
    compare("[fit R-yf, pool, fit window]", a, yfR, yfD)
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
            with old_formula():
                a = c4.yf_total_returns(px, cols, sess, actions=p, **kw_old)
            b = c4.yf_total_returns(px, cols, sess, actions=p, split_rulings=c4.SPLIT_RULINGS, **kw_old)
            c = c4.yf_total_returns(px, cols, sess, actions=p, split_rulings=drop, **kw_old)
            compare(f"[holdout assemble({k}), {len(cols)} funds]", a, b, c)
            print(f"   the yfinance leg the holdout keeps ({c4.YF_START.date()}..): old {h(a.loc[c4.YF_START:])} "
                  f"guarded {h(b.loc[c4.YF_START:])}, drop_split {h(c.loc[c4.YF_START:])}")

    H = bf.band_gross_capped(T74, BAND_WIDTH, MAX_GROSS_STRESS)

    def row(R):
        R0 = c4.check_held(H, R[UF].reindex(idx), "R-yf")
        r = bf.evaluate(H, R0)
        held = H.shift(2).abs().sum(axis=1)
        p0 = held.index[held > 0][0]
        return c4.row_stats(r["pnl"].loc[p0:c4.FIT_END], r["turn_series"].loc[p0:c4.FIT_END])

    com = pd.read_csv(c4.FIT_TABLES)
    com = com[com["book"] == "R-yf (yfinance-built total returns)"].iloc[0]
    keys = ("sr", "ann_pct", "turn", "net5", "net15", "net30")
    s, sd = row(yfR), row(yfD)
    same = all(abs(float(s[k]) - float(com[k])) <= 1e-12 for k in keys)
    print(f"\n[3] the fit's R-yf row (report-only robustness row; the CRSP primary return is not touched)")
    print(f"  under {c4.SPLIT_RULINGS.name} (book_as_is): gross SR {float(s['sr'])!r}, net@15 {float(s['net15'])!r}; committed "
          f"{float(com['sr'])!r}, {float(com['net15'])!r} -> {'EQUAL' if same else 'DIFFER'} on {', '.join(keys)} "
          "to 1e-12")
    print(f"  under drop_split (NOT ruled): gross SR {sd['sr']:.4f} (committed {float(com['sr']):.4f}), ann "
          f"{sd['ann_pct']:.3f}% ({float(com['ann_pct']):.3f}%), turn {sd['turn']:.2f} ({float(com['turn']):.2f}), net@5 "
          f"{sd['net5']:.3f} ({float(com['net5']):.3f}), net@15 {sd['net15']:.3f} ({float(com['net15']):.3f}), net@30 "
          f"{sd['net30']:.3f} ({float(com['net30']):.3f}); flips {sd['flips']}")
    J = crsp_comparison(bf.load_families_actions(c4.FAM_DIR / "cef_actions.parquet")[1])
    blind = J[(J["basis_yf"] == "undecidable") & J["adjusted_vs_crsp"] & J["ticker"].isin(UF)
              & J["ex_date"].isin(idx)]
    fix2 = yfD.copy()
    for r in blind.itertuples():
        fix2.loc[r.ex_date, r.ticker] = (1 + yfR.loc[r.ex_date, r.ticker]) / r.factor - 1
    s2 = row(fix2)
    print(f"  the guard's blind spot, sized: k also removed on the {len(blind)} split(s) of the 74 in the fit window "
          f"that are too small for the price to judge (|ln k| <= 2 tau) and that the CRSP-built close reads as adjusted "
          f"in yfinance ({', '.join(f'{r.ticker} {r.ex_date.date()} k {r.factor:g}' for r in blind.itertuples())}): "
          f"gross SR {s2['sr']:.4f}, net@15 {s2['net15']:.3f}, net@30 {s2['net30']:.3f} (NOT ruled; a sizing only)")

    print("\n[4] the fit's NAV catch-up (split_factor on the families NAV, as c4_families.fit forms it)")
    pnl_ = bf.build_panel(universe=UF, source=c4.FAM_SRC, mask=c4.declared_mask(UF))
    z = pnl_["z"].reindex(idx)
    M = z.notna() & (pnl_["adv"].reindex(idx) >= MIN_ADV)
    t0 = H.index[H.abs().sum(axis=1) > 0][0]
    dates = w4.grid(idx[idx >= t0], 0)
    dist, spl = bf.load_families_actions(c4.FAM_DIR / "cef_actions.parquet")
    amt = (dist[dist["ticker"].isin(UF)].groupby(["ex_date", "ticker"])["amount"].sum().unstack()
           .reindex(index=idx, columns=UF))
    full_nav = pnl_["nav"]
    rn = full_nav.pct_change(fill_method=None).reindex(idx)
    yn = (amt / full_nav.shift(1).reindex(idx)).where(amt.notna(), 0.0)
    kn = bf.split_factor(idx, UF, splits=spl).reindex(index=idx, columns=UF)
    raises("nav", lambda: dg.guard_split_basis(rn.reindex(columns=UF), kn, series="nav", context="nav_catchup"))
    kg = dg.guard_split_basis(rn.reindex(columns=UF), kn, rulings=c4.SPLIT_RULINGS, series="nav", context="nav_catchup")
    kd = dg.guard_split_basis(rn.reindex(columns=UF), kn, rulings=drop, series="nav", context="nav_catchup")
    print(f"  under {c4.SPLIT_RULINGS.name}: the guard returns the input factor frame itself: {kg is kn}; "
          f"sha256 {h(kn)} -> {h(kg)}")
    com_v = json.loads(c4.FIT_JSON.read_text())["nav_catchup"]
    for lab, kk in (("book_as_is", kg), ("drop_split (NOT ruled)", kd)):
        fmn = w4.fm_slopes(z, w4.fwd((1 + rn) * kk - 1 + yn, 2, 3), M, dates)
        bp, t = float(fmn.mean() * 1e4), float(fmn.mean() / fmn.std(ddof=1) * np.sqrt(len(fmn)))
        eq = abs(bp - com_v["fm_bp"]) <= 1e-12 and abs(t - com_v["t"]) <= 1e-12 and len(fmn) == com_v["n"]
        print(f"  {lab}: FM slope {bp:+.4f} bp per unit z (t {t:.4f}, n {len(fmn)}); committed "
              f"{com_v['fm_bp']:+.4f} (t {com_v['t']:.4f}, n {com_v['n']})" + (" -> EQUAL to 1e-12" if eq else ""))

    print("\n[5] the second source, counts only (the CRSP-built panel is licensed; data/cef_families/, to 2024-12-31)")
    adj = J[J["basis_yf"] == "adjusted"]
    four = adj[adj["ticker"].isin(["BTO", "TYG", "NXG", "EMO"]) & (adj["ex_date"].dt.year >= 2005)]
    print(f"  yfinance-ADJUSTED cells with a CRSP return on the same day: {len(adj)}; CRSP reads `raw` on "
          f"{int((adj['basis_crsp'] == 'raw').sum())} of them, including {int((four['basis_crsp'] == 'raw').sum())} "
          f"of the {len(four)} C4 cells")
    und = J[J["basis_yf"] == "undecidable"]
    closer_k = int(und["adjusted_vs_crsp"].sum())
    print(f"  undecidable cells (|ln k| <= 2 tau) with both: {len(und)}. Where the two sources' steps differ, the gap "
          f"is nearer ln k than 0 (yfinance adjusted, CRSP raw) on {closer_k}, nearer 0 (the same basis) on "
          f"{len(und) - closer_k}. The price alone cannot see these; a second source can.")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        R, doc = dg.load_split_rulings(c4.SPLIT_RULINGS)
        doc = dict(doc, ruled_by="nobody: a counterfactual for this report", record="this script only",
                   splits=[dict(s, treatment="drop_split") for s in doc["splits"]])
        drop = Path(td) / "drop_split_counterfactual.json"
        drop.write_text(json.dumps(doc))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(drop)
    OUT.write_text(buf.getvalue())
    print(buf.getvalue())
