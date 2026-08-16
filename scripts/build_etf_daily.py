#!/usr/bin/env python3
"""Build data/etf_daily.parquet: daily TOTAL RETURN panel for the 9 credit/rates ETFs.

Columns: [date, ticker, permno, ret_total, ret_px, prc_adj, volume, source].

CRSP leg (inception .. 2024-12-31): R2 wrds/crsp_a_stock/dsf.parquet.
  The R2 manifest (wrds/manifest.json) describes per-year source partitions
  crsp.dsf/2000..2025, but the physical mirror stores one combined
  dsf.parquet — glob-verified: no per-year objects exist in the bucket.
  2004-05 coverage was verified inside the combined file (504 trading days
  for the 2002-inception funds). The 2025 partition has 0 rows, hence the
  yfinance splice.
  - ret  = CRSP daily total return (distributions reinvested on ex-date).
  - retx = price-only return.
  - prc < 0 means CRSP recorded a bid/ask midpoint instead of a trade price
    (happens on zero-trade days: 30 ANGL rows, 38 FALN, 1 JNK) -> abs().
  - prc_adj = abs(prc)/cfacpr puts prices on the current share basis across
    the two real reverse splits in the panel: BIL 1:2 effective 2017-11-30
    (cfacpr 0.5 -> 1.0) and JNK 1:3 effective 2019-05-06 (1/3 -> 1.0).
  - ret is NULL only on each fund's inception day (asserted); those rows are
    dropped so ret_total is never NaN.

yfinance leg (2025-01-01 .. present): one download with auto_adjust=False +
actions=True, which returns raw Close, Adj Close, Dividends and Capital
Gains together (Adj Close here is numerically what auto_adjust=True would
put in Close). Two total-return candidates are computed:
  - adjclose: Adj Close pct_change (the spec's default), and
  - inhouse:  (Close + Div + CapGains) / prev Close - 1.
The 2024 overlap validation against CRSP ret picks, per ticker, the method
that passes max|diff| < 5 bp; if adjclose fails on dividend ex-dates
(yfinance back-propagates a rounded adjustment factor — see
archive/calendar-premia-v2/scripts/build_etf.py header) the inhouse TR is
used and the diagnostics are printed either way, never silently accepted.

Splice: yfinance rows strictly after each ticker's CRSP end date; the
yfinance bar immediately preceding the first spliced bar must BE the CRSP
end date (holiday-aware seam check), so the first spliced return accrues
exactly from the CRSP end close.

Bad-print repair (explicit, loud, table-driven): CRSP records the last
trade, and on 2013-08-02 ANGL's closing print was a stub-quote trade at
40.35 (closing bid 27.64, intraday askhi 40.35, 5,100 shares, NAV ~27.1)
producing a fake +48.9% / -32.5% two-day swing that fully reverses.
Yahoo's official consolidated close that day is 27.35 (within the day's
27.12-27.50 real range). BAD_PRINTS replaces the print with the Yahoo
close fetched at build time and recomputes the two affected returns,
preserving CRSP's dividend component (ret - retx). The 2008-10 HYG/JNK
+/-11-15% days are genuine crisis prints (300k-500k shares) and are kept.
A reversal scan prints any other |ret|>8% low-volume reversal candidates
for manual review; only rows in BAD_PRINTS are ever altered.

Run:  python3 scripts/build_etf_daily.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.data.r2 import connect, r2_path, q  # noqa: E402

OUT = REPO / "data" / "etf_daily.parquet"
YF_START = "2023-12-15"  # buffer: every 2024 overlap return must be computable
SPLICE_MAX_BP = 5.0      # acceptance gate on the 2024 overlap, per ticker

# Resolved ticker -> permno map (built/verified by scripts/build_permno_map.py;
# expected dsf ranges/rowcounts re-asserted here so a mirror change is loud).
PERMNOS = {
    "HYG":  {"permno": 91933, "first": "2007-04-11", "last": "2024-12-31", "n": 4463},
    "JNK":  {"permno": 92922, "first": "2007-12-04", "last": "2024-12-31", "n": 4298},
    "ANGL": {"permno": 13348, "first": "2012-04-11", "last": "2024-12-31", "n": 3202},
    "FALN": {"permno": 16094, "first": "2016-06-16", "last": "2024-12-31", "n": 2150},
    "SHY":  {"permno": 89470, "first": "2002-07-26", "last": "2024-12-31", "n": 5647},
    "BIL":  {"permno": 92027, "first": "2007-05-30", "last": "2024-12-31", "n": 4429},
    "IEF":  {"permno": 89469, "first": "2002-07-26", "last": "2024-12-31", "n": 5647},
    "LQD":  {"permno": 89467, "first": "2002-07-26", "last": "2024-12-31", "n": 5647},
    "TLT":  {"permno": 89468, "first": "2002-07-26", "last": "2024-12-31", "n": 5647},
}
TICKERS = list(PERMNOS)
BY_PERMNO = {v["permno"]: t for t, v in PERMNOS.items()}

# Known bad closing prints, repaired with Yahoo's official consolidated close
# (fetched at build time, sanity-bounded). Evidence in the module docstring.
BAD_PRINTS = {("ANGL", "2013-08-02"): "stub-quote close 40.35 vs bid 27.64, NAV ~27.1"}


def repair_bad_prints(df: pd.DataFrame) -> pd.DataFrame:
    """Replace known bad closing prints; recompute the print-day and next-day
    returns, preserving CRSP's dividend component (ret - retx)."""
    for (t, day), why in BAD_PRINTS.items():
        day = pd.Timestamp(day)
        y = yf.download(t, start=day - pd.Timedelta(days=7),
                        end=day + pd.Timedelta(days=7), auto_adjust=False,
                        progress=False)
        yclose = float(y["Close"].loc[day].iloc[0])
        sub = df[df["ticker"] == t].sort_values("date")
        i = sub.index[sub["date"] == day]
        assert len(i) == 1, f"{t} {day.date()}: bad-print row not found"
        i = i[0]
        pos = sub.index.get_loc(i)
        i_prev, i_next = sub.index[pos - 1], sub.index[pos + 1]
        prev_prc, next_prc = df.at[i_prev, "prc_adj"], df.at[i_next, "prc_adj"]
        assert abs(yclose / prev_prc - 1) < 0.05, \
            f"{t} {day.date()}: repair close {yclose} implausible vs prev {prev_prc}"
        old = (df.at[i, "ret_total"], df.at[i_next, "ret_total"], df.at[i, "prc_adj"])
        div_t = df.at[i, "ret_total"] - df.at[i, "ret_px"]
        div_n = df.at[i_next, "ret_total"] - df.at[i_next, "ret_px"]
        df.at[i, "prc_adj"] = yclose
        df.at[i, "ret_px"] = yclose / prev_prc - 1
        df.at[i, "ret_total"] = df.at[i, "ret_px"] + div_t
        df.at[i_next, "ret_px"] = next_prc / yclose - 1
        df.at[i_next, "ret_total"] = df.at[i_next, "ret_px"] + div_n
        print(f"  REPAIRED bad print {t} {day.date()} ({why}): prc {old[2]:.2f} -> "
              f"{yclose:.2f}; ret {old[0]:+.4f} -> {df.at[i, 'ret_total']:+.4f}; "
              f"next-day ret {old[1]:+.4f} -> {df.at[i_next, 'ret_total']:+.4f}")
    return df


