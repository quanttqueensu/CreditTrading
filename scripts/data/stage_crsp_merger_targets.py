"""CRSP daily rows for MA-HZ's cash-deal targets, 2001-2022, from the R2 WRDS mirror. ZERO TRIALS.

    export QUANTT_ENV_FILE=<absolute path to the env file holding the R2 keys and SEC_USER_AGENT>
    python3 scripts/data/stage_crsp_merger_targets.py                  # EDGAR 2001-09 + CRSP, ~1 h
    python3 scripts/data/stage_crsp_merger_targets.py --offline-edgar  # re-run: EDGAR from the cache only
    python3 scripts/data/stage_crsp_merger_targets.py --no-extension   # CRSP for the 2010-22 census only

The team lead runs it (it loads credentials). Agents never do. Then, offline:

    python3 scripts/events/mahz_spread_measure.py

WHY THIS EXISTS
---------------
`results/events/MERGER_ARB_V2_2026-10-19.md` names one design worth a
pre-registration, MA-HZ: long cash-merger targets in their high-hazard event
weeks, short them in their low-hazard weeks (Giglio & Shue 2014). Its §2.6
item 1 asks for a zero-trial data build before any trial is spent, and the
team lead asked for it on 2026-10-19: "the zero-trial CRSP pull for MA-HZ
(target prices and bid/ask, and the deal list back to 2001), so its spreads
can be measured before any trial is spent". This script stages that data. It
computes no statistic of the strategy; `scripts/events/mahz_spread_measure.py`
measures the zero-trial quantities (quoted spreads, the completion hazard,
turnover, capacity, power) and reads no return.

WHERE THE DEAL LIST COMES FROM (the note's own tables, said plainly)
--------------------------------------------------------------------
The merger-v2 note's deals are the EDGAR census of
`scripts/events/merger_arb_feasibility.py`: target-only anchor forms
(DEFM14A/PREM14A, DEFM14C/PREM14C, SC 14D9/SC14D9C) in EDGAR's quarterly
`master.gz` full index, chained back through 425 / SC TO-T / SC TO-C filings,
with the target's submissions JSON and announcement document for the
consideration class. Its CRSP inputs were `crsp_a_stock.dsedelist` and
`dsenames`, for counts only. CRSP has no announcement date and no failed deal
(a failed target does not delist), so the deal list cannot come from CRSP
alone: a CRSP-only list would hold completed deals only, the outcome
conditioning that made the note's stock universe unusable (§2.3).

* **2010-2022: the committed census, unchanged.** `results/events/merger_arb/
  edgar_deals.csv`, d0 on or after 2010-01-01, classified by
  `merger_arb_v2_feasibility.classify_universe`. These are the note's 1,251
  CASH_1STEP and 588 TENDER_CASH deals [V, `universe_by_year.csv`].
* **2001-2009: the same census rules, run here on EDGAR's 2000Q1-2012Q4
  indexes**, with ONE substitution, forced by the filing record:
    - the census calls a target LISTED if it filed a Form 25 / 25-NSE after
      d0, and COMPLETED if it filed one within 730 days of its last anchor.
      Electronic Form 25 on EDGAR was required only from the compliance date
      of Release 34-52029, 2006-04-24 (`docs/REFERENCES.md` §12au). Applied to
      2001-05 the census rule would call almost every completed target
      unlisted and drop it, keeping the failures: survivorship inverted.
    - so in the extension, LISTED means a CRSP common-stock record
      (`stocknames`, share code 10/11/12/18, exchange code 1/2/3) in force on
      d0 whose name matches the EDGAR target (`link_targets`), and only those
      deals are read from EDGAR.
  Other consequences, stated rather than fixed: 8-K item 1.01 exists only
  from 2004-08-23 (Release 33-8400), so an earlier one-step deal has no
  announcement document and is dated by d0, its first deal filing, an UPPER
  bound (`ann_basis = d0_upper_bound`, counted by year); its class is still
  structural (no 425 = cash), as in 2010+. Rule 425 exists from 2000-01-24
  (Release 33-7760), so the structural cash rule holds from 2001.
* **Completion, every year: CRSP**, so that one rule dates every deal: the
  linked permno's `dsedelist` row, attributed to the latest deal of that
  target whose d0 precedes it, if it falls within that deal's
  [d0, a1 + 730 days] (the census's COMPLETE_DAYS). A code 200-299 is a
  merger; any other code is a non-merger delisting, an OBSERVED failure date
  the census never had. The EDGAR Form 25 completion is kept beside it
  (`completed_edgar`, `delist_date_edgar`) so the two can be compared.

UNIVERSES: CASH_1STEP (the trial's universe) and TENDER_CASH (its negative
control, K3). Stock deals are not staged: the note recommends cash only, and
the stock universe is outcome-conditioned (§2.3).

TARGET -> PERMNO, BY NAME ON d0 (`link_targets`)
------------------------------------------------
CRSP carries no CIK. The EDGAR target name is matched to the CRSP names in
force on d0 by `edgar_merger_dates.name_score` (an in-order token alignment
built for CRSP's abbreviated names), with that module's MIN_SCORE and
MIN_MARGIN; the margin is taken over the next PERMCO, so two share classes of
one company are not "ambiguous" but `multi_class`. Only candidates whose first
significant word could align with the EDGAR name's first significant word are
scored (`token_credit`), which makes the match fast and assumes CRSP keeps the
word order (it abbreviates, it does not reorder). A deal is staged only when
`link_status == "linked"`; `multi_class`, `ambiguous`, `below_min` and
`no_candidate` are counted by year and never guessed. The link's accuracy is
measured where a second source exists: for completed 2010+ deals, the CRSP
delisting date against the census's Form 25 date (`stage_summary.json`).

WHAT IS STAGED, PER DEAL
------------------------
`dsf` rows (`DSF_COLS`: prc, bid, ask, bidlo, askhi, openprc, vol, numtrd,
ret, retx, shrout, cfacpr, cfacshr) for the linked permno from
PRE_SESSIONS of its own sessions before the announcement to POST_SESSIONS
after the deal's end: the CRSP delisting attributed to it, else announcement
+ 52 weeks (the note's bracket B), capped at the last fit day. PRE_SESSIONS is
63, not the 60 the request named: 63 is the desk's ADV window
(`merger_arb_feasibility.ADV_SESSIONS`), so a position entered in event week 1
has a full trailing ADV for the capacity check, and 63 covers 60. `dsedelist`
codes and payoffs (dlstcd, dlstdt, dlamt, dlpdt, dlprc, dlret, dlretx,
nwperm). CRSP conventions are kept as published (negative `prc` = no closing
trade; NaN `ret` stays NaN); nothing is filled.

THE 2023-01-01 TIME HOLDOUT. Every query stops at 2022-12-31: no `dsf` row and
no `dsedelist` row (dlret and dlretx are returns) dated on or after
2023-01-01 is requested, and `refuse_holdout` raises if a source hands one
back anyway. A deal still open at the censor is open; its later completion is
not fetched here.

WHERE IT WRITES. `data/events/merger_targets/` (gitignored by `/data/`),
through `cef_families_common.write_frame`, which refuses any path inside the
live `data/cef/`. CRSP is licensed and this repository is public: nothing
staged here is committed. `stage_summary.json` beside it holds counts only.
The EDGAR index is cached in `results/events/_cache_marb/` (gitignored), the
merger census's own cache.

NO SILENT FALLBACKS. A CRSP table missing a needed column raises, naming it.
Two `dsedelist` rows for one permno raise. A pre-announcement calendar pad too
short to hold PRE_SESSIONS rows raises. A census missing a column raises.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUT_DIR = REPO / "data" / "events" / "merger_targets"
LIVE_DIR = REPO / "data" / "cef"
DEALS_CSV = "deals.csv"                      # one row per staged-universe deal (licensed: permno, CRSP codes)
DSF_PARQUET = "crsp_dsf_targets.parquet"     # unique (permno, date)
DELIST_PARQUET = "crsp_delist_targets.parquet"
NAMES_CSV = "crsp_names_linked.csv"          # the CRSP name records the links used, for audit
EXT_CSV = "edgar_deals_2001_2009.csv"        # the census extension (EDGAR fields + the CRSP listing flag)
SUMMARY_JSON = "stage_summary.json"          # counts only

COMMITTED_CENSUS = REPO / "results" / "events" / "merger_arb" / "edgar_deals.csv"
EDGAR_CACHE = REPO / "results" / "events" / "_cache_marb"

STAGED_UNIVERSES = ("CASH_1STEP", "TENDER_CASH")
EXT_D0_FROM, EXT_D0_TO = pd.Timestamp("2001-01-01"), pd.Timestamp("2009-12-31")
COMMITTED_D0_FROM = pd.Timestamp("2010-01-01")
# EDGAR index span for the extension: a year of chain look-back before 2001
# (the census's LOOKBACK_DAYS), and to 2012Q4 so a late-2009 deal's anchors and
# its Form 25 within a1 + 730 days are inside the index.
EXT_INDEX_FROM, EXT_INDEX_TO = date(2000, 1, 1), date(2012, 12, 31)

HOLDOUT_START = pd.Timestamp("2023-01-01")   # sealed (CLAUDE.md research rules; H13)
LAST_FIT_DAY = pd.Timestamp("2022-12-31")    # every query stops here
PRE_SESSIONS = 63                            # = merger_arb_feasibility.ADV_SESSIONS (checked in the tests)
POST_SESSIONS = 10
# Calendar days fetched before `ann`. 63 sessions span at most 63 / 5 * 7 = 88.2 weekday-days plus the
# market's closures inside them (about 9 holidays a year, the four-day closure of 2001-09-11, two days
# for Hurricane Sandy in 2012); 130 leaves 40 days for those, so the pad cannot bind and a deal with
# fewer than PRE_SESSIONS pre rows is one whose CRSP history starts later (counted, never filled).
PRE_PAD_DAYS = 130
assert PRE_PAD_DAYS >= PRE_SESSIONS / 5 * 7 + 21
POST_PAD_DAYS = 30
OPEN_WEEKS = 52                              # a deal with no attributed delisting is followed to ann + 52 weeks (bracket B)
COMPLETE_DAYS = 730                          # = merger_arb_feasibility.COMPLETE_DAYS (checked in the tests)

LINK_SHRCD = (10, 11, 12, 18)                # as `merger_arb_feasibility.match_crsp`
LISTED_EXCHCD = (1, 2, 3)                    # NYSE, NYSE American (AMEX), Nasdaq: as `crsp_by_year`
MERGER_DLSTCD = (200, 299)
ACTIVE_DLSTCD = (100, 199)                   # "Issue still trading" (CRSP guide §6.3): not a delisting

NAME_COLS = ["permno", "permco", "namedt", "nameenddt", "shrcd", "exchcd", "comnam", "ticker"]
DELIST_COLS = ["permno", "dlstdt", "dlstcd", "nwperm", "dlamt", "dlpdt", "dlprc", "dlret", "dlretx"]
DSF_COLS = ["permno", "date", "prc", "bid", "ask", "bidlo", "askhi", "openprc", "vol", "numtrd",
            "ret", "retx", "shrout", "cfacpr", "cfacshr"]
RETURN_FIELDS = ("ret", "retx", "dlret", "dlretx")
CENSUS_COLS = ["deal", "target_cik", "target_name", "d0", "a1", "doc_date", "doc_source", "ann", "ann_basis",
               "tender", "stock_structural", "text_class", "final_class", "universe", "acquirer_cik",
               "target_rule", "target_registered", "sic", "completed", "delist_date"]


class StageError(RuntimeError):
    pass


# =========================================================================== guards
def refuse_holdout(frame: pd.DataFrame, date_col: str, what: str) -> None:
    """Raise if any row is dated on or after 2023-01-01. Every query already stops
    at LAST_FIT_DAY; this catches a source that ignored the bound, before a return
    field (RETURN_FIELDS) of a sealed year can be written anywhere."""
    d = pd.to_datetime(frame[date_col])
    n = int((d >= HOLDOUT_START).sum())
    if n:
        raise StageError(f"{what}: {n} row(s) dated on/after {HOLDOUT_START.date()} reached the stage; "
                         f"the time holdout is sealed and {', '.join(RETURN_FIELDS)} are returns")


def require_columns(have, need, table: str) -> None:
    miss = [c for c in need if c not in set(have)]
    if miss:
        raise StageError(f"CRSP table {table} lacks column(s) {miss}; nothing is staged without them")


# =========================================================================== census
def load_committed_census(path: Path = COMMITTED_CENSUS) -> pd.DataFrame:
    """The note's 2010+ census, with `ann` and `universe` exactly as the v2 script makes them."""
    from scripts.events.merger_arb_v2_feasibility import load_deals
    d = load_deals(path)
    d = d[d["d0"] >= COMMITTED_D0_FROM].copy()
    d["source"] = "census_2010"
    return d


