"""A1, CEF share issuance at a premium (at-the-market programmes and shelf offerings): the zero-trial gate.

    python3 scripts/events/a1_cef_issuance_gate.py census --edgar-cache DIR --crsp-cache DIR [DIR ...]
    python3 scripts/events/a1_cef_issuance_gate.py levels --edgar-cache DIR --crsp-cache DIR [DIR ...]
    python3 -m pytest scripts/events/tests/test_a1_cef_issuance_gate.py

`DIR` for EDGAR is an existing `results/events/_cache_edgar` (any worktree's, read
only); for CRSP, one or more `results/events/_cache_crsp` directories, whose
`dsf_*` extracts are unioned. **Nothing here opens a network connection or reads
a credential**: it parses cached EDGAR quarterly indexes (`master.gz`) and cached
CRSP extracts directly. It never constructs `scripts/data/edgar_client.EdgarClient`
(which reads SEC_USER_AGENT from the env file) and never calls `crsp_events`
(which reads R2). A missing input raises, naming it.

WHY THIS EXISTS
---------------
Team lead, 2026-10-19: start the zero-trial checks on the new event paths. Path
A1: when a closed-end fund trades above NAV its sponsor can sell new shares into
the premium, through an N-2 shelf and prospectus supplements, often an
at-the-market (ATM) sales agreement. That makes the share count elastic, but only
upwards and only above NAV: section 23(b) of the 1940 Act bars a registered
closed-end fund from selling common below NAV outside rights offerings and a few
other exceptions (`docs/REFERENCES.md` §12av). An ATM is therefore a ONE-SIDED
authorised participant. `docs/BRIEF.md` §2 and the frozen spec's description rest
the whole book on "a fixed share count and no authorised participants"; A1 asks
whether, for the funds that issue, the premium side of that is false, and whether
the live z-score is blind to it.

WHAT IT COUNTS (census), AND HOW AN EVENT IS DEFINED
----------------------------------------------------
Two independent methods, each from one structural source, then joined:

* **E, EDGAR.** Every listed registered CEF (a CRSP share-code 14/44 permno linked
  to an EDGAR CIK that files N-CSR, and not a BDC) and its offering filings from
  the quarterly indexes: shelf forms (`SHELF_FORMS`) and prospectus supplements
  (`SUPP_FORMS`: Rule 424(b) forms and, before the 2020 offering reform, Rule 497).
  Supplements are grouped per fund into episodes (a gap over `EPISODE_GAP_DAYS`
  starts a new one); an episode's date is its FIRST supplement, the earliest date
  the offering was public on EDGAR. Supplements within `IPO_EXCLUDE_DAYS` of the
  fund's first CRSP row are the IPO's and are dropped (counted).
* **C, CRSP shares outstanding.** A seasoned quarter (fund older than
  `SEASONED_QUARTERS`) whose raw `shrout` rose by at least `MIN_Q_GROWTH`, with no
  split (`cfacpr` change), no CRSP merger into the fund within `MERGER_Q_PAD`
  quarters (`dsedelist` `nwperm`), no CRSP rights distribution (code 45xx) in that
  quarter or the `RIGHTS_Q_AFTER` before it, AND beyond what dividend reinvestment
  could have issued: trailing four-quarter share growth above the trailing
  four-quarter distribution yield divided by `DRIP_PRICE_FLOOR`. A DRIP issues new
  shares only at or above NAV, at the greater of NAV and 95% of the market price
  (two cached N-14 8C plan descriptions, §12av), so 100% participation can add at
  most yield/0.95 a year. CRSP updates `shrout` irregularly (some funds yearly),
  which is why the bound is on four quarters, not one.
* **Joined.** An EDGAR episode is `confirmed` if a C quarter falls within
  `CONFIRM_QUARTERS_AFTER` quarters of its date; `rights` if a CRSP 45xx ex-date
  lies within `RIGHTS_EDGAR_DAYS` of it (rights offerings are plan item 2d, not
  A1); else `unconfirmed` (a preferred-share offering, an unused shelf, or a
  rights offering CRSP did not code). **An A1 event is a confirmed, non-rights
  episode dated before 2023-01-01.** A C quarter is EDGAR-confirmed if the fund
  filed a supplement in the year to its end.

Every parameter above is chosen from how the instruments work, before any level
was computed, and none is fitted. The precision of the event definition is
measured on a seeded random sample read by hand (note §3), not assumed.

**Revision 1 (2026-10-20, after the hand-read sample, before any level).** The
sample of 15 confirmed episodes held 4 rights offerings that CRSP had not coded
45xx, one shelf base prospectus that left the method open (the same fund's next
episode was a rights offering) and one former fund that had become an operating
REIT. Nine were ATM programmes or an equity shelf. So (i) the CIK must
have filed an N-CSR/N-CSRS within `REGISTERED_LOOKBACK_DAYS` before the episode
or a year after it (`mark_events`), giving the BROAD set `a1_event`; and (ii) the
level check's PRIMARY set is `a1_programme`, the broad events with at least
`PROGRAMME_MIN_SUPPLEMENTS` supplements. The broad set is reported beside it as a
sensitivity that rights offerings contaminate. `programme` reads the episode's
later filings: an ex-post label, for description only.

THE MECHANISM CHECK (levels), FIXED BEFORE ANY LEVEL WAS COMPUTED
-----------------------------------------------------------------
Premium levels are descriptive: no position, no hedge, no cost, no strategy P&L.
They are computed only where a daily NAV exists outside the 44
`data/cef/cef_universe.csv` names: the CEF-families panel (equity, preferred,
multi-asset). The 44 are counted only (the census's precedent), so the 27-name
set is not consumed. Every level is dated before 2023-01-01, asserted.

* Premium `p = 100 (P - NAV) / NAV` on same-date pairs of the CRSP close and the
  panel NAV. The live z-score is mirrored from `cef_discount.py` (rolling
  `Z_WINDOW` from the frozen spec, `min_periods` 120, `shift(1)`, clipped at 4).
* tau0 = the first paired session on or after the event date. Offsets `OFFSETS`
  are in the fund's own paired sessions. `Delta_k = p(tau0+k) - p(tau0)`.
* Controls: on the same date, families funds with no A1 event within a year and
  no C quarter within four, whose premium is within `MATCH_PREM_PP` points and
  whose z is within `MATCH_Z` of the event fund's. `D_k = Delta_k(event) -
  median Delta_k(controls)`; an event with fewer than `MIN_CONTROLS` is dropped
  and counted. The z match is the point: it asks whether issuance tells you
  anything the live signal does not already know.
* Placebo (negative control, H12): the same event fund `PLACEBO_SHIFT` sessions
  earlier, with no C quarter in its forward window, matched the same way.
* Dispersion: the fund's own premium sd over [-126, -1] against [+1, +126], for
  events and controls; the cross-section of p(tau0).

GATES, on the PRIMARY (programme) set (a FAIL on any of G-A1-1, -3, -4 or -5 kills
A1 as a trial on this data; G-A1-2 is a data gate that halts, because it means the
event set is not "issuance at a premium"):

  G-A1-1  independent groups (sponsor x calendar month) in the level sample >= 30   (D7)
  G-A1-2  share of level-sample events with p(tau0) >= 0  >= 0.80                    (identity)
  G-A1-3  median D_63 <= -(ROUND_TRIP_UNITS x top cost) = -60bp AND share(D_63<0) >= 0.60
          (issuers' premiums compress, beyond what premium and z already predict, by
          at least a round trip at the grid's top cost)                               (mechanism)
  G-A1-4  |median D_63 (placebo)| < 0.5 |median D_63 (event)|                         (control)
  G-A1-5  share of distinct A1-event funds still listed that are shortable at Alpaca
          on the latest read >= 0.50                                                  (access)

H14: no gate keys on a number written in a document. Each is re-measured by this
script from its inputs, and the cost bar is the house cost grid's top point, a
convention rather than a measurement.

PUBLIC REPOSITORY: CRSP AGGREGATES ONLY
---------------------------------------
Tracked outputs carry counts, medians and EDGAR facts (CIK, dates, forms, today's
ticker). Rows that join CRSP (per-fund growth, prices, premiums) go to
`results/events/a1/_cache_a1/`, gitignored by `results/**/_cache_*`.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

OUT = REPO / "results" / "events" / "a1"
PRIVATE = OUT / "_cache_a1"                 # gitignored: CRSP-joined rows
CENSUS_JSON = OUT / "a1_census_2026-10-20.json"
LEVELS_JSON = OUT / "a1_levels_2026-10-20.json"
EPISODES_CSV = OUT / "a1_edgar_episodes.csv"  # tracked: EDGAR facts only
TIME_HOLDOUT = pd.Timestamp("2023-01-01")
INDEX_FIRST_Q = (2008, 1)
INDEX_REQUIRED_LAST_Q = (2022, 4)          # every quarter up to here must be cached
CEF_SHRCD = (14, 44)

# ---- the definitions (module docstring); fixed 2026-10-20 before any level ----
MIN_Q_GROWTH = 0.02          # one quarter's raw shrout growth to count at all
DRIP_PRICE_FLOOR = 0.95      # DRIP issues at >= max(NAV, 0.95 x market)  [V: §12av]
SEASONED_QUARTERS = 2        # IPO quarter and the over-allotment quarter after it
MERGER_Q_PAD = 1             # CRSP shrout can lag a merger's completion by a quarter
RIGHTS_Q_AFTER = 2           # rights shares issue after expiry, weeks after the ex-date
EPISODE_GAP_DAYS = 365       # a shelf is updated yearly; a longer silence is a new episode
IPO_EXCLUDE_DAYS = 365
CONFIRM_QUARTERS_AFTER = 4
RIGHTS_EDGAR_DAYS = 120
SHELF_FORMS = ("N-2", "N-2/A", "N-2ASR", "N-2 POSASR", "N-2MEF", "POS 8C")
SUPP_FORMS = ("424B1", "424B2", "424B3", "424B4", "424B5", "424B7", "424B8", "497")
NCSR_FORMS = ("N-CSR", "N-CSRS", "N-CSR/A", "N-CSRS/A")
BDC_FORMS = ("N-54A", "N-54A/A", "N-54C", "N-54C/A")
OPCO_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")

# ---- the mechanism check and gates (module docstring); fixed before any level ----
OFFSETS = (-63, -21, 0, 21, 63, 126)
H_GATE = 63
WIN_DISP = 126
MATCH_PREM_PP = 2.5
MATCH_Z = 0.5
MIN_CONTROLS = 3
PLACEBO_SHIFT = 252
Z_MIN_PERIODS = 120          # as cef_discount.py
Z_CLIP = 4.0                 # as cef_discount.py
COST_GRID_BP = (5, 15, 30)
ROUND_TRIP_UNITS = 2
GATE_MIN_GROUPS = 30
GATE_IDENTITY_SHARE = 0.80
GATE_SIGN_SHARE = 0.60
GATE_PLACEBO_RATIO = 0.5
GATE_SHORTABLE_SHARE = 0.50
SAMPLE_SEED = 20261020
SAMPLE_N = 15
# REVISION 1 (2026-10-20, after the hand-read sample of SAMPLE_N broad events and BEFORE any
# level was computed; note §3): 4 of 15 were rights offerings CRSP had not coded 45xx, 1 a shelf
# base prospectus with the method left open, and 1 a former fund that had become an operating
# REIT. Two structural rules follow, neither fitted:
# * the CIK must be a registered fund AT THE TIME: an N-CSR/N-CSRS filed within
#   REGISTERED_LOOKBACK_DAYS before the episode (or within a year after it);
# * the level sample's primary set is PROGRAMME episodes, with at least
#   PROGRAMME_MIN_SUPPLEMENTS supplements: an ATM or shelf is a continuing offering that is
#   re-supplemented (each sales agreement, update and sticker), while a rights offering is one
#   prospectus and perhaps a sticker. On the sample: 6 of 6 such episodes were ATM or shelf; 3
#   of 9 smaller ones were. The rule reads the episode's LATER filings, so it is an ex-post
#   label for description only; a tradable rule must read the first supplement's cover.
REGISTERED_LOOKBACK_DAYS = 730
PROGRAMME_MIN_SUPPLEMENTS = 4


# The tracked episode table carries EDGAR facts only (public repository; CRSP is licensed).
TRACKED_COLUMNS = ("cik", "episode", "company", "ticker_now", "first_date", "first_form", "first_accession",
                   "last_date", "n_supplements", "forms", "shelf_form_date", "left_censored", "sponsor",
                   "group_month", "programme")
CRSP_DERIVED = ("permno", "crsp_class", "first_iss_quarter", "a1_event", "a1_programme", "in_44", "deployed",
                "families_ticker", "registered_at_time")


class A1DataError(RuntimeError):
    """An input is missing or inconsistent. Names what, never guesses."""


def assert_pre_holdout(when, what: str) -> None:
    """Every level and every CRSP row used here is dated before 2023-01-01."""
    w = pd.Timestamp(when) if not isinstance(when, pd.Series) else pd.Timestamp(when.max())
    if w >= TIME_HOLDOUT:
        raise A1DataError(f"{what}: {w.date()} is on or after the 2023-01-01 time holdout")


# =============================================================================
# inputs
# =============================================================================

def quarters_between(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    out, (y, q) = [], first
    while (y, q) <= last:
        out.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def load_index(edgar_cache: Path, keep_forms) -> tuple[pd.DataFrame, list[str]]:
    """Every cached quarterly master index from 2008-Q1, filtered to `keep_forms`.

    Quarters through 2022-Q4 are REQUIRED (the fit period); later cached quarters
    are read too, for 2023+ counts only. A missing required quarter raises."""
    from scripts.data.fetch_edgar_events import parse_master_index
    root = Path(edgar_cache) / "www.sec.gov" / "Archives" / "edgar" / "full-index"
    if not root.is_dir():
        raise A1DataError(f"no EDGAR full-index cache under {edgar_cache}")
    have = sorted((int(p.parent.parent.name), int(p.parent.name[3:])) for p in root.glob("*/QTR*/master.gz"))
    need = quarters_between(INDEX_FIRST_Q, INDEX_REQUIRED_LAST_Q)
    missing = [f"{y}Q{q}" for y, q in need if (y, q) not in have]
    if missing:
        raise A1DataError(f"EDGAR master.gz missing for {missing} under {root}")
    frames, labels = [], []
    for y, q in have:
        if (y, q) < INDEX_FIRST_Q:
            continue
        raw = (root / str(y) / f"QTR{q}" / "master.gz").read_bytes()
        try:
            text = gzip.decompress(raw).decode("latin-1")
        except OSError:
            text = raw.decode("latin-1")
        frames.append(parse_master_index(text, label=f"{y}Q{q}", keep_forms=set(keep_forms)))
        labels.append(f"{y}Q{q}")
    return pd.concat(frames, ignore_index=True), labels


def load_sec_tickers(edgar_cache: Path) -> tuple[pd.DataFrame, str]:
    p = Path(edgar_cache) / "www.sec.gov" / "files" / "company_tickers_exchange.json"
    if not p.exists():
        raise A1DataError(f"SEC ticker file not cached: {p}")
    j = json.loads(p.read_text())
    if j.get("fields") != ["cik", "name", "ticker", "exchange"]:
        raise A1DataError(f"company_tickers_exchange.json fields changed: {j.get('fields')}")
    fetched = "unknown"
    man = Path(edgar_cache) / "_manifest.jsonl"
    if man.exists():
        for line in man.read_text().splitlines():
            r = json.loads(line)
            if r.get("url", "").endswith("company_tickers_exchange.json"):
                fetched = r.get("fetched_utc", fetched)
    return pd.DataFrame(j["data"], columns=j["fields"]), fetched


def _first_existing(dirs, name):
    for d in dirs:
        p = Path(d) / name
        if p.exists():
            return p
    raise A1DataError(f"CRSP extract {name} not in any of {[str(d) for d in dirs]}")


def load_crsp(crsp_dirs) -> dict:
    """names, delistings, distributions and the daily file for share-code 14/44 permnos.

    Daily extracts from every directory are unioned; a (permno, date) present in
    two extracts must agree on every column used, or this raises (two pulls of
    one mirror should be byte-identical; a disagreement is a defect, not a pick)."""
    dirs = [Path(d) for d in crsp_dirs]
    nm = pd.read_parquet(_first_existing(dirs, "dsenames.parquet"))
    dl = pd.read_parquet(_first_existing(dirs, "dsedelist.parquet"))
    cef = set(nm.loc[nm["shrcd"].isin(CEF_SHRCD), "permno"].astype(int))
    dist_frames, dsf_frames, files = [], [], []
    seen = set()
    for d in dirs:
        for p in sorted(d.glob("dsedist_*.parquet")):
            if p.name in seen:
                continue
            seen.add(p.name)
            dist_frames.append(pd.read_parquet(p))
        for p in sorted(d.glob("dsf_*.parquet")):
            if p.name in seen:
                continue
            seen.add(p.name)
            import pyarrow.parquet as pq
            t = pq.read_table(p, columns=["permno", "date", "prc", "vol", "shrout", "cfacpr"],
                              filters=[("permno", "in", sorted(cef))]).to_pandas()
            if len(t):
                dsf_frames.append(t)
                files.append(p.name)
    if not dsf_frames:
        raise A1DataError("no CRSP daily rows for share-code 14/44 permnos in the given caches")
    if not dist_frames:
        raise A1DataError("no CRSP distribution extract (dsedist_*.parquet) in the given caches")
    dsf = pd.concat(dsf_frames, ignore_index=True)
    dsf["date"] = pd.to_datetime(dsf["date"])
    assert_pre_holdout(dsf["date"], "CRSP daily rows")
    key = ["permno", "date"]
    dup = dsf[dsf.duplicated(key, keep=False)]
    if len(dup):
        cols = ["prc", "vol", "shrout", "cfacpr"]
        g = dup.groupby(key)[cols].nunique(dropna=False)
        bad = g[(g > 1).any(axis=1)]
        if len(bad):
            raise A1DataError(f"{len(bad)} (permno, date) rows disagree across CRSP extracts, e.g. {bad.index[:3].tolist()}")
    dsf = dsf.drop_duplicates(key).sort_values(key).reset_index(drop=True)
    dist = pd.concat(dist_frames, ignore_index=True).drop_duplicates()
    for c in ("exdt", "dclrdt", "rcrddt", "paydt"):
        if c in dist:
            dist[c] = pd.to_datetime(dist[c])
    dl["dlstdt"] = pd.to_datetime(dl["dlstdt"])
    for c in ("namedt", "nameendt"):
        nm[c] = pd.to_datetime(nm[c])
    return {"names": nm, "delist": dl, "dist": dist, "dsf": dsf, "dsf_files": files, "cef_permnos": cef}


# =============================================================================
# the fund set
# =============================================================================

def link_permnos(crsp: dict, idx: pd.DataFrame, tickers: pd.DataFrame, fund_ciks: set) -> pd.DataFrame:
    """CRSP CEF permno (with daily rows from 2008) -> EDGAR CIK, by today's ticker or by name.

    Ticker route: a permno whose last CRSP name runs to the end of CRSP (still
    listed), whose ticker maps to exactly one CIK in the SEC file, and whose names
    agree loosely (score >= 0.5, the census's `CrspMap` rule). Otherwise the merger
    matcher's name rule (`edgar_merger_dates.match_cik`) among fund-set CIKs whose
    EDGAR names were in use within the permno's life. Unmatched is kept with the
    reason; nothing is guessed."""
    from scripts.events.edgar_merger_dates import match_cik, name_score, name_tokens
    nm, dsf = crsp["names"], crsp["dsf"]
    life = dsf[dsf["date"] >= pd.Timestamp("2008-01-01")].groupby("permno")["date"].agg(lo="min", hi="max")
    first_row = dsf.groupby("permno")["date"].min()
    cefnm = nm[nm["shrcd"].isin(CEF_SHRCD)]
    last = cefnm.sort_values("nameendt").groupby("permno").last()
    crsp_end = nm["nameendt"].max()
    fi = idx[idx["cik"].isin(fund_ciks)]
    names = fi.groupby(["cik", "company"])["date_filed"].agg(first="min", last="max").reset_index()
    names["tok"] = names["company"].map(name_tokens)
    t2c = tickers.groupby("ticker")["cik"].apply(lambda s: sorted(set(int(x) for x in s))).to_dict()
    rows = []
    for p, r in life.iterrows():
        if p not in last.index:
            raise A1DataError(f"permno {p} has daily rows but no share-code 14/44 name record")
        L = last.loc[p]
        cik, how = None, None
        if L["nameendt"] >= crsp_end and isinstance(L["ticker"], str) and len(t2c.get(L["ticker"], [])) == 1:
            c = t2c[L["ticker"]][0]
            cn = names[names["cik"] == c]
            if len(cn):
                sc = max(name_score(name_tokens(L["comnam"]), t) for t in cn["tok"])
                if sc >= 0.5:
                    cik, how = c, f"ticker {L['ticker']} (name score {sc:.2f})"
        if cik is None:
            m = match_cik(L["comnam"], names, r["lo"] - pd.Timedelta(days=365), r["hi"] + pd.Timedelta(days=60))
            if m.get("status") == "matched":
                cik, how = int(m["cik"]), f"name (score {m['score']})"
            else:
                how = f"unmatched: {m.get('status')}"
        rows.append({"permno": int(p), "ticker_last": L["ticker"], "comnam_last": L["comnam"],
                     "alive_at_crsp_end": bool(L["nameendt"] >= crsp_end),
                     "cik": cik, "link": how, "first_crsp_date": first_row.loc[p],
                     "lo_2008": r["lo"], "hi": r["hi"]})
    return pd.DataFrame(rows)


def classify_funds(link: pd.DataFrame, idx: pd.DataFrame) -> pd.DataFrame:
    """registered CEF / BDC / mixed / unclassified, from the forms each CIK files.

    Registered management companies file N-CSR; BDCs elect on N-54A and file
    10-K/10-Q like an operating company. A CIK with both is `mixed` (a fund that
    converted) and is excluded rather than placed by a guess."""
    c = set(link["cik"].dropna().astype(int))
    sub = idx[idx["cik"].isin(c)]
    ncsr = set(sub.loc[sub["form"].isin(NCSR_FORMS), "cik"])
    bdc = set(sub.loc[sub["form"].isin(BDC_FORMS), "cik"]) | (set(sub.loc[sub["form"].isin(OPCO_FORMS), "cik"]) - ncsr)
    def kind(x):
        if pd.isna(x):
            return "unlinked"
        x = int(x)
        if x in ncsr and x in bdc:
            return "mixed"
        if x in ncsr:
            return "registered"
        if x in bdc:
            return "bdc"
        return "unclassified"
    out = link.copy()
    out["kind"] = out["cik"].map(kind)
    return out


# =============================================================================
# method C: CRSP shares outstanding
# =============================================================================

def quarter_panel(dsf: pd.DataFrame, delist: pd.DataFrame, dist: pd.DataFrame, permnos,
                  first_row: pd.Series) -> pd.DataFrame:
    """One row per (permno, calendar quarter) with growth, exclusions and the DRIP bound.

    `first_row` is each permno's first CRSP date (the listing), for seasoning.
    Distribution coverage: a permno with NO distribution rows at all in the
    extract cannot be bounded and is flagged `dist_unmeasured` (never treated as
    paying nothing)."""
    d = dsf[dsf["permno"].isin(permnos)].copy()
    d["q"] = d["date"].dt.to_period("Q")
    d["ap"] = d["prc"].abs()
    g = (d.groupby(["permno", "q"])
         .agg(sh_last=("shrout", "last"), cf_last=("cfacpr", "last"), pmed=("ap", "median"),
              q_last_date=("date", "max"))
         .reset_index().sort_values(["permno", "q"]))
    g["sh_prev"] = g.groupby("permno")["sh_last"].shift(1)
    g["cf_prev"] = g.groupby("permno")["cf_last"].shift(1)
    g["q_prev"] = g.groupby("permno")["q"].shift(1)
    g = g[g["sh_prev"].notna()].copy()
    # a quarter with no row between it and the previous one is not a one-quarter change
    g["contiguous"] = [(a - b).n == 1 for a, b in zip(g["q"], g["q_prev"])]
    g["gr"] = g["sh_last"] / g["sh_prev"] - 1.0
    g["split"] = g["cf_last"] != g["cf_prev"]
    acq = delist[(delist["dlstcd"] // 100 == 2) & delist["nwperm"].notna()]
    A = {(int(r.nwperm), pd.Period(r.dlstdt, "Q") + k) for r in acq.itertuples() for k in range(-MERGER_Q_PAD, MERGER_Q_PAD + 1)}
    rights = dist[(dist["distcd"] // 100 == 45) & dist["exdt"].notna()]
    R = {(int(r.permno), pd.Period(r.exdt, "Q") + k) for r in rights.itertuples() for k in range(0, RIGHTS_Q_AFTER + 1)}
    g["merger"] = [(p, q) in A for p, q in zip(g["permno"], g["q"])]
    g["rights"] = [(p, q) in R for p, q in zip(g["permno"], g["q"])]
    g["age_q"] = [(q - pd.Period(first_row.loc[p], "Q")).n for p, q in zip(g["permno"], g["q"])]
    cash = dist[(dist["distcd"] // 1000 == 1) & dist["exdt"].notna()].copy()
    cash["q"] = cash["exdt"].dt.to_period("Q")
    dq = cash.groupby(["permno", "q"])["divamt"].sum()
    covered = set(dist["permno"].astype(int))
    g["dist_unmeasured"] = ~g["permno"].isin(covered)
    g["div_q"] = [float(dq.get((p, q), 0.0)) if p in covered else np.nan for p, q in zip(g["permno"], g["q"])]
    # trailing four quarters: growth and the DRIP ceiling
    g4, y4, clean4 = [], [], []
    for p, x in g.groupby("permno", sort=False):
        x = x.set_index("q")
        sh_all = pd.concat([x["sh_prev"].rename(None).set_axis(x.index - 1), x["sh_last"]])
        sh_all = sh_all[~sh_all.index.duplicated(keep="last")]
        for q in x.index:
            w = [q - k for k in range(4)]
            if not all(k in x.index for k in w) or (q - 4) not in sh_all.index:
                g4.append(np.nan); y4.append(np.nan); clean4.append(False)
                continue
            g4.append(float(x.at[q, "sh_last"] / sh_all[q - 4] - 1.0))
            pv = x.loc[w, "pmed"].to_numpy(dtype=float)
            pm = float(np.nanmedian(pv)) if np.isfinite(pv).any() else np.nan
            dv = x.loc[w, "div_q"].to_numpy(dtype=float)
            # an unmeasured distribution history leaves the bound unmeasured (pandas' sum
            # would skip the NaNs and read it as "paid nothing", which flags everything)
            y4.append(float(dv.sum() / pm) if np.isfinite(dv).all() and np.isfinite(pm) and pm > 0 else np.nan)
            clean4.append(not bool(x.loc[w, ["split", "merger", "rights"]].to_numpy().any())
                          and bool(x.loc[w, "contiguous"].all()))
    g["G4"], g["Y4"], g["clean4"] = g4, y4, clean4
    g["beyond_drip"] = g["clean4"] & g["Y4"].notna() & (g["G4"] > g["Y4"] / DRIP_PRICE_FLOOR)
    g["iss"] = ((g["gr"] >= MIN_Q_GROWTH) & g["contiguous"] & ~g["split"] & ~g["merger"] & ~g["rights"]
                & (g["age_q"] >= SEASONED_QUARTERS) & g["beyond_drip"])
    return g.reset_index(drop=True)


# =============================================================================
# method E: EDGAR offering episodes
# =============================================================================

def edgar_episodes(idx: pd.DataFrame, cik_first_listing: dict) -> tuple[pd.DataFrame, dict]:
    """Per CIK, supplements grouped into episodes; IPO-period supplements dropped (counted).

    `cik_first_listing` maps CIK -> the first CRSP date of its linked permno."""
    supp = idx[idx["form"].isin(SUPP_FORMS) & idx["cik"].isin(cik_first_listing)].copy()
    shelf = idx[idx["form"].isin(SHELF_FORMS) & idx["cik"].isin(cik_first_listing)]
    supp["first_listing"] = supp["cik"].map(cik_first_listing)
    ipo = supp["date_filed"] < supp["first_listing"] + pd.Timedelta(days=IPO_EXCLUDE_DAYS)
    counts = {"supplements": int(len(supp)), "supplements_ipo_period_dropped": int(ipo.sum())}
    supp = supp[~ipo].sort_values(["cik", "date_filed", "accession"])
    shelf_by = {c: g["date_filed"].sort_values().to_numpy() for c, g in shelf.groupby("cik")}
    rows = []
    for c, g in supp.groupby("cik"):
        ep = (g["date_filed"].diff() > pd.Timedelta(days=EPISODE_GAP_DAYS)).cumsum()
        for k, e in g.groupby(ep):
            f0 = e.iloc[0]
            sd = shelf_by.get(c, np.array([], dtype="datetime64[ns]"))
            prior = sd[(sd <= np.datetime64(f0["date_filed"])) & (sd >= np.datetime64(f0["date_filed"] - pd.Timedelta(days=365)))]
            rows.append({"cik": int(c), "episode": int(k), "company": f0["company"],
                         "first_date": f0["date_filed"], "first_form": f0["form"], "first_accession": f0["accession"],
                         "last_date": e["date_filed"].max(), "n_supplements": int(len(e)),
                         "forms": ";".join(sorted(e["form"].unique())),
                         "shelf_form_date": pd.Timestamp(prior.max()) if len(prior) else pd.NaT,
                         "left_censored": bool(f0["date_filed"] < pd.Timestamp("2009-01-01"))})
    return pd.DataFrame(rows), counts


def join_episodes(eps: pd.DataFrame, qp: pd.DataFrame, dist: pd.DataFrame, cik2perm: dict) -> pd.DataFrame:
    """Classify each EDGAR episode against CRSP: rights / confirmed / unconfirmed / after CRSP."""
    out = eps.copy()
    rights = dist[(dist["distcd"] // 100 == 45) & dist["exdt"].notna()]
    rights_by = {int(p): g["exdt"].to_numpy() for p, g in rights.groupby("permno")}
    iss_by = {int(p): set(g.loc[g["iss"], "q"]) for p, g in qp.groupby("permno")}
    last_q = qp["q"].max()
    cls, perm, first_iss = [], [], []
    for r in out.itertuples():
        p = cik2perm[int(r.cik)]
        perm.append(p)
        q0 = pd.Period(r.first_date, "Q")
        if r.first_date >= TIME_HOLDOUT:
            cls.append("after_crsp (2023+, count only)"); first_iss.append(None)
            continue
        ex = rights_by.get(p, np.array([], dtype="datetime64[ns]"))
        near = np.abs((ex - np.datetime64(r.first_date)).astype("timedelta64[D]").astype(int)) <= RIGHTS_EDGAR_DAYS if len(ex) else []
        qs = sorted(q for q in iss_by.get(p, ()) if q0 <= q <= q0 + CONFIRM_QUARTERS_AFTER)
        if len(ex) and np.any(near):
            cls.append("rights")
        elif qs:
            cls.append("confirmed")
        else:
            cls.append("unconfirmed" if q0 + CONFIRM_QUARTERS_AFTER <= last_q else "unconfirmed (window runs past CRSP)")
        first_iss.append(str(qs[0]) if qs else None)
    out["permno"], out["crsp_class"], out["first_iss_quarter"] = perm, cls, first_iss
    out["programme"] = out["n_supplements"] >= PROGRAMME_MIN_SUPPLEMENTS
    return out


def mark_events(eps: pd.DataFrame, idx: pd.DataFrame) -> pd.DataFrame:
    """Revision 1: registered at the time, then the broad and programme A1 sets."""
    ncsr = idx[idx["form"].isin(NCSR_FORMS)]
    by = {int(c): g["date_filed"].to_numpy() for c, g in ncsr.groupby("cik")}
    reg = []
    for r in eps.itertuples():
        v = by.get(int(r.cik))
        if v is None:
            reg.append(False)
            continue
        lo = np.datetime64(r.first_date - pd.Timedelta(days=REGISTERED_LOOKBACK_DAYS))
        hi = np.datetime64(r.first_date + pd.Timedelta(days=365))
        reg.append(bool(((v >= lo) & (v <= hi)).any()))
    out = eps.copy()
    out["registered_at_time"] = reg
    out["a1_event"] = (out["crsp_class"] == "confirmed") & (out["first_date"] < TIME_HOLDOUT) & out["registered_at_time"]
    out["a1_programme"] = out["a1_event"] & out["programme"]
    return out


def c_quarters_confirmed(qp: pd.DataFrame, idx: pd.DataFrame, perm2cik: dict) -> pd.Series:
    """For each C quarter: did the fund file a supplement in the year to the quarter's end?"""
    supp = idx[idx["form"].isin(SUPP_FORMS)]
    by = {int(c): g["date_filed"].to_numpy() for c, g in supp.groupby("cik")}
    res = []
    for r in qp.itertuples():
        c = perm2cik.get(int(r.permno))
        v = by.get(c) if c is not None else None
        if v is None or not r.iss:
            res.append(False)
            continue
        lo = np.datetime64(r.q.start_time - pd.Timedelta(days=365))
        hi = np.datetime64(r.q.end_time)
        res.append(bool(((v >= lo) & (v <= hi)).any()))
    return pd.Series(res, index=qp.index)


# =============================================================================
# membership, sponsors, access
# =============================================================================

def universe_permnos(names: pd.DataFrame, tickers) -> dict:
    """permno -> the 44-name tickers it carried at any time from 2008 (CRSP names)."""
    nn = names[names["shrcd"].isin(CEF_SHRCD) & names["ticker"].isin(set(tickers)) & (names["nameendt"] >= pd.Timestamp("2008-01-01"))]
    return nn.groupby("permno")["ticker"].agg(lambda s: ";".join(sorted(set(s)))).to_dict()


def families_permnos(fmap: pd.DataFrame) -> dict:
    """permno -> families-panel ticker (current and predecessor permnos the panel used)."""
    out = {}
    for r in fmap.itertuples():
        ps = []
        if pd.notna(r.current_permno):
            ps.append(int(r.current_permno))
        if isinstance(r.other_permnos, str):
            ps += [int(x) for x in re.split(r"[;,\s]+", r.other_permnos) if x.strip().isdigit()]
        for p in ps:
            if p in out and out[p] != r.ticker:
                raise A1DataError(f"permno {p} maps to two families tickers: {out[p]}, {r.ticker}")
            out[p] = r.ticker
    return out


def sponsor_groups(ev: pd.DataFrame) -> pd.DataFrame:
    from scripts.events.cef_corp_action_census import sponsor_of
    s = ev["company"].map(sponsor_of)
    out = ev.copy()
    out["sponsor"] = [a for a, _ in s]
    out["sponsor_recognised"] = [b for _, b in s]
    out["group_month"] = out["sponsor"] + " | " + pd.to_datetime(out["first_date"]).dt.strftime("%Y-%m")
    out["group_date"] = out["sponsor"] + " | " + pd.to_datetime(out["first_date"]).dt.strftime("%Y-%m-%d")
    return out


def common_symbol(tickers: str) -> str:
    """The common share's symbol among a CIK's SEC tickers (preferreds carry a suffix such as GAB-PG)."""
    ts = [t for t in str(tickers).split(";") if t]
    plain = sorted((t for t in ts if not re.search(r"[-.^]", t)), key=lambda t: (len(t), t))
    if not plain:
        raise A1DataError(f"no plain common symbol among {tickers!r}")
    return plain[0]


def alpaca_flags(path: Path) -> tuple[pd.DataFrame, str]:
    j = json.loads(Path(path).read_text())
    if "data" not in j or "meta" not in j:
        raise A1DataError(f"{path}: not the expected {{meta, data}} asset dump")
    df = pd.DataFrame(j["data"])
    need = {"symbol", "shortable", "easy_to_borrow", "tradable", "status"}
    if not need <= set(df.columns):
        raise A1DataError(f"{path}: missing columns {sorted(need - set(df.columns))}")
    return df.set_index("symbol"), j["meta"].get("received_utc", "unknown")


# =============================================================================
# census
# =============================================================================

def _year(s):
    return pd.to_datetime(s).dt.year


def event_summary(a1: pd.DataFrame) -> dict:
    """Counts for one event set: per year, funds, independent groups, membership."""
    if not len(a1):
        return {"n": 0}
    return {
        "n": int(len(a1)), "funds": int(a1["cik"].nunique()),
        "by_year": _year(a1["first_date"]).value_counts().sort_index().rename(index=str).to_dict(),
        "funds_by_year": a1.groupby(_year(a1["first_date"]))["cik"].nunique().rename(index=str).to_dict(),
        "groups_sponsor_month": int(a1["group_month"].nunique()),
        "groups_sponsor_date": int(a1["group_date"].nunique()),
        "sponsor_unrecognised_share": round(float((~a1["sponsor_recognised"]).mean()), 3),
        "top_sponsors": a1["sponsor"].value_counts().head(12).to_dict(),
        "first_form": a1["first_form"].value_counts().to_dict(),
        "median_supplements": float(a1["n_supplements"].median()),
        "in_44": {"events": int(a1["in_44"].notna().sum()), "funds": sorted(a1["in_44"].dropna().unique().tolist())},
        "deployed_13": {"events": int(a1["deployed"].notna().sum()), "funds": sorted(a1["deployed"].dropna().unique().tolist())},
        "families_panel": {"events": int(a1["families_ticker"].notna().sum()),
                           "funds": int(a1["families_ticker"].nunique()),
                           "groups_sponsor_month": int(a1.loc[a1["families_ticker"].notna(), "group_month"].nunique())},
        "outside_both_panels_no_nav_in_repo": {
            "events": int((a1["families_ticker"].isna() & a1["in_44"].isna()).sum()),
            "funds_with_ticker_now": sorted(a1.loc[a1["families_ticker"].isna() & a1["in_44"].isna(), "ticker_now"].dropna().unique().tolist())},
    }


def deployed_activity(eps: pd.DataFrame) -> dict:
    """EDGAR supplement episodes of the deployed 13 from 2020 (EDGAR facts; 2023+ is a count only)."""
    from scripts.cef.spec import UNIVERSE
    d = eps[eps["deployed"].notna() & (eps["first_date"] >= pd.Timestamp("2020-01-01"))]
    out = {}
    for t in UNIVERSE:
        x = d[d["deployed"].str.split(";").map(lambda v: t in v)]
        if len(x):
            out[t] = [{"first": str(r.first_date.date()), "last": str(r.last_date.date()), "n_supplements": int(r.n_supplements),
                       "forms": r.forms} for r in x.itertuples()]
    return out


def census(edgar_cache: Path, crsp_dirs, write: bool = True) -> dict:
    from scripts.data.fetch_edgar_events import fund_set, MARKER_FORMS
    from scripts.cef.spec import UNIVERSE
    keep = set(SHELF_FORMS) | set(SUPP_FORMS) | set(NCSR_FORMS) | set(BDC_FORMS) | set(OPCO_FORMS) | set(MARKER_FORMS) | {"3", "4"}
    idx, qlabels = load_index(edgar_cache, keep)
    tickers, tk_fetched = load_sec_tickers(edgar_cache)
    crsp = load_crsp(crsp_dirs)
    fs = fund_set(idx)
    link = classify_funds(link_permnos(crsp, idx, tickers, set(fs)), idx)
    reg = link[link["kind"] == "registered"]
    dup = reg["cik"].duplicated(keep=False)
    # one CIK may own successive permnos (a re-listing); keep the latest listed one for EDGAR,
    # and every permno for CRSP. The EDGAR side needs ONE first-listing date per CIK: the earliest.
    cik_first = reg.groupby(reg["cik"].astype(int))["first_crsp_date"].min().to_dict()
    cik2perm = reg.sort_values("hi").groupby(reg["cik"].astype(int))["permno"].last().astype(int).to_dict()
    perm2cik = {int(p): int(c) for p, c in zip(reg["permno"], reg["cik"])}
    first_row = crsp["dsf"].groupby("permno")["date"].min()
    qp = quarter_panel(crsp["dsf"], crsp["delist"], crsp["dist"], set(reg["permno"]), first_row)
    # the trailing windows above used every cached quarter; the census counts 2008-Q1 on,
    # the span the EDGAR index covers, so the two methods count the same years
    qp = qp[(qp["q"] >= pd.Period("2008Q1")) & (qp["q"] <= pd.Period("2022Q4"))].copy()
    qp["edgar_confirmed"] = c_quarters_confirmed(qp, idx, perm2cik)
    eps, ecounts = edgar_episodes(idx, cik_first)
    eps = join_episodes(eps, qp, crsp["dist"], cik2perm)
    eps = mark_events(eps, idx)
    eps = sponsor_groups(eps)
    u = pd.read_csv(REPO / "data" / "cef" / "cef_universe.csv")["ticker"].tolist()
    u2p = universe_permnos(crsp["names"], u)
    fmap = pd.read_csv(REPO / "data" / "cef_families" / "crsp_permno_map.csv")
    f2p = families_permnos(fmap)
    tk_by_cik = tickers.groupby("cik")["ticker"].agg(lambda s: ";".join(sorted(set(s))))
    eps["ticker_now"] = eps["cik"].map(tk_by_cik)
    eps["in_44"] = eps["permno"].map(u2p)
    eps["deployed"] = eps["in_44"].map(lambda s: ";".join(t for t in str(s).split(";") if t in UNIVERSE) if isinstance(s, str) else None)
    eps["deployed"] = eps["deployed"].replace("", None)
    eps["families_ticker"] = eps["permno"].map(f2p)
    qp["in_44"] = qp["permno"].map(u2p)
    qp["families_ticker"] = qp["permno"].map(f2p)

    pre = eps[eps["first_date"] < TIME_HOLDOUT]
    year = _year
    cq = qp[qp["iss"]]
    res = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "edgar_index_quarters": [qlabels[0], qlabels[-1]], "n_quarters": len(qlabels),
            "edgar_last_date_filed": str(idx["date_filed"].max().date()),
            "sec_ticker_file_fetched_utc": tk_fetched,
            "crsp_dsf_extracts": crsp["dsf_files"], "crsp_dsf_last_date": str(crsp["dsf"]["date"].max().date()),
            "crsp_names_end": str(crsp["names"]["nameendt"].max().date()),
        },
        "fund_set": {
            "crsp_cef_permnos_with_rows_from_2008": int(len(link)),
            "by_kind": link["kind"].value_counts().to_dict(),
            "link_route": link["link"].fillna("none").str.split().str[0].value_counts().to_dict(),
            "registered_permnos": int(len(reg)), "registered_ciks": int(reg["cik"].nunique()),
            "registered_ciks_with_two_or_more_permnos": int(reg.loc[dup, "cik"].nunique()),
            "registered_permnos_no_distribution_rows": int(qp.groupby("permno")["dist_unmeasured"].first().sum()),
        },
        "edgar": {
            **ecounts,
            "episodes_all": int(len(eps)), "episodes_pre_2023": int(len(pre)),
            "episodes_pre_2023_left_censored_2008": int(pre["left_censored"].sum()),
            "by_class_pre_2023": pre["crsp_class"].value_counts().to_dict(),
            "episodes_2023_on_count_only": int((eps["first_date"] >= TIME_HOLDOUT).sum()),
            "episodes_2023_on_by_year": year(eps.loc[eps["first_date"] >= TIME_HOLDOUT, "first_date"]).value_counts().sort_index().rename(index=str).to_dict(),
            "first_form_pre_2023": pre["first_form"].value_counts().to_dict(),
            "pre_2023_not_registered_at_time": int((~pre["registered_at_time"]).sum()),
            "pre_2023_confirmed_programme_vs_not": {"programme": int((pre["crsp_class"].eq("confirmed") & pre["programme"]).sum()),
                                                    "fewer_supplements": int((pre["crsp_class"].eq("confirmed") & ~pre["programme"]).sum())},
        },
        "a1_broad": event_summary(eps[eps["a1_event"]]),
        "a1_programme": event_summary(eps[eps["a1_programme"]]),
        "a1_programme_deployed_names_2020_on_count_only": deployed_activity(eps),
        "crsp_c_quarters": {
            "beyond_drip_issuance_quarters": int(len(cq)), "funds": int(cq["permno"].nunique()),
            "by_year": cq.groupby(cq["q"].dt.year).size().rename(index=str).to_dict(),
            "edgar_confirmed": int(cq["edgar_confirmed"].sum()),
            "edgar_confirmed_funds": int(cq.loc[cq["edgar_confirmed"], "permno"].nunique()),
            "edgar_confirmed_by_year": cq[cq["edgar_confirmed"]].groupby(cq["q"].dt.year).size().rename(index=str).to_dict(),
            "quarters_ge_2pct_raw_seasoned": int(((qp["gr"] >= MIN_Q_GROWTH) & (qp["age_q"] >= SEASONED_QUARTERS)).sum()),
            "excluded_merger": int(((qp["gr"] >= MIN_Q_GROWTH) & qp["merger"]).sum()),
            "excluded_rights": int(((qp["gr"] >= MIN_Q_GROWTH) & qp["rights"] & ~qp["merger"]).sum()),
            "excluded_split": int(((qp["gr"] >= MIN_Q_GROWTH) & qp["split"]).sum()),
            "excluded_within_drip_bound": int(((qp["gr"] >= MIN_Q_GROWTH) & ~qp["split"] & ~qp["merger"] & ~qp["rights"]
                                                & (qp["age_q"] >= SEASONED_QUARTERS) & ~qp["beyond_drip"]).sum()),
            "in_44_funds": sorted(set(";".join(cq["in_44"].dropna()).split(";")) - {""}),
            "families_funds": int(cq["families_ticker"].nunique()),
        },
    }
    # the method cross-check: EDGAR-confirmed C quarters that sit inside an A1 event's window
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        PRIVATE.mkdir(parents=True, exist_ok=True)
        tracked = eps[list(TRACKED_COLUMNS)].copy()
        tracked.to_csv(EPISODES_CSV, index=False)
        eps.to_csv(PRIVATE / "a1_episodes_crsp_joined.csv", index=False)
        qp.to_parquet(PRIVATE / "a1_c_quarters.parquet")
        link.to_csv(PRIVATE / "a1_link.csv", index=False)
        CENSUS_JSON.write_text(json.dumps(res, indent=2, default=str))
    res["_eps"], res["_qp"], res["_link"], res["_tickers"] = eps, qp, link, tickers
    return res


