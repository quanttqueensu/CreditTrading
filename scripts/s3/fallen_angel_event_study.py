"""Test 4 -- the identification argument. Forced, information-free flow.

The hardest problem in flow research is that flow and information are tangled. If
a fund is redeemed because holders know something, the price move that follows is
news, not mispricing, and there is nothing to trade.

Index migrations break the tangle. When a bond is cut from investment grade to
high yield it leaves the IG indices, and every fund tracking those indices must
sell it -- not because the fund has a view, but because its mandate forbids
holding it. The downgrade was public earlier and is already in the price; the
selling at the index flip is mechanical and carries no information.

  pressure    => price falls into the flip and RECOVERS after
  information => price falls and STAYS down

Two things this file is careful about, because the naive version of this study
produces a large fake reversal:

1. EVENT TIME IS CALENDAR TIME. Corporate bonds do not trade every day. Ranking
   observed trades makes "60 days after" mean a year later for an illiquid bond.
   Every event is therefore laid on a fixed business-day grid around the flip and
   prices are held flat across days with no trade.

2. THE PANEL IS BALANCED. Bonds that stop trading after a downgrade are the
   distressed ones. Letting them drop out of the sample as the window advances
   leaves only the survivors and manufactures a recovery out of nothing. Only
   bonds observed at BOTH ends of the window are admitted, and the count is
   constant across the whole window by construction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
PANEL = REPO / "data/forced_flow2/bond_day_panel"
OUT = REPO / "results/s3"
OUT.mkdir(parents=True, exist_ok=True)

PRE, POST = 40, 60           # business days either side of the index flip
MIN_TRADE_DAYS = 20          # bond must actually trade this often in the window


def load_events() -> pd.DataFrame:
    e = pd.read_parquet(REPO / "data/forced_flow2/m6_events.parquet")
    e["day0"] = pd.to_datetime(e["day0"])
    e = e[["cusip_id", "day0", "path"]].dropna(subset=["day0"])
    return e.drop_duplicates(subset=["cusip_id"])          # first flip per bond


def load_panel(years, cusips):
    cols = ["cusip_id", "dt", "n_trades", "vwap_all", "grade",
            "cust_sell_par", "cust_buy_par"]
    keep, med = [], []
    for y in years:
        p = PANEL / f"year={y}" / "data_0.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p, columns=cols)
        d["dt"] = pd.to_datetime(d["dt"])
        d = d[d.vwap_all.between(20, 200)]
        d = d.sort_values(["cusip_id", "dt"])
        d["ret"] = d.groupby("cusip_id").vwap_all.pct_change()
        d.loc[d.ret.abs() > 0.25, "ret"] = np.nan
        med.append(d.groupby(["dt", "grade"]).ret.median().rename("mkt").reset_index())
        keep.append(d[d.cusip_id.isin(cusips)])
        print(f"  {y}: {len(d):>9,} bond-days  {len(keep[-1]):>7,} on event bonds")
    return pd.concat(keep, ignore_index=True), pd.concat(med, ignore_index=True)


def main() -> int:
    ev = load_events()
    print(f"events: {len(ev):,}  {ev.day0.min().date()} -> {ev.day0.max().date()}")
    yrs = range(2003, 2026)
    print(f"loading TRACE {yrs.start}-{yrs.stop-1} ...")
    d, med = load_panel(yrs, set(ev.cusip_id))

    d = d.merge(ev, on="cusip_id", how="inner")
    # --- calendar event time, not trade-count event time --------------------
    d["k"] = (d.dt.values.astype("datetime64[D]") -
              d.day0.values.astype("datetime64[D]")).astype(int)
    d["k"] = [np.busday_count(a, b) for a, b in
              zip(d.day0.values.astype("datetime64[D]"),
                  d.dt.values.astype("datetime64[D]"))]
    d = d[(d.k >= -PRE) & (d.k <= POST)]

    # --- lay each event on a full business-day grid, hold price flat --------
    d = d.merge(med, on=["dt", "grade"], how="left")
    grid = np.arange(-PRE, POST + 1)
    piv_p = d.pivot_table(index="cusip_id", columns="k", values="vwap_all",
                          aggfunc="last").reindex(columns=grid)
    piv_m = d.pivot_table(index="cusip_id", columns="k", values="mkt",
                          aggfunc="last").reindex(columns=grid)
    traded = piv_p.notna().sum(axis=1)
    piv_p.to_parquet(OUT / "_cache_px.parquet")
    piv_m.to_parquet(OUT / "_cache_mkt.parquet")
    d[["cusip_id", "k", "cust_sell_par", "cust_buy_par"]].to_parquet(
        OUT / "_cache_flow.parquet", index=False)

    # --- BALANCED: observed at both ends, and actually trades ---------------
    ok = (piv_p[grid[grid <= -PRE + 5]].notna().any(axis=1) &
          piv_p[grid[grid >= POST - 5]].notna().any(axis=1) &
          (traded >= MIN_TRADE_DAYS))
    piv_p, piv_m = piv_p[ok], piv_m[ok]
    n = len(piv_p)
    print(f"\nevents in window          {len(traded):,}")
    print(f"balanced + traded >= {MIN_TRADE_DAYS}d  {n:,}   "
          f"(constant across the whole window by construction)")
    if n < 200:
        print("too few events to conclude"); return 1

    px = piv_p.ffill(axis=1).bfill(axis=1)
    ret = px.pct_change(axis=1)
    mkt = piv_m.fillna(0.0)
    abn = (ret - mkt).clip(-0.25, 0.25)

    car = abn.cumsum(axis=1)
    mean = car.mean() * 1e4
    se = car.std() / np.sqrt(n) * 1e4
    res = pd.DataFrame({"car_bp": mean, "se_bp": se, "t": mean / se, "n": n})
    res.to_csv(OUT / "fallen_angel_car.csv")

    print("\n" + "=" * 74)
    print("CUMULATIVE ABNORMAL RETURN around forced index deletion (bp)")
    print("  balanced panel, business-day event time, vs median same-grade bond")
    print("=" * 74)
    print(f"  {'k':>5}{'CAR bp':>11}{'+-se':>9}{'t':>8}")
    for k in [-40, -30, -20, -10, -5, -2, 0, 1, 2, 3, 5, 10, 20, 30, 40, 60]:
        if k in res.index:
            r = res.loc[k]
            print(f"  {k:>5}{r.car_bp:>11.1f}{r.se_bp:>9.1f}{r.t:>8.2f}")

    tr = res.car_bp.loc[-PRE:5].idxmin()
    rec = res.car_bp.loc[POST] - res.car_bp.loc[tr]
    dd = res.car_bp.loc[tr]
    print(f"\n  trough  k={tr}: {dd:+.1f}bp")
    print(f"  recovery to k={POST}: {rec:+.1f}bp = "
          f"{100*rec/abs(dd) if dd else 0:.0f}% of the drawdown")

    # --- was the selling actually forced? -----------------------------------
    fl = d[d.cusip_id.isin(piv_p.index)]
    f = fl.groupby("k")[["cust_sell_par", "cust_buy_par"]].sum()
    f["imb"] = ((f.cust_sell_par - f.cust_buy_par) /
                (f.cust_sell_par + f.cust_buy_par).replace(0, np.nan))
    f.to_csv(OUT / "fallen_angel_flow.csv")
    print("\n" + "=" * 74)
    print("CUSTOMER SELL IMBALANCE (>0 = customers net sellers to dealers)")
    print("  the mechanism REQUIRES forced selling to show up here")
    print("=" * 74)
    print(f"  {'window':>12}{'imbalance':>12}")
    for lo, hi, lab in [(-40, -21, "k -40..-21"), (-20, -6, "k -20..-6"),
                        (-5, -1, "k -5..-1"), (0, 2, "k 0..+2"),
                        (3, 10, "k +3..+10"), (11, 30, "k +11..+30"),
                        (31, 60, "k +31..+60")]:
        w = f.loc[lo:hi]
        num = (w.cust_sell_par - w.cust_buy_par).sum()
        den = (w.cust_sell_par + w.cust_buy_par).sum()
        print(f"  {lab:>12}{num/den if den else np.nan:>12.4f}")
    print(f"\nwrote {OUT/'fallen_angel_car.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
