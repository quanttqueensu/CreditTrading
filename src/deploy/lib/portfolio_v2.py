"""H1/H2/H3/H4 — the v2 portfolio orchestrator over ONE shared MarginBook.

REFINE_ARCHITECTURE.md §1.3. One `advance(asof)` runs the frozen v1 sleeves
verbatim, then assembles their output into the single margined book:

  1.  COLLECT  each enabled sleeve's target_positions(asof, ms). ms.holdings is
      that sleeve's OWN as-if-siloed sub-ledger (a v1 Simulator kept purely so
      the FROZEN per-sleeve kill switches fire on un-levered v1 economics —
      §4.2's canonicalizing view, realized here as a real siloed shadow).
  1a. RESOLVE weight-expressed targets to signed qty at the SLEEVE's OWN
      capital and the asof close (never the whole-book NAV).
  2.  EXPRESS rewrite resolved duration ETF qty -> DV01-matched FUTURES qty
      where book_v2.json says so (H3); everything else passes through.
  3.  NET sum same-instrument, same-kind signed qtys across sleeves (H4) — the
      EOM long ZN/IEF and overlay short net into ONE book leg.
  4.  SCALE apply the book vol-target factor k to the risky legs (H2).
  5.  CLAMP scale down so projected gross leverage <= the ceiling; integer
      round futures/options.
  6.  COMMIT the ONE MarginBook advances a single day (portfolio margin, A1
      financing on the single shared negative balance).
  7.  RISK per-sleeve kill/halve on the siloed shadow; book limits + margin_util
      + leverage on the MarginBook.

Frozen SIGNALS are never touched — the sleeves' target_positions run verbatim.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ops import common as ops_common
from ops.ledger import CASH
from ...deploy import registry, risk
from ...deploy.broker.simulator import Simulator
from ...deploy.portfolio import BookView, local_panel_loader
from ...deploy.sleeve import (ETF, FLAT, FUTURES, LONG, OPTION, SHORT,
                              MarketState, PositionTarget, KILL, HALVE, OK)
from .expression import Expression
from .financing import FinancingModel
from .netting import net_targets
from .broker.margin_broker import MarginBroker


def _resolve_qty(pt: PositionTarget, price, capital) -> float | None:
    """§1.3 step-1a: weight -> signed shares at the SLEEVE's own capital."""
    if pt.side == FLAT:
        return 0.0
    if pt.qty is not None:
        return float(pt.signed_qty())
    if pt.weight is None:
        return 0.0
    if not (np.isfinite(price) and price > 0):
        return None
    mag = math.floor(abs(float(pt.weight)) * float(capital) / price)
    return float(-mag if pt.side == SHORT else mag)


def _scale_nonoption_legs(legs, factor):
    """Multiply each NON-OPTION leg's signed qty by `factor` (a HALVE de-rate,
    factor<1), flooring share magnitude / rounding contracts, leaving OPTION
    legs untouched (they de-rate through their own capital sizing). A leg that
    rounds to zero becomes FLAT so a held position is still driven off."""
    out = []
    for lg in legs:
        if lg.kind == OPTION or lg.side == FLAT or lg.qty is None:
            out.append(lg)
            continue
        signed = lg.signed_qty() * float(factor)
        if lg.kind == FUTURES:
            q = float(round(signed))
        else:
            q = float(math.copysign(math.floor(abs(signed)), signed))
        if abs(q) < 1e-12:
            out.append(PositionTarget(instrument=lg.instrument, side=FLAT,
                                      kind=lg.kind, qty=0.0,
                                      reason=f"[HALVE x{factor:.2f}->0] {lg.reason}",
                                      combo_id=lg.combo_id, meta=dict(lg.meta)))
            continue
        side = SHORT if q < 0 else LONG
        out.append(PositionTarget(instrument=lg.instrument, side=side,
                                  kind=lg.kind, qty=q,
                                  reason=f"[HALVE x{factor:.2f}] {lg.reason}",
                                  combo_id=lg.combo_id, meta=dict(lg.meta)))
    return out


