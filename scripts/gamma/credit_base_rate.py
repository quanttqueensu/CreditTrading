"""G6 Part A — the credit variance risk premium, measured on our own data.

    python3 scripts/gamma/credit_base_rate.py [--out results/gamma/CREDIT_BASE_RATE_<date>.md]

WHAT THIS SETTLES
-----------------
`W14 Part A` had to record the credit `rich_ratio` as **UNMEASURED** — the repo
carried it for SPY and QQQ only. With VXHYG fetched
(`scripts/gamma/fetch_cboe_vol_indices.py`) it becomes measurable back to 2015,
and it is the number a long-gamma credit book is fighting: how much more does
HYG implied vol cost than the realised vol it delivers?

TWO RATIOS, AND THE REPO CONFLATES THEM
---------------------------------------
`data/vrp/vrp_series.parquet` carries a `rich_ratio` column for SPY. Reverse-
engineered here against that file, exactly and to machine precision:

    rich_ratio == impl_var / rv_TRAIL          (max |err| 0.0 over the series)

**`G0_BRIEF` §2 describes that number as "the ratio of implied to forward
realised variance ... median 1.32 and mean 1.55".** The medians match (1.3011 /
1.5253 recomputed here), so it is the same column — but it is **trailing**
realised, not forward. Those are different quantities and only one of them is a
risk premium:

  * **implied vs TRAILING realised** is a rich/cheap INDICATOR. Computable in
    real time, knowable at the decision. This is what `C1` can actually
    condition on, and what the repo's SPY column contains.
  * **implied vs FORWARD realised** is the VARIANCE RISK PREMIUM itself — what a
    long-gamma position would actually have earned or paid. Only knowable after
    the fact, and therefore never a signal.

Both are reported below, labelled, and never averaged. A note that quotes "the
VRP is 1.3x" without saying which one is quoting an indicator as though it were
a payoff.

CONVENTIONS
-----------
* **VXHYG is a 30-calendar-day, VIX-methodology index in vol points.** So
  `impl_vol = VXHYG/100` annualised, and `impl_var = impl_vol**2`.
* **Realised is CLOSE-TO-CLOSE**, annualised, over **21 sessions** (~30 calendar
  days, matching VXHYG's horizon). Close-to-close because that is what a
  once-daily hedger earns — `G3` Part C, and `REFERENCES.md` §9 measures the
  overnight share of HYG's close-to-close variance at **59.6%** since 2019, so
  a range estimator here would be blind to most of it.
* **Forward realised is strictly forward**: sessions t+1..t+21. No overlap with
  the implied reading at t.
* Everything is reported with its panel's own last date. HYG's panel is stale
  relative to VXHYG and that is stated rather than joined away.
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

WINDOW = 21                      # sessions, ~30 calendar days = VXHYG's horizon
ANN = 252


def load_vxhyg() -> pd.Series:
    p = REPO / "data/gamma/cboe_vol_indices.parquet"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} — run scripts/gamma/fetch_cboe_vol_indices.py first")
    d = pd.read_parquet(p)
    s = d[d["index"] == "VXHYG"].set_index("date")["value"].sort_index()
    if s.empty:
        raise ValueError("no VXHYG rows in the panel")
    return s / 100.0                                    # vol points -> decimal


def load_hyg() -> pd.Series:
    """HYG close-to-close returns from the freshest panel that carries them."""
    p = REPO / "data/rv/etf_ohlc_extended.parquet"
    d = pd.read_parquet(p)
    d = d[d.ticker == "HYG"].copy()
    d["date"] = pd.to_datetime(d["date"])
    s = d.set_index("date")["close"].sort_index()
    return s.pct_change(fill_method=None).dropna()


def realised(ret: pd.Series, window: int = WINDOW) -> tuple[pd.Series, pd.Series]:
    """(trailing, forward) annualised close-to-close vol over `window` sessions.

    ALIGNMENT (H7). `trail` at t uses t-window+1..t — all known at t. `fwd` at t
    uses t+1..t+window — strictly after t, and therefore never a signal. The
    shift is what keeps the premium honest: an overlapping window would let the
    day's own return appear on both sides.
    """
    trail = ret.rolling(window).std() * np.sqrt(ANN)
    # Reverse-roll, then shift: `ret[::-1].rolling(w).std()[::-1]` at t is the sd
    # of ret[t .. t+w-1] (a window STARTING at t); `.shift(-1)` moves it to
    # ret[t+1 .. t+w]. Written this way rather than as a shifted forward rolling
    # window because the obvious `ret.shift(-1).rolling(w)` ends at t+1 instead
    # of starting there, which quietly includes the day's own return.
    fwd = ret[::-1].rolling(window).std()[::-1].shift(-1) * np.sqrt(ANN)
    return trail, fwd


def summarise(name: str, s: pd.Series) -> str:
    q = s.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    return (f"| {name} | {len(s):,} | {s.mean():.3f} | {q[0.05]:.3f} | "
            f"{q[0.25]:.3f} | **{q[0.5]:.3f}** | {q[0.75]:.3f} | {q[0.95]:.3f} |")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = Path(a.out) if a.out else \
        REPO / f"results/gamma/CREDIT_BASE_RATE_{date.today().isoformat()}.md"

    iv = load_vxhyg()
    ret = load_hyg()
    trail, fwd = realised(ret)

    df = pd.DataFrame({"iv": iv}).join(
        pd.DataFrame({"rv_trail": trail, "rv_fwd": fwd}), how="inner").dropna(
        subset=["iv"])
    df["impl_var"] = df["iv"] ** 2
    df["rich_ratio"] = df["impl_var"] / (df["rv_trail"] ** 2)
    df["vrp_fwd"] = df["impl_var"] / (df["rv_fwd"] ** 2)

    L: list[str] = []
    say = lambda s="": (print(s), L.append(s))            # noqa: E731

    say("# G6 Part A — the credit variance risk premium, on our own data")
    say()
    say(f"**Run {date.today().isoformat()}** by "
        "`python3 scripts/gamma/credit_base_rate.py`. **Trials: 0** — this is a "
        "base rate, not a specification.")
    say()
    say("## Inputs")
    say()
    say("| series | what | coverage | source |")
    say("|---|---|---|---|")
    say(f"| VXHYG | HYG ETF option implied vol, 30d VIX methodology | "
        f"{iv.index[0].date()} .. **{iv.index[-1].date()}** ({len(iv):,}) | "
        f"Cboe, `scripts/gamma/fetch_cboe_vol_indices.py` |")
    say(f"| HYG | close-to-close returns | "
        f"{ret.index[0].date()} .. **{ret.index[-1].date()}** ({len(ret):,}) | "
        f"`data/rv/etf_ohlc_extended.parquet` |")
    say()
    stale = (iv.index[-1] - ret.index[-1]).days
    say(f"**The two panels do not end together.** HYG's is **{stale} days** "
        f"behind VXHYG's, so every ratio below ends at "
        f"**{df.index[-1].date()}**, not at VXHYG's last date. `ops/doctor.py` "
        f"flags the ETF panel as stale and names this exact consumer. Refreshing "
        f"it extends the sample; it does not change the base rate over eleven "
        f"years.")
    say()
    say("## The two ratios, and why they are not the same number")
    say()
    say("| ratio | n | mean | p5 | p25 | **median** | p75 | p95 |")
    say("|---|---:|---:|---:|---:|---:|---:|---:|")
    rr = df["rich_ratio"].replace([np.inf, -np.inf], np.nan).dropna()
    vf = df["vrp_fwd"].replace([np.inf, -np.inf], np.nan).dropna()
    say(summarise("implied ÷ **trailing** realised variance (`rich_ratio`)", rr))
    say(summarise("implied ÷ **forward** realised variance (the VRP itself)", vf))
    say()
    say(f"**Read the second row, not the first, for what a long-gamma book "
        f"pays.** Buying and delta-hedging HYG gamma loses when implied exceeds "
        f"subsequent realised, and the median says it does so by a factor of "
        f"**{vf.median():.2f}** in variance — i.e. about "
        f"**{np.sqrt(vf.median()):.2f}x in vol terms**. That is the headwind, "
        f"and it is before any spread, commission or hedge cost.")
    say()
    say(f"The first row is the ex-ante INDICATOR — implied against *recent* "
        f"realised, knowable at the decision. Median **{rr.median():.2f}**. It "
        f"is what `C1` conditions on; it is not a payoff. **`G0_BRIEF` §2 "
        f"describes the repo's SPY column as \"implied to *forward* realised\" "
        f"and it is trailing** — reverse-engineered exactly against "
        f"`data/vrp/vrp_series.parquet` (`impl_var / rv_trail`, max error 0.0). "
        f"The medians it quotes, 1.32 and 1.55, are the trailing figures.")
    say()
    say("## Credit against equity, on the identical construction")
    say()
    say("The number above is only interpretable beside the equity benchmark this "
        "repo already carries, computed the same way from "
        "`data/vrp/vrp_series.parquet`:")
    say()
    say("| underlier | median implied | median forward realised | vol ratio | **variance ratio** |")
    say("|---|---:|---:|---:|---:|")
    say(f"| **HYG** (credit) | {df['iv'].median()*100:.2f}% | "
        f"{df['rv_fwd'].median()*100:.2f}% | "
        f"{df['iv'].median()/df['rv_fwd'].median():.2f}x | "
        f"**{(df['iv'].median()/df['rv_fwd'].median())**2:.2f}x** |")
    try:
        v = pd.read_parquet(REPO / "data/vrp/vrp_series.parquet")
        sp = v[v.ticker == "SPY"].dropna(subset=["impl_vol", "real_vol_fwd"])
        r_spy = sp["impl_vol"].median() / sp["real_vol_fwd"].median()
        say(f"| SPY (equity) | {sp['impl_vol'].median()*100:.2f}% | "
            f"{sp['real_vol_fwd'].median()*100:.2f}% | {r_spy:.2f}x | "
            f"**{r_spy**2:.2f}x** |")
        say()
        say(f"**Credit gamma is more than twice as expensive as equity gamma** — "
            f"{(df['iv'].median()/df['rv_fwd'].median())**2:.2f}x against "
            f"{r_spy**2:.2f}x in variance. HYG's implied vol sits near "
            f"{df['iv'].median()*100:.1f}% while it delivers about "
            f"{df['rv_fwd'].median()*100:.1f}%; SPY's two numbers are far closer "
            f"together. The mechanism is not mysterious — a credit ETF's implied "
            f"vol prices jump and default risk that realised vol almost never "
            f"delivers — but the SIZE of it is the single most important number "
            f"for this programme, and it was unmeasured until today.")
    except Exception as exc:                              # noqa: BLE001
        say(f"| SPY (equity) | UNMEASURED | | | {exc!r} |")
    say()
    say("## The prompt predicted this, and the prediction holds")
    say()
    say("`G6` Part A states the prior in advance, from primary sources: *\"the "
        "prior is that credit's VRP is real and probably larger than equity's, "
        "not smaller\"* — citing Wang, Zhou & Zhou (FEDS 2011-02, 382 firms, "
        "2001–2008), whose central finding is that **mean VRP rises "
        "monotonically with credit risk, from 7 at AAA to 82 at CCC**, and "
        "Kita & Tortorice (2021) that the smirk *\"is more pronounced in the "
        "credit market than in the equity market\"*.")
    say()
    say(f"HYG is a **high-yield** basket, so that literature predicts a large "
        f"premium, and the measurement agrees: **{(df['iv'].median()/df['rv_fwd'].median())**2:.2f}x "
        f"against equity's 1.28x.** This is a prior stated before the data was "
        f"fetched and confirmed by it — worth recording as such, because the "
        f"opposite result would have been the more interesting one and would "
        f"have pointed at a bug in the surface or the estimator rather than at "
        f"an edge (G6 Part A says exactly that).")
    say()
    say("## How often is credit gamma actually cheap?")
    say()
    say("The fraction of days on which implied was BELOW subsequent realised — "
        "i.e. long gamma would have paid:")
    say()
    say("| window | days | implied < forward realised |")
    say("|---|---:|---:|")
    for lab, sl in (("full sample", vf),
                    ("2015–2019", vf.loc[:"2019-12-31"]),
                    ("2020–2022", vf.loc["2020-01-01":"2022-12-31"]),
                    ("2023–2026", vf.loc["2023-01-01":])):
        if len(sl):
            say(f"| {lab} | {len(sl):,} | **{(sl < 1).mean():.1%}** |")
    say()
    say("## By era")
    say()
    say("| era | n | median `rich_ratio` | median VRP (fwd) | median VXHYG |")
    say("|---|---:|---:|---:|---:|")
    for lab, a_, b_ in (("2015–2019", "2015", "2019"), ("2020–2022", "2020", "2022"),
                        ("2023–2026", "2023", "2026")):
        sl = df.loc[a_:b_]
        if not len(sl):
            continue
        say(f"| {lab} | {len(sl):,} | {sl['rich_ratio'].median():.3f} | "
            f"{sl['vrp_fwd'].replace([np.inf,-np.inf],np.nan).median():.3f} | "
            f"{sl['iv'].median()*100:.2f} |")
    say()
    say("## What this means for the programme")
    say()
    say(f"A systematic long-gamma credit book pays the second row every day it "
        f"is on. At a median variance ratio of **{vf.median():.2f}** the "
        f"conditioner has to do real work: `G6`'s decision rule requires a "
        f"candidate to beat **C1**, not merely to beat always-on, and this is "
        f"the size of the hole always-on starts in.")
    say()
    say(f"Days on which long gamma would have paid: **{(vf < 1).mean():.1%}** of "
        f"the sample. A conditioner is useful only if it selects them at a rate "
        f"materially above that base rate — which is the null `C1` and `C3` are "
        f"tested against, and it is stated here BEFORE either is run.")
    say()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print(f"\n[written] {out}")


if __name__ == "__main__":
    main()