# =============================================================================
# levels: the mechanism check (descriptive; no position, no P&L)
# =============================================================================

def premium_panel(px: pd.DataFrame, nav: pd.DataFrame, z_window: int) -> dict:
    """ticker -> DataFrame(date, p, z, adv) on same-date pairs before 2023-01-01.

    p mirrors the sleeve's `disc` (percent); z mirrors its rolling z with
    `shift(1)` (data strictly before the date); adv is the 63-session mean dollar
    volume, also `shift(1)`."""
    px = px[px["date"] < TIME_HOLDOUT]
    nav = nav[nav["date"] < TIME_HOLDOUT]
    m = px[["date", "ticker", "close", "volume"]].merge(nav[["date", "ticker", "nav"]], on=["date", "ticker"], how="inner")
    m = m[(m["close"] > 0) & (m["nav"] > 0)].sort_values(["ticker", "date"])
    out = {}
    for t, g in m.groupby("ticker"):
        g = g.set_index("date")
        p = 100.0 * (g["close"] - g["nav"]) / g["nav"]
        mu = p.rolling(z_window, min_periods=Z_MIN_PERIODS).mean().shift(1)
        sd = p.rolling(z_window, min_periods=Z_MIN_PERIODS).std().shift(1)
        z = ((p - mu) / sd.replace(0, np.nan)).clip(-Z_CLIP, Z_CLIP)
        adv = (g["close"] * g["volume"]).rolling(63, min_periods=21).mean().shift(1)
        df = pd.DataFrame({"p": p, "z": z, "adv": adv}).reset_index()
        assert_pre_holdout(df["date"], f"premium panel {t}")
        out[t] = df
    return out


