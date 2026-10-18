"""Trial C5 (CEF trial 51): fill the live book's trades at the t+1 OPENING
auction instead of the t+1 closing auction. The trial script that
`results/cef/PREREG_C5_OPEN_AUCTION_2026-10-13.md` §17 names.

    QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side open
    QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side open --sizes
    QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side close --sizes
    python3 scripts/data/stage_crsp_w4.py
    QUANTT_ENV_FILE=<config/.env> python3 scripts/cef/exec_capacity_open_cross.py fetch --skip-recent
    python3 scripts/cef/c5_open_auction.py freeze        # the frozen fit inputs + D-6; writes their sha256
    python3 scripts/cef/c5_open_auction.py stage0        # counts, gates and hashes on the FROZEN copy; no P&L

HISTORY OF THIS SCRIPT (both runs are on the record)
---------------------------------------------------
* 2026-10-14, commit 71e106b: Stage 0 on the live caches HALTED on §4.5(c), a
  panel close off both CRSP `prc` and the NYSE closing print (MHD 2017-06-21).
  Its outputs are `results/cef/c5/c5_stage0_{output,record,flags}_2026-10-14.*`;
  `git show 71e106b:scripts/cef/c5_open_auction.py` reproduces it.
* The team lead's rulings of 2026-10-14 (the AMENDMENT block at the top of the
  pre-registration): (1) a new declared defect class D-6 -- a panel close off
  both CRSP and the NYSE print, which agree with each other, takes the NYSE
  print in the TRIAL'S OWN INPUT COPY (never data/), halting above 5 name-days
  in the decision window; (2) every price-agreement test is |diff| <= $0.005 +
  1e-6, so an exact half cent on float32-stored prices agrees; (4) the fit
  reads a FROZEN copy of its inputs, so no later panel refresh can move it.
  `freeze` builds that copy and `stage0` now reads only it, after checking every
  file's sha256 against `results/cef/c5/c5_frozen_inputs_2026-10-14.json`.

WHAT IS HERE, AND WHAT IS NOT
-----------------------------
Only STAGE 0 of the order of evaluation (§13): the data gates DG-C5-1..5 and
DG-C5-8, the declared defect classes and halt rules (§4.2 and the amendment's
D-6), the "any other defect" examples of §4.5, the spec pin, the
equal-turnover check, and the input hashes. **No return is combined into a P&L
at this stage** (§13): the session return C/O - 1 is formed only to test the
harness's 50% filter, and nothing is summed over a holdings path. Stages 1-8 are
NOT implemented: the team lead reviews the amendment before any P&L.

THE FROZEN COPY. Every input the fit reads, truncated at 2022-12-30 (the whole
history to that date, not only 2016-22, because H is built from 2005 and a
copy starting in 2016 could not rebuild it): the 13 names' prices, NAVs,
distributions, splits and IBKR fee panel; the 2016-22 auction prints; the CRSP
stage; the 2016-22 quote sample. It lives in the gitignored
`results/cef/c5/_cache_c5_frozen/` (vendor and licensed data; the repository is
public) and its hashes are committed. `frozen()` points every reader at it --
`band_frontier.DATA_DIR` and the quote module's caches -- so no reader is left
on the live panel. Truncating first is exact (every builder is causal); `freeze`
proves it by rebuilding T, R and both H from the uncorrected copy and comparing
them with the live build cut at 2022-12-30.

THE HOLDOUTS. Nothing in the frozen copy is dated after 2022-12-30. The 2023+
opening prints are not fetched: `fetch_alpaca_auction_history.py --holdout`
refuses until `results/cef/c5/C5_FIT_VERDICT.json` is committed (DG-C5-6).
Only the 13 spec names are read.

NO SILENT FALLBACK. A missing cache raises naming its builder. A defect is
counted and listed by its declared class; D-6 is the only alteration, applied
to the trial's copy by its stated rule and logged name-day by name-day; anything
outside the declared classes halts.

Committed outputs hold counts, shares, differences in cents and hashes, never a
vendor price level:
  results/cef/c5/c5_frozen_inputs_<STAMP>.json, c5_freeze_output_<STAMP>.txt
  results/cef/c5/c5_stage0_amended_{output,record,flags}_<STAMP>.*
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import pickle
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

STAMP = "2026-10-14"
OUT_DIR = REPO / "results" / "cef" / "c5"
LIVE_CEF = REPO / "data" / "cef"                  # read by `freeze` only
LIVE_W4 = REPO / "results" / "cef" / "w4" / "_cache_w4"
LIVE_EXEC = REPO / "results" / "cef" / "exec_capacity" / "_cache_exec"
FROZEN = OUT_DIR / "_cache_c5_frozen"              # gitignored (results/**/_cache_*)
F_CEF_RAW = FROZEN / "cef_raw"                     # the panels as in data/: 13 names, <= 2022-12-30, uncorrected
F_CEF = FROZEN / "cef"                             # the TRIAL'S INPUT COPY: the same, with D-6 applied
F_W4 = FROZEN / "w4"                               # the 2016-22 auction prints and the CRSP stage
F_EXEC = FROZEN / "exec"                           # the 2016-22 quote sample (126 sessions) and its calendar
FREEZE_RECORD = OUT_DIR / f"c5_frozen_inputs_{STAMP}.json"
# LICENSED DETAIL STAYS OUT OF TRACKED FILES (coordinator, 2026-10-15; main a838b24): a signed
# close-minus-CRSP (or CRSP-minus-NYSE) difference beside the public close recovers CRSP's
# licensed price on that date. Tracked outputs carry counts, era aggregates, the class of a
# name-day and its difference from the NYSE print; any per-date CRSP quantity is written
# only here, gitignored (results/**/_cache_*) and outside the hash-verified frozen copy.
LOG_CACHE = OUT_DIR / "_cache_c5_logs"
PANELS = ("cef_prices", "cef_nav", "cef_distributions", "cef_splits", "cef_borrow_history")
W4_FILES = ("alpaca_opening_prints_2016_2022.parquet", "alpaca_opening_prints_sized_2016_2022.parquet",
            "alpaca_closing_prints_sized_2016_2022.parquet", "crsp_dsf_w4.parquet")
OPEN_PRINTS = F_W4 / W4_FILES[0]
CLOSE_SIZED = F_W4 / W4_FILES[2]
CRSP = F_W4 / W4_FILES[3]
SPEC_FILE = REPO / "ops" / "specs" / "cef_discount.frozen.json"

# ---- the pre-registration's declarations (PREREG_C5, read 2026-10-14). These are
# the RULES the trial was approved on, asserted against the data, never tuned.
SPEC_SHA256 = "c05035e55eaa89172f65d38a3485cb1c68123217177343b38576edf56583c02e"   # DG-C5-2
SPEC_PIN = dict(spec_id="cef_discount.v7.20260928", band_width=0.048, max_gross_stress=1.80,
                z_window=252, min_adv_usd=3_000_000, min_names=6, vol_target=0.06,
                n_names=13, capital_usd=100_000.0, order_type="MOC",
                MIN_PERIODS=120, VOL_LOOKBACK=63, SAMPLE_START="2005-01-03")
N_APPROVED = 52                                   # the APPROVED block: judged at N = 52
WINDOW = (pd.Timestamp("2016-01-04"), pd.Timestamp("2022-12-30"))   # decision 3
WINDOW_SESSIONS = 1762                            # §5: "That is 1,762 sessions"
TICK = 0.005                                      # §4.2's price-agreement tolerance
TOL = TICK + 1e-6                                 # ruling 2 (team lead, 2026-10-14): |diff| <= $0.005 + 1e-6 agrees
D6_HALT_N = 5                                     # ruling 1: halt if more than 5 D-6 name-days in the window
FIT_END = pd.Timestamp("2022-12-30")
MATERIAL = 0.005                                  # §12.2: a trade of at least 0.5% of capital
HALT = dict(D1_trades=0.01, D1_notional=0.01, D2_both=0.01, D3_trades=0.005, D5_trades=0.001)
# the pre-edit no-op hashes of build_targets() (DG-C5-4): first and second call in one process
NOOP_FIRST = "007e221b574418095acae07c4ef7d1f650cc31c18ef05c3d4528d49867c37cdc"
NOOP_SECOND = "c8291c1ea3834a4c9e2b61d6e8064860ddf124d6c547b7942eb24d685b8ee599"
# [S] the 2026-10-13 counts of §4.2 and §12, printed BESIDE today's; never a decision input (H14)
REF_2026_10_13 = dict(panel_name_days=21628, O=21598, none=29, Q_only=1, both_OQ=5341, D2=0, D3=0,
                      out_of_range_flagged=4, D1_trades_dep=3, D1_trades_wide=9,
                      mat_dep=1763, mat_wide=6456, D5_dep=0, D5_wide=0)


class Halt(RuntimeError):
    """A Stage 0 gate or halt rule fired: stop before any P&L (PREREG_C5 §4.2, §4.5, §13)."""


def _need(p: Path, builder: str) -> Path:
    if not p.exists():
        raise FileNotFoundError(f"{p.relative_to(REPO)} is missing; build it with `{builder}`. "
                                "No substitute is used.")
    return p


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def hr(t: str) -> None:
    print("\n" + "=" * 100 + f"\n{t}\n" + "=" * 100)


@contextlib.contextmanager
def frozen():
    """Point EVERY reader at the frozen copy, and restore on exit: the harness's
    panels (band_frontier.DATA_DIR) and the quote module's caches (CACHE for the
    sample, W4_CACHE for the sized prints it classifies)."""
    from scripts.cef import band_frontier as bf
    from scripts.cef import exec_capacity_open_cross as X
    old = (bf.DATA_DIR, X.CACHE, X.W4_CACHE)
    bf.DATA_DIR, X.CACHE, X.W4_CACHE = F_CEF, F_EXEC, F_W4
    try:
        yield
    finally:
        bf.DATA_DIR, X.CACHE, X.W4_CACHE = old


def nyse_close_prints(k: pd.DataFrame, idx, U) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(close6, closeM, repeated): the primary listing's closing-trade (`6`) and
    official-close (`M`) prints, date x ticker. Two prints of one condition on one
    name-day are ambiguous only if their PRICES differ -- the runner's rule
    (quantt/broker/alpaca.py closing_auction_prints raises AmbiguousAuctionPrint on
    two prices); that raises here. On 2021-12-31 every name's M was published
    twice, at 16:00 and 19:00 ET, at one price and size: counted, not a defect."""
    kn = k[k.exchange == "N"]
    reps = {}
    for cond in ("6", "M"):
        s = kn[kn.condition == cond]
        d = s[s.duplicated(["date", "ticker"], keep=False)]
        if len(d) and (d.groupby(["date", "ticker"]).price.nunique() > 1).any():
            raise Halt(f"NYSE condition-{cond} closing prints at two different prices on one name-day")
        reps[cond] = sorted({str(x.date()) for x in d.date})
    piv = lambda cond: (kn[kn.condition == cond].drop_duplicates(["date", "ticker"])
                        .pivot(index="date", columns="ticker", values="price").reindex(index=idx, columns=U))
    return piv("6"), piv("M"), reps


def _read_panel(path: Path, datecol: str, U) -> pd.DataFrame:
    d = pd.read_parquet(_need(path, "the live panel"))
    d = d[d.ticker.isin(U)].copy()
    return d[pd.to_datetime(d[datecol]) <= FIT_END].reset_index(drop=True)


def _holdings(min_adv) -> pd.DataFrame:
    """band_gross_capped on the spec, on whatever bf.DATA_DIR points at, cut at the fit."""
    from scripts.cef import band_frontier as bf
    from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS
    cap = MAX_GROSS_STRESS if MAX_GROSS_STRESS is not None else np.inf
    T, R = bf.build_targets(min_adv=min_adv)
    T, R = bf.fit_only(T, R)
    return T, R, bf.band_gross_capped(T, BAND_WIDTH, cap)


