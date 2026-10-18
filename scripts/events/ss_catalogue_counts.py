"""Event counts and pre-event liquidity for the special-situations catalogue, half 1 (zero trials).

    export QUANTT_ENV_FILE=/abs/path/config/.env     # R2, SEC_USER_AGENT and the Alpaca keys; never printed
    python3 scripts/events/ss_catalogue_counts.py crsp
    python3 scripts/events/ss_catalogue_counts.py edgar [--edgar-cache DIR --offline]
    python3 scripts/events/ss_catalogue_counts.py alpaca
    python3 scripts/events/ss_catalogue_counts.py all

WHY THIS EXISTS
---------------
The team lead asked on 2026-10-15 for a systematic catalogue of event-driven and
special-situation sub-strategies (`results/events/SPECIAL_SITUATIONS_CATALOGUE_CORP_2026-10-15.md`).
Each row needs "events per year and independent groups", and the desk's rule is
that a count is fetched, never recalled. This script is where every count in
that note comes from. It computes NO return of any strategy: it counts events,
the issuers behind them, and the liquidity of the issuers BEFORE the event.
No trial is spent and no counter moves.

THREE SOURCES, EACH WITH A DIFFERENT BLIND SPOT
-----------------------------------------------
1. CRSP CIZ tables on the R2 mirror (`stkdistributions`, `stkdelists`,
   `stksecurityinfohist`; mirror ends 2024-12-31, `results/data/R2_CATALOG.md`).
   The event taxonomy is CRSP's own: `disdetailtype`, `distype`,
   `delactiontype` and `delreasontype` are decoded from the mirror's
   `metaflaginfo` table (flag types AD, AT, CD, DR), so no code meaning is
   recalled. CRSP covers exchange-listed securities only: an OTC event is
   invisible here by construction. Event counts may use 2023-24 (they are not
   returns; `scripts/events/crsp_events.py` states the same rule). The
   pre-event ADV uses `dsf` price x volume and only for events dated
   2018-01-01..2022-12-31, so no 2023+ market data is read at all.
   Security type at the event date is an AS-OF join (the last
   `stksecurityinfohist` row starting on or before the date), because a
   delisting or a cash-merger payment falls after the security's last info
   row and a BETWEEN join leaves it unclassified (measured 2026-10-15: 2,417
   cash-merger rows fell into "UNK" that way).
2. EDGAR quarterly full indexes (`master.gz`) through `scripts/data/edgar_client.py`,
   parsed by `scripts/data/fetch_edgar_events.py::parse_master_index`. Form
   counts per year, as unique accessions. A filing is indexed once per party,
   so a third-party tender (SC TO-T) appears under bidder and target; counting
   accessions, not rows, removes that double count. "Fund" filers are the
   fetcher's own `fund_set` rule (a CIK that filed a closed-end-only form, or
   N-CSR plus Form 3/4); everything else is labelled "non-fund". SC TO-I by a
   non-fund is NOT the same as an equity buyback tender: it also covers
   warrant and option exchange offers and convertible-note repurchase offers.
   The note says so.
3. Alpaca, read-only GETs only (paper endpoint, cef key, `quantt/broker/alpaca.py`):
   (a) `GET /v2/assets` (active) for tradable/shortable/easy-to-borrow flags,
   true on the date of the read only; (b) `GET /v1/corporate-actions` by
   type and calendar window, counted per type. Alpaca says its corporate
   actions carry "no guarantees on the creation time" and its history depth
   is undocumented, so the earliest date returned is printed, and 2024 is
   compared with CRSP where both exist (a second source, not an average).
   The corporate-actions call goes through `AlpacaClient._get`, the client's
   retrying, key-scrubbing GET; no order method is touched.

OUTPUTS (aggregates only; CRSP is licensed and this repository is public)
--------------------------------------------------------------------------
`results/events/ss_catalogue/`:
  crsp_distribution_events_by_year.csv   class x subtype x year: events, issuers, months
  crsp_delistings_by_year.csv            action x reason x subtype x year
  crsp_dual_class_by_year.csv            permcos with >= 2 listed common lines, per year-end
  crsp_pre_event_adv.csv                 per class, 2018-22 events: median ADV, share >= $0.1m/$1m/$10m
  edgar_form_counts_by_year.csv          form x fund/non-fund x year: accessions, CIKs
  alpaca_corporate_actions_by_year.csv   type x year (process-date window)
  alpaca_flags_summary.json              hedge ETFs, CEF index ETFs, dual-class legs, exchange mix
  run_meta.json                          when each part ran and on what
Row-level tables carrying CRSP identifiers (the dual-class ticker list) go to
`results/events/ss_catalogue/_cache_rows/`, gitignored by `results/**/_cache_*`.

NO SILENT FALLBACKS: a missing table, an empty result where events must exist,
or an unknown flag value raises naming what was missing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "events" / "ss_catalogue"
ROWS = OUT / "_cache_rows"
COUNT_START, COUNT_END = date(2010, 1, 1), date(2024, 12, 31)      # CRSP counts
ADV_START, ADV_END = date(2018, 1, 1), date(2022, 12, 31)          # pre-holdout liquidity only
TIME_HOLDOUT = date(2023, 1, 1)
assert ADV_END < TIME_HOLDOUT, "pre-event ADV must not read 2023+ market data"
EDGAR_START_YEAR, EDGAR_END_YEAR = 2010, 2025                       # closed years only

# Event classes over CRSP's own codes (decoded from metaflaginfo AD/AT at run time).
# Each class is a predicate on (distype, disdetailtype, disfacpr).
DIST_CLASSES = {
    "special_dividend": "d.distype = 'SD'",
    # (A "CD with disfreqtype E" class was tried first and is EMPTY for 2010-24:
    # CRSP codes specials as distype SD, measured 2026-10-15. Removed, not defaulted.)
    "spin_off": "d.disdetailtype = 'SECSO'",
    "rights_distribution": "d.disdetailtype IN ('SECRD', 'URTSD')",
    "reverse_split": "d.distype = 'FRS' AND d.disfacpr < 0",
    "forward_split_ge_2for1": "d.distype = 'FRS' AND d.disfacpr >= 1",
    "self_tender_or_exchange_in_kind": "d.disdetailtype IN ('CPBLST', 'SECBLST', 'SECEX', 'CPEX', 'CPEXCSH', 'SECDO')",
    "non_ordinary_security_distribution": "d.disdetailtype = 'SECNOD'",
    "partial_liquidation": "d.disdetailtype IN ('CPPL', 'SECPL', 'CPSIL')",
    "final_liquidation_payment": "d.disdetailtype IN ('CPFL', 'SECFL', 'SECSTL', 'ULIQ')",
}
CODES_USED = {"AT": {"SD", "CD", "FRS"},
              "AD": {"SECSO", "SECRD", "URTSD", "CPBLST", "SECBLST", "SECEX", "CPEX", "CPEXCSH",
                     "SECDO", "SECNOD", "CPPL", "SECPL", "CPSIL", "CPFL", "SECFL", "SECSTL", "ULIQ"},
              "S2": {"COM", "CEF", "ETF"}, "S4": {"NS"},
              "CD": {"GDR", "GEX", "GLI", "MER"}}

# EDGAR forms counted (initial filings; amendments excluded on purpose: one event, one count).
EDGAR_FORMS = ("SC TO-I", "SC TO-T", "SC TO-C", "SC 13E3", "SC 14D9", "SC 13D",
               "10-12B", "10-12G", "25-NSE", "25", "15-12B", "15-12G",
               "N-23C3A", "N-23C3B", "N-23C3C", "N-8F", "N-2", "N-54A", "N-54C", "N-14 8C",
               "DEFM14A", "S-4", "S-11", "424B4")

# Alpaca corporate-action types counted (cash_dividend is paged separately: its volume is large).
ALPACA_CA_TYPES = ("spin_off", "reverse_split", "forward_split", "unit_split", "stock_dividend",
                   "rights_distribution", "cash_merger", "stock_merger", "stock_and_cash_merger",
                   "name_change", "worthless_removal", "redemption", "partial_call", "reorganization")
ALPACA_YEARS = tuple(range(2016, 2027))
# Instruments looked up by name in the active-asset list. A symbol absent from
# the list is recorded as absent: that is a finding, never a default.
HEDGE_ETFS = ("SPY", "IWM", "QQQ", "MDY", "IJR", "XLF", "XLE", "XLK", "XLV", "XLI", "XLU", "XLY", "XLP",
              "XLB", "XLRE", "XLC", "KRE", "XBI", "HYG", "LQD", "MUB", "PFF")
CEF_INDEX_ETFS = ("CEFS", "PCEF", "YYY", "FCEF", "CEFD", "MCEF")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _meta_update(part: str, rec: dict) -> None:
    path = OUT / "run_meta.json"
    m = json.loads(path.read_text()) if path.exists() else {}
    m[part] = rec
    path.write_text(json.dumps(m, indent=1, sort_keys=True, default=str) + "\n")


# ---------------------------------------------------------------- CRSP

def _crsp_con():
    from src.data.r2 import connect, r2_path
    con = connect()
    paths = {t: r2_path("crsp_a_stock", t) for t in
             ("stkdistributions", "stkdelists", "stksecurityinfohist", "metaflaginfo", "dsf")}
    return con, paths


def _check_codes(con, paths) -> dict:
    """Every CRSP code this script keys on must exist in the mirror's own code table."""
    from src.data.r2 import q
    mf = q(con, f"SELECT flagtype, flagvalue, flagdesc FROM read_parquet('{paths['metaflaginfo']}')")
    out = {}
    for ft, vals in CODES_USED.items():
        have = set(mf.loc[mf.flagtype == ft, "flagvalue"])
        missing = vals - have
        if missing:
            raise KeyError(f"CRSP flag type {ft}: codes {sorted(missing)} not in metaflaginfo")
        out[ft] = {v: mf.loc[(mf.flagtype == ft) & (mf.flagvalue == v), "flagdesc"].iloc[0] for v in sorted(vals)}
    return out


