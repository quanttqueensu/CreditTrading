"""Zero-trial feasibility for trial C4 (the live discount z-score, pooled, on
equity, sector, covered-call, preferred and multi-asset CEFs).

    python3 scripts/cef/c4_feasibility.py          # ~1 min; reads data/cef_families/ and data/cef/
                                                    # read-only; writes results/cef/c4/*_2026-10-13.csv

WHAT THIS IS FOR
----------------
`results/cef/PREREG_C4_FAMILIES_2026-10-13.md` (a DRAFT awaiting the team lead)
declares C4's universe, its two data masks and its pass bar before any of its
returns exist. This script measures the inputs that declaration needs and
nothing else:

* the declared pool, and every fund left out with the reason;
* how much each declared mask removes (the NAV-repeat mask and the
  zero-volume mask), and how often a NAV repeat is a vendor stale copy rather
  than a genuine unchanged NAV, on the dates CEFConnect can check;
* eligible breadth per session after the masks, by era, for the pool and for
  the fresh-NAV sub-book (the stale-NAV control), and the first session on
  which the pool reaches the spec's `min_names`;
* the length of the fit window that sets, and arithmetic on the pass bar:
  the Sharpe at which `scripts/cef/validate.py::_dsr` reaches 0.95 at the CEF
  counter's N, the power at a grid of hypothetical true Sharpes, the Sharpe an
  alpha t of 3.0 needs, the false-kill rate of the holdout sign rule, and the
  sampling error of the correlation kill.

WHAT IT DOES NOT DO (zero trials)
---------------------------------
No discount z-score is computed on any family fund, no position, no P&L, no
IC, no correlation and no forward return. Eligibility is a count of the
sleeve's filters (a paired price and NAV, enough history, ADV), the same
count `scripts/data/cef_families_quality.py` makes, with the two masks added.
The deployed book's first position is read from the canonical harness on the
live panel, which every W4-era script already does; its P&L is not computed.

ALIGNMENT (H7): the history count and the ADV are `.shift(1)`, as the sleeve's
`mu`, `sd` and `adv` are (scripts/cef/band_frontier.py::build_panel). The NAV
repeat is judged against the fund's own previous NAV row, which exists before
the date it masks.

NO SILENT FALLBACK: every input file is required and named when missing; a
fund in the pool with no NAV raises.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FAM_DIR = REPO / "data" / "cef_families"
NAMES_CSV = REPO / "results" / "cef" / "cef_families" / "names_2026-10-12.csv"
OUT_DIR = REPO / "results" / "cef" / "c4"
STAMP = "2026-10-13"

# The declared pool (PREREG_C4 §2.1). Global equity is left out by declaration:
# its NAVs are struck at foreign closes, hours before the US close that prices
# the shares, which is the `single-fund-PD` structure (families note §5).
POOL_FAMILIES = ("equity_domestic", "equity_sector", "equity_covered_call",
                 "preferred", "multi_asset")
EXCLUDED_FAMILIES = {"equity_global": "asynchronous NAV (foreign close); single-fund-PD structure"}
# The stale-NAV control (PREREG_C4 §5, plan row 9): the families whose NAVs are
# measured NOT smoothed (lag-1 autocorrelation of NAV changes <= 0 at the family
# median, families note §5). Preferred (+0.01, upper quartile +0.23) is not in it.
FRESH_NAV_FAMILIES = ("equity_domestic", "equity_sector", "equity_covered_call")

SAMPLE_START = pd.Timestamp("2005-01-03")      # band_frontier.SAMPLE_START, asserted in main()
HOLDOUT_START = pd.Timestamp("2023-01-01")
FIT_END = pd.Timestamp("2022-12-30")
ERAS = [("2005-09", "2005-01-01", "2009-12-31"), ("2010-14", "2010-01-01", "2014-12-31"),
        ("2015-19", "2015-01-01", "2019-12-31"), ("2020-22", "2020-01-01", "2022-12-31"),
        ("2023-26 (holdout)", "2023-01-01", "2026-12-31")]
ADV_DAYS, ADV_MIN = 63, 21                     # the sleeve's `adv` line
MIN_PERIODS = 120                              # band_frontier.MIN_PERIODS, asserted in main()


def _need(p: Path) -> Path:
    if not p.exists():
        raise FileNotFoundError(f"{p} is missing; it is built by the scripts named in "
                                "results/cef/CEF_FAMILIES_DATA_2026-10-12.md")
    return p


def flagged_funds(names: pd.DataFrame) -> pd.DataFrame:
    """The 14 funds the families note flags (§3.2-3.3): a SYSTEMATIC discount
    disagreement before 2023 or in the daily window, or a split-basis mismatch."""
    f = names[(names["disc_All_pre2023_class"] == "SYSTEMATIC")
              | (names["disc_1Y_class"] == "SYSTEMATIC")
              | names["split_basis_mismatch_before"].notna()]
    return f[["ticker", "family"]].assign(reason=np.where(
        f["split_basis_mismatch_before"].notna(), "split-basis mismatch (close re-based, NAV not)",
        "SYSTEMATIC discount disagreement with CEFConnect"))


def declare_pool(names: pd.DataFrame) -> tuple[list[str], pd.DataFrame]:
    """(pool tickers, table of every C4-family fund left out, with its reason)."""
    out = []
    flag = set(flagged_funds(names)["ticker"])
    pool = []
    for r in names.itertuples(index=False):
        if r.family in EXCLUDED_FAMILIES:
            out.append((r.ticker, r.family, EXCLUDED_FAMILIES[r.family]))
        elif r.family not in POOL_FAMILIES:
            raise ValueError(f"{r.ticker}: family {r.family!r} is in neither the pool nor the exclusions")
        elif not (r.nav_rows or 0) > 0:
            out.append((r.ticker, r.family, "no usable daily NAV (families note §4)"))
        elif r.ticker in flag:
            out.append((r.ticker, r.family, "flagged vendor defect (families note §3.2-3.3)"))
        else:
            pool.append(r.ticker)
    return sorted(pool), pd.DataFrame(out, columns=["ticker", "family", "reason"])


def repeat_mask(nav: pd.DataFrame) -> pd.Series:
    """True where a fund's NAV equals its own previous NAV row exactly (to the
    cent as stored). Every vendor stale copy is such a repeat; so is a genuine
    unchanged NAV. Index aligned to `nav`."""
    n = nav.sort_values(["ticker", "date"])
    rep = n.groupby("ticker")["nav"].diff().eq(0)
    return rep.reindex(nav.index)


def eligibility(px: pd.DataFrame, nav: pd.DataFrame, floor: float, z_window: int,
                mask_repeat: bool = True, mask_zero_volume: bool = True,
                min_periods: int = MIN_PERIODS) -> dict:
    """Per session and fund, the sleeve's filters without a signal.

    The panel is the inner join of price and NAV with both above $0.50, as
    `build_panel` makes it. ADV is computed on that joined panel, unmasked, as
    the harness computes it. The masks act on the DISCOUNT only: a masked
    fund-day has no discount that day, so it is not eligible and does not count
    toward the z-window history; its price stays in the panel (PREREG_C4 §2.3).
    """
    d = px[["ticker", "date", "close", "volume"]].merge(nav[["ticker", "date", "nav", "repeat"]],
                                                         on=["ticker", "date"], how="inner")
    d = d[(d["nav"] > 0.5) & (d["close"] > 0.5)]
    piv = lambda c: d.pivot_table(index="date", columns="ticker", values=c).sort_index()  # noqa: E731
    close, vol = piv("close"), piv("volume")
    paired = close.notna()
    rep = d.pivot_table(index="date", columns="ticker", values="repeat", aggfunc="max")
    rep = rep.reindex_like(paired).eq(True)        # a fund-day with no NAV row is not a repeat
    zv = vol.reindex_like(paired).eq(0) & paired
    ok = paired.copy()
    if mask_repeat:
        ok &= ~rep
    if mask_zero_volume:
        ok &= ~zv
    nobs = ok.astype(float).rolling(z_window, min_periods=1).sum().shift(1)
    adv = (close * vol).rolling(ADV_DAYS, min_periods=ADV_MIN).mean().shift(1)
    elig = ok & (nobs >= min_periods) & (adv >= floor)
    return dict(elig=elig, paired=paired, repeat=rep & paired, zero_vol=zv)


def era_rows(elig: pd.DataFrame, min_names: int, label: str) -> list[dict]:
    cnt = elig.sum(axis=1)
    cnt = cnt[cnt.index >= SAMPLE_START]
    rows = []
    for era, a, b in ERAS + [("fit 2005-22", "2005-01-01", "2022-12-31")]:
        c = cnt.loc[a:b]
        if c.empty:
            continue
        act = c >= min_names
        rows.append(dict(book=label, era=era, sessions=len(c), active_sessions=int(act.sum()),
                         active_share=float(act.mean()), median_eligible=float(c.median()),
                         p10_eligible=float(c.quantile(0.10)), max_eligible=int(c.max()),
                         funds_ever_eligible=int(elig.loc[a:b].any().sum())))
    return rows


def first_active(elig: pd.DataFrame, min_names: int) -> pd.Timestamp:
    cnt = elig.sum(axis=1)
    act = cnt[(cnt.index >= SAMPLE_START) & (cnt >= min_names)]
    if act.empty:
        raise RuntimeError("the pool never reaches min_names eligible funds")
    return act.index[0]


def corr_kill_prob(rho_true: float, n: int, thr: float = 0.5) -> float:
    """P(sample Pearson rho >= thr | true rho, n pairs), Fisher-z approximation."""
    from statistics import NormalDist
    se = 1.0 / math.sqrt(n - 3)
    return 1.0 - NormalDist().cdf((math.atanh(thr) - math.atanh(rho_true)) / se)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.parse_args(argv)
    from scripts.cef import band_frontier as bf
    from scripts.cef.spec import (BAND_WIDTH, MAX_GROSS_STRESS, MIN_ADV_USD, MIN_NAMES,
                                  Z_WINDOW, summary)
    from scripts.xasset.slate_feasibility import power, required_sharpe
    assert bf.SAMPLE_START == str(SAMPLE_START.date()) and bf.MIN_PERIODS == MIN_PERIODS
    assert bf.HOLDOUT_START == HOLDOUT_START
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)
    print(summary())
    print(f"floor min_adv_usd {MIN_ADV_USD:,.0f}; min_names {MIN_NAMES}; z_window {Z_WINDOW}; "
          f"band_width {BAND_WIDTH}; max_gross_stress {MAX_GROSS_STRESS} (all read through scripts/cef/spec.py)")

    names = pd.read_csv(_need(NAMES_CSV))
    pool, left_out = declare_pool(names)
    print(f"\n[1] POOL: {len(pool)} funds in {', '.join(POOL_FAMILIES)}; "
          f"{len(left_out)} C4-family funds left out")
    print(left_out.groupby("reason").size().to_string())
    print("flagged (excluded on every date):", ", ".join(sorted(flagged_funds(names)["ticker"])))
    fam = names.set_index("ticker")["family"]
    print("pool by family:", fam.reindex(pool).value_counts().to_dict())

    px = pd.read_parquet(_need(FAM_DIR / "cef_prices.parquet"))
    nav = pd.read_parquet(_need(FAM_DIR / "cef_nav.parquet"))
    px, nav = px[px["ticker"].isin(pool)].copy(), nav[nav["ticker"].isin(pool)].copy()
    missing = sorted(set(pool) - set(nav["ticker"]))
    if missing:
        raise RuntimeError(f"pool funds with no NAV rows: {missing}")
    for f in (px, nav):
        f["date"] = pd.to_datetime(f["date"])
    nav["repeat"] = repeat_mask(nav)
    print(f"panels: prices last {px['date'].max().date()}, NAV last {nav['date'].max().date()} "
          "(data/cef_families/, built 2026-10-12)")

    # [2] the NAV-repeat mask: bite by year, and precision where CEFConnect can check
    flags = pd.read_parquet(_need(FAM_DIR / "nav_flags.parquet"))
    flags = flags[flags["ticker"].isin(pool)].copy()
    flags["date"] = pd.to_datetime(flags["date"])
    chk = flags["cc_nav_All"].where(flags["cc_nav_All"].notna(), flags["cc_nav_1Y"])
    flags["checked"] = chk.notna()
    flags["stale_copy"] = chk.eq("A_REPEATED")
    rep_chk = flags[flags["yf_nav_repeated"] & flags["checked"]]
    nav["year"] = nav["date"].dt.year
    by_year = pd.DataFrame({
        "nav_rows": nav.groupby("year").size(),
        "repeat_share": nav.groupby("year")["repeat"].mean(),
        "checked_repeats": rep_chk.groupby(rep_chk["date"].dt.year).size(),
        "of_which_stale_copy": rep_chk.groupby(rep_chk["date"].dt.year)["stale_copy"].sum(),
    }).fillna(0)
    by_year["stale_share_of_checked_repeats"] = (by_year["of_which_stale_copy"]
                                                 / by_year["checked_repeats"].replace(0, np.nan))
    print("\n[2] NAV-repeat mask, pool NAV rows by year (repeat = equal to the fund's previous NAV row);"
          "\n    precision on CEFConnect-checked rows (weekly Fridays to 2025-10-10, daily after):")
    print(by_year.loc[2005:].round(3).to_string())
    by_year.to_csv(OUT_DIR / f"c4_repeat_mask_by_year_{STAMP}.csv")

    # [3] eligibility, masked and unmasked, by era; first active session
    # The declared universe (PREREG_C4 §2.1): the pool less the funds Alpaca does
    # not list shortable, on the snapshot the families build read (2026-10-12T18:27Z;
    # the trial re-reads the latest snapshot at run time, H14). Like the v7
    # universe rule, a fund that cannot be shorted leaves the book on both sides.
    shortable = set(names.loc[names["alpaca_shortable"].astype(bool), "ticker"])
    prim = [t for t in pool if t in shortable]
    fresh = [t for t in prim if fam[t] in FRESH_NAV_FAMILIES]
    print(f"\n    declared universe: {len(prim)} of the {len(pool)} pool funds shortable on the "
          f"2026-10-12 snapshot; by family {fam.reindex(prim).value_counts().to_dict()}; "
          f"fresh-NAV sub-book {len(fresh)}")
    E_all = eligibility(px, nav, MIN_ADV_USD, Z_WINDOW)
    E0 = eligibility(px, nav, MIN_ADV_USD, Z_WINDOW, mask_repeat=False, mask_zero_volume=False)
    sub = lambda e, keep: e[[c for c in e.columns if c in keep]]  # noqa: E731
    E = {k: sub(v, prim) for k, v in E_all.items()}
    elig, elig0 = E["elig"], sub(E0["elig"], prim)
    rows = (era_rows(elig, MIN_NAMES, "declared: shortable pool, masked")
            + era_rows(elig0, MIN_NAMES, "shortable pool, unmasked (R-Q)")
            + era_rows(E_all["elig"], MIN_NAMES, "all 105, masked (R-S)")
            + era_rows(sub(elig, fresh), MIN_NAMES, "fresh-NAV sub-book, masked"))
    T = pd.DataFrame(rows)
    print(f"\n[3] eligible breadth per session from {SAMPLE_START.date()} (active = >= {MIN_NAMES} eligible):")
    print(T.round(3).to_string(index=False))
    T.to_csv(OUT_DIR / f"c4_breadth_by_era_{STAMP}.csv", index=False)

    lost = (elig0 & ~elig).loc[SAMPLE_START:]
    base = elig0.loc[SAMPLE_START:]
    print("\n    eligible fund-days removed by the masks, share of unmasked eligible fund-days:")
    for era, a, b in ERAS:
        nb = int(base.loc[a:b].sum().sum())
        print(f"      {era:<18} {int(lost.loc[a:b].sum().sum()):>7} of {nb:>7}  "
              f"({(lost.loc[a:b].sum().sum() / nb if nb else float('nan')):.1%})")
    zv_el = (E0["zero_vol"] & E0["elig"]).loc[SAMPLE_START:].sum().sum()
    print(f"    zero-volume bars on otherwise-eligible fund-days (all 105): {int(zv_el)}")

    share = elig.loc[SAMPLE_START:FIT_END].sum().groupby(fam).sum()
    print("    share of fit-period eligible fund-days by family:",
          (share / share.sum()).round(3).to_dict())

    f0 = first_active(elig, MIN_NAMES)
    cnt = elig.sum(axis=1)
    fit_sessions = int(((cnt.index >= f0) & (cnt.index <= FIT_END)).sum())
    ho = cnt[cnt.index >= HOLDOUT_START]
    print(f"\n    first active session (declared universe, masked): {f0.date()}; fit sessions from it to "
          f"{FIT_END.date()}: {fit_sessions} ({fit_sessions / 252:.1f} yr); holdout sessions "
          f"{ho.index[0].date()} -> {ho.index[-1].date()}: {len(ho)} ({len(ho) / 252:.2f} yr)")

    # [4] the deployed book: first position (for the correlation-kill window); no P&L
    Tb, Rb = bf.fit_only(*bf.build_targets())
    Hb = bf.band_gross_capped(Tb, BAND_WIDTH, MAX_GROSS_STRESS)
    b0 = Hb.abs().sum(axis=1).gt(0).idxmax()
    ov0 = max(b0, f0)
    n_ov = int(((cnt.index >= ov0) & (cnt.index <= FIT_END)).sum())
    n21 = n_ov // 21
    print(f"\n[4] deployed v7 book (live panel, read-only): first position {b0.date()}; "
          f"fit overlap with C4 from {ov0.date()}: {n_ov} sessions = {n21} non-overlapping 21-session blocks")
    print("    P(sample rho_21 >= 0.5 | true rho): "
          + ", ".join(f"{r:.1f}: {corr_kill_prob(r, n21):.3f}" for r in (0.2, 0.3, 0.4, 0.5, 0.6)))

    # [5] the bar and its power (arithmetic; skew 0, kurtosis 3; SE = 1/sqrt(years))
    from statistics import NormalDist
    yrs = fit_sessions / 252
    print(f"\n[5] pass bar: validate._dsr > 0.95 at the CEF counter's N, on {fit_sessions} fit sessions")
    print(f"{'N':>4}{'sqrt(2lnN)':>11}{'req SR':>8}{'SR@80%':>8}"
          + "".join(f"{'P|SR=' + format(s, '.2f'):>11}" for s in (0.50, 0.75, 1.00, 1.25)))
    bar_rows = []
    for N in (51, 52, 53, 55, 58):
        req = required_sharpe(N, fit_sessions)
        mde = req + NormalDist().inv_cdf(0.80) / math.sqrt(yrs)
        ps = [power(s, N, fit_sessions) for s in (0.50, 0.75, 1.00, 1.25)]
        print(f"{N:>4}{math.sqrt(2 * math.log(N)):>11.3f}{req:>8.3f}{mde:>8.3f}"
              + "".join(f"{p:>11.3f}" for p in ps))
        bar_rows.append(dict(N=N, emax=math.sqrt(2 * math.log(N)), required_sr=req, sr_80pct=mde,
                             **{f"p_pass_sr_{s:.2f}": p for s, p in zip((0.50, 0.75, 1.00, 1.25), ps)}))
    pd.DataFrame(bar_rows).to_csv(OUT_DIR / f"c4_bar_power_{STAMP}.csv", index=False)
    print(f"    D4 alpha t >= 3.0 needs a residual Sharpe of at least {3.0 / math.sqrt(yrs):.3f} "
          f"over {yrs:.1f} fit years (HAC widens it)")
    yh = len(ho) / 252
    print(f"    holdout sign rule over {yh:.2f} yr: false-kill probability at a true SR of "
          + ", ".join(f"{s:.2f}: {NormalDist().cdf(-s * math.sqrt(yh)):.3f}" for s in (0.5, 0.75, 1.0)))
    print("\nzero trials: no z-score, position, P&L, IC or correlation of any family fund was computed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
