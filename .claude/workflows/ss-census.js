export const meta = {
  name: 'ss-census',
  description: 'Event desk: take one or more special-situation ideas from graveyard screen to a measured event card and a zero-trial gate verdict',
  whenToUse: 'Run with args = an idea string, {id, idea}, or an array of them. Spends ZERO trials: it counts events, reads flags and terms, and designs the test; it never computes a return. Survivors go to /prereg (research-idea), which the team lead approves.',
  phases: [
    { title: 'Screen', detail: 'event-scout: graveyard, both catalogues, the expansion note' },
    { title: 'Census', detail: 'filings, data, execution, adversary, domain specialist, in parallel' },
    { title: 'Design', detail: 'event-econometrician: power and the evaluate() mapping' },
    { title: 'Card', detail: 'event-scout: the event card and the gate verdict' },
  ],
}

// WHY THIS SHAPE. The event desk's ideas die in three places, all before a
// return is ever computed: they are already in the graveyard or a catalogue
// (the screen); they have too few independent events, no lawful data, or a
// leg the broker will not lend (the census); or the effect they could
// plausibly have sits below what their event count can detect (the design).
// Each of those is answerable at zero trials, so this workflow stops at the
// gate and never runs a backtest. That stays with research-idea, behind the
// team lead's approval of a pre-registration (CLAUDE.md research rules).
//
// The census seats run in parallel because the card needs all of them at once
// (a real barrier). Several ideas run as a pipeline, so one idea's card does
// not wait for another's census.

const RAW = Array.isArray(args) ? args : [args]
const IDEAS = RAW.filter(Boolean).map((a, i) =>
  typeof a === 'string' ? { id: `idea${i + 1}`, idea: a } : { id: a.id || `idea${i + 1}`, idea: a.idea })
if (!IDEAS.length || IDEAS.some(x => !x.idea)) throw new Error('ss-census needs args = an idea string, {id, idea}, or an array of them')

const ZERO = `ZERO TRIALS: count events, read flags, terms and literature only. Compute NO return, CAR, drift, Sharpe or hit rate of any candidate. No 2023+ market returns (the time holdout is sealed); no return on a data/cef/cef_universe.csv name (the 27-name holdout). Every figure labelled [V]/[S]/[U] and naming the command that produced it. EDGAR only through scripts/data/edgar_client.py with EdgarClient(limiter=RateLimiter(min_interval=${IDEAS.length > 1 ? '1.5' : '0.5'})) while other ideas run, offline cache first; R2 only through src/data/r2.py; Alpaca read-only GETs only; never open config/.env.`

const SCREEN = { type: 'object', properties: {
  proceed: { type: 'boolean' }, existing_id: { type: 'string' }, dead_match: { type: 'string' },
  who_loses: { type: 'string' }, clock: { type: 'string' },
  domain: { type: 'string', enum: ['fund', 'credit', 'deal', 'equity', 'calendar'] }, notes: { type: 'string' } },
  required: ['proceed', 'domain', 'notes'] }
const CARD = { type: 'object', properties: {
  verdict: { type: 'string', enum: ['KILL', 'PASS_GATE', 'NEEDS_RULING', 'NOT_ESTABLISHED'] },
  score_esf: { type: 'string' }, events_per_year: { type: 'string' }, counter: { type: 'string' },
  card_path: { type: 'string' }, summary: { type: 'string' } },
  required: ['verdict', 'summary'] }

const SPECIALIST = { fund: 'equity-research', credit: 'credit-situations-analyst', deal: 'deal-analyst' }

