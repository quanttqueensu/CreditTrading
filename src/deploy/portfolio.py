"""The portfolio orchestrator: N independent sub-ledgers rolled up into a
book-level reporting view.

One `advance(asof)` call, for each ENABLED sleeve, in order:
  1. load >= sleeve.history_warmup_trading_days() price bars before asof,
  2. build a MarketState whose `holdings` is THAT sleeve's OWN sub-ledger
     signed positions (never a sibling's),
  3. sleeve.target_positions(asof, ms) -> the desired book,
  4. broker.place_targets(...) -> the sub-ledger advances ONE day (idempotent,
     resumable),
  5. risk.evaluate_sleeve(...) -> KILL flattens+disables the sleeve, HALVE
     scales its capital.
Then roll up into a BookView and (optionally) persist book_status.json.

"Shared cash" at book level is the SUM of the sub-ledger cash — a reporting
aggregation, not one margin account (paper simplification, per DEPLOY_CONTEXT).
Drive it day-by-day over the replay calendar; each call books exactly one new
day per sleeve, so a calendar-timed sleeve always sees fresh holdings.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ops import common as ops_common
from ops.ledger import CASH
from . import registry, risk
from .sleeve import MarketState, PositionTarget, RiskVerdict, OK, HALVE, KILL, FLAT


def local_panel_loader(instruments, asof, warmup_trading_days):
    """Default price loader: pull ETF bars from data/etf_daily.parquet deep
    enough to cover `warmup_trading_days` before `asof`. Fetches by a generous
    calendar span (holidays cannot shorten it below the warmup) and returns the
    ops tidy price store."""
    asof = pd.Timestamp(asof)
    span = max(10, int(math.ceil(warmup_trading_days * 1.7)) + 15)
    start = asof - pd.Timedelta(days=span)
    px = ops_common.fetch_local(list(instruments), start, asof)
    return px


@dataclass
class BookView:
    asof: object
    book_nav: float
    book_pnl: float
    sleeves: dict
    book_cash: float
    gross_exposure: float
    net_exposure: float
    limits: dict = field(default_factory=dict)
    book_turnover: float = 0.0     # sum of sub-ledger last-day traded notional

    def to_json(self):
        return {
            "asof": str(pd.Timestamp(self.asof).date()),
            "book_nav": self.book_nav, "book_pnl": self.book_pnl,
            "book_cash": self.book_cash, "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure, "book_turnover": self.book_turnover,
            "sleeves": self.sleeves, "limits": self.limits}


class PortfolioOrchestrator:
    def __init__(self, book_spec, broker, books_root="ops/books",
                 price_loader=None, costs=None, sleeves=None, events=None,
                 verbose=False, mark_fns=None, greeks_fns=None, dry_run=False):
        self.book_spec = book_spec
        self.broker = broker
        self.books_root = Path(books_root)
        self.books_root.mkdir(parents=True, exist_ok=True)
        # dry_run: compute + log targets only. Pair with a broker whose
        # place_targets never advances a ledger (DryRunBroker); the risk block
        # is skipped (no ledger moved, so no verdict to act on) and the rollup
        # is persisted to book_status_dryrun.json, never book_status.json.
        self.dry_run = bool(dry_run)
        self.price_loader = price_loader or local_panel_loader
        self.costs = costs if costs is not None else ops_common.load_costs()
        self.events = events
        self.verbose = verbose

        self.sleeves = {}          # name -> Sleeve
        self.capital = {}          # name -> capital_usd (mutable; HALVE scales it)
        self.enabled = set()
        self.disabled = set()
        self.review_flags = set()
        self.mark_fns = {}
        self.greeks_fns = {}
        self.sleeve_costs = {}      # name -> costs dict (per-sleeve override, e.g. VRP)
        self.last_targets = {}      # name -> list[PositionTarget] emitted this run
        self.initial_capital = {}

        if sleeves is not None:
            # test / programmatic path: pre-built Sleeve instances. Option-math
            # callbacks may be supplied per-sleeve via mark_fns/greeks_fns.
            _mark_fns = mark_fns or {}
            _greeks_fns = greeks_fns or {}
            for name, sleeve in sleeves.items():
                self._register(name, sleeve, sleeve.capital_usd,
                               enabled=True, mark_fn=_mark_fns.get(name),
                               greeks_fn=_greeks_fns.get(name))
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
        capital = float(entry.get("capital_usd",
                                  spec.get("capital_usd", spec.get("book_usd"))))
        sleeve = registry.build_sleeve(spec, capital)
        self._register(name, sleeve, capital,
                       enabled=entry.get("enabled", True),
                       mark_fn=entry.get("mark_fn"),
                       greeks_fn=entry.get("greeks_fn"),
                       costs=entry.get("costs"))

    def _register(self, name, sleeve, capital, enabled, mark_fn, greeks_fn=None,
                  costs=None):
        self.sleeves[name] = sleeve
        self.capital[name] = float(capital)
        self.initial_capital[name] = float(capital)
        self.mark_fns[name] = mark_fn
        self.greeks_fns[name] = greeks_fn
        # per-sleeve costs (short-vol uses data/vrp/costs_vrp.yaml, not the ETF
        # costs); default to the book-wide costs when the entry names none.
        sleeve_costs = costs if costs is not None else self.costs
        self.sleeve_costs[name] = sleeve_costs
        if enabled:
            self.enabled.add(name)
        if hasattr(self.broker, "register_sleeve"):
            self.broker.register_sleeve(
                name, sleeve.alloc_type, sleeve.spec, sleeve_costs, capital,
                sleeve.instruments(), mark_fn=mark_fn, greeks_fn=greeks_fn)

    # -- the daily step ---------------------------------------------------

    def advance(self, asof, source="local") -> BookView:
        asof = pd.Timestamp(asof)
        for name in list(self.sleeves):
            disabled_now = name in self.disabled
            if not disabled_now and name not in self.enabled:
                continue
            sleeve = self.sleeves[name]
            prices = self.price_loader(sleeve.instruments(), asof,
                                       sleeve.history_warmup_trading_days())
            holdings = self.broker.sync_positions(name)
            ms = MarketState(asof=asof, prices=prices, holdings=holdings,
                             mark_fn=self.mark_fns.get(name),
                             greeks_fn=self.greeks_fns.get(name),
                             events=self.events)

            # A killed sleeve keeps advancing FLAT until its position is wound
            # down (the exit order fills T+1 like any other), then goes quiet.
            if disabled_now:
                held = {k: v for k, v in holdings.items() if k != CASH}
                if held:
                    flats = [PositionTarget(instrument=inst, side=FLAT, qty=0.0)
                             for inst in held]
                    self.broker.place_targets(name, flats, asof, ms)
                continue

            targets = sleeve.target_positions(asof, ms)
            self.last_targets[name] = list(targets)
            self.broker.place_targets(name, targets, asof, ms)

            ledger = (self.broker.ledger(name)
                      if hasattr(self.broker, "ledger") and not self.dry_run
                      else None)
            if ledger is not None:
                verdict = risk.evaluate_sleeve(sleeve, ledger)
                if verdict.status in (KILL, HALVE):
                    action = risk.apply_verdict(self, name, verdict)
                    if self.verbose:
                        print(f"[book] {name}: {verdict.status} — {action['effect']}")
        view = self.rollup(asof)
        self._persist(view)
        return view

    # -- rollup -----------------------------------------------------------

    def rollup(self, asof=None) -> BookView:
        book_nav = 0.0
        book_cash = 0.0
        book_pnl = 0.0
        gross = 0.0
        net = 0.0
        turnover = 0.0
        sleeve_views = {}
        ledgers = {}
        for name, sleeve in self.sleeves.items():
            if not hasattr(self.broker, "ledger"):
                continue
            lg = self.broker.ledger(name)
            ledgers[name] = lg
            nav = float(lg.nav_series().iloc[-1]) if not lg.nav.empty else np.nan
            cash = float(lg.cash)
            init = self.initial_capital[name]
            pnl = (nav - init) if np.isfinite(nav) else 0.0
            g = self._gross_exposure(lg)
            n = self._net_exposure(lg)
            tvr = self._last_traded_usd(lg)
            if np.isfinite(nav):
                book_nav += nav
                book_cash += cash
                book_pnl += pnl
                gross += g
                net += n
                turnover += tvr
            sleeve_views[name] = {
                "nav": nav, "pnl": pnl, "cash": cash,
                "capital_usd": self.capital[name],
                "gross_exposure": g, "net_exposure": n, "turnover": tvr,
                "enabled": name in self.enabled and name not in self.disabled,
                "disabled": name in self.disabled,
                "review_flag": name in self.review_flags,
                "risk_verdict": self._last_verdict(sleeve, lg)}

        limits = risk.check_book_limits(self.book_spec, sleeve_views,
                                        book_nav, gross, ledgers)
        return BookView(asof=asof, book_nav=book_nav, book_pnl=book_pnl,
                        sleeves=sleeve_views, book_cash=book_cash,
                        gross_exposure=gross, net_exposure=net, limits=limits,
                        book_turnover=turnover)

    def _last_verdict(self, sleeve, ledger):
        try:
            v = risk.evaluate_sleeve(sleeve, ledger)
            return {"status": v.status, "reasons": v.reasons}
        except Exception as exc:
            return {"status": OK, "reasons": [f"verdict unavailable: {exc!r}"]}

    @staticmethod
    def _last_traded_usd(ledger):
        """Traded notional on the sub-ledger's most recent day (turnover), read
        off the nav frame's traded_usd column (present in both ops.Ledger and
        DerivativesLedger). 0 when the book has not traded yet."""
        nav = ledger.nav
        if nav is None or nav.empty or "traded_usd" not in nav.columns:
            return 0.0
        last = nav.sort_values("date")["traded_usd"].iloc[-1]
        return float(last) if pd.notna(last) else 0.0

    @staticmethod
    def _gross_exposure(ledger):
        if ledger.positions.empty:
            return 0.0
        last = ledger.positions[ledger.positions["date"] == ledger.positions["date"].max()]
        mv = last[last["ticker" if "ticker" in last.columns else "instrument"] != CASH]["market_value"]
        return float(mv.abs().sum())

    @staticmethod
    def _net_exposure(ledger):
        if ledger.positions.empty:
            return 0.0
        last = ledger.positions[ledger.positions["date"] == ledger.positions["date"].max()]
        col = "ticker" if "ticker" in last.columns else "instrument"
        mv = last[last[col] != CASH]["market_value"]
        return float(mv.sum())

    def _persist(self, view):
        fname = "book_status_dryrun.json" if self.dry_run else "book_status.json"
        path = self.books_root / fname
        with open(path, "w") as fh:
            json.dump(view.to_json(), fh, indent=2, default=str)
