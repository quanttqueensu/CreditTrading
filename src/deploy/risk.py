"""Per-sleeve kill/halve switches and book-level risk limits.

Two layers, both machine-readable:

  * `evaluate_sleeve(...)` combines a sleeve's own `risk_check` verdict with a
    drawdown backstop read straight off its sub-ledger NAV. KILL flattens and
    disables the sleeve for the rest of the run; HALVE scales its capital and
    flags a review. One sleeve's verdict never touches another's ledger.
  * `check_book_limits(...)` enforces the book-level caps from
    `book_spec["limits"]`: aggregate gross-exposure, book drawdown suspend
    (Gate S at book level), per-sleeve capital caps, and a worst-month dollar
    budget. Breaches are written to `ops/books/book_status.json`, the same
    machine-readable pattern as `ops/monitor.py::monitor_status.json`.
"""

import numpy as np
import pandas as pd

from .sleeve import OK, HALVE, KILL, RiskVerdict


def _max_drawdown(nav_series):
    if nav_series is None or len(nav_series) == 0:
        return 0.0
    nav = pd.Series(nav_series).astype(float).dropna()
    if nav.empty:
        return 0.0
    peak = nav.cummax()
    dd = (nav / peak - 1.0)
    return float(dd.min())


def _worst_month_usd(ledger):
    """Worst calendar-month P&L in dollars off the sub-ledger NAV."""
    nav = ledger.nav_series()
    if nav.empty:
        return 0.0
    monthly = nav.resample("ME").last()
    pnl = monthly.diff().dropna()
    return float(pnl.min()) if len(pnl) else 0.0


def evaluate_sleeve(sleeve, ledger, verbose=False):
    """Return a RiskVerdict for one sleeve. Merges the sleeve's own
    `risk_check` with a drawdown backstop from `sleeve.risk` (if present)."""
    try:
        verdict = sleeve.risk_check(ledger)
    except Exception as exc:              # a sleeve that can't self-grade halves
        return RiskVerdict(HALVE, [f"risk_check raised {exc!r}; halving pending review"])
    if not isinstance(verdict, RiskVerdict):
        verdict = RiskVerdict(OK, [])

    reasons = list(verdict.reasons)
    status = verdict.status

    # Drawdown backstop from the spec's risk block, if it names one.
    dd_kill = sleeve.risk.get("max_drawdown_kill_pct")
    if dd_kill is not None:
        dd = _max_drawdown(ledger.nav_series())
        if dd <= -abs(float(dd_kill)) / 100.0:
            status = KILL
            reasons.append(
                f"sub-ledger drawdown {dd:+.2%} breached kill threshold "
                f"{-abs(float(dd_kill)):.2f}%")
    return RiskVerdict(status, reasons)


