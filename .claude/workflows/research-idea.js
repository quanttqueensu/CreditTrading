export const meta = {
  name: 'research-idea',
  description: 'Research line: take one idea through question, data, power, pre-registration, a single test, two adversaries and the book, to a verdict that names both the evidence and the gate',
  whenToUse: 'Two runs. First args = the idea (string) or {idea}: screens, audits the data, computes power and drafts the pre-registration, spending nothing. Then, after the draft is approved as CLAUDE.md and docs/SYSTEM.md §5 require and is committed, args = {idea, stage: "test", prereg: "<path>", prereg_sha: "<commit>", approved: true} runs the test and spends the one trial.',
  phases: [
    { title: 'Screen', detail: 'quant-researcher: graveyard, loser, components' },
    { title: 'Data', detail: 'data-engineer then data-analyst; no returns' },
    { title: 'Power', detail: 'statistician: design and P(pass); stops if underpowered' },
    { title: 'Pre-register', detail: 'draft only; the run stops here for approval' },
    { title: 'Test', detail: 'backtest-engineer or ml-engineer: one run, P&L stored' },
    { title: 'Attack', detail: 'beta-detector, quant-reviewer, statistician, portfolio-manager, quant-trader' },
    { title: 'Verdict', detail: 'evidence outcome + D-code + successor entries' },
  ],
}

// WHY THIS SHAPE (rebuilt 2026-10-27). A zero-trial audit of 82 kills
// (results/research/DESK_METHOD_2026-10-27.md) found three process failures:
//
// 1. Power was forecast and then ignored. The NAV-tender pre-registration put
//    P(pass) at 0.02 and E1's at 0.15; both trials were spent anyway. So the
//    statistician computes P(pass) at every gate BEFORE the draft, and the run
//    stops below min_power. Only the team lead overrides that, with
//    override_power.
// 2. The old version of this workflow went straight from DRAFTING the
//    pre-registration to the TEST in one run. Nothing waited for approval,
//    although whenToUse said it did. The test stage now refuses to start without
//    {prereg, prereg_sha, approved: true}, which only a second run supplies. WHO
//    may approve is CLAUDE.md's and SYSTEM.md §5's to say, read at run time. On
//    2026-10-27 that is the team lead; a ruling on agent self-approval was made in
//    another session and was not yet recorded there.
// 3. Verdicts named the gate that fired, not what was found (C5 labelled D1 with
//    a replicated gain; E1 labelled D4 with every beta near zero), and a passing
//    component died with its expression. So every verdict carries the evidence
//    outcome (PRESENT / ABSENT / INCONCLUSIVE, from scripts/research/inference.py
//    read_result) beside the D-code. The portfolio-manager reads each sleeve's
//    marginal contribution to the book beside its standalone figures, and every
//    PRESENT effect whose gate failed gets a successor entry.
//
// The person who designs a test does not run it, and the two adversaries did not
// build it: the stations are separate agents on purpose.
//
// HARDENED THE SAME DAY after an independent review:
// - an agent that returns nothing stops the run (a crashed quant-reviewer once
//   read the same as a clean review);
// - the power gate can only be tightened by args, never loosened without
//   override_power === true;
// - the gate takes the MINIMUM over every P(pass) the statistician reports,
//   including a simulated joint P(pass all), and refuses missing or out-of-range
//   numbers;
// - the approved pre-registration is read at a pinned commit, so no station can
//   edit what was approved (as release-check.js pins its tree since 2026-10-10).

const A = typeof args === 'string' ? { idea: args } : (args || {})
const IDEA = A.idea
if (!IDEA) throw new Error('research-idea needs args = the idea text, or {idea, ...}')
const STAGE = A.stage || 'design'
const DEFAULT_MIN_POWER = 0.5
const OVERRIDE = A.override_power === true
if (A.min_power !== undefined && !(typeof A.min_power === 'number' && A.min_power >= 0 && A.min_power <= 1)) {
  throw new Error(`min_power must be a number in [0, 1], got ${JSON.stringify(A.min_power)}`)
}
if (typeof A.min_power === 'number' && A.min_power < DEFAULT_MIN_POWER && !OVERRIDE) {
  throw new Error(`min_power ${A.min_power} loosens the power gate below ${DEFAULT_MIN_POWER}; only the team lead does that, with override_power: true`)
}
const MIN_POWER = typeof A.min_power === 'number' ? A.min_power : DEFAULT_MIN_POWER
const need = (x, what) => { if (x === null || x === undefined) throw new Error(`${what} returned nothing; the run stops rather than read a missing result as a clean one`); return x }
const P = { type: 'number', minimum: 0, maximum: 1 }

