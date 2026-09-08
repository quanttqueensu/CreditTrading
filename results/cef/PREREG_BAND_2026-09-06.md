# Pre-registration — no-trade band replaces the rebalance calendar

**Spec** `cef_discount.v5.20260731` → `cef_discount.v6.20260906`
**Written before the first session that trades it.** Trial 48 of the CEF counter.

## The change

One key added to the frozen spec: `band_width = 0.048`. It replaces the
`rebalance_days = 2` calendar. The signal is recomputed every session; a position
is left alone unless it is more than 4.8% (in portfolio weight) from target, and
is then traded back to the **band edge**, not to target.

`rebalance_days` is retained and inert. Deleting `band_width` restores v5
behaviour byte-for-byte — verified by diffing sleeve output before and after the
code change with the key absent: **identical**.

## Why

Under proportional cost the optimal policy is a no-trade band, not a fixed
interval (Constantinides 1986; Davis & Norman 1990). Our participation is ~0.7%
of ADV, so we pay half-spread — proportional — and essentially no impact.

Measured over 5,452 sessions, identical signal and identical T+1 MOC execution:

| policy | gross SR | turn/yr | net@15bp | net@30bp |
|---|---:|---:|---:|---:|
| calendar 2d (v5) | 1.20 | 31.1 | 0.33 | **−0.55** |
| **band 4.8% (v6)** | **1.16** | **17.6** | **0.66** | **+0.17** |

Two properties, not one:
1. **Net Sharpe roughly doubles on 43% less trading.** At matched turnover the
   band also earns *more gross*, because a calendar's information loss compounds
   with its interval while a band only ever discards small moves.
2. **Every calendar configuration goes negative at 30bp. Bands ≥4.8% never do.**
   Cost is the input we do not know, so we prefer the policy least sensitive to it.

## The width is derived, not fitted

Cube-root law $h^\* = (3c\sigma_w^2/2\kappa_w)^{1/3}$ on measured target-weight
dynamics ($\sigma_w = 0.04083$/day, $\phi_w = 0.95280 \Rightarrow \kappa_w =
0.04835$, half-life 14.3d): **4.26% at 15bp, 4.85% at 22bp**. Scaling verifies
exactly — $h(30)/h(15) = 1.260$ against $2^{1/3} = 1.2599$.

4.8% is the derived width at a mid-range cost estimate and the lower edge of the
measured plateau (4.8–9.6%). **6.4% topped the swept column and was deliberately
not chosen** — selecting the argmax of a sweep is how `z_window=63` was picked,
and it failed out of sample.

## Committed in advance

- **Primary readout is turnover, not P&L.** Expected ~17.6×/yr against 31.1;
  realised turnover converges in weeks, Sharpe does not (Lo 2002: SE ≈ 2.05 over
  60 sessions). If realised turnover is not materially below the calendar's
  within 20 armed sessions, the implementation is wrong — that is a code bug to
  find, not a result to interpret.
- **Average holding period should rise** from ~6 to ~12 business days.
- **We do not re-tune the width on live data.** The next legitimate change to it
  is a re-derivation from a better cost estimate, not a re-sweep.
- **No P&L-based verdict is claimed this year.** 0.33 → 0.66 is not measurable in
  60 sessions.

## Known divergences from the backtest, stated in advance

1. **Reference state is actual holdings, not a stored target.** The backtest has
   no failed fills; we do. Comparing to what we really hold makes the policy
   self-correcting — a missed session leaves the position further from target and
   the band closes it later — but it is not identical to the simulated policy.
2. **`min_abs_weight` = 0.005 wins over the band.** If the band edge lands inside
   the dust threshold the name is flattened instead, which trades slightly more
   than the band asked. Narrow window, bounded, deliberate.
3. **The backtest models neither borrow nor the minimum weight.** Borrow is
   measured at 1.22%/yr ≈ 0.23 Sharpe and applies to every policy about equally
   (`results/cef/BORROW_NOTE_2026-09-06.md`).

## What this change is NOT

Not a universe change (PHK stays; §4.1's fifth argument against it was withdrawn
when borrow was measured). Not a leverage change (6% vol target untouched). Not
a risk-control change. Not the joint cost-aware optimiser of `docs/PLAN.md` §4.5,
which measures better (net 0.90 vs 0.70 matched) but is a larger change with
3× worse turnover stability and is deliberately not deployed here.

## The caveat that dominates all of the above

**The book has armed on 3 of 26 sessions.** Twenty-one were lost to a broker port
misconfiguration (`IBKR_PORT=7497` against a gateway on 4002, corrected
2026-09-01), two to the gateway being down. Twenty-two of 24 ledger trade dates
book modelled fills for sessions that never traded, and the ledger currently
disagrees with the broker on all 17 positions.

Order sizing is unaffected — `arm()` adopts quantities from `ib.positions()`
every armed session, so deltas are computed against real broker holdings — but
**no live evidence about this change accumulates on sessions that do not arm.**
Gateway uptime, not this spec, is the binding constraint on learning anything.
