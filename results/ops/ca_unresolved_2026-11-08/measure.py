#!/usr/bin/env python3
"""Reproduces every measured figure in results/ops/CA_UNRESOLVED_ROWS_2026-11-08.md.

    python3 results/ops/ca_unresolved_2026-11-08/measure.py --env-file config/.env [--plans DIR]

READ-ONLY. It issues GETs through the repo's own AlpacaClient (keys loaded by the client
from `--env-file`, never printed) and writes nothing. `--plans` is an optional directory of
private plan.json copies (`<book>/<date>/plan.json`, not committed) for the recorded windows.

WHAT IT PRINTS. (1) What the party fields of the real feed hold, by the ticker test: the
classes in the note's table, on the parser before the fix (`--base`, loaded from git). (2)
The 87 funds' CUSIPs, from Alpaca's own dividend rows, and their issue codes. (3) The
parser before and after the fix on the same pages: which events change. (4) Sessions a flat
book would be refused, before and after, and which rows block each session after. (5) On
the recorded windows, if `--plans` is given. The windows are `corp_actions.blocking_events`
itself; nothing is re-implemented. The feed is as read at run time, so a later run can
differ where Alpaca has revised its rows.
"""
import argparse
import collections
import datetime as dt
import glob
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from ops.schedule.nyse_calendar import is_trading_day, previous_trading_day  # noqa: E402
from quantt.broker import alpaca as new  # noqa: E402
from quantt.session import corp_actions as cam  # noqa: E402
from quantt.session.run import BOOKS, load_spec, spec_params  # noqa: E402

START, END = dt.date(2025, 11, 1), dt.date(2028, 11, 8)