def freeze() -> dict:
    """Build the frozen copy, apply D-6 to the trial's input copy, and hash it all.

    D-6 (ruling 1, team lead 2026-10-14): on a decision-window name-day where the
    panel close is off BOTH CRSP |prc| and the NYSE closing print (M where
    published, else 6) by more than TOL, and those two agree within TOL, the
    trial's copy takes the NYSE closing print -- the closing-auction price the MOC
    convention models; for MHD 2017-06-21 the two sources are identical. Off both
    with the two sources NOT agreeing is still a §4.5(c) defect and halts. More
    than D6_HALT_N D-6 name-days halts. Only `close` is altered; data/ never is."""
    from scripts.cef import band_frontier as bf
    from scripts.cef import exec_capacity_open_cross as X
    from scripts.cef.spec import UNIVERSE
    U = list(UNIVERSE)
    halts = []
    hr("FREEZE: THE FIT'S INPUTS, CUT AT 2022-12-30, INTO results/cef/c5/_cache_c5_frozen/ (gitignored)")
    if FROZEN.exists():
        shutil.rmtree(FROZEN)                          # a freeze starts empty: no stale file is hashed in
    for d in (F_CEF_RAW, F_CEF, F_W4, F_EXEC / "days"):
        d.mkdir(parents=True, exist_ok=True)
    live_last = {}
    for name in PANELS:
        col = "ex_date" if name in ("cef_distributions", "cef_splits") else "date"
        full = pd.read_parquet(LIVE_CEF / f"{name}.parquet")
        live_last[name] = str(pd.to_datetime(full[col]).max().date())
        _read_panel(LIVE_CEF / f"{name}.parquet", col, U).to_parquet(F_CEF_RAW / f"{name}.parquet", index=False)
    print("live panels' last dates (read once, never again by the fit):", live_last)
    for f in W4_FILES:
        a = pd.read_parquet(_need(LIVE_W4 / f, "see the module docstring"))
        if pd.to_datetime(a["date"]).max() > FIT_END:
            raise Halt(f"{f} carries a date after {FIT_END.date()}")
        shutil.copy2(LIVE_W4 / f, F_W4 / f)
    cal = pd.read_parquet(_need(LIVE_EXEC / "calendar.parquet", "exec_capacity_open_cross.py fetch --skip-recent"))
    cal[cal.date <= str(FIT_END.date())].to_parquet(F_EXEC / "calendar.parquet", index=False)
    old = X.CACHE
    X.CACHE = F_EXEC
    try:
        days = X.sample_days(eras=("fit",))
    finally:
        X.CACHE = old
    for dd in days:
        shutil.copy2(_need(LIVE_EXEC / "days" / f"{dd}.json", "exec_capacity_open_cross.py fetch --skip-recent"),
                     F_EXEC / "days" / f"{dd}.json")
    print(f"copied: {len(PANELS)} panels (13 names, <= {FIT_END.date()}), {len(W4_FILES)} print/CRSP caches, "
          f"the quote sample's {len(days)} sessions and its calendar")

    # ---- the truncation is exact: the uncorrected copy rebuilds T, R and both H of the live build
    hr("FREEZE: THE UNCORRECTED COPY REBUILDS THE LIVE BUILD EXACTLY (cut at 2022-12-30)")
    noop = {}
    old = bf.DATA_DIR
    try:
        live = {lab: _holdings(f) for lab, f in (("WIDE", 0), ("deployed", None))}
        live_tr = bf.total_returns(live["WIDE"][1])
        bf.DATA_DIR = F_CEF_RAW
        raw = {lab: _holdings(f) for lab, f in (("WIDE", 0), ("deployed", None))}
        raw_tr = bf.total_returns(raw["WIDE"][1])
    finally:
        bf.DATA_DIR = old
    for lab in live:
        noop[lab] = all(x.equals(y) for x, y in zip(live[lab], raw[lab]))
    noop["total_returns"] = live_tr.equals(raw_tr)
    print("T, R and H identical, live build vs the uncorrected frozen copy:", noop)
    if not all(noop.values()):
        raise Halt("the frozen copy does not rebuild the live fit-period build exactly")

    # ---- D-6 on the uncorrected copy, decision window
    hr("FREEZE: D-6 (ruling 1) ON THE DECISION WINDOW; tolerance |diff| <= $0.005 + 1e-6 (ruling 2)")
    P = pd.read_parquet(F_CEF_RAW / "cef_prices.parquet")
    P["date"] = pd.to_datetime(P["date"])
    C = P.pivot_table(index="date", columns="ticker", values="close").sort_index().reindex(columns=U)
    idx = C.index[(C.index >= WINDOW[0]) & (C.index <= WINDOW[1])]
    C = C.loc[idx]
    c = pd.read_parquet(F_W4 / W4_FILES[3])
    c["date"] = pd.to_datetime(c["date"])
    prc = c[c.ticker.isin(U)].pivot_table(index="date", columns="ticker", values="prc").reindex(index=idx, columns=U).abs()
    k = pd.read_parquet(F_W4 / W4_FILES[2])
    k["date"] = pd.to_datetime(k["date"])
    c6, cM, _ = nyse_close_prints(k, idx, U)
    cp = cM.combine_first(c6)
    which = pd.DataFrame(np.where(cM.notna(), "M", np.where(c6.notna(), "6", "")), index=idx, columns=U)
    avail = C.notna() & prc.notna() & cp.notna()
    off_both = avail & ((C - prc).abs() > TOL) & ((C - cp).abs() > TOL)
    agree = (prc - cp).abs() <= TOL
    d6, other = off_both & agree, off_both & ~agree
    tr = {lab: open_trades(raw[lab][2]).loc[idx] for lab in raw}
    log, detail = [], []
    for (d, t) in _cells(off_both):
        lab_w = _tradelab(tr["WIDE"].at[d, t])
        lab_d = _tradelab(tr["deployed"].at[d, t])
        log.append(dict(date=str(d.date()), ticker=t, cls="D-6" if d6.at[d, t] else "§4.5(c) (sources disagree)",
                        close_minus_nyse_c=round(float(100 * (C.at[d, t] - cp.at[d, t])), 3),
                        nyse_print=which.at[d, t], value_used="NYSE closing print" if d6.at[d, t] else "none (halt)",
                        WIDE_trade=lab_w, deployed_trade=lab_d))
        detail.append(dict(date=str(d.date()), ticker=t, close_minus_crsp_c=round(float(100 * (C.at[d, t] - prc.at[d, t])), 3),
                           crsp_minus_nyse_c=round(float(100 * (prc.at[d, t] - cp.at[d, t])), 3)))
    LOG_CACHE.mkdir(parents=True, exist_ok=True)
    (LOG_CACHE / f"d6_crsp_detail_fit_{STAMP}.json").write_text(json.dumps(detail, indent=1) + "\n")
    print(f"name-days with a close, CRSP prc and an NYSE closing print: {int(avail.sum().sum()):,}; off both: "
          f"{int(off_both.sum().sum())}; D-6 (the two sources agree): {int(d6.sum().sum())}; "
          f"sources disagree (§4.5(c), halts): {int(other.sum().sum())}")
    for r in log:
        print("   ", r)
    if d6.sum().sum() > D6_HALT_N:
        halts.append(f"D-6: {int(d6.sum().sum())} name-days, above the ruled {D6_HALT_N}")
    if other.any().any():
        halts.append(f"§4.5(c): {int(other.sum().sum())} close(s) off both sources, which disagree with each other")

    # ---- the trial's input copy: D-6 applied to `close`, every other file identical
    Praw = pd.read_parquet(F_CEF_RAW / "cef_prices.parquet")
    Pin = Praw.copy()
    dts = pd.to_datetime(Pin["date"])
    for (d, t) in _cells(d6):
        m = (dts == d) & (Pin.ticker == t)
        if m.sum() != 1:
            raise Halt(f"D-6 {d.date()} {t}: {int(m.sum())} rows in the copy, not one")
        Pin.loc[m, "close"] = float(cp.at[d, t])
    Pin.to_parquet(F_CEF / "cef_prices.parquet", index=False)
    for name in PANELS[1:]:
        shutil.copy2(F_CEF_RAW / f"{name}.parquet", F_CEF / f"{name}.parquet")
    changed = int((Pin["close"] != Praw["close"]).sum())
    print(f"the trial's input copy: {changed} close(s) altered (D-6), every other value and file identical")
    old = bf.DATA_DIR
    try:
        bf.DATA_DIR = F_CEF
        inp = {lab: _holdings(f)[2] for lab, f in (("WIDE", 0), ("deployed", None))}
    finally:
        bf.DATA_DIR = old
    hdiff = {}
    for lab in inp:
        dd = (inp[lab] - raw[lab][2]).abs()
        hdiff[lab] = dict(cells_differing=int((dd > 0).sum().sum()), cells_over_1e_4=int((dd > 1e-4).sum().sum()),
                          max_abs_weight_diff=float(dd.max().max()),
                          first_date=str(dd.index[(dd.sum(axis=1) > 0).to_numpy()].min().date())
                          if (dd > 0).any().any() else None)
    print("holdings (date x name, 2005-2022), input copy against the uncorrected copy: the close enters the "
          "z-score's 252-session window, the vol scalar and the band's path, so one corrected close moves later "
          "weights slightly (weights only; no return):", hdiff)

    hr("FREEZE: SHA-256 OF EVERY FROZEN FILE")
    files = {}
    for f in sorted(FROZEN.rglob("*")):
        if f.is_file():
            files[str(f.relative_to(FROZEN))] = sha256_file(f)
    for name in sorted(files):
        if not name.startswith("exec/days/"):
            print(f"{files[name]}  {name}")
    dh = hashlib.sha256("".join(f"{n}{h}" for n, h in sorted(files.items()) if n.startswith("exec/days/")).encode())
    print(f"{dh.hexdigest()}  exec/days/<{sum(n.startswith('exec/days/') for n in files)} session files> (combined)")
    rec = dict(stamp=STAMP, root=str(FROZEN.relative_to(REPO)), fit_end=str(FIT_END.date()),
               live_last_dates=live_last, tolerance="|diff| <= 0.005 + 1e-6", d6_halt_above=D6_HALT_N,
               d6_value_rule="the NYSE closing print (M where published, else 6); applied to `close` only",
               truncation_noop=noop, d6_log=log, d6_count=int(d6.sum().sum()), holdings_cells_changed=hdiff,
               exec_days_combined_sha256=dh.hexdigest(), files=files, halts=halts,
               verdict="HALT" if halts else "FROZEN")
    hr("FREEZE VERDICT: " + rec["verdict"])
    for x in halts:
        print("  - " + x)
    return rec


def verify_frozen() -> dict:
    """Every later stage re-verifies the frozen files before it reads one; a
    mismatch, a missing file or an extra file halts."""
    if not FREEZE_RECORD.exists():
        raise Halt(f"{FREEZE_RECORD.relative_to(REPO)} is missing: run `freeze` and commit it first")
    rec = json.loads(FREEZE_RECORD.read_text())
    if rec.get("verdict") != "FROZEN":
        raise Halt(f"the freeze record's verdict is {rec.get('verdict')}, not FROZEN")
    got = {str(f.relative_to(FROZEN)): sha256_file(f) for f in sorted(FROZEN.rglob("*")) if f.is_file()}
    bad = sorted(set(got) ^ set(rec["files"])) + sorted(n for n in got if n in rec["files"] and got[n] != rec["files"][n])
    if bad:
        raise Halt(f"the frozen copy differs from its committed hashes: {bad[:10]}")
    return rec


def open_trades(H: pd.DataFrame) -> pd.DataFrame:
    """Row s: |the trade decided at s-1|, which fills at the open of s -- read
    through `open_fill_gain` with RS = 1, so there is one definition of the lag."""
    from scripts.cef.band_frontier import open_fill_gain
    ones = pd.DataFrame(1.0, index=H.index, columns=H.columns)
    return open_fill_gain(H, ones, by_name=True).abs()


def _tradelab(x: float) -> str:
    return "material" if x >= MATERIAL else ("small" if x > 1e-12 else "-")


# =============================================================================
# the data
# =============================================================================

class Data:
    """Every frame Stage 0 reads, on the decision window's sessions, from the
    FROZEN copy (call inside `frozen()`). Nothing here carries a date after
    2022-12-30."""

    def __init__(self):
        from scripts.cef import band_frontier as bf
        from scripts.cef.c5_feasibility import nyse_open_prints
        from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS, UNIVERSE
        from scripts.cef.w4_artifacts import _assert_fit
        self.U = U = list(UNIVERSE)
        if bf.DATA_DIR != F_CEF:
            raise Halt("Data() must be built inside frozen(): the fit reads only the frozen copy")
        P = pd.read_parquet(F_CEF / "cef_prices.parquet")
        P = P[P.ticker.isin(U)].copy()
        P["date"] = pd.to_datetime(P["date"])
        self.prices_last = P["date"].max()
        P = P[P["date"] <= WINDOW[1]]
        pv = lambda c: P.pivot_table(index="date", columns="ticker", values=c).sort_index().reindex(columns=U)
        close, op_y, hi, lo = pv("close"), pv("open"), pv("high"), pv("low")
        _assert_fit(close)
        idx = close.index[(close.index >= WINDOW[0]) & (close.index <= WINDOW[1])]
        if len(idx) != WINDOW_SESSIONS:
            raise Halt(f"the decision window has {len(idx)} sessions in cef_prices, not the declared "
                       f"{WINDOW_SESSIONS}")
        self.idx = idx
        self.close_full = close                       # whole history to 2022-12-30 (C[s-1] needs the row before)
        self.C, self.op_y, self.hi, self.lo = close.loc[idx], op_y.loc[idx], hi.loc[idx], lo.loc[idx]
        self.C_prev = close.shift(1).loc[idx]

        a = pd.read_parquet(_need(OPEN_PRINTS, "fetch_alpaca_auction_history.py --side open"))
        a["date"] = pd.to_datetime(a["date"])
        _assert_fit(a.set_index("date"))
        self.open_raw = a
        self.O, self.Q = nyse_open_prints(a, idx, U)   # raises on two O (or Q) prints for one name-day (D-4)

        c = pd.read_parquet(_need(CRSP, "python3 scripts/data/stage_crsp_w4.py"))
        c["date"] = pd.to_datetime(c["date"])
        c = c[c["date"] <= WINDOW[1]]
        _assert_fit(c.set_index("date"))
        self.crsp = c
        cc = c[c.ticker.isin(U)]
        self.op_c = cc.pivot_table(index="date", columns="ticker", values="openprc").reindex(index=idx, columns=U)
        self.op_c = self.op_c.where(self.op_c > 0)
        self.prc = cc.pivot_table(index="date", columns="ticker", values="prc").reindex(index=idx, columns=U)

        k = pd.read_parquet(_need(CLOSE_SIZED, "fetch_alpaca_auction_history.py --side close --sizes"))
        k["date"] = pd.to_datetime(k["date"])
        _assert_fit(k.set_index("date"))
        self.close6, self.closeM, self.close_dups = nyse_close_prints(k, idx, U)

        # the two evaluation sets' holdings paths (H only; no return is formed from them here)
        cap = MAX_GROSS_STRESS if MAX_GROSS_STRESS is not None else np.inf
        self.H = {}
        for lab, floor in (("WIDE", 0), ("deployed", None)):
            T, R = bf.build_targets(min_adv=floor)
            T, _ = bf.fit_only(T, R)
            H = bf.band_gross_capped(T, BAND_WIDTH, cap)
            _assert_fit(H)
            if not H.loc[WINDOW[0]:WINDOW[1]].index.equals(idx):
                raise Halt(f"{lab}: the holdings index differs from cef_prices' on the decision window")
            self.H[lab] = H
        self.adv = bf.build_panel(end=WINDOW[1])["adv"].reindex(columns=U)

    def trades(self, lab: str) -> pd.DataFrame:
        """Row s: |the trade decided at s-1|, which goes to the open of s."""
        return open_trades(self.H[lab]).loc[self.idx]


# =============================================================================
# sections
# =============================================================================

def sec_spec() -> dict:
    hr("[0] DG-C5-2: THE SPEC PIN, THE HARNESS CONSTANTS AND N")
    from scripts.cef import band_frontier as bf
    from scripts.cef import spec
    got = sha256_file(SPEC_FILE)
    print(f"sha256 {SPEC_FILE.relative_to(REPO)} = {got}")
    print(f"pinned                                   = {SPEC_SHA256}")
    vals = dict(spec_id=spec.SPEC_ID, band_width=spec.BAND_WIDTH, max_gross_stress=spec.MAX_GROSS_STRESS,
                z_window=spec.Z_WINDOW, min_adv_usd=spec.MIN_ADV_USD, min_names=spec.MIN_NAMES,
                vol_target=spec.VOL_TARGET, n_names=len(spec.UNIVERSE), capital_usd=spec.CAPITAL_USD,
                order_type=spec.ORDER_TYPE, MIN_PERIODS=bf.MIN_PERIODS, VOL_LOOKBACK=bf.VOL_LOOKBACK,
                SAMPLE_START=bf.SAMPLE_START)
    bad = {k: (vals[k], v) for k, v in SPEC_PIN.items() if vals[k] != v}
    print("values read through scripts/cef/spec.py and band_frontier:", vals)
    from ops.orient import trials
    n = trials()["counters"]["CEF"]["trials"]
    bar = float(np.sqrt(2 * np.log(n)))
    print(f"CEF counter (docs/RESEARCH_STATE.md, read through ops.orient.trials): N = {n}, "
          f"bar sqrt(2 ln N) = {bar:.3f}; the approval judges C5 at N = {N_APPROVED}")
    if got != SPEC_SHA256:
        raise Halt("DG-C5-2: the spec's sha256 differs from the pin; the trial returns to the team lead re-pinned")
    if bad:
        raise Halt(f"DG-C5-2: spec or harness values differ from the declaration: {bad}")
    if n != N_APPROVED:
        raise Halt(f"the CEF counter reads {n}, not the approved {N_APPROVED}")
    print("DG-C5-2: PASS")
    return dict(spec_sha256=got, values=vals, N=n, bar=round(bar, 3))


