"""H1 — the ONE shared-collateral margin account for book v2.

REFINE_ARCHITECTURE.md §1. v1 is N siloed sub-ledgers whose "book cash" is a
reporting SUM (`portfolio.py`), so the credit-base holding finances nothing.
v2 puts every sleeve's legs into ONE `MarginBook`: the credit base is the
collateral, and EOM / FOMC / overlay / short-vol are timing overlays funded
from the same margin. Financing is charged ONCE on the single negative-cash
balance (A1 `margin_debit`), not five times.

`MarginBook` is a thin subclass of the v1 `DerivativesLedger`. It does NOT copy
`advance()` — it overrides only the Edit-2 seams (§0.2) plus the two methods
that were already methods (`_multiplier`, `_fill_order`) and `_mark`:

  * `_multiplier`        — FUTURES carry meta['multiplier'] (ZN/ZF/ZB = 1000).
  * `_mark`              — FUTURES priced off the roll-spliced settle level
                           (FuturesMarks), never the ETF close store.
  * `_fill_order`        — FUTURES cost NO notional cash on open; only realized
                           P&L of the CLOSED portion flows to cash on a reduce,
                           so NAV is continuous across every futures fill.
  * `_position_value`    — FUTURES contributes VARIATION only, q*mult*(mark-
                           entry), never its settle LEVEL (no phantom notional).
  * `_accrue_financing`  — per-leg A1 dispatch: margin_debit (all-in) on |neg
                           cash|, base credited on positive cash, and only the
                           FEE SPREAD over base charged on short ETF MV / posted
                           futures margin (base handled once by the cash leg, so
                           a cash-collateralized short nets to its ~50bp fee —
                           ties to credit_hedged.py). Delegates to the base
                           ledger, which now implements exactly this.
  * `_margin_and_rollup` — margin_req (a pluggable MarginModel), collateral
                           equity, margin_util, gross/net leverage into the
                           widened NAV columns; a gross-leverage post-condition.

Nothing here reads or moves a frozen signal — it changes only collateral,
financing realism, and the futures expression of an already-emitted target.
"""

from __future__ import annotations

import json

import numpy as np

from ops.ledger import CASH
from ..exec_ledger import DerivativesLedger, D_NAV_COLUMNS
from ..sleeve import (ETF, EQUITY, FLAT, FUTURES, LONG, OPTION, SHORT,
                      PositionTarget)
from .financing import FinancingModel
from .futures import load_futures_specs


# ==========================================================================
# Pluggable margin requirement
# ==========================================================================

class MarginModel:
    """Book-level margin requirement in dollars. `book_spec['margin']['model']`
    selects the implementation; Reg-T is the conservative floor used for the
    deployable point, portfolio_margin is the reported upside."""

    def requirement(self, positions: dict, marks: dict, meta: dict) -> float:
        raise NotImplementedError


class RegTMargin(MarginModel):
    """A Reg-T / house-rule floor. Positions that don't net across sleeves:

      long ETF/EQUITY   house_factor * MV        (25% house on IG/Treasury)
      short ETF/EQUITY  1.5 * MV                 (Reg-T short)
      short OPTION      premium + 20% notional   (naked-option stress proxy)
      long OPTION       premium (full)
      FUTURES           initial_margin_usd * |contracts|
    """

    def __init__(self, house_factor: float = 0.25,
                 short_factor: float = 1.5,
                 option_stress: float = 0.20):
        self.house_factor = float(house_factor)
        self.short_factor = float(short_factor)
        self.option_stress = float(option_stress)

    def requirement(self, positions, marks, meta) -> float:
        req = 0.0
        for inst, q in positions.items():
            if inst == CASH:
                continue
            q = float(q)
            if abs(q) < 1e-12:
                continue
            m = meta.get(inst, {}) or {}
            kind = m.get("kind", ETF)
            mult = float(m.get("multiplier", 1.0) or 1.0)
            px = float(marks.get(inst, np.nan))
            if kind == FUTURES:
                im = float(m.get("initial_margin_usd", 0.0) or 0.0)
                req += im * abs(q)
                continue
            if not np.isfinite(px):
                continue
            mv = abs(q) * px * mult
            if kind == OPTION:
                if q < 0:
                    # premium held as credit + a stress bump on the notional
                    strike = float(m.get("strike", px) or px)
                    notional = strike * mult * abs(q)
                    req += mv + self.option_stress * notional
                else:
                    req += mv
            else:  # ETF / EQUITY
                req += (self.short_factor if q < 0 else self.house_factor) * mv
        return float(req)


