"""Rebuild per-sleeve position attribution from broker truth.

WHY THIS EXISTS
---------------
`arm()` splits authority: the broker is authoritative for HOW MANY shares exist,
the shadow ledger for WHICH SLEEVE owns them. On 2026-07-31 the ledgers were
frozen at their funding row (a missing `config/costs.yaml` entry crashed
`ops/ledger.py` mid-write, AFTER orders had gone out), so the attribution half of
that split was simply missing. For symbols only one book trades, `arm()` can take
the account net. For symbols several books share -- HYG, JNK, LQD, VCIT, EMB,
SHYG, and the rest of the null trader's universe -- it cannot, and it correctly
refuses rather than guessing.

This script reconstructs the missing half and writes it where `register_sleeve`
will find it, so `arm()` has something to trust.

HOW ATTRIBUTION IS RECOVERED
----------------------------
IBKR executions carry no `orderRef` for these fills (checked: 302 executions, all
untagged), so tags cannot be used. Two facts make it recoverable anyway:

1. **Fills separate by time.** Each book ran as its own process at a distinct
   time, so a fill's timestamp identifies the book that placed it. Windows are
   passed in rather than inferred, because guessing a boundary is exactly the
   class of error this script exists to remove.
2. **The books are exhaustive.** Only three exist against this paper account, so
   whatever the account holds that is not explained by the others belongs to the
   remainder book. That makes the last book's attribution exact arithmetic, not
   an estimate.

The output is deliberately a plain JSON file per book rather than a rewrite of
the shadow ledger: the ledger carries a manifest integrity check, and hand-
editing state files to satisfy a checker is how a bookkeeping problem becomes a
position problem. `_attribution.json` is additive, readable, and easy to audit
against `ib.positions()`.

USAGE
    python3 scripts/ops/reconcile_attribution.py --write
    python3 scripts/ops/reconcile_attribution.py            # dry run, prints only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# Fill windows in UTC, from the executions actually observed on 2026-07-31.
# CEF ran 11:15-13:34 (pre-market market orders, the 94bp slippage incident);
# the null trader ran at 18:45-18:46. Benchmarks filled on 2026-07-30 and so do
# not appear in today's execution list at all -- they are the remainder book.
SLEEVE_WINDOWS = [
    # (books_root, sleeve, utc_hour_start, utc_hour_end)
    ("ops/books/cef_live", "cef_discount", 10, 15),
    ("ops/books/phase0_live", "null_trader", 18, 20),
]
REMAINDER = ("ops/books/benchmarks_live", None)   # sleeve resolved per symbol


def sleeve_universes():
    """{book_root: {sleeve: [instruments]}} read from the committed book specs."""
    out = {}
    for path in sorted((REPO / "ops/books").glob("*.json")):
        try:
            spec = json.loads(path.read_text())
        except Exception:
            continue
        sleeves = spec.get("sleeves")
        if not isinstance(sleeves, list) or not sleeves:
            continue
        for s in sleeves:
            if not isinstance(s, dict):
                continue
            name = s.get("name") or s.get("sleeve_id") or s.get("id")
            frozen = s.get("spec")
            if frozen is None and s.get("spec_path"):
                try:
                    frozen = json.loads(Path(s["spec_path"]).read_text())
                except Exception:
                    continue
            uni = _deep_get(frozen, "universe") or _deep_get(frozen, "instruments")
            if name and uni:
                out.setdefault(path.stem, {})[name] = list(uni)
    return out


def _deep_get(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _deep_get(v, key)
            if r is not None:
                return r
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="write _attribution.json files (default: dry run)")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--client-id", type=int, default=140)
    args = ap.parse_args()

    from ib_async import IB, ExecutionFilter
    ib = IB()
    ib.connect("127.0.0.1", args.port, clientId=args.client_id, timeout=25)
    account = {}
    for p in ib.positions():
        sym = getattr(p.contract, "localSymbol", None) or p.contract.symbol
        account[sym] = account.get(sym, 0.0) + float(p.position)
    execs = ib.reqExecutions(ExecutionFilter())
    ib.disconnect()

    # Attribute today's fills to a book by the window they landed in.
    attributed = {}
    for root, sleeve, h0, h1 in SLEEVE_WINDOWS:
        book = {}
        for e in execs:
            if not (h0 <= e.time.hour < h1):
                continue
            sym = e.contract.symbol
            qty = float(e.execution.shares)
            book[sym] = book.get(sym, 0.0) + (qty if e.execution.side == "BOT" else -qty)
        attributed[(root, sleeve)] = {k: v for k, v in book.items() if abs(v) > 1e-9}

    # The remainder book gets whatever the account holds that the others do not.
    explained = {}
    for book in attributed.values():
        for k, v in book.items():
            explained[k] = explained.get(k, 0.0) + v
    rem_root, _ = REMAINDER
    remainder = {}
    for sym, qty in account.items():
        left = float(qty) - explained.get(sym, 0.0)
        if abs(left) > 1e-9:
            remainder[sym] = left

    print("=== attribution rebuilt from broker truth ===")
    for (root, sleeve), book in attributed.items():
        print(f"\n{sleeve} ({root}) — {len(book)} symbols")
        for k in sorted(book):
            print(f"   {k:6s} {book[k]:>9.0f}")
    print(f"\nREMAINDER -> {rem_root} — {len(remainder)} symbols")
    for k in sorted(remainder):
        print(f"   {k:6s} {remainder[k]:>9.0f}")

    # Arithmetic check: the parts must sum to the account, exactly.
    total = dict(explained)
    for k, v in remainder.items():
        total[k] = total.get(k, 0.0) + v
    bad = {k: (account.get(k, 0.0), total.get(k, 0.0))
           for k in set(account) | set(total)
           if abs(float(account.get(k, 0.0)) - float(total.get(k, 0.0))) > 1e-6}
    print(f"\nreconciliation: {'OK — parts sum to the account' if not bad else 'MISMATCH'}")
    for k, (a, t) in bad.items():
        print(f"   {k}: account {a:+g} vs attributed {t:+g}")
    if bad:
        return 1

    if not args.write:
        print("\n(dry run — pass --write to persist)")
        return 0

    # Write an EXPLICIT ZERO for every universe symbol the sleeve did not fill.
    # Absence and zero are different claims: absence means "no information", and
    # arm() rightly refuses on that, while zero means "we own none of it" and
    # fully disambiguates a contested symbol. Without this, null_trader blocked
    # on USHY -- it targeted 0 shares ("below min weight") so had no fill, while
    # the account's 67 shares belong to bench_b6_ew_credit. The file is generated
    # from complete fill history, so it can make the stronger claim.
    all_unis = sleeve_universes()
    by_sleeve = {s: u for book in all_unis.values() for s, u in book.items()}
    for (root, sleeve), book in attributed.items():
        for sym in by_sleeve.get(sleeve, []):
            book.setdefault(sym, 0.0)
        path = REPO / root / "_attribution.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.loads(path.read_text()) if path.exists() else {}
        payload[sleeve] = book
        path.write_text(json.dumps(payload, indent=1, sort_keys=True))
        print(f"wrote {path} ({sum(1 for v in book.values() if v)} held, "
              f"{sum(1 for v in book.values() if not v)} explicit zeros)")

    # Remainder is split across the benchmark sleeves by their own universes.
    unis = sleeve_universes().get("benchmarks_book", {})
    bench = {}
    for sym, qty in remainder.items():
        owners = [s for s, u in unis.items() if sym in u]
        if len(owners) == 1:
            bench.setdefault(owners[0], {})[sym] = qty
        elif owners:
            print(f"   NOTE {sym}: {len(owners)} benchmark sleeves claim it "
                  f"({', '.join(owners)}) — left unattributed, arm() will refuse")
    if bench:
        path = REPO / rem_root / "_attribution.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.loads(path.read_text()) if path.exists() else {}
        payload.update(bench)
        path.write_text(json.dumps(payload, indent=1, sort_keys=True))
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
