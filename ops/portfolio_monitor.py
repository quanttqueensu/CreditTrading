"""Multi-sleeve book monitor — the portfolio-level companion to ops/monitor.py.

    python3 ops/portfolio_monitor.py --book ops/books/book.json
    python3 ops/portfolio_monitor.py --book ops/books/book.json --rebuild-bands

`ops/monitor.py` grades ONE static-weights sleeve against block-bootstrap Gate S
bands. This grades the WHOLE 5-sleeve book:

  * the credit base (static_weights, carries `allocation.weights` + `book_usd`
    + a `gate_s` block) is graded by the SAME `ops.monitor.run` machinery —
    full bootstrap bands, CONTINUE/HALVE/SUSPEND;
  * the calendar/option sleeves (eom, fomc, short-vol, overlay) are not
    weight-expressible, so bootstrap-from-weights bands do not apply. They are
    graded "Gate-S style" off their own sub-ledger: live drawdown vs the frozen
    `risk` halve/kill thresholds, worst-month dollars, trailing return, and the
    sleeve's own `risk_check` verdict (the exact machinery the runner's kill
    switch uses) — so the monitor and the live book agree by construction.

It also flags DATA STALENESS across every source the book reads (the ETF panel,
the VRP marks — which end early BY DESIGN — the SPY underlying, the risk-free
curve), and rolls the per-sleeve grades into a single book verdict. Writes
`ops/books/book_monitor.json` (machine-readable, same pattern as
`monitor_status.json`) and prints a human summary.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops import common, monitor as sleeve_monitor  # noqa: E402
from src.backtest import tearsheet as ts  # noqa: E402
from src.deploy import registry, risk as deploy_risk, report as book_report  # noqa: E402
from src.deploy.broker.simulator import LONG_ONLY_TYPES, DERIVATIVES_TYPES  # noqa: E402
from src.deploy.exec_ledger import LongOnlySleeveLedger, DerivativesLedger  # noqa: E402

CONTINUE, HALVE, SUSPEND = "CONTINUE", "HALVE", "SUSPEND"
BOOK_MONITOR_FILE = "book_monitor.json"


def _load_spec(entry, books_root):
    spec = entry.get("spec")
    if spec is None:
        sp = entry.get("spec_path")
        if sp is None:
            sp = Path(books_root) / entry["name"] / "frozen_spec.json"
        with open(sp) as fh:
            spec = json.load(fh)
    return spec


def _open_ledger(alloc_type, state_dir):
    if alloc_type in DERIVATIVES_TYPES:
        return DerivativesLedger(state_dir)
    return LongOnlySleeveLedger(state_dir)      # long-only incl. static_weights


def _as_dd_fraction(v):
    """Normalize a drawdown threshold to a POSITIVE fraction, tolerant of the
    two conventions the frozen specs use side-by-side: credit/short-vol store
    percentages (23.0, 7.99); the overlay stores fractions (-0.25, -0.12). A
    magnitude > 1 is a percent (divide by 100); <= 1 is already a fraction."""
    if v is None:
        return None
    m = abs(float(v))
    return m / 100.0 if m > 1.0 else m


def _dd_thresholds(spec):
    """(halve_frac, kill_frac) as positive fractions from the frozen risk block,
    tolerant of the per-sleeve naming (credit uses max_drawdown_*; overlay uses
    dd_*; short-vol uses halve_drawdown_pct). None where the sleeve names none."""
    r = spec.get("risk", {})
    halve = (r.get("max_drawdown_halve_pct") or r.get("dd_halve")
             or r.get("halve_drawdown_pct"))
    kill = (r.get("max_drawdown_kill_pct") or r.get("dd_kill"))
    return _as_dd_fraction(halve), _as_dd_fraction(kill)


def _lightweight_grade(name, spec, capital, state_dir):
    """Gate-S-style grade for a non-weight-expressible sleeve, off its own
    sub-ledger. Uses the SAME `risk_check` the live kill switch uses."""
    alloc_type = spec["allocation"]["type"]
    lg = _open_ledger(alloc_type, state_dir)
    out = {"name": name, "alloc_type": alloc_type, "grader": "sleeve_ledger"}
    if lg.nav.empty:
        out.update({"status": CONTINUE, "graded": False,
                    "reason": "sub-ledger empty — not graded yet (run the book first)"})
        return out

    nav = lg.nav_series()
    rets = nav.pct_change().dropna()
    mdd = ts.max_drawdown(rets)[0] if len(rets) else 0.0
    monthly = nav.resample("ME").last().diff().dropna()
    worst_month = float(monthly.min()) if len(monthly) else 0.0
    total_ret = float(nav.iloc[-1] / nav.iloc[0] - 1.0)

    sleeve = registry.build_sleeve(spec, capital)
    verdict = deploy_risk.evaluate_sleeve(sleeve, lg)

    halve_dd, kill_dd = _dd_thresholds(spec)   # positive fractions
    # map the sub-ledger verdict onto the CONTINUE/HALVE/SUSPEND vocabulary the
    # book verdict speaks, and cross-check drawdown against the frozen bands.
    status = {"OK": CONTINUE, "HALVE": HALVE, "KILL": SUSPEND}[verdict.status]
    band_flag = None
    if kill_dd is not None and mdd <= -kill_dd:
        status, band_flag = SUSPEND, f"drawdown {mdd:+.2%} <= kill {-kill_dd:.2%}"
    elif halve_dd is not None and mdd <= -halve_dd and status == CONTINUE:
        status, band_flag = HALVE, f"drawdown {mdd:+.2%} <= halve {-halve_dd:.2%}"

    out.update({
        "graded": True, "status": status,
        "live_start": str(nav.index.min().date()),
        "live_end": str(nav.index.max().date()),
        "n_live_days": int(len(nav)),
        "nav": float(nav.iloc[-1]), "total_return": total_ret,
        "live_max_drawdown": float(mdd), "worst_month_usd": worst_month,
        "dd_halve_frac": halve_dd, "dd_kill_frac": kill_dd,
        "risk_verdict": verdict.status,
        "reasons": list(verdict.reasons) + ([band_flag] if band_flag else []),
    })
    return out


def _full_gate_s_grade(name, spec, state_dir, rebuild):
    """Grade a static-weights sleeve with the ops/monitor.py Gate S bands.

    Uses `build_bands`/`load_bands` + `grade_live` directly (the block-bootstrap
    machinery) rather than `ops.monitor.run`, so the credit base is graded even
    though its frozen spec carries no `crowding` block — the S1 crowding light is
    a monthly check run separately via `ops/monitor.py --state-dir
    ops/books/credit_base` (§5), not part of the daily book roll-up."""
    state_dir = Path(state_dir)
    bands = sleeve_monitor.load_bands(state_dir)
    if bands is None or rebuild or bands.get("weights") != spec["allocation"]["weights"]:
        bands = sleeve_monitor.build_bands(spec, state_dir, verbose=False)
    lg = LongOnlySleeveLedger(state_dir)
    prices = common.read_prices(state_dir)
    g = sleeve_monitor.grade_live(spec, lg, prices, bands, verbose=False)
    book_status = {"OK": CONTINUE, "HALVE": HALVE,
                   "SUSPEND": SUSPEND}.get(g["status"], CONTINUE)
    return {"name": name, "alloc_type": "static_weights",
            "grader": "gate_s_bootstrap", "graded": g["return_3m"] is not None,
            "status": book_status, "gate_s": g,
            "crowding_note": ("S1 crowding light graded separately via "
                              "ops/monitor.py on ops/books/credit_base"),
            "live_start": g.get("live_start"), "live_end": g.get("live_end"),
            "n_live_days": g.get("n_live_days"),
            "live_max_drawdown": g.get("live_max_drawdown"),
            "worst_month_usd": None,
            "reasons": [g.get("reason", "")]}


def grade_book(book_spec, books_root="ops/books", asof=None,
               rebuild_bands=False, verbose=True):
    books_root = Path(books_root)
    asof = pd.Timestamp(asof) if asof else pd.Timestamp(datetime.now().date())
    sleeves_out = {}
    for entry in book_spec.get("sleeves", []):
        name = entry["name"]
        if not entry.get("enabled", True):
            sleeves_out[name] = {"name": name, "status": "DISABLED",
                                 "graded": False, "reason": "disabled in book spec"}
            continue
        spec = _load_spec(entry, books_root)
        capital = float(entry.get("capital_usd",
                                  spec.get("capital_usd", spec.get("book_usd", 0.0))))
        state_dir = books_root / name
        alloc_type = spec["allocation"]["type"]
        weight_ok = (alloc_type == "static_weights"
                     and "weights" in spec["allocation"]
                     and "book_usd" in spec and "gate_s" in spec)
        try:
            if weight_ok:
                sleeves_out[name] = _full_gate_s_grade(name, spec, state_dir,
                                                       rebuild_bands)
            else:
                sleeves_out[name] = _lightweight_grade(name, spec, capital, state_dir)
        except Exception as exc:      # a grader that blows up HALVES pending review
            sleeves_out[name] = {"name": name, "alloc_type": alloc_type,
                                 "graded": False, "status": HALVE,
                                 "reason": f"grader raised {exc!r}"}

    stale = book_report.staleness_report(asof, book_spec.get("data_sources"))
    stale_hits = [s for s in stale if s["stale"] and not s["expected"]]

    # book verdict: worst sleeve grade, escalated by any UNEXPECTED stale source.
    order = {CONTINUE: 0, "DISABLED": 0, HALVE: 1, SUSPEND: 2}
    worst = CONTINUE
    for sv in sleeves_out.values():
        st = sv.get("status", CONTINUE)
        if order.get(st, 0) > order.get(worst, 0):
            worst = st
    if stale_hits and order.get(worst, 0) < 1:
        worst = HALVE

    actions = []
    for name, sv in sleeves_out.items():
        if sv.get("status") == SUSPEND:
            actions.append(f"SUSPEND {name} and write the Gate S review.")
        elif sv.get("status") == HALVE:
            actions.append(f"HALVE {name} and review before the next period.")
    for s in stale_hits:
        actions.append(f"Refresh {s['source']} ({s['path']}) — "
                       f"{s['age_days']}d stale. A stale green is not a green.")

    status = {
        "asof": str(asof.date()),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "book_id": book_spec.get("book_id", "book"),
        "book_verdict": worst,
        "sleeves": sleeves_out,
        "data_freshness": stale,
        "actions": actions or ["Continue the whole book at frozen size."],
    }
    (books_root / BOOK_MONITOR_FILE).write_text(json.dumps(status, indent=2, default=str) + "\n")
    if verbose:
        _print(status)
        print(f"\n  written to {books_root / BOOK_MONITOR_FILE}")
    return status


def _print(s):
    common.banner(f"BOOK MONITOR — {s['book_id']}  ({s['asof']})")
    print(f"  book verdict: {s['book_verdict']}")
    print()
    print(f"  {'sleeve':<20}{'grader':<18}{'status':<10}{'maxDD':>9}"
          f"{'worst mo $':>13}   verdict")
    for name, sv in s["sleeves"].items():
        mdd = sv.get("live_max_drawdown")
        mdd_s = f"{mdd:+.2%}" if isinstance(mdd, (int, float)) else "-"
        wm = sv.get("worst_month_usd")
        wm_s = common.money(wm) if isinstance(wm, (int, float)) else "-"
        rv = sv.get("risk_verdict", "-")
        print(f"  {name:<20}{sv.get('grader','-'):<18}{sv.get('status','-'):<10}"
              f"{mdd_s:>9}{wm_s:>13}   {rv}")
    common.banner("DATA FRESHNESS")
    for d in s["data_freshness"]:
        tag = ("expected-stale" if d["expected"] and d["stale"]
               else "STALE" if d["stale"] else "fresh")
        print(f"  {d['source']:<16} last {str(d['last_date']):<12} "
              f"age {str(d['age_days']):>4}d  -> {tag}")
    common.banner("ACTIONS")
    for a in s["actions"]:
        print(f"    - {a}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", default="ops/books/book.json")
    ap.add_argument("--books-root", default="ops/books")
    ap.add_argument("--asof", default=None)
    ap.add_argument("--rebuild-bands", action="store_true",
                    help="recompute the credit-base Gate S bootstrap bands")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    with open(args.book) as fh:
        book_spec = json.load(fh)
    grade_book(book_spec, books_root=args.books_root, asof=args.asof,
               rebuild_bands=args.rebuild_bands, verbose=not args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
