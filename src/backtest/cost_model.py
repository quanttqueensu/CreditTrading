"""Realistic execution and financing costs for a dollar-neutral ETF book.

Each component below is justified by market structure, and each is VERIFIABLE with
`scripts/rv/measure_rth_liquidity.py` at the open. Where a number is an assumption
it is named as one and carries a scenario knob so the sensitivity is visible.

--------------------------------------------------------------------------------
1. HALF-SPREAD
--------------------------------------------------------------------------------
US equities and ETFs quote in $0.01 increments. For any ETF whose natural spread is
one tick, the half-spread IS half a cent -- it cannot be less, and for a liquid name
it is not more. My first model multiplied that tick floor by a "liquidity tier"
factor of 1.75x-5x, which is unjustified for names that genuinely quote penny-wide
(HYG, LQD, JNK, VCIT, USHY, EMB all do, all day).

The tier multiple is retained ONLY for names thin enough that the book is genuinely
multiple ticks wide. Threshold set on measured ADV, not on which answer it gives.

--------------------------------------------------------------------------------
2. MARKET IMPACT
--------------------------------------------------------------------------------
The square-root law (impact ~ sigma * sqrt(Q/ADV)) is calibrated on single stocks,
where supply is inelastic: buying pressure must be absorbed by other holders.

An ETF is not supply-constrained in that way. Authorised participants create new
units against the underlying basket, so displayed liquidity at the touch is
replenished continuously and an order that fits inside it is filled at the quote
with NO price concession. Impact is therefore correctly modelled as a threshold
function, not a power law:

    impact = 0                                     if order <= touch_depth
    impact = sigma * sqrt(excess / ADV)            on the EXCESS only

Touch depth is parameterised as a fraction of ADV (`touch_frac`) and is directly
measurable -- the RTH harness prints it per name.

--------------------------------------------------------------------------------
3. FINANCING  (this is where the first model was simply wrong)
--------------------------------------------------------------------------------
The original charged `financing_spread * (gross - 1) * NAV`, i.e. it treated the
whole levered notional as a margin loan. For a DOLLAR-NEUTRAL book that is false:

    equity 1,000,000
    buy long  1,175,000  ->  cash   -175,000
    short     1,175,000  ->  cash +1,000,000   (proceeds held as collateral)
    net cash  = +1,000,000  =>  margin debit = 0

The book's true financing is:
    - stock-borrow fee on the SHORT notional (liquid credit ETFs are easy-to-borrow),
    - interest EARNED on the cash balance,
    - margin interest only on any genuine net debit, which a balanced book rarely has.

Charging 150bp on $1.35m of phantom loan cost ~2-3.3%/yr of pure fiction.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CostModel:
    """Scenario-able cost model. `scenario` names the assumption set."""
    scenario: str = "base"
    # spreads
    tick_usd: float = 0.005                 # half of a $0.01 quote increment
    penny_wide_adv_usd: float = 50e6        # above this ADV, assume one-tick market
    thin_tier_mult: float = 2.5             # multiple of tick for names below it
    spread_mult: float = 1.0                # global stress knob
    # impact
    touch_frac_of_adv: float = 5e-4         # displayed touch ~ 0.05% of ADV
    impact_coef: float = 1.0                # applies to the EXCESS over touch only
    # financing
    borrow_fee_bp: float = 50.0             # on short notional, easy-to-borrow ETF
    margin_spread_bp: float = 100.0         # over base, on genuine net debit (IBKR tier)
    # participation guard
    max_participation: float = 0.05

    # Measured half-spreads (bp) from IBKR historical BID_ASK, RTH closing window,
    # 2021-08 -> 2026-07, validated with SPY as a control (0.068bp measured vs a
    # ~0.1bp truth). Where a name is in here we use the MEASUREMENT, never the
    # model: the 2.5x "thin tier" multiplier was over-charging ANGL by exactly
    # 2.5x (4.334bp modelled vs 1.735bp measured) because credit ETFs quote a
    # penny wide regardless of ADV. Genuinely illiquid wrappers go the OTHER way
    # (CWB, HYGH, LQDH are far worse than any tier multiple would predict), which
    # is the second reason to trust the measurement over the formula.
    MEASURED_HALF_SPREAD_BP = {
        "SPY": 0.068, "LQD": 0.459, "EMB": 0.554, "JNK": 0.523, "AGG": 0.506,
        "HYG": 0.634, "VCIT": 0.615, "VCSH": 0.653, "IEI": 0.430, "IEF": 0.518,
        "SHY": 0.617, "TLT": 0.513, "GOVT": 2.161, "IGSB": 0.987, "SHYG": 1.179,
        "USHY": 1.360, "ANGL": 1.735, "FALN": 1.930, "SJNK": 2.006, "SPHY": 3.115,
        "BKLN": 2.406, "SRLN": 1.249, "JAAA": 1.826, "JBBB": 5.659, "VCLT": 1.738,
        "CWB": 4.248, "HYGH": 7.449, "LQDH": 4.415, "PFF": 1.577,
    }

    def half_spread_bp(self, price: float, adv_usd: float,
                       ticker: str | None = None) -> float:
        """Measured half-spread where we have one, else the tick-floor model.

        The measurement wins because it is a measurement. The model is only a
        fallback for names never measured against the broker.
        """
        meas = self.MEASURED_HALF_SPREAD_BP.get(ticker) if ticker else None
        if meas is not None:
            return meas * self.spread_mult
        floor_bp = self.tick_usd / max(price, 1e-6) * 1e4
        mult = 1.0 if adv_usd >= self.penny_wide_adv_usd else self.thin_tier_mult
        return floor_bp * mult * self.spread_mult

    def impact_bp(self, notional: np.ndarray, adv: np.ndarray,
                  day_vol_bp: np.ndarray) -> np.ndarray:
        """Zero inside the touch; square-root law on the excess only."""
        adv = np.nan_to_num(adv, nan=0.0, posinf=0.0)
        touch = adv * self.touch_frac_of_adv
        excess = np.clip(notional - touch, 0.0, None)
        with np.errstate(divide="ignore", invalid="ignore"):
            part = np.where(adv > 0, excess / adv, 0.0)
        part = np.nan_to_num(part, nan=0.0, posinf=0.0)
        return self.impact_coef * np.nan_to_num(day_vol_bp, nan=50.0) * np.sqrt(part)

    def financing_daily(self, nav: float, long_notional: float,
                        short_notional: float, base_rate: float) -> tuple[float, float]:
        """Returns (cost_usd, cash_interest_usd) for one day.

        Short proceeds offset the long purchase; only a genuine net debit is financed.
        """
        cash = nav - long_notional + short_notional
        debit = max(-cash, 0.0)
        margin_cost = debit * (base_rate + self.margin_spread_bp / 1e4) / 252.0
        borrow_cost = short_notional * (self.borrow_fee_bp / 1e4) / 252.0
        cash_interest = max(cash, 0.0) * base_rate / 252.0
        return margin_cost + borrow_cost, cash_interest


SCENARIOS = {
    # what a $1m account should actually see in liquid credit ETFs
    "base": CostModel(scenario="base"),
    # everything that could plausibly go against us at once
    "pessimistic": CostModel(scenario="pessimistic", thin_tier_mult=4.0, spread_mult=1.5,
                             touch_frac_of_adv=1e-4, impact_coef=1.5,
                             borrow_fee_bp=100.0, margin_spread_bp=150.0),
    # the original (wrong) model, kept so the comparison is explicit
    "legacy_wrong": CostModel(scenario="legacy_wrong", thin_tier_mult=5.0,
                              touch_frac_of_adv=0.0, impact_coef=1.0,
                              borrow_fee_bp=50.0, margin_spread_bp=150.0),
    # deep-liquidity read: penny-wide everywhere, touch absorbs a $1m clip
    "optimistic": CostModel(scenario="optimistic", thin_tier_mult=1.5,
                            touch_frac_of_adv=2e-3, impact_coef=0.5,
                            borrow_fee_bp=30.0, margin_spread_bp=75.0),
}
