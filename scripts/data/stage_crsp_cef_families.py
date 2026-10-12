"""CRSP daily prices for the C4 family CEFs, from the R2 WRDS mirror (licensed; never committed).

    export QUANTT_ENV_FILE=<absolute path to the env file holding the R2 keys>
    python3 scripts/data/stage_crsp_cef_families.py

Run after fetch_cef_families_yf.py: the yfinance panel's dates are what tie a
ticker to a PERMNO. Writes, under data/cef_families/ (gitignored, `/data/`):

    cef_prices_crsp.parquet   date open high low close volume ticker grp   (the live schema)
    crsp_dsf_raw.parquet      permno date prc vol openprc askhi bidlo cfacpr cfacshr shrout ticker
    crsp_permno_map.csv       ticker -> permno(s), share codes, name records

WHY CRSP, AND WHERE IT IS "BETTER"
----------------------------------
CRSP `dsf` is built from exchange data independently of Yahoo, so it is the
second price source (docs/DATA.md §4 did the same for the live 13). It is
better than yfinance in three specific ways, each measured by
`cef_families_quality.py` rather than assumed:
  * it says when there was NO closing trade (negative `prc` = minus the
    bid/ask midpoint). yfinance prints a bar on such days;
  * its `prc` is the raw print, on the share basis of its own day, so a split
    that yfinance back-adjusts is visible as a constant ratio;
  * for some funds it starts before yfinance does.
It is worse in one: **the mirror ends 2024-12-31** (R2_CATALOG), so it cannot
carry a panel to today. Hence a separate file in the same schema, never spliced
into the yfinance panel, and the choice between them is the C4
pre-registration's to make, with the agreement table in front of it.

TICKER -> PERMNO: THE FUND IT IS TODAY, THEN BACK THROUGH ITS OWN PERMNO.
Tickers are recycled (DSL was Downey Financial until 2008; `docs/DATA.md`
§4), and yfinance carries a fund's history back through its own earlier
tickers (STEW's yfinance bars run from 1980, when the fund was USLIFE Income,
ticker UIF). A plain date-range join of the yfinance dates to `stocknames`
therefore mis-maps: on 2026-10-12 it tied STEW's 1980-93 bars to Stewart
Sandwiches (share code 10/11), AEF's 1990-97 bars to Alliance Global
Environment Fund and CRF's 1994-2002 bars to the Czech Republic Fund, none of
which is the fund. So:
  * the CURRENT permno is the one whose `stocknames` record covers the
    ticker on the latest yfinance date inside CRSP's coverage (the
    date-range join of `cef_crosscheck_crsp.map_permnos`, on that one date);
  * that permno's WHOLE dsf history is kept, under any earlier ticker: it is
    the same security;
  * another permno that carried the ticker is added only on dates BEFORE the
    current permno's first dsf row, only inside its own name record for this
    ticker, and only if every such record has a CEF share code (14/44). That
    admits a reorganised predecessor (QQQX: permno 91745 to 2014-12-19, then
    15136 from 2014-12-22) and refuses an unrelated company. Such rows are
    counted per ticker (`predecessor_rows`) so the C4 pre-registration can
    decide whether to use them.
A ticker with no CRSP record on any yfinance date is reported; nothing is
guessed.

PANEL ROWS. `close = prc` only where `prc > 0` (a closing trade). No-trade rows
are kept in `crsp_dsf_raw.parquet` for the cross-check and left out of the
panel, counted. `open = openprc`, `high = askhi`, `low = bidlo` (on a trade
day CRSP's askhi/bidlo are the day's high and low). A trade row with no `vol`
is dropped and counted: `volume` is int64 in the live schema.

The 2023-01-01 time holdout: these are prices, not returns, and the mirror
ends 2024-12-31. Nothing here computes a return.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.data.cef_families_common import (  # noqa: E402
    OUT_DIR, PRICES, PRICES_CRSP, FamiliesDataError, assert_no_universe_names, cef_universe_names,
    included, load_universe, write_frame)

DSF_COLS = ["permno", "date", "prc", "vol", "openprc", "askhi", "bidlo", "cfacpr", "cfacshr", "shrout"]


def permno_map(px: pd.DataFrame, names: pd.DataFrame, crsp_last: pd.Timestamp) -> pd.DataFrame:
    """Per ticker: the CURRENT permno (module docstring) and every permno the
    date-range join ties to any of its yfinance dates, with row counts."""
    from scripts.data.cef_crosscheck_crsp import map_permnos
    m = map_permnos(px[["ticker", "date"]], names)
    rows = []
    for tk, g in m.groupby("ticker"):
        ok = g[g["map_status"] == "MAPPED"]
        inside = ok[ok["date"] <= crsp_last]
        cur = int(inside.loc[inside["date"].idxmax(), "permno"]) if len(inside) else None
        joined = sorted(int(p) for p in ok["permno"].unique())
        rows.append({"ticker": tk, "current_permno": cur,
                     "other_permnos": " ".join(str(p) for p in joined if p != cur),
                     "yf_rows": len(g), "join_mapped_rows": len(ok),
                     "join_unmapped_rows": int((g["map_status"] == "UNMAPPED").sum()),
                     "join_ambiguous_rows": int((g["map_status"] == "AMBIGUOUS").sum())})
    return pd.DataFrame(rows)


CEF_SHRCD = {14, 44}


def build_panel(dsf: pd.DataFrame, pmap: pd.DataFrame, names: pd.DataFrame,
                fam: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(panel rows in the live schema, raw rows tagged with ticker, per-ticker counts). Pure.

    `names` holds the stocknames records of every permno in `pmap` (all tickers)."""
    nm = names.copy()
    nm["namedt"], nm["nameenddt"] = pd.to_datetime(nm["namedt"]), pd.to_datetime(nm["nameenddt"])
    d = dsf.copy()
    # DuckDB hands back datetime64[us]; the live schema is datetime64[ns]
    d["date"] = pd.to_datetime(d["date"]).dt.normalize().astype("datetime64[ns]")
    raw, counts = [], []
    for _, r in pmap.iterrows():
        tk, cur = r["ticker"], r["current_permno"]
        if cur is None or pd.isna(cur):
            counts.append({"ticker": tk, "crsp_rows": 0}); continue
        x = d[d["permno"] == int(cur)].copy()
        first_cur = x["date"].min() if len(x) else pd.Timestamp.max
        added, refused = [], []
        others = [int(v) for v in str(r.get("other_permnos") or "").split()]
        for p in others:
            rng = nm[(nm["permno"] == p) & (nm["ticker"] == tk)]
            if rng.empty or not set(rng["shrcd"].dropna().astype(int)) <= CEF_SHRCD:
                refused.append(p); continue
            xp = d[(d["permno"] == p) & (d["date"] < first_cur)]
            keep = np.zeros(len(xp), bool)
            for _, q in rng.iterrows():
                keep |= ((xp["date"] >= q["namedt"]) & (xp["date"] <= q["nameenddt"])).to_numpy()
            if keep.any():
                added.append(xp[keep])
        pred_rows = sum(len(a) for a in added)
        x = pd.concat([x] + added) if added else x
        if x.duplicated("date").any():
            raise FamiliesDataError(f"{tk}: two CRSP rows on one date")
        x["ticker"] = tk
        raw.append(x)
        trade = x["prc"] > 0
        counts.append({"ticker": tk, "crsp_rows": len(x), "crsp_trade_rows": int(trade.sum()),
                       "crsp_no_trade_rows": int((~trade).sum()),
                       "crsp_trade_rows_no_vol": int((trade & x["vol"].isna()).sum()),
                       "predecessor_rows": pred_rows,
                       "predecessor_permnos_used": " ".join(str(int(a["permno"].iloc[0])) for a in added),
                       "permnos_refused": " ".join(map(str, refused)),
                       "crsp_first": x["date"].min(), "crsp_last": x["date"].max()})
    R = pd.concat(raw, ignore_index=True)
    t = R[(R["prc"] > 0) & R["vol"].notna()]
    P = pd.DataFrame({"date": t["date"], "open": t["openprc"].astype(float), "high": t["askhi"].astype(float),
                      "low": t["bidlo"].astype(float), "close": t["prc"].astype(float),
                      "volume": t["vol"].astype("int64"), "ticker": t["ticker"],
                      "grp": t["ticker"].map(fam)})
    if P["grp"].isna().any():
        raise FamiliesDataError(f"no family for {sorted(P.loc[P.grp.isna(), 'ticker'].unique())}")
    return P.sort_values(["ticker", "date"]).reset_index(drop=True), R, pd.DataFrame(counts)


