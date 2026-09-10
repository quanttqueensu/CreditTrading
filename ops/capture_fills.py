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

    # Symbol attribution, plus the shared-ticker escape hatch.
    #
    # Symbol alone stops working the moment two sleeves of one book trade the
    # same ticker -- bench_b1_hyg and bench_b6_ew_credit both hold HYG. This
    # used to raise outright, which was right while there was nothing better to
    # fall back on. There now is: the adapter writes orderId -> sleeve at
    # placement (_record_order_attribution), which is exact, because the
    # placing process is the one moment attribution is actually known.
    #
    # A shared ticker is resolved by orderId or it is NOT RECORDED. It is never
    # split, apportioned or assigned to a best guess: a fabricated fill would
    # corrupt the volume-weighted slippage statistic that kill rule (b) reads.
    owner, shared = {}, {}
    for sleeve, insts in universes.items():
        for t in insts:
            if t in owner:
                shared.setdefault(t, {owner[t]}).add(sleeve)
                continue
            owner[t] = sleeve

    order_map = _load_order_map(books_root)
    if shared and not order_map:
        # Warn, do NOT raise. Raising would abandon the fills of every OTHER
        # sleeve in the book, which are perfectly attributable -- trading one
        # incomplete record for a completely absent one. The per-fill path
        # below drops exactly the ambiguous rows and says so.
        print(f"[capture] WARNING shared ticker(s) "
              f"{ {k: sorted(v) for k, v in shared.items()} } and no "
              f"_order_map.csv yet; those fills will be reported "
              f"UNATTRIBUTED and skipped. Everything else still records.")

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
    unattributed = 0
    for f in fills:
        sym = f.contract.symbol
        e = f.execution
        if sym in shared:
            sleeve = order_map_owner(order_map, e,
                                     client_id=int(client_id or (cfg.client_id + 50)))
            if sleeve not in shared[sym]:
                unattributed += 1
                print(f"[capture] UNATTRIBUTED {sym} execId={e.execId} "
                      f"orderId={getattr(e, 'orderId', '?')}: claimed by "
                      f"{sorted(shared[sym])} and no order-map entry. NOT "
                      f"recorded -- this fill is missing from slippage.")
                continue
        else:
            sleeve = owner.get(sym)
        if sleeve is None:
            skipped += 1           # another book's position, or a stale benchmark leg
            continue
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
        if shared:
            print(f"[capture]   shared tickers resolved by orderId: "
                  f"{ {k: sorted(v) for k, v in shared.items()} }")
        if unattributed:
            print(f"[capture]   *** {unattributed} fill(s) UNATTRIBUTED and not "
                  f"recorded -- slippage for those is incomplete ***")
    return {"total": len(fills), "written": written, "skipped": skipped,
            "duplicates": dupes, "by_sleeve": by_sleeve,
            "unattributed": unattributed}


def _load_order_map(books_root) -> dict:
    """{order_id: sleeve} written by the adapter at placement time.

    A MISSING map is a legitimate state (no order has been placed from this
    book yet) and returns {}. An UNREADABLE map is not, and now raises.

    It used to `except Exception: print(...)` and return whatever it had parsed
    so far. That is a silent fallback of the worst shape here, because the
    caller cannot tell a partial map from a complete one: the only consumer is
    the shared-ticker branch, which asks `order_map.get(orderId)` and, on a
    miss, declares the fill UNATTRIBUTED and DOES NOT RECORD IT. So a CSV that
    went unreadable half way through would quietly drop real executions out of
    the slippage record while printing one line and continuing to exit 0 --
    the same failure mode as the fills this module was written to stop losing.
    Attribution has to be exact or absent, never partial and unlabelled.
    """
    path = Path(books_root) / "_ibkr_shadow" / "_order_map.csv"
    if not path.exists():
        return {}
    import csv as _csv
    out = {}
    with open(path) as fh:
        for row in _csv.DictReader(fh):
            oid = str(row.get("order_id", "")).strip()
            sleeve = row.get("sleeve", "")
            pid = str(row.get("perm_id", "") or "").strip()
            cid = str(row.get("client_id", "") or "").strip()
            # THREE KEYS PER ROW, MOST SPECIFIC FIRST (2026-09-10).
            #   ("perm", permId)          globally unique at IBKR, stable across
            #                             client ids -- the only key that can
            #                             attribute an execution account-wide.
            #   ("cid", clientId, orderId) unique BY CONSTRUCTION: IBKR order ids
            #                             are per-client-id sequences.
            #   ("day", asof, orderId)    the legacy key. Known to collide across
            #                             books -- 8 times in the 100 rows written
            #                             before the adapter recorded the two
            #                             fields above. Kept only because those
            #                             rows carry nothing better, and consulted
            #                             last.
            # Rows written before 2026-09-10 have neither perm_id nor client_id,
            # so they contribute only the legacy key and remain exactly as
            # ambiguous as they always were. Nothing here invents a key for them.
            if pid and pid != "0":
                out[("perm", pid)] = sleeve
            if oid:
                out[("cid", cid, oid)] = sleeve
                out[("day", str(row.get("asof", ""))[:10], oid)] = sleeve
    return out


