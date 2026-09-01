"""Capture the session's REAL broker executions before TWS forgets them.

WHY THIS IS A SEPARATE STEP AND NOT PART OF place_targets
----------------------------------------------------------
`ib.fills()` serves the CURRENT session only. TWS force-restarts daily, and at
that moment every execution it was holding becomes unrecoverable from the API —
there is no historical execution endpoint that reaches back past the restart.
So the real fill record has a hard deadline, and anything that captures it as a
side effect of a successful trading run will lose it on exactly the days that
matter most: the ones where the trading run failed.

That is not hypothetical. On 2026-07-31 the CEF sleeve transmitted 16 orders,
the shadow ledger then crashed on a missing cost entry, and the process exited.
302 executions existed in TWS and none of them were written anywhere. The
ledger was later advanced with SIMULATED fills, so the book now reports modelled
prices for trades that really happened at different ones.

Hence: an independent capture that runs at the END of every session regardless
of whether the trading step succeeded, was skipped, or never armed.

WHAT IT IS FOR (and what it is NOT for)
---------------------------------------
This is a side channel. Nothing here feeds P&L — the shadow ledger with its
modelled cost stays the sole P&L source, per FORCED_FLOW_PREREG locked decision
1 and the reasoning in `src/deploy/lib/odd_lot.py`: paper fills are cosmetic,
generated against top-of-book with no dealer layer, and are unrealistically kind.

It exists so that two questions have answers:

  1. **Kill rule (b)** — "realised slippage > 2x modelled for 5 consecutive
     sessions" is uncheckable without a realised number. Until now we had none.
  2. **Phase 0's entire mandate** — the null trader exists to measure what real
     fills do to a book with no edge. Simulated fills answer a question we
     already knew the answer to.

Run it standalone (safe, read-only against the broker):

    python3 -m ops.capture_fills --book ops/books/cef_discount_book.json \
                                 --books-root ops/books/cef_live
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def sleeve_universes(book_path) -> dict:
    """{sleeve_name: set(instruments)} for the enabled sleeves of one book."""
    from ops.preflight import deployed_tickers
    return {k: set(v) for k, v in deployed_tickers(book_path).items()}


def capture(book_path, books_root, client_id=None, asof=None, verbose=True) -> dict:
    """Pull every execution TWS still holds and file it under the owning sleeve.

    Attribution is by SYMBOL, not by `orderRef`. The adapter tags orders with an
    orderRef, but every execution actually returned on 2026-07-31 carried
    `ref=''` — the tag does not survive the round trip on this TWS build. Symbol
    attribution is unambiguous here because no two deployed sleeves share a
    ticker (checked below, and loudly refused if that ever stops being true).
    """
    import ib_async as ibapi

    from src.deploy.broker.ibkr import IBKRConfig
    from src.deploy.lib.odd_lot import record_broker_fill

    asof = asof or f"{datetime.now():%Y-%m-%d}"
    universes = sleeve_universes(book_path)

    owner = {}
    for sleeve, insts in universes.items():
        for t in insts:
            if t in owner:
                raise RuntimeError(
                    f"{t} is claimed by both {owner[t]} and {sleeve}; symbol "
                    f"attribution is no longer safe. Capture by orderRef "
                    f"instead before running this again.")
            owner[t] = sleeve

    cfg = IBKRConfig.from_env()
    app = ibapi.IB()
    app.connect(cfg.host, int(cfg.port),
                clientId=int(client_id or (cfg.client_id + 50)),
                readonly=True, timeout=30)
    try:
        fills = app.fills()
    finally:
        app.disconnect()

    # Already-recorded executions, keyed by IBKR's execId.
    #
    # THIS DEDUP IS LOAD-BEARING, NOT HYGIENE. `ib.fills()` returns the whole
    # session every time it is called, so a job that runs twice — a manual
    # re-run, a launchd double-fire, an operator checking something — silently
    # doubles the fill record. The slippage numbers this file exists to produce
    # are volume-weighted, so duplicates do not merely inflate a row count, they
    # corrupt the very statistic kill rule (b) is evaluated against. Verified on
    # 2026-07-31: three captures of the same session produced 514 rows for 257
    # real executions.
    seen = _recorded_exec_ids(books_root, universes)

    written, skipped, dupes, by_sleeve = 0, 0, 0, {}
    for f in fills:
        sym = f.contract.symbol
        sleeve = owner.get(sym)
        if sleeve is None:
            skipped += 1           # another book's position, or a stale benchmark leg
            continue
        e = f.execution
        if e.execId in seen.get(sleeve, set()):
            dupes += 1
            continue
        commission = None
        rep = getattr(f, "commissionReport", None)
        if rep is not None and getattr(rep, "commission", None) is not None:
            commission = float(rep.commission)
        record_broker_fill(
            Path(books_root) / "_ibkr_shadow" / sleeve,
            instrument=sym, side=("BUY" if e.side.upper().startswith("B") else "SELL"),
            qty=float(e.shares), price=float(e.price),
            fill_date=str(e.time)[:10], source="ibkr_paper",
            note=(f"execId={e.execId} orderRef={e.orderRef!r} "
                  f"commission={commission} time={e.time}"))
        written += 1
        seen.setdefault(sleeve, set()).add(e.execId)
        by_sleeve[sleeve] = by_sleeve.get(sleeve, 0) + 1

    if verbose:
        print(f"[capture] {len(fills)} execution(s) in the TWS session")
        for s in sorted(universes):
            n = by_sleeve.get(s, 0)
            print(f"[capture]   {s}: {n} new -> "
                  f"{Path(books_root)/'_ibkr_shadow'/s/'broker_fills.csv'}")
        print(f"[capture]   {dupes} already recorded (skipped), "
              f"{skipped} belonged to another book (ignored)")
    return {"total": len(fills), "written": written, "skipped": skipped,
            "duplicates": dupes, "by_sleeve": by_sleeve}


def _recorded_exec_ids(books_root, universes) -> dict:
    """{sleeve: set(execId)} already present in each broker_fills.csv."""
    import pandas as pd

    out = {}
    for sleeve in universes:
        path = Path(books_root) / "_ibkr_shadow" / sleeve / "broker_fills.csv"
        if not path.exists():
            out[sleeve] = set()
            continue
        try:
            note = pd.read_csv(path)["note"].astype(str)
            out[sleeve] = set(note.str.extract(r"execId=(\S+)")[0].dropna())
        except Exception:
            out[sleeve] = set()
    return out


def dedupe(books_root, universes, verbose=True) -> dict:
    """Drop duplicate execIds from the on-disk record, keeping the first.

    Needed once because captures taken before the dedup above went in blind.
    """
    import pandas as pd

    out = {}
    for sleeve in universes:
        path = Path(books_root) / "_ibkr_shadow" / sleeve / "broker_fills.csv"
        if not path.exists():
            continue
        d = pd.read_csv(path)
        before = len(d)
        key = d["note"].astype(str).str.extract(r"execId=(\S+)")[0]
        d = d[~key.duplicated(keep="first")]
        if len(d) != before:
            d.to_csv(path, index=False)
        out[sleeve] = {"before": before, "after": len(d)}
        if verbose:
            print(f"[dedupe] {sleeve}: {before} -> {len(d)} row(s)")
    return out


def slippage_report(books_root, sleeve, verbose=True):
    """Realised (broker) vs modelled (ledger) average fill price, per ticker.

    This is the number kill rule (b) is written against and which nothing has
    ever been able to compute. Positive bp = we paid MORE than the model said.
    """
    import pandas as pd

    state = Path(books_root) / "_ibkr_shadow" / sleeve
    bf, tr = state / "broker_fills.csv", state / "trades.csv"
    if not bf.exists() or not tr.exists():
        if verbose:
            print(f"[slippage] {sleeve}: need both broker_fills.csv and trades.csv")
        return None

    real = pd.read_csv(bf)
    real["signed"] = real["qty"] * real["side"].map({"BUY": 1, "SELL": -1})
    agg = real.groupby(["fill_date", "instrument"]).apply(
        lambda g: pd.Series({
            "real_qty": g["signed"].sum(),
            "real_vwap": (g["price"] * g["qty"]).sum() / max(g["qty"].sum(), 1e-9)}),
        include_groups=False).reset_index()

    model = pd.read_csv(tr)
    model["fill_date"] = model["fill_date"].astype(str).str[:10]
    model = model.rename(columns={"ticker": "instrument"})
    m = agg.merge(model[["fill_date", "instrument", "fill_price", "close_price",
                         "shares", "side", "half_spread_bp"]],
                  on=["fill_date", "instrument"], how="inner")
    if m.empty:
        if verbose:
            print(f"[slippage] {sleeve}: no overlapping fill dates yet")
        return None

    # Signed so that "worse for us" is always positive, on both sides.
    dirn = m["side"].str.upper().map({"BUY": 1.0, "SELL": -1.0}).fillna(1.0)
    m["realised_bp"] = dirn * (m["real_vwap"] - m["close_price"]) / m["close_price"] * 1e4
    m["modelled_bp"] = dirn * (m["fill_price"] - m["close_price"]) / m["close_price"] * 1e4
    m["excess_bp"] = m["realised_bp"] - m["modelled_bp"]

    out = state / "slippage.csv"
    m.to_csv(out, index=False)
    if verbose:
        print(f"[slippage] {sleeve}: {len(m)} matched fill(s) -> {out}")
        print(f"[slippage]   realised {m['realised_bp'].mean():+.1f}bp  "
              f"modelled {m['modelled_bp'].mean():+.1f}bp  "
              f"excess {m['excess_bp'].mean():+.1f}bp")
        ratio = (abs(m["realised_bp"].mean()) /
                 max(abs(m["modelled_bp"].mean()), 1e-9))
        print(f"[slippage]   realised/modelled = {ratio:.2f}x "
              f"(kill rule (b) trips above 2.0x for 5 straight sessions)")
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", required=True)
    ap.add_argument("--books-root", required=True)
    ap.add_argument("--client-id", type=int, default=None)
    ap.add_argument("--asof", default=None)
    ap.add_argument("--slippage", action="store_true",
                    help="also compute realised-vs-modelled slippage")
    ap.add_argument("--dedupe-only", action="store_true",
                    help="repair an existing broker_fills.csv; no broker connection")
    a = ap.parse_args(argv)
    universes = sleeve_universes(a.book)
    if a.dedupe_only:
        dedupe(a.books_root, universes)
        for sleeve in universes:
            slippage_report(a.books_root, sleeve)
        return 0
    capture(a.book, a.books_root, client_id=a.client_id, asof=a.asof)
    if a.slippage:
        # Report on every sleeve, not just those with new fills today — a sleeve
        # that traded nothing still has a slippage history worth surfacing.
        for sleeve in universes:
            slippage_report(a.books_root, sleeve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
