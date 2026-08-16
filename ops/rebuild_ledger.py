"""Rebuild a shadow sub-ledger from the REAL broker executions.

WHEN TO USE THIS
----------------
Only when a ledger has lost touch with the account and cannot catch up by
advancing normally. That happened once, on 2026-07-31: a missing
`config/costs.yaml` entry crashed `Ledger.advance` mid-write, so both books
stayed frozen at their funding row while the account filled ~$2.07M gross.
`arm()` repairs the LIVE tag book from the broker every session, which is what
stops a double-buy — but it does not repair the ledger, and the ledger is what
NAV, the kill switches and the whole reported P&L are computed from. A sleeve
whose ledger says "100% cash" has every risk gate disabled.

WHAT IT DOES NOT DO
-------------------
It does not replace the ledger's modelled-cost accounting as a matter of course.
The shipped design deliberately books MODELLED fills, because paper fills are
cosmetic — generated against top-of-book with no dealer layer — and flattering
them into P&L would make the paper record worthless. That reasoning is spelled
out in `src/deploy/lib/odd_lot.py` and locked by FORCED_FLOW_PREREG decision 1.

The exception this file exists for is a ledger with NO position history at all.
There is nothing to preserve, the real executions are the only record of what
happened, and phase 0's entire mandate is to measure what real fills do to a
book with no edge in it. Booking simulated fills there would answer a question
we already know the answer to.

SAFETY
------
  * refuses to run unless the captured fills reproduce the broker's CURRENT
    position exactly — if they do not, the fill record is incomplete and a
    rebuild would invent a cost basis,
  * backs the existing state up to `_prerebuild_<timestamp>/` first,
  * writes the manifest last, exactly like `Ledger.save()`, so a crash leaves a
    detectably-inconsistent book rather than a silently wrong one.

    python3 -m ops.rebuild_ledger --books-root ops/books/phase0_live \
        --sleeve null_trader --capital 640000 --asof 2026-07-31
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from ops.ledger import (NAV_COLUMNS, POSITION_COLUMNS,  # noqa: E402
                        TRADE_COLUMNS)


def _closes(instruments, asof):
    """Last close on or before `asof` for each instrument, from the local stores."""
    asof = pd.Timestamp(asof)
    out = {}
    for path, tcol in ((REPO_ROOT / "data/rv/etf_ohlc.parquet", "ticker"),
                       (REPO_ROOT / "data/cef/cef_prices.parquet", "ticker")):
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["date", tcol, "close"])
        df = df[df[tcol].isin(instruments) & (df["date"] <= asof)]
        for t, g in df.groupby(tcol):
            row = g.sort_values("date").iloc[-1]
            prev = out.get(t)
            if prev is None or row["date"] > prev[0]:
                out[t] = (row["date"], float(row["close"]))
    missing = [t for t in instruments if t not in out]
    if missing:
        from ops import common as ops_common
        tail = ops_common.fetch_yfinance(
            missing, asof - pd.Timedelta(days=10), asof, verbose=False)
        for t, g in tail.groupby("ticker"):
            row = g.sort_values("date").iloc[-1]
            out[t] = (row["date"], float(row["close"]))
    return {t: v[1] for t, v in out.items()}


def rebuild(books_root, sleeve, capital_usd, asof, broker_positions=None,
            dry_run=False, verbose=True) -> dict:
    state = Path(books_root) / "_ibkr_shadow" / sleeve
    fills_path = state / "broker_fills.csv"
    if not fills_path.exists():
        raise SystemExit(f"no broker_fills.csv under {state} — run "
                         f"`python3 -m ops.capture_fills` first (and note that "
                         f"TWS only serves the CURRENT session's executions)")

    fills = pd.read_csv(fills_path)
    fills["signed"] = fills["qty"] * fills["side"].map({"BUY": 1, "SELL": -1})
    net = fills.groupby("instrument")["signed"].sum()
    vwap = fills.groupby("instrument").apply(
        lambda g: (g["price"] * g["qty"]).sum() / g["qty"].sum(),
        include_groups=False)

    # -- safety: the fills must explain the CURRENT broker position ---------
    if broker_positions is not None:
        bad = []
        for inst in set(net.index) | set(broker_positions):
            a = float(net.get(inst, 0.0))
            b = float(broker_positions.get(inst, 0.0))
            if abs(a - b) > 1e-6:
                bad.append(f"{inst}: fills imply {a:+,.0f} but the tag book "
                           f"holds {b:+,.0f}")
        if bad:
            raise SystemExit(
                "REFUSING to rebuild — the captured fills do not reproduce the "
                "current position, so the fill record is incomplete and any cost "
                "basis derived from it would be invented:\n  " + "\n  ".join(bad))

    asof = pd.Timestamp(asof)
    held = {t: float(q) for t, q in net.items() if abs(float(q)) > 1e-9}
    closes = _closes(sorted(held), asof)

    # Cash: start at capital, pay for buys, receive short proceeds.
    spent = sum(float(net[t]) * float(vwap[t]) for t in net.index)
    cash = float(capital_usd) - spent
    invested = sum(q * closes[t] for t, q in held.items())
    nav = cash + invested

    trades = pd.DataFrame([{
        "fill_date": asof, "decision_date": asof, "ticker": t,
        "side": "BUY" if net[t] > 0 else "SELL", "shares": abs(float(net[t])),
        "decision_price": float(vwap[t]), "close_price": closes.get(t, float(vwap[t])),
        "fill_price": float(vwap[t]), "half_spread_bp": float("nan"),
        "impact_bp": float("nan"),
        "slip_vs_decision_bp": 0.0, "participation_pct": float("nan"),
        "over_participation_cap": False,
        "notional_usd": float(net[t]) * float(vwap[t]),
        "cost_usd": 0.0,
        "reason": "rebuilt from broker executions (real fills, not modelled)",
    } for t in sorted(net.index) if abs(float(net[t])) > 1e-9],
        columns=TRADE_COLUMNS)

    prows = [{"date": asof, "ticker": t, "shares": q, "close": closes[t],
              "market_value": q * closes[t], "weight": q * closes[t] / nav}
             for t, q in sorted(held.items())]
    prows.append({"date": asof, "ticker": "CASH", "shares": None, "close": None,
                  "market_value": cash, "weight": cash / nav})
    positions = pd.DataFrame(prows, columns=POSITION_COLUMNS)

    navdf = pd.DataFrame([
        {"date": asof - pd.Timedelta(days=1), "nav": float(capital_usd),
         "cash": float(capital_usd), "invested": 0.0, "distributions_usd": 0.0,
         "cost_usd": 0.0, "traded_usd": 0.0, "daily_return": None,
         "decision": "funding"},
        {"date": asof, "nav": nav, "cash": cash, "invested": invested,
         "distributions_usd": 0.0, "cost_usd": 0.0,
         "traded_usd": float(sum(abs(net[t] * vwap[t]) for t in net.index)),
         "daily_return": nav / float(capital_usd) - 1.0,
         "decision": "rebuilt_from_broker"},
    ], columns=NAV_COLUMNS)

    if verbose:
        print(f"[rebuild] {sleeve}: {len(fills)} execution(s) -> "
              f"{len(held)} position(s)")
        print(f"[rebuild]   capital {capital_usd:>12,.2f}")
        print(f"[rebuild]   cash    {cash:>12,.2f}")
        print(f"[rebuild]   invested{invested:>12,.2f}")
        print(f"[rebuild]   NAV     {nav:>12,.2f}  "
              f"({nav/float(capital_usd)-1:+.3%} vs capital)")
    if dry_run:
        print("[rebuild] --dry-run: nothing written")
        return {"nav": nav, "cash": cash, "positions": len(held)}

    backup = state.parent / f"_prerebuild_{sleeve}_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copytree(state, backup)
    print(f"[rebuild] previous state backed up to {backup}")

    for name, frame in (("trades.csv", trades), ("positions.csv", positions),
                        ("nav.csv", navdf)):
        frame.to_csv(state / name, index=False, date_format="%Y-%m-%d")
    orders = pd.read_csv(state / "orders.csv") if (state / "orders.csv").exists() \
        else pd.DataFrame()
    if not orders.empty and "status" in orders:
        # fill_date is read back as float64 when every value was blank; assigning
        # a date string into that raises in pandas 3.
        orders["fill_date"] = orders["fill_date"].astype("object")
        orders.loc[orders["status"] == "open", "fill_date"] = str(asof.date())
        orders.loc[orders["status"] == "open", "status"] = "filled"
        orders.to_csv(state / "orders.csv", index=False)

    manifest = {"version": 1, "written_utc": pd.Timestamp.utcnow().isoformat(),
                "rebuilt_from": "broker executions (ops/rebuild_ledger.py)",
                "files": {}}
    for name, frame in (("orders.csv", orders), ("trades.csv", trades),
                        ("positions.csv", positions), ("nav.csv", navdf)):
        last = (str(frame["date"].max())[:10]
                if len(frame) and "date" in frame else None)
        manifest["files"][name] = {"rows": int(len(frame)), "last_date": last}
    (state / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[rebuild] wrote {state}")
    return {"nav": nav, "cash": cash, "positions": len(held)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--books-root", required=True)
    ap.add_argument("--sleeve", required=True)
    ap.add_argument("--capital", type=float, required=True)
    ap.add_argument("--asof", default=f"{datetime.now():%Y-%m-%d}")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check-broker", action="store_true",
                    help="verify the fills reproduce the live tag book first")
    a = ap.parse_args(argv)

    positions = None
    if a.check_broker:
        from src.deploy.broker.ibkr import IBKRBroker
        from src.deploy.portfolio import PortfolioOrchestrator
        from src.deploy.run_book import (book_price_loader, load_book_spec,
                                         wire_runtime)
        book = next(Path(a.books_root).resolve().parent.glob("*_book.json"))
        for cand in Path(a.books_root).resolve().parent.glob("*_book.json"):
            spec = json.loads(cand.read_text())
            if any(s.get("name") == a.sleeve for s in spec.get("sleeves", [])):
                book = cand
                break
        spec = load_book_spec(str(book))
        ev = wire_runtime(spec, verbose=False)
        br = IBKRBroker(books_root=a.books_root, verbose=False, client_id=110)
        br.connect()
        try:
            PortfolioOrchestrator(spec, br, books_root=a.books_root, events=ev,
                                  price_loader=book_price_loader, verbose=False)
            br.arm()
            positions = br.sync_positions(a.sleeve)
        finally:
            br.disconnect()

    rebuild(a.books_root, a.sleeve, a.capital, a.asof,
            broker_positions=positions, dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
