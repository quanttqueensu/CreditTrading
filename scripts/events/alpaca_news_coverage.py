"""How well does Alpaca's Benzinga news feed cover closed-end funds and their events?

    export QUANTT_ENV_FILE=/abs/path/config/.env   # Alpaca cef key; never printed
    python3 scripts/events/alpaca_news_coverage.py            # fetch (read-only), then summarise
    python3 scripts/events/alpaca_news_coverage.py --offline  # the same, from the cache only

ZERO TRIALS. A COUNT, NOT A RETURN. Written for the special-situations scan
`results/events/PREDICTION_MARKETS_ALT_DATA_2026-10-15.md` (part B). Nothing here
reads a price, a NAV or a return, so no holdout is touched: the 27-name holdout
is consumed only by a test that computes returns on a `cef_universe.csv` name
(`docs/RESEARCH_STATE.md`, 2026-10-09), and the 2023 time holdout is about
returns too.

WHY IT EXISTS
-------------
The event-driven pod note lists Alpaca news as a producer for the event log and
says, of its coverage: "The docs cite about 130 articles a day across all
symbols and say nothing about CEFs, so coverage is probably thin. **Measure it
on our 44 names before relying on it**" (`results/cef/EVENT_DRIVEN_POD_2026-10-12.md`
§3.3). This is that measurement. "Probably thin" was a guess; a guess about
coverage is exactly the kind of figure this desk has been burned by.

TWO MEASUREMENTS
----------------
1. `names`: every article Alpaca returns for each of the 44 `cef_universe.csv`
   names (plus two ETF controls, HYG and BKLN), from 2015-01-01 to the run date:
   the count, the first and last article, articles per year, and how many are
   SPECIFIC to the fund (tagged with at most `SPECIFIC_MAX_SYMBOLS` symbols, so
   not a 40-ticker "52-week lows" list). Headline keywords sort the articles
   into routine (distribution notices) and event-type buckets.
2. `events`: for every EDGAR CEF/BDC episode in
   `results/events/edgar_cef_bdc_episodes.csv` (the 2026-10-12 EDGAR fetcher's
   output) whose first filing is on or after `EVENT_START` and whose fund still
   has a ticker today, does Alpaca carry an article tagged with that ticker in
   [first filing date - `PRE_DAYS`, first filing date + `POST_DAYS`], and does
   one of them name the event (kind-specific keywords)? The offset of the
   earliest such article from the EDGAR filing date says whether the wire ran
   AHEAD of EDGAR -- the question that decides whether news can improve an
   event's `observed_at`.

WHAT IT CANNOT SEE (stated, not fixed)
--------------------------------------
* The EDGAR episode table carries the filing DATE, not `acceptanceDateTime`. A
  filing whose transmission starts after 17:30 ET is dated the next business
  day (17 CFR 232.13(a), `docs/REFERENCES.md` §12j), so a "1 day before EDGAR"
  article may be the same evening. Offsets are in New York calendar days.
* `ticker_now` is today's ticker. A fund renamed or re-tickered since the event
  is queried under the wrong symbol, and a fund merged away has no ticker and
  is excluded. Both bias coverage DOWN for old events; the fund set is a
  survivor set.
* A keyword match is a crude relevance test. It is reported beside the
  any-article count, never instead of it.
* Benzinga tags symbols itself. An article about a fund that Benzinga did not
  tag with the fund's ticker is invisible to a symbol query.

LICENCE AND THE PUBLIC REPOSITORY
---------------------------------
Article text is Benzinga's, delivered under Alpaca's market-data terms. This
repository is public, so the raw responses (headlines and summaries) are cached
only under `results/events/_cache_news/`, which `.gitignore` excludes
(`results/**/_cache_*`). The committed outputs carry COUNTS, dates and article
ids only -- no headline, summary or URL.

READ-ONLY
---------
One endpoint, `GET data.alpaca.markets/v1beta1/news` (symbols, start, end,
sort, limit <= 50, page_token; docs.alpaca.markets/reference/news-3, fetched
2026-10-15), through `AlpacaClient._get`, which retries GETs only and scrubs
the keys from any error. No order path is reachable from this module. The
client is imported inside `make_client`, which no test calls.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

NY = ZoneInfo("America/New_York")
CACHE = REPO / "results/events/_cache_news"
OUT = REPO / "results/events/news_coverage"
UNIVERSE = REPO / "data/cef/cef_universe.csv"          # read-only
EPISODES = REPO / "results/events/edgar_cef_bdc_episodes.csv"

NEWS_PATH = "/v1beta1/news"
PAGE_LIMIT = 50              # the documented maximum
HISTORY_START = "2015-01-01"  # Alpaca's docs say news goes back to 2015 (§12k)
CONTROLS = ("HYG", "BKLN")   # liquid credit ETFs: what "covered" looks like for a fund
# Is the feed alive at all? One large-cap stock over one recent month. A thin
# CEF count beside a busy control is a coverage finding; beside an empty
# control it would be an outage.
FEED_CONTROL = ("AAPL", "2026-09-01", "2026-09-30")
SPECIFIC_MAX_SYMBOLS = 3      # an article tagged with more is a list, not news about the fund
EVENT_START = "2016-01-01"    # one full year after the feed's stated start
PRE_DAYS = 7
POST_DAYS = 3
THROTTLE_S = 0.35             # < 200 requests a minute

# Headline/summary keywords. Lower-cased, matched as regex alternations.
# Chosen from the event kinds' own vocabulary (the SEC form names and the
# words sponsors use in their releases), not tuned on the output.
BUCKETS = {
    "distribution": r"distribution|dividend|declares|payout|monthly income",
    "tender": r"tender",
    "merger": r"merger|merge|reorganiz|reorganis|combin|acqui",
    "rights": r"rights offering|rights offer",
    "activist": r"activist|proxy|saba|karpus|bulldog|nominat|standstill|13d|shareholder proposal",
    "liquidation_term": r"liquidat|termination|term trust|conversion|open-end",
}
EVENT_KEYWORDS = {
    "tender": BUCKETS["tender"],
    "merger": BUCKETS["merger"],
    "contest": BUCKETS["activist"] + r"|board|annual meeting|vote",
}


# --------------------------------------------------------------- pure parts

def classify(text: str) -> list[str]:
    """Every bucket whose keywords appear in `text` (lower-cased); [] if none."""
    t = (text or "").lower()
    return [b for b, rx in BUCKETS.items() if re.search(rx, t)]


def ny_date(ts: str) -> dt.date:
    """An Alpaca RFC-3339 UTC timestamp as a New York calendar date.

    Alpaca stamps `created_at` in UTC ("...Z"). Comparing it with an EDGAR
    filing date (an Eastern business date) without converting would move every
    evening article a day forward.
    """
    if not isinstance(ts, str) or not ts:
        raise ValueError(f"timestamp missing or not a string: {ts!r}")
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"timestamp {ts!r} has no time zone")
    return t.astimezone(NY).date()


def article_rows(items: list[dict], symbol: str) -> pd.DataFrame:
    """Flatten one symbol's articles to the fields the summaries use.

    Raises on an item missing `id`, `created_at` or `symbols`: the counts are
    the deliverable, and an item we cannot date or attribute would be silently
    miscounted.
    """
    rows = []
    for it in items:
        for f in ("id", "created_at", "symbols"):
            if f not in it:
                raise KeyError(f"news item for {symbol} has no {f!r}: keys {sorted(it)}")
        text = f"{it.get('headline') or ''} {it.get('summary') or ''}"
        rows.append({
            "symbol": symbol,
            "id": int(it["id"]),
            "created_at": it["created_at"],
            "ny_date": ny_date(it["created_at"]),
            "n_symbols": len(it["symbols"]),
            "tagged": symbol in it["symbols"],
            "buckets": classify(text),
            "source": it.get("source"),
        })
    return pd.DataFrame(rows, columns=["symbol", "id", "created_at", "ny_date", "n_symbols",
                                       "tagged", "buckets", "source"])


def name_summary(df: pd.DataFrame, symbol: str, run_date: dt.date) -> dict:
    """One row of the per-name table. An empty frame is a measured zero."""
    out = {"symbol": symbol, "n_articles": int(len(df))}
    if df.empty:
        out.update({"first": None, "last": None, "n_specific": 0, "per_year_2016_2025": 0.0,
                    "n_2025": 0})
        out.update({f"n_{b}": 0 for b in BUCKETS})
        return out
    if not df["tagged"].all():
        bad = df.loc[~df["tagged"], "id"].tolist()[:5]
        raise ValueError(f"{symbol}: Alpaca returned articles not tagged with it, e.g. ids {bad}")
    years = pd.Series([d.year for d in df["ny_date"]])
    out["first"] = min(df["ny_date"]).isoformat()
    out["last"] = max(df["ny_date"]).isoformat()
    out["n_specific"] = int((df["n_symbols"] <= SPECIFIC_MAX_SYMBOLS).sum())
    out["per_year_2016_2025"] = round(float(years.between(2016, 2025).sum()) / 10.0, 2)
    out["n_2025"] = int((years == 2025).sum())
    for b in BUCKETS:
        out[f"n_{b}"] = int(df["buckets"].apply(lambda bs: b in bs).sum())
    return out


def event_match(arts: pd.DataFrame, kind: str, first_date: dt.date) -> dict:
    """Did the feed carry the event near its first EDGAR filing, and when?

    `arts` are the articles tagged with the fund's ticker in the window.
    Offsets are New York calendar days from the EDGAR filing date (negative:
    the article came first).
    """
    if kind not in EVENT_KEYWORDS:
        raise ValueError(f"unknown episode kind {kind!r}; known {sorted(EVENT_KEYWORDS)}")
    out = {"n_window": int(len(arts)), "any": bool(len(arts)),
           "relevant": False, "first_relevant_offset": None, "first_any_offset": None}
    if arts.empty:
        return out
    offs = [(d - first_date).days for d in arts["ny_date"]]
    out["first_any_offset"] = int(min(offs))
    rx = EVENT_KEYWORDS[kind]
    rel = [o for o, t in zip(offs, arts["text"]) if re.search(rx, (t or "").lower())]
    if rel:
        out["relevant"] = True
        out["first_relevant_offset"] = int(min(rel))
    return out


# ------------------------------------------------------------- fetch parts

def make_client():
    """The desk's read-only Alpaca client (cef key). Imported here so that no
    test, and nothing at import time, can open a socket."""
    from quantt.broker.alpaca import AlpacaClient
    return AlpacaClient.from_environment("cef")


def _cache_key(params: dict) -> Path:
    h = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:20]
    return CACHE / f"{h}.json"


def fetch_all(client, symbol: str, start: str, end: str, *, offline: bool) -> list[dict]:
    """Every article for `symbol` in [start, end], following `next_page_token`.

    Each page is cached by its exact parameters; `--offline` raises on a page
    that is not cached rather than returning a partial count.
    """
    items: list[dict] = []
    token = None
    while True:
        params = {"symbols": symbol, "start": start, "end": end, "sort": "asc",
                  "limit": PAGE_LIMIT, "include_content": "false"}
        if token:
            params["page_token"] = token
        path = _cache_key(params)
        if path.exists():
            page = json.loads(path.read_text())
        else:
            if offline:
                raise FileNotFoundError(f"--offline: no cached page for {params}")
            page = client._get(client._data, NEWS_PATH, params)
            if not isinstance(page, dict) or "news" not in page:
                raise ValueError(f"news response for {symbol} has no 'news' key")
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(page))
            time.sleep(THROTTLE_S)
        items.extend(page["news"])
        token = page.get("next_page_token")
        if not token:
            return items


def run(offline: bool) -> dict:
    run_date = dt.date.today()
    end = (run_date - dt.timedelta(days=1)).isoformat()   # whole days only
    client = None if offline else make_client()
    uni = pd.read_csv(UNIVERSE)["ticker"].tolist()
    if len(uni) != 44:
        raise ValueError(f"cef_universe.csv has {len(uni)} names; this note was written for 44")

    # 1. per name, and per year across the 44 (an article tagged with several
    #    universe names is one article: `unique_articles` counts ids once)
    rows, frames = [], []
    for sym in list(uni) + list(CONTROLS):
        df = article_rows(fetch_all(client, sym, HISTORY_START, end, offline=offline), sym)
        r = name_summary(df, sym, run_date)
        r["group"] = "control_etf" if sym in CONTROLS else "cef_universe"
        rows.append(r)
        if sym not in CONTROLS:
            frames.append(df)
    names = pd.DataFrame(rows)
    a = pd.concat(frames, ignore_index=True)
    a["year"] = [d.year for d in a["ny_date"]]
    a["specific"] = a["n_symbols"] <= SPECIFIC_MAX_SYMBOLS
    by_year = a.groupby("year").agg(name_articles=("id", "size"),
                                    unique_articles=("id", "nunique"),
                                    specific_name_articles=("specific", "sum")).reset_index()

    # 2. EDGAR episodes
    ep = pd.read_csv(EPISODES, parse_dates=["first_date"])
    ep = ep[(ep["first_date"] >= EVENT_START) & ep["ticker_now"].notna()].copy()
    ev_rows = []
    for _, e in ep.iterrows():
        fd = e["first_date"].date()
        lo = (fd - dt.timedelta(days=PRE_DAYS)).isoformat()
        hi = (fd + dt.timedelta(days=POST_DAYS + 2)).isoformat()   # a UTC-midnight end; the NY-date filter below trims it
        items = fetch_all(client, e["ticker_now"], lo, hi, offline=offline)
        arts = pd.DataFrame([{"ny_date": ny_date(it["created_at"]),
                              "text": f"{it.get('headline') or ''} {it.get('summary') or ''}"}
                             for it in items], columns=["ny_date", "text"])
        if not arts.empty:
            arts = arts[(arts["ny_date"] >= fd - dt.timedelta(days=PRE_DAYS))
                        & (arts["ny_date"] <= fd + dt.timedelta(days=POST_DAYS))]
        m = event_match(arts, e["kind"], fd)
        ev_rows.append({"cik": int(e["cik"]), "kind": e["kind"], "first_date": fd.isoformat(),
                        "first_form": e["first_form"], "ticker_now": e["ticker_now"],
                        "set_rule": e["set_rule"], "in_universe44": e["ticker_now"] in uni, **m})
    events = pd.DataFrame(ev_rows)

    OUT.mkdir(parents=True, exist_ok=True)
    names.to_csv(OUT / "names.csv", index=False)
    by_year.to_csv(OUT / "universe_by_year.csv", index=False)
    events.to_csv(OUT / "events.csv", index=False)

    cef = names[names["group"] == "cef_universe"]
    fc_sym, fc_lo, fc_hi = FEED_CONTROL
    fc = article_rows(fetch_all(client, fc_sym, fc_lo, fc_hi, offline=offline), fc_sym)
    summ = {
        "run_date": run_date.isoformat(), "window": [HISTORY_START, end],
        "feed_control": {"symbol": fc_sym, "window": [fc_lo, fc_hi], "n_articles": int(len(fc)),
                         "n_specific": int((fc["n_symbols"] <= SPECIFIC_MAX_SYMBOLS).sum())},
        "endpoint": "GET https://data.alpaca.markets/v1beta1/news (cef paper key, read-only)",
        "names": {
            "n_names": int(len(cef)),
            "n_with_any_article": int((cef["n_articles"] > 0).sum()),
            "median_articles": float(cef["n_articles"].median()),
            "median_specific": float(cef["n_specific"].median()),
            "median_per_year_2016_2025": float(cef["per_year_2016_2025"].median()),
            "earliest_first": cef["first"].dropna().min(),
            "unique_articles_all_names": int(a["id"].nunique()),
            "by_year": by_year.to_dict("records"),
            "controls": names[names["group"] == "control_etf"][
                ["symbol", "n_articles", "n_specific", "per_year_2016_2025", "first"]].to_dict("records"),
        },
        "events": {},
    }
    for kind, g in events.groupby("kind"):
        rel = g[g["relevant"]]
        summ["events"][kind] = {
            "n": int(len(g)), "any": int(g["any"].sum()), "relevant": int(g["relevant"].sum()),
            "n_universe44": int(g["in_universe44"].sum()),
            "relevant_universe44": int(rel["in_universe44"].sum()),
            "relevant_before_edgar": int((rel["first_relevant_offset"] < 0).sum()),
            "relevant_same_day": int((rel["first_relevant_offset"] == 0).sum()),
            "relevant_after_edgar": int((rel["first_relevant_offset"] > 0).sum()),
        }
    (OUT / "summary.json").write_text(json.dumps(summ, indent=2, default=str))
    return summ


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="rebuild from the cache only")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.offline), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
