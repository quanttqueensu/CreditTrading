"""Can the pair sleeve be levered to a 12% vol target? Priced three ways.

The sleeve's problem is not signal, it is size: 22 diversified pairs produce
0.37% annualised vol, and the mandate wants 12%. This file asks what actually
stops us getting there, and prices each candidate answer with real numbers.

THE FUTURES QUESTION, ANSWERED FIRST. Substituting Treasury futures for a cash
rates leg is a large margin saving -- ZN carries a $2,063 CME performance bond on
roughly $110k of notional, about 1.9%, against Reg T's 50% on an ETF. But every
pair in this sleeve is credit-versus-credit (HYG/JNK, LQD/VCIT, IGLB/VCLT). There
is no rates leg to convert. Futures cannot help a book that holds no duration.

WHAT CAN HELP is the margin REGIME, because a beta-hedged credit pair nets. Reg T
charges 50% on each side and cannot see the hedge. PortfolioMargin nets credit
DV01 across the book BEFORE applying the shock, so an offsetting pair collapses to
the 5%-of-gross floor -- a 10x capital efficiency the cash rules cannot express.

AND THE CONSTRAINT THAT ACTUALLY BINDS is market impact. Leverage multiplies the
clip size in every name, and the thin legs (ANGL at $20m ADV, JBBB at $15m) run
into their own book long before margin runs out. This file finds which limit hits
first, which is the whole point -- there is no use freeing margin we cannot trade
into.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.strategies.credit_rv.costs import SCENARIOS  # noqa: E402
from scripts.ou.ou_band_sleeve import PAIRS, load  # noqa: E402

CM = SCENARIOS["base"]
EQUITY = 640_000.0
REGT_FRAC = 0.50          # Reg T initial, each side of a long/short book
PM_FLOOR = 0.05           # PortfolioMargin floor on gross (src/deploy/lib/margin.py)
MAX_PARTICIPATION = 0.05  # cost model's own guard
TARGETS = (6.0, 8.0, 12.0, 15.0)


def main() -> int:
    cl, mid, adv = load()
    W = pd.read_parquet(REPO / "results/ou/pair_net_returns.parquet")
    combo = W.fillna(0.0)
    iv = 1.0 / combo.rolling(126, min_periods=60).std().shift(1)
    iv = iv.div(iv.sum(axis=1), axis=0)
    r = (combo * iv.fillna(0.0)).sum(axis=1)
    base_vol = r.std() * np.sqrt(252) * 100.0

    # gross of the unlevered book: each pair holds long + beta*short at its
    # inverse-vol weight, so gross ~ sum over pairs of w_i * (1 + beta_i) ~ 2x.
    names = [c for c in W.columns]
    legs = {}
    for a, b, k in PAIRS:
        key = f"{a}/{b}"
        if key in names and a in adv.columns and b in adv.columns:
            legs[key] = (a, b, float(adv[a].iloc[-1]), float(adv[b].iloc[-1]))
    base_gross = 2.0

    print("=" * 96)
    print("CAPACITY FRONTIER for the 22-pair sleeve")
    print(f"  equity ${EQUITY:,.0f}   unlevered vol {base_vol:.2f}%   "
          f"unlevered gross {base_gross:.1f}x")
    print("=" * 96)
    print(f"{'vol target':>11}{'leverage':>10}{'gross $':>14}{'RegT margin':>14}"
          f"{'PM margin':>13}{'RegT ok?':>10}{'PM ok?':>9}")
    rows = []
    for tgt in TARGETS:
        lev = tgt / base_vol
        gross_usd = EQUITY * base_gross * lev
        regt = gross_usd * REGT_FRAC
        pm = gross_usd * PM_FLOOR      # credit DV01 nets, so the floor binds
        rows.append((tgt, lev, gross_usd, regt, pm))
        print(f"{tgt:>10.0f}%{lev:>10.1f}x{gross_usd:>14,.0f}{regt:>14,.0f}"
              f"{pm:>13,.0f}{'YES' if regt <= EQUITY else 'NO':>10}"
              f"{'YES' if pm <= EQUITY else 'NO':>9}")

    max_lev_regt = EQUITY / (EQUITY * base_gross * REGT_FRAC)
    max_lev_pm = EQUITY / (EQUITY * base_gross * PM_FLOOR)
    print(f"\n  max leverage under Reg T           {max_lev_regt:>6.1f}x "
          f"-> vol {base_vol*max_lev_regt:>5.2f}%")
    print(f"  max leverage under PortfolioMargin {max_lev_pm:>6.1f}x "
          f"-> vol {base_vol*max_lev_pm:>5.2f}%")

    # ---- does IMPACT bind before margin? ---------------------------------
    print("\n" + "=" * 96)
    print("BUT DOES IMPACT BIND FIRST?  clip per leg vs that name's ADV")
    print(f"  cost model refuses above {MAX_PARTICIPATION:.0%} of ADV; impact starts")
    print("  once a clip exceeds displayed touch depth (0.05% of ADV)")
    print("=" * 96)
    n_pairs = len(legs)
    print(f"{'vol target':>11}{'leverage':>10}{'clip/leg $':>13}"
          f"{'worst name':>12}{'ADV $M':>9}{'participation':>15}{'verdict':>12}")
    for tgt, lev, gross_usd, _, _ in rows:
        per_pair = gross_usd / max(n_pairs, 1)
        clip = per_pair / 2.0                       # two legs per pair
        worst_key, worst_adv, worst_leg = None, np.inf, None
        for key, (a, b, aa, ab) in legs.items():
            for leg, av in ((a, aa), (b, ab)):
                if av < worst_adv:
                    worst_adv, worst_key, worst_leg = av, key, leg
        part = clip / worst_adv if worst_adv else np.inf
        verdict = ("OK" if part <= MAX_PARTICIPATION * 0.2 else
                   "impact" if part <= MAX_PARTICIPATION else "REFUSED")
        print(f"{tgt:>10.0f}%{lev:>10.1f}x{clip:>13,.0f}{worst_leg:>12}"
              f"{worst_adv/1e6:>9.1f}{part:>14.2%}{verdict:>12}")

    # ---- what a futures substitution would be worth, if there were a rates leg
    print("\n" + "=" * 96)
    print("FUTURES SUBSTITUTION -- what it would be worth IF a rates leg existed")
    print("=" * 96)
    import yaml
    spec = yaml.safe_load((REPO / "config/futures_specs.yaml").read_text())
    for code in ("ZF", "ZN", "ZB"):
        s = spec[code]
        notional = 1000.0 * 110.0        # ~$110k per contract at a ~110 handle
        im = float(s["initial_margin_usd"])
        print(f"  {code}: margin ${im:,.0f} on ~${notional:,.0f} notional = "
              f"{im/notional:.2%}  vs Reg T ETF {REGT_FRAC:.0%}  "
              f"-> {REGT_FRAC/(im/notional):.0f}x more efficient")
    print("\n  BUT: all 22 pairs are credit-vs-credit and hold ZERO duration.")
    print("  There is no rates leg to convert, so this saving is unavailable here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
