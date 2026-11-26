"""The side-by-side table (contract §2, B6): each book's twin against its Alpaca book, session by session.

    python3 -m quantt.twin compare               every session so far, then the tally
    python3 -m quantt.twin compare --aggregates  the tally only: safe to paste into a committed note

The lines of §2, per book, from `<state>/compare.csv` (written by verify; aggregates only):
  1. sessions       both traded / only Alpaca / only the twin. A twin session missed (Gateway down,
                    refused) counts against the twin.
  2. filled in full the book's orders whose booked shares equal what the book wanted, against
                    Alpaca's orders filled in full.
  3. fill vs close  notional-weighted bp, + = worse, on the sessions BOTH traded, with the paired
                    difference (twin - Alpaca) and, from two sessions on, its standard error over
                    sessions. ONE session has no standard error, and none is printed: the team lead
                    rules on the table, not on a threshold written here (H14).
  4. reconciled     sessions whose ledger summed to IBKR's positions on every symbol.
  5. double sends   sessions with a second set for one auction (must be zero).
  6. refused shorts shorts IBKR refused, counted (named in each session's verify.json).
Crossed shares are counted apart and never enter the twin's bp (contract §8 N5). The events book's
per-sleeve P&L is printed from the twin's ledger at the newest official closes (verify.json).
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from quantt.twin import books

FILE = "compare.csv"


def read_rows(state: Path) -> list:
    p = Path(state) / FILE
    if not p.exists():
        return []
    with p.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _num(x):
    return None if x in ("", None) else float(x)


def tally(rows: list) -> dict:
    out = {}
    for b in books.BOOK_NAMES:
        mine = [r for r in rows if r["book"] == b]
        both = [r for r in mine if r["twin_traded"] == "True" and r["alpaca_traded"] == "True"]
        pairs = [(_num(r["twin_bp"]), _num(r["alpaca_bp"])) for r in both
                 if _num(r["twin_bp"]) is not None and _num(r["alpaca_bp"]) is not None]
        diffs = [t - a for t, a in pairs]
        se = None
        if len(diffs) >= 2:
            m = sum(diffs) / len(diffs)
            se = math.sqrt(sum((d - m) ** 2 for d in diffs) / (len(diffs) - 1)) / math.sqrt(len(diffs))

        def wmean(col_bp, col_w):
            rs = [(_num(r[col_w]), _num(r[col_bp])) for r in both if _num(r[col_bp]) is not None and _num(r[col_w])]
            w = sum(n for n, _ in rs)
            return None if not w else sum(n * x for n, x in rs) / w

        out[b] = {
            "sessions": len(mine), "both_traded": len(both),
            "only_alpaca": sum(1 for r in mine if r["alpaca_traded"] == "True" and r["twin_traded"] != "True"),
            "only_twin": sum(1 for r in mine if r["twin_traded"] == "True" and r["alpaca_traded"] != "True"),
            "twin_full": sum(int(r["twin_full"] or 0) for r in both),
            "twin_orders": sum(int(r["twin_orders"] or 0) for r in both),
            "alpaca_full": sum(int(r["alpaca_full"] or 0) for r in both),
            "alpaca_orders": sum(int(r["alpaca_orders"] or 0) for r in both),
            "twin_bp": wmean("twin_bp", "twin_scored_usd"), "alpaca_bp": wmean("alpaca_bp", "alpaca_scored_usd"),
            "paired_sessions": len(diffs), "paired_diff_bp": (sum(diffs) / len(diffs)) if diffs else None,
            "paired_diff_se_bp": se,
            "twin_crossed_shares": sum(int(r["twin_crossed_shares"] or 0) for r in mine),
            "reconciled": sum(1 for r in mine if r["reconciled"] == "True"),
            "twin_sessions_booked": sum(1 for r in mine if r["reconciled"] in ("True", "False")),
            "double_sends": sum(1 for r in mine if r["double_send"] == "True"),
            "refused_shorts": sum(int(r["refused_shorts"] or 0) for r in mine),
            "residual_usd": sum(_num(r["residual_usd"]) or 0.0 for r in mine)}
    return out


def _fmt(x, nd=1):
    return "-" if x is None else f"{x:+.{nd}f}"


def render(state: Path, *, aggregates: bool) -> str:
    rows = read_rows(state)
    lines = ["IBKR twin against Alpaca, per book (paper fills both sides; + bp = worse than the official close)"]
    if not rows:
        return "\n".join(lines + ["no session verified yet (compare.csv is empty)"])
    if not aggregates:
        lines.append(f"{'date':<11}{'book':<8}{'twin':>5}{'alp':>5}{'full twin':>11}{'full alp':>10}"
                     f"{'bp twin':>9}{'bp alp':>8}{'diff':>7}{'crossed':>9}{'resid $':>10}{'ref.sh':>7}{'recon':>7}")
        for r in rows:
            t, a = _num(r["twin_bp"]), _num(r["alpaca_bp"])
            lines.append(f"{r['date']:<11}{r['book']:<8}{'Y' if r['twin_traded'] == 'True' else 'n':>5}"
                         f"{'Y' if r['alpaca_traded'] == 'True' else ('?' if not r['alpaca_traded'] else 'n'):>5}"
                         f"{(r['twin_full'] + '/' + r['twin_orders']) if r['twin_orders'] != '' else '-':>11}"
                         f"{(str(r['alpaca_full']) + '/' + str(r['alpaca_orders'])) if r['alpaca_orders'] != '' else '-':>10}"
                         f"{_fmt(t):>9}{_fmt(a):>8}{_fmt(t - a if t is not None and a is not None else None):>7}"
                         f"{r['twin_crossed_shares'] or '-':>9}{r['residual_usd'] or '-':>10}"
                         f"{r['refused_shorts'] or '-':>7}{r['reconciled'] or '-':>7}")
    lines.append("")
    lines.append("TALLY (the side-by-side so far)")
    for b, t in tally(rows).items():
        lines.append(f"  {b}: {t['sessions']} session(s), both traded {t['both_traded']}, only Alpaca "
                     f"{t['only_alpaca']}, only twin {t['only_twin']}; filled in full twin {t['twin_full']}/"
                     f"{t['twin_orders']}, Alpaca {t['alpaca_full']}/{t['alpaca_orders']}; fill vs close twin "
                     f"{_fmt(t['twin_bp'])}bp, Alpaca {_fmt(t['alpaca_bp'])}bp, paired diff "
                     f"{_fmt(t['paired_diff_bp'])}bp over {t['paired_sessions']} session(s), SE "
                     + ("none (fewer than two sessions)" if t["paired_diff_se_bp"] is None else f"{t['paired_diff_se_bp']:.1f}bp")
                     + f"; reconciled {t['reconciled']}/{t['twin_sessions_booked']}; double sends "
                     f"{t['double_sends']}; refused shorts {t['refused_shorts']}; crossed shares {t['twin_crossed_shares']}")
    sp = _sleeve_pnl(state)
    if sp:
        lines.append(f"  events sleeves, twin ledger at the {sp['date']} official close (cash + shares x close, USD):")
        for slug, v in sp["pnl"].items():
            dc = sp["day"].get(slug)
            lines.append(f"    {slug:<36}{'UNMEASURED' if v is None else f'{v:+,.2f}':>14}"
                         f"   day {'-' if dc is None else f'{dc:+,.2f}'}")
    return "\n".join(lines)


def _sleeve_pnl(state: Path) -> dict | None:
    for d in sorted((x for x in Path(state).iterdir() if x.is_dir() and x.name[:2] == "20"), reverse=True):
        v = d / "verify.json"
        if v.exists():
            vd = json.loads(v.read_text())
            if vd.get("ledger_applied"):
                p = {s: x for s, x in (vd.get("slug_pnl") or {}).items() if s.startswith(books.EVENTS_PREFIX)}
                return {"date": d.name, "pnl": p, "day": vd.get("slug_day_change") or {}}
    return None
