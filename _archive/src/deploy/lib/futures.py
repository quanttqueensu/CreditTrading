"""Futures expression layer (H3) — roll-spliced Treasury futures for the v2 book.

REFINE_ARCHITECTURE.md §2.2. This module is the ONLY futures-price seam for
v2: sleeves/engines never read ``data/futures_daily.parquet`` ad hoc. It
provides:

  * ``FuturesInstrument`` + ``load_futures_specs()`` — the frozen contract
    table from ``config/futures_specs.yaml`` (multiplier, tick, half-spread,
    initial margin, informational DV01). Contract facts live in THAT file.
  * ``FuturesReturns`` — roll-splice-PATCHED daily log returns via the frozen
    archive engine (``archive/calendar-premia-v2/src/analysis/returns.py``,
    loaded by file path so the repo's own ``src`` package cannot shadow it),
    plus a synthetic continuous settle level per instrument:

        level_T = actual front (wvol) settle on the last bar
        level_t = level_{t+1} / exp(r_{t+1})        (back-propagated)

    Day-over-day changes of the level reproduce the patched roll-spliced
    return exactly (roll jumps are NEVER booked as P&L), and the LAST level
    equals the real settle, so forward-deployment notionals are honest.
  * ``FuturesMarks`` — ``mark_fn(asof, PositionTarget) -> level | None``
    (None beyond the last settle: the caller reports INSUFFICIENT_MARKS,
    never invents a price — same contract as the vrp marks seam).
  * ``duration_to_contracts`` — integer-contract sizing off a target DV01.
  * ``implied_repo_carry`` — the annual bp carry differential (ETF stock
    borrow minus futures implied-repo drag) off the A1 ``FinancingModel``.

Cardinal rule: nothing here touches a frozen signal. This layer changes only
the EXPRESSION of an already-emitted duration target (ETF -> futures).
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
FUTURES_PARQUET = REPO_ROOT / "data" / "futures_daily.parquet"
SPECS_YAML = REPO_ROOT / "config" / "futures_specs.yaml"
_ARCHIVE_RETURNS = (REPO_ROOT / "archive" / "calendar-premia-v2" / "src"
                    / "analysis" / "returns.py")

# Effective duration of the ETF each frozen duration signal is expressed on,
# used ONLY to convert an ETF-notional target into a target DV01
# (dv01_usd = notional * duration * 1e-4). IEF effective duration ~7.1y
# (iShares 7-10yr Treasury fund page; 6.9-7.6 band over the sample). This is
# an expression-layer constant, not a signal parameter.
ETF_DURATION_YEARS = {"IEF": 7.1}

# Beyond the last settle a mark is served (marked to the last settle) only
# within this tolerance — a holiday/weekend/one-off-late-bar gap. Past it the
# data file is STALE and a book that requires a futures mark must HALT rather
# than silently drop the leg. Mirrors financing.FinancingModel.max_staleness_days.
DEFAULT_MAX_STALENESS_DAYS = 7


def _load_archive_returns_module():
    """Load the archive roll-splice engine by FILE PATH (never ``import
    src.analysis.returns`` — the repo's own ``src`` package would shadow it)."""
    spec = importlib.util.spec_from_file_location(
        "archive_calendar_premia_v2_returns", _ARCHIVE_RETURNS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ret_mod = None


def _archive_returns():
    global _ret_mod
    if _ret_mod is None:
        _ret_mod = _load_archive_returns_module()
    return _ret_mod


# --------------------------------------------------------------------------
# Frozen contract table
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FuturesInstrument:
    code: str                   # "ZN" | "ZF" | "ZB"
    multiplier: float           # $ per full point ($1,000 for ZF/ZN/ZB)
    dv01_per_contract: float    # $/bp per contract — OPERATIONAL default only
    initial_margin_usd: float   # CME performance bond per contract (central)
    tick_usd: float
    half_spread_bp: float       # per-side cost, frozen (CALENDAR_v3 cost model)


_specs_cache: dict[str, FuturesInstrument] | None = None


def load_futures_specs(path: str | Path = SPECS_YAML) -> dict[str, FuturesInstrument]:
    """The frozen contract table, keyed by code. Cached after first load."""
    global _specs_cache
    if _specs_cache is not None and Path(path) == SPECS_YAML:
        return _specs_cache
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    out = {}
    for code, row in raw.items():
        if not isinstance(row, dict):
            continue
        need = ("multiplier_usd_per_point", "dv01_per_contract_usd",
                "initial_margin_usd", "tick_usd", "half_spread_bp")
        missing = [k for k in need if k not in row]
        if missing:
            raise ValueError(f"futures_specs.yaml: {code} missing {missing}")
        out[code] = FuturesInstrument(
            code=code,
            multiplier=float(row["multiplier_usd_per_point"]),
            dv01_per_contract=float(row["dv01_per_contract_usd"]),
            initial_margin_usd=float(row["initial_margin_usd"]),
            tick_usd=float(row["tick_usd"]),
            half_spread_bp=float(row["half_spread_bp"]),
        )
    if not out:
        raise ValueError(f"no instruments parsed from {path}")
    if Path(path) == SPECS_YAML:
        _specs_cache = out
    return out


# --------------------------------------------------------------------------
# Roll-spliced returns + synthetic continuous settle level
# --------------------------------------------------------------------------

class FuturesReturns:
    """Roll-splice-safe returns and a markable continuous settle level.

    The level is anchored at the LAST actual front (wvol) settle and
    back-propagated through the PATCHED log returns, so (a) day-over-day
    level changes reproduce the roll-spliced return exactly — a roll jump is
    never P&L — and (b) the latest level equals the real, tradeable settle,
    making ``qty * multiplier * level`` an honest current notional.
    """

    def __init__(self, parquet_path: str | Path = FUTURES_PARQUET,
                 instruments: tuple[str, ...] = ("ZN", "ZF", "ZB")):
        self.parquet_path = str(parquet_path)
        self.instruments = list(instruments)
        mod = _archive_returns()
        self._logret, self._patches = mod.daily_log_returns(
            self.parquet_path, self.instruments, return_patches=True)
        raw = pd.read_parquet(self.parquet_path)
        raw["date"] = pd.to_datetime(raw["date"])
        self._front = {
            inst: (raw[(raw["instrument"] == inst) & (raw["roll"] == "wvol")]
                   .set_index("date")["settle"].sort_index())
            for inst in self.instruments
        }
        levels = {}
        for inst in self.instruments:
            r = self._logret[inst].dropna()
            anchor_date = r.index.max()
            front = self._front[inst]
            anchor = float(front.loc[front.index <= anchor_date].iloc[-1])
            # level_t = anchor / exp(sum of r over (t, T])
            rev_cum = r.iloc[::-1].cumsum().iloc[::-1]      # sum r_{t..T}
            level = anchor * np.exp(-(rev_cum - r))          # exclude own-day r
            # append the anchor day itself (sum over empty tail = 0)
            level.loc[anchor_date] = anchor
            levels[inst] = level.sort_index()
        self._levels = pd.DataFrame(levels)

    # -- surfaces ----------------------------------------------------------
    def log_returns(self) -> pd.DataFrame:
        """Wide patched daily log returns (one column per instrument)."""
        return self._logret[self.instruments].copy()

    def simple_returns(self) -> pd.DataFrame:
        return np.exp(self._logret[self.instruments]) - 1.0

    def settle_index(self) -> pd.DataFrame:
        """Synthetic continuous settle level (last level == real settle)."""
        return self._levels.copy()

    def front_settle(self, inst: str) -> pd.Series:
        """Raw front (wvol) settle series — actual levels, roll jumps and all.
        Use for notional/cost arithmetic, never for P&L."""
        return self._front[inst].copy()

    def roll_patch_days(self, inst: str) -> pd.DatetimeIndex:
        """Dates where the base continuation rolled (splice-patched days) —
        the conservative proxy for when a held position must roll."""
        p = self._patches[self._patches["instrument"] == inst]
        return pd.DatetimeIndex(sorted(pd.to_datetime(p["date"]).unique()))

    def marks_provider(self) -> "FuturesMarks":
        return FuturesMarks(self._levels)


class FuturesMarks:
    """The mark seam: ``mark_fn(asof, PositionTarget) -> level | None``.

    Mirrors the vrp marks contract: an ``asof`` before the first settle, or
    more than ``max_staleness_days`` beyond the last settle, returns None so
    the caller reports INSUFFICIENT_MARKS instead of trading a fabricated
    price. Intraday/holiday/short-gap asofs (within the staleness tolerance)
    mark to the last settle at-or-before ``asof``. A None here is the signal
    the fill path turns into a HARD HALT for a required leg (a stale
    ``data/futures_daily.parquet`` must never silently drop a hedge) — see
    ``MarginBook._fill_order`` and ``assert_fresh``. Mirrors
    ``financing.FinancingModel``'s stale-file guard.
    """

    def __init__(self, levels: pd.DataFrame,
                 max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS):
        self._levels = levels
        self.max_staleness_days = int(max_staleness_days)

    def last_settle_date(self, inst) -> pd.Timestamp | None:
        """The last date this instrument has a settle level for (None if the
        instrument is unknown / has no data)."""
        if inst not in self._levels.columns:
            return None
        s = self._levels[inst].dropna()
        return None if s.empty else pd.Timestamp(s.index.max())

    def staleness_days(self, asof, inst) -> float | None:
        """Calendar days ``asof`` is beyond the last settle (negative/0 when in
        range). None if the instrument is unknown."""
        last = self.last_settle_date(inst)
        if last is None:
            return None
        return float((pd.Timestamp(asof).normalize() - last).days)

    def is_stale(self, asof, inst) -> bool:
        """True when ``asof`` is more than ``max_staleness_days`` beyond the
        last settle for ``inst`` (so a required mark cannot be trusted)."""
        sd = self.staleness_days(asof, inst)
        return sd is not None and sd > self.max_staleness_days

    def assert_fresh(self, asof, inst) -> None:
        """Raise if ``inst`` cannot be freshly marked at ``asof`` (unknown, or
        stale beyond tolerance). Loud stale-file guard mirroring
        ``FinancingModel.base_rate_pct`` — call before requiring a mark."""
        last = self.last_settle_date(inst)
        if last is None:
            raise RuntimeError(
                f"futures marks have no data for {inst!r} — rebuild "
                f"data/futures_daily.parquet (build_futures.py) before "
                f"expressing duration in {inst}.")
        if self.is_stale(asof, inst):
            raise RuntimeError(
                f"futures marks for {inst!r} are STALE: asof {pd.Timestamp(asof).date()} "
                f"is {self.staleness_days(asof, inst):.0f}d beyond the last settle "
                f"{last.date()} (> {self.max_staleness_days}d tolerance) — rebuild "
                f"data/futures_daily.parquet (build_futures.py). Refusing to trade a "
                f"stale/fabricated futures price (stale-file guard).")

    def mark_fn(self, asof, pt) -> float | None:
        inst = getattr(pt, "instrument", pt)
        if inst not in self._levels.columns:
            return None
        s = self._levels[inst].dropna()
        if s.empty:
            return None
        asof = pd.Timestamp(asof).normalize()
        if asof < s.index.min() or self.is_stale(asof, inst):
            return None
        return float(s.loc[s.index <= asof].iloc[-1])


# --------------------------------------------------------------------------
# Sizing + carry helpers
# --------------------------------------------------------------------------

def etf_target_dv01(notional_usd: float, etf: str = "IEF") -> float:
    """The DV01 (in $/bp) an ETF-expressed duration leg of ``notional_usd``
    carries: notional * duration * 1e-4."""
    dur = ETF_DURATION_YEARS.get(etf)
    if dur is None:
        raise KeyError(f"no frozen duration for ETF {etf!r} "
                       f"(known: {sorted(ETF_DURATION_YEARS)})")
    return float(notional_usd) * dur * 1e-4


def duration_to_contracts(signal_weight: float, capital_usd: float,
                          target_dv01_usd: float | None,
                          inst: FuturesInstrument,
                          etf: str = "IEF") -> int:
    """Integer-contract sizing: n = round(target_dv01 / inst.dv01_per_contract).

    ``target_dv01_usd`` is the DV01 the ETF expression would have carried at
    ``signal_weight * capital_usd``; pass None to derive it from the frozen
    ``ETF_DURATION_YEARS`` table. Never fractional — the residual DV01 is the
    caller's to REPORT, not to trade. Uses the frozen table DV01 (operational
    default); backtest risk-matching is empirical and does not consume this.
    """
    if target_dv01_usd is None:
        target_dv01_usd = etf_target_dv01(abs(signal_weight) * capital_usd, etf)
    if inst.dv01_per_contract <= 0:
        raise ValueError(f"{inst.code} dv01_per_contract must be > 0")
    return int(round(abs(float(target_dv01_usd)) / inst.dv01_per_contract))


def implied_repo_carry(inst: FuturesInstrument, asof, financing) -> float:
    """Annual bp carry differential of expressing a SHORT duration leg in
    futures instead of a borrowed ETF, per $ of notional:

        (ETF stock-borrow leg) - (futures posted-margin carry leg)

    off the A1 ``FinancingModel`` named buckets (``short_etf`` central 50bp
    [25,75]; ``futures_carry`` central 5bp [-10,25] — CTD implied repo ~
    GC/SOFR, per the curve builder's citations). The future's own financing
    is embedded in the settle (implied repo), so only posted margin drags.
    Positive = futures expression is cheaper. Deterministic; no sampling
    error (MDE n/a).
    """
    etf_bp = (financing.annual_rate_pct(asof, "short_etf")
              - financing.base_rate_pct(asof)) * 100.0
    fut_bp = (financing.annual_rate_pct(asof, "futures_carry")
              - financing.base_rate_pct(asof)) * 100.0
    return float(etf_bp - fut_bp)
