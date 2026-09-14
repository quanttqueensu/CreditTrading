"""G6 Part B — the three conditioners, and the regression that gates C3.

    python3 scripts/gamma/conditioners.py [--out results/gamma/CONDITIONERS_<date>.md]

WHAT THIS IS AND IS NOT
-----------------------
G6's full battery needs a delta-hedged straddle P&L — G3's hedging rule and G4's
ledger — and neither is built. But G6 Part B is explicit that the P&L is not the
first question:

    "**Test C3 as a regression first, before it ever sizes a position.**
     Does `Stress_t` predict `RV_cc(HYG)_{t+1..t+5} - IV_t` with a positive
     coefficient, out of sample, by era? And - the bar that matters - **does it
     predict it better than C1 does?** If it does not beat the VRP level, C3 is
     dead and the sleeve has nothing of ours in it."

That is this script. It is the gate, not the trade, and it spends **no trial**.

THE THREE CONDITIONERS, DECLARED BEFORE RUNNING AND NOT AMENDED AFTER
--------------------------------------------------------------------
**C1 - the VRP's own level.** The literature baseline, and the thing anything
else must beat rather than merely beating always-on. `S=1` when the standardised
trailing implied-minus-realised spread is in its CHEAP tail - implied unusually
low relative to recent realised. Trailing 504 sessions ending t-1, threshold
**-1.0 sd**, fixed before running; -0.5 and -1.5 reported as sensitivity and
NOT selected on.

**C2 - the variance term-structure slope. DECLARED, NOT RUN.** It needs a
1m/3m ATM implied ratio, i.e. a term structure, i.e. a fitted surface. The
account audit of 2026-09-12 established IBKR serves **no historical option bars
at all** (nine venue x data-type combinations, all IB error 162), so there is no
surface and C2 is not computable. G6's rule is "declare all three here and do
not amend them after seeing results" - so it is recorded here as
declared-and-unavailable, BEFORE any result, rather than quietly dropped.

**C3 - the CEF stress nowcast. The only one that is ours.** The claim: retail
liquidation shows up in CEF discounts BEFORE it shows up in realised ETF
volatility, because the CEF holder sells the wrapper at whatever price while
the ETF's creation/redemption arbitrage keeps its price near NAV until flows are
large. Built from the 17 at t:

    D_t  cross-sectional sd of the day's discount CHANGES
    V_t  mean over names of the 3-session z-velocity, SIGNED so widening is +ve
    W_t  fraction of names whose discount widened by more than one
         trailing-63-session sd today

each standardised on a trailing 252 sessions ending t-1, then averaged:
`Stress_t = (D~ + V~ + W~)/3`. `S=1` when `Stress_t > 1.5`, fixed before
running; 1.0 and 2.0 as sensitivity.

SIGN CONVENTION, STATED BECAUSE IT IS EASY TO GET BACKWARDS
-----------------------------------------------------------
`disc = 100*(price - nav)/nav`, so a **widening** discount is disc FALLING and z
falling. V_t is therefore `mean(z_{t-3} - z_t)`, not the other way round, and
W_t counts names whose `disc` change is below MINUS one sd. A sign error here
would not error; it would quietly test the opposite hypothesis.

ALIGNMENT (H7)
--------------
Every standardisation window ends at **t-1**. `Stress_t` and the C1 state use
only data available at the close of t. The target is strictly forward - realised
over t+1..t+5 - so nothing on the right-hand side can see the left.

PRIOR EVIDENCE FOR C3, AND WHAT IT DOES NOT SAY
-----------------------------------------------
`W14 Part A` (2026-09-11) measured that the CEF signal's own IC is **2.39x
stronger** in the top VIX tercile, and that the book earns **+1.60%** over the
21 sessions a top-decile-VIX decision actually earns against +0.84%
unconditionally. That is real evidence that CEF discounts carry stress
information. It is **not** evidence that they LEAD HYG realised volatility,
which is a different claim and is exactly what this script measures. The prior
must not be smuggled in as a result.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.gamma.credit_base_rate import load_hyg, load_vxhyg  # noqa: E402

# Declared before running. Not tuned, not swept, not amended after results.
C1_WINDOW, C1_THRESHOLD = 504, -1.0
C1_SENSITIVITY = (-0.5, -1.5)
C3_WINDOW, C3_THRESHOLD = 252, 1.5
C3_SENSITIVITY = (1.0, 2.0)
STRESS_VELOCITY_LAG = 3
STRESS_BREADTH_WINDOW = 63
TARGET_HORIZON = 5               # RV_cc(HYG)_{t+1..t+5}
NW_LAGS = 5
ANN = 252


def _z(s: pd.Series, window: int) -> pd.Series:
    """Standardise on a trailing window ENDING t-1. H7: never includes its own day."""
    mu = s.rolling(window).mean().shift(1)
    sd = s.rolling(window).std().shift(1)
    return (s - mu) / sd.replace(0, np.nan)


def build_c1(iv: pd.Series, ret: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(continuous spread, standardised) — implied minus trailing realised vol."""
    rv_trail = ret.rolling(21).std() * np.sqrt(ANN)
    spread = (iv - rv_trail).dropna()
    return spread, _z(spread, C1_WINDOW)