def _asof_dist_sql(paths, where: str, start: date, end: date) -> str:
    return f"""
    WITH d AS (
      SELECT permno, disexdt, distype, disfreqtype, disdetailtype, disfacpr, disfacshr, disdivamt
      FROM read_parquet('{paths['stkdistributions']}')
      WHERE disexdt BETWEEN DATE '{start}' AND DATE '{end}'),
    s AS (
      SELECT permno, secinfostartdt, securitysubtype, sharetype, permco, issuernm, ticker
      FROM read_parquet('{paths['stksecurityinfohist']}'))
    SELECT d.*, s.securitysubtype AS sub, s.sharetype AS sharetype, s.permco AS permco,
           s.issuernm AS issuernm
    FROM d ASOF LEFT JOIN s ON d.permno = s.permno AND d.disexdt >= s.secinfostartdt
    WHERE {where}"""


def _adv_table(px: pd.DataFrame, events: pd.DataFrame, lo: int, hi: int) -> pd.DataFrame:
    """Mean dollar volume over sessions [-hi, -lo) before each event date, per event."""
    by = {p: g for p, g in px.groupby("permno")}
    out = []
    for r in events.itertuples(index=False):
        g = by.get(r.permno)
        if g is None:
            continue
        pre = g[g["date"] < r.date].tail(hi).head(hi - lo)
        if len(pre) < 0.75 * (hi - lo):
            continue
        out.append({"cls": r.cls, "sub": r.sub, "adv": float(pre["dv"].mean())})
    return pd.DataFrame(out)


