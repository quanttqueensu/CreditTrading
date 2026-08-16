"""Book-level daily report for the human.

The portfolio runner produces two machine files already (`book_status.json` and
each sub-ledger's own CSVs). This module adds the two artefacts a person reads
each morning, per the build brief ("write a daily report + target_vs_current for
the human"):

  * `ops/books/report_<asof>.md` — one page: book NAV/PnL/turnover, the
    per-sleeve table (NAV, PnL, gross, turnover, risk verdict, enabled state),
    the book-level limit checks, and a data-staleness note.
  * `ops/books/target_vs_current.csv` — book-level target-vs-held: for every
    sleeve, each instrument's CURRENT signed holding, the sleeve's freshly
    emitted TARGET (side + qty/weight), and the delta the executor must trade.

Reuses `src/backtest/tearsheet` (drawdown/worst-month off the sub-ledger NAV)
and `ops.common.money`. It reads the orchestrator's post-`advance` state — the
same `BookView` the runner already has — so it invents no numbers.
"""

import csv
from pathlib import Path

import numpy as np
import pandas as pd

from ops import common as ops_common
from src.backtest import tearsheet as ts


# -- data staleness ------------------------------------------------------

# (label, path, how-many-days-old before we flag it). ETF panel drives every
# long-only sleeve; the VRP marks drive short-vol and END EARLIER by design.
def _last_date(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p, columns=["date"])
        return pd.Timestamp(df["date"].max())
    except Exception:
        return None


def staleness_report(asof, data_sources=None, stale_after_days=5):
    """Flag each data source whose newest bar is > stale_after_days before asof.
    Short-vol marks legitimately end 2026-07-10, so their staleness is reported
    but tagged expected=True — it means 'short-vol reports INSUFFICIENT_MARKS',
    not 'the pipeline broke'."""
    asof = pd.Timestamp(asof)
    srcs = data_sources or {
        "etf_panel": "data/etf_daily.parquet",
        "vrp_marks": "data/vrp/marks_SPY.parquet",
        "vrp_underlying": "data/vrp/underlying_daily.parquet",
        "riskfree": "data/riskfree_daily.parquet",
    }
    rows = []
    for label, path in srcs.items():
        last = _last_date(path)
        if last is None:
            rows.append({"source": label, "path": path, "last_date": None,
                         "age_days": None, "stale": True, "expected": False,
                         "note": "MISSING or unreadable"})
            continue
        age = int((asof.normalize() - last.normalize()).days)
        expected = label == "vrp_marks"     # marks end earlier by design (§6)
        rows.append({"source": label, "path": path,
                     "last_date": str(last.date()), "age_days": age,
                     "stale": bool(age > stale_after_days),
                     "expected": expected,
                     "note": ("marks end early by design -> short-vol "
                              "INSUFFICIENT_MARKS" if expected else "")})
    return rows


# -- target vs current ---------------------------------------------------

def _target_rows(orch):
    """One row per (sleeve, instrument): current signed holding vs the target
    the sleeve just emitted, and the trade delta implied. Weight-expressed
    targets (static/eom) show the emitted side + weight; qty-expressed targets
    (short-vol, overlay) show the signed qty."""
    rows = []
    for name in orch.sleeves:
        held = {}
        try:
            held = orch.broker.sync_positions(name)
        except Exception:
            held = {}
        held = {k: float(v) for k, v in held.items() if k != "CASH"}
        targets = orch.last_targets.get(name, [])
        seen = set()
        for t in targets:
            inst = t.instrument
            seen.add(inst)
            cur = held.get(inst, 0.0)
            tgt_qty = t.qty if t.qty is not None else None
            delta = (tgt_qty - cur) if tgt_qty is not None else None
            rows.append({
                "sleeve": name, "instrument": inst, "kind": t.kind,
                "current_qty": round(cur, 6),
                "target_side": t.side,
                "target_qty": ("" if tgt_qty is None else round(float(tgt_qty), 6)),
                "target_weight": ("" if t.weight is None else round(float(t.weight), 6)),
                "delta_qty": ("" if delta is None else round(float(delta), 6)),
                "reason": t.reason})
        # instruments held but no longer targeted (should be flattened)
        for inst, cur in held.items():
            if inst in seen or abs(cur) < 1e-9:
                continue
            rows.append({
                "sleeve": name, "instrument": inst, "kind": "ETF",
                "current_qty": round(cur, 6), "target_side": "FLAT",
                "target_qty": 0.0, "target_weight": "",
                "delta_qty": round(-cur, 6),
                "reason": "held but not in current target"})
    return rows


