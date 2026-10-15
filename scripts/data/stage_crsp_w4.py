"""Stage CRSP daily rows for the deployed CEFs and the W4 bond-ETF proxies,
2004-01-01 .. 2022-12-31, from the R2 WRDS mirror into a gitignored cache.

    python3 scripts/data/stage_crsp_w4.py

WHY CRSP, AND WHY THESE COLUMNS
-------------------------------
W4 (results/cef/RESEARCH_PLAN_2026-10-09.md item 0.6) needs three things the
live yfinance panels cannot give:

* an INDEPENDENT total return: CRSP `ret` includes every distribution on its
  ex-date and `retx` excludes ordinary ones, so `ret - retx` is CRSP's own
  distribution yield -- a second source for `cef_distributions.parquet`;
* the closing BID and ASK (`bid`, `ask`), so the discount and the forward return
  can be rebuilt on the quote midpoint, which carries no bid-ask bounce;
* total returns of live-priced bond ETFs (MUB, HYG, JNK, LQD, IEF, BKLN) for
  the stale-NAV lead-lag regressions -- from one primary source, rather than
  the `data/rv/` panels whose fetchers were deleted in the clean slate (plan
  item 0.1 restores them).

THE TIME HOLDOUT. The query stops at 2022-12-31: the 2023-01-01 holdout is
sealed (CLAUDE.md research rules), and a row that is never fetched cannot leak.

TICKER -> PERMNO. By date range through `crsp_a_stock.stocknames`, as
`scripts/data/cef_crosscheck_crsp.py` does, restricted to the share codes that
identify the instrument: 14/44 (closed-end funds) for the CEFs, 73 (ETFs) for
the proxies. Tickers are recycled (DSL was Downey Financial until 2008; MUB was
Mueller Brass in the 1960s), which is why the share code is part of the key.
A ticker that maps to two permnos on one date raises; one that maps to none on
any date the deployed panel has is reported by the caller, not filled.

WHERE IT WRITES. `results/cef/w4/_cache_w4/crsp_dsf_w4.parquet`, gitignored
(`results/**/_cache_*`). CRSP is licensed data and this repository is public:
nothing fetched here is committed.

CRSP CONVENTIONS KEPT AS PUBLISHED: a negative `prc` means no closing trade
(minus the bid/ask average); `bid`/`ask` are the closing quotes; `ret` is
NaN where CRSP has none. Nothing is filled.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
CACHE = REPO / "results" / "cef" / "w4" / "_cache_w4"
OUT = CACHE / "crsp_dsf_w4.parquet"
LO, HI = "2004-01-01", "2022-12-31"           # HI: last day before the sealed holdout
# --holdout (added 2026-10-15, trial C5's holdout bad-close check, team lead's ruling of
# 2026-10-14): CRSP prc for 2023-2024 -- R2's CRSP ends 2024-12-31 -- to its own file,
# refused until C5's fit verdict is committed (the auction fetcher's gate).
HOLDOUT_LO, HOLDOUT_HI = "2023-01-01", "2024-12-31"
OUT_HOLDOUT = CACHE / "crsp_dsf_holdout_2023_2024.parquet"
PROXIES = ["MUB", "HYG", "JNK", "LQD", "IEF", "BKLN"]
CEF_SHRCD = {14, 44}
ETF_SHRCD = {73}
COLS = ["permno", "date", "prc", "bid", "ask", "bidlo", "askhi", "openprc",
        "vol", "numtrd", "ret", "retx", "cfacpr", "shrout"]


class StageError(RuntimeError):
    pass


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true")
    a = ap.parse_args(argv)
    lo, hi, out = LO, HI, OUT
    if a.holdout:
        from scripts.data.fetch_alpaca_auction_history import fit_verdict_committed
        ok, why = fit_verdict_committed()
        if not ok:
            raise StageError(f"--holdout refused: C5's fit verdict is not committed ({why})")
        lo, hi, out = HOLDOUT_LO, HOLDOUT_HI, OUT_HOLDOUT
    from scripts.cef.spec import UNIVERSE
    from src.data import r2
    cfg = r2.load_config()
    con = r2.connect(cfg)
    want = {t: CEF_SHRCD for t in UNIVERSE} | {t: ETF_SHRCD for t in PROXIES}
    names = con.execute(
        f"SELECT permno, ticker, namedt, nameenddt, shrcd, comnam FROM "
        f"read_parquet('{r2.r2_path('crsp_a_stock', 'stocknames', cfg)}') "
        f"WHERE ticker IN ({','.join('?' * len(want))})", list(want)).df()
    names["namedt"] = pd.to_datetime(names["namedt"])
    names["nameenddt"] = pd.to_datetime(names["nameenddt"])
    keep = names[[int(s) in want[t] for t, s in zip(names.ticker, names.shrcd)]]
    keep = keep[(keep.nameenddt >= lo) & (keep.namedt <= hi)]
    missing = sorted(set(want) - set(keep.ticker))
    if missing:
        raise StageError(f"no CRSP name record with the expected share code for {missing}")
    permnos = sorted(int(p) for p in keep.permno.unique())
    dsf = con.execute(
        f"SELECT {', '.join(COLS)} FROM "
        f"read_parquet('{r2.r2_path('crsp_a_stock', 'dsf', cfg)}') "
        f"WHERE permno IN ({','.join('?' * len(permnos))}) AND date BETWEEN ? AND ?",
        permnos + [lo, hi]).df()
    dsf["date"] = pd.to_datetime(dsf["date"])
    # attach the ticker by date range; a (permno, date) covered by two tickers raises
    j = dsf.merge(keep[["permno", "ticker", "namedt", "nameenddt", "shrcd"]], on="permno")
    j = j[(j.date >= j.namedt) & (j.date <= j.nameenddt)]
    dup = j.duplicated(["ticker", "date"], keep=False)
    if dup.any():
        raise StageError(f"(ticker, date) covered twice: {j.loc[dup, ['ticker', 'date', 'permno']].head()}")
    j = j.drop(columns=["namedt", "nameenddt"])
    for c in ["prc", "bid", "ask", "bidlo", "askhi", "openprc", "ret", "retx"]:
        j[c] = j[c].astype(float)
    if j.date.min() < pd.Timestamp(lo) or j.date.max() > pd.Timestamp(hi):
        raise StageError(f"a row outside {lo}..{hi} was staged")
    CACHE.mkdir(parents=True, exist_ok=True)
    j.sort_values(["ticker", "date"]).to_parquet(out, index=False)
    print(f"staged {len(j)} rows, {j.ticker.nunique()} tickers, {j.date.min().date()}.."
          f"{j.date.max().date()} -> {out.relative_to(REPO)}")
    print(keep.sort_values(["ticker", "namedt"]).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