def sec_classes(D: Data) -> tuple[dict, list, list]:
    """DG-C5-1: the declared defect classes of §4.2, re-counted, with their halt rules."""
    hr("[1] DG-C5-1: THE OPENING PRINTS AND THE DECLARED PRICE RULE (§4.2), RE-COUNTED; agreement = |diff| <= $0.005 + 1e-6 (ruling 2)")
    a = D.open_raw
    fa = sorted(a["fetched_at_utc"].unique()) if "fetched_at_utc" in a.columns else ["(no stamp)"]
    print(f"opening-print cache: {len(a):,} rows, {a['date'].min().date()}..{a['date'].max().date()}, "
          f"fetched {fa[0]}{'' if len(fa) == 1 else ' .. ' + fa[-1]}")
    print("rows by exchange/condition:", a.groupby(["exchange", "condition"]).size().to_dict())
    O, Q, C = D.O, D.Q, D.C
    priced = C.notna()
    hasO, hasQ = O.notna() & priced, Q.notna() & priced
    n_pr = int(priced.sum().sum())
    nO = int(hasO.sum().sum())
    nQonly = int((hasQ & ~hasO).sum().sum())
    nnone = int((priced & O.isna() & Q.isna()).sum().sum())
    both = O.notna() & Q.notna()
    d2 = both & ((O - Q).abs() > TOL)
    out_rng = hasO & D.lo.notna() & ((O < D.lo - TOL) | (O > D.hi + TOL))
    eq_y = hasO & D.op_y.notna() & ((O - D.op_y).abs() <= TOL)
    eq_c = hasO & D.op_c.notna() & ((O - D.op_c).abs() <= TOL)
    d3 = hasO & D.op_y.notna() & D.op_c.notna() & ~eq_y & ~eq_c & out_rng
    flagged = out_rng & ~d3
    dup = a[a.exchange == "N"].duplicated(["date", "ticker", "condition"], keep=False)
    rows = [("panel name-days 2016-22 with a close", n_pr, REF_2026_10_13["panel_name_days"]),
            ("  with an NYSE 'O' print", nO, REF_2026_10_13["O"]),
            ("  'Q' only (no round-lot cross)", nQonly, REF_2026_10_13["Q_only"]),
            ("  neither", nnone, REF_2026_10_13["none"]),
            ("O and Q both present", int(both.sum().sum()), REF_2026_10_13["both_OQ"]),
            ("D-2: |O - Q| > $0.005 + 1e-6", int(d2.sum().sum()), REF_2026_10_13["D2"]),
            ("D-3: O off both consolidated opens AND outside the day's range", int(d3.sum().sum()),
             REF_2026_10_13["D3"]),
            ("D-4: two O (or Q) prints on one N name-day", int(dup.sum()), 0),
            ("flagged, NOT a defect: O outside the range, one consolidated open agreeing",
             int(flagged.sum().sum()), REF_2026_10_13["out_of_range_flagged"])]
    print(f"\n{'count':<72}{'today':>8}{'2026-10-13 [S]':>16}")
    for lab, v, r in rows:
        print(f"{lab:<72}{v:>8,}{r:>16,}")
    # the no-cross set of §4.2: D-1 (no O print), D-2, D-3 (D-4 raised in nyse_open_prints)
    no_cross = priced & (O.isna() | d2 | d3)
    halts, flags = [], []
    rec = dict(panel_name_days=n_pr, O=nO, Q_only=nQonly, none=nnone, both_OQ=int(both.sum().sum()),
               D2=int(d2.sum().sum()), D3_all=int(d3.sum().sum()), D4=int(dup.sum()),
               flagged_out_of_range=int(flagged.sum().sum()))
    if rec["both_OQ"] and rec["D2"] / rec["both_OQ"] > HALT["D2_both"]:
        halts.append(f"D-2: {rec['D2']} of {rec['both_OQ']} name-days with both O and Q (> 1%)")
    print(f"\n{'by evaluation set, decision window (a trade decided at s-1 fills at the open of s)':<72}")
    print(f"{'':<12}{'material':>10}{'D-1':>6}{'D-1 %':>8}{'D-1 notl %':>11}{'D-3':>6}{'D-3 %':>8}"
          f"{'D-5':>6}{'D-5 %':>8}{'no-cross':>10}   2026-10-13 [S]: material / D-1 / D-5")
    for lab in ("WIDE", "deployed"):
        tr = D.trades(lab)
        mat = tr >= MATERIAL
        nm = int(mat.sum().sum())
        d1 = mat & priced & O.isna()
        d1n = float(tr.where(d1, 0.0).sum().sum() / tr.where(mat, 0.0).sum().sum())
        d3m = mat & d3
        d5 = mat & C.isna()
        ncx = mat & (no_cross | C.isna())
        k = "wide" if lab == "WIDE" else "dep"
        print(f"{lab:<12}{nm:>10,}{int(d1.sum().sum()):>6}{d1.sum().sum() / nm:>8.2%}{d1n:>11.2%}"
              f"{int(d3m.sum().sum()):>6}{d3m.sum().sum() / nm:>8.2%}{int(d5.sum().sum()):>6}"
              f"{d5.sum().sum() / nm:>8.2%}{int(ncx.sum().sum()):>10}   "
              f"{REF_2026_10_13['mat_' + k]:,} / {REF_2026_10_13['D1_trades_' + k]} / {REF_2026_10_13['D5_' + k]}")
        rec[f"{lab}_material"] = nm
        rec[f"{lab}_D1"] = int(d1.sum().sum())
        rec[f"{lab}_D1_notional_share"] = round(d1n, 6)
        rec[f"{lab}_D3"] = int(d3m.sum().sum())
        rec[f"{lab}_D5"] = int(d5.sum().sum())
        if d1.sum().sum() / nm > HALT["D1_trades"] or d1n > HALT["D1_notional"]:
            halts.append(f"D-1 ({lab}): above 1% of material trade name-days or of traded notional")
        if d3m.sum().sum() / nm > HALT["D3_trades"]:
            halts.append(f"D-3 ({lab}): above 0.5% of material trade name-days")
        if d5.sum().sum() / nm > HALT["D5_trades"]:
            halts.append(f"D-5 ({lab}): above 0.1% of material trade name-days")
        for (d, t) in _cells(d1):
            flags.append(dict(date=str(d.date()), ticker=t, set=lab, kind="D-1 no O print on a material trade",
                              note="Q only" if Q.notna().at[d, t] else "no N print"))
        for (d, t) in _cells(d3m):
            flags.append(dict(date=str(d.date()), ticker=t, set=lab, kind="D-3 on a material trade", note=""))
        for (d, t) in _cells(d5):
            flags.append(dict(date=str(d.date()), ticker=t, set=lab, kind="D-5 no panel close", note=""))
    for (d, t) in _cells(flagged):
        flags.append(dict(date=str(d.date()), ticker=t, set="all", kind="flagged: O outside range, one open agrees",
                          note=f"O vs yfinance open agree: {bool(eq_y.at[d, t])}; vs CRSP openprc: {bool(eq_c.at[d, t])}"))
    print("\nhalt rules (§4.2):", "NONE FIRED" if not halts else "; ".join(halts))
    return rec, halts, flags


def _cells(mask: pd.DataFrame):
    s = mask.stack()
    s = s[s]
    return list(s.index)


def sec_other(D: Data, frz: dict) -> tuple[dict, list, list]:
    """§4.5: 'Any other defect found at Stage 0 halts the trial before any P&L ...
    for example a print at an impossible price, a session return over 50% in
    magnitude (the harness's own price filter), or a close that disagrees with
    both CRSP prc and the NYSE closing print.' Each example is tested on the
    trial's input copy. (c) uses the ruled tolerance (ruling 2: |diff| <= $0.005
    + 1e-6 agrees) and the declared class D-6 (ruling 1), which `freeze` applied
    and logged: after it, no close may be off both sources."""
    hr("[2] §4.5: DEFECTS OUTSIDE THE DECLARED CLASSES (any one halts before P&L), ON THE TRIAL'S INPUT COPY")
    O, C = D.O, D.C
    halts, flags = [], []
    nonpos = int(((O <= 0) | ~np.isfinite(O.fillna(1.0))).sum().sum())
    print(f"(a) opening prints at an impossible price (<= 0 or non-finite): {nonpos}")
    if nonpos:
        halts.append(f"§4.5(a): {nonpos} opening print(s) at an impossible price")
    rs = C / O - 1.0                                  # formed ONLY to test the filter; never summed
    big = rs.abs() >= 0.5
    print(f"(b) name-days with |C/O - 1| >= 50% (the harness's filter): {int(big.sum().sum())}; "
          "the five largest |C/O - 1| (information, not defects under the declared rule):")
    top = rs.abs().stack().sort_values(ascending=False).head(5)
    for (d, t), v in top.items():
        print(f"      {d.date()} {t}: {v:.2%}; O vs yfinance open agree {abs(O.at[d, t] - D.op_y.at[d, t]) <= TOL}, "
              f"vs CRSP openprc {abs(O.at[d, t] - D.op_c.at[d, t]) <= TOL}")
    if big.any().any():
        halts.append(f"§4.5(b): {int(big.sum().sum())} session return(s) of 50% or more")
    # (c) the close against CRSP prc and the NYSE closing print
    cp = D.closeM.combine_first(D.close6)             # M (official close) where published, else 6 (closing trade)
    prc = D.prc.abs()                                 # CRSP: a negative prc is a bid/ask midpoint (no closing trade)
    neg = int((D.prc < 0).sum().sum())
    avail = C.notna() & prc.notna() & cp.notna()
    off_both = avail & ((C - prc).abs() > TOL) & ((C - cp).abs() > TOL)
    print(f"(c) NYSE closing prints repeated at one price (counted, not defects): "
          f"{ {k: v for k, v in D.close_dups.items() if v} }")
    print(f"(c) D-6 (ruling 1), applied by `freeze` to the trial's input copy and logged there: {frz['d6_count']} "
          f"name-day(s), halt above {D6_HALT_N}. Value used: {frz['d6_value_rule']}. In cents, no price level, and no "
          "per-date CRSP difference (licensed data):")
    for r in frz["d6_log"]:
        print(f"      {r['date']} {r['ticker']}: {r['cls']}; close-NYSE({r['nyse_print']}) {r['close_minus_nyse_c']:+.2f}c "
              f"(CRSP detail in the gitignored log only); WIDE trade {r['WIDE_trade']}, deployed trade {r['deployed_trade']}")
        flags.append(dict(date=r["date"], ticker=r["ticker"], set="all", kind=f"{r['cls']} (freeze log)",
                          note=f"close-NYSE({r['nyse_print']}) {r['close_minus_nyse_c']:+.2f}c; CRSP detail not "
                               f"published (licensed); WIDE trade {r['WIDE_trade']}; deployed trade {r['deployed_trade']}"))
    print(f"(c) on the input copy, of {int(avail.sum().sum()):,} name-days with a close, CRSP prc and an NYSE print "
          f"(CRSP prc < 0: {neg}): closes off both by more than $0.005 + 1e-6: {int(off_both.sum().sum())}")
    if off_both.any().any():
        halts.append(f"§4.5(c): {int(off_both.sum().sum())} close(s) of the input copy off both CRSP and the NYSE print")
    if frz["d6_count"] > D6_HALT_N:
        halts.append(f"D-6: {frz['d6_count']} name-days, above the ruled {D6_HALT_N}")
    rec = dict(impossible_open=nonpos, session_ge_50pct=int(big.sum().sum()), d6=frz["d6_count"],
               close_off_both_after_d6=int(off_both.sum().sum()), crsp_prc_negative=neg)
    print("\nhalt rules (§4.5 and D-6):", "NONE FIRED" if not halts else "; ".join(halts))
    return rec, halts, flags


def sec_tests() -> dict:
    hr("[3] DG-C5-3: THE HARNESS EXTENSION'S TESTS (each also asserts failure against its wrong versions)")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "scripts/cef/tests/test_c5_harness.py",
                        "scripts/data/tests/test_auction_holdout_gate.py"], cwd=REPO, capture_output=True, text=True)
    last = [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1] if r.stdout.strip() else r.stderr[-300:]
    print(f"python3 -m pytest scripts/cef/tests/test_c5_harness.py scripts/data/tests/test_auction_holdout_gate.py"
          f" -> exit {r.returncode}: {last}")
    if r.returncode != 0:
        raise Halt("DG-C5-3: the harness extension's tests fail")
    return dict(pytest_exit=r.returncode, summary=last)


def sec_noop(frz: dict) -> dict:
    hr("[4] DG-C5-4: THE WIDE FLAG (AND THE DATA_DIR SWITCH) ARE NO-OPS WHEN ABSENT; THE FROZEN CUT IS EXACT")
    from scripts.cef import band_frontier as bf
    from scripts.cef.c5_feasibility import adv_floor
    # The pins were taken as the first and second call of a FRESH process: pickle's bytes
    # depend on the process's state (an earlier build_targets() call changes the first
    # hash), so the comparison is like for like only in a fresh interpreter.
    code = ("import sys, hashlib, pickle; sys.path.insert(0, '.');"
            "from scripts.cef.band_frontier import build_targets;"
            "print(hashlib.sha256(pickle.dumps(build_targets())).hexdigest());"
            "print(hashlib.sha256(pickle.dumps(build_targets())).hexdigest())")
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        raise Halt(f"DG-C5-4: the fresh-process hash failed: {r.stderr[-300:]}")
    h1, h2 = r.stdout.split()
    with adv_floor(0.0):
        a = bf.build_targets()
    b = bf.build_targets(min_adv=0)
    same_wide = all(x.equals(y) for x, y in zip(a, b))
    print(f"sha256(pickle.dumps(build_targets())) in a fresh process, first call {h1}\n  pre-edit pin             {NOOP_FIRST}")
    print(f"second call {h2}\n  pre-edit pin {NOOP_SECOND}")
    print(f"build_targets(min_adv=0) equals the feasibility script's adv_floor(0) build (frozen copy): {same_wide}")
    print(f"freeze: T, R and H rebuilt from the uncorrected frozen copy equal the live build cut at "
          f"{FIT_END.date()}: {frz['truncation_noop']}")
    if (h1, h2) != (NOOP_FIRST, NOOP_SECOND) or not same_wide or not all(frz["truncation_noop"].values()):
        raise Halt("DG-C5-4: build_targets() is not byte-identical with the arguments absent, WIDE differs, "
                   "or the frozen cut is not exact")
    print("DG-C5-4: PASS")
    return dict(first=h1, second=h2, wide_equals_feasibility=same_wide, truncation_noop=frz["truncation_noop"])


EXEC_FIT_LINES = REPO / "results" / "cef" / "exec_capacity" / "exec_capacity_output.txt"


def sec_quotes() -> dict:
    """DG-C5-5: rebuild the 2016-22 quote sample and reproduce the EXEC note's
    §6 fit-period block to the printed precision. The EXEC note's §5 breakeven
    (a P&L of the deployed book) is NOT recomputed at Stage 0, so the one line
    per horizon that divides by it is excluded from the comparison."""
    hr("[5] DG-C5-5: THE 2016-22 QUOTE SAMPLE (fetch --skip-recent), READ FROM THE FROZEN COPY")
    from scripts.cef import exec_capacity_open_cross as X
    if X.CACHE != F_EXEC or X.W4_CACHE != F_W4:
        raise Halt("sec_quotes must run inside frozen()")
    from scripts.cef.spec import UNIVERSE
    syms = sorted(UNIVERSE)
    days = X.load_days(eras=("fit",))
    fitA = X.fit_auction_rows(syms)
    fit_days = sorted(days)
    allA = fitA[fitA.date.isin(fit_days)]
    Xc = X.cross_tables(days, allA, syms)
    empty = pd.DataFrame(columns=["date", "ticker", "side", "x", "c", "p", "s", "t"])
    pc = X.prior_closes(days, empty, fitA)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        X.sec_cost(days, Xc, pc, {})
    mine = buf.getvalue()
    ref = EXEC_FIT_LINES.read_text()
    blk = lambda s: s[s.index("FIT: "):].splitlines()
    skip = lambda ln: ("of the deployed book's gross return" in ln) or not ln.strip() or ln.startswith("=")
    a = [ln for ln in blk(mine) if not skip(ln)]
    b = [ln for ln in blk(ref) if not skip(ln)][:len(a)]
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    print(f"sample: {len(fit_days)} sessions, every {X.FIT_SAMPLE_EVERY}th of {X.FIT_FIRST}..{X.FIT_END} "
          f"({fit_days[0]}..{fit_days[-1]})")
    print(f"the EXEC note's §6 FIT block ({EXEC_FIT_LINES.relative_to(REPO)}), {len(b)} lines, against today's "
          f"rebuild, {len(a)} lines: {len(diff)} differ")
    for ln in a:
        if "pooled" in ln or "signed mean" in ln or "STUB" in ln or "reference methods" in ln:
            print("   " + ln.strip())
    for x, y in diff[:10]:
        print(f"   DIFF today: {x.strip()}\n        note : {y.strip()}")
    if diff or len(a) != len(b):
        raise Halt("DG-C5-5: the rebuilt quote sample does not reproduce the EXEC note's §6 fit table")
    print("DG-C5-5: PASS (reproduced line for line, to the printed precision)")
    return dict(sessions=len(fit_days), lines_compared=len(a), lines_differing=len(diff))


def sec_crsp(D: Data) -> dict:
    hr("[6] DG-C5-8: CRSP openprc / prc FOR THE R-D4 FACTORS OVER THE DECISION WINDOW")
    out, bad = {}, []
    for t in ("HYG", "IEF", "MUB", "BKLN"):
        x = D.crsp[D.crsp.ticker == t].set_index("date").reindex(D.idx)
        miss = int(((x.openprc <= 0) | x.openprc.isna() | x.prc.isna() | (x.prc <= 0) | x.ret.isna()).sum())
        out[t] = miss
        print(f"{t}: {len(D.idx)} window sessions, {miss} without a positive openprc, a positive prc and a ret")
        if miss:
            bad.append(t)
    if bad:
        raise Halt(f"DG-C5-8: CRSP does not cover the decision window for {bad}")
    print("DG-C5-8: PASS")
    return out


def sec_turnover(D: Data) -> dict:
    hr("[7] TURNOVER: ONE HOLDINGS PATH, TWO FILLS (H2 by construction)")
    out = {}
    for lab, H in D.H.items():
        turn = H.diff().abs().sum(axis=1).fillna(0.0).loc[D.idx].mean() * 252   # evaluate()'s `turn` line, no P&L
        out[lab] = round(float(turn), 4)
        print(f"{lab}: one-way turnover {turn:.2f}/yr over the decision window, the SAME series for the MOC "
              "and the opening-auction fill (gap 0% against H2's 5%)")
    return out


def sec_hashes(frz: dict) -> dict:
    hr("[8] THE FROZEN INPUTS: SHA-256 VERIFIED AGAINST results/cef/c5/c5_frozen_inputs_2026-10-14.json")
    print(f"{len(frz['files'])} files under {frz['root']}/, every one re-hashed before this stage read it and equal "
          "to the committed record (verify_frozen); the panels and caches outside it were not read")
    for n, h in sorted(frz["files"].items()):
        if not n.startswith("exec/days/"):
            print(f"{h}  {n}")
    print(f"{frz['exec_days_combined_sha256']}  exec/days/<126 session files> (combined)")
    print(f"{sha256_file(SPEC_FILE)}  {SPEC_FILE.relative_to(REPO)} (tracked; pinned by DG-C5-2)")
    return dict(n_files=len(frz["files"]), record=str(FREEZE_RECORD.relative_to(REPO)))


