# Superseded prompts (2026-09-07 → 2026-09-08)

These 51 files were consolidated on **2026-09-09** into the 14 `W*` prompts and
`00_BRIEF.md` one directory up. Nothing was dropped: every task, decision rule,
falsifier and "do not" from these files is carried in the new set. Kept for
provenance — for what a prompt said when it was written, and for the amendment
notes that record how the plan changed between 09-07 and 09-08.

Two things in here are now known to be **wrong** and were corrected in the new
set; do not paste these files into a session:

1. `18_P3.2`, `22_P3.6` and others assert an ex-distribution date "moves price
   and not NAV". The distribution leaves the fund's assets, so **NAV drops on
   the ex-date too**, and the discount barely moves. See `00_BRIEF.md` §3 and
   `W4_artifact_battery.md` Part A.
2. `35_P6.3` gives the muni group a SOFR-based leverage-cost conditioner. Nuveen
   munis lever through tender option bond trusts whose floaters reset to
   **SIFMA**, not SOFR. See `W10_breadth_and_groups.md` Part D.

`01_P0.1_dust_orders.md` is the one prompt that was fully executed; its result
is `results/cef/DUST_ORDERS_2026-09.md`.

## Where each went

| old | new |
|---|---|
| 00_README | 00_BRIEF |
| P0.1 dust orders | **done**; recorded in W5's header |
| P0.2 phantom flatten, P3.4 order lifecycle | W5 |
| P0.3 hardening, P2.1–2.3, P3.1–3.3, P3.5, P3.6, P4.1, P4.2 | W9 |
| P0.4 alerting, P4.3 session watch, P8.1 timing, P8.2 data | W3 |
| P0.5 risk keys, P1.5 vol target | W6 |
| P1.1 availability cap, P1.2 borrow scoring, P6.6 borrow by group | W8 |
| P1.3 cost, P1.4 turnover, P6.7 execution by group | W7 |
| P1.6 tick screen + the 27, P6.1–P6.4, P6.8 | W10 |
| P1.7 joint shadow, P5.1 structured Σ, P5.2 c_model | W12 |
| P1.8 price tilt, P5.3 turnover targeting, P5.7 + P6.5 band/resolution | W11 |
| P5.4 NAV unsmoothing, P8.5 intraday | W13 |
| P5.5 survivorship, P5.6 inference, P8.6 holdout | W1 |
| P7.1–P7.4, P8.4 timed gamma | W14 |
| P8.3 account audit | W2 |
| — | **W4 is new**: the artifact battery (bid-ask bounce, stale NAV, ex-date, crisis and seasonal concentration, clustered SEs) plus the total-return correction |

## Second consolidation, 2026-09-09 (same day)

After a ten-agent research pass, the set was restructured again into three
tracks. Nothing above changed status; what changed is where the forward work
lives:

| track | files | what it is |
|---|---|---|
| `../W1`–`W14` | 15 | the CEF book, as consolidated earlier today |
| `../perfund/F1`–`F3` | 3 | **new** — the per-fund architecture: characteristics panel, group forms with fund-level shrinkage, seventeen sleeves |
| `../gamma/G0`–`G7` | 8 | **new** — gamma scalping as a standalone programme with its own trial counter |

Two further changes to the W set on the same day:

- **`W14_options.md` was narrowed** to the CEF book's *use* of options — the
  stress-beta measurement, the convexity overlay, and vol-as-information. Its
  learning book moved to `gamma/G5` and its timed sleeve to `gamma/G7`.
- **`W10` Part D was superseded** by `perfund/F2`, which generalises it from
  group-pooled slopes to per-fund shrunk slopes. W10's other parts stand.

A third factual error was found and corrected in the W set itself (not only in
these archived files): **MQY and MHD are BlackRock funds, not Nuveen.** That
splits the muni group across two leverage mechanisms — Nuveen's tender option
bonds reset to SIFMA, BlackRock's preferred shares do not — so they cannot share
a financing conditioner. See `../W10` Part D and `../perfund/F2` Part B.
