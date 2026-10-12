"""Option-chain liquidity snapshots for TLT and HYG: volume, open interest, quoted width.

    python3 scripts/gamma/option_chain_snapshot.py cboe   --out-dir DIR TLT HYG
    export QUANTT_ENV_FILE=/abs/path/to/config/.env
    python3 scripts/gamma/option_chain_snapshot.py alpaca --out-dir DIR TLT HYG   # GET only
    python3 scripts/gamma/option_chain_snapshot.py stats  --out-dir DIR

WHY THIS EXISTS
---------------
`results/cef/SCALING_RESEARCH_2026-10-08.md` §7.1 says "TLT options trade about
1.1m contracts a day, about 0.28 vol pts wide" (row 3) and that HYG's
"post-close spreads are about 60% of mid" (row 10). Both came from ONE
post-close snapshot on 2026-10-08, pulled by hand into a deleted scratchpad.
Neither the Cboe endpoint nor Alpaca's snapshot endpoint serves history, so the
2026-10-08 values cannot be re-fetched: this script re-measures them on the
date it runs and saves the raw JSON so the measurement can be re-read.

WHAT IT IS NOT: G2's spread input. G2(a) needs >= 20 sessions of measured
REGULAR-HOURS spreads on a four-leg structure (plan item 0.10). A snapshot taken
after the close, or on a weekend, records the quotes left standing after the
close: wider than a working regular-hours book, so an UPPER bound on the
regular-hours width, from one session. Alpaca's free `indicative` feed is "not
actual OPRA quotes" [V, Alpaca historical option data docs, read 2026-10-09];
the `opra` feed returned 403 "OPRA agreement is not signed" on 2026-10-09.

SOURCES
-------
* Cboe delayed quotes: `https://cdn.cboe.com/api/global/delayed_quotes/options/<SYM>.json`
  (unauthenticated; the JSON Cboe's own quote pages load). **FETCHING IS
  DISABLED (2026-10-12).** Cboe's delayed-quote terms say "IT IS STRICTLY
  PROHIBITED TO DOWNLOAD DELAYED QUOTE TABLE DATA FROM THIS WEB SITE BY USING
  AUTO-EXTRACTION PROGRAMS/QUERIES AND/OR SOFTWARE" [V,
  https://www.cboe.com/delayed_quotes/terms, read 2026-10-12]. `stats` still
  reads snapshots already on disk. Whether its quotes
  are Cboe's own book or the consolidated NBBO is NOT documented there [U].
  Per-contract `vega` is per one vol point, so width / vega is the width in vol
  points (the 2026-10-09 convention).
* Alpaca: `GET https://data.alpaca.markets/v1beta1/options/snapshots/<SYM>?feed=indicative`
  with the CEF paper key (read-only; credentials stay in the session headers and
  are never printed).

THE STATISTICS (as the 2026-10-09 scratch scripts computed them)
---------------------------------------------------------------
Near-ATM = expiries 20..60 calendar days after the session date and strikes
within 2% of the underlying close, with a two-sided quote (bid > 0, ask > bid).
Reported: total option contracts traded in the session, total open interest,
the median quoted width in $, in % of mid and in vol points, and the 1-month
ATM straddle width as % of the straddle mid.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics as st
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
ALPACA = "https://data.alpaca.markets/v1beta1/options/snapshots/{sym}"
_UA = "Mozilla/5.0 (QUANTT research; contact via repo)"
OSI = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")
DTE, MONEYNESS = (20, 60), 0.02


def _stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fetch_cboe(sym: str, out_dir: Path) -> Path:
    """Refuses: Cboe's terms prohibit automated download of delayed quotes (module
    docstring, SOURCES). Kept as a refusal so the old command fails loudly."""
    raise SystemExit("cboe fetch disabled 2026-10-12: Cboe's delayed-quote terms prohibit "
                     "automated download (https://www.cboe.com/delayed_quotes/terms). "
                     "Use a licensed source (docs/REFERENCES.md, the Cboe chain row).")


def fetch_alpaca(sym: str, out_dir: Path) -> Path:
    from quantt.broker import alpaca_probe as ap
    env_path = Path(os.environ["QUANTT_ENV_FILE"]) if os.environ.get("QUANTT_ENV_FILE") \
        else ap.ENV_FILE
    kid, sec = ap.load_credentials("cef", ap.read_env_file(env_path))
    s = ap._session(kid, sec)
    del kid, sec
    snaps, token = {}, None
    for _ in range(50):
        params = {"feed": "indicative", "limit": 1000}
        if token:
            params["page_token"] = token
        r = s.get(ALPACA.format(sym=sym), params=params, timeout=60)   # GET only
        if r.status_code != 200:
            raise RuntimeError(f"{sym}: Alpaca HTTP {r.status_code}: {r.text[:200]}")
        j = r.json()
        snaps.update(j.get("snapshots") or {})
        token = j.get("next_page_token")
        if not token:
            break
    else:
        raise RuntimeError(f"{sym}: more than 50 pages; refusing to return a partial chain")
    p = out_dir / f"{sym}_alpaca_{_stamp()}.json"
    p.write_text(json.dumps(snaps))
    return p


def cboe_stats(path: Path) -> dict:
    d = json.loads(path.read_text())
    dd = d["data"]
    S = dd["close"] or dd["current_price"]
    session = dt.date.fromisoformat(dd["last_trade_time"][:10])
    vol = sum(o["volume"] or 0 for o in dd["options"])
    oi = sum(o["open_interest"] or 0 for o in dd["options"])
    near = []
    for o in dd["options"]:
        m = OSI.match(o["option"])
        if not m:
            continue
        e = dt.datetime.strptime(m.group(2), "%y%m%d").date()
        K = int(m.group(4)) / 1000
        if DTE[0] <= (e - session).days <= DTE[1] and abs(K / S - 1) <= MONEYNESS \
                and o["bid"] > 0 and o["ask"] > o["bid"]:
            mid = (o["bid"] + o["ask"]) / 2
            near.append(dict(e=e, K=K, cp=m.group(3), w=o["ask"] - o["bid"], mid=mid,
                             vp=(o["ask"] - o["bid"]) / o["vega"] if o["vega"] else None))
    out = dict(source="cboe", file=path.name, snapshot=d["timestamp"], session=str(session),
               spot=S, contracts=vol, open_interest=oi, n_near=len(near))
    if near:
        e30 = min({n["e"] for n in near}, key=lambda e: abs((e - session).days - 30))
        legs = [n for n in near if n["e"] == e30]
        strad = None
        for k in sorted({n["K"] for n in legs}, key=lambda k: abs(k - S)):
            c = [n for n in legs if n["K"] == k and n["cp"] == "C"]
            p = [n for n in legs if n["K"] == k and n["cp"] == "P"]
            if c and p:
                strad = (c[0]["w"] + p[0]["w"]) / (c[0]["mid"] + p[0]["mid"]) * 100
                break
        vps = [n["vp"] for n in near if n["vp"]]
        out.update(width_usd=st.median(n["w"] for n in near),
                   width_pct_mid=st.median(n["w"] / n["mid"] * 100 for n in near),
                   width_volpts=st.median(vps) if vps else None,
                   straddle_1m_pct_mid=strad, iv30_cboe=dd.get("iv30"))
    return out


def alpaca_stats(path: Path, spot: float, session: dt.date) -> dict:
    d = json.loads(path.read_text())
    day = session.isoformat()
    vol = sum((x.get("dailyBar") or {}).get("v", 0) for x in d.values()
              if (x.get("dailyBar") or {}).get("t", "").startswith(day))
    near, qt = [], []
    for k, x in d.items():
        m = OSI.match(k)
        q = x.get("latestQuote") or {}
        if not m or not q:
            continue
        e = dt.datetime.strptime(m.group(2), "%y%m%d").date()
        K = int(m.group(4)) / 1000
        if DTE[0] <= (e - session).days <= DTE[1] and abs(K / spot - 1) <= MONEYNESS \
                and q.get("bp", 0) > 0 and q.get("ap", 0) > q["bp"]:
            mid = (q["ap"] + q["bp"]) / 2
            near.append(((q["ap"] - q["bp"]), (q["ap"] - q["bp"]) / mid * 100))
            qt.append(q["t"][:19])
    out = dict(source="alpaca-indicative", file=path.name, session=day, contracts=vol,
               n_near=len(near))
    if near:
        out.update(width_usd=st.median(a for a, _ in near),
                   width_pct_mid=st.median(b for _, b in near),
                   quote_times_utc=f"{min(qt)}..{max(qt)}")
    return out


def stats(out_dir: Path) -> None:
    latest = {}
    for p in sorted(out_dir.glob("*.json")):
        sym, src, _ = p.stem.split("_", 2)
        latest[(sym, src)] = p                       # sorted by stamp: last wins
    for (sym, src), p in sorted(latest.items()):
        if src != "cboe":
            continue
        c = cboe_stats(p)
        print(c)
        a = latest.get((sym, "alpaca"))
        if a is not None:
            print(alpaca_stats(a, c["spot"], dt.date.fromisoformat(c["session"])))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step", choices=["cboe", "alpaca", "stats"])
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if a.step == "stats":
        stats(out)
        return 0
    if not a.symbols:
        raise SystemExit("name at least one symbol")
    for sym in a.symbols:
        p = fetch_cboe(sym, out) if a.step == "cboe" else fetch_alpaca(sym, out)
        print(f"[written] {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
