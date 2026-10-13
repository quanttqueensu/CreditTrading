"""Conditional-tender census (idea N1): every US-listed CEF/BDC programme that commits a tender if an average discount passes a threshold.

    export QUANTT_ENV_FILE=/abs/path/config/.env      # SEC_USER_AGENT is read from it, never printed
    python3 scripts/events/conditional_tender_census.py           # EDGAR through the cache, then the network
    python3 scripts/events/conditional_tender_census.py --offline # cache only; raises on a miss

ZERO TRIALS. COUNT AND DESCRIBE ONLY.
------------------------------------
`results/cef/EVENT_DRIVEN_POD_2026-10-12.md` §4.3, N1: "A census from the EDGAR
fetcher of every programme in the CEF universe: fund, terms, measurement
windows, how many triggered, dates. Below about 30 independent windows it is
D7." Nothing here computes a return. The only market quantity computed is a
window's AVERAGE DISCOUNT from our close/NAV panels, and only to answer two
questions the task asks: can our panels compute the trigger (does the panel
reproduce the sponsor's published average?), and how near did the live book's
names come to it. A discount level is not a return; no holdout is consumed
(`docs/RESEARCH_STATE.md`: the 27-name set is consumed by the first test that
computes RETURNS on a `cef_universe.csv` name; the 2023-01-01 time holdout
seals fitted quantities and performance, not data checks).

WHAT IS MEASURED, AND HOW
-------------------------
1. **Discovery** (`discover`). The SEC full indexes through
   `fetch_edgar_events.build` give every CEF/BDC filing since 2008. Every
   SC TO-C filed 2010+ (pre-commencement communications: where sponsors file a
   conditional programme's announcement and its results) and the FIRST
   SC TO-I of every tender episode (whose "purpose of the offer" names the
   programme that triggered it) is fetched and scored by two rules:
   `RULES_V1` (the vocabulary: average discount + measurement period /
   conditional tender / discount management program) and `TRIGGER_RE` (an
   average discount and a threshold percentage in one sentence). A document is
   a candidate if either fires. Every candidate's fund is then either in the
   census (`conditional_tender_programmes.PROGRAMMES`) or in `EXCLUDED` with a
   reason; `account_for_hits` raises on a fund in neither, so a hit cannot be
   silently dropped. EDGAR full-text search is not used (the fetcher's
   documented route; `fetch_edgar_events` docstring), so a programme announced
   only in a press release, an 8-K or an annual report is found only by the
   second channel: a web search, recorded per programme as `channel`.
2. **The census** (`conditional_tender_programmes`): programmes and fund x
   window rows, each fact quoted from a filing and verified here
   (`verify_evidence`), the BlackRock tables parsed (`parse_dmp_table`) and
   cross-checked against the funds' own SC TO-C filings (`check_blk_triggers`),
   and every inferred outcome checked against the index (`check_inferred`).
3. **Panel coverage** (`panel_coverage`). For each window with dates: is the
   fund in `data/cef/` (the live 44-name panel: closes to 2026-09-28, NAV to
   2026-09-25 at the time of writing; the script prints the dates it read) or
   in `data/cef_families/` (C4: yfinance closes and NAVs, and CEFConnect's
   NAVs); how many of the window's NYSE sessions have both a close and a NAV;
   and, where coverage is at least `MIN_COVERAGE`, the panel's mean daily
   close/NAV - 1 over the window, set against the published figure.
   ALIGNMENT: a window's average uses the fund's close and NAV of each session
   in [start, end], exactly as published; a running average at day t uses
   sessions <= t only (`running_average`), i.e. what was knowable at t's close
   once t's NAV printed (the evening; the live book decides in the evening).
4. **Groups and exposure.** Independent groups are counted two ways
   (`independent_groups`): by (sponsor, programme announcement date), as the
   task specifies, and by (sponsor, window end date), the stricter unit for a
   test because one sponsor's funds measured over the same weeks share one
   market. The live book's 13 names come from `scripts/cef/spec.py`.

NO SILENT FALLBACKS. A quote not found raises, naming the accession. A ticker
with no panel is reported as uncovered, never imputed. A window without dates
is counted but never given dates.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

from scripts.events import conditional_tender_programmes as P  # noqa: E402  (data only, stdlib)

OUT = REPO / "results" / "events"
CENSUS_CSV = OUT / "conditional_tender_census.csv"            # tracked: CRSP-derived figures blanked
CENSUS_FULL_CSV = OUT / "conditional_tender_census_full.csv"  # gitignored: includes figures computed on CRSP closes
PROGRAMMES_CSV = OUT / "conditional_tender_programmes.csv"
CANDIDATES_CSV = OUT / "conditional_tender_candidates.csv"
SUMMARY_JSON = OUT / "conditional_tender_summary.json"
LIVE_PATH_CSV = OUT / "conditional_tender_live_running_average.csv"

LIVE_NAV = REPO / "data" / "cef" / "cef_nav.parquet"
LIVE_PX = REPO / "data" / "cef" / "cef_prices.parquet"
FAM_NAV = REPO / "data" / "cef_families" / "cef_nav.parquet"
FAM_PX = REPO / "data" / "cef_families" / "cef_prices.parquet"
FAM_CC = REPO / "data" / "cef_families" / "cef_nav_cefconnect.parquet"
FAM_CRSP = REPO / "data" / "cef_families" / "cef_prices_crsp.parquet"
# Order of preference for the headline panel figure. CRSP's raw close comes before
# yfinance's because yfinance re-bases some funds' closes but not their NAVs
# (docs/REFERENCES.md §12h: NRO, JRI, RIV, CLM, ...), which moves the discount by
# percentage points; CEFConnect is weekly before its 1-year daily window.
PANEL_ORDER = ("live44", "c4_crsp_close", "c4_yf", "c4_cefconnect")

SCOPE_START = date(2010, 1, 1)
INFER_DAYS = 180          # an inferred non-trigger: no SC TO-I (a tender actually commenced) within this many days
BLK_CHECK_DAYS = 10       # a BlackRock trigger is followed by the fund's SC TO-C within this many days
MIN_COVERAGE = 0.95       # share of a window's NYSE sessions with both a close and a NAV before a panel average is shown
REPLICATION_TOL_PP = 0.25  # |panel - published| in percentage points that counts as "reproduced"

# ----------------------------------------------------------------- parsing

_TAG_RE = re.compile(r"<[^>]{0,400}>")


def plain(text: str) -> str:
    """HTML/SGML text -> one line of plain text (tags removed, entities decoded, whitespace collapsed)."""
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def normalise(s: str) -> str:
    """The form in which a quote is matched against a filing.

    Filings differ from a reader's copy in ways that carry no meaning: curly
    versus straight quotes, en dashes printed as minus signs ("–9.06%"), a
    space before a percent sign ("-10.51 %") or after a minus ("- 10.17%"),
    line breaks, case. Nothing else is changed, so a different NUMBER never
    matches.
    """
    s = plain(s).casefold()
    s = s.translate(str.maketrans({"’": "'", "‘": "'", "`": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}))
    s = re.sub(r"(?<=\d)\s+%", "%", s)
    s = re.sub(r"-\s+(?=\d)", "-", s)
    return re.sub(r"\s+", " ", s)


def quote_in(doc: str, quote: str) -> bool:
    """True if `quote` occurs in `doc` after `normalise` on both."""
    if not quote or not quote.strip():
        raise ValueError("empty quote")
    return normalise(quote) in normalise(doc)


RULES_V1 = {
    "avg_disc": re.compile(r"AVERAGE\s+(?:DAILY\s+)?(?:TRADING\s+)?DISCOUNT"),
    "meas": re.compile(r"MEASUREMENT\s+PERIOD|MEASURING\s+PERIOD"),
    "dmp": re.compile(r"DISCOUNT\s+MANAGEMENT\s+PROGRAM"),
    "cond": re.compile(r"CONDITIONAL\s+TENDER"),
    "thresh": re.compile(r"DISCOUNT\s+(?:TRIGGER|THRESHOLD)"),
}
TRIGGER_RE = re.compile(
    r"AVERAGE[^.]{0,60}DISCOUNT[^.]{0,140}(?:MORE THAN|GREATER THAN|IN EXCESS OF|EXCEEDS?|EXCEEDING|AT LEAST|OR MORE|EQUAL TO OR GREATER)"
    r"[^.]{0,20}\d+(?:\.\d+)?\s?(?:%|PERCENT)"
    r"|(?:MORE THAN|GREATER THAN|IN EXCESS OF|EXCEEDS?|AT LEAST)\s\d+(?:\.\d+)?\s?(?:%|PERCENT)[^.]{0,80}AVERAGE[^.]{0,40}DISCOUNT")


def score(doc_plain: str) -> dict:
    """Counts for each discovery rule on one document (upper-cased plain text)."""
    u = doc_plain.upper()
    out = {k: len(rx.findall(u)) for k, rx in RULES_V1.items()}
    out["trigger_sentence"] = len(TRIGGER_RE.findall(u))
    return out


def is_candidate(s: dict) -> bool:
    """Either rule. V1: an average discount with window/trigger vocabulary, or the
    programme vocabulary itself. The sentence rule catches weekly-average and
    'twelve calendar weeks' wording that V1 misses (Delaware, Herzfeld)."""
    v1 = (s["avg_disc"] > 0 and (s["meas"] + s["cond"] + s["dmp"] + s["thresh"]) > 0) or s["dmp"] > 0 or s["cond"] > 0
    return bool(v1 or s["trigger_sentence"] > 0)


_PCT = r"\(?-?\s?\d+(?:\.\d+)?\s?\)?\s?%"
_ROW_RE = re.compile(r"\b([A-Z]{2,5})\s+(" + _PCT + r")")
_NOT_TICKERS = frozenset({"NAV", "NYSE", "ESG", "II", "III", "LLC", "INC"})


def parse_pct(s: str) -> float:
    """'-8.81%' -> -8.81; '(8.17)%' -> -8.17 (accounting negative); '3.30%' -> 3.30; '-8.81 %' -> -8.81."""
    t = s.replace(" ", "")
    m = re.fullmatch(r"(\()?(-)?(\d+(?:\.\d+)?)(\))?%", t)
    if not m:
        raise ValueError(f"not a percentage: {s!r}")
    paren, minus, num, close = m.groups()
    if bool(paren) != bool(close):
        raise ValueError(f"unbalanced parentheses: {s!r}")
    v = float(num)
    return -v if (paren or minus) else v


def parse_dmp_table(doc_plain: str) -> dict[str, float]:
    """Ticker -> published average premium(+)/discount(-) from a BlackRock DMP results table.

    The table opens at "...Discount Results for the Fund(s)..." or
    "Measurement Period Results for the Funds" and is a run of
    "<Fund name> <TICKER> <pct>" rows; it ends at the first sentence that
    follows it (the boards' determination, or a footnote). A ticker seen twice
    with different values raises. An empty table raises.
    """
    m = re.search(r"(?:Discount|Measurement Period) Results for the Funds?", doc_plain)
    if not m:
        raise ValueError("no DMP results table heading")
    body = doc_plain[m.end():]
    stop = re.search(r"The Funds?’? ?(?:’s )?Boards?|\b1 Based on|Based on BMEZ|As a result of the occurrence", body)
    body = body[: stop.start()] if stop else body[:4000]
    out: dict[str, float] = {}
    for tk, val in _ROW_RE.findall(body):
        if tk in _NOT_TICKERS:
            continue
        v = parse_pct(val)
        if tk in out and out[tk] != v:
            raise ValueError(f"{tk} appears twice in one table with {out[tk]} and {v}")
        out[tk] = v
    if not out:
        raise ValueError("DMP table heading found but no ticker rows parsed")
    return out


def is_triggered(avg: float, threshold: float, cmp: str) -> bool:
    """avg is signed (discount < 0); threshold is the discount magnitude."""
    if cmp == ">":
        return avg < -threshold
    if cmp == ">=":
        return avg <= -threshold
    raise ValueError(f"unknown comparator {cmp!r}")


# --------------------------------------------------------------- EDGAR access

def _client(offline: bool):
    from scripts.data.edgar_client import EdgarClient
    return EdgarClient(offline=offline)


def fetch_plain(client, cik: int, accession: str) -> str:
    from scripts.data.edgar_client import filing_txt_url
    return plain(client.get_text(filing_txt_url(int(cik), accession)))


def edgar_index(client, today: date) -> dict:
    """The fetcher's CEF/BDC filings and episodes (nothing written)."""
    from scripts.data import fetch_edgar_events as fe
    return fe.build(client, today)


# ----------------------------------------------------------------- discovery

def candidate_documents(filings: pd.DataFrame, episodes: pd.DataFrame) -> pd.DataFrame:
    """Every SC TO-C filed 2010+, plus the first SC TO-I of each 2010+ tender episode."""
    f = filings[filings["date_filed"] >= pd.Timestamp(SCOPE_START)]
    toc = f[f["form"] == "SC TO-C"]
    toi = f[f["form"] == "SC TO-I"].sort_values("date_filed")
    ep = episodes[(episodes["kind"] == "tender") & (pd.to_datetime(episodes["first_date"]) >= pd.Timestamp(SCOPE_START))]
    firsts = []
    for e in ep.itertuples():
        g = toi[(toi["cik"] == e.cik) & (toi["date_filed"] >= pd.Timestamp(e.first_date))
                & (toi["date_filed"] <= pd.Timestamp(e.last_date))]
        if len(g):
            firsts.append(g.iloc[0])
    cols = ["cik", "company", "form", "date_filed", "accession", "ticker_now"]
    docs = pd.concat([toc[cols], pd.DataFrame(firsts)[cols] if firsts else toc[cols].iloc[:0]])
    return docs.drop_duplicates("accession").sort_values(["date_filed", "cik"]).reset_index(drop=True)


def discover(client, docs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in docs.itertuples():
        s = score(fetch_plain(client, r.cik, r.accession))
        rows.append({"cik": int(r.cik), "company": r.company, "ticker_now": r.ticker_now, "form": r.form,
                     "date_filed": pd.Timestamp(r.date_filed).date(), "accession": r.accession, **s,
                     "candidate": is_candidate(s)})
    return pd.DataFrame(rows)


def census_ciks() -> set[int]:
    out = set()
    for p in P.PROGRAMMES:
        if isinstance(p["funds"], dict):
            out |= set(p["funds"].values())
    return out | set(P.BLK_CIK.values())


def account_for_hits(cands: pd.DataFrame) -> pd.DataFrame:
    """Label each candidate document; raise on a candidate fund that is neither in the census nor excluded."""
    inc, exc = census_ciks(), P.EXCLUDED
    c = cands.copy()
    c["disposition"] = ["census" if k in inc else ("excluded: " + exc[k] if k in exc else "")
                        for k in c["cik"]]
    miss = c[c["candidate"] & (c["disposition"] == "")]
    if len(miss):
        raise RuntimeError("candidate funds neither in the census nor excluded (read them, then code them): "
                           + "; ".join(f"{r.cik} {r.company} {r.accession}" for r in miss.itertuples()))
    c.loc[~c["candidate"], "disposition"] = "not a candidate"
    return c


# ------------------------------------------------------------------- census

def blk_windows(client) -> list[dict]:
    """BlackRock table rows -> window dicts (outcome from the published value, overrides applied)."""
    prog = {p["pid"]: p for p in P.PROGRAMMES}
    out = []
    for pid, start, end, cik, acc in P.TABLES:
        table = parse_dmp_table(fetch_plain(client, cik, acc))
        for tk, avg in table.items():
            row_pid = (P.BLK_2026_ROUTE.get(tk, "BLK-2026E") if pid == "BLK-2026" else pid)
            p = prog[row_pid]
            outcome = "triggered" if is_triggered(avg, p["threshold"], p["cmp"]) else "not_triggered"
            ev = (cik, acc, "table")
            if (tk, end) in P.BLK_OVERRIDES:
                new, ev2 = P.BLK_OVERRIDES[(tk, end)]
                if outcome != "triggered":
                    raise RuntimeError(f"override for {tk} {end} expects a triggered table row, got {avg}")
                outcome, ev = new, ev2
            out.append(P.W(row_pid, tk, start, end, outcome, ev=ev, avg=avg))
            out[-1]["table_ev"] = (cik, acc)
    return out + [dict(w) for w in P.EXTRA_BLK_WINDOWS]


def fund_cik(pid: str, ticker: str) -> int:
    p = next(p for p in P.PROGRAMMES if p["pid"] == pid)
    if isinstance(p["funds"], dict):
        return int(p["funds"][ticker])
    return int(P.BLK_CIK[ticker])


def verify_evidence(client, programmes: list[dict], windows: list[dict]) -> int:
    """Fetch every cited filing and assert every quote is in it. Returns the number of quotes checked."""
    cache: dict[tuple, str] = {}
    failures: list[str] = []

    def check(ev, what):
        if ev is None:
            return 0
        cik, acc, q = ev
        if q == "table":
            return 0
        key = (int(cik), acc)
        if key not in cache:
            cache[key] = fetch_plain(client, *key)
        if not quote_in(cache[key], q):
            failures.append(f"{what}: quote not found in {acc} (CIK {cik}): {q[:100]!r}")
        return 1

    n = 0
    for p in programmes:
        n += check(p.get("ann_ev"), f"{p['pid']} announcement")
        n += check(p.get("terms_ev"), f"{p['pid']} terms")
    for w in windows:
        tag = f"{w['pid']} {w['ticker']} {w['start']}..{w['end']}"
        n += check(w.get("ev"), tag)
        n += check(w.get("wev"), tag + " window dates")
        n += check(w.get("pr_ev"), tag + " pro-ration")
        if w.get("avg") is not None and w.get("ev") and w["ev"][2] != "table" and not w.get("table_ev"):
            # (a table row's average comes from the parsed table, even when a later filing overrode its outcome)
            # the quote that carries an average must contain the number itself
            num = f"{abs(w['avg']):.10g}"
            if num not in normalise(w["ev"][2]) and f"{abs(w['avg']):.2f}" not in normalise(w["ev"][2]):
                failures.append(f"{tag}: the quoted text does not contain the coded average {w['avg']}")
        if w.get("proration_pct") is not None and w.get("pr_ev"):
            if f"{w['proration_pct']:.10g}" not in normalise(w["pr_ev"][2]):
                failures.append(f"{tag}: the pro-ration quote does not contain {w['proration_pct']}")
    if failures:  # every failure at once, so one run lists them all
        raise AssertionError(f"{len(failures)} evidence check(s) failed:\n  " + "\n  ".join(failures))
    return n


def check_inferred(filings: pd.DataFrame, windows: list[dict]) -> list[dict]:
    """Every *_inferred non-trigger: the fund commenced no tender (no SC TO-I) within INFER_DAYS of the window's end.

    SC TO-C is not counted: sponsors file the NEXT window's announcement as an
    SC TO-C (NRO, 2017-06-30), which is not a tender. A window with no stated
    end is taken to end 12 weeks after its start (84 days), the length every
    such programme states; that date is used only for this check."""
    out = []
    for w in windows:
        if w["outcome"] != "not_triggered_inferred":
            continue
        cik = fund_cik(w["pid"], w["ticker"])
        end = pd.Timestamp(w["end"]) if w["end"] else pd.Timestamp(w["start"]) + pd.Timedelta(days=84)
        g = filings[(filings["cik"] == cik) & (filings["form"] == "SC TO-I")
                    & (filings["date_filed"] > end) & (filings["date_filed"] <= end + pd.Timedelta(days=INFER_DAYS))]
        if len(g):
            raise AssertionError(f"{w['pid']} {w['ticker']} window ending {end.date()} is coded not_triggered_inferred "
                                 f"but the fund filed {sorted(set(g['form']))} on {sorted(g['date_filed'].dt.date.astype(str))}")
        out.append({"pid": w["pid"], "ticker": w["ticker"], "checked_through": str((end + pd.Timedelta(days=INFER_DAYS)).date())})
    return out


def check_blk_triggers(filings: pd.DataFrame, windows: list[dict]) -> dict:
    """Second method for the parsed BlackRock tables: a fund the table shows as triggered filed an SC TO-C
    within BLK_CHECK_DAYS of the window end, and a fund shown as not triggered did not."""
    agree, disagree = 0, []
    for w in windows:
        if w.get("table_ev") is None:
            continue
        cik = fund_cik(w["pid"], w["ticker"])
        end = pd.Timestamp(w["end"])
        g = filings[(filings["cik"] == cik) & (filings["form"] == "SC TO-C") & (filings["date_filed"] > end)
                    & (filings["date_filed"] <= end + pd.Timedelta(days=BLK_CHECK_DAYS))]
        filed = len(g) > 0
        trig = w["outcome"] in P.TRIGGERED
        if filed == trig:
            agree += 1
        else:
            disagree.append((w["ticker"], w["end"], trig, filed))
    if disagree:
        raise AssertionError(f"table trigger and SC TO-C filing disagree: {disagree}")
    return {"rows_checked": agree, "disagreements": 0}


# ----------------------------------------------------------- panel coverage

def nyse_sessions(start, end) -> pd.DatetimeIndex:
    """NYSE sessions in [start, end] by the rule calendar (ops/schedule/nyse_calendar.py).

    The rule calendar holds every 2010+ one-off closure the desk knows of
    (2012-10-29/30, 2018-12-05, 2025-01-09); it lacks earlier ones, so it is
    asserted to start no earlier than 2009."""
    from ops.schedule.nyse_calendar import is_trading_day
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    if s < pd.Timestamp("2009-01-01"):
        raise ValueError("the rule calendar is not trusted before 2009 (missing one-off closures)")
    return pd.DatetimeIndex([d for d in pd.date_range(s, e, freq="D") if is_trading_day(d.date())])


def dedupe_agreeing(df: pd.DataFrame, value_cols: list[str]) -> pd.DataFrame:
    """Drop duplicate (ticker, date) rows whose values agree; raise if any disagree.

    CEFConnect's panel stores a date once per history window it came from
    (`1Y` daily and `All` weekly overlap on Fridays; docs/REFERENCES.md §12h
    measured them equal on every common date). Equal copies carry no
    information; unequal copies would be a choice, and this function does not
    make it."""
    k = df.duplicated(["ticker", "date"], keep=False)
    if k.any():
        bad = df[k].groupby(["ticker", "date"])[value_cols].nunique(dropna=False).gt(1).any(axis=1)
        if bad.any():
            raise ValueError(f"{int(bad.sum())} (ticker, date) keys carry different values: {list(bad[bad].index[:5])}")
    return df.drop_duplicates(["ticker", "date"], keep="first")


def load_panels() -> dict:
    """The panels, each as (close Series by (ticker, date), nav Series), with their last dates."""
    out = {}
    for name, nav_p, px_p, nav_col, px_col in (("live44", LIVE_NAV, LIVE_PX, "nav", "close"),
                                               ("c4_yf", FAM_NAV, FAM_PX, "nav", "close")):
        nav, px = dedupe_agreeing(pd.read_parquet(nav_p), [nav_col]), dedupe_agreeing(pd.read_parquet(px_p), [px_col])
        out[name] = {"nav": nav.set_index(["ticker", "date"])[nav_col].sort_index(),
                     "px": px.set_index(["ticker", "date"])[px_col].sort_index(),
                     "tickers": set(nav["ticker"]) & set(px["ticker"]),
                     "last_nav": str(nav["date"].max().date()), "last_px": str(px["date"].max().date())}
    crsp = dedupe_agreeing(pd.read_parquet(FAM_CRSP), ["close"])
    out["c4_crsp_close"] = {"nav": out["c4_yf"]["nav"],
                            "px": crsp.set_index(["ticker", "date"])["close"].abs().sort_index(),
                            "tickers": set(crsp["ticker"]) & out["c4_yf"]["tickers"],
                            "last_nav": out["c4_yf"]["last_nav"], "last_px": str(crsp["date"].max().date())}
    cc = dedupe_agreeing(pd.read_parquet(FAM_CC), ["nav", "close_cc"])
    out["c4_cefconnect"] = {"nav": cc.set_index(["ticker", "date"])["nav"].sort_index(),
                            "px": cc.set_index(["ticker", "date"])["close_cc"].sort_index(),
                            "tickers": set(cc["ticker"]),
                            "last_nav": str(cc["date"].max().date()), "last_px": str(cc["date"].max().date())}
    return out


def window_discount(px: pd.Series, nav: pd.Series, sessions: pd.DatetimeIndex) -> dict:
    """Mean of close/NAV - 1 (in %) over `sessions` where both exist; coverage = days with both / sessions."""
    d = pd.concat([px.reindex(sessions), nav.reindex(sessions)], axis=1, keys=["px", "nav"]).dropna()
    d = d[(d["nav"] > 0) & (d["px"] > 0)]
    n = len(sessions)
    return {"sessions": n, "days_both": len(d), "coverage": (len(d) / n) if n else float("nan"),
            "mean_disc_pct": float(((d["px"] / d["nav"] - 1) * 100).mean()) if len(d) else float("nan")}


def running_average(px: pd.Series, nav: pd.Series, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """The window's average discount as known at each session's close (sessions <= t only)."""
    d = pd.concat([px.reindex(sessions), nav.reindex(sessions)], axis=1, keys=["px", "nav"]).dropna()
    disc = (d["px"] / d["nav"] - 1) * 100
    run = disc.expanding().mean()
    assert all(run.index[i] >= disc.index[0] for i in range(len(run)))  # causal by construction
    return pd.DataFrame({"discount_pct": disc, "running_avg_pct": run})


def panel_coverage(windows: pd.DataFrame, panels: dict) -> pd.DataFrame:
    rows = []
    for w in windows.itertuples():
        tk = P.PANEL_TICKER.get(w.ticker, w.ticker)
        rec = {"row_id": w.row_id, "panel": None, "panel_ticker": tk, "sessions": None, "days_both": None,
               "coverage": None, "panel_avg_pct": None, "panel_minus_published_pp": None}
        if w.window_start is None or w.window_end is None or pd.isna(w.window_start) or pd.isna(w.window_end):
            rows.append(rec)
            continue
        sess = nyse_sessions(w.window_start, w.window_end)
        res = {}
        for name in PANEL_ORDER:
            pnl = panels[name]
            if tk not in pnl["tickers"]:
                continue
            r = window_discount(pnl["px"].loc[tk], pnl["nav"].loc[tk], sess)
            res[name] = r
            rec[f"cov_{name}"] = round(r["coverage"], 4)
            if r["coverage"] >= MIN_COVERAGE:
                rec[f"avg_{name}"] = round(r["mean_disc_pct"], 3)
        # headline: the first panel in PANEL_ORDER that covers the window; else the best coverage seen
        covered = [n for n in PANEL_ORDER if n in res and res[n]["coverage"] >= MIN_COVERAGE]
        pick = covered[0] if covered else (max(res, key=lambda n: res[n]["coverage"]) if res else None)
        if pick is not None:
            r = res[pick]
            rec.update(panel=pick, sessions=r["sessions"], days_both=r["days_both"], coverage=round(r["coverage"], 4))
            if r["coverage"] >= MIN_COVERAGE:
                rec["panel_avg_pct"] = round(r["mean_disc_pct"], 3)
                if w.published_avg_pct is not None and not pd.isna(w.published_avg_pct):
                    rec["panel_minus_published_pp"] = round(r["mean_disc_pct"] - w.published_avg_pct, 3)
                if w.threshold_pct is not None and not pd.isna(w.threshold_pct) and w.comparator:
                    # a second reading of the outcome, from our data alone (close basis; see metric_basis)
                    rec["panel_implies_triggered"] = is_triggered(r["mean_disc_pct"], w.threshold_pct, w.comparator)
        rows.append(rec)
    return pd.DataFrame(rows)


# ------------------------------------------------------------- the tables

def build_windows(client) -> list[dict]:
    ws = [dict(w) for w in P.WINDOWS] + blk_windows(client)
    for w in ws:
        if w["outcome"] not in P.OUTCOMES:
            raise ValueError(f"unknown outcome {w['outcome']!r} in {w['pid']} {w['ticker']}")
    return ws


def known_before_start(p: dict, w: dict, filed_on: dict) -> bool | None:
    """Were this window's dates public before the window began?

    False if the programme's window END is a date the board designates
    without publishing it (the Delaware funds). True if a cited filing that
    states the window's dates was filed on or before the start (`wev`), or if
    the programme fixes its dates by rule (`fixed_dates`) and was announced on
    or before the start. False if the programme was announced after the start
    and nothing earlier states the dates. Otherwise None: not shown either way.
    """
    if not p.get("end_date_public", True):
        return False
    start = pd.Timestamp(w["start"]) if w["start"] else None
    if start is None:
        return None
    if w.get("wev"):
        key = (int(w["wev"][0]), w["wev"][1])
        if key not in filed_on:
            raise KeyError(f"filing date of {key} not in the EDGAR index")
        if filed_on[key] <= start:
            return True
    ann = pd.Timestamp(p["ann"]) if p["ann"] else None
    if ann is not None and p["fixed_dates"] and ann <= start:
        return True
    if ann is not None and ann > start:
        return False
    return None


def windows_frame(ws: list[dict], filed_on: dict) -> pd.DataFrame:
    prog = {p["pid"]: p for p in P.PROGRAMMES}
    rows = []
    for i, w in enumerate(ws):
        p = prog[w["pid"]]
        thr = P.WINDOW_THRESHOLD.get((w["pid"], w["end"]), p["threshold"])
        ann = p["ann"]
        ex_ante = known_before_start(p, w, filed_on)
        ev = w.get("ev") or (None, None, None)
        rows.append({
            "row_id": i, "pid": w["pid"], "sponsor": p["sponsor"], "origin": p["origin"], "asset": p["asset"],
            "ticker": w["ticker"], "cik": fund_cik(w["pid"], w["ticker"]),
            "announced": ann, "window_start": w["start"], "window_end": w["end"],
            "threshold_pct": thr, "comparator": p["cmp"], "metric_basis": p["basis"],
            "tender_size": p["size"], "tender_price_pct_nav": p["price"], "hybrid_condition": p["hybrid"],
            "published_avg_pct": w.get("avg"), "outcome": w["outcome"],
            "proration_pct": w.get("proration_pct"),
            "window_known_before_start": ex_ante, "fixed_dates": p["fixed_dates"],
            "evidence_cik": ev[0], "evidence_accession": ev[1],
            "evidence": ("parsed results table" if ev[2] == "table" else ev[2]),
            "note": w.get("note", ""), "discovery_channel": p["channel"],
        })
    df = pd.DataFrame(rows)
    df["window_end_year"] = pd.to_datetime(df["window_end"]).dt.year
    return df


def independent_groups(df: pd.DataFrame) -> dict:
    """Two counts. (a) sponsor x announcement date (the task's unit; an unknown date counts once per programme).
    (b) sponsor x window end date, over windows with an end date and a known outcome (the unit for a test)."""
    a = df.assign(ann_key=df["announced"].fillna("pid:" + df["pid"]))[["sponsor", "ann_key"]].drop_duplicates()
    known = df[df["outcome"].isin(P.TRIGGERED + P.NOT_TRIGGERED) & df["window_end"].notna()]
    b = known.groupby(["sponsor", "window_end"]).agg(n=("ticker", "size"),
                                                     any_trig=("outcome", lambda s: s.isin(P.TRIGGERED).any()),
                                                     all_trig=("outcome", lambda s: s.isin(P.TRIGGERED).all()))
    b = b.reset_index()
    b["year"] = pd.to_datetime(b["window_end"]).dt.year
    return {"by_sponsor_announcement": len(a), "by_sponsor_window_end": len(b), "clusters": b}


# The proposed zero-trial gate for an N1 trial (the note's §7). A cluster is one sponsor's
# windows that end on one date. "Usable" = what a backtest of the trigger needs: the outcome
# is known, the window's dates were public before it began, the metric can be computed
# from a daily close and NAV (not a VWAP or a 10-day run), and a panel covers it.
GATE_MIN_CLUSTERS = 30
GATE_MIN_EACH_SIDE = 10
CLOSE_COMPUTABLE = ("daily_close", "unspecified_daily", "unspecified", "weekly_close")


def gate(m: pd.DataFrame) -> dict:
    known = m[m["outcome"].isin(P.TRIGGERED + P.NOT_TRIGGERED) & m["window_end"].notna()].copy()
    # one sponsor's funds measured over the same window share its dates: if any of them shows the
    # dates were public before the start, all do (NB 2010: the announcement names all five funds)
    shared = known.groupby(["sponsor", "window_end"])["window_known_before_start"].transform(lambda x: x.eq(True).any())
    known["ex_ante"] = shared
    exante_close = known[known["ex_ante"] & known["metric_basis"].isin(CLOSE_COMPUTABLE)]
    usable = exante_close[exante_close["coverage"].fillna(0) >= MIN_COVERAGE]

    def clusters(x):
        c = x.groupby(["sponsor", "window_end"])["outcome"].agg(lambda o: o.isin(P.TRIGGERED).any()).rename("trig")
        return c.reset_index()

    out = {}
    for label, frame in (("all", known), ("ex_ante_close_computable_any_panel", exante_close), ("usable", usable)):
        c = clusters(frame)
        fit = c[pd.to_datetime(c["window_end"]) < pd.Timestamp("2023-01-01")]
        out[label] = {"clusters": len(c), "triggered": int(c["trig"].sum()), "not_triggered": int((~c["trig"]).sum()),
                      "clusters_pre2023": len(fit), "triggered_pre2023": int(fit["trig"].sum()),
                      "not_triggered_pre2023": int((~fit["trig"]).sum()),
                      "sponsors": int(c["sponsor"].nunique()), "sponsors_pre2023": int(fit["sponsor"].nunique())}
    u = out["usable"]
    out["criteria"] = {
        "a_known_clusters_ge_30": out["all"]["clusters"] >= GATE_MIN_CLUSTERS,
        "b_usable_clusters_ge_30": u["clusters"] >= GATE_MIN_CLUSTERS,
        "c_usable_each_side_ge_10": min(u["triggered"], u["not_triggered"]) >= GATE_MIN_EACH_SIDE,
        "d_fit_period_usable_ge_30_and_each_side_ge_10": (u["clusters_pre2023"] >= GATE_MIN_CLUSTERS and
                                                          min(u["triggered_pre2023"], u["not_triggered_pre2023"]) >= GATE_MIN_EACH_SIDE),
    }
    out["passes"] = all(out["criteria"].values())
    return out


def summarise(df: pd.DataFrame, cov: pd.DataFrame, grp: dict, live: dict, meta: dict) -> dict:
    m = df.merge(cov, on="row_id", how="left")
    known = m[m["outcome"].isin(P.TRIGGERED + P.NOT_TRIGGERED)]
    documented = m[m["outcome"].isin(P.DOCUMENTED)]
    cl = grp["clusters"]
    fit = cl[cl["year"] < 2023]
    covered = m[(m["coverage"].fillna(0) >= MIN_COVERAGE)]
    cov_clusters = covered[covered["outcome"].isin(P.TRIGGERED + P.NOT_TRIGGERED)][["sponsor", "window_end"]].drop_duplicates()
    cov_clusters_fit = cov_clusters[pd.to_datetime(cov_clusters["window_end"]).dt.year < 2023]
    imp = m[m["panel_implies_triggered"].notna() & m["outcome"].isin(P.TRIGGERED + P.NOT_TRIGGERED)]
    imp_agree = (imp["panel_implies_triggered"].astype(bool) == imp["outcome"].isin(P.TRIGGERED))
    rep = m[m["panel_minus_published_pp"].notna()]
    rep_daily = rep[rep["metric_basis"].isin(("daily_close", "unspecified_daily", "unspecified"))]
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **meta,
        "programmes": int(df["pid"].nunique()),
        "programmes_by_sponsor": df.groupby("sponsor")["pid"].nunique().sort_values(ascending=False).to_dict(),
        "fund_windows": len(df),
        "funds": int(df["ticker"].nunique()),
        "outcomes": df["outcome"].value_counts().to_dict(),
        "fund_windows_with_known_outcome": len(known),
        "triggered_share_known": round(float(known["outcome"].isin(P.TRIGGERED).mean()), 3),
        "triggered_share_documented_only": round(float(documented["outcome"].isin(P.TRIGGERED).mean()), 3),
        "independent_groups": {
            "by_sponsor_announcement": grp["by_sponsor_announcement"],
            "by_sponsor_window_end_known_outcome": grp["by_sponsor_window_end"],
            "by_sponsor_window_end_known_outcome_pre2023": int(len(fit)),
            "clusters_any_triggered": int(cl["any_trig"].sum()),
            "clusters_none_triggered": int((~cl["any_trig"]).sum()),
            "clusters_pre2023_any_triggered": int(fit["any_trig"].sum()),
            "clusters_pre2023_none_triggered": int((~fit["any_trig"]).sum()),
        },
        "clusters_per_window_end_year": cl.groupby("year").size().to_dict(),
        "fund_windows_per_window_end_year": df["window_end_year"].dropna().astype(int).value_counts().sort_index().to_dict(),
        "computability": {
            "windows_with_dates": int((df["window_start"].notna() & df["window_end"].notna()).sum()),
            "windows_known_before_start": int(df["window_known_before_start"].eq(True).sum()),
            "windows_announced_after_start": int((df["window_known_before_start"] == False).sum()),  # noqa: E712
            "metric_basis_counts": df["metric_basis"].value_counts().to_dict(),
            "fund_windows_panel_coverage_ge_min": int(len(covered)),
            "clusters_panel_covered_known_outcome": int(len(cov_clusters)),
            "clusters_panel_covered_known_outcome_pre2023": int(len(cov_clusters_fit)),
            "replication_rows": int(len(rep_daily)),
            "replication_within_tol": int((rep_daily["panel_minus_published_pp"].abs() <= REPLICATION_TOL_PP).sum()),
            "replication_median_abs_pp": (round(float(rep_daily["panel_minus_published_pp"].abs().median()), 3)
                                          if len(rep_daily) else None),
            "replication_max_abs_pp": (round(float(rep_daily["panel_minus_published_pp"].abs().max()), 3)
                                       if len(rep_daily) else None),
            "replication_panels": rep_daily["panel"].value_counts().to_dict(),
            "outcome_rows_panel_can_check": int(len(imp)),
            "outcome_rows_panel_agrees": int(imp_agree.sum()),
            "outcome_rows_panel_disagrees": imp[~imp_agree][["pid", "ticker", "window_end", "outcome",
                                                             "panel_avg_pct", "metric_basis"]].to_dict("records"),
        },
        "gate_proposed": gate(m),
        "live_book": live,
        "thresholds": {"MIN_COVERAGE": MIN_COVERAGE, "REPLICATION_TOL_PP": REPLICATION_TOL_PP,
                       "INFER_DAYS": INFER_DAYS, "BLK_CHECK_DAYS": BLK_CHECK_DAYS},
    }


def live_exposure(df: pd.DataFrame, panels: dict) -> tuple[dict, pd.DataFrame]:
    """The deployed names (scripts/cef/spec.py) that were in a programme, and how near the trigger they came."""
    sys.path.insert(0, str(REPO / "scripts" / "cef"))
    import spec  # the frozen spec is the only authority on the universe
    names = list(spec.UNIVERSE)
    hit = df[df["ticker"].isin(names)]
    out = {"spec_id": spec.SPEC_ID, "universe": names, "names_in_a_programme": sorted(hit["ticker"].unique().tolist()),
           "windows": []}
    paths = []
    for w in hit.itertuples():
        rec = {"ticker": w.ticker, "pid": w.pid, "window": f"{w.window_start}..{w.window_end}",
               "announced": w.announced, "threshold_pct": w.threshold_pct, "published_avg_pct": w.published_avg_pct,
               "outcome": w.outcome,
               "published_distance_to_trigger_pp": (round(w.published_avg_pct + w.threshold_pct, 2)
                                                    if w.published_avg_pct is not None else None)}
        pnl = panels["live44"]
        sess = nyse_sessions(w.window_start, w.window_end)
        ra = running_average(pnl["px"].loc[w.ticker], pnl["nav"].loc[w.ticker], sess)
        last = ra.index.max()
        rec.update({"panel_last_session": str(last.date()), "panel_sessions_used": len(ra), "window_sessions": len(sess),
                    "panel_final_running_avg_pct": round(float(ra["running_avg_pct"].iloc[-1]), 3),
                    "panel_min_running_avg_pct": round(float(ra["running_avg_pct"].min()), 3),
                    "panel_min_running_avg_date": str(ra["running_avg_pct"].idxmin().date()),
                    "panel_days_daily_discount_beyond_threshold": int((ra["discount_pct"] < -w.threshold_pct).sum()),
                    "panel_min_daily_discount_pct": round(float(ra["discount_pct"].min()), 2)})
        ann = pd.Timestamp(w.announced)
        known = ra[ra.index < ann]
        rec["panel_running_avg_on_announcement_eve_pct"] = (round(float(known["running_avg_pct"].iloc[-1]), 3)
                                                            if len(known) else None)
        # What the rest of the window would have had to average for the trigger to fire, as known on the
        # announcement eve: (-threshold x all sessions - sum so far) / sessions left. Uses sessions < ann only.
        n_all, n_k = len(sess), len(known)
        rec["required_avg_over_rest_at_announcement_pct"] = (
            round(float((-w.threshold_pct * n_all - known["discount_pct"].sum()) / (n_all - n_k)), 3) if n_k < n_all else None)
        after20 = ra["running_avg_pct"].iloc[20:]
        rec["panel_min_running_avg_after_20_sessions_pct"] = round(float(after20.min()), 3) if len(after20) else None
        out["windows"].append(rec)
        paths.append(ra.assign(ticker=w.ticker).reset_index(names="date"))
    return out, (pd.concat(paths, ignore_index=True) if paths else pd.DataFrame())


def public_view(full: pd.DataFrame) -> pd.DataFrame:
    """The tracked census: every EDGAR fact and every coverage count, but no number computed on CRSP prices.

    CRSP is licensed and this repository is public (`.gitignore`, the WRDS
    block): row-level CRSP-derived values stay on disk. A window average from
    the CRSP-close panel is blanked here and replaced by a yes/no: did the panel
    reproduce the published figure within REPLICATION_TOL_PP? The aggregate
    counts in the summary JSON are tracked, as the policy allows."""
    out = full.copy()
    crsp = out["panel"].eq("c4_crsp_close")
    out["panel_reproduces_published"] = out["panel_minus_published_pp"].abs().le(REPLICATION_TOL_PP).where(
        out["panel_minus_published_pp"].notna())
    out.loc[crsp, ["panel_avg_pct", "panel_minus_published_pp"]] = None
    return out.drop(columns=[c for c in out.columns if c.endswith("_c4_crsp_close")])


# --------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="EDGAR from the cache only")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD (the index's current quarter)")
    a = ap.parse_args(argv)
    client = _client(a.offline)
    today = date.fromisoformat(a.today) if a.today else date.today()

    idx = edgar_index(client, today)
    filings, episodes = idx["filings"], idx["episodes"]
    docs = candidate_documents(filings, episodes)
    cands = account_for_hits(discover(client, docs))

    ws = build_windows(client)
    n_quotes = verify_evidence(client, P.PROGRAMMES, ws)
    inferred = check_inferred(filings, ws)
    blk = check_blk_triggers(filings, ws)

    filed_on = {(int(c), a): d for c, a, d in zip(filings["cik"], filings["accession"], filings["date_filed"])}
    df = windows_frame(ws, filed_on)
    panels = load_panels()
    cov = panel_coverage(df, panels)
    grp = independent_groups(df)
    live, live_path = live_exposure(df, panels)

    # recall of the scan: which programmes had a candidate document from their own funds
    cand_ciks = set(cands.loc[cands["candidate"], "cik"])
    found_by_scan = {p["pid"]: bool(set((p["funds"] if isinstance(p["funds"], dict) else P.BLK_CIK).values()) & cand_ciks)
                     for p in P.PROGRAMMES}
    meta = {"edgar_index_last_filing": idx["summary"]["last_date_filed_seen"],
            "candidate_documents_scanned": int(len(cands)), "candidate_documents_flagged": int(cands["candidate"].sum()),
            "candidate_funds_flagged": int(cands.loc[cands["candidate"], "cik"].nunique()),
            "candidate_funds_excluded": int(cands.loc[cands["candidate"] & cands["disposition"].str.startswith("excluded"), "cik"].nunique()),
            "programmes_found_by_scan": int(sum(found_by_scan.values())),
            "programmes_not_found_by_scan": sorted(k for k, v in found_by_scan.items() if not v),
            "quotes_verified": n_quotes, "inferred_rows_checked": len(inferred), "blk_table_crosscheck": blk,
            "excluded_other": P.EXCLUDED_OTHER,
            "panels": {k: {"last_nav": v["last_nav"], "last_px": v["last_px"]} for k, v in panels.items()}}
    summary = summarise(df, cov, grp, live, meta)

    OUT.mkdir(parents=True, exist_ok=True)
    full = df.merge(cov, on="row_id", how="left").drop(columns=["row_id"])
    full.to_csv(CENSUS_FULL_CSV, index=False)
    public_view(full).to_csv(CENSUS_CSV, index=False)
    progs = pd.DataFrame([{k: (json.dumps(v) if isinstance(v, (dict, tuple, list)) else v) for k, v in p.items()}
                          for p in P.PROGRAMMES])
    progs.to_csv(PROGRAMMES_CSV, index=False)
    cands.to_csv(CANDIDATES_CSV, index=False)
    live_path.to_csv(LIVE_PATH_CSV, index=False)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps({k: summary[k] for k in ("programmes", "fund_windows", "funds", "outcomes", "triggered_share_known",
                                              "triggered_share_documented_only", "independent_groups", "computability",
                                              "quotes_verified", "programmes_not_found_by_scan")},
                     indent=1, default=str))
    print(json.dumps(summary["live_book"], indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
