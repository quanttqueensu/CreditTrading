"""Block B charts. Every book on one axis, identical accounting."""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results/bench/charts"
OUT.mkdir(parents=True, exist_ok=True)

d = pd.read_parquet(REPO / "results/bench/benchmark_daily.parquet")
d.index = pd.to_datetime(d.index)
books = sorted(d.book.unique())
cmap = plt.get_cmap("tab10")
col = {b: cmap(i % 10) for i, b in enumerate(books)}

def series(b, c="excess_ret"):
    return d[d.book == b][c].dropna()

# 1 cumulative net equity ------------------------------------------------------
fig, ax = plt.subplots(figsize=(13, 7))
for b in books:
    s = series(b)
    ax.plot(s.index, (1 + s).cumprod(), label=b, color=col[b],
            lw=2.2 if b in ("B2_HY_carry_dhedged", "B8_naive_raw_PD") else 1.2)
ax.set_yscale("log"); ax.axhline(1, color="k", lw=.6, ls=":")
ax.set_title("Cumulative net equity, excess of risk-free — nine benchmark books\n"
             "identical cost model, fills and accounting", fontsize=12)
ax.set_ylabel("growth of 1 (log)"); ax.legend(fontsize=8, ncol=2); ax.grid(alpha=.25)
fig.tight_layout(); fig.savefig(OUT / "01_cumulative_equity.png", dpi=130); plt.close(fig)

# 2 rolling 63d Sharpe ---------------------------------------------------------
fig, ax = plt.subplots(figsize=(13, 6))
for b in books:
    if b == "B9_null_trader":
        continue
    s = series(b)
    rs = s.rolling(63).mean() / s.rolling(63).std() * np.sqrt(252)
    ax.plot(rs.index, rs, label=b, color=col[b], lw=1.0)
ax.axhline(0, color="k", lw=.6)
ax.set_title("Rolling 63-day net Sharpe (null trader omitted for scale)")
ax.set_ylim(-6, 6); ax.legend(fontsize=8, ncol=2); ax.grid(alpha=.25)
fig.tight_layout(); fig.savefig(OUT / "02_rolling_sharpe.png", dpi=130); plt.close(fig)

# 3 underwater -----------------------------------------------------------------
fig, ax = plt.subplots(figsize=(13, 6))
for b in books:
    if b == "B9_null_trader":
        continue
    eq = (1 + series(b)).cumprod()
    ax.plot(eq.index, 100 * (eq / eq.cummax() - 1), label=b, color=col[b], lw=1.0)
ax.set_title("Underwater drawdown, % (null trader omitted: monotone by construction)")
ax.set_ylabel("%"); ax.legend(fontsize=8, ncol=2); ax.grid(alpha=.25)
fig.tight_layout(); fig.savefig(OUT / "03_drawdown.png", dpi=130); plt.close(fig)

# 4 rolling 63d correlation to B2 (the benchmark that matters) -----------------
fig, ax = plt.subplots(figsize=(13, 6))
base = series("B2_HY_carry_dhedged")
for b in books:
    if b == "B2_HY_carry_dhedged":
        continue
    s = series(b)
    j = pd.concat([s.rename("x"), base.rename("y")], axis=1).dropna()
    ax.plot(j.index, j.x.rolling(63).corr(j.y), label=b, color=col[b], lw=1.0)
ax.axhline(0, color="k", lw=.6)
ax.set_title("Rolling 63-day correlation to B2 (duration-hedged HY carry)")
ax.set_ylim(-1, 1); ax.legend(fontsize=8, ncol=2); ax.grid(alpha=.25)
fig.tight_layout(); fig.savefig(OUT / "04_corr_to_B2.png", dpi=130); plt.close(fig)

# 5 cost as share of gross P&L -------------------------------------------------
fig, ax = plt.subplots(figsize=(13, 6))
for b in books:
    g = d[d.book == b]
    cost = (g.cost_usd + g.fin_usd.clip(lower=0)).rolling(252).sum()
    grossp = g.gross_ret.abs().rolling(252).sum() * 640_000
    ax.plot(g.index, 100 * (cost / grossp.replace(0, np.nan)), label=b,
            color=col[b], lw=1.0)
ax.set_title("Trailing 1y cost as % of gross P&L (|gross| basis)")
ax.set_ylim(0, 120); ax.set_ylabel("%"); ax.legend(fontsize=8, ncol=2); ax.grid(alpha=.25)
fig.tight_layout(); fig.savefig(OUT / "05_cost_share.png", dpi=130); plt.close(fig)

# 6 turnover -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(13, 6))
for b in books:
    g = d[d.book == b]
    ax.plot(g.index, g.turnover.rolling(63).mean() * 252, label=b, color=col[b], lw=1.0)
ax.set_yscale("symlog"); ax.set_title("Annualised turnover (63d mean of sum|dw| x 252)")
ax.legend(fontsize=8, ncol=2); ax.grid(alpha=.25)
fig.tight_layout(); fig.savefig(OUT / "06_turnover.png", dpi=130); plt.close(fig)

print("wrote:")
for p in sorted(OUT.glob("*.png")):
    print(f"  {p.relative_to(REPO)}  {p.stat().st_size//1024}kb")
print("\nNOT produced (require a live strategy to compare against, none has yet "
      "cleared a gate):\n  - return attribution by sleeve\n  - realized vs modelled "
      "slippage scatter (needs executed fills; the Phase 0 null trader has 1 "
      "session of live fills, too few to plot)")
