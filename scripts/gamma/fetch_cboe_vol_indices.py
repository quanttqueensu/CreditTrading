"""Cboe's published credit volatility indices — the credit VRP's only data source.

    python3 scripts/gamma/fetch_cboe_vol_indices.py
    python3 scripts/gamma/fetch_cboe_vol_indices.py --check   # no write; report freshness

WHY THIS EXISTS
---------------
`gamma/G2` was meant to fit an implied-vol surface for HYG from option prints.
It cannot: the account audit of 2026-09-12 established that **IBKR serves no
historical option bars at all** to this account — nine combinations of
SMART/AMEX/CBOE x TRADES/MIDPOINT/BID_ASK, every one returning IB error 162,
"No data of type EODChart is available". The contract itself qualifies, so this
is a data-service limit, not a bad contract.

That blocks skew and term structure. It does NOT block the at-the-money LEVEL,
because Cboe publishes it. `G2_surface.md:134-157` already says so in terms:
"**G6's base-rate measurement can start immediately** against VXHYG". This
module is what makes that true, and it is the difference between the credit
gamma programme having a data source and not having one.

THE THREE SERIES, AND WHY THEY ARE NOT INTERCHANGEABLE
------------------------------------------------------
    VXHYG   implied vol of options on the HYG ETF      -> ETF PRICE vol
    VIXHY   implied vol of options on CDX HY           -> credit SPREAD vol
    VIXIG   implied vol of options on CDX IG           -> credit SPREAD vol

**VXHYG is the one this programme trades against**, because HYG ETF options are
the only credit vol instrument this account can reach. VIXHY and VIXIG measure a
different quantity on a different underlying and are carried as CONTEXT — G2
Part E asks whether the ETF surface prices the CDX basis or ignores it, and that
question needs both. They are never averaged, never spliced, and never used as a
substitute for one another. `combined()` refuses to hand back a single aligned
frame for exactly that reason.

THE FRESHNESS TRAP, WHICH IS NOT HYPOTHETICAL
---------------------------------------------
G2 recorded VXHYG as current while VIXHY and VIXIG were three weeks stale.
Measured again on 2026-09-12 the gap had grown: VXHYG ran to **2026-09-11**
(one session old) while VIXHY and VIXIG both stopped at **2026-08-14** — 29
days. A naive inner join across the three silently truncates eleven years of
usable VXHYG to whenever the CDX series last updated, and nothing about that
would look wrong.

So: each index keeps its OWN last date, `fetched_at` is stamped per index, and
any caller asking for more than one series must say how it handles the mismatch.
There is no default alignment. `docs/REFERENCES.md` §8 carries a row per index.

SOURCE
------
`https://cdn.cboe.com/api/global/us_indices/daily_prices/<INDEX>_History.csv`
Unauthenticated, no key, `DATE,<INDEX>` with dates as MM/DD/YYYY. Verified
2026-09-12: VXHYG 1,914 rows from 2015-04-22, VIXHY 3,681 from 2012-03-05,
VIXIG 3,674 from 2012-03-05.
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data/gamma/cboe_vol_indices.parquet"

BASE = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{idx}_History.csv"

# index -> (what it measures, what it is FOR here)
INDICES = {
    "VXHYG": ("HYG ETF option implied vol", "the series this programme trades against"),
    "VIXHY": ("CDX HY index option implied vol", "context: the CDX basis (G2 Part E)"),
    "VIXIG": ("CDX IG index option implied vol", "context: the CDX basis (G2 Part E)"),
}

# Plausible ranges. A value outside these is not a quiet or a wild day, it is a
# parse error, a changed convention, or a vendor defect -- and each of those
# needs a human, not a clip.
#
# The VIXHY ceiling is deliberately high. Its March 2020 prints -- 1001.9 on the
# 12th rising to 1263.97 on the 23rd, the exact bottom -- are REAL: CDX HY option
# implied vol against a ~92 baseline today and ~196 at the 2012 start. A ceiling
# tight enough to look sensible on a calm tape rejects the single most important
# credit vol event in the sample, which is the opposite of a data guard.
PLAUSIBLE = {"VXHYG": (1.0, 200.0), "VIXHY": (5.0, 2500.0), "VIXIG": (2.0, 2500.0)}

# VENDOR DEFECTS, NAMED. Not a filter, not a range, not a tolerance -- an
# explicit list of (index, date) that Cboe publishes wrong, each with the reason
# it is impossible rather than merely surprising. Anything NOT on this list that
# fails the range check still RAISES.
#
# Keeping it as a named list rather than widening a bound is the whole point: a
# bound wide enough to swallow -19,738,470 would also swallow every future
# parse error silently. This one row is dropped; the next one stops the fetch.
KNOWN_BAD = {
    ("VXHYG", "2017-10-30"):
        "Cboe publishes -19738470.0 -- a negative implied vol is impossible, and "
        "the row sits between 5.99 (10/27) and 5.52 (10/31). Single isolated "
        "defect in 1,914 rows; verified 2026-09-12 against the raw CSV.",
}

_UA = "Mozilla/5.0 (QUANTT research; contact via repo)"


class FetchError(RuntimeError):
    """The source did not give us something we can use. Never returns a default."""


def fetch_one(index: str, timeout: int = 60) -> pd.DataFrame:
    """One index, as (date, index, value, fetched_at). Raises rather than guessing."""
    if index not in INDICES:
        raise FetchError(f"unknown index {index!r}; known: {sorted(INDICES)}")
    url = BASE.format(idx=index)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                raise FetchError(f"{url} returned HTTP {r.status}")
            raw = r.read().decode("utf-8", errors="strict")
    except FetchError:
        raise
    except Exception as exc:                                # noqa: BLE001
        raise FetchError(f"{url} could not be fetched: {exc!r}") from exc

    df = pd.read_csv(io.StringIO(raw))
    if list(df.columns) != ["DATE", index]:
        raise FetchError(
            f"{index}: unexpected columns {list(df.columns)} -- Cboe changed the "
            f"schema. Do not coerce; look at the file and update this fetcher.")

    # MM/DD/YYYY. `format=` explicitly, so a changed convention raises instead of
    # being silently reinterpreted as DD/MM by the dateutil fallback -- which
    # would corrupt every date before the 13th of a month and nothing else.
    out = pd.DataFrame({
        "date": pd.to_datetime(df["DATE"], format="%m/%d/%Y", errors="raise"),
        "index": index,
        "value": pd.to_numeric(df[index], errors="raise").astype(float),
    })
    out = out.dropna().drop_duplicates("date").sort_values("date")
    if out.empty:
        raise FetchError(f"{index}: no usable rows after parsing")

    # Drop the named vendor defects FIRST, loudly, and only those.
    dropped = []
    for (bad_idx, bad_date), reason in KNOWN_BAD.items():
        if bad_idx != index:
            continue
        hit = out["date"] == pd.Timestamp(bad_date)
        if hit.any():
            dropped.append((bad_date, float(out.loc[hit, "value"].iloc[0]), reason))
            out = out[~hit]
        else:
            # The vendor fixed it, or the date moved. Either way this entry is
            # now a lie and should be deleted rather than left to rot.
            print(f"[cboe] NOTE {index} {bad_date}: the KNOWN_BAD row is no "
                  f"longer present upstream — remove it from KNOWN_BAD.",
                  file=sys.stderr)
    for d, v, reason in dropped:
        print(f"[cboe] DROPPED {index} {d} = {v:,.1f} — {reason}", file=sys.stderr)

    lo, hi = PLAUSIBLE[index]
    bad = out[(out.value < lo) | (out.value > hi)]
    if not bad.empty:
        raise FetchError(
            f"{index}: {len(bad)} value(s) outside the plausible range "
            f"[{lo}, {hi}] -- e.g. {bad.iloc[0].date.date()} = "
            f"{bad.iloc[0].value}. Either Cboe changed units, the parse is "
            f"wrong, or this is a new vendor defect. All three need a human: "
            f"widen PLAUSIBLE only if the value is REAL (VIXHY's March 2020 "
            f"prints are), and add it to KNOWN_BAD only if it is impossible.")

    out["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out.reset_index(drop=True)


def fetch_all(indices=None) -> pd.DataFrame:
    """Every index as one LONG frame. Long, not wide, so nothing is aligned."""
    frames = [fetch_one(i) for i in (indices or INDICES)]
    return pd.concat(frames, ignore_index=True)


def coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Per-index first date, last date, rows and staleness. The freshness table."""
    today = pd.Timestamp(datetime.now().date())
    g = df.groupby("index")["date"]
    cov = pd.DataFrame({"first": g.min(), "last": g.max(), "rows": g.size()})
    cov["days_stale"] = (today - cov["last"]).dt.days
    return cov.sort_values("last", ascending=False)