def order_map_owner(order_map, execution, client_id=""):
    """Which sleeve placed `execution`, or None. Most specific key wins.

    Split out so the adapter and this module cannot drift apart about what the
    map means -- they resolve the same fill from the same file, and a
    disagreement between them would move a real position between two live books.
    """
    for key in (("perm", str(getattr(execution, "permId", "") or "")),
                ("cid", str(client_id), str(getattr(execution, "orderId", ""))),
                ("day", str(getattr(execution, "time", ""))[:10],
                 str(getattr(execution, "orderId", "")))):
        owner = order_map.get(key)
        if owner is not None:
            return owner
    return None


def _recorded_exec_ids(books_root, universes) -> dict:
    """{sleeve: set(execId)} already present in each broker_fills.csv.

    A missing broker_fills.csv means the sleeve has never recorded a fill, and
    is an empty set. A PRESENT-BUT-UNREADABLE one raises, naming the file.

    This is the dedup the module docstring calls LOAD-BEARING, and the old
    `except Exception: out[sleeve] = set()` disarmed it precisely when it was
    needed. An empty `seen` set is indistinguishable from "nothing recorded
    yet", so a broker_fills.csv that was truncated, half-written or missing its
    `note` column would make the very next capture re-write every execution it
    already held -- silently doubling the file, and with it the volume-weighted
    slippage statistic kill rule (b) is evaluated against. Measured 2026-07-31:
    three blind captures of one session produced 514 rows for 257 executions.
    A corrupt file is the one input that must stop the run, not be read as zero.
    """
    import pandas as pd

    out = {}
    for sleeve in universes:
        path = Path(books_root) / "_ibkr_shadow" / sleeve / "broker_fills.csv"
        if not path.exists():
            out[sleeve] = set()
            continue
        d = pd.read_csv(path)
        if "note" not in d.columns:
            raise ValueError(
                f"{path} has no 'note' column, so no execId can be read from it "
                f"and the dedup would silently treat this sleeve as having "
                f"recorded nothing. Columns present: {list(d.columns)}")
        note = d["note"].astype(str)
        out[sleeve] = set(note.str.extract(r"execId=(\S+)")[0].dropna())
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


def _ratio(m):
    """realised/modelled on `m`. nan when there is nothing left to compare."""
    if m.empty:
        return float("nan")
    return abs(m["realised_bp"].mean()) / max(abs(m["modelled_bp"].mean()), 1e-9)