def scan_reversals(df: pd.DataFrame) -> None:
    """Print (never alter) other bad-print candidates: |ret|>8% mostly reversed
    next day on thin volume. Repairs happen only via BAD_PRINTS."""
    for t in TICKERS:
        sub = df[df["ticker"] == t].sort_values("date").reset_index(drop=True)
        r, nxt = sub["ret_total"], sub["ret_total"].shift(-1)
        cand = sub[(r.abs() > 0.08) & (((1 + r) * (1 + nxt) - 1).abs() < 0.3 * r.abs())
                   & (sub["volume"] < 50_000)]
        for _, row in cand.iterrows():
            if (t, row["date"].strftime("%Y-%m-%d")) not in BAD_PRINTS:
                print(f"  WARNING unrepaired reversal candidate {t} "
                      f"{row['date'].date()} ret {row['ret_total']:+.2%} "
                      f"vol {row['volume']:.0f} — review before trusting")


def load_crsp() -> pd.DataFrame:
    con = connect()
    dsf = r2_path("crsp_a_stock", "dsf")
    plist = ",".join(str(v["permno"]) for v in PERMNOS.values())
    df = q(con, f"""
        SELECT date, permno,
               ret::DOUBLE          AS ret_total,
               retx::DOUBLE         AS ret_px,
               ABS(prc)::DOUBLE / cfacpr AS prc_adj,
               vol::DOUBLE          AS volume
        FROM read_parquet('{dsf}')
        WHERE permno IN ({plist})
        ORDER BY permno, date
    """)
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["permno"].map(BY_PERMNO)

    print("--- CRSP leg (wrds/crsp_a_stock/dsf.parquet) ---")
    for t in TICKERS:
        exp = PERMNOS[t]
        sub = df[df["ticker"] == t]
        d0, d1 = sub["date"].min(), sub["date"].max()
        assert (d0.date().isoformat(), d1.date().isoformat(), len(sub)) == \
            (exp["first"], exp["last"], exp["n"]), \
            f"{t}: dsf {d0.date()}..{d1.date()} n={len(sub)} != expected {exp}"
        nan_ret = sub[sub["ret_total"].isna()]
        assert list(nan_ret["date"]) == [d0], \
            f"{t}: NULL ret beyond inception day: {nan_ret['date'].tolist()}"
        assert sub["date"].is_unique
        assert sub["prc_adj"].notna().all() and (sub["prc_adj"] > 0).all()
        assert sub["volume"].notna().all()
        print(f"  {t:<5} {d0.date()} -> {d1.date()}  {len(sub)} rows "
              f"(inception-day NaN ret dropped: 1)")
    df = df.dropna(subset=["ret_total"]).reset_index(drop=True)
    df = repair_bad_prints(df)
    scan_reversals(df)
    return df