class PortfolioMargin(MarginModel):
    """A stressed-loss grid over the WHOLE book. The requirement is the worst
    aggregate loss under a joint (rates, credit, equity) shock. Because the
    duration bucket is netted BEFORE the shock, an EOM-long vs overlay-short
    duration offset cross-margins — the capital efficiency Reg-T cannot see
    (H1). Instruments are classified by a small frozen map; the shocks are the
    book-spec knobs (defaults are a defensible 1-day stress)."""

    # effective duration (years) used to turn a rate shock into a $ loss
    DURATION_YEARS = {"IEF": 7.1, "TLT": 17.0, "SHY": 1.9, "BIL": 0.1,
                      "ZN": 7.1, "ZF": 4.5, "ZB": 17.0, "LQD": 8.5}
    # credit-spread DV01 proxy (years of spread duration) for credit ETFs
    CREDIT_DURATION = {"LQD": 8.5, "HYG": 3.8, "JNK": 3.8, "ANGL": 4.2,
                       "FALN": 4.4}

    def __init__(self, rate_shock_bp: float = 100.0,
                 credit_shock_bp: float = 150.0,
                 equity_shock_pct: float = 20.0,
                 floor_frac: float = 0.05):
        self.rate_shock_bp = float(rate_shock_bp)
        self.credit_shock_bp = float(credit_shock_bp)
        self.equity_shock_pct = float(equity_shock_pct)
        self.floor_frac = float(floor_frac)

    def _signed_notional(self, inst, q, marks, meta):
        m = meta.get(inst, {}) or {}
        kind = m.get("kind", ETF)
        mult = float(m.get("multiplier", 1.0) or 1.0)
        px = float(marks.get(inst, np.nan))
        if not np.isfinite(px):
            return 0.0, kind, m
        return float(q) * px * mult, kind, m

    def requirement(self, positions, marks, meta) -> float:
        rate_dv01 = 0.0        # signed $/bp of the netted duration bucket
        credit_dv01 = 0.0      # signed $/bp of the credit bucket
        equity_notional = 0.0  # signed equity/option delta notional
        gross_notional = 0.0
        for inst, q in positions.items():
            if inst == CASH or abs(float(q)) < 1e-12:
                continue
            notional, kind, _m = self._signed_notional(inst, q, marks, meta)
            gross_notional += abs(notional)
            dur = self.DURATION_YEARS.get(inst)
            if dur is not None:
                rate_dv01 += notional * dur * 1e-4
            cdur = self.CREDIT_DURATION.get(inst)
            if cdur is not None:
                credit_dv01 += notional * cdur * 1e-4
            if inst in ("SPY", "QQQ") or kind in (OPTION, EQUITY):
                equity_notional += notional
        # worst-case: shock each bucket in its adverse direction (abs of the
        # netted exposure — the book is hurt by the sign it is net exposed to)
        rate_loss = abs(rate_dv01) * self.rate_shock_bp
        credit_loss = abs(credit_dv01) * self.credit_shock_bp
        equity_loss = abs(equity_notional) * self.equity_shock_pct / 100.0
        stress = rate_loss + credit_loss + equity_loss
        # never below a small fraction of gross (a hard PB floor)
        return float(max(stress, self.floor_frac * gross_notional))


def build_margin_model(spec_block: dict | None) -> MarginModel:
    """Select + configure a MarginModel from `book_spec['margin']`."""
    block = dict(spec_block or {})
    model = str(block.get("model", "reg_t")).lower()
    if model in ("portfolio", "portfolio_margin", "pm"):
        return PortfolioMargin(
            rate_shock_bp=block.get("rate_shock_bp", 100.0),
            credit_shock_bp=block.get("credit_shock_bp", 150.0),
            equity_shock_pct=block.get("equity_shock_pct", 20.0))
    return RegTMargin(house_factor=block.get("house_factor", 0.25))


