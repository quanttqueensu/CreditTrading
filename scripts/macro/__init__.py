"""FICC event-driven research: macro and thematic event signals (the MACRO lane).

WHY THIS PACKAGE EXISTS
-----------------------
On 2026-10-22 the team lead gave one analyst lane the FICC event-driven signals
(macro and thematic events) meant to be integrated into the strategy, and put all
of it on a new MACRO trial counter: whether a signal is an overlay on the CEF book
or its own sleeve (`docs/SYSTEM.md` §5, "Team lead, 2026-10-22, later: the lanes
revised"; the counter is in `docs/RESEARCH_STATE.md`). Its scripts live here and
its notes in `results/macro/`. Like everything under `scripts/`, nothing here is on
the live path; a signal reaches the book only as a frozen-spec key, through
`/spec-change` and a release.

Before writing anything here, read the KILLED and WATCH tables in
`docs/RESEARCH_STATE.md`: several flow and calendar ideas in this space have
already died (raw ETF flow, short pressure, the month-end Treasury extension),
and the forced IG-to-HY index deletion is on WATCH.
"""
