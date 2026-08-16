"""The daily book runner. Same code, two execution backends:

    EXECUTION=simulator python3 src/deploy/run_book.py --asof 2026-07-17 --source local
    EXECUTION=ibkr      python3 src/deploy/run_book.py --asof 2026-07-17   # after the gateway runbook

It reads a BOOK SPEC (JSON: which sleeves, their frozen-spec paths, capital,
enabled flags, book-level limits), builds the selected broker, and advances the
PortfolioOrchestrator to `--asof`. Pass `--replay-start` to loop the orchestrator
day-by-day from that date to `--asof` (the way a cold book is built up), so each
calendar-timed sleeve always sees fresh holdings.

Prints the book roll-up and sample dates + N (the standing rule). Deterministic
given the frozen specs and local data.
"""

import argparse
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops import common as ops_common  # noqa: E402
from src.deploy.broker import make_broker  # noqa: E402
from src.deploy.portfolio import PortfolioOrchestrator  # noqa: E402
from src.deploy import report as book_report  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = REPO_ROOT / "data" / "events.parquet"


UNDERLYING_PATH = REPO_ROOT / "data" / "vrp" / "underlying_daily.parquet"
UNDERLIER_TICKERS = {"SPY", "QQQ"}   # priced from the vrp underlying file, not the ETF panel


# ---------------------------------------------------------------------------
# Forward-operability: the frozen panel (data/etf_daily.parquet) is the backtest
# reference + snapshot cutoff and is NEVER modified. To run the book on a date
# AFTER the panel's last bar (the live paper phase), warmup history still comes
# from the panel and only the post-panel tail is spliced from yfinance, plus the
# replay calendar is extended with forward NYSE trading days. Both fall back to
# the exact within-panel path when asof is inside the panel, so backtest
# behaviour is byte-for-byte unchanged.
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _panel_last_date():
    """Newest bar in the frozen ETF panel. Cached — a replay loop calls the
    price loader once per sleeve per day."""
    dates = pd.read_parquet(ops_common.PANEL_PATH, columns=["date"])["date"]
    return pd.Timestamp(pd.to_datetime(dates).max()).normalize()


def _nyse_calendar():
    """The scheduler's pure-stdlib NYSE calendar (ops/schedule/nyse_calendar.py),
    the same one the launchd wrapper gates on — so forward days here and the
    scheduler's trading-day gate can never disagree."""
    from ops.schedule import nyse_calendar
    return nyse_calendar


def _load_etf(tickers, start, asof):
    """ETF bars for [start, asof]. History always comes from the frozen panel
    (ops.common.fetch_local). For an asof AFTER the panel's last bar the
    post-panel tail is spliced from yfinance (ops.common.fetch_yfinance), which
    carries per-share distributions in the SAME total-return convention as
    fetch_local: a raw split-adjusted close plus the cash distribution in its own
    column (fetch_local backs D_t out of the two return columns; fetch_yfinance
    reads dividends+capital-gains as actions). The panel is only read, never
    written."""
    asof = pd.Timestamp(asof)
    panel_last = _panel_last_date()
    local = ops_common.fetch_local(tickers, start, asof)
    if asof <= panel_last:
        return local                          # within-panel: byte-for-byte UNCHANGED
    local = local[local["date"] <= panel_last]
    tail = ops_common.fetch_yfinance(
        list(tickers), panel_last + pd.Timedelta(days=1), asof, verbose=False)
    if not tail.empty:
        tail = tail[tail["date"] > panel_last]
    if tail.empty:
        return local.reset_index(drop=True)
    return pd.concat([local, tail], ignore_index=True)


RV_OHLC_PATH = Path(__file__).resolve().parents[2] / "data" / "rv" / "etf_ohlc.parquet"


