export const meta = {
  name: 'release-check',
  description: 'Production: go/no-go on the current commit for a prod release tag (tests, doc audit, orient, independent review of the diff since the last release)',
  whenToUse: 'Before tagging a release for the prod clone. Read-only: it never tags, installs, arms or sends anything; the team lead approves the tag.',
  phases: [
    { title: 'Checks', detail: 'pytest, doc_audit, orient, runner preview' },
    { title: 'Review', detail: 'quant-reviewer + execution-trader on the diff' },
    { title: 'Decision', detail: 'go / no-go with reasons' },
  ],
}

// WHY. Prod is this repository at a tag and nothing else (docs/ROADMAP.md
// phase 6). A tag is the only thing that reaches the order path, so the tag is
// where the checks sit. A green suite says little about the code that places
// orders (CLAUDE.md), so the diff that touches the order path is reviewed by two
// seats that did not write it.

phase('Checks')
const checks = await agent(`In the repo, run and report the real output of each (do not quote a test count from memory):
1. git status --short; git describe --tags --abbrev=0 --match 'release-*' (the last release tag, or none); git log --oneline <that tag>..HEAD
2. python3 -m pytest -q  (tail of output)
3. python3 -m ops.doc_audit --check
4. python3 -m ops.orient
5. With DRY_RUN=1 and the team lead's QUANTT_STATE_DIR pointed at a scratch directory (never the prod state dir) and QUANTT_ENV_FILE=config/.env: python3 -m quantt.session run --book cef --preview --skip-refresh  — this is read-only (it prints the order list; it cannot transmit under DRY_RUN=1). If it errors, report the error verbatim.
Never print a credential. Return a pass/fail line for each.`,
  { label: 'checks', phase: 'Checks' })

phase('Review')
const scope = `Review the diff between the last release-* tag (or, if none, the first commit of branch alpaca-runner's merge base with main) and HEAD, focusing on quantt/, src/deploy/, ops/specs/, ops/books/. Report only real defects with a concrete failure scenario.`
const [qr, ex] = await parallel([
  () => agent(`${scope} Lens: lookahead, alignment, silent fallbacks, unit/sign errors, idempotency, credential leakage.`,
    { label: 'quant-reviewer', phase: 'Review', agentType: 'quant-reviewer' }),
  () => agent(`${scope} Lens: order-path correctness — cls cutoff, Alpaca rules (wash trade, flips, shortability, client_order_id), gates, ambiguous submits, retries.`,
    { label: 'execution-trader', phase: 'Review', agentType: 'execution-trader' }),
])

phase('Decision')
return await agent(`Give the team lead a GO or NO-GO for tagging HEAD as the next release-YYYYMMDD-N, with one line per reason. NO-GO if any check failed or any reviewer finding is a real defect on the order path. Checks: ${checks}. quant-reviewer: ${qr}. execution-trader: ${ex}. Finish with the exact commands the team lead would approve (git tag, git push origin <tag>, python3 -m quantt.deploy.install_prod --tag <tag> ...) but do NOT run them.`,
  { label: 'decision', phase: 'Decision' })