def path_at(df: pd.DataFrame, i0: int, offsets) -> dict | None:
    """Premium at each offset (paired sessions) from row i0, or None if any is missing."""
    if i0 + max(offsets) >= len(df) or i0 + min(offsets) < 0:
        return None
    vals = {k: float(df["p"].iat[i0 + k]) for k in offsets}
    if not all(np.isfinite(v) for v in vals.values()):
        return None
    assert_pre_holdout(df["date"].iat[i0 + max(offsets)], "premium at the last offset")
    return vals


def disp_ratio(df: pd.DataFrame, i0: int) -> float | None:
    if i0 - WIN_DISP < 0 or i0 + WIN_DISP >= len(df):
        return None
    pre = df["p"].iloc[i0 - WIN_DISP:i0].std()
    post = df["p"].iloc[i0 + 1:i0 + 1 + WIN_DISP].std()
    return float(post / pre) if pre > 0 else None


def match_controls(panel: dict, date: pd.Timestamp, p0: float, z0: float, exclude: set, offsets) -> list[dict]:
    """Same-date families funds within the premium and z bands, not excluded, with a full path."""
    out = []
    for t, df in panel.items():
        if t in exclude:
            continue
        hit = np.flatnonzero(df["date"].to_numpy() == np.datetime64(date))
        if not len(hit):
            continue
        i = int(hit[0])
        pz, zz = df["p"].iat[i], df["z"].iat[i]
        if not (np.isfinite(pz) and np.isfinite(zz)):
            continue
        if abs(pz - p0) > MATCH_PREM_PP or abs(zz - z0) > MATCH_Z:
            continue
        path = path_at(df, i, offsets)
        if path is None:
            continue
        out.append({"ticker": t, "path": path, "disp": disp_ratio(df, i)})
    return out


