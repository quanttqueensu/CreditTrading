export const meta = {
  name: 'research-loop',
  description: 'The daily autonomous research cycle: ops gate, pick one idea, design, self-approve as CLAUDE.md allows, test, record, admit to the paper lab',
  whenToUse: 'Once per trading day after the close, from the scheduled loop session (team lead, 2026-10-27: laptop, one idea per day). args = {date: "YYYY-MM-DD"}, which is required because a script cannot read the clock. Never sends an order: the lab account trades only through its quantt runner.',
  phases: [
    { title: 'Gate', detail: 'orient: operations outrank research; is self-approval recorded; does a lab book exist' },
    { title: 'Pick', detail: 'one idea: the in-progress one, else the SYSTEM.md §5 queue, else a new one past the graveyard' },
    { title: 'Design', detail: 'research-idea, design stage (spends nothing)' },
    { title: 'Approve', detail: 'self-approval, only if CLAUDE.md records it; commit the prereg and the counter' },
    { title: 'Test', detail: 'research-idea, test stage (spends the trial)' },
    { title: 'Record', detail: 'ledger edit, trial series in the registry, loop state' },
    { title: 'Admit', detail: 'the paper-lab admission decision; refuses while no lab book exists' },
    { title: 'Report', detail: 'results/research/loop/<date>.md, committed on the loop branch' },
  ],
}

// WHY THIS SHAPE (2026-10-27, the team lead's rulings in docs/SYSTEM.md §5):
// agents research, deploy and trade on the PAPER book; a new agent-lab account;
// trials self-approved with no cap; the laptop, one idea per day.
//
// What the loop must never do, and how the script makes it impossible:
// - SEND AN ORDER. No stage transmits. A sleeve admitted to the lab is traded by
//   the quantt runner for the lab book on its own schedule (CLAUDE.md hard rule 1,
//   recorded exception), which applies hard rules 2-5. Until that book exists,
//   Admit records "admitted, waiting for the lab book" and stops.
// - SELF-APPROVE BEFORE THE RULING IS RECORDED. The Gate reads CLAUDE.md in the
//   loop's own checkout at run time. If the self-approval sentence is not there
//   (because research-infra is not merged yet), the cycle stops after Design and
//   reports a draft waiting for the team lead. A ruling is never acted on from
//   memory (H14).
// - SPEND A TRIAL WITHOUT COUNTING IT. Approve commits the prereg and the counter
//   increment together. Record stores the series through scripts/research/registry.py.
//   Uncapped self-approval is safe only because every trial raises the bar for the next.
// - READ A MISSING RESULT AS A CLEAN ONE. Any station that returns nothing stops
//   the cycle (research-idea's rule, applied here too), and so does a Record that
//   reports ok=false.
// - TAKE AN APPROVER'S WORD FOR THE COUNT. An independent Verify station confirms
//   from git that the commit adding the pre-registration also moved the counter.
//   That applies to a resumed test too, which used to skip approval and the
//   recorded-ruling check entirely (quant-reviewer, 2026-10-28).
// - ASSEMBLE THE BAR ITSELF. The team lead ruled on 2026-10-28 (docs/SYSTEM.md §5)
//   that the paper's bar uses the DECLARED slate size and floors V[SR] at 1/T.
//   Built from bar_inputs' raw N and V, EVENTS' hurdle was 0.06 against 0.36.
//   The pre-registration declares N; the Verify station reads it back from git;
//   Record runs `registry bars` at that N; Admit reads the DSR from that output.
//
// The cycle is ONE idea. Data length, not agent speed, limits how many trials are
// worth spending (minimum backtest length, Bailey et al. 2014; 2-1 verified).

const A = args || {}
if (!/^\d{4}-\d{2}-\d{2}$/.test(A.date || '')) throw new Error('research-loop needs args = {date: "YYYY-MM-DD"}')
const D = A.date
const STATE = 'results/research/loop/STATE.md'
const need = (x, what) => { if (x === null || x === undefined) throw new Error(`${what} returned nothing; the cycle stops rather than read a missing result as a clean one`); return x }