def load_index_range(client, lo: date, hi: date, today: date, offline: bool) -> pd.DataFrame:
    """EDGAR quarterly master indexes for [lo, hi], filtered to the census's forms.

    The census's own `load_index` starts at its INDEX_FROM (2009-07-01); this is
    the same fetch for another span, cached under its own name."""
    from scripts.data.fetch_edgar_events import DAY, INDEX_URL, parse_master_index, quarter_is_closed, quarters
    from scripts.events.merger_arb_feasibility import INDEX_FORMS
    p = EDGAR_CACHE / f"index_{lo}_{hi}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    if offline:
        raise FileNotFoundError(f"offline and no cached {p.name}")
    frames = []
    for y, q in quarters(lo, hi):
        t = client.get_text(INDEX_URL.format(y=y, q=q), max_age_s=None if quarter_is_closed(y, q, today) else DAY)
        frames.append(parse_master_index(t, label=f"{y}Q{q}", keep_forms=INDEX_FORMS))
    idx = pd.concat(frames, ignore_index=True)
    EDGAR_CACHE.mkdir(parents=True, exist_ok=True)
    idx.to_parquet(p)
    return idx


def extend_census(idx: pd.DataFrame, names: pd.DataFrame, enrich_fn,
                  d0_from: pd.Timestamp = EXT_D0_FROM, d0_to: pd.Timestamp = EXT_D0_TO) -> tuple[pd.DataFrame, dict]:
    """The census rules on an earlier index, with LISTED from CRSP (module docstring).

    `enrich_fn(deals) -> deals` is `merger_arb_feasibility.enrich` bound to an
    EDGAR client (the tests pass a fake). Only CRSP-linked deals are enriched,
    exactly as the census enriches only listed ones. Returns the in-scope deals
    with `ann`, `universe`, the link columns, and a dict of counts."""
    from scripts.events import merger_arb_feasibility as F
    from scripts.events.merger_arb_v2_feasibility import announcement_dates, classify_universe
    funds = set(int(c) for c in idx.loc[idx["form"].isin(F.FUND_FORMS), "cik"])
    tickers = pd.DataFrame(columns=["cik", "name", "ticker", "exchange"])   # "listed today" is not used here
    deals = F.assemble_deals(idx, funds, tickers)
    deals = deals[(deals["d0"] >= d0_from) & (deals["d0"] <= d0_to)].reset_index(drop=True)
    link = link_targets(deals[["target_name", "d0"]].rename(columns={"d0": "on"}), names)
    deals = pd.concat([deals, link], axis=1)
    deals["listed_form25_rule"] = deals["listed"]
    deals["listed"] = deals["link_status"].eq("linked")
    d = enrich_fn(deals)
    # `enrich` writes these only on the deals it reads; if it read none, the columns are absent.
    # They stay empty: no in-scope deal (scope = listed = enriched) is ever given a value here.
    for c in ("sic", "text_class", "text_why", "doc_source", "doc_accession", "doc_name", "doc_date"):
        if c not in d.columns:
            d[c] = np.nan
    d["spac_name"] = d["target_name"].str.contains(F.SPAC_NAME_RE)
    d["spac"] = (d["sic"] == F.SPAC_SIC) | d["spac_name"]
    reg_all = F._dates_by_cik(idx, F.REG_FORMS)
    d["target_registered"] = [F._any_in(reg_all.get(int(r["target_cik"])), r["d0"] - pd.Timedelta(days=F.LOOKBACK_DAYS),
                                        r["a1"] + pd.Timedelta(days=F.TAIL_DAYS)) for _, r in d.iterrows()]
    scope = d[d["listed"] & ~d["spac"].fillna(False).astype(bool)].copy()
    if "doc_date" not in scope.columns:
        scope["doc_date"] = pd.NaT
    scope["doc_date"] = pd.to_datetime(scope["doc_date"])
    scope["final_class"] = scope.apply(F.final_class, axis=1)
    scope["ann"], scope["ann_basis"] = announcement_dates(scope)
    scope["universe"] = classify_universe(scope)
    scope["source"] = "extension_2001"
    counts = {"assembled_deals": int(len(deals)),
              "link_status": {k: int(v) for k, v in deals["link_status"].value_counts().items()},
              "form25_rule_listed": int(deals["listed_form25_rule"].sum()),
              "crsp_listed": int(deals["listed"].sum()),
              "spac_excluded": int((d["listed"] & d["spac"].fillna(False).astype(bool)).sum()),
              "primary_document_unusable": int(d["text_why"].astype(str).str.startswith(
                  "primary document unusable").sum()),
              "in_scope": int(len(scope)),
              "universe": {k: int(v) for k, v in scope["universe"].value_counts().items()},
              "ann_basis_by_year": {f"{y}|{b}": int(n) for (y, b), n in
                                    scope.groupby([scope["d0"].dt.year, "ann_basis"]).size().items()}}
    return scope, counts


