"""Zero-trial feasibility for the XASSET slate (RESEARCH_PLAN_2026-10-09 gate G8).

    python3 scripts/xasset/slate_feasibility.py                 # panels + bar and power arithmetic
    export QUANTT_ENV_FILE=/abs/path/to/config/.env             # never printed
    python3 scripts/xasset/slate_feasibility.py --alpaca        # + read-only asset flags
    python3 scripts/xasset/slate_feasibility.py --crsp          # + CRSP coverage (R2 mirror)
    python3 scripts/xasset/slate_feasibility.py --factors       # + AQR factor-file coverage

WHY THIS EXISTS
---------------
Gate G8 declares the five cross-asset tests X1-X5 in one pre-registration
(`results/xasset/PREREG_XASSET_SLATE_2026-10-12.md`) BEFORE any of them runs, so
the XASSET counter's N (and its sqrt(2 ln N) bar) is fixed in advance. Declaring
a test needs three facts that do not spend it:

1. does the repo hold every instrument the test names, from which date, with
   which interior gaps, and to which last date (stale is a form of wrong);
2. can the instrument be traded (and, where the test shorts it, shorted) at
   Alpaca today -- `shortable` changes daily (CLAUDE.md landmine 5), so every
   row carries the UTC time it was read and is true on that date only;
3. given each test's declared eligibility rule, how many fit-period years it
   has before the sealed 2023-01-01 holdout, and therefore what Sharpe the bar
   demands. That is arithmetic on the BAR, not on any return: the required
   Sharpe is found by inverting `scripts/cef/validate.py::_dsr` (the repo's only
   implementation of the deflated-Sharpe bar) at zero skew and normal kurtosis.

4. POWER (added 2026-10-12, with the team lead's rulings on the draft): at
   each test's fit length, the Sharpe it must show to pass, the Sharpe at which
   it would pass four times in five, and the probability of passing if the true
   Sharpe were the published one, or the published one cut by McLean and
   Pontiff's 58% post-publication decline (docs/REFERENCES.md §12b). It uses the
   normal approximation SE(annual SR) = 1/sqrt(years), which ignores the small
   SR^2/2 term. This is arithmetic on published numbers, so a null result can be
   read: a test that cannot pass at its published Sharpe teaches little when it
   fails.
5. `--crsp`: each slate instrument's CRSP identity (`stocknames`, share code
   73), and in `dsf` its first and last date, row count, NULL-`ret` count,
   negative-`prc` count (no closing trade: CRSP stores minus the bid/ask
   average) and zero-volume count. These are coverage and quality COUNTS. No
   `ret` value is read into Python.
6. `--factors`: the AQR Time Series Momentum and Value and Momentum Everywhere
   factor files are reachable, with their column names and first and last month.
   The download goes to a temporary directory that is deleted, and no factor
   value is printed.

WHAT IT MUST NEVER DO
---------------------
Compute a strategy return, Sharpe, IC, turnover or any statistic of an X-test.
That would spend the trial before the slate is declared. It reads the
`ret_total` column only to find where it is non-missing (coverage). No return
is summed, averaged, signed or combined. `ret_total` values are never printed.

INPUTS (read-only; `data/` is what the live sleeve decides on, landmine 9)
-------------------------------------------------------------------------
`data/rv/etf_panel.parquet` (34 tickers) and `data/rv/etf_ohlc_extended.parquet`
(60 tickers): in-house total return (close + distribution) / previous close - 1,
yfinance up to each fetcher's YF_LAST and Alpaca SIP bars after it
(docs/REFERENCES.md §8, fetchers `scripts/rv/stage_universe.py`,
`stage_ohlc_extended.py`). `data/etf_daily.parquet` (13 tickers; CRSP to
2024-12-31) is reported beside them as the second source where it exists.
The master session calendar is SPY's row set in `etf_panel` (SPY trades every
NYSE session from 1993-02-01).

OUTPUT
------
`results/xasset/slate_feasibility_<date>.csv`, one row per instrument: panel,
first and last non-missing `ret_total` date, interior gap count against the
master calendar, the CRSP-panel first date where it exists, and (with
`--alpaca`) name / status / tradable / shortable / easy_to_borrow / borrow_status /
exchange / marginable / fractionable with the UTC read time. It carries no
account identifier (the asset endpoint returns none). The per-test fit windows
and required Sharpes are printed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

HOLDOUT_START = pd.Timestamp("2023-01-01")       # H13: sealed; nothing here reads past it
PANELS = {
    "etf_panel": REPO / "data/rv/etf_panel.parquet",
    "etf_ohlc_extended": REPO / "data/rv/etf_ohlc_extended.parquet",
}
CRSP_PANEL = REPO / "data/etf_daily.parquet"

# The slate, exactly as declared in the pre-registration. Changing a list here
# after the declaration is approved changes the trial; it needs a dated note.
X1 = ["HYG", "LQD", "IEF", "TLT", "EMB", "PFF", "MUB", "BKLN", "CWB"]
X4 = X1 + ["SPY", "EFA", "EEM", "GLD", "DBC"]
# X5 is a dollar-neutral cross-section, so it takes X1's names that could be
# shorted on the declaration snapshot (MUB was not, 2026-10-12). Declared, not
# measured: a later flip in MUB's flag does not change the trial's universe.
X5 = [s for s in X1 if s != "MUB"]
X5_TREASURY_CONTROL = ["SHY", "IEI", "IEF", "TLH", "TLT"]
TESTS = {
    # name: (traded instruments, eligibility lag in months, breadth rule)
    "X1": (X1, 12, "half"),
    "X2": (["SPY", "IEF"], 1, "all"),
    "X3": (["IEF"], 1, "all"),
    "X4": (X4, 12, "half"),
    "X5": (X5, 36, "half"),
}
CONTROLS = ["SHY", "BIL", "IEI", "TLH", "AGG"]   # controls and factor proxies named in the prereg

# The published Sharpe each test is powered against (docs/REFERENCES.md §12i).
# Out-of-sample figures where the paper gives one. An INPUT TO THE POWER
# ARITHMETIC ONLY: no decision rule reads it (H14).
PUBLISHED_SR = {
    "X1": (0.49, "BSV Table IV Panel A, bond trend, new sample"),
    "X2": (1.11, "HMM Table 6, 1997-2023, in-sample"),
    "X3": (0.88, "Hartley-Schwarz Table 3, 10-year, t=3, 1990-2018"),
    "X4": (0.98, "BSV Table IV Panel A, multi-asset trend, new sample"),
    "X5": (0.31, "BSV Table IV Panel A, bond momentum, new sample"),
}
MCLEAN_PONTIFF_KEEP = 0.42     # 1 - 0.58: "58% lower after publication" (REFERENCES §12b, [V] abstract)
AQR_FILES = {
    "TSMOM": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Time-Series-Momentum-Factors-Monthly.xlsx",
    "VME": "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Value-and-Momentum-Everywhere-Factors-Monthly.xlsx",
}


def coverage(sym: str, frames: dict, cal: pd.DatetimeIndex) -> dict:
    """Where `sym`'s ret_total is non-missing, and how many master sessions inside
    its own [first, last] carry no value. Raises if no panel holds it."""
    for name, df in frames.items():
        s = df.loc[df["ticker"] == sym].set_index("date")["ret_total"]
        if s.notna().any():
            s = s[s.notna()]
            first, last = s.index.min(), s.index.max()
            inside = cal[(cal >= first) & (cal <= last)]
            gaps = int((~inside.isin(s.index)).sum())
            return dict(symbol=sym, panel=name, first=first.date(), last=last.date(),
                        sessions=len(s), interior_gaps=gaps)
    raise KeyError(f"{sym}: no non-missing ret_total in any of {list(frames)}; "
                   f"the test that names it cannot be built from repo data")


def month_ends(cal: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last NYSE session of each calendar month, from the master calendar."""
    s = pd.Series(cal, index=cal)
    return pd.DatetimeIndex(s.groupby([cal.year, cal.month]).max().values)