def series(df: pd.DataFrame, index: str) -> pd.Series:
    """One index as a date-indexed Series. The ONLY sanctioned way to get one."""
    s = df[df["index"] == index].set_index("date")["value"].sort_index()
    if s.empty:
        raise FetchError(f"{index} is not in this frame")
    return s


def combined(df: pd.DataFrame, indices, how: str):
    """Two or more indices in one frame -- and you must say how you handle the gap.

    THERE IS NO DEFAULT, ON PURPOSE. VXHYG runs a month ahead of VIXHY/VIXIG
    (measured 2026-09-12: 2026-09-11 against 2026-08-14, 29 days). An inner join
    silently truncates eleven years of VXHYG to whenever the CDX series last
    updated, and the result looks perfectly ordinary.

    how="inner"  intersect -- correct when you need the pair on the same day,
                 and you accept the shorter sample. Says so in the returned
                 attrs so a note cannot omit it.
    how="outer"  keep every date, NaN where an index has not published. Correct
                 when the series are analysed separately.
    """
    if how not in ("inner", "outer"):
        raise FetchError(
            f"how must be 'inner' or 'outer', got {how!r}. There is no default: "
            f"these series have different last dates and the choice changes the "
            f"sample. State it.")
    wide = (df[df["index"].isin(indices)]
            .pivot(index="date", columns="index", values="value")
            .sort_index())
    if how == "inner":
        wide = wide.dropna(how="any")
    wide.attrs["join"] = how
    wide.attrs["note"] = ("VXHYG is ETF PRICE vol; VIXHY/VIXIG are credit "
                          "SPREAD vol. Different quantities -- never averaged.")
    return wide


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="fetch and report freshness, write nothing")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    df = fetch_all()
    cov = coverage(df)

    print(f"Cboe credit volatility indices — fetched "
          f"{datetime.now().isoformat(timespec='seconds')}")
    print()
    print(f"{'index':8s}{'measures':34s}{'first':>12s}{'last':>12s}"
          f"{'rows':>7s}{'stale':>7s}")
    print("-" * 80)
    for idx, row in cov.iterrows():
        print(f"{idx:8s}{INDICES[idx][0]:34s}{row['first'].date()!s:>12s}"
              f"{row['last'].date()!s:>12s}{row['rows']:>7d}"
              f"{row['days_stale']:>6d}d")
    print()
    spread = int(cov["days_stale"].max() - cov["days_stale"].min())
    if spread > 5:
        print(f"** The series are {spread} days apart in freshness. That is the "
              f"trap G2 Part C names: an inner join across them truncates the "
              f"freshest to the stalest and looks fine. `combined()` refuses to "
              f"pick for you. **")
        print()
    for idx in cov.index:
        s = series(df, idx)
        print(f"{idx}: last {s.index[-1].date()} = {s.iloc[-1]:.2f}, "
              f"median {s.median():.2f}, min {s.min():.2f}, max {s.max():.2f}")

    if a.check:
        print("\n--check: nothing written")
        return 0
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\n[written] {out}  ({len(df):,} rows, long form)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
