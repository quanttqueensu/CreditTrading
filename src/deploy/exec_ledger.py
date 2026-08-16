"""Sub-ledgers the sleeves trade through.

Two flavours, one file:

  LongOnlySleeveLedger(ops.Ledger)
      A thin subclass of the shipped ops ledger. It reuses the fill math,
      atomic save()/manifest, distribution crediting, price-gap guard and
      idempotence UNCHANGED, and overrides only two seams:
        * the decision calendar — it decides EVERY trading day (calendar-timed
          sleeves must be consulted on non-month-end days), not month-end only;
        * order sizing — it consumes a sleeve's `PositionTarget` book (absolute
          signed qty, or weight-of-sleeve-capital) instead of static weights.
      Used by the long-only ETF sleeves (#1 EOM, #2 FOMC).

  DerivativesLedger
      A new, standalone signed-position ledger the ops (long-only) ledger
      cannot be: signed positions, option legs (contract multiplier, atomic
      combo fills), short-borrow financing, and pluggable marks via `mark_fn`.
      It reuses `src/deploy/fills.py` for equity fill pricing and mirrors the
      ops atomic CSV+manifest write discipline (its own save(); the same
      crash-atomicity property, asserted by a unit test). Used by the
      short-vol (#3) and duration-hedged overlay (#5) legs.

Both fill at the NEXT close: an order emitted on trading day D fills at
close(D+1), and the mark for D+1 is that same close. The executor diffs a
sleeve's target book against current holdings and trades the delta.
"""

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from ops import common as ops_common
from ops.ledger import Ledger, CASH

from . import fills
from .sleeve import PositionTarget, LONG, SHORT, FLAT, ETF, EQUITY, FUTURES, OPTION

TRADING_DAYS = ops_common.TRADING_DAYS


# ===========================================================================
# Long-only sleeve ledger — reuse ops.Ledger, override two seams
# ===========================================================================

def _target_shares_for(pt: PositionTarget, price, nav_today) -> float:
    """Absolute target share count a long-only PositionTarget implies.

    FLAT -> 0. qty-expressed -> floor(|qty|) (whole shares). weight-expressed
    -> floor(nav_today * weight / price), the same sizing the ops ledger uses
    for a static weight. Long-only, so the result is always >= 0.
    """
    if pt.side == FLAT:
        return 0.0
    if not np.isfinite(price) or price <= 0:
        return 0.0
    if pt.qty is not None:
        return float(math.floor(abs(float(pt.qty))))
    if pt.weight is not None:
        return float(math.floor(nav_today * float(pt.weight) / price))
    return 0.0


class LongOnlySleeveLedger(Ledger):
    """ops.Ledger that decides every day and follows a PositionTarget book."""

    def _decision_reason(self, d, prev_day, is_funding_day, decided_months):
        """Decide EVERY trading day. A calendar-timed sleeve (EOM entry on j=4,
        a FOMC day-0) must be consulted on days the month-end-only ops calendar
        would skip; the diff-vs-holdings in `_make_orders` means a decision that
        matches the current book writes no order, so deciding daily is free."""
        if is_funding_day:
            return "funding"
        return "target"

    def _make_orders(self, d, targets, shares, close, nav_today, spec,
                     reason="", verbose=True):
        """Size orders from a list[PositionTarget] (the sleeve's full desired
        book). Any currently-held ticker absent from `targets` is driven to
        FLAT. Reuses the ops ORDER schema and min-trade filter verbatim."""
        min_trade = float(spec.get("rebalance", {}).get("min_trade_usd", 0.0))
        desired = {}
        for pt in targets:
            price = float(close.get(pt.instrument, np.nan))
            desired[pt.instrument] = _target_shares_for(pt, price, nav_today)
        # Held-but-unmentioned -> FLAT (target 0).
        for t in shares:
            if t != CASH and t not in desired:
                desired[t] = 0.0

        rows = []
        for t in sorted(desired):
            price = float(close.get(t, np.nan))
            if not np.isfinite(price) or price <= 0:
                if desired[t] != 0.0:
                    print(f"[sleeve-ledger] WARNING {d.date()}: no usable close "
                          f"for {t}; no order written.")
                continue
            target_shares = float(desired[t])
            current = float(shares.get(t, 0.0))
            delta = target_shares - current
            if abs(delta * price) < min_trade:
                continue
            rows.append({"decision_date": d, "ticker": t,
                         "current_shares": current,
                         "target_shares": target_shares,
                         "delta_shares": float(delta),
                         "decision_price": price, "target_weight": np.nan,
                         "reason": reason, "status": "open", "fill_date": pd.NaT})
        if verbose and rows:
            desc = ", ".join(f"{r['ticker']} {r['delta_shares']:+.0f}sh" for r in rows)
            print(f"[sleeve-ledger] {d.date()} [{reason}]: {desc} "
                  "(fills at the next close)")
        return rows


