# E1 on Alpaca paper: the broker check — 2026-10-28

**Zero trials. Read-only.** This is the first step of `quant-trader`'s rollout for E1, which the team lead
ruled eligible for the paper book on 2026-10-28 (`docs/SYSTEM.md` §5). Reproduce it by re-reading the two
sources below. Alpaca's asset endpoint was read through the session's connector tools
(`get_asset NZF`, `get_asset MMU`) on 2026-10-28.

## The answer: E1 as specified cannot run on Alpaca paper

E1 is the NAV-for-NAV CEF merger pair: long the target, short the acquirer, held from A+1 to completion
(`results/events/PREREG_E1_MERGER_PAIR_2026-10-19.md`). Its payoff is realised at completion, when the
target's shares convert into the acquirer's. Two things block it on paper.

1. **Alpaca paper does not process mergers, or any corporate action** [V, Alpaca staff on the Alpaca
   forum].
   - "paper accounts do not implement any corporate actions such as stock splits or dividends", a staff
     reply of 2026-07-15 (https://forum.alpaca.markets/t/corporate-actions-handeling/19325). The only
     workaround it offers is "deleting the account and recreating it".
   - "the paper trading environment doesn't implement corporate actions including stock splits", a staff
     reply of 2024-06-10 (https://forum.alpaca.markets/t/paper-account-nvda-stock-split-issue/14412).
   - Alpaca's mandatory-corporate-actions documentation
     (https://docs.alpaca.markets/us/docs/mandatory-corporate-actions) describes only live processing.
     It says nothing about paper.
   - So a long target held to completion is never converted on paper. It stays as a merged-away symbol
     that a forum report says could not be sold, and the pair's P&L is never realised in the record.
2. **The short leg is half unavailable** [V, Alpaca asset endpoint, 2026-10-28]. The two pending muni
   acquirers named on 2026-10-13 (`results/events/G1A_SHORTABILITY_2026-10-13.md`):
   - **NZF: `shortable` false, `borrow_status` hard_to_borrow;**
   - MMU: shortable, easy to borrow.
   `borrow_status` changes daily, and this is true on its date only.

## What this means beyond E1

**The live paper book has the same exposure.** If a CEF the book holds splits or reverse-splits, Alpaca
paper will not adjust the position. A held fund that merges away will also not convert. A search of
`quantt/session/` found no corporate-action handling. This is an operations finding for the team lead,
not a research one. `CLAUDE.md` landmine 1 now says so.

## Options for E1, for the team lead

- **A shadow record:** decide E1's targets each session and score them off-broker with the conversion
  modelled. It spends nothing and decides nothing. Modelled sessions are not evidence (`CLAUDE.md`).
- **A new expression that exits before completion:** close the target on the day before the merger's
  effective date, so no corporate action is needed. That is a new EVENTS trial under the standing
  declared N = 6, and it needs a power check and a pre-registration first. The short leg is still blocked
  where the acquirer cannot be borrowed.
- **IBKR paper** (the second broker, equities only; team lead, 2026-10-19). Whether IBKR paper processes
  CEF mergers is **[U]**. The team lead holds that account.