def old_parser(base: str):
    """`quantt/broker/alpaca.py` as of `base`, loaded beside the fixed one."""
    src = subprocess.run(["git", "-C", str(REPO), "show", f"{base}:quantt/broker/alpaca.py"],
                         check=True, capture_output=True, text=True).stdout
    tmp = Path(tempfile.mkdtemp()) / "old_alpaca.py"
    tmp.write_text(src)
    spec = importlib.util.spec_from_file_location("old_alpaca", tmp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["old_alpaca"] = mod
    spec.loader.exec_module(mod)
    return mod


def read_feed(client) -> list:
    """Every page of the 13 non-dividend types over START..END, as the gate asks."""
    pages, token = [], None
    for _ in range(new.MAX_PAGES):
        p = {"types": ",".join(new.CORPORATE_ACTION_TYPES), "start": START.isoformat(),
             "end": END.isoformat(), "limit": 1000, "data_quality": "all"}
        if token:
            p["page_token"] = token
        body = client._get(client._data, "/v1/corporate-actions", p)
        pages.append(body)
        token = body.get("next_page_token")
        if not token:
            return pages
    raise RuntimeError("the feed did not end")


def fund_cusips(client, names) -> dict:
    """{fund: [CUSIPs]} from Alpaca's own cash-dividend rows, 2025-05-01 -> 2026-11-08."""
    out = collections.defaultdict(set)
    for i in range(0, len(names), 40):
        token = None
        while True:
            p = {"symbols": ",".join(names[i:i + 40]), "types": "cash_dividend",
                 "start": "2025-05-01", "end": "2026-11-08", "limit": 1000}
            if token:
                p["page_token"] = token
            body = client._get(client._data, "/v1/corporate-actions", p)
            for r in (body["corporate_actions"] or {}).get("cash_dividends") or []:
                if r.get("cusip"):
                    out[r["symbol"]].add(r["cusip"])
            token = body.get("next_page_token")
            if not token:
                break
    return {s: sorted(out.get(s, set())) for s in names}


def replay(mod, pages, names):
    """(events, skipped) from module `mod`'s real parser over the saved pages."""
    env = Path(tempfile.mkdtemp()) / "k.env"             # constants; no network below
    env.write_text("ALPACA_CEF_KEY_ID=K\nALPACA_CEF_SECRET_KEY=S\n")
    import requests
    c = mod.AlpacaClient("cef", env, session=requests.Session(), sleep=lambda s: None)

    def served(base, path, params=None, **kw):
        i = int(params.get("page_token") or 0)
        return {**pages[i], "next_page_token": str(i + 1) if i + 1 < len(pages) else None}
    c._get = served
    sk = []
    return c.corporate_actions(names, START, END, universe=names, skipped=sk, rows={}), sk


def cusip_check_ok(v: str) -> bool:
    """The CUSIP check digit (modulus 10, double-add-double) over a 9-character value."""
    total = 0
    for i, ch in enumerate(v[:8]):
        d = int(ch) if ch.isdigit() else ord(ch) - 55
        d = d * 2 if i % 2 else d
        total += d // 10 + d % 10
    return (10 - total % 10) % 10 == int(v[8]) if v[8].isdigit() else False


def field_value(r, f):
    if "[" not in f:
        return r.get(f)
    return r["stock_movements"][int(f.split("[")[1].split("]")[0])].get("symbol")


def classes(old, pages):
    """Unread party fields on the pre-fix parser, by what the field actually holds."""
    rows_un, fields, n = set(), collections.Counter(), 0
    for kind, (key, df, fds) in old.CORPORATE_ACTION_TYPES.items():
        for pg in pages:
            for r in (pg["corporate_actions"] or {}).get(key) or []:
                n += 1
                unread = old._ca_read(r, kind, df, fds)[1]
                if unread:
                    rows_un.add((key, r.get("id")))
                for u in unread:
                    v = field_value(r, u["field"])
                    c = ("null/empty" if v in (None, "") else
                         "ISIN-shaped, check digit ok" if new._CA_ISIN_RE.fullmatch(v)
                         and new._ca_isin_check_digit(v) else
                         "CUSIP-format (9 chars)" if re.fullmatch(r"[A-Z0-9]{9}", v) else "other")
                    fields[(kind, c)] += 1
    return n, len(rows_un), fields


def field_value_from_saw(s: str) -> str:
    """The value quoted at the start of an event's `saw` text."""
    m = re.match(r"'([^']*)'", s)
    return m.group(1) if m else s


def sessions(a, b):
    d = a
    while d <= b:
        if is_trading_day(d):
            yield d
        d += dt.timedelta(days=1)


def flat_blockers(events, names, D):
    return cam.blocking_events(events, held={}, targets=names, asof=previous_trading_day(D),
                               session_date=D)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--env-file", required=True, help="the file holding the book's Alpaca keys")
    ap.add_argument("--plans", help="directory of private plan.json copies (optional)")
    ap.add_argument("--base", default="a5b94c8", help="commit of the parser before the fix")
    a = ap.parse_args()
    old = old_parser(a.base)
    client = new.AlpacaClient("cef", a.env_file)
    uni = {b: sorted(spec_params(load_spec(BOOKS[b].spec_path))["universe"]) for b in ("cef", "c4")}
    print("universes:", {b: len(v) for b, v in uni.items()},
          "SNTI in either:", any("SNTI" in v for v in uni.values()),
          "JAGX in either:", any("JAGX" in v for v in uni.values()))
    pages = read_feed(client)

    n, nun, fields = classes(old, pages)
    print(f"\n(1) feed read: {n} rows, process dates {START}..{END}; unread party rows on the old parser: {nun}")
    by = collections.Counter()
    for (kind, c), v in sorted(fields.items()):
        by[c] += v
        print(f"    {kind:24s} {c:28s} {v}")
    print("    fields by class:", dict(by))
    # The mirror image: a letter-led CUSIP-format value PASSES the ticker test.
    passing = [v for pg in pages for rows in (pg["corporate_actions"] or {}).values() for r in rows or []
               for k, v in r.items() if k.endswith("symbol") and isinstance(v, str)
               and new._SYMBOL_RE.fullmatch(v) and re.fullmatch(r"[A-Z][A-Z0-9]{8}", v)
               and any(c.isdigit() for c in v) and cusip_check_ok(v)]
    print(f"    letter-led CUSIP-format fields that pass as tickers (check digit ok): {len(passing)}, "
          f"e.g. {sorted(set(passing))[:6]}")

    names = sorted(set(uni["cef"]) | set(uni["c4"]))
    cus = fund_cusips(client, names)
    flat = [c for v in cus.values() for c in v]
    print(f"\n(2) fund CUSIPs: {sum(1 for v in cus.values() if v)} of {len(names)} funds, {len(flat)} CUSIPs;",
          "issue codes", sorted(collections.Counter(c[6:8] for c in flat).items()),
          "non-numeric", [c for c in flat if not c[6:8].isdigit()],
          "one of the three rows' identifiers:",
          sorted(set(flat) & {"816CVR021", "47010C847", "47010C854", "U67540AA9", "816944102"}))

    res = {}
    print("\n(3) old vs new parser on the same pages (`saw` aside, new only)")
    for b in ("cef", "c4"):
        eo, so = replay(old, pages, uni[b])
        en, sn = replay(new, pages, uni[b])
        strip = lambda e: {k: v for k, v in e.items() if k != "saw"}
        do, dn = {e["id"]: strip(e) for e in eo}, {e["id"]: strip(e) for e in en}
        gone = sorted(set(do) - set(dn))
        bonds = {k["id"] for k in sn if "bonds" in k}
        print(f"    {b}: events {len(eo)} -> {len(en)}; left the events {len(gone)} "
              f"(types {dict(collections.Counter(do[i]['type'] for i in gone))}); added "
              f"{len(set(dn) - set(do))}; changed {sum(dn[i] != do[i] for i in dn if i in do)}; "
              f"recorded as bond rows {len(bonds)}, same set {set(gone) == bonds}; malformed "
              f"skip records {sum('bonds' not in k for k in so)} -> {sum('bonds' not in k for k in sn)}")
        res[b] = {"old": eo, "new": en}

    print("\n(4) sessions a flat book would be refused, every name target-only (feed as read now)")
    for b in ("cef", "c4"):
        for lab, lo, hi in (("10-01..11-02", dt.date(2026, 10, 1), dt.date(2026, 11, 2)),
                            ("11-03..11-09", dt.date(2026, 11, 3), dt.date(2026, 11, 9))):
            line = []
            for tag in ("old", "new"):
                days = list(sessions(lo, hi))
                hit = [d for d in days if flat_blockers(res[b][tag], uni[b], d)]
                line.append(f"{tag} {len(hit)}/{len(days)}")
            print(f"    {b} {lab}: " + ", ".join(line))
    ev = {e["id"]: e for e in res["c4"]["new"]}
    for D in sessions(dt.date(2026, 10, 1), dt.date(2026, 11, 20)):
        ids = sorted({x["id"] for x in flat_blockers(res["c4"]["new"], uni["c4"], D)})
        print(f"    {D} {len(ids)} {[(i[:8], ev[i]['type']) for i in ids]}")

    ids = {x["id"] for D in sessions(dt.date(2026, 10, 1), dt.date(2026, 11, 9))
           for x in flat_blockers(res["cef"]["new"], uni["cef"], D)}
    held_by = {e["id"]: e for e in res["cef"]["new"]}
    vals = [field_value_from_saw(s) for i in ids for s in (held_by[i].get("saw") or {}).values()]
    print(f"\n    rows still blocking a flat core book over 10-01..11-09: {len(ids)}; their values "
          f"are CUSIP-format: {sum(bool(re.fullmatch(r'[A-Z0-9]{9}', v)) for v in vals)} of {len(vals)}")

    still = [e for e in res["c4"]["new"] if e.get("missing") and e.get("date")]
    span = [e for e in still if dt.date(2026, 7, 1) <= e["date"] <= dt.date(2026, 11, 20)]
    weeks = {tuple(e["date"].isocalendar())[:2] for e in span}
    print(f"\n    still-unresolved rows dated 2026-07-01..11-20 (market date, else process date): "
          f"{len(span)}, in {len(weeks)} distinct ISO weeks of the 20.3 calendar weeks spanned")

    if a.plans:
        print("\n(5) the recorded windows (distinct blocking action ids)")
        for f in sorted(glob.glob(a.plans + "/*/*/plan.json")):
            ca = json.load(open(f)).get("corporate_actions")
            if not ca or not ca.get("names"):
                continue
            held = {s: dt.date.fromisoformat(v["held_since"]) for s, v in ca["names"].items()
                    if v.get("held_since")}
            tg = [s for s, v in ca["names"].items() if not v.get("held_since")]
            A, D = dt.date.fromisoformat(ca["asof"]), dt.date.fromisoformat(ca["session_date"])
            book = Path(f).parts[-3]
            got = [sorted({x["id"][:8] for x in cam.blocking_events(
                res[book][t], held=held, targets=tg, asof=A, session_date=D)}) for t in ("old", "new")]
            print(f"    {book} {D}: old {len(got[0])} {got[0]}; new {len(got[1])} {got[1]}")


if __name__ == "__main__":
    main()
