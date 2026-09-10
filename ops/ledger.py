"""Persistent position / trade ledger for the paper-trading simulator.

The whole point of this file is that it is the only thing that writes state,
and that it can never write the same day twice. Everything it knows lives in
four CSVs under ops/state/, all of which a human can open in a spreadsheet:

    orders.csv     one row per decision (what we WANTED to trade, and at what
                   price we decided), status open -> filled/skipped
    trades.csv     one row per simulated fill (what we actually got, and the
                   slippage against the decision price)
    positions.csv  daily snapshot of shares held and their market value
    nav.csv        daily book value, cash, distributions, costs, daily return

How a day is processed, in this order:

    1. credit distributions on shares held into the previous close
    2. fill any order decided yesterday, at TODAY's close +/- half the
       configured spread, plus square-root-law market impact
    3. mark everything at today's close and write the NAV row
    4. if today is a rebalance decision day, write tomorrow's order

Step 2 before step 3 is deliberate: the fill price and the mark price are the
same close, so the spread and impact show up immediately as a small NAV hit.
That is what they are.

IDEMPOTENCE. ``Ledger.advance`` only ever processes dates strictly after the
last date already in nav.csv. Re-running on the same day is a no-op and says
so. Nothing here rewrites history.
"""

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import common

ORDER_COLUMNS = ["decision_date", "ticker", "current_shares", "target_shares",
                 "delta_shares", "decision_price", "target_weight",
                 "reason", "status", "fill_date"]

TRADE_COLUMNS = ["fill_date", "decision_date", "ticker", "side", "shares",
                 "decision_price", "close_price", "fill_price",
                 "half_spread_bp", "impact_bp", "slip_vs_decision_bp",
                 "participation_pct", "over_participation_cap",
                 "notional_usd", "cost_usd", "reason",
                 "modelled_fill_price", "exec_ids"]

# `modelled_fill_price` and `exec_ids` were added 2026-09-10 with the real-fill
# path (see `Ledger.execution_record`). Both are written by BOTH fill paths, so
# the column means the same thing in every row:
#
#   modelled_fill_price  what `_simulate_fill` WOULD have charged. On the
#                        simulated path it equals `fill_price` by construction.
#                        On the real-fill path it is the counterfactual, and it
#                        is what keeps KILL RULE (b) computable: `slippage_report`
#                        measures realised against modelled, and once `fill_price`
#                        carries the broker's own price the two would otherwise be
#                        identical by construction, `excess_bp` would be exactly
#                        0.0 on every row, and the rule could never trip again. A
#                        kill rule that cannot fire is worse than none, because it
#                        reports "1.00x" forever and reads like evidence.
#   exec_ids             ";"-joined IBKR execIds backing the row, "" on the
#                        simulated path. This is what makes "no booked fill
#                        without an execution" auditable after the fact rather
#                        than only enforced at write time.

POSITION_COLUMNS = ["date", "ticker", "shares", "close", "market_value",
                    "weight"]

NAV_COLUMNS = ["date", "nav", "cash", "invested", "distributions_usd",
               "cost_usd", "traded_usd", "daily_return", "decision"]

CASH = "CASH"


class NoCommissionReport(RuntimeError):
    """A real execution arrived with no commission we could read.

    Raised rather than defaulted. `cost_usd` and the cash leg are computed from
    the commission, so substituting `costs['commission_usd_per_trade']` here
    would charge a configured guess against a real trade and label it realised —
    the same shape as the `fee.fillna(fee.median())` this repo has already been
    bitten by, and just as invisible inside a confident-looking total.
    """


class ExecutionRecordGap(RuntimeError):
    """The ledger must book a fill on a date the execution record cannot answer for.

    `ib.fills()` serves the CURRENT TWS session only; it cannot reach back past
    the daily restart, and there is no historical execution endpoint that can.
    So a ledger that has fallen behind CANNOT be caught up from the broker, and
    the two ways of continuing are both wrong: booking simulated fills for the
    uncovered day rebuilds the exact fault the real-fill path was written to
    stop, and booking them `skipped` asserts that nothing traded, which we do
    not know either. Stop instead, and rebuild from the captured record
    (`python3 -m ops.rebuild_ledger`), which is durable and does reach back.
    """