@lru_cache(maxsize=1)
def _rv_ohlc():
    """Full-OHLC credit panel (data/rv/etf_ohlc.parquet), or None.

    The frozen panel data/etf_daily.parquet holds 9 tickers and no session
    range. The credit RV sleeve needs ~22 names AND high/low, because its signal
    is built on the (H+L)/2 mid — a close-built signal is the bounce-contaminated
    one Phase 0 rejected. So this file is a second ETF source, routed exactly the
    way SPY/QQQ already route to the vrp underlying file.
    """
    if not RV_OHLC_PATH.exists():
        return None
    df = pd.read_parquet(RV_OHLC_PATH,
                         columns=["date", "ticker", "close", "dividend",
                                  "volume", "high", "low"])
    df["date"] = pd.to_datetime(df["date"])
    return df


@lru_cache(maxsize=1)
def _panel_tickers():
    t = pd.read_parquet(ops_common.PANEL_PATH, columns=["ticker"])["ticker"]
    return frozenset(t.unique())


CEF_PX_PATH = Path(__file__).resolve().parents[2] / "data" / "cef" / "cef_prices.parquet"
CEF_DIST_PATH = Path(__file__).resolve().parents[2] / "data" / "cef" / "cef_distributions.parquet"


@lru_cache(maxsize=1)
def _cef_px():
    """Closed-end fund bars (data/cef/cef_prices.parquet), or None.

    A THIRD price source, added for the same reason the RV OHLC file was: the
    frozen panel carries 9 tickers and the RV file ~56 credit ETF wrappers, and
    neither holds a single CEF. Without this the CEF sleeve's own signal file was
    the only place its prices existed, so `place_targets` could not convert a
    weight into shares and the shadow ledger could not mark the book.

    Observed 2026-07-31: an armed run transmitted NOTHING and died with
    `KeyError('NVG')` in the ledger advance, because CEF names fell through to
    `_load_rv_only`, which has no rows for them and could only splice a short
    yfinance tail. Same class of fault as bench_b4_60_40 failing on an absent SPY.

    DISTRIBUTIONS ARE JOINED HERE and that is not optional. Credit CEFs yield
    8-16% a year in monthly distributions; dropping them would understate the
    book's return by roughly its entire expected alpha and would misstate NAV on
    every ex-date. `cef_prices.parquet` carries no dividend column, so the amounts
    come from `cef_distributions.parquet` keyed on (ticker, ex_date) -- the same
    total-return convention as fetch_local: a raw split-adjusted close plus the
    cash distribution in its own column.
    """
    if not CEF_PX_PATH.exists():
        return None
    df = pd.read_parquet(CEF_PX_PATH,
                         columns=["date", "ticker", "close", "volume", "high", "low"])
    df["date"] = pd.to_datetime(df["date"])
    if CEF_DIST_PATH.exists():
        dist = pd.read_parquet(CEF_DIST_PATH, columns=["ticker", "ex_date", "amount"])
        dist["ex_date"] = pd.to_datetime(dist["ex_date"])
        dist = (dist.groupby(["ticker", "ex_date"], as_index=False)["amount"].sum()
                    .rename(columns={"ex_date": "date", "amount": "dividend"}))
        df = df.merge(dist, on=["date", "ticker"], how="left")
    if "dividend" not in df.columns:
        df["dividend"] = 0.0
    df["dividend"] = df["dividend"].fillna(0.0)
    return df


@lru_cache(maxsize=1)
def _cef_tickers():
    df = _cef_px()
    return frozenset() if df is None else frozenset(df["ticker"].unique())


def _load_cef(tickers, start, asof):
    """CEF bars for [start, asof] from the CEF file, post-file tail from
    yfinance -- same splice convention as `_load_etf` and `_load_rv_only`."""
    cef = _cef_px()
    if cef is None or not tickers:
        return pd.DataFrame(columns=ops_common.PRICE_COLUMNS)
    asof = pd.Timestamp(asof)
    d = cef[cef["ticker"].isin(list(tickers))].copy()
    d = d[(d["date"] >= pd.Timestamp(start)) & (d["date"] <= asof)]
    d["source"] = "cef_prices"
    d["fetched_at"] = ""
    cef_last = pd.Timestamp(cef["date"].max()).normalize()
    if asof > cef_last:
        tail = ops_common.fetch_yfinance(
            list(tickers), cef_last + pd.Timedelta(days=1), asof, verbose=False)
        if not tail.empty:
            d = pd.concat([d, tail[tail["date"] > cef_last]], ignore_index=True)
    return d.reset_index(drop=True)


