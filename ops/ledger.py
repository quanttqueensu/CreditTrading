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
                 "notional_usd", "cost_usd", "reason"]

POSITION_COLUMNS = ["date", "ticker", "shares", "close", "market_value",
                    "weight"]

NAV_COLUMNS = ["date", "nav", "cash", "invested", "distributions_usd",
               "cost_usd", "traded_usd", "daily_return", "decision"]

CASH = "CASH"


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
            for order in self._sells_then_buys(pending):
                fill = self._simulate_fill(
                    order, d, close, vol, vol_bp, costs, cash)
                if fill is None:
                    self._close_order(order, "skipped", d)
                    continue
                t = order["ticker"]
                shares[t] = shares.get(t, 0.0) + fill["shares"]
                if abs(shares[t]) < 1e-9:
                    shares.pop(t, None)
                cash -= fill["shares"] * fill["fill_price"]
                cash -= float(costs["commission_usd_per_trade"])
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
        cost_usd = abs(delta) * abs(fill_price - price)

        cap = float(costs.get("max_participation_pct", 100.0)) / 100.0
        over_cap = bool(np.isfinite(participation) and participation > cap)
        if over_cap:
            print(f"[ledger] LIQUIDITY WARNING {d.date()} {t}: this trade is "
                  f"{participation:.1%} of the day's dollar volume, above the "
                  f"{cap:.0%} cap in config/costs.yaml. The fill is simulated "
                  "anyway and flagged — a real order this size would not fill "
                  "at the close.")

        dec_price = float(order["decision_price"])
        slip_bp = (fill_price / dec_price - 1.0) * 1e4 * side

        row = {
            "fill_date": d, "decision_date": pd.Timestamp(order["decision_date"]),
            "ticker": t, "side": "BUY" if side > 0 else "SELL",
            "shares": abs(delta), "decision_price": dec_price,
            "close_price": price, "fill_price": fill_price,
            "half_spread_bp": half_bp, "impact_bp": impact_bp,
            "slip_vs_decision_bp": slip_bp,
            "participation_pct": (participation * 100.0
                                  if np.isfinite(participation) else np.nan),
            "over_participation_cap": over_cap,
            "notional_usd": delta * fill_price, "cost_usd": cost_usd,
            "reason": order.get("reason", ""),
        }
        return {"shares": delta, "fill_price": fill_price,
                "cost_usd": cost_usd, "notional_usd": delta * fill_price,
                "row": row}