const GATE = { type: 'object', properties: {
  research_ok: { type: 'boolean' }, why: { type: 'string' },
  self_approval_recorded: { type: 'boolean' }, lab_book_exists: { type: 'boolean' },
  checkout_clean: { type: 'boolean' }, series_ok: { type: 'boolean' }, panels_ok: { type: 'boolean' },
  branch: { type: 'string' }, head: { type: 'string' } },
  required: ['research_ok', 'why', 'self_approval_recorded', 'lab_book_exists', 'checkout_clean', 'series_ok', 'panels_ok', 'branch', 'head'] }
const PICK = { type: 'object', properties: {
  kind: { type: 'string', enum: ['new', 'resume_test', 'nothing'] },
  idea: { type: 'string' }, source: { type: 'string' }, why: { type: 'string' },
  prereg: { type: 'string' }, prereg_sha: { type: 'string' }, ml: { type: 'boolean' } },
  required: ['kind', 'idea', 'source', 'why'] }
const APPROVAL = { type: 'object', properties: {
  approved: { type: 'boolean' }, why: { type: 'string' },
  prereg: { type: 'string' }, prereg_sha: { type: 'string' }, counter: { type: 'string' },
  counter_after: { type: 'integer' }, declared_n: { type: 'integer' } },
  required: ['approved', 'why'] }
const COUNTED = { type: 'object', properties: {
  counted: { type: 'boolean' }, why: { type: 'string' }, prereg_commit: { type: 'string' },
  counter: { type: 'string' }, from: { type: 'integer' }, to: { type: 'integer' },
  declared_n: { type: 'integer' }, declared_n_ok: { type: 'boolean' }, slate: { type: 'string' } },
  required: ['counted', 'why'] }
const DONE = { type: 'object', properties: {
  ok: { type: 'boolean' }, summary: { type: 'string' }, commit: { type: 'string' } },
  required: ['ok', 'summary'] }
// Record returns the registry's bars output as an object, so the script can check
// it was run at the declared N before Admit reads a DSR from it (quant-reviewer, 2026-10-28).
const RECORDED = { type: 'object', properties: {
  ok: { type: 'boolean' }, summary: { type: 'string' }, commit: { type: 'string' },
  bars: { type: 'object', properties: {
    counter: { type: 'string' }, trial: { type: 'string' }, variant: { type: 'string' }, judged: { type: 'boolean' },
    desk: { type: 'object', properties: { n_trials: { type: 'integer' }, dsr: { type: 'number' } }, required: ['n_trials', 'dsr'] },
    // Either may be null in the registry's output. No type is declared, so the
    // schema never rejects a null; the script checks both below.
    paper: { description: "the registry's paper object, or null" },
    paper_refused: { description: "the registry's refusal text, or null" },
    paper_refused_code: { description: "the registry's refusal code, or null" } },
    required: ['counter', 'trial', 'variant', 'judged', 'desk'] } },
  required: ['ok', 'summary'] }
const ADMIT = { type: 'object', properties: {
  decision: { type: 'string', enum: ['ADMIT_LAB', 'ADMITTED_WAITING_FOR_LAB_BOOK', 'NOT_ADMITTED', 'NOT_ESTABLISHED'] },
  route: { type: 'string' }, why: { type: 'string' } },
  required: ['decision', 'why'] }

const report = async (outcome, detail) => need(await agent(`Write the loop's report for ${D} at results/research/loop/${D}.md and update ${STATE} (append one history line: date, idea, outcome, commit). Outcome: ${outcome}. Detail: ${JSON.stringify(detail)}.
Plain British English, every figure labelled [V]/[S]/[U] with the script that reproduces it, no figure invented. If the outcome is a stop, the report names what would unblock it and who must act. Commit both files on the current branch with a message that starts "research-loop ${D}:". Do not push. Return the commit hash and a three-line summary.`,
  { label: 'report', phase: 'Report', schema: DONE }), 'the report writer')