def _summ(a: pd.DataFrame) -> pd.DataFrame:
    return a.groupby(["cls", "sub"]).agg(
        n_events_with_adv=("adv", "size"), median_adv_usd=("adv", "median"),
        p25_adv_usd=("adv", lambda s: s.quantile(0.25)),
        share_adv_ge_100k=("adv", lambda s: (s >= 1e5).mean()),
        share_adv_ge_1m=("adv", lambda s: (s >= 1e6).mean()),
        share_adv_ge_10m=("adv", lambda s: (s >= 1e7).mean())).reset_index()


def _extra_adv(con, paths, dl: pd.DataFrame) -> pd.DataFrame:
    """Two capacity rows the distribution table cannot give.

    (a) ETF liquidations (CRSP delisting action GLI on an ETF), 2018-22: ADV
        over sessions -60..-41 before the delisting date, a window chosen to
        sit before a typical closure announcement (announcements run weeks
        ahead of the last trading day [U: not measured here]) so the figure
        is the ETF's ordinary liquidity, not its wind-down volume.
    (b) Dual-class lines: for each permco with >= 2 listed common lines at
        2022-12-31 (pre-holdout), the LESS liquid line's mean dollar volume over
        2022-07-01..2022-12-30. The thinner leg sets a pair's capacity.
    """
    from src.data.r2 import q
    rows = []
    e = dl[(dl["sub"] == "ETF") & (dl["delactiontype"] == "GLI")].copy()
    e["date"] = pd.to_datetime(e["delistingdt"])
    e = e[(e["date"] >= pd.Timestamp(ADV_START)) & (e["date"] <= pd.Timestamp(ADV_END))]
    if e.empty:
        raise RuntimeError("no ETF liquidations 2018-22 in stkdelists")
    e["cls"] = "etf_liquidation"
    px = q(con, f"""SELECT permno, date, abs(prc) * vol AS dv FROM read_parquet('{paths['dsf']}')
                    WHERE date BETWEEN DATE '2017-09-01' AND DATE '{ADV_END}'
                      AND permno IN ({','.join(map(str, sorted(e.permno.unique())))})
                      AND prc IS NOT NULL AND vol IS NOT NULL""")
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].max() >= pd.Timestamp(TIME_HOLDOUT):
        raise RuntimeError("a 2023+ dsf row was read")
    rows.append(_summ(_adv_table(px.sort_values(["permno", "date"]), e[["cls", "permno", "date", "sub"]], 41, 60)))

    d = q(con, f"""SELECT permco, permno FROM read_parquet('{paths['stksecurityinfohist']}')
                   WHERE secinfostartdt <= DATE '2022-12-31' AND secinfoenddt >= DATE '2022-12-31'
                     AND securitysubtype = 'COM' AND sharetype = 'NS' AND tradingstatusflg = 'A'""")
    k = d.groupby("permco").permno.nunique()
    d = d[d.permco.isin(k[k >= 2].index)]
    if d.empty:
        raise RuntimeError("no dual-class permcos at 2022-12-31")
    v = q(con, f"""SELECT permno, avg(abs(prc) * vol) AS adv FROM read_parquet('{paths['dsf']}')
                   WHERE date BETWEEN DATE '2022-07-01' AND DATE '2022-12-30'
                     AND permno IN ({','.join(map(str, sorted(d.permno.unique())))})
                     AND prc IS NOT NULL AND vol IS NOT NULL GROUP BY permno""")
    m = d.merge(v, on="permno", how="inner").groupby("permco").adv.min().rename("adv").reset_index()
    m["cls"], m["sub"] = "dual_class_thinner_line_2022H2", "COM"
    rows.append(_summ(m[["cls", "sub", "adv"]]))
    return pd.concat(rows, ignore_index=True)


