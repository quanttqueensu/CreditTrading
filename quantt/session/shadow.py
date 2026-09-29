"""The shadow benchmark: the book the runner INTENDED, as if every order filled at
the official closing-auction print. MODELLED -- never broker evidence.

WHY IT EXISTS
-------------
Alpaca paper does not run a closing auction. Staff, 2026-06-24: paper treats a
`cls` order "simply like market orders placed at the close", with random partial
fills, and "they may expire before filling completely" [V: forum thread
"Paper MOC orders partially fill remainder expires", fetched 2026-09-29].
Measured on our first armed session, 2026-09-29: 13 `cls` orders accepted, PHK
filled 4,019/4,019 and PFN 1,529/2,227 at 15:59:55-58 ET, the other eleven
expired 16:00:10-16:02:33 ET with nothing filled -- although every NYSE closing
auction that day printed more shares than we asked for (e.g. PDI 12,327 vs 345).
So the paper account's P&L measures Alpaca's simulator as much as the strategy.

The team lead's decision (2026-09-29): keep `cls` (CLAUDE.md rule 3), and carry
a labelled shadow score beside the real one for a week of comparison before the
order type is revisited. This module is that score. It never enters
`scores.csv`, never changes a verify verdict, and every row says MODELLED
(CLAUDE.md: "Modelled sessions are not evidence").

THE RULE
--------
For session date D (a trading day) and its previous trading day P:

    book_in   = the shadow book after the last scored session (shadow_book.json);
                on the first run, the targets of P's plan if it made a decision,
                else empty.
    pnl_D     = sum_s  book_in[s] * (A_D[s] - A_P[s])      A = official close (M, primary)
    book_out  = D's plan targets if D's plan made a decision that only DRY_RUN or
                arming could have stopped; otherwise book_in, carried.

Every intended trade on D fills at A_D by construction, so it adds nothing to
pnl_D; it starts earning on D+1. That is exactly the paper convention the real
book is scored on (fill on D's close, earn from D+1), without the simulator.

A name in book_in with no print on D or P makes pnl_D UNMEASURED, naming it:
a sum with a missing term is not the sum, and no bar close stands in (see
score.py "A MISSING PRINT IS A GAP"). The book still advances: the intended
book is known whether or not a print is.

CAVEAT, STATED: D's targets are anchored on the REAL account's holdings (the
band is measured from what the account actually holds), so this is "the runner's
intended book on each day", not an independent simulation of the strategy from
day one. On days when paper fills everything, the two books coincide.

One run per D: rerunning for a D already scored refuses rather than advancing
the book twice.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

LABEL = "MODELLED: intended book at official closing prints; not broker evidence"
COLUMNS = ("date", "prev", "shadow_pnl_usd", "unmeasured", "book_in_json",
           "book_out_json", "book_out_source", "gross_in_usd", "label", "written_at_utc")
# A decision that only these gates stopped was a real intention to trade.
INTENT_GATES = {"dry_run", "arming"}


class ShadowError(RuntimeError):
    """A fact the shadow score needs is missing or contradictory. Names it."""


def _plan(state_dir: Path, day: dt.date) -> dict | None:
    """plan.json, with a late-market SEND refusal folded in (send.json): a plan
    the send refused on anything but dry-run/arming was not an intention to
    trade that day, exactly as a decide-time refusal is not (review 2026-09-29)."""
    d = state_dir / day.isoformat()
    p = d / "plan.json"
    if not p.exists():
        return None
    plan = json.loads(p.read_text())
    s = d / "send.json"
    if plan.get("execution") == "late_market" and s.exists():
        plan = dict(plan, refusals=list(plan.get("refusals") or [])
                    + list(json.loads(s.read_text()).get("refusals") or []))
    return plan


def intended_book(plan: dict | None) -> dict | None:
    """{symbol: signed shares} the plan intended after its orders, or None if the
    plan made no decision or was refused by anything but DRY_RUN/arming."""
    if not plan or not plan.get("targets"):
        return None
    if {r.get("gate") for r in plan.get("refusals") or []} - INTENT_GATES:
        return None
    out = {}
    for sym, t in plan["targets"].items():
        q = t.get("target")
        if not isinstance(q, int):
            raise ShadowError(f"plan {plan.get('session_date')}: target for {sym} is {q!r}, "
                              f"not an integer share count")
        if q:
            out[sym] = q
    return out


def score_day(prices_d: dict, prices_p: dict, book_in: dict) -> tuple[float | None, list]:
    """(pnl, unmeasured). pnl is None when any held name lacks a print."""
    missing = sorted(s for s in book_in if s not in prices_d or s not in prices_p)
    if missing:
        return None, [f"{s}: no official close on "
                      + " and ".join(w for w, px in (("D", prices_d), ("P", prices_p))
                                     if s not in px) for s in missing]
    return sum(q * (prices_d[s] - prices_p[s]) for s, q in book_in.items()), []


def run_day(client, state_dir: Path, day: dt.date, *, fetch, prev: dt.date,
            now_utc: dt.datetime) -> dict:
    """Score D, append one row to <state>/shadow.csv, advance shadow_book.json.

    `fetch(symbols, date) -> (prices, gaps)` supplies official closes (verify's
    fetch_prints in production). Returns the row written.
    """
    book_path = state_dir / "shadow_book.json"
    if book_path.exists():
        st = json.loads(book_path.read_text())
        last = dt.date.fromisoformat(st["after_session"])
        if last >= day:
            raise ShadowError(f"shadow already scored {last} (>= {day}); not advancing twice")
        book_in = {k: int(v) for k, v in st["book"].items()}
    else:
        book_in = intended_book(_plan(state_dir, prev)) or {}

    unmeasured, pnl = [], 0.0
    prices_d = prices_p = {}
    if book_in:
        syms = sorted(book_in)
        prices_d, gaps_d = fetch(syms, day)
        prices_p, gaps_p = fetch(syms, prev)
        pnl, unmeasured = score_day(prices_d, prices_p, book_in)
        unmeasured += [f"{s} ({day}): {g}" for s, g in sorted(gaps_d.items())]
        unmeasured += [f"{s} ({prev}): {g}" for s, g in sorted(gaps_p.items())]

    plan_d = _plan(state_dir, day)
    out = intended_book(plan_d)
    source = f"plan {day}" if out is not None else "carried (no decision to trade on D)"
    book_out = book_in if out is None else out
    gross_in = (sum(abs(q) * prices_p[s] for s, q in book_in.items())
                if book_in and all(s in prices_p for s in book_in) else None)

    row = {"date": day.isoformat(), "prev": prev.isoformat(),
           "shadow_pnl_usd": "UNMEASURED" if pnl is None else f"{pnl:.2f}",
           "unmeasured": " | ".join(unmeasured),
           "book_in_json": json.dumps(book_in, sort_keys=True, separators=(",", ":")),
           "book_out_json": json.dumps(book_out, sort_keys=True, separators=(",", ":")),
           "book_out_source": source,
           "gross_in_usd": "" if gross_in is None else f"{gross_in:.2f}",
           "label": LABEL, "written_at_utc": now_utc.isoformat()}
    _append(state_dir / "shadow.csv", row)
    tmp = book_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"after_session": day.isoformat(), "book": book_out,
                               "source": source, "label": LABEL}, indent=2, sort_keys=True))
    tmp.replace(book_path)
    return row


def _append(path: Path, row: dict) -> None:
    new = not path.exists() or path.stat().st_size == 0
    if not new:
        with path.open(newline="") as fh:
            header = next(csv.reader(fh), None)
        if tuple(header or ()) != COLUMNS:
            raise ShadowError(f"{path} header {header} is not {list(COLUMNS)}")
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)


def record_error(state_dir: Path, day: dt.date, prev: dt.date | None, err: str,
                 now_utc: dt.datetime) -> None:
    """A shadow run that could not score D still leaves a row saying why."""
    _append(state_dir / "shadow.csv", {
        "date": day.isoformat(), "prev": prev.isoformat() if prev else "",
        "shadow_pnl_usd": "UNMEASURED", "unmeasured": f"shadow error: {err}",
        "book_in_json": "", "book_out_json": "", "book_out_source": "not advanced",
        "gross_in_usd": "", "label": LABEL, "written_at_utc": now_utc.isoformat()})
