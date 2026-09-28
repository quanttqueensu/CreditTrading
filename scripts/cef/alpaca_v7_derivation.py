"""Derive and report the cef_discount spec for the Alpaca paper account (v7-on-Alpaca).

    python3 scripts/cef/alpaca_v7_derivation.py

WHY THIS EXISTS
---------------
On 2026-09-28 the team lead moved the book to Alpaca paper and decided, from the
first account probe (`results/ops/alpaca_probe/2026-09-28_cef.json`), to drop the
four funds Alpaca will not let us short: NAD, NEA, NVG, NZF. That changes the
universe, which changes every quantity the v7 constraints were derived from, so
each is re-derived here by the rule its pre-registration fixed
(`results/cef/PREREG_GROUP_CAP_2026-09-16.md` §3), on the book that will trade.

VALIDATION FIRST. The derivation code is only trusted because it reproduces the
two recorded 17-name figures exactly before it is pointed at 13 names:
k = 0.304953 (median |net muni-minus-taxable weight| on targets, 2013-06-14 ..
2022-12-30) and w5 = 0.038264817497540925 (worst 5-session total-return loss per
unit of gross held, ending 2020-03-18). If either stops reproducing, this script
raises rather than printing a derivation it cannot vouch for.

CONVENTIONS (all from the harness, none re-implemented): targets from
`band_frontier.build_targets`, the band from `band_frontier.band` /
`band_gross_capped`, P&L from `band_frontier.evaluate` (shift(2)), total returns
from `band_frontier.total_returns`. Scoring is GROSS P&L (D19/D20); the cost grid
is a labelled sensitivity. Report only: the team lead ruled the change goes ahead
on tradability grounds whatever these numbers say.

Reads `data/` only; writes nothing.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.cef import band_frontier as bf                       # noqa: E402
from scripts.cef.spec import BAND_WIDTH, UNIVERSE                 # noqa: E402

DROPPED = ("NAD", "NEA", "NVG", "NZF")        # team lead, 2026-09-28
TRADED_START = "2013-06-14"                    # the traded era, as pre-registered
FIT_END = "2022-12-30"                         # k is fit before 2023 (H13)
MARGIN = 0.50                                  # team lead: Reg T initial, 2026-09-28
ERAS = [("2005-09", "2005", "2009"), ("2010-14", "2010", "2014"),
        ("2015-19", "2015", "2019"), ("2020-22", "2020", "2022"),
        ("2023-26", "2023", "2026")]
RECORDED_K17 = 0.304953
RECORDED_W5_17 = 0.038264817497540925


def groups(universe) -> tuple[list, list]:
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet", columns=["ticker", "grp"])
    g = P.drop_duplicates("ticker").set_index("ticker")["grp"]
    missing = [t for t in universe if t not in g.index or pd.isna(g[t])]
    if missing:
        raise KeyError(f"no `grp` for {missing} in data/cef/cef_prices.parquet")
    return ([t for t in universe if g[t] == "muni"],
            [t for t in universe if g[t] != "muni"])


def k_median(T, universe) -> float:
    muni, tax = groups(universe)
    g = (T[muni].sum(axis=1) - T[tax].sum(axis=1)).loc[TRADED_START:FIT_END]
    return float(g.abs().median())


def w5(H, Rt) -> tuple[float, pd.Timestamp]:
    """Worst 5-session loss per unit gross: P&L on day t over the gross of the
    weights that earned it (decided t-2, shift(2)), summed over 5 sessions."""
    pnl = bf.evaluate(H, Rt)["pnl"]
    x = pnl / H.abs().sum(axis=1).shift(2).replace(0, np.nan)
    r5 = x.loc[TRADED_START:].rolling(5).sum()
    return float(-r5.min()), r5.idxmin()


def stats(H, Rt, a=None, b=None) -> dict:
    Hs, Rs = (H.loc[a:b], Rt.loc[a:b]) if a else (H.loc[TRADED_START:], Rt.loc[TRADED_START:])
    if float(Hs.abs().sum(axis=1).max()) == 0.0:
        return None                     # the book is flat in this window (H5)
    r = bf.evaluate(Hs, Rs)
    pnl = r["pnl"]
    eq = (1 + pnl).cumprod()
    gross = Hs.abs().sum(axis=1)
    return dict(sr=r["gross_sr"], ann=r["ann_ret"] * 100, vol=r["vol"] * 100,
                mdd=float((eq / eq.cummax() - 1).min() * 100), turn=r["turn"],
                g_mean=float(gross.mean()), g_max=float(gross.max()),
                net=[(r["ann_ret"] - r["turn"] * c / 1e4) / r["vol"] for c in (5, 15, 30)])


def main() -> int:
    u17 = list(UNIVERSE)
    u13 = [t for t in u17 if t not in DROPPED]

    # -- 1. validation on 17 names ------------------------------------------
    T17, R17 = bf.build_targets(u17)
    Rt17 = bf.total_returns(R17)
    H17 = bf.band(T17, BAND_WIDTH)
    k17 = k_median(T17, u17)
    w17, d17 = w5(H17, Rt17)
    print("VALIDATION (17 names, must reproduce the recorded figures)")
    print(f"  k  median |g| on targets  {k17:.6f}   recorded {RECORDED_K17}")
    print(f"  w5                         {w17:.15f} ending {d17.date()}   recorded {RECORDED_W5_17}")
    if round(k17, 6) != RECORDED_K17 or abs(w17 - RECORDED_W5_17) > 1e-12:
        raise RuntimeError("the derivation no longer reproduces the recorded 17-name "
                           "figures; refusing to derive for 13 names with it")

    # -- 2. derivation on 13 names ------------------------------------------
    T13, R13 = bf.build_targets(u13)
    Rt13 = bf.total_returns(R13)
    H13 = bf.band(T13, BAND_WIDTH)
    muni13, _ = groups(u13)
    k13 = k_median(T13, u13)
    w13, d13 = w5(H13, Rt13)
    held = (T13.loc[TRADED_START:FIT_END, muni13].abs().sum(axis=1) > 0).mean()
    G = 1.0 / (MARGIN + w13)        # (NLV - M_other)/(m + w5)/E_book, NLV = E_book, M_other = 0
    cap = math.floor(G / 0.05 + 1e-12) * 0.05
    print(f"\nDERIVATION (13 names: {', '.join(u13)})")
    print(f"  group_cap rule: median |g| on targets = {k13:.6f} -> k = {round(k13, 2):.2f}"
          f"   (muni names {muni13} have any target on {held:.1%} of pre-2023 traded days)")
    print(f"  w5 = {w13:.10f} ending {d13.date()}")
    print(f"  G_stress = 1/({MARGIN} + w5) = {G:.6f}   -> max_gross_stress = floor_0.05 = {cap:.2f}")

    # -- 3. report (not a gate) ---------------------------------------------
    books = {"v6 band, 17 names": H17,
             "band, 13 names": H13,
             f"band + gross cap {cap:.2f}, 13": bf.band_gross_capped(T13, BAND_WIDTH, cap)}
    rets = {"v6 band, 17 names": Rt17, "band, 13 names": Rt13,
            f"band + gross cap {cap:.2f}, 13": Rt13}
    print(f"\nREPORT — gross P&L (total returns), shift(2), band {BAND_WIDTH:.1%}, traded era "
          f"{TRADED_START}..; net columns are a COST SENSITIVITY, not the score")
    hdr = (f"{'book':<28}{'grossSR':>8}{'ann%':>7}{'vol%':>7}{'maxDD%':>8}{'turn/yr':>8}"
           f"{'gross avg':>10}{'gross max':>10}{'net@5':>7}{'net@15':>7}{'net@30':>7}")
    print(hdr)
    for name, H in books.items():
        s = stats(H, rets[name])
        print(f"{name:<28}{s['sr']:8.2f}{s['ann']:7.2f}{s['vol']:7.2f}{s['mdd']:8.2f}"
              f"{s['turn']:8.1f}{s['g_mean']:10.2f}{s['g_max']:10.2f}"
              + "".join(f"{n:7.2f}" for n in s["net"]))
    Hc = books[f"band + gross cap {cap:.2f}, 13"]
    bind = (H13.abs().sum(axis=1).loc[TRADED_START:] > cap).mean()
    print(f"  the gross cap binds on {bind:.1%} of traded days (uncapped 13-name band above {cap:.2f})")

    print("\nBY ERA — gross SR (ann %)")
    print(f"{'book':<28}" + "".join(f"{e[0]:>15}" for e in ERAS) + f"{'last 12m':>15}")
    last = Hc.index[-252]
    for name, H in books.items():
        cells = []
        for _, a, b in ERAS + [("", str(last.date()), None)]:
            s = stats(H, rets[name], a, b)
            cells.append("flat" if s is None else f"{s['sr']:6.2f} ({s['ann']:5.1f})")
        print(f"{name:<28}" + "".join(f"{c:>15}" for c in cells))

    print("\nPLATEAU of the gross cap on 13 names (H8: shown to prove the derived value "
          "is not on a cliff; the value comes from the margin arithmetic, not from this)")
    for c in (1.60, 1.70, cap, round(G, 4), 2.00, np.inf):
        s = stats(bf.band_gross_capped(T13, BAND_WIDTH, c), Rt13)
        print(f"  cap {c:>7}  gross SR {s['sr']:.3f}  ann {s['ann']:.2f}%  max gross {s['g_max']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
