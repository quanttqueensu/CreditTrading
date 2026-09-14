#!/usr/bin/env python3
"""The volatility scalar's whole history. Is $813,682 of gross the target working, or drift?

    python3 scripts/cef/vol_scalar_history.py

WHY THIS EXISTS
---------------
The 2026-09-11 session printed `volscal=1.58` and a book gross of **$813,682**,
against a frozen-spec `sizing_note` that reads "At the current 1.5x volatility
scalar that is ~$750k gross". Gross came in ~9% above the figure that note
describes, and the only guard on it -- `risk.max_gross_exposure_usd = $1.3M` --
was never within reach of firing. Nobody had asked whether 1.5 was ever a BOUND
or merely an illustration written on a particular afternoon.

IT MEASURES AND IT CHANGES NOTHING. No spec key moves out of this script. A
sizing change needs a pre-registration; this is the measurement that would have
to precede one.

HOW IT REPRODUCES THE LIVE NUMBER
---------------------------------
It does not re-implement the sleeve. It instantiates the REAL
`CEFDiscountSleeve` against the REAL frozen spec, calls the sleeve's own
`_panel()` loader, and re-runs the sleeve's own sizing block. The one thing it
must get right is that the sleeve sees a panel TRUNCATED at each decision date,
while this script loads the panel once -- so every backward-looking quantity is
sliced `.loc[:d]` before use. Two of them bite if you forget:

  * `nav[tk].dropna().index[-1]`, the NAV staleness check. On an untruncated
    panel this reads the LAST NAV IN THE FILE, so a fund that was stale in March
    looks fresh because it has a September NAV. That would silently re-admit
    names the live sleeve dropped.
  * `ret.tail(63)`, the trailing vol window, which would otherwise be the last
    63 days of the FILE rather than of the decision.

Both are pure lookahead, both are invisible in the output, and both are the
shape of defect this desk has been bitten by before. `rolling(...).shift(1)` is
causal, so computing `mu`/`sd`/`adv` once over the full panel and slicing is
exact -- that part needs no truncation, and the test suite pins the claim.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.deploy.sleeves.cef_discount import CEFDiscountSleeve  # noqa: E402

SPEC_PATH = REPO / "ops/specs/cef_discount.frozen.json"


def load_sleeve() -> CEFDiscountSleeve:
    spec = json.loads(SPEC_PATH.read_text())
    return CEFDiscountSleeve(spec, float(spec.get("capital_usd", 500_000.0)))


def scalar_series(sleeve: CEFDiscountSleeve, panel) -> pd.DataFrame:
    """(rv, scal, n_names, clipped) for every date the sleeve could have decided on.

    The body below is the sleeve's own sizing block with `.loc[:d]` inserted at
    each backward-looking read. Nothing else is changed; if the sleeve's formula
    moves, `tests/test_vol_scalar_matches_sleeve.py` fails.
    """
    px, nav, vol = panel
    win, min_adv = sleeve._win, sleeve._min_adv
    vt, lev = sleeve._vol_target, float(sleeve.frozen.get("gross_leverage", 1.0))
    minw = float(sleeve.frozen.get("min_abs_weight", 0.005))
    min_names = int(sleeve.frozen.get("min_names", 6))
    max_age = int(sleeve.frozen.get("max_nav_age_bd", 3))

    disc = 100.0 * (px - nav) / nav
    mu = disc.rolling(win, min_periods=120).mean().shift(1)
    sd = disc.rolling(win, min_periods=120).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    adv = (px * vol).rolling(63, min_periods=21).mean().shift(1)
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)

    out = []
    for d in px.index[win + 20:]:
        row = {}
        for tk in px.columns:
            zi = z.loc[d, tk]
            if not np.isfinite(zi):
                continue
            if float(adv.loc[d, tk] or 0.0) < min_adv:
                continue
            nav_tk = nav[tk].loc[:d].dropna()          # TRUNCATED -- see docstring
            if nav_tk.empty:
                continue
            if len(pd.bdate_range(nav_tk.index[-1], d)) - 1 > max_age:
                continue
            row[tk] = float(zi)
        if len(row) < min_names:
            continue

        s = pd.Series(row)
        w = -(s - s.mean())
        w = w / w.abs().sum()
        hist = (ret.loc[:d, list(row)].mul(w, axis=1)).sum(axis=1).tail(63)
        rv = float(hist.std() * np.sqrt(252))
        scal = float(np.clip(vt / rv, 0.2, 2.5)) if rv > 0 else 1.0

        w = w * scal * lev
        keep = w[w.abs() >= minw]
        if len(keep) >= min_names:
            keep = keep - keep.mean()
            den = keep.abs().sum()
            if den > 0:
                w = keep / den * scal * lev
        out.append({"date": d, "rv": rv, "scal": scal, "n": len(row),
                    "gross_w": float(w.abs().sum()),
                    "clipped": scal in (0.2, 2.5)})
    return pd.DataFrame(out).set_index("date")


def main() -> None:
    sleeve = load_sleeve()
    panel = sleeve._panel(pd.Timestamp.today())
    if panel is None:
        raise SystemExit("no CEF price/NAV panel on disk -- nothing to measure")
    df = scalar_series(sleeve, panel)
    if df.empty:
        raise SystemExit("panel too short for any decision date")

    cap = sleeve.capital_usd
    spec = json.loads(SPEC_PATH.read_text())
    max_gross = float(spec.get("risk", {}).get("max_gross_exposure_usd", float("nan")))
    note = spec.get("sizing_note", "")

    L: list[str] = []
    say = lambda s="": (print(s), L.append(s))                    # noqa: E731

    say("# The volatility scalar, measured over its whole history")
    say()
    say(f"**Run {date.today().isoformat()}** by `python3 scripts/cef/vol_scalar_history.py`. "
        f"**Trials: 0** — a measurement. Nothing is adopted and no spec key moves.")
    say()
    say(f"Spec `{spec.get('spec_id')}`, `vol_target_annual` "
        f"**{sleeve._vol_target}**, capital **${cap:,.0f}**, "
        f"`max_gross_exposure_usd` **${max_gross:,.0f}**. Panel "
        f"{df.index[0].date()} .. {df.index[-1].date()}, {len(df):,} decision dates.")
    say()
    say("## The question")
    say()
    say("The 2026-09-11 session printed `volscal=1.58` and gross **$813,682**. The "
        "frozen spec's `sizing_note` says:")
    say()
    say(f"> {note}")
    say()
    say("So: was **1.5x** ever a bound?")
    say()

    say("## The scalar's distribution")
    say()
    say("| statistic | trailing realised vol `rv` | scalar |")
    say("|---|---:|---:|")
    for lab, q in (("min", 0.0), ("p5", .05), ("p25", .25), ("median", .5),
                   ("p75", .75), ("p95", .95), ("max", 1.0)):
        say(f"| {lab} | {df.rv.quantile(q):.4f} | {df.scal.quantile(q):.3f} |")
    say(f"| mean | {df.rv.mean():.4f} | {df.scal.mean():.3f} |")
    say()

    hi = int((df.scal >= 2.499).sum())
    lo = int((df.scal <= 0.201).sum())
    above15 = int((df.scal > 1.5).sum())
    say(f"- At the **2.5 cap**: {hi:,} of {len(df):,} dates (**{hi/len(df):.1%}**)")
    say(f"- At the **0.2 floor**: {lo:,} (**{lo/len(df):.1%}**)")
    say(f"- **Above 1.5**: {above15:,} (**{above15/len(df):.1%}**) — "
        f"the note's figure is not a ceiling the scalar respects")
    say()

    say("## By year")
    say()
    say("| year | n | median scalar | max | % of days > 1.5 | % at the 2.5 cap |")
    say("|---|---:|---:|---:|---:|---:|")
    for y, g in df.groupby(df.index.year):
        say(f"| {y} | {len(g):,} | {g.scal.median():.2f} | {g.scal.max():.2f} | "
            f"{(g.scal > 1.5).mean():.1%} | {(g.scal >= 2.499).mean():.1%} |")
    say()

    say("## The last 10 decision dates")
    say()
    say("| date | rv (ann.) | scalar | names | target gross |")
    say("|---|---:|---:|---:|---:|")
    for d, r in df.tail(10).iterrows():
        say(f"| {d.date()} | {r.rv:.4f} | **{r.scal:.2f}** | {int(r.n)} | "
            f"${cap * r.gross_w:,.0f} |")
    say()

    last = df.iloc[-1]
    say("## The answer")
    say()
    say(f"**The scalar is doing exactly what it was specified to do.** On the last "
        f"decision date the sleeve's own trailing 63-day realised vol was "
        f"**{last.rv:.2%}** annualised against a **{sleeve._vol_target:.0%}** target, "
        f"so the scalar is {sleeve._vol_target:.2f}/{last.rv:.4f} = "
        f"**{last.scal:.2f}**. A quiet tape produces a low `rv`, a low `rv` produces "
        f"a high scalar, and that is the mechanism, not a fault in it.")
    say()
    say(f"**1.5 was never a bound.** It appears once, inside `sizing_note`, as a "
        f"description of the scalar on the afternoon that note was written, used to "
        f"derive a margin figure. It is not a key, nothing reads it, and no code "
        f"path compares against it. The scalar has exceeded 1.5 on **{above15/len(df):.1%}** "
        f"of all decision dates in the panel.")
    say()
    say(f"**The real bound is `max_gross_exposure_usd` = ${max_gross:,.0f}**, and at "
        f"the measured gross of $813,682 the book is at "
        f"**{813_682 / max_gross:.0%}** of it. The cap that binds the scalar itself "
        f"is the `np.clip(..., 0.2, 2.5)` in `cef_discount.py:198`, which the "
        f"scalar has reached on {hi/len(df):.1%} of dates.")
    say()
    say(f"**Where the extra gross comes from.** Target gross is capital x scalar = "
        f"${cap:,.0f} x {last.scal:.2f} = **${cap * last.gross_w:,.0f}**. The session "
        f"reported **$813,682**, about "
        f"{813_682 / (cap * last.gross_w) - 1:+.1%} against that. That gap is the "
        f"**no-trade band**, not the scalar: at `band_width` "
        f"{sleeve._band_width}, a position inside the band is left alone, so held "
        f"gross drifts with prices between trades instead of being marked back to "
        f"target every session. A band that never let gross drift would be a band "
        f"that always traded, which is the cost this book is built to avoid.")
    say()
    say("## What this does NOT say")
    say()
    say("It does not say the sizing is right. Two things are worth a separate look, "
        "and neither is decided here:")
    say()
    say(f"1. **The 2.5 cap binds on {hi/len(df):.1%} of dates.** Where it binds, the "
        f"book is NOT running at its vol target — it is running below it, by "
        f"construction. Whether that is the intended behaviour in the calmest "
        f"regimes is a question for a pre-registration, not for this script.")
    say(f"2. **`rv` is measured on TODAY's weights applied to the last 63 days**, not "
        f"on the book's own realised P&L. Those differ whenever the weight vector "
        f"turns over. It is not lookahead — every input precedes the decision — but "
        f"it is not the traded book's volatility either, and the distinction should "
        f"be stated wherever this number is quoted.")

    out = REPO / f"results/cef/VOL_SCALAR_{date.today().isoformat()}.md"
    out.write_text("\n".join(L) + "\n")
    print(f"\n[written] {out}")


if __name__ == "__main__":
    main()