def crsp_part() -> None:
    from src.data.r2 import q
    con, paths = _crsp_con()
    codes = _check_codes(con, paths)
    frames, events_for_adv = [], []
    for cls, pred in DIST_CLASSES.items():
        ev = q(con, _asof_dist_sql(paths, pred, COUNT_START, COUNT_END))
        if ev.empty:
            raise RuntimeError(f"CRSP class {cls}: no events 2010-24; the predicate or the mirror is wrong")
        ev["disexdt"] = pd.to_datetime(ev["disexdt"])
        # One event = one (permno, ex-date): a spin-off of two securities on one date is one event.
        ev = ev.drop_duplicates(["permno", "disexdt"])
        ev["cls"] = cls
        ev["sub"] = ev["sub"].where(ev["sub"].notna(), "UNMATCHED")
        ev["year"] = ev["disexdt"].dt.year
        ev["month"] = ev["disexdt"].dt.to_period("M").astype(str)
        g = ev.groupby(["cls", "sub", "year"]).agg(events=("permno", "size"), issuers=("permco", "nunique"),
                                                   months_with_events=("month", "nunique")).reset_index()
        frames.append(g)
        events_for_adv.append(ev[["cls", "permno", "disexdt", "sub", "sharetype", "issuernm"]])
    dist = pd.concat(frames, ignore_index=True)
    dist.to_csv(OUT / "crsp_distribution_events_by_year.csv", index=False)

    # Delistings, AS-OF classified.
    dl = q(con, f"""
      WITH d AS (SELECT permno, delistingdt, delactiontype, delreasontype, delpaymenttype
                 FROM read_parquet('{paths['stkdelists']}')
                 WHERE delistingdt BETWEEN DATE '{COUNT_START}' AND DATE '{COUNT_END}'),
      s AS (SELECT permno, secinfostartdt, securitysubtype, sharetype, permco
            FROM read_parquet('{paths['stksecurityinfohist']}'))
      SELECT d.*, s.securitysubtype AS sub, s.sharetype, s.permco
      FROM d ASOF LEFT JOIN s ON d.permno = s.permno AND d.delistingdt >= s.secinfostartdt""")
    if dl.empty:
        raise RuntimeError("CRSP stkdelists: no delistings 2010-24")
    dl["year"] = pd.to_datetime(dl["delistingdt"]).dt.year
    dl["sub"] = dl["sub"].where(dl["sub"].notna(), "UNMATCHED")
    dlg = dl.groupby(["sub", "delactiontype", "delreasontype", "delpaymenttype", "year"]).agg(
        delistings=("permno", "size"), issuers=("permco", "nunique")).reset_index()
    dlg.to_csv(OUT / "crsp_delistings_by_year.csv", index=False)

    # Dual-class: permcos with >= 2 simultaneously listed common, non-ADR lines at each year-end.
    rows, dual_2024 = [], None
    for y in range(COUNT_START.year, COUNT_END.year + 1):
        ye = date(y, 12, 31)
        d = q(con, f"""
          SELECT permco, permno, shareclass, ticker, issuernm, primaryexch
          FROM read_parquet('{paths['stksecurityinfohist']}')
          WHERE secinfostartdt <= DATE '{ye}' AND secinfoenddt >= DATE '{ye}'
            AND securitysubtype = 'COM' AND sharetype = 'NS' AND tradingstatusflg = 'A'""")
        if d.empty:
            raise RuntimeError(f"no active common lines at {ye}")
        k = d.groupby("permco").permno.nunique()
        multi = k[k >= 2].index
        rows.append({"year_end": str(ye), "active_common_permcos": int(k.size),
                     "permcos_with_2plus_lines": int(len(multi)),
                     "lines_in_those_permcos": int(d[d.permco.isin(multi)].permno.nunique())})
        if y == COUNT_END.year:
            dual_2024 = d[d.permco.isin(multi)].sort_values(["permco", "shareclass"])
    pd.DataFrame(rows).to_csv(OUT / "crsp_dual_class_by_year.csv", index=False)
    ROWS.mkdir(parents=True, exist_ok=True)
    dual_2024.to_csv(ROWS / "crsp_dual_class_lines_2024-12-31.csv", index=False)

    # Pre-event ADV, COM non-ADR and CEF only, events 2018-01-01..2022-12-31.
    ev = pd.concat(events_for_adv, ignore_index=True)
    ev = ev[(ev.disexdt >= pd.Timestamp(ADV_START)) & (ev.disexdt <= pd.Timestamp(ADV_END))
            & (((ev["sub"] == "COM") & (ev["sharetype"] == "NS")) | (ev["sub"] == "CEF"))]
    permnos = sorted(ev.permno.unique().tolist())
    if not permnos:
        raise RuntimeError("no 2018-22 events for the ADV pass")
    px = q(con, f"""
      SELECT permno, date, abs(prc) * vol AS dv FROM read_parquet('{paths['dsf']}')
      WHERE date BETWEEN DATE '2017-11-01' AND DATE '{ADV_END}'
        AND permno IN ({','.join(map(str, permnos))}) AND prc IS NOT NULL AND vol IS NOT NULL""")
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].max() >= pd.Timestamp(TIME_HOLDOUT):
        raise RuntimeError("a 2023+ dsf row was read: the time holdout is sealed")
    px = px.sort_values(["permno", "date"])
    # ADV = mean dollar volume over the 20 sessions ending two sessions before the ex-date
    # (the information is public by then for every class counted here; the window avoids
    # the event's own flow).
    out = []
    by = {p: g for p, g in px.groupby("permno")}
    for r in ev.itertuples(index=False):
        g = by.get(r.permno)
        if g is None:
            continue
        pre = g[g["date"] < r.disexdt].tail(22).head(20)
        if len(pre) < 15:
            continue
        out.append({"cls": r.cls, "sub": r.sub, "adv": float(pre["dv"].mean())})
    a = pd.DataFrame(out)
    if a.empty:
        raise RuntimeError("ADV pass produced no events with 15+ prior sessions")
    adv = a.groupby(["cls", "sub"]).agg(
        n_events_with_adv=("adv", "size"), median_adv_usd=("adv", "median"),
        p25_adv_usd=("adv", lambda s: s.quantile(0.25)),
        share_adv_ge_100k=("adv", lambda s: (s >= 1e5).mean()),
        share_adv_ge_1m=("adv", lambda s: (s >= 1e6).mean()),
        share_adv_ge_10m=("adv", lambda s: (s >= 1e7).mean())).reset_index()
    adv = pd.concat([adv, _extra_adv(con, paths, dl)], ignore_index=True)
    adv.to_csv(OUT / "crsp_pre_event_adv.csv", index=False)
    _meta_update("crsp", {"ran_utc": _now(), "count_window": [str(COUNT_START), str(COUNT_END)],
                          "adv_window": [str(ADV_START), str(ADV_END)], "codes_decoded": codes,
                          "source": "R2 WRDS mirror crsp_a_stock CIZ tables (mirror ends 2024-12-31)"})
    print(dist.groupby(["cls", "sub"]).events.sum().unstack("sub").fillna(0).astype(int).to_string())
    print(adv.to_string(index=False))


