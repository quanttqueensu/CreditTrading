"""Trial C5 (CEF trial 51): fill the live book's trades at the t+1 OPENING
auction instead of the t+1 closing auction. The trial script that
`results/cef/PREREG_C5_OPEN_AUCTION_2026-10-13.md` §17 names.

    QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side open
    QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side open --sizes
    QUANTT_ENV_FILE=<config/.env> python3 scripts/data/fetch_alpaca_auction_history.py --side close --sizes
    python3 scripts/data/stage_crsp_w4.py
    QUANTT_ENV_FILE=<config/.env> python3 scripts/cef/exec_capacity_open_cross.py fetch --skip-recent
    python3 scripts/cef/c5_open_auction.py stage0        # counts, gates and hashes; no P&L

WHAT IS HERE, AND WHAT IS NOT
-----------------------------
Only STAGE 0 of the pre-registration's order of evaluation (§13): the data
gates DG-C5-1..5 and DG-C5-8, the declared price rule's defect classes and
their halt rules (§4.2), the "any other defect" examples of §4.5, the spec pin,
the equal-turnover check, and one record of the SHA-256 of every input. **No
return is combined into a P&L at this stage** (§13; the XASSET review's
finding 1): the session return C/O - 1 is formed only to test it against the
harness's 50% filter, and nothing is summed over a holdings path.

Stages 1-8 are deliberately NOT implemented. The first run of Stage 0, on
2026-10-14, HALTED on a §4.5 defect (panel closes that disagree with both CRSP
`prc` and the NYSE closing print), and the pre-registration sends a Stage 0
halt to the team lead before any P&L: "a rule is never edited to make a count
pass". Writing the scoring code before that ruling would invite running it.
`results/cef/C5_RESULT_2026-10-14.md` records the halt and the questions.

THE HOLDOUTS. Every frame stops at 2022-12-30 (`fit_only`, `_assert_fit`). The
2023+ opening prints are not fetched: `fetch_alpaca_auction_history.py
--holdout` refuses until `results/cef/c5/C5_FIT_VERDICT.json` is committed
(DG-C5-6). The quote sample is the 2016-22 sample alone (`fetch
--skip-recent`). Only the 13 spec names are read.

NO SILENT FALLBACK. A missing cache raises naming its builder. A defect is
counted and listed by its declared class, never filled; anything outside the
declared classes halts.

Outputs (counts, shares, differences in cents, hashes: no vendor price level,
because the caches are licensed or vendor data and this repository is public):
  results/cef/c5/c5_stage0_output_<STAMP>.txt
  results/cef/c5/c5_stage0_record_<STAMP>.json
  results/cef/c5/c5_stage0_flags_<STAMP>.csv
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import pickle
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
W4_CACHE = REPO / "results" / "cef" / "w4" / "_cache_w4"
OPEN_PRINTS = W4_CACHE / "alpaca_opening_prints_2016_2022.parquet"
OPEN_SIZED = W4_CACHE / "alpaca_opening_prints_sized_2016_2022.parquet"
CLOSE_SIZED = W4_CACHE / "alpaca_closing_prints_sized_2016_2022.parquet"
CRSP = W4_CACHE / "crsp_dsf_w4.parquet"
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
MATERIAL = 0.005                                  # §12.2: a trade of at least 0.5% of capital
HALT = dict(D1_trades=0.01, D1_notional=0.01, D2_both=0.01, D3_trades=0.005, D5_trades=0.001)
FLOAT_EPS = 1e-6                                  # float32 panel noise at the $0.005 boundary (see sec_other)
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


# =============================================================================
# the data
# =============================================================================

class Data:
    """Every frame Stage 0 reads, on the decision window's sessions. Nothing here
    carries a date after 2022-12-30."""

    def __init__(self):
        from scripts.cef import band_frontier as bf
        from scripts.cef.c5_feasibility import nyse_open_prints
        from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS, UNIVERSE
        from scripts.cef.w4_artifacts import _assert_fit
        self.U = U = list(UNIVERSE)
        P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
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
        kn = k[k.exchange == "N"]
        # Two primary prints of one condition on one name-day are ambiguous only if their PRICES
        # differ (the runner's rule: quantt/broker/alpaca.py closing_auction_prints raises
        # AmbiguousAuctionPrint on two prices). On 2021-12-31 every name's M print was published
        # twice, at 16:00 and again at 19:00 ET, at the same price and size; that is counted here.
        self.close_dups = {}
        for cond in ("6", "M"):
            s = kn[kn.condition == cond]
            d = s[s.duplicated(["date", "ticker"], keep=False)]
            if len(d) and (d.groupby(["date", "ticker"]).price.nunique() > 1).any():
                raise Halt(f"NYSE condition-{cond} closing prints at two different prices on one name-day")
            self.close_dups[cond] = sorted({str(x.date()) for x in d.date})
        piv = lambda cond: (kn[kn.condition == cond].drop_duplicates(["date", "ticker"])
                            .pivot(index="date", columns="ticker", values="price").reindex(index=idx, columns=U))
        self.close6, self.closeM = piv("6"), piv("M")

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
        """Row s: |the trade decided at s-1|, which goes to the open of s (the
        alignment of `open_fill_gain`, read through it with RS = 1 so there is
        one definition of the lag)."""
        from scripts.cef.band_frontier import open_fill_gain
        H = self.H[lab]
        ones = pd.DataFrame(1.0, index=H.index, columns=H.columns)
        return open_fill_gain(H, ones, by_name=True).abs().loc[self.idx]


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
    hr("[1] DG-C5-1: THE OPENING PRINTS AND THE DECLARED PRICE RULE (§4.2), RE-COUNTED")
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
    d2 = both & ((O - Q).abs() > TICK)
    out_rng = hasO & D.lo.notna() & ((O < D.lo - TICK) | (O > D.hi + TICK))
    eq_y = hasO & D.op_y.notna() & ((O - D.op_y).abs() <= TICK)
    eq_c = hasO & D.op_c.notna() & ((O - D.op_c).abs() <= TICK)
    d3 = hasO & D.op_y.notna() & D.op_c.notna() & ~eq_y & ~eq_c & out_rng
    flagged = out_rng & ~d3
    dup = a[a.exchange == "N"].duplicated(["date", "ticker", "condition"], keep=False)
    rows = [("panel name-days 2016-22 with a close", n_pr, REF_2026_10_13["panel_name_days"]),
            ("  with an NYSE 'O' print", nO, REF_2026_10_13["O"]),
            ("  'Q' only (no round-lot cross)", nQonly, REF_2026_10_13["Q_only"]),
            ("  neither", nnone, REF_2026_10_13["none"]),
            ("O and Q both present", int(both.sum().sum()), REF_2026_10_13["both_OQ"]),
            ("D-2: |O - Q| > $0.005", int(d2.sum().sum()), REF_2026_10_13["D2"]),
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


def sec_other(D: Data) -> tuple[dict, list, list]:
    """§4.5: 'Any other defect found at Stage 0 halts the trial before any P&L and
    goes to the team lead: for example a print at an impossible price, a session
    return over 50% in magnitude (the harness's own price filter), or a close
    that disagrees with both CRSP prc and the NYSE closing print.' Each example is
    tested here. The pre-registration states no tolerance for 'disagrees'; the
    declared price-agreement tolerance of §4.2 ($0.005) is applied, and because
    the yfinance panel stores float32 prices (10.89 is 10.890000343), a
    disagreement of EXACTLY half a cent can land either side of $0.005. Both
    counts are printed: 'strict' (> $0.005 on the stored floats) and 'robust'
    (> $0.005 + 1e-6, so an exact half cent is agreement)."""
    hr("[2] §4.5: DEFECTS OUTSIDE THE DECLARED CLASSES (any one halts before P&L)")
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
        print(f"      {d.date()} {t}: {v:.2%}; O vs yfinance open agree {abs(O.at[d, t] - D.op_y.at[d, t]) <= TICK}, "
              f"vs CRSP openprc {abs(O.at[d, t] - D.op_c.at[d, t]) <= TICK}")
    if big.any().any():
        halts.append(f"§4.5(b): {int(big.sum().sum())} session return(s) of 50% or more")
    # (c) the close against CRSP prc and the NYSE closing print
    cp = D.closeM.combine_first(D.close6)             # M (official close) where published, else 6 (closing trade)
    which = pd.DataFrame(np.where(D.closeM.notna(), "M", np.where(D.close6.notna(), "6", "")),
                         index=C.index, columns=C.columns)
    prc = D.prc.abs()                                 # CRSP: a negative prc is a bid/ask midpoint (no closing trade)
    neg = int((D.prc < 0).sum().sum())
    avail = C.notna() & prc.notna() & cp.notna()
    dc, dp = (C - prc).abs(), (C - cp).abs()
    strict = avail & (dc > TICK) & (dp > TICK)
    robust = avail & (dc > TICK + FLOAT_EPS) & (dp > TICK + FLOAT_EPS)
    print(f"(c) NYSE closing prints repeated at one price (counted, not defects): "
          f"{ {k: v for k, v in D.close_dups.items() if v} }")
    print(f"(c) the panel close against CRSP prc and the NYSE closing print (M where published, else 6), "
          f"name-days with all three: {int(avail.sum().sum()):,} of {int(C.notna().sum().sum()):,} "
          f"(CRSP prc < 0, i.e. no closing trade: {neg})")
    print(f"    close off CRSP prc by > $0.005: {int((avail & (dc > TICK)).sum().sum())}; off the NYSE print: "
          f"{int((avail & (dp > TICK)).sum().sum())}")
    tr = {lab: D.trades(lab) for lab in ("WIDE", "deployed")}
    print(f"    {'off BOTH by > $0.005':<44}{'all name-days':>14}{'WIDE material':>15}{'WIDE any':>10}"
          f"{'deployed material':>19}{'deployed any':>14}")
    for lab, m in (("strict (stored float32)", strict), ("robust (an exact half cent agrees)", robust)):
        cnt = [int(m.sum().sum())]
        for s in ("WIDE", "deployed"):
            cnt += [int((m & (tr[s] >= MATERIAL)).sum().sum()), int((m & (tr[s] > 1e-12)).sum().sum())]
        print(f"    {lab:<44}{cnt[0]:>14}{cnt[1]:>15}{cnt[2]:>10}{cnt[3]:>19}{cnt[4]:>14}")
    print("    every such name-day (strict), in cents (no price level is printed: CRSP is licensed data):")
    print(f"      {'date':<12}{'name':<6}{'close-CRSP':>11}{'close-NYSE':>11}{'print':>6}{'robust':>8}"
          f"{'WIDE trade':>12}{'deployed trade':>16}")
    for (d, t) in _cells(strict):
        wt, dtd = tr["WIDE"].at[d, t], tr["deployed"].at[d, t]
        lab_w = "material" if wt >= MATERIAL else ("small" if wt > 1e-12 else "-")
        lab_d = "material" if dtd >= MATERIAL else ("small" if dtd > 1e-12 else "-")
        cc = 100 * (C.at[d, t] - prc.at[d, t])
        cn = 100 * (C.at[d, t] - cp.at[d, t])
        print(f"      {str(d.date()):<12}{t:<6}{cc:>+11.2f}{cn:>+11.2f}{which.at[d, t]:>6}"
              f"{'yes' if robust.at[d, t] else 'no':>8}{lab_w:>12}{lab_d:>16}")
        flags.append(dict(date=str(d.date()), ticker=t, set="all", kind="§4.5(c) close off CRSP prc and NYSE print",
                          note=f"close-CRSP {cc:+.2f}c; close-NYSE({which.at[d, t]}) {cn:+.2f}c; "
                               f"robust {bool(robust.at[d, t])}; WIDE trade {lab_w}; deployed trade {lab_d}"))
    if robust.any().any():
        halts.append(f"§4.5(c): {int(robust.sum().sum())} panel close(s) disagree with both CRSP prc and the NYSE "
                     f"closing print by more than $0.005 (robust count; {int(strict.sum().sum())} strict), of which "
                     f"{int((robust & (tr['WIDE'] >= MATERIAL)).sum().sum())} on WIDE material trade name-days and "
                     f"{int((robust & (tr['deployed'] >= MATERIAL)).sum().sum())} on the deployed set's")
    elif strict.any().any():
        halts.append(f"§4.5(c): {int(strict.sum().sum())} panel close(s) disagree with both sources by more than "
                     "$0.005 only on the stored floats (an exact half cent); the tolerance is the team lead's ruling")
    rec = dict(impossible_open=nonpos, session_ge_50pct=int(big.sum().sum()),
               close_off_both_strict=int(strict.sum().sum()), close_off_both_robust=int(robust.sum().sum()),
               close_off_both_robust_WIDE_material=int((robust & (tr["WIDE"] >= MATERIAL)).sum().sum()),
               close_off_both_robust_deployed_material=int((robust & (tr["deployed"] >= MATERIAL)).sum().sum()),
               crsp_prc_negative=neg)
    print("\nhalt rules (§4.5):", "NONE FIRED" if not halts else "; ".join(halts))
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


def sec_noop() -> dict:
    hr("[4] DG-C5-4: THE WIDE FLAG IS A NO-OP WHEN ABSENT")
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
    print(f"build_targets(min_adv=0) equals the feasibility script's adv_floor(0) build: {same_wide}")
    if (h1, h2) != (NOOP_FIRST, NOOP_SECOND) or not same_wide:
        raise Halt("DG-C5-4: build_targets() is not byte-identical with the argument absent, or WIDE differs")
    print("DG-C5-4: PASS")
    return dict(first=h1, second=h2, wide_equals_feasibility=same_wide)


EXEC_FIT_LINES = REPO / "results" / "cef" / "exec_capacity" / "exec_capacity_output.txt"


def sec_quotes() -> dict:
    """DG-C5-5: rebuild the 2016-22 quote sample and reproduce the EXEC note's
    §6 fit-period block to the printed precision. The EXEC note's §5 breakeven
    (a P&L of the deployed book) is NOT recomputed at Stage 0, so the one line
    per horizon that divides by it is excluded from the comparison."""
    hr("[5] DG-C5-5: THE 2016-22 QUOTE SAMPLE (exec_capacity_open_cross.py fetch --skip-recent)")
    from scripts.cef import exec_capacity_open_cross as X
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


def sec_hashes() -> dict:
    hr("[8] THE SHA-256 OF EVERY INPUT (every later stage re-verifies these before it reads an input)")
    from scripts.cef import exec_capacity_open_cross as X
    files = {
        "opening prints (Alpaca SIP, NYSE O/Q) 2016-22": OPEN_PRINTS,
        "opening prints, sized 2016-22": OPEN_SIZED,
        "closing prints, sized 2016-22 (R-CLOSE, capacity)": CLOSE_SIZED,
        "CRSP dsf cache (stage_crsp_w4.py)": CRSP,
        "data/cef/cef_prices.parquet": REPO / "data/cef/cef_prices.parquet",
        "data/cef/cef_nav.parquet": REPO / "data/cef/cef_nav.parquet",
        "data/cef/cef_distributions.parquet": REPO / "data/cef/cef_distributions.parquet",
        "data/cef/cef_splits.parquet": REPO / "data/cef/cef_splits.parquet",
        "data/cef/cef_universe.csv (groups)": REPO / "data/cef/cef_universe.csv",
        "data/cef/cef_borrow_history.parquet (IBKR fee panel row)": REPO / "data/cef/cef_borrow_history.parquet",
        "ops/specs/cef_discount.frozen.json": SPEC_FILE,
        "quote sample calendar": X.CACHE / "calendar.parquet",
    }
    out = {}
    for lab, p in files.items():
        out[lab] = dict(path=str(p.relative_to(REPO)), sha256=sha256_file(_need(p, "see the module docstring")))
        print(f"{out[lab]['sha256']}  {out[lab]['path']}")
    days = X.sample_days(eras=("fit",))
    h = hashlib.sha256()
    for d in sorted(days):
        h.update(d.encode())
        h.update(sha256_file(X.CACHE / "days" / f"{d}.json").encode())
    out["quote sample, 126 fit session files (sha256 of date+sha256 pairs)"] = dict(
        path=str((X.CACHE / "days").relative_to(REPO)), sha256=h.hexdigest(), n=len(days))
    print(f"{h.hexdigest()}  {(X.CACHE / 'days').relative_to(REPO)}/<{len(days)} fit sessions>.json (combined)")
    return out


# =============================================================================
# main
# =============================================================================

def stage0() -> tuple[dict, list]:
    halts, flags, rec = [], [], dict(stamp=STAMP, stage="0")
    print(f"C5 (CEF trial 51) STAGE 0, run {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M}Z. "
          "Counts, gates and hashes only; no return is combined into a P&L.")
    rec["spec"] = sec_spec()
    D = Data()
    print(f"\ncef_prices last date {D.prices_last.date()}; rows to {WINDOW[1].date()} only. Decision window "
          f"{WINDOW[0].date()}..{WINDOW[1].date()}: {len(D.idx)} sessions.")
    r, h, f = sec_classes(D)
    rec["classes"], halts, flags = r, halts + h, flags + f
    r, h, f = sec_other(D)
    rec["other_defects"], halts, flags = r, halts + h, flags + f
    for key, fn in (("tests", sec_tests), ("noop", sec_noop), ("quotes", sec_quotes)):
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
    rec["hashes"] = sec_hashes()
    rec["halts"] = halts
    rec["verdict"] = "HALT" if halts else "PASS"
    hr("STAGE 0 VERDICT")
    if halts:
        print("HALT before any P&L (PREREG_C5 §4.2, §4.5, §13). No statistic of C5 has been computed. The case")
        print("goes to the team lead; no rule is edited to make a count pass, and nothing in data/ is repaired here.")
        for x in halts:
            print(f"  - {x}")
    else:
        print("PASS: every Stage 0 gate cleared.")
    return rec, flags


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=("stage0",))
    ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rec, flags = stage0()
    text = buf.getvalue()
    sys.stdout.write(text)
    (OUT_DIR / f"c5_stage0_output_{STAMP}.txt").write_text(
        f"# python3 scripts/cef/c5_open_auction.py stage0  (run {STAMP}; counts, gates, hashes; no P&L)\n" + text)
    (OUT_DIR / f"c5_stage0_record_{STAMP}.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    pd.DataFrame(flags, columns=["date", "ticker", "set", "kind", "note"]).to_csv(
        OUT_DIR / f"c5_stage0_flags_{STAMP}.csv", index=False)
    return 1 if rec["verdict"] == "HALT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
