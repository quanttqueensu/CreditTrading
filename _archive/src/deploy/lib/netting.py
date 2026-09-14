"""H4 — book-level netting of shared duration legs (REFINE_ARCHITECTURE §4).

v1 runs the EOM sleeve (long IEF) and the duration-hedged overlay (short IEF)
in SEPARATE sub-ledgers: on every EOM window day the book is simultaneously
long and short the same instrument, paying stock-borrow financing on the full
overlay short while an equal-and-opposite long sits in a sibling ledger — the
integration review's shared-IEF cross-contamination. v2 nets the legs by
design at book level, while keeping every sleeve's FROZEN kill logic intact.

Three pieces, per the architecture:

  net_targets(sleeve_targets)  — sum same-instrument, same-kind SIGNED QTYS
      across sleeves into one net book leg, retaining each sleeve's
      contributor share. PRECONDITION: every incoming target is qty-expressed
      (the orchestrator resolves weights -> signed shares upstream, §1.3 step
      1a). Options (distinct premium legs) never net across sleeves.

  SleeveAttribution — the book HOLDS the net; each SLEEVE still needs its own
      P&L so its frozen kill logic fires on the sleeve, not the net. The
      attribution maintains a SHADOW per-sleeve NAV in strict AS-IF-SILOED
      SIZING: each sleeve's shadow is charged the trade cost and the
      short-borrow financing on its OWN (un-netted) short MV. As of the A1
      refine cycle the borrow is priced at the A1 FinancingModel — the SAME
      per-leg curve the real MarginBook trades on (short_etf / margin_debit
      spreads over daily SOFR), NOT the legacy flat 150bp v1 basis. Only the
      financing RATE moved to A1; the SIZING stays as-if-siloed (unchanged), so
      every netting-dilution argument below is untouched. The whole netting
      saving (financing + turnover cost) is booked to an explicit book-level
      `netting_benefit` line, NEVER smeared into a sleeve's shadow. Rationale
      (risk-conservative, and the reason the frozen kills are provably intact):

        * the overlay's frozen financing-watch (realized short-financing rate
          > 300 bp/yr -> SUSPEND) is a BORROW-RATE regime detector. If the
          netting benefit were attributed into the overlay's shadow, its
          realized `financing_usd / margin` rate would be diluted by however
          much the EOM long happened to offset that month — a genuinely
          300bp+ borrow regime could be masked. As-if-siloed SIZING at the A1
          rate reproduces the overlay's true borrow economics (what the book
          actually pays), so the frozen watch fires on the real regime, not a
          netting-diluted one and not the stale 150bp basis.
        * likewise the frozen drawdown-kill reads a shadow NAV drawn down by
          the A1 financing the book genuinely experiences, not an over-penalized
          150bp NAV the book never trades on.
        * likewise the EOM trailing-24-window mean sees exactly its own
          siloed window economics.

      Reconciliation identity (asserted to the penny by `reconcile()`):

          book_pnl(day) = Σ_sleeves shadow_pnl(day) + netting_benefit(day)

      because price P&L is linear in qty (Σ contributor qtys == net qty) and
      the benefit is defined as (Σ siloed costs − net cost) + (Σ siloed
      financing − net financing).

  ShadowLedgerView — the canonicalizing adapter: exposes `nav_series()`,
      `daily_returns()`, `trades`, `positions`, `nav` — the exact surface the
      frozen `risk_check` implementations read (EomDurationSleeve filters
      trades for SELL fills of its instrument; DurationHedgedOverlaySleeve
      reads nav.financing_usd / nav.margin and positions closes). Executed
      instruments can be relabeled to the sleeve's SIGNAL instrument (e.g.
      ZN -> IEF under futures expression) via `canonical_map`, so the frozen
      symbol-keyed kill logic never goes dark.

No frozen signal parameter is read, set, or moved here. This module changes
EXPRESSION of the book only (netting), never a signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..sleeve import FLAT, LONG, OPTION, SHORT, PositionTarget

RECONCILE_TOL_USD = 0.005     # "to the penny"


# ===========================================================================
# net_targets — the netting itself
# ===========================================================================

@dataclass
class NettedLeg:
    """One net book leg: the signed sum of every sleeve's resolved qty."""

    instrument: str
    net_qty: float                    # signed SUM of resolved contributor qtys
    contributors: dict                # sleeve_name -> signed qty it asked for
    kind: str                         # ETF | EQUITY | FUTURES | OPTION

    @property
    def gross_qty(self) -> float:
        return float(sum(abs(q) for q in self.contributors.values()))

    @property
    def offset_qty(self) -> float:
        """Shares/contracts that cancel across sleeves (the netting)."""
        return self.gross_qty - abs(self.net_qty)