phase('Gate')
const gate = need(await agent(`Run the loop's pre-flight for ${D}. Read-only except where stated.
1. Run python3 -m ops.orient. research_ok=false if the book is not trading cleanly: a WARNING that both machines are armed, the last session verdict is not PASS, or orient reports an incident. Operations outrank research (the /next-task skill). Give the reason.
2. self_approval_recorded = whether CLAUDE.md in THIS checkout contains the sentence "The research loop approves its own trials" AND docs/SYSTEM.md §5 has the block "Team lead, 2026-10-27: the autonomous loop and the harness". Check with grep. Do not infer it from memory or from another branch.
3. lab_book_exists = whether the lab can trade: quantt/session/run.py's BOOKS dict has a book that carries lab sleeves (python3 -c "from quantt.session.run import BOOKS; print(sorted(BOOKS))"). Since 2026-10-28 the lab shares the account C4 trades in (docs/SYSTEM.md §5), so that is a lab book netted with C4's targets, or C4's book carrying lab sleeves. A separate book on the same account does not count.
4. checkout_clean = whether git status --porcelain --untracked-files=no is empty. Also report the branch and HEAD.
5. panels_ok = whether orient's PANELS section measures every panel in THIS checkout (none UNMEASURED). Never read another checkout's data/ to make up for it: under launchd that read is refused, and a test on panels the loop cannot see is not reproducible here. Put orient's PANELS last dates in why. Stale is a form of wrong. A fit-period (pre-2023) study can proceed on a stale panel; anything that reads 2023+ must name the panel's last date in its report.
6. series_ok = whether python3 -m scripts.research.registry verify exits 0 in THIS checkout. The trial series are gitignored and live only where they were recorded, so a checkout can hold ledger lines whose files are elsewhere; without them no bar can be computed after the trial is spent. If it fails, put its problems in why.`,
  { label: 'gate', phase: 'Gate', schema: GATE }), 'the gate')
if (!gate.research_ok || !gate.checkout_clean || gate.series_ok !== true || gate.panels_ok !== true) {
  return { date: D, outcome: 'STOPPED AT GATE', gate, report: await report('STOPPED AT GATE', gate) }
}

phase('Pick')
const pick = need(await agent(`Choose ONE research item for ${D}, in this order:
(a) An item in ${STATE}'s "In progress" section whose pre-registration is committed but whose test has not run: kind=resume_test, with its prereg path and prereg_sha.
(b) Else the first item in docs/SYSTEM.md §5's queue (the 2026-10-27 block "The audit's zero-trial re-opens", in its stated order) that ${STATE}'s history has not finished: kind=new. Read the queue from SYSTEM.md; do not copy it from memory.
(c) Else docs/RESEARCH_STATE.md's ACTIVE and WATCH entries, best value per hour first (/next-task).
(d) Else one new idea from the quant-researcher seat's method: name the loser, check /graveyard first, and prefer raising breadth or the transfer coefficient over a new IC source (the harness rule's "What finding alpha means here").
Skip any item whose latest line in ${STATE}'s history is a stop that waits on a team-lead ruling (for example a screen stop "until the team lead rules"), unless docs/SYSTEM.md §5 now records that ruling. Never pick an item another session owns. ${STATE}'s "Owned elsewhere" section lists them; the trial-series backfill belongs to the desk-research-method session. If nothing qualifies, return kind=nothing. Set ml=true only if the item's design is an ML model (scripts/research/ml.py).`,
  { label: 'pick', phase: 'Pick', agentType: 'quant-researcher', schema: PICK }), 'the pick')
if (pick.kind === 'nothing') return { date: D, outcome: 'NOTHING TO DO', gate, pick, report: await report('NOTHING TO DO', pick) }

