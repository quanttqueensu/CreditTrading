"""Which deployed names would need IBKR for their short leg, and what IBKR charges for them.

    python3 scripts/ops/ibkr_second_broker_names.py --today 2026-10-19            # fetch IBKR's file once
    python3 scripts/ops/ibkr_second_broker_names.py --today 2026-10-19 --offline  # re-read the cache

WHY (team lead, 2026-10-19: open IBKR as a second broker, equities only, for the
shorts Alpaca will not lend; `results/ops/IBKR_SECOND_BROKER_2026-10-19.md` §1).
The question "which names need it" must be re-measured, never copied from a
note: `borrow_status` changes daily (CLAUDE.md landmine 5), and on the five
committed probe snapshots three different spec names have each been the one
Alpaca would not lend. So this script answers it from three dated records and
prints each one's date beside it:

1. **Alpaca, per committed probe snapshot** (`results/ops/alpaca_probe/*_cef.json`,
   written by `quantt.broker.alpaca_probe`). Read from disk only. This script
   holds no credentials and opens no broker connection: the snapshots are what
   the probe recorded on their dates, and a newer read is the probe's job.
2. **Alpaca, the 2026-10-18 flag read** committed by the merger-arbitrage job
   (`results/events/merger_arb/cef_names_borrow_2026-10-18.csv`; `docs/REFERENCES.md`
   §12aa). It is a different record from the probe (a Sunday GET of
   `/v2/assets/{symbol}`), so it is reported in its own column, never pooled
   into the probe count.
3. **IBKR's public shortstock file** (`https://www.interactivebrokers.com/shortstock/usa.txt`),
   fetched once per run day and cached raw under the gitignored
   `results/ops/ibkr_second_broker/_cache_ibkr/`. Its first line,
   `#BOF|YYYY.MM.DD|HH:MM:SS`, is IBKR's stamp; the file states no time zone,
   so the stamp is reported verbatim and the fetch time in UTC beside it.

NO SILENT FALLBACKS. A spec name missing from a snapshot's `assets`, or from
IBKR's file, raises naming it. A snapshot whose `universe` is not the spec's is
counted only for the names it carries, and the per-name denominator says so: the
2026-09-28 snapshot predates v7 and carries 17 names. An availability of
">10000000" keeps its bound in `ibkr_available_gt`.

WHAT IT DOES NOT DO. It does not say whether IBKR would actually lend at order
time (the file is "indicative"; `docs/REFERENCES.md` §4 records a 28x
disagreement between the file and TWS tick 236 on 2026-09-08/10), and it does
not price Alpaca's hard-to-borrow fee, which Alpaca does not publish
(`results/cef/REAL_MONEY_COSTS_2026-10-12.md`).

Writes `results/ops/ibkr_second_broker/names_<today>.csv` and prints a summary.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

PROBE_DIR = REPO / "results" / "ops" / "alpaca_probe"
MARB_FLAGS = REPO / "results" / "events" / "merger_arb" / "cef_names_borrow_2026-10-18.csv"
OUT = REPO / "results" / "ops" / "ibkr_second_broker"
CACHE = OUT / "_cache_ibkr"                       # gitignored: results/**/_cache_*
IBKR_URL = "https://www.interactivebrokers.com/shortstock/usa.txt"

# The four munis v7 dropped because Alpaca would not lend them on 2026-09-28
# (team lead, docs/SYSTEM.md §5, "Universe on Alpaca"). They are not spec names;
# they are reported because IBKR is the route by which they could return, which
# would be a spec change and a CEF trial, not something this script decides.
DROPPED_V7 = ("NAD", "NEA", "NVG", "NZF")

NEED_COLS = ("SYM", "CUR", "NAME", "REBATERATE", "FEERATE", "AVAILABLE")


def parse_usa_txt(text: str) -> tuple[pd.DataFrame, str]:
    """IBKR's usa.txt -> (one row per line, the file's own stamp 'YYYY-MM-DD HH:MM:SS').

    The layout is `#BOF|YYYY.MM.DD|HH:MM:SS`, a `#SYM|CUR|NAME|...` header, then
    pipe-delimited rows with a trailing pipe, then `#EOF`. A changed header raises:
    the column order is IBKR's to change, and reading a fee from the rebate column
    would be a confident wrong number. Rows are kept as IBKR wrote them (a symbol
    can appear twice for two contracts; `dup_symbol` flags it, nothing is dropped).
    """
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#BOF|"):
        raise ValueError(f"IBKR usa.txt: first line {lines[:1]!r} is not '#BOF|date|time'")
    parts = lines[0].split("|")
    if len(parts) < 3:
        raise ValueError(f"IBKR usa.txt: stamp line {lines[0]!r} has no date and time")
    fdate, ftime = parts[1].strip(), parts[2].strip()
    stamp = f"{fdate.replace('.', '-')} {ftime}"
    if len(lines) < 2 or not lines[1].startswith("#"):
        raise ValueError("IBKR usa.txt: no '#SYM|...' header on line 2")
    hdr = [h for h in lines[1].lstrip("#").split("|") if h]
    missing = [c for c in NEED_COLS if c not in hdr]
    if missing:
        raise ValueError(f"IBKR usa.txt header lacks {missing}: {hdr}")
    rows = []
    for ln in lines[2:]:
        if not ln.strip() or ln.startswith("#EOF"):
            continue
        d = dict(zip(hdr, ln.split("|")))
        sym = d.get("SYM", "")
        try:
            av = d["AVAILABLE"].strip()
            rows.append({
                "symbol": sym,
                "currency": d["CUR"],
                "ibkr_name": html.unescape(d["NAME"]),
                "ibkr_fee_pct": float(d["FEERATE"]) if d["FEERATE"] not in ("", "NA") else None,
                "ibkr_rebate_pct": float(d["REBATERATE"]) if d["REBATERATE"] not in ("", "NA") else None,
                "ibkr_available": float(av.lstrip(">")),
                "ibkr_available_gt": av.startswith(">"),
            })
        except (KeyError, ValueError) as e:
            raise ValueError(f"IBKR usa.txt row for {sym!r} will not parse: {e!r}") from None
    out = pd.DataFrame(rows)
    out["dup_symbol"] = out["symbol"].duplicated(keep=False)
    return out, stamp


def ibkr_rows(text: str, names) -> tuple[pd.DataFrame, str]:
    """IBKR's rows for `names`. Raises naming any name the file does not carry,
    and any name carried twice (which contract is ours would then be a guess)."""
    df, stamp = parse_usa_txt(text)
    sub = df[df.symbol.isin(names)]
    absent = sorted(set(names) - set(sub.symbol))
    if absent:
        raise ValueError(f"IBKR usa.txt stamped {stamp} has no row for {absent}")
    dups = sorted(sub.loc[sub.dup_symbol, "symbol"].unique())
    if dups:
        raise ValueError(f"IBKR usa.txt stamped {stamp} carries {dups} more than once; "
                         "which row is the listed common is not decidable here")
    return sub.drop(columns="dup_symbol").set_index("symbol"), stamp


def snapshot_flags(snapshots: dict[str, dict], names) -> pd.DataFrame:
    """One row per (snapshot date, name the snapshot carries): Alpaca's `shortable`,
    `easy_to_borrow` and `borrow_status` as the probe recorded them.

    `snapshots` maps a label (the file's date) to the parsed JSON. A name in the
    snapshot's `universe` but absent from its `assets` raises: the probe wrote a
    universe it did not read, and counting that name as shortable or not would
    be an invented value. A name outside a snapshot's universe is simply not in
    that snapshot's rows (the 2026-09-28 snapshot predates v7).
    """
    recs = []
    for label, snap in sorted(snapshots.items()):
        uni = snap.get("universe")
        assets = snap.get("assets")
        if uni is None or assets is None:
            raise ValueError(f"probe snapshot {label}: no 'universe' or no 'assets'")
        for s in names:
            if s not in uni:
                continue
            a = assets.get(s)
            if a is None:
                raise ValueError(f"probe snapshot {label}: {s} is in its universe but has no asset row")
            for k in ("shortable", "easy_to_borrow", "borrow_status"):
                if k not in a:
                    raise ValueError(f"probe snapshot {label}: {s} asset row lacks {k!r}")
            recs.append({"snapshot": label, "fetched_at_utc": snap.get("fetched_at_utc"),
                         "symbol": s, "shortable": bool(a["shortable"]),
                         "easy_to_borrow": bool(a["easy_to_borrow"]),
                         "borrow_status": a["borrow_status"]})
    return pd.DataFrame(recs)


def tally(flags: pd.DataFrame) -> pd.DataFrame:
    """Per name: snapshots carrying it, how many said `shortable: false`, on which
    dates, and the newest snapshot's flag. The denominator is per name."""
    out = []
    for s, g in flags.groupby("symbol", sort=True):
        g = g.sort_values("snapshot")
        bad = g.loc[~g.shortable, "snapshot"].tolist()
        out.append({"symbol": s, "probe_snapshots": len(g), "probe_unshortable": len(bad),
                    "probe_unshortable_dates": ";".join(bad),
                    "probe_latest": g.snapshot.iloc[-1],
                    "probe_latest_shortable": bool(g.shortable.iloc[-1]),
                    "probe_latest_borrow_status": g.borrow_status.iloc[-1]})
    return pd.DataFrame(out).set_index("symbol")


def load_snapshots() -> dict[str, dict]:
    files = sorted(PROBE_DIR.glob("*_cef.json"))
    if not files:
        raise FileNotFoundError(f"no probe snapshots under {PROBE_DIR}")
    return {f.name.split("_")[0]: json.loads(f.read_text()) for f in files}


def load_marb_flags(names) -> pd.DataFrame:
    """The 2026-10-18 Alpaca read from the merger-arbitrage job, for `names`."""
    m = pd.read_csv(MARB_FLAGS).set_index("symbol")
    absent = sorted(set(names) - set(m.index))
    if absent:
        raise ValueError(f"{MARB_FLAGS.name} has no row for {absent}")
    return m.loc[list(names), ["alp_shortable", "alp_borrow"]].rename(
        columns={"alp_shortable": "alpaca_20261018_shortable",
                 "alp_borrow": "alpaca_20261018_borrow_status"})


def fetch_ibkr(today: str, offline: bool) -> tuple[str, str]:
    """The raw file text and the UTC time it was fetched (or the cache's record of it)."""
    p = CACHE / f"usa_{today}.txt"
    meta = CACHE / f"usa_{today}.fetched_at_utc"
    if not p.exists():
        if offline:
            raise FileNotFoundError(f"--offline and no cached IBKR file {p}")
        import urllib.request
        req = urllib.request.Request(IBKR_URL, headers={"User-Agent": "Mozilla/5.0 (research; read-only)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            if r.status != 200:
                raise RuntimeError(f"GET {IBKR_URL} -> HTTP {r.status}")
            body = r.read()
        CACHE.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        meta.write_text(dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds") + "\n")
    if not meta.exists():
        raise FileNotFoundError(f"cached {p.name} has no fetch-time record {meta.name}")
    return p.read_text(encoding="utf-8", errors="replace"), meta.read_text().strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--today", required=True, help="the run date, YYYY-MM-DD (names the cache and output)")
    ap.add_argument("--offline", action="store_true", help="read the cached IBKR file; no network")
    a = ap.parse_args(argv)

    from scripts.cef.spec import SPEC_ID, UNIVERSE
    spec = list(UNIVERSE)
    names = spec + [s for s in DROPPED_V7 if s not in spec]

    snaps = load_snapshots()
    flags = snapshot_flags(snaps, names)
    t = tally(flags)
    marb = load_marb_flags(names)
    text, fetched = fetch_ibkr(a.today, a.offline)
    ib, stamp = ibkr_rows(text, names)

    tab = t.join(marb, how="right").join(ib, how="left")
    tab.insert(0, "in_spec", [s in spec for s in tab.index])
    tab["ibkr_file_stamp"] = stamp
    tab["ibkr_fetched_at_utc"] = fetched
    tab["spec_id"] = SPEC_ID
    tab = tab.loc[names]

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"names_{a.today}.csv"
    tab.to_csv(out)

    print(f"spec {SPEC_ID}: {len(spec)} names; plus the four v7 dropped: {', '.join(DROPPED_V7)}")
    print(f"probe snapshots read: {', '.join(sorted(snaps))}")
    print(f"IBKR usa.txt stamp '{stamp}' (no time zone stated), fetched {fetched}")
    print(f"Alpaca 2026-10-18 flags: {MARB_FLAGS.relative_to(REPO)}")
    cols = ["in_spec", "probe_snapshots", "probe_unshortable", "probe_unshortable_dates",
            "probe_latest_shortable", "alpaca_20261018_shortable", "ibkr_fee_pct",
            "ibkr_rebate_pct", "ibkr_available", "ibkr_available_gt"]
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print(tab[cols].to_string())
    latest = t.loc[[s for s in spec if s in t.index]]
    need = latest.index[~latest.probe_latest_shortable].tolist()
    ever = latest.index[latest.probe_unshortable > 0].tolist()
    print(f"\nspec names NOT shortable at Alpaca in the newest probe snapshot "
          f"({latest.probe_latest.max()}): {need or 'none'}")
    print(f"spec names unshortable in at least one probe snapshot: {ever or 'none'}")
    m18 = marb.loc[spec]
    print(f"spec names not shortable in the 2026-10-18 read: "
          f"{m18.index[~m18.alpaca_20261018_shortable.astype(bool)].tolist() or 'none'}")
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