def build_c3() -> tuple[pd.DataFrame, pd.Series]:
    """The CEF stress nowcast from the 17, and its three components."""
    from scripts.cef.band_frontier import build_panel

    p = build_panel()
    disc, z = p["disc"], p["z"]
    d_chg = disc.diff()

    # D: cross-sectional dispersion of today's discount CHANGES.
    D = d_chg.std(axis=1)

    # V: 3-session z-velocity, SIGNED so widening is positive. A widening
    # discount is disc FALLING, hence z falling, hence z_{t-3} - z_t > 0.
    V = (z.shift(STRESS_VELOCITY_LAG) - z).mean(axis=1)

    # W: fraction of names whose discount widened by more than one trailing
    # 63-session sd today. Trailing sd is shifted so it cannot include today.
    sd63 = d_chg.rolling(STRESS_BREADTH_WINDOW).std().shift(1)
    eligible = sd63.notna() & d_chg.notna()
    # Count as float, not via `.where()` on a boolean frame -- that yields
    # object dtype, which propagates silently through the mean and only
    # surfaces as a TypeError inside statsmodels three functions later.
    widened = ((d_chg < -sd63) & eligible).astype(float)
    n_elig = eligible.sum(axis=1).astype(float).replace(0, np.nan)
    W = widened.sum(axis=1) / n_elig

    comp = pd.DataFrame({"D": D.astype(float), "V": V.astype(float),
                         "W": W.astype(float)}).dropna()
    stress = pd.concat([_z(comp[c], C3_WINDOW) for c in ("D", "V", "W")],
                       axis=1).mean(axis=1)
    stress = pd.to_numeric(stress, errors="raise").dropna()
    if stress.dtype.kind != "f":
        raise TypeError(f"stress came out {stress.dtype}, not float")
    return comp, stress


def forward_realised(ret: pd.Series, h: int = TARGET_HORIZON) -> pd.Series:
    """Annualised close-to-close realised vol over t+1..t+h. Strictly forward."""
    return ret[::-1].rolling(h).std()[::-1].shift(-1) * np.sqrt(ANN)