# =============================================================================
# main
# =============================================================================

def stage0() -> tuple[dict, list]:
    halts, flags, rec = [], [], dict(stamp=STAMP, stage="0 (amended, frozen inputs)")
    print(f"C5 (CEF trial 51) STAGE 0 UNDER THE 2026-10-14 AMENDMENT, run {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M}Z. "
          "Counts, gates and hashes only; no return is combined into a P&L. Every input is the frozen copy.")
    frz = verify_frozen()
    rec["spec"] = sec_spec()
    with frozen():
        D = Data()
        print(f"\nfrozen cef_prices last date {D.prices_last.date()}. Decision window "
              f"{WINDOW[0].date()}..{WINDOW[1].date()}: {len(D.idx)} sessions.")
        r, h, f = sec_classes(D)
        rec["classes"], halts, flags = r, halts + h, flags + f
        r, h, f = sec_other(D, frz)
        rec["other_defects"], halts, flags = r, halts + h, flags + f
        for key, fn in (("tests", sec_tests), ("noop", lambda: sec_noop(frz)), ("quotes", sec_quotes)):
            try:
                rec[key] = fn()
            except Halt as e:
                halts.append(str(e))
                rec[key] = dict(halt=str(e))
        try:
            rec["crsp"] = sec_crsp(D)
        except Halt as e:
            halts.append(str(e))
        rec["turnover"] = sec_turnover(D)
        rec["hashes"] = sec_hashes(frz)
    rec["halts"] = halts
    rec["verdict"] = "HALT" if halts else "PASS"
    hr("STAGE 0 VERDICT")
    if halts:
        print("HALT before any P&L (PREREG_C5 §4.2, §4.5, §13 and the 2026-10-14 amendment). No statistic of C5 has")
        print("been computed. The case goes to the team lead; no rule is edited to make a count pass.")
        for x in halts:
            print(f"  - {x}")
    else:
        print("PASS: every Stage 0 gate cleared on the frozen inputs. STOP: the team lead reviews the amendment")
        print("before Stage 1, and no stage after 0 is implemented here.")
    return rec, flags


# =============================================================================
# THE FIT: stages 1-7 of §13, on the frozen inputs (team lead's go, 2026-10-14)
# =============================================================================
# Every number below is computed on the frozen copy, after verify_frozen() and
# after the amended Stage 0 record says PASS. The verdict is the FIRST failing
# rule in §13's order (1, 2a, 2b, 2c, 3, 4, 5); stage 6 only labels; every
# statistic is computed and printed whatever the verdict. Nothing here reads a
# date after 2022-12-30.

FIT_VERDICT = OUT_DIR / "C5_FIT_VERDICT.json"
FIT_CACHE = OUT_DIR / "_cache_c5_fit"                # gitignored: the daily series, for stage 8
STAGE0_AMENDED = OUT_DIR / f"c5_stage0_amended_record_{STAMP}.json"
NW_L, NW_L2 = 21, 5                                  # §8
BOOT = dict(mean_block=21, reps=10_000, seed=20261013)   # §8
SHUFFLE = dict(block=21, draws=1_000, seed=20261013)     # §9 2c, amendment ruling 3 item 3
COSTS = (5, 15, 30)
FACTORS = ("HYG", "IEF", "MUB", "BKLN")
LATE_ET_MIN = 9 * 60 + 35                            # §11 R-LATE: O printed after 09:35 ET
CAPITALS = (100_000.0, 1_000_000.0, 10_000_000.0)    # §11 capacity


def gstats(g: pd.Series, turn_yr: float | None = None) -> dict:
    """Moments of a daily gain series on its own window: zeros included (§5)."""
    from scripts.cef.w4_artifacts import nw_auto_lag, nw_t
    g = g.astype(float)
    m, sd = g.mean(), g.std(ddof=1)
    lag = nw_auto_lag(g)
    out = dict(n=len(g), mean_bp_yr=m * 252 * 1e4, sd_bp_day=sd * 1e4,
               sr=m / sd * np.sqrt(252) if sd > 0 else np.nan,
               t21=nw_t(g, lags=NW_L), t5=nw_t(g, lags=NW_L2), auto_lag=lag, t_auto=nw_t(g, lags=lag))
    if turn_yr:
        out["bp_per_turn"] = m * 252 / turn_yr * 1e4
    return out


def fmt_g(lab: str, d: dict) -> str:
    x = (f"{lab:<46} mean {d['mean_bp_yr']:+8.1f}bp/yr  SR {d['sr']:+6.2f}  t(NW21) {d['t21']:+6.2f}  "
         f"t(NW5) {d['t5']:+6.2f}  t(NW auto L={d['auto_lag']}) {d['t_auto']:+6.2f}")
    return x + (f"  per unit turnover {d['bp_per_turn']:+6.2f}bp" if "bp_per_turn" in d else "")


class FitData:
    """The frozen inputs as frames on the holdings index (2005-01-03 .. 2022-12-30)."""

    def __init__(self):
        from scripts.cef import band_frontier as bf
        from scripts.cef.c5_feasibility import nyse_open_prints
        from scripts.cef.spec import UNIVERSE
        from scripts.cef.w4_artifacts import _assert_fit
        if bf.DATA_DIR != F_CEF:
            raise Halt("FitData() must be built inside frozen()")
        U = self.U = list(UNIVERSE)
        self.T = {}
        self.H = {}
        Rs = []
        for lab, floor in (("WIDE", 0), ("deployed", None)):
            T, R, H = _holdings(floor)
            self.T[lab], self.H[lab] = T, H
            Rs.append(R)
        if not Rs[0].equals(Rs[1]):
            raise Halt("the two sets' return frames differ; they must share one R")
        self.R = Rs[0]
        self.Rt = bf.total_returns(self.R)               # H15: the deployed leg's returns
        idx = self.idx = self.H["WIDE"].index
        _assert_fit(self.Rt, self.H["WIDE"], self.H["deployed"])
        W = self.W = idx[(idx >= WINDOW[0]) & (idx <= WINDOW[1])]
        if len(W) != WINDOW_SESSIONS or idx.get_loc(W[0]) < 2:
            raise Halt("the decision window is not the declared 1,762 sessions after the first two rows")
        P = pd.read_parquet(F_CEF / "cef_prices.parquet")
        P["date"] = pd.to_datetime(P["date"])
        pv = lambda c: P.pivot_table(index="date", columns="ticker", values=c).sort_index().reindex(columns=U)
        call = pv("close")
        if not idx.isin(call.index).all():
            raise Halt("the holdings index has a session the price panel lacks")
        self.C = call.reindex(idx)                        # the panel close (the trial's input copy, D-6 applied)
        self.C_prev = call.shift(1).reindex(idx)          # the previous panel session's close, never forward-filled
        self.op_y = pv("open").reindex(idx)
        self.hi, self.lo = pv("high").reindex(idx), pv("low").reindex(idx)
        a = pd.read_parquet(OPEN_PRINTS)
        a["date"] = pd.to_datetime(a["date"])
        self.O_raw, self.Q = nyse_open_prints(a, idx, U)
        on = a[(a.exchange == "N") & (a.condition == "O")].copy()
        tod = pd.to_datetime(on["t"], utc=True, format="ISO8601").dt.tz_convert("America/New_York")
        on["et_min"] = tod.dt.hour * 60 + tod.dt.minute + tod.dt.second / 60
        self.O_min = on.pivot(index="date", columns="ticker", values="et_min").reindex(index=idx, columns=U)
        c = pd.read_parquet(CRSP)
        c["date"] = pd.to_datetime(c["date"])
        self.crsp = c
        cc = c[c.ticker.isin(U)]
        self.op_c = cc.pivot_table(index="date", columns="ticker", values="openprc").reindex(index=idx, columns=U)
        self.op_c = self.op_c.where(self.op_c > 0)
        k = pd.read_parquet(CLOSE_SIZED)
        k["date"] = pd.to_datetime(k["date"])
        self.close6, self.closeM, _ = nyse_close_prints(k, idx, U)
        # §4.2's classes with ruling 2's tolerance: D-2 and D-3 are no-cross (D-1 is a missing O already)
        O, Q = self.O_raw, self.Q
        hasO = O.notna() & self.C.notna()
        d2 = O.notna() & Q.notna() & ((O - Q).abs() > TOL)
        out_rng = hasO & self.lo.notna() & ((O < self.lo - TOL) | (O > self.hi + TOL))
        eq_y = hasO & self.op_y.notna() & ((O - self.op_y).abs() <= TOL)
        eq_c = hasO & self.op_c.notna() & ((O - self.op_c).abs() <= TOL)
        d3 = hasO & self.op_y.notna() & self.op_c.notna() & ~eq_y & ~eq_c & out_rng
        self.n_d2d3 = int((d2 | d3).sum().sum())
        self.O = O.where(~(d2 | d3))
        self.RS, self.no_cross = bf.session_returns(self.O, self.C)
        self.adv = bf.build_panel()["adv"].reindex(index=idx, columns=U)
        N = pd.read_parquet(F_CEF / "cef_nav.parquet")
        N["date"] = pd.to_datetime(N["date"])
        self.nav = N.pivot_table(index="date", columns="ticker", values="nav").sort_index().reindex(columns=U)
        dist = pd.read_parquet(F_CEF / "cef_distributions.parquet")
        dist["ex_date"] = pd.to_datetime(dist["ex_date"])
        self.ex = (dist.groupby(["ex_date", "ticker"]).size().unstack().reindex(index=idx, columns=U).notna())
        self.y = bf.distribution_yield(idx, U).reindex_like(self.C)          # D / C[s-1] on ex-dates
        self.k = bf.split_factor(idx, U).reindex_like(self.C)
        self.e = {lab: bf.evaluate(self.H[lab], self.Rt) for lab in self.H}

    def gain(self, lab="WIDE", RS=None, H=None) -> pd.Series:
        from scripts.cef.band_frontier import open_fill_gain
        return open_fill_gain(self.H[lab] if H is None else H, self.RS if RS is None else RS)

    def turn_yr(self, lab="WIDE", lo=None, hi=None) -> float:
        t = self.e[lab]["turn_series"]
        return float(t.loc[lo or self.W[0]:hi or self.W[-1]].mean() * 252)


def stage1(F: FitData) -> dict:
    hr("STAGE 1: THE GAIN G (WIDE) OVER THE DECISION WINDOW 2016-01-04 .. 2022-12-30 (KILL D1 if mean <= 0 or t < 1.96)")
    from scripts.cef.w4_artifacts import block_boot_t, stationary_boot
    G = F.gain().loc[F.W]
    tw = F.turn_yr()
    st = gstats(G, tw)
    print(fmt_g("G, WIDE", st))
    nz = int((G != 0).sum())
    print(f"sessions {len(G)}, with a non-zero gain {nz}; WIDE turnover {tw:.2f}/yr (one H, both fills)")
    out = dict(stats=st, sessions_nonzero=nz, turn_yr=tw)
    for mb in (BOOT["mean_block"], 63):
        b = stationary_boot(G, mean_block=mb, reps=BOOT["reps"], seed=BOOT["seed"])
        ci = dict(mean_bp_yr=(b["lo_mean"] * 252e4, b["hi_mean"] * 252e4),
                  per_turn_bp=(b["lo_mean"] * 252 / tw * 1e4, b["hi_mean"] * 252 / tw * 1e4),
                  sr=(b["lo_sr"], b["hi_sr"]))
        out[f"stationary_boot_{mb}"] = ci
        print(f"stationary bootstrap (mean block {mb}, {BOOT['reps']:,} resamples, seed {BOOT['seed']}): 95% CI "
              f"mean {ci['mean_bp_yr'][0]:+.1f} .. {ci['mean_bp_yr'][1]:+.1f}bp/yr; per unit turnover "
              f"{ci['per_turn_bp'][0]:+.2f} .. {ci['per_turn_bp'][1]:+.2f}bp; Sharpe {ci['sr'][0]:+.2f} .. {ci['sr'][1]:+.2f}")
    t_b, lo_b, hi_b = block_boot_t(G, block=BOOT["mean_block"], reps=BOOT["reps"], seed=BOOT["seed"])
    out["moving_block_t"] = t_b
    print(f"moving-block bootstrap (w4_artifacts.block_boot_t, block 21, 10,000, seed 20261013): t {t_b:+.2f}, "
          f"95% CI of the mean {lo_b * 252e4:+.1f} .. {hi_b * 252e4:+.1f}bp/yr")
    ok = st["mean_bp_yr"] > 0 and st["t21"] >= 1.96
    out["pass"] = bool(ok)
    print(f"STAGE 1: {'PASS' if ok else 'KILL D1'} (mean {'>' if st['mean_bp_yr'] > 0 else '<='} 0, NW t(L=21) "
          f"{st['t21']:.2f} {'>=' if st['t21'] >= 1.96 else '<'} 1.96)")
    return out


def stage2(F: FitData, G: pd.Series) -> dict:
    from scripts.cef.band_frontier import open_fill_gain
    from scripts.cef.w4_artifacts import nw_t
    hr("STAGE 2: CONTROLS (§9) -- 2a stale-open stratum, 2b lagged-signal placebo, 2c shuffled-trade placebo")
    out = {}
    W = F.W
    # 2a: moved <=> |O - C[s-1]| > $0.005 + 1e-6 (ruling 2); no prior close -> not moved (ruling 3 item 4)
    moved = F.O.notna() & F.C_prev.notna() & ((F.O - F.C_prev).abs() > TOL)
    trades = open_fill_gain(F.H["WIDE"], pd.DataFrame(1.0, index=F.idx, columns=F.U), by_name=True).abs()
    tw = trades.loc[W] > 1e-12
    cross = F.O.notna().loc[W] & F.C.notna().loc[W]
    noprev = int((tw & cross & F.C_prev.isna().loc[W]).sum().sum())
    Gm = F.gain(RS=F.RS.where(moved, 0.0)).loc[W]
    st = gstats(Gm, F.turn_yr())
    share_nd = float((tw & cross & moved.loc[W]).sum().sum() / (tw & cross).sum().sum())
    print(fmt_g("2a G on moved-open name-days", st))
    print(f"   moved name-days: {share_nd:.1%} of trade name-days with a cross; trade name-days with a cross "
          f"and no prior close (not moved, ruling 3 item 4): {noprev}; stratum's share of G's mean: "
          f"{Gm.mean() / G.mean():.1%}" if G.mean() != 0 else "")
    ok_a = st["mean_bp_yr"] > 0
    out["2a"] = dict(stats=st, moved_share=share_nd, no_prev_close=noprev, pass_=bool(ok_a))
    print(f"   2a: {'PASS' if ok_a else 'KILL D1'} (stratum mean {'>' if ok_a else '<='} 0)")
    # 2b: the open fill applied to the book decided a day earlier
    Hl = F.H["WIDE"].shift(1).fillna(0.0)
    Gl = F.gain(H=Hl).loc[W]
    sl = gstats(Gl, F.turn_yr())
    d = G - Gl
    print(fmt_g("2b G_lag = sum (H[s-2]-H[s-3]) rS[s]", sl))
    print(f"   paired G - G_lag: mean {d.mean() * 252e4:+.1f}bp/yr, NW t(L=21) {nw_t(d, lags=NW_L):+.2f}; "
          f"G_lag / G = {Gl.mean() / G.mean():.2f}" if G.mean() != 0 else "")
    ok_b = Gl.mean() < G.mean()
    out["2b"] = dict(stats=sl, diff_bp_yr=d.mean() * 252e4, diff_t21=nw_t(d, lags=NW_L), pass_=bool(ok_b))
    print(f"   2b: {'PASS' if ok_b else 'KILL D1'} (mean G_lag {'<' if ok_b else '>='} mean G)")
    # 2c: block-permuted trade rows against fixed session returns
    TM = open_fill_gain(F.H["WIDE"], pd.DataFrame(1.0, index=F.idx, columns=F.U), by_name=True).loc[W].values
    RSW = F.RS.loc[W].values
    n = len(W)
    blocks = [np.arange(a, min(a + SHUFFLE["block"], n)) for a in range(0, n, SHUFFLE["block"])]
    rng = np.random.default_rng(SHUFFLE["seed"])
    means = np.empty(SHUFFLE["draws"])
    for i in range(SHUFFLE["draws"]):
        rows = np.concatenate([blocks[j] for j in rng.permutation(len(blocks))])
        means[i] = (TM[rows] * RSW).sum(axis=1).mean()
    p95 = float(np.percentile(means, 95))
    rank = float((means < G.mean()).mean())
    ok_c = G.mean() > p95
    print(f"2c shuffled-trade placebo: {len(blocks)} blocks ({len(blocks) - 1} of {SHUFFLE['block']}, last "
          f"{len(blocks[-1])}), {SHUFFLE['draws']:,} draws, seed {SHUFFLE['seed']}: placebo mean "
          f"{means.mean() * 252e4:+.1f}bp/yr, 95th percentile {p95 * 252e4:+.1f}bp/yr; G {G.mean() * 252e4:+.1f}bp/yr "
          f"exceeds {rank:.1%} of draws")
    out["2c"] = dict(placebo_mean_bp_yr=means.mean() * 252e4, p95_bp_yr=p95 * 252e4, g_rank=rank, pass_=bool(ok_c))
    print(f"   2c: {'PASS' if ok_c else 'KILL D1'} (mean G {'>' if ok_c else '<='} the placebo's 95th percentile)")
    np.save(FIT_CACHE / "shuffle_means.npy", means)
    out["pass"] = bool(ok_a and ok_b and ok_c)
    out["first_fail"] = next((k for k, v in (("2a", ok_a), ("2b", ok_b), ("2c", ok_c)) if not v), None)
    return out