def busy_tickers(date: pd.Timestamp, ev_dates: dict, cq_by_ticker: dict) -> set:
    """Families tickers with an A1 event within a year of `date` or a C quarter within four."""
    q = pd.Period(date, "Q")
    busy = {t for t, ds in ev_dates.items() if any(abs((d - date).days) <= 365 for d in ds)}
    busy |= {t for t, qs in cq_by_ticker.items() if any(abs((x - q).n) <= 4 for x in qs)}
    return busy


def summarise_D(rows: list[dict], k: int) -> dict:
    D = np.array([r[f"D_{k}"] for r in rows], dtype=float)
    D = D[np.isfinite(D)]
    if not len(D):
        return {"n": 0}
    from math import comb
    n, neg = len(D), int((D < 0).sum())
    # two-sided sign test, descriptive only (no trial is judged on it)
    tail = sum(comb(n, i) for i in range(0, min(neg, n - neg) + 1)) / 2 ** n
    return {"n": n, "median_bp": round(float(np.median(D)) * 100, 1), "mean_bp": round(float(D.mean()) * 100, 1),
            "share_negative": round(neg / n, 3), "sign_test_p_two_sided": round(min(1.0, 2 * tail), 4),
            "iqr_bp": [round(float(np.percentile(D, 25)) * 100, 1), round(float(np.percentile(D, 75)) * 100, 1)]}