def _load_rv_only(tickers, start, asof):
    """Bars for tickers the frozen panel does not carry, from the RV OHLC file,
    with the post-file tail spliced from yfinance (same convention as
    `_load_etf`: raw split-adjusted close plus the cash distribution)."""
    rv = _rv_ohlc()
    if rv is None or not tickers:
        return pd.DataFrame(columns=ops_common.PRICE_COLUMNS)
    asof = pd.Timestamp(asof)
    d = rv[rv["ticker"].isin(list(tickers))].copy()
    d = d[(d["date"] >= pd.Timestamp(start)) & (d["date"] <= asof)]
    d["source"] = "rv_ohlc"
    d["fetched_at"] = ""
    rv_last = pd.Timestamp(rv["date"].max()).normalize()
    if asof > rv_last:
        tail = ops_common.fetch_yfinance(
            list(tickers), rv_last + pd.Timedelta(days=1), asof, verbose=False)
        if not tail.empty:
            d = pd.concat([d, tail[tail["date"] > rv_last]], ignore_index=True)
    return d.reset_index(drop=True)


def _attach_range(df):
    """Left-join high/low from the RV OHLC file onto rows that lack them.

    Purely additive: close/dividend/volume are untouched, so every existing
    sleeve prices exactly as before. It only lets a panel-sourced ticker (HYG,
    LQD, ...) carry the session range the credit sleeve needs.
    """
    rv = _rv_ohlc()
    if rv is None or df.empty:
        return df
    if "high" in df.columns and df["high"].notna().all():
        return df                              # already complete — nothing to do

    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    lookup = (rv[["date", "ticker", "high", "low"]]
              .rename(columns={"high": "_rv_high", "low": "_rv_low"}))
    out = out.merge(lookup, on=["date", "ticker"], how="left")

    # A row's OWN range wins (e.g. the fresh yfinance tail); the RV file only
    # fills gaps. combine_first does exactly that and needs no length assumptions.
    for col, src in (("high", "_rv_high"), ("low", "_rv_low")):
        if col in df.columns:
            out[col] = out[col].combine_first(out[src])
        else:
            out[col] = out[src]
    return out.drop(columns=["_rv_high", "_rv_low"])


def load_book_spec(path):
    with open(path) as fh:
        return json.load(fh)


def _load_underliers(tickers, start, asof):
    """SPY/QQQ closes from data/vrp/underlying_daily.parquet, reshaped into the
    ops tidy store (date,ticker,close,dividend,volume,...) so they flow through
    the same `wide()`/mark path as ETF bars. Dividends 0 (the short-vol hedge is
    price-only) and a flat large volume (the frozen c2b cost model has
    impact_coefficient=0, so volume never moves a cost)."""
    if not UNDERLYING_PATH.exists():
        return pd.DataFrame(columns=["date", "ticker", "close", "dividend",
                                     "volume", "source", "fetched_at"])
    u = pd.read_parquet(UNDERLYING_PATH)
    u = u[u["ticker"].isin(list(tickers))].copy()
    u["date"] = pd.to_datetime(u["date"])
    u = u[(u["date"] >= pd.Timestamp(start)) & (u["date"] <= pd.Timestamp(asof))]
    u["dividend"] = 0.0
    u["volume"] = 1e9
    u["source"] = "vrp_underlying"
    u["fetched_at"] = ""
    return u[["date", "ticker", "close", "dividend", "volume",
              "source", "fetched_at"]].reset_index(drop=True)


