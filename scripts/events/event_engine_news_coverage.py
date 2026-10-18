"""Does Alpaca's news feed (Benzinga) carry the prototype's events, and does it lead EDGAR?

    export QUANTT_ENV_FILE=/abs/path/config/.env   # Alpaca keys are read from it, never printed
    python3 scripts/events/event_engine_news_coverage.py

ZERO TRIALS. A coverage and timing count; no return is computed.

WHY
---
The pod note (`results/cef/EVENT_DRIVEN_POD_2026-10-12.md` §3.3) lists Alpaca
news as a producer and says "Measure it on our 44 names before relying on it":
Alpaca's docs cite about 130 articles a day across all symbols and say nothing
about closed-end funds (docs/REFERENCES.md §12k). The event engine's design
needs one fact from it: for an event the engine must catch, is there an
article, and is it EARLIER than the EDGAR acceptance time (in which case news
would be the event's `observed_at`, and EDGAR its confirmation)?

WHAT IS MEASURED
----------------
For each EVENT of the 50-filing sample (one row per tender episode, merger
episode and rights offering: the first sampled filing of each), the ticker the
SEC ticker file gives its CIK TODAY (2026-10-12 file; a 2021 ticker can
differ, so a miss can be a ticker change, noted per row), and a window from
30 days before to 3 days after the filing's acceptance time:
* `n_articles`: Benzinga articles tagged with the ticker in the window;
* `first_event_article`: the earliest whose headline or summary matches the
  event's vocabulary (`EVENT_RE`), and its lead over the EDGAR acceptance
  time in hours (positive = news first).
Read-only: `GET /v1beta1/news` only, through `quantt.broker.alpaca.AlpacaClient`
(the paper client; it can GET the data host and nothing here posts).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "events" / "event_engine"
MANIFEST = OUT / "sample_manifest.csv"
TICKERS = REPO / "results" / "events" / "_cache_edgar" / "www.sec.gov" / "files" / "company_tickers_exchange.json"
BEFORE, AFTER = timedelta(days=30), timedelta(days=3)
EVENT_RE = {
    "T": re.compile(r"tender|repurchase offer|offer to purchase", re.I),
    "M": re.compile(r"merge|reorganiz|reorganis|combin|acqui", re.I),
    "R": re.compile(r"rights offering|rights offer|subscription", re.I),
}


def events(man: pd.DataFrame) -> pd.DataFrame:
    """One row per event: the first sampled filing of each episode (T, M) or rights filing (R)."""
    m = man.copy()
    m["event_key"] = m["stratum"] + ":" + m["cik"].astype(str) + ":" + m["episode_first_date"].fillna("").astype(str)
    m.loc[m.stratum == "R", "event_key"] = "R:" + m["accession"]
    return m.sort_values("sample_order").drop_duplicates("event_key")


def tickers_now() -> dict[int, list[str]]:
    j = json.loads(TICKERS.read_text())
    if j.get("fields") != ["cik", "name", "ticker", "exchange"]:
        raise ValueError(f"ticker file fields changed: {j.get('fields')}")
    out: dict[int, list[str]] = {}
    for cik, _, t, _ in j["data"]:
        out.setdefault(int(cik), []).append(t)
    return out


def fetch_news(client, symbol: str, start: str, end: str) -> list[dict]:
    from quantt.broker.alpaca import DATA_BASE
    items, token = [], None
    for _ in range(20):   # 20 pages x 50 = 1,000 articles: more than any CEF window; raise if exceeded
        p = {"symbols": symbol, "start": start, "end": end, "limit": 50, "sort": "asc"}
        if token:
            p["page_token"] = token
        body = client._get(DATA_BASE, "/v1beta1/news", p)
        if not isinstance(body, dict) or "news" not in body:
            raise ValueError(f"news response for {symbol} has no 'news' key")
        items += body["news"]
        token = body.get("next_page_token")
        if not token:
            return items
    raise RuntimeError(f"{symbol}: more than 1,000 articles in the window; widen the page cap knowingly")


def main() -> int:
    from quantt.broker.alpaca import AlpacaClient
    client = AlpacaClient.from_environment("cef")
    man = pd.read_csv(MANIFEST)
    ev = events(man)
    tk = tickers_now()
    rows = []
    for r in ev.itertuples():
        acc_t = pd.Timestamp(r.acceptance_header_as_et_utc)
        syms = [s for s in tk.get(int(r.cik), []) if re.fullmatch(r"[A-Z]{1,5}", s)]
        rec = {"stratum": r.stratum, "accession": r.accession, "company": r.company, "cik": r.cik,
               "acceptance_utc": r.acceptance_header_as_et_utc, "symbols_now": ";".join(syms)}
        if not syms:
            rec.update(n_articles=None, note="no common-share ticker in the SEC file today")
            rows.append(rec)
            continue
        start = (acc_t - BEFORE).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = (acc_t + AFTER).strftime("%Y-%m-%dT%H:%M:%SZ")
        news = []
        for s in syms:
            news += fetch_news(client, s, start, end)
        seen, uniq = set(), []
        for n in news:
            if n["id"] not in seen:
                seen.add(n["id"])
                uniq.append(n)
        hits = [n for n in uniq if EVENT_RE[r.stratum].search((n.get("headline") or "") + " " + (n.get("summary") or ""))]
        hits.sort(key=lambda n: n["created_at"])
        rec["n_articles"] = len(uniq)
        rec["n_event_articles"] = len(hits)
        if hits:
            first = hits[0]
            t0 = pd.Timestamp(first["created_at"])
            rec.update(first_event_article_utc=t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       first_event_headline=(first.get("headline") or "")[:160],
                       news_lead_hours=round((acc_t - t0).total_seconds() / 3600, 2))
        rows.append(rec)
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "alpaca_news_coverage.csv", index=False)
    with_t = df[df["n_articles"].notna()]
    summ = {"events": len(df), "with_ticker_now": len(with_t),
            "with_any_article": int((with_t["n_articles"] > 0).sum()),
            "with_event_article": int((with_t.get("n_event_articles", pd.Series(dtype=float)) > 0).sum()),
            "news_first": int((df.get("news_lead_hours", pd.Series(dtype=float)) > 0).sum()),
            "edgar_first_or_same": int((df.get("news_lead_hours", pd.Series(dtype=float)) <= 0).sum()),
            "window": "acceptance - 30d .. acceptance + 3d", "endpoint": "GET /v1beta1/news"}
    (OUT / "alpaca_news_coverage.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))
    print(df.drop(columns=["company"]).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