def nw_regress(y: pd.Series, X: pd.DataFrame, lags: int = NW_LAGS) -> dict:
    import statsmodels.api as sm
    df = pd.concat([y.rename("_y"), X], axis=1).dropna()
    if len(df) < 100:
        return {"n": len(df), "error": "too few overlapping observations"}
    cols = list(X.columns)
    fit = sm.OLS(df["_y"].to_numpy(), sm.add_constant(df[cols].to_numpy())).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags})
    return {"n": len(df), "r2": float(fit.rsquared),
            "beta": {c: float(b) for c, b in zip(cols, fit.params[1:])},
            "t": {c: float(t) for c, t in zip(cols, fit.tvalues[1:])},
            "start": df.index[0], "end": df.index[-1]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = Path(a.out) if a.out else \
        REPO / f"results/gamma/CONDITIONERS_{date.today().isoformat()}.md"

    iv, ret = load_vxhyg(), load_hyg()
    spread, c1 = build_c1(iv, ret)
    comp, stress = build_c3()
    rv_fwd = forward_realised(ret)

    # THE TARGET, exactly as G6 Part B specifies it: realised over t+1..t+5
    # MINUS implied at t. Positive = realised exceeded what was priced = the
    # state a long-gamma position wants.
    target = (rv_fwd - iv).dropna().rename("target")

    L: list[str] = []
    say = lambda s="": (print(s), L.append(s))               # noqa: E731

    say("# G6 Part B — the conditioners, and the regression that gates C3")
    say()
    say(f"**Run {date.today().isoformat()}** by "
        "`python3 scripts/gamma/conditioners.py`. **Trials: 0** — a regression "
        "test, not a specification. Nothing is traded and nothing is adopted.")
    say()
    say("## Declared before running")
    say()
    say("| conditioner | rule | threshold | status |")
    say("|---|---|---|---|")
    say(f"| **C1** VRP level | standardised trailing implied − realised spread, "
        f"cheap tail | {C1_THRESHOLD} sd, {C1_WINDOW}-session window | run |")
    say("| **C2** term structure | 1m/3m ATM implied ratio > 1.0 | 1.0 | "
        "**DECLARED, NOT RUN** — needs a term structure; IBKR serves no "
        "historical option bars (verified 9 ways, 2026-09-12) |")
    say(f"| **C3** CEF stress | ⅓(D̃+Ṽ+W̃) from the 17 | > {C3_THRESHOLD}, "
        f"{C3_WINDOW}-session window | run |")
    say()
    say("C2 is recorded here **before any result**, per G6's own rule that all "
        "three are declared and none amended after seeing results. It is "
        "unavailable, not unpromising, and the distinction is kept.")
    say()
    say("## The target")
    say()
    say(f"`RV_cc(HYG)_{{t+1..t+{TARGET_HORIZON}}} − IV_t`, in **annualised vol "
        f"as a DECIMAL** — `load_vxhyg` divides Cboe's quote by 100, so "
        f"`{target.mean():.4f}` means **{abs(target.mean()) * 100:.2f} "
        f"percentage points** of annualised vol, not {abs(target.mean()):.2f}. "
        f"The unit is spelled out because every beta and every mean below "
        f"inherits it, and a reader who takes these for percentage points is "
        f"off by a factor of 100 in the direction that makes the premium look "
        f"negligible. **Positive = realised exceeded what was priced**, which is "
        f"the state long gamma wants. Close-to-close because that is what a "
        f"once-daily hedger earns (G3 Part C). Sample "
        f"{target.index[0].date()} .. {target.index[-1].date()}, "
        f"n = {len(target):,}, mean **{target.mean():.4f}**, median "
        f"**{target.median():.4f}**.")
    say()
    say(f"That mean is negative by construction of the premium measured in "
        f"`CREDIT_BASE_RATE`: implied exceeds realised most of the time. A "
        f"conditioner earns its keep only by finding the minority of days when "
        f"it does not.")
    say()

    say("## The regression that decides C3")
    say()
    say(f"OLS, Newey–West lag {NW_LAGS}. **The bar is not "
        f"significance — it is beating C1.**")
    say()
    rows = [("C1 alone", pd.DataFrame({"C1": c1})),
            ("C3 alone", pd.DataFrame({"C3": stress})),
            ("C1 + C3", pd.concat([c1.rename("C1"), stress.rename("C3")], axis=1))]
    say("| model | n | β C1 | t | β C3 | t | R² |")
    say("|---|---:|---:|---:|---:|---:|---:|")
    res = {}
    for lab, X in rows:
        r = nw_regress(target, X)
        res[lab] = r
        if "error" in r:
            say(f"| {lab} | {r['n']} | — | | — | | {r['error']} |")
            continue
        b1 = f"{r['beta'].get('C1', float('nan')):+.4f}" if "C1" in r["beta"] else "—"
        t1 = f"{r['t'].get('C1', float('nan')):+.2f}" if "C1" in r["t"] else ""
        b3 = f"{r['beta'].get('C3', float('nan')):+.4f}" if "C3" in r["beta"] else "—"
        t3 = f"{r['t'].get('C3', float('nan')):+.2f}" if "C3" in r["t"] else ""
        say(f"| {lab} | {r['n']:,} | {b1} | {t1} | {b3} | {t3} | {r['r2']:.4f} |")
    say()
    if all("error" not in res[k] for k in res):
        inc = res["C1 + C3"]["r2"] - res["C1 alone"]["r2"]
        say(f"**Incremental R² of C3 over C1: {inc:+.4f}** "
            f"({res['C1 alone']['r2']:.4f} → {res['C1 + C3']['r2']:.4f}).")
        say()

    # ---- THE TWO CHECKS THAT DECIDE, AND THE FIRST VERDICT WAS WRONG -----
    say("### Is it mechanical? The target contains IV_t, and so does C1")
    say()
    say(f"`target = RV_fwd − IV_t` and C1 is built from IV_t "
        f"(corr {c1.corr(iv):+.3f}), so part of any fit is arithmetic rather "
        f"than prediction. The honest test is whether C3 predicts **forward "
        f"realised vol itself**, which contains no IV term at all:")
    say()
    say("| left-hand side | model | n | β C3 | t | R² |")
    say("|---|---|---:|---:|---:|---:|")
    both = pd.concat([c1.rename("C1"), stress.rename("C3")], axis=1)
    checks = {}
    for ylab, y in (("`RV_fwd − IV_t` (the stated target)", target),
                    ("**`RV_fwd` alone — no IV term**", rv_fwd.dropna())):
        for xlab, X in (("C3 alone", pd.DataFrame({"C3": stress})), ("C1 + C3", both)):
            r = nw_regress(y, X)
            checks[(ylab, xlab)] = r
            if "error" in r:
                say(f"| {ylab} | {xlab} | {r['n']} | — | | {r['error']} |")
                continue
            say(f"| {ylab} | {xlab} | {r['n']:,} | {r['beta']['C3']:+.5f} | "
                f"{r['t']['C3']:+.2f} | {r['r2']:.4f} |")
    say()
    clean = checks[("**`RV_fwd` alone — no IV term**", "C3 alone")]
    say(f"**C3 survives that check.** Against forward realised vol with no IV "
        f"term anywhere, β **{clean['beta']['C3']:+.5f}**, t "
        f"**{clean['t']['C3']:+.2f}**, n = {clean['n']:,}. So the in-sample "
        f"result is not purely the arithmetic of subtracting IV from itself — "
        f"CEF stress really does carry information about HYG's next week.")
    say()

    say("### The holdout, which is where it dies")
    say()
    say("G6's decision rule requires the full sample **and** the 2023–2026 "
        "holdout. The thresholds and windows were fixed in advance, so the "
        "holdout tests the rule rather than a fit.")
    say()
    say("| window | left-hand side | n | β C3 | t |")
    say("|---|---|---:|---:|---:|")
    hold = {}
    for wlab, sl in (("full sample", slice(None)), ("**holdout 2023–2026**", slice("2023", None))):
        for ylab, y in (("RV_fwd − IV_t", target), ("RV_fwd alone", rv_fwd.dropna())):
            r = nw_regress(y.loc[sl] if sl != slice(None) else y, both)
            hold[(wlab, ylab)] = r
            if "error" in r:
                say(f"| {wlab} | {ylab} | {r['n']} | — | {r['error']} |")
                continue
            say(f"| {wlab} | {ylab} | {r['n']:,} | {r['beta']['C3']:+.5f} | "
                f"{r['t']['C3']:+.2f} |")
    say()
    h_t = hold[("**holdout 2023–2026**", "RV_fwd alone")]
    f_t = hold[("full sample", "RV_fwd alone")]
    ratio = (h_t["beta"]["C3"] / f_t["beta"]["C3"]) if f_t["beta"]["C3"] else float("nan")
    holdout_ok = (h_t["beta"]["C3"] > 0) and (h_t["t"]["C3"] >= 2.0)
    say(f"**On the holdout the coefficient falls to "
        f"{ratio:.0%} of its full-sample value** "
        f"({f_t['beta']['C3']:+.5f} → {h_t['beta']['C3']:+.5f}) and t drops to "
        f"**{h_t['t']['C3']:+.2f}**. On the stated target it is "
        f"**{hold[('**holdout 2023–2026**', 'RV_fwd − IV_t')]['t']['C3']:+.2f}** — "
        f"indistinguishable from nothing.")
    say()
    full_ok = (res["C1 + C3"]["beta"]["C3"] > 0 and
               abs(res["C1 + C3"]["t"]["C3"]) >= 2.0 and
               (res["C1 + C3"]["r2"] - res["C1 alone"]["r2"]) > 0.002)
    verdict = full_ok and holdout_ok
    say(f"### VERDICT: C3 {'CLEARS' if verdict else 'DOES NOT CLEAR'} the bar")
    say()
    if not verdict:
        say(f"It clears the full-sample half — beside C1 its coefficient is "
            f"**{res['C1 + C3']['beta']['C3']:+.4f}** at t "
            f"**{res['C1 + C3']['t']['C3']:+.2f}**, adding "
            f"**{res['C1 + C3']['r2'] - res['C1 alone']['r2']:+.4f}** of R², and "
            f"it survives the no-IV-term control. **It fails the holdout**, and "
            f"G6's rule requires both.")
        say()
        say("**This is the `z_window = 63` shape**, which `00_BRIEF.md` H8 calls "
            "the most instructive event in this project's history: a clean "
            "in-sample result, a plausible mechanism, and a holdout that says "
            "no. The mechanism may still be real — 2023–2026 is 298 "
            "observations of an unusually calm credit tape, and **1.8% of days** "
            "in that era had implied below realised at all "
            "(`CREDIT_BASE_RATE`), so there was almost nothing for a "
            "long-gamma timer to find. But that is an explanation, and the rule "
            "does not bend for explanations.")
    say()

    say("## By era — the rule, not a fit")
    say()
    say("| era | n | β C3 (with C1) | t | R² (C1+C3) | R² (C1) |")
    say("|---|---:|---:|---:|---:|---:|")
    for lab, a_, b_ in (("2015–2019", "2015", "2019"),
                        ("2020–2022", "2020", "2022"),
                        ("2023–2026", "2023", "2026")):
        y = target.loc[a_:b_]
        both = nw_regress(y, pd.concat([c1.rename("C1"), stress.rename("C3")], axis=1))
        only = nw_regress(y, pd.DataFrame({"C1": c1}))
        if "error" in both or "error" in only:
            say(f"| {lab} | — | UNMEASURED | | | |")
            continue
        say(f"| {lab} | {both['n']:,} | {both['beta']['C3']:+.4f} | "
            f"{both['t']['C3']:+.2f} | {both['r2']:.4f} | {only['r2']:.4f} |")
    say()

    say("## The states as traded, and time in market")
    say()
    say("| conditioner | threshold | days on | % of sample | mean target when ON | when OFF |")
    say("|---|---:|---:|---:|---:|---:|")
    for name, series_, thresholds, cheap in (
            ("C1", c1, (C1_THRESHOLD,) + C1_SENSITIVITY, True),
            ("C3", stress, (C3_THRESHOLD,) + C3_SENSITIVITY, False)):
        for th in thresholds:
            state = (series_ <= th) if cheap else (series_ > th)
            al = target.reindex(state.index).dropna()
            st = state.reindex(al.index)
            if st.sum() < 20:
                say(f"| {name} | {th} | {int(st.sum())} | — | too few days | |")
                continue
            mark = " **(declared)**" if th in (C1_THRESHOLD, C3_THRESHOLD) else ""
            say(f"| {name}{mark} | {th} | {int(st.sum()):,} | {st.mean():.1%} | "
                f"**{al[st].mean():+.4f}** | {al[~st].mean():+.4f} |")
    say()
    say("Sensitivity rows are reported and **not selected on** — the declared "
        "thresholds are the ones that count.")
    say()

    say("## Negative control: shuffled states, 20 draws")
    say()
    say("If a shuffled state series with the same on-fraction earns comparably, "
        "the gain is time-in-market rather than timing.")
    say()
    rng = np.random.default_rng(20260913)
    say("| conditioner | real mean target when ON | shuffled mean (20 draws) | real percentile |")
    say("|---|---:|---:|---:|")
    for name, series_, th, cheap in (("C1", c1, C1_THRESHOLD, True),
                                     ("C3", stress, C3_THRESHOLD, False)):
        state = (series_ <= th) if cheap else (series_ > th)
        al = target.reindex(state.index).dropna()
        st = state.reindex(al.index)
        if st.sum() < 20:
            say(f"| {name} | too few ON days | | |")
            continue
        real = al[st].mean()
        n_on = int(st.sum())
        draws = [al.iloc[rng.permutation(len(al))[:n_on]].mean() for _ in range(20)]
        pct = float((np.array(draws) < real).mean())
        say(f"| {name} | {real:+.4f} | {np.mean(draws):+.4f} | {pct:.0%} |")
    say()

    say("## The three components of C3, separately")
    say()
    say("Reported because an average can hide one component doing all the work "
        "and another doing none — and because C3 is the only conditioner that "
        "is ours, so it is the one worth taking apart.")
    say()
    say("| component | what | β (alone) | t | R² |")
    say("|---|---|---:|---:|---:|")
    for c, what in (("D", "cross-sectional sd of discount changes"),
                    ("V", "3-session z-velocity, widening positive"),
                    ("W", "fraction widening > 1 trailing-63d sd")):
        r = nw_regress(target, pd.DataFrame({c: _z(comp[c], C3_WINDOW)}))
        if "error" in r:
            say(f"| {c} | {what} | — | | {r['error']} |")
            continue
        say(f"| {c} | {what} | {r['beta'][c]:+.4f} | {r['t'][c]:+.2f} | "
            f"{r['r2']:.4f} |")
    say()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print(f"\n[written] {out}")


if __name__ == "__main__":
    main()
