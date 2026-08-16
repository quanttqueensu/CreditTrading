"""The internal simulator broker.

Owns one **sub-ledger per sleeve** under `books_root/<sleeve>/` and advances it
one day per `place_targets` call. Long-only ETF sleeves get a
`LongOnlySleeveLedger` (ops.Ledger subclass — same fill math, same atomic save,
same idempotence); short/option sleeves get a `DerivativesLedger`. This is the
path that proves the whole book tonight with zero broker dependencies: the same
`run_book.py` runs it, and flipping `EXECUTION=ibkr` swaps only this object.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from ops.ledger import CASH
from .base import Broker, Fill, AccountSnapshot
from ..exec_ledger import LongOnlySleeveLedger, DerivativesLedger

# alloc_type -> which sub-ledger. Long-only ETF sleeves reuse ops.Ledger; the
# short-vol and short-IEF-overlay legs need signed positions / options.
LONG_ONLY_TYPES = {"static_weights", "eom_duration", "fomc_event"}
DERIVATIVES_TYPES = {"short_vol_straddle", "duration_hedged_overlay"}


class Simulator(Broker):
    def __init__(self, books_root="ops/books", verbose=False, financing=None):
        self.books_root = Path(books_root)
        self.verbose = verbose
        # Optional A1 FinancingModel handed to the DERIVATIVES_TYPES sub-ledgers
        # (LongOnly ETF sleeves are unaffected). None -> the flat legacy path,
        # so every existing caller is byte-unchanged; the v2 kill shadow passes
        # a FinancingModel so its per-sleeve kills fire on real book economics.
        self.financing = financing
        self._cfg = {}          # sleeve_name -> config dict
        self._ledger = {}       # sleeve_name -> ledger instance

    # -- registration -----------------------------------------------------

    def register_sleeve(self, sleeve_name, alloc_type, spec, costs, capital_usd,
                        instruments, mark_fn=None, greeks_fn=None,
                        option_half_spread_usd=0.02):
        """Wire a sleeve's sub-ledger. Called by the orchestrator before the
        first `place_targets`. Idempotent: re-registering reuses the on-disk
        book (resumable).

        `mark_fn` prices option legs for the sub-ledger; `greeks_fn` is the
        sleeve-side delta/rate-beta seam threaded onto MarketState by the
        orchestrator (the ledger itself needs only marks), stored here so the
        registered surface matches the documented MarketState contract."""
        state_dir = self.books_root / sleeve_name
        if alloc_type in DERIVATIVES_TYPES:
            kind = "derivatives"
            ledger = DerivativesLedger(state_dir,
                                       option_half_spread_usd=option_half_spread_usd,
                                       financing=self.financing)
        else:
            kind = "long_only"
            ledger = LongOnlySleeveLedger(state_dir)
        # ops.Ledger.advance reads book_usd / tickers / rebalance off the spec;
        # sleeve specs carry capital_usd, so hand the ledger an augmented view.
        run_spec = dict(spec)
        run_spec.setdefault("rebalance", {"min_trade_usd": 0.0})
        run_spec["book_usd"] = float(capital_usd)
        run_spec["capital_usd"] = float(capital_usd)
        run_spec["tickers"] = list(instruments)
        self._cfg[sleeve_name] = {
            "kind": kind, "alloc_type": alloc_type, "run_spec": run_spec,
            "costs": costs, "capital_usd": float(capital_usd),
            "instruments": list(instruments), "mark_fn": mark_fn,
            "greeks_fn": greeks_fn}
        self._ledger[sleeve_name] = ledger
        return ledger

    def ledger(self, sleeve_name):
        return self._ledger[sleeve_name]

    # -- Broker API -------------------------------------------------------

    def sync_positions(self, sleeve_name) -> dict:
        lg = self._ledger[sleeve_name]
        return lg.held_shares() if hasattr(lg, "held_shares") else lg.held()

    def cash(self, sleeve_name) -> float:
        return float(self._ledger[sleeve_name].cash)

    def place_targets(self, sleeve_name, targets, asof, market_state) -> list:
        """Advance the sleeve's sub-ledger one day to `asof`, deciding today's
        order from `targets` (fills at the next close). Returns the fills booked
        THIS call as `Fill`s."""
        cfg = self._cfg[sleeve_name]
        lg = self._ledger[sleeve_name]
        asof = pd.Timestamp(asof)
        prices = market_state.prices

        n_trades_before = len(lg.trades)
        target_fn = lambda spec, d, prices_: list(targets)
        start = asof if lg.last_date is None else None

        if cfg["kind"] == "derivatives":
            lg.advance(prices, cfg["run_spec"], cfg["costs"], target_fn,
                       through=asof, start=start, mark_fn=cfg["mark_fn"],
                       verbose=self.verbose)
        else:
            lg.advance(prices, cfg["run_spec"], cfg["costs"], target_fn,
                       through=asof, start=start, verbose=self.verbose)

        return self._fills_since(lg, n_trades_before, cfg["kind"])

    def snapshot(self, sleeve_name, asof, market_state) -> AccountSnapshot:
        lg = self._ledger[sleeve_name]
        nav = float(lg.nav_series().iloc[-1]) if not lg.nav.empty else np.nan
        fin = 0.0
        if "financing_usd" in lg.nav.columns and not lg.nav.empty:
            fin = float(lg.nav.sort_values("date")["financing_usd"].iloc[-1])
        return AccountSnapshot(cash=float(lg.cash),
                               positions=self.sync_positions(sleeve_name),
                               nav=nav, asof=pd.Timestamp(asof),
                               financing_usd=fin)

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _fills_since(lg, n_before, kind):
        if lg.trades.empty or len(lg.trades) <= n_before:
            return []
        fresh = lg.trades.iloc[n_before:]
        out = []
        for _, r in fresh.iterrows():
            inst = r["ticker"] if "ticker" in r else r["instrument"]
            out.append(Fill(
                instrument=inst, side=r["side"],
                qty=float(r["shares"] if "shares" in r else r["qty"]),
                price=float(r["fill_price"]), cost_usd=float(r["cost_usd"]),
                asof=pd.Timestamp(r["fill_date"]), reason=str(r.get("reason", "")),
                combo_id=r.get("combo_id"),
                kind=(r.get("kind", "ETF") if kind == "derivatives" else "ETF")))
        return out


class DryRunBroker(Simulator):
    """A Simulator that NEVER advances or writes a sub-ledger and never places
    an order. `place_targets` only records the sleeve's emitted target book
    (plus the currently held book, read-only from the on-disk sub-ledger) into
    `self.planned`, so the runner can log "what the book WOULD do today"
    without transmitting anything. Used by `run_book.py --dry-run` and the
    scheduler's safe default mode (ops/schedule/)."""

    def __init__(self, books_root="ops/books", verbose=False):
        super().__init__(books_root=books_root, verbose=verbose)
        self.planned = []          # list of {asof, sleeve, targets, held, cash}

    def place_targets(self, sleeve_name, targets, asof, market_state) -> list:
        held = dict(self.sync_positions(sleeve_name))
        cash = held.pop(CASH, None)
        rows = []
        for t in targets:
            rows.append({
                "instrument": t.instrument, "side": t.side, "kind": t.kind,
                "qty": t.qty, "weight": t.weight, "combo_id": t.combo_id,
                "held_qty": held.get(t.instrument, 0.0),
                "reason": t.reason})
        self.planned.append({
            "asof": str(pd.Timestamp(asof).date()), "sleeve": sleeve_name,
            "targets": rows, "held": held,
            "cash": None if cash is None else float(cash)})
        if self.verbose:
            for r in rows:
                size = (f"qty={r['qty']:g}" if r["qty"] is not None
                        else f"w={r['weight']:g}" if r["weight"] is not None
                        else "")
                print(f"[dry-run] {sleeve_name}: {r['side']:<5} "
                      f"{r['instrument']:<24} {size:<12} held={r['held_qty']:g}"
                      f"  ({r['reason']})")
        return []                  # nothing fills; nothing is written