class Execution:
    """One broker execution, as the ledger needs it.

    `qty` is UNSIGNED, exactly as IBKR reports it; `side` carries the sign.
    Keeping the broker's own convention here rather than normalising at the
    edges means a mis-signed short shows up as an assertion in one place
    instead of as a plausible-looking position.
    """

    __slots__ = ("instrument", "side", "qty", "price", "commission", "exec_id")

    def __init__(self, instrument, side, qty, price, commission, exec_id):
        self.instrument = str(instrument)
        self.side = str(side).upper()
        self.qty = abs(float(qty))
        self.price = float(price)
        self.commission = None if commission is None else float(commission)
        self.exec_id = str(exec_id)

    @property
    def signed_qty(self):
        return self.qty if self.side.startswith("B") else -self.qty


class ExecutionRecord:
    """What the broker actually executed, keyed by (instrument, date).

    WHY THE LEDGER TAKES THIS AT ALL (2026-09-10)
    ---------------------------------------------
    Until today the shadow sub-ledger was handed the sleeve's TARGETS and never
    its fills (`IBKRBroker.place_targets` -> `Simulator.place_targets`), so it
    filled every pending order at the next close by construction. It could not
    tell a rejected order from an executed one, and it did not try. On
    2026-09-10 `null_trader` booked fourteen orders as `filled`; five of them —
    EMB +57, HYG +605, JAAA -1503, JNK +420, LQD +861 — had **zero** executions
    at the broker and nothing resting, and the remaining nine each disagreed
    with the broker by 1 to 5 shares. The day's nav.csv row charged
    cost_usd $291.68 and traded_usd $941,272 against that. The invented
    1,503-share JAAA short is what `ops/HALT_phase0_null.md` exists for.

    Every execId this returns has been reported by the broker. An instrument
    with no entry did not trade, and `_broker_fill` closes its order `skipped`
    rather than inventing one.

    ATTRIBUTION IS THE CALLER'S JOB. This object is built per-sleeve and holds
    only that sleeve's executions; it has no view of the other books sharing
    the account, so it cannot and does not resolve a shared ticker. See
    `IBKRBroker._execution_record` for how the sleeve's rows are selected.
    """

    def __init__(self, source="", covers=()):
        self._by_key = {}
        self.source = str(source)
        #: The dates this record can speak to. NOT the dates it happens to hold
        #: executions for -- those are two different claims, and conflating them
        #: is what would let "the broker reports nothing for LQD today" and "we
        #: cannot see today" produce the same, silently wrong, answer.
        self.covers = {pd.Timestamp(c).normalize() for c in covers}

    def covers_date(self, date):
        return pd.Timestamp(date).normalize() in self.covers

    def add(self, execution, date):
        key = (str(execution.instrument), pd.Timestamp(date).normalize())
        self._by_key.setdefault(key, []).append(execution)

    def executions(self, instrument, date):
        """Executions for this instrument on this date. [] means it did not trade."""
        return list(self._by_key.get(
            (str(instrument), pd.Timestamp(date).normalize()), []))

    def dates(self):
        return sorted({k[1] for k in self._by_key})

    def exec_ids_on(self, date):
        d = pd.Timestamp(date).normalize()
        return {e.exec_id for k, v in self._by_key.items() if k[1] == d for e in v}

    def __len__(self):
        return sum(len(v) for v in self._by_key.values())


def _empty(cols):
    return pd.DataFrame(columns=cols)


def _concat(old, rows, cols):
    """Append rows to a frame, tolerating either side being empty without
    pandas complaining about dtypes it cannot infer from an empty frame."""
    if not len(rows):
        return old
    new = pd.DataFrame(rows, columns=cols)
    if old is None or old.empty:
        return new
    return pd.concat([old, new], ignore_index=True)


def _read(path, cols, date_cols):
    if not Path(path).exists():
        return _empty(cols)
    df = pd.read_csv(path)
    if df.empty:
        return _empty(cols)
    for c in date_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


