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

`--returns` (added 2026-10-14, trial C4's data gate DG-C4-1)
-------------------------------------------------------------
    python3 scripts/data/stage_crsp_cef_families.py --returns

Stages CRSP's own `ret` and `retx` for the C4 pool (the 105 funds of
`scripts/cef/c4_feasibility.py::declare_pool`, which include QQQX's
predecessor rows) to `results/cef/c4/_cache_c4/crsp_ret_families.parquet`,
a gitignored cache (`results/**/_cache_*`; CRSP is licensed and the
repository is public). It does NOT re-decide the ticker -> permno mapping:
it reads the (permno, date, ticker) rows the panel build above already
chose (`crsp_dsf_raw.parquet`, read-only) and attaches `ret` and `retx`
from `dsf` to exactly those rows, so the returns and the prices can never
disagree about which security a row is. Every staged row must find exactly
one `dsf` row; a miss or a duplicate raises. `ret` is CRSP's as published:
NaN where CRSP has none, never filled (the trial's H15 check decides what a
NaN means). Nothing is written under data/, which a trial worktree may hold
read-only. A CRSP return is a return on the fund, not on C4; this stages
data and computes no statistic.
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


RET_CACHE = REPO / "results" / "cef" / "c4" / "_cache_c4" / "crsp_ret_families.parquet"
RET_COLS = ["permno", "date", "ret", "retx"]
# Ticker -> permno corrections to the map in data/cef_families/crsp_permno_map.csv, applied to the
# C4 return cache only (data/ is never written from a trial worktree). Each is VERIFIED every time
# it is staged (`verify_override`): a CEF share code on every name record, and the CRSP closing
# print equal to the yfinance close within $0.005 on at least OVERRIDE_MIN_AGREE of common days.
#   BTX (2026-10-15, the independent review of C4's fit at 3be92cd): the map's 76963 is NTN
#   Buzztime -> Brooklyn Immunotherapeutics -> Eterna Therapeutics (share code 11), which matched
#   0 of 446 yfinance closes; the date-range join tied BTX's 2021-22 bars to Brooklyn
#   Immunotherapeutics, which used the ticker then. yfinance's BTX history is BIGZ's: BlackRock
#   Innovation & Growth Term Trust, renamed BTX on 2025-02-18 (docs/REFERENCES.md §12k). CRSP
#   stocknames: permno 20674, ticker BIGZ, share code 44, NYSE, 2021-03-26 -> 2024-12-31.
PERMNO_OVERRIDES = {"BTX": (76963, 20674)}       # ticker: (wrong permno, correct permno)
OVERRIDE_MIN_AGREE = 0.99


def attach_returns(raw: pd.DataFrame, rets: pd.DataFrame) -> pd.DataFrame:
    """`raw` (permno, date, ticker, prc, vol, cfacpr) with CRSP's `ret`/`retx` attached. Pure.

    One `dsf` row per staged (permno, date), or it raises: a missing row would
    leave a price with no return, and a duplicate would make the return
    ambiguous. Neither is resolved here."""
    r = rets.copy()
    r["date"] = pd.to_datetime(r["date"]).dt.normalize().astype("datetime64[ns]")
    r["permno"] = r["permno"].astype("int64")
    for c in ("ret", "retx"):
        r[c] = r[c].astype(float)
    dup = r.duplicated(["permno", "date"], keep=False)
    if dup.any():
        raise FamiliesDataError(f"dsf holds two rows for one (permno, date): {r.loc[dup].head().to_dict('records')}")
    x = raw[["permno", "date", "ticker", "prc", "vol", "cfacpr"]].copy()
    x["permno"] = x["permno"].astype("int64")
    x["date"] = pd.to_datetime(x["date"]).dt.normalize().astype("datetime64[ns]")
    j = x.merge(r, on=["permno", "date"], how="left", indicator=True)
    miss = j["_merge"] != "both"
    if miss.any():
        raise FamiliesDataError(f"{int(miss.sum())} staged rows have no dsf row for their own (permno, date): "
                                f"{j.loc[miss, ['ticker', 'permno', 'date']].head().to_dict('records')}")
    if len(j) != len(x):
        raise FamiliesDataError("attaching returns changed the row count")
    return j.drop(columns="_merge").sort_values(["ticker", "date"]).reset_index(drop=True)


def attach_shrcd(rows: pd.DataFrame, names: pd.DataFrame) -> pd.DataFrame:
    """Each row's CRSP share code from the name record in force on its date. Pure.
    A row no name record covers gets NaN (the identity check in c4_families then refuses it)."""
    nm = names.copy()
    nm["namedt"], nm["nameenddt"] = pd.to_datetime(nm["namedt"]), pd.to_datetime(nm["nameenddt"])
    nm["permno"] = nm["permno"].astype("int64")
    j = rows.reset_index().merge(nm, on="permno", how="left")
    j = j[(j["date"] >= j["namedt"]) & (j["date"] <= j["nameenddt"])]
    if j.duplicated("index").any():
        raise FamiliesDataError("two CRSP name records cover one (permno, date)")
    out = rows.copy()
    out["shrcd"] = j.set_index("index")["shrcd"].reindex(out.index)
    return out