def slippage_report(books_root, sleeve, verbose=True):
    """Realised (broker) vs modelled (ledger) average fill price, per ticker.

    This is the number kill rule (b) is written against and which nothing has
    ever been able to compute. Positive bp = we paid MORE than the model said.
    """
    import numpy as np
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

    # THE MODELLED PRICE COMES FROM ITS OWN COLUMN, NOT FROM `fill_price`
    # (2026-09-10). It used to read `fill_price`, which was safe only while the
    # ledger always simulated. Since the team lead's decision to book the
    # broker's real price, `fill_price` IS the realised price on any row with an
    # execId -- so `modelled_bp` would equal `realised_bp` by construction,
    # `excess_bp` would be exactly 0.0 on every row, and the ratio below would
    # print "1.00x" forever. Kill rule (b) would have become structurally unable
    # to trip, while still reporting a number that reads like evidence that it
    # had been checked. `modelled_fill_price` is written by BOTH fill paths and
    # is the counterfactual on the real one; see ops/ledger.py TRADE_COLUMNS.
    # A row written before 2026-09-10 has neither column. For such a row the
    # ledger simulated, so `fill_price` IS the modelled price -- by construction,
    # not by assumption -- and `exec_ids` is what distinguishes the two cases.
    # This is deliberately NOT a fillna: a row that carries an execId and yet has
    # no modelled price is a real fill whose counterfactual was lost, and there
    # is no honest value to put there, so it raises and names itself.
    if "exec_ids" not in model.columns:
        model["exec_ids"] = ""
    is_real = model["exec_ids"].fillna("").astype(str).str.len() > 0
    if "modelled_fill_price" not in model.columns:
        model["modelled_fill_price"] = pd.NA
    model["modelled_fill_price"] = model["modelled_fill_price"].where(
        model["modelled_fill_price"].notna(), model["fill_price"].where(~is_real))
    # A row that carries an execId but no modelled price is a real fill whose
    # counterfactual was never recorded -- `ops/rebuild_ledger.py` books real
    # prices and cannot reconstruct what the model would have charged. Such a
    # row is DROPPED from the comparison rather than defaulted, and the drop is
    # reported. Using `fill_price` there would set excess_bp to exactly 0.0 and
    # pull the ratio toward 1.00x, which is worse than a smaller sample: it
    # reads like evidence the rule was checked.
    orphan = model[is_real & model["modelled_fill_price"].isna()]
    if not orphan.empty and verbose:
        print(f"[slippage] {sleeve}: {len(orphan)} real fill(s) have no "
              f"modelled price and are EXCLUDED from kill rule (b) "
              f"({', '.join(orphan['instrument'].astype(str).head(5))}"
              f"{' ...' if len(orphan) > 5 else ''}). Their counterfactual was "
              f"never recorded and cannot be reconstructed.")
    model = model[~(is_real & model["modelled_fill_price"].isna())]
    model["modelled_fill_price"] = model["modelled_fill_price"].astype(float)
    m = agg.merge(model[["fill_date", "instrument", "fill_price", "close_price",
                         "shares", "side", "half_spread_bp",
                         "modelled_fill_price"]],
                  on=["fill_date", "instrument"], how="inner")
    if m.empty:
        if verbose:
            print(f"[slippage] {sleeve}: no overlapping fill dates yet")
        return None

    # Signed so that "worse for us" is always positive, on both sides.
    dirn = m["side"].str.upper().map({"BUY": 1.0, "SELL": -1.0}).fillna(1.0)
    m["realised_bp"] = dirn * (m["real_vwap"] - m["close_price"]) / m["close_price"] * 1e4
    m["modelled_bp"] = (dirn * (m["modelled_fill_price"] - m["close_price"])
                        / m["close_price"] * 1e4)
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
        # A row whose realised and modelled bp are IDENTICAL contributes a
        # guaranteed zero excess and pulls the mean toward "no slippage". That
        # happens when the ledger row was itself written from the real price --
        # `ops/rebuild_ledger.py` does exactly that -- so the comparison is
        # against itself. Before 2026-09-10 nothing recorded which rows those
        # were, and a rebuilt row is indistinguishable from a modelled row that
        # happened to be exactly right. Count them so the ratio is never read
        # without its own dilution visible.
        tied = int(np.isclose(m["excess_bp"], 0.0, atol=1e-6).sum())
        if tied:
            print(f"[slippage]   NOTE {tied} of {len(m)} row(s) show excess "
                  f"0.0bp exactly, i.e. modelled == realised by construction, "
                  f"and dilute the ratio toward 1.00x. Rows written before "
                  f"2026-09-10 cannot be distinguished from genuinely modelled "
                  f"ones. Excluding them the ratio is "
                  f"{_ratio(m[~np.isclose(m['excess_bp'], 0.0, atol=1e-6)]):.2f}x.")
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
