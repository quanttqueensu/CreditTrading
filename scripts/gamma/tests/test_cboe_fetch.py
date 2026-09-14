"""The Cboe fetcher's guards, tested without touching the network.

WHY THESE AND NOT A LIVE FETCH
------------------------------
A test that hits `cdn.cboe.com` fails when the network is down, which teaches
nothing and blocks the suite. What is worth pinning is the three decisions this
fetcher makes about DATA IT DOES NOT CONTROL, each of which was written after
the real file surprised us on 2026-09-12:

1. **A named vendor defect is dropped; an unnamed one RAISES.** Cboe publishes
   `VXHYG 2017-10-30 = -19,738,470.0`. Widening the plausible range to swallow
   that would also swallow every future parse error in silence, so it is dropped
   by name and anything else out of range stops the fetch.
2. **VIXHY's March 2020 prints are REAL and must survive.** 1,001.9 rising to
   1,263.97 on the 23rd — the exact COVID bottom, and the same day VXHYG peaked
   at 59.26. A range tight enough to look sensible on a calm tape rejects the
   single most important credit vol event in the sample.
3. **`combined()` has no default join.** VXHYG leads VIXHY/VIXIG by 28 days;
   an inner join silently truncates eleven years to whenever CDX last updated.

The date format is pinned too, because `%m/%d/%Y` parsed loosely would
reinterpret every date before the 13th of a month as DD/MM and nothing else —
a corruption that touches 40% of rows and looks like noise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.gamma import fetch_cboe_vol_indices as M  # noqa: E402


def _frame(index, rows):
    return pd.DataFrame({
        "date": pd.to_datetime([d for d, _ in rows]),
        "index": index,
        "value": [v for _, v in rows],
        "fetched_at": "2026-09-12T00:00:00+00:00",
    })


# -- the named defect ------------------------------------------------------

def test_the_known_bad_row_is_named_with_a_reason_not_just_a_date():
    """A bare exclusion list rots. Each entry has to say why it is impossible."""
    assert ("VXHYG", "2017-10-30") in M.KNOWN_BAD
    reason = M.KNOWN_BAD[("VXHYG", "2017-10-30")]
    assert "negative" in reason.lower()
    assert "19738470" in reason.replace(",", "")


def test_plausible_range_rejects_the_vendor_defect():
    """The guard must consider -19.7M out of range in the first place."""
    lo, hi = M.PLAUSIBLE["VXHYG"]
    assert not (lo <= -19738470.0 <= hi)


def test_march_2020_vixhy_is_inside_the_plausible_range():
    """The real event must NOT be rejected. This is the half that is easy to break.

    Tightening VIXHY's ceiling to something that looks sensible against its ~92
    baseline would throw away 2020-03-12 through 2020-03-23 — the COVID credit
    crash, and the most informative fortnight in the sample for a programme
    about credit volatility.
    """
    lo, hi = M.PLAUSIBLE["VIXHY"]
    for v in (1001.9232, 1080.6191, 1046.7797, 1181.9345, 1263.9695):
        assert lo <= v <= hi, f"VIXHY {v} (March 2020) would be rejected"


def test_vxhyg_covid_peak_is_inside_the_range():
    lo, hi = M.PLAUSIBLE["VXHYG"]
    assert lo <= 59.26 <= hi, "VXHYG's 2020-03-23 peak would be rejected"


# -- combined() has no default --------------------------------------------

def test_combined_refuses_to_choose_a_join():
    df = pd.concat([_frame("VXHYG", [("2026-08-14", 6.0), ("2026-09-11", 6.31)]),
                    _frame("VIXHY", [("2026-08-14", 91.82)])], ignore_index=True)
    with pytest.raises(M.FetchError, match="no default"):
        M.combined(df, ["VXHYG", "VIXHY"], how="whatever")
    with pytest.raises(TypeError):
        M.combined(df, ["VXHYG", "VIXHY"])          # `how` is required


def test_inner_join_really_does_truncate_and_outer_does_not():
    """The trap, demonstrated rather than described.

    VXHYG has a date VIXHY does not. Inner loses it; outer keeps it with a NaN.
    Both are legitimate; choosing silently is not.
    """
    df = pd.concat([_frame("VXHYG", [("2026-08-14", 6.0), ("2026-09-11", 6.31)]),
                    _frame("VIXHY", [("2026-08-14", 91.82)])], ignore_index=True)
    inner = M.combined(df, ["VXHYG", "VIXHY"], how="inner")
    outer = M.combined(df, ["VXHYG", "VIXHY"], how="outer")
    assert len(inner) == 1 and len(outer) == 2
    assert pd.Timestamp("2026-09-11") not in inner.index
    assert pd.Timestamp("2026-09-11") in outer.index
    assert inner.attrs["join"] == "inner"
    assert "never averaged" in outer.attrs["note"]


# -- the series accessor ---------------------------------------------------

def test_series_raises_for_an_index_that_is_not_there():
    df = _frame("VXHYG", [("2026-09-11", 6.31)])
    with pytest.raises(M.FetchError, match="VIXHY"):
        M.series(df, "VIXHY")


def test_coverage_reports_each_index_on_its_own_last_date():
    """Per-index freshness, never a single 'the data ends here'."""
    df = pd.concat([_frame("VXHYG", [("2026-09-11", 6.31)]),
                    _frame("VIXHY", [("2026-08-14", 91.82)])], ignore_index=True)
    cov = M.coverage(df)
    assert cov.loc["VXHYG", "last"] == pd.Timestamp("2026-09-11")
    assert cov.loc["VIXHY", "last"] == pd.Timestamp("2026-08-14")
    assert cov.loc["VIXHY", "days_stale"] > cov.loc["VXHYG", "days_stale"]


# -- the panel on disk, if it has been fetched -----------------------------

def test_the_fetched_panel_is_sane_if_present():
    """Not a network test: checks what a real fetch left behind, if anything did."""
    p = REPO / "data/gamma/cboe_vol_indices.parquet"
    if not p.exists():
        pytest.skip("panel not fetched on this machine")
    df = pd.read_parquet(p)
    assert set(df.columns) == {"date", "index", "value", "fetched_at"}
    assert (df["value"] > 0).all(), "a non-positive implied vol survived"
    for idx in df["index"].unique():
        lo, hi = M.PLAUSIBLE[idx]
        s = M.series(df, idx)
        assert s.between(lo, hi).all(), f"{idx} has a value outside its range"
        assert s.index.is_monotonic_increasing and s.index.is_unique
    # the named defect must NOT be in the panel
    vx = df[(df["index"] == "VXHYG") & (df["date"] == pd.Timestamp("2017-10-30"))]
    assert vx.empty, "the known-bad VXHYG row reached the panel"
