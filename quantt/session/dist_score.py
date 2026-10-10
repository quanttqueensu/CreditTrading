"""The third score: auction-marked P&L plus the distributions a real account would book.

WHY IT EXISTS
-------------
Alpaca paper credits no dividends [V: docs.alpaca.markets/us/docs/paper-trading,
fetched 2026-09-28]. On a CEF's ex-date its price drops by about the distribution.
So a paper LONG loses that drop with nothing credited back, and a paper SHORT
gains it without paying the distribution a real short owes its lender. Measured
2026-10-08 (`scripts/xasset/book_profile.py`): the book has recently been net
short distribution yield, a distribution leg of about −0.6 to −0.9%/yr. The two
existing scores (`score.py`) therefore flatter the book against a real account.
The team lead ruled on 2026-10-09 (`docs/SYSTEM.md` §5) to carry a third line
beside them. This module is that line.

THE RULE
--------
For session D, with `held` = the signed shares held at the START of D (verify's
`held_into_close`, q0: what was held into D from the previous close):

    distribution_pnl_D = sum_s held[s] * cash_per_share[s, ex_date == D]
    auction_pnl_with_distributions_D = auction_pnl_D + distribution_pnl_D

The holder at the previous close is the one entitled on the ex-date: a long is
credited, a short is charged. Shares bought or sold on D trade ex, so D's fills
earn nothing here. `auction_pnl_D` already carries the ex-date price drop, so the
sum is what a real account filled in the auction would have earned, gross of
borrow and fees.

WHERE THE AMOUNTS COME FROM, AND WHEN ONE IS UNMEASURED
-------------------------------------------------------
Primary: Alpaca's corporate-actions data (`AlpacaClient.distributions`). It is the
broker's own data, and it lists DECLARED distributions weeks ahead (measured
2026-10-09: ex-dates to 2026-12-11 already listed). So D's ex-dates are known
before the 17:30 verify. Alpaca warns its corporate actions "may not be available
immediately after they are announced" [V], so absence there is not proof.

Second source: the repo's yfinance panel, `data/cef/cef_distributions.parquet`
(`scripts/fetch_cef_distributions.py`). It serves amounts rounded to 3 decimals,
where Alpaca has 4. Measured 2026-10-09 on the 13 names, June to August 2026: 28
of 40 events common to both sources differed, every one by ≤ 0.0005 (e.g. MHD
0.0595 vs 0.060), and no event differed by more. So:

  both list D, |diff| ≤ ROUNDING_TOL per event  -> Alpaca's (more precise) amount
  both list D, |diff| > ROUNDING_TOL            -> UNMEASURED, naming both values
  only Alpaca lists D                           -> Alpaca's amount (the panel
                                                   lists an ex-date only after it
                                                   passes, and may lag)
  only the panel lists D                        -> UNMEASURED, naming it: Alpaca's
                                                   silence is not a zero
  neither lists D                               -> 0.0, recorded as "none listed
                                                   by Alpaca or the panel"

The two sources are never averaged, and every name's row says which rule applied.
A name that is UNMEASURED makes the day's distribution P&L UNMEASURED: a sum with
a missing term is not the sum (the same rule as `score.py`).

IT NEVER CHANGES THE VERDICT
----------------------------
Like the shadow score (`shadow.py`), this runs after verify writes its verdict.
It writes only `<state>/distribution_scores.csv`. A failure here becomes an
UNMEASURED row naming it, not a FAIL of the session. `scores.csv`'s columns are
untouched: adding one there would make verify refuse its own existing file.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
from pathlib import Path

LABEL = ("distribution-adjusted: auction-marked P&L plus distributions on shares held "
         "at the start of the ex-date (credited long, charged short); gross of borrow "
         "and fees; Alpaca paper credits none")
COLUMNS = ("date", "auction_pnl_usd", "distribution_pnl_usd",
           "auction_pnl_with_distributions_usd", "unmeasured", "per_symbol_json",
           "source", "label", "written_at_utc")
UNMEASURED = "UNMEASURED"

# yfinance serves 3 decimals, Alpaca 4: the largest rounding gap is 0.0005 per
# event (measured 2026-10-09, module docstring). Anything wider is a real conflict.
ROUNDING_TOL = 0.0005

# The query window around D. Alpaca's start/end filter is not documented as
# ex-date (results are "sorted by their process_date", which for a dividend is near
# the payable date, weeks after the ex-date), so the window is wide and the
# ex-date is filtered here.
QUERY_BACK_DAYS = 45
QUERY_FWD_DAYS = 120

DEFAULT_PANEL = Path(__file__).resolve().parents[2] / "data" / "cef" / "cef_distributions.parquet"


class DistError(RuntimeError):
    """A fact the distribution score needs is missing or contradictory. Names it."""


def score(held: dict, per_share: dict, gaps: dict) -> tuple[float | None, list, list]:
    """(distribution_pnl, rows, unmeasured). Pure.

    held       {symbol: signed whole shares at the start of D}, non-zero ints.
    per_share  {symbol: cash per share with ex-date D}; 0.0 means "none on D".
    gaps       {symbol: reason the amount is unknown}.
    Every held symbol must be in exactly one of `per_share` and `gaps`: a symbol
    in neither was never resolved, which is a caller bug and raises.
    """
    rows, unmeasured, total = [], [], 0.0
    for sym in sorted(held):
        q = held[sym]
        if type(q) is not int or q == 0:
            raise DistError(f"held[{sym}] = {q!r} must be a non-zero int (whole shares)")
        if (sym in per_share) == (sym in gaps):
            raise DistError(f"{sym}: must be in exactly one of per_share and gaps "
                            f"({'both' if sym in per_share else 'neither'})")
        if sym in gaps:
            reason = gaps[sym]
            if not isinstance(reason, str) or not reason.strip():
                raise DistError(f"{sym}: gap has no reason")
            unmeasured.append(f"{sym}: {reason}")
            rows.append({"symbol": sym, "held_qty": q, "per_share": None, "dist_pnl": None})
            continue
        a = per_share[sym]
        if isinstance(a, bool) or not isinstance(a, (int, float)) or not math.isfinite(a) or a < 0:
            raise DistError(f"{sym}: per-share amount {a!r} must be a finite number >= 0")
        pnl = q * float(a)
        total += pnl
        rows.append({"symbol": sym, "held_qty": q, "per_share": float(a), "dist_pnl": pnl})
    return (None if unmeasured else total), rows, unmeasured


def resolve(symbols, day: dt.date, alpaca_events: list, panel) -> tuple[dict, dict, dict]:
    """(per_share, gaps, notes) for `symbols` on ex-date `day`, by the module's rules.

    alpaca_events  `AlpacaClient.distributions` output (any window containing D).
    panel          a DataFrame with ticker / ex_date / amount (the yfinance panel),
                   or None when no panel is available (then only-Alpaca and neither
                   still resolve; the note says the second source was absent).
    """
    alp: dict[str, list] = {}
    for e in alpaca_events:
        if e["ex_date"] == day:
            alp.setdefault(e["symbol"], []).append(float(e["amount"]))
    pan: dict[str, list] = {}
    if panel is not None:
        for sym, ex, amt in zip(panel["ticker"], panel["ex_date"], panel["amount"]):
            if hasattr(ex, "date"):
                ex = ex.date()
            if ex == day and float(amt) > 0:
                pan.setdefault(sym, []).append(float(amt))
    second = "the yfinance panel" if panel is not None else "no second source (panel absent)"

    per_share, gaps, notes = {}, {}, {}
    for sym in sorted(set(symbols)):
        a, p = alp.get(sym), pan.get(sym)
        if a and p:
            sa, sp = sum(a), sum(p)
            tol = ROUNDING_TOL * max(len(a), len(p))
            if abs(sa - sp) <= tol + 1e-12:
                per_share[sym] = sa
                notes[sym] = (f"Alpaca {sa:g} (panel {sp:g}, within rounding {tol:g}); "
                              f"Alpaca used")
            else:
                gaps[sym] = (f"sources disagree on ex {day}: Alpaca {sa:g}, yfinance panel "
                             f"{sp:g}; not averaged")
        elif a:
            per_share[sym] = sum(a)
            notes[sym] = f"Alpaca {sum(a):g}; {second} does not list ex {day}"
        elif p:
            gaps[sym] = (f"the yfinance panel lists ex {day} at {sum(p):g} but Alpaca lists "
                         f"none; Alpaca's silence is not a zero")
        else:
            per_share[sym] = 0.0
            notes[sym] = f"none listed for ex {day} by Alpaca or {second}"
    return per_share, gaps, notes


def _fmt(x) -> str:
    return UNMEASURED if x is None else f"{x:.2f}"


def _already_scored(path: Path, day: dt.date) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open(newline="") as fh:
        return any(r.get("date") == day.isoformat() for r in csv.DictReader(fh))


def _append(path: Path, row: dict) -> None:
    new = not path.exists() or path.stat().st_size == 0
    if not new:
        with path.open(newline="") as fh:
            header = next(csv.reader(fh), None)
        if tuple(header or ()) != COLUMNS:
            raise DistError(f"{path} header {header} is not {list(COLUMNS)}")
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)


def _load_panel(panel_path: Path):
    if not panel_path.exists():
        return None
    import pandas as pd
    df = pd.read_parquet(panel_path, columns=["ticker", "ex_date", "amount"])
    return df


def run_day(client, state_dir: Path, day: dt.date, *, held: dict, auction_pnl: float | None,
            now_utc: dt.datetime, panel_path: Path = DEFAULT_PANEL) -> dict | None:
    """Score D's distribution line and append one row to <state>/distribution_scores.csv.

    Returns the row written, or None if D already has a row: verify can be re-run
    for a day, and a second row for the same D would be read as two days.
    """
    path = state_dir / "distribution_scores.csv"
    if _already_scored(path, day):
        return None
    held = {s: q for s, q in held.items()}
    if held:
        events = client.distributions(sorted(held), day - dt.timedelta(days=QUERY_BACK_DAYS),
                                      day + dt.timedelta(days=QUERY_FWD_DAYS))
        panel = _load_panel(panel_path)
        per_share, gaps, notes = resolve(held, day, events, panel)
        pnl, rows, unmeasured = score(held, per_share, gaps)
        for r in rows:
            r["source"] = notes.get(r["symbol"], gaps.get(r["symbol"], ""))
        source = (f"Alpaca corporate actions (read {now_utc.isoformat()}), cross-checked "
                  f"against {'the yfinance panel ' + str(panel_path.name) if panel is not None else 'no panel'}")
    else:
        pnl, rows, unmeasured = 0.0, [], []
        source = "no positions held into D: nothing is entitled"
    combined = None if (pnl is None or auction_pnl is None) else auction_pnl + pnl
    row = {"date": day.isoformat(), "auction_pnl_usd": _fmt(auction_pnl),
           "distribution_pnl_usd": _fmt(pnl),
           "auction_pnl_with_distributions_usd": _fmt(combined),
           "unmeasured": " | ".join(unmeasured),
           "per_symbol_json": json.dumps(rows, sort_keys=True, separators=(",", ":")),
           "source": source, "label": LABEL, "written_at_utc": now_utc.isoformat()}
    _append(path, row)
    return row


def record_error(state_dir: Path, day: dt.date, err: str, now_utc: dt.datetime) -> None:
    """A run that could not score D still leaves a row saying why (never a silent gap)."""
    path = state_dir / "distribution_scores.csv"
    if _already_scored(path, day):
        return
    _append(path, {"date": day.isoformat(), "auction_pnl_usd": "", "distribution_pnl_usd": UNMEASURED,
                   "auction_pnl_with_distributions_usd": UNMEASURED,
                   "unmeasured": f"distribution score error: {err}", "per_symbol_json": "",
                   "source": "", "label": LABEL, "written_at_utc": now_utc.isoformat()})