def book_price_loader(instruments, asof, warmup_trading_days):
    """Price loader for the whole book: routes each instrument to its source —
    SPY/QQQ to the vrp underlying file, every ETF to data/etf_daily.parquet.
    Sleeves are single-source (short-vol SPY-only, overlay LQD/IEF, credit
    ANGL/BIL), so a sleeve's call hits exactly one branch."""
    import math
    asof = pd.Timestamp(asof)
    span = max(10, int(math.ceil(warmup_trading_days * 1.7)) + 15)
    start = asof - pd.Timedelta(days=span)
    instruments = list(instruments)
    etf = [i for i in instruments if i not in UNDERLIER_TICKERS]
    und = [i for i in instruments if i in UNDERLIER_TICKERS]
    frames = []
    if etf:
        # Tickers the frozen panel carries keep their EXACT existing path; the
        # rest (the credit RV wrappers) come from the full-OHLC file.
        known = _panel_tickers()
        cef_known = _cef_tickers()
        in_panel = [t for t in etf if t in known]
        # CEFs are checked BEFORE the RV fallback. The two sets are disjoint
        # (verified: no CEF ticker appears in the frozen panel or the RV OHLC
        # file), so precedence cannot change how any existing ticker is priced.
        cef = [t for t in etf if t not in known and t in cef_known]
        rv_only = [t for t in etf if t not in known and t not in cef_known]
        if in_panel:
            frames.append(_attach_range(_load_etf(in_panel, start, asof)))
        if cef:
            frames.append(_load_cef(cef, start, asof))
        if rv_only:
            frames.append(_load_rv_only(rv_only, start, asof))
    if und:
        # SPY is both a short-vol underlier and the credit sleeve's equity
        # factor leg. The vrp file is close-only, so attach the session range
        # here too — otherwise the factor build drops SPY and the credit book
        # cannot neutralise its equity exposure.
        frames.append(_attach_range(_load_underliers(und, start, asof)))
    if not frames:
        return _load_etf(instruments, start, asof)
    return pd.concat(frames, ignore_index=True)


def _entry_alloc_type(entry):
    spec = entry.get("spec")
    if spec is None and entry.get("spec_path"):
        with open(entry["spec_path"]) as fh:
            spec = json.load(fh)
        entry["spec"] = spec          # cache so the orchestrator doesn't re-read
    return (spec or {}).get("allocation", {}).get("type")


def wire_runtime(book_spec, verbose=True):
    """Attach the runtime callables a JSON book spec cannot carry: the VRP
    marks/greeks seam and per-sleeve VRP costs for any short_vol_straddle
    sleeve. ETF sleeves need nothing here (marks come from the price panel);
    the FOMC sleeve self-loads data/events.parquet. Returns the events frame to
    thread onto MarketState (or None)."""
    provider = None
    for entry in book_spec.get("sleeves", []):
        if not entry.get("enabled", True):
            continue
        if _entry_alloc_type(entry) != "short_vol_straddle":
            continue
        if entry.get("mark_fn") is not None:      # already wired (test path)
            continue
        # lazy import: only a short-vol book pulls in the vrp math
        from src.deploy.sleeves.spy_shortvol_marks import (
            SpyVrpMarks, load_vrp_costs)
        if provider is None:
            provider = SpyVrpMarks()
            if verbose:
                print(f"[run_book] wired SPY vrp marks "
                      f"{provider.first_mark_date}..{provider.last_mark_date} "
                      f"for {entry['name']}")
        entry["mark_fn"] = provider.mark_fn
        entry["greeks_fn"] = provider.greeks_fn
        entry["costs"] = load_vrp_costs()

    events = None
    if EVENTS_PATH.exists():
        events = pd.read_parquet(EVENTS_PATH)
    return events