def gate_verdict(g1_groups: int, g2_share: float, d63_med_bp: float, d63_neg_share: float,
                 placebo_med_bp: float | None, short_share: float) -> dict:
    """The five gates, from measured inputs only (H14)."""
    bar = -ROUND_TRIP_UNITS * max(COST_GRID_BP)
    g = {
        "G-A1-1 groups >= %d" % GATE_MIN_GROUPS: g1_groups >= GATE_MIN_GROUPS,
        "G-A1-2 identity share >= %.2f" % GATE_IDENTITY_SHARE: g2_share >= GATE_IDENTITY_SHARE,
        "G-A1-3 median D63 <= %dbp and share<0 >= %.2f" % (bar, GATE_SIGN_SHARE):
            (d63_med_bp <= bar) and (d63_neg_share >= GATE_SIGN_SHARE),
        "G-A1-4 |placebo| < %.1f |event|" % GATE_PLACEBO_RATIO:
            placebo_med_bp is not None and abs(placebo_med_bp) < GATE_PLACEBO_RATIO * abs(d63_med_bp),
        "G-A1-5 shortable share >= %.2f" % GATE_SHORTABLE_SHARE: short_share >= GATE_SHORTABLE_SHARE,
    }
    halted = not g["G-A1-2 identity share >= %.2f" % GATE_IDENTITY_SHARE]
    verdict = "HALT (identity)" if halted else ("PASS" if all(g.values()) else "FAIL")
    return {"gates": g, "verdict": verdict, "cost_bar_bp": bar}


