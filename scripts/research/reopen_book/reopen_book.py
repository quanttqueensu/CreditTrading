"""Zero-trial re-open: do NAV tenders (EVENTS 2) and E1 (EVENTS 1) add to the CEF book? Fit period only.

    python3 -m scripts.research.reopen_book.reopen_book                 # re-derive both series, then measure
    python3 -m scripts.research.reopen_book.reopen_book --no-extract    # reuse the cached series
    python3 -m pytest scripts/research/tests/test_reopen_book.py

WHAT THIS ANSWERS (team lead, 2026-10-27, `docs/SYSTEM.md` §5, "the research method")
------------------------------------------------------------------------------------
A sleeve that fails the standalone deflated Sharpe may join the PAPER book, labelled,
if it adds to the book, SR_sleeve > ρ·SR_book across ρ's plausible range, AND the
combined book's net is positive at 5, 15 and 30bp. Real capital keeps the standalone
gate. The audit (`results/research/DESK_METHOD_2026-10-27.md` §2) found both trials
had a near-zero correlation with the book that was never weighed. This script
measures the rule's inputs. It decides nothing, spends no trial, and edits no
counter, spec or `docs/RESEARCH_STATE.md`.

THE SERIES
----------
* Each sleeve: its tradable fit-period daily gross P&L, re-derived by its own
  branch's committed code (`extract_trial_series.py`, which refuses unless it
  reproduces the committed fit JSON to 1e-9). Neither trial stored a daily series.
  The series are CRSP-derived, so they stay in the gitignored cache, as the trials
  kept theirs. Only aggregates are tracked.
* The book: the live policy on the canonical harness. `build_targets` on the live
  panels CUT AT 2022-12-30 BEFORE ANY COMPUTATION (`source=`, the harness's own
  argument), `band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)` (spec.LIVE_POLICY:
  the band plus the frozen gross ceiling, both read from the spec), `evaluate()`
  (shift(2)) on `total_returns` (H15). No 2023+ price, NAV or return is read into
  any computation. Every target is causal (z, ADV and the vol scaler are all
  `.shift(1)` or trailing), so the cut changes no fit-period value; it only keeps
  the sealed holdout out of the process. Price returns and the plain band are
  reported beside it, labelled, because Alpaca paper pays no distributions
  (CLAUDE.md landmine 1).

THE RULES FIXED BEFORE ANY NUMBER WAS SEEN (stated here, not chosen from output)
-------------------------------------------------------------------------------
* Common window: from the later of the sleeve's first P&L session and the book's
  first session holding a position, to 2022-12-30, on dates in both series. Idle
  sleeve days are zeros and stay in: that is what the sleeve earns.
* ρ's range: the union of every interval below. The rule must hold at its upper end.
  - daily ρ, stationary bootstrap (pairs resampled together; 10,000 draws), mean
    block = the sleeve's median ACTIVE-SPELL length in sessions (how long a run of
    held positions lasts: the persistence a resample must keep, measured from the
    sleeve's holdings, never from P&L), and 21 and 63 beside it (the blocks both
    trials declared);
  - non-overlapping weekly (Friday) sums and 21-session sums, Fisher intervals. The
    21-session sum is `results/cef/PORTFOLIO_FRAMEWORK_2026-10-15.md` §2.4's input,
    because daily correlations of thinly traded CEF books understate co-movement.
* The combined book's weight: EQUAL RISK BUDGETS. With fewer than four sleeves the
  framework sets b ∝ R̃⁻¹·1 (§2.3), which for two sleeves is equal budgets at any ρ.
  Each sleeve's own scalar targets its budget (§2.2), and an event sleeve's budget is
  a ceiling (§2.2, §2.8). So each enters at the sizing its own pre-registration
  derived: the book at `vol_target_annual` through build_targets' scaler, the sleeve
  at k = vol_target / σ_active (NAV tenders) or σ_raw (E1), capped at
  `max_gross_stress`. Combined = book + 1.0 × sleeve on capital. Nothing is
  optimised on the fit.
* Costs: each leg on its own convention, never netted between them (they trade
  different symbols): the book's `evaluate()` turnover; NAV tenders' notional on
  every leg; E1's event turnover (a conversion is not a trade), with the harness's
  count beside it.
* DSR: `desk_dsr` at the EVENTS counter's declared N = 6, and `dsr(...)` with
  sr_var = 1/T on both bounds, "upper" (the desk's √(2 ln N)) and "gumbel" (the
  paper's expected maximum), labelled.

ALIGNMENT (H7): every series is P&L earned on date t from weights decided at t−2
(evaluate()'s shift(2), in each trial's code and here). Nothing estimated here feeds
back into a weight; the bootstrap and the sums only describe realised P&L.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.research import inference as I  # noqa: E402

OUT = REPO / "results" / "research" / "reopen_book"
CACHE = OUT / "_cache_reopen"                    # gitignored (results/**/_cache_*): CRSP-derived daily series
OUT_JSON = OUT / "reopen_book_2026-10-28.json"
EXTRACTOR = Path(__file__).resolve().parent / "extract_trial_series.py"
HOLDOUT_START = pd.Timestamp("2023-01-01")
FIT_LAST = pd.Timestamp("2022-12-30")
N_EVENTS = 6                                     # EVENTS' declared bar N (docs/RESEARCH_STATE.md, 2026-10-19)
COSTS_BP = (5, 15, 30)
BLOCKS_DECLARED = (21, 63)                       # both trials' declared bootstrap blocks
REPS = 10_000
SEED = 20261028
SUM_SESSIONS = 21                                # PORTFOLIO_FRAMEWORK §2.4
ERAS = (("2010-14", "2010-01-01", "2014-12-31"), ("2015-19", "2015-01-01", "2019-12-31"),
        ("2020-22", "2020-01-01", "2022-12-31"))
TRIALS = {"navtender": "trial-events-navtender", "e1": "trial-events-e1"}


# ============================================================ pure helpers (tested)

def common_window(sleeve: pd.DataFrame, book: pd.DataFrame) -> tuple[pd.DatetimeIndex, dict]:
    """Dates in both frames from max(sleeve's first P&L session, book's first held session).

    `book.held_gross` > 0 marks the book holding a position. Returns the index and
    what was dropped, so a calendar mismatch is reported, never silent."""
    if sleeve.index.max() >= HOLDOUT_START or book.index.max() >= HOLDOUT_START:
        raise AssertionError("a series reaches 2023-01-01: the time holdout is sealed")
    held = book.index[book["held_gross"] > 0]
    if not len(held):
        raise ValueError("the book never holds a position")
    start = max(sleeve.index[0], held[0])
    s_ix = sleeve.index[sleeve.index >= start]
    b_ix = book.index[book.index >= start]
    idx = s_ix.intersection(b_ix)
    lost = sleeve.loc[s_ix.difference(b_ix), "pnl"]
    return idx, {"start": str(start.date()), "end": str(idx[-1].date()), "T": int(len(idx)),
                 "sleeve_sessions_not_in_book": int(len(lost)),
                 "sleeve_pnl_on_those_sessions": float(lost.sum()),
                 "book_sessions_not_in_sleeve": int(len(b_ix.difference(s_ix)))}


def spells(active: pd.Series) -> np.ndarray:
    """Lengths (in sessions) of each run of consecutive True values."""
    a = np.asarray(active, dtype=bool)
    if not a.any():
        return np.array([], dtype=int)
    edges = np.diff(np.r_[0, a.astype(int), 0])
    return np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)


def block_sums(x: pd.Series, n: int) -> pd.Series:
    """Non-overlapping sums of n consecutive sessions from the first; a trailing partial block is dropped."""
    k = len(x) // n
    if k < 4:
        raise ValueError(f"{len(x)} sessions make {k} blocks of {n}; too few to correlate")
    v = np.asarray(x, dtype=float)[: k * n].reshape(k, n).sum(axis=1)
    return pd.Series(v, index=x.index[n - 1: k * n: n])


def stats(pnl: pd.Series, turn: pd.Series) -> dict:
    """`band_frontier._stats` (gross SR and nets at 5/15/30bp, annualised) plus the moments the DSR needs."""
    from scripts.cef.band_frontier import _stats
    st = _stats(pnl, turn)
    return {"gross": float(st["sr"]), "ann": float(st["ann"]), "vol": float(st["vol"]), "turn": float(st["turn"]),
            **{f"net{c}": float(v) for c, v in zip(COSTS_BP, st["nets"])},
            **{f"ann_net{c}": float(st["ann"] - st["turn"] * c / 1e4) for c in COSTS_BP},
            "T": int(len(pnl)), "skew": float(pnl.skew()), "kurt_raw": float(pnl.kurt() + 3.0)}


def deflated(s: dict, n: float = N_EVENTS) -> dict:
    """Both DSR bars on the sleeve's gross daily P&L, sr_var = 1/T (the desk's null spread)."""
    T, sk, ku = s["T"], s["skew"], s["kurt_raw"]
    sr_pp = s["gross"] / np.sqrt(252)
    up, sr0_up = I.dsr(sr_pp, T, sk, ku, n, 1 / T, bound="upper")
    gu, sr0_gu = I.dsr(sr_pp, T, sk, ku, n, 1 / T, bound="gumbel")
    desk = I.desk_dsr(s["gross"], T, sk, ku, n)
    if abs(desk - up) > 1e-12:
        raise AssertionError("desk_dsr and dsr(bound='upper', sr_var=1/T) disagree")
    return {"N": n, "desk_dsr": desk, "upper": {"dsr": up, "sr0_annual": sr0_up * np.sqrt(252)},
            "gumbel": {"dsr": gu, "sr0_annual": sr0_gu * np.sqrt(252)}}


def rho_range(rows: list[dict]) -> tuple[float, float]:
    return min(r["lo"] for r in rows), max(r["hi"] for r in rows)


def reading(gain_hi: float, gain_point: float, nets_positive: bool) -> str:
    """The rule's three outcomes. `gain_*` = marginal_gain at ρ's upper end and its point estimate."""
    if not nets_positive:
        return "DOES NOT MEET (the combined book's net is not positive at every cost on the grid)"
    if gain_hi > 0:
        return "MEETS the paper-admission rule across rho's range"
    if gain_point > 0:
        return "MEETS it only at the point estimate (fails at the upper end of rho's range)"
    return "DOES NOT MEET (SR_sleeve <= rho * SR_book at the point estimate)"


def combine(book: pd.DataFrame, sleeve: pd.DataFrame, w: float) -> pd.DataFrame:
    """Book + w × sleeve on common dates: P&L, turnover and held gross add (no symbol is shared)."""
    if not book.index.equals(sleeve.index):
        raise ValueError("combine needs both frames on the same dates")
    return pd.DataFrame({"pnl": book["pnl"] + w * sleeve["pnl"], "turn": book["turn"] + w * sleeve["turn"],
                         "held_gross": book["held_gross"] + w * sleeve["held_gross"]})


def leverage(held: pd.Series, cap: float) -> dict:
    return {"mean": float(held.mean()), "p95": float(held.quantile(0.95)), "max": float(held.max()),
            "share_days_above_cap": float((held > cap + 1e-12).mean())}


# ============================================================ the series

def main_tree() -> Path:
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO,
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent


def extract(trees: dict) -> None:
    for trial, tree in trees.items():
        # -I: isolated (no caller env, no script dir on the path); -B: no bytecode written into the trial tree.
        subprocess.run([sys.executable, "-I", "-B", str(EXTRACTOR), trial, "--tree", str(tree), "--out", str(CACHE)],
                       check=True)


def load_sleeve(trial: str) -> tuple[pd.DataFrame, dict]:
    p, m = CACHE / f"{trial}_fit_series.parquet", CACHE / f"{trial}_fit_check.json"
    if not p.exists() or not m.exists():
        raise FileNotFoundError(f"{p.name} is missing: run without --no-extract")
    return pd.read_parquet(p), json.loads(m.read_text())


def book_series() -> tuple[dict, dict]:
    """The live policy on the fit-cut panels. Returns {variant: frame(pnl, turn, held_gross)} and provenance."""
    from scripts.cef import band_frontier as bf
    from scripts.cef.spec import BAND_WIDTH, LIVE_POLICY, MAX_GROSS_STRESS, SPEC_ID
    if MAX_GROSS_STRESS is None:
        raise RuntimeError("the spec has no max_gross_stress; the live policy label would not match")
    CACHE.mkdir(parents=True, exist_ok=True)
    prov = {"spec": SPEC_ID, "live_policy": LIVE_POLICY}
    paths = []
    for name in ("cef_prices", "cef_nav"):
        df = pd.read_parquet(bf.DATA_DIR / f"{name}.parquet")
        d = pd.to_datetime(df["date"])
        prov[f"{name}_panel_last"] = str(d.max().date())
        cut = df[d < HOLDOUT_START]
        prov[f"{name}_cut_last"] = str(pd.to_datetime(cut["date"]).max().date())
        p = CACHE / f"{name}_fit_cut.parquet"
        cut.to_parquet(p)
        paths.append(p)
    T, R = bf.build_targets(source=tuple(paths))
    T, R = bf.fit_only(T, R)                          # asserts nothing reaches 2023-01-01
    Rt = bf.total_returns(R)
    if Rt.index.max() >= HOLDOUT_START:
        raise AssertionError("holdout leak in the total-return matrix")
    out = {}
    for label, H, RR in (("live_total", bf.band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS), Rt),
                         ("live_price", bf.band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS), R),
                         ("band_only_total", bf.band(T, BAND_WIDTH), Rt)):
        ev = bf.evaluate(H, RR)
        out[label] = pd.DataFrame({"pnl": ev["pnl"], "turn": ev["turn_series"],
                                   "held_gross": H.shift(2).fillna(0.0).abs().sum(axis=1)})
    prov["targets_first"], prov["targets_last"] = str(T.index[0].date()), str(T.index[-1].date())
    prov["max_gross_stress"] = MAX_GROSS_STRESS
    return out, prov


# ============================================================ the measurement

def measure(trial: str, sleeve_all: pd.DataFrame, meta: dict, books: dict, cap: float) -> dict:
    book_all = books["live_total"]
    idx, win = common_window(sleeve_all, book_all)
    S, B = sleeve_all.loc[idx], book_all.loc[idx]
    active = S["held_gross"] > 0
    sp = spells(active)
    out = {"window": win, "cost_convention": meta["cost_convention"],
           "activity": {"active_days": int(active.sum()), "active_share": float(active.mean()),
                        "nonzero_pnl_days": int((S["pnl"] != 0).sum()), "spells": int(len(sp)),
                        "median_spell_sessions": float(np.median(sp)), "book_flat_days": int((B["held_gross"] == 0).sum())}}

    # 1. standalone, on the common window and on the sleeve's own fit span (the reproduction row)
    s_win, s_own = stats(S["pnl"], S["turn"]), stats(sleeve_all["pnl"], sleeve_all["turn"])
    out["sleeve"] = {"common_window": {**s_win, "dsr": deflated(s_win),
                                       "nw_t_auto": I.newey_west_t(S["pnl"].values),
                                       "nw_t_L21": I.newey_west_t(S["pnl"].values, 21)},
                     "own_span": {**s_own, "dsr": deflated(s_own), "first": str(sleeve_all.index[0].date())}}
    if "harness_turn" in S:
        out["sleeve"]["common_window"]["harness_turn_sensitivity"] = stats(S["pnl"], S["harness_turn"])
    b = stats(B["pnl"], B["turn"])
    out["book"] = {"live_total": b, **{k: stats(v.loc[idx, "pnl"], v.loc[idx, "turn"])
                                       for k, v in books.items() if k != "live_total"}}

    # 2. rho and its range
    rho = float(np.corrcoef(S["pnl"], B["pnl"])[0, 1])
    mech = max(1, int(round(out["activity"]["median_spell_sessions"])))
    boot = []
    for blk, why in ((mech, "median active spell of the sleeve"), *((k, "declared by both trials") for k in BLOCKS_DECLARED)):
        r = I.stationary_bootstrap_corr(S["pnl"].values, B["pnl"].values, blk, seed=SEED, reps=REPS)
        boot.append({"kind": f"daily, stationary bootstrap, mean block {blk} ({why})", **r})
    sums = []
    wk = pd.DataFrame({"s": S["pnl"], "b": B["pnl"]}).resample("W-FRI").sum()
    for label, x, y in (("weekly (W-FRI) sums", wk["s"], wk["b"]),
                        (f"{SUM_SESSIONS}-session sums", block_sums(S["pnl"], SUM_SESSIONS), block_sums(B["pnl"], SUM_SESSIONS))):
        r_ = float(np.corrcoef(x, y)[0, 1])
        lo, hi = I.fisher_corr_ci(r_, len(x))
        sums.append({"kind": f"{label}, Fisher", "rho": r_, "lo": lo, "hi": hi, "n": int(len(x)),
                     "nonzero_sleeve_blocks": int((x != 0).sum())})
    lo, hi = rho_range(boot + sums)
    out["rho"] = {"daily_point": rho, "intervals": boot + sums, "range": [lo, hi],
                  "break_even_rho_gross": s_win["gross"] / b["gross"]}

    # 3. marginal gain at the point and both ends, gross headline and the grid beside it
    mg = {}
    for lab, ss, bb in (("gross", s_win["gross"], b["gross"]),
                        *((f"net{c}", s_win[f"net{c}"], b[f"net{c}"]) for c in COSTS_BP)):
        mg[lab] = {"sr_sleeve": ss, "sr_book": bb, "at_point": I.marginal_gain(ss, bb, rho),
                   "at_lo": I.marginal_gain(ss, bb, lo), "at_hi": I.marginal_gain(ss, bb, hi),
                   "long_only_optimum_sr_at_point": I.combined_sharpe(bb, ss, rho) if (bb > 0 or ss > 0) else None}
    out["marginal_gain"] = mg

    # 4. the combined book at the stated weight (w = 1: equal risk budgets, each at its own sizing)
    C = combine(B, S, 1.0)
    c = stats(C["pnl"], C["turn"])
    scale = b["vol"] / c["vol"]
    out["combined"] = {"weight_rule": "equal risk budgets (PORTFOLIO_FRAMEWORK §2.3, < 4 sleeves); each sleeve at its "
                                      "own pre-registered vol-target sizing, the event sleeve's budget a ceiling (§2.2)",
                       "w": 1.0, **c, "gross_change_vs_book": c["gross"] - b["gross"],
                       "nets_all_positive": all(c[f"ann_net{k}"] > 0 for k in COSTS_BP),
                       "leverage": {"cap_max_gross_stress": cap, "book": leverage(B["held_gross"], cap),
                                    "sleeve": leverage(S["held_gross"], cap),
                                    "combined": leverage(C["held_gross"], cap),
                                    "combined_on_sleeve_active_days": leverage(C.loc[active, "held_gross"], cap),
                                    "combined_rescaled_to_book_vol": {"scale": scale, **leverage(C["held_gross"] * scale, cap)}}}
    # The cap applied to the combined held book, uniformly, as the sleeve applies it (approximate:
    # the band's feedback from a scaled book to the next day's trade is not rebuilt, and turnover
    # is scaled with the book). Labelled; it decides nothing.
    f = np.minimum(1.0, cap / C["held_gross"].where(C["held_gross"] > 0))
    f = f.where(C["held_gross"] > 0, 1.0)
    out["combined"]["capped_approx"] = stats(C["pnl"] * f, C["turn"] * f)
    for lab in ("live_price", "band_only_total"):
        Bv = books[lab].loc[idx]
        cc = stats(Bv["pnl"] + S["pnl"], Bv["turn"] + S["turn"])
        out["combined"][f"book_{lab}"] = {"gross": cc["gross"], **{f"net{k}": cc[f"net{k}"] for k in COSTS_BP},
                                          "nets_all_positive": all(cc[f"ann_net{k}"] > 0 for k in COSTS_BP)}
    if "harness_turn" in S:
        cc = stats(C["pnl"], B["turn"] + S["harness_turn"])
        out["combined"]["harness_turn_sensitivity"] = {**{f"net{k}": cc[f"net{k}"] for k in COSTS_BP},
                                                       "nets_all_positive": all(cc[f"ann_net{k}"] > 0 for k in COSTS_BP)}

    # report-only: does the sleeve lose when the book does? 21-session blocks, by the book's quintile
    bs, ss_ = block_sums(B["pnl"], SUM_SESSIONS), block_sums(S["pnl"], SUM_SESSIONS)
    worst = bs <= bs.quantile(0.2)
    out["book_worst_quintile_blocks"] = {"blocks": int(worst.sum()), "sleeve_mean_in_worst": float(ss_[worst].mean()),
                                         "sleeve_mean_in_rest": float(ss_[~worst].mean()),
                                         "book_mean_in_worst": float(bs[worst].mean())}
    eras = {}
    for lab, a, z in ERAS:
        m = (idx >= pd.Timestamp(a)) & (idx <= pd.Timestamp(z))
        if m.sum() < 126:
            eras[lab] = {"T": int(m.sum()), "not computed": "fewer than 126 common sessions"}
            continue
        se, be = stats(S["pnl"][m], S["turn"][m]), stats(B["pnl"][m], B["turn"][m])
        re_ = float(np.corrcoef(S["pnl"][m], B["pnl"][m])[0, 1])
        tq = B["turn"][m]
        eras[lab] = {"T": int(m.sum()), "sr_sleeve": se["gross"], "sr_book": be["gross"], "rho": re_,
                     "marginal_gain": I.marginal_gain(se["gross"], be["gross"], re_),
                     "active_share": float(active[m].mean()), "book_turn_sd_over_mean": float(tq.std() / tq.mean())}
    out["eras"] = eras
    # PORTFOLIO_FRAMEWORK §2.5: once gross binds, a sleeve is ranked by return per unit of gross held.
    out["return_per_unit_gross"] = {"book": b["ann"] / float(B["held_gross"].mean()),
                                    "sleeve": s_win["ann"] / float(S["held_gross"].mean())}
    # Second method for the BOOK series: each trial's own R-BOOK row (in its committed fit JSON)
    # correlated its sleeve with the book built on the FULL panel. Reproducing that correlation
    # from this fit-cut book, on the trial's own rule for the dates, shows the cut changed no
    # fit-period value. The trial's figure is [S] (read from its JSON); ours is [V].
    if trial == "navtender":                 # nav_tender_trial.r_book: inner join, dropna, book != 0
        d = pd.concat([sleeve_all["pnl"].rename("s"), book_all["pnl"].rename("b")], axis=1, join="inner").dropna()
        d = d[d["b"] != 0]
        ours, n = float(d["s"].corr(d["b"])), int(len(d))
    else:                                    # e1_merger_pair.fit_core: book reindexed on the sleeve's dates
        y, bb = sleeve_all["pnl"], book_all["pnl"].reindex(sleeve_all.index)
        d = pd.concat([y, bb], axis=1).dropna()
        ours, n = float(d.corr().iloc[0, 1]), int(len(d))
    out["book_parity_with_trial_r_book"] = {"ours": ours, "n": n, "trial_committed": meta.get("r_book_committed")}
    out["reading"] = reading(mg["gross"]["at_hi"], mg["gross"]["at_point"], out["combined"]["nets_all_positive"])
    out["reading_at_each_cost"] = {f"net{k}": reading(mg[f"net{k}"]["at_hi"], mg[f"net{k}"]["at_point"],
                                                      out["combined"]["nets_all_positive"]) for k in COSTS_BP}
    out["reproduction"] = {"check": meta["check"], "provenance": meta["provenance"],
                           "committed_fit_json": meta["committed_fit_json"]}
    return out


def _f(x, d=3):
    return "—" if x is None else f"{x:+.{d}f}"


def report(res: dict) -> None:
    print(f"{res['book_provenance']['spec']} | {res['book_provenance']['live_policy']} | fit only, panels cut at "
          f"{res['book_provenance']['cef_prices_cut_last']} (prices) / {res['book_provenance']['cef_nav_cut_last']} (NAV)")
    for trial, r in res["sleeves"].items():
        w, s, bk = r["window"], r["sleeve"]["common_window"], r["book"]["live_total"]
        print(f"\n=== {trial}: common window {w['start']} .. {w['end']}, T {w['T']} "
              f"(sleeve sessions not in the book: {w['sleeve_sessions_not_in_book']})")
        a = r["activity"]
        print(f"  active {a['active_days']} days ({a['active_share']:.1%}), {a['spells']} spells, median "
              f"{a['median_spell_sessions']:.0f} sessions; book flat {a['book_flat_days']} days")
        print(f"  1. sleeve gross {s['gross']:+.3f}  net5 {s['net5']:+.3f}  net15 {s['net15']:+.3f}  net30 {s['net30']:+.3f}"
              f"  (vol {s['vol']:.2%}, turn {s['turn']:.2f}/yr)")
        d = s["dsr"]
        print(f"     DSR N=6: desk/upper {d['upper']['dsr']:.3f} (SR0 {d['upper']['sr0_annual']:.3f}),"
              f" gumbel {d['gumbel']['dsr']:.3f} (SR0 {d['gumbel']['sr0_annual']:.3f}); NW t {s['nw_t_auto']:.2f}")
        print(f"     book gross {bk['gross']:+.3f}  net5 {bk['net5']:+.3f}  net15 {bk['net15']:+.3f}  net30 {bk['net30']:+.3f}")
        ro = r["rho"]
        print(f"  2. rho daily {ro['daily_point']:+.3f}; range [{ro['range'][0]:+.3f}, {ro['range'][1]:+.3f}];"
              f" break-even rho (gross) {ro['break_even_rho_gross']:+.3f}")
        for iv in ro["intervals"]:
            print(f"     {iv['kind']:<70} {iv['rho']:+.3f} [{iv['lo']:+.3f}, {iv['hi']:+.3f}] n {iv['n']}")
        print("  3. marginal gain (SR_sleeve - rho*SR_book): point / lo / hi")
        for lab, m in r["marginal_gain"].items():
            print(f"     {lab:<6} {_f(m['at_point'])} / {_f(m['at_lo'])} / {_f(m['at_hi'])}")
        c = r["combined"]
        print(f"  4. combined (w=1) gross {c['gross']:+.3f} (book {bk['gross']:+.3f}); net5 {c['net5']:+.3f} net15 "
              f"{c['net15']:+.3f} net30 {c['net30']:+.3f}; vol {c['vol']:.2%}")
        L = c["leverage"]
        print(f"     held gross vs cap {L['cap_max_gross_stress']}: book mean {L['book']['mean']:.2f} max {L['book']['max']:.2f};"
              f" combined mean {L['combined']['mean']:.2f} p95 {L['combined']['p95']:.2f} max {L['combined']['max']:.2f},"
              f" above cap {L['combined']['share_days_above_cap']:.1%}")
        ca = c["capped_approx"]
        print(f"     capped (approx): gross {ca['gross']:+.3f} net5 {ca['net5']:+.3f} net15 {ca['net15']:+.3f} net30 {ca['net30']:+.3f}")
        rg = r["return_per_unit_gross"]
        print(f"     return per unit of held gross: book {rg['book']:.2%}/yr, sleeve {rg['sleeve']:.2%}/yr")
        pb = r["book_parity_with_trial_r_book"]
        print(f"     book parity: rho vs the trial's R-BOOK rule {pb['ours']:.6f} (n {pb['n']}); committed "
              f"{pb['trial_committed']['corr']:.6f} (n {pb['trial_committed']['n']})")
        print(f"  5. {r['reading']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-extract", action="store_true", help="reuse the cached sleeve series")
    ap.add_argument("--navtender-tree", type=Path)
    ap.add_argument("--e1-tree", type=Path)
    a = ap.parse_args(argv)
    pd.set_option("compute.use_numexpr", False)
    root = main_tree()
    trees = {"navtender": a.navtender_tree or root / ".claude" / "worktrees" / TRIALS["navtender"],
             "e1": a.e1_tree or root / ".claude" / "worktrees" / TRIALS["e1"]}
    if not a.no_extract:
        extract(trees)
    from scripts.cef.spec import MAX_GROSS_STRESS
    books, bprov = book_series()
    res = {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
                                      check=True).stdout.strip(),
           "book_provenance": bprov, "seed": SEED, "reps": REPS, "n_events": N_EVENTS, "sleeves": {}}
    for trial in TRIALS:
        sl, meta = load_sleeve(trial)
        res["sleeves"][trial] = measure(trial, sl, meta, books, MAX_GROSS_STRESS)
    OUT.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(res, indent=1, default=float) + "\n")
    report(res)
    print(f"\nwrote {OUT_JSON.relative_to(REPO)} (aggregates only; the daily series stay in {CACHE.relative_to(REPO)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