def fit_window(syms, lag_m: int, rule: str, firsts: dict, cal: pd.DatetimeIndex):
    """First month-end E at which the declared breadth rule holds, where an
    instrument is eligible at E once its first return is on or before the first
    session after the month-end `lag_m` months earlier (a full lookback window).
    `half` = at least ceil(n/2) eligible (MOP p.236 starts its evaluation once
    "a comprehensive set of instruments have data"; ceil(n/2) is this desk's
    mechanical stand-in, declared before any return is seen); `all` = every one."""
    me = month_ends(cal)
    need = math.ceil(len(syms) / 2) if rule == "half" else len(syms)
    for i in range(lag_m, len(me)):
        start_of_window = cal[cal > me[i - lag_m]][0]
        n_ok = sum(pd.Timestamp(firsts[s]) <= start_of_window for s in syms)
        if n_ok >= need:
            fit = cal[(cal > me[i]) & (cal < HOLDOUT_START)]
            return me[i].date(), len(fit), need
    raise RuntimeError(f"breadth rule {rule} never holds for {syms}")


def required_sharpe(n_trials: int, n_days: int) -> float:
    """Annualised Sharpe at which validate._dsr == 0.95 (its PASS line), skew 0,
    kurtosis 3. Bisection on the repo's own function: no second copy of the bar."""
    from scripts.cef.validate import _dsr
    lo, hi = 0.0, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        d, _, _ = _dsr(mid, n_days, 0.0, 3.0, n_trials)
        lo, hi = (mid, hi) if d < 0.95 else (lo, mid)
    return hi