def replay_calendar(book_spec, asof, replay_start):
    """Trading days between replay_start and asof, using the union of the book's
    ETF instruments as the calendar reference.

    Within the panel these are the panel's own bar dates (unchanged). For an asof
    beyond the panel's last bar the list is EXTENDED with forward NYSE trading
    days from ops/schedule/nyse_calendar.py (weekends/holidays skipped), so the
    live paper window (e.g. 2026-07-21..2026-07-24) is booked day-by-day."""
    tickers = set()
    for entry in book_spec.get("sleeves", []):
        spec = entry.get("spec")
        if spec is None and entry.get("spec_path"):
            with open(entry["spec_path"]) as fh:
                spec = json.load(fh)
        alloc = (spec or {}).get("allocation", {})
        if "weights" in alloc:
            tickers.update(alloc["weights"])
        # A weight-expressed sleeve (credit_rv) carries no allocation.weights —
        # its instruments live in frozen.universe. Without this the calendar
        # reference falls back to BIL and the book's own trading days are
        # inferred from an instrument it does not hold.
        uni = (spec or {}).get("frozen", {}).get("universe")
        if isinstance(uni, list):
            tickers.update(uni)
    tickers = sorted(tickers) or ["BIL"]
    asof = pd.Timestamp(asof)
    replay_start = pd.Timestamp(replay_start)
    px = ops_common.fetch_local(tickers, replay_start, asof)
    days = sorted(pd.DatetimeIndex(px["date"].unique()))
    panel_last = _panel_last_date()
    if asof <= panel_last:
        return days                              # within-panel: UNCHANGED
    cal = _nyse_calendar()
    cursor = max([panel_last] + days)            # last real bar we already have
    d = cal.next_trading_day(cursor)             # strictly after cursor
    while pd.Timestamp(d) <= asof:
        if pd.Timestamp(d) >= replay_start:
            days.append(pd.Timestamp(d))
        d = cal.next_trading_day(d)
    return days


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asof", required=True, help="run as of this date (YYYY-MM-DD)")
    ap.add_argument("--book", required=True, help="path to the book spec JSON")
    ap.add_argument("--source", default="local", choices=["local", "yfinance"])
    ap.add_argument("--books-root", default="ops/books")
    ap.add_argument("--replay-start", default=None,
                    help="loop the orchestrator day-by-day from here to --asof")
    ap.add_argument("--no-report", action="store_true",
                    help="skip the human daily report + target_vs_current")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and LOG the target book only: no order is "
                         "transmitted, no sub-ledger is advanced or written, "
                         "and the rollup goes to book_status_dryrun.json "
                         "(book_status.json is untouched). Works regardless "
                         "of EXECUTION — ibkr is never connected.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    execution = os.environ.get("EXECUTION", "simulator")
    asof = pd.Timestamp(args.asof)
    book_spec = load_book_spec(args.book)
    verbose = not args.quiet

    events = wire_runtime(book_spec, verbose=verbose)

    if args.dry_run:
        from src.deploy.broker import DryRunBroker
        if execution == "ibkr" and verbose:
            print("[run_book] --dry-run: EXECUTION=ibkr ignored — no broker "
                  "connection; holdings read from the local sub-ledgers.")
        broker = DryRunBroker(books_root=args.books_root, verbose=verbose)
    else:
        broker = make_broker(execution, books_root=args.books_root,
                             verbose=verbose)
        if execution == "ibkr":
            broker.connect()

    orch = PortfolioOrchestrator(book_spec, broker, books_root=args.books_root,
                                 events=events, price_loader=book_price_loader,
                                 verbose=verbose, dry_run=args.dry_run)

    # Arm AFTER the sleeves are registered (the orchestrator's constructor does
    # that) and BEFORE any target is placed. arm() adopts the broker's position
    # counts into the per-sleeve tag books, so a shadow ledger that fell behind
    # can no longer make a held book look flat. Refusing to arm is not a crash:
    # the run continues and still reports, it just never transmits.
    if not args.dry_run and execution == "ibkr":
        report = broker.arm()
        if not report["ok"]:
            from ops.halt import write_halt
            detail = "\n".join(f"  - {p}" for p in report["problems"])
            write_halt(reason="broker arming failed — position attribution is ambiguous",
                       detail=f"`arm()` could not explain the account with the "
                              f"registered sleeves:\n\n{detail}\n\nNo order was "
                              f"transmitted. Resolve the attribution (usually by "
                              f"rebuilding the shadow ledger from broker fills) "
                              f"before the next session.",
                       source="run_book.arm")
            print("[run_book] NOT ARMED — no orders will be transmitted this session.")
            return 3

    # ARM BEFORE TRANSMITTING. The orchestrator has now registered every sleeve,
    # so the broker can compare the account against the sleeves that claim it.
    # `arm()` adopts broker QUANTITIES while keeping the ledger's ATTRIBUTION,
    # and refuses when a shared symbol is genuinely ambiguous.
    #
    # This call is what makes the adapter's NotArmed guard reachable. Without it
    # `place_targets` raises on every live sleeve and the run silently transmits
    # nothing -- which is exactly what happened on the first two armed CEF runs
    # of 2026-07-31, both of which exited 0 having sent no orders.
    #
    # A refusal is fatal on purpose: the alternative is diffing targets against a
    # position book we know is wrong, and on 2026-07-31 that would have re-bought
    # $2.07M of already-held positions.
    if execution == "ibkr" and not args.dry_run:
        report = broker.arm()
        if not report.get("ok"):
            print(f"[run_book] ABORT: broker.arm() refused to arm — "
                  f"{len(report.get('problems', []))} unexplainable position(s). "
                  f"No orders transmitted.")
            for p in report.get("problems", []):
                print(f"[run_book]   {p}")
            return 2

    if args.replay_start:
        days = replay_calendar(book_spec, asof, args.replay_start)
        if verbose:
            print(f"[run_book] EXECUTION={execution} replay {days[0].date()}.."
                  f"{days[-1].date()} N={len(days)} trading days")
        view = None
        for d in days:
            view = orch.advance(d, source=args.source)
    else:
        if verbose:
            print(f"[run_book] EXECUTION={execution} single day asof={asof.date()}")
        view = orch.advance(asof, source=args.source)

    if args.dry_run:
        out = Path(args.books_root) / f"dryrun_{asof.date()}.json"
        payload = {"asof": str(asof.date()), "execution_requested": execution,
                   "transmitted": False, "planned": broker.planned}
        with open(out, "w") as fh:
            json.dump(payload, fh, indent=2, default=str)
        n_t = sum(len(p["targets"]) for p in broker.planned)
        if verbose:
            print(f"\n[run_book] DRY-RUN asof {asof.date()}: "
                  f"{n_t} targets across {len(broker.planned)} sleeve-days "
                  f"logged to {out} — NO orders transmitted, NO ledger writes.")
    elif view is not None and not args.no_report:
        book_report.write_daily_report(
            orch, view, args.books_root,
            data_sources=book_spec.get("data_sources"), verbose=verbose)

    if verbose and view is not None:
        print(f"\n[run_book] BOOK asof {pd.Timestamp(view.asof).date()}  "
              f"NAV ${view.book_nav:,.2f}  PnL ${view.book_pnl:,.2f}  "
              f"turnover ${view.book_turnover:,.0f}  "
              f"gross ${view.gross_exposure:,.0f}")
        for name, sv in view.sleeves.items():
            nav = sv['nav']
            nav_s = f"${nav:,.2f}" if nav == nav else "n/a"
            print(f"[run_book]   {name}: NAV {nav_s}  "
                  f"verdict {sv['risk_verdict']['status']}  "
                  f"{'DISABLED' if sv['disabled'] else 'enabled'}")
        for lim, res in view.limits.items():
            print(f"[run_book]   limit {lim}: {'OK' if res.get('ok') else 'BREACH'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
