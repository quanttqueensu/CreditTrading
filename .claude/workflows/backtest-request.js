export const meta = {
  name: 'backtest-request',
  description: 'Backtest department: answer one backtest question on the canonical harness, then have it independently re-derived and reviewed',
  whenToUse: 'Run with args = the question (e.g. "band 4.8% vs 6% on the 13-name universe, turnover-matched"). Report only; spends no trial and changes no spec.',
  phases: [
    { title: 'Run', detail: 'canonical harness, gross headline + cost grid' },
    { title: 'Check', detail: 'independent re-derivation + review' },
    { title: 'Report', detail: 'one table, provenance labelled' },
  ],
}

// WHY TWO RUNS. "Double-check anything that drives a decision — a second
// method" (CLAUDE.md data rules). The second agent re-derives the headline
// without reading the first agent's script, so a shared bug cannot agree with
// itself. Disagreement is reported, never averaged.

const Q = typeof args === 'string' ? args : (args && args.question)
if (!Q) throw new Error('backtest-request needs args = the question')

phase('Run')
const run = await agent(`Backtest question: "${Q}".
Use the /harness skill: extend scripts/cef/band_frontier.py (build_targets, band, band_gross_capped, evaluate, total_returns), shift(2), total returns, parameters from scripts/cef/spec.py (never literals). If the question needs data beyond data/cef (e.g. CRSP, TRACE, factors), use src/data/r2.py per docs/DATA.md, read-only. Output under results/backtests/<slug>/, never data/. Report: GROSS headline (SR, ann %, vol, maxDD, turn/yr) with net@5/15/30bp beside it labelled; eras H5; fit (<2023) and 2023-26 rows; turnover-matched if comparing policies (H2); panel last date. Return the table, the reproducer command and the exact definitions used.`,
  { label: 'harness-run', phase: 'Run' })

phase('Check')
const [rederive, review] = await parallel([
  () => agent(`Independently re-derive ONLY the headline gross Sharpe and annual return for this backtest question, WITHOUT reading any script under results/backtests/ or scripts written today: "${Q}". Use the canonical harness functions directly. Then compare to this reported result and state agree/disagree with the numbers side by side: ${run}`,
    { label: 're-derive', phase: 'Check' }),
  () => agent(`Review this backtest for lookahead, alignment, turnover mismatch, silent fallbacks and harness deviations. Question: "${Q}". Result: ${run}`,
    { label: 'quant-reviewer', phase: 'Check', agentType: 'quant-reviewer' }),
])

phase('Report')
const report = await agent(`Write the final report for the team lead to results/backtests/<slug>/REPORT.md and return its text. Question: "${Q}". Run: ${run}. Independent re-derivation: ${rederive}. Review: ${review}. Label every figure [V]/[S]/[U]; if the re-derivation disagrees or the review found a real defect, say so at the top and do not present the number as established.`,
  { label: 'report', phase: 'Report' })
return { run, rederive, review, report }
