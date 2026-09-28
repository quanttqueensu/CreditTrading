"""QUANTT book dashboard — local, read-only, PM view.

    python3 dashboard/server.py            # http://127.0.0.1:8787

WHY LOCAL, AND WHY READ-ONLY
----------------------------
Local because the whole point is a live broker: a hosted page cannot reach
127.0.0.1:4002, and a dashboard that cannot see the account is decoration.

Read-only because a monitor that can also trade is a second, unreviewed order
path into a live account. Every guard this repo has — preflight, `arm()`, the
same-day guard, the shadow ledger — lives on the `launch_job.py` path. A button
here that placed orders would bypass all of them. So:

  * NOTHING in this file transmits an order. There is no code path to it.
  * `/api/connect` starts IB GATEWAY (via IBC). That is infrastructure, not
    trading, and it is the one action the PM needs that is not a read.
  * `/api/verify` re-derives the signal INDEPENDENTLY and compares. It answers
    "would tonight's trades be right?", it does not place them.

Trading stays where it is reviewed: the scheduled jobs.

ENDPOINTS (every one a GET and a pure read, except /api/connect)
---------------------------------------------------------------
  /api/status      broker reachability, account summary, DATA FRESHNESS
  /api/connect     POST — starts IB Gateway via IBC. The only non-read. No orders.
  /api/signal      today's target weights, re-derived independently
  /api/pnl         shadow-ledger statistics + EXECUTION PROVENANCE per book
  /api/benchmarks  everything indexed to 100, plus what is MISSING and why
  /api/live        broker marks + ledger-vs-broker RECONCILIATION
  /api/verify      operational + mathematical pre-trade checks
  /api/doctor      scheduler / plumbing checks
  /api/provenance  which ledger sessions have real broker fills   [read-only]
  /api/risk        the book's own limit state from book_status.json [read-only]
  /api/sessions    per-session ARM/miss outcomes, both log trees   [read-only]

NO SILENT FALLBACKS
-------------------
Every endpoint here reports missing data as missing. Nothing substitutes a
default, a zero, or a plausible-looking number for something it could not
compute — a fabricated figure on a trading dashboard is worse than a blank one,
because a blank invites a question and a fabrication does not. Where a value
cannot be produced, the payload carries the REASON alongside the gap, and the
page renders the reason where the number would have been.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from flask import Flask, jsonify, send_from_directory  # noqa: E402

app = Flask(__name__, static_folder=str(Path(__file__).parent / "static"))

BOOKS = {
    "cef_discount": ("ops/books/cef_discount_book.json", "ops/books/cef_live"),
    "null_trader": ("ops/books/phase0_book.json", "ops/books/phase0_live"),
}
BENCH_ROOT = REPO / "ops/books/benchmarks_live/_ibkr_shadow"
# Plain-English names, defined once and used everywhere. The internal keys
# (bench_b3_agg, cef_discount, null_trader) are spec filenames and mean nothing
# to a reader; a dashboard that makes you translate its own labels is a
# dashboard you stop reading.
LABEL = {
    "cef_discount":       "Credit CEF strategy",
    "null_trader":        "Null trader (control)",
    "bench_b1_hyg":       "Benchmark · high yield (HYG)",
    "bench_b3_agg":       "Benchmark · core bonds (AGG)",
    "bench_b4_60_40":     "Benchmark · 60/40 stocks & bonds",
    "bench_b5_shy":       "Benchmark · short treasuries (SHY)",
    "bench_b6_ew_credit": "Benchmark · equal-weight credit",
    "shared":             "Held by more than one book",
    "unattributed":       "Not assigned to a book",
}
def label(k):
    return LABEL.get(k, k)

BENCH_LABEL = {k: LABEL[k] for k in
               ("bench_b1_hyg", "bench_b3_agg", "bench_b4_60_40",
                "bench_b5_shy", "bench_b6_ew_credit")}

_cache: dict = {}
# One lock per cache key, plus one lock for the whole broker. See cached().
_cache_locks: dict = {}
_cache_locks_guard = threading.Lock()
_broker_lock = threading.Lock()
# The page polls /api/live every 5s. A 4s TTL meant a fresh IBKR session on
# nearly every poll -- roughly 17,000 connect/disconnect cycles a day, each
# leaving a socket behind. 12s keeps the monitor live to the eye and cuts the
# churn by two thirds. Portfolio marks do not move faster than this matters.
LIVE_TTL = 12


def clean(o):
    """Replace non-finite floats with None, recursively, before serialising.

    `json.dumps` emits a bare `NaN` token by default. Python's own loader accepts
    it; a BROWSER's JSON.parse does not, and Flask's jsonify does it silently. So
    one NaN anywhere in a payload turns into an uncaught exception in the page's
    fetch chain and the whole dashboard renders blank.

    Measured 2026-09-04: null_trader's ledger has two NAV rows, so
    `pct_change().dropna()` leaves ONE return, whose sample std is NaN by
    definition (ddof=1). `ann_vol_pct` carried that straight into /api/pnl and
    killed the page. Guarding one field would not have been enough — this walks
    the whole structure so no future statistic can reintroduce it.
    """
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def sjson(payload):
    """jsonify, but never emits NaN/Infinity."""
    return jsonify(clean(payload))


def cached(key, ttl, fn):
    """Broker probes are slow and the page polls; never hit TWS per widget.

    SINGLE FLIGHT, added 2026-09-10. The cache alone was not enough. Flask
    serves requests on threads, so two requests that miss the same key both
    ran `fn()`, and when `fn` is `_portfolio` that means two sockets opening
    with the SAME IBKR client id. IB allows one session per client id: the
    second connect silently evicts the first, which then reports a dead
    broker. Measured on the running server: 7 CLOSED sockets to port 4002
    still held by this process after 38h, `/api/live` polling every 5s
    against a 4s TTL, and `factor_pos` calling `_portfolio` (client 302) on
    its own key at the same time. That churn is also what makes the gateway
    answer 10197 "No market data during competing live session" to the
    borrow-availability tick.

    So: one lock per key, and the winner recomputes while everyone else
    waits and takes the fresh value. The double-check inside the lock is what
    makes the waiters cheap — they return the value the winner just stored
    instead of queueing another broker round trip.
    """
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    with _cache_locks_guard:
        lock = _cache_locks.setdefault(key, threading.Lock())
    with lock:
        # Someone may have refreshed it while we waited for the lock.
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        val = fn()
        _cache[key] = (time.time(), val)
        return val


# ---------------------------------------------------------------- broker ----
def _probe_broker():
    try:
        from src.deploy.broker.ibkr import IBKRConfig
        from ops.switch_broker import _probe
        cfg = IBKRConfig.from_env()
        res = _probe(cfg.host, cfg.port, client_id=205, timeout=8)
        res["host"], res["port"] = cfg.host, cfg.port
        return res
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


def _ibc_running():
    """True / False / None — None meaning "could not tell".

    This used to `except: pass` and fall through to `return False`, so a failed
    or timed-out `ps` reported the gateway supervisor as NOT RUNNING. That is a
    fabricated negative on a health panel: "I could not check" and "it is down"
    are different facts and only one of them should send someone to the logs.
    """
    try:
        out = subprocess.run(["ps", "axo", "pid=,command="], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return None
    me = str(subprocess.os.getpid())
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if pid == me:
            continue
        if any(t in cmd.lower() for t in
               ("ibcstart", "gatewaystart", "ibcontroller", "ibc.jar")):
            return True
    return False


def _age_bd(datestr):
    """Business days between a YYYY-MM-DD string and today, or None if unparseable.

    None means "could not be computed" and the page prints that. It never
    collapses to 0, which would read as "fresh today" — the exact inversion of
    the truth you want when a feed has silently stopped.
    """
    try:
        d = pd.Timestamp(datestr).normalize()
    except Exception:
        return None
    today = pd.Timestamp.today().normalize()
    if d > today:
        return 0
    return max(0, len(pd.bdate_range(d, today)) - 1)


def _freshness():
    """How stale is each thing the page reports? One place, explicit reasons."""
    out = {}

    def add(key, datestr, reason=None, stale_bd=2):
        if datestr is None:
            out[key] = {"date": None, "age_bd": None, "state": "unknown",
                        "reason": reason or "not available"}
            return
        age = _age_bd(datestr)
        out[key] = {
            "date": datestr, "age_bd": age,
            "state": ("unknown" if age is None
                      else "stale" if age > stale_bd else "fresh"),
            "reason": reason,
        }

    df = _nav_df(BOOKS["cef_discount"][1], "cef_discount")
    add("ledger", (str(df["date"].iloc[-1].date()) if df is not None else None),
        None if df is not None else "no readable nav.csv for the strategy book")

    try:
        from src.deploy.sleeves.cef_discount import PX_PATH, NAV_PATH
        for key, p in (("prices", PX_PATH), ("nav_panel", NAV_PATH)):
            if not Path(p).exists():
                add(key, None, f"{p} does not exist")
                continue
            t = pd.read_parquet(p, columns=["date"])
            add(key, str(pd.to_datetime(t["date"]).max().date()))
    except Exception as exc:
        for key in ("prices", "nav_panel"):
            out.setdefault(key, {"date": None, "age_bd": None, "state": "unknown",
                                 "reason": f"panel unreadable: {exc!r}"})

    hb = REPO / "ops/heartbeat.json"
    if not hb.exists():
        add("heartbeat", None, f"no {hb.relative_to(REPO)}")
    else:
        try:
            h = json.loads(hb.read_text())
            cef = h.get("cef") or {}
            add("heartbeat", cef.get("date"),
                None if cef.get("date") else "heartbeat.json has no cef.date")
            out["heartbeat"]["status"] = cef.get("status")
            out["heartbeat"]["jobs"] = {
                k: {"status": v.get("status"), "date": v.get("date")}
                for k, v in h.items() if isinstance(v, dict)}
        except Exception as exc:
            add("heartbeat", None, f"heartbeat.json unreadable: {exc!r}")
    return out


@app.get("/api/status")
def api_status():
    b = cached("broker", 20, _probe_broker)
    acct = {}
    if b.get("ok"):
        acct = {"account": (b.get("accounts") or [None])[0],
                "nlv": b.get("nlv"), "positions": len(b.get("positions") or {})}
    try:
        fresh = cached("fresh", 30, _freshness)
    except Exception as exc:
        fresh = {"_error": f"freshness check failed: {exc!r}"}
    return sjson({
        "connected": bool(b.get("ok")),
        "error": b.get("error"),
        "endpoint": f"{b.get('host', '?')}:{b.get('port', '?')}",
        "ibc": _ibc_running(),
        "freshness": fresh,
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        **acct,
    })


@app.get("/api/risk")
def api_risk():
    """READ-ONLY. The book's own limit state — what would stop it trading.

    Straight from ops/books/cef_live/book_status.json, which the scheduled job
    writes. Reported, never recomputed here: a second opinion on a kill-switch
    would be a second kill-switch.
    """
    p = REPO / "ops/books/cef_live/book_status.json"
    if not p.exists():
        return sjson({"ok": False,
                      "reason": f"no {p.relative_to(REPO)} — the book has not "
                                f"written a status file"})
    try:
        s = json.loads(p.read_text())
    except Exception as exc:
        return sjson({"ok": False, "reason": f"book_status.json unreadable: {exc!r}"})
    lims = []
    for name, v in (s.get("limits") or {}).items():
        if not isinstance(v, dict):
            lims.append({"name": name, "ok": None,
                         "detail": f"unexpected shape: {v!r}"})
            continue
        lims.append({
            "name": name, "ok": v.get("ok"),
            "value": v.get("value"), "cap": v.get("cap") or v.get("budget"),
            "action": v.get("action"),
            "breaches": v.get("breaches"),
        })
    sl = (s.get("sleeves") or {}).get("cef_discount") or {}
    return sjson({
        "ok": True,
        "asof": s.get("asof"),
        "age_bd": _age_bd(s.get("asof")),
        "limits": lims,
        "enabled": sl.get("enabled"),
        "disabled": sl.get("disabled"),
        "review_flag": sl.get("review_flag"),
        "verdict": sl.get("risk_verdict"),
        "gross_exposure": s.get("gross_exposure"),
        "net_exposure": s.get("net_exposure"),
    })


@app.post("/api/connect")
def api_connect():
    """Start IB Gateway via IBC. Infrastructure only — places no orders."""
    plist = Path.home() / "Library/LaunchAgents/com.quantt.ibgateway.plist"
    if not plist.exists():
        return sjson({"ok": False, "msg": "com.quantt.ibgateway.plist not installed"})
    try:
        uid = str(subprocess.os.getuid())
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/com.quantt.ibgateway"],
                       capture_output=True, timeout=20)
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
                           capture_output=True, text=True, timeout=30)
        _cache.pop("broker", None)
        ok = r.returncode == 0
        return sjson({"ok": ok,
                      "msg": "IBC starting — login takes 60-90s"
                             if ok else (r.stderr or "bootstrap failed").strip()})
    except Exception as exc:
        return sjson({"ok": False, "msg": repr(exc)})


# ---------------------------------------------------------------- signal ----
def _signal_frame(asof=None):
    """Re-derive discount / z / weights straight from the staged panel.

    This is an INDEPENDENT reimplementation of
    src/deploy/sleeves/cef_discount.py, not a call into it. That is the point:
    /api/verify compares the two, so a silent divergence between the deployed
    sleeve and its documented maths shows up as a diff instead of a surprise.
    """
    from src.deploy.sleeves.cef_discount import PX_PATH, NAV_PATH
    spec = json.loads((REPO / "ops/specs/cef_discount.frozen.json").read_text())
    fz = spec["frozen"]
    uni = list(fz["universe"])
    win = int(fz.get("z_window", 252))

    P = pd.read_parquet(PX_PATH)
    N = pd.read_parquet(NAV_PATH)
    P, N = P[P.ticker.isin(uni)], N[N.ticker.isin(uni)]
    d = P.merge(N, on=["date", "ticker"], how="inner")
    d["date"] = pd.to_datetime(d["date"])
    if asof:
        d = d[d.date <= pd.Timestamp(asof)]
    d = d[(d.nav > 0.5) & (d.close > 0.5)]
    px = d.pivot_table(index="date", columns="ticker", values="close").sort_index()
    nav = d.pivot_table(index="date", columns="ticker", values="nav").sort_index()
    vol = d.pivot_table(index="date", columns="ticker", values="volume").sort_index()

    disc = 100.0 * (px - nav) / nav
    mu = disc.rolling(win, min_periods=120).mean().shift(1)
    sd = disc.rolling(win, min_periods=120).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    adv = (px * vol).rolling(63, min_periods=21).mean().shift(1)

    # A band replaces the calendar: under `band_width` the sleeve recomputes the
    # signal EVERY session (`cef_discount.py`, sig_pos = pos), so this
    # re-derivation must too or the two land on different signal dates and
    # disagree for a reason that has nothing to do with the maths.
    rebal = 1 if fz.get("band_width") else int(fz.get("rebalance_days", 1))
    pos = len(z.index) - 1
    last = z.index[pos - (pos % rebal)]

    min_adv = float(fz.get("min_adv_usd", 0))
    max_age = int(fz.get("max_nav_age_bd", 3))
    row, dropped = {}, {}
    for tk in px.columns:
        zi = z.loc[last, tk]
        if not np.isfinite(zi):
            dropped[tk] = "no z"; continue
        if float(adv.loc[last, tk] or 0.0) < min_adv:
            dropped[tk] = "illiquid"; continue
        nt = nav[tk].dropna()
        if nt.empty:
            dropped[tk] = "no NAV"; continue
        age = len(pd.bdate_range(nt.index[-1], last)) - 1
        if age > max_age:
            dropped[tk] = f"NAV {age}bd stale"; continue
        row[tk] = float(zi)

    s = pd.Series(row)
    w = -(s - s.mean())
    w = w / w.abs().sum()
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    hist = (ret[list(row)].mul(w, axis=1)).sum(axis=1).tail(63)
    rv = float(hist.std() * np.sqrt(252))
    # Key names must match the sleeve's accessors EXACTLY, defaults included —
    # this function's whole value is that it is an independent re-derivation, and
    # a re-derivation reading a different config key silently compares two
    # different strategies. Mirrors cef_discount.py `_vol_target` / `_min_adv`
    # / `_rebal_days`, which read vol_target_annual (0.06), min_adv_usd (3e6)
    # and rebalance_days (2).
    vt = float(fz.get("vol_target_annual", 0.06))
    scal = float(np.clip(vt / rv, 0.2, 2.5)) if rv > 0 else 1.0
    gl = float(fz.get("gross_leverage", 1.0))
    w = w * scal * gl
    minw = float(fz.get("min_abs_weight", 0.005))
    keep = w[w.abs() >= minw]
    if len(keep) >= int(fz.get("min_names", 6)):
        keep = keep - keep.mean()
        den = keep.abs().sum()
        if den > 0:
            w = keep / den * scal * gl

    return {"asof": str(px.index[-1].date()), "signal_date": str(last.date()),
            "disc": disc.loc[last], "z": s, "w": w, "dropped": dropped,
            "volscal": scal, "realised_vol": rv, "vol_target": vt,
            "gross_leverage": gl, "min_abs_weight": minw, "px": px.loc[last]}


@app.get("/api/signal")
def api_signal():
    try:
        f = _signal_frame()
    except Exception as exc:
        return sjson({"ok": False, "error": repr(exc)})
    held = _held("cef_discount")
    # `or 500000.0` used to sit here. If the ledger could not be read, every
    # target_shares and notional on this page was silently computed against an
    # invented half-million-dollar book and rendered as though it were real.
    # There is no defensible default for the size of a book; if we do not know
    # it, the share counts do not exist and the page must say so.
    nav_now = _nav_last("cef_discount")
    if nav_now is None:
        return sjson({
            "ok": False,
            "error": "cannot size positions: no readable nav.csv for "
                     "cef_discount, so the book's capital is unknown",
        })
    # Cheap/rich is a CROSS-SECTIONAL judgement, not an absolute one. The book
    # trades `w = -(z - mean(z))`, so the dividing line is today's mean z, not
    # zero. Using zero mislabels any name whose z sits between the two: measured
    # 2026-09-04, mean z was -0.765, and NZF (-0.70) and MQY (-0.36) were tagged
    # CHEAP in blue while the book was SHORTING them — the tag contradicted the
    # panel's own "cheap -> long, rich -> short" legend. The reference point has
    # to be the same one the weights use or the label is decoration.
    zbar = float(f["z"].mean())
    rows = []
    for tk in sorted(f["z"].index, key=lambda t: f["z"][t]):
        w = float(f["w"].get(tk, 0.0))
        price = float(f["px"].get(tk, np.nan))
        tgt_sh = int(round(w * nav_now / price)) if price > 0 else 0
        cur = int(held.get(tk, 0))
        rows.append({
            "ticker": tk,
            "discount": round(float(f["disc"].get(tk, np.nan)), 2),
            "z": round(float(f["z"][tk]), 2),
            "verdict": "CHEAP" if f["z"][tk] < zbar else "RICH",
            "weight": round(w, 5),
            "price": round(price, 2),
            "target_shares": tgt_sh,
            "current_shares": cur,
            "delta_shares": tgt_sh - cur,
            "side": "LONG" if w > 0 else ("SHORT" if w < 0 else "FLAT"),
            "notional": round(abs(tgt_sh * price), 0),
        })
    return sjson({
        "ok": True, "asof": f["asof"], "signal_date": f["signal_date"],
        "volscal": round(f["volscal"], 3),
        "realised_vol": round(f["realised_vol"], 4),
        "vol_target": f["vol_target"],
        "dropped": f["dropped"], "rows": rows,
        "z_mean": round(zbar, 3),
        "gross_weight": round(float(f["w"].abs().sum()), 4),
        "net_weight": round(float(f["w"].sum()), 6),
        "book_nav": round(nav_now, 2),
        # Named so the page cannot present these as an order ticket. "Held now"
        # is the LEDGER's belief about the book; /api/live's `reconcile` block
        # says whether the account agrees. When it does not, delta_shares is
        # arithmetic against a position that is not there.
        "current_shares_source": "shadow ledger positions.csv (not the broker)",
        "is_order_ticket": False,
    })


@app.get("/api/trades")
def api_trades():
    """The order list the next session would transmit — nothing else.

    This is the one panel that must not be a re-derivation. `/api/signal` shows
    the FRICTIONLESS target book (what the maths wants); the executor sends
    something different, because the sleeve runs a no-trade band and the ledger
    floors weights to whole shares. A trade list built from the frictionless
    weights would print orders the session will not send, which is worse than
    printing nothing.

    So: RUN the deployed sleeve against the ledger's own holdings and NAV, then
    diff it exactly the way exec_ledger.DerivativesLedger._make_orders does —
    signed target = sign * floor(nav * |w| / price), delta = target - held,
    dropped under `rebalance.min_trade_usd`.

    TIMING. The signal needs the fund's NAV, which sponsors publish some time
    after the close. Since 2026-09-08 the job fires at 17:15 ET and then WAITS
    for today's NAV on every deployed name (deadline NAV_DEADLINE in cef.env,
    21:30) before deciding on today's price/NAV pair; if the pair is not
    complete by then it stands down. Either way the decision is past the 15:50
    MOC cutoff, so an order decided on session D rests overnight and fills in
    the closing auction of D+1. Both dates are reported; neither is inferred
    by the page.

    Until today's pair lands this endpoint runs the sleeve on the last complete
    pair -- that is what `asof` says -- so before ~19:00 the list is the
    previous session's answer, not tonight's.
    """
    spec_path = REPO / "ops/specs/cef_discount.frozen.json"
    try:
        spec = json.loads(spec_path.read_text())
    except Exception as exc:
        return sjson({"ok": False, "error": f"cannot read {spec_path.name}: {exc!r}"})
    fz = spec.get("frozen", {})

    nav_now = _nav_last("cef_discount")
    if nav_now is None:
        return sjson({"ok": False,
                      "error": "no readable nav.csv for cef_discount, so the "
                               "book's capital is unknown and no order can be sized"})
    held = _held("cef_discount")

    # Sizing price: the price-store close the executor would read on the day it
    # runs. That is the LAST CLOSE, which is not necessarily the signal date —
    # the signal needs a price/NAV pair and NAV publishes later, so the panel
    # routinely knows one more close than it knows discounts.
    from src.deploy.sleeves.cef_discount import PX_PATH
    try:
        P = pd.read_parquet(PX_PATH)
        P["date"] = pd.to_datetime(P["date"])
        last_px_date = P["date"].max()
        close = (P[P["date"] == last_px_date]
                 .set_index("ticker")["close"].astype(float).to_dict())
    except Exception as exc:
        return sjson({"ok": False, "error": f"price store unreadable: {exc!r}"})

    # Run the DEPLOYED sleeve, handed the same two things the live executor
    # hands it: this sleeve's own holdings, and this sleeve's NAV. Without both
    # the band has no denominator and correctly refuses to trade.
    try:
        from src.deploy.sleeves.cef_discount import CEFDiscountSleeve
        from src.deploy.sleeve import MarketState, FLAT, SHORT
        sl = CEFDiscountSleeve(spec, nav_now)
        asof = str(last_px_date.date())
        ms = MarketState(asof=asof, prices=pd.DataFrame(), holdings=dict(held),
                         extras={"sleeve_nav": nav_now})
        targets = sl.target_positions(asof, ms)
    except Exception as exc:
        return sjson({"ok": False, "error": f"sleeve refused to produce a book: {exc!r}"})

    min_trade = float(spec.get("rebalance", {}).get("min_trade_usd", 0.0))
    desired, why = {}, {}
    for pt in targets:
        why[pt.instrument] = pt.reason or ""
        price = float(close.get(pt.instrument, float("nan")))
        if pt.side == FLAT:
            desired[pt.instrument] = 0.0
            continue
        if pt.qty is not None:
            # Qty-expressed: the sleeve has named the share count itself (a band
            # HOLD, since 2026-09-08) and no price is consulted on either side of
            # the diff. That is the whole point — see the dust-order note below.
            desired[pt.instrument] = float(pt.signed_qty())
            continue
        if not np.isfinite(price) or price <= 0:
            # The executor skips the name with a warning rather than sizing it.
            continue
        mag = math.floor(nav_now * abs(float(pt.weight)) / price)
        desired[pt.instrument] = float(-mag if pt.side == SHORT else mag)
    for tk in held:
        desired.setdefault(tk, 0.0)

    # Last known close per name, used ONLY to size the warning on a name the
    # executor cannot price. It is never substituted into `price`: a row the
    # session will send at an unknown price must not display a known one.
    lastpx = (P.sort_values("date").groupby("ticker")
              .agg(close=("close", "last"), date=("date", "last")))

    rows, held_rows = [], []
    for tk in sorted(desired):
        price = float(close.get(tk, float("nan")))
        priced = bool(np.isfinite(price) and price > 0)
        cur = float(held.get(tk, 0.0))
        tgt = float(desired[tk])
        delta = tgt - cur
        reason = why.get(tk, "")
        band = "hold" if "band hold" in reason else ("trade" if tk in why else "n/a")
        # WHAT KIND OF ORDER IS THIS. Separating the strategy's trades from the
        # plumbing's is the difference between "the strategy is trading" and
        # "the plumbing is trading". Until 2026-09-08 the band decided hold/trade
        # on WEIGHTS and the executor re-derived SHARES from a possibly newer
        # close, so a name the band told us to leave alone still emitted a few
        # shares of rounding drift: `dust`. A HOLD is now qty-expressed and its
        # delta is exactly zero, so `dust` should never appear again — the label
        # is kept, and kept off the zero-delta rows, precisely so that a
        # regression shows up here as an order rather than hiding among the
        # holds.
        if cur and not tgt:
            kind = "exit"
        elif tgt and not cur:
            kind = "entry"
        elif band == "hold":
            kind = "hold" if abs(delta) < 1e-9 else "dust"
        else:
            kind = "rebalance"
        rec = {"ticker": tk, "current_shares": int(cur), "target_shares": int(tgt),
               "delta_shares": int(delta),
               "price": round(price, 2) if priced else None,
               "notional": round(abs(delta) * price, 0) if priced else None,
               "side": "BUY" if delta > 0 else ("SELL" if delta < 0 else "flat"),
               "position_side": "LONG" if tgt > 0 else ("SHORT" if tgt < 0 else "FLAT"),
               "band": band, "kind": kind, "reason": reason}
        if not priced:
            # Not a cosmetic gap. A name the sleeve WANTED but could not price
            # falls out of the executor's `desired` map, and the
            # held-but-unmentioned rule then sweeps it to FLAT -- so a missing
            # mark does not hold the position, it liquidates it.
            lp = lastpx.loc[tk] if tk in lastpx.index else None
            rec["kind"] = "forced-exit" if cur else "unpriced"
            rec["warn"] = (f"no close on {asof}; the sleeve still wants this "
                           f"name, but the executor cannot size an unpriced "
                           f"leg and the held-but-unmentioned rule flattens it")
            if lp is not None:
                rec["last_close"] = round(float(lp["close"]), 2)
                rec["last_close_date"] = str(pd.Timestamp(lp["date"]).date())
                rec["notional_est"] = round(abs(delta) * float(lp["close"]), 0)
            rows.append(rec)
            continue
        if abs(delta) < 1e-9:
            held_rows.append(rec)
            continue
        if abs(delta) * price < min_trade:
            rec["skipped"] = f"under min_trade_usd {min_trade:,.0f}"
            held_rows.append(rec)
            continue
        rows.append(rec)

    rows.sort(key=lambda r: -(r.get("notional") or r.get("notional_est") or 0.0))
    gross_traded = sum(r.get("notional") or 0.0 for r in rows)
    gross_unpriced = sum(r.get("notional_est") or 0.0
                         for r in rows if r.get("notional") is None)

    # Sessions. `nyse_calendar` is the same module the scheduler gates on, so
    # the page cannot disagree with the job about whether tonight is a session.
    sys.path.insert(0, str(REPO / "ops/schedule"))
    import nyse_calendar as cal
    today = pd.Timestamp.today().normalize().date()
    decide = today if cal.is_trading_day(today) else cal.next_trading_day(today)
    fills = cal.next_trading_day(decide)

    return sjson({
        "ok": True,
        "asof": asof,
        "book_nav": round(nav_now, 2),
        "orders": rows,
        "unchanged": held_rows,
        "n_orders": len(rows),
        "gross_traded_usd": round(gross_traded, 0),
        "gross_unpriced_usd": round(gross_unpriced, 0),
        "turnover_pct": round(gross_traded / nav_now * 100, 2) if nav_now else None,
        "n_by_kind": {k: sum(1 for r in rows if r["kind"] == k)
                      for k in sorted({r["kind"] for r in rows})},
        "band_width": fz.get("band_width"),
        "order_type": str(fz.get("order_type", "MOC")).upper(),
        "decision_date": str(decide),
        "decision_time_et": "after today's NAV publishes (from 17:15, by "
                            + _nav_deadline() + ")",
        # Both halves: a close for today with yesterday's NAV is not today's pair.
        "pair_is_today": bool(last_px_date.normalize() == pd.Timestamp(today)
                              and _nav_panel_last() == pd.Timestamp(today)),
        "fill_date": str(fills),
        "today_is_session": bool(cal.is_trading_day(today)),
        "min_trade_usd": min_trade,
        # Same caveat as /api/signal: "held" is the shadow ledger's belief.
        "current_shares_source": "shadow ledger positions.csv (not the broker)",
        "is_order_ticket": False,
    })


# ------------------------------------------------------------- book state ---
def _nav_df(book_root, sleeve):
    p = REPO / book_root / "_ibkr_shadow" / sleeve / "nav.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
    return df if not df.empty else None


def _nav_last(sleeve):
    root = BOOKS.get(sleeve, (None, None))[1]
    if not root:
        return None
    df = _nav_df(root, sleeve)
    return float(df["nav"].iloc[-1]) if df is not None else None


def _held(sleeve):
    root = BOOKS.get(sleeve, (None, None))[1]
    p = REPO / root / "_ibkr_shadow" / sleeve / "positions.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    df = df[df.ticker != "CASH"]
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    last = df[df["date"] == df["date"].max()]
    return {r.ticker: float(r.shares) for r in last.itertuples()
            if pd.notna(r.shares)}


def _stats(nav: pd.Series):
    """Book statistics, with an explicit REASON for anything not computable.

    NO SILENT FALLBACKS. A statistic that cannot be computed from the data on
    hand must not come back as 0, as a bare null the page renders as an em-dash,
    or as an omitted key the page skips over — on a trading dashboard all three
    read as "small" rather than "unknown". Every such field is instead named in
    `unavailable` with the reason it could not be produced, and the page renders
    that reason where the number would have gone.

    Measured 2026-09-04: null_trader's ledger has exactly two NAV rows, so its
    single return has an undefined sample std (ddof=1) and Sharpe has no
    denominator. That used to surface as `ann_vol_pct: null` next to a
    confident-looking `ann_return_pct: -31.24`, which is an annualised figure
    extrapolated from one day. Both are now flagged.
    """
    if nav is None:
        return {"unavailable": {"*": "no nav.csv for this book"}}
    if len(nav) < 2:
        # A single seed row still KNOWS things: what the book is worth, when it
        # started, and that nothing has moved yet. Returning a bare
        # `unavailable: *` made the page print "no data" over a NAV we hold in
        # our hand. Only the statistics that need a RETURN are unavailable, and
        # each is named so the page can say which.
        derived = f"{len(nav)} NAV row(s); a return-based statistic needs >= 2"
        return {
            "n_days": int(len(nav)),
            "nav": round(float(nav.iloc[-1]), 2) if len(nav) else None,
            "pnl": 0.0 if len(nav) else None,
            "ret_pct": 0.0 if len(nav) else None,
            "first_date": str(nav.index[0].date()) if len(nav) else None,
            "last_date": str(nav.index[-1].date()) if len(nav) else None,
            "unavailable": {k: derived for k in
                            ("day_pnl", "day_ret_pct", "ann_return_pct",
                             "ann_vol_pct", "sharpe", "max_dd_pct",
                             "best_day_pct", "worst_day_pct", "hit_rate_pct")},
        }
    r = nav.pct_change().dropna()
    eq = nav / nav.iloc[0]
    dd = (eq / eq.cummax() - 1.0)
    ann = float(r.mean() * 252)
    vol = float(r.std() * np.sqrt(252))
    un = {}
    # One return has no sample dispersion; two have very little. Say so rather
    # than printing a number whose confidence interval covers everything.
    if len(r) < 2 or not math.isfinite(vol):
        un["ann_vol_pct"] = f"{len(r)} daily return(s); sample std needs >= 2"
        un["sharpe"] = un["ann_vol_pct"]
    elif vol <= 0:
        un["sharpe"] = "realised volatility is zero — Sharpe has no denominator"
    if len(r) < 20:
        un["ann_return_pct"] = (f"annualised from {len(r)} session(s) — "
                                f"extrapolation, not a track record")
    out = {
        "nav": round(float(nav.iloc[-1]), 2),
        "pnl": round(float(nav.iloc[-1] - nav.iloc[0]), 2),
        "ret_pct": round(float(eq.iloc[-1] - 1) * 100, 3),
        "day_pnl": round(float(nav.iloc[-1] - nav.iloc[-2]), 2),
        "day_ret_pct": round(float(r.iloc[-1]) * 100, 3),
        "ann_return_pct": round(ann * 100, 2),
        "ann_vol_pct": round(vol * 100, 2) if math.isfinite(vol) else None,
        "sharpe": (round(ann / vol, 2)
                   if (vol > 0 and math.isfinite(vol) and "sharpe" not in un)
                   else None),
        "max_dd_pct": round(float(dd.min()) * 100, 2),
        "best_day_pct": round(float(r.max()) * 100, 2),
        "worst_day_pct": round(float(r.min()) * 100, 2),
        "hit_rate_pct": round(float((r > 0).mean()) * 100, 1),
        "n_days": int(len(nav)),
        "first_date": str(nav.index[0].date()),
        "last_date": str(nav.index[-1].date()),
    }
    if un:
        out["unavailable"] = un
    return out


# ------------------------------------------------------- execution provenance -
def _provenance(sleeve):
    """Which ledger sessions are backed by REAL broker executions, and which are
    simulated.

    THE SINGLE MOST IMPORTANT THING THIS DASHBOARD SAYS.

    `ops/reconcile_orders.py` documents what happened: the account traded on
    2026-07-31 and then sat untouched for 21 business days while TWS was
    misconfigured, but the shadow ledger walked forward through every one of
    those sessions booking modelled trades that were never transmitted —
    including $366k of turnover on 2026-08-04. The ledger's NAV, P&L, Sharpe and
    drawdown are therefore a SIMULATION from the first unconfirmed session
    onward, not a realised track record.

    A monitor that prints "-0.36% since inception" without saying which of those
    words are real is not reporting, it is laundering. So every session is
    classified against `broker_fills.csv`, which is the only file here written
    from broker execution reports rather than from the model:

      broker_confirmed  the broker reported fills on this date
      modelled_only     the ledger booked trades the broker never reported
      no_trades         the ledger moved no shares (marks only)
      funding           the seed row

    If `broker_fills.csv` is absent we return `unknown` for every session rather
    than assuming zero — absence of the evidence file is not evidence of no
    fills, and guessing here would be exactly the fabrication this is meant to
    prevent.
    """
    root = BOOKS.get(sleeve, (None, None))[1]
    if not root:
        return {"ok": False, "reason": f"{sleeve!r} is not a configured book"}
    base = REPO / root / "_ibkr_shadow" / sleeve
    nav_p, tr_p, bf_p = base / "nav.csv", base / "trades.csv", base / "broker_fills.csv"
    if not nav_p.exists():
        return {"ok": False, "reason": f"no nav.csv at {nav_p.relative_to(REPO)}"}
    nav = pd.read_csv(nav_p, parse_dates=["date"]).sort_values("date")
    if nav.empty:
        return {"ok": False, "reason": f"{nav_p.relative_to(REPO)} has no rows"}

    # -- real executions ---------------------------------------------------
    real, real_reason, sources = {}, None, []
    if not bf_p.exists():
        real_reason = (f"{bf_p.relative_to(REPO)} does not exist — execution "
                       f"provenance cannot be established for this book")
    else:
        bf = pd.read_csv(bf_p)
        if bf.empty:
            real_reason = (f"{bf_p.relative_to(REPO)} is empty — no broker "
                           f"execution has ever been recorded for this book")
        elif "fill_date" not in bf.columns:
            real_reason = (f"{bf_p.relative_to(REPO)} has no fill_date column "
                           f"(columns: {list(bf.columns)})")
        else:
            sources = sorted(str(s) for s in bf.get("source", pd.Series(dtype=str))
                             .dropna().unique())
            for d, g in bf.groupby(bf["fill_date"].astype(str)):
                qty = pd.to_numeric(g.get("qty"), errors="coerce")
                px = pd.to_numeric(g.get("price"), errors="coerce")
                real[d] = {
                    "n_fills": int(len(g)),
                    "shares": float(qty.abs().sum(skipna=True)),
                    "notional_usd": float((qty.abs() * px).sum(skipna=True)),
                    "instruments": sorted(set(g.get("instrument", pd.Series(dtype=str))
                                              .dropna().astype(str))),
                }

    # -- modelled trades ---------------------------------------------------
    modelled, mod_reason = {}, None
    if not tr_p.exists():
        mod_reason = f"no trades.csv at {tr_p.relative_to(REPO)}"
    else:
        tr = pd.read_csv(tr_p)
        if "fill_date" not in tr.columns:
            mod_reason = f"{tr_p.relative_to(REPO)} has no fill_date column"
        else:
            for d, g in tr.groupby(tr["fill_date"].astype(str)):
                modelled[d] = {
                    "n_trades": int(len(g)),
                    "notional_usd": float(
                        pd.to_numeric(g.get("notional_usd"), errors="coerce")
                        .abs().sum(skipna=True)),
                }

    unknown = real_reason is not None
    sessions, conf, mod_only, none_, turn_conf, turn_mod = [], 0, 0, 0, 0.0, 0.0
    for row in nav.itertuples():
        d = str(row.date.date())
        traded = float(getattr(row, "traded_usd", 0.0) or 0.0)
        dec = str(getattr(row, "decision", "") or "")
        r, m = real.get(d), modelled.get(d)
        if unknown:
            kind = "unknown"
        elif dec == "funding" and not m:
            kind = "funding"
        elif r:
            kind = "broker_confirmed"; conf += 1; turn_conf += traded
        elif m:
            kind = "modelled_only"; mod_only += 1; turn_mod += traded
        else:
            kind = "no_trades"; none_ += 1
        sessions.append({
            "date": d, "nav": float(row.nav), "decision": dec,
            "traded_usd": traded, "provenance": kind,
            "n_broker_fills": (r or {}).get("n_fills"),
            "broker_notional_usd": (r or {}).get("notional_usd"),
            "n_modelled_trades": (m or {}).get("n_trades"),
        })

    # -- realised vs modelled cost on the sessions we CAN check ------------
    slip, slip_reason = [], None
    sp = base / "slippage.csv"
    if not sp.exists():
        slip_reason = f"no slippage.csv at {sp.relative_to(REPO)}"
    else:
        sdf = pd.read_csv(sp)
        need = {"fill_date", "realised_bp", "modelled_bp", "excess_bp"}
        if not need.issubset(sdf.columns):
            slip_reason = (f"{sp.relative_to(REPO)} missing column(s): "
                           f"{sorted(need - set(sdf.columns))}")
        else:
            for d, g in sdf.groupby(sdf["fill_date"].astype(str)):
                slip.append({
                    "date": d, "n": int(len(g)),
                    "realised_bp": round(float(g.realised_bp.mean()), 1),
                    "modelled_bp": round(float(g.modelled_bp.mean()), 1),
                    "excess_bp": round(float(g.excess_bp.mean()), 1),
                })
            slip.sort(key=lambda x: x["date"])

    traded_sessions = conf + mod_only
    first_unconf = next((s["date"] for s in sessions
                         if s["provenance"] == "modelled_only"), None)
    return {
        "ok": True,
        "sleeve": sleeve, "label": label(sleeve),
        "unknown": unknown, "reason": real_reason,
        "modelled_reason": mod_reason,
        "sources": sources,
        "sessions": sessions,
        "confirmed_dates": sorted(real),
        "n_sessions": len(sessions),
        "n_traded_sessions": traded_sessions,
        "n_confirmed": conf,
        "n_modelled_only": mod_only,
        "n_no_trades": none_,
        "turnover_confirmed_usd": round(turn_conf, 2),
        "turnover_modelled_usd": round(turn_mod, 2),
        "confirmed_share_pct": (round(100.0 * conf / traded_sessions, 1)
                                if traded_sessions else None),
        "first_unconfirmed": first_unconf,
        "nav_is_modelled": (not unknown) and mod_only > 0,
        "slippage": slip, "slippage_reason": slip_reason,
    }


@app.get("/api/provenance")
def api_provenance():
    """READ-ONLY. Execution provenance per book: real broker fills vs simulated."""
    out = {}
    for sleeve in BOOKS:
        try:
            out[sleeve] = _provenance(sleeve)
        except Exception as exc:
            out[sleeve] = {"ok": False, "reason": f"crashed: {exc!r}"}
    return sjson({"books": out, "asof": time.strftime("%Y-%m-%d %H:%M:%S")})


@app.get("/api/pnl")
def api_pnl():
    # `missing` rather than `continue`: a configured book whose ledger cannot be
    # read is a fact the page must show. Dropping it silently leaves the reader
    # looking at a shorter list with no way to tell that anything is absent.
    out = {"books": {}, "series": {}, "missing": {}, "provenance": {}}
    for sleeve, (_, root) in BOOKS.items():
        nm = label(sleeve)
        df = _nav_df(root, sleeve)
        if df is None:
            out["missing"][nm] = (f"no readable nav.csv at "
                                  f"{root}/_ibkr_shadow/{sleeve}/nav.csv")
            continue
        nav = df.set_index("date")["nav"]
        out["books"][nm] = _stats(nav)
        out["series"][nm] = [
            {"d": str(d.date()), "v": round(float(v), 2)} for d, v in nav.items()]
        if sleeve == "cef_discount":
            out["books"][nm]["cost_usd"] = round(float(df["cost_usd"].sum()), 2)
            out["books"][nm]["turnover_usd"] = round(
                float(df["traded_usd"].sum()), 2)
        try:
            p = _provenance(sleeve)
        except Exception as exc:
            p = {"ok": False, "reason": f"crashed: {exc!r}"}
        # Carried on the same payload as the statistics it qualifies, so the page
        # cannot render a NAV without also having the answer to "is this real?".
        out["provenance"][nm] = {
            k: p.get(k) for k in
            ("ok", "reason", "unknown", "nav_is_modelled", "n_sessions",
             "n_traded_sessions", "n_confirmed", "n_modelled_only",
             "confirmed_dates", "confirmed_share_pct", "first_unconfirmed",
             "turnover_confirmed_usd", "turnover_modelled_usd")}
    return sjson(out)


def _relative(strat: pd.Series, bench: pd.Series):
    """Strategy-vs-one-benchmark statistics on their OVERLAPPING sessions.

    A benchmark is not there to be beaten on total return alone -- it is there
    to say how much of the book is just that benchmark. So: beta and
    correlation (how much is exposure), tracking error and information ratio
    (how much is skill per unit of deviation), and up/down capture (whether the
    deviation is symmetric). Every one of them needs paired daily returns, so
    the pair is intersected on DATE, never zipped by position.

    Anything not computable is named in `unavailable` with the reason, per the
    no-silent-fallbacks rule at the top of this file.
    """
    a = strat.pct_change().dropna()
    b = bench.pct_change().dropna()
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    j.columns = ["s", "b"]
    n = len(j)
    if n < 2:
        return {"n_obs": int(n),
                "unavailable": {"*": f"{n} overlapping daily return(s); need >= 2"}}
    ex = j["s"] - j["b"]
    un = {}
    te = float(ex.std() * np.sqrt(252))
    vb = float(j["b"].var())
    beta = float(j[["s", "b"]].cov().iloc[0, 1] / vb) if vb > 0 else None
    if vb <= 0:
        un["beta"] = "the benchmark has zero return variance over the overlap"
        un["corr"] = un["beta"]
    corr = (float(j["s"].corr(j["b"])) if vb > 0 and float(j["s"].var()) > 0
            else None)
    if corr is not None and not math.isfinite(corr):
        corr = None
        un["corr"] = "one of the two series has no variance over the overlap"
    ir = None
    if te > 0 and math.isfinite(te):
        ir = float(ex.mean() * 252 / te)
    else:
        un["info_ratio"] = "tracking error is zero -- no denominator"
    if n < 20:
        un["annualised"] = (f"tracking error and information ratio are "
                            f"annualised from {n} session(s)")
    up = j[j["b"] > 0]
    dn = j[j["b"] < 0]
    cap_up = (float(up["s"].mean() / up["b"].mean())
              if len(up) and up["b"].mean() != 0 else None)
    cap_dn = (float(dn["s"].mean() / dn["b"].mean())
              if len(dn) and dn["b"].mean() != 0 else None)
    if cap_up is None:
        un["capture_up"] = "no session in the overlap where the benchmark rose"
    if cap_dn is None:
        un["capture_down"] = "no session in the overlap where the benchmark fell"
    out = {
        "n_obs": int(n),
        "excess_ret_pct": round(float((1 + j["s"]).prod() - (1 + j["b"]).prod()) * 100, 3),
        "beta": round(beta, 3) if beta is not None and math.isfinite(beta) else None,
        "corr": round(corr, 3) if corr is not None else None,
        "te_pct": round(te * 100, 2) if math.isfinite(te) else None,
        "info_ratio": round(ir, 2) if ir is not None and math.isfinite(ir) else None,
        "capture_up": round(cap_up, 2) if cap_up is not None and math.isfinite(cap_up) else None,
        "capture_down": round(cap_dn, 2) if cap_dn is not None and math.isfinite(cap_dn) else None,
    }
    if un:
        out["unavailable"] = un
    return out


@app.get("/api/benchmarks")
def api_benchmarks():
    """Everything indexed to 100 at a COMMON start — the only honest way to put
    a $500k book and five $20k books on one axis (never a second y-scale)."""
    series, stats = {}, {}
    frames = {}
    # A benchmark that is CONFIGURED but has no usable ledger must be reported,
    # not skipped. Measured 2026-09-06: bench_b4_60_40's nav.csv is header-only
    # (its ledger was truncated on 2026-09-04) even though the book has real
    # broker fills from 2026-08-31. The old code hit `continue` and the 60/40
    # line simply was not on the chart — no gap, no note, nothing. The most
    # recognisable benchmark on the page vanished and the chart still looked
    # complete, which is the worst kind of missing data: invisible.
    missing = {}
    cef = _nav_df(BOOKS["cef_discount"][1], "cef_discount")
    if cef is not None:
        frames[label("cef_discount")] = cef.set_index("date")["nav"]
    else:
        missing[label("cef_discount")] = "no readable nav.csv for the strategy book"
    # `name`, not `label` — a loop variable called `label` shadows the module
    # level label() helper and makes the whole endpoint 500 with an
    # UnboundLocalError that points nowhere near the loop.
    for sl, name in BENCH_LABEL.items():
        p = BENCH_ROOT / sl / "nav.csv"
        if not p.exists():
            missing[name] = f"no nav.csv at {p.relative_to(REPO)}"
            continue
        try:
            df = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
        except Exception as exc:
            missing[name] = f"nav.csv unreadable: {exc!r}"
            continue
        if df.empty:
            missing[name] = (f"{p.relative_to(REPO)} has a header but no rows — "
                             f"this book's ledger is empty")
            continue
        if len(df) < 2:
            missing[name] = (f"{p.relative_to(REPO)} has only {len(df)} NAV row — "
                             f"an indexed series needs >= 2")
            continue
        frames[name] = df.set_index("date")["nav"]
    if not frames:
        return sjson({"series": {}, "stats": {}, "missing": missing,
                      "common_start": None,
                      "error": "no book has a usable NAV series"})
    start = max(s.index.min() for s in frames.values())
    clipped = {}
    for name, s in frames.items():
        s = s[s.index >= start]
        if s.empty:
            missing[name] = (f"no NAV rows on or after the common start "
                             f"{pd.Timestamp(start).date()}")
            continue
        idx = 100.0 * s / s.iloc[0]
        series[name] = [{"d": str(d.date()), "v": round(float(v), 3)}
                        for d, v in idx.items()]
        stats[name] = _stats(s)
        clipped[name] = s
    # Relative statistics are computed against the STRATEGY, so they exist only
    # if the strategy itself has a series. Saying that once beats repeating
    # "no strategy" on every benchmark row.
    me = label("cef_discount")
    rel = {}
    if me in clipped:
        for name, sr in clipped.items():
            if name == me:
                continue
            rel[name] = _relative(clipped[me], sr)
    return sjson({"series": series, "stats": stats, "missing": missing,
                    "relative": rel, "strategy": me,
                    "common_start": str(pd.Timestamp(start).date())})


def _nav_panel_last():
    from src.deploy.sleeves.cef_discount import NAV_PATH
    return pd.read_parquet(NAV_PATH, columns=["date"])["date"].max().normalize()


def _nav_deadline() -> str:
    """NAV_DEADLINE from ops/schedule/cef.env, the value launch_job.py reads."""
    try:
        for line in (REPO / "ops/schedule/cef.env").read_text().splitlines():
            if line.strip().startswith("NAV_DEADLINE="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "21:30"


# --------------------------------------------------------------- live ------
def _portfolio():
    """Live marks straight from the broker: position, cost, last, unrealised.

    This is the layer that makes the page a monitor rather than a report.
    Everything else here is the shadow ledger's END OF DAY state — correct, but
    yesterday's. `ib.portfolio()` carries marketPrice / marketValue /
    unrealizedPNL per position and needs no separate market-data subscription,
    so intraday P&L costs one round trip rather than a quote stream.
    """
    import ib_async as ibapi
    from src.deploy.broker.ibkr import IBKRConfig
    cfg = IBKRConfig.from_env()
    app = ibapi.IB()
    # Held for the whole session, not just the connect: the id is only free
    # once disconnect() has run. Without this, /api/live and /api/verify can
    # each be inside their own cache lock and still collide on client 302.
    _broker_lock.acquire()
    try:
        app.connect(cfg.host, int(cfg.port), clientId=302, readonly=True, timeout=10)
    except Exception as exc:
        # The gateway restarts daily and drops briefly on its own. A monitor
        # that 500s on a transient blip trains you to ignore it, so this
        # degrades to a flagged empty state the page can render.
        return {"ok": False, "error": repr(exc)}
    try:
        pos = [{"ticker": i.contract.symbol,
                "qty": float(i.position),
                "avg_cost": float(i.averageCost or 0.0),
                "last": float(i.marketPrice or 0.0),
                "value": float(i.marketValue or 0.0),
                "unrealized": float(i.unrealizedPNL or 0.0)}
               for i in app.portfolio() if float(i.position) != 0.0]
        acct = {r.tag: r.value for r in app.accountSummary()}
        return {"ok": True, "positions": pos, "account": acct}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}
    finally:
        try:
            app.disconnect()
        except Exception:
            pass
        _broker_lock.release()


def _owner_map():
    """({ticker: [sleeve,...]}, problems) from every book's ledger.

    `problems` exists because the old version swallowed a failed book with
    `except: continue`. A book whose ledger will not load contributes no
    ownership, so every ticker it owns silently falls through to the
    "Not assigned to a book" bucket — a confident, wrong label that looks
    exactly like a correctly-attributed answer. Now the failure travels with
    the result and the page shows it.
    """
    from ops.reconcile_orders import ALL_BOOKS, _sleeves, ledger_positions
    own, problems = {}, {}
    for bpath, broot in ALL_BOOKS:
        bp, br = REPO / bpath, REPO / broot
        if not bp.exists():
            problems[bpath] = "book spec not found"
            continue
        try:
            for sl in _sleeves(bp):
                for t in ledger_positions(br, sl):
                    own.setdefault(t, []).append(sl)
        except Exception as exc:
            problems[bpath] = repr(exc)
    return own, problems


def _ledger_all():
    """{ticker: shares} summed across EVERY book's shadow ledger.

    Summed, because all three books share one IBKR account and the broker
    reports only the net. Comparing one book's ledger against the account net
    would flag every ticker another book also holds.

    Returns (positions, problems) — `problems` names any book that could not be
    read, so a book silently missing from the sum cannot masquerade as a book
    that holds nothing.
    """
    from ops.reconcile_orders import ALL_BOOKS, _sleeves, ledger_positions
    own, problems = {}, {}
    for bpath, broot in ALL_BOOKS:
        bp, br = REPO / bpath, REPO / broot
        if not bp.exists():
            problems[bpath] = "book spec not found"
            continue
        try:
            for sl in _sleeves(bp):
                for t, q in ledger_positions(br, sl).items():
                    own[t] = own.get(t, 0.0) + float(q)
        except Exception as exc:
            problems[bpath] = repr(exc)
    return own, problems


def _reconcile(broker_pos, marks):
    """Shadow ledger vs the broker's actual book, per ticker.

    This is the comparison `ops/reconcile_orders.py` exists because nobody was
    making: every other guard compares the account to the TAG BOOK, which
    `arm()` overwrites from `ib.positions()` at the start of each session — so
    the account was being compared to itself and always agreed. The LEDGER, the
    thing this dashboard reports P&L from, was never in the comparison.

    It matters here because the signal blotter's "held now" column is the
    LEDGER's position. If the ledger and the account disagree, then the
    blotter's implied trade list is arithmetic against a book that does not
    exist, and it must not be read as an order ticket.
    """
    led, problems = _ledger_all()
    rows = []
    for t in sorted(set(led) | set(broker_pos)):
        l = float(led.get(t, 0.0))
        b = float(broker_pos.get(t, 0.0))
        d = b - l
        if abs(d) < 0.5:
            continue
        scale = max(abs(l), abs(b), 1.0)
        px = marks.get(t)
        rows.append({
            "ticker": t, "ledger": l, "broker": b, "drift": d,
            "drift_pct": round(100.0 * d / scale, 1),
            # Rounding/partial-fill noise vs a genuine divergence. Both are
            # returned; the flag only decides emphasis, it never hides a row.
            "material": bool(abs(d) >= 2 and abs(d) / scale >= 0.01),
            "drift_usd": (round(abs(d) * px, 0) if px else None),
            "in_ledger_only": t not in broker_pos,
            "in_broker_only": t not in led,
        })
    rows.sort(key=lambda r: -(r["drift_usd"] or 0))
    mat = [r for r in rows if r["material"]]
    return {
        "ok": True,
        "rows": rows,
        "n_checked": len(set(led) | set(broker_pos)),
        "n_drift": len(rows),
        "n_material": len(mat),
        "abs_drift_shares": round(sum(abs(r["drift"]) for r in rows), 0),
        "material_drift_usd": (round(sum(r["drift_usd"] or 0 for r in mat), 0)
                               if mat else 0.0),
        "agrees": not mat,
        "problems": problems,
    }


@app.get("/api/live")
def api_live():
    d = cached("live", LIVE_TTL, _portfolio)
    if not d.get("ok"):
        return sjson({"ok": False, "error": d.get("error", "broker unreachable")})
    own, own_problems = _owner_map()
    a = d["account"]

    def num(k):
        try:
            return float(a.get(k))
        except (TypeError, ValueError):
            return None

    rows, by_sleeve = [], {}
    for p in d["positions"]:
        who = own.get(p["ticker"], [])
        # A ticker two books both hold cannot be assigned to one of them from
        # the account net alone; say so rather than pick.
        key = who[0] if len(who) == 1 else ("shared" if who else "unattributed")
        rows.append({**p, "sleeve": label(key), "owners": who})
        agg = by_sleeve.setdefault(label(key), {"gross": 0.0, "net": 0.0,
                                           "unrealized": 0.0, "n": 0})
        agg["gross"] += abs(p["value"])
        agg["net"] += p["value"]
        agg["unrealized"] += p["unrealized"]
        agg["n"] += 1
    rows.sort(key=lambda r: -abs(r["value"]))
    try:
        rec = _reconcile({p["ticker"]: p["qty"] for p in d["positions"]},
                         {p["ticker"]: p["last"] for p in d["positions"]})
    except Exception as exc:
        # Never a bare pass: a reconciliation that did not run is reported as
        # "did not run", which is a different thing from "found no drift".
        rec = {"ok": False, "reason": f"reconciliation failed: {exc!r}"}
    return sjson({
        "ok": True,
        "ts": time.strftime("%H:%M:%S"),
        "epoch": time.time(),
        "positions": rows,
        "by_sleeve": by_sleeve,
        "reconcile": rec,
        # A book whose ledger would not load cannot attribute its tickers; the
        # page must say so rather than let them read as genuinely unattributed.
        "attribution_problems": own_problems,
        "account": {
            "nlv": num("NetLiquidation"),
            "gross": num("GrossPositionValue"),
            "cash": num("TotalCashValue"),
            "excess_liquidity": num("ExcessLiquidity"),
            "cushion": num("Cushion"),
            "maint_margin": num("MaintMarginReq"),
            "available": num("AvailableFunds"),
        },
        "totals": {
            "unrealized": sum(r["unrealized"] for r in rows),
            "gross": sum(abs(r["value"]) for r in rows),
            "net": sum(r["value"] for r in rows),
            "n": len(rows),
        },
    })


# ------------------------------------------------------------- verify -------
# --------------------------------------------------------------- factors ----
# WHY THIS PANEL EXISTS
# ---------------------
# The single most important risk fact about this book is not on any other card:
# it is dollar-neutral, which kills market direction, and then puts roughly
# two-thirds of what remains into ONE unmanaged spread bet -- municipal CEFs
# against everything else. Effective breadth is about 2.2 of 17 names, so
# IR ~ IC*sqrt(BR) computed on the name count overstates by ~2.75x.
#
# Lee, Shleifer & Thaler (1991) predicts exactly this: CEF discounts share a
# large common component. PC2 here is a credit-CEF instance of it.
#
# A PM sizing this book needs to see that number, and it is not derivable from
# the positions table by eye. Nothing here is a trading rule -- it is a mirror.

MUNI_GRP = "muni"


def _grp_map():
    """ticker -> asset group (muni / multi / hy / loan) from the staged universe."""
    p = REPO / "data/cef/cef_universe.csv"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; cannot classify muni vs taxable")
    u = pd.read_csv(p)
    return {r.ticker: str(r.grp) for r in u.itertuples()}


def _weights_from_shares(shares, marks, nav):
    """Signed portfolio weights. Requires a mark for every held name."""
    if nav is None or not np.isfinite(nav) or nav <= 0:
        raise ValueError("sleeve NAV unknown or non-positive")
    w, missing = {}, []
    for t, q in shares.items():
        px = marks.get(t)
        if px is None or not np.isfinite(px) or px <= 0:
            missing.append(t)
            continue
        w[t] = float(q) * float(px) / float(nav)
    if missing:
        raise ValueError("no mark for " + ", ".join(sorted(missing)))
    return w


def _decompose(weights, window=252):
    """Eigen-decompose book variance on the CURRENT weights.

    Returns variance share per principal component, effective breadth, and a
    reading of what each of the top components economically IS, from its
    loadings. Raises rather than guessing when the covariance is not estimable
    -- a breadth number computed off a short or ragged window is worse than no
    breadth number, because it looks the same.
    """
    from src.deploy.sleeves.cef_discount import PX_PATH
    names = [t for t, x in weights.items() if abs(x) > 1e-9]
    if len(names) < 3:
        raise ValueError(f"only {len(names)} non-zero position(s); need >= 3")

    px = pd.read_parquet(PX_PATH)
    px = px[px.ticker.isin(names)]
    px["date"] = pd.to_datetime(px["date"])
    piv = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    have = [t for t in names if t in piv.columns]
    if len(have) < len(names):
        raise ValueError("no price history for " + ", ".join(sorted(set(names) - set(have))))

    ret = piv[have].pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    hist = ret.tail(window).dropna()
    if len(hist) < 120:
        raise ValueError(f"{len(hist)} clean joint returns in the last {window} "
                         f"sessions; need >= 120")

    from sklearn.covariance import LedoitWolf
    lw = LedoitWolf().fit(hist.values)
    S = lw.covariance_
    w = np.array([weights[t] for t in have], float)

    ev, V = np.linalg.eigh(S)
    order = np.argsort(ev)[::-1]
    ev, V = np.clip(ev[order], 1e-18, None), V[:, order]
    c = V.T @ w
    var = (c ** 2) * ev
    tot = float(var.sum())
    if tot <= 0:
        raise ValueError("book variance is zero; weights may all be zero")
    share = var / tot
    br = float(1.0 / np.sum(share ** 2))

    grp = _grp_map()
    comps = []
    for k in range(min(4, len(have))):
        load = {t: float(V[i, k]) for i, t in enumerate(have)}
        muni = [v for t, v in load.items() if grp.get(t) == MUNI_GRP]
        other = [v for t, v in load.items() if grp.get(t) != MUNI_GRP]
        # A component is a "muni vs taxable" spread when the two groups sit on
        # opposite sides of zero with a clear gap between them.
        #
        # Deliberately NOT a unanimity test. The first version required every
        # taxable loading to be strictly negative, and a single near-zero name
        # (AWF at +0.009) was enough to reject a component that was 92.5% of
        # book variance with group means of +0.318 and -0.150. A classifier
        # that silently downgrades the dominant risk factor to "residual"
        # because of a rounding-scale loading is worse than none.
        mm = float(np.mean(muni)) if muni else 0.0
        om = float(np.mean(other)) if other else 0.0
        spread = (len(muni) >= 2 and len(other) >= 2
                  and mm * om < 0                       # opposite sides
                  and abs(mm - om) >= 0.15              # and clearly apart
                  # majority of each group on its own side of zero
                  and sum(1 for v in muni if v * mm > 0) >= 0.8 * len(muni)
                  and sum(1 for v in other if v * om > 0) >= 0.8 * len(other))
        same = all(v > 0 for v in load.values()) or all(v < 0 for v in load.values())
        comps.append({
            "pc": k + 1,
            "variance_share": round(100 * float(share[k]), 1),
            # Short enough to survive a narrow card. The evidence behind the
            # label travels in `loadings`, which the page hangs off the row.
            "reading": ("market direction" if same else
                        "muni vs taxable" if spread else
                        "mixed / residual"),
            "muni_mean_loading": round(float(np.mean(muni)), 3) if muni else None,
            "other_mean_loading": round(float(np.mean(other)), 3) if other else None,
            # A LIST of pairs, not a dict. Flask sorts JSON object keys
            # alphabetically, which silently destroyed this ordering: the panel
            # showed AWF/BIT/DSL/HYT (all near zero) under a heading that said
            # "largest loadings", hiding NAD/NEA/NVG/NZF -- the muni block that
            # IS the factor. Order is data here, so it travels as a sequence.
            "loadings": [[t, round(v, 3)] for t, v in
                         sorted(load.items(), key=lambda kv: -abs(kv[1]))],
        })

    muni_w = sum(v for t, v in weights.items() if grp.get(t) == MUNI_GRP)
    return {
        "ok": True,
        "n_names": len(have),
        "n_long": int(sum(1 for v in w if v > 0)),
        "n_short": int(sum(1 for v in w if v < 0)),
        "br_eff": round(br, 2),
        "br_overstatement": round(float(np.sqrt(len(have) / br)), 2),
        "components": comps,
        "tail_share": round(100 * float(share[4:].sum()), 1) if len(share) > 4 else 0.0,
        "net_muni_weight": round(muni_w, 4),
        "gross": round(float(np.abs(w).sum()), 4),
        "net": round(float(w.sum()), 4),
        "window": int(len(hist)),
    }


def _br_history(sleeve="cef_discount", sessions=40, window=252):
    """BR_eff per session from the shadow ledger's own daily weights.

    LEDGER-DERIVED, and the caller must say so: most sessions in this book book
    modelled fills (see /api/provenance), so this is the breadth of the book the
    ledger believes it held, not necessarily the one the account held.
    """
    root = BOOKS.get(sleeve, (None, None))[1]
    if root is None:
        raise KeyError(f"unknown sleeve {sleeve!r}")
    p = REPO / root / "_ibkr_shadow" / sleeve / "positions.csv"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing")
    df = pd.read_csv(p)
    df = df[(df.ticker != "CASH") & df.weight.notna()]
    if df.empty:
        raise ValueError("no weighted positions in the ledger")
    df["date"] = pd.to_datetime(df["date"])
    out = []
    for d in sorted(df["date"].unique())[-sessions:]:
        rows = df[df["date"] == d]
        w = {r.ticker: float(r.weight) for r in rows.itertuples()}
        try:
            dec = _decompose(w, window)
        except Exception as exc:
            out.append({"date": str(pd.Timestamp(d).date()), "br_eff": None,
                        "reason": str(exc)})
            continue
        pc2 = next((c for c in dec["components"]
                    if c["reading"] == "muni vs taxable spread"), None)
        out.append({"date": str(pd.Timestamp(d).date()),
                    "br_eff": dec["br_eff"],
                    "spread_share": pc2["variance_share"] if pc2 else 0.0})
    return out


@app.get("/api/factors")
def api_factors():
    """READ-ONLY. Risk decomposition of the CEF book: what the risk really is."""
    def run():
        res = {"asof": time.strftime("%Y-%m-%d %H:%M:%S")}
        marks, nav = {}, None
        try:
            from src.deploy.sleeves.cef_discount import PX_PATH
            px = pd.read_parquet(PX_PATH)
            px["date"] = pd.to_datetime(px["date"])
            piv = px.pivot_table(index="date", columns="ticker",
                                 values="close").sort_index().ffill()
            marks = {t: float(piv[t].iloc[-1]) for t in piv.columns}
            res["marks_asof"] = str(piv.index[-1].date())
        except Exception as exc:
            res["current"] = {"ok": False, "reason": f"price panel unreadable: {exc}"}
            return res
        nav = _nav_last("cef_discount")

        # LIVE book: what the broker says we hold right now.
        # `positions` from _portfolio is a LIST spanning the WHOLE account --
        # three books share it -- so restrict to this sleeve's frozen universe.
        # Those 17 tickers are traded by the CEF book alone; if that ever stops
        # being true the /api/live reconciliation flags it as held by more than
        # one book, and this panel would need real attribution rather than a
        # name filter.
        try:
            spec = json.loads(
                (REPO / "ops/specs/cef_discount.frozen.json").read_text())
            uni = set(spec["frozen"]["universe"])
        except Exception as exc:
            res["current"] = {"ok": False, "reason": f"frozen spec unreadable: {exc}"}
            return res
        shares = {}
        # SAME key as /api/live on purpose: identical call, identical client
        # id. Two keys meant two concurrent sessions as 302 (see cached()).
        pos = cached("live", LIVE_TTL, _portfolio)
        if pos.get("ok"):
            for row in pos.get("positions") or []:
                t = row.get("ticker")
                if t in uni and t in marks and float(row.get("qty") or 0.0):
                    shares[t] = float(row["qty"])
            res["source"] = "broker positions"
        if not shares:
            shares = {t: q for t, q in _held("cef_discount").items() if t in uni}
            res["source"] = ("shadow ledger — broker positions unavailable: "
                             + str(pos.get("error", "no CEF names reported")))
        try:
            res["current"] = _decompose(_weights_from_shares(shares, marks, nav))
        except Exception as exc:
            res["current"] = {"ok": False, "reason": str(exc)}

        try:
            res["history"] = _br_history()
            res["history_note"] = ("ledger-derived weights; most sessions book "
                                   "modelled fills -- see /api/provenance")
        except Exception as exc:
            res["history"] = []
            res["history_reason"] = str(exc)
        return res

    return sjson(cached("factors", 90, run))


@app.get("/api/verify")
def api_verify():
    """Would tonight's trades be right? Two independent questions.

    1. OPERATIONAL — will the session run at all (ops/preflight + ops/doctor).
    2. MATHEMATICAL — does the signal obey the properties the strategy claims:
       dollar-neutral, gross at target, vol scaling in bounds, min-weight
       respected, cheap->long / rich->short, and — the real check — does the
       DEPLOYED sleeve agree with an independent re-derivation of the maths.
    """
    checks = []

    def add(name, ok, detail, kind="math"):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "kind": kind})

    # -- operational -------------------------------------------------------
    try:
        from ops import preflight as pf
        v = pf.run("cef", str(REPO / "ops/books/cef_discount_book.json"),
                   str(pd.Timestamp.today().date()), want_live=True)
        for line in v.get("checks", []):
            ok = "[PASS]" in line
            add(line.split("]", 1)[-1].split(":")[0].strip() or "preflight",
                ok, line.strip(), "ops")
        add("arm", v.get("arm"), f"preflight verdict arm={v.get('arm')}", "ops")
    except Exception as exc:
        add("preflight", False, f"crashed: {exc!r}", "ops")

    # -- mathematical ------------------------------------------------------
    try:
        f = _signal_frame()
        w = f["w"]
        net, gross = float(w.sum()), float(w.abs().sum())
        add("dollar-neutral", abs(net) < 1e-6,
            f"sum(w) = {net:+.2e} (must be ~0: this book carries no credit beta "
            f"by construction)")
        tgt_gross = f["volscal"] * f["gross_leverage"]
        add("gross at target", abs(gross - tgt_gross) < 1e-6,
            f"sum|w| = {gross:.4f} vs volscal x leverage = {tgt_gross:.4f}")
        add("vol scaling in bounds", 0.2 <= f["volscal"] <= 2.5,
            f"volscal = {f['volscal']:.3f} (clip 0.2-2.5); realised vol "
            f"{f['realised_vol']:.2%} vs target {f['vol_target']:.2%}")
        small = w[w.abs() < f["min_abs_weight"]]
        add("min weight respected", small.empty,
            f"{len(small)} name(s) below {f['min_abs_weight']:.3f}"
            + (f": {list(small.index)}" if len(small) else ""))
        zz, ww = f["z"], w
        common = [t for t in ww.index if t in zz.index]
        sign_ok = all((ww[t] > 0) == (zz[t] < zz[common].mean()) for t in common)
        add("cheap->long, rich->short", sign_ok,
            f"every long has below-average z, every short above, across "
            f"{len(common)} name(s)")
        add("z bounded", bool(zz.abs().max() <= 4.0 + 1e-9),
            f"max |z| = {zz.abs().max():.2f} (clipped at 4)")

        # the one that matters: deployed sleeve vs independent re-derivation
        try:
            from src.deploy.sleeves.cef_discount import CEFDiscountSleeve as C
            from src.deploy.sleeve import MarketState
            spec = json.loads((REPO / "ops/specs/cef_discount.frozen.json").read_text())
            nav_ref = float(spec["capital_usd"])
            sl = C(spec, nav_ref)
            # Compare LIKE WITH LIKE. The sleeve runs a no-trade band (frozen
            # `band_width`, live 2026-09-06), so it must be handed a NAV and a
            # holdings map or it correctly refuses for want of a denominator --
            # which is what made this check fail with market_state=None: the
            # sleeve returned all-FLAT and every "disagreement" was just the
            # frictionless weight itself. Both sides are evaluated FROM FLAT,
            # so the band's effect is present on both and the comparison still
            # tests the deployed maths rather than the policy.
            ms = MarketState(asof=f["asof"], prices=pd.DataFrame(), holdings={},
                             extras={"sleeve_nav": nav_ref})
            tgts = sl.target_positions(f["asof"], ms)
            dep = {t.instrument: float(t.weight or 0.0) for t in tgts}
            bw = spec["frozen"].get("band_width")
            ref = dict(w)
            if bw:                       # independent re-implementation of the band
                bw = float(bw)
                minw = float(spec["frozen"].get("min_abs_weight", 0.005))
                ref = {t: (0.0 if abs(v) <= bw else v - math.copysign(bw, v))
                       for t, v in ref.items()}
                ref = {t: (0.0 if abs(v) < minw else v) for t, v in ref.items()}
            diffs = {t: round(abs(dep.get(t, 0.0) - float(ref.get(t, 0.0))), 6)
                     for t in set(dep) | set(ref)}
            worst = max(diffs.values()) if diffs else 0.0
            bad = sorted((v, k) for k, v in diffs.items() if v > 1e-6)
            add("deployed sleeve == independent re-derivation", not bad,
                f"max |Δweight| = {worst:.2e} across {len(diffs)} name(s)"
                + (f"; worst: {', '.join(k for _, k in bad[-3:])}" if bad else ""))
        except Exception as exc:
            add("deployed sleeve == independent re-derivation", False,
                f"could not compare: {exc!r}")
    except Exception as exc:
        add("signal", False, f"crashed: {exc!r}")

    return sjson({"checks": checks,
                    "ok": all(c["ok"] for c in checks),
                    "n_fail": sum(1 for c in checks if not c["ok"])})


@app.get("/api/doctor")
def api_doctor():
    def run():
        try:
            from ops import doctor as doc
            r = doc.Report()
            for fn, a in ((doc.check_entrypoint, ()), (doc.check_plists, ()),
                          (doc.check_launchd, ()), (doc.check_env_paths, ()),
                          (doc.check_ibc, ()), (doc.check_sleep, ()),
                          (doc.check_heartbeats, ()), (doc.check_alerts, ())):
                try:
                    fn(r, *a)
                except Exception as exc:
                    r.add(doc.WARN, fn.__name__, repr(exc))
            return [{"level": l, "name": n, "msg": m} for l, n, m, _ in r.rows]
        except Exception as exc:
            return [{"level": "WARN", "name": "doctor", "msg": repr(exc)}]
    return sjson({"rows": cached("doctor", 30, run)})


@app.get("/api/sessions")
def api_sessions():
    """READ-ONLY. Did each eligible session ARM, and if not which blocker fired.

    This is the panel the 2026-08 outage needed and did not have: twenty-one
    sessions logged `ok`, wrote a heartbeat and advanced a ledger while
    transmitting nothing, because nothing was listening on the configured broker
    port. Every other panel on this page reads calm in that state — NAV moves,
    positions are there, the signal computes — because all of them read the
    shadow ledger, which does not know whether an order was ever sent.

    The measurement is `ops.session_uptime`, the same module the CLI prints, so
    the screen and the command can never disagree. It reads the UNION of this
    tree's `ops/schedule/logs` and `~/prod/QUANTT`'s: the logs bifurcated on
    2026-09-10 when prod took over the scheduler, and a tally from one tree
    undercounts by one more every session.

    Returns `ok: false` with a reason rather than raising. A 500 here takes the
    whole tab down, and the tab that goes down is the one that would have told
    the operator the book is not trading.
    """
    def run():
        try:
            from ops import session_uptime as su
            return su.measure()
        except Exception as exc:
            return {"ok": False, "complete": False,
                    "reason": f"session_uptime crashed: {exc!r}"}
    # 120s: session logs advance once a day. The only reason to poll at all is so
    # the panel notices tonight's session without a page reload.
    return sjson(cached("sessions", 120, run))


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    print("QUANTT dashboard — http://127.0.0.1:8787   (read-only; places no orders)")
    app.run(host="127.0.0.1", port=8787, debug=False)