const GO = { type: 'object', properties: {
  proceed: { type: 'boolean' }, summary: { type: 'string' }, notes: { type: 'string' } },
  required: ['proceed', 'summary'] }
const POWER = { type: 'object', properties: {
  binding_gate: { type: 'string' },
  p_pass_binding: P,
  p_pass_all: P,
  gates: { type: 'array', minItems: 1, items: { type: 'object', properties: {
    gate: { type: 'string' }, p_pass: P, how: { type: 'string' } },
    required: ['gate', 'p_pass'] } },
  meaningful: { type: 'string' },
  independent_units: { type: 'string' },
  design: { type: 'string' },
  redesign_options: { type: 'array', items: { type: 'string' } },
  proceed: { type: 'boolean' }, notes: { type: 'string' } },
  required: ['binding_gate', 'p_pass_binding', 'p_pass_all', 'gates', 'meaningful', 'design', 'proceed'] }
const READ = { type: 'object', properties: {
  finding: { type: 'string' }, defect_or_explanation: { type: 'string' },
  severity: { type: 'string' }, settles_it: { type: 'string' }, notes: { type: 'string' } },
  required: ['finding'] }

if (STAGE === 'design') {
  phase('Screen')
  const screen = await agent(`Idea: "${IDEA}".
Act as the quant-researcher station. Run /graveyard and read docs/RESEARCH_STATE.md. Name the closest dead entry and what its death actually showed: ABSENT (a powered null, an artifact, a control that scored as well), INCONCLUSIVE (too weak to tell), or PRESENT with a failed gate. If it restates an ABSENT idea with no new mechanism or data, set proceed=false. Otherwise give: the mechanism and the loser; the components (effect / expression / conditioner / execution) and which one this test is about; the negative control; a plausible effect size from a cited prior or measured magnitude, labelled [V]/[S]/[U]; the count of independent units likely available; the holding window; the counter it would spend (from python3 -m ops.orient TRIALS).`,
    { label: 'quant-researcher', phase: 'Screen', agentType: 'quant-researcher', schema: GO })
  if (!screen || !screen.proceed) return { stage: 'screen', outcome: 'STOPPED AT SCREEN', screen }

  phase('Data')
  const source = await agent(`Idea: "${IDEA}". Screen: ${screen.summary}
Act as the data-engineer station. Build the idea × data matrix: primary and independent secondary source; earliest usable year; the count of independent units before 2023-01-01; the point-in-time field; survivorship; terms for automated research use, quoted; existing fetcher by path or one to build. proceed=false if no usable pre-2023 history exists (say what forward-only protocol the team lead would have to rule on) or if the terms forbid storage. Compute no returns.`,
    { label: 'data-engineer', phase: 'Data', agentType: 'data-engineer', schema: GO })
  if (!source || !source.proceed) return { stage: 'data', outcome: 'STOPPED AT DATA', screen, source }
  const audit = await agent(`Idea: "${IDEA}". Data matrix: ${source.summary}
Act as the data-analyst station on the series available locally. Audit coverage, last dates, stale-price signatures, bad bars and Stage-0 flags, alignment and survivorship. Profile the candidate feature: dispersion, persistence against the window, effective breadth, correlation with the live signal's inputs. Never relate the feature to forward returns. Write the dated audit note under results/research/<slug>/ and return the verdict: USABLE, USABLE AFTER RULINGS (list them), or CANNOT CARRY INFORMATION. proceed=false only for the last.`,
    { label: 'data-analyst', phase: 'Data', agentType: 'data-analyst', schema: GO })
  if (!audit || !audit.proceed) return { stage: 'data', outcome: 'STOPPED AT DATA AUDIT', screen, source, audit }

  phase('Power')
  const power = await agent(`Idea: "${IDEA}". Screen: ${screen.summary}. Data: ${source.summary}. Audit: ${audit.summary}
Act as the statistician station. Design the test (daily target-weight panel on the harness CLAUDE.md names; calendar-time headline; clustering; controls; the D4 specification; the 'meaningful' effect size). Then, with scripts/research/inference.py only, compute P(pass) at the plausible effect for EVERY gate the pre-registration will apply: the deflated Sharpe on both bars at the Declared N the pre-registration will state, which is at least the minimum that python3 -m scripts.research.registry slate <counter> --pending 1 prints (the counter after this trial, and any standing declared slate): the desk's with p_pass_dsr(bound='upper', n_trials=N), and the paper's with p_pass_dsr(bound='gumbel', n_trials=n_effective, sr_var=sr_var_used) taken from python3 -m scripts.research.registry sr0 <counter> --declared-n N (if it refuses, quote the refusal; never build the paper's bar another way), both with the payoff's expected skew and kurtosis. Which bar gates is docs/SYSTEM.md §5's, read at run time; the D4 alpha t >= 3.0, any net-t gate, and any count gate. Report every gate, the binding one, and p_pass_all: the chance of passing ALL gates together, simulated on the design where the gates are correlated. All probabilities are fractions in [0, 1]. Set proceed=false if any of them is below ${MIN_POWER}, and list redesign options, cheapest first. Never assume a sigma: measure it on pre-2023 non-event windows, or cite it.`,
    { label: 'statistician', phase: 'Power', agentType: 'statistician', schema: POWER })
  need(power, 'the statistician (power)')
  const ps = [power.p_pass_binding, power.p_pass_all, ...(power.gates || []).map(g => g.p_pass)]
  if (!power.gates || !power.gates.length || ps.some(p => typeof p !== 'number' || !(p >= 0 && p <= 1))) {
    throw new Error(`the power table is incomplete or out of range: ${JSON.stringify(ps)}`)
  }
  const pMin = Math.min(...ps)
  const under = pMin < MIN_POWER || !power.proceed
  if (under && !OVERRIDE) {
    return { stage: 'power', outcome: 'UNDERPOWERED: no trial spent', min_power: MIN_POWER, p_pass_min: pMin, power, screen, source, audit,
      next: 'Take a redesign option and re-run, or the team lead re-runs with override_power: true.' }
  }
  const loosened = MIN_POWER < DEFAULT_MIN_POWER
  if (under || loosened) log(`POWER GATE OVERRIDDEN by the team lead: min P(pass) ${pMin}, threshold ${MIN_POWER} (default ${DEFAULT_MIN_POWER})`)

  phase('Pre-register')
  const prereg = await agent(`Idea: "${IDEA}". Screen: ${JSON.stringify(screen)}. Data: ${source.summary}. Audit: ${audit.summary}. Design and power: ${JSON.stringify(power)}.${under || loosened ? ` THE POWER GATE WAS OVERRIDDEN by the team lead (min P(pass) ${pMin}, threshold ${MIN_POWER}, default ${DEFAULT_MIN_POWER}): say so at the top.` : ''}
Use /prereg to DRAFT the pre-registration at results/research/PREREG_DRAFT_<slug>.md. Do not commit it and do not touch docs/RESEARCH_STATE.md. Include: hypothesis, mechanism and loser; the component under test and the successor to try if the effect is PRESENT but a gate fails; the exact test; the power table per gate; the 'meaningful' size and the three-outcome reading (PRESENT / ABSENT / INCONCLUSIVE via read_result, with n_trials = the counter's N at the time of the test); the negative control; fit < 2023-01-01 with a 2023-26 holdout row; where the per-period P&L series will be stored; what kills it; the counter it spends. Return the path and a five-line summary.`,
    { label: 'prereg-draft', phase: 'Pre-register' })
  need(prereg, 'the pre-registration drafter')
  return { stage: 'design-complete', prereg, power, screen, source, audit,
    next: 'Approve the draft as CLAUDE.md and SYSTEM.md §5 require, then commit it (/prereg). To spend the trial: re-run with {idea, stage: "test", prereg: "<path>", prereg_sha: "<that commit>", approved: true}.' }
}

