# Research loop state

The daily `research-loop` workflow (`.claude/workflows/research-loop.js`) reads and
writes this file. It holds what the loop has done and what it is in the middle
of. It holds no queue: the queue is `docs/SYSTEM.md` §5 (the 2026-10-27 re-opens,
in their stated order), then `docs/RESEARCH_STATE.md` ACTIVE/WATCH. The loop reads
those at run time, so there is no second copy to drift.

Rulings the loop runs under: `docs/SYSTEM.md` §5, 2026-10-27 ("the research
method" and "the autonomous loop and the harness").

## In progress

(none)

## Owned elsewhere

- The trial P&L series backfill ("backfill what is reproducible", SYSTEM.md §5,
  2026-10-27) belongs to the desk-research-method session, which writes through
  `scripts/research/registry.py`.

## History

| date | idea | outcome | commit |
|---|---|---|---|
| 2026-10-28 | C2 Part C: size the CEF book's between-group bet with a two-sleeve, derived budget (`results/research/loop/2026-10-28.md`) | **STOPPED AT SCREEN**, 0 trials, CEF stays 52. The closest priors are INCONCLUSIVE on the fit period and Part C does not change the power (P(pass) about 0.01–0.02 at the CEF bar). The bet's size needs a team-lead ruling, and so does the evaluation set (W10-B §10.1). Do not re-pick Part C or Part D before either ruling. | no trial commit; ran at `73639d5`; the report's commit is `git log -1 -- results/research/loop/2026-10-28.md` |
