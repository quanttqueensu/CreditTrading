"""A1 real financing/borrow cost model (refine cycle 2026-07-21).

Replaces v1's flat ``config/costs.yaml::financing_spread_bp = 150`` with a
daily term curve built by ``scripts/refine/build_financing_curve.py`` into
``data/financing_curve.parquet``:

  base_rate_pct  — overnight SOFR (FRED, 2018-04-03 ->) spliced onto EFFR/DFF
                   (pre-2018 backfill), business days, ffilled; annualized %.
  base_source    — "SOFR" | "DFF" per row.

Legs and central spreads over base (annualized bp), with defensible bands
(provenance and citations in the builder script's docstring):

  short_etf      +50  [25, 75]     PB stock-borrow on liquid Treasury/IG ETFs
                                   (general-collateral bucket, fee < 100bp)
  futures_carry  +5   [-10, 25]    CTD implied repo ~ GC/SOFR (CME, Dallas Fed)
  margin_debit   +100 [50, 150]    IBKR Pro USD tiers: BM+1.5% first $100k,
                                   BM+1.0% $100k-$1M (~$300k book blend)
  cash           +0               uninvested cash earns the base rate

Accrual convention matches the repo standard (``riskfree_daily.parquet``):
``daily = annual_pct / 100 / 252``.

Usage:
    from src.deploy.lib.financing import FinancingModel
    fm = FinancingModel()                      # loads data/financing_curve.parquet
    fm.annual_rate_pct(asof, "short_etf")      # central-spread annualized %
    fm.daily_rate(asof, "margin_debit")        # decimal per trading day
    fm.rate_series("short_etf", spread_bp=75)  # band-edge override, full history
    fm.sensitivity("short_etf", [0, 150, 300]) # spread grid -> mean rates

Every H1-H6 A/B in this cycle must be net of THIS model (REFINE_PREREG A1).
The overlay's ~300bp flip point is exposed as ``OVERLAY_FLIP_BP`` so reports
can quote each spread's distance to it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CURVE_PATH = REPO_ROOT / "data" / "financing_curve.parquet"

TRADING_DAYS = 252

# central spreads + bands (annualized bp over base) — keep in sync with the
# builder script, which documents provenance/citations for every number.
SPREADS_BP: dict[str, dict] = {
    "short_etf":     {"central": 50.0,  "band": (25.0, 75.0)},
    "futures_carry": {"central": 5.0,   "band": (-10.0, 25.0)},
    "margin_debit":  {"central": 100.0, "band": (50.0, 150.0)},
    "cash":          {"central": 0.0,   "band": (0.0, 0.0)},
}
V1_FLAT_SPREAD_BP = 150.0   # the flat spread this model replaces
OVERLAY_FLIP_BP = 300.0     # v1 finding: overlay net Sharpe ~0.05 at ~300bp


class FinancingModel:
    """Daily financing-rate lookup on the A1 curve.

    Lookup is as-of (backward-fill-free): the rate for ``asof`` is the last
    curve row with date <= asof; asking for a date before the curve starts
    raises. Dates beyond the last curve row are served only within
    ``max_staleness_days`` (default 7 calendar days) so a stale curve file
    cannot silently price a live book.
    """

    def __init__(self, curve_path: str | Path = DEFAULT_CURVE_PATH,
                 max_staleness_days: int = 7):
        curve_path = Path(curve_path)
        if not curve_path.exists():
            raise FileNotFoundError(
                f"{curve_path} missing — run scripts/refine/build_financing_curve.py first")
        df = pd.read_parquet(curve_path)
        need = {"date", "base_rate_pct", "base_source"}
        missing = need - set(df.columns)
        if missing:
            raise ValueError(f"financing curve missing columns {sorted(missing)}")
        df = df.sort_values("date").reset_index(drop=True)
        if df["base_rate_pct"].isna().any():
            raise ValueError("financing curve has NaN base rates")
        self._curve = df.set_index("date")
        self._base = self._curve["base_rate_pct"]
        self.max_staleness_days = int(max_staleness_days)
        self.start: pd.Timestamp = self._curve.index.min()
        self.end: pd.Timestamp = self._curve.index.max()

    # ----------------------------------------------------------------- core
    def _spread_bp(self, leg: str, spread_bp: float | None) -> float:
        if leg not in SPREADS_BP:
            raise KeyError(f"unknown financing leg {leg!r}; legs: {sorted(SPREADS_BP)}")
        return SPREADS_BP[leg]["central"] if spread_bp is None else float(spread_bp)

    def base_rate_pct(self, asof) -> float:
        """Annualized base (SOFR/EFFR) % as of ``asof`` (last row <= asof)."""
        asof = pd.Timestamp(asof)
        if asof < self.start:
            raise ValueError(f"asof {asof.date()} precedes curve start {self.start.date()}")
        if asof > self.end + pd.Timedelta(days=self.max_staleness_days):
            raise ValueError(
                f"asof {asof.date()} is > {self.max_staleness_days}d beyond curve end "
                f"{self.end.date()} — rebuild the curve (stale-file guard)")
        i = self._base.index.searchsorted(asof, side="right") - 1
        return float(self._base.iloc[i])

    def annual_rate_pct(self, asof, leg: str, spread_bp: float | None = None) -> float:
        """Annualized financing rate % for a leg: base(asof) + spread."""
        return self.base_rate_pct(asof) + self._spread_bp(leg, spread_bp) / 100.0

    def daily_rate(self, asof, leg: str, spread_bp: float | None = None) -> float:
        """Decimal financing accrual per trading day (annual/100/252)."""
        return self.annual_rate_pct(asof, leg, spread_bp) / 100.0 / TRADING_DAYS

    def fee_spread_bp(self, asof, leg: str, spread_bp: float | None = None) -> float:
        """Annualized borrow-FEE spread (bp) a leg pays OVER base as of ``asof``.

        The pure fee component, base removed — equivalently
        ``annual_rate_pct(leg) - base_rate_pct``, i.e. ``SPREADS_BP[leg]`` (base
        cancels). For ``short_etf`` this is the stock-borrow fee (central 50bp).
        It is the quantity the duration overlay's financing-watch compares to its
        300bp suspend: because positive cash (the short's collateral) is credited
        the base rate, a HIGH base paired with a NORMAL ~50bp fee is NOT a
        distressed borrow and must not trip the watch — only a genuinely wide
        fee spread does."""
        return (self.annual_rate_pct(asof, leg, spread_bp)
                - self.base_rate_pct(asof)) * 100.0

    # ------------------------------------------------------------- vectorized
    def rate_series(self, leg: str, spread_bp: float | None = None) -> pd.Series:
        """Full-history annualized % series for a leg (index = curve dates)."""
        s = self._base + self._spread_bp(leg, spread_bp) / 100.0
        s.name = f"r_{leg}_pct"
        return s

    def daily_rate_series(self, leg: str, spread_bp: float | None = None) -> pd.Series:
        """Full-history decimal per-trading-day accrual series."""
        s = self.rate_series(leg, spread_bp) / 100.0 / TRADING_DAYS
        s.name = f"daily_{leg}"
        return s

    def sensitivity(self, leg: str, spreads_bp: list[float],
                    start=None, end=None) -> pd.DataFrame:
        """Mean/last annualized rate per candidate spread over [start, end].

        Columns include distance to the v1 flat 150bp and to the ~300bp
        overlay flip point, so any A/B table can quote its position on the
        band. Deterministic — no sampling error, MDE n/a.
        """
        base = self._base.loc[slice(pd.Timestamp(start) if start else None,
                                    pd.Timestamp(end) if end else None)]
        if base.empty:
            raise ValueError("empty window for sensitivity")
        rows = []
        for bp in spreads_bp:
            r = base + bp / 100.0
            rows.append({"leg": leg, "spread_bp": float(bp),
                         "mean_rate_pct": r.mean(), "last_rate_pct": r.iloc[-1],
                         "vs_v1_flat150_bp": float(bp) - V1_FLAT_SPREAD_BP,
                         "vs_overlay_flip300_bp": float(bp) - OVERLAY_FLIP_BP})
        out = pd.DataFrame(rows)
        out.attrs["sample"] = (str(base.index.min().date()),
                               str(base.index.max().date()), len(base))
        return out