class Ledger:
    """Position and trade book for one strategy, persisted under ``state_dir``."""

    #: An `ExecutionRecord`, or None for the pure simulator.
    #:
    #: None is the default and keeps every backtest, every research script and
    #: every sim-path book byte-identical: `advance` then fills from the cost
    #: model exactly as it always has. `IBKRBroker` installs one for the
    #: duration of a single shadow advance (`Simulator.place_targets`), and the
    #: ledger books the broker's own executions instead. It is deliberately NOT
    #: a constructor argument: a ledger that carried a fill record across calls
    #: could book the same execIds twice, and the whole point is that the record
    #: is scoped to the one advance that has just queried the broker.
    execution_record = None

    def __init__(self, state_dir=common.DEFAULT_STATE_DIR):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.orders = _read(self.state_dir / "orders.csv", ORDER_COLUMNS,
                            ["decision_date", "fill_date"])
        self.trades = _read(self.state_dir / "trades.csv", TRADE_COLUMNS,
                            ["fill_date", "decision_date"])
        self.positions = _read(self.state_dir / "positions.csv",
                               POSITION_COLUMNS, ["date"])
        self.nav = _read(self.state_dir / "nav.csv", NAV_COLUMNS, ["date"])
        self._verify_manifest()

    def _verify_manifest(self):
        """Refuse to open a book whose files disagree with their manifest.

        save() writes the manifest last, so a mismatch means a previous run
        died mid-write. Continuing from a half-written book silently invents
        P&L, so this raises instead — noisy and recoverable beats quiet and
        permanent.
        """
        path = self.state_dir / "manifest.json"
        if not path.exists():
            return          # first run, or a book written before manifests
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
                bad.append(f"{fname}: manifest says {expected.get('rows')} "
                           f"rows, file has {len(frame)}")
        if bad:
            raise RuntimeError(
                "ledger state is inconsistent with its manifest — a previous "
                "run almost certainly crashed mid-write:\n  "
                + "\n  ".join(bad)
                + f"\nManifest written {manifest.get('written_utc')}. Do NOT "
                  "continue from this book: inspect the files in "
                  f"{self.state_dir}, restore the last good copy, or delete "
                  "the state directory and replay from the start.")

    # -- state ------------------------------------------------------------

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

    def held_shares(self):
        """{ticker: shares} as of the last recorded day."""
        if self.positions.empty:
            return {}
        last = self.positions["date"].max()
        snap = self.positions[self.positions["date"] == last]
        return {r["ticker"]: float(r["shares"]) for _, r in snap.iterrows()
                if abs(float(r["shares"])) > 0}

    def open_orders(self):
        if self.orders.empty:
            return self.orders
        return self.orders[self.orders["status"] == "open"]

    def daily_returns(self):
        """Live daily net return series (Series indexed by date)."""
        if self.nav.empty:
            return pd.Series(dtype=float)
        n = self.nav.sort_values("date").set_index("date")["daily_return"]
        return n.dropna().astype(float)

    def nav_series(self):
        if self.nav.empty:
            return pd.Series(dtype=float)
        return self.nav.sort_values("date").set_index("date")["nav"].astype(float)

    # -- writing ----------------------------------------------------------

    def save(self):
        """Write the four state files, then a manifest describing them.

        These four files are ONE record. Writing them in sequence means a
        crash between two writes leaves the book internally inconsistent —
        and the failure is silent and permanent, because nothing on the next
        run notices. A reproduced crash mid-write invented $271.22 of profit,
        more than a year of this strategy's entire expected edge.

        So: every file is written to a temporary name, flushed to disk, and
        atomically renamed into place. The manifest is written LAST and holds
        each file's row count and last date. A crash therefore leaves either a
        complete record or a manifest that disagrees with the files — and
        load() refuses to open a disagreeing set rather than trusting it.
        """
        payload = {
            "orders.csv": self.orders,
            "trades.csv": self.trades,
            "positions.csv": self.positions,
            "nav.csv": self.nav,
        }
        tmps = []
        for fname, frame in payload.items():
            tmp = self.state_dir / f".{fname}.tmp"
            with open(tmp, "w", newline="") as fh:
                frame.to_csv(fh, index=False, date_format="%Y-%m-%d")
                fh.flush()
                os.fsync(fh.fileno())
            tmps.append((tmp, self.state_dir / fname))
        for tmp, final in tmps:
            os.replace(tmp, final)          # atomic per file

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

    # -- the daily loop ---------------------------------------------------

    def advance(self, prices, spec, costs, target_weights_fn, through,
                start=None, verbose=True):
        """Process every trading day in the price store after ``last_date``,
        up to and including ``through``.

        Returns a dict summarising what happened (n_days, n_fills, ...).
        """
        px = common.wide(prices, "close")
        dv = common.wide(prices, "dividend").reindex_like(px).fillna(0.0)
        vol = common.wide(prices, "volume").reindex_like(px).fillna(0.0)
        vol_bp = common.impact_vol_bp(prices)
        through = pd.Timestamp(through)

        calendar = px.index[px.index <= through]
        if len(calendar) == 0:
            raise ValueError(
                f"price store has no bars on or before {through.date()} — "
                "fetch prices before advancing the ledger")

        book = float(spec["book_usd"])
        funding_run = self.last_date is None
        if funding_run:
            first = pd.Timestamp(start) if start is not None else calendar[0]
            todo = calendar[calendar >= first]
            cash = book
            if verbose and len(todo):
                print(f"[ledger] EMPTY ledger — funding with "
                      f"{common.money(book)} on {todo[0].date()}")
        else:
            todo = calendar[calendar > self.last_date]
            cash = self.cash

        if len(todo) == 0:
            if verbose:
                print(f"[ledger] nothing to do: ledger already recorded through "
                      f"{self.last_date.date()}, asof is {through.date()}. "
                      "NO-OP.")
            return {"n_days": 0, "n_fills": 0, "n_orders": 0,
                    "no_op": True, "last_date": self.last_date}

        decided_months = self._decided_months()
        shares = self.held_shares()
        prev_nav = (float(self.nav_series().iloc[-1])
                    if not self.nav.empty else None)

        new_pos, new_nav, new_trades, new_orders = [], [], [], []
        n_fills = 0
        prev_day = self.last_date

        for d in todo:
            close = px.loc[d]

            # -- 0. refuse to book a day we cannot price -------------------
            # A missing bar for a held or targeted ticker used to propagate
            # NaN straight into positions and NAV, where it stayed for good:
            # every later return silently became NaN and the Gate S window
            # quietly shortened. Stop at the gap instead. The run is
            # resumable — fix or backfill the price and re-run, and the loop
            # picks up exactly here.
            needed = set(shares) | set(spec.get("tickers", []))
            missing = sorted(t for t in needed
                             if t != CASH
                             and (t not in close.index
                                  or not np.isfinite(float(close.get(t, np.nan)))))
            if missing:
                if verbose:
                    print(f"[ledger] STOPPING at {d.date()}: no usable close "
                          f"for {missing}. Nothing was booked for this day. "
                          "Backfill the price store and re-run — the ledger "
                          "resumes from here.")
                break

            # -- 1. distributions on shares held into today ----------------
            dist = sum(sh * float(dv.loc[d, t]) for t, sh in shares.items()
                       if t in dv.columns and np.isfinite(dv.loc[d, t]))
            cash += dist

            # -- 2. fill yesterday's order at TODAY's close ----------------
            day_cost, day_traded = 0.0, 0.0
            pending = self._pending_before(d, new_orders)
            book_fill = (self._simulate_fill if self.execution_record is None
                         else self._broker_fill)
            for order in self._sells_then_buys(pending):
                fill = book_fill(order, d, close, vol, vol_bp, costs, cash)
                if fill is None:
                    self._close_order(order, "skipped", d)
                    continue
                t = order["ticker"]
                shares[t] = shares.get(t, 0.0) + fill["shares"]
                if abs(shares[t]) < 1e-9:
                    shares.pop(t, None)
                cash -= fill["shares"] * fill["fill_price"]
                # The broker's commission when we have one, the configured
                # per-trade charge when we are simulating. Spelled out rather
                # than `.get(..., default)` so that a real fill arriving with no
                # commission cannot quietly take the configured number --
                # `_broker_fill` raises NoCommissionReport before it gets here.
                cash -= (float(costs["commission_usd_per_trade"])
                         if fill["commission_usd"] is None
                         else float(fill["commission_usd"]))
                day_cost += fill["cost_usd"]
                day_traded += abs(fill["notional_usd"])
                self._close_order(order, "filled", d)
                new_trades.append(fill["row"])
                n_fills += 1

            # -- 3. mark to today's close ----------------------------------
            invested = sum(sh * float(close[t]) for t, sh in shares.items())
            nav_today = cash + invested
            if cash < -1e-6:
                print(f"[ledger] WARNING {d.date()}: cash is negative "
                      f"({common.money(cash)}). This simulator does not "
                      "borrow; check the fill sizing.")
            for t, sh in sorted(shares.items()):
                mv = sh * float(close[t])
                new_pos.append({"date": d, "ticker": t, "shares": sh,
                                "close": float(close[t]), "market_value": mv,
                                "weight": mv / nav_today if nav_today else np.nan})
            new_pos.append({"date": d, "ticker": CASH, "shares": np.nan,
                            "close": np.nan, "market_value": cash,
                            "weight": cash / nav_today if nav_today else np.nan})
            ret = (nav_today / prev_nav - 1.0) if prev_nav else np.nan
            prev_nav = nav_today

            # -- 4. decide tomorrow's order --------------------------------
            reason = self._decision_reason(
                d, prev_day, funding_run and d == todo[0], decided_months)
            if reason:
                decided_months.add((d.year, d.month))
                targets = target_weights_fn(spec, d, prices)
                new_orders.extend(
                    self._make_orders(d, targets, shares, close, nav_today,
                                      spec, reason, verbose=verbose))

            new_nav.append({"date": d, "nav": nav_today, "cash": cash,
                            "invested": invested, "distributions_usd": dist,
                            "cost_usd": day_cost, "traded_usd": day_traded,
                            "daily_return": ret, "decision": reason or ""})
            prev_day = d

        self.positions = _concat(self.positions, new_pos, POSITION_COLUMNS)
        self.nav = _concat(self.nav, new_nav, NAV_COLUMNS)
        self.trades = _concat(self.trades, new_trades, TRADE_COLUMNS)
        self.orders = _concat(self.orders, new_orders, ORDER_COLUMNS)
        self.save()

        if verbose:
            print(f"[ledger] processed {len(todo)} trading day(s) "
                  f"{todo[0].date()}..{todo[-1].date()} | {n_fills} fill(s) | "
                  f"NAV {common.money(prev_nav)}")
        return {"n_days": len(todo), "n_fills": n_fills,
                "n_orders": len(new_orders), "no_op": False,
                "last_date": todo[-1], "nav": prev_nav}

    # -- decision calendar -------------------------------------------------

    def _decided_months(self):
        """(year, month) pairs in which a rebalance decision has already been
        made. Read back off nav.csv so the rule survives a restart."""
        if self.nav.empty or "decision" not in self.nav.columns:
            return set()
        made = self.nav[self.nav["decision"].fillna("").astype(str) != ""]
        return {(pd.Timestamp(d).year, pd.Timestamp(d).month)
                for d in made["date"]}

    @staticmethod
    def _decision_reason(d, prev_day, is_funding_day, decided_months):
        """Is ``d`` a rebalance decision day, and why?

        Three ways to say yes, in order:

        1. it is the day the book is funded;
        2. no business day is left in ``d``'s month after ``d`` — this is the
           month end, and it reads the same whether we are replaying history or
           running tonight with no future data at all;
        3. the month has just turned over and last month never got its
           rebalance. That happens when the last business day of a month was a
           market holiday (Good Friday closed March 2024, Memorial Day closed
           May 2021), so rule 2 waited for a day that never traded. The
           rebalance then happens one day late, and says so.

        Rule 2 uses business days rather than "the last date I have prices
        for", because mid-month those are the same thing and treating them as
        the same thing would rebalance the book every single day.
        """
        if is_funding_day:
            return "funding"
        if (d + pd.tseries.offsets.BDay(1)).month != d.month:
            return "month_end"
        if prev_day is not None:
            prev = pd.Timestamp(prev_day)
            if (prev.year, prev.month) != (d.year, d.month) \
                    and (prev.year, prev.month) not in decided_months:
                return f"month_end (late, {prev:%Y-%m} had no trading day left)"
        return ""

    # -- orders ------------------------------------------------------------

    def _pending_before(self, d, new_orders):
        """Orders decided strictly before ``d`` that are still open.

        Two sources: orders written earlier in this same run (plain dicts,
        mutated in place and appended at the end) and orders left open on disk
        by a previous run (tagged with their row index so the status update
        lands back on the stored frame).
        """
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
        """Mark an order filled/skipped, wherever it is being held."""
        order["status"] = status
        order["fill_date"] = fill_date
        if "_stored_row" in order:
            self.orders.loc[order["_stored_row"], "status"] = status
            self.orders.loc[order["_stored_row"], "fill_date"] = fill_date

    @staticmethod
    def _sells_then_buys(orders):
        """Sell first so the proceeds are available to the buys, the way a
        real cash account behaves."""
        return sorted(orders, key=lambda o: float(o["delta_shares"]))

    def _make_orders(self, d, targets, shares, close, nav_today, spec,
                     reason="", verbose=True):
        min_trade = float(spec["rebalance"].get("min_trade_usd", 0.0))
        rows = []
        for t in sorted(targets):
            w = float(targets[t])
            price = float(close.get(t, np.nan))
            if not np.isfinite(price) or price <= 0:
                print(f"[ledger] WARNING {d.date()}: no usable close for {t}; "
                      "no order written.")
                continue
            target_shares = math.floor(nav_today * w / price)
            current = float(shares.get(t, 0.0))
            delta = target_shares - current
            if abs(delta * price) < min_trade:
                continue
            rows.append({"decision_date": d, "ticker": t,
                         "current_shares": current,
                         "target_shares": float(target_shares),
                         "delta_shares": float(delta),
                         "decision_price": price, "target_weight": w,
                         "reason": reason,
                         "status": "open", "fill_date": pd.NaT})
        if verbose:
            if rows:
                desc = ", ".join(f"{r['ticker']} {r['delta_shares']:+.0f}sh"
                                 for r in rows)
                print(f"[ledger] {d.date()} [{reason}] rebalance: {desc} "
                      f"(fills at the next close)")
            else:
                print(f"[ledger] {d.date()} [{reason}] rebalance: no leg has "
                      f"drifted past the {common.money(min_trade)} minimum — "
                      "no order")
        return rows

    # -- fills -------------------------------------------------------------

    def _simulate_fill(self, order, d, close, vol, vol_bp, costs, cash):
        """Fill an order at today's close, adjusted for cost.

        Buy  -> close * (1 + (half_spread_bp + impact_bp)/1e4)
        Sell -> close * (1 - (half_spread_bp + impact_bp)/1e4)

        with impact_bp = impact_coefficient * daily_vol_bp * sqrt(participation),
        exactly the square-root law the engine uses (config/costs.yaml).
        """
        t = order["ticker"]
        delta = float(order["delta_shares"])
        price = float(close.get(t, np.nan))
        if not np.isfinite(price) or price <= 0 or delta == 0:
            return None

        # A buy can never spend cash the book does not have. Trim rather than
        # overdraw, and the trim shows up in the trade row as a smaller size.
        if delta > 0:
            affordable = math.floor(max(cash, 0.0) / (price * 1.01))
            if affordable < delta:
                delta = float(affordable)
            if delta <= 0:
                return None

        q = self._modelled_quote(t, d, delta, price, vol, vol_bp, costs)
        fill_price, side = q["fill_price"], q["side"]
        cost_usd = abs(delta) * abs(fill_price - price)
        dec_price = float(order["decision_price"])
        slip_bp = (fill_price / dec_price - 1.0) * 1e4 * side

        row = {
            "fill_date": d, "decision_date": pd.Timestamp(order["decision_date"]),
            "ticker": t, "side": "BUY" if side > 0 else "SELL",
            "shares": abs(delta), "decision_price": dec_price,
            "close_price": price, "fill_price": fill_price,
            "half_spread_bp": q["half_bp"], "impact_bp": q["impact_bp"],
            "slip_vs_decision_bp": slip_bp,
            "participation_pct": (q["participation"] * 100.0
                                  if np.isfinite(q["participation"]) else np.nan),
            "over_participation_cap": q["over_cap"],
            "notional_usd": delta * fill_price, "cost_usd": cost_usd,
            "reason": order.get("reason", ""),
            # Identical by construction on this path -- see TRADE_COLUMNS.
            "modelled_fill_price": fill_price,
            "exec_ids": "",
        }
        return {"shares": delta, "fill_price": fill_price,
                "cost_usd": cost_usd, "notional_usd": delta * fill_price,
                "commission_usd": None, "row": row}

    def _broker_fill(self, order, d, close, vol, vol_bp, costs, cash):
        """Book what the BROKER executed for this order, at the price it got.

        Returns the same shape as `_simulate_fill`, or None when the broker
        executed nothing — in which case `advance` closes the order `skipped`,
        which is the truth: no trade happened.

        WHAT IS REAL HERE AND WHAT IS NOT
        ---------------------------------
        Real, from the broker: that the fill happened, how many shares, at what
        price, and the commission. Modelled, and carried alongside in
        `modelled_fill_price`: what the cost model WOULD have charged.

        THE PRICE IS THE BROKER'S, BY DECISION OF THE TEAM LEAD, 2026-09-10.

        Eight files in this repo call that a violation of "FORCED_FLOW_PREREG
        locked decision 1", which they state as "the modelled cost is the sole
        P&L source". Read against the pre-registration itself, it is not.
        Decision 1 is scoped to BOND legs — "IBKR *paper* fills on bonds are
        unrealistically kind -> every bond leg is charged the measured odd-lot
        cost model in the ledger regardless of paper fill" — and no bond leg is
        deployed in any live book. The blanket reading is an over-extension that
        entered through docstrings (`ops/capture_fills.py:24`,
        `src/deploy/broker/ibkr.py:107`, `ops/rebuild_ledger.py:20`) and was
        never in the decision. Booking a real equity fill price does not touch
        it. `src/deploy/lib/odd_lot.py` still charges the bond model, unchanged,
        and `Simulator.place_targets` refuses the real-fill path for a
        DerivativesLedger, which is where a bond leg would live.

        WHAT REMAINS TRUE, AND IS NOT A GOVERNANCE POINT BUT AN ECONOMIC ONE:
        an IBKR *paper* fill is generated against top of book with no dealer
        layer, so reported P&L here is flattered by however much the paper venue
        is kinder than a real one. That amount is measurable and is exactly
        `excess_bp` in slippage.csv, which is why `modelled_fill_price` is kept
        beside the real one rather than discarded. See
        `results/ops/PREREG_AMENDMENT_REAL_FILLS_2026-09-10.md` before quoting a
        net return from this ledger.

        Note what did NOT change: `cost_usd` still means "slippage against the
        close", the same quantity it means on the simulated path, so the column
        is comparable across every row in the file. Commission is charged
        separately by `advance`, as it always was — from the broker's number
        here, from `costs['commission_usd_per_trade']` on the simulated path.
        """
        t = order["ticker"]
        price = float(close.get(t, np.nan))
        if not np.isfinite(price) or price <= 0:
            return None

        if not self.execution_record.covers_date(d):
            covered = sorted(self.execution_record.covers)
            raise ExecutionRecordGap(
                f"{d.date()} {t}: a pending order must be booked on this date, "
                f"but the execution record ({self.execution_record.source}) "
                f"covers only "
                f"{', '.join(str(c.date()) for c in covered) or '<nothing>'}. "
                f"The ledger is behind the account and cannot be caught up from "
                f"a live broker query. Rebuild it from the captured record: "
                f"python3 -m ops.rebuild_ledger --books-root <root> "
                f"--sleeve <sleeve>.")

        execs = self.execution_record.executions(t, d)
        if not execs:
            # NOT a silent skip: an order the broker never executed is the exact
            # fault this path was built for, and it must be visible in the log
            # of the session that discovered it, not only in the CSV.
            print(f"[ledger] NO EXECUTION {d.date()} {t}: the order to trade "
                  f"{float(order['delta_shares']):+,.0f} share(s) has no "
                  f"execution at the broker ({self.execution_record.source}). "
                  f"Booking it as SKIPPED, not filled. The position is "
                  f"unchanged and the next session re-diffs against it.")
            return None

        missing = [e.exec_id for e in execs if e.commission is None]
        if missing:
            raise NoCommissionReport(
                f"{d.date()} {t}: {len(missing)} of {len(execs)} execution(s) "
                f"carry no commission report ({', '.join(missing[:5])}). "
                f"cost_usd and the cash leg are computed from it; refusing to "
                f"substitute costs['commission_usd_per_trade'], which would "
                f"charge a configured guess against a real trade and report it "
                f"as realised.")

        gross = sum(e.qty for e in execs)
        if gross <= 0:
            raise ValueError(f"{d.date()} {t}: {len(execs)} execution(s) sum to "
                             f"zero shares; the fill record is malformed.")
        delta = sum(e.signed_qty for e in execs)
        if delta == 0:
            raise ValueError(
                f"{d.date()} {t}: {len(execs)} execution(s) net to zero shares "
                f"({gross:,.0f} gross). A round trip inside one fill date is not "
                f"something this ledger can represent as one trade row.")
        vwap = sum(e.price * e.qty for e in execs) / gross
        commission = sum(e.commission for e in execs)

        # Modelled counterfactual, priced on the shares that ACTUALLY traded so
        # the two are comparable. `warn=False`: see `_modelled_quote`.
        q = self._modelled_quote(t, d, delta, price, vol, vol_bp, costs,
                                 warn=False)
        side = 1.0 if delta > 0 else -1.0

        ordered = float(order["delta_shares"])
        if abs(delta - ordered) > 1e-9:
            print(f"[ledger] PARTIAL {d.date()} {t}: ordered {ordered:+,.0f}, "
                  f"broker executed {delta:+,.0f} over {len(execs)} execution(s). "
                  f"Booking what executed; the residual returns as tomorrow's "
                  f"diff against the position.")

        dec_price = float(order["decision_price"])
        cost_usd = abs(delta) * abs(vwap - price)
        slip_bp = (vwap / dec_price - 1.0) * 1e4 * side

        row = {
            "fill_date": d, "decision_date": pd.Timestamp(order["decision_date"]),
            "ticker": t, "side": "BUY" if side > 0 else "SELL",
            "shares": abs(delta), "decision_price": dec_price,
            "close_price": price, "fill_price": vwap,
            # A real fill does not decompose into spread and impact -- nothing
            # observable separates them -- so the realised total goes in
            # half_spread_bp and impact_bp is NaN, meaning "not observable",
            # never 0.0, which would read as "there was no impact".
            "half_spread_bp": (vwap / price - 1.0) * 1e4 * side,
            "impact_bp": np.nan,
            "slip_vs_decision_bp": slip_bp,
            "participation_pct": (q["participation"] * 100.0
                                  if np.isfinite(q["participation"]) else np.nan),
            "over_participation_cap": q["over_cap"],
            "notional_usd": delta * vwap, "cost_usd": cost_usd,
            "reason": order.get("reason", ""),
            "modelled_fill_price": q["fill_price"],
            "exec_ids": ";".join(e.exec_id for e in execs),
        }
        return {"shares": delta, "fill_price": vwap, "cost_usd": cost_usd,
                "notional_usd": delta * vwap, "commission_usd": commission,
                "row": row}

    def _modelled_quote(self, t, d, delta, price, vol, vol_bp, costs, warn=True):
        """The cost model's view of trading `delta` shares of `t` at `price`.

        Split out of `_simulate_fill` on 2026-09-10 because the REAL-fill path
        needs the same number as a counterfactual (`modelled_fill_price`), and
        computing it twice in two places is how the two would drift apart. The
        arithmetic is unchanged, byte for byte; only its address moved.

        `warn` is False when the caller is pricing a counterfactual rather than
        a fill — the liquidity warning describes an order we are about to
        simulate, and printing it about a trade that has ALREADY executed at a
        real price would be telling the operator to worry about the wrong thing.
        """
        half_bp = (float(costs["tickers"][t]["half_spread_bp"])
                   + float(costs["slippage_extra_bp"]))
        notional = abs(delta) * price
        dollar_vol = float(vol.loc[d, t]) * price if t in vol.columns else 0.0
        participation = notional / dollar_vol if dollar_vol > 0 else np.nan
        coef = float(costs.get("impact_coefficient", 0.0))
        vbp = float(vol_bp.loc[d, t]) if t in vol_bp.columns else common.IMPACT_VOL_FALLBACK_BP
        impact_bp = (coef * vbp * math.sqrt(participation)
                     if np.isfinite(participation) else coef * vbp)

        side = 1.0 if delta > 0 else -1.0
        fill_price = price * (1.0 + side * (half_bp + impact_bp) / 1e4)

        cap = float(costs.get("max_participation_pct", 100.0)) / 100.0
        over_cap = bool(np.isfinite(participation) and participation > cap)
        if over_cap and warn:
            print(f"[ledger] LIQUIDITY WARNING {d.date()} {t}: this trade is "
                  f"{participation:.1%} of the day's dollar volume, above the "
                  f"{cap:.0%} cap in config/costs.yaml. The fill is simulated "
                  "anyway and flagged — a real order this size would not fill "
                  "at the close.")
        return {"fill_price": fill_price, "half_bp": half_bp,
                "impact_bp": impact_bp, "participation": participation,
                "over_cap": over_cap, "side": side}