if (STAGE !== 'test') throw new Error(`unknown stage "${STAGE}" (design | test)`)
if (!A.prereg || A.approved !== true || !/^[0-9a-f]{7,40}$/.test(A.prereg_sha || '')) {
  throw new Error('stage "test" spends a trial and needs {prereg: "<path>", prereg_sha: "<commit>", approved: true}; approve the draft as CLAUDE.md requires and commit it first')
}
// Every station reads the approved text at the pinned commit, never the working
// file, which a station with Write access could otherwise change after approval.
const PREREG = `the approved pre-registration ${A.prereg} AS COMMITTED at ${A.prereg_sha} (read it with: git show ${A.prereg_sha}:${A.prereg}; never edit that file)`

phase('Test')
const runner = A.ml ? 'ml-engineer' : 'backtest-engineer'
const test = need(await agent(`Read ${PREREG}. Idea: "${IDEA}".
Act as the ${runner} station. Implement exactly what the pre-registration says, once, on the harness CLAUDE.md names at run time, in a new script under scripts/research/<slug>/, with output under results/research/<slug>/ (never data/). Stop and report any ambiguity instead of resolving it. Store the per-period P&L series (gross and on the cost grid), and every configuration's if several ran, with scripts/research/registry.py record(...) under the pre-registration's counter and trial id: judged=True on the configuration the pre-registration selects (its gross series), even when it is the only one, and judged=False on every other. Without that flag the paper's deflated-Sharpe bar is refused for the whole counter, and the flag can never be added after recording. Commit your script first: record refuses a dirty tree. Return: the headline table (GROSS first, net 5/15/30bp beside it labelled, sign flip y/n, eras, fit and holdout rows, the control's row, turnover, panel last date), the P&L series path and the reproducer command.`,
  { label: runner, phase: 'Test', agentType: runner }), runner)