def level_check(ev: pd.DataFrame, panel: dict, ev_dates: dict, cq_by_ticker: dict, min_adv: float) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """The descriptive mechanism check on one event set (families-panel events only)."""
    rows, plac = [], []
    dropped = {"no_panel": 0, "no_tau0": 0, "no_path_or_holdout": 0, "no_z": 0, "few_controls": 0}
    for r in ev.itertuples():
        t = r.families_ticker
        if t not in panel:
            dropped["no_panel"] += 1
            continue
        df = panel[t]
        later = np.flatnonzero(df["date"].to_numpy() >= np.datetime64(r.first_date))
        if not len(later):
            dropped["no_tau0"] += 1
            continue
        i0 = int(later[0])
        path = path_at(df, i0, OFFSETS)
        if path is None:
            dropped["no_path_or_holdout"] += 1
            continue
        d0, p0, z0 = df["date"].iat[i0], df["p"].iat[i0], df["z"].iat[i0]
        rec = {"ticker": t, "sponsor": r.sponsor, "group_month": r.group_month, "date": d0, "p0": p0, "z0": z0,
               "adv0": df["adv"].iat[i0], "disp": disp_ratio(df, i0), **{f"p_{k}": v for k, v in path.items()}}
        if not np.isfinite(z0):
            dropped["no_z"] += 1
            rec["controls"] = 0
            rows.append(rec)
            continue
        ctr = match_controls(panel, d0, p0, z0, busy_tickers(d0, ev_dates, cq_by_ticker) | {t}, OFFSETS)
        rec["controls"] = len(ctr)
        if len(ctr) >= MIN_CONTROLS:
            for k in OFFSETS:
                if k > 0:
                    rec[f"D_{k}"] = (path[k] - path[0]) - float(np.median([x["path"][k] - x["path"][0] for x in ctr]))
            dd = [x["disp"] for x in ctr if x["disp"] is not None]
            rec["ctrl_disp_median"] = float(np.median(dd)) if dd else np.nan
        else:
            dropped["few_controls"] += 1
        rows.append(rec)
        # placebo: the same fund PLACEBO_SHIFT sessions earlier, with no C quarter or EDGAR
        # episode touching its forward window, matched the same way
        j0 = i0 - PLACEBO_SHIFT
        if j0 >= 0:
            pp = path_at(df, j0, OFFSETS)
            dj = df["date"].iat[j0]
            fwd_end = df["date"].iat[min(j0 + max(OFFSETS), len(df) - 1)]
            clean = (not any(pd.Period(dj, "Q") <= x <= pd.Period(fwd_end, "Q") for x in cq_by_ticker.get(t, []))
                     and not any(dj <= d <= fwd_end for d in ev_dates.get(t, [])))
            zj = df["z"].iat[j0]
            if pp is not None and clean and np.isfinite(zj) and fwd_end < r.first_date:
                cj = match_controls(panel, dj, df["p"].iat[j0], zj, busy_tickers(dj, ev_dates, cq_by_ticker) | {t}, OFFSETS)
                if len(cj) >= MIN_CONTROLS:
                    plac.append({"ticker": t, "date": dj, **{f"D_{k}": (pp[k] - pp[0]) - float(np.median([x["path"][k] - x["path"][0] for x in cj]))
                                                            for k in OFFSETS if k > 0}})
    R = pd.DataFrame(rows)
    usable = R[R["D_63"].notna()] if "D_63" in R else R.iloc[0:0]
    res = {"events_in_families_panel": int(len(ev)), "dropped": dropped,
           "with_full_path": int(len(R)), "with_controls": int(len(usable)),
           "groups_sponsor_month_with_controls": int(usable["group_month"].nunique()) if len(usable) else 0,
           "groups_sponsor_month_with_full_path": int(R["group_month"].nunique()) if len(R) else 0,
           "funds_with_full_path": int(R["ticker"].nunique()) if len(R) else 0}
    if len(R):
        res["first_tau0"] = str(pd.Timestamp(R["date"].min()).date())
        res["last_tau0"] = str(pd.Timestamp(R["date"].max()).date())
        res["premium_at_tau0"] = {"n": int(len(R)), "median_pct": round(float(R["p0"].median()), 2),
                                  "iqr_pct": [round(float(R["p0"].quantile(.25)), 2), round(float(R["p0"].quantile(.75)), 2)],
                                  "share_ge_0": round(float((R["p0"] >= 0).mean()), 3),
                                  "median_z0": round(float(R["z0"].median()), 2) if R["z0"].notna().any() else None}
        res["premium_path_median_pct"] = {str(k): round(float(R[f"p_{k}"].median()), 2) for k in OFFSETS}
        res["premium_path_iqr_pct"] = {str(k): [round(float(R[f"p_{k}"].quantile(.25)), 2), round(float(R[f"p_{k}"].quantile(.75)), 2)] for k in OFFSETS}
        res["share_events_premium_lower_at_63"] = round(float((R["p_63"] < R["p_0"]).mean()), 3)
        res["dispersion"] = {"own_sd_ratio_post_over_pre_events_median": round(float(R["disp"].dropna().median()), 3) if R["disp"].notna().any() else None,
                             "own_sd_ratio_controls_median_of_medians": round(float(usable["ctrl_disp_median"].dropna().median()), 3) if len(usable) and usable["ctrl_disp_median"].notna().any() else None}
        res["adv_tau0"] = {"median_usd": round(float(R["adv0"].median()), 0),
                           "share_ge_spec_min_adv": round(float((R["adv0"] >= min_adv).mean()), 3)}
    res["D_event"] = {str(k): summarise_D(usable.to_dict("records"), k) for k in OFFSETS if k > 0} if len(usable) else {}
    if len(usable):
        gm = usable.groupby("group_month")[[f"D_{k}" for k in OFFSETS if k > 0]].median().reset_index()
        res["D_event_group_medians"] = {str(k): summarise_D(gm.to_dict("records"), k) for k in OFFSETS if k > 0}
    P = pd.DataFrame(plac)
    res["D_placebo"] = {str(k): summarise_D(P.to_dict("records"), k) for k in OFFSETS if k > 0} if len(P) else {}
    return res, R, P


