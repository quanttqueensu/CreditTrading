"""Replay every recorded run in a state directory through TODAY's gate 8 (exposure) and re-fit.

    python3 -m ops.replay_exposure <copy of the prod state dir>

WHY (2026-10-09). That day both sends were refused by gate 8 on a rule nobody had
replayed against the book's own history. Run against the recorded runs, the rule
had passed 2026-10-07 by $168 and 2026-10-08 by $765, both times only because
equity rose between the evening decide and the 15:52 send. Anyone changing
`quantt/session/gate.py` or the send path should run this on a copy of the prod
state before tagging (docs/RUNBOOK.md 8.6). It shows, for every recorded decide
and send:
  - what gate 8 refused THEN (from the run record), and
  - what it refuses NOW (the same inputs, the code in this tree),
  - `old_headroom`: 1.8 x live equity - gross after the plan, the margin the
    pre-2026-10-09 stress rule had (negative = it refused).

The inputs are the run's own records, never a re-read: `runs/*-run.json` holds
the account and positions the run measured. For a SEND the orders, closes and
sized equity come from that day's `plan.json`, minus any names skipped at send.
For a DECIDE (or a `cls` run) they come from the run record's decision and
closes. A run whose record lacks a field is listed as skipped, with the field;
nothing is assumed. The re-fit is replayed only where the run recorded one
(`bp_scale` / `bp_scale_at_send`), as the book's json said then, and the share
of the plan's traded notional it keeps is printed beside it (2026-10-13: the
release-check found the released fit kept 72% of a plan where 98.7% fits).

READ-ONLY. It imports the pure gate and the pure re-fit; it opens no socket and
writes nothing. The state copy holds the account's positions: keep it out of the
repo (`results/` is tracked).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from quantt.session import gate as gt
from quantt.session import run as rn
from quantt.session.decide import Order


def _orders(rows) -> tuple:
    return tuple(Order(**{k: o[k] for k in rn.ORDER_FIELDS if k in o}) for o in rows)


def replay_run(rec: dict, plan: dict | None, spec_p: dict) -> dict:
    """One run record -> a row; `skipped` names what the record lacked."""
    a = rec.get("account") or {}
    need = ("equity", "buying_power", "maintenance_margin", "long_market_value",
            "short_market_value")
    if any(k not in a for k in need):
        return {"skipped": f"account lacks {[k for k in need if k not in a]}"}
    pos = rec.get("positions")
    if pos is None:
        return {"skipped": "no positions"}
    if rec.get("phase") == "send":
        if not plan:
            return {"skipped": "send with no plan.json"}
        closes = {k: float(v) for k, v in plan["closes"].items()}
        gone = {s.split(":")[0] for s in rec.get("skipped_at_send") or []}
        orders = tuple(o for o in _orders(plan["orders"]) if o.client_order_id not in gone)
        sized = float(plan["equity"])
    elif rec.get("decision"):
        closes = {s: v["close"] for s, v in (rec.get("closes") or {}).items()
                  if v.get("close") is not None}
        orders = _orders(rec["decision"]["orders"])
        sized = float(a["equity"])
    else:
        return {"skipped": "no decision and not a send"}
    if not orders:
        return {"skipped": "no orders"}
    names = set(pos) | {o.symbol for o in orders}
    if any(s not in closes for s in names):
        return {"skipped": f"no close for {sorted(s for s in names if s not in closes)}"}
    eq, bp = float(a["equity"]), float(a["buying_power"])
    gross_now = float(a["long_market_value"]) + abs(float(a["short_market_value"]))
    after = sum(abs(q) * closes[s] for s, q in gt.projected_positions(orders, pos).items())
    held = sum(abs(q) * closes[s] for s, q in pos.items())
    fitted, binding, kept = orders, None, 1.0
    if rec.get("bp_scale_at_send") is not None or rec.get("bp_scale") is not None:
        fitted, kept, binding = rn.fit_to_buying_power(
            orders, pos, closes, eq, bp, gross_now, float(a["maintenance_margin"]),
            max_gross_stress=spec_p["max_gross_stress"], sized_equity=sized)
    now = gt.gate_exposure(fitted, pos, closes, eq, bp, spec_p["max_gross_usd"],
                           spec_p["max_gross_stress"], sized_equity=sized,
                           current_gross=gross_now,
                           maintenance_margin=float(a["maintenance_margin"]))
    mgs = spec_p["max_gross_stress"]
    return {"n": len(orders), "held": held, "after": after, "sized": sized, "live": eq,
            "old_headroom": None if mgs is None else mgs * eq - after, "refit": binding,
            "kept": kept,
            "then": [r["detail"] for r in rec.get("refusals") or [] if r["gate"] == "exposure"],
            "now": [r.detail for r in now]}


def replay(state: Path, spec_p: dict) -> tuple[list, Counter]:
    rows, every = [], Counter()
    for day in sorted(d for d in state.iterdir() if d.is_dir() and d.name[:2] == "20"):
        pp = day / "plan.json"
        plan = json.loads(pp.read_text()) if pp.exists() else None
        for f in sorted((day / "runs").glob("*-run.json")) if (day / "runs").is_dir() else []:
            rec = json.loads(f.read_text())
            phase = rec.get("phase") or rec.get("mode") or "?"
            for r in rec.get("refusals") or []:
                every[(day.name, phase, r["gate"])] += 1
            ex = rec.get("exit")
            rows.append({"day": day.name, "run": f.name.split("-run")[0], "phase": phase,
                         "exit": ex.get("name") if isinstance(ex, dict) else ex,
                         **replay_run(rec, plan, spec_p)})
    return rows, every


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m ops.replay_exposure")
    ap.add_argument("state", type=Path, help="a COPY of the prod state dir (never the live one)")
    ap.add_argument("--spec", type=Path, default=rn.BOOKS["cef"].spec_path)
    a = ap.parse_args(argv)
    spec_p = rn.spec_params(rn.load_spec(a.spec))
    rows, every = replay(a.state, spec_p)
    print(f"{'day':<11}{'run':<17}{'phase':<8}{'exit':<10}{'n':>3}{'held':>10}{'after':>10}"
          f"{'sized eq':>11}{'live eq':>11}{'old room':>10}  then | now")
    for r in rows:
        if "skipped" in r:
            print(f"{r['day']:<11}{r['run']:<17}{r['phase']:<8}{str(r['exit']):<10}  skipped: "
                  f"{r['skipped']}")
            continue
        room = "-" if r["old_headroom"] is None else f"{r['old_headroom']:+,.0f}"
        print(f"{r['day']:<11}{r['run']:<17}{r['phase']:<8}{str(r['exit']):<10}{r['n']:>3}"
              f"{r['held']:>10,.0f}{r['after']:>10,.0f}{r['sized']:>11,.0f}{r['live']:>11,.2f}"
              f"{room:>10}  {'; '.join(r['then'])[:60] or '-'} | "
              f"{'; '.join(r['now'])[:80] or '-'}"
              + (f" [re-fit kept {r['kept']:.1%}: {r['refit']}]" if r["refit"] else ""))
    done = [r for r in rows if "skipped" not in r]
    print(f"\n{len(done)} run(s) replayed, {len(rows) - len(done)} skipped; gate 8 refused "
          f"{sum(bool(r['then']) for r in done)} then, {sum(bool(r['now']) for r in done)} now.")
    print("Every refusal recorded, any gate (day, phase, gate): count")
    for k, v in sorted(every.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
