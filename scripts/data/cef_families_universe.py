"""The C4 family universe: listed equity, preferred and multi-asset CEFs, by family,
with today's Alpaca flags, and every 44-name `cef_universe.csv` fund fenced off.

    export QUANTT_ENV_FILE=<absolute path to the env file holding the Alpaca keys>
    python3 scripts/data/cef_families_universe.py            # fetches; writes data/cef_families/universe.csv
    python3 scripts/data/cef_families_universe.py --offline  # rebuild from the saved raw responses

WHAT IT READS (each response saved under data/cef_families/raw/, dated)
------------------------------------------------------------------------
1. **CEFConnect `GET /api/v3/DailyPricing`**, unauthenticated, one call: every
   listed CEF CEFConnect covers, with `Strategy` (the Morningstar category),
   `SponsorName`, `InceptionDate`, `NavTicker`, `NAVPublished`. The family
   comes from `Strategy` through `cef_families_common.FAMILY_OF_STRATEGY`
   (module docstring there says why Morningstar and not a new judgement).
   **The NAV ticker comes from here too**: on 2026-10-12, 72 of 359 funds had
   a `NavTicker` other than `X<TK>X` (ADX -> XADEX, QQQX -> XQQQX), and
   `X<TK>X` returned nothing from yfinance for every one sampled. The live
   fetcher's `X<TK>X` rule would have found no NAV for them.
2. **Alpaca `GET /v2/assets?status=active&asset_class=us_equity`** (paper, cef
   key, read-only, through `AlpacaClient.assets`). `tradable`, `shortable`,
   `easy_to_borrow`, `exchange`. **True at its read time only** (CLAUDE.md
   landmine 5): `shortable` churns daily.
3. `data/cef/cef_universe.csv`: the 44 (deployed 13 + 27-name holdout).
   Membership is a column; any member is EXCLUDED, whatever its category.
4. `results/data/universe_2026-10-08/universe_map.csv` (committed, dated
   2026-10-08): the earlier CRSP-name classification, kept as a column for
   comparison, and the source of CEFs that CEFConnect does not list.

WHO IS INCLUDED. A fund enters the panels iff its Morningstar category is one
of the six families, it is not one of the 44, and Alpaca lists it active and
`tradable` today. Everything else is in the table with `exclusion_reason`.
A CEF in the 2026-10-08 map's equity/preferred buckets that CEFConnect does
not list has no category and no NAV ticker from this source: it is listed,
excluded, and named in the note. Nothing is classified by hand here.

ZERO TRIALS. Read-only GETs. Nothing here is a return.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.data.cef_families_common import (  # noqa: E402
    FAMILIES, OUT_DIR, RAW_DIR, RESULTS_DIR, UNIVERSE, UNIVERSE_MAP_CSV,
    FamiliesDataError, assert_no_universe_names, cef_universe_names, family_of, out_path,
    write_frame)

CC_URL = "https://www.cefconnect.com/api/v3/DailyPricing"
CC_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}  # as scripts/cef/fetch_daily.py
RAW_CC = "cefconnect_dailypricing"
RAW_ALPACA = "alpaca_assets_active"
MAP_EQ_FAMILIES = ("cef_equity_multi", "cef_preferred")   # the 2026-10-08 map's buckets for these families
CC_FIELDS = ["Ticker", "Name", "Strategy", "CategoryName", "SponsorName", "InceptionDate",
             "NavTicker", "NAVPublished", "Cusip", "IsLeveraged", "IsManagedDistribution",
             "Term", "MarketCapUSDm", "TotalAssetsUSDm"]


def fetch_cefconnect() -> tuple[list, dict]:
    import requests
    sent = dt.datetime.now(dt.timezone.utc)
    r = requests.get(CC_URL, headers=CC_HEADERS, timeout=60)
    if r.status_code != 200:
        raise FamiliesDataError(f"GET {CC_URL} -> HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    if not isinstance(j, list) or not j:
        raise FamiliesDataError(f"GET {CC_URL} returned no list")
    return j, {"url": CC_URL, "sent_utc": sent.isoformat(),
               "received_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "n": len(j)}


def fetch_alpaca() -> tuple[list, dict]:
    from quantt.broker.alpaca import AlpacaClient
    c = AlpacaClient.from_environment("cef")
    sent = dt.datetime.now(dt.timezone.utc)
    rows = c.assets(status="active", asset_class="us_equity")
    return rows, {"request": "GET https://paper-api.alpaca.markets/v2/assets?status=active&asset_class=us_equity",
                  "book_account": "cef", "sent_utc": sent.isoformat(),
                  "received_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "n": len(rows)}


def _save_raw(stem: str, payload, meta: dict) -> Path:
    day = meta.get("sent_utc", "")[:10]
    p = out_path(f"raw/{stem}_{day}.json")
    p.write_text(json.dumps({"meta": meta, "data": payload}) + "\n")
    return p


def _latest_raw(stem: str) -> dict:
    c = sorted(RAW_DIR.glob(f"{stem}_*.json"))
    if not c:
        raise FamiliesDataError(f"no saved {stem}_*.json under {RAW_DIR}; run without --offline")
    return json.loads(c[-1].read_text())


def build(cc: list, cc_meta: dict, assets: list, al_meta: dict, the44: set[str],
          umap: pd.DataFrame) -> pd.DataFrame:
    """One row per candidate fund, with family, flags and inclusion. Pure: no I/O."""
    d = pd.DataFrame(cc)
    missing = [c for c in CC_FIELDS if c not in d.columns]
    if missing:
        raise FamiliesDataError(f"CEFConnect DailyPricing lacks fields {missing}")
    if d["Ticker"].duplicated().any():
        raise FamiliesDataError(f"CEFConnect lists tickers twice: {sorted(d.Ticker[d.Ticker.duplicated()])}")
    d = d[CC_FIELDS].copy()
    fam = d["Strategy"].map(family_of)
    d["family"] = fam.map(lambda t: t[0] if t else None)
    d["sub"] = fam.map(lambda t: t[1] if t else None)
    cand = d[d["family"].notna()].copy()
    cand["source"] = "cefconnect"

    # CEFs in the 2026-10-08 map's equity/preferred buckets that CEFConnect does not list.
    um = umap[umap["family"].isin(MAP_EQ_FAMILIES)]
    extra = um[~um["symbol"].isin(d["Ticker"])]
    ex = pd.DataFrame({"Ticker": extra["symbol"].values, "source": "universe_map_2026-10-08 only"})
    cand = pd.concat([cand, ex], ignore_index=True)

    a = pd.DataFrame(assets).set_index("symbol")
    cand["alpaca_listed"] = cand["Ticker"].isin(a.index)
    for f in ("status", "exchange", "tradable", "shortable", "easy_to_borrow", "borrow_status"):
        cand[f"alpaca_{f}"] = cand["Ticker"].map(a[f]) if f in a.columns else None
    cand["alpaca_read_utc"] = al_meta["received_utc"]
    cand["cefconnect_read_utc"] = cc_meta["received_utc"]
    cand["in_cef_universe_csv"] = cand["Ticker"].isin(the44)
    cand["map_family_2026_10_08"] = cand["Ticker"].map(umap.drop_duplicates("symbol").set_index("symbol")["family"])

    reasons = []
    for _, r in cand.iterrows():
        if r["in_cef_universe_csv"]:
            reasons.append("in data/cef/cef_universe.csv (deployed 13 or 27-name holdout)")
        elif r["source"] != "cefconnect":
            reasons.append("not listed by CEFConnect: no Morningstar category and no NAV ticker from this source")
        elif not r["alpaca_listed"]:
            reasons.append("not in Alpaca's active asset list today")
        elif r["alpaca_tradable"] is not True:
            reasons.append("Alpaca: tradable is false today")
        else:
            reasons.append("")
    cand["exclusion_reason"] = reasons
    cand["included"] = cand["exclusion_reason"] == ""
    assert_no_universe_names(cand.loc[cand["included"], "Ticker"], the44)
    bad = set(cand.loc[cand["included"], "family"]) - set(FAMILIES)
    if bad:
        raise FamiliesDataError(f"included rows carry unknown families {bad}")
    cand["inception_cefconnect"] = pd.to_datetime(cand["InceptionDate"]).dt.date
    cand = cand.rename(columns={"Ticker": "ticker", "Name": "name_cefconnect", "Strategy": "morningstar_strategy",
                                "CategoryName": "morningstar_category", "SponsorName": "sponsor",
                                "NavTicker": "nav_ticker_cefconnect", "NAVPublished": "nav_published_cefconnect",
                                "Cusip": "cusip", "IsLeveraged": "leveraged", "IsManagedDistribution":
                                "managed_distribution", "Term": "term", "MarketCapUSDm": "mktcap_usdm",
                                "TotalAssetsUSDm": "total_assets_usdm"}).drop(columns=["InceptionDate"])
    order = ["ticker", "family", "sub", "included", "exclusion_reason", "sponsor", "name_cefconnect",
             "inception_cefconnect", "morningstar_strategy", "morningstar_category", "nav_ticker_cefconnect",
             "nav_published_cefconnect", "in_cef_universe_csv", "map_family_2026_10_08", "alpaca_listed",
             "alpaca_status", "alpaca_exchange", "alpaca_tradable", "alpaca_shortable", "alpaca_easy_to_borrow",
             "alpaca_borrow_status", "alpaca_read_utc", "cefconnect_read_utc", "source", "leveraged",
             "managed_distribution", "term", "mktcap_usdm", "total_assets_usdm", "cusip"]
    return cand[order].sort_values(["family", "ticker"], na_position="last").reset_index(drop=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="rebuild from the latest saved raw responses")
    args = ap.parse_args(argv)
    if args.offline:
        rc, ra = _latest_raw(RAW_CC), _latest_raw(RAW_ALPACA)
        cc, cc_meta, assets, al_meta = rc["data"], rc["meta"], ra["data"], ra["meta"]
    else:
        cc, cc_meta = fetch_cefconnect()
        assets, al_meta = fetch_alpaca()
        _save_raw(RAW_CC, cc, cc_meta)
        _save_raw(RAW_ALPACA, assets, al_meta)
    if not UNIVERSE_MAP_CSV.exists():
        raise FamiliesDataError(f"{UNIVERSE_MAP_CSV} does not exist")
    u = build(cc, cc_meta, assets, al_meta, cef_universe_names(), pd.read_csv(UNIVERSE_MAP_CSV))
    p = write_frame(u, UNIVERSE)
    # The committed copy drops the CUSIP (public repository; nothing row-level from a
    # licensed or identifier source goes in git). Asset flags and categories are public.
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    day = al_meta["received_utc"][:10]
    u.drop(columns=["cusip"]).to_csv(RESULTS_DIR / f"universe_{day}.csv", index=False)
    inc = u[u["included"]]
    print(f"CEFConnect {cc_meta['n']} funds read {cc_meta['received_utc']}; Alpaca {al_meta['n']} active "
          f"assets read {al_meta['received_utc']}")
    print(f"candidates {len(u)}, included {len(inc)}  -> {p}")
    print(u.groupby(["family", "included"], dropna=False).size().to_string())
    print("excluded:", u.loc[~u["included"], "exclusion_reason"].value_counts().to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