def main(argv=None) -> int:
    pd.set_option("compute.use_numexpr", False)        # scripts/events/numexpr_fault.py
    from src.data import r2
    u = included(load_universe())
    the44 = cef_universe_names()
    assert_no_universe_names(u["ticker"], the44)
    pxp = OUT_DIR / PRICES
    if not pxp.exists():
        raise FamiliesDataError(f"{pxp} does not exist: run fetch_cef_families_yf.py first")
    px = pd.read_parquet(pxp, columns=["date", "ticker"])
    px["date"] = pd.to_datetime(px["date"]).dt.normalize()
    tickers = sorted(px["ticker"].unique())
    cfg = r2.load_config()
    con = r2.connect(cfg)
    base = f"s3://{cfg.bucket}"
    names = con.execute(
        f"SELECT permno, ticker, namedt, nameenddt, shrcd, comnam "
        f"FROM read_parquet('{base}/wrds/crsp_a_stock/stocknames.parquet') "
        f"WHERE ticker IN ({','.join('?' * len(tickers))})", tickers).df()
    crsp_last = pd.Timestamp(con.execute(
        f"SELECT max(date) FROM read_parquet('{base}/wrds/crsp_a_stock/dsf.parquet')").fetchone()[0])
    pmap = permno_map(px, names, crsp_last)
    perms = sorted({int(p) for p in pmap["current_permno"].dropna()} |
                   {int(p) for s in pmap["other_permnos"].fillna("") for p in str(s).split()})
    if not perms:
        raise FamiliesDataError("no family ticker maps to a CRSP permno on any yfinance date")
    dsf = con.execute(
        f"SELECT {', '.join(DSF_COLS)} FROM read_parquet('{base}/wrds/crsp_a_stock/dsf.parquet') "
        f"WHERE permno IN ({','.join('?' * len(perms))})", perms).df()
    allnames = con.execute(
        f"SELECT permno, ticker, namedt, nameenddt, shrcd, comnam "
        f"FROM read_parquet('{base}/wrds/crsp_a_stock/stocknames.parquet') "
        f"WHERE permno IN ({','.join('?' * len(perms))})", perms).df()
    fam = dict(zip(u["ticker"], u["family"]))
    P, R, counts = build_panel(dsf, pmap, allnames, fam)
    assert_no_universe_names(P["ticker"].unique(), the44)
    cur_shr = (allnames.groupby("permno")["shrcd"]
               .agg(lambda s: " ".join(str(int(v)) for v in sorted(set(s.dropna())))))
    pmap["current_shrcds"] = pmap["current_permno"].map(lambda p: cur_shr.get(int(p), "?") if pd.notna(p) else "")
    pmap = pmap.merge(counts, on="ticker", how="left")
    write_frame(P, PRICES_CRSP)
    write_frame(R[DSF_COLS + ["ticker"]], "crsp_dsf_raw.parquet")
    write_frame(pmap, "crsp_permno_map.csv")
    write_frame(allnames, "crsp_stocknames_mapped.csv")
    print(f"CRSP last {crsp_last.date()}: current permno for {int(pmap.current_permno.notna().sum())} of "
          f"{len(pmap)} tickers; unmapped {pmap.loc[pmap.current_permno.isna(), 'ticker'].tolist()}")
    print("predecessor rows used:", pmap.loc[pmap.predecessor_rows.fillna(0) > 0,
                                             ["ticker", "predecessor_permnos_used", "predecessor_rows"]].to_dict("records"))
    print("permnos refused:", pmap.loc[pmap.permnos_refused.fillna("") != "", ["ticker", "permnos_refused"]].to_dict("records"))
    print(f"panel rows {len(P):,}, last {P.date.max().date()}; dsf rows {len(R):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