def enrich_each(enrich_one, deals: pd.DataFrame) -> pd.DataFrame:
    """`merger_arb_feasibility.enrich`, one deal at a time, recording an unusable
    primary-document name instead of aborting the run.

    The census reader catches EDGAR's 404 (`EdgarNotFound`) and records it; its
    `fetch_doc` raises ValueError on a primary-document name it will not build a
    URL from (empty, or with a path in it). The 2010+ census never met one; a
    2001-04 filing may. Such a deal is recorded exactly as a 404 is: class
    `unclassified`, the reason in `text_why`, counted. Any other error raises."""
    out = []
    for i in range(len(deals)):
        one = deals.iloc[[i]]
        try:
            out.append(enrich_one(one))
        except ValueError as e:
            if "bad primary document name" not in str(e):
                raise
            rec = one.copy()
            rec["text_class"], rec["text_why"] = "unclassified", f"primary document unusable: {e}"
            for c in ("doc_source", "doc_accession", "doc_name"):
                rec[c] = None
            out.append(rec)
        if (i + 1) % 250 == 0:
            print(f"  enrich: {i + 1}/{len(deals)} deals", flush=True)
    return pd.concat(out, ignore_index=True) if out else deals.copy()


def splice_census(ext: pd.DataFrame, committed: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Extension (d0 < 2010) + committed census (d0 >= 2010). A deal of the same
    target whose [d0, a1] overlaps a committed deal's is the same transaction seen
    from two indexes: the committed row is kept (it is the note's), and the
    overlaps are counted."""
    c = committed.copy()
    c["deal_id"] = "C" + c["deal"].astype(int).astype(str)
    if ext is None or ext.empty:
        return c, 0
    e = ext.copy()
    e["deal_id"] = "X" + e["deal"].astype(int).astype(str)
    j = e[["deal_id", "target_cik", "d0", "a1"]].merge(c[["target_cik", "d0", "a1"]], on="target_cik",
                                                       suffixes=("", "_c"))
    ov = j[(j["d0"] <= j["a1_c"]) & (j["d0_c"] <= j["a1"])]["deal_id"].unique()
    e = e[~e["deal_id"].isin(ov)]
    return pd.concat([e, c], ignore_index=True, sort=False), int(len(ov))


# =========================================================================== CRSP link
def _sig(tokens: tuple) -> tuple:
    from scripts.events.edgar_merger_dates import GENERIC
    s = tuple(t for t in tokens if t not in GENERIC)
    return s if s else tuple(tokens)


def prepare_names(names: pd.DataFrame) -> pd.DataFrame:
    """CRSP name records with tokens; records without a name are dropped (counted by the caller)."""
    from scripts.events.edgar_merger_dates import name_tokens
    require_columns(names.columns, NAME_COLS, "stocknames (as staged)")
    if names["permco"].isna().any() or names["permno"].isna().any():
        raise StageError("a CRSP name record has no permno or permco")
    n = names[names["comnam"].notna() & names["comnam"].astype(str).str.strip().ne("")].copy()
    n["namedt"], n["nameenddt"] = pd.to_datetime(n["namedt"]), pd.to_datetime(n["nameenddt"])
    n["tok"] = [name_tokens(x) for x in n["comnam"]]
    n["first"] = [_sig(t)[0] for t in n["tok"]]
    return n.reset_index(drop=True)


def link_targets(targets: pd.DataFrame, names: pd.DataFrame) -> pd.DataFrame:
    """For each (target_name, on) row: the CRSP permno whose name record in force on
    `on` matches it (module docstring). Returns one row per input row, same index.

    Status: linked | multi_class | ambiguous | below_min | no_candidate | no_name."""
    from scripts.events.edgar_merger_dates import MIN_MARGIN, MIN_SCORE, name_score, name_tokens, token_credit
    n = names if "tok" in names.columns else prepare_names(names)
    n = n[n["shrcd"].isin(LINK_SHRCD) & n["exchcd"].isin(LISTED_EXCHCD)]
    by_letter = {k: g for k, g in n.groupby(n["first"].str[0])}
    out = []
    for i, r in targets.iterrows():
        rec = {"link_status": None, "permno": np.nan, "permco": np.nan, "crsp_comnam": None, "link_score": np.nan,
               "runner_up_score": np.nan, "exchcd_at_d0": np.nan, "shrcd_at_d0": np.nan, "n_permnos": 0}
        nm, on = r["target_name"], pd.Timestamp(r["on"])
        if not isinstance(nm, str) or not nm.strip():
            rec["link_status"] = "no_name"
            out.append(rec)
            continue
        et = name_tokens(nm)
        ef = _sig(et)[0]
        g = by_letter.get(ef[0])
        if g is not None:
            g = g[(g["namedt"] <= on) & (g["nameenddt"] >= on)]
            g = g.loc[np.array([bool(token_credit(c, ef)) for c in g["first"]], dtype=bool)]
        if g is None or g.empty:
            rec["link_status"] = "no_candidate"
            out.append(rec)
            continue
        g = g.assign(s=[name_score(t, et) for t in g["tok"]])
        per_co = g.groupby("permco")["s"].max().sort_values(ascending=False)
        best_co, s1 = per_co.index[0], float(per_co.iloc[0])
        s2 = float(per_co.iloc[1]) if len(per_co) > 1 else -np.inf
        rec["link_score"] = round(s1, 3)
        rec["runner_up_score"] = round(s2, 3) if np.isfinite(s2) else np.nan
        top = g[(g["permco"] == best_co) & (g["s"] == s1)]
        rec["n_permnos"] = int(top["permno"].nunique())
        if s1 < MIN_SCORE:
            rec["link_status"] = "below_min"
        elif s1 - s2 < MIN_MARGIN:
            rec["link_status"] = "ambiguous"
        elif top["permno"].nunique() > 1:
            rec["link_status"] = "multi_class"
            rec["permco"] = int(best_co)
        else:
            t = top.iloc[0]
            rec.update(link_status="linked", permno=int(t["permno"]), permco=int(best_co), crsp_comnam=t["comnam"],
                       exchcd_at_d0=int(t["exchcd"]), shrcd_at_d0=int(t["shrcd"]))
        out.append(rec)
    return pd.DataFrame(out, index=targets.index)


# =========================================================================== delistings and windows
def attribute_delistings(deals: pd.DataFrame, delist: pd.DataFrame) -> pd.DataFrame:
    """Attach each linked permno's `dsedelist` row to the deal it ends (module docstring):
    the latest deal of that permno with d0 <= dlstdt, if dlstdt <= that deal's a1 + 730 days.

    Adds dlstcd, dlstdt, dlamt, dlpdt, dlprc, nwperm and `crsp_outcome` in
    {merger, other_delist, none}. A code 100-199 ("still trading") is not a
    delisting and is never attributed. Two delisting rows for one permno raise."""
    refuse_holdout(delist, "dlstdt", "dsedelist")
    dl = delist.copy()
    dl["dlstdt"] = pd.to_datetime(dl["dlstdt"])
    if dl["permno"].duplicated().any():
        raise StageError(f"dsedelist holds two rows for permno(s) {sorted(dl.loc[dl.permno.duplicated(), 'permno'].unique())[:5]}")
    out = deals.copy()
    for c in ("dlstcd", "dlamt", "dlprc", "nwperm"):
        out[c] = np.nan
    out["dlstdt"], out["dlpdt"] = pd.NaT, pd.NaT
    out["crsp_outcome"] = "none"
    by = dl.set_index("permno")
    linked = out[out["permno"].notna()]
    for p, g in linked.groupby("permno"):
        if int(p) not in by.index:
            continue
        row = by.loc[int(p)]
        if ACTIVE_DLSTCD[0] <= int(row["dlstcd"]) <= ACTIVE_DLSTCD[1]:
            continue
        when = row["dlstdt"]
        cand = g[g["d0"] <= when].sort_values("d0")
        if cand.empty:
            continue
        i = cand.index[-1]
        if when > cand.loc[i, "a1"] + pd.Timedelta(days=COMPLETE_DAYS):
            continue
        code = int(row["dlstcd"])
        out.loc[i, ["dlstcd", "dlamt", "dlprc", "nwperm"]] = [code, row["dlamt"], row["dlprc"], row["nwperm"]]
        out.loc[i, "dlstdt"] = when
        out.loc[i, "dlpdt"] = pd.to_datetime(row["dlpdt"]) if pd.notna(row["dlpdt"]) else pd.NaT
        out.loc[i, "crsp_outcome"] = "merger" if MERGER_DLSTCD[0] <= code <= MERGER_DLSTCD[1] else "other_delist"
    return out


def deal_windows(deals: pd.DataFrame) -> pd.DataFrame:
    """Each staged deal's END (its attributed delisting, else ann + 52 weeks, capped
    at the last fit day) and the calendar span fetched for it."""
    out = deals.copy()
    open_end = out["ann"] + pd.Timedelta(weeks=OPEN_WEEKS)
    end = out["dlstdt"].where(out["crsp_outcome"].ne("none"), open_end)
    out["end"] = end.where(end <= LAST_FIT_DAY, LAST_FIT_DAY)
    out["fetch_lo"] = out["ann"] - pd.Timedelta(days=PRE_PAD_DAYS)
    hi = out["end"] + pd.Timedelta(days=POST_PAD_DAYS)
    out["fetch_hi"] = hi.where(hi <= LAST_FIT_DAY, LAST_FIT_DAY)
    return out


def trim_windows(deals: pd.DataFrame, dsf: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep, per deal, at most PRE_SESSIONS of the permno's own rows before `ann`, every
    row from `ann` to `end`, and at most POST_SESSIONS after `end`. Returns the
    unique (permno, date) rows kept and the deals with their row counts. Fewer
    than PRE_SESSIONS pre rows means the security's CRSP history starts later
    (the pad cannot bind: PRE_PAD_DAYS); it is counted, never filled."""
    refuse_holdout(dsf, "date", "dsf")
    d = dsf.copy()
    d["date"] = pd.to_datetime(d["date"])
    if d.duplicated(["permno", "date"]).any():
        raise StageError("dsf rows are not unique by (permno, date); `unique_rows` first")
    groups = {int(p): g.sort_values("date") for p, g in d.groupby("permno")}
    keep, counts = [], []
    for i, r in deals.iterrows():
        g = groups.get(int(r["permno"]))
        if g is None:
            counts.append({"idx": i, "pre_sessions": 0, "post_sessions": 0, "rows": 0})
            continue
        g = g[(g["date"] >= r["fetch_lo"]) & (g["date"] <= r["fetch_hi"])]
        pre = g[g["date"] < r["ann"]].tail(PRE_SESSIONS)
        mid = g[(g["date"] >= r["ann"]) & (g["date"] <= r["end"])]
        post = g[g["date"] > r["end"]].head(POST_SESSIONS)
        k = pd.concat([pre, mid, post])
        keep.append(k)
        counts.append({"idx": i, "pre_sessions": len(pre), "post_sessions": len(post), "rows": len(k)})
    c = pd.DataFrame(counts).set_index("idx")
    out = deals.join(c)
    rows = pd.concat(keep, ignore_index=True) if keep else d.iloc[0:0]
    rows = rows.drop_duplicates(["permno", "date"]).sort_values(["permno", "date"]).reset_index(drop=True)
    return rows, out


# =========================================================================== sources
class R2Source:
    """The R2 WRDS mirror, read-only (`src/data/r2.py`). Credentials come from the env
    file named by $QUANTT_ENV_FILE and are never printed."""

    def __init__(self):
        from src.data import r2
        self._r2 = r2
        self.cfg = r2.load_config()
        self.con = r2.connect(self.cfg)

    def _p(self, table: str) -> str:
        return self._r2.r2_path("crsp_a_stock", table, self.cfg)

    def columns(self, table: str) -> list[str]:
        return [r[0] for r in self.con.execute(f"DESCRIBE SELECT * FROM read_parquet('{self._p(table)}')").fetchall()]

    def names(self) -> pd.DataFrame:
        return self.con.execute(
            f"SELECT {', '.join(NAME_COLS)} FROM read_parquet('{self._p('stocknames')}') "
            f"WHERE shrcd IN ({','.join(map(str, LINK_SHRCD))}) AND exchcd IN ({','.join(map(str, LISTED_EXCHCD))}) "
            f"AND nameenddt >= DATE '2000-01-01' AND namedt <= DATE '{LAST_FIT_DAY.date()}'").df()

    def delistings(self, permnos: list[int]) -> pd.DataFrame:
        return self.con.execute(
            f"SELECT {', '.join(DELIST_COLS)} FROM read_parquet('{self._p('dsedelist')}') "
            f"WHERE permno IN ({','.join('?' * len(permnos))}) AND dlstdt <= DATE '{LAST_FIT_DAY.date()}'",
            permnos).df()

    def dsf(self, windows: pd.DataFrame) -> pd.DataFrame:
        w = windows[["permno", "fetch_lo", "fetch_hi"]].copy()
        w["permno"] = w["permno"].astype("int64")
        self.con.register("mahz_windows", w)
        try:
            # the explicit IN list lets the parquet scan skip row groups before the join (as the CEF
            # staging scripts query dsf); the join then cuts each permno to its deals' windows
            perms = sorted(int(p) for p in w["permno"].unique())
            return self.con.execute(
                f"SELECT {', '.join('d.' + c for c in DSF_COLS)} FROM read_parquet('{self._p('dsf')}') d "
                f"JOIN mahz_windows w ON d.permno = w.permno "
                f"AND d.date BETWEEN CAST(w.fetch_lo AS DATE) AND CAST(w.fetch_hi AS DATE) "
                f"WHERE d.permno IN ({','.join('?' * len(perms))}) AND d.date <= DATE '{LAST_FIT_DAY.date()}'",
                perms).df()
        finally:
            self.con.unregister("mahz_windows")


# =========================================================================== the stage
def unique_rows(dsf: pd.DataFrame) -> pd.DataFrame:
    """One row per (permno, date). Two deals of one target fetch overlapping windows,
    so exact duplicates are expected and dropped; two DIFFERENT rows for one
    (permno, date) raise (the source would be ambiguous)."""
    d = dsf.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.normalize().astype("datetime64[ns]")
    d = d.drop_duplicates()
    if d.duplicated(["permno", "date"]).any():
        raise StageError("dsf holds two different rows for one (permno, date)")
    return d.reset_index(drop=True)


def _floats(frame: pd.DataFrame, cols) -> pd.DataFrame:
    for c in cols:
        if c in frame.columns:
            frame[c] = frame[c].astype(float)
    return frame


def stage(source, census: pd.DataFrame, names: pd.DataFrame | None = None) -> dict:
    """Link, attribute delistings, fetch and trim. Returns the frames to write and
    a summary of counts. Pure given `source` (the tests pass a fake)."""
    miss = [c for c in CENSUS_COLS + ["deal_id", "source"] if c not in census.columns]
    if miss:
        raise StageError(f"census lacks {miss}")
    require_columns(source.columns("stocknames"), NAME_COLS, "stocknames")
    require_columns(source.columns("dsedelist"), DELIST_COLS, "dsedelist")
    require_columns(source.columns("dsf"), DSF_COLS, "dsf")
    c = census[census["universe"].isin(STAGED_UNIVERSES) & (census["ann"] < HOLDOUT_START)].copy()
    c = c.reset_index(drop=True)
    names = prepare_names(source.names() if names is None else names)
    link = link_targets(c[["target_name", "d0"]].rename(columns={"d0": "on"}), names)
    c = pd.concat([c.drop(columns=[k for k in link.columns if k in c.columns]), link], axis=1)
    linked = c[c["link_status"].eq("linked")].copy()
    perms = sorted(int(p) for p in linked["permno"].unique())
    dl = source.delistings(perms) if perms else pd.DataFrame(columns=DELIST_COLS)
    refuse_holdout(dl, "dlstdt", "dsedelist")
    dl = _floats(dl, ["dlamt", "dlprc", "dlret", "dlretx"])
    linked = attribute_delistings(linked, dl)
    linked = deal_windows(linked)
    dsf = source.dsf(linked) if len(linked) else pd.DataFrame(columns=DSF_COLS)
    refuse_holdout(dsf, "date", "dsf")
    dsf = unique_rows(_floats(dsf, ["prc", "bid", "ask", "bidlo", "askhi", "openprc", "vol", "ret", "retx",
                                    "shrout", "cfacpr", "cfacshr"]))
    rows, linked = trim_windows(linked, dsf)
    deals = c.merge(
        linked[["deal_id", "dlstcd", "dlstdt", "dlamt", "dlpdt", "dlprc", "nwperm", "crsp_outcome", "end",
                "fetch_lo", "fetch_hi", "pre_sessions", "post_sessions", "rows"]], on="deal_id", how="left")
    deals = deals.rename(columns={"completed": "completed_edgar", "delist_date": "delist_date_edgar"})
    used = names[names["permno"].isin(perms)].drop(columns=["tok", "first"])
    return {"deals": deals, "dsf": rows, "delist": dl[dl["permno"].isin(perms)], "names": used,
            "summary": summarise(deals, rows)}


def summarise(deals: pd.DataFrame, rows: pd.DataFrame) -> dict:
    """Counts only: what was staged, what was not and why, and the link's agreement
    with the census's Form 25 dates where both exist (2010+ completions)."""
    yr = deals["ann"].dt.year
    lk = deals["link_status"].eq("linked")
    both = deals[lk & deals["crsp_outcome"].eq("merger") & deals["completed_edgar"].astype(bool)
                 & deals["delist_date_edgar"].notna()]
    gap = (pd.to_datetime(both["dlstdt"]) - pd.to_datetime(both["delist_date_edgar"])).dt.days.abs()
    edgar_done = deals[lk & deals["completed_edgar"].astype(bool) & deals["delist_date_edgar"].notna()
                       & (pd.to_datetime(deals["delist_date_edgar"]) <= LAST_FIT_DAY)]
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "zero_trials": True,
        "deals_in_staged_universes": int(len(deals)),
        "by_universe_and_link_status": {f"{u}|{s}": int(n) for (u, s), n in
                                        deals.groupby(["universe", "link_status"]).size().items()},
        "linked_by_ann_year": {int(y): int(n) for y, n in deals[lk].groupby(yr[lk]).size().items()},
        "not_linked_by_ann_year": {int(y): int(n) for y, n in deals[~lk].groupby(yr[~lk]).size().items()},
        "crsp_outcome_linked": {k: int(v) for k, v in deals.loc[lk, "crsp_outcome"].value_counts().items()},
        "form25_vs_crsp": {"edgar_completed_by_2022_linked": int(len(edgar_done)),
                           "of_which_crsp_merger_delisting": int(len(both)),
                           "abs_gap_days_median": float(gap.median()) if len(gap) else None,
                           "abs_gap_days_le_15": int((gap <= 15).sum())},
        "dsf_rows": int(len(rows)), "dsf_permnos": int(rows["permno"].nunique()) if len(rows) else 0,
        "dsf_first": str(rows["date"].min().date()) if len(rows) else None,
        "dsf_last": str(rows["date"].max().date()) if len(rows) else None,
        "deals_short_pre_window": int((deals.loc[lk, "pre_sessions"] < PRE_SESSIONS).sum()),
    }