# ==========================================================================
# The shared account
# ==========================================================================

class MarginBook(DerivativesLedger):
    """One shared-collateral account for the whole v2 book. Every sleeve's legs
    live here, tagged by meta['sleeve']. Cash is a single pool; financing is
    charged once on the single negative balance at the A1 rate."""

    _NAV_COLUMNS = D_NAV_COLUMNS + [
        "margin_req", "collateral_equity", "margin_util",
        "gross_leverage", "net_leverage"]

    def __init__(self, state_dir, margin_model: MarginModel = None,
                 financing: FinancingModel = None, futures_marks=None,
                 futures_specs=None, option_half_spread_usd: float = 0.02,
                 max_gross_leverage: float = 3.0, verbose: bool = False):
        self.margin_model = margin_model or RegTMargin()
        self.financing = financing if financing is not None else FinancingModel()
        self.futures_marks = futures_marks
        self.futures_specs = futures_specs or load_futures_specs()
        self.max_gross_leverage = float(max_gross_leverage)
        self.verbose = bool(verbose)
        # futures entry-level bookkeeping (variation P&L needs a per-leg entry).
        self._fut_entry: dict[str, float] = {}
        self._fut_qty: dict[str, float] = {}
        # rollup values stashed by _margin_and_rollup for the snapshot API
        self._last_margin_req = 0.0
        self._last_gross_lev = 0.0
        self._last_net_lev = 0.0
        super().__init__(state_dir, option_half_spread_usd=option_half_spread_usd)
        self._recover_futures_state()

    # -- futures state recovery/persistence -------------------------------

    def _recover_futures_state(self):
        if self.positions.empty:
            return
        last = self.positions["date"].max()
        snap = self.positions[(self.positions["date"] == last)
                              & (self.positions.get("kind") == FUTURES)]
        for _, r in snap.iterrows():
            inst = r["instrument"]
            q = float(r["qty"])
            self._fut_qty[inst] = q
            j = r.get("meta_json")
            if isinstance(j, str) and j and j != "nan":
                try:
                    e = json.loads(j).get("entry_level")
                    if e is not None:
                        self._fut_entry[inst] = float(e)
                except (ValueError, TypeError):
                    pass

    def save(self):
        # stamp the current futures entry level onto the latest position rows so
        # a restart recovers it (leg_meta is rebuilt each decision day and would
        # otherwise lose it).
        if not self.positions.empty and self._fut_entry:
            last = self.positions["date"].max()
            for idx in self.positions.index[
                    (self.positions["date"] == last)
                    & (self.positions["kind"] == FUTURES)]:
                inst = self.positions.at[idx, "instrument"]
                j = self.positions.at[idx, "meta_json"]
                meta = {}
                if isinstance(j, str) and j and j != "nan":
                    try:
                        meta = json.loads(j)
                    except (ValueError, TypeError):
                        meta = {}
                if inst in self._fut_entry:
                    meta["entry_level"] = float(self._fut_entry[inst])
                    self.positions.at[idx, "meta_json"] = json.dumps(meta)
        super().save()

    # -- marks / multiplier -----------------------------------------------

    def _multiplier(self, instrument, kind, meta):
        if kind == FUTURES:
            m = meta or self.leg_meta.get(instrument, {})
            mult = float((m or {}).get("multiplier", 0.0) or 0.0)
            if mult <= 0 and instrument in self.futures_specs:
                mult = self.futures_specs[instrument].multiplier
            return mult or 1000.0
        return super()._multiplier(instrument, kind, meta)

    def _mark(self, instrument, kind, asof, close_row, mark_fn):
        if kind == FUTURES:
            if self.futures_marks is None:
                return None
            px = self.futures_marks.mark_fn(asof, instrument)
            return None if px is None or not np.isfinite(px) else float(px)
        return super()._mark(instrument, kind, asof, close_row, mark_fn)

    def _futures_half_spread_bp(self, inst, costs):
        if inst in self.futures_specs:
            return float(self.futures_specs[inst].half_spread_bp)
        row = (costs.get("tickers", {}) or {}).get(inst, {})
        return float(row.get("half_spread_bp", 0.0))

    # -- fills -------------------------------------------------------------

    def _fill_order(self, order, d, close, vol, vol_bp, costs, mark_fn):
        kind = order.get("kind", ETF)
        if kind != FUTURES:
            return super()._fill_order(order, d, close, vol, vol_bp, costs, mark_fn)

        inst = order["instrument"]
        delta = float(order["delta_qty"])
        if delta == 0:
            return None
        mult = self._multiplier(inst, FUTURES, self.leg_meta.get(inst))
        level = self._mark(inst, FUTURES, d, close, mark_fn)
        if level is None or not np.isfinite(level):
            # A REQUIRED futures leg (delta != 0) cannot be marked -> HALT the
            # book. The v1 'skipped' path (return None) would silently drop a
            # hedge / EOM leg with no error, leaving the book wrongly
            # un-hedged and mis-levered off stale futures data. Turn the silent
            # skip into a loud, resumable halt (staleness detail if available).
            detail = ""
            if self.futures_marks is not None:
                try:
                    self.futures_marks.assert_fresh(d, inst)
                except Exception as exc:                       # noqa: BLE001
                    detail = f" {exc}"
            dd = d.date() if hasattr(d, "date") else d
            raise RuntimeError(
                f"MarginBook: cannot mark required FUTURES leg {inst!r} at {dd} "
                f"(delta={delta:+g}) — refusing to book a day a required leg "
                f"cannot be priced (silent-skip -> hard halt).{detail}")

        q0 = float(self._fut_qty.get(inst, 0.0))
        e0 = float(self._fut_entry.get(inst, level))
        new_q = q0 + delta
        realized = 0.0
        if q0 == 0.0 or (np.sign(delta) == np.sign(q0)):
            # open or add -> weighted-average entry, no realized P&L
            e_new = level if new_q == 0.0 else (q0 * e0 + delta * level) / new_q
        else:
            # reduce/close/flip -> realize the closed portion into cash
            closed = np.sign(q0) * min(abs(delta), abs(q0))
            realized = closed * mult * (level - e0)
            e_new = level if (abs(delta) > abs(q0)) else e0
            if abs(new_q) < 1e-12:
                e_new = level
        self._fut_qty[inst] = new_q
        self._fut_entry[inst] = float(e_new)

        hs_bp = self._futures_half_spread_bp(inst, costs)
        cost_usd = abs(delta) * mult * level * hs_bp / 1e4
        notional = abs(delta) * mult * level
        # cash moves only by realized P&L, net of the trading cost. No notional
        # outlay on a future (initial margin is posted, tracked in margin_req).
        cash_delta = -(realized - cost_usd)
        row = {"fill_date": d,
               "decision_date": order["decision_date"],
               "instrument": inst, "kind": FUTURES,
               "side": "BUY" if delta > 0 else "SELL",
               "qty": abs(delta), "multiplier": mult,
               "decision_price": float(order.get("decision_price", np.nan)),
               "close_price": level, "fill_price": level,
               "cost_usd": cost_usd, "notional_usd": notional,
               "combo_id": order.get("combo_id"),
               "reason": order.get("reason", "")}
        return {"signed_qty": delta, "cash_delta": cash_delta,
                "cost_usd": cost_usd, "notional_usd": notional, "row": row}

    # -- Edit-2 seams ------------------------------------------------------

    def _position_value(self, inst, kind, q, mark, mult, meta):
        if kind == FUTURES:
            entry = float(self._fut_entry.get(inst, mark))
            return float(q) * mult * (mark - entry)     # variation only
        return super()._position_value(inst, kind, q, mark, mult, meta)

    def _posted_futures_margin(self, pos, kinds):
        posted = 0.0
        for inst, q in pos.items():
            if kinds.get(inst) == FUTURES:
                m = self.leg_meta.get(inst, {})
                im = float(m.get("initial_margin_usd", 0.0) or 0.0)
                if im <= 0 and inst in self.futures_specs:
                    im = self.futures_specs[inst].initial_margin_usd
                posted += im * abs(float(q))
        return posted

    def _accrue_financing(self, asof, pos, marks, kinds, cash, short_mv,
                          neg_cash, costs, fin_daily):
        # Identical A1 economics to DerivativesLedger._accrue_financing: base
        # credited on positive cash, short/futures charged only their fee SPREAD
        # over base, margin_debit all-in on borrowed cash. self.financing is
        # never None here and self._posted_futures_margin already resolves to
        # this class's futures_specs-aware override, so delegating to super keeps
        # the shared-book and per-sleeve-shadow paths identical by construction.
        return super()._accrue_financing(asof, pos, marks, kinds, cash, short_mv,
                                         neg_cash, costs, fin_daily)

    def _economic_mv(self, pos, marks, kinds):
        """Signed economic market value per leg (futures use |contracts|*mult*
        level, NOT variation) — the basis for gross/net leverage and margin."""
        signed = {}
        for inst, q in pos.items():
            mark = marks.get(inst)
            if mark is None or not np.isfinite(mark):
                signed[inst] = 0.0
                continue
            mult = kinds.get(inst) and self._multiplier(inst, kinds[inst],
                                                        self.leg_meta.get(inst))
            signed[inst] = float(q) * float(mark) * float(mult or 1.0)
        return signed

    def _margin_and_rollup(self, asof, pos, marks, kinds, cash, invested,
                           nav_today, short_mv, neg_cash, fin_extra):
        econ = self._economic_mv(pos, marks, kinds)
        gross = sum(abs(v) for v in econ.values())
        net = sum(econ.values())
        equity = float(nav_today)
        meta = {inst: {**(self.leg_meta.get(inst, {}) or {}),
                       "kind": kinds.get(inst, ETF),
                       "multiplier": self._multiplier(inst, kinds.get(inst, ETF),
                                                      self.leg_meta.get(inst))}
                for inst in pos}
        margin_req = self.margin_model.requirement(pos, marks, meta)
        gross_lev = gross / equity if equity else np.nan
        net_lev = net / equity if equity else np.nan
        self._last_margin_req = float(margin_req)
        self._last_gross_lev = float(gross_lev) if np.isfinite(gross_lev) else 0.0
        self._last_net_lev = float(net_lev) if np.isfinite(net_lev) else 0.0
        if (np.isfinite(gross_lev) and gross_lev
                > self.max_gross_leverage + 1e-6):
            # clamped upstream (§1.3); a breach here is a bug, logged loudly.
            print(f"[margin-book] WARNING {asof.date() if hasattr(asof,'date') else asof}: "
                  f"gross leverage {gross_lev:.2f}x exceeds ceiling "
                  f"{self.max_gross_leverage:.2f}x — orchestrator clamp missed.")
        return {"margin": short_mv,
                "margin_req": margin_req,
                "collateral_equity": equity,
                "margin_util": (margin_req / equity) if equity else np.nan,
                "gross_leverage": gross_lev,
                "net_leverage": net_lev}

    # -- reporting API -----------------------------------------------------

    def collateral_equity(self) -> float:
        return float(self.nav_series().iloc[-1]) if not self.nav.empty else 0.0

    def margin_requirement(self) -> float:
        if self.nav.empty or "margin_req" not in self.nav.columns:
            return self._last_margin_req
        v = self.nav.sort_values("date")["margin_req"].iloc[-1]
        return float(v) if v == v else self._last_margin_req

    def margin_utilization(self) -> float:
        eq = self.collateral_equity()
        return self.margin_requirement() / eq if eq else np.nan

    def leverage(self) -> tuple[float, float]:
        if self.nav.empty or "gross_leverage" not in self.nav.columns:
            return self._last_gross_lev, self._last_net_lev
        last = self.nav.sort_values("date").iloc[-1]
        g = float(last["gross_leverage"]) if last["gross_leverage"] == last["gross_leverage"] else 0.0
        n = float(last["net_leverage"]) if last["net_leverage"] == last["net_leverage"] else 0.0
        return g, n