def access(eps: pd.DataFrame, flags: pd.DataFrame, flags_utc: str, sel: str) -> dict:
    """Alpaca flags (one read) for the distinct funds of an event set that still have a ticker."""
    from scripts.cef.spec import UNIVERSE
    a1 = eps[eps[sel]].copy()
    funds = a1.groupby("cik").agg(ticker_now=("ticker_now", "first")).reset_index()
    listed = funds[funds["ticker_now"].notna()].copy()
    listed["sym"] = listed["ticker_now"].map(common_symbol)
    listed["alpaca_active"] = listed["sym"].isin(flags.index)
    act = listed[listed["alpaca_active"]]
    sh = flags.loc[act["sym"], "shortable"].astype(bool).to_numpy() if len(act) else np.array([])
    etb = flags.loc[act["sym"], "easy_to_borrow"].astype(bool).to_numpy() if len(act) else np.array([])
    probe = json.loads((REPO / "results" / "ops" / "alpaca_probe" / "2026-10-15_cef.json").read_text())
    pa = probe["assets"]
    return {"set": sel, "alpaca_assets_read_utc": flags_utc,
            "event_funds": int(len(funds)), "with_sec_ticker_now": int(len(listed)),
            "active_at_alpaca": int(len(act)), "shortable": int(sh.sum()), "easy_to_borrow": int(etb.sum()),
            "shortable_share_of_active": round(float(sh.mean()), 3) if len(sh) else 0.0,
            "not_shortable": sorted(act.loc[~sh.astype(bool), "sym"].tolist()) if len(act) else [],
            "probe_2026_10_15_utc": probe.get("fetched_at_utc"),
            "deployed_flags_2026_10_15": {t: {"shortable": pa[t]["shortable"], "easy_to_borrow": pa[t]["easy_to_borrow"]}
                                          for t in UNIVERSE if t in pa}}