let prereg = pick.prereg, preregSha = pick.prereg_sha, approverN = null, approverCount = null
if (pick.kind === 'new') {
  phase('Design')
  const design = need(await workflow('research-idea', { idea: pick.idea }), 'research-idea (design)')
  if (design.stage !== 'design-complete') {
    return { date: D, outcome: design.outcome || 'STOPPED IN DESIGN', pick, design, report: await report(design.outcome || 'STOPPED IN DESIGN', { pick, design }) }
  }
  phase('Approve')
  if (!gate.self_approval_recorded) {
    const waiting = { pick, prereg_draft: design.prereg, next: 'Self-approval is not recorded in this checkout\'s CLAUDE.md; the team lead approves this draft, or merges research-infra.' }
    return { date: D, outcome: 'DRAFT AWAITING APPROVAL', report: await report('DRAFT AWAITING APPROVAL', waiting) }
  }
  const appr = need(await agent(`Self-approval of a pre-registration for ${D}, under CLAUDE.md "Count trials" (the loop approves its own trials, team lead 2026-10-27). Draft: ${JSON.stringify(design.prereg)}. Power: ${JSON.stringify(design.power)}.
Approve only if ALL of these hold: the draft is complete against the /prereg template (hypothesis, mechanism and loser, the exact test, the power table, the meaningful size and the three-outcome reading, the negative control, fit before 2023-01-01 with a holdout row, the kill condition, the counter); the power gate passed with no override; and the test uses the harness CLAUDE.md names. Otherwise approved=false, with the reason.
If approved: use /prereg to finalise it at its dated path. The pre-registration must state, on a line of its own, "Declared N: <integer>": the slate size the trial is judged at on both deflated-Sharpe bars (docs/SYSTEM.md §5, 2026-10-28). Before committing, run python3 -m scripts.research.registry slate <counter> --pending 1 --declared-n <N>: approve only if it exits 0. It refuses an N below the counter after this trial or below the counter's standing declared slate, and it refuses any new trial on a counter whose slate is closed, because that needs a new declaration, which is the team lead's ruling. Increment the counter it names in docs/RESEARCH_STATE.md IN THE SAME COMMIT; add the item to ${STATE}'s "In progress" section; commit with a message that starts "research-loop ${D}: prereg"; and return prereg (the path), prereg_sha (that commit), counter, counter_after and declared_n. Do not push.`,
    { label: 'self-approve', phase: 'Approve', agentType: 'statistician', schema: APPROVAL }), 'the self-approval')
  if (!appr.approved) return { date: D, outcome: 'NOT APPROVED', pick, design, appr, report: await report('NOT APPROVED', { pick, appr }) }
  if (!appr.prereg || !appr.prereg_sha || !appr.counter || !Number.isInteger(appr.counter_after) || !Number.isInteger(appr.declared_n)) {
    throw new Error(`self-approval said yes but did not name the prereg, its commit, the counter, its new value and the declared N: ${JSON.stringify(appr)}`)
  }
  prereg = appr.prereg; preregSha = appr.prereg_sha; approverN = appr.declared_n
  approverCount = { counter: appr.counter, to: appr.counter_after }
} else if (!gate.self_approval_recorded) {
  // A resumed test spends a trial too: the same recorded-ruling check applies.
  return { date: D, outcome: 'RESUME AWAITING APPROVAL', pick,
    report: await report('RESUME AWAITING APPROVAL', { pick, next: 'Self-approval is not recorded in this checkout; the team lead approves the in-progress pre-registration.' }) }
}
if (!prereg || !/^[0-9a-f]{7,40}$/.test(preregSha || '')) throw new Error(`no committed pre-registration to test: ${JSON.stringify({ prereg, preregSha })}`)

