"""fetch_daily never merges a fetched row with no close (fix approved by the team lead, 2026-10-28).

WHY. When Yahoo's chart response carries a dividend (or split) for a date with no
bar, yfinance 0.2.66 emits a row for that date with every price NaN and volume
filled to 0 (`yfinance/utils.py` `safe_merge_dfs`, "row of NaNs";
`scrapers/history.py` `Volume.fillna(0)`). fetch_daily wrote it unchecked, and its
`drop_duplicates(keep="last")` let it replace a good bar. Measured 2026-10-28,
read-only, on the laptop's `data/cef/cef_prices.parquet` (to 2026-10-15) against
its 2026-09-28 backup: 15 good 2026-09-15 bars had become empty rows (BGT BIT EFR
EFT HYT JFR MHD MQY NAD NAN NEA NIM NVG NXP NZF; BIT HYT JFR MHD MQY are in the
live 13), and the panel held 65 empty-close rows against the backup's 49, every
one with volume 0. `--require-asof` counted such a row as the as-of close.

The bar values below are those panels' rows, copied as test fixtures (the
2026-09-15 bars from the backup; DHY's 2026-09-28 bar and empty 2026-09-30 row and
FCT's zero-volume 2026-08-10 bar from the current panel). They pin the code's
behaviour on the incident's own shapes; they are not a claim about the market.

Each test drives the real `refresh` with yfinance replaced by a fake that returns
frames in yfinance's own shape. Hermetic: every path is monkeypatched into
tmp_path (the root conftest refuses a write under data/) and no network is
reached (netguard).
"""
import math
import types

import numpy as np
import pandas as pd
import pytest

from ops.common import atomic_write
from scripts.cef import fetch_daily as fd

PANEL_COLS = ["date", "open", "high", "low", "close", "volume", "ticker", "grp"]

# 2026-09-15 bars that the 2026-10-15 refresh turned into empty rows, read from
# data/cef/cef_prices.parquet.pre-20261015.bak: (ticker, grp, open, high, low, close, volume).
SEP15_LOST = [
    ("BGT", "loan", 10.81, 10.83, 10.72, 10.72, 137400),
    ("BIT", "multi", 11.55, 11.60, 11.48, 11.49, 616900),
    ("EFR", "loan", 10.32, 10.40, 10.28, 10.28, 153100),
    ("EFT", "loan", 10.45, 10.47, 10.43, 10.45, 128900),
    ("HYT", "hy", 8.02, 8.06, 7.98, 7.98, 1365200),
    ("JFR", "loan", 7.46, 7.48, 7.44, 7.44, 869300),
    ("MHD", "muni", 10.94, 10.94, 10.67, 10.83, 1128300),
    ("MQY", "muni", 10.49, 10.54, 10.32, 10.32, 2038400),
    ("NAD", "muni", 10.79, 10.91, 10.65, 10.73, 1845900),
    ("NAN", "muni", 10.34, 10.37, 10.10, 10.13, 212300),
    ("NEA", "muni", 10.62, 10.63, 10.49, 10.53, 2107600),
    ("NIM", "muni", 8.90, 9.02, 8.90, 8.97, 30100),
    ("NVG", "muni", 11.40, 11.43, 11.27, 11.28, 1125500),
    ("NXP", "muni", 13.63, 13.66, 13.42, 13.46, 304500),
    ("NZF", "muni", 11.39, 11.41, 11.24, 11.28, 1261700),
]
SEP15 = pd.Timestamp("2026-09-15")
NAN = float("nan")


def bar(ticker, grp, date, o, h, l, c, v):
    return {"date": pd.Timestamp(date), "open": o, "high": h, "low": l, "close": c,
            "volume": v, "ticker": ticker, "grp": grp}


def empty(ticker, grp, date, close=NAN):
    """The row yfinance emits for a corporate action with no bar: no prices, volume 0."""
    return bar(ticker, grp, date, NAN, NAN, NAN, close, 0)


def panel(rows) -> pd.DataFrame:
    P = pd.DataFrame(rows, columns=PANEL_COLS)
    P["volume"] = P["volume"].astype("int64")
    return P.sort_values(["ticker", "date"]).reset_index(drop=True)


