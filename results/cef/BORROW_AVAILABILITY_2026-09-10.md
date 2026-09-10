# Borrow availability — the dispute cannot be settled the way W8 proposes

**Date: 2026-09-10.** Panel `data/cef/cef_borrow.csv`, last date **2026-09-10**, 4 dates
(2026-09-06, -09-08, -09-09, -09-10), 17 names each. All figures below re-read from that
panel today. Supersedes nothing; extends `BORROW_NOTE_2026-09-06.md`.

`W8` part A asks for "a week of paired readings" to settle whether NAD has 3,000 lendable
shares or 83,942. **That plan is not executable, and no amount of waiting will make it so.**

## Why

The two numbers come from two different sources that **have never both reported on the same
date**, and one of them is now permanently gone. [V]

| date | day | `available_shares` (public file) | `api_shortable_shares` (TWS tick 236) |
|---|---|---:|---:|
| 2026-09-06 | Sunday | 17/17 | 0/17 |
| 2026-09-08 | Tuesday | 17/17 | 0/17 |
| 2026-09-09 | Wednesday | 0/17 | 0/17 |
| 2026-09-10 | Thursday | 0/17 | **16/17** |

**Paired readings in the panel: zero.** The file stopped answering exactly when the API
started. For NAD specifically: [V]

| date | fee %/yr | file avail | API avail |
|---|---:|---:|---:|
| 2026-09-06 | 9.98 | 3,000 | — |
| 2026-09-08 | 9.98 | 3,000 | — |
| 2026-09-09 | 10.21 | — | — |
| 2026-09-10 | 10.88 | — | **83,942** |

The "3,000 vs 83,942" disagreement is **four days and two sources apart**. It is not a
contradiction anyone can resolve by measuring more carefully; it is two different
instruments, never pointed at the market at the same moment.

## The file source is dead, not flaky

`https://www.interactivebrokers.com/shortstock/usa.txt` → **HTTP 404**, verified today. So
is the directory, `www.ibkr.com/shortstock/usa.txt` (302 → the same 404), the
`/en/pagefiles/` and `gdcdyn` variants, and the `ftp3.interactivebrokers.com` mirror
(connection timeout). IBKR's own *Short-Securities Availability* page no longer links a
downloadable file at all — only the Client Portal and TWS tools. [V]

`scripts/cef/fetch_borrow_rates.py` already handles this: since commit `43ec054` it catches
the 404 and takes fees from `reqHistoricalData(whatToShow="FEE_RATE")` instead. That path
**works** — today's 17/17 fee rates and 16/17 availability figures came from it. [V]

**So a paired reading can never be taken again.** W8 part A should be closed on that basis,
not left open pending a week of data that cannot arrive.

## What the two sources actually are

Not a measurement disagreement — a **granularity** disagreement:

- Every file value is a round multiple of 1,000. The thirteen distinct values across 17
  names were 3,000 / 20,000 / 150,000 / 250,000 / 650,000 / 900,000 / 950,000 / 1,000,000 /
  1,300,000 / 1,800,000 / 2,500,000 / 5,700,000 / 6,400,000. [V]
- No API value is round: 83,942 / 102,491 / 149,125 / 217,707 / 275,577 / 286,462 … [V]

The file reports a **rounded tier**; the API reports a **count**. Read that way, "3,000" is a
floor on a bucket, not an assertion that exactly 3,000 shares are lendable.

**One inference I explicitly do not draw.** The file's values are identical across 09-06 and
09-08 on all 17 names, fee *and* availability. That looks like a static table — but 09-06 was
a Sunday and 09-07 was not an NYSE trading day, so an unchanged file across that span is
equally consistent with a stale weekend publication. Two dates spanning a holiday weekend
cannot separate the two, and the source is now dead, so this will not be resolved. It is
recorded as an observation, not a conclusion. [U]

## What the short leg actually looks like today

Availability against the live short positions (`positions.csv`, last date 2026-09-09): [V]

| ticker | fee %/yr | API avail | short shares | cover |
|---|---:|---:|---:|---:|
| NAD | 10.88 | 83,942 | 6,550 | 12.8× |
| MHD | 0.41 | 102,491 | 8,856 | 11.6× |
| NVG | 3.62 | 149,125 | 4,679 | 31.9× |
| JFR | 1.53 | 893,530 | 5,837 | 153× |
| MQY | 0.54 | 217,707 | 1,750 | 124× |
| NZF | 2.46 | 275,577 | 271 | 1,017× |
| **NEA** | 3.39 | **no reading** | 7,118 | **unknown** |

**No name is under 5× cover.** On today's reading the availability cap binds on nothing, and
the "18.7% of the short book unbuildable" scenario does not reproduce. That is *one* day of
the only source that still exists — it is not yet a series.

Two things to carry forward rather than conclude:

1. **NEA returned no availability tick** (16/17). It is the second-largest short leg at 7,118
   shares. A missing reading is not an abundant one; until it reports, NEA's availability is
   a stated gap, not a pass.
2. **NAD and HYT cost ~10.9% and ~10.6% a year to borrow.** That is the number that survived
   the source change — fee rates are present on all four dates from both eras and move
   plausibly day to day (NAD 9.98 → 10.21 → 10.88). Availability was the disputed quantity;
   **cost** is the one that is actually measured, and it is large. NAD alone at 6,550 shares
   is a real annual drag and belongs in the joint optimiser before any availability cap does.

## Recommendation

- Close the W8 part A paired-reading plan as **not executable**; record why.
- Take the daily TWS tick-236 reading as the availability source of record, with its
  limitation stated: delayed data (`reqMarketDataType(3)`), one broker's book, no history.
- Do not size anything on a single day's availability. Do let the **fee** panel, which is
  four dates deep and consistent, feed the cost work in `W7`/`W12` now.
- Chase NEA's missing tick before treating the 17-name availability picture as complete.