# ---------------------------------------------------------------- EDGAR

def edgar_part(cache: Path | None, offline: bool) -> None:
    from scripts.data.edgar_client import EdgarClient, CACHE
    from scripts.data import fetch_edgar_events as fe
    client = EdgarClient(cache=cache or CACHE, offline=offline)
    keep = set(EDGAR_FORMS) | fe.MARKER_FORMS | fe.NCSR_FORMS | fe.INSIDER_FORMS
    frames = []
    for y in range(2008, EDGAR_END_YEAR + 1):          # 2008-09 only to build the fund set
        for qn in (1, 2, 3, 4):
            text = client.get_text(fe.INDEX_URL.format(y=y, q=qn))   # closed quarters: immutable
            frames.append(fe.parse_master_index(text, label=f"{y}Q{qn}", keep_forms=keep))
    idx = pd.concat(frames, ignore_index=True)
    funds = fe.fund_set(idx)
    ev = idx[idx.form.isin(EDGAR_FORMS)].copy()
    ev["year"] = ev.date_filed.dt.year
    ev = ev[(ev.year >= EDGAR_START_YEAR) & (ev.year <= EDGAR_END_YEAR)]
    # A filing is "fund" if ANY CIK it is indexed under is in the fund set.
    acc_fund = ev.assign(f=ev.cik.isin(funds)).groupby("accession").f.any()
    ev["filer_kind"] = ev.accession.map(acc_fund).map({True: "fund", False: "non-fund"})
    g = ev.groupby(["form", "filer_kind", "year"]).agg(accessions=("accession", "nunique"),
                                                        ciks=("cik", "nunique")).reset_index()
    g.to_csv(OUT / "edgar_form_counts_by_year.csv", index=False)
    _meta_update("edgar", {"ran_utc": _now(), "years": [EDGAR_START_YEAR, EDGAR_END_YEAR],
                           "requests": client.n_requests, "cache_hits": client.n_cache_hits,
                           "cache": "default" if cache is None else "external (read-only, offline)",
                           "fund_set_size": len(funds)})
    piv = g.groupby(["form", "filer_kind"]).accessions.sum().unstack("filer_kind").fillna(0).astype(int)
    print(piv.to_string())


