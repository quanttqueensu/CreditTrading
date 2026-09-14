"""Rebuild data/events.parquet for the deploy book — historical + FORWARD FOMC calendar.

Run:  /opt/anaconda3/bin/python3 scripts/build_events_deploy.py

Purpose (DEPLOY_CONTEXT / DEPLOY_ARCHITECTURE "data/events.parquet (FOMC)"):
the FOMC sleeve needs the SCHEDULED FOMC decision calendar, including the
forward meetings through end-2027, so the live sleeve knows upcoming day-0s.

Sources
-------
HISTORICAL (1988-02-04 .. 2026-06-17): the validated unified event table built
by archive/calendar-premia-v2/scripts/build_events*.py (USMPD + Bauer-Swanson
spines, in-house Kuttner surprises, cross-checked against federalreserve.gov
calendar pages). Copied verbatim — no re-derivation, no re-tuning. Historical
FOMC dates are re-validated here against archive events_fomc.parquet.

FORWARD (2026-07-29 .. 2027-12-08): the Federal Reserve's official meeting
calendar, https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
(page "Last Update: July 08, 2026"; verified live on 2026-07-20 and identical
to the archived copy data/raw/fed_fomccalendars.htm). Statement day = last day
of each two-day meeting, 14:00 ET. The Fed notes each date is tentative until
confirmed at the preceding meeting — the daily runner should re-check the page
when a meeting confirms/moves. * = SEP meeting (metadata only; not a signal
input).

Schema (archive src.data.events unified schema + `emergency`):
  date, time_et, event_type in {FOMC,CPI,NFP}, scheduled(bool),
  actual, consensus, surprise, surprise_z, surprise_bp, source, emergency(bool)

`emergency` = FOMC inter-meeting/unscheduled action (== ~scheduled on FOMC
rows; always False on CPI/NFP). The FOMC sleeve filters
`(event_type=="FOMC") & scheduled & ~emergency`. Forward rows have all
surprise columns NaN (nothing has happened yet) and
source = "fed_fomccalendars (Last Update 2026-07-08)".
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = REPO_ROOT / "archive" / "calendar-premia-v2"
HIST_PATH = ARCHIVE / "data" / "events.parquet"
FOMC_HIST_PATH = ARCHIVE / "data" / "events_fomc.parquet"
OUT_PATH = REPO_ROOT / "data" / "events.parquet"

FWD_SOURCE = "fed_fomccalendars (Last Update 2026-07-08)"

# Official forward scheduled FOMC statement days (last day of each meeting),
# federalreserve.gov/monetarypolicy/fomccalendars.htm, fetched 2026-07-20.
# (date, sep_meeting) — sep kept as a comment-level fact only.
FORWARD_FOMC = [
    # 2026 remaining
    "2026-07-29",  # Jul 28-29
    "2026-09-16",  # Sep 15-16 *SEP
    "2026-10-28",  # Oct 27-28
    "2026-12-09",  # Dec  8-9 *SEP
    # 2027
    "2027-01-27",  # Jan 26-27
    "2027-03-17",  # Mar 16-17 *SEP
    "2027-04-28",  # Apr 27-28
    "2027-06-09",  # Jun  8-9 *SEP
    "2027-07-28",  # Jul 27-28
    "2027-09-15",  # Sep 14-15 *SEP
    "2027-10-27",  # Oct 26-27
    "2027-12-08",  # Dec  7-8 *SEP
]

COLS = [
    "date", "time_et", "event_type", "scheduled", "actual", "consensus",
    "surprise", "surprise_z", "surprise_bp", "source", "emergency",
]


def main() -> None:
    hist = pd.read_parquet(HIST_PATH)
    hist["date"] = pd.to_datetime(hist["date"])

    # --- validate historical FOMC dates against the archive FOMC builder ---
    fomc_src = pd.read_parquet(FOMC_HIST_PATH)
    fomc_src["date"] = pd.to_datetime(fomc_src["date"])
    hist_fomc = hist[hist["event_type"] == "FOMC"]
    assert set(hist_fomc["date"]) == set(fomc_src["date"]), (
        "unified vs events_fomc date mismatch"
    )
    chk = hist_fomc.merge(fomc_src[["date", "scheduled"]], on="date",
                          suffixes=("", "_src"))
    assert (chk["scheduled"] == chk["scheduled_src"]).all(), (
        "scheduled flag mismatch vs events_fomc"
    )
    print(f"historical validated vs archive events_fomc: {len(hist_fomc)} FOMC rows, "
          f"scheduled={int(hist_fomc['scheduled'].sum())}, "
          f"emergency/inter-meeting={int((~hist_fomc['scheduled']).sum())}")

    # --- emergency flag ---
    hist = hist.copy()
    hist["emergency"] = (hist["event_type"] == "FOMC") & ~hist["scheduled"]

    # --- forward scheduled FOMC rows ---
    fwd_dates = pd.to_datetime(FORWARD_FOMC)
    last_hist = hist["date"].max()
    assert (fwd_dates > last_hist).all(), "forward date overlaps history"
    assert fwd_dates.is_monotonic_increasing and not fwd_dates.duplicated().any()
    fwd = pd.DataFrame(
        {
            "date": fwd_dates,
            "time_et": "14:00",
            "event_type": "FOMC",
            "scheduled": True,
            "actual": np.nan,
            "consensus": np.nan,
            "surprise": np.nan,
            "surprise_z": np.nan,
            "surprise_bp": np.nan,
            "source": FWD_SOURCE,
            "emergency": False,
        }
    )

    events = (
        pd.concat([hist[COLS], fwd[COLS]], ignore_index=True)
        .sort_values(["date", "event_type"])
        .reset_index(drop=True)
    )

    # --- validation ---
    assert list(events.columns) == COLS
    assert not events.duplicated(["date", "event_type"]).any()
    assert events["date"].is_monotonic_increasing
    fomc = events[events["event_type"] == "FOMC"]
    # emergency is exactly the unscheduled-FOMC flag; never both scheduled+emergency
    assert (fomc["emergency"] == ~fomc["scheduled"]).all()
    assert not events.loc[events["event_type"] != "FOMC", "emergency"].any()
    # 8 scheduled meetings every full year 1994..2027 (2026: 4 done + 4 forward).
    # Known exception: 2020 has 7 — the scheduled Mar 17-18 2020 meeting was
    # superseded by the emergency Sun 2020-03-15 action (scheduled=False).
    sched = fomc[fomc["scheduled"]]
    per_year = sched.groupby(sched["date"].dt.year).size()
    bad = per_year[(per_year.index >= 1994) & (per_year.index <= 2027) & (per_year != 8)]
    assert dict(bad) in ({}, {2020: 7}), f"scheduled FOMC count != 8: {bad.to_dict()}"
    # forward rows: scheduled, non-emergency, no invented surprises
    fmask = events["source"] == FWD_SOURCE
    assert int(fmask.sum()) == len(FORWARD_FOMC)
    assert events.loc[fmask, "scheduled"].all() and not events.loc[fmask, "emergency"].any()
    assert events.loc[fmask, ["actual", "consensus", "surprise", "surprise_z",
                              "surprise_bp"]].isna().all().all()

    out = events.copy()
    out["date"] = out["date"].dt.date  # store as DATE like the archive table
    OUT_PATH.parent.mkdir(exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)

    print(f"\nwrote {OUT_PATH}")
    print(f"N={len(events)} rows, sample {events['date'].min():%Y-%m-%d} .. "
          f"{events['date'].max():%Y-%m-%d}")
    print("by type:", events["event_type"].value_counts().to_dict())
    print(f"FOMC: N={len(fomc)}, scheduled={int(fomc['scheduled'].sum())}, "
          f"emergency={int(fomc['emergency'].sum())}, forward={int(fmask.sum())}")
    print("\nforward scheduled FOMC statement days (source: federalreserve.gov "
          "fomccalendars.htm, Last Update 2026-07-08, fetched 2026-07-20):")
    for d in FORWARD_FOMC:
        print(f"  {d}")


if __name__ == "__main__":
    main()