class MarginPortfolioOrchestrator:
    def __init__(self, book_spec, broker: MarginBroker, books_root="ops/books/v2",
                 price_loader=None, costs=None, sleeves=None, events=None,
                 vol_target=None, expression=None, mark_fns=None,
                 greeks_fns=None, verbose=False, apply_risk_ladder=True,
                 readjud=None):
        self.book_spec = book_spec
        self.broker = broker                      # risk.apply_verdict scales this
        # apply_risk_ladder=True (default, SHIPPED): the frozen per-sleeve
        # HALVE/KILL/financing-SUSPEND ladder GOVERNS the book path every day.
        # False produces the counterfactual ALWAYS-LIVE arm (verdicts computed
        # for reporting but never acted on) — used only to A/B the kill-aware
        # vs always-live numbers (results/refine/OVERLAY_KILL_AWARE.md).
        self.apply_risk_ladder = bool(apply_risk_ladder)
        # OPERATIONAL re-adjudication (NOT a signal change): book_spec
        # ['risk_readjudication'] governs whether a KILLed sleeve may re-enable
        # after its counterfactual shadow recovers / N months pass, and whether
        # a HALVE restores. Absent / enabled=false -> the permanent-kill
        # CONSERVATIVE FLOOR (sticky for the run).
        self._readjud = (readjud if readjud is not None
                         else book_spec.get("risk_readjudication"))
        self.books_root = Path(books_root)
        self.books_root.mkdir(parents=True, exist_ok=True)
        self.price_loader = price_loader or local_panel_loader
        self.costs = costs if costs is not None else ops_common.load_costs()
        self.events = events
        self.verbose = bool(verbose)
        self.vol_target = vol_target
        self.expression = expression or Expression(
            {e["name"]: e["expression"] for e in book_spec.get("sleeves", [])
             if e.get("expression")})

        # The siloed shadow the FROZEN per-sleeve kills read. As-if-siloed
        # SIZING (v1 economics — unchanged) but financed at the A1 model, the
        # same per-leg FinancingModel the real MarginBook trades on. So the
        # frozen drawdown-kill AND financing-watch fire on the borrow economics
        # the book actually experiences, not the legacy flat-150bp v1 basis
        # (results/refine/OVERLAY_KILL_AWARE.md). Only the RATE changes; the
        # sizing stays siloed, so the netting-dilution reasoning is unaffected.
        self.shadow = Simulator(books_root=str(self.books_root / "_shadow"),
                                verbose=False, financing=FinancingModel())

        self.sleeves = {}
        self.capital = {}
        self.initial_capital = {}
        self.enabled = set()
        self.disabled = set()
        self.review_flags = set()
        # book-level per-sleeve risk de-rate: 1.0 normally, 0.5 while HALVEd.
        # risk.apply_verdict sets it; _assemble_book applies it BEFORE netting
        # so a HALVE genuinely halves the sleeve's contribution (incl. the
        # buy-and-hold overlay's short-IEF hedge) and the shared-IEF leg
        # re-nets against it. KILL is handled by exclusion from the book.
        self.risk_scale = {}
        self.kill_info = {}          # sleeve -> {"date": kill asof} (re-adjud)
        self.reenable_flags = {}     # sleeve -> "eligible" note (manual mode)
        self.mark_fns = {}
        self.greeks_fns = {}
        self.sleeve_costs = {}
        self.last_targets = {}
        self._last_verdicts = {}

        if sleeves is not None:
            _m, _g = mark_fns or {}, greeks_fns or {}
            for name, sleeve in sleeves.items():
                self._register(name, sleeve, sleeve.capital_usd, True,
                               _m.get(name), _g.get(name))
        else:
            for entry in book_spec.get("sleeves", []):
                self._register_from_entry(entry)

    # -- wiring -----------------------------------------------------------

    def _register_from_entry(self, entry):
        name = entry["name"]
        spec = entry.get("spec")
        if spec is None and entry.get("spec_path"):
            with open(entry["spec_path"]) as fh:
                spec = json.load(fh)
        # Forced-flow ZERO-CAPITAL paper trackers (build B2, 2026-07-26): a book
        # entry may point spec_path at the UNTOUCHED governance draft under
        # ops/books/v2/ff_sleeves/ (shape: sleeve_id + type
        # "paper_tracker_zero_capital", no "allocation" block). Wrap it on the
        # registry seam here so the draft stays the single source of truth, and
        # give the tracker its OWN measurement sub-ledger under
        # <books_root>/ff_state/<name>/ (per-sleeve attribution; a replay in a
        # temp books_root therefore never writes into ops/). Additive: any spec
        # that already carries an "allocation" block is untouched.
        if (isinstance(spec, dict) and "allocation" not in spec
                and spec.get("type") == "paper_tracker_zero_capital"):
            from .ff_sleeves import wrap_tracker_spec
            spec = wrap_tracker_spec(
                spec, state_dir=self.books_root / "ff_state" / name)
        capital = float(entry.get("capital_usd",
                                  spec.get("capital_usd", spec.get("book_usd"))))
        sleeve = registry.build_sleeve(spec, capital)
        self._register(name, sleeve, capital, entry.get("enabled", True),
                       entry.get("mark_fn"), entry.get("greeks_fn"),
                       entry.get("costs"))

    # -- F4 distressed caps (FORCED_FLOW_PREREG hard caps, build B2) -------

    def _f4_caps(self):
        """The book's declared distressed-sleeve caps, or None. Declared in
        book limits as `ff_f4_distressed_caps` and ENFORCED here for any
        sleeve whose name starts with an applies_to prefix (no such sleeve
        exists today — F4 failed the deployment gates; the caps guard any
        future wiring)."""
        caps = (self.book_spec.get("limits", {}) or {}).get("ff_f4_distressed_caps")
        return caps if isinstance(caps, dict) else None

    def _f4_applies(self, name) -> bool:
        caps = self._f4_caps()
        if not caps:
            return False
        prefixes = tuple(caps.get("applies_to_name_prefixes", []) or [])
        return bool(prefixes) and str(name).startswith(prefixes)

    def _register(self, name, sleeve, capital, enabled, mark_fn, greeks_fn=None,
                  costs=None):
        if self._f4_applies(name):
            caps = self._f4_caps()
            cap_max = float(caps.get("max_notional_usd", 25000))
            if float(capital) > cap_max:
                raise ValueError(
                    f"sleeve {name!r} matches the ff_f4_distressed_caps prefixes "
                    f"but carries capital_usd {float(capital):,.0f} > the "
                    f"pre-registered max_notional_usd {cap_max:,.0f} "
                    "(FORCED_FLOW_PREREG: distressed sleeve <=$25k notional, "
                    "<=$2.5k per position). Refusing to register.")
            self._check_f4_stress_budget_share(name, sleeve, caps)
        self.sleeves[name] = sleeve
        self.capital[name] = float(capital)
        self.initial_capital[name] = float(capital)
        self.risk_scale.setdefault(name, 1.0)
        self.mark_fns[name] = mark_fn
        self.greeks_fns[name] = greeks_fn
        sleeve_costs = costs if costs is not None else self.costs
        self.sleeve_costs[name] = sleeve_costs
        if enabled:
            self.enabled.add(name)
        # register with BOTH the shadow (per-sleeve kill) and the shared book
        self.shadow.register_sleeve(name, sleeve.alloc_type, sleeve.spec,
                                    sleeve_costs, capital, sleeve.instruments(),
                                    mark_fn=mark_fn, greeks_fn=greeks_fn)
        self.broker.register_sleeve(name, sleeve.alloc_type, sleeve.spec,
                                    sleeve_costs, capital, sleeve.instruments(),
                                    mark_fn=mark_fn, greeks_fn=greeks_fn)

    def _check_f4_stress_budget_share(self, name, sleeve, caps):
        """ENFORCE `max_stress_budget_share` at registration (2026-07-26
        integration fix — the cap was declared 'ENFORCED by the orchestrator'
        but nothing read it). A matching (F4/distressed) sleeve must DECLARE
        its measured worst-month loss (`spec['risk']['worst_month_usd']` or
        `spec['frozen']['backtest_worst_month_usd']`, in USD, sign ignored)
        and that magnitude must fit within share x the book stress budget
        (`vol_target.stress_drawdown_budget_usd`, falling back to
        `limits.book_worst_month_usd`). Missing declaration or missing budget
        => the cap is unverifiable => registration refused."""
        share = caps.get("max_stress_budget_share")
        if share is None:
            return
        budget = (self.book_spec.get("vol_target", {}) or {}).get(
            "stress_drawdown_budget_usd")
        if budget is None:
            budget = (self.book_spec.get("limits", {}) or {}).get(
                "book_worst_month_usd")
        if budget is None or not float(budget) > 0:
            raise ValueError(
                f"sleeve {name!r}: ff_f4_distressed_caps declares "
                f"max_stress_budget_share={share} but the book spec carries no "
                "positive stress budget (vol_target.stress_drawdown_budget_usd "
                "or limits.book_worst_month_usd) to take the share of. "
                "Refusing to register an unverifiable cap.")
        allowed = float(share) * float(budget)
        spec_d = getattr(sleeve, "spec", {}) or {}
        declared = (spec_d.get("risk", {}) or {}).get("worst_month_usd")
        if declared is None:
            declared = (spec_d.get("frozen", {}) or {}).get(
                "backtest_worst_month_usd")
        if declared is None:
            raise ValueError(
                f"sleeve {name!r} matches the ff_f4_distressed_caps prefixes "
                "but declares no measured worst-month loss "
                "(spec['risk']['worst_month_usd'] or "
                "spec['frozen']['backtest_worst_month_usd']), so the "
                f"pre-registered max_stress_budget_share={float(share):.0%} of "
                f"the ${float(budget):,.0f} book stress budget cannot be "
                "verified. Refusing to register (FORCED_FLOW_PREREG F4 hard "
                "caps).")
        if abs(float(declared)) > allowed:
            raise ValueError(
                f"sleeve {name!r} declares worst month "
                f"${abs(float(declared)):,.0f} > its "
                f"max_stress_budget_share allowance ${allowed:,.0f} "
                f"({float(share):.0%} of the ${float(budget):,.0f} book stress "
                "budget). Refusing to register (FORCED_FLOW_PREREG F4 hard "
                "caps).")

    # -- the daily step ---------------------------------------------------

    def _all_book_instruments(self):
        insts = set()
        for name in self.sleeves:
            insts.update(self.sleeves[name].instruments())
        return sorted(insts)

    def advance(self, asof, source="local") -> BookView:
        asof = pd.Timestamp(asof)
        sleeve_final = {}          # name -> resolved+expressed targets (for book)
        max_warmup = 0

        readjud_on = self._readjud_enabled()
        for name in list(self.sleeves):
            if name not in self.enabled:
                continue
            disabled = name in self.disabled
            # A disabled (KILLed) sleeve is normally excluded and its shadow is
            # flattened (the CONSERVATIVE FLOOR). With re-adjudication ON we keep
            # its shadow running at full size as the COUNTERFACTUAL that the
            # re-enable test reads, and never flatten it.
            if disabled and not readjud_on:
                self._flatten_disabled_shadow(name, asof)
                continue

            sleeve = self.sleeves[name]
            warm = sleeve.history_warmup_trading_days()
            max_warmup = max(max_warmup, warm)
            prices = self.price_loader(sleeve.instruments(), asof, warm)
            holdings = self.shadow.sync_positions(name)
            ms = MarketState(asof=asof, prices=prices, holdings=holdings,
                             mark_fn=self.mark_fns.get(name),
                             greeks_fn=self.greeks_fns.get(name),
                             events=self.events)
            targets = sleeve.target_positions(asof, ms)
            self.last_targets[name] = list(targets)

            # SHADOW advance (as-if-siloed v1 economics, full size — never
            # de-rated) -> the frozen kill logic + the re-adjudication signal.
            self.shadow.place_targets(name, targets, asof, ms)
            ledger = self.shadow.ledger(name)

            reenabled_now = False
            if disabled:
                # OPERATIONAL re-adjudication: eligible to bring the KILLed
                # sleeve back (returns at HALF size)?
                if self._readjud_reenable_ok(name, ledger, asof):
                    self.disabled.discard(name)
                    self.review_flags.add(name)
                    self.risk_scale[name] = 0.5
                    self.kill_info.pop(name, None)
                    disabled = False
                    reenabled_now = True
                    if self.verbose:
                        print(f"[book-v2] {name}: RE-ENABLED at 0.5x "
                              "(re-adjudication: shadow recovered)")
                else:
                    continue        # still KILLed -> excluded from the book

            verdict = risk.evaluate_sleeve(sleeve, ledger)
            self._last_verdicts[name] = {"status": verdict.status,
                                         "reasons": list(verdict.reasons)}
            if self.apply_risk_ladder and verdict.status in (KILL, HALVE):
                action = risk.apply_verdict(self, name, verdict)
                if self.verbose:
                    print(f"[book-v2] {name}: {verdict.status} — {action['effect']}")
                if verdict.status == KILL:
                    self.kill_info[name] = {"date": asof}
                    continue        # excluded from the book this day onward
            elif (self.apply_risk_ladder and verdict.status == OK
                  and not reenabled_now):
                # a recovered HALVE restores to full (re-adjudication). A sleeve
                # RE-ENABLED this same tick holds its 0.5x (phased re-entry) — it
                # only restores to full on a LATER day that clears the restore
                # threshold.
                self._readjud_restore(name, ledger)

            # RESOLVE (§1.3 step 1a) + EXPRESS (H3) for the shared book
            resolved = self._resolve(name, targets, prices, asof)
            expressed = self.expression.rewrite(name, resolved, asof,
                                                self.capital[name], ms)
            sleeve_final[name] = expressed

        # BOOK: net -> scale -> clamp -> commit
        combined = self.price_loader(self._all_book_instruments(), asof,
                                     max_warmup)
        final = self._assemble_book(sleeve_final, combined, asof)
        self.broker.commit(asof, final, combined)

        # track each sleeve's tagged holdings for the rollup (from the shadow)
        self.broker.set_sleeve_holdings(
            {n: {k: v for k, v in self.shadow.sync_positions(n).items()
                 if k != CASH} for n in self.sleeves})

        view = self.rollup(asof)
        self._persist(view)
        return view

    # -- OPERATIONAL re-adjudication (NOT a signal change) -----------------

    def _readjud_enabled(self) -> bool:
        r = self._readjud
        return bool(isinstance(r, dict) and r.get("enabled"))

    def _readjud_auto(self) -> bool:
        """True when eligibility should be ACTED on automatically. When
        `manual_confirmation_required` is set (the shipped default) the
        orchestrator only FLAGS eligibility and a human confirms — so the live
        book behaves like the CONSERVATIVE FLOOR until acted on; the re-adjudicated
        realistic path is measured with manual_confirmation_required=false."""
        r = self._readjud
        if not self._readjud_enabled():
            return False
        return not bool(r.get("manual_confirmation_required", True))

    @staticmethod
    def _shadow_dd(ledger) -> float:
        nav = ledger.nav_series()
        if nav is None or nav.empty:
            return 0.0
        return float((nav / nav.cummax() - 1.0).iloc[-1])

    def _readjud_reenable_ok(self, name, ledger, asof) -> bool:
        """A KILLed sleeve is eligible to re-enable (returns at HALF size) once
        its COUNTERFACTUAL (kill-blind) shadow drawdown has recovered above
        `kill_reenable_shadow_dd_pct` AND at least `kill_reenable_min_months`
        have elapsed since the KILL. Records an eligibility flag either way."""
        if not self._readjud_enabled():
            return False
        r = self._readjud
        ki = self.kill_info.get(name)
        if ki is None:
            return False
        dd = self._shadow_dd(ledger)
        months = ((asof.year - ki["date"].year) * 12
                  + (asof.month - ki["date"].month))
        dd_ok = dd > float(r.get("kill_reenable_shadow_dd_pct", -8.0)) / 100.0
        time_ok = months >= int(r.get("kill_reenable_min_months", 6))
        eligible = dd_ok and time_ok
        self.reenable_flags[name] = (
            f"eligible (shadow dd {dd:+.1%}, {months}mo since kill)" if eligible
            else f"not yet (shadow dd {dd:+.1%}, {months}mo)")
        return eligible and self._readjud_auto()

    def _readjud_restore(self, name, ledger):
        """A HALVEd sleeve restores to FULL size once its shadow drawdown has
        recovered above `halve_restore_shadow_dd_pct`."""
        if name not in self.review_flags or not self._readjud_enabled():
            return
        r = self._readjud
        dd = self._shadow_dd(ledger)
        if dd > float(r.get("halve_restore_shadow_dd_pct", -6.0)) / 100.0:
            self.reenable_flags[name] = f"halve-restore eligible (shadow dd {dd:+.1%})"
            if self._readjud_auto():
                self.risk_scale[name] = 1.0
                self.review_flags.discard(name)
                self.capital[name] = self.initial_capital[name]
                if self.verbose:
                    print(f"[book-v2] {name}: HALVE RESTORED to 1.0x "
                          f"(re-adjudication: shadow dd {dd:+.1%})")

    def _flatten_disabled_shadow(self, name, asof):
        held = {k: v for k, v in self.shadow.sync_positions(name).items()
                if k != CASH}
        if held:
            prices = self.price_loader(self.sleeves[name].instruments(), asof, 0)
            ms = MarketState(asof=asof, prices=prices, holdings=held)
            flats = [PositionTarget(instrument=i, side=FLAT, qty=0.0)
                     for i in held]
            self.shadow.place_targets(name, flats, asof, ms)

    def _resolve(self, name, targets, prices, asof):
        close = ops_common.wide(prices, "close")
        px_row = close.loc[close.index <= asof].iloc[-1] if len(close) else {}
        out = []
        # Size weight-expressed targets at the sleeve's INITIAL capital, not the
        # HALVE-mutated `capital[name]`. All book de-rating flows through the
        # single `risk_scale` factor applied in _assemble_book; sizing here at
        # initial capital keeps a HALVEd weight sleeve from being halved twice
        # (once in resolve, once by risk_scale).
        for t in targets:
            price = float(px_row.get(t.instrument, np.nan)) if len(close) else np.nan
            q = _resolve_qty(t, price, self.initial_capital[name])
            if q is None:
                continue
            if t.side == FLAT or q == 0.0:
                out.append(PositionTarget(instrument=t.instrument, side=FLAT,
                                          kind=t.kind, qty=0.0,
                                          reason=t.reason, combo_id=t.combo_id,
                                          meta=dict(t.meta)))
                continue
            side = SHORT if q < 0 else LONG
            out.append(PositionTarget(instrument=t.instrument, side=side,
                                      kind=t.kind, qty=float(q),
                                      reason=t.reason, combo_id=t.combo_id,
                                      meta=dict(t.meta)))
        return out

    # -- book assembly ----------------------------------------------------

    def _meta_lookup(self, sleeve_final):
        """instrument -> a representative meta (multiplier/margin/option desc),
        so netted legs can carry what the MarginBook needs to mark/size them."""
        meta = {}
        for legs in sleeve_final.values():
            for t in legs:
                if t.instrument not in meta and t.meta:
                    m = dict(t.meta)
                    m.setdefault("kind", t.kind)
                    meta[t.instrument] = m
        return meta

    def _assemble_book(self, sleeve_final, combined, asof):
        if not sleeve_final:
            return []
        # SCALE per-sleeve (H2 vol target) BEFORE netting, so a per-sleeve
        # leverage sub-cap (e.g. per_sleeve_max_leverage['eom_ief']=1.0 — the
        # prereg HARD RULE never to lever the fragile 2019+ EOM holdout beyond
        # its full-sample support) is honoured on that sleeve's OWN
        # contribution and is NOT re-levered by another sleeve's k after the
        # legs net together at book level.
        per_sleeve = dict((self.book_spec.get("vol_target", {}) or {})
                          .get("per_sleeve_max_leverage", {}) or {})
        k = (self.vol_target.scale_factor(self._core_nav_series())
             if self.vol_target is not None else 1.0)
        scaled_final = {}
        for name, legs in sleeve_final.items():
            cap = per_sleeve.get(name)
            k_s = k if cap is None else min(k, float(cap))
            # H2 vol-target scaling (OPTION legs never scale ABOVE 1.0).
            if self.vol_target is not None:
                legs = self.vol_target.apply(legs, k_s)
            # HALVE de-rate: shrink the sleeve's book footprint to risk_scale
            # (0.5 while HALVEd). Applied to NON-OPTION legs only — a short-vol
            # OPTION sleeve de-rates via its capital_usd->n_straddles sizing, so
            # touching it here would halve it twice. This is the step that makes
            # the frozen ladder GOVERN the netted book: the overlay's short IEF
            # is genuinely halved here BEFORE it nets against the EOM long.
            rs = float(self.risk_scale.get(name, 1.0))
            if rs != 1.0:
                legs = _scale_nonoption_legs(legs, rs)
            scaled_final[name] = legs

        # F4 distressed hard caps (FORCED_FLOW_PREREG): clamp any matching
        # sleeve's per-position and total notional BEFORE netting, so the caps
        # bind on the sleeve's OWN contribution. No-op when no sleeve matches
        # (today's case — no F4 sleeve deployed).
        f4_names = [n for n in scaled_final if self._f4_applies(n)]
        if f4_names:
            close = ops_common.wide(combined, "close")
            close_row = (close.loc[close.index <= asof].iloc[-1]
                         if len(close) else {})
            caps = self._f4_caps()
            for n in f4_names:
                scaled_final[n] = self._apply_f4_position_caps(
                    scaled_final[n], close_row, asof, caps, n)

        meta_lookup = self._meta_lookup(scaled_final)
        net_legs, _prov = net_targets(scaled_final)
        legs = []
        for leg in net_legs:
            meta = dict(meta_lookup.get(leg.instrument, {}))
            meta.setdefault("kind", leg.kind)
            if abs(leg.net_qty) < 1e-12:
                legs.append(PositionTarget(instrument=leg.instrument, side=FLAT,
                                           kind=leg.kind, qty=0.0, meta=meta))
                continue
            side = SHORT if leg.net_qty < 0 else LONG
            legs.append(PositionTarget(instrument=leg.instrument, side=side,
                                       kind=leg.kind, qty=float(leg.net_qty),
                                       combo_id=meta.get("combo_id"), meta=meta))
        # CLAMP (book gross-leverage ceiling) — only ever scales DOWN, so the
        # per-sleeve sub-cap applied above is preserved.
        legs = self._clamp_leverage(legs, combined, asof)
        return legs

    def _apply_f4_position_caps(self, legs, close_row, asof, caps, name):
        """FORCED_FLOW_PREREG distressed caps, enforced at book assembly:
        every leg's notional <= max_position_usd, and the sleeve's summed
        gross notional <= max_notional_usd. Scaling only ever shrinks
        (share magnitudes floored, contracts rounded, same conventions as
        the leverage clamp); a leg that scales to zero goes FLAT so a held
        position is still driven off."""
        max_pos = float(caps.get("max_position_usd", 2500))
        max_notional = float(caps.get("max_notional_usd", 25000))

        def _shrink(lg, factor, tag):
            signed = lg.signed_qty() * factor
            if lg.kind in (FUTURES, OPTION):
                q = float(round(signed))
            else:
                q = float(math.copysign(math.floor(abs(signed)), signed))
            if abs(q) < 1e-12:
                return PositionTarget(instrument=lg.instrument, side=FLAT,
                                      kind=lg.kind, qty=0.0,
                                      reason=f"[{tag}->0] {lg.reason}",
                                      combo_id=lg.combo_id, meta=dict(lg.meta))
            side = SHORT if q < 0 else LONG
            return PositionTarget(instrument=lg.instrument, side=side,
                                  kind=lg.kind, qty=q,
                                  reason=f"[{tag} x{factor:.3f}] {lg.reason}",
                                  combo_id=lg.combo_id, meta=dict(lg.meta))

        out = []
        for lg in legs:
            notional = self._leg_notional(lg, close_row, asof)
            if notional > max_pos > 0:
                lg = _shrink(lg, max_pos / notional, "f4-poscap")
            out.append(lg)
        gross = sum(self._leg_notional(lg, close_row, asof) for lg in out)
        if gross > max_notional > 0:
            factor = max_notional / gross
            out = [_shrink(lg, factor, "f4-cap") if lg.side != FLAT
                   and lg.qty is not None else lg for lg in out]
            if self.verbose:
                print(f"[book-v2] {pd.Timestamp(asof).date()}: {name} F4 gross "
                      f"${gross:,.0f} clamped to ${max_notional:,.0f}")
        return out

    def _leg_notional(self, leg, close_row, asof):
        q = leg.signed_qty()
        if q is None or leg.side == FLAT:
            return 0.0
        mult = float((leg.meta or {}).get("multiplier", 1.0) or 1.0)
        if leg.kind == FUTURES:
            fm = getattr(self.broker, "futures_returns", None)
            level = None
            if fm is not None:
                level = fm.marks_provider().mark_fn(asof, leg.instrument)
            if level is None:
                return 0.0
            return abs(q) * mult * float(level)
        px = float(close_row.get(leg.instrument, np.nan))
        if not np.isfinite(px):
            return 0.0
        return abs(q) * float(px) * mult

    def _clamp_leverage(self, legs, combined, asof):
        max_lev = float(self.book_spec.get("margin", {})
                        .get("max_gross_leverage",
                             getattr(self.broker, "max_gross_leverage", 3.0)))
        close = ops_common.wide(combined, "close")
        close_row = close.loc[close.index <= asof].iloc[-1] if len(close) else {}
        gross = sum(self._leg_notional(lg, close_row, asof) for lg in legs)
        equity = self._book_equity()
        if equity <= 0 or gross <= 0:
            return legs
        proj_lev = gross / equity
        if proj_lev <= max_lev + 1e-9:
            return legs
        factor = max_lev / proj_lev
        out = []
        for lg in legs:
            if lg.side == FLAT or lg.qty is None:
                out.append(lg)
                continue
            signed = lg.signed_qty() * factor
            if lg.kind in (FUTURES, OPTION):
                q = float(round(signed))
            else:
                q = float(math.copysign(math.floor(abs(signed)), signed))
            if abs(q) < 1e-12:
                out.append(PositionTarget(instrument=lg.instrument, side=FLAT,
                                          kind=lg.kind, qty=0.0,
                                          reason=f"[clamp->0] {lg.reason}",
                                          combo_id=lg.combo_id, meta=dict(lg.meta)))
                continue
            side = SHORT if q < 0 else LONG
            out.append(PositionTarget(instrument=lg.instrument, side=side,
                                      kind=lg.kind, qty=q,
                                      reason=f"[clamp x{factor:.3f}] {lg.reason}",
                                      combo_id=lg.combo_id, meta=dict(lg.meta)))
        if self.verbose:
            print(f"[book-v2] {asof.date()}: clamp gross lev "
                  f"{proj_lev:.2f}x -> {max_lev:.2f}x (x{factor:.3f})")
        return out

    def _book_nav_series(self):
        book = self.broker.ledger()
        return book.nav_series() if book is not None else pd.Series(dtype=float)

    def _core_equity_initial(self) -> float:
        """Initial equity of the REAL-CAPITAL (enabled, non-disabled) sleeves —
        the base the vol-target is meant to scale. Excludes inert paper-sleeve
        capital: FOMC/short-vol are registered so their capital funds the shared
        book, but they carry no risk here, so ~$120k sits as idle cash that must
        NOT dilute the realized-vol estimate."""
        core = sum(self.initial_capital[n] for n in self.sleeves
                   if n in self.enabled and n not in self.disabled)
        return float(core) if core > 0 else float(sum(self.initial_capital.values()))

    def _core_nav_series(self) -> pd.Series:
        """Book NAV re-based onto CORE equity for the vol-target. All book P&L
        comes from the core (enabled) legs — idle paper-sleeve cash neither
        earns nor loses here — so core_nav_t = core_equity_0 + (book_nav_t -
        book_nav_0). Measuring realized vol on this ~$180k core base instead of
        the whole-book ~$300k NAV removes the dilution that inflated k."""
        book = self._book_nav_series()
        if len(book) == 0:
            return book
        book0 = float(sum(self.initial_capital.values()))
        core0 = self._core_equity_initial()
        return core0 + (book - book0)

    def _book_equity(self):
        s = self._book_nav_series()
        if len(s):
            return float(s.iloc[-1])
        return float(sum(self.initial_capital.values()))

    # -- rollup -----------------------------------------------------------

    def rollup(self, asof=None) -> BookView:
        book = self.broker.ledger()
        book_nav = self._book_equity()
        book_pnl = book_nav - float(sum(self.initial_capital.values()))
        gross, net = book.leverage() if hasattr(book, "leverage") else (0.0, 0.0)
        margin_util = book.margin_utilization() if hasattr(book, "margin_utilization") else np.nan
        book_cash = float(book.cash)
        fin = 0.0
        if not book.nav.empty and "financing_usd" in book.nav.columns:
            fin = float(book.nav.sort_values("date")["financing_usd"].iloc[-1])
        turnover = 0.0
        if not book.nav.empty and "traded_usd" in book.nav.columns:
            turnover = float(book.nav.sort_values("date")["traded_usd"].iloc[-1])

        sleeve_views = {}
        for name in self.sleeves:
            lg = self.shadow.ledger(name)
            snav = float(lg.nav_series().iloc[-1]) if not lg.nav.empty else np.nan
            v = self._last_verdicts.get(name, {"status": OK, "reasons": []})
            sleeve_views[name] = {
                "shadow_nav": snav, "capital_usd": self.capital[name],
                "enabled": name in self.enabled and name not in self.disabled,
                "disabled": name in self.disabled,
                "review_flag": name in self.review_flags,
                "risk_scale": float(self.risk_scale.get(name, 1.0)),
                "readjud_flag": self.reenable_flags.get(name),
                "risk_verdict": v}

        gross_notional = gross * book_nav
        limits = risk.check_book_limits(self.book_spec, sleeve_views,
                                        book_nav, gross_notional,
                                        {"_book": book})
        view = BookView(asof=asof, book_nav=book_nav, book_pnl=book_pnl,
                        sleeves=sleeve_views, book_cash=book_cash,
                        gross_exposure=gross_notional,
                        net_exposure=net * book_nav, limits=limits,
                        book_turnover=turnover)
        # v2 extras (attached; consumed by _persist and the runner banner)
        view.margin_util = float(margin_util) if margin_util == margin_util else None
        view.gross_leverage = float(gross)
        view.net_leverage = float(net)
        view.financing_usd = fin
        view.margin_req = book.margin_requirement() if hasattr(book, "margin_requirement") else None
        return view

    def _persist(self, view):
        path = self.books_root / "book_status_v2.json"
        payload = view.to_json()
        payload.update({
            "margin_util": getattr(view, "margin_util", None),
            "gross_leverage": getattr(view, "gross_leverage", None),
            "net_leverage": getattr(view, "net_leverage", None),
            "financing_usd": getattr(view, "financing_usd", None),
            "margin_req": getattr(view, "margin_req", None)})
        with open(path, "w") as fh:
            json.dump(payload, fh, indent=2, default=str)