def yf_frame(rows) -> pd.DataFrame:
    """Panel-shaped rows in the shape `yf.Ticker(tk).history(auto_adjust=False)`
    returns: a tz-aware 'Date' index, float prices, int64 Volume, and a nonzero
    Dividends on a row that has no prices (that dividend is why yfinance keeps it)."""
    if not rows:
        return pd.DataFrame()
    f = pd.DataFrame(rows)
    out = pd.DataFrame({
        "Open": f["open"].astype(float), "High": f["high"].astype(float),
        "Low": f["low"].astype(float), "Close": f["close"].astype(float),
        "Adj Close": f["close"].astype(float),
        "Volume": f["volume"].astype("int64"),
        "Dividends": np.where(np.isfinite(f["close"].astype(float)), 0.0, 0.06),
        "Stock Splits": 0.0, "Capital Gains": 0.0})
    out.index = pd.DatetimeIndex(f["date"]).tz_localize("America/New_York")
    out.index.name = "Date"
    return out


def nav_frame(ticker, dates, nav=10.0) -> pd.DataFrame:
    rows = [bar(ticker, "", d, nav, nav, nav, nav, 0) for d in dates]
    return yf_frame(rows)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Point every path fetch_daily touches into tmp_path, fake yfinance, and run
    `refresh` after the close. Returns run(P, N, fetched, navs, **kw) -> (rc, out)."""
    monkeypatch.setattr(fd, "PX_PATH", tmp_path / "cef_prices.parquet")
    monkeypatch.setattr(fd, "NAV_PATH", tmp_path / "cef_nav.parquet")
    monkeypatch.setattr(fd, "LOCK_PATH", tmp_path / ".fetch.lock")
    monkeypatch.setattr(fd, "FALLBACK_LOG", tmp_path / "nav_fallback_log.csv")
    monkeypatch.setattr(fd, "before_close", lambda now: False)

    def run(P, N, fetched, navs, errors=(), require_asof=None, capsys=None):
        atomic_write(P, fd.PX_PATH)
        atomic_write(N, fd.NAV_PATH)

        class Ticker:
            def __init__(self, sym):
                self.sym = sym

            def history(self, period, auto_adjust):
                tk = self.sym[1:-1] if self.sym.startswith("X") and self.sym.endswith("X") else self.sym
                if tk in errors:
                    raise ConnectionError("fake yfinance outage")
                if self.sym == tk:
                    return yf_frame(fetched.get(tk, []))
                return navs.get(tk, pd.DataFrame())

        monkeypatch.setattr(fd, "yf", types.SimpleNamespace(Ticker=Ticker))
        rc = fd.refresh("6mo", require_asof, None, None)
        out = capsys.readouterr().out if capsys is not None else ""
        return rc, out
    return run


def nav_panel(tickers, dates, nav=10.0) -> pd.DataFrame:
    return pd.DataFrame([{"date": pd.Timestamp(d), "nav": nav, "ticker": t}
                         for t in tickers for d in dates])


def lines(out, tag):
    return [ln.strip() for ln in out.splitlines() if ln.strip().startswith(tag)]


def row(P, ticker, date):
    r = P[(P["ticker"] == ticker) & (P["date"] == pd.Timestamp(date))]
    assert len(r) <= 1, f"duplicate {ticker} {date}"
    return None if r.empty else r.iloc[0]


# --------------------------------------------------------------------------------

def test_an_empty_row_does_not_overwrite_a_good_bar(env, capsys):
    """The 2026-10-15 incident replayed: the panel holds the 15 good 2026-09-15
    bars, the fetch returns an empty 2026-09-15 row for each. All 15 bars survive,
    and each refused row is named with its date and why."""
    P = panel([bar(t, g, SEP15, o, h, l, c, v) for t, g, o, h, l, c, v in SEP15_LOST])
    N = nav_panel([t for t, *_ in SEP15_LOST], [SEP15])
    fetched = {t: [empty(t, g, SEP15)] for t, g, *_ in SEP15_LOST}
    rc, out = env(P, N, fetched, {}, capsys=capsys)
    assert rc == 0
    got = pd.read_parquet(fd.PX_PATH)
    for t, g, o, h, l, c, v in SEP15_LOST:
        r = row(got, t, SEP15)
        assert r is not None and r["close"] == c and r["volume"] == v, \
            f"{t} 2026-09-15 bar {c} on {v} was overwritten by an empty row: {r}"
    refused = lines(out, "NO CLOSE")
    assert len(refused) == len(SEP15_LOST) == 15
    for t, *_ in SEP15_LOST:
        hit = [ln for ln in refused if f" {t} " in ln and "2026-09-15" in ln]
        assert len(hit) == 1 and "kept" in hit[0], (t, refused)


@pytest.mark.parametrize("close", [NAN, math.inf, -math.inf], ids=["nan", "inf", "-inf"])
def test_an_empty_row_for_a_new_date_is_not_written_and_is_logged(env, capsys, close):
    """DHY's 2026-09-30 row (empty in the laptop panel today). A close that is not
    finite is no close, whatever else the row carries."""
    good = bar("DHY", "hy", "2026-09-28", 1.62, 1.64, 1.61, 1.61, 949700)
    P = panel([bar("DHY", "hy", "2026-09-25", 1.62, 1.63, 1.61, 1.62, 1045100)])
    N = nav_panel(["DHY"], ["2026-09-25"])
    rc, out = env(P, N, {"DHY": [good, empty("DHY", "hy", "2026-09-30", close)]}, {},
                  capsys=capsys)
    assert rc == 0
    got = pd.read_parquet(fd.PX_PATH)
    assert row(got, "DHY", "2026-09-30") is None, "an empty row was written as a new date"
    assert row(got, "DHY", "2026-09-28")["close"] == 1.61, "the good bar beside it was lost"
    refused = lines(out, "NO CLOSE")
    assert len(refused) == 1
    assert " DHY " in refused[0] and "2026-09-30" in refused[0] and "not written" in refused[0]


def test_a_good_bar_replaces_an_existing_empty_row_and_is_logged(env, capsys):
    """HYT 2026-09-15 is empty in the laptop panel now. A later fetch that has the
    bar repairs it, and the repair is named; the empty row never wins the other way."""
    P = panel([bar("HYT", "hy", "2026-09-12", 8.05, 8.07, 8.01, 8.03, 900000),
               empty("HYT", "hy", SEP15)])
    N = nav_panel(["HYT"], ["2026-09-12", SEP15])
    t, g, o, h, l, c, v = next(x for x in SEP15_LOST if x[0] == "HYT")
    rc, out = env(P, N, {"HYT": [bar(t, g, SEP15, o, h, l, c, v)]}, {}, capsys=capsys)
    assert rc == 0
    r = row(pd.read_parquet(fd.PX_PATH), "HYT", SEP15)
    assert r["close"] == 7.98 and r["volume"] == 1365200
    repaired = lines(out, "REPAIRED")
    assert len(repaired) == 1, out
    assert " HYT " in repaired[0] and "2026-09-15" in repaired[0] and "7.98" in repaired[0]
    assert not lines(out, "NO CLOSE")


@pytest.mark.parametrize("fetch", ["returns_the_empty_row_again", "fails_for_that_name"])
def test_require_asof_refuses_an_empty_as_of_row(env, capsys, fetch):
    """The panel already holds an empty HYT 2026-09-15 row (it does on the laptop).
    Whether the fetch brings the same empty row again or brings nothing for HYT, the
    as-of check must refuse HYT for 2026-09-15 exactly as for a missing row: exit 4,
    the date in the INCOMPLETE line, HYT named as having no close. BIT is complete."""
    P = panel([bar("BIT", "multi", SEP15, 11.55, 11.60, 11.48, 11.49, 616900),
               empty("HYT", "hy", SEP15)])
    N = nav_panel(["BIT", "HYT"], [SEP15])
    fetched = {"BIT": [bar("BIT", "multi", SEP15, 11.55, 11.60, 11.48, 11.49, 616900)]}
    errors = ()
    if fetch == "returns_the_empty_row_again":
        fetched["HYT"] = [empty("HYT", "hy", SEP15)]
    else:
        errors = ("HYT",)
    rc, out = env(P, N, fetched, {}, errors=errors, require_asof="2026-09-15", capsys=capsys)
    assert rc == 4, out
    inc = lines(out, "INCOMPLETE")
    assert len(inc) == 1 and "2026-09-15" in inc[0] and "1 deployed name(s)" in inc[0], inc
    assert "HYT: no close" in inc[0] and "BIT" not in inc[0], inc


def test_a_real_zero_volume_day_with_a_close_is_kept(env, capsys):
    """Volume 0 is not 'empty'. FCT traded no shares on 2026-08-10 and printed 9.67
    (one of 20 such rows in the panel). That bar is written and is the as-of close;
    the empty row HYT brings in the same fetch is not. A fix keyed on volume would
    drop FCT; the old code writes HYT's empty row."""
    P = panel([bar("FCT", "loan", "2026-08-07", 9.66, 9.70, 9.66, 9.70, 1200),
               bar("HYT", "hy", "2026-08-07", 8.40, 8.42, 8.38, 8.40, 800000)])
    N = nav_panel(["FCT", "HYT"], ["2026-08-07", "2026-08-10"])
    fetched = {"FCT": [bar("FCT", "loan", "2026-08-10", 9.67, 9.67, 9.67, 9.67, 0)],
               "HYT": [bar("HYT", "hy", "2026-08-10", 8.41, 8.43, 8.39, 8.42, 700000),
                       empty("HYT", "hy", "2026-08-11")]}
    rc, out = env(P, N, fetched, {}, require_asof="2026-08-10", capsys=capsys)
    assert rc == 0, out
    got = pd.read_parquet(fd.PX_PATH)
    r = row(got, "FCT", "2026-08-10")
    assert r is not None and r["close"] == 9.67 and r["volume"] == 0
    assert row(got, "HYT", "2026-08-11") is None
    refused = lines(out, "NO CLOSE")
    assert len(refused) == 1 and " HYT " in refused[0] and "2026-08-11" in refused[0]
    assert not any(" FCT " in ln for ln in refused)