def factor_frames(F: FitData) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Session (open -> close) and lagged close-to-close factor returns on the window
    (amendment ruling 3 item 2). ETFs: CRSP openprc -> prc, and CRSP `ret` lagged one
    session. The 13 names: the trial's own O print -> close, equal-weighted over names
    with a cross; total returns (harness) lagged, over names with a close on s and s-1.
    Returns (session, lagged, the CRSP-based 13-name session leg for the beside row)."""
    W, c = F.W, F.crsp
    sess, lag = {}, {}
    for t in FACTORS:
        x = c[c.ticker == t].set_index("date").reindex(F.idx)
        sess[t] = (x.prc / x.openprc - 1.0).loc[W]
        lag[t] = x.ret.shift(1).loc[W]
    rs_raw = (F.C / F.O - 1.0)                       # NaN on no-cross name-days: excluded from the mean, not zeroed
    sess["CEF13"] = rs_raw.mean(axis=1).loc[W]
    ok = F.C.notna() & F.C_prev.notna()
    lag["CEF13"] = F.Rt.where(ok).mean(axis=1).shift(1).loc[W]
    S, L = pd.DataFrame(sess), pd.DataFrame(lag)
    prc13 = c[c.ticker.isin(F.U)].pivot_table(index="date", columns="ticker", values="prc").reindex(index=F.idx, columns=F.U)
    crsp13 = (prc13.abs() / F.op_c - 1.0).mean(axis=1).loc[W]
    for nm, fr in (("session", S), ("lagged", L)):
        if fr.isna().any().any():
            raise Halt(f"R-D4: the {nm} factor frame has {int(fr.isna().sum().sum())} missing values on the window")
    return S, L, crsp13


def regress(y: pd.Series, X: pd.DataFrame) -> dict:
    import statsmodels.api as sm
    Xc = sm.add_constant(X, has_constant="add")
    m = sm.OLS(y.values, Xc.values).fit(cov_type="HAC", cov_kwds={"maxlags": NW_L})
    names = list(Xc.columns)
    b = dict(zip(names, m.params))
    V = pd.DataFrame(m.cov_params(), index=names, columns=names)
    return dict(alpha_bp_yr=b["const"] * 252e4, alpha_t=b["const"] / np.sqrt(V.at["const", "const"]),
                b=b, V=V, r2=float(m.rsquared), n=int(m.nobs))


def stage3(F: FitData, G: pd.Series) -> dict:
    hr("STAGE 3: R-D4 (§10) -- G on HYG, IEF, MUB, BKLN and the 13 names' session returns, each with its "
       "one-session-lagged close-to-close return (Dimson, betas summed); HAC maxlags 21")
    S, L, crsp13 = factor_frames(F)
    X = pd.concat([S.add_suffix("_s"), L.add_suffix("_l")], axis=1)
    r = regress(G, X)
    summed = {}
    for f in S.columns:
        a, b = f"{f}_s", f"{f}_l"
        v = r["V"].at[a, a] + r["V"].at[b, b] + 2 * r["V"].at[a, b]
        summed[f] = (r["b"][a] + r["b"][b], (r["b"][a] + r["b"][b]) / np.sqrt(v))
    print(f"alpha {r['alpha_bp_yr']:+.1f}bp/yr, t {r['alpha_t']:+.2f}; R^2 {r['r2']:.4f}; n {r['n']}")
    for f, (bb, tt) in summed.items():
        print(f"   summed beta {f:<6} {bb:+.4f} (t {tt:+.2f}); session {r['b'][f + '_s']:+.4f}, lagged {r['b'][f + '_l']:+.4f}")
    ok = r["alpha_t"] >= 3.0 and all(abs(bb) <= 0.10 for bb, _ in summed.values())
    out = dict(alpha_bp_yr=r["alpha_bp_yr"], alpha_t=r["alpha_t"], r2=r["r2"],
               summed_beta={f: dict(beta=bb, t=tt) for f, (bb, tt) in summed.items()}, pass_=bool(ok))
    print(f"STAGE 3: {'PASS' if ok else 'KILL D4'} (alpha t {r['alpha_t']:.2f} {'>=' if r['alpha_t'] >= 3 else '<'} 3.0; "
          f"max |summed beta| {max(abs(bb) for bb, _ in summed.values()):.4f} vs 0.10)")
    r0 = regress(G, S)
    out["R0"] = dict(alpha_bp_yr=r0["alpha_bp_yr"], alpha_t=r0["alpha_t"], r2=r0["r2"],
                     beta={f: r0["b"][f] for f in S.columns})
    print(f"R-0 (contemporaneous only, reported): alpha {r0['alpha_bp_yr']:+.1f}bp/yr t {r0['alpha_t']:+.2f}; "
          + ", ".join(f"{f} {r0['b'][f]:+.4f}" for f in S.columns))
    S2 = S.assign(CEF13=crsp13)
    if S2.isna().any().any():
        print(f"beside (CRSP openprc -> prc for the 13 names): {int(S2.isna().sum().sum())} missing values; not run")
    else:
        rc = regress(G, pd.concat([S2.add_suffix("_s"), L.add_suffix("_l")], axis=1))
        out["beside_crsp13"] = dict(alpha_t=rc["alpha_t"],
                                    summed_CEF13=rc["b"]["CEF13_s"] + rc["b"]["CEF13_l"])
        print(f"beside, never deciding (13 names' session leg on CRSP openprc -> prc): alpha t {rc['alpha_t']:+.2f}, "
              f"summed CEF13 beta {out['beside_crsp13']['summed_CEF13']:+.4f}")
    for lab in ("WIDE", "deployed"):
        pb = F.e[lab]["pnl"].loc[F.W]
        rb = regress(G, pb.rename("book").to_frame())
        out[f"R_BOOK_{lab}"] = dict(beta=rb["b"]["book"], alpha_t=rb["alpha_t"], r2=rb["r2"])
        print(f"R-BOOK (reported): G on the {lab} set's MOC-filled book P&L: beta {rb['b']['book']:+.4f}, "
              f"alpha t {rb['alpha_t']:+.2f}, R^2 {rb['r2']:.4f}")
    return out


def stage4(G: pd.Series, N: int) -> dict:
    from scripts.cef.validate import _dsr
    hr(f"STAGE 4: THE BAR -- validate._dsr on G at N = {N} (> 0.95), T = {len(G)}")
    obs = G.mean() / G.std(ddof=1) * np.sqrt(252)
    sk, ku = pd.Series(G.values).skew(), pd.Series(G.values).kurt() + 3.0    # exactly validate.py:342
    dsr, sr0, emax = _dsr(obs, len(G), sk, ku, N)
    yrs = len(G) / 252
    print(f"observed SR {obs:.3f}; skew {sk:+.3f}, kurtosis {ku:.2f}; null best-of-{N} SR {sr0:.3f}; "
          f"sqrt(2 ln N) {emax:.3f}; SR*sqrt(years) {obs * np.sqrt(yrs):.3f}")
    print(f"_dsr = {dsr:.4f}: {'PASS' if dsr > 0.95 else 'NEITHER (below the bar)'}")
    return dict(sr=obs, skew=sk, kurt=ku, dsr=dsr, sr0=sr0, bar=emax, sr_sqrt_years=obs * np.sqrt(yrs), pass_=bool(dsr > 0.95))


def stage5(F: FitData) -> dict:
    from scripts.cef.spec import MIN_ADV_USD
    hr("STAGE 5: THE EVALUATION-SET GUARDS (decision 1) -- both means must be > 0")
    Gd = F.gain("deployed").loc[F.W]
    sd = gstats(Gd, F.turn_yr("deployed"))
    above = (F.adv >= MIN_ADV_USD).shift(1).fillna(False).astype(bool)   # row s: the floor at the decision date s-1
    Ga = F.gain(RS=F.RS.where(above, 0.0)).loc[F.W]
    sa = gstats(Ga, F.turn_yr())
    print(fmt_g("deployed set's G", sd))
    print(fmt_g("WIDE's G on at-or-above-floor name-days", sa))
    ok = sd["mean_bp_yr"] > 0 and sa["mean_bp_yr"] > 0
    print(f"STAGE 5: {'PASS' if ok else 'KILL (evaluation-set guard)'}")
    return dict(deployed=sd, wide_above_floor=sa, pass_=bool(ok))


def quote_sample(F: FitData):
    from scripts.cef import exec_capacity_open_cross as X
    from scripts.cef.spec import UNIVERSE
    syms = sorted(UNIVERSE)
    days = X.load_days(eras=("fit",))
    fitA = X.fit_auction_rows(syms)
    Xc = X.cross_tables(days, fitA[fitA.date.isin(sorted(days))], syms)
    empty = pd.DataFrame(columns=["date", "ticker", "side", "x", "c", "p", "s", "t"])
    pc = X.prior_closes(days, empty, fitA)
    return days, X.cost_table(days, Xc, pc)


def stage6(F: FitData, G: pd.Series) -> dict:
    hr("STAGE 6: COST ROWS (§6) -- labels, never kills")
    from scripts.cef.band_frontier import open_fill_gain
    days, Ct = quote_sample(F)
    tw = F.turn_yr()
    gpt = G.mean() * 252 / tw * 1e4
    # s_open: mean paired (|open - mid| - |close - mid|), NBBO-referenced, the larger of h1 and h5 (H14: re-measured)
    s = {}
    for h in ("h1", "h5"):
        gh = Ct[(Ct.era == "fit") & (Ct.h == h)]
        cl = gh[(gh.side == "close") & (gh.method != "unmeasured")]
        op = gh[(gh.side == "open") & (gh.method == "nbbo")]
        pair = (cl.set_index(["date", "ticker"])["abs"].rename("c").to_frame()
                .join(op.set_index(["date", "ticker"])["abs"].rename("o"), how="inner"))
        s[h] = float((pair.o - pair.c).mean())
    s_open = max(s.values())
    print(f"s_open = max(h1 {s['h1']:+.2f}, h5 {s['h5']:+.2f}) = {s_open:+.2f}bp (the 2016-22 quote sample, 126 sessions)")
    # the signed dislocation of C5's own trades (amendment ruling 3 item 1)
    TM = open_fill_gain(F.H["WIDE"], pd.DataFrame(1.0, index=F.idx, columns=F.U), by_name=True)
    rows, unmeasured = [], 0
    for ds, rec in days.items():
        d = pd.Timestamp(ds)
        if d not in F.idx:
            raise Halt(f"quote sample day {ds} is not a holdings session")
        for t in F.U:
            dh = TM.at[d, t]
            if abs(dh) <= 1e-12 or not np.isfinite(F.O.at[d, t]):
                continue
            qo, qc = rec["q_open_p1"].get(t), rec["q_close_m1"].get(t)
            if qo is None or qc is None or not np.isfinite(F.C.at[d, t]):
                unmeasured += 1
                continue
            sg = np.sign(dh)
            do = sg * (F.O.at[d, t] - qo["mid"]) / qo["mid"]
            dc = sg * (F.C.at[d, t] - qc["mid"]) / qc["mid"]
            rows.append(dict(date=ds, ticker=t, dh=dh, signed_bp=(do - dc) * 1e4, hs_o=qo["hs_bp"], hs_c=qc["hs_bp"]))
    D = pd.DataFrame(rows)
    mat = D[D.dh.abs() >= MATERIAL]
    ew = float(mat.signed_bp.mean())
    tw_ = float((D.signed_bp * D.dh.abs()).sum() / D.dh.abs().sum())
    stub = int(((D.hs_o > 1000) | (D.hs_c > 1000)).sum())
    s_signed = max(ew, tw_, 0.0)
    print(f"signed dislocation of C5's own trades, open (vs mid 09:31) minus close (vs mid 15:59), bp: equal-weighted "
          f"over {len(mat)} material trade name-days {ew:+.2f}; |dH|-weighted over {len(D)} trade name-days {tw_:+.2f}; "
          f"unmeasured {unmeasured}; stub-like references (half-spread > 1,000bp, shown, not dropped) {stub}. "
          f"The row charges max(larger, 0) = {s_signed:.2f}bp")
    lab_open = gpt < s_open
    lab_signed = gpt < ew or gpt < tw_
    print(f"gain per unit of turnover {gpt:+.2f}bp against s_open {s_open:+.2f}bp: "
          f"{'D2-open' if lab_open else 'clears it'}; against the signed figures: {'D2-open (signed)' if lab_signed else 'clears both'}")
    # the dislocation split on the sample: print -> mid 09:35 and mid 09:35 -> close
    p1 = p2 = tot = 0.0
    nsplit = nmiss = 0
    for ds, rec in days.items():
        d = pd.Timestamp(ds)
        for t in F.U:
            dh = TM.at[d, t]
            if abs(dh) <= 1e-12 or not (np.isfinite(F.O.at[d, t]) and np.isfinite(F.C.at[d, t])):
                continue
            q = rec["q_postopen"].get(t)
            if q is None:
                nmiss += 1
                continue
            o, m, c = F.O.at[d, t], q["mid"], F.C.at[d, t]
            p1 += dh * (m / o - 1.0)
            p2 += dh * (c - m) / o
            tot += dh * (c / o - 1.0)
            nsplit += 1
    cap_bound = (tot <= 0) or (p1 > 0.5 * tot)
    print(f"dislocation split on the sample ({nsplit} trade name-days; {nmiss} without a 09:35 mid): gain "
          f"{tot * 1e4:+.2f}bp of capital in total = print->mid {p1 * 1e4:+.2f} + mid->close {p2 * 1e4:+.2f}; "
          f"label {'CAPACITY-BOUND' if cap_bound else 'none'} "
          f"({'the sample gain is <= 0 (ruling 3 item 6)' if tot <= 0 else f'print->mid share {p1 / tot:.0%}'})")
    # the C5 and deployed books (WIDE H), gross headline and the 5/15/30 grid, plus the surcharge rows
    rows_ = cost_rows(F, G, s_open, s_signed)
    return dict(s_open_h1=s["h1"], s_open_h5=s["h5"], s_open=s_open, gain_per_turn_bp=gpt,
                signed_ew_material=ew, signed_turnover_weighted=tw_, signed_n=len(D), signed_material_n=len(mat),
                signed_unmeasured=unmeasured, signed_stub=stub, s_signed=s_signed,
                label_D2_open=bool(lab_open), label_D2_open_signed=bool(lab_signed),
                split=dict(total_bp=tot * 1e4, print_mid_bp=p1 * 1e4, mid_close_bp=p2 * 1e4, n=nsplit, no_mid=nmiss),
                label_capacity_bound=bool(cap_bound), books=rows_)


def cost_rows(F: FitData, G: pd.Series, s_open: float, s_signed: float) -> dict:
    from scripts.cef.band_frontier import _stats
    print("\nBOOKS over the decision window, total returns, GROSS headline; net at 5/15/30bp per unit of one-way "
          "turnover beside it (real-money view, labelled). No borrow (its own table).")
    print(f"{'book':<46}{'grossSR':>8}{'ann%':>7}{'vol%':>7}{'turn/yr':>8}{'net@5':>8}{'net@15':>8}{'net@30':>8}{'flips?':>8}")
    out = {}
    for lab in ("WIDE", "deployed"):
        e = F.e[lab]
        gl = F.gain(lab)
        pd_, pc = e["pnl"].loc[F.W], (e["pnl"] + gl).loc[F.W]
        tt = e["turn_series"].loc[F.W]
        for nm, pnl, extra in ((f"{lab}: MOC fill (the deployed fill)", pd_, 0.0),
                               (f"{lab}: C5 open fill", pc, 0.0),
                               (f"{lab}: C5, + s_open {s_open:.2f}bp", pc, s_open),
                               (f"{lab}: C5, + signed {s_signed:.2f}bp", pc, s_signed)):
            st = _stats(pnl, tt)
            nets = [(st["ann"] - st["turn"] * (c + extra) / 1e4) / st["vol"] for c in COSTS]
            gross = (st["ann"] - st["turn"] * extra / 1e4) / st["vol"]
            flips = any(np.sign(x) != np.sign(gross) for x in nets)
            print(f"{nm:<46}{gross:8.2f}{st['ann'] * 100:7.2f}{st['vol'] * 100:7.2f}{st['turn']:8.2f}"
                  + "".join(f"{x:8.2f}" for x in nets) + f"{'YES' if flips else 'no':>8}")
            out[nm] = dict(gross=gross, ann_pct=st["ann"] * 100, vol_pct=st["vol"] * 100, turn=st["turn"],
                           net=dict(zip(COSTS, nets)), flips=bool(flips))
    print("The two fills share one H, so one turnover: the grid moves both by the same amount and cannot flip the "
          "comparison; it can only flip a book.")
    return out


def borrow_table(F: FitData) -> dict:
    from scripts.cef.band_frontier import borrow_charge
    hr("BORROW (H4), charged separately on the held short book H.shift(2); IDENTICAL for both fills")
    print("COUNTERFACTUAL: today's fee terms applied to 2016-22 history; not a historical cost.")
    probes = sorted((REPO / "results/ops/alpaca_probe").glob("*_cef.json"))
    tracked = [p for p in probes if subprocess.run(["git", "-C", str(REPO), "ls-files", "--error-unmatch", str(p)],
                                                    capture_output=True).returncode == 0]
    pr = json.loads(tracked[-1].read_text())["assets"]
    fee_a = pd.DataFrame({t: (0.0 if pr[t]["borrow_status"] == "easy_to_borrow" else np.nan) for t in F.U},
                         index=F.idx)
    fb = pd.read_parquet(F_CEF / "cef_borrow_history.parquet")
    fb["date"] = pd.to_datetime(fb["date"])
    fee_i = fb.pivot(index="date", columns="ticker", values="fee_rate_pct").reindex(index=F.idx, columns=F.U)
    out = {}
    print(f"(A) Alpaca's published live terms: easy-to-borrow pays no fee (REFERENCES §12l [V]); status from the latest "
          f"committed probe, {tracked[-1].name}: HTB with no published rate = a gap, never zero")
    print(f"(B) IBKR FEE_RATE panel [S], 2021-09-13 .. 2022-12-30 only (no fee data before it)")
    for lab in ("WIDE", "deployed"):
        for key, fee, lo in (("A", fee_a, F.W[0]), ("B", fee_i, pd.Timestamp("2021-09-13"))):
            ch = borrow_charge(F.H[lab], fee)
            sl = slice(lo, F.W[-1])
            sh, un = ch["short"].loc[sl], ch["uncovered"].loc[sl]
            cov = 1 - un.sum() / sh.sum() if sh.sum() > 0 else 1.0
            drag = ch["cost"].loc[sl].mean() * 252 * 100
            out[f"{lab}_{key}"] = dict(drag_pct_yr=drag, covered=cov, from_=str(pd.Timestamp(lo).date()))
            print(f"   {lab:<9} ({key}) from {pd.Timestamp(lo).date()}: drag {drag:.3f}%/yr, short book covered "
                  f"{cov:.1%}{'  <- lower bound (gaps not charged)' if cov < 0.999 else ''}")
    return out


def reported(F: FitData, G: pd.Series, N: int) -> dict:
    """Everything §9 and §11 report and never decide on."""
    from scripts.cef import band_frontier as bf
    from scripts.cef.band_frontier import evaluate, open_fill_gain
    from scripts.cef.validate import _dsr
    out = {}
    W = F.W
    hr("REPORTED, NEVER DECIDING (§9, §11)")
    # ---- where the return lands: the open -> close split
    ok_o = F.O.notna() & F.C_prev.notna() & F.C.notna()
    rO = (F.O * F.k / F.C_prev + F.y - 1.0).where(ok_o, F.Rt)   # no usable open: the whole day is "overnight"
    RSd = F.RS.where(ok_o, 0.0)
    print("[split] annualised means over the window, bp/yr of capital (WIDE H):")
    e = F.e["WIDE"]
    pnl_d = e["pnl"]
    ov = evaluate(F.H["WIDE"], rO)["pnl"]
    se = evaluate(F.H["WIDE"], RSd)["pnl"]
    gd = F.gain(RS=RSd)
    comp_d = pnl_d - ov - se
    pnl_c = pnl_d + G.reindex(pnl_d.index, fill_value=0.0)
    se_c = se + gd
    comp_c = pnl_c - ov - se_c
    nt = open_fill_gain(F.H["WIDE"], rO.fillna(0.0)).loc[W]
    f = lambda x: x.loc[W].mean() * 252e4
    sp = dict(deployed=dict(overnight=f(ov), session=f(se), compounding=f(comp_d), total=f(pnl_d)),
              C5=dict(overnight=f(ov), session=f(se_c), compounding=f(comp_c), total=f(pnl_c)),
              G=f(G.reindex(pnl_d.index, fill_value=0.0)), overnight_not_transactable=nt.mean() * 252e4)
    for k_ in ("deployed", "C5"):
        print(f"   {k_:<9} overnight H[s-2]rO {sp[k_]['overnight']:+8.1f}  session {sp[k_]['session']:+8.1f}  "
              f"compounding/ex-date residual {sp[k_]['compounding']:+7.1f}  = total {sp[k_]['total']:+8.1f}")
    print(f"   G {sp['G']:+.1f}; the overnight the decision cannot reach, sum dH[s-1] rO[s] (NOT TRANSACTABLE, "
          f"diagnostic): {sp['overnight_not_transactable']:+.1f}")
    out["split"] = sp
    # ---- decay profile
    dec = {}
    for k_ in range(1, 6):
        Hk = F.H["WIDE"].shift(k_ - 1).fillna(0.0)
        gk = gstats(F.gain(H=Hk).loc[W])
        dec[k_] = dict(mean_bp_yr=gk["mean_bp_yr"], t21=gk["t21"])
    print("[decay] sum (H[s-k]-H[s-k-1]) rS[s], bp/yr (t NW21): "
          + "; ".join(f"k={k_} {v['mean_bp_yr']:+.1f} ({v['t21']:+.2f})" for k_, v in dec.items()))
    out["decay"] = dec
    # ---- NAV freshness, months, ex-dates
    navm = (F.nav.shift(1) != F.nav.shift(2)) & F.nav.shift(1).notna() & F.nav.shift(2).notna()
    navm = navm.reindex(index=F.idx, columns=F.U).fillna(False).astype(bool)
    mth = pd.DataFrame(np.repeat(F.idx.month.values[:, None], len(F.U), axis=1), index=F.idx, columns=F.U)
    strata = {"NAV[s-1] moved": navm, "NAV[s-1] repeated": ~navm,
              "December fills": mth == 12, "Feb-Nov fills": (mth >= 2) & (mth <= 11),
              "January fills (in neither declared stratum)": mth == 1,
              "ex-date name-days": F.ex, "non-ex-date name-days": ~F.ex}
    out["strata"] = {}
    print("[strata] G restricted to the name-days of each stratum (zeros elsewhere):")
    for nm, m in strata.items():
        gs = gstats(F.gain(RS=F.RS.where(m, 0.0)).loc[W])
        out["strata"][nm] = dict(mean_bp_yr=gs["mean_bp_yr"], t21=gs["t21"], sr=gs["sr"])
        print(f"   {nm:<44} {gs['mean_bp_yr']:+8.1f}bp/yr  t {gs['t21']:+6.2f}")
    # ---- correlations
    out["corr"] = {lab: float(np.corrcoef(G.values, F.e[lab]["pnl"].loc[W].values)[0, 1]) for lab in ("WIDE", "deployed")}
    print(f"[corr] G with the MOC book's daily P&L: WIDE {out['corr']['WIDE']:+.3f}, deployed set {out['corr']['deployed']:+.3f}")
    # ---- eras (H5): 2016-19 ("the 2015-19 era from the print's start") and 2020-22
    print("[eras] G and the WIDE books, gross and net:")
    from scripts.cef.band_frontier import _stats
    era = {}
    for nm, lo, hi in (("2016-19 (2015-19 era from the print's start)", "2016-01-04", "2019-12-31"),
                       ("2020-22", "2020-01-01", "2022-12-30")):
        gs = gstats(G.loc[lo:hi], F.turn_yr(lo=pd.Timestamp(lo), hi=pd.Timestamp(hi)))
        bd = _stats(e["pnl"].loc[lo:hi], e["turn_series"].loc[lo:hi])
        bc = _stats((e["pnl"] + F.gain()).loc[lo:hi], e["turn_series"].loc[lo:hi])
        era[nm] = dict(G=gs, moc_sr=bd["sr"], c5_sr=bc["sr"], turn=bd["turn"], c5_nets=bc["nets"], moc_nets=bd["nets"])
        print(f"   {nm:<46} G {gs['mean_bp_yr']:+7.1f}bp/yr SR {gs['sr']:+5.2f} t {gs['t21']:+5.2f}; turnover "
              f"{bd['turn']:.1f}; MOC book SR {bd['sr']:.2f} (net 5/15/30 {', '.join(f'{x:.2f}' for x in bd['nets'])}); "
              f"C5 book SR {bc['sr']:.2f} (net {', '.join(f'{x:.2f}' for x in bc['nets'])})")
    tv = np.array([v["turn"] for v in era.values()])
    print(f"   era turnover sd/mean {tv.std() / tv.mean():.1%}")
    out["eras"] = era
    # ---- robustness rows
    rob = {}

    def row(nm, g, turn=None):
        st = gstats(g, turn)
        rob[nm] = st
        print("   " + fmt_g(nm, st))

    print("[robustness] (none of it rescues a failed headline)")
    first_half, second_half = W[:len(W) // 2], W[len(W) // 2:]
    row("first half of the window", G.loc[first_half])
    row("second half of the window", G.loc[second_half])
    # R-STALE0 is 2a's stratum (amendment ruling 3 item 4); R-LATE
    late = F.O_min > LATE_ET_MIN
    row("R-LATE: O after 09:35 ET as no-cross", F.gain(RS=F.RS.where(~late, 0.0)).loc[W], F.turn_yr())
    print(f"      (late O name-days in the window: {int(late.loc[W].sum().sum())})")
    # R-YF
    oy = F.op_y.where(F.op_y > 0)
    oy.loc[oy.index < WINDOW[0]] = np.nan              # the window only, as the print
    try:
        RSy, _ = bf.session_returns(oy, F.C)
        row("R-YF: the yfinance open", F.gain(RS=RSy).loc[W], F.turn_yr())
    except ValueError as x:
        print(f"   R-YF not computed: {x}")
    # R-CLOSE (amendment ruling 3 item 5): the 6-print day's official close; no 6 -> no cross
    cpx = F.closeM.combine_first(F.close6).where(F.close6.notna())
    both = F.closeM.notna() & F.close6.notna()
    m_ne_6 = int((both & ((F.closeM - F.close6).abs() > TOL)).sum().sum())
    RSc, _ = bf.session_returns(F.O, cpx)
    row("R-CLOSE: G on the NYSE closing print", F.gain(RS=RSc).loc[W], F.turn_yr())
    amt = (F.y * F.C_prev)                                # the distribution amount on its ex-date
    Rc = ((cpx * F.k + amt) / cpx.shift(1) - 1.0)
    miss = Rc.isna() & (F.C.notna())
    Rc0 = Rc.fillna(0.0)
    held = F.H["WIDE"].shift(2).abs()
    share = float((held.where(miss, 0.0).loc[W].sum().sum()) / held.loc[W].sum().sum())
    pc = evaluate(F.H["WIDE"], Rc0)["pnl"]
    stc = _stats(pc.loc[W], e["turn_series"].loc[W])
    stc5 = _stats((pc + F.gain(RS=RSc)).loc[W], e["turn_series"].loc[W])
    print(f"      R-CLOSE books (print-to-print total returns; a return needing a missing print is 0, held-weight "
          f"share {share:.2%}; M != 6 beyond tolerance on {m_ne_6} name-days): MOC SR {stc['sr']:.2f}, C5 SR {stc5['sr']:.2f}")
    rob["R-CLOSE books"] = dict(moc_sr=stc["sr"], c5_sr=stc5["sr"], missing_share=share, m_ne_6=m_ne_6)
    # R-DEP: the deciding stages on the deployed set
    print("   R-DEP (decision 1's alternative A), the deciding statistics on the deployed set:")
    Gd = F.gain("deployed").loc[W]
    sd = gstats(Gd, F.turn_yr("deployed"))
    dd = _dsr(sd["sr"], len(Gd), pd.Series(Gd.values).skew(), pd.Series(Gd.values).kurt() + 3.0, N)[0]
    moved = F.O.notna() & F.C_prev.notna() & ((F.O - F.C_prev).abs() > TOL)
    gm = F.gain("deployed", RS=F.RS.where(moved, 0.0)).loc[W].mean()
    gl = F.gain(H=F.H["deployed"].shift(1).fillna(0.0)).loc[W].mean()
    print(f"      G {sd['mean_bp_yr']:+.1f}bp/yr SR {sd['sr']:+.2f} t(NW21) {sd['t21']:+.2f} _dsr {dd:.4f}; moved-open "
          f"stratum {gm * 252e4:+.1f}bp/yr; lagged placebo {gl * 252e4:+.1f}bp/yr")
    rob["R-DEP"] = dict(stats=sd, dsr=dd, moved_bp_yr=gm * 252e4, lag_bp_yr=gl * 252e4)
    # R-PRE16: CRSP openprc from first decision + 2 sessions to 2015-12-31, and spliced
    for lab in ("WIDE", "deployed"):
        H = F.H[lab]
        first = H.index[(H.abs().sum(axis=1) > 0).to_numpy()].min()
        lo = H.index[H.index.get_loc(first) + 2]
        pre = (F.idx >= lo) & (F.idx < WINDOW[0])
        oc = F.op_c.where(pd.DataFrame(np.repeat(pre[:, None], len(F.U), axis=1), index=F.idx, columns=F.U))
        try:
            RSp, _ = bf.session_returns(oc, F.C)
        except ValueError as x:
            print(f"   R-PRE16 ({lab}) not computed: {x}")
            continue
        gp = F.gain(lab, RS=RSp).loc[F.idx[pre]]
        sp_ = gstats(gp)
        spl = pd.concat([gp, F.gain(lab).loc[W]])
        ss = gstats(spl)
        dsr_s = _dsr(ss["sr"], len(spl), pd.Series(spl.values).skew(), pd.Series(spl.values).kurt() + 3.0, N)[0]
        print(f"   R-PRE16 {lab} (CRSP openprc, a consolidated first price, not an auction print) {lo.date()}..2015-12-31: "
              f"G {sp_['mean_bp_yr']:+.1f}bp/yr SR {sp_['sr']:+.2f} t {sp_['t21']:+.2f}; spliced with the window "
              f"({len(spl)} sessions): SR {ss['sr']:+.2f} t {ss['t21']:+.2f} _dsr {dsr_s:.4f}")
        rob[f"R-PRE16 {lab}"] = dict(pre=sp_, spliced=ss, spliced_dsr=dsr_s, start=str(lo.date()))
    # leave one name out
    loo = {}
    for t in F.U:
        loo[t] = gstats(F.gain(RS=F.RS.assign(**{t: 0.0})).loc[W])["sr"]
    v = pd.Series(loo)
    print(f"   leave-one-name-out SR of G: min {v.min():+.2f} (without {v.idxmin()}), median {v.median():+.2f}, "
          f"max {v.max():+.2f} (without {v.idxmax()})")
    rob["LOO"] = loo
    out["robustness"] = rob
    # capacity: the opening cross against the closing cross, at $100k / $1m / $10m (the EXEC note's method)
    from scripts.cef import exec_capacity_open_cross as X
    from scripts.cef.spec import UNIVERSE
    fitA = X.fit_auction_rows(sorted(UNIVERSE))
    fitX = X.fit_cross_all(fitA, sorted(UNIVERSE))
    cap = {}
    print("[capacity] C5's (WIDE) trades as whole-share orders sized at the decision close, matched to their fill "
          "day's cross (round-lot crosses), participation = our shares / cross shares:")
    # H from two rows before the window: backtest_orders treats its first row as a build from flat,
    # and that build then fills before the window and is dropped with every other pre-window fill
    Hc = F.H["WIDE"].iloc[F.idx.get_loc(F.W[0]) - 2:]
    for k_ in CAPITALS:
        try:
            B = X.backtest_orders(Hc, F.C, k_)
        except ValueError as x:
            print(f"   capacity at ${k_:,.0f} not computed: {x}")
            continue
        B = B[(B.fill >= WINDOW[0]) & (B.fill <= WINDOW[1])].copy()
        B["fill"] = B.fill.dt.strftime("%Y-%m-%d")
        for side in ("open", "close"):
            M = X.participation(B.rename(columns={"fill": "date"}), fitX[fitX.side == side], on="date")
            rr = M[(M.kind == "round") & np.isfinite(M.part)]
            cap[f"{int(k_)}_{side}"] = dict(med=float(rr.part.median()), p90=float(rr.part.quantile(0.9)),
                                            wmed=float(X.weighted_median(rr.part, rr.notional)), n=len(rr))
            print(f"   ${k_ / 1e6:>5.1f}m {side:<5}: median {rr.part.median():7.2%}, notional-weighted median "
                  f"{X.weighted_median(rr.part, rr.notional):7.2%}, p90 {rr.part.quantile(0.9):7.2%} ({len(rr):,} orders)")
    out["capacity"] = cap
    return out


def fit() -> dict:
    """Stages 1-7 of §13 on the frozen inputs."""
    FIT_CACHE.mkdir(parents=True, exist_ok=True)
    print(f"C5 (CEF trial 51) THE FIT, run {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M}Z, on the frozen inputs. "
          "Decision window 2016-01-04 .. 2022-12-30; the holdout is not read.")
    frz = verify_frozen()
    s0 = json.loads(_need(STAGE0_AMENDED, "c5_open_auction.py stage0").read_text())
    if s0.get("verdict") != "PASS":
        raise Halt("the amended Stage 0 record does not say PASS")
    spec = sec_spec()
    N = spec["N"]
    rec = dict(stamp=STAMP, trial="C5, CEF trial 51", N=N, bar=spec["bar"], window=[str(WINDOW[0].date()),
               str(WINDOW[1].date())], frozen_record=str(FREEZE_RECORD.relative_to(REPO)),
               frozen_files=len(frz["files"]))
    with frozen():
        F = FitData()
        print(f"\nfrozen inputs verified ({len(frz['files'])} files); no-cross name-days from D-2/D-3 under ruling 2: "
              f"{F.n_d2d3}")
        G = F.gain().loc[F.W]
        G.to_frame("G").to_parquet(FIT_CACHE / "G_wide.parquet")
        rec["stage1"] = stage1(F)
        rec["stage2"] = stage2(F, G)
        rec["stage3"] = stage3(F, G)
        rec["stage4"] = stage4(G, N)
        rec["stage5"] = stage5(F)
        rec["stage6"] = stage6(F, G)
        rec["borrow"] = borrow_table(F)
        hr("BESIDE THE BAR, NEVER DECIDING (§8)")
        from scripts.cef.validate import _dsr
        from scripts.cef.w4_artifacts import nw_t
        pc = (F.e["WIDE"]["pnl"] + F.gain()).loc[F.W]
        src = pc.mean() / pc.std(ddof=1) * np.sqrt(252)
        d_c5 = _dsr(src, len(pc), pd.Series(pc.values).skew(), pd.Series(pc.values).kurt() + 3.0, N)[0]
        paired = pc - F.e["WIDE"]["pnl"].loc[F.W]
        print(f"_dsr of the C5 book's own gross series (decision 2's alternative): SR {src:.3f}, _dsr {d_c5:.4f}")
        print(f"paired t of C5 - MOC (NW21): {nw_t(paired, lags=NW_L):+.3f}; G's t {rec['stage1']['stats']['t21']:+.3f} "
              "(the same series)")
        rec["beside"] = dict(c5_book_sr=src, c5_book_dsr=d_c5, paired_t=nw_t(paired, lags=NW_L))
        rec["reported"] = reported(F, G, N)
    order = [("1", rec["stage1"]["pass"], "KILL D1 (stage 1: G not detectable)"),
             ("2", rec["stage2"]["pass"], f"KILL D1 (stage {rec['stage2']['first_fail']}: artefact control)"),
             ("3", rec["stage3"]["pass_"], "KILL D4 (stage 3: factor regression)"),
             ("4", rec["stage4"]["pass_"], "NEITHER (stage 4: below the _dsr bar)"),
             ("5", rec["stage5"]["pass_"], "KILL (stage 5: evaluation-set guard)")]
    fail = next(((st, v) for st, ok, v in order if not ok), None)
    labels = [x for x, on in (("D2-open", rec["stage6"]["label_D2_open"]),
                              ("D2-open (signed)", rec["stage6"]["label_D2_open_signed"]),
                              ("capacity-bound", rec["stage6"]["label_capacity_bound"])) if on]
    rec["verdict"] = fail[1] if fail else "FIT PASS (stages 1-5); the holdout (stage 8) decides the trial"
    rec["deciding_stage"] = fail[0] if fail else None
    rec["labels"] = labels
    hr("THE FIT VERDICT (stage 7: committed before the holdout is read)")
    print(rec["verdict"])
    print("stage results:", {st: ("pass" if ok else "FAIL") for st, ok, _ in order})
    print("stage-6 labels:", labels or "none")
    return rec


# =============================================================================
# STAGE 8: THE HOLDOUT, 2023-01-03 .. 2026-09-30 (opened once; it can kill, never rescue)
# =============================================================================
# The team lead's ruling of 2026-10-14 on the holdout's bad-close check (amendment line of
# 2026-10-15): the fit's D-6 rule, with the second source CRSP `prc` for 2023-24 and
# CEFConnect's close for 2025-26 (R2's CRSP ends 2024-12-31). Both sources must AGREE before a
# panel close is replaced; a single available source never replaces anything and is logged,
# not used. Same tolerance, same halt (more than 5 D-6 name-days). The holdout's inputs are
# frozen and hashed before G is formed on a single holdout date.

HOLD = (pd.Timestamp("2023-01-03"), pd.Timestamp("2026-09-30"))     # §7, fixed
HOLD_SESSIONS = 939                                                 # §7: 937 to 2026-09-28 + 2
H_STAMP = "2026-10-15"
H_FROZEN = OUT_DIR / "_cache_c5_holdout"                           # gitignored
H_RECORD = OUT_DIR / f"c5_holdout_inputs_{H_STAMP}.json"
H_RESULT = OUT_DIR / "C5_HOLDOUT_RESULT.json"
H_W4 = ("alpaca_opening_prints_holdout_2023_2026.parquet", "alpaca_closing_prints_holdout_2023_2026.parquet",
        "crsp_dsf_holdout_2023_2024.parquet")
CC_FILE = REPO / "results" / "cef" / "c5" / "_cache_cefconnect" / "cefconnect_closes.parquet"


def _fit_committed():
    from scripts.data.fetch_alpaca_auction_history import fit_verdict_committed
    ok, why = fit_verdict_committed()
    if not ok:
        raise Halt(f"the holdout stage refuses: C5's fit verdict is not committed ({why})")


def freeze_holdout() -> dict:
    """Freeze every holdout input with its sha256; apply the holdout bad-close rule to the
    holdout copy. The fit's frozen copy is reused for every row to 2022-12-30 (so H to 2022
    is the fit's H, which `holdout` asserts) and the live panel supplies 2023 .. 2026-09-30."""
    from scripts.cef.spec import UNIVERSE
    _fit_committed()
    U = list(UNIVERSE)
    halts = []
    hr(f"FREEZE THE HOLDOUT INPUTS into {H_FROZEN.relative_to(REPO)}/ (gitignored)")
    if H_FROZEN.exists():
        shutil.rmtree(H_FROZEN)
    for d in ("cef", "w4", "cc"):
        (H_FROZEN / d).mkdir(parents=True)
    out_last, cover = {}, {}
    for name in ("cef_prices", "cef_nav", "cef_distributions", "cef_splits"):
        col = "ex_date" if name in ("cef_distributions", "cef_splits") else "date"
        live = pd.read_parquet(LIVE_CEF / f"{name}.parquet")
        live = live[live.ticker.isin(U)].copy()
        ld = pd.to_datetime(live[col])
        out_last[name] = str(ld.max().date())
        fit_raw = pd.read_parquet(F_CEF_RAW / f"{name}.parquet") if (F_CEF_RAW / f"{name}.parquet").exists() else None
        old = live[ld <= FIT_END].reset_index(drop=True)
        if fit_raw is not None and name != "cef_splits":
            a = old.sort_values([col, "ticker"]).reset_index(drop=True)
            b = fit_raw.sort_values([col, "ticker"]).reset_index(drop=True)
            if not a.equals(b):
                raise Halt(f"{name}: the live rows to {FIT_END.date()} differ from the fit's frozen raw copy")
        fit_in = pd.read_parquet(F_CEF / f"{name}.parquet")          # the fit's input copy (D-6 applied)
        new = live[(ld > FIT_END) & (ld <= HOLD[1])]
        pd.concat([fit_in, new], ignore_index=True).to_parquet(H_FROZEN / "cef" / f"{name}.parquet", index=False)
    print("live panels' last dates:", out_last, "; rows to 2022-12-30 equal the fit's frozen raw copy, and the "
          "fit's input copy (with its D-6) is reused for them")
    P = pd.read_parquet(H_FROZEN / "cef" / "cef_prices.parquet")
    P["date"] = pd.to_datetime(P["date"])
    N = pd.read_parquet(H_FROZEN / "cef" / "cef_nav.parquet")
    N["date"] = pd.to_datetime(N["date"])
    cover = dict(prices_on_2026_09_30=int((P.date == HOLD[1]).sum()),
                 navs_on_2026_09_29=int((N.date == pd.Timestamp("2026-09-29")).sum()))
    print(f"DG-C5-7: names with a price on 2026-09-30: {cover['prices_on_2026_09_30']} of 13; with a NAV on "
          f"2026-09-29: {cover['navs_on_2026_09_29']} of 13")
    if cover["prices_on_2026_09_30"] < 13 or cover["navs_on_2026_09_29"] < 13:
        halts.append("DG-C5-7: the panels do not reach the fixed holdout end for every name")
    for f in H_W4:
        shutil.copy2(_need(LIVE_W4 / f, "the --holdout fetches"), H_FROZEN / "w4" / f)
    cc = pd.read_parquet(_need(CC_FILE, "python3 scripts/data/fetch_cefconnect_closes.py"))
    cc = cc[(cc.date >= pd.Timestamp("2025-01-01")) & (cc.date <= HOLD[1])]
    cc.to_parquet(H_FROZEN / "cc" / "cefconnect_closes_2025_2026.parquet", index=False)

    # ---- the bad-close check on the holdout window, before anything else reads the copy
    hr("THE HOLDOUT BAD-CLOSE CHECK (ruling of 2026-10-14): two agreeing sources replace; one alone never does")
    C = P.pivot_table(index="date", columns="ticker", values="close").sort_index().reindex(columns=U)
    hidx = C.index[(C.index >= HOLD[0]) & (C.index <= HOLD[1])]
    if len(hidx) != HOLD_SESSIONS:
        halts.append(f"the holdout has {len(hidx)} sessions in the price panel, not {HOLD_SESSIONS}")
    C = C.loc[hidx]
    k = pd.read_parquet(H_FROZEN / "w4" / H_W4[1])
    k["date"] = pd.to_datetime(k["date"])
    c6, cM, reps = nyse_close_prints(k, hidx, U)
    cp = cM.combine_first(c6)
    c = pd.read_parquet(H_FROZEN / "w4" / H_W4[2])
    c["date"] = pd.to_datetime(c["date"])
    prc = c[c.ticker.isin(U)].pivot_table(index="date", columns="ticker", values="prc").reindex(index=hidx, columns=U).abs()
    one = cc[cc.window == "1Y"].pivot(index="date", columns="ticker", values="close_cc").reindex(index=hidx, columns=U)
    alls = cc[cc.window == "All"].pivot(index="date", columns="ticker", values="close_cc").reindex(index=hidx, columns=U)
    cc_amb = one.notna() & alls.notna() & ((one - alls).abs() > TOL)
    ccv = one.combine_first(alls).where(~cc_amb)
    y2425 = pd.DataFrame(np.repeat((hidx <= pd.Timestamp("2024-12-31"))[:, None], len(U), axis=1), index=hidx, columns=U)
    second = prc.where(y2425).combine_first(ccv.where(~y2425))
    src2 = np.where(y2425, "CRSP", "CEFConnect")
    have = C.notna()
    n_src = cp.notna().astype(int) + second.notna().astype(int)
    off_p, off_s = (C - cp).abs() > TOL, (C - second).abs() > TOL
    both = have & cp.notna() & second.notna()
    off_both = both & off_p & off_s
    agree = (cp - second).abs() <= TOL
    d6, other = off_both & agree, off_both & ~agree
    single = have & (n_src == 1) & ((cp.notna() & off_p) | (second.notna() & off_s))
    by_year = {}
    for yv in sorted(set(hidx.year)):
        m = hidx.year == yv
        by_year[int(yv)] = dict(name_days=int(have.loc[m].sum().sum()), two_sources=int(both.loc[m].sum().sum()),
                                one_source=int((have & (n_src == 1)).loc[m].sum().sum()),
                                no_source=int((have & (n_src == 0)).loc[m].sum().sum()),
                                d6=int(d6.loc[m].sum().sum()), sources_disagree=int(other.loc[m].sum().sum()),
                                single_source_logged=int(single.loc[m].sum().sum()),
                                cc_windows_disagree=int((cc_amb & have).loc[m].sum().sum()))
    print("by year (counts only; the second source is CRSP in 2023-24 and CEFConnect in 2025-26):")
    print(pd.DataFrame(by_year).T.to_string())
    print(f"NYSE closing prints repeated at one price (counted, not defects): { {k_: v for k_, v in reps.items() if v} }")
    log, detail = [], []
    for (d, t) in _cells(d6 | other):
        log.append(dict(date=str(d.date()), ticker=t, cls="D-6" if d6.at[d, t] else "§4.5(c) (sources disagree)",
                        second_source=str(src2[hidx.get_loc(d), U.index(t)]),
                        close_minus_nyse_c=round(float(100 * (C.at[d, t] - cp.at[d, t])), 3),
                        value_used="NYSE closing print" if d6.at[d, t] else "none (halt)"))
    for (d, t) in _cells(single | off_both):
        detail.append(dict(date=str(d.date()), ticker=t, close_minus_nyse_c=_c(C, cp, d, t),
                           close_minus_second_c=_c(C, second, d, t), second_source=str(src2[hidx.get_loc(d), U.index(t)]),
                           single_source=bool(single.at[d, t])))
    LOG_CACHE.mkdir(parents=True, exist_ok=True)
    (LOG_CACHE / f"holdout_close_check_detail_{H_STAMP}.json").write_text(json.dumps(detail, indent=1) + "\n")
    print("replaced or halting name-days (the NYSE difference only; second-source detail is in the gitignored log):")
    for r in log:
        print("   ", r)
    if d6.sum().sum() > D6_HALT_N:
        halts.append(f"D-6 (holdout): {int(d6.sum().sum())} name-days, above the ruled {D6_HALT_N}")
    if other.any().any():
        halts.append(f"§4.5(c) (holdout): {int(other.sum().sum())} close(s) off both sources, which disagree")
    Pin = P.copy()
    for (d, t) in _cells(d6):
        m = (Pin.date == d) & (Pin.ticker == t)
        if m.sum() != 1:
            raise Halt(f"holdout D-6 {d.date()} {t}: {int(m.sum())} rows, not one")
        Pin.loc[m, "close"] = float(cp.at[d, t])
    Pin.to_parquet(H_FROZEN / "cef" / "cef_prices.parquet", index=False)
    print(f"the holdout copy: {int(d6.sum().sum())} close(s) replaced (D-6); single-source disagreements logged and "
          f"not used: {int(single.sum().sum())}")
    files = {str(f.relative_to(H_FROZEN)): sha256_file(f) for f in sorted(H_FROZEN.rglob("*")) if f.is_file()}
    hr("SHA-256 OF EVERY FROZEN HOLDOUT FILE")
    for n_, h_ in files.items():
        print(f"{h_}  {n_}")
    rec = dict(stamp=H_STAMP, root=str(H_FROZEN.relative_to(REPO)), holdout=[str(HOLD[0].date()), str(HOLD[1].date())],
               live_last_dates=out_last, dg_c5_7=cover, ruling="two agreeing sources replace a panel close (CRSP prc "
               "2023-24, CEFConnect close 2025-26, each with the NYSE closing print); one source alone is logged, "
               "never used; |diff| <= 0.005 + 1e-6; halt above 5", by_year=by_year, d6_log=log,
               d6_count=int(d6.sum().sum()), files=files, halts=halts, verdict="HALT" if halts else "FROZEN")
    hr("HOLDOUT FREEZE VERDICT: " + rec["verdict"])
    for x in halts:
        print("  - " + x)
    return rec