def verify_override(ticker: str, dsf: pd.DataFrame, shrcds: set, yf_close: pd.DataFrame) -> dict:
    """The checks a permno override must pass, or raise. Pure."""
    if not shrcds or not shrcds <= CEF_SHRCD:
        raise FamiliesDataError(f"{ticker}: override permno has share codes {sorted(shrcds)}, not a CEF's {sorted(CEF_SHRCD)}")
    j = dsf.merge(yf_close, on="date", how="inner")
    tr = j[j["prc"] > 0]
    agree = int(((tr["close"] - tr["prc"]).abs() <= 0.005).sum())
    share = agree / len(tr) if len(tr) else 0.0
    if share < OVERRIDE_MIN_AGREE:
        raise FamiliesDataError(f"{ticker}: override permno agrees with the yfinance close on {agree} of {len(tr)} "
                                f"days ({share:.2%}), below {OVERRIDE_MIN_AGREE:.0%}")
    return dict(compared=len(tr), agree=agree, share=share)


def apply_overrides(out: pd.DataFrame, con, cfg) -> pd.DataFrame:
    """Replace each overridden ticker's rows with its verified permno's dsf rows."""
    from src.data import r2
    px = pd.read_parquet(OUT_DIR / PRICES, columns=["date", "ticker", "close"])
    px["date"] = pd.to_datetime(px["date"])
    for tk, (wrong, right) in PERMNO_OVERRIDES.items():
        if tk not in set(out["ticker"]):
            continue
        have = set(out.loc[out["ticker"] == tk, "permno"])
        if have != {wrong}:
            raise FamiliesDataError(f"{tk}: expected the map's permno {wrong} to override, found {sorted(have)}")
        d = con.execute(f"SELECT permno, date, prc, vol, cfacpr, ret, retx FROM "
                        f"read_parquet('{r2.r2_path('crsp_a_stock', 'dsf', cfg)}') WHERE permno = ?", [right]).df()
        d["date"] = pd.to_datetime(d["date"]).dt.normalize().astype("datetime64[ns]")
        for c in ("prc", "vol", "ret", "retx"):
            d[c] = d[c].astype(float)
        d["permno"] = d["permno"].astype("int64")
        sc = con.execute(f"SELECT DISTINCT shrcd FROM read_parquet('{r2.r2_path('crsp_a_stock', 'stocknames', cfg)}') "
                         f"WHERE permno = ?", [right]).df()["shrcd"]
        v = verify_override(tk, d, {int(x) for x in sc.dropna()}, px[px["ticker"] == tk][["date", "close"]])
        print(f"override {tk}: permno {wrong} -> {right} ({len(d)} dsf rows, {d['date'].min().date()}.."
              f"{d['date'].max().date()}); CRSP print = yfinance close within $0.005 on {v['agree']} of "
              f"{v['compared']} days ({v['share']:.2%})")
        out = pd.concat([out[out["ticker"] != tk], d.assign(ticker=tk)[out.columns]], ignore_index=True)
    return out.sort_values(["ticker", "date"]).reset_index(drop=True)


def stage_returns() -> int:
    """DG-C4-1: CRSP `ret`/`retx` for the C4 pool, to RET_CACHE (see the module docstring)."""
    from scripts.cef.c4_feasibility import NAMES_CSV, declare_pool
    from src.data import r2
    pool, _ = declare_pool(pd.read_csv(NAMES_CSV))
    assert_no_universe_names(pool, cef_universe_names())
    rawp = OUT_DIR / "crsp_dsf_raw.parquet"
    if not rawp.exists():
        raise FamiliesDataError(f"{rawp} does not exist: run this script without --returns first")
    raw = pd.read_parquet(rawp)
    raw = raw[raw["ticker"].isin(pool)]
    missing = sorted(set(pool) - set(raw["ticker"]))
    if missing:
        raise FamiliesDataError(f"pool funds with no staged CRSP rows: {missing}")
    perms = sorted(int(p) for p in raw["permno"].unique())
    cfg = r2.load_config()
    con = r2.connect(cfg)
    rets = con.execute(
        f"SELECT {', '.join(RET_COLS)} FROM read_parquet('{r2.r2_path('crsp_a_stock', 'dsf', cfg)}') "
        f"WHERE permno IN ({','.join('?' * len(perms))})", perms).df()
    out = attach_returns(raw, rets)
    out = apply_overrides(out, con, cfg)
    names = con.execute(
        f"SELECT permno, namedt, nameenddt, shrcd FROM read_parquet('{r2.r2_path('crsp_a_stock', 'stocknames', cfg)}') "
        f"WHERE permno IN ({','.join('?' * out['permno'].nunique())})", sorted(int(p) for p in out["permno"].unique())).df()
    out = attach_shrcd(out, names)
    RET_CACHE.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(RET_CACHE, index=False)
    per = out.groupby("ticker").agg(rows=("date", "size"), first=("date", "min"), last=("date", "max"),
                                    ret_nan=("ret", lambda s: int(s.isna().sum())),
                                    permnos=("permno", lambda s: " ".join(map(str, sorted(set(s))))))
    print(f"staged CRSP ret/retx: {len(out):,} rows, {out['ticker'].nunique()} pool funds, "
          f"{out['date'].min().date()}..{out['date'].max().date()} -> {RET_CACHE.relative_to(REPO)}")
    print(f"rows with no CRSP ret: {int(out['ret'].isna().sum())} (by fund below; never filled)")
    print(per[per["ret_nan"] > 0].to_string())
    print("funds on more than one permno:", per[per["permnos"].str.contains(" ")].to_dict("index"))
    return 0


def main(argv=None) -> int:
    pd.set_option("compute.use_numexpr", False)        # scripts/events/numexpr_fault.py
    if argv is None:
        argv = sys.argv[1:]
    if "--returns" in argv:
        return stage_returns()
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
