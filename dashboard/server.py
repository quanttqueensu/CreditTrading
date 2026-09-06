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
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
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
BENCH_LABEL = {
    "bench_b1_hyg": "B1 HYG",
    "bench_b3_agg": "B3 AGG",
    "bench_b4_60_40": "B4 60/40",
    "bench_b5_shy": "B5 SHY",
    "bench_b6_ew_credit": "B6 EW credit",
}

_cache: dict = {}


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
    """Broker probes are slow and the page polls; never hit TWS per widget."""
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
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
    try:
        out = subprocess.run(["ps", "axo", "pid=,command="], capture_output=True,
                             text=True, timeout=10).stdout
        me = str(subprocess.os.getpid())
        for line in out.splitlines():
            pid, _, cmd = line.strip().partition(" ")
            if pid == me:
                continue
            if any(t in cmd.lower() for t in
                   ("ibcstart", "gatewaystart", "ibcontroller", "ibc.jar")):
                return True
    except Exception:
        pass
    return False


@app.get("/api/status")
def api_status():
    b = cached("broker", 20, _probe_broker)
    acct = {}
    if b.get("ok"):
        acct = {"account": (b.get("accounts") or [None])[0],
                "nlv": b.get("nlv"), "positions": len(b.get("positions") or {})}
    return sjson({
        "connected": bool(b.get("ok")),
        "error": b.get("error"),
        "endpoint": f"{b.get('host', '?')}:{b.get('port', '?')}",
        "ibc": _ibc_running(),
        **acct,
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

    rebal = int(fz.get("rebalance_days", 1))
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
    nav_now = _nav_last("cef_discount") or 500000.0
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
    if nav is None or len(nav) < 2:
        return {}
    r = nav.pct_change().dropna()
    eq = nav / nav.iloc[0]
    dd = (eq / eq.cummax() - 1.0)
    ann = float(r.mean() * 252)
    vol = float(r.std() * np.sqrt(252))
    return {
        "nav": round(float(nav.iloc[-1]), 2),
        "pnl": round(float(nav.iloc[-1] - nav.iloc[0]), 2),
        "ret_pct": round(float(eq.iloc[-1] - 1) * 100, 3),
        "day_pnl": round(float(nav.iloc[-1] - nav.iloc[-2]), 2),
        "day_ret_pct": round(float(r.iloc[-1]) * 100, 3),
        "ann_return_pct": round(ann * 100, 2),
        "ann_vol_pct": round(vol * 100, 2),
        "sharpe": round(ann / vol, 2) if vol > 0 else None,
        "max_dd_pct": round(float(dd.min()) * 100, 2),
        "best_day_pct": round(float(r.max()) * 100, 2),
        "worst_day_pct": round(float(r.min()) * 100, 2),
        "hit_rate_pct": round(float((r > 0).mean()) * 100, 1),
        "n_days": int(len(nav)),
    }


@app.get("/api/pnl")
def api_pnl():
    out = {"books": {}, "series": {}}
    for sleeve, (_, root) in BOOKS.items():
        df = _nav_df(root, sleeve)
        if df is None:
            continue
        nav = df.set_index("date")["nav"]
        out["books"][sleeve] = _stats(nav)
        out["series"][sleeve] = [
            {"d": str(d.date()), "v": round(float(v), 2)} for d, v in nav.items()]
        if sleeve == "cef_discount":
            out["books"][sleeve]["cost_usd"] = round(float(df["cost_usd"].sum()), 2)
            out["books"][sleeve]["turnover_usd"] = round(float(df["traded_usd"].sum()), 2)
    return sjson(out)


@app.get("/api/benchmarks")
def api_benchmarks():
    """Everything indexed to 100 at a COMMON start — the only honest way to put
    a $500k book and five $20k books on one axis (never a second y-scale)."""
    series, stats = {}, {}
    frames = {}
    cef = _nav_df(BOOKS["cef_discount"][1], "cef_discount")
    if cef is not None:
        frames["cef_discount"] = cef.set_index("date")["nav"]
    for sl, label in BENCH_LABEL.items():
        p = BENCH_ROOT / sl / "nav.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
        if df.empty or len(df) < 2:
            continue
        frames[label] = df.set_index("date")["nav"]
    if not frames:
        return sjson({"series": {}, "stats": {}})
    start = max(s.index.min() for s in frames.values())
    for name, s in frames.items():
        s = s[s.index >= start]
        if s.empty:
            continue
        idx = 100.0 * s / s.iloc[0]
        series[name] = [{"d": str(d.date()), "v": round(float(v), 3)}
                        for d, v in idx.items()]
        stats[name] = _stats(s)
    return sjson({"series": series, "stats": stats,
                    "common_start": str(pd.Timestamp(start).date())})


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


def _owner_map():
    """{ticker: [sleeve,...]} from every book's ledger + attribution seed."""
    from ops.reconcile_orders import ALL_BOOKS, _sleeves, ledger_positions
    own = {}
    for bpath, broot in ALL_BOOKS:
        bp, br = REPO / bpath, REPO / broot
        if not bp.exists():
            continue
        try:
            for sl in _sleeves(bp):
                for t in ledger_positions(br, sl):
                    own.setdefault(t, []).append(sl)
        except Exception:
            continue
    return own


@app.get("/api/live")
def api_live():
    d = cached("live", 4, _portfolio)
    if not d.get("ok"):
        return sjson({"ok": False, "error": d.get("error", "broker unreachable")})
    own = _owner_map()
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
        label = who[0] if len(who) == 1 else ("shared" if who else "unattributed")
        rows.append({**p, "sleeve": label, "owners": who})
        agg = by_sleeve.setdefault(label, {"gross": 0.0, "net": 0.0,
                                           "unrealized": 0.0, "n": 0})
        agg["gross"] += abs(p["value"])
        agg["net"] += p["value"]
        agg["unrealized"] += p["unrealized"]
        agg["n"] += 1
    rows.sort(key=lambda r: -abs(r["value"]))
    return sjson({
        "ok": True,
        "ts": time.strftime("%H:%M:%S"),
        "positions": rows,
        "by_sleeve": by_sleeve,
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
            spec = json.loads((REPO / "ops/specs/cef_discount.frozen.json").read_text())
            sl = C(spec, float(spec["capital_usd"]))
            tgts = sl.target_positions(f["asof"], None)
            dep = {t.instrument: float(t.weight or 0.0) for t in tgts}
            diffs = {t: round(abs(dep.get(t, 0.0) - float(w.get(t, 0.0))), 6)
                     for t in set(dep) | set(w.index)}
            worst = max(diffs.values()) if diffs else 0.0
            bad = {k: v for k, v in diffs.items() if v > 1e-6}
            add("deployed sleeve == independent re-derivation", not bad,
                f"max |Δweight| = {worst:.2e} across {len(diffs)} name(s)"
                + (f"; disagreements: {bad}" if bad else ""))
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


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    print("QUANTT dashboard — http://127.0.0.1:8787   (read-only; places no orders)")
    app.run(host="127.0.0.1", port=8787, debug=False)
