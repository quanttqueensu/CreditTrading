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
    log = []
    for (d, t) in _cells(off_both):
        lab_w = _tradelab(tr["WIDE"].at[d, t])
        lab_d = _tradelab(tr["deployed"].at[d, t])
        log.append(dict(date=str(d.date()), ticker=t, cls="D-6" if d6.at[d, t] else "§4.5(c) (sources disagree)",
                        close_minus_crsp_c=round(float(100 * (C.at[d, t] - prc.at[d, t])), 3),
                        close_minus_nyse_c=round(float(100 * (C.at[d, t] - cp.at[d, t])), 3),
                        crsp_minus_nyse_c=round(float(100 * (prc.at[d, t] - cp.at[d, t])), 3),
                        nyse_print=which.at[d, t], value_used="NYSE closing print" if d6.at[d, t] else "none (halt)",
                        WIDE_trade=lab_w, deployed_trade=lab_d))
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
          f"name-day(s), halt above {D6_HALT_N}. Value used: {frz['d6_value_rule']}. In cents, no price level:")
    for r in frz["d6_log"]:
        print(f"      {r['date']} {r['ticker']}: {r['cls']}; close-CRSP {r['close_minus_crsp_c']:+.2f}c, close-NYSE("
              f"{r['nyse_print']}) {r['close_minus_nyse_c']:+.2f}c, CRSP-NYSE {r['crsp_minus_nyse_c']:+.2f}c; "
              f"WIDE trade {r['WIDE_trade']}, deployed trade {r['deployed_trade']}")
        flags.append(dict(date=r["date"], ticker=r["ticker"], set="all", kind=f"{r['cls']} (freeze log)",
                          note=f"close-CRSP {r['close_minus_crsp_c']:+.2f}c; close-NYSE({r['nyse_print']}) "
                               f"{r['close_minus_nyse_c']:+.2f}c; CRSP-NYSE {r['crsp_minus_nyse_c']:+.2f}c; "
                               f"WIDE trade {r['WIDE_trade']}; deployed trade {r['deployed_trade']}"))
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
    ap.add_argument("stage", choices=("freeze", "stage0"))
    a = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    if a.stage == "freeze":
        rec = _write(f"c5_freeze_output_{STAMP}.txt",
                     f"# python3 scripts/cef/c5_open_auction.py freeze  (run {STAMP}; counts, cents, hashes)\n", freeze)
        FREEZE_RECORD.write_text(json.dumps(rec, indent=1, default=str) + "\n")
        return 1 if rec["verdict"] == "HALT" else 0
    rec, flags = _write(f"c5_stage0_amended_output_{STAMP}.txt",
                        f"# python3 scripts/cef/c5_open_auction.py stage0  (run {STAMP}, amended, frozen inputs; "
                        "counts, gates, hashes; no P&L)\n", stage0)
    (OUT_DIR / f"c5_stage0_amended_record_{STAMP}.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    pd.DataFrame(flags, columns=["date", "ticker", "set", "kind", "note"]).to_csv(
        OUT_DIR / f"c5_stage0_amended_flags_{STAMP}.csv", index=False)
    return 1 if rec["verdict"] == "HALT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