# ===========================================================================
# Derivatives ledger — signed positions, options, short financing
# ===========================================================================

D_ORDER_COLUMNS = ["decision_date", "instrument", "kind", "current_qty",
                   "target_qty", "delta_qty", "decision_price", "multiplier",
                   "combo_id", "side", "reason", "status", "fill_date", "meta_json"]

D_TRADE_COLUMNS = ["fill_date", "decision_date", "instrument", "kind", "side",
                   "qty", "multiplier", "decision_price", "close_price",
                   "fill_price", "cost_usd", "notional_usd", "combo_id", "reason"]

D_POSITION_COLUMNS = ["date", "instrument", "kind", "side", "qty", "multiplier",
                      "close", "market_value", "weight", "combo_id", "meta_json"]

D_NAV_COLUMNS = ["date", "nav", "cash", "invested", "distributions_usd",
                 "cost_usd", "traded_usd", "financing_usd", "margin",
                 "daily_return", "decision"]


def _dread(path, cols, date_cols):
    if not Path(path).exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=cols)
    for c in date_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


class DerivativesLedger:
    """Signed-position book with option legs and short financing.

    Column superset of the ops schema plus `side`, `multiplier`, `combo_id`,
    `margin`, `financing_usd`. Marks: ETF/EQUITY legs from the close store,
    OPTION legs from `mark_fn(asof, PositionTarget) -> price` (None beyond the
    last mark -> the day is not booked, resumable). Short ETF/EQUITY legs accrue
    stock-borrow at `costs['financing_spread_bp']` per trading day on their
    market value; short OPTION premium is a credit, not a borrowable asset, and
    is deliberately NOT charged borrow (mirrors scripts/vrp/c2b_sleeve.py so the
    short-vol reproduction ties to the penny).

    OPTIONAL A1 FINANCING (`financing=FinancingModel()`). When a FinancingModel
    is supplied, the flat `financing_spread_bp` accrual is replaced by the SAME
    per-leg A1 dispatch MarginBook uses (margin_debit all-in on |neg cash|, base
    CREDITED on positive cash, and only the FEE SPREAD over base charged on short
    MV / posted futures margin — base handled once by the cash leg so a
    cash-collateralized short nets to its ~50bp fee, tying to credit_hedged.py),
    applied to THIS ledger's own as-if-siloed balances. This is what the v2
    per-sleeve kill shadow runs on, so the frozen drawdown-kill / financing-watch
    fire on the A1 economics the real book trades on rather than the legacy 150bp
    v1 basis. Absent a model (the default, every v1 caller) the flat path is
    byte-for-byte unchanged.

    PAPER MARGIN MODEL (intentional simplification, per DEPLOY_CONTEXT §3). This
    is a margin book, not a cash-secured one: unlike ops.Ledger (which floors a
    long buy to affordable cash), a long ETF/EQUITY buy here is filled in full
    even when it drives sub-ledger cash negative — the duration-hedged overlay
    (long LQD / short IEF) and the short-vol hedge both need to hold a position
    larger than settled cash. Negative cash is then financed daily at the same
    `financing_spread_bp` (`fin_daily * neg_cash`), so the carrying cost of the
    borrow is booked; the paper account is never margin-called. Book-level risk
    limits, not per-fill cash trimming, cap gross exposure.
    """

    def __init__(self, state_dir, option_half_spread_usd=0.02, financing=None):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.option_half_spread_usd = float(option_half_spread_usd)
        # Optional A1 FinancingModel (per-leg dispatch in _accrue_financing).
        # A subclass (MarginBook) may set self.financing to its own model BEFORE
        # calling super().__init__; never clobber that. For a direct
        # DerivativesLedger, adopt the passed model (None -> flat legacy path).
        if financing is not None or not hasattr(self, "financing"):
            self.financing = financing
        self.orders = _dread(self.state_dir / "orders.csv", D_ORDER_COLUMNS,
                             ["decision_date", "fill_date"])
        self.trades = _dread(self.state_dir / "trades.csv", D_TRADE_COLUMNS,
                             ["fill_date", "decision_date"])
        self.positions = _dread(self.state_dir / "positions.csv",
                                D_POSITION_COLUMNS, ["date"])
        self.nav = _dread(self.state_dir / "nav.csv", D_NAV_COLUMNS, ["date"])
        self._verify_manifest()
        self.leg_meta = self._recover_leg_meta()

    # -- state ------------------------------------------------------------

    def _verify_manifest(self):
        path = self.state_dir / "manifest.json"
        if not path.exists():
            return
        with open(path) as fh:
            manifest = json.load(fh)
        actual = {"orders.csv": self.orders, "trades.csv": self.trades,
                  "positions.csv": self.positions, "nav.csv": self.nav}
        bad = []
        for fname, expected in manifest.get("files", {}).items():
            frame = actual.get(fname)
            if frame is None:
                continue
            if int(expected.get("rows", -1)) != len(frame):
                bad.append(f"{fname}: manifest says {expected.get('rows')} rows, "
                           f"file has {len(frame)}")
        if bad:
            raise RuntimeError(
                "derivatives ledger state disagrees with its manifest — a "
                "previous run almost certainly crashed mid-write:\n  "
                + "\n  ".join(bad)
                + f"\nInspect {self.state_dir}; restore the last good copy or "
                  "delete the state dir and replay.")

    def _recover_leg_meta(self):
        meta = {}
        for frame, col in ((self.positions, "meta_json"), (self.orders, "meta_json")):
            if frame.empty or col not in frame.columns:
                continue
            for _, r in frame.iterrows():
                j = r.get(col)
                if isinstance(j, str) and j and j != "nan":
                    try:
                        meta[r["instrument"]] = json.loads(j)
                    except (ValueError, TypeError):
                        pass
        return meta

    @property
    def last_date(self):
        if self.nav.empty:
            return None
        return pd.Timestamp(self.nav["date"].max())

    @property
    def cash(self):
        if self.nav.empty:
            return 0.0
        return float(self.nav.sort_values("date")["cash"].iloc[-1])

    def held(self):
        """{instrument: signed qty} as of the last recorded day (option legs
        keyed by leg-id)."""
        if self.positions.empty:
            return {}
        last = self.positions["date"].max()
        snap = self.positions[self.positions["date"] == last]
        return {r["instrument"]: float(r["qty"]) for _, r in snap.iterrows()
                if r["instrument"] != CASH and abs(float(r["qty"])) > 1e-12}

    def held_shares(self):
        """Alias so risk/monitor helpers that expect the ops name still work."""
        return self.held()

    def nav_series(self):
        if self.nav.empty:
            return pd.Series(dtype=float)
        return self.nav.sort_values("date").set_index("date")["nav"].astype(float)

    def daily_returns(self):
        if self.nav.empty:
            return pd.Series(dtype=float)
        n = self.nav.sort_values("date").set_index("date")["daily_return"]
        return n.dropna().astype(float)

    def open_orders(self):
        if self.orders.empty:
            return self.orders
        return self.orders[self.orders["status"] == "open"]

    def _multiplier(self, instrument, kind, meta):
        if kind == OPTION:
            return float((meta or {}).get("multiplier", 100.0))
        return 1.0

    # -- Edit-2 seams (REFINE_ARCHITECTURE §0.2): three thin override points
    # extracted from advance() so v2's MarginBook can add FUTURES variation
    # P&L, per-leg A1 financing, and the margin/leverage NAV columns WITHOUT
    # copying advance(). Each default body is byte-identical to the code it
    # replaced — a golden-master replay pins v1 output unchanged.

    _NAV_COLUMNS = D_NAV_COLUMNS      # MarginBook widens this

    def _position_value(self, inst, kind, q, mark, mult, meta):
        """Dollar market value of one leg for the NAV `invested` roll and the
        positions-write. Default = q*mark*mult (v1). MarginBook overrides
        FUTURES to variation-only (q*mult*(mark-entry))."""
        return q * mark * mult

    def _posted_futures_margin(self, pos, kinds):
        """Initial margin posted across FUTURES legs (0 for a pure ETF/OPTION
        sub-ledger — which the v2 kill shadow's derivatives sleeves are). Reads
        the per-leg `initial_margin_usd` off leg_meta; the base ledger carries
        no futures_specs fallback (MarginBook overrides to add one)."""
        posted = 0.0
        for inst, q in pos.items():
            if kinds.get(inst) == FUTURES:
                m = self.leg_meta.get(inst, {}) or {}
                im = float(m.get("initial_margin_usd", 0.0) or 0.0)
                posted += im * abs(float(q))
        return posted

    def _accrue_financing(self, asof, pos, marks, kinds, cash, short_mv,
                          neg_cash, costs, fin_daily):
        """Daily financing charge and any extra bookkeeping.

        Default (no FinancingModel wired in) = the flat `financing_spread_bp` on
        (short MV + negative cash), returned with an empty extras dict (v1 —
        byte-for-byte unchanged for every existing caller).

        When `self.financing` is set, the flat accrual is replaced by the SAME
        per-leg A1 dispatch MarginBook uses, and base is handled UNIFORMLY by the
        cash leg so the model ties to the credit_hedged.py reduced form:

          + margin_debit(all-in) * |neg cash|      borrowed cash pays base+spread
          - base(cash rate)      * max(cash, 0)     positive cash — uninvested
                                                    capital AND short proceeds —
                                                    EARNS the base rate
          + fee_spread(short_etf) * short MV        a short pays only its borrow
                                                    FEE over base (base on its
                                                    collateral is captured by the
                                                    cash-interest credit above)
          + fee_spread(futures_carry) * posted margin   carry spread over base

        where fee_spread(leg) = daily_rate(leg) - daily_rate('cash'). A
        cash-collateralized short therefore nets to ~its fee (base cancels via
        the cash credit); a levered long that drives cash negative still pays the
        all-in margin-loan rate on the borrow. MarginBook delegates here (its
        _posted_futures_margin override adds the futures_specs fallback)."""
        if self.financing is None:
            return fin_daily * (short_mv + neg_cash), {}
        fm = self.financing
        base = fm.daily_rate(asof, "cash")          # base rate (spread 0)
        total = 0.0
        # Borrowed cash pays the all-in margin-loan rate (base + margin spread).
        if neg_cash > 0:
            total += fm.daily_rate(asof, "margin_debit") * neg_cash
        # Positive cash EARNS the base rate (this is the leg the shipped ledger
        # was missing — uninvested capital and short proceeds both earn base).
        pos_cash = max(cash, 0.0)
        if pos_cash > 0:
            total -= base * pos_cash
        # A short pays ONLY its borrow fee SPREAD over base, not the all-in rate.
        if short_mv > 0:
            total += (fm.daily_rate(asof, "short_etf") - base) * short_mv
        # Posted futures margin carries only its spread over base, likewise.
        posted = self._posted_futures_margin(pos, kinds)
        if posted > 0:
            total += (fm.daily_rate(asof, "futures_carry") - base) * posted
        return float(total), {"posted_futures_margin": posted}

    def _margin_and_rollup(self, asof, pos, marks, kinds, cash, invested,
                           nav_today, short_mv, neg_cash, fin_extra):
        """Margin requirement + any extra NAV columns. Default = margin==short
        MV and nothing else (v1). MarginBook overrides to compute margin_req,
        collateral_equity, margin_util, gross/net leverage."""
        return {"margin": short_mv}

    # -- writing ----------------------------------------------------------

    def save(self):
        """Atomic write of the four state files then a manifest, exactly the
        ops discipline: each file to a temp name, fsync, atomic rename; manifest
        LAST. A crash leaves a complete record or a manifest that disagrees, and
        load refuses the latter."""
        payload = {"orders.csv": self.orders, "trades.csv": self.trades,
                   "positions.csv": self.positions, "nav.csv": self.nav}
        tmps = []
        for fname, frame in payload.items():
            tmp = self.state_dir / f".{fname}.tmp"
            with open(tmp, "w", newline="") as fh:
                frame.to_csv(fh, index=False, date_format="%Y-%m-%d")
                fh.flush()
                os.fsync(fh.fileno())
            tmps.append((tmp, self.state_dir / fname))
        for tmp, final in tmps:
            os.replace(tmp, final)
        manifest = {
            "version": 1,
            "written_utc": pd.Timestamp.utcnow().isoformat(),
            "files": {fname: {"rows": int(len(frame)),
                              "last_date": (str(frame["date"].max())[:10]
                                            if len(frame) and "date" in frame
                                            else None)}
                      for fname, frame in payload.items()},
        }
        mtmp = self.state_dir / ".manifest.json.tmp"
        with open(mtmp, "w") as fh:
            json.dump(manifest, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(mtmp, self.state_dir / "manifest.json")

    # -- marking ----------------------------------------------------------

    def _mark(self, instrument, kind, asof, close_row, mark_fn):
        """Price one instrument on `asof`. ETF/EQUITY -> close store; OPTION ->
        mark_fn. Returns None if unavailable (day not booked, resumable)."""
        if kind == OPTION:
            if mark_fn is None:
                return None
            meta = self.leg_meta.get(instrument, {})
            # A neutral LONG/1-contract carrier: a price mark is side-independent
            # and greeks_fn reads strike/opt_type/side from meta, not qty.
            pt = PositionTarget(instrument=instrument, side=LONG, kind=OPTION,
                                qty=1.0, meta=meta)
            px = mark_fn(asof, pt)
            return None if px is None or not np.isfinite(px) else float(px)
        px = float(close_row.get(instrument, np.nan))
        return px if np.isfinite(px) and px > 0 else None

    # -- the daily loop ---------------------------------------------------

    def advance(self, prices, spec, costs, target_fn, through, start=None,
                mark_fn=None, verbose=True):
        """Process every trading day after last_date up to `through`.

        `target_fn(spec, d, market_prices) -> list[PositionTarget]` supplies the
        desired book on decision day d. Order: (1) distributions/borrow-side
        dividend on ETF legs, (2) fill yesterday's orders at today's close/mark,
        (3) mark, accrue short financing, write NAV, (4) decide tomorrow.
        """
        px = ops_common.wide(prices, "close")
        dv = ops_common.wide(prices, "dividend").reindex_like(px).fillna(0.0)
        vol = ops_common.wide(prices, "volume").reindex_like(px).fillna(0.0)
        vol_bp = ops_common.impact_vol_bp(prices)
        through = pd.Timestamp(through)

        calendar = px.index[px.index <= through]
        if len(calendar) == 0:
            raise ValueError(f"price store has no bars on or before {through.date()}")

        capital = float(spec.get("capital_usd", spec.get("book_usd", 0.0)))
        fin_bp = float(costs.get("financing_spread_bp", 0.0))
        fin_daily = fin_bp / 1e4 / TRADING_DAYS

        funding_run = self.last_date is None
        if funding_run:
            first = pd.Timestamp(start) if start is not None else calendar[0]
            todo = calendar[calendar >= first]
            cash = capital
            if verbose and len(todo):
                print(f"[deriv-ledger] EMPTY ledger — funding with "
                      f"{ops_common.money(capital)} on {todo[0].date()}")
        else:
            todo = calendar[calendar > self.last_date]
            cash = self.cash

        if len(todo) == 0:
            if verbose:
                print(f"[deriv-ledger] nothing to do: recorded through "
                      f"{self.last_date.date()}, asof {through.date()}. NO-OP.")
            return {"n_days": 0, "n_fills": 0, "no_op": True,
                    "last_date": self.last_date}

        pos = self.held()                              # instrument -> signed qty
        prev_nav = (float(self.nav_series().iloc[-1]) if not self.nav.empty else None)
        decided = self._decided_days()

        new_pos, new_nav, new_trades, new_orders = [], [], [], []
        n_fills = 0

        for d in todo:
            close = px.loc[d]

            # -- kinds for currently-held legs --------------------------------
            kinds = {inst: self.leg_meta.get(inst, {}).get("kind", ETF) for inst in pos}

            # -- 0. refuse to book a day we cannot price ----------------------
            unpriceable = []
            for inst, q in pos.items():
                if self._mark(inst, kinds.get(inst, ETF), d, close, mark_fn) is None:
                    unpriceable.append(inst)
            if unpriceable:
                if verbose:
                    print(f"[deriv-ledger] STOPPING at {d.date()}: no usable mark "
                          f"for {sorted(unpriceable)}. Nothing booked; resumable.")
                break

            # -- 1. distributions on ETF legs (short pays them away) ----------
            dist = 0.0
            for inst, q in pos.items():
                if kinds.get(inst, ETF) in (ETF, EQUITY) and inst in dv.columns:
                    dvd = float(dv.loc[d, inst])
                    if np.isfinite(dvd):
                        dist += q * dvd            # long receives, short pays
            cash += dist

            # -- 2. fill yesterday's orders at today's close/mark -------------
            day_cost, day_traded = 0.0, 0.0
            pending = self._pending_before(d, new_orders)
            for order in self._combo_sorted(pending):
                fill = self._fill_order(order, d, close, vol, vol_bp, costs, mark_fn)
                if fill is None:
                    self._close_order(order, "skipped", d)
                    continue
                inst = order["instrument"]
                pos[inst] = pos.get(inst, 0.0) + fill["signed_qty"]
                if abs(pos[inst]) < 1e-9:
                    pos.pop(inst, None)
                cash -= fill["cash_delta"]
                cash -= float(costs["commission_usd_per_trade"])
                day_cost += fill["cost_usd"]
                day_traded += abs(fill["notional_usd"])
                self._close_order(order, "filled", d)
                new_trades.append(fill["row"])
                n_fills += 1

            # -- 3. mark, accrue financing, write NAV (via Edit-2 seams) ------
            kinds = {inst: self.leg_meta.get(inst, {}).get("kind", ETF) for inst in pos}
            marks, mults = {}, {}
            invested = 0.0
            short_mv = 0.0
            for inst, q in sorted(pos.items()):
                kind = kinds.get(inst, ETF)
                mark = self._mark(inst, kind, d, close, mark_fn)
                mult = self._multiplier(inst, kind, self.leg_meta.get(inst))
                marks[inst], mults[inst] = mark, mult
                mv = self._position_value(inst, kind, q, mark, mult,
                                          self.leg_meta.get(inst))
                invested += mv
                # Stock-borrow financing accrues only on borrowable positions —
                # a short ETF/EQUITY leg. A short OPTION is a written premium
                # (a credit), NOT a borrowed asset, so it is never charged
                # stock-borrow; charging it would (a) be a modeling artifact and
                # (b) break the c2b short-vol reproduction to the penny.
                if q < 0 and kind in (ETF, EQUITY):
                    short_mv += abs(mv)
            neg_cash = max(0.0, -cash)
            financing, fin_extra = self._accrue_financing(
                d, pos, marks, kinds, cash, short_mv, neg_cash, costs, fin_daily)
            cash -= financing
            nav_today = cash + invested
            rollup = self._margin_and_rollup(
                d, pos, marks, kinds, cash, invested, nav_today, short_mv,
                neg_cash, fin_extra)
            margin = rollup.get("margin", short_mv)

            for inst, q in sorted(pos.items()):
                kind = kinds.get(inst, ETF)
                mark = marks[inst]
                mult = mults[inst]
                mv = self._position_value(inst, kind, q, mark, mult,
                                          self.leg_meta.get(inst))
                meta = self.leg_meta.get(inst, {})
                new_pos.append({
                    "date": d, "instrument": inst, "kind": kind,
                    "side": SHORT if q < 0 else LONG, "qty": q,
                    "multiplier": mult, "close": mark, "market_value": mv,
                    "weight": mv / nav_today if nav_today else np.nan,
                    "combo_id": meta.get("combo_id"),
                    "meta_json": json.dumps(meta) if meta else ""})
            new_pos.append({"date": d, "instrument": CASH, "kind": "CASH",
                            "side": "", "qty": np.nan, "multiplier": np.nan,
                            "close": np.nan, "market_value": cash,
                            "weight": cash / nav_today if nav_today else np.nan,
                            "combo_id": None, "meta_json": ""})
            ret = (nav_today / prev_nav - 1.0) if prev_nav else np.nan
            prev_nav = nav_today

            # -- 4. decide tomorrow's order -----------------------------------
            reason = "funding" if (funding_run and d == todo[0]) else "target"
            decided.add(pd.Timestamp(d))
            targets = target_fn(spec, d, prices)
            new_orders.extend(self._make_orders(d, targets, pos, close, nav_today,
                                                spec, reason, verbose=verbose))

            nav_row = {"date": d, "nav": nav_today, "cash": cash,
                       "invested": invested, "distributions_usd": dist,
                       "cost_usd": day_cost, "traded_usd": day_traded,
                       "financing_usd": financing, "margin": margin,
                       "daily_return": ret, "decision": reason}
            # extra columns a subclass rollup adds (margin_req, leverage, ...);
            # `margin` is already placed, so it is not double-written here.
            for _k, _v in rollup.items():
                if _k != "margin":
                    nav_row[_k] = _v
            new_nav.append(nav_row)

        self.positions = _concat(self.positions, new_pos, D_POSITION_COLUMNS)
        self.nav = _concat(self.nav, new_nav, self._NAV_COLUMNS)
        self.trades = _concat(self.trades, new_trades, D_TRADE_COLUMNS)
        self.orders = _concat(self.orders, new_orders, D_ORDER_COLUMNS)
        self.save()

        if verbose and len(new_nav):
            print(f"[deriv-ledger] processed {len(new_nav)} day(s) "
                  f"{todo[0].date()}..{pd.Timestamp(new_nav[-1]['date']).date()} | "
                  f"{n_fills} fill(s) | NAV {ops_common.money(prev_nav)}")
        return {"n_days": len(new_nav), "n_fills": n_fills,
                "n_orders": len(new_orders), "no_op": False,
                "last_date": (pd.Timestamp(new_nav[-1]["date"]) if new_nav else self.last_date),
                "nav": prev_nav}

    # -- decision / orders ------------------------------------------------

    def _decided_days(self):
        if self.nav.empty or "decision" not in self.nav.columns:
            return set()
        made = self.nav[self.nav["decision"].fillna("").astype(str) != ""]
        return {pd.Timestamp(d) for d in made["date"]}

    def _pending_before(self, d, new_orders):
        out = [o for o in new_orders
               if o["status"] == "open" and pd.Timestamp(o["decision_date"]) < d]
        if not self.orders.empty:
            stale = self.orders[(self.orders["status"] == "open")
                                & (self.orders["decision_date"] < d)]
            for idx, r in stale.iterrows():
                o = r.to_dict()
                o["_stored_row"] = idx
                out.append(o)
        return out

    def _close_order(self, order, status, fill_date):
        order["status"] = status
        order["fill_date"] = fill_date
        if "_stored_row" in order:
            self.orders.loc[order["_stored_row"], "status"] = status
            self.orders.loc[order["_stored_row"], "fill_date"] = fill_date

    @staticmethod
    def _combo_sorted(orders):
        """Sells before buys (proceeds fund buys); legs of one combo_id stay
        adjacent so an atomic combo fills together within a day."""
        return sorted(orders, key=lambda o: (str(o.get("combo_id") or ""),
                                             float(o["delta_qty"])))

    def _make_orders(self, d, targets, pos, close, nav_today, spec, reason="",
                     verbose=True):
        """Diff the sleeve's signed target book against current signed
        positions; write an order per leg whose delta clears min_trade."""
        min_trade = float(spec.get("rebalance", {}).get("min_trade_usd", 0.0))
        desired = {}
        for pt in targets:
            mult = self._multiplier(pt.instrument, pt.kind, pt.meta)
            if pt.side == FLAT:
                tqty = 0.0
            elif pt.qty is not None:
                tqty = pt.signed_qty()
            elif pt.weight is not None:
                price = float(close.get(pt.instrument, np.nan))
                if not np.isfinite(price) or price <= 0:
                    continue
                mag = math.floor(nav_today * abs(float(pt.weight)) / (price * mult))
                tqty = -mag if pt.side == SHORT else mag
            else:
                continue
            desired[pt.instrument] = tqty
            # remember leg descriptors so marks/financing survive restarts.
            # MERGE over any stored meta instead of replacing it (2026-07-26
            # integration fix): a FLAT/exit target built without meta must
            # never downgrade what entry stamped — dropping a bond leg's
            # odd_lot_cost block would let the EXIT side bypass the measured
            # odd-lot model (the 'cost model bypassed on one side' failure
            # class), and dropping kind/multiplier would mis-price the close.
            # Keys the new target explicitly carries still win.
            meta = {**(self.leg_meta.get(pt.instrument) or {}),
                    **(pt.meta or {})}
            meta.setdefault("kind", pt.kind)
            meta.setdefault("multiplier", mult)
            if pt.combo_id is not None:
                meta.setdefault("combo_id", pt.combo_id)
            meta.setdefault("side", pt.side)
            self.leg_meta[pt.instrument] = meta
        for inst in pos:
            if inst != CASH and inst not in desired:
                desired[inst] = 0.0

        rows = []
        for inst in sorted(desired):
            meta = self.leg_meta.get(inst, {})
            kind = meta.get("kind", ETF)
            mult = self._multiplier(inst, kind, meta)
            price = float(close.get(inst, np.nan)) if kind != OPTION else np.nan
            current = float(pos.get(inst, 0.0))
            target_qty = float(desired[inst])
            delta = target_qty - current
            ref_price = price if np.isfinite(price) else 1.0
            if abs(delta) * ref_price * mult < min_trade and kind != OPTION:
                continue
            if abs(delta) < 1e-9:
                continue
            side = SHORT if delta < 0 else LONG
            rows.append({"decision_date": d, "instrument": inst, "kind": kind,
                         "current_qty": current, "target_qty": target_qty,
                         "delta_qty": float(delta),
                         "decision_price": price, "multiplier": mult,
                         "combo_id": meta.get("combo_id"), "side": side,
                         "reason": reason, "status": "open", "fill_date": pd.NaT,
                         "meta_json": json.dumps(meta) if meta else ""})
        if verbose and rows:
            desc = ", ".join(f"{r['instrument']} {r['delta_qty']:+.0f}" for r in rows)
            print(f"[deriv-ledger] {d.date()} [{reason}]: {desc} (fills next close)")
        return rows

    # -- fills ------------------------------------------------------------

    def _odd_lot_fill(self, order, d, close):
        """ADDITIVE odd-lot bond cost model (build B1, FORCED_FLOW_PREREG
        decision 1) — default OFF.

        Returns a fill dict ONLY for a leg whose meta carries an ENABLED
        ``odd_lot_cost`` block (stamped by a sleeve from its spec via
        ``src.deploy.lib.odd_lot.leg_meta``); every existing book has no such
        meta, gets None here, and takes the unchanged fill paths below
        byte-for-byte. When enabled, the leg fills at the close shifted by
        the measured per-side odd-lot rate (1.45%/2 standard, 8.6%/2 sub-20c
        round trips — results/S1_BOND_LEVEL.md), charged at entry AND exit.
        This REPLACES the ETF half-spread+impact pricing for the leg (the
        odd-lot round trip is the whole measured friction, and a bond CUSIP
        has no config/costs.yaml entry). IBKR/paper fills for such legs are
        recorded out-of-band (odd_lot.record_broker_fill) and never drive
        P&L: this simulated ledger is the P&L source of record."""
        inst = order["instrument"]
        meta = self.leg_meta.get(inst) or {}
        cfg = meta.get("odd_lot_cost")
        if not (isinstance(cfg, dict) and cfg.get("enabled")):
            return None
        kind = order.get("kind", ETF)
        if kind in (OPTION, FUTURES):
            raise ValueError(
                f"odd_lot_cost meta on {inst!r} with kind={kind!r}: the "
                "odd-lot model prices cash bond legs only (kind ETF/EQUITY)")
        delta = float(order["delta_qty"])
        if delta == 0:
            return None
        mult = float(order.get("multiplier", 1.0) or 1.0)
        price = float(close.get(inst, np.nan))
        if not np.isfinite(price) or price <= 0:
            return None                    # skipped, resumable (ETF semantics)
        from .v2.odd_lot import odd_lot_fill_price   # lazy: v1 import graph unchanged
        fp = odd_lot_fill_price(cfg, delta, price, mult)
        if fp is None:
            return None
        fill_price = fp["fill_price"]
        cost_usd = fp["cost_usd"]
        cash_delta = delta * fill_price * mult
        notional = delta * fill_price * mult
        reason = (str(order.get("reason", ""))
                  + f" [odd_lot {fp['tier']} rt={fp['round_trip_pct']:.2f}%]").strip()
        row = {"fill_date": d,
               "decision_date": pd.Timestamp(order["decision_date"]),
               "instrument": inst, "kind": kind,
               "side": "BUY" if delta > 0 else "SELL",
               "qty": abs(delta), "multiplier": mult,
               "decision_price": float(order.get("decision_price", np.nan)),
               "close_price": price, "fill_price": fill_price,
               "cost_usd": cost_usd, "notional_usd": notional,
               "combo_id": order.get("combo_id"), "reason": reason}
        return {"signed_qty": delta, "cash_delta": cash_delta,
                "cost_usd": cost_usd, "notional_usd": notional, "row": row}

    def _fill_order(self, order, d, close, vol, vol_bp, costs, mark_fn):
        inst = order["instrument"]
        kind = order.get("kind", ETF)
        delta = float(order["delta_qty"])
        mult = float(order.get("multiplier", 1.0) or 1.0)
        if delta == 0:
            return None

        # Odd-lot bond legs (meta-flagged, default OFF) fill via the measured
        # odd-lot model instead of the ETF/OPTION paths below.
        odd = self._odd_lot_fill(order, d, close)
        if odd is not None:
            return odd

        if kind == OPTION:
            meta = self.leg_meta.get(inst, {})
            side = LONG if delta > 0 else SHORT
            pt = PositionTarget(instrument=inst, side=side, kind=OPTION,
                                qty=float(delta), meta=meta)
            mark = mark_fn(d, pt) if mark_fn is not None else None
            if mark is None or not np.isfinite(mark):
                return None
            hs = self.option_half_spread_usd
            sign = 1.0 if delta > 0 else -1.0
            fill_price = float(mark) + sign * hs      # buy pays up, sell receives less
            cost_usd = abs(delta) * mult * hs
            close_price = float(mark)
        else:
            price = float(close.get(inst, np.nan))
            dollar_vol = (float(vol.loc[d, inst]) * price
                          if inst in vol.columns and np.isfinite(price) else 0.0)
            vbp = (float(vol_bp.loc[d, inst]) if inst in vol_bp.columns
                   else fills.IMPACT_VOL_FALLBACK_BP)
            fp = fills.simulated_fill_price(delta, price, costs, inst,
                                            dollar_volume=dollar_vol, vol_bp=vbp)
            if fp is None:
                return None
            fill_price = fp["fill_price"]
            cost_usd = fp["cost_usd"]
            close_price = price

        cash_delta = delta * fill_price * mult     # +delta buy spends cash; short (delta<0) adds cash
        notional = delta * fill_price * mult
        row = {"fill_date": d, "decision_date": pd.Timestamp(order["decision_date"]),
               "instrument": inst, "kind": kind,
               "side": "BUY" if delta > 0 else "SELL",
               "qty": abs(delta), "multiplier": mult,
               "decision_price": float(order.get("decision_price", np.nan)),
               "close_price": close_price, "fill_price": fill_price,
               "cost_usd": cost_usd, "notional_usd": notional,
               "combo_id": order.get("combo_id"), "reason": order.get("reason", "")}
        return {"signed_qty": delta, "cash_delta": cash_delta,
                "cost_usd": cost_usd, "notional_usd": notional, "row": row}


def _concat(old, rows, cols):
    if not len(rows):
        return old
    new = pd.DataFrame(rows, columns=cols)
    if old is None or old.empty:
        return new
    return pd.concat([old, new], ignore_index=True)