def load_yf() -> pd.DataFrame:
    raw = yf.download(TICKERS, start=YF_START, auto_adjust=False, actions=True,
                      progress=False, group_by="ticker")
    assert raw is not None and not raw.empty, "yfinance returned nothing"
    frames = []
    print(f"\n--- yfinance leg (auto_adjust=False + actions; requested start {YF_START}) ---")
    for t in TICKERS:
        d = raw[t].dropna(subset=["Close"]).copy()
        assert not d.empty, f"{t}: empty yfinance frame"
        d.index = pd.to_datetime(d.index).tz_localize(None)
        # assert the returned range covers the request (standing fetch rule)
        assert d.index.min() <= pd.Timestamp(YF_START) + pd.Timedelta(days=5), \
            f"{t}: yfinance starts {d.index.min().date()}, requested {YF_START}"
        assert d.index.max() >= pd.Timestamp.today().normalize() - pd.Timedelta(days=7), \
            f"{t}: yfinance ends {d.index.max().date()} — stale fetch"
        splits = d.get("Stock Splits", pd.Series(0.0, index=d.index)).fillna(0)
        assert (splits == 0).all(), \
            f"{t}: stock split inside yfinance window — ret_px/prc_adj formulas must be extended"
        dist = d["Dividends"].fillna(0.0)
        if "Capital Gains" in d.columns:
            dist = dist + d["Capital Gains"].fillna(0.0)
        frames.append(pd.DataFrame({
            "date": d.index, "ticker": t,
            "ret_adjclose": d["Adj Close"].pct_change().to_numpy(),
            "ret_inhouse": ((d["Close"] + dist) / d["Close"].shift(1) - 1).to_numpy(),
            "ret_px": d["Close"].pct_change().to_numpy(),
            "prc_adj": d["Close"].to_numpy(dtype=float),
            "volume": d["Volume"].to_numpy(dtype=float),
        }))
        print(f"  {t:<5} {d.index.min().date()} -> {d.index.max().date()}  {len(d)} rows, "
              f"{int((dist > 0).sum())} distribution days")
    return pd.concat(frames, ignore_index=True)


