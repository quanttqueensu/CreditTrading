"""Fixed-income research: macro events, credit events and FI instruments (the MACRO lane).

WHY THIS PACKAGE EXISTS
-----------------------
On 2026-10-22 the team lead gave one analyst lane the FICC event-driven signals
(macro and thematic events) meant to be integrated into the strategy, and put all
of it on a new MACRO trial counter: whether a signal is an overlay on the CEF book
or its own sleeve (`docs/SYSTEM.md` §5, "Team lead, 2026-10-22, later: the lanes
revised"; the counter is in `docs/RESEARCH_STATE.md`). On 2026-10-26 the team lead
widened the lane to all of fixed income: macro events, credit events, and the
instruments themselves (rate and credit ETFs, preferreds, baby bonds), each tied to
how it helps the one book, as an overlay or conditioner, a sleeve, or a hedge
(`docs/SYSTEM.md` §5, "Team lead, 2026-10-26"). The team lead's EVENTS rows and the
S3 row on WATCH are not this lane's. Its scripts live here and its notes in
`results/macro/`. Like everything under `scripts/`, nothing here is on the live
path; a signal reaches the book only as a frozen-spec key, through `/spec-change`
and a release.

Before writing anything here, read the KILLED and WATCH tables in
`docs/RESEARCH_STATE.md`: several ideas in this space have already died
(credit-ETF relative value, raw ETF flow, short pressure, credit and rates trend,
and the month-end Treasury extension, which was real but term premium: XASSET-X3,
D4). Whether trial C2 (macro observables per fund group, planned on CEF) moves to
MACRO is the team lead's open question; do not start a test like it before that
ruling.
"""