const results = await pipeline(IDEAS,
  (x) => agent(`Idea ${x.id}: "${x.idea}".
Run /graveyard; read docs/RESEARCH_STATE.md, both special-situations catalogues (results/events/SPECIAL_SITUATIONS_CATALOGUE_*_2026-10-15.md), results/events/SS_DESK_EXPANSION_2026-10-19.md and results/cef/EVENT_DRIVEN_POD_2026-10-12.md §4. Is it already dead, or already catalogued (give existing_id)? Name who is forced or slow on the other side, and the event clock with its first point-in-time source. proceed=false if it restates a dead idea with no new mechanism, or duplicates a catalogued id with nothing new. ${ZERO}`,
    { label: `screen:${x.id}`, phase: 'Screen', agentType: 'event-scout', schema: SCREEN }),

  async (screen, x) => {
    if (!screen || !screen.proceed) return { x, screen, stopped: 'screen' }
    const ctx = `Idea ${x.id}: "${x.idea}". Screen: ${JSON.stringify(screen)}. ${ZERO}`
    const seats = [
      () => agent(`${ctx}\nAs the filings seat: which form or item first carries this event, its PIT field (acceptance time; after 16:00 ET means the next session), and the count by year (raw, distinct issuers, distinct months), with the share that maps to a listed security and how it was mapped. Write any script to scripts/events/.`,
        { label: `filings:${x.id}`, phase: 'Census', agentType: 'filings-analyst' }),
      () => agent(`${ctx}\nAs the data seat: the primary and independent secondary source for every series this needs, coverage, whether pre-2023 history exists, the PIT field, the quoted terms for automated research use, and the fetcher to build or reuse.`,
        { label: `data:${x.id}`, phase: 'Census', agentType: 'data-librarian' }),
      () => agent(`${ctx}\nAs the execution seat: can each leg be held at Alpaca (and IBKR for shorts Alpaca will not lend) today: tradable, shortable, easy-to-borrow (true today only), whole shares, an MOC-compatible exit, a shortable ETF hedge, and pre-event ADV against the 5%-of-ADV auction rule (events dated <= 2022 only)?`,
        { label: `execution:${x.id}`, phase: 'Census', agentType: 'execution-trader' }),
      () => agent(`${ctx}\nAssume this idea is a risk premium, a stale-price artifact or a control-group tie. Name the closest graveyard entry, the D4 factors it most likely loads on (and a conditional down-market beta if the payoff could be a short put), the negative control to declare in advance, and the newest out-of-sample evidence in the literature (fetched). Verdict: fragile / plausible / strong.`,
        { label: `adversary:${x.id}`, phase: 'Census', agentType: 'beta-detector' }),
    ]
    if (SPECIALIST[screen.domain]) seats.push(() => agent(`${ctx}\nAs the domain specialist: read the primary documents (terms, prospectus, methodology) that decide this idea, and say what they imply for the mechanism, the clock and the gate.`,
      { label: `specialist:${x.id}`, phase: 'Census', agentType: SPECIALIST[screen.domain] }))
    const census = await parallel(seats)
    return { x, screen, census }
  },

  async (prev) => {
    if (!prev || prev.stopped) return prev
    const design = await agent(`Idea ${prev.x.id}: "${prev.x.idea}". Screen: ${JSON.stringify(prev.screen)}. Census: ${JSON.stringify(prev.census)}.
Design the test without running it: the daily target-weight panel for evaluate() in scripts/cef/band_frontier.py under shift(2), windows derived from the mechanism, the hedge and its pre-event beta window, the declared controls, the D4 specification, and a power table (MDE ~ 2.8 sigma / sqrt(N_independent), sigma from a measured or cited source). If the plausible effect is below the MDE at the census count, say KILL ON POWER. ${ZERO}`,
      { label: `design:${prev.x.id}`, phase: 'Design', agentType: 'event-econometrician' })
    return { ...prev, design }
  },

  async (prev) => {
    if (!prev) return null
    if (prev.stopped) return { id: prev.x.id, verdict: 'KILL', summary: `stopped at screen: ${prev.screen ? prev.screen.notes : 'no screen result'}` }
    const card = await agent(`Write the event card for idea ${prev.x.id}: "${prev.x.idea}" to results/events/cards/${prev.x.id}.md, in the event-scout card format (mechanism and loser; why it persists; why the live book is blind; clock and PIT source; expression and hedge; count; capacity; borrow; graveyard neighbour; D4 prior and negative control; counter; the zero-trial gate with its kill number and its status; E·S·F score; what is not established). Inputs: screen ${JSON.stringify(prev.screen)}; census ${JSON.stringify(prev.census)}; design ${JSON.stringify(prev.design)}.
Verdict: KILL if any census seat or the power table closed it; NEEDS_RULING if it needs a counter or access ruling from the team lead; PASS_GATE only if every zero-trial gate passed on measured numbers; NOT_ESTABLISHED if a seat could not measure what the gate needs. Do not commit, do not touch docs/RESEARCH_STATE.md. ${ZERO}`,
      { label: `card:${prev.x.id}`, phase: 'Card', agentType: 'event-scout', schema: CARD })
    return { id: prev.x.id, ...(card || { verdict: 'NOT_ESTABLISHED', summary: 'card agent returned nothing' }) }
  },
)

const done = results.filter(Boolean)
log(`${done.length}/${IDEAS.length} ideas carded: ` + done.map(r => `${r.id}=${r.verdict}`).join(', '))
return done