def _c(A, B, d, t):
    v = A.at[d, t] - B.at[d, t]
    return round(float(100 * v), 3) if np.isfinite(v) else None


def verify_holdout() -> dict:
    rec = json.loads(_need(H_RECORD, "c5_open_auction.py freeze-holdout, committed").read_text())
    if rec.get("verdict") != "FROZEN":
        raise Halt(f"the holdout freeze record says {rec.get('verdict')}")
    got = {str(f.relative_to(H_FROZEN)): sha256_file(f) for f in sorted(H_FROZEN.rglob("*")) if f.is_file()}
    if got != rec["files"]:
        raise Halt("the frozen holdout copy differs from its committed hashes")
    return rec


def holdout() -> dict:
    """Stage 8, once: the sign of the holdout mean of G (WIDE) against the fit's."""
    from scripts.cef import band_frontier as bf
    from scripts.cef.band_frontier import _stats, open_fill_gain
    from scripts.cef.c5_feasibility import nyse_open_prints
    from scripts.cef.spec import UNIVERSE
    from scripts.cef.w4_artifacts import stationary_boot
    from statistics import NormalDist
    _fit_committed()
    fitrec = json.loads(FIT_VERDICT.read_text())
    hrec = verify_holdout()
    U = list(UNIVERSE)
    print(f"C5 (CEF trial 51) STAGE 8, THE HOLDOUT {HOLD[0].date()} .. {HOLD[1].date()}, run "
          f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M}Z. Opened once; it can kill, never rescue. The fit verdict "
          f"stands: {fitrec['verdict']}")
    print(f"frozen holdout inputs verified ({len(hrec['files'])} files, {H_RECORD.relative_to(REPO)}); "
          f"holdout D-6 replacements: {hrec['d6_count']}")
    fit_mean = fitrec["stage1"]["stats"]["mean_bp_yr"]
    fit_sr = fitrec["stage1"]["stats"]["sr"]
    old = bf.DATA_DIR
    try:
        bf.DATA_DIR = F_CEF
        Hfit = {lab: _holdings(f)[2] for lab, f in (("WIDE", 0), ("deployed", None))}
        bf.DATA_DIR = H_FROZEN / "cef"
        built = {lab: bf.build_targets(min_adv=f) for lab, f in (("WIDE", 0), ("deployed", None))}
        from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS
        H = {}
        for lab, (T, R) in built.items():
            T, R = T.loc[:HOLD[1]], R.loc[:HOLD[1]]
            H[lab] = bf.band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)
        Rt = bf.total_returns(built["WIDE"][1].loc[:HOLD[1]])
    finally:
        bf.DATA_DIR = old
    for lab in H:
        same = H[lab].loc[:FIT_END].equals(Hfit[lab])
        print(f"H ({lab}) to 2022-12-30 from the holdout copy equals the fit's H exactly: {same}")
        if not same:
            raise Halt(f"{lab}: H to 2022 differs between the fit's copy and the holdout copy")
    idx = H["WIDE"].index
    HW = idx[(idx >= HOLD[0]) & (idx <= HOLD[1])]
    if len(HW) != HOLD_SESSIONS:
        raise Halt(f"the holdout has {len(HW)} sessions, not {HOLD_SESSIONS}")
    P = pd.read_parquet(H_FROZEN / "cef" / "cef_prices.parquet")
    P["date"] = pd.to_datetime(P["date"])
    pv = lambda c_: P.pivot_table(index="date", columns="ticker", values=c_).sort_index().reindex(columns=U).reindex(idx)
    C, op_y, hi, lo = pv("close"), pv("open"), pv("high"), pv("low")
    a = pd.read_parquet(H_FROZEN / "w4" / H_W4[0])
    a["date"] = pd.to_datetime(a["date"])
    O, Q = nyse_open_prints(a, idx, U)
    c = pd.read_parquet(H_FROZEN / "w4" / H_W4[2])
    c["date"] = pd.to_datetime(c["date"])
    op_c = c[c.ticker.isin(U)].pivot_table(index="date", columns="ticker", values="openprc").reindex(index=idx, columns=U)
    op_c = op_c.where(op_c > 0)
    hasO = O.notna() & C.notna()
    d2 = O.notna() & Q.notna() & ((O - Q).abs() > TOL)
    out_rng = hasO & lo.notna() & ((O < lo - TOL) | (O > hi + TOL))
    eq_y = hasO & op_y.notna() & ((O - op_y).abs() <= TOL)
    eq_c = hasO & op_c.notna() & ((O - op_c).abs() <= TOL)
    d3 = hasO & op_y.notna() & op_c.notna() & ~eq_y & ~eq_c & out_rng
    d3_unevaluable = hasO & out_rng & op_c.isna()
    Oe = O.where(~(d2 | d3))
    RS, _ = bf.session_returns(Oe, C)                 # raises on a non-positive price or a 50% session (§4.5)
    hr("STAGE 8 DATA: §4.2's classes on the holdout (the rule applied unchanged)")
    halts, cls = [], {}
    for lab in ("WIDE", "deployed"):
        tr = open_fill_gain(H[lab], pd.DataFrame(1.0, index=idx, columns=U), by_name=True).abs().loc[HW]
        mat = tr >= MATERIAL
        nm = int(mat.sum().sum())
        d1 = mat & C.loc[HW].notna() & O.loc[HW].isna()
        d1n = float(tr.where(d1, 0.0).sum().sum() / tr.where(mat, 0.0).sum().sum()) if nm else 0.0
        d5 = mat & C.loc[HW].isna()
        d3m = mat & d3.loc[HW]
        cls[lab] = dict(material=nm, D1=int(d1.sum().sum()), D1_notional=d1n, D3=int(d3m.sum().sum()),
                        D5=int(d5.sum().sum()))
        print(f"{lab}: material trade name-days {nm:,}; D-1 {int(d1.sum().sum())} ({d1.sum().sum() / max(nm, 1):.2%}, "
              f"{d1n:.2%} of notional); D-3 {int(d3m.sum().sum())}; D-5 {int(d5.sum().sum())}")
        if nm and (d1.sum().sum() / nm > HALT["D1_trades"] or d1n > HALT["D1_notional"]):
            halts.append(f"D-1 ({lab}) above 1%")
        if nm and d3m.sum().sum() / nm > HALT["D3_trades"]:
            halts.append(f"D-3 ({lab}) above 0.5%")
        if nm and d5.sum().sum() / nm > HALT["D5_trades"]:
            halts.append(f"D-5 ({lab}) above 0.1%: {int(d5.sum().sum())} of {nm:,} material trade name-days "
                         f"({d5.sum().sum() / nm:.2%})")
        for (d, t) in _cells(d5):
            print(f"      D-5 ({lab}): {d.date()} {t} -- a material trade fills on a name-day with no panel close")
    both = O.notna() & Q.notna()
    nd2, nboth = int(d2.loc[HW].sum().sum()), int(both.loc[HW].sum().sum())
    print(f"D-2: {nd2} of {nboth} name-days with both O and Q; D-3 (all name-days): {int(d3.loc[HW].sum().sum())}; "
          f"O outside the day's range with no CRSP openprc to test D-3 against (2025-26, CRSP ends 2024): "
          f"{int(d3_unevaluable.loc[HW].sum().sum())} name-days, reported, not classified")
    if nboth and nd2 / nboth > HALT["D2_both"]:
        halts.append("D-2 above 1% of name-days with both")
    if halts:
        raise Halt("; ".join(halts))
    # ---- the rule
    hr("STAGE 8: THE HOLDOUT SIGN RULE (§7) -- KILL D3 if the holdout mean of G has the opposite sign to the fit's")
    e = {lab: bf.evaluate(H[lab], Rt) for lab in H}
    G = open_fill_gain(H["WIDE"], RS).loc[HW]
    turn = float(e["WIDE"]["turn_series"].loc[HW].mean() * 252)
    st = gstats(G, turn)
    b = stationary_boot(G, mean_block=BOOT["mean_block"], reps=BOOT["reps"], seed=BOOT["seed"])
    n = len(G)
    z = fit_sr * np.sqrt(n / 252)
    sign_h = np.sign(st["mean_bp_yr"])
    p_obs = NormalDist().cdf(z) if sign_h > 0 else NormalDist().cdf(-z)
    agree = sign_h == np.sign(fit_mean)
    print(fmt_g("G, WIDE, holdout", st))
    print(f"fit mean {fit_mean:+.1f}bp/yr (SR {fit_sr:+.2f}); holdout mean {st['mean_bp_yr']:+.1f}bp/yr over {n} sessions; "
          f"signs {'AGREE' if agree else 'DISAGREE'}")
    print(f"stationary bootstrap (block 21, 10,000, seed 20261013) 95% CI: mean {b['lo_mean'] * 252e4:+.1f} .. "
          f"{b['hi_mean'] * 252e4:+.1f}bp/yr; Sharpe {b['lo_sr']:+.2f} .. {b['hi_sr']:+.2f}")
    print(f"probability of the observed sign if the fit's Sharpe were true: {p_obs:.3f}")
    rule = "PASS (signs agree)" if agree else "KILL D3 (signs disagree)"
    print(f"STAGE 8: {rule}. It cannot rescue: the trial's verdict stays {fitrec['verdict']}")
    # ---- beside: the deployed set, by year, the books' holdout rows (H13)
    hr("BESIDE THE RULE, NEVER DECIDING")
    Gd = open_fill_gain(H["deployed"], RS).loc[HW]
    sd = gstats(Gd, float(e["deployed"]["turn_series"].loc[HW].mean() * 252))
    print(fmt_g("G, deployed set, holdout", sd))
    yr = {}
    for yv in sorted(set(HW.year)):
        g_ = G[G.index.year == yv]
        yr[int(yv)] = dict(mean_bp_yr=g_.mean() * 252e4, sessions=len(g_))
    print("G (WIDE) by year, bp/yr: " + "; ".join(f"{k_} {v['mean_bp_yr']:+.1f} ({v['sessions']})" for k_, v in yr.items()))
    print(f"{'book (holdout rows, H13)':<40}{'grossSR':>8}{'ann%':>7}{'turn/yr':>8}{'net@5':>8}{'net@15':>8}{'net@30':>8}")
    books = {}
    for lab in ("WIDE", "deployed"):
        gl = open_fill_gain(H[lab], RS)
        for nm_, pnl in ((f"{lab}: MOC fill", e[lab]["pnl"]), (f"{lab}: C5 open fill", e[lab]["pnl"] + gl)):
            s_ = _stats(pnl.loc[HW], e[lab]["turn_series"].loc[HW])
            books[nm_] = dict(sr=s_["sr"], ann_pct=s_["ann"] * 100, turn=s_["turn"], nets=s_["nets"])
            print(f"{nm_:<40}{s_['sr']:8.2f}{s_['ann'] * 100:7.2f}{s_['turn']:8.2f}" + "".join(f"{x:8.2f}" for x in s_["nets"]))
    G.to_frame("G").to_parquet(FIT_CACHE / "G_wide_holdout.parquet")
    return dict(stamp=H_STAMP, holdout=[str(HOLD[0].date()), str(HOLD[1].date())], sessions=n, G=st,
                boot_ci=dict(mean_bp_yr=(b["lo_mean"] * 252e4, b["hi_mean"] * 252e4), sr=(b["lo_sr"], b["hi_sr"])),
                fit_mean_bp_yr=fit_mean, fit_sr=fit_sr, signs_agree=bool(agree), p_observed_sign=p_obs,
                rule=rule, trial_verdict=fitrec["verdict"], classes=cls, d2=nd2,
                d3_unevaluable=int(d3_unevaluable.loc[HW].sum().sum()), deployed_G=sd, by_year=yr, books=books,
                holdout_inputs=str(H_RECORD.relative_to(REPO)))


