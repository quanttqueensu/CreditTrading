# CEF discount — sealed holdout pre-registration

**Written 2026-07-31, BEFORE the holdout was run.** Authorised by Simon
("1" — freeze and open the holdout now).

## The specification under test — frozen, no further changes

`ops/specs/cef_discount.frozen.json`, **`spec_id: cef_discount.v3.20260731`**

| parameter | value | chosen how |
|---|---|---|
| universe | 17 credit CEFs, PIT-eligible | ADV >= $3m evaluated per date |
| `z_window` | **63** | 2005-2023 sweep, interior optimum |
| `rebalance_days` | **2** | 2005-2023 sweep, interior optimum |
| execution shift | **2** | MOC fills at close(t+1), not close(t) |
| `vol_target_annual` | 0.06 | unchanged since deployment |
| `min_adv_usd` | 3,000,000 | unchanged |
| `max_nav_age_bd` | 3 | unchanged |
| `min_names` | 6 | unchanged |
| `min_abs_weight` | 0.005 | unchanged |
| `gross_leverage` | 1.0 | unchanged |
| costs | per-name half-spread, `SCENARIOS['base']` | unchanged |

## Holdout window

**2024-01-01 → 2026-07-30.** Never evaluated. Every parameter above was selected
on 2005-01-01 → 2023-12-31 only.

## The pre-registered question

> Does the frozen v3 configuration earn a **positive net Sharpe** on 2024-01+?

## Decision rule, committed in advance

| holdout net Sharpe | verdict |
|---|---|
| **>= +0.40** | PASS — config change justified, keep trading, raise nothing |
| **0.00 to +0.40** | WEAK — keep the sleeve live at current size, do not add capital, no further spec work on this source |
| **< 0.00** | FAIL — the 2005-2023 result did not generalise. Halt the sleeve and flatten. |

The 0.40 threshold is roughly half the pre-holdout net of 0.84, which is the
standard haircut for a result selected over ~29 trials on this source
(deflated-Sharpe haircut at N=29 is sqrt(2*ln 29) = 2.60 sigma).

## What is being run, and once only

One script, one pass, both configurations reported:

1. **v3 frozen** (`z_window=63, rebalance=2`) — the specification under test.
2. **as-deployed this morning** (`z_window=252, rebalance=5`) — a reference point,
   NOT a selection. The choice between them was already made on pre-2024 data and
   will not be revisited on the basis of the holdout. It is reported so that a
   reader can see whether the improvement generalised or merely the level did.

No variants. No re-runs with adjustments. Whatever it prints is the answer, and
it is recorded in `results/cef/HOLDOUT_OPENED.json` with a UTC timestamp.

## Known reasons this could fail, stated in advance

- The 2023-26 era net Sharpe was already the weak one (0.30) on the old config.
- The most recent purged walk-forward block scored 0.05.
- Kurtosis is 41.2; a 2.5-year window is short enough that one bad week moves the
  Sharpe materially.
- `z_window=63` was selected over four window values and is the newest, least
  tested parameter in the specification.

If it fails, it fails. The point of sealing it was to be able to believe the
answer.
