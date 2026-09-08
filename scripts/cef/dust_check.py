"""Two checks on the CEF band's order list. Neither trades; neither writes.

    python3 scripts/cef/dust_check.py orders --signal 2026-09-03 --sizing 2026-09-04
    python3 scripts/cef/dust_check.py targets --out /tmp/targets.txt

`orders` reproduces what the next session would send, with the SIGNAL date and
the SIZING date set separately. They are the same date on a healthy day, and
they diverge whenever the price/NAV panel is a session behind the price store
(price and NAV are inner-joined; a fund's NAV publishes after its close). That
divergence is what produced the dust orders of 2026-09: the band judged held
weights on one close and the executor re-derived shares from another, so twelve
names the band had told us to leave alone each emitted a few shares as live MOC
orders. See results/cef/DUST_ORDERS_2026-09.md.

`targets` serialises every target the sleeve emits over the last five trading
days at full precision, under a spec copy with `band_width` DELETED as well as
under the live spec. Diffing the band-absent block across a code change is the
house rule for any new frozen-spec key (SYSTEM_AND_STRATEGY.md 9.1: "the code
change alone should be a provable no-op"). Run it before the change, run it
after, diff the two files.

Holdings and NAV come from the live shadow sub-ledger's CSVs, read directly:
this must not open a Ledger, whose manifest check is a separate concern.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.deploy.sleeve import FLAT, SHORT, MarketState        # noqa: E402
from src.deploy.sleeves.cef_discount import CEFDiscountSleeve, PX_PATH  # noqa: E402

SPEC_PATH = REPO / "ops/specs/cef_discount.frozen.json"
LEDGER = REPO / "ops/books/cef_live/_ibkr_shadow/cef_discount"


def _book():
    """(holdings, nav) as the executor would see them. Raises if either is
    missing — sizing a book against an invented NAV is the failure mode
    SYSTEM_AND_STRATEGY.md 9.1 opens with."""
    pos = pd.read_csv(LEDGER / "positions.csv")
    pos = pos[pos.ticker != "CASH"]
    if pos.empty:
        raise SystemExit(f"no positions in {LEDGER}/positions.csv")
    pos["date"] = pd.to_datetime(pos["date"])
    last = pos[pos["date"] == pos["date"].max()]
    held = {r.ticker: float(r.shares) for r in last.itertuples() if pd.notna(r.shares)}
    nav = pd.read_csv(LEDGER / "nav.csv")
    if nav.empty:
        raise SystemExit(f"no nav rows in {LEDGER}/nav.csv")
    return held, float(nav["nav"].iloc[-1])


def _targets(spec, asof, held, nav):
    sl = CEFDiscountSleeve(spec, nav)
    ms = MarketState(asof=asof, prices=pd.DataFrame(), holdings=dict(held),
                     extras={"sleeve_nav": nav})
    return sl.target_positions(asof, ms)


def cmd_orders(a):
    spec = json.loads(SPEC_PATH.read_text())
    if a.min_trade is not None:            # to isolate the source fix from the backstop
        spec.setdefault("rebalance", {})["min_trade_usd"] = float(a.min_trade)
    min_trade = float(spec.get("rebalance", {}).get("min_trade_usd", 0.0))
    held, nav = _book()

    P = pd.read_parquet(PX_PATH)
    P["date"] = pd.to_datetime(P["date"])
    sizing = pd.Timestamp(a.sizing or P["date"].max())
    signal = a.signal or str(sizing.date())
    close = (P[P["date"] == sizing].set_index("ticker")["close"]
             .astype(float).to_dict())
    if not close:
        raise SystemExit(f"no closes in the price store on {sizing.date()}")

    desired, why, hold = {}, {}, {}
    for pt in _targets(spec, signal, held, nav):
        why[pt.instrument] = pt.reason or ""
        hold[pt.instrument] = "band hold" in (pt.reason or "")
        if pt.side == FLAT:
            desired[pt.instrument] = 0.0
        elif pt.qty is not None:           # qty-expressed: no price round trip
            desired[pt.instrument] = float(pt.signed_qty())
        else:
            price = float(close.get(pt.instrument, float("nan")))
            if not np.isfinite(price) or price <= 0:
                continue                   # the executor skips it, loudly
            mag = math.floor(nav * abs(float(pt.weight)) / price)
            desired[pt.instrument] = float(-mag if pt.side == SHORT else mag)
    for tk in held:
        desired.setdefault(tk, 0.0)

    rows, kinds, gross = [], {}, 0.0
    for tk in sorted(desired):
        price = float(close.get(tk, float("nan")))
        cur, tgt = float(held.get(tk, 0.0)), float(desired[tk])
        delta = tgt - cur
        if abs(delta) < 1e-9:
            continue
        priced = bool(np.isfinite(price) and price > 0)
        notional = abs(delta) * price if priced else float("nan")
        if priced and notional < min_trade:
            continue
        kind = ("unpriced" if not priced else
                "exit" if cur and not tgt else
                "entry" if tgt and not cur else
                "dust" if hold.get(tk) else "rebalance")
        kinds[kind] = kinds.get(kind, 0) + 1
        gross += 0.0 if not priced else notional
        rows.append((tk, int(delta), notional, kind, why.get(tk, "")))

    print(f"signal {signal} / sizing close {sizing.date()} / "
          f"min_trade_usd {min_trade:,.0f} / nav ${nav:,.0f}")
    print(f"n_orders {len(rows)}  n_by_kind {kinds}  gross ${gross:,.0f}")
    for tk, d, n, kind, reason in sorted(rows, key=lambda r: -(r[2] if r[2] == r[2] else 0)):
        print(f"  {tk:<5} {d:+6d}sh  ${n:>9,.0f}  {kind:<9} {reason}")
    return 1 if kinds.get("dust") else 0


def cmd_targets(a):
    spec_live = json.loads(SPEC_PATH.read_text())
    spec_noband = json.loads(json.dumps(spec_live))
    spec_noband["frozen"].pop("band_width", None)
    held, nav = _book()
    P = pd.read_parquet(PX_PATH)
    P["date"] = pd.to_datetime(P["date"])
    days = sorted(P["date"].unique())[-int(a.days):]

    lines = []
    for label, spec in (("band_width ABSENT", spec_noband), ("band_width LIVE", spec_live)):
        lines.append(f"### {label}  (holdings={len(held)} names, sleeve_nav={nav!r})")
        for d in days:
            asof = str(pd.Timestamp(d).date())
            for t in _targets(spec, asof, held, nav):
                lines.append(
                    f"{asof} {t.instrument} side={t.side} kind={t.kind} "
                    f"qty={t.qty!r} weight={t.weight!r} combo={t.combo_id!r} "
                    f"meta={sorted((t.meta or {}).items())!r} reason={t.reason!r}")
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"{a.out}: {len(lines)} lines over {len(days)} days "
          f"({', '.join(str(pd.Timestamp(d).date()) for d in days)})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("orders", help="the order list, signal and sizing dates apart")
    o.add_argument("--signal", default=None, help="signal date (default: the sizing date)")
    o.add_argument("--sizing", default=None, help="close the executor sizes on "
                                                  "(default: the last in the price store)")
    o.add_argument("--min-trade", default=None,
                   help="override rebalance.min_trade_usd, to isolate the two fixes")
    o.set_defaults(fn=cmd_orders)
    t = sub.add_parser("targets", help="serialise targets for the no-op diff")
    t.add_argument("--out", required=True)
    t.add_argument("--days", default=5)
    t.set_defaults(fn=cmd_targets)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