def apply_verdict(orchestrator, sleeve_name, verdict):
    """Effect a KILL/HALVE on the orchestrator's view. KILL disables the sleeve
    (and signals a flatten); HALVE scales its capital and flags a review.
    Returns a dict describing the action for the book status file."""
    action = {"sleeve": sleeve_name, "status": verdict.status,
              "reasons": list(verdict.reasons)}
    if verdict.status == KILL:
        orchestrator.disabled.add(sleeve_name)
        action["effect"] = "flattened and disabled for the rest of the run"
    elif verdict.status == HALVE:
        # Idempotent: a breach that persists day-after-day must NOT keep halving
        # (that would compound to zero). Halve once, on the first breach.
        if sleeve_name in orchestrator.review_flags:
            action["effect"] = "already halved earlier; review flag stands"
            return action
        orchestrator.capital[sleeve_name] *= 0.5
        # Book-level de-rate (the mechanism the v2 orchestrator actually acts
        # on): a HALVEd sleeve contributes HALF its legs to the netted book.
        # `risk_scale` is applied per-sleeve at book assembly BEFORE netting
        # (portfolio_v2._assemble_book), so it works for a buy-and-hold sleeve
        # (the overlay's credit leg never re-sizes off capital, so halving
        # capital alone would NOT shrink its short-IEF hedge) as well as for a
        # weight/qty sleeve. Guarded so risk.apply_verdict stays usable by the
        # unit-test orchestrator stub that carries no `risk_scale`. Idempotent —
        # set to 0.5 (assignment, never compounded), and the review_flags
        # early-return above prevents a second visit anyway.
        rscale = getattr(orchestrator, "risk_scale", None)
        if isinstance(rscale, dict):
            rscale[sleeve_name] = 0.5
        # Halve the REAL sizing base too, not just the reported capital. The
        # short-vol (`n_straddles`) sleeve sizes off `sleeve.capital_usd`;
        # without this the de-risk was cosmetic and it kept trading full size
        # after a HALVE. (Weight/qty sleeves de-rate via risk_scale above; the
        # orchestrator resolves them at INITIAL capital so this halving is
        # reporting-only for them and never double-counts.)
        sleeve = orchestrator.sleeves.get(sleeve_name)
        if sleeve is not None:
            sleeve.capital_usd = float(sleeve.capital_usd) * 0.5
            # Keep the shadow/sim sub-ledger's sizing view in step so a weight
            # sleeve's NAV-based sizing and the broker's registered capital agree.
            broker = getattr(orchestrator, "broker", None)
            cfg = getattr(broker, "_cfg", None)
            if isinstance(cfg, dict) and sleeve_name in cfg:
                c = cfg[sleeve_name]
                c["capital_usd"] = float(c.get("capital_usd", 0.0)) * 0.5
                run_spec = c.get("run_spec")
                if isinstance(run_spec, dict):
                    for k in ("capital_usd", "book_usd"):
                        if k in run_spec:
                            run_spec[k] = float(run_spec[k]) * 0.5
        orchestrator.review_flags.add(sleeve_name)
        action["effect"] = "capital halved (reported + sizing base); review flag set"
    else:
        action["effect"] = "none"
    return action


def check_book_limits(book_spec, sleeve_views, book_nav, book_gross, ledgers):
    """Evaluate book-level limits. `sleeve_views` is name -> view dict.
    Returns {limit_name: {ok, detail, action}}."""
    limits = book_spec.get("limits", {})
    out = {}

    gross_cap = limits.get("max_gross_exposure_usd")
    if gross_cap is not None:
        ok = book_gross <= float(gross_cap)
        out["max_gross_exposure_usd"] = {
            "ok": bool(ok), "value": float(book_gross), "cap": float(gross_cap),
            "action": None if ok else "REDUCE gross exposure below the book cap"}

    dd_suspend = limits.get("book_drawdown_suspend_pct")
    if dd_suspend is not None and ledgers:
        navs = [lg.nav_series() for lg in ledgers.values() if not lg.nav.empty]
        if navs:
            # Align on the union calendar and forward-fill: a sleeve whose marks
            # end early (short-vol stops 2026-07-10) HOLDS its last NAV rather
            # than collapsing to 0 — otherwise the sum shows a phantom book
            # drawdown of that sleeve's whole NAV and falsely trips SUSPEND.
            # Leading gaps (a sleeve not yet funded) back-fill to its first NAV
            # so the book series is the sum of live sub-books at every date.
            book = (pd.concat(navs, axis=1).sort_index()
                    .ffill().bfill().sum(axis=1))
            dd = _max_drawdown(book)
            ok = dd > -abs(float(dd_suspend)) / 100.0
            out["book_drawdown_suspend_pct"] = {
                "ok": bool(ok), "value": float(dd), "cap": -abs(float(dd_suspend)) / 100.0,
                "action": None if ok else "SUSPEND the book (Gate S, book level)"}

    cap_lo, cap_hi = limits.get("per_sleeve_capital_band", [None, None])
    if cap_hi is not None:
        breaches = [n for n, v in sleeve_views.items()
                    if v.get("capital_usd", 0) > float(cap_hi)]
        out["per_sleeve_capital_band"] = {
            "ok": not breaches, "breaches": breaches,
            "action": None if not breaches else f"per-sleeve cap exceeded: {breaches}"}

    wm_budget = limits.get("book_worst_month_usd")
    if wm_budget is not None and ledgers:
        worst = sum(_worst_month_usd(lg) for lg in ledgers.values())
        ok = worst >= -abs(float(wm_budget))
        out["book_worst_month_usd"] = {
            "ok": bool(ok), "value": float(worst), "budget": -abs(float(wm_budget)),
            "action": None if ok else "worst-month dollar budget breached"}
    return out