def premium_funds_now(flags: pd.DataFrame, path: Path) -> dict:
    """CEFConnect's 2026-10-09 discount for every fund it lists, against Alpaca's flags.

    A one-day LEVEL used for feasibility only (which funds trade above NAV today and
    can they be shorted); no return is formed from it."""
    j = json.loads(Path(path).read_text())
    d = pd.DataFrame(j["data"])
    need = {"Ticker", "Discount", "Strategy"}
    if not need <= set(d.columns):
        raise A1DataError(f"{path}: missing {sorted(need - set(d.columns))}")
    prem = d[d["Discount"] > 0].copy()
    prem["active"] = prem["Ticker"].isin(flags.index)
    a = prem[prem["active"]]
    sh = flags.loc[a["Ticker"], "shortable"].astype(bool)
    etb = flags.loc[a["Ticker"], "easy_to_borrow"].astype(bool)
    return {"cefconnect_read_utc": j["meta"].get("received_utc"), "funds_listed": int(len(d)),
            "at_premium": int(len(prem)), "at_premium_active_at_alpaca": int(len(a)),
            "at_premium_shortable": int(sh.sum()), "at_premium_easy_to_borrow": int(etb.sum()),
            "at_premium_by_strategy": prem["Strategy"].value_counts().head(8).to_dict()}


def levels(edgar_cache: Path, crsp_dirs, write: bool = True) -> dict:
    from scripts.cef.spec import Z_WINDOW, MIN_ADV_USD
    c = census(edgar_cache, crsp_dirs, write=write)
    eps, qp = c["_eps"], c["_qp"]
    fam = REPO / "data" / "cef_families"
    px = pd.read_parquet(fam / "cef_prices_crsp.parquet")
    nav = pd.read_parquet(fam / "cef_nav.parquet")
    for d in (px, nav):
        d["date"] = pd.to_datetime(d["date"])
    u44 = set(pd.read_csv(REPO / "data" / "cef" / "cef_universe.csv")["ticker"])
    if set(px["ticker"]) & u44 or set(nav["ticker"]) & u44:
        raise A1DataError("a cef_universe.csv name is in the families panel; refusing (27-name set)")
    panel = premium_panel(px, nav, Z_WINDOW)
    # a control or placebo must be clean of ANY EDGAR offering episode (rights and
    # unconfirmed included) within a year, not only of A1 events
    pre_eps = eps[(eps["first_date"] < TIME_HOLDOUT) & eps["families_ticker"].notna()]
    ev_dates = {t: list(pd.to_datetime(g["first_date"])) for t, g in pre_eps.groupby("families_ticker")}
    cq_by_ticker = {t: list(g["q"]) for t, g in qp[qp["iss"] & qp["families_ticker"].notna()].groupby("families_ticker")}
    out = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "params": {"z_window_from_spec": Z_WINDOW, "offsets": OFFSETS, "match_prem_pp": MATCH_PREM_PP,
                      "match_z": MATCH_Z, "min_controls": MIN_CONTROLS, "placebo_shift": PLACEBO_SHIFT,
                      "spec_min_adv_usd": MIN_ADV_USD, "panel_last_price_date_used": str(px.loc[px["date"] < TIME_HOLDOUT, "date"].max().date()),
                      "panel_last_nav_date_used": str(nav.loc[nav["date"] < TIME_HOLDOUT, "date"].max().date())}}
    frames = {}
    for label, sel in (("primary_programme", "a1_programme"), ("sensitivity_broad", "a1_event")):
        ev = eps[eps[sel] & eps["families_ticker"].notna()]
        res, R, P = level_check(ev, panel, ev_dates, cq_by_ticker, MIN_ADV_USD)
        out[label] = res
        frames[label] = (R, P)
    flags, flags_utc = alpaca_flags(fam / "raw" / "alpaca_assets_active_2026-10-12.json")
    out["access_primary"] = access(eps, flags, flags_utc, "a1_programme")
    out["access_broad"] = access(eps, flags, flags_utc, "a1_event")
    out["premium_funds_now"] = premium_funds_now(flags, fam / "raw" / "cefconnect_dailypricing_2026-10-12.json")
    pr = out["primary_programme"]
    de = pr["D_event"].get(str(H_GATE), {}) if pr["D_event"] else {}
    pl = pr["D_placebo"].get(str(H_GATE), {}).get("median_bp") if pr["D_placebo"] else None
    out["gate"] = gate_verdict(
        g1_groups=pr["groups_sponsor_month_with_controls"],
        g2_share=pr.get("premium_at_tau0", {}).get("share_ge_0", 0.0),
        d63_med_bp=de.get("median_bp", 0.0) if de.get("n") else 0.0,
        d63_neg_share=de.get("share_negative", 0.0) if de.get("n") else 0.0,
        placebo_med_bp=pl, short_share=out["access_primary"]["shortable_share_of_active"])
    if write:
        for label, (R, P) in frames.items():
            R.to_csv(PRIVATE / f"a1_level_events_{label}.csv", index=False)
            P.to_csv(PRIVATE / f"a1_level_placebo_{label}.csv", index=False)
        LEVELS_JSON.write_text(json.dumps(out, indent=2, default=str))
    out["_eps"] = eps
    return out


def validation_sample(eps: pd.DataFrame, n: int = SAMPLE_N, seed: int = SAMPLE_SEED) -> pd.DataFrame:
    """A seeded random draw of A1 events for reading by hand (note §3): EDGAR facts only."""
    # drawn on 2026-10-20 BEFORE revision 1, from every confirmed episode dated before
    # 2023 (no registered-at-the-time rule yet); kept so that the draw reproduces
    a1 = eps[(eps["crsp_class"] == "confirmed") & (eps["first_date"] < TIME_HOLDOUT)]
    a1 = a1.sort_values(["cik", "first_date"]).reset_index(drop=True)
    rng = np.random.default_rng(seed)
    pick = sorted(rng.choice(len(a1), size=min(n, len(a1)), replace=False))
    s = a1.iloc[pick][["cik", "company", "ticker_now", "first_date", "first_form", "first_accession", "forms", "n_supplements"]].copy()
    s["index_url"] = [f"https://www.sec.gov/Archives/edgar/data/{c}/{a.replace('-', '')}/{a}-index.htm"
                      for c, a in zip(s["cik"], s["first_accession"])]
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=("census", "levels", "sample"))
    ap.add_argument("--edgar-cache", required=True, type=Path)
    ap.add_argument("--crsp-cache", required=True, type=Path, nargs="+")
    a = ap.parse_args(argv)
    if a.stage == "census":
        r = census(a.edgar_cache, a.crsp_cache)
    elif a.stage == "sample":
        r = census(a.edgar_cache, a.crsp_cache, write=False)
        s = validation_sample(r["_eps"])
        s.to_csv(OUT / "a1_validation_sample_draw.csv", index=False)
        print(s.to_string())
        return 0
    else:
        r = levels(a.edgar_cache, a.crsp_cache)
    print(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
