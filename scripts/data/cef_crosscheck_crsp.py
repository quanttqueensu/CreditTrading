"""Independent-source check of the live price panel's closes against CRSP daily.

    python3 scripts/data/cef_crosscheck_crsp.py      # writes results/data/cef_crosscheck_crsp_<date>.md

WHY THIS EXISTS
---------------
The live sleeve decides on `data/cef/cef_prices.parquet`, which has exactly one
source: yfinance, through `scripts/cef/fetch_daily.py`. Nothing has ever checked
that panel against a second, independent source, and the data rules say
anything that drives a decision is double-checked by an independent source,
with disagreements REPORTED, never averaged and never silently resolved
(CLAUDE.md). CRSP daily (`crsp_a_stock.dsf` on the R2 WRDS mirror) is the
academic reference close and is built from exchange data independently of
Yahoo, so it is the natural second source for the history. It is only a check:
nothing here writes to `data/`, and R2 is never on the live path
(`docs/RUNNER.md`).

WHAT IT COMPARES (columns verified in the mirror, results/data/R2_CATALOG.md,
run 2026-09-28 20:31 UTC)
------------------------------------------------------------------------------
Universe: the frozen spec's `UNIVERSE`, read through `scripts/cef/spec.py` (the
only reader of the spec).

Ticker -> PERMNO: `crsp_a_stock.stocknames` (`permno`, `ticker`, `namedt`,
`nameenddt`). A panel row (ticker, date) maps to the permno whose name record
covers that date, inclusive. Tickers are recycled across unrelated issuers
over decades, which is why the join is by date range and not by ticker alone.
Zero covering records -> UNMAPPED; two or more distinct permnos -> AMBIGUOUS.
Neither is resolved by picking one; both are reported.

Close: CRSP `dsf.prc`. CRSP's convention (CRSP data descriptions guide): a
POSITIVE `prc` is the closing trade price; a NEGATIVE one means there was no
closing trade and the value is minus the bid/ask average. So a negative `prc`
is not a close and is placed in its own category, CRSP_NO_TRADE, never
compared as if it were one.

Two comparisons, reported side by side, never blended:
  RAW       panel close vs CRSP `prc` as printed that day.
  SPLIT_ADJ panel close vs CRSP `prc / cfacpr * cfacpr_last`, i.e. CRSP's
            price restated in the share units of CRSP's LAST date for that
            permno. yfinance's `history(auto_adjust=False)` Close is believed to
            be split-adjusted after the fact; that belief is exactly what this
            column tests rather than assumes. A split after CRSP's last date
            (the mirror ends 2024-12-31) is invisible to `cfacpr`; the
            per-ticker median ratio panel/CRSP exposes one as a constant factor.

Agreement tolerance `TOL_USD`: half a cent. Both sources quote to the cent;
anything wider is a real difference, anything tighter would count float noise
in the yfinance series as disagreement.

Coverage gaps are reported both ways inside the overlap window: panel dates a
mapped permno has no CRSP row for, and CRSP dates (for the mapped permno) the
panel lacks.

Exit code: 0 only if every universe ticker mapped on every overlapping date,
nothing is ambiguous, and every comparable RAW row agrees. Otherwise 1, after
writing the report -- a check that found something must not read as success.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

PANEL_PATH = REPO / "data" / "cef" / "cef_prices.parquet"
OUT_DIR = REPO / "results" / "data"

TOL_USD = 0.005
N_WORST = 15   # disagreements listed per ticker in the report


class CrossCheckError(RuntimeError):
    """An input needed for the check is missing. Names what."""


def load_panel(path: Path, universe: list[str]) -> pd.DataFrame:
    """(ticker, date, close) for the universe, from the live panel (read-only)."""
    if not path.exists():
        raise CrossCheckError(f"price panel {path} does not exist")
    px = pd.read_parquet(path, columns=["date", "ticker", "close"])
    missing = sorted(set(universe) - set(px["ticker"].unique()))
    if missing:
        raise CrossCheckError(f"universe tickers absent from {path}: {', '.join(missing)}")
    px = px[px["ticker"].isin(universe)].copy()
    px["date"] = pd.to_datetime(px["date"]).dt.normalize()
    dup = px.duplicated(["ticker", "date"], keep=False)
    if dup.any():
        # Two closes for one (ticker, date) in the panel is a panel defect, and
        # comparing either one would hide it.
        ex = px[dup].head(5)[["ticker", "date"]].to_records(index=False).tolist()
        raise CrossCheckError(f"panel has duplicate (ticker, date) rows, e.g. {ex}")
    return px.dropna(subset=["close"]).reset_index(drop=True)


def map_permnos(panel: pd.DataFrame, names: pd.DataFrame) -> pd.DataFrame:
    """Add `permno` and `map_status` (MAPPED / UNMAPPED / AMBIGUOUS) to each panel row.

    `names` has permno, ticker, namedt, nameenddt. Inclusive date-range join.
    `permno` is NaN unless MAPPED.
    """
    need = {"permno", "ticker", "namedt", "nameenddt"}
    if not need <= set(names.columns):
        raise CrossCheckError(f"names table lacks {sorted(need - set(names.columns))}")
    nm = names[list(need)].copy()
    nm["namedt"] = pd.to_datetime(nm["namedt"])
    nm["nameenddt"] = pd.to_datetime(nm["nameenddt"])
    j = panel[["ticker", "date"]].merge(nm, on="ticker", how="left")
    cover = (j["date"] >= j["namedt"]) & (j["date"] <= j["nameenddt"])
    hits = (j[cover].groupby(["ticker", "date"])["permno"]
            .agg(lambda s: sorted(set(int(v) for v in s))).rename("permnos"))
    out = panel.merge(hits, on=["ticker", "date"], how="left")
    n = out["permnos"].map(lambda v: len(v) if isinstance(v, list) else 0)
    out["map_status"] = np.select([n == 1, n == 0], ["MAPPED", "UNMAPPED"], "AMBIGUOUS")
    out["permno"] = [v[0] if k == 1 else np.nan for v, k in zip(out["permnos"], n)]
    return out


def compare(mapped: pd.DataFrame, crsp: pd.DataFrame, tol: float = TOL_USD) -> pd.DataFrame:
    """Row-level comparison of MAPPED panel rows against CRSP dsf.

    `crsp` has permno, date, prc, cfacpr. Returns one row per MAPPED panel row
    with `category`:
      AGREE / DISAGREE   RAW comparison of a positive CRSP prc
      CRSP_NO_TRADE      CRSP prc <= 0 or null (not a closing trade)
      NOT_IN_CRSP        mapped permno has no dsf row that date
    and `split_adj_category` AGREE / DISAGREE / NOT_COMPARABLE (cfacpr missing
    or zero, or the row is not a RAW comparison). No value is filled in.
    """
    c = crsp[["permno", "date", "prc", "cfacpr"]].copy()
    c["date"] = pd.to_datetime(c["date"]).dt.normalize()
    c["prc"] = c["prc"].astype(float)
    c["cfacpr"] = c["cfacpr"].astype(float)
    last = (c.sort_values("date").groupby("permno")["cfacpr"].last().rename("cfacpr_last"))
    c = c.merge(last, on="permno", how="left")
    m = mapped[mapped["map_status"] == "MAPPED"].copy()
    m["permno"] = m["permno"].astype(int)
    r = m.merge(c, on=["permno", "date"], how="left", indicator=True)
    in_crsp = r["_merge"] == "both"
    trade = in_crsp & (r["prc"] > 0)
    r["diff_raw"] = np.where(trade, r["close"] - r["prc"], np.nan)
    r["category"] = np.select(
        [~in_crsp, ~trade, np.abs(r["diff_raw"]) <= tol],
        ["NOT_IN_CRSP", "CRSP_NO_TRADE", "AGREE"], "DISAGREE")
    adj_ok = trade & (r["cfacpr"] > 0) & (r["cfacpr_last"] > 0)
    r["crsp_split_adj"] = np.where(adj_ok, r["prc"] / r["cfacpr"] * r["cfacpr_last"], np.nan)
    r["diff_split_adj"] = r["close"] - r["crsp_split_adj"]
    r["split_adj_category"] = np.select(
        [~adj_ok, np.abs(r["diff_split_adj"]) <= tol], ["NOT_COMPARABLE", "AGREE"], "DISAGREE")
    return r.drop(columns="_merge")


def crsp_only_dates(mapped: pd.DataFrame, crsp: pd.DataFrame) -> pd.DataFrame:
    """CRSP trade dates for a mapped permno, inside that ticker's panel window, the panel lacks."""
    m = mapped[mapped["map_status"] == "MAPPED"]
    if m.empty:
        return pd.DataFrame(columns=["ticker", "permno", "date"])
    win = m.groupby(["ticker", "permno"])["date"].agg(["min", "max"]).reset_index()
    c = crsp[["permno", "date", "prc"]].copy()
    c["date"] = pd.to_datetime(c["date"]).dt.normalize()
    c = c.merge(win, on="permno")
    c = c[(c["date"] >= c["min"]) & (c["date"] <= c["max"])]
    have = set(zip(m["ticker"], m["date"]))
    mask = [(t, d) not in have for t, d in zip(c["ticker"], c["date"])]
    return c.loc[mask, ["ticker", "permno", "date", "prc"]].reset_index(drop=True)


