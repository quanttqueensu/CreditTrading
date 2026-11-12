# Shadow universes

Lists of symbols a shadow book may trade. Each is built from files already in the repository,
never typed by hand, and each says where it came from.

| file | what | built from |
|---|---|---|
| `cef_v1.csv` | 91 US closed-end funds: the 74 frozen for C4, the core's 13, and the four municipal funds dropped on 2026-09-28 | `results/cef/c4/c4_universe_frozen_2026-10-14.csv`, `ops/specs/cef_discount.frozen.json` (`frozen.universe`), `docs/SYSTEM.md` §5 (2026-09-28, "Universe on Alpaca") |
| `units_v1.csv` | 48 listed partnership and trust units that paid a distribution in the 400 days to 2026-11-11, with Alpaca's shortable flag on that date | `python3 -m shadow.universes.build_units_v1`: Nasdaq Trader's symbol directory and a name rule, then Alpaca (tradable, a cash distribution on the feed). `docs/REFERENCES.md` §12sd |

`cef_v1` is the funds this desk already knows, not the market: CRSP holds about 576 funds a
day (`results/ideas/2026-11-10_cef_exdate_drift.md`). Widening it needs a public source that
classifies a listing as a closed-end fund; CRSP's rows are licensed and stay out of the
repository.

`units_v1` is rebuilt from public sources because CRSP's own list cannot be published. Checked
locally on 2026-11-11: it holds 46 of the 51 CRSP units with an ex-date since 2025-06. 14 of the
48 were not shortable at Alpaca that day; a shadow book ignores borrow, so its short leg
overstates what a paper account could hold.