def write_outputs(res: dict, ext: pd.DataFrame | None, ext_counts: dict | None, out_dir: Path | None = None) -> None:
    from scripts.data.cef_families_common import write_frame
    out_dir = OUT_DIR if out_dir is None else Path(out_dir)
    write_frame(res["deals"], DEALS_CSV, base=out_dir, live=LIVE_DIR)
    write_frame(res["dsf"], DSF_PARQUET, base=out_dir, live=LIVE_DIR)
    write_frame(res["delist"].reset_index(drop=True), DELIST_PARQUET, base=out_dir, live=LIVE_DIR)
    write_frame(res["names"], NAMES_CSV, base=out_dir, live=LIVE_DIR)
    if ext is not None:
        write_frame(ext.drop(columns=[c for c in ("tok",) if c in ext.columns]), EXT_CSV, base=out_dir, live=LIVE_DIR)
    s = dict(res["summary"])
    s["extension"] = ext_counts
    p = out_dir / SUMMARY_JSON
    p.write_text(json.dumps(s, indent=1, default=str))


def main(argv=None) -> int:
    pd.set_option("compute.use_numexpr", False)        # scripts/events/numexpr_fault.py
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline-edgar", action="store_true", help="EDGAR from the cache only (a re-run)")
    ap.add_argument("--no-extension", action="store_true", help="stage the committed 2010-22 census only")
    a = ap.parse_args(argv)
    today = date.today()
    src = R2Source()
    names = src.names()
    print(f"CRSP stocknames: {len(names):,} common-stock records on NYSE/AMEX/Nasdaq, 2000..2022", flush=True)
    committed = load_committed_census()
    ext, ext_counts = None, None
    if not a.no_extension:
        from scripts.events import merger_arb_feasibility as F
        client = F.edgar(a.offline_edgar)
        idx = load_index_range(client, EXT_INDEX_FROM, EXT_INDEX_TO, today, a.offline_edgar)
        print(f"EDGAR index {EXT_INDEX_FROM}..{EXT_INDEX_TO}: {len(idx):,} rows", flush=True)
        ext, ext_counts = extend_census(
            idx, prepare_names(names),
            lambda d: enrich_each(lambda one: F.enrich(client, one, a.offline_edgar, today), d))
        print("extension:", json.dumps(ext_counts, default=str), flush=True)
    census, overlaps = splice_census(ext, committed)
    if ext_counts is not None:
        ext_counts["overlaps_dropped_in_favour_of_committed"] = overlaps
    res = stage(src, census, names)
    write_outputs(res, ext, ext_counts, OUT_DIR)
    s = res["summary"]
    print(json.dumps({k: v for k, v in s.items() if k != "generated_utc"}, indent=1, default=str))
    print(f"wrote {OUT_DIR}/ ({DEALS_CSV}, {DSF_PARQUET}, {DELIST_PARQUET}, {NAMES_CSV}"
          f"{', ' + EXT_CSV if ext is not None else ''}, {SUMMARY_JSON}); next: "
          f"python3 scripts/events/mahz_spread_measure.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
