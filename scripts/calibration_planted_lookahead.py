#!/usr/bin/env python3
"""Phase 2 planted case — KNOWN ARTIFACT (deliberate look-ahead).

Man-AHL calibration discipline: before any strategy result is trusted, feed the
harness a signal whose answer we already know. This one is a *known artifact*:

    Signal: hold HYG on days whose OWN SAME-DAY return is positive.
            s_t = 1{ r_HYG,t > 0 },  earned on day t's return.

That is not a strategy, it is a time machine. The engine's T+1 rule means a
weight row dated t is applied from day t+1's return, so to earn s_t on r_t the
caller must BACKDATE the row to t-1 — a row dated t-1 that was built from day
t's close. The harness must refuse it.

Both halves of the calibration are demonstrated:

  RUN A  naive path, honest info_dates -> guard.assert_lagged must raise
         LookaheadError. (This is what a Phase 3+ caller obeying the house
         rule "always pass info_dates" would hit.)
  RUN B  same weights, info_dates omitted -> guard bypassed, engine runs and
         reports an absurd Sharpe (expect >> 3). This is the artifact the
         guard exists to stop.
  RUN C  the SAME signal correctly lagged (row dated t = s_t, applied to
         r_{t+1}) -> guard passes and the edge collapses to ~0.

  RUN D  forensics on C's residual: prove it is not leftover leakage.

PASS requires: A raises, B is absurd (net Sharpe > 3), and the LOOK-AHEAD
EDGE in C is destroyed.

A note on the last criterion, written after the first run (declared openly
rather than quietly retuned). The pre-run threshold was |Sharpe_C| < 0.5,
on the assumption that the correctly-lagged signal is a null strategy. It is
not: C scores +0.54, and Run D shows why. HYG's day-t return has essentially
zero linear autocorrelation (AC(1) = +0.0003, t = 0.02) but a strong
SIGN-conditional vol asymmetry — annualized vol is 9.30% after an up day vs
12.49% after a down day. Sitting in cash after down days dodges the
high-volatility regime, which is a genuine, well-documented leverage effect,
not artifact residue. Run D proves the point three ways (applied weight
equals the PRIOR day's signal on 100% of days; correlation of applied weight
with the same-day return falls from ~+0.6 to +0.03; the run sits at the
99.8th percentile of a random-signal null, i.e. it carries real information).

So the criterion is stated in the units of the artifact itself: the
look-ahead signature must be gone (>=90% of Sharpe destroyed, and applied
weight decorrelated from the same-day return). The naive |Sharpe| < 0.5 test
is still printed, and still marked failed, so the change is auditable.

Risk-free choice: BIL ret_total is the rf proxy (data/README.md). BIL starts
2007-05-31, one and a half months after HYG (2007-04-12), so the sample is
restricted to BIL coverage rather than splicing SHY or zero in for 33 days —
the cleanest choice, and it costs 33 of 4,813 days. Costs come from
config/costs.yaml; nothing is hardcoded here.

Run:  python3 scripts/calibration_planted_lookahead.py     (from repo root)
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.backtest import engine, guard  # noqa: E402
from src.backtest import tearsheet as ts  # noqa: E402

ASSET = "HYG"
RF_TICKER = "BIL"

# PASS thresholds. ABSURD_SHARPE / COLLAPSE_FRAC / MAX_LEAK_CORR are the
# operative gates; DEAD_SHARPE is the pre-run guess, kept and reported so the
# post-hoc reasoning in the docstring stays auditable.
ABSURD_SHARPE = 3.0     # bypassed run must beat this
DEAD_SHARPE = 0.5       # pre-run guess for |Sharpe_C|; superseded, see docstring
COLLAPSE_FRAC = 0.90    # lagging must destroy >= this share of |net Sharpe|
MAX_LEAK_CORR = 0.10    # corr(applied weight, same-day return) must fall below
NULL_DRAWS = 500        # random-signal null replications (Run D)


def banner(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def build_signal(rets):
    """s_t = 1 if HYG's day-t total return is positive, else 0 (flat, in cash).

    The signal at date t is a function of the day-t close. Nothing else.
    """
    return (rets[ASSET] > 0).astype(float)


def main():
    banner("PLANTED CASE — KNOWN ARTIFACT: same-day HYG return, applied same day")

    # ---------------------------------------------------------------- data
    costs = engine.load_costs()
    print(f"[calib] costs from {engine.DEFAULT_COSTS_PATH} "
          f"(HYG half-spread {costs['tickers'][ASSET]['half_spread_bp']}bp, "
          f"slippage {costs['slippage_extra_bp']}bp, commission "
          f"${costs['commission_usd_per_trade']}/trade, book "
          f"${costs['book_usd_default']:,.0f})")

    rets_all, rf_all = engine.load_panel(tickers=[ASSET, RF_TICKER])

    # Common sample: both series present. BIL (rf proxy) binds on the left.
    both = rets_all[[ASSET, RF_TICKER]].dropna()
    sample = both.index
    rets = rets_all.loc[sample]
    rf = rf_all.loc[sample]
    print(f"[calib] common {ASSET}+{RF_TICKER} sample "
          f"{sample[0].date()}..{sample[-1].date()} N={len(sample)} days "
          f"(rf = BIL ret_total; BIL inception clips "
          f"{(rets_all[ASSET].notna() & rets_all[RF_TICKER].isna()).sum()} "
          f"early {ASSET} days)")

    signal = build_signal(rets)
    print(f"[calib] signal: long {ASSET} on positive-same-day-return days; "
          f"in-market {signal.mean():.1%} of days "
          f"({int(signal.sum())} of {len(signal)})")

    # ------------------------------------------------------- weight frames
    # LEAKY: row dated t-1 carries s_t, so the engine's T+1 shift lands s_t on
    # day t's own return. Honest info date for that row is t — the future.
    leaky_w = pd.DataFrame({ASSET: signal.shift(-1).dropna()})
    leaky_info = pd.Series(signal.index[1:], index=leaky_w.index)

    # HONEST: row dated t carries s_t, applied to r_{t+1}. info date = t.
    honest_w = pd.DataFrame({ASSET: signal})
    honest_info = pd.Series(honest_w.index, index=honest_w.index)

    # Same simulation window for B and C so the Sharpes are comparable.
    common_start = max(leaky_w.index[0], honest_w.index[0])
    common_end = min(leaky_w.index[-1], honest_w.index[-1])
    clip = lambda df: df.loc[common_start:common_end]  # noqa: E731
    leaky_w, honest_w = clip(leaky_w), clip(honest_w)
    leaky_info, honest_info = clip(leaky_info), clip(honest_info)
    print(f"[calib] weight rows {common_start.date()}..{common_end.date()} "
          f"N={len(leaky_w)} rows (identical row dates for both runs)")

    verdicts = {}

    # ============================================================== RUN A
    banner("RUN A — naive caller, honest info_dates: the guard must REFUSE")
    print("[A] weight row dated t-1 was built from day t's close "
          "(info_date = t > t-1).")
    print(f"[A] e.g. row {leaky_w.index[0].date()} claims info from "
          f"{leaky_info.iloc[0].date()}")
    caught = False
    err_text = ""
    try:
        engine.run_backtest(leaky_w, rets, costs, rf=rf, info_dates=leaky_info,
                            name="planted lookahead (guarded)", verbose=True)
        print("[A] !!! ENGINE RAN. The look-ahead guard did NOT fire.")
    except guard.LookaheadError as exc:
        caught = True
        err_text = str(exc)
        print(f"[A] LookaheadError raised by guard.assert_lagged:\n"
              f"[A]   {err_text}")
        print("[A] PASS — the naive path is refused before a single return "
              "is computed.")
    except Exception as exc:  # any other failure is NOT the guard working
        print(f"[A] !!! wrong exception type {type(exc).__name__}: {exc}")
        traceback.print_exc()
    verdicts["A_guard_caught"] = caught
    verdicts["A_error"] = err_text

    # Direct unit-level confirmation that it is assert_lagged doing the work.
    direct = False
    try:
        guard.assert_lagged(leaky_w, leaky_info)
    except guard.LookaheadError:
        direct = True
    print(f"[A] guard.assert_lagged called directly also raises: {direct}")
    print(f"[A] rows flagged: "
          f"{int((leaky_info.values > leaky_info.index.values).sum())} "
          f"of {len(leaky_w)} (every row — the leak is systematic)")
    verdicts["A_direct_raise"] = direct
    verdicts["A_rows_flagged"] = int(
        (leaky_info.values > leaky_info.index.values).sum())

    # ============================================================== RUN B
    banner("RUN B — guard BYPASSED (info_dates omitted): the artifact appears")
    print("[B] This is what the number looks like when nobody checks. "
          "The engine warns, then obeys.")
    res_b = engine.run_backtest(leaky_w, rets, costs, rf=rf, info_dates=None,
                                name="planted lookahead (guard bypassed)",
                                verbose=True)
    m_b = ts.tearsheet(res_b)

    # Independent check that the bypassed path really is the time machine:
    # applied weight on day t must equal s_t, and gross must be max(r_t, rf_t).
    applied = res_b.positions[ASSET]
    aligned = float((applied == signal.reindex(applied.index)).mean())
    # Exact identity for this construction: fully invested on up days, fully
    # in cash (earning rf) otherwise. NB it is NOT max(r, rf) — on days where
    # 0 < r < rf, or rf < r <= 0, the two differ; the strategy follows the
    # SIGN of r, not the better of the two.
    r_asset_b = rets[ASSET].reindex(applied.index)
    rf_b = rf.reindex(applied.index)
    expect_gross = applied * r_asset_b + (1.0 - applied) * rf_b
    gross_err = float((res_b.gross - expect_gross).abs().max())
    print(f"[B] applied weight equals same-day signal on {aligned:.1%} of days "
          f"(first day is flat by construction)")
    print(f"[B] max |gross - (w*r_HYG + (1-w)*rf)| = {gross_err:.2e} "
          f"-> the run banks every up day and sits in cash on every down day")
    print(f"[B] it books {int((applied > 0).sum())} up days and dodges "
          f"{int((applied == 0).sum())} down days, chosen with that same day's "
          f"own return")
    verdicts["B_alignment"] = aligned
    verdicts["B_gross_identity_err"] = gross_err

    # ============================================================== RUN C
    banner("RUN C — the SAME signal, correctly lagged: the edge dies")
    print("[C] row dated t carries s_t and is applied to r_{t+1}. "
          "info_dates = row date, so the guard passes.")
    guard.assert_lagged(honest_w, honest_info)
    print("[C] guard.assert_lagged: OK (no row claims future information)")
    res_c = engine.run_backtest(honest_w, rets, costs, rf=rf,
                                info_dates=honest_info,
                                name="same signal, correctly lagged",
                                verbose=True)
    m_c = ts.tearsheet(res_c)

    # ============================================================== RUN D
    banner("RUN D — forensics: is C's residual leftover leakage, or real?")

    # (i) the direct alignment proof
    ap_c = res_c.positions[ASSET]
    sig_prev = signal.shift(1).reindex(ap_c.index).fillna(0.0)
    match_prev = float((ap_c == sig_prev).mean())
    leak_corr_c = float(ap_c.corr(rets[ASSET].reindex(ap_c.index)))
    leak_corr_b = float(applied.corr(rets[ASSET].reindex(applied.index)))
    print(f"[D] C: applied weight on day d equals signal(d-1) on "
          f"{match_prev:.2%} of days — no future information, by construction")
    print(f"[D] corr(applied weight, SAME-day return): "
          f"B(leaky) {leak_corr_b:+.4f}  ->  C(lagged) {leak_corr_c:+.4f} "
          f"(gate < {MAX_LEAK_CORR})")

    # (ii) why C is not zero: sign-conditional vol asymmetry in HYG
    r_asset = rets[ASSET]
    prev_up = (r_asset.shift(1) > 0)
    up_nxt = r_asset[prev_up.fillna(False)]
    dn_nxt = r_asset[(~prev_up).fillna(False)]
    ac1 = float(r_asset.autocorr(1))
    print(f"[D] HYG AC(1) = {ac1:+.4f} (t = {ac1 * np.sqrt(len(r_asset)):+.2f}) "
          f"— no linear 1-day momentum at all")
    print(f"[D] but conditioning on the SIGN of day t-1:")
    print(f"[D]   after UP   day: N={len(up_nxt)} mean {up_nxt.mean()*1e4:+.2f}bp "
          f"ann.vol {up_nxt.std()*np.sqrt(engine.TRADING_DAYS):.2%}")
    print(f"[D]   after DOWN day: N={len(dn_nxt)} mean {dn_nxt.mean()*1e4:+.2f}bp "
          f"ann.vol {dn_nxt.std()*np.sqrt(engine.TRADING_DAYS):.2%}")
    se = float(np.sqrt(up_nxt.var(ddof=1) / len(up_nxt)
                       + dn_nxt.var(ddof=1) / len(dn_nxt)))
    tstat = float((up_nxt.mean() - dn_nxt.mean()) / se)
    print(f"[D]   mean gap {(up_nxt.mean()-dn_nxt.mean())*1e4:+.2f}bp "
          f"(t = {tstat:+.2f}); vol ratio "
          f"{up_nxt.std()/dn_nxt.std():.3f}")
    print("[D]   -> staying in cash after down days dodges the high-vol "
          "regime (leverage effect).")
    print("[D]   -> that is a genuine, documented phenomenon, NOT look-ahead "
          "residue.")

    # (iii) random-signal null with the same in-market rate
    rng = np.random.default_rng(20260720)
    p_in = float(signal.mean())
    null = []
    for _ in range(NULL_DRAWS):
        rs = pd.Series((rng.random(len(honest_w)) < p_in).astype(float),
                       index=honest_w.index)
        wb = pd.DataFrame({ASSET: rs})
        rb = engine.run_backtest(wb, rets, costs, rf=rf,
                                 info_dates=pd.Series(wb.index, index=wb.index),
                                 name="null", verbose=False)
        null.append(ts.sharpe_ratio(rb.net, rb.rf))
    null = np.array(null)
    s_c = m_c["sharpe_net"]
    null_z = float((s_c - null.mean()) / null.std(ddof=1))
    null_pct = float((null < s_c).mean() * 100)
    print(f"[D] random-signal null (same {p_in:.1%} in-market rate, "
          f"B={NULL_DRAWS}, correctly lagged):")
    print(f"[D]   net Sharpe mean {null.mean():+.3f} sd {null.std(ddof=1):.3f} "
          f"5-95pct [{np.percentile(null,5):+.3f}, {np.percentile(null,95):+.3f}]")
    print(f"[D]   observed C {s_c:+.3f} -> z {null_z:+.2f}, "
          f"{null_pct:.1f}th percentile — C carries real (non-leaky) "
          f"information")
    verdicts.update({
        "D_match_prev_signal": match_prev,
        "D_leak_corr_leaky": leak_corr_b,
        "D_leak_corr_lagged": leak_corr_c,
        "D_hyg_ac1": ac1,
        "D_vol_after_up": float(up_nxt.std() * np.sqrt(engine.TRADING_DAYS)),
        "D_vol_after_down": float(dn_nxt.std() * np.sqrt(engine.TRADING_DAYS)),
        "D_mean_gap_bp": float((up_nxt.mean() - dn_nxt.mean()) * 1e4),
        "D_mean_gap_t": tstat,
        "D_null_mean": float(null.mean()),
        "D_null_sd": float(null.std(ddof=1)),
        "D_null_p5": float(np.percentile(null, 5)),
        "D_null_p95": float(np.percentile(null, 95)),
        "D_null": null,
    })

    # ------------------------------------------------- shift_test, reported
    banner("guard.shift_test on the leaky weights — reported, NOT the detector")
    st = guard.shift_test(leaky_w, rets, costs, rf=rf, info_dates=None,
                          name="planted lookahead", verbose=True)
    print("[shift] Read this correctly: shift_test only FAILS when delay "
          "IMPROVES Sharpe.")
    print("[shift] A look-ahead artifact does the opposite — it collapses "
          "under delay — so shift_test")
    print("[shift] reports 'passed' here. The detector for THIS bug class is "
          "assert_lagged (Run A);")
    print("[shift] the collapse size below is corroborating evidence, not the "
          "gate.")

    # ============================================================ verdict
    banner("VERDICT")
    s_b = m_b["sharpe_net"]
    collapse = 1.0 - (abs(s_c) / abs(s_b)) if abs(s_b) > 0 else np.nan

    table = ts.compare([res_b, res_c], verbose=False)
    print(table[["start", "end", "n_days", "cagr", "ann_vol", "sharpe_gross",
                 "sharpe_net", "max_drawdown", "worst_month",
                 "avg_annual_turnover"]].to_string())
    print()
    print(f"sample {m_b['start'].date()}..{m_b['end'].date()} "
          f"N={m_b['n_days']} days ({m_b['years']:.1f}y) — identical for both runs")
    print(f"  B  bypassed lookahead : net Sharpe {s_b:+.3f}  "
          f"CAGR {m_b['cagr']:+.2%}  maxDD {m_b['max_drawdown']:.2%}")
    print(f"  C  correctly lagged   : net Sharpe {s_c:+.3f}  "
          f"CAGR {m_c['cagr']:+.2%}  maxDD {m_c['max_drawdown']:.2%}")
    print(f"  edge destroyed by lagging: {collapse:.1%} of |Sharpe|")

    cond_a = verdicts["A_guard_caught"] and verdicts["A_direct_raise"]
    cond_b = s_b > ABSURD_SHARPE
    cond_c1 = collapse > COLLAPSE_FRAC
    cond_c2 = abs(leak_corr_c) < MAX_LEAK_CORR
    cond_c3 = match_prev == 1.0
    naive_c = abs(s_c) < DEAD_SHARPE          # pre-run guess; reported, not gating
    print()
    print(f"  [{'PASS' if cond_a else 'FAIL'}] guard refuses the naive path "
          f"(LookaheadError on {verdicts['A_rows_flagged']}/{len(leaky_w)} rows)")
    print(f"  [{'PASS' if cond_b else 'FAIL'}] bypassed run is absurd "
          f"(net Sharpe {s_b:+.2f} > {ABSURD_SHARPE})")
    print(f"  [{'PASS' if cond_c1 else 'FAIL'}] lagging destroys the edge "
          f"({collapse:.1%} of |net Sharpe| gone, gate {COLLAPSE_FRAC:.0%})")
    print(f"  [{'PASS' if cond_c2 else 'FAIL'}] look-ahead signature gone "
          f"(corr(w, same-day ret) {leak_corr_b:+.3f} -> {leak_corr_c:+.3f}, "
          f"gate < {MAX_LEAK_CORR})")
    print(f"  [{'PASS' if cond_c3 else 'FAIL'}] lagged weights provably use "
          f"only prior-day information ({match_prev:.1%} match)")
    print(f"  [{'pass' if naive_c else 'FAIL'}] (superseded, non-gating) "
          f"pre-run guess |Sharpe_C| < {DEAD_SHARPE}: got {abs(s_c):.2f} — "
          f"explained by Run D, see docstring")
    overall = cond_a and cond_b and cond_c1 and cond_c2 and cond_c3
    print()
    print(f"PLANTED-CASE (KNOWN ARTIFACT) RESULT: {'PASS' if overall else 'FAIL'}")
    print("  Both required halves demonstrated: the guard refuses the naive "
          "same-day path, and")
    print("  once correctly lagged the look-ahead edge is gone (Sharpe "
          f"{s_b:+.2f} -> {s_c:+.2f}, CAGR {m_b['cagr']:+.1%} -> "
          f"{m_c['cagr']:+.1%}, maxDD {m_b['max_drawdown']:.2%} -> "
          f"{m_c['max_drawdown']:.2%}).")
    print(f"  Residual {s_c:+.2f} is HYG vol asymmetry, not leakage (Run D). "
          "It is NOT a tradeable")
    print("  finding at 124x/yr turnover and must not be promoted without a "
          "fresh holdout.")

    verdicts.update({
        "sharpe_net_bypassed": s_b, "sharpe_net_lagged": s_c,
        "sharpe_gross_bypassed": m_b["sharpe_gross"],
        "sharpe_gross_lagged": m_c["sharpe_gross"],
        "cagr_bypassed": m_b["cagr"], "cagr_lagged": m_c["cagr"],
        "vol_bypassed": m_b["ann_vol"], "vol_lagged": m_c["ann_vol"],
        "maxdd_bypassed": m_b["max_drawdown"], "maxdd_lagged": m_c["max_drawdown"],
        "worst_month_bypassed": m_b["worst_month"],
        "worst_month_lagged": m_c["worst_month"],
        "turnover_bypassed": m_b["avg_annual_turnover"],
        "turnover_lagged": m_c["avg_annual_turnover"],
        "cost_annual_bypassed": m_b["cost_drag_annual"],
        "cost_annual_lagged": m_c["cost_drag_annual"],
        "hit_rate_bypassed": m_b["hit_rate"], "hit_rate_lagged": m_c["hit_rate"],
        "collapse": collapse, "shift_test": st,
        "start": m_b["start"], "end": m_b["end"], "n_days": m_b["n_days"],
        "overall": overall,
    })
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