def _write(name: str, header: str, fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn()
    text = buf.getvalue()
    sys.stdout.write(text)
    (OUT_DIR / name).write_text(header + text)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=("freeze", "stage0", "fit", "freeze-holdout", "holdout"))
    a = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    if a.stage == "freeze":
        rec = _write(f"c5_freeze_output_{STAMP}.txt",
                     f"# python3 scripts/cef/c5_open_auction.py freeze  (run {STAMP}; counts, cents, hashes)\n", freeze)
        FREEZE_RECORD.write_text(json.dumps(rec, indent=1, default=str) + "\n")
        return 1 if rec["verdict"] == "HALT" else 0
    if a.stage == "freeze-holdout":
        rec = _write(f"c5_holdout_freeze_output_{H_STAMP}.txt",
                     f"# python3 scripts/cef/c5_open_auction.py freeze-holdout  (run {H_STAMP}; counts, cents vs the "
                     "NYSE print, hashes; no CRSP or CEFConnect quantity per date)\n", freeze_holdout)
        H_RECORD.write_text(json.dumps(rec, indent=1, default=str) + "\n")
        return 1 if rec["verdict"] == "HALT" else 0
    if a.stage == "holdout":
        FIT_CACHE.mkdir(parents=True, exist_ok=True)
        # A halt is a result too: the log up to it is written, never discarded (2026-10-15: the first
        # attempt halted on D-5 before G was formed, and its buffered log was lost with the exception).
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rec = holdout()
        except Halt as e:
            text = buf.getvalue() + f"\nSTAGE 8 HALTED BEFORE G WAS FORMED (§4.2, applied unchanged; DG-C5-6): {e}\n"
            sys.stdout.write(text)
            (OUT_DIR / f"c5_holdout_halt_output_{H_STAMP}.txt").write_text(
                f"# python3 scripts/cef/c5_open_auction.py holdout  (run {H_STAMP}; stage 8 HALTED on a declared "
                "data class before the holdout gain was formed)\n" + text)
            (OUT_DIR / f"c5_holdout_halt_{H_STAMP}.json").write_text(json.dumps(
                dict(stamp=H_STAMP, stage="8", verdict="HALT before G", reason=str(e),
                     trial_verdict=json.loads(FIT_VERDICT.read_text())["verdict"]), indent=1) + "\n")
            return 1
        sys.stdout.write(buf.getvalue())
        (OUT_DIR / f"c5_holdout_output_{H_STAMP}.txt").write_text(
            f"# python3 scripts/cef/c5_open_auction.py holdout  (run {H_STAMP}; stage 8, opened once)\n" + buf.getvalue())
        H_RESULT.write_text(json.dumps(rec, indent=1, default=lambda o: float(o) if isinstance(o, np.floating)
                                       else (bool(o) if isinstance(o, np.bool_) else str(o))) + "\n")
        return 0
    if a.stage == "fit":
        rec = _write(f"c5_fit_output_{STAMP}.txt",
                     f"# python3 scripts/cef/c5_open_auction.py fit  (run {STAMP}; frozen inputs; decision window "
                     "2016-01-04..2022-12-30; the holdout is not read)\n", fit)
        FIT_VERDICT.write_text(json.dumps(rec, indent=1, default=lambda o: float(o) if isinstance(o, np.floating)
                                          else (bool(o) if isinstance(o, np.bool_) else str(o))) + "\n")
        return 0
    rec, flags = _write(f"c5_stage0_amended_output_{STAMP}.txt",
                        f"# python3 scripts/cef/c5_open_auction.py stage0  (run {STAMP}, amended, frozen inputs; "
                        "counts, gates, hashes; no P&L)\n", stage0)
    (OUT_DIR / f"c5_stage0_amended_record_{STAMP}.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    pd.DataFrame(flags, columns=["date", "ticker", "set", "kind", "note"]).to_csv(
        OUT_DIR / f"c5_stage0_amended_flags_{STAMP}.csv", index=False)
    return 1 if rec["verdict"] == "HALT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
