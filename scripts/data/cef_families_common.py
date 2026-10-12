"""Shared paths, family map and guards for the CEF-families data build (plan C4).

WHAT THIS IS FOR
----------------
`results/cef/RESEARCH_PLAN_2026-10-09.md` trial C4 runs the live discount
z-score on equity, preferred and multi-asset CEFs (agenda B1). It "needs NAV
fetchers for those families". The fetchers are four scripts beside this file:

    cef_families_universe.py          which funds, by family; Alpaca flags today
    fetch_cef_families_yf.py          daily price, volume, NAV (yfinance)
    fetch_cef_families_cefconnect.py  dated NAV, daily 1Y and weekly All (CEFConnect)
    stage_crsp_cef_families.py        CRSP daily prices (R2 WRDS mirror)
    cef_families_quality.py           coverage, gaps, staleness, ADV, source agreement

They build DATA only. No discount z-score, IC, P&L or return statistic of the
trial is computed anywhere in them: that is the C4 trial itself, and it is
spent only after its pre-registration.

THE TWO WALLS
-------------
1. **Never `data/cef/`.** The live sleeve decides on `data/cef/*.parquet`
   (CLAUDE.md landmine 9). Everything here writes under `data/cef_families/`,
   and `out_path()` raises on any path that resolves inside `data/cef/`.
   `data/` in a worktree is a symlink to the main checkout's `data/`, which is
   why the check resolves the path first.
2. **Never a `data/cef/cef_universe.csv` name.** That file is the 44-name set:
   the deployed 13 and the 27-name holdout (H9). The holdout is consumed by the
   first pre-registered test that computes returns on any of them
   (`docs/SYSTEM.md` §5, 2026-10-09), so a family panel that carried one would
   put a holdout name one join away from a return. `assert_no_universe_names`
   raises before any panel is written. Measured 2026-10-12: no in-scope
   CEFConnect fund is one of the 44, so this is a guard, not a filter.

THE FAMILY MAP (why Morningstar, through CEFConnect)
----------------------------------------------------
`results/data/universe_2026-10-08/` sorted CEFs by reading CRSP names, and put
every equity and multi-asset fund in one residual bucket (`cef_equity_multi`),
with "family membership is a judgement" as its caveat. C4 needs the
sub-families (domestic, global, sector, covered-call, preferred, multi-asset),
so this build takes them from one dated, external classification instead of a
new judgement: the Morningstar category CEFConnect publishes per fund
(`/api/v3/DailyPricing`, field `Strategy`). Where it disagrees with the
2026-10-08 map, both are kept in the universe table; neither is overwritten.

A `Strategy` string that is in neither map raises: a new Morningstar category
must be placed by a person, not defaulted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUT_DIR = REPO / "data" / "cef_families"
RAW_DIR = OUT_DIR / "raw"
LIVE_DIR = REPO / "data" / "cef"
CEF_UNIVERSE_CSV = LIVE_DIR / "cef_universe.csv"
RESULTS_DIR = REPO / "results" / "cef" / "cef_families"
UNIVERSE_MAP_CSV = REPO / "results" / "data" / "universe_2026-10-08" / "universe_map.csv"

# Panels, same schema as data/cef/cef_prices.parquet / cef_nav.parquet.
PRICES = "cef_prices.parquet"           # yfinance; date open high low close volume ticker grp
NAV = "cef_nav.parquet"                 # yfinance NAV ticker; date nav ticker
# Side files, each one source, never spliced into the panels above.
PRICES_CRSP = "cef_prices_crsp.parquet"  # CRSP dsf, same schema as PRICES (licensed: never committed)
NAV_CEFCONNECT = "cef_nav_cefconnect.parquet"
ACTIONS = "cef_actions.parquet"         # yfinance Dividends / Stock Splits of the price ticker
UNIVERSE = "universe.csv"

# Morningstar category (CEFConnect `Strategy`) -> (family, sub-family).
FAMILY_OF_STRATEGY: dict[str, tuple[str, str]] = {
    "Equity-U.S. Equity": ("equity_domestic", "us_equity"),
    "Equity-Global Equity": ("equity_global", "global"),
    "Equity-Asia Equity": ("equity_global", "asia"),
    "Equity-Emerging Market Equity": ("equity_global", "emerging"),
    "Equity-Single-Country Equity": ("equity_global", "single_country"),
    "Equity-Sector Equity": ("equity_sector", "sector"),
    "Equity-Real Estate": ("equity_sector", "real_estate"),
    "Equity-MLP": ("equity_sector", "mlp"),
    "Equity-Covered-Call Funds": ("equity_covered_call", "covered_call"),
    "Fixed Income - Taxable-Preferreds": ("preferred", "preferred"),
    "Hybrid-U.S. Allocation": ("multi_asset", "us_allocation"),
    "Hybrid-Global Allocation": ("multi_asset", "global_allocation"),
}
FAMILIES = ("equity_domestic", "equity_global", "equity_sector",
            "equity_covered_call", "preferred", "multi_asset")

# Categories deliberately outside C4, each with the reason. Credit and munis are
# the live book's own asset class (and hold the 44); convertibles are a hybrid
# the plan row does not name; the commodity category is physical-metal trusts.
OUT_OF_SCOPE_STRATEGY: dict[str, str] = {
    "Equity-Commodities": "Morningstar 'Commodity': physical-metal trusts, not an equity, "
                          "preferred or multi-asset CEF; CEFConnect lists no NAV ticker for them",
    "Fixed Income - Taxable-Convertibles": "convertibles: not among the C4 families as written",
    "Fixed Income - Taxable-Emerging Market Income": "credit: the live book's asset class",
    "Fixed Income - Taxable-Global Income": "credit: the live book's asset class",
    "Fixed Income - Taxable-High Yield": "credit: the live book's asset class",
    "Fixed Income - Taxable-Investment Grade": "credit: the live book's asset class",
    "Fixed Income - Taxable-Limited Duration": "credit: the live book's asset class",
    "Fixed Income - Taxable-Multi-Sector": "credit: the live book's asset class",
    "Fixed Income - Taxable-Senior Loans": "credit: the live book's asset class",
    "Fixed Income - Taxable-Taxable Muni": "credit: the live book's asset class",
    "Fixed Income - Municipal-Municipal": "muni: the live book's asset class",
    "Fixed Income - Municipal-Municipal - CA": "muni: the live book's asset class",
    "Fixed Income - Municipal-Municipal - NY": "muni: the live book's asset class",
    "Fixed Income - Municipal-Municipal - Single-State": "muni: the live book's asset class",
}

# The time holdout (CLAUDE.md research rules). No RETURN statistic in this build
# reads a date on or after it; levels, coverage and volume are not returns.
TIME_HOLDOUT = pd.Timestamp("2023-01-01")


class FamiliesDataError(RuntimeError):
    """A required input is missing or a guard tripped. The message names it."""


def family_of(strategy) -> tuple[str, str] | None:
    """(family, sub) for an in-scope Morningstar category; None if out of scope.

    Raises on a category in neither map, and on a missing one: an unplaced
    category is a decision for a person, never a default."""
    if strategy is None or (isinstance(strategy, float) and pd.isna(strategy)) or strategy == "":
        raise FamiliesDataError("fund has no Morningstar category (CEFConnect `Strategy` empty)")
    if strategy in FAMILY_OF_STRATEGY:
        return FAMILY_OF_STRATEGY[strategy]
    if strategy in OUT_OF_SCOPE_STRATEGY:
        return None
    raise FamiliesDataError(
        f"Morningstar category {strategy!r} is in neither FAMILY_OF_STRATEGY nor "
        f"OUT_OF_SCOPE_STRATEGY ({__file__}); place it by hand")


def cef_universe_names(path: Path = CEF_UNIVERSE_CSV) -> set[str]:
    """The 44 names of data/cef/cef_universe.csv (deployed 13 + 27-name holdout).

    Raises if the file is missing or has no `ticker` column: an empty set would
    silently disable the holdout wall."""
    if not Path(path).exists():
        raise FamiliesDataError(f"{path} does not exist: cannot fence off the holdout")
    u = pd.read_csv(path)
    if "ticker" not in u.columns or u.empty:
        raise FamiliesDataError(f"{path} has no tickers: cannot fence off the holdout")
    return set(u["ticker"].astype(str))


def assert_no_universe_names(tickers, universe: set[str]) -> None:
    """Raise, naming them, if any ticker is one of the 44 (see module docstring)."""
    hit = sorted(set(map(str, tickers)) & set(universe))
    if hit:
        raise FamiliesDataError(
            f"cef_universe.csv name(s) {hit} reached a family panel: the 27-name "
            f"holdout and the deployed 13 never enter data/cef_families/")


def out_path(name: str, base: Path = OUT_DIR, live: Path = LIVE_DIR) -> Path:
    """`base / name`, refusing anything that resolves inside the live `data/cef/`."""
    p = (Path(base) / name)
    p.parent.mkdir(parents=True, exist_ok=True)
    rp, rlive = p.resolve(), Path(live).resolve()
    if rp == rlive or rlive in rp.parents:
        raise FamiliesDataError(f"refusing to write {rp}: inside the live panel directory {rlive}")
    return p


def write_frame(frame: pd.DataFrame, name: str, base: Path = OUT_DIR, live: Path = LIVE_DIR) -> Path:
    """Atomic write (ops.common.atomic_write) to `base/name`, behind `out_path`."""
    from ops.common import atomic_write
    p = out_path(name, base, live)
    atomic_write(frame, p)
    return p


def load_universe(base: Path = OUT_DIR) -> pd.DataFrame:
    """The universe table written by cef_families_universe.py. Raises if absent."""
    p = Path(base) / UNIVERSE
    if not p.exists():
        raise FamiliesDataError(f"{p} does not exist: run scripts/data/cef_families_universe.py first")
    u = pd.read_csv(p)
    for c in ("ticker", "family", "included"):
        if c not in u.columns:
            raise FamiliesDataError(f"{p} lacks column {c!r}")
    return u


def included(u: pd.DataFrame) -> pd.DataFrame:
    """Rows of the universe table that enter the panels."""
    return u[u["included"].astype(bool)].copy()
