"""CEF trial 54: C4's discount level against family peers (results/cef/PREREG_C4_LEVEL_2026-11-02.md).

Approved 2026-11-03 (CEF 53 -> 54; §0.A). This script runs the pre-registration's §6.2 in order. Each stage
is a subcommand and is read once:

    python3 -B results/cef/prereg_c4_level/trial54.py dgl2      # DG-L2: CRSP primary vs the yfinance leg
    python3 -B results/cef/prereg_c4_level/trial54.py dgl3      # DG-L3: triage evidence and the rulings check
    python3 -B results/cef/prereg_c4_level/trial54.py fit       # P1, K1-K3, P3 (refuses until DG-L3 is ruled)

NO NEW BACKTESTER. The books are built from C4's own trial machinery (`scripts/cef/c4_families.py`:
`universes`, `load_panels`, `crsp_returns`, `qqqx_rule`, `crsp_pivot`, `build_book`, `declared_mask`,
`check_held`, `yf_total_returns`) and scored by `band_frontier.band_gross_capped` + `band_frontier.evaluate`
(shift(2), H1). The one extension is `level_targets` below. It builds the level weights and the blend with
`build_targets`' own eligibility rule and vol-scalar estimator, line for line, on the same panel. It is
visible here, not hidden in a copy of `evaluate`.

C4'S SPEC IS THE ONLY AUTHORITY ON ITS PARAMETERS. `sizing_multiplier` and `max_gross_stress` are read from
`ops/specs/c4_families.frozen.json` (spec_id asserted to be c4_families.v4.20261102), as
`scripts/cef/c4_paper_benchmark.py` reads it. `build_targets` takes z_window, vol_target, the ADV floor and
min_names from the core spec module, so every one of those is asserted EQUAL to C4's spec value, and a
mismatch raises. `band_width` comes from C4's spec. Nothing is written as a literal.

HOLDOUT. Every frame is cut at 2022-12-30 (`c4.fit_slice`, asserted). The holdout stage is not in this file
yet: it is added, and run once, only after every fit kill has cleared.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from scripts.cef import band_frontier as bf  # noqa: E402
from scripts.cef import c4_families as c4  # noqa: E402

C4_SPEC = REPO / "ops" / "specs" / "c4_families.frozen.json"
SPEC_ID = "c4_families.v4.20261102"
FIT_END = pd.Timestamp("2022-12-30")
RISK_SHARE_Z = 0.5                 # PREREG §3.1: derived equal risk (0.514 -> 0.50); a trial parameter, not a spec key
SEED = 20261102
DGL2_TOL = 0.2                     # PREREG §4b DG-L2
DGL3_THRESH = 0.10                 # PREREG §4b DG-L3: |price TR - NAV TR| > 10%
STAMP = "2026-11-03"
# PROPOSED for the team lead's ruling (DG-L3), identified by inspection of the NAV paths around the 242 flags and
# by `navscan`; each is a vendor NAV that leaves and returns while the close (CRSP-confirmed) does not follow.
# Recommended treatment: mask the LEVEL leg's discount on these name-days only (the z book is C4's v4 book as
# trading, untouched, so DG-L4's identity is unaffected). Nothing is masked until the rulings file says so.
NAV_MISPRINTS_PROPOSED = {
    ("BME", "2006-07-24"): "NAV 26.35 -> 29.68 -> 27.12, close 24.56 -> 24.98 -> 25.80",
    ("ASG", "2006-12-20"): "NAV 5.71 -> 6.48 -> 5.68, close 5.44 -> 5.39 -> 5.38",
    ("PFO", "2006-12-26"): "NAV 12.40 -> 16.30 (three sessions) -> 12.39, close 12.15 -> 12.30..12.36",
    ("PFO", "2006-12-27"): "the same three-session run",
    ("PFO", "2006-12-28"): "the same three-session run",
    ("JPC", "2008-01-11"): "NAV 12.68 -> 11.35 -> 12.78; the NAV printed equals that day's close (11.35)",
    ("SCD", "2010-10-01"): "NAV 12.93 -> 11.82 -> 12.97, close 11.41 -> 11.42 -> 11.27 (below the 10% flag line)",
    ("BME", "2021-06-28"): "NAV 47.86 -> 27.65 -> 47.79, close 48.78 -> 48.56 -> 48.41 (discount read +75.6%)",
    ("GAM", "2006-04-19"): "NAV 41.46 -> 45.85 -> 41.55 (navscan; outside any crisis window)",
}
CACHE = HERE / "_cache_trial54"


def c4_spec() -> dict:
    d = json.loads(C4_SPEC.read_text())
    if d["spec_id"] != SPEC_ID:
        raise RuntimeError(f"{C4_SPEC}: spec_id {d['spec_id']}, the pre-registration names {SPEC_ID}")
    f = d["frozen"]
    from scripts.cef import spec as core
    pairs = {"z_window": core.Z_WINDOW, "vol_target_annual": core.VOL_TARGET, "min_adv_usd": core.MIN_ADV_USD,
             "min_names": core.MIN_NAMES}
    bad = {k: (f[k], v) for k, v in pairs.items() if float(f[k]) != float(v)}
    if bad:
        raise RuntimeError(f"build_targets reads these from the core spec and they differ from C4's: {bad}")
    return dict(m=float(f["sizing_multiplier"]), cap=float(f["max_gross_stress"]), band=float(f["band_width"]),
                vol=float(f["vol_target_annual"]), min_names=int(f["min_names"]), min_adv=float(f["min_adv_usd"]))


def _rv(W: np.ndarray, ret: np.ndarray, i: int, w: np.ndarray, lookback: int) -> float:
    """build_targets' estimator: today's weights on the last `lookback` rows of price returns through row i."""
    lo = max(0, i - lookback + 1)
    h = np.nansum(ret[lo:i + 1] * w, axis=1)
    return float(np.std(h, ddof=1) * np.sqrt(252)) if len(h) > 1 else np.nan


def level_targets(UF: list, fam: pd.Series, S: dict) -> dict:
    """Unit targets T_z (C4's own build_book), T_L (the level with its own scalar) and T_B (the blend), fit cut.

    Eligibility, the hold on thin days and the vol scalar repeat `bf.build_targets` exactly:
    a name needs a z-score on t and ADV >= the floor through t-1; fewer than min_names holds the previous row;
    scalar = clip(vol / rv, 0.2, 2.5), with rv from today's weights on the last VOL_LOOKBACK price returns
    through t (H7: everything here is date-t information; the book is scored under shift(2))."""
    mask = c4.declared_mask(UF, "M1M2")
    p = bf.build_panel(universe=UF, source=c4.FAM_SRC, mask=mask)
    z, adv, disc, ret = p["z"], p["adv"], p["disc"], p["ret"]
    Tz = c4.fit_slice(c4.build_book(UF))
    idx = Tz.index
    z, adv, disc, ret = (x.reindex(idx)[UF] for x in (z, adv, disc, ret))
    R = ret.to_numpy()
    TL = np.zeros((len(idx), len(UF)))
    TB = np.zeros_like(TL)
    famv = fam.reindex(UF).to_numpy()
    for i in range(len(idx)):
        zr = z.iloc[i]
        ok = zr.notna().to_numpy() & (adv.iloc[i].fillna(-1).to_numpy() >= S["min_adv"])
        if ok.sum() < S["min_names"]:
            if i:
                TL[i], TB[i] = TL[i - 1], TB[i - 1]
            continue
        # w_z: build_targets' own unit-gross weights (recomputed only to take their vol; T_z itself is build_book's)
        zz = np.where(ok, zr.to_numpy(), np.nan)
        wz = -(zz - np.nanmean(zz))
        wz = np.where(ok, wz, 0.0)
        wz = wz / np.abs(wz).sum()
        # w_L: -(disc - family mean), on the same eligible names; a family with < 2 eligible names gets zero
        dv = np.where(ok, disc.iloc[i].to_numpy(), np.nan)
        wl = np.zeros(len(UF))
        for f in pd.unique(famv[ok]):
            sel = ok & (famv == f) & np.isfinite(dv)
            if sel.sum() >= 2:
                wl[sel] = -(dv[sel] - dv[sel].mean())
        if np.abs(wl).sum() == 0:
            if i:
                TL[i], TB[i] = TL[i - 1], TB[i - 1]
            continue
        wl = wl / np.abs(wl).sum()
        s_z, s_l = _rv(None, R, i, wz, bf.VOL_LOOKBACK), _rv(None, R, i, wl, bf.VOL_LOOKBACK)
        sc = lambda rv: float(np.clip(S["vol"] / rv, 0.2, 2.5)) if rv and rv > 0 else 1.0   # build_targets' rule
        TL[i] = wl * sc(s_l)
        if not (s_z > 0 and s_l > 0):
            TB[i] = TB[i - 1] if i else 0.0
            continue
        mix = RISK_SHARE_Z * wz / s_z + (1 - RISK_SHARE_Z) * wl / s_l
        mix = mix / np.abs(mix).sum()
        TB[i] = mix * sc(_rv(None, R, i, mix, bf.VOL_LOOKBACK))
    TL = pd.DataFrame(TL, index=idx, columns=UF)
    TB = pd.DataFrame(TB, index=idx, columns=UF)
    for f in (Tz, TL, TB):
        if f.index.max() > FIT_END:
            raise AssertionError("holdout leak in a target")
    return dict(Tz=Tz, TL=TL, TB=TB, disc=disc)


def book(T: pd.DataFrame, S: dict, band: float | None = None) -> pd.DataFrame:
    """The account's held book: m x band_gross_capped(unit target, band, cap / m) -- the sizing_multiplier path."""
    b = S["band"] if band is None else band
    return bf.band_gross_capped(T, b, S["cap"] / S["m"]) * S["m"]


def score(H: pd.DataFrame, R: pd.DataFrame, label: str) -> dict:
    R0 = c4.check_held(H, R.reindex(H.index)[H.columns], label)
    res = bf.evaluate(H, R0)
    held = H.shift(2).abs().sum(axis=1)
    p0 = held.index[held > 0][0]
    P, TU = res["pnl"].loc[p0:FIT_END], res["turn_series"].loc[p0:FIT_END]
    return dict(P=P, TU=TU, p0=p0, **c4.row_stats(P, TU))


def inputs():
    U = c4.universes()
    pool, UF = U["pool"], U["frozen"]
    px, nav = c4.load_panels(pool)
    crsp = c4.crsp_returns(pool)
    qr = c4.qqqx_rule(crsp, px)
    if not qr["use_predecessor"]:
        raise RuntimeError("the QQQX rule's decision differs from C4's Stage 0")
    fam = pd.read_csv(c4.FROZEN).set_index("ticker")["family"]
    return U, pool, UF, px, nav, crsp, qr, fam


def stage_dgl2() -> int:
    lines = []
    say = lambda s="": (print(s), lines.append(s))
    S = c4_spec()
    U, pool, UF, px, nav, crsp, qr, fam = inputs()
    say(f"CEF trial 54, DG-L2 ({dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}): "
        f"C4 spec {SPEC_ID}: m {S['m']}, cap {S['cap']}, band {S['band']}")
    B = level_targets(UF, fam, S)
    idx = B["Tz"].index
    R_crsp = c4.crsp_pivot(crsp, pool, idx, qr, "ret", px=px)
    # the yfinance leg exactly as C4's primary_returns builds it (bar rulings + split rulings)
    R_yf = c4.yf_total_returns(px, UF, idx, rulings=c4.BAR_RULINGS, split_rulings=c4.SPLIT_RULINGS)
    HL = book(B["TL"], S)
    out = {}
    for lab, R in (("CRSP primary", R_crsp), ("yfinance leg", R_yf)):
        r = score(HL, R, f"level book on {lab}")
        out[lab] = {k: r[k] for k in ("sr", "ann_pct", "vol_pct", "turn")}
        say(f"  level-only spec book on {lab:<13}: gross SR {r['sr']:+.3f}  ann {r['ann_pct']:+.2f}%  vol {r['vol_pct']:.2f}%  "
            f"turn {r['turn']:.1f}/yr  (from {r['p0'].date()})")
    d = abs(out["CRSP primary"]["sr"] - out["yfinance leg"]["sr"])
    verdict = "CLEAR" if d <= DGL2_TOL else "HALT (difference > 0.2; explain or stop)"
    say(f"  |difference| {d:.3f} against {DGL2_TOL}: DG-L2 {verdict}")
    (HERE / f"dgl2_output_{STAMP}.txt").write_text("\n".join(lines) + "\n")
    (HERE / f"dgl2_{STAMP}.json").write_text(json.dumps(dict(spec=SPEC_ID, **S, books=out, diff=d, verdict=verdict),
                                                          indent=1, default=float))
    return 0 if d <= DGL2_TOL else 2


def stage_dgl3() -> int:
    """The 242 flags, with their evidence and a RECOMMENDED ruling per flag. A recommendation is not a ruling:
    `fit` refuses until a rulings file signed by the team lead exists (require_stage0_rulings)."""
    from scripts.cef.data_guards import require_stage0_rulings  # noqa: F401  (the block `fit` uses)
    lines = []
    say = lambda s="": (print(s), lines.append(s))
    S = c4_spec()
    U, pool, UF, px, nav, crsp, qr, fam = inputs()
    sys.path.insert(0, str(REPO / "results" / "cef" / "screens_2026-11-02"))
    import alpha_common as ac
    D = ac.load_c4()                          # the leg the 242 were counted on (ALPHA_SLATE §S5)
    gap = (D["r_tr"] - D["r_nav_tr"])
    hit = gap.abs() > DGL3_THRESH
    s = hit.stack()
    s = s[s].index
    idx = D["idx"]
    R = c4.crsp_pivot(crsp, pool, idx, qr, "ret", px=px)
    cc = pd.read_parquet(c4.FAM_DIR / "cef_nav_cefconnect.parquet")
    cc["date"] = pd.to_datetime(cc["date"])
    ccn = cc.pivot_table(index="date", columns="ticker", values="nav")
    rules = {k: json.loads(Path(p).read_text()) for k, p in
             (("split", c4.SPLIT_RULINGS), ("bar", c4.BAR_RULINGS),
              ("seed", c4.OUT_DIR / "c4_seed_rulings_2026-10-29.json"))}
    ruled_cells = set()
    for k, j in rules.items():
        for r in [x for key in ("bars", "cells", "splits") for x in (j.get(key) or [])]:
            if isinstance(r, dict) and "ticker" in r and ("date" in r or "ex_date" in r):
                ruled_cells.add((r["ticker"], str(r.get("date") or r.get("ex_date"))[:10], k))
    crisis = lambda d: (pd.Timestamp("2008-09-01") <= d <= pd.Timestamp("2009-06-30")) or \
                       (pd.Timestamp("2020-02-20") <= d <= pd.Timestamp("2020-04-30"))
    rows = []
    for d, t in s:
        i = idx.get_loc(d)
        dp = idx[i - 1]
        c0 = ccn.at[dp, t] if (dp in ccn.index and t in ccn.columns) else np.nan
        c1 = ccn.at[d, t] if (d in ccn.index and t in ccn.columns) else np.nan
        nxt = D["r_nav_tr"].iat[i + 1, D["U"].index(t)] if i + 1 < len(idx) else np.nan
        cr = R.at[d, t] if t in R.columns else np.nan
        r = dict(ticker=t, date=d.date().isoformat(), family=fam.get(t), yf_price_tr=float(D["r_tr"].at[d, t]),
                 crsp_ret=float(cr), nav_tr=float(D["r_nav_tr"].at[d, t]), nav_tr_next=float(nxt),
                 nav_prev=float(D["nav"].at[dp, t]), nav=float(D["nav"].at[d, t]), cc_nav_prev=float(c0),
                 cc_nav=float(c1), crisis_window=bool(crisis(d)),
                 c4_ruling=";".join(k for (tk, dd, k) in ruled_cells if tk == t and dd == d.date().isoformat()))
        r["price_confirmed_by_crsp"] = bool(np.isfinite(cr) and abs(r["yf_price_tr"] - cr) <= 0.005)
        r["nav_confirmable"] = bool(np.isfinite(c0) and np.isfinite(c1))
        # a NAV SPIKE: the NAV leg itself moves >= 5% and gives back more than half of it the next session
        r["nav_spike_reverts"] = bool(abs(r["nav_tr"]) >= 0.05 and np.sign(r["nav_tr"]) != np.sign(nxt)
                                      and abs(nxt) > 0.5 * abs(r["nav_tr"]))
        prev_s = idx[i - 1].date().isoformat()
        if (t, r["date"]) in NAV_MISPRINTS_PROPOSED:
            rec, why = "MASK (recommended)", ("vendor NAV misprint, " + NAV_MISPRINTS_PROPOSED[(t, r["date"])] +
                                              "; mask the level leg's discount on this name-day; its return books")
        elif (t, prev_s) in NAV_MISPRINTS_PROPOSED:
            rec, why = "KEEP (recommended)", (f"the day after the NAV misprint of {prev_s}; the flag is that misprint's "
                                              "echo and is resolved by masking that day; this NAV is good again")
        elif r["c4_ruling"]:
            rec, why = "APPLY C4 RULING", f"covered by C4's {r['c4_ruling']} ruling"
        elif not r["price_confirmed_by_crsp"]:
            rec, why = "KEEP (recommended)", ("the yfinance price TR disagrees with CRSP's, but the trial books CRSP's "
                                              "return (§4) and the level uses the yfinance close and NAV, which share "
                                              "a basis; the disagreement is the distribution leg, not the close")
        elif not r["nav_spike_reverts"]:
            rec, why = "KEEP (recommended)", ("price leg confirmed by CRSP (an independent source); the NAV is not a "
                                              "one-day spike; C4 keeps an unmasked NAV (its M1|M2 masks are its NAV "
                                              "policy). A real discount move")
        elif r["crisis_window"]:
            rec, why = "KEEP (recommended)", ("price confirmed by CRSP; a NAV spike that reverts inside the 2008-09 or "
                                              "2020 crisis window is a plausible marked move; no second NAV source "
                                              "covers the day")
        else:
            rec, why = "MASK (recommended)", ("a one-day NAV spike (>= 5%, more than half given back next session) "
                                              "outside a crisis window, with the price flat and confirmed by CRSP: a "
                                              "vendor NAV misprint. Mask that name-day's discount as C4's M1 does "
                                              "(build_panel `mask`); its return still books")
        r["recommended"], r["why"] = rec, why
        rows.append(r)
    F = pd.DataFrame(rows).sort_values(["date", "ticker"])
    F.insert(0, "check", "DG-L3")
    # CRSP is licensed and the repository is public: the committed table carries the CHECK, never CRSP's value
    F.drop(columns=["crsp_ret"]).to_csv(HERE / f"dgl3_flags_{STAMP}.csv", index=False)
    prop = F[["check", "ticker", "date"]].assign(ruling=F.recommended + ": " + F.why, ruled_by="", ruled_on="")
    extra = [dict(check="DG-L3-NAV", ticker=t, date=d, ruling="MASK (recommended): vendor NAV misprint, " + why +
                  "; not among the 242 (below the 10% line); mask the level leg's discount", ruled_by="", ruled_on="")
             for (t, d), why in NAV_MISPRINTS_PROPOSED.items() if (t, d) not in set(zip(F.ticker, F.date))]
    prop = pd.concat([prop, pd.DataFrame(extra)], ignore_index=True)
    prop.to_csv(HERE / f"dgl3_rulings_PROPOSAL_{STAMP}.csv", index=False)
    say(f"CEF trial 54, DG-L3 ({STAMP}): {len(F)} name-days with |price TR - NAV TR| > {DGL3_THRESH:.0%} on the fit's "
        f"yfinance leg")
    say(f"  by year: {F.date.str[:4].value_counts().sort_index().to_dict()}")
    say(f"  price leg confirmed by CRSP (|yf - CRSP| <= 50bp): {int(F.price_confirmed_by_crsp.sum())}; "
        f"NAV confirmable by CEFConnect (both days present): {int(F.nav_confirmable.sum())}; "
        f"NAV spike reverts next day: {int(F.nav_spike_reverts.sum())}; in a crisis window: {int(F.crisis_window.sum())}; "
        f"covered by a C4 split/bar/seed ruling: {int((F.c4_ruling != '').sum())}")
    say(f"  RECOMMENDED on the 242: {F.recommended.value_counts().to_dict()}; plus "
        f"{sum((t, d) not in set(zip(F.ticker, F.date)) for (t, d) in NAV_MISPRINTS_PROPOSED)} NAV-misprint name-days "
        f"below the 10% line (DG-L3-NAV rows); {len(NAV_MISPRINTS_PROPOSED)} misprint name-days proposed in all")
    for _, r in F[~F.recommended.str.startswith("KEEP") | ~F.price_confirmed_by_crsp].iterrows():
        say(f"    {r.recommended}: {r.ticker} {r.date}: yf price TR {r.yf_price_tr:+.2%}, CRSP agrees: {r.price_confirmed_by_crsp}, NAV TR "
            f"{r.nav_tr:+.2%} then {r.nav_tr_next:+.2%}; NAV {r.nav_prev:.2f} -> {r.nav:.2f}")
    ruled = HERE / f"dgl3_rulings_{STAMP}.csv"
    say(f"  every flag needs a ruling (§4b). Proposal: dgl3_rulings_PROPOSAL_{STAMP}.csv (keys + recommended ruling; "
        f"ruled_by / ruled_on blank). The team lead signs it into {ruled.name}.")
    say(f"  rulings file {ruled.name}: {'PRESENT' if ruled.exists() else 'ABSENT: the fit refuses until the team lead rules'}")
    (HERE / f"dgl3_output_{STAMP}.txt").write_text("\n".join(lines) + "\n")
    return 0


NAV_JUMP, NAV_BACK, NAV_RUN, PX_FLAT = 0.05, 0.01, 3, 0.02


def nav_misprints(nav: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """A PROPOSED rule for the team lead (no P&L): a NAV misprint is a run of 1..NAV_RUN sessions whose NAV
    differs from the session before the run by >= NAV_JUMP, after which the NAV comes back within NAV_BACK of
    that prior NAV, while the close stays within PX_FLAT of its prior close on every day of the run (the
    market did not move; the vendor's NAV did). Returns one row per misprinted name-day."""
    out = []
    for t in nav.columns:
        n, c = nav[t].to_numpy(), close[t].reindex(nav.index).to_numpy()
        i = 1
        while i < len(n) - 1:
            if not (np.isfinite(n[i - 1]) and np.isfinite(n[i]) and n[i - 1] > 0):
                i += 1; continue
            base, cb = n[i - 1], c[i - 1]
            if abs(n[i] / base - 1) < NAV_JUMP:
                i += 1; continue
            for L in range(1, NAV_RUN + 1):
                j = i + L
                if j >= len(n) or not np.isfinite(n[j]):
                    break
                if abs(n[j] / base - 1) <= NAV_BACK:
                    run = range(i, j)
                    flat = all(np.isfinite(c[k]) and np.isfinite(cb) and abs(c[k] / cb - 1) < PX_FLAT for k in run)
                    if flat and all(abs(n[k] / base - 1) >= NAV_JUMP for k in run):
                        out += [dict(ticker=t, date=nav.index[k].date().isoformat(), nav_prior=float(base),
                                     nav=float(n[k]), nav_after=float(n[j]), run_len=L) for k in run]
                    break
            i += 1
    return pd.DataFrame(out, columns=["ticker", "date", "nav_prior", "nav", "nav_after", "run_len"])


def stage_navscan() -> int:
    lines = []
    say = lambda s="": (print(s), lines.append(s))
    U, pool, UF, px, nav, crsp, qr, fam = inputs()
    nv = nav.pivot_table(index="date", columns="ticker", values="nav").sort_index()
    cl = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    nv = nv.loc[:FIT_END, [t for t in UF if t in nv.columns]]
    M = nav_misprints(nv, cl)
    M = M[pd.to_datetime(M.date) >= pd.Timestamp("2004-01-01")]
    M.to_csv(HERE / f"nav_misprints_PROPOSED_{STAMP}.csv", index=False)
    F = pd.read_csv(HERE / f"dgl3_flags_{STAMP}.csv")
    keyF = set(zip(F.ticker, F.date))
    nxt = {}
    for t, g in F.groupby("ticker"):
        pass
    say(f"CEF trial 54, NAV-misprint scan ({STAMP}; no P&L): rule = NAV jumps >= {NAV_JUMP:.0%} for 1..{NAV_RUN} sessions "
        f"and returns within {NAV_BACK:.0%} of the prior NAV, the close within {PX_FLAT:.0%} of its prior close throughout")
    say(f"  the frozen 74's families NAVs, 2004-01-01..{FIT_END.date()}: {len(M)} misprinted name-days in "
        f"{M.groupby(['ticker', 'nav_prior']).ngroups if len(M) else 0} runs, {M.ticker.nunique() if len(M) else 0} funds")
    say(f"  of them among the 242 DG-L3 flags: {sum((t, d) in keyF for t, d in zip(M.ticker, M.date))}; "
        f"the rest were below the 10% flag line or on days whose price TR moved with the NAV")
    say("  by year: " + str(pd.to_datetime(M.date).dt.year.value_counts().sort_index().to_dict() if len(M) else {}))
    for _, r in M.head(40).iterrows():
        say(f"    {r.ticker} {r.date}: NAV {r.nav_prior:.2f} -> {r.nav:.2f} -> {r.nav_after:.2f} (run {r.run_len})")
    (HERE / f"navscan_output_{STAMP}.txt").write_text("\n".join(lines) + "\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["dgl2", "dgl3", "navscan"])
    a = ap.parse_args(argv)
    return {"dgl2": stage_dgl2, "dgl3": stage_dgl3, "navscan": stage_navscan}[a.stage]()


if __name__ == "__main__":
    raise SystemExit(main())