def write_target_vs_current(orch, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _target_rows(orch)
    path = out_dir / "target_vs_current.csv"
    cols = ["sleeve", "instrument", "kind", "current_qty", "target_side",
            "target_qty", "target_weight", "delta_qty", "reason"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path, rows


# -- the report ----------------------------------------------------------

def _sleeve_dd_and_worst(ledger):
    """(maxDD fraction, worst-month $) off the sub-ledger, via tearsheet.
    Empty ledger -> (0, 0)."""
    if ledger is None or ledger.nav.empty:
        return 0.0, 0.0
    nav = ledger.nav_series()
    rets = nav.pct_change().dropna()
    mdd = ts.max_drawdown(rets)[0] if len(rets) else 0.0
    monthly = nav.resample("ME").last().diff().dropna()
    worst = float(monthly.min()) if len(monthly) else 0.0
    return float(mdd), worst


def write_daily_report(orch, view, out_dir, asof=None,
                       data_sources=None, verbose=True):
    """Write report_<asof>.md + target_vs_current.csv. Returns (md_path, csv_path).
    `view` is the BookView returned by orchestrator.advance()."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    asof = pd.Timestamp(asof or view.asof)

    csv_path, tvc_rows = write_target_vs_current(orch, out_dir)
    stale = staleness_report(asof, data_sources)

    M = ops_common.money
    L = []
    A = L.append
    A(f"# Book daily report — {asof.date()}")
    A("")
    A(f"Book `{orch.book_spec.get('book_id', 'book')}`. "
      f"NAV **{M(view.book_nav)}**, PnL **{M(view.book_pnl)}**, "
      f"turnover today **{M(view.book_turnover)}**, "
      f"gross {M(view.gross_exposure)}, net {M(view.net_exposure)}, "
      f"cash {M(view.book_cash)}.")
    A("")
    A("Everything below is read straight off the sub-ledgers and the frozen "
      "specs; nothing is hand-entered.")
    A("")

    # -- per-sleeve table --
    A("## Sleeves")
    A("")
    A("| sleeve | state | NAV | PnL | gross | turnover | maxDD | worst mo $ | verdict |")
    A("|---|---|---:|---:|---:|---:|---:|---:|---|")
    for name, sv in view.sleeves.items():
        lg = orch.broker.ledger(name) if hasattr(orch.broker, "ledger") else None
        mdd, worst = _sleeve_dd_and_worst(lg)
        state = ("DISABLED" if sv["disabled"]
                 else "review" if sv.get("review_flag") else "enabled")
        verdict = sv["risk_verdict"]["status"]
        nav = sv["nav"]
        nav_s = M(nav) if np.isfinite(nav) else "n/a"
        A(f"| {name} | {state} | {nav_s} | {M(sv['pnl'])} | "
          f"{M(sv['gross_exposure'])} | {M(sv.get('turnover', 0.0))} | "
          f"{mdd:+.2%} | {M(worst)} | {verdict} |")
    A("")

    # per-sleeve risk reasons (only when not OK)
    flagged = [(n, sv) for n, sv in view.sleeves.items()
               if sv["risk_verdict"]["status"] != "OK"
               or sv["disabled"] or sv.get("review_flag")]
    if flagged:
        A("### Risk notes")
        A("")
        for n, sv in flagged:
            reasons = "; ".join(sv["risk_verdict"].get("reasons", [])) or "—"
            A(f"- **{n}** ({sv['risk_verdict']['status']}"
              f"{', DISABLED' if sv['disabled'] else ''}): {reasons}")
        A("")

    # -- book limits --
    A("## Book limits")
    A("")
    if not view.limits:
        A("_No book-level limits configured._")
    else:
        A("| limit | status | detail |")
        A("|---|---|---|")
        for lim, res in view.limits.items():
            ok = res.get("ok", True)
            if "value" in res and "cap" in res:
                detail = f"value {res['value']:,.2f} vs cap {res['cap']:,.2f}"
            elif "value" in res and "budget" in res:
                detail = f"value {res['value']:,.2f} vs budget {res['budget']:,.2f}"
            elif "breaches" in res:
                detail = f"breaches: {res['breaches'] or 'none'}"
            else:
                detail = ""
            act = res.get("action")
            if act:
                detail += f" — {act}"
            A(f"| {lim} | {'OK' if ok else '**BREACH**'} | {detail} |")
    A("")

    # -- data staleness --
    A("## Data freshness")
    A("")
    A("| source | last bar | age (d) | status |")
    A("|---|---|---:|---|")
    for s in stale:
        if s["expected"] and s["stale"]:
            status = "expected-stale (by design)"
        elif s["stale"]:
            status = "**STALE**"
        else:
            status = "fresh"
        A(f"| {s['source']} | {s['last_date'] or 'MISSING'} | "
          f"{s['age_days'] if s['age_days'] is not None else '—'} | {status} |")
    A("")

    # -- target vs current --
    A("## Target vs current (executor's trade list)")
    A("")
    if not tvc_rows:
        A("_No open targets — every enabled sleeve emitted FLAT / nothing._")
    else:
        A("| sleeve | instrument | current | target side | target qty | weight | delta | reason |")
        A("|---|---|---:|---|---:|---:|---:|---|")
        for r in tvc_rows:
            A(f"| {r['sleeve']} | {r['instrument']} | {r['current_qty']} | "
              f"{r['target_side']} | {r['target_qty']} | {r['target_weight']} | "
              f"{r['delta_qty']} | {r['reason']} |")
    A("")
    A(f"_Full machine-readable list: `{csv_path.name}`. "
      f"Book status: `book_status.json`._")
    A("")

    md_path = out_dir / f"report_{asof.date()}.md"
    md_path.write_text("\n".join(L) + "\n")
    if verbose:
        print(f"[report] wrote {md_path}")
        print(f"[report] wrote {csv_path}")
    return md_path, csv_path


# -- the v2 (margin-book) report -----------------------------------------

def write_v2_daily_report(orch, view, out_dir, asof=None,
                          data_sources=None, verbose=True):
    """Daily report for the v2 margin book. Same human page as `write_daily_report`
    but reads the v2 `BookView` schema (per-sleeve `shadow_nav` + `risk_verdict`;
    book-level margin/leverage/financing attached on the view) and the netted
    book. Writes `report_<asof>.md` + `target_vs_current.csv`. Invents no numbers
    — every figure is read off `view`, `orch.last_targets`, and the sub-ledgers.
    Returns (md_path, csv_path)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    asof = pd.Timestamp(asof or view.asof)

    csv_path, tvc_rows = write_target_vs_current(orch, out_dir)
    stale = staleness_report(asof, data_sources)

    M = ops_common.money
    def _pct(x):
        return f"{x:.1%}" if x is not None and x == x else "n/a"

    L = []
    A = L.append
    A(f"# Book v2 daily report — {asof.date()}")
    A("")
    A(f"Book `{orch.book_spec.get('book_id', 'book_v2')}` "
      f"(EXECUTION=simulator, marks = yfinance EOD). "
      f"NAV **{M(view.book_nav)}**, PnL **{M(view.book_pnl)}**, "
      f"turnover today **{M(view.book_turnover)}**, cash {M(view.book_cash)}.")
    A("")
    A(f"Portfolio margin: gross **{getattr(view, 'gross_leverage', 0.0):.2f}x**, "
      f"net **{getattr(view, 'net_leverage', 0.0):.2f}x**, "
      f"margin util **{_pct(getattr(view, 'margin_util', None))}**, "
      f"financing/day **{M(getattr(view, 'financing_usd', 0.0) or 0.0)}**, "
      f"gross notional {M(view.gross_exposure)}, net {M(view.net_exposure)}.")
    A("")
    A("Everything below is read straight off the netted book, the as-if-siloed "
      "shadow sub-ledgers, and the frozen specs; nothing is hand-entered.")
    A("")

    # -- per-sleeve table (shadow economics drive the frozen kill ladder) --
    A("## Sleeves (shadow economics + kill ladder)")
    A("")
    A("| sleeve | state | shadow NAV | risk_scale | verdict | re-adjud flag |")
    A("|---|---|---:|---:|---|---|")
    for name, sv in view.sleeves.items():
        state = ("DISABLED" if sv["disabled"]
                 else "review" if sv.get("review_flag")
                 else "enabled" if sv.get("enabled") else "off")
        snav = sv.get("shadow_nav")
        snav_s = M(snav) if snav is not None and np.isfinite(snav) else "n/a"
        A(f"| {name} | {state} | {snav_s} | "
          f"{sv.get('risk_scale', 1.0):.2f}x | "
          f"{sv['risk_verdict']['status']} | {sv.get('readjud_flag') or '—'} |")
    A("")

    flagged = [(n, sv) for n, sv in view.sleeves.items()
               if sv["risk_verdict"]["status"] != "OK"
               or sv["disabled"] or sv.get("review_flag")]
    if flagged:
        A("### Risk notes")
        A("")
        for n, sv in flagged:
            reasons = "; ".join(sv["risk_verdict"].get("reasons", [])) or "—"
            A(f"- **{n}** ({sv['risk_verdict']['status']}"
              f"{', DISABLED' if sv['disabled'] else ''}): {reasons}")
        A("")

    # -- book limits (Gate S at book level) --
    A("## Book limits (Gate S)")
    A("")
    if not view.limits:
        A("_No book-level limits configured._")
    else:
        A("| limit | status | detail |")
        A("|---|---|---|")
        for lim, res in view.limits.items():
            ok = res.get("ok", True)
            if "value" in res and "cap" in res:
                detail = f"value {res['value']:,.2f} vs cap {res['cap']:,.2f}"
            elif "value" in res and "budget" in res:
                detail = f"value {res['value']:,.2f} vs budget {res['budget']:,.2f}"
            elif "breaches" in res:
                detail = f"breaches: {res['breaches'] or 'none'}"
            else:
                detail = ""
            act = res.get("action")
            if act:
                detail += f" — {act}"
            A(f"| {lim} | {'OK' if ok else '**BREACH**'} | {detail} |")
    A("")

    # -- data staleness --
    A("## Data freshness")
    A("")
    A("| source | last bar | age (d) | status |")
    A("|---|---|---:|---|")
    for s in stale:
        if s["expected"] and s["stale"]:
            status = "expected-stale (by design)"
        elif s["stale"]:
            status = "**STALE**"
        else:
            status = "fresh"
        A(f"| {s['source']} | {s['last_date'] or 'MISSING'} | "
          f"{s['age_days'] if s['age_days'] is not None else '—'} | {status} |")
    A("")

    # -- today's target book --
    A("## Target book (today's positions per sleeve)")
    A("")
    if not tvc_rows:
        A("_No open targets — every enabled sleeve emitted FLAT / nothing._")
    else:
        A("| sleeve | instrument | current | target side | target qty | weight | delta | reason |")
        A("|---|---|---:|---|---:|---:|---:|---|")
        for r in tvc_rows:
            A(f"| {r['sleeve']} | {r['instrument']} | {r['current_qty']} | "
              f"{r['target_side']} | {r['target_qty']} | {r['target_weight']} | "
              f"{r['delta_qty']} | {r['reason']} |")
    A("")
    A(f"_Full machine-readable list: `{csv_path.name}`. "
      f"Book status: `book_status_v2.json`._")
    A("")

    md_path = out_dir / f"report_{asof.date()}.md"
    md_path.write_text("\n".join(L) + "\n")
    if verbose:
        print(f"[report] wrote {md_path}")
        print(f"[report] wrote {csv_path}")
    return md_path, csv_path


__all__ = ["write_daily_report", "write_v2_daily_report",
           "write_target_vs_current", "staleness_report"]