# ---------------------------------------------------------------- Alpaca

def _ca_count(c, types: str, start: date, end: date) -> tuple[dict, str | None]:
    counts, first, token = {}, None, None
    for _ in range(500):
        params = {"types": types, "start": start.isoformat(), "end": end.isoformat(), "limit": 1000}
        if token:
            params["page_token"] = token
        body = c._get(c._data, "/v1/corporate-actions", params)
        if "corporate_actions" not in body:
            raise RuntimeError("GET /v1/corporate-actions: no corporate_actions key")
        for k, rows in (body["corporate_actions"] or {}).items():
            counts[k] = counts.get(k, 0) + len(rows)
            for r in rows:
                pdte = r.get("process_date")
                if pdte and (first is None or pdte < first):
                    first = pdte
        nxt = body.get("next_page_token")
        if not nxt:
            return counts, first
        if nxt == token:
            raise RuntimeError("next_page_token did not advance")
        token = nxt
    raise RuntimeError("more than 500 pages")


def spin_off_reconcile(c, years=(2023, 2024)) -> dict:
    """Alpaca's raw `spin_off` rows against CRSP's SECSO count, for the years both cover.

    Measured 2026-10-15: Alpaca's 2024 window holds 48 `spin_off` rows against
    CRSP's 10 common-stock spin-offs. Read row by row, Alpaca's type also holds
    contingent-value-right and warrant distributions (new symbols with "CVR" in
    them or ending in "W") and BACKFILLED events (process date in the window,
    ex-date years earlier). This applies those three filters, each stated, and
    counts what is left by (source symbol, ex-date) on an exchange-listed
    source. It does not average the two sources; the note reports both.
    """
    act = {a["symbol"]: a["exchange"] for a in c.assets(status="active")}
    out = {}
    for y in years:
        body = c._get(c._data, "/v1/corporate-actions",
                      {"types": "spin_off", "start": f"{y}-01-01", "end": f"{y}-12-31", "limit": 1000})
        if body.get("next_page_token"):
            raise RuntimeError(f"spin_off {y}: more than one page; page it before counting")
        rows = pd.DataFrame(body["corporate_actions"].get("spin_offs") or [])
        if rows.empty:
            raise RuntimeError(f"spin_off {y}: no rows")
        raw = len(rows)
        ns = rows["new_symbol"].astype(str)
        cvr_or_warrant = ns.str.contains("CVR") | ns.str.match(r"^[A-Z]{3,5}W$")
        backfilled = ~rows["ex_date"].astype(str).str.startswith(str(y))
        listed_src = rows["source_symbol"].map(act).isin(["NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"])
        keep = rows[~cvr_or_warrant & ~backfilled].drop_duplicates(["source_symbol", "ex_date"])
        out[str(y)] = {"raw_rows": raw, "cvr_or_warrant_rows": int(cvr_or_warrant.sum()),
                       "backfilled_rows": int(backfilled.sum()),
                       "kept_unique_source_exdate": int(len(keep)),
                       "kept_with_source_listed_today": int(listed_src.loc[keep.index].sum())}
    return out


