"""A4 — factor attribution & risk decomposition (REFINE_ARCHITECTURE §6).

FactorAttributor regresses a sleeve's (or the book's) daily NET EXCESS returns
on tradeable factor proxies with Newey-West HAC standard errors, and decomposes
variance into per-factor systematic shares + residual.

Factor set (tradeable proxies, per REFINE_PREREG A4):
    DUR   duration  — IEF daily total return minus cash (the book's v1 duration
                      expression; the ZN roll-splice is the futures twin but its
                      settles end 2025-04-25, so the ETF leg is the full-sample
                      tradeable proxy).
    CRD   credit    — duration-hedged IG spread return: LQD excess minus a
                      walk-forward trailing-63d rate-beta times IEF excess
                      (same frozen estimator as the overlay sleeve, GROSS of
                      financing — it is a factor, not a strategy).
    VOL   vol       — the SPY short-ATM-straddle daily carry P&L on notional
                      from the c2b tradeable path (delta-hedged, net of its own
                      option costs), results/vrp/refute_tail_ledger_SPY.csv.
    CARRY carry     — BIL daily total return minus cash (tradeable money-market
                      carry leg; near-zero vol by nature, reported for
                      completeness).

Statistics convention (mirrors scripts/calendar/refute_durbeta.py and
refute_fomc_alwayslong.py): OLS with intercept, HAC(NW) maxlags=10, one-sided
p-value for alpha>0, alphas annualized x252. Every result carries sample
start/end + N + MDE@80% (one-sided 5% test, 80% power: 2.486 x SE(alpha)).

This module holds no I/O beyond `to_memo`; series construction lives in
scripts/refine/a4_attribution.py (the A4 driver).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 252
HAC_LAGS = 10                       # NW(10), same as the EOM/FOMC refuters
# one-sided 5% size, 80% power: z_{0.95} + z_{0.80}
_MDE_Z = 1.6449 + 0.8416


@dataclass
class AttributionResult:
    name: str
    alpha_annual: float             # annualized intercept (decimal, e.g. 0.016)
    alpha_t_hac: float
    alpha_p_one_sided: float        # H1: alpha > 0
    mde80_alpha_annual: float       # min detectable annual alpha @80% power
    betas: dict = field(default_factory=dict)
    betas_t_hac: dict = field(default_factory=dict)
    r2: float = np.nan
    n: int = 0
    sample_start: pd.Timestamp | None = None
    sample_end: pd.Timestamp | None = None
    resid_vol_annual: float = np.nan
    var_shares: dict = field(default_factory=dict)   # factor -> share of Var(r); + 'residual'

    def row(self) -> dict:
        out = {"name": self.name, "alpha_annual": self.alpha_annual,
               "alpha_t_hac": self.alpha_t_hac,
               "alpha_p_one_sided": self.alpha_p_one_sided,
               "mde80_alpha_annual": self.mde80_alpha_annual,
               "r2": self.r2, "n": self.n,
               "sample_start": self.sample_start, "sample_end": self.sample_end,
               "resid_vol_annual": self.resid_vol_annual}
        for k, v in self.betas.items():
            out[f"beta_{k}"] = v
        for k, v in self.betas_t_hac.items():
            out[f"t_{k}"] = v
        for k, v in self.var_shares.items():
            out[f"varshare_{k}"] = v
        return out


class FactorAttributor:
    """HAC-robust factor regressions + variance decomposition on daily series."""

    def __init__(self, factors: pd.DataFrame):
        if not isinstance(factors.index, pd.DatetimeIndex):
            raise TypeError("factors must be indexed by DatetimeIndex")
        self.factors = factors.sort_index().dropna(how="all")

    def decompose(self, returns: pd.Series, name: str = "series",
                  factor_cols: list[str] | None = None,
                  hac_lags: int = HAC_LAGS) -> AttributionResult:
        import statsmodels.api as sm
        from scipy import stats as sps

        cols = list(factor_cols) if factor_cols else list(self.factors.columns)
        df = pd.concat([returns.rename("r"), self.factors[cols]], axis=1).dropna()
        if len(df) < 60:
            raise ValueError(f"{name}: only {len(df)} overlapping days — too few to attribute")
        y = df["r"].to_numpy()
        X = sm.add_constant(df[cols].to_numpy())
        fit = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})

        alpha_d, alpha_se = float(fit.params[0]), float(fit.bse[0])
        t_alpha = alpha_d / alpha_se if alpha_se > 0 else np.nan
        # one-sided p with the same normal reference the refuters used
        p1 = float(sps.norm.sf(t_alpha))
        betas = {c: float(b) for c, b in zip(cols, fit.params[1:])}
        betas_t = {c: float(t) for c, t in zip(cols, fit.tvalues[1:])}

        resid = y - fit.fittedvalues
        var_r = float(np.var(y, ddof=1))
        # variance shares: beta_i * Cov(F_i, r) / Var(r); sums with residual to ~1
        shares = {}
        for c in cols:
            cov = float(np.cov(df[c].to_numpy(), y, ddof=1)[0, 1])
            shares[c] = betas[c] * cov / var_r if var_r > 0 else np.nan
        shares["residual"] = float(np.var(resid, ddof=1)) / var_r if var_r > 0 else np.nan

        return AttributionResult(
            name=name,
            alpha_annual=alpha_d * TRADING_DAYS,
            alpha_t_hac=t_alpha,
            alpha_p_one_sided=p1,
            mde80_alpha_annual=_MDE_Z * alpha_se * TRADING_DAYS,
            betas=betas, betas_t_hac=betas_t,
            r2=float(fit.rsquared), n=int(len(df)),
            sample_start=df.index[0], sample_end=df.index[-1],
            resid_vol_annual=float(np.std(resid, ddof=1) * np.sqrt(TRADING_DAYS)),
            var_shares=shares,
        )

    def attribute_book(self, sleeve_returns: dict[str, pd.Series],
                       weights: dict[str, float] | None = None,
                       factor_cols: list[str] | None = None,
                       hac_lags: int = HAC_LAGS
                       ) -> tuple[dict[str, AttributionResult], pd.Series, dict]:
        """Per-sleeve decompositions + the capital-weighted book on the COMMON sample.

        Returns (results incl. 'book', book_return_series,
        sleeve_var_contrib: sleeve -> w_i*Cov(r_i, r_book)/Var(r_book))."""
        names = list(sleeve_returns)
        w = {k: 1.0 / len(names) for k in names} if weights is None else dict(weights)
        wide = pd.concat({k: v for k, v in sleeve_returns.items()}, axis=1).dropna()
        book = sum(wide[k] * w[k] for k in names).rename("book")

        results = {k: self.decompose(wide[k], name=k, factor_cols=factor_cols,
                                     hac_lags=hac_lags) for k in names}
        results["book"] = self.decompose(book, name="book", factor_cols=factor_cols,
                                         hac_lags=hac_lags)

        var_book = float(book.var(ddof=1))
        contrib = {k: float(w[k] * wide[k].cov(book) / var_book) for k in names}
        return results, book, contrib

    @staticmethod
    def to_frame(results: dict[str, AttributionResult]) -> pd.DataFrame:
        return pd.DataFrame([r.row() for r in results.values()]).set_index("name")
