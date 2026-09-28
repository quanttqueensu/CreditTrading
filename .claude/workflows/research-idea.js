export const meta = {
  name: 'research-idea',
  description: 'Research department: take one idea from graveyard check to a reviewed, pre-registered harness result',
  whenToUse: 'Run with args = the idea in one or two sentences. Spends at most one trial, and only after the team lead approves the pre-registration.',
  phases: [
    { title: 'Screen', detail: 'graveyard + counterparty' },
    { title: 'Pre-register', detail: 'draft only; the team lead approves' },
    { title: 'Test', detail: 'harness run, gross headline + cost grid' },
    { title: 'Attack', detail: 'beta-detector + quant-reviewer, independently' },
    { title: 'Verdict', detail: 'D1-D7 synthesis' },
  ],
}

// WHY THIS SHAPE. Every mechanism this desk has killed died in one of two
// places: it was already in the graveyard (a stale-price artifact, or a control
// group scoring as well as the treatment), or it was scored by the person who
// built it. So the screen runs before any code, the pre-registration is written
// before any number is seen, and two adversaries who did not build the test
// attack it independently. The trial counter moves only with the team lead's
// approval of the pre-registration (CLAUDE.md research rules).

const IDEA = typeof args === 'string' ? args : (args && args.idea)
if (!IDEA) throw new Error('research-idea needs args = the idea text')
const V = { type: 'object', properties: {
  verdict: { type: 'string' }, dead_match: { type: 'string' }, who_loses: { type: 'string' },
  proceed: { type: 'boolean' }, notes: { type: 'string' } }, required: ['verdict', 'proceed', 'notes'] }

phase('Screen')
const screen = await agent(`Idea: "${IDEA}".
Run the /graveyard skill and read docs/RESEARCH_STATE.md and docs/BRIEF.md. Is this idea (or its mechanism) already dead? Name the closest dead entry and how it died. Then, as the alpha-finder seat, name who is on the other side of the trade and why they would keep losing. proceed=false if it is a restatement of a dead idea with no new mechanism. Never invent a figure; cite files.`,
  { label: 'graveyard+counterparty', phase: 'Screen', agentType: 'alpha-finder', schema: V })
if (!screen || !screen.proceed) return { stage: 'screen', screen }

phase('Pre-register')
const prereg = await agent(`Idea: "${IDEA}". Screen result: ${JSON.stringify(screen)}.
Use the /prereg skill to DRAFT a pre-registration at results/research/PREREG_DRAFT_<slug>.md (do not commit, do not touch docs/RESEARCH_STATE.md — the team lead approves the trial). State: hypothesis, mechanism, the exact test on the canonical harness (scripts/cef/band_frontier.py, shift(2), total returns), turnover matching, eras H5, fit < 2023-01-01 with a 2023-26 holdout row, the negative control (H12), what result kills it, and which counter it would spend. Return the file path and a 5-line summary.`,
  { label: 'prereg-draft', phase: 'Pre-register' })

phase('Test')
const test = await agent(`Idea: "${IDEA}". Pre-registration draft: ${prereg}
Implement exactly the pre-registered test by EXTENDING scripts/cef/band_frontier.py's functions visibly (/harness skill) in a new script under scripts/research/<slug>/, reading data/ only and writing output under results/research/<slug>/ (never data/ — CLAUDE.md landmine 9). Headline table: GROSS P&L; beside it net at 5/15/30bp, labelled; say whether the sign flips across the grid; eras; holdout row; panel last date stated. No sweeping and picking. Return the table and the reproducer command.`,
  { label: 'harness-run', phase: 'Test' })

phase('Attack')
const [beta, qr] = await parallel([
  () => agent(`Assume this result is false and prove it: risk premium in costume, stale-price artifact, data bug, or lookahead. Idea: "${IDEA}". Result: ${test}`,
    { label: 'beta-detector', phase: 'Attack', agentType: 'beta-detector', schema: V }),
  () => agent(`Review the code and numbers behind this result for lookahead, alignment, silent fallbacks, unit errors, turnover mismatch, harness deviations. Idea: "${IDEA}". Result: ${test}`,
    { label: 'quant-reviewer', phase: 'Attack', agentType: 'quant-reviewer', schema: V }),
])

phase('Verdict')
const verdict = await agent(`Synthesize a verdict for the team lead on idea "${IDEA}" using the D1-D7 legend in docs/RESEARCH_STATE.md. Inputs — screen: ${JSON.stringify(screen)}; prereg: ${prereg}; test: ${test}; beta-detector: ${JSON.stringify(beta)}; quant-reviewer: ${JSON.stringify(qr)}. If either adversary found a real defect, the verdict is 'not established' until fixed. Write results/research/<slug>/VERDICT.md (provenance labels [V]/[S]/[U] on every figure) and return its text. Do not update the trial counter; list the exact edit the team lead would approve.`,
  { label: 'verdict', phase: 'Verdict' })
return { screen, prereg, test, beta, qr, verdict }