def power(sr_true: float, n_trials: int, n_days: int) -> float:
    """P(validate._dsr > 0.95) when the true annual Sharpe is `sr_true`, under
    the normal approximation SE = 1/sqrt(years) around the required Sharpe."""
    from statistics import NormalDist
    yrs = n_days / 252
    return NormalDist().cdf((sr_true - required_sharpe(n_trials, n_days)) * math.sqrt(yrs))


def crsp_coverage(symbols) -> pd.DataFrame:
    """CRSP identity and dsf coverage/quality COUNTS for each symbol (share code
    73, ETFs). A ticker with no share-code-73 record, or with two permnos at
    once, raises. No return value leaves the database."""
    from src.data import r2
    cfg = r2.load_config()
    con = r2.connect(cfg)
    names = con.execute(
        f"SELECT permno, ticker, namedt, nameenddt, shrcd FROM "
        f"read_parquet('{r2.r2_path('crsp_a_stock', 'stocknames', cfg)}') "
        f"WHERE ticker IN ({','.join('?' * len(symbols))}) AND shrcd = 73", list(symbols)).df()
    rows = []
    for sym in symbols:
        rec = names[names.ticker == sym]
        if rec.empty:
            raise KeyError(f"{sym}: no CRSP stocknames record with share code 73")
        if rec.permno.nunique() != 1:
            raise RuntimeError(f"{sym}: {rec.permno.nunique()} permnos carry this ticker as an ETF: "
                               f"{sorted(rec.permno.unique())}; resolve by date before use")
        permno = int(rec.permno.iloc[0])
        c = con.execute(
            f"SELECT MIN(date), MAX(date), COUNT(*), "
            f"SUM(CASE WHEN ret IS NULL THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN prc < 0 THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN vol = 0 THEN 1 ELSE 0 END) "
            f"FROM read_parquet('{r2.r2_path('crsp_a_stock', 'dsf', cfg)}') WHERE permno = ?",
            [permno]).fetchone()
        rows.append(dict(symbol=sym, crsp_permno=permno, crsp_first=pd.Timestamp(c[0]).date(),
                         crsp_last=pd.Timestamp(c[1]).date(), crsp_rows=int(c[2]),
                         crsp_null_ret=int(c[3]), crsp_neg_prc=int(c[4]), crsp_zero_vol=int(c[5])))
    return pd.DataFrame(rows)


def factor_file_coverage() -> list[str]:
    """Reach each AQR factor file; report columns and first/last month only."""
    import tempfile
    import urllib.request
    out = []
    ua = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    with tempfile.TemporaryDirectory() as tmp:
        for name, url in AQR_FILES.items():
            path = Path(tmp) / f"{name}.xlsx"
            with urllib.request.urlopen(urllib.request.Request(url, headers=ua), timeout=60) as r:
                path.write_bytes(r.read())
            book = pd.ExcelFile(path)
            df = book.parse(book.sheet_names[0], header=None)
            hdr = next((i for i in range(min(60, len(df)))
                        if any(str(v).strip().upper() in ("DATE", "TSMOM") for v in df.iloc[i])), None)
            if hdr is None:
                raise RuntimeError(f"{name}: no header row found; the file layout changed -- look at it")
            cols = [str(v).strip() for v in df.iloc[hdr] if str(v).strip() not in ("nan", "DATE")]
            dates = pd.to_datetime(df.iloc[hdr + 1:, 0], errors="coerce").dropna()
            out.append(f"{name}: sheet '{book.sheet_names[0]}', {len(dates)} months "
                       f"{dates.min().date()} .. {dates.max().date()}; columns {cols[:8]}")
    return out