phase('Attack')
const ctx = `Idea: "${IDEA}". Read ${PREREG}. Result: ${test}`
const [beta, review, stats, book, trade] = await parallel([
  () => agent(`${ctx}\nAssume the effect is false and find the boring explanation: an artifact, a control that scores as well, factor beta, a bug. Keep "explanation found" apart from "too weak to tell". Attack the effect and the expression separately.`,
    { label: 'beta-detector', phase: 'Attack', agentType: 'beta-detector', schema: READ }),
  () => agent(`${ctx}\nReview the code and numbers: lookahead, leakage, alignment, silent fallbacks, units, turnover mismatch, private copies of statistics, and every deviation from the pre-registration.`,
    { label: 'quant-reviewer', phase: 'Attack', agentType: 'quant-reviewer', schema: READ }),
  () => agent(`${ctx}\nIndependently re-derive the inference from the stored P&L series with scripts/research/inference.py: read_result against the pre-registered 'meaningful' size with n_trials = the counter's N, both deflated-Sharpe bars at the pre-registration's Declared N from python3 -m scripts.research.registry bars <counter> <trial> <variant> --declared-n N if the series is already in the registry, else the desk's from inference.desk_dsr at N and the paper's marked PENDING until the series is recorded (never build the paper's bar from bar_inputs; which bar gates is docs/SYSTEM.md §5's, read at run time), clustering or HAC as the design requires, and PBO if several configurations ran. Do not reuse the runner's statistics.`,
    { label: 'statistician', phase: 'Attack', agentType: 'statistician', schema: READ }),
  () => agent(`${ctx}\nFrom the stored series and the book's own fit-period P&L: the sleeve's correlation with the book (with a range), marginal_gain and combined_sharpe from scripts/research/inference.py, the combined net at 5/15/30bp, and the leverage implied. Say whether the standalone admission rule and the marginal reading disagree, and which route, if any, admits it under docs/SYSTEM.md §5 (2026-10-27: marginal admission is paper only).`,
    { label: 'portfolio-manager', phase: 'Attack', agentType: 'portfolio-manager', schema: READ }),
  () => agent(`${ctx}\nCan this be traded as specified at Alpaca today (shortability, whole shares, wash-trade netting with the CEF book, venue cutoffs), and what would the real-money cost gate need? If the expression is blocked, name the cheapest expression that is not.`,
    { label: 'quant-trader', phase: 'Attack', agentType: 'quant-trader', schema: READ }),
])
;[['beta-detector', beta], ['quant-reviewer', review], ['statistician', stats],
  ['portfolio-manager', book], ['quant-trader', trade]].forEach(([who, r]) => need(r, who))

phase('Verdict')
const verdict = await agent(`Write the verdict for the team lead on idea "${IDEA}".
Inputs: ${PREREG}; test: ${test}; beta-detector: ${JSON.stringify(beta)}; quant-reviewer: ${JSON.stringify(review)}; statistician: ${JSON.stringify(stats)}; portfolio-manager: ${JSON.stringify(book)}; quant-trader: ${JSON.stringify(trade)}.
The verdict states both: (1) the EVIDENCE outcome, PRESENT / ABSENT / INCONCLUSIVE, from the statistician's read_result; and (2) the D-code from the canonical legend in docs/RESEARCH_STATE.md for the gate that fired, if one did. If quant-reviewer found a correctness defect, the verdict is "not established" until it is fixed. If the effect is PRESENT (at the multiplicity-adjusted level read_result applies) and a gate failed, write the successor entry: the cheapest other expression of the same effect. Give the standalone and marginal readings side by side. Write results/research/<slug>/VERDICT.md, labelling every figure [V]/[S]/[U], and return its text. Do not edit docs/RESEARCH_STATE.md: list the exact ledger edit (counter, verdict row with its evidence outcome, successor row) for approval as CLAUDE.md requires. Report both deflated-Sharpe bars at the Declared N as the statistician station gave them (the registry's bars output, or the paper's marked PENDING until the series is recorded), and say which one gates under docs/SYSTEM.md §5, read at run time.`,
  { label: 'verdict', phase: 'Verdict' })
need(verdict, 'the verdict writer')
return { stage: 'test-complete', prereg_sha: A.prereg_sha, test, beta, review, stats, book, trade, verdict }
