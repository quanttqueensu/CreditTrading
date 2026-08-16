"""The gate every scheduled session passes through before it is allowed to trade.

DESIGN RULE: A FAILED CHECK DOWNGRADES THE SESSION, IT DOES NOT CANCEL IT
-------------------------------------------------------------------------
There are two different things a scheduled run does, and they have opposite
failure preferences:

  * TRADING is dangerous when the state is wrong. It should fail closed.
  * DATA COLLECTION is only lost if it does not happen. Today's closing prices,
    NAVs and holdings are not re-fetchable later — the issuers publish no
    archive — so a day skipped is a day gone permanently.

The old scheduler conflated them: any fault aborted the whole job, so a broker
problem also cost us the day's data. This module separates the decision. A
failing check clears `arm` (no orders) while leaving `collect` true, so a halted
book keeps accumulating the record it will need to be trusted later.

WHAT IT CHECKS, AND WHICH 2026-07-31 FAILURE EACH ONE WOULD HAVE CAUGHT
-----------------------------------------------------------------------
  halt          an active ops/HALT.md          — the desync, on the NEXT session
  costs         every deployed ticker priced   — the NVG/USHY KeyError itself
  cost_drift    yaml vs the tick-floor model   — (new) silent staleness
  data          price/NAV freshness            — trading a blind signal
  broker        TWS actually reachable         — a run that thinks it traded
  heartbeat     did the last session fire      — the 09:35 exit-126 silence

Run it standalone to see the state without trading anything:

    python3 -m ops.preflight --book ops/books/cef_discount_book.json
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops import halt as halt_mod  # noqa: E402


class Check:
    """One verdict. `blocking` decides whether it can stop live orders; a
    non-blocking check is advisory and only ever produces a warning."""

    def __init__(self, name, ok, detail="", blocking=True):
        self.name, self.ok, self.detail, self.blocking = name, ok, detail, blocking

    def __repr__(self):
        mark = "PASS" if self.ok else ("FAIL" if self.blocking else "WARN")
        return f"[{mark}] {self.name}: {self.detail}"


# -- individual checks ----------------------------------------------------

def check_halt() -> Check:
    active = halt_mod.read_halt()
    if active is None:
        return Check("halt", True, "no active halt")
    return Check("halt", False,
                 f"ops/HALT.md is active ({active['when']}: {active['reason']}). "
                 f"Clear it with ops.halt.clear_halt() once genuinely fixed.")


def deployed_tickers(book_path) -> dict:
    """{sleeve_name: [instrument, ...]} for every ENABLED sleeve in the book.

    Uses the sleeve object's own `instruments()` rather than reading a spec key,
    because that is the exact list the runner will trade — a spec-key shortcut
    would drift from reality the moment a sleeve computes its universe.
    """
    from src.deploy import registry

    spec_book = json.loads(Path(book_path).read_text())
    out = {}
    for entry in spec_book.get("sleeves", []):
        if not entry.get("enabled", True):
            continue
        spec = entry.get("spec")
        if spec is None and entry.get("spec_path"):
            spec = json.loads((REPO_ROOT / entry["spec_path"]).read_text())
        if spec is None:
            continue
        sleeve = registry.build_sleeve(spec, entry.get("capital_usd", 0.0))
        out[entry["name"]] = list(sleeve.instruments())
    return out


def check_costs(book_path) -> Check:
    """Every deployed ticker must have a cost entry.

    THIS IS THE CHECK THAT WOULD HAVE PREVENTED THE WHOLE 2026-07-31 INCIDENT.
    `ops/ledger.py:511` reads costs["tickers"][t]["half_spread_bp"] and raises a
    deliberate KeyError on a miss. Both books were deployed with 28 of 31 tickers
    missing, so the ledger died mid-advance every session — after the orders had
    gone out. A missing cost entry is not a modelling nicety, it is a hard
    prerequisite, and it is cheap to verify before anything is transmitted.
    """
    from ops import common as ops_common

    costs = ops_common.load_costs()
    have = set(costs.get("tickers", {}))
    missing = {}
    for sleeve, insts in deployed_tickers(book_path).items():
        gap = sorted(t for t in insts if t not in have)
        if gap:
            missing[sleeve] = gap
    if not missing:
        n = sum(len(v) for v in deployed_tickers(book_path).values())
        return Check("costs", True, f"all {n} deployed ticker(s) priced")
    detail = "; ".join(f"{s}: {', '.join(g)}" for s, g in missing.items())
    return Check("costs", False,
                 f"config/costs.yaml has no half_spread_bp for -> {detail}. "
                 f"The ledger will KeyError mid-advance, AFTER orders are sent.")


def check_cost_drift(book_path, tol=0.20) -> Check:
    """Warn when a static yaml half-spread has drifted from the tick-floor model.

    The backtest recomputes half_spread_bp from each day's price; this file is a
    fixed number per ticker. A CEF that halves in price genuinely doubles its
    cost in bp, so the static entry silently stops describing reality. Advisory
    only — drift is a reason to re-measure, never a reason to stop trading.
    """
    try:
        import pandas as pd

        from ops import common as ops_common
        from src.strategies.credit_rv.costs import CostModel

        cm = CostModel()
        costs = ops_common.load_costs().get("tickers", {})
        px_path = REPO_ROOT / "data" / "cef" / "cef_prices.parquet"
        if not px_path.exists():
            return Check("cost_drift", True, "no CEF price store to compare", blocking=False)
        p = pd.read_parquet(px_path)
        wanted = {t for insts in deployed_tickers(book_path).values() for t in insts}
        drifted = []
        for t in sorted(wanted):
            if t not in costs:
                continue
            d = p[p["ticker"] == t].sort_values("date").tail(252)
            if d.empty:
                continue
            model = cm.half_spread_bp(float(d["close"].median()),
                                      float((d["close"] * d["volume"]).median()))
            book = float(costs[t]["half_spread_bp"])
            if book > 0 and abs(model - book) / book > tol:
                drifted.append(f"{t} yaml {book:.2f}bp vs model {model:.2f}bp")
        if not drifted:
            return Check("cost_drift", True, "static costs still match the model",
                         blocking=False)
        return Check("cost_drift", False,
                     f"{len(drifted)} ticker(s) drifted >{tol:.0%}: "
                     f"{'; '.join(drifted[:6])}", blocking=False)
    except Exception as exc:
        return Check("cost_drift", True, f"skipped ({exc!r})", blocking=False)


def check_data(asof, max_price_age_bd=3, max_nav_age_bd=3) -> Check:
    """Prices and NAVs must be recent. A stale NAV is not a cheap fund, it is a
    blind one — the CEF signal is price MINUS nav, so trading on a stale NAV
    trades on a number that no longer exists."""
    import pandas as pd

    asof = pd.Timestamp(asof)
    notes, bad = [], False
    for label, path, col, limit in (
            ("prices", REPO_ROOT / "data/cef/cef_prices.parquet", "date", max_price_age_bd),
            ("NAV", REPO_ROOT / "data/cef/cef_nav.parquet", "date", max_nav_age_bd)):
        if not path.exists():
            notes.append(f"{label}: MISSING {path.name}")
            bad = True
            continue
        last = pd.Timestamp(pd.read_parquet(path, columns=[col])[col].max())
        age = len(pd.bdate_range(last, asof)) - 1
        notes.append(f"{label} -> {last.date()} ({age}bd)")
        if age > limit:
            bad = True
    return Check("data", not bad, "; ".join(notes))


def check_broker(host=None, port=None, timeout=5.0) -> Check:
    """Is TWS/Gateway actually listening?

    TWS force-restarts daily and comes back requiring a login. If nobody is
    home, an EXECUTION=ibkr run raises ConnectionRefused deep inside connect()
    — recoverable, but only if we look BEFORE deciding to trade, so the session
    can downgrade to collect-only instead of dying.
    """
    from src.deploy.broker.ibkr import IBKRConfig

    cfg = IBKRConfig.from_env()
    host = host or cfg.host
    port = int(port or cfg.port)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return Check("broker", True, f"TWS/Gateway listening on {host}:{port}")
    except Exception as exc:
        return Check("broker", False,
                     f"nothing listening on {host}:{port} ({exc.__class__.__name__}). "
                     f"TWS restarts daily and needs a login — start it, or let the "
                     f"session run collect-only.")


def check_margin(min_cushion=0.10) -> Check:
    """Refuse to add risk when the account is close to a forced liquidation.

    IBKR liquidates at cushion 0, and it does not care which sleeve it unwinds
    or what that does to an experiment. As of 2026-07-31 the account ran at
    cushion 0.166 with 2.09x gross/NLV, because two books sized independently
    ($500k CEF + $640k phase0 = $1.14M USD) share one account holding ~$722k USD
    of equity — 158% committed. That is survivable while it is watched and
    dangerous the moment it is not, which is precisely what unattended running
    changes. Blocking here costs a session of trading; being liquidated costs
    the position history that makes the paper record worth anything.
    """
    try:
        import ib_async as ibapi

        from src.deploy.broker.ibkr import IBKRConfig

        cfg = IBKRConfig.from_env()
        app = ibapi.IB()
        app.connect(cfg.host, int(cfg.port), clientId=int(cfg.client_id) + 60,
                    readonly=True, timeout=20)
        try:
            vals = {r.tag: r.value for r in app.accountSummary()}
        finally:
            app.disconnect()
        cushion = float(vals.get("Cushion", "nan"))
        nlv = float(vals.get("NetLiquidation", "nan"))
        gross = float(vals.get("GrossPositionValue", "nan"))
        excess = float(vals.get("ExcessLiquidity", "nan"))
        detail = (f"cushion {cushion:.3f}, gross/NLV {gross/nlv:.2f}x, "
                  f"excess liquidity {excess:,.0f}")
        if cushion < min_cushion:
            return Check("margin", False,
                         f"{detail} — below the {min_cushion:.2f} floor; adding "
                         f"exposure risks a broker liquidation that would end the "
                         f"experiment, not just a trade.")
        return Check("margin", True, detail)
    except Exception as exc:
        return Check("margin", True, f"skipped ({exc.__class__.__name__})",
                     blocking=False)


def check_heartbeat(job, asof, max_missed=1) -> Check:
    """Did the previous trading session actually run?

    Silence and success look identical from outside. This is the only check that
    would have caught the 09:35 exit-126 TCC failure, which transmitted nothing
    and wrote no application log at all.
    """
    import pandas as pd

    beat = halt_mod.last_beat(job)
    if beat is None:
        return Check("heartbeat", True, "no prior beat (first run)", blocking=False)
    last = pd.Timestamp(beat["date"])
    sessions = len(pd.bdate_range(last, pd.Timestamp(asof))) - 1
    if sessions > max_missed:
        return Check("heartbeat", False,
                     f"last {job} beat was {beat['date']} ({beat['status']}) — "
                     f"{sessions} session(s) ago. Something stopped firing.",
                     blocking=False)
    return Check("heartbeat", True,
                 f"last beat {beat['date']} ({beat['status']})", blocking=False)


# -- the gate -------------------------------------------------------------

def run(job, book_path, asof, want_live=True, notify=True) -> dict:
    """Run every check and return the session plan.

    Returns {'arm', 'collect', 'checks', 'blockers', 'warnings'}. `arm` is the
    only thing that authorises an order; `collect` is true unconditionally,
    because data we do not capture today cannot be captured tomorrow.
    """
    checks = [check_halt(), check_costs(book_path), check_cost_drift(book_path),
              check_data(asof), check_heartbeat(job, asof)]
    if want_live:
        broker = check_broker()
        checks.append(broker)
        # Only worth asking about margin if something is actually listening.
        if broker.ok:
            checks.append(check_margin())

    blockers = [c for c in checks if not c.ok and c.blocking]
    warnings = [c for c in checks if not c.ok and not c.blocking]
    arm = want_live and not blockers

    print(f"[preflight] {job} asof={asof}")
    for c in checks:
        print(f"[preflight]   {c!r}")
    print(f"[preflight] verdict: arm={arm} collect=True "
          f"({len(blockers)} blocker(s), {len(warnings)} warning(s))")

    if notify and (blockers or warnings):
        subject = (f"QUANTT {job}: NOT TRADING ({len(blockers)} blocker(s))"
                   if blockers else f"QUANTT {job}: warnings")
        body = "\n".join(repr(c) for c in checks if not c.ok)
        halt_mod.alert(subject=subject, body=body,
                       speak="Quant book is not trading today." if blockers else "")

    return {"arm": arm, "collect": True,
            "checks": [repr(c) for c in checks],
            "blockers": [repr(c) for c in blockers],
            "warnings": [repr(c) for c in warnings]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", default="cef")
    ap.add_argument("--book", required=True)
    ap.add_argument("--asof", default=f"{datetime.now():%Y-%m-%d}")
    ap.add_argument("--no-live", action="store_true",
                    help="skip the broker check (collect-only session)")
    ap.add_argument("--quiet-alerts", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.job, a.book, a.asof, want_live=not a.no_live,
              notify=not a.quiet_alerts)
    return 0 if res["arm"] else 1


if __name__ == "__main__":
    sys.exit(main())