const counted = need(await agent(`Verify, from git only, that the trial about to be spent is counted. You did not write the pre-registration; do not trust any claim about it.
Pre-registration path: ${prereg}. Pinned commit: ${preregSha}.
1. git show ${preregSha}:${prereg} must succeed.
2. Find the commit that added that file: git log --diff-filter=A --format=%H -- ${prereg}. It must be ${preregSha} or an ancestor of it (git merge-base --is-ancestor).
3. That same commit must change docs/RESEARCH_STATE.md so that the counter the pre-registration names goes up by exactly one in the canonical counter table (git show <commit> -- docs/RESEARCH_STATE.md). Report from and to.
4. HEAD's canonical counter table must still show at least that value.
5. Read the "Declared N:" line of the pre-registration at the pinned commit and return its integer as declared_n. If there is no such line, omit declared_n.
6. If it has one, run python3 -m scripts.research.registry slate <counter> --declared-n <declared_n> (HEAD's counter already includes this trial). declared_n_ok = whether it exits 0; put its JSON output in slate.
counted=true only if 1-4 hold. Change no file.`,
  { label: 'verify-count', phase: 'Approve', agentType: 'quant-reviewer', schema: COUNTED }), 'the count verifier')
if (!counted.counted) {
  return { date: D, outcome: 'TRIAL NOT COUNTED: test refused', pick, counted,
    report: await report('TRIAL NOT COUNTED: test refused', { pick, prereg, preregSha, counted }) }
}
// The declared N decides both bars. It is read from the committed record, never
// taken from the approver alone. It may not be below the counter it was spent on,
// and the approver and the verifier must agree on it.
const declaredN = counted.declared_n
const badN = !Number.isInteger(declaredN) ? 'the pre-registration states no "Declared N:"'
  : !Number.isInteger(counted.to) || declaredN < counted.to ? `declared N ${declaredN} is below the counter's ${counted.to}`
  : counted.declared_n_ok !== true ? `registry slate refused declared N ${declaredN}: ${counted.slate || 'no output'}`
  : approverN !== null && approverN !== declaredN ? `the approver returned ${approverN} but the pre-registration says ${declaredN}`
  : approverCount !== null && (approverCount.counter !== counted.counter || approverCount.to !== counted.to)
    ? `the approver returned ${JSON.stringify(approverCount)} but git shows ${counted.counter} at ${counted.to}`
  : null
if (badN) {
  return { date: D, outcome: 'DECLARED N INVALID: test refused', pick, counted,
    report: await report('DECLARED N INVALID: test refused', { pick, prereg, preregSha, counted, why: badN }) }
}

phase('Test')
const result = need(await workflow('research-idea', { idea: pick.idea, stage: 'test', prereg, prereg_sha: preregSha, approved: true, ml: pick.ml === true }), 'research-idea (test)')

phase('Record')
const rec = need(await agent(`Record the trial for ${D}. Pre-registration: ${prereg} at ${preregSha}. Verdict: ${result.verdict}. Statistician: ${JSON.stringify(result.stats)}. Test: ${result.test}.
1. Make sure every configuration's per-period P&L series is stored with scripts/research/registry.py record(...), under the counter the pre-registration names and its trial id ${counted.counter}-${counted.to}, with judged=True on the configuration the pre-registration selects and on no other (the paper's bar takes one series per trial). Commit the runner's code first: record refuses a dirty tree. If the runner already stored them, check the ledger lines exist, their sha256 match, and the selected one is judged. Then run python3 -m scripts.research.registry bars ${counted.counter} ${counted.counter}-${counted.to} <the selected variant> --declared-n ${declaredN} and return its JSON output, parsed and unchanged, as bars. That is both deflated-Sharpe bars, labelled, the paper's with the 2026-10-28 safeguards. Do not compute a bar any other way. If the command fails, ok=false with its error.
2. Apply the ledger edit the verdict lists to docs/RESEARCH_STATE.md: the verdict row with its evidence outcome beside the D-code, and any successor row. The counter was incremented when the pre-registration was committed: do not increment it again.
3. Move the item from ${STATE}'s "In progress" section to its history.
Commit with a message that starts "research-loop ${D}: verdict". Do not push.`,
  { label: 'record', phase: 'Record', schema: RECORDED }), 'the recorder')