def validate_splice(crsp: pd.DataFrame, yfd: pd.DataFrame) -> dict:
    """2024 overlap: CRSP ret vs both yfinance TR candidates. Returns per-ticker
    chosen method + diagnostics dict; raises if neither method passes."""
    print("\n--- 2024 overlap validation (CRSP ret vs yfinance TR candidates) ---")
    diag = {}
    for t in TICKERS:
        a = crsp[(crsp.ticker == t) & (crsp.date.dt.year == 2024)].set_index("date")
        b = yfd[(yfd.ticker == t) & (yfd.date.dt.year == 2024)].set_index("date")
        missing_crsp = sorted(set(b.index) - set(a.index))
        missing_yf = sorted(set(a.index) - set(b.index))
        assert not missing_crsp and not missing_yf, \
            f"{t}: 2024 calendar mismatch crsp-missing={missing_crsp} yf-missing={missing_yf}"
        both = a[["ret_total"]].join(b[["ret_adjclose", "ret_inhouse"]]).dropna()
        stats = {}
        for m in ("ret_adjclose", "ret_inhouse"):
            dd = (both["ret_total"] - both[m]).abs()
            stats[m] = {"max_bp": dd.max() * 1e4, "mean_bp": dd.mean() * 1e4,
                        "worst_day": dd.idxmax().date()}
        # prefer the spec default (adjclose) when it passes, else inhouse
        method = "ret_adjclose" if stats["ret_adjclose"]["max_bp"] < SPLICE_MAX_BP \
            else "ret_inhouse"
        s = stats[method]
        assert s["max_bp"] < SPLICE_MAX_BP, (
            f"{t}: BOTH TR methods exceed {SPLICE_MAX_BP}bp on 2024 overlap — "
            f"adjclose max {stats['ret_adjclose']['max_bp']:.2f}bp "
            f"(worst {stats['ret_adjclose']['worst_day']}), "
            f"inhouse max {stats['ret_inhouse']['max_bp']:.2f}bp "
            f"(worst {stats['ret_inhouse']['worst_day']}) — investigate, do not accept"
        )
        diag[t] = {"method": method.replace("ret_", ""), **{
            k.replace("ret_", ""): v for k, v in stats.items()}}
        print(f"  {t:<5} n={len(both)}  "
              f"adjclose max/mean {stats['ret_adjclose']['max_bp']:.2f}/"
              f"{stats['ret_adjclose']['mean_bp']:.3f} bp "
              f"(worst {stats['ret_adjclose']['worst_day']})  |  "
              f"inhouse max/mean {stats['ret_inhouse']['max_bp']:.2f}/"
              f"{stats['ret_inhouse']['mean_bp']:.3f} bp  ->  using {diag[t]['method']}")
    return diag


def main() -> None:
    crsp = load_crsp()
    yfd = load_yf()
    diag = validate_splice(crsp, yfd)

    print("\n--- splice ---")
    parts = [crsp.assign(source="crsp")[
        ["date", "ticker", "permno", "ret_total", "ret_px", "prc_adj", "volume", "source"]]]
    for t in TICKERS:
        last_crsp = crsp.loc[crsp.ticker == t, "date"].max()
        yft = yfd[yfd.ticker == t]
        tail = yft[yft.date > last_crsp].copy()
        prev_bar = yft.loc[yft.date < tail["date"].min(), "date"].max()
        assert prev_bar == last_crsp, \
            f"{t}: splice seam gap — yfinance bar before splice is {prev_bar.date()}, " \
            f"CRSP ends {last_crsp.date()}"
        tail["ret_total"] = tail["ret_adjclose" if diag[t]["method"] == "adjclose"
                                 else "ret_inhouse"]
        tail["permno"] = PERMNOS[t]["permno"]
        tail["source"] = "yfinance"
        assert tail["ret_total"].notna().all()
        parts.append(tail[["date", "ticker", "permno", "ret_total", "ret_px",
                           "prc_adj", "volume", "source"]])
        print(f"  {t:<5} CRSP ends {last_crsp.date()}, yfinance takes over "
              f"{tail['date'].min().date()} ({len(tail)} rows, TR method: {diag[t]['method']})")

    etf = (pd.concat(parts, ignore_index=True)
           .sort_values(["ticker", "date"])
           .reset_index(drop=True))
    etf["date"] = pd.to_datetime(etf["date"])
    etf["permno"] = etf["permno"].astype("int64")

    assert not etf.duplicated(["ticker", "date"]).any()
    assert etf[["ret_total", "ret_px", "prc_adj", "volume"]].notna().all().all()
    assert etf["ret_total"].abs().max() < 0.15, \
        f"daily ETF return {etf['ret_total'].abs().max():.2%} > 15% — data error"

    print("\n--- final panel ---")
    for t in TICKERS:
        sub = etf[etf.ticker == t].set_index("date")["ret_total"]
        ann = (1 + sub).prod() ** (252 / len(sub)) - 1
        vol = sub.std() * np.sqrt(252)
        print(f"  {t:<5} {sub.index.min().date()} -> {sub.index.max().date()}  "
              f"{len(sub)} rows  annTR {ann:+.2%}  annVol {vol:.2%}  "
              f"max|ret| {sub.abs().max():.2%}")

    etf.to_parquet(OUT, index=False)
    src_counts = etf.groupby("source").size().to_dict()
    print(f"\nwrote {OUT} ({len(etf)} rows; {etf.date.min().date()} -> "
          f"{etf.date.max().date()}; {src_counts})")


if __name__ == "__main__":
    main()