def event_name_flags(c, year: int, A: pd.DataFrame) -> dict:
    """Today's Alpaca flags on the names behind one year's events (a feasibility gate, not history).

    For each event type, the symbols Alpaca's corporate-actions feed names for
    `year`, looked up in TODAY's active list: found / tradable / shortable /
    easy to borrow / on the OTC venue. Survivorship runs one way here: a
    symbol that has since been delisted or renamed is "absent", so the shares
    describe the survivors and overstate what was shortable at the event.
    """
    spec = {"spin_off": ("spin_offs", ("source_symbol", "new_symbol")),
            "reverse_split": ("reverse_splits", ("symbol",)),
            "rights_distribution": ("rights_distributions", ("source_symbol", "new_symbol"))}
    out = {}
    for t, (key, fields) in spec.items():
        rows, token = [], None
        for _ in range(50):
            params = {"types": t, "start": f"{year}-01-01", "end": f"{year}-12-31", "limit": 1000}
            if token:
                params["page_token"] = token
            body = c._get(c._data, "/v1/corporate-actions", params)
            rows += (body.get("corporate_actions") or {}).get(key) or []
            nxt = body.get("next_page_token")
            if not nxt:
                break
            token = nxt
        else:
            raise RuntimeError(f"{t} {year}: more than 50 pages")
        df = pd.DataFrame(rows)
        if df.empty:
            raise RuntimeError(f"{t} {year}: no rows")
        df = df[df["ex_date"].astype(str).str.startswith(str(year))] if "ex_date" in df else df
        for f in fields:
            syms = df[f].dropna().astype(str)
            syms = syms[~syms.str.contains("CVR") & ~syms.str.match(r"^[0-9A-Z]{9}$")].unique()
            found = [x for x in syms if x in A.index]
            sub = A.loc[found] if found else A.iloc[0:0]
            out[f"{t}.{f}"] = {"symbols": int(len(syms)), "in_active_list": int(len(found)),
                               "tradable": int(sub["tradable"].sum()), "shortable": int(sub["shortable"].sum()),
                               "easy_to_borrow": int((sub["easy_to_borrow"] == True).sum()),  # noqa: E712
                               "on_otc": int((sub["exchange"] == "OTC").sum())}
    return out