const b = rec.bars
// Every field Admit reads is checked here, after the trial is spent, so a bad
// output becomes RECORD FAILED with a report, never a TypeError with none.
const paperOk = b && b.paper && typeof b.paper.dsr === 'number' && b.paper.declared_n === declaredN && !b.paper_refused
const refusedOk = b && !b.paper && typeof b.paper_refused === 'string' && b.paper_refused.length > 0
  && typeof b.paper_refused_code === 'string' && b.paper_refused_code.length > 0
const badBars = !rec.ok ? null
  : !b ? 'the recorder returned no bars output'
  : b.counter !== counted.counter || b.trial !== `${counted.counter}-${counted.to}` ? `bars ran on ${b.counter}/${b.trial}, not ${counted.counter}-${counted.to}`
  : b.judged !== true ? `bars ran on ${b.variant}, which is not recorded as the judged series`
  : !b.desk || typeof b.desk.dsr !== 'number' || b.desk.n_trials !== declaredN ? `the desk's bar is missing or not at the declared N ${declaredN}: ${JSON.stringify(b.desk)}`
  : !paperOk && !refusedOk ? `the paper's bar is neither a DSR at N ${declaredN} nor a stated refusal: ${JSON.stringify({ paper: b.paper, paper_refused: b.paper_refused })}`
  : null
if (!rec.ok || badBars) {
  return { date: D, outcome: 'RECORD FAILED', pick, prereg, prereg_sha: preregSha, record: rec,
    report: await report('RECORD FAILED', { pick, prereg, preregSha, verdict: result.verdict, record: rec, why: badBars }) }
}

phase('Admit')
const admit = need(await agent(`Decide paper-lab admission for this result (${D}), under docs/SYSTEM.md §5 as written in this checkout. Read it now: the 2026-10-27 blocks on the research method (bar, marginal admission, paper only) and on the autonomous loop (the lab account).
Verdict: ${result.verdict}. Portfolio-manager: ${JSON.stringify(result.book)}. Quant-reviewer: ${JSON.stringify(result.review)}. Quant-trader: ${JSON.stringify(result.trade)}. Registry bars (checked by the script to be this trial at declared N ${declaredN}): ${JSON.stringify(b)}. Recorder: ${rec.summary}.
- NOT_ESTABLISHED if the quant-reviewer found a correctness defect.
- NOT_ADMITTED unless the evidence outcome is PRESENT AND it is admitted EITHER by the standalone deflated Sharpe on the bar SYSTEM.md §5 says gates for this counter today, OR by the marginal-contribution route. For the standalone route, read SYSTEM.md's rows on which bar gates (on 2026-10-28: the paper's bar with safeguards for a counter whose every trial has a stored series, CEF always on the desk's bar, and a counter with one stored trial on the desk's bar until a second is stored). Take the DSR from the registry bars above, never from anywhere else: paper.dsr or desk.dsr, at declared N ${declaredN}. If the paper's bar would gate but paper is null: when paper_refused_code is "one_trial", the desk's bar gates instead, as SYSTEM.md §5 records; for any other code the standalone route is closed, so quote paper_refused. Never otherwise substitute the desk's bar, and never build a bar from bar_inputs' n_effective or sr_var. The marginal-contribution route is paper only: the sleeve adds to the book across rho's range, and the combined net is positive across 5/15/30bp. It must also be tradable as specified per the quant-trader.
- If admitted: ADMIT_LAB if the lab book exists (${gate.lab_book_exists}), else ADMITTED_WAITING_FOR_LAB_BOOK.
Name the route. This step changes no file and sends nothing. Building the lab book's spec and release is the deploy step, and it is not automated yet.`,
  { label: 'portfolio-manager', phase: 'Admit', agentType: 'portfolio-manager', schema: ADMIT }), 'the admission')

const outcome = `TESTED: ${admit.decision}`
return { date: D, outcome, pick, prereg, prereg_sha: preregSha, admit, record: rec,
  report: await report(outcome, { pick, prereg, preregSha, verdict: result.verdict, admit, record: rec.summary, bars: b }) }
