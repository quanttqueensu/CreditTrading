"""S3 expressed in tradable instruments: fallen-angel ETF vs broad high yield.

The bond-level event study says a bond forced out of investment grade is pushed
down ~400bp and recovers ~85% of it over the following 60 business days. Bonds
are not tradable at our size, so the question is whether that pressure can be
harvested through the wrapper.

ANGL and FALN hold precisely the bonds that were just forced out of IG. HYG holds
broad high yield. So when a lot of bonds migrate, the fallen-angel funds are
holding freshly-depressed paper and should outperform broad HY as it recovers.

  signal(t)   = z-score of migration intensity over the trailing 21 business days
  position    = long ANGL, short beta x HYG   (beta rolling 126d, PIT)
  horizon     = the 60 business days over which the bond study says it reverts

Point-in-time: an event enters the signal only on its index-flip date day0, which
is the day the forced selling actually happens and is public. Trading starts the
next session. The rating action that caused it was public earlier still, so no
information is used before the market had it.

Negative control: the identical signal on a Treasury pair, where no bond is ever
forced out of an index by a downgrade and the mechanism cannot operate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.bench.run_benchmarks import (  # noqa: E402
    load_panel, load_rates, run_book, stats, CAPITAL)
from src.strategies.credit_rv.costs import SCENARIOS  # noqa: E402

OUT = REPO / "results/s3"
OUT.mkdir(parents=True, exist_ok=True)


def migration_intensity(idx: pd.DatetimeIndex, win: int = 21) -> pd.Series:
    """Bonds forced out of IG in the trailing `win` sessions, as a z-score."""
    e = pd.read_parquet(REPO / "data/forced_flow2/m6_events.parquet")
    e["day0"] = pd.to_datetime(e["day0"])
    daily = e.groupby("day0").size().reindex(idx, fill_value=0).astype(float)
    roll = daily.rolling(win, min_periods=win).sum()
    # normalise against the fund's own trailing 3y history, ending YESTERDAY
    mu = roll.shift(1).rolling(756, min_periods=252).mean()
    sd = roll.shift(1).rolling(756, min_periods=252).std()
    return ((roll - mu) / sd.replace(0, np.nan)).clip(-4, 4)


def hedged_pair(long_tk: str, short_tk: str, ret: pd.DataFrame,
                idx: pd.DatetimeIndex, sig: pd.Series, hold: int) -> pd.DataFrame:
    """Long `long_tk`, short rolling-beta x `short_tk`, scaled by the signal."""
    both = ret[[long_tk, short_tk]].dropna()
    cov = both[long_tk].rolling(126).cov(both[short_tk])
    var = both[short_tk].rolling(126).var()
    beta = (cov / var).shift(1).reindex(idx).ffill().clip(0.2, 2.5)

    # hold the signal for `hold` sessions: average of the last `hold` entries,
    # which is the standard overlapping-portfolio construction and keeps
    # turnover at 1/hold of the naive version.
    s = sig.reindex(idx)
    pos = s.rolling(hold, min_periods=1).mean().clip(-2, 2)
    w = pd.DataFrame({long_tk: pos, short_tk: -pos * beta}, index=idx)
    return w.fillna(0.0)


def main() -> int:
    px, ret, adv, dayvol_bp = load_panel()
    rf = load_rates()
    cm = SCENARIOS["base"]
    rows = []

    for long_tk, short_tk, start in [("ANGL", "HYG", "2013-06-01"),
                                     ("FALN", "HYG", "2017-06-01"),
                                     ("ANGL", "JNK", "2013-06-01"),
                                     ("IEF", "TLT", "2013-06-01")]:   # UST control
        if long_tk not in ret.columns or short_tk not in ret.columns:
            print(f"skip {long_tk}/{short_tk}: missing"); continue
        idx = ret.index[(ret.index >= start) &
                        ret[long_tk].notna() & ret[short_tk].notna()]
        if len(idx) < 500:
            print(f"skip {long_tk}/{short_tk}: only {len(idx)} sessions"); continue
        sig = migration_intensity(ret.index).reindex(idx)

        for hold in (21, 42, 63):
            w = hedged_pair(long_tk, short_tk, ret, idx, sig, hold)
            name = f"{long_tk}/{short_tk} h={hold}"
            df = run_book(name, w, ret, px, adv, dayvol_bp, rf, cm)
            st = stats(df)
            if st:
                st["pair"] = f"{long_tk}/{short_tk}"
                st["hold"] = hold
                st["control"] = long_tk == "IEF"
                rows.append(st)

    r = pd.DataFrame(rows)
    r.to_csv(OUT / "angl_expression.csv", index=False)
    print("=" * 96)
    print("FALLEN-ANGEL PRESSURE, EXPRESSED IN TRADABLE ETFs")
    print("  long fallen-angel fund / short beta x broad HY, scaled by migration z")
    print("  same cost model, fills and accounting as the nine benchmark books")
    print("=" * 96)
    print(f"{'book':<22}{'from':>11}{'N':>7}{'CAGR%':>8}{'vol%':>7}"
          f"{'net SR':>8}{'gr SR':>7}{'maxDD%':>8}{'turn/yr':>9}{'tcost bp':>10}")
    for _, x in r.iterrows():
        tag = "  <-- CONTROL, must be flat" if x.control else ""
        print(f"{x.book:<22}{x.start:>11}{x.N:>7,}{x.cagr:>8.2f}{x.vol:>7.2f}"
              f"{x.sharpe:>8.2f}{x.gross_sharpe:>7.2f}{x.maxdd:>8.1f}"
              f"{x.turnover:>9.1f}{x.tcost_bp_yr:>10.0f}{tag}")
    print("\nhurdle to beat: B2 duration-hedged HY carry, net Sharpe 0.54 "
          "(0.47 in 2023-26)")
    print(f"wrote {OUT/'angl_expression.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
