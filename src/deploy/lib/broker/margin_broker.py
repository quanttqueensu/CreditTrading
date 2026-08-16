"""H1 — MarginBroker: the Broker seam over ONE shared MarginBook.

REFINE_ARCHITECTURE.md §1.2. v1's Simulator keeps one sub-ledger PER sleeve;
the MarginBroker keeps ONE `MarginBook` for the whole book, so cash, financing,
margin and leverage are computed on the single shared account (portfolio
margin). The orchestrator (portfolio_v2.py) resolves weights -> signed qty,
expresses ETF -> futures, NETS same-instrument legs across sleeves, scales to
the vol target and clamps to the leverage ceiling; it then hands the FINAL net
book to `commit(asof, targets, prices)`, which advances the MarginBook exactly
one day. `place_targets` only BUFFERS a sleeve's raw targets (for record); no
sub-ledger moves until `commit`.

An `EXECUTION=ibkr` v2 run uses the SAME v1 `IBKRBroker` — one paper account is
natively portfolio-margined — so the MarginBroker is the simulator twin that
reproduces that single-account margining locally. `ib_insync` stays lazy in the
v1 adapter; nothing here imports it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ...broker.base import Broker, Fill, AccountSnapshot
from ...sleeve import MarketState
from ..financing import FinancingModel
from ..futures import FuturesReturns
from ..margin import MarginBook, build_margin_model


class MarginBroker(Broker):
    def __init__(self, books_root="ops/books/v2", margin_spec=None,
                 financing=None, futures_returns=None, costs=None,
                 max_gross_leverage=3.0, verbose=False):
        self.books_root = Path(books_root)
        self.books_root.mkdir(parents=True, exist_ok=True)
        self.margin_spec = dict(margin_spec or {})
        self.financing = financing
        self.futures_returns = futures_returns
        self.book_costs = costs
        self.max_gross_leverage = float(
            self.margin_spec.get("max_gross_leverage", max_gross_leverage))
        self.verbose = bool(verbose)

        self._cfg = {}                 # sleeve -> config (mirrors Simulator._cfg)
        self._buffer = {}              # sleeve -> last-buffered targets
        self._option_mark_fns = {}     # sleeve -> option mark_fn
        self._sleeve_holdings = {}     # sleeve -> {inst: signed qty} (tracked)
        self._total_capital = 0.0
        self._book = None
        self._live = None              # optional v1 IBKRBroker for live forward

    # -- registration -----------------------------------------------------

    def register_sleeve(self, sleeve_name, alloc_type, spec, costs, capital_usd,
                        instruments, mark_fn=None, greeks_fn=None,
                        option_half_spread_usd=0.02):
        run_spec = dict(spec)
        run_spec.setdefault("rebalance", {"min_trade_usd": 0.0})
        run_spec["capital_usd"] = float(capital_usd)
        run_spec["book_usd"] = float(capital_usd)
        run_spec["tickers"] = list(instruments)
        self._cfg[sleeve_name] = {
            "alloc_type": alloc_type, "run_spec": run_spec, "costs": costs,
            "capital_usd": float(capital_usd), "instruments": list(instruments),
            "mark_fn": mark_fn, "greeks_fn": greeks_fn}
        if mark_fn is not None:
            self._option_mark_fns[sleeve_name] = mark_fn
        self._sleeve_holdings.setdefault(sleeve_name, {})
        self._total_capital = sum(c["capital_usd"] for c in self._cfg.values())
        if self.book_costs is None:
            self.book_costs = costs
        self._ensure_book()
        return self._book

    def _ensure_book(self):
        if self._book is not None:
            return self._book
        if self.financing is None:
            self.financing = FinancingModel()
        fut_marks = None
        if self.futures_returns is None:
            try:
                self.futures_returns = FuturesReturns()
            except Exception:                       # no futures data -> ETF only
                self.futures_returns = None
        if self.futures_returns is not None:
            fut_marks = self.futures_returns.marks_provider()
        model = build_margin_model(self.margin_spec)
        self._book = MarginBook(
            self.books_root / "_book", margin_model=model,
            financing=self.financing, futures_marks=fut_marks,
            max_gross_leverage=self.max_gross_leverage, verbose=self.verbose)
        return self._book

    def ledger(self, sleeve_name=None):
        return self._ensure_book()

    # -- composite option marks (one book, many sleeves' option legs) ------

    def _composite_option_mark(self, asof, pt):
        for fn in self._option_mark_fns.values():
            try:
                px = fn(asof, pt)
            except Exception:
                px = None
            if px is not None and np.isfinite(px):
                return float(px)
        return None

    # -- Broker API -------------------------------------------------------

    def sync_positions(self, sleeve_name) -> dict:
        """This sleeve's OWN tagged share of the shared book (tracked by the
        orchestrator's resolved contributor qtys)."""
        return dict(self._sleeve_holdings.get(sleeve_name, {}))

    def cash(self, sleeve_name=None) -> float:
        return float(self._ensure_book().cash)

    def place_targets(self, sleeve_name, targets, asof, market_state) -> list:
        """BUFFER only — the shared book advances once at commit()."""
        self._buffer[sleeve_name] = list(targets)
        return []

    def set_sleeve_holdings(self, holdings: dict):
        """Orchestrator hands back each sleeve's tagged post-commit holdings."""
        for name, held in holdings.items():
            self._sleeve_holdings[name] = dict(held)

    def commit(self, asof, targets, prices) -> list:
        """Advance the ONE MarginBook a single day to `asof`, deciding today's
        order from the FINAL net `targets`. Returns the fills booked this call."""
        book = self._ensure_book()
        asof = pd.Timestamp(asof)
        n_before = len(book.trades)
        book_spec = {"capital_usd": self._total_capital,
                     "book_usd": self._total_capital,
                     "rebalance": {"min_trade_usd": 0.0}}
        target_fn = lambda spec, d, px_: list(targets)   # noqa: E731
        start = asof if book.last_date is None else None
        book.advance(prices, book_spec, self.book_costs, target_fn,
                     through=asof, start=start,
                     mark_fn=self._composite_option_mark, verbose=self.verbose)
        fills = self._fills_since(book, n_before)
        # EXECUTION=ibkr: forward the netted book to the ONE v1 IBKR paper
        # account (natively portfolio-margined). Lazy, guarded, never in CI —
        # the local MarginBook stays the simulator-of-record. The forward
        # carries a MarketState with the SAME price frame this commit used
        # (2026-07-26 integration fix): with market_state=None the adapter
        # could not price weight legs or derive a bond leg's last-close limit
        # (bonds are limit-only), so any bond leg without an explicit
        # meta['limit_price'] was warned-and-skipped every day while the
        # simulator-of-record traded it.
        if self._live is not None:
            try:
                ms = MarketState(asof=asof, prices=prices)
                self._live.place_targets("book_v2", list(targets), asof, ms)
            except Exception as exc:                       # pragma: no cover
                if self.verbose:
                    print(f"[margin-broker] live IBKR forward skipped: {exc!r}")
        return fills

    def attach_live(self, ibkr_broker):
        """Attach a connected v1 IBKRBroker so commit() forwards the netted book
        to the single paper account. `ib_insync` is imported only inside that
        adapter's connect(); nothing here touches it."""
        self._live = ibkr_broker

    def snapshot(self, sleeve_name, asof, market_state) -> AccountSnapshot:
        book = self._ensure_book()
        nav = float(book.nav_series().iloc[-1]) if not book.nav.empty else np.nan
        fin = 0.0
        if not book.nav.empty and "financing_usd" in book.nav.columns:
            fin = float(book.nav.sort_values("date")["financing_usd"].iloc[-1])
        return AccountSnapshot(cash=float(book.cash),
                               positions=dict(book.held()),
                               nav=nav, asof=pd.Timestamp(asof),
                               financing_usd=fin)

    @staticmethod
    def _fills_since(book, n_before):
        if book.trades.empty or len(book.trades) <= n_before:
            return []
        out = []
        for _, r in book.trades.iloc[n_before:].iterrows():
            out.append(Fill(
                instrument=r["instrument"], side=r["side"],
                qty=float(r["qty"]), price=float(r["fill_price"]),
                cost_usd=float(r["cost_usd"]), asof=pd.Timestamp(r["fill_date"]),
                reason=str(r.get("reason", "")), combo_id=r.get("combo_id"),
                kind=r.get("kind", "ETF")))
        return out