def alpaca_flags(symbols) -> pd.DataFrame:
    """GET /v2/assets/{symbol} on the cef paper key (read-only). A 404 is a finding."""
    from quantt.broker.alpaca import AlpacaClient, AssetNotFound
    client = AlpacaClient.from_environment("cef")   # raises if QUANTT_ENV_FILE is unset
    fields = ("name", "status", "exchange", "tradable", "shortable", "easy_to_borrow",
              "borrow_status", "marginable", "fractionable")
    rows = []
    for sym in symbols:
        t = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        try:
            a = client.asset(sym)
            rows.append({"symbol": sym, "alpaca_read_utc": t, "found": True,
                         **{f: a.get(f) for f in fields}})
        except AssetNotFound:
            rows.append({"symbol": sym, "alpaca_read_utc": t, "found": False})
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--alpaca", action="store_true", help="also read Alpaca asset flags (read-only)")
    ap.add_argument("--crsp", action="store_true", help="also read CRSP coverage counts from the R2 mirror")
    ap.add_argument("--factors", action="store_true", help="also check the AQR factor files are reachable")
    ap.add_argument("--out", default=None, help="CSV path (default results/xasset/slate_feasibility_<today>.csv)")
    a = ap.parse_args(argv)

    frames = {}
    for name, path in PANELS.items():
        df = pd.read_parquet(path, columns=["date", "ticker", "ret_total"])
        df["date"] = pd.to_datetime(df["date"])
        frames[name] = df
        print(f"{name}: last date {df['date'].max().date()}  ({path.relative_to(REPO)})")
    cal = pd.DatetimeIndex(sorted(frames["etf_panel"].loc[frames["etf_panel"]["ticker"] == "SPY", "date"].unique()))
    crsp = pd.read_parquet(CRSP_PANEL, columns=["date", "ticker", "source"])
    crsp_first = crsp.groupby("ticker")["date"].min()
    print(f"etf_daily (CRSP <= 2024-12-31): last date {crsp['date'].max().date()}")

    syms = list(dict.fromkeys(X4 + CONTROLS))
    cov = pd.DataFrame([coverage(s, frames, cal) for s in syms])
    cov["crsp_panel_first"] = [crsp_first[s].date() if s in crsp_first else None for s in syms]
    if a.crsp:
        cov = cov.merge(crsp_coverage(syms), on="symbol", how="left")
    if a.alpaca:
        cov = cov.merge(alpaca_flags(syms), on="symbol", how="left")
    pd.set_option("display.width", 220)
    print(cov.to_string(index=False))

    firsts = dict(zip(cov["symbol"], cov["first"]))
    print("\nper test: first decision month-end under its declared rule; fit sessions to 2022-12-30;"
          "\nrequired annualised Sharpe for validate._dsr > 0.95 (skew 0, kurt 3) at N = 5/4/3/2;"
          "\nthe 'sr0' reading sqrt(2 ln N)/sqrt(years) at N = 5 (the agenda's arithmetic);"
          "\nthe Sharpe a D4 alpha t of 3.0 implies, 3/sqrt(years) (plan section 0, alpha only);"
          "\nand the LEGACY reading at N = 162 for reference (agenda section 6, item 1)")
    for name, (s, lag, rule) in TESTS.items():
        first_dec, n_fit, need = fit_window(s, lag, rule, firsts, cal)
        yrs = n_fit / 252
        req = {n: required_sharpe(n, n_fit) for n in (5, 4, 3, 2)}
        sr0 = math.sqrt(2 * math.log(5)) / math.sqrt(yrs)
        d4 = 3.0 / math.sqrt(yrs)
        legacy = required_sharpe(162, n_fit)
        print(f"  {name}: n={len(s)} need {need} eligible (lag {lag}m); first decision {first_dec}; "
              f"fit {n_fit} sessions = {yrs:.1f} yr; required SR "
              + " ".join(f"N{n}:{v:.2f}" for n, v in req.items())
              + f"; sr0@N5 {sr0:.2f}; D4 alpha-t3 {d4:.2f}; LEGACY N162 {legacy:.2f}")
        pub, src = PUBLISHED_SR[name]
        from statistics import NormalDist
        mde80 = req[5] + NormalDist().inv_cdf(0.80) / math.sqrt(yrs)
        print(f"      power at N=5: Sharpe for 80% power {mde80:.2f}; P(pass | true SR = {pub:.2f}, {src}) "
              f"{power(pub, 5, n_fit):.2f}; P(pass | {MCLEAN_PONTIFF_KEEP:.2f} x that = "
              f"{pub * MCLEAN_PONTIFF_KEEP:.2f}) {power(pub * MCLEAN_PONTIFF_KEEP, 5, n_fit):.2f}; "
              f"P(D4 alpha t >= 3 | alpha SR = {pub:.2f}) "
              f"{NormalDist().cdf(pub * math.sqrt(yrs) - 3.0):.2f}")
    if a.factors:
        print("\nfactor files (coverage only; no value printed):")
        for line in factor_file_coverage():
            print("  " + line)

    out = Path(a.out) if a.out else REPO / "results/xasset" / f"slate_feasibility_{dt.date.today():%Y-%m-%d}.csv"
    cov.to_csv(out, index=False)
    print(f"\nwrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