def test_with_no_empty_rows_a_fetch_is_byte_identical_to_before(env, capsys, tmp_path):
    """The no-op proof. (a) A fetch with no empty rows writes exactly the bytes the
    pre-fix merge wrote (concat, drop_duplicates keep='last', sort), and logs
    nothing new. (b) Adding empty rows to that same fetch -- over good bars, over
    nothing, on dates the panel lacks -- changes not one byte of either panel."""
    P = panel([bar("BIT", "multi", "2026-09-12", 11.50, 11.56, 11.45, 11.52, 500000),
               bar("BIT", "multi", SEP15, 11.55, 11.60, 11.48, 11.49, 616900),
               bar("HYT", "hy", "2026-09-12", 8.05, 8.07, 8.01, 8.03, 900000),
               bar("HYT", "hy", SEP15, 8.02, 8.06, 7.98, 7.98, 1365200)])
    N = nav_panel(["BIT", "HYT"], ["2026-09-12", SEP15])
    clean = {"BIT": [bar("BIT", "multi", SEP15, 11.55, 11.60, 11.48, 11.50, 616900),   # restated
                     bar("BIT", "multi", "2026-09-16", 11.49, 11.53, 11.40, 11.41, 410000)],
             "HYT": [bar("HYT", "hy", "2026-09-16", 7.99, 8.00, 7.93, 7.95, 1100000)]}
    navs = {t: nav_frame(t, ["2026-09-16"]) for t in clean}

    # (a) against the pre-fix merge, done here by hand on the same rows.
    rc, out = env(P, N, clean, navs, capsys=capsys)
    assert rc == 0
    a_px, a_nav = fd.PX_PATH.read_bytes(), fd.NAV_PATH.read_bytes()
    new = [pd.DataFrame(rows, columns=PANEL_COLS).astype({"volume": "int64"})
           for rows in clean.values()]
    ref = (pd.concat([P] + new, ignore_index=True)
             .drop_duplicates(subset=["date", "ticker"], keep="last")
             .sort_values(["ticker", "date"]))
    ref_path = tmp_path / "reference.parquet"
    atomic_write(ref, ref_path)
    assert a_px == ref_path.read_bytes(), "a clean fetch no longer writes what it wrote before"
    assert not lines(out, "NO CLOSE") and not lines(out, "REPAIRED")

    # (b) the same fetch with empty rows mixed in.
    dirty = {"BIT": clean["BIT"] + [empty("BIT", "multi", "2026-09-12"),
                                    empty("BIT", "multi", "2026-09-17")],
             "HYT": [empty("HYT", "hy", SEP15)] + clean["HYT"]}
    rc, out = env(P, N, dirty, navs, capsys=capsys)
    assert rc == 0
    assert fd.PX_PATH.read_bytes() == a_px, "empty rows changed the price panel"
    assert fd.NAV_PATH.read_bytes() == a_nav, "empty rows changed the NAV panel"
    assert len(lines(out, "NO CLOSE")) == 3