def _resolved_signed_qty(sleeve: str, pt: PositionTarget) -> float:
    """Signed qty of a resolved target. Raises on a weight-expressed target —
    the §1.3 step-1a precondition (weights are resolved to signed shares with
    the SLEEVE's own capital upstream; a weight cannot be summed)."""
    if pt.weight is not None and pt.side != FLAT:
        raise ValueError(
            f"net_targets precondition violated: sleeve {sleeve!r} target for "
            f"{pt.instrument!r} is weight-expressed (weight={pt.weight}). "
            "Resolve weights to signed qty at the sleeve's own capital before "
            "netting (REFINE_ARCHITECTURE §1.3 step 1a).")
    q = pt.signed_qty()
    return 0.0 if q is None else float(q)


def net_targets(sleeve_targets: dict[str, list[PositionTarget]]
                ) -> tuple[list[NettedLeg], dict]:
    """Sum same-instrument, same-kind legs across sleeves into net book legs.

    OPTION legs never net across sleeves (each is a distinct premium leg with
    its own combo semantics); they pass through one NettedLeg per (sleeve,
    leg-id). FLAT targets contribute 0 but keep the instrument present so a
    held position is still driven flat downstream.

    Returns (netted_legs, provenance) where provenance[instrument] carries
    contributors / gross_qty / net_qty / offset_qty for reporting.
    """
    acc: dict[tuple, NettedLeg] = {}
    for sleeve, targets in sleeve_targets.items():
        for pt in targets:
            q = _resolved_signed_qty(sleeve, pt)
            if pt.kind == OPTION:
                key = (pt.instrument, pt.kind, sleeve)      # never nets
            else:
                key = (pt.instrument, pt.kind)
            leg = acc.get(key)
            if leg is None:
                leg = NettedLeg(instrument=pt.instrument, net_qty=0.0,
                                contributors={}, kind=pt.kind)
                acc[key] = leg
            leg.contributors[sleeve] = leg.contributors.get(sleeve, 0.0) + q
            leg.net_qty += q

    legs = list(acc.values())
    provenance = {}
    for leg in legs:
        p = provenance.setdefault(leg.instrument, {
            "kind": leg.kind, "contributors": {}, "gross_qty": 0.0,
            "net_qty": 0.0, "offset_qty": 0.0})
        for s, q in leg.contributors.items():
            p["contributors"][s] = p["contributors"].get(s, 0.0) + q
        p["gross_qty"] += leg.gross_qty
        p["net_qty"] += leg.net_qty
        p["offset_qty"] += leg.offset_qty
    return legs, provenance


# ===========================================================================
# ShadowLedgerView — the surface the frozen risk_check implementations read
# ===========================================================================

class ShadowLedgerView:
    """Per-sleeve as-if-siloed ledger view built by SleeveAttribution.

    Exposes exactly what the frozen `risk_check`s consume:
      nav            DataFrame[date, nav, cash, financing_usd, margin,
                               cost_usd, traded_usd, daily_return]
      trades         DataFrame[decision_date, ticker, instrument, side,
                               delta_shares, fill_price, fill_date]
      positions      DataFrame[date, instrument, ticker, qty, close,
                               market_value]
      nav_series()   date-indexed float Series of nav
      daily_returns() date-indexed float Series (nav pct change)
    """

    def __init__(self, sleeve: str, nav: pd.DataFrame, trades: pd.DataFrame,
                 positions: pd.DataFrame):
        self.sleeve = sleeve
        self.nav = nav
        self.trades = trades
        self.positions = positions

    def nav_series(self) -> pd.Series:
        if self.nav.empty:
            return pd.Series(dtype=float)
        return (self.nav.sort_values("date").set_index("date")["nav"]
                .astype(float))

    def daily_returns(self) -> pd.Series:
        s = self.nav_series()
        if s.empty:
            return pd.Series(dtype=float)
        return s.pct_change().dropna()


# ===========================================================================
# SleeveAttribution — shadow per-sleeve economics + the explicit benefit line
# ===========================================================================

