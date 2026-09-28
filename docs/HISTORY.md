# History — what was tried before the clean slate, on one page

**Why this exists.** On 2026-09-28 the team lead deleted everything not needed to
run the strategy on Alpaca: the IBKR system, the archive, ~140 dated research notes
and a dozen research families. This page is what survives of them, so that nothing
is rebuilt by accident. **The canonical record of what is dead is the KILLED table
in `docs/RESEARCH_STATE.md`** — read it before proposing anything (`/graveyard`).

**Every deleted file is recoverable** from the git tag `pre-clean-slate`:

```bash
git show pre-clean-slate:<path>                  # read one file
git checkout pre-clean-slate -- <path>           # bring it back
git ls-tree -r --name-only pre-clean-slate | grep <word>   # find it
```

The IBKR-era code alone is also tagged `ibkr-final`.

## Timeline

| when | what happened |
|---|---|
| 2026-07 | Credit-ETF research (credit_rv, E1 premium/discount, forced flow, staleness, lead-lag, dealer inventory). All died; see KILLED. |
| 2026-07-31 | The CEF discount-reversion book deployed on an IBKR paper account ($500k). The first night's overnight market orders cost far more than modelled → order type fixed to MOC. |
| 2026-08 | A 21-session silent outage: the book refused to arm and every surface read "ok". → outcome-based verification and the rule "silence must never read as success". |
| 2026-09-06 | Trading policy moved from a 2-day calendar to a derived **no-trade band** (`results/cef/PREREG_BAND_2026-09-06.md`). |
| 2026-09-10 | The execution convention was corrected to `shift(2)` (decide *t*, fill *t+1* close, earn *t+2*); several "established" results were re-scored and weakened. |
| 2026-09-13 | Options/credit-gamma programme closed: the book is not short volatility in a way a hedge can use, and no conditioner times gamma. |
| 2026-09-14/15 | IBKR shadow-ledger desyncs halted all three books. The last broker-confirmed fill was 2026-09-15. |
| 2026-09-16 | v7 constraints pre-registered: group cap 0.30, gross ceiling (`results/cef/PREREG_GROUP_CAP_2026-09-16.md`). |
| 2026-09-28 | IBKR retired (final flatten sent, left unconfirmed by decision); move to Alpaca paper; clean slate. |

## What the research established (and what it did not)

- **Established:** the discount signal has a real, persistent IC at the traded
  horizon across sub-periods; it is not credit beta, not one name, not reversal.
- **Not established:** that the traded band policy survives out of sample — it was
  never walk-forwarded, bootstrapped or deflated. The sealed CEF holdout was opened
  once and its net verdict was FAIL. Survivorship bias is unmeasured.
- **Borrow:** at measured IBKR fees, borrow roughly equalled the gross edge on the
  short leg in recent years. The team lead ruled (D19/D20, 2026-09-15) that paper is
  scored on gross P&L; the real-money view is kept beside it, labelled.

## Lessons that became rules (all in `CLAUDE.md`)

- **Picking the argmax of a swept column fails** (`z_window = 63`: gross 1.75, net
  −0.30 out of sample, hours after adoption). Derive, then check the plateau.
- **Stale prices fake alpha.** The most common cause of death here was a
  non-synchronous-price artifact; the second, a control group scoring as well as
  the treatment.
- **The trade phase is not idempotent.** A second armed run doubles the book.
- **The ledger is a reconstruction; the broker is the fact.** Every IBKR halt in
  September came from the local ledger disagreeing with the account.
- **Confident wrong numbers cost more than missing ones.** Fetch, don't recall.