def alpaca_part() -> None:
    from quantt.broker.alpaca import AlpacaClient
    c = AlpacaClient.from_environment("cef")
    clock = c.clock()
    asof = clock["timestamp"]                       # a datetime (the client parses it)
    today = asof.date() if hasattr(asof, "date") else date.fromisoformat(str(asof)[:10])
    asof = asof.isoformat() if hasattr(asof, "isoformat") else str(asof)
    rows, earliest = [], None
    for y in ALPACA_YEARS:
        start, end = date(y, 1, 1), min(date(y, 12, 31), today)
        if start > today:
            break
        counts, first = _ca_count(c, ",".join(ALPACA_CA_TYPES), start, end)
        if first and (earliest is None or first < earliest):
            earliest = first
        for k, n in counts.items():
            rows.append({"year": y, "window_end": str(end), "type_key": k, "count": n})
        # Specials: cash dividends flagged special, one page loop per year.
        sp, tot, token = 0, 0, None
        for _ in range(2000):
            params = {"types": "cash_dividend", "start": start.isoformat(), "end": end.isoformat(), "limit": 1000}
            if token:
                params["page_token"] = token
            body = c._get(c._data, "/v1/corporate-actions", params)
            cd = (body.get("corporate_actions") or {}).get("cash_dividends") or []
            tot += len(cd)
            sp += sum(1 for r in cd if r.get("special") is True)
            nxt = body.get("next_page_token")
            if not nxt:
                break
            if nxt == token:
                raise RuntimeError("next_page_token did not advance (cash_dividend)")
            token = nxt
        else:
            raise RuntimeError("cash_dividend paging exceeded 2000 pages")
        rows.append({"year": y, "window_end": str(end), "type_key": "cash_dividends_total", "count": tot})
        rows.append({"year": y, "window_end": str(end), "type_key": "cash_dividends_special_flag", "count": sp})
        print(y, {r["type_key"]: r["count"] for r in rows if r["year"] == y})
    ca = pd.DataFrame(rows)
    ca.to_csv(OUT / "alpaca_corporate_actions_by_year.csv", index=False)

    assets = pd.DataFrame(c.assets(status="active"))
    if assets.empty:
        raise RuntimeError("GET /v2/assets returned no active assets")
    A = assets.set_index("symbol")

    def flags(syms):
        out = {}
        for s in syms:
            if s in A.index:
                r = A.loc[s]
                out[s] = {k: (None if pd.isna(r[k]) else (bool(r[k]) if k in ("tradable", "shortable", "easy_to_borrow",
                                                                              "fractionable", "marginable") else r[k]))
                          for k in ("exchange", "tradable", "shortable", "easy_to_borrow", "fractionable")}
            else:
                out[s] = "ABSENT from the active list"
        return out

    dual_path = ROWS / "crsp_dual_class_lines_2024-12-31.csv"
    dual_summary = None
    if dual_path.exists():
        d = pd.read_csv(dual_path)
        d["alpaca_sym"] = d["ticker"].astype(str).str.replace(r"\.", "", regex=True)
        # CRSP tickers carry no class suffix punctuation; Alpaca writes BRK.B. Match both forms.
        def look(t, cls):
            for s in (t, f"{t}.{cls}" if isinstance(cls, str) and len(cls) == 1 else None):
                if s and s in A.index:
                    return s
            return None
        d["alpaca_symbol"] = [look(t, c_) for t, c_ in zip(d["ticker"].astype(str), d["shareclass"])]
        d["shortable"] = [bool(A.loc[s, "shortable"]) if s else None for s in d["alpaca_symbol"]]
        d["etb"] = [(None if s is None or pd.isna(A.loc[s, "easy_to_borrow"]) else bool(A.loc[s, "easy_to_borrow"]))
                    for s in d["alpaca_symbol"]]
        d.to_csv(ROWS / "dual_class_lines_with_alpaca_flags.csv", index=False)
        per = d.groupby("permco").agg(lines=("permno", "size"),
                                      found=("alpaca_symbol", lambda s: s.notna().sum()),
                                      shortable=("shortable", lambda s: sum(x is True for x in s)),
                                      etb=("etb", lambda s: sum(x is True for x in s)))
        dual_summary = {"permcos_2024": int(len(per)),
                        "all_lines_found_at_alpaca": int((per.found == per.lines).sum()),
                        "two_plus_lines_shortable": int((per.shortable >= 2).sum()),
                        "two_plus_lines_easy_to_borrow": int((per.etb >= 2).sum())}
    summary = {"asof_alpaca_clock": asof, "endpoint": "GET /v2/assets?status=active&asset_class=us_equity (paper, cef key)",
               "n_active": int(len(A)),
               "exchange_mix_active": A["exchange"].value_counts().to_dict(),
               "exchange_mix_tradable": A[A["tradable"]]["exchange"].value_counts().to_dict(),
               "symbols_ending_RT_or_dotRT": int(A.index.str.contains(r"(?:\.RT|RT)$").sum()),
               "symbols_ending_dotRT_tradable_by_exchange": A[A.index.str.endswith(".RT")].groupby("exchange")["tradable"].agg(["size", "sum"]).astype(int).to_dict("index"),
               "symbols_with_dot_WS": int(A.index.str.contains(r"\.WS").sum()),
               "symbols_with_dot_U": int(A.index.str.endswith(".U").sum()),
               "hedge_etfs": flags(HEDGE_ETFS), "cef_index_etfs": flags(CEF_INDEX_ETFS),
               "dual_class": dual_summary,
               "earliest_corporate_action_process_date_seen": earliest,
               "spin_off_reconcile": spin_off_reconcile(c),
               "event_name_flags_2025": event_name_flags(c, 2025, A)}
    (OUT / "alpaca_flags_summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n")
    _meta_update("alpaca", {"ran_utc": _now(), "clock": asof, "years": list(ALPACA_YEARS)})
    print(json.dumps({k: v for k, v in summary.items() if k not in ("hedge_etfs", "cef_index_etfs")}, indent=1, default=str))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("part", choices=("crsp", "edgar", "alpaca", "all"))
    ap.add_argument("--edgar-cache", type=Path, default=None,
                    help="read EDGAR indexes from this cache directory (e.g. another worktree's)")
    ap.add_argument("--offline", action="store_true", help="EDGAR: cache only, no network")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    if a.part in ("crsp", "all"):
        crsp_part()
    if a.part in ("edgar", "all"):
        edgar_part(a.edgar_cache, a.offline)
    if a.part in ("alpaca", "all"):
        alpaca_part()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