class SleeveAttribution:
    """Accumulates the netted book's daily activity into (a) as-if-siloed
    shadow ledgers per sleeve and (b) an explicit book-level netting-benefit
    line, reconciling to the book NAV to the penny.

    Parameters
    ----------
    capitals : {sleeve: starting capital USD}. Book start NAV = their sum.
    canonical_map : optional {sleeve: {executed_instrument: signal_instrument}}
        relabel map for the canonicalizing view (ZN -> IEF under futures
        expression). Identity when omitted (ETF expression, this cycle's H4).
    """

    def __init__(self, capitals: dict[str, float],
                 canonical_map: dict[str, dict] | None = None):
        if not capitals:
            raise ValueError("SleeveAttribution needs at least one sleeve")
        self.capitals = {s: float(c) for s, c in capitals.items()}
        self.canonical_map = canonical_map or {}
        self._nav = {s: float(c) for s, c in self.capitals.items()}
        self._book_nav = float(sum(self.capitals.values()))
        self._rows: dict[str, list] = {s: [] for s in capitals}
        self._trades: dict[str, list] = {s: [] for s in capitals}
        self._positions: dict[str, list] = {s: [] for s in capitals}
        self._book_rows: list = []

    # ------------------------------------------------------------------ day
    def attribute_day(self, asof, *, held_start: dict, fills: dict,
                      prices: dict, prev_prices: dict, dividends: dict,
                      siloed_costs: dict, net_cost_usd: float,
                      siloed_financing: dict, net_financing_usd: float,
                      siloed_margin: dict) -> dict:
        """Book one trading day.

        held_start : {sleeve: {inst: signed qty}} held INTO asof's close
                     (post the previous close's fill) — these earn asof's
                     close-to-close return.
        fills      : {sleeve: {inst: delta qty}} filled AT asof's close.
        prices / prev_prices / dividends : {inst: float} for asof.
        siloed_costs / siloed_financing / siloed_margin : {sleeve: usd} — the
                     v1 as-if-siloed numbers (cost of the sleeve's OWN delta,
                     borrow on the sleeve's OWN short MV, and that short MV).
        net_cost_usd / net_financing_usd : the netted book's actual numbers.

        Returns {sleeve: {...}, 'book': {...}} for the day.
        """
        asof = pd.Timestamp(asof)
        out = {}
        sum_pnl = 0.0
        sum_siloed_cost = 0.0
        sum_siloed_fin = 0.0

        for s in self.capitals:
            held = held_start.get(s, {})
            price_pnl = 0.0
            for inst, q in held.items():
                p1 = float(prices.get(inst, np.nan))
                p0 = float(prev_prices.get(inst, np.nan))
                if not (np.isfinite(p1) and np.isfinite(p0)):
                    continue
                d = float(dividends.get(inst, 0.0) or 0.0)
                price_pnl += float(q) * ((p1 + d) - p0)
            cost = float(siloed_costs.get(s, 0.0))
            fin = float(siloed_financing.get(s, 0.0))
            margin = float(siloed_margin.get(s, 0.0))
            pnl = price_pnl - cost - fin
            prev_nav = self._nav[s]
            self._nav[s] = prev_nav + pnl
            sum_pnl += pnl
            sum_siloed_cost += cost
            sum_siloed_fin += fin

            traded = 0.0
            for inst, dq in (fills.get(s) or {}).items():
                dq = float(dq)
                if dq == 0.0:
                    continue
                p1 = float(prices.get(inst, np.nan))
                traded += abs(dq) * (p1 if np.isfinite(p1) else 0.0)
                canon = self.canonical_map.get(s, {}).get(inst, inst)
                self._trades[s].append({
                    "decision_date": asof, "ticker": canon,
                    "instrument": canon, "side": "BUY" if dq > 0 else "SELL",
                    "delta_shares": dq,
                    "fill_price": p1 if np.isfinite(p1) else np.nan,
                    "fill_date": asof})

            # post-fill positions snapshot (what the ledger writes)
            post = dict(held)
            for inst, dq in (fills.get(s) or {}).items():
                post[inst] = post.get(inst, 0.0) + float(dq)
            for inst, q in post.items():
                if abs(float(q)) <= 1e-12:
                    continue
                p1 = float(prices.get(inst, np.nan))
                canon = self.canonical_map.get(s, {}).get(inst, inst)
                self._positions[s].append({
                    "date": asof, "instrument": canon, "ticker": canon,
                    "qty": float(q), "close": p1,
                    "market_value": float(q) * p1 if np.isfinite(p1) else np.nan})

            ret = pnl / prev_nav if prev_nav else np.nan
            self._rows[s].append({
                "date": asof, "nav": self._nav[s],
                "cash": np.nan,                     # not meaningful in a shadow
                "financing_usd": fin, "margin": margin, "cost_usd": cost,
                "traded_usd": traded, "daily_return": ret})
            out[s] = {"pnl": pnl, "price_pnl": price_pnl, "cost": cost,
                      "financing": fin, "nav": self._nav[s]}

        benefit = ((sum_siloed_cost - float(net_cost_usd))
                   + (sum_siloed_fin - float(net_financing_usd)))
        book_pnl = sum_pnl + benefit
        prev_book = self._book_nav
        self._book_nav = prev_book + book_pnl
        self._book_rows.append({
            "date": asof, "nav": self._book_nav, "pnl": book_pnl,
            "net_cost_usd": float(net_cost_usd),
            "net_financing_usd": float(net_financing_usd),
            "siloed_cost_usd": sum_siloed_cost,
            "siloed_financing_usd": sum_siloed_fin,
            "netting_benefit_usd": benefit,
            "daily_return": book_pnl / prev_book if prev_book else np.nan})
        out["book"] = self._book_rows[-1]
        return out

    # ---------------------------------------------------------------- views
    def shadow_ledger_view(self, sleeve: str) -> ShadowLedgerView:
        if sleeve not in self.capitals:
            raise KeyError(f"unknown sleeve {sleeve!r}")
        nav = pd.DataFrame(self._rows[sleeve],
                           columns=["date", "nav", "cash", "financing_usd",
                                    "margin", "cost_usd", "traded_usd",
                                    "daily_return"])
        trades = pd.DataFrame(self._trades[sleeve],
                              columns=["decision_date", "ticker", "instrument",
                                       "side", "delta_shares", "fill_price",
                                       "fill_date"])
        positions = pd.DataFrame(self._positions[sleeve],
                                 columns=["date", "instrument", "ticker",
                                          "qty", "close", "market_value"])
        return ShadowLedgerView(sleeve, nav, trades, positions)

    def book_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self._book_rows)

    def book_nav_series(self) -> pd.Series:
        bf = self.book_frame()
        if bf.empty:
            return pd.Series(dtype=float)
        return bf.set_index("date")["nav"].astype(float)

    def netting_benefit_series(self) -> pd.Series:
        bf = self.book_frame()
        if bf.empty:
            return pd.Series(dtype=float)
        return bf.set_index("date")["netting_benefit_usd"].astype(float)

    # ------------------------------------------------------------ reconcile
    def reconcile(self) -> dict:
        """Prove no risk-accounting error: for every day,
        book_nav == Σ shadow_navs + cumulative netting benefit, to the penny.

        Returns {'max_abs_err_usd', 'n_days', 'ok'}; raises if the identity is
        broken beyond RECONCILE_TOL_USD (a broken identity means P&L was
        created or destroyed by the netting — a hard bug, never a warning).
        """
        bf = self.book_frame()
        if bf.empty:
            return {"max_abs_err_usd": 0.0, "n_days": 0, "ok": True}
        shadow_sum = None
        for s in self.capitals:
            ns = self.shadow_ledger_view(s).nav_series()
            shadow_sum = ns if shadow_sum is None else shadow_sum.add(ns,
                                                                      fill_value=np.nan)
        cum_benefit = self.netting_benefit_series().cumsum()
        book = self.book_nav_series()
        err = (book - (shadow_sum + cum_benefit)).abs()
        max_err = float(err.max())
        ok = bool(max_err <= RECONCILE_TOL_USD)
        if not ok:
            raise AssertionError(
                f"netting reconciliation broken: max |book - (Σ shadow + "
                f"cum benefit)| = ${max_err:.6f} > ${RECONCILE_TOL_USD} over "
                f"{len(err)} days — P&L created/destroyed by netting")
        return {"max_abs_err_usd": max_err, "n_days": int(len(err)), "ok": ok}


# ===========================================================================
# helpers the A/B harness and orchestrator share
# ===========================================================================

def short_mv(held: dict, prices: dict) -> float:
    """Borrowable short market value of a {inst: signed qty} book (ETF/EQUITY
    convention: only negative qtys are borrowed; mirrors DerivativesLedger)."""
    total = 0.0
    for inst, q in held.items():
        q = float(q)
        if q < 0:
            p = float(prices.get(inst, np.nan))
            if np.isfinite(p) and p > 0:
                total += abs(q) * p
    return total


def gross_mv(held: dict, prices: dict) -> float:
    """Gross market value Σ|qty|·price of a {inst: signed qty} book."""
    total = 0.0
    for inst, q in held.items():
        p = float(prices.get(inst, np.nan))
        if np.isfinite(p) and p > 0:
            total += abs(float(q)) * p
    return total