def summarise(rows: pd.DataFrame, mapped: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    """Per-ticker counts. Medians of the ratio are shown, never a blended price."""
    out = []
    for t in universe:
        mt = mapped[mapped["ticker"] == t]
        rt = rows[rows["ticker"] == t]
        cmp_ = rt[rt["category"].isin(["AGREE", "DISAGREE"])]
        adj = rt[rt["split_adj_category"].isin(["AGREE", "DISAGREE"])]
        out.append({
            "ticker": t,
            "permnos": ",".join(str(int(p)) for p in sorted(mt["permno"].dropna().unique())) or "-",
            "overlap_from": cmp_["date"].min().date() if len(cmp_) else None,
            "overlap_to": cmp_["date"].max().date() if len(cmp_) else None,
            "unmapped": int((mt["map_status"] == "UNMAPPED").sum()),
            "ambiguous": int((mt["map_status"] == "AMBIGUOUS").sum()),
            "compared": len(cmp_),
            "raw_agree": int((cmp_["category"] == "AGREE").sum()),
            "raw_disagree": int((cmp_["category"] == "DISAGREE").sum()),
            "adj_agree": int((adj["split_adj_category"] == "AGREE").sum()),
            "adj_disagree": int((adj["split_adj_category"] == "DISAGREE").sum()),
            "crsp_no_trade": int((rt["category"] == "CRSP_NO_TRADE").sum()),
            "not_in_crsp": int((rt["category"] == "NOT_IN_CRSP").sum()),
            "median_ratio_raw": float((cmp_["close"] / cmp_["prc"]).median()) if len(cmp_) else None,
            "max_abs_diff_raw": float(cmp_["diff_raw"].abs().max()) if len(cmp_) else None,
        })
    return pd.DataFrame(out)


def fetch_crsp(con, base: str, universe: list[str], lo: pd.Timestamp, hi: pd.Timestamp):
    """stocknames rows for the universe tickers, then dsf rows for their permnos."""
    names = con.execute(
        f"SELECT permno, ticker, namedt, nameenddt, shrcd, comnam "
        f"FROM read_parquet('{base}/wrds/crsp_a_stock/stocknames.parquet') "
        f"WHERE ticker IN ({','.join('?' * len(universe))})", list(universe)).df()
    permnos = sorted(int(p) for p in names["permno"].unique())
    if not permnos:
        raise CrossCheckError("no universe ticker appears in crsp_a_stock.stocknames")
    crsp = con.execute(
        f"SELECT permno, date, prc, cfacpr "
        f"FROM read_parquet('{base}/wrds/crsp_a_stock/dsf.parquet') "
        f"WHERE permno IN ({','.join('?' * len(permnos))}) AND date BETWEEN ? AND ?",
        permnos + [lo.date(), hi.date()]).df()
    return names, crsp


def render(run_utc: str, panel_last: pd.Timestamp, crsp_last, names: pd.DataFrame,
           summary: pd.DataFrame, rows: pd.DataFrame, extra: pd.DataFrame, ok: bool) -> str:
    L = ["# CEF price panel vs CRSP daily (independent-source check)", "",
         f"**Run:** {run_utc} UTC by `scripts/data/cef_crosscheck_crsp.py`.",
         f"Panel `data/cef/cef_prices.parquet` last date {panel_last.date()} (yfinance); "
         f"CRSP `crsp_a_stock.dsf` rows fetched through {crsp_last}. "
         "The overlap ends where CRSP ends.",
         f"Tolerance: |panel - CRSP| <= ${TOL_USD}. RAW and SPLIT_ADJ are separate "
         "comparisons; nothing is averaged.",
         f"**Verdict: {'PASS' if ok else 'FAIL'}** "
         "(PASS = every ticker mapped, none ambiguous, every RAW comparable row agrees).", "",
         "## Ticker -> PERMNO name records (crsp_a_stock.stocknames)", "",
         names.sort_values(["ticker", "namedt"]).to_markdown(index=False), "",
         "## Per ticker", "", summary.to_markdown(index=False), ""]
    dis = rows[rows["category"] == "DISAGREE"].copy()
    L += ["## Largest RAW disagreements (per ticker, up to %d)" % N_WORST, ""]
    if dis.empty:
        L += ["None.", ""]
    else:
        dis["abs"] = dis["diff_raw"].abs()
        top = (dis.sort_values("abs", ascending=False).groupby("ticker").head(N_WORST)
               .sort_values(["ticker", "date"]))
        L += [top[["ticker", "date", "permno", "close", "prc", "diff_raw", "cfacpr",
                   "crsp_split_adj", "split_adj_category"]].to_markdown(index=False), ""]
    L += ["## CRSP trade dates the panel lacks (inside each ticker's panel window)", ""]
    L += [(extra.groupby("ticker").size().rename("n").reset_index().to_markdown(index=False)
           if not extra.empty else "None."), ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    from scripts.cef.spec import UNIVERSE
    from src.data import r2

    panel = load_panel(PANEL_PATH, list(UNIVERSE))
    cfg = r2.load_config()
    con = r2.connect(cfg)
    names, crsp = fetch_crsp(con, f"s3://{cfg.bucket}", list(UNIVERSE),
                             panel["date"].min(), panel["date"].max())
    if crsp.empty:
        raise CrossCheckError("CRSP dsf returned no rows for the mapped permnos in the panel window")
    crsp_last = pd.to_datetime(crsp["date"]).max()
    # Compare only inside CRSP's coverage: a panel date after CRSP's last row is
    # not a disagreement, it is outside the check.
    in_window = panel[panel["date"] <= crsp_last]
    mapped = map_permnos(in_window, names)
    rows = compare(mapped, crsp)
    extra = crsp_only_dates(mapped, crsp)
    summary = summarise(rows, mapped, list(UNIVERSE))
    ok = bool((summary["unmapped"] == 0).all() and (summary["ambiguous"] == 0).all()
              and (summary["raw_disagree"] == 0).all() and (summary["compared"] > 0).all())
    run_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    md = render(run_utc, panel["date"].max(), crsp_last.date(), names, summary, rows, extra, ok)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"cef_crosscheck_crsp_{run_utc[:10]}.md"
    out.write_text(md + "\n")
    rows[rows["category"] != "AGREE"].to_csv(out.with_suffix(".nonagree.csv"), index=False)
    print(summary.to_string(index=False))
    print(f"\nwrote {out}  verdict {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
