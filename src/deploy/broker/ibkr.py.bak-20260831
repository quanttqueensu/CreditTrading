"""IBKR paper adapter — the SAME runner trades paper once a human starts the
gateway. `ib_insync` is imported ONLY inside `connect()`; this module imports,
and its unit tests run, with **no ib_insync installed** (a stubbed module is
injected). We never `pip install ib_insync` and never open a live socket in CI.

CONNECTION RUNBOOK (documented, not run tonight)
------------------------------------------------
1. On a desktop with IB Gateway (or TWS) installed, log in to the **paper**
   account and enable the API: Configure > Settings > API > Enable ActiveX and
   Socket Clients, add 127.0.0.1 to trusted IPs, note the socket port
   (paper gateway default **4002**, paper TWS default 7497).
2. In `config/.env` add:
       IBKR_HOST=127.0.0.1
       IBKR_PORT=4002
       IBKR_CLIENT_ID=17
   (no username/password lives in the repo — the human is already logged into
   the gateway; the API attaches to that session).
3. `pip install ib_insync` in the deploy environment (NOT in CI / the sim path).
4. `EXECUTION=ibkr python3 src/deploy/run_book.py --asof <date>` — the same
   orchestrator, the same sleeves, now routing through this adapter.

Order model: each `PositionTarget` maps to an ib_insync `Stock`/`Option`; legs
sharing a `combo_id` are grouped into one combo (`BAG`) order so a straddle
fills atomically; equities/ETFs use `MarketOrder`, options a marketable limit.
A **weight-expressed** target (the credit-base, EOM and FOMC longs all emit
weights, not share counts) is sized to an integer share count here — using the
same `floor(nav * weight / price)` rule the simulator sub-ledger uses — so it
places a real order instead of being silently dropped.

PER-SLEEVE SEGREGATION INSIDE ONE PAPER ACCOUNT
-----------------------------------------------
The paper account is a single pool, but the book is N logically-independent
sleeves that may hold the SAME instrument in opposite directions (e.g. IEF is
long in the EOM/FOMC sleeves and short in the duration-hedged overlay). We must
NOT let one sleeve see the account-net IEF and "flatten" a leg it never took.
So each sleeve's position is tracked by its own `orderRef` tag in
`self._live_positions[sleeve_name]`, updated from the fills IBKR reports, and
`sync_positions(name)` returns THAT — never the account net. `reconcile()`
checks that the sum of the tagged sleeve books equals `ib.positions()` and warns
on drift (the shared-symbol reconciliation guard).

ARMING — WHY NO ORDER GOES OUT UNTIL `arm()` HAS RUN (added 2026-07-31)
-----------------------------------------------------------------------
The tag book above is a local reconstruction, and on 2026-07-31 it was flatly
wrong: a missing `config/costs.yaml` entry crashed the shadow ledger AFTER the
orders were transmitted, so the ledger stayed at its funding row while the
account filled ~$2.07M gross. `place_targets` diffs targets against that book,
so the following session would have seen a flat sleeve and bought the entire
thing a second time — against 164,500 CAD of excess liquidity at 83% margin use.

The rule that prevents it splits authority between the two sources:

    the BROKER is authoritative for HOW MANY shares exist,
    the shadow LEDGER is authoritative for WHICH SLEEVE owns them.

`arm()` enforces exactly that — it overwrites quantities from `ib.positions()`
while keeping the ledger's attribution, and refuses to arm only when attribution
is genuinely ambiguous (a symbol two sleeves both claim, whose tagged split does
not sum to the account). Stale quantities are adopted and logged; they are no
longer a reason to halt, because a system that halts on every one-share rounding
difference is not one that can run unattended.

`place_targets` raises `NotArmed` if called first. Symbols held by another book
in the same paper account are ignored, not flagged: one process per book means a
CEF run legitimately sees the null trader's ETFs in the account.

BOOK-LEVEL NAV / RISK / REPORTING
---------------------------------
For every sleeve the adapter also keeps a local **shadow sub-ledger** (the same
`Simulator` bookkeeping the sim path uses), advanced day-by-day and marked to
local EOD data. It is the source of `ledger(name)`, so the orchestrator's
per-sleeve kill switches (`risk.evaluate_sleeve`) and the book-level rollup /
limits (`risk.check_book_limits`) run LIVE exactly as they do under the
simulator — otherwise the live paper book would run with every kill switch and
book limit disabled. The shadow book is the paper "reporting convention"
(shared-cash aggregation, per DEPLOY_CONTEXT §3); the real orders go to IBKR.

BOND LEGS (build B3 — forced-flow sleeves; recon: results/forced_flow/IBKR_BOND_RECON.md)
-----------------------------------------------------------------------------------------
A bond leg is a `PositionTarget` whose meta carries `asset='corporate_bond'`
(stamped by `src.deploy.lib.odd_lot.leg_meta`) and/or a `cusip`. The adapter maps
it to an ib_insync `Bond` contract by CUSIP on exchange SMART (`Bond(secIdType=
'CUSIP', secId=<cusip>, exchange='SMART', currency='USD')` — recon §7 route (b);
falls back to `Contract(secType='BOND', symbol=<cusip>)`, route (a), if the
module has no `Bond` helper). Execution facts encoded from the recon:

  * **Quantity units.** IBKR quotes bond quantity in units of **$1,000 face**
    (recon §2); the ledger prices bonds per 100 par, so one ledger unit is $100
    face (`meta['face_per_unit_usd']`, default 100). The adapter converts
    ledger qty -> $1k units, rounds DOWN to the per-issue size increment, and
    refuses to send anything below the per-issue minimum (default 1 unit =
    $1k; many issues carry $2k minimums — override via `meta['min_size_units']`
    / `meta['size_increment_units']`, or let the adapter read
    `ContractDetails.minSize`/`sizeIncrement` when the API offers them).
  * **Limit orders ONLY** (recon §4: bond entry is limit-based; market orders
    on odd-lot corporates are never used). Limit = `meta['limit_price']` if
    given, else the last local close (per 100 par). A bond leg with no
    priceable limit is warned and skipped — never sent at market. TIF default
    DAY (`meta['tif']` to override; recon §3: overnight-persisting orders are
    re-treated as new orders).
  * **Never in a BAG combo** — odd-lot corporates fill (or don't) on their own.
  * **Paper fills are cosmetic** (recon §5: top-of-book simulation, no dealer/
    RFQ layer). Every bond paper fill is recorded to the odd-lot side channel
    (`odd_lot.record_broker_fill` -> `broker_fills.csv`) which no P&L path
    reads; the shadow sub-ledger charges the measured odd-lot cost model
    (1.45% / 8.6% round trips, results/S1_BOND_LEVEL.md) and remains the sole
    P&L source, per FORCED_FLOW_PREREG locked decision 1.
"""

import json
import math
import os
from dataclasses import dataclass

import pandas as pd

from ops.ledger import CASH
from .base import Broker, Fill, AccountSnapshot
from ..sleeve import PositionTarget, OPTION, LONG, SHORT, FLAT


# IBKR bond quantities are quoted in units of $1,000 face value
# (results/forced_flow/IBKR_BOND_RECON.md §2).
BOND_FACE_PER_IBKR_UNIT_USD = 1000.0
# The ledger prices bond legs per 100 par, so one ledger unit is $100 face
# unless the leg's meta overrides `face_per_unit_usd`.
DEFAULT_BOND_FACE_PER_LEDGER_UNIT_USD = 100.0


def _deep_get(obj, key):
    """First value for `key` anywhere in a nested dict, else None.

    Frozen specs nest their universe at different depths (`frozen.universe`,
    `allocation.universe`, top level), so a recursive lookup avoids hard-coding
    each layout and silently returning nothing when one changes.
    """
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _deep_get(value, key)
            if found is not None:
                return found
    return None


class ShadowLedgerDesync(RuntimeError):
    """The shadow sub-ledger failed to record orders that were already sent.

    Raised instead of being swallowed, because the 2026-07-31 incident showed the
    swallowed form is far more dangerous than the crash: 28 of the 31 deployed
    tickers had no `config/costs.yaml` entry, so `ops/ledger.py:511` KeyErrored on
    the first unknown name (NVG / USHY). The old handler printed one line and
    returned normally, leaving both ledgers frozen at their funding row while the
    account filled ~$2.07M gross. The next session then seeded positions from that
    empty ledger, saw a flat book, and would have re-bought all of it.

    A ledger that does not know what the account holds is not a reporting problem,
    it is a position-state corruption, and it must stop the run.
    """


class NotArmed(RuntimeError):
    """`place_targets` was called before `arm()` confirmed the account is
    explainable by the registered sleeves. Never transmit on unverified state."""


@dataclass
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 4002            # paper IB Gateway default (TWS paper is 7497)
    client_id: int = 17
    account: str = ""           # optional explicit paper account id
    readonly: bool = False

    @classmethod
    def from_env(cls, repo_root=None) -> "IBKRConfig":
        """Read host/port/client id from the environment, then config/.env.

        This exists because nothing was reading either one: `make_broker` builds
        IBKRBroker with only books_root/verbose, so the dataclass default of 4002
        always won while TWS was listening on 7497 and every live run died with
        ConnectionRefused. Process environment wins over the file so a one-off
        run can override without editing committed config.
        """
        import os
        from pathlib import Path
        vals = {}
        root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
        env_file = root / "config" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
        vals.update({k: v for k, v in os.environ.items() if k.startswith("IBKR_")})

        def pick(key, default, cast=str):
            raw = vals.get(key)
            if raw in (None, ""):
                return default
            try:
                return cast(raw)
            except (TypeError, ValueError):
                return default

        return cls(host=pick("IBKR_HOST", cls.host),
                   port=pick("IBKR_PORT", cls.port, int),
                   client_id=pick("IBKR_CLIENT_ID", cls.client_id, int),
                   account=pick("IBKR_ACCOUNT", cls.account),
                   readonly=str(vals.get("IBKR_READONLY", "")).lower()
                            in ("1", "true", "yes"))


class IBKRBroker(Broker):
    """Lazy-`ib_insync` broker. Pass `ib_insync_module` to unit-test against a
    stub; leave it None in production and `connect()` imports the real one."""

    def __init__(self, config=None, ib_insync_module=None, books_root="ops/books",
                 verbose=False, **kwargs):
        if config is None:
            overrides = {k: v for k, v in kwargs.items()
                         if k in IBKRConfig.__dataclass_fields__}
            config = IBKRConfig.from_env()
            for k, v in overrides.items():
                setattr(config, k, v)
        self.config = config
        self.verbose = bool(verbose)
        self._ib_insync = ib_insync_module     # injected stub in tests; None in prod
        self.ib = None                         # the connected IB() handle
        self._sleeves = {}                     # sleeve_name -> {instruments, ...}
        # Per-sleeve position attribution (orderRef tag), maintained from fills.
        # This — NOT the account net — is what each sleeve diffs against, so a
        # symbol shared across sleeves never cross-contaminates.
        self._live_positions = {}              # sleeve_name -> {instrument: signed qty}
        # Shadow bookkeeping for NAV / risk / rollup (a Simulator under its own
        # root so it never collides with an EXECUTION=simulator run's books).
        self._books_root = books_root
        self._book = None
        # Bond-leg support (build B3). Instruments once seen with bond meta are
        # remembered so an implicit flatten target (constructed without meta)
        # still routes through the Bond path. The set is PERSISTED to a state
        # file under the shadow-book root and re-loaded on construction /
        # register_sleeve: every daily paper run is a fresh process, and a
        # restart that then flattens a held bond must NOT route it through the
        # Stock path as a market order (recon §4: bonds are limit-only).
        # Per-issue min/increment lookups via ContractDetails are cached per
        # instrument.
        self._bond_instruments = set()
        self._bond_size_cache = {}             # instrument -> (min_u, inc_u) | None
        self._load_bond_state()
        # Live-order arming (added 2026-07-31 after the incident below). No order
        # is transmitted until `arm()` has adopted broker truth into the tag books
        # and found the account explainable. Default False: an un-armed adapter
        # refuses to trade rather than trading on unverified state.
        self._armed = False
        self._arm_report = None

    # -- bond identity persistence (restart safety) -----------------------

    def _bond_state_path(self):
        from pathlib import Path
        return Path(self._books_root) / "_ibkr_shadow" / "bond_instruments.json"

    def _load_bond_state(self):
        """Merge the persisted bond-identity set into memory (never removes).
        Safe on a missing/corrupt file — starts empty, exactly as before."""
        path = self._bond_state_path()
        try:
            if path.exists():
                with open(path) as fh:
                    got = json.load(fh)
                if isinstance(got, list):
                    self._bond_instruments.update(str(i) for i in got)
        except Exception:
            pass

    def _persist_bond_state(self):
        """Atomic write (tmp + rename, the ledger discipline) of the bond
        identity set. Failure never blocks trading — worst case is the
        pre-fix behavior, and register_sleeve's leg_meta reseed still covers
        the restart."""
        path = self._bond_state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.parent / f".{path.name}.tmp"
            with open(tmp, "w") as fh:
                json.dump(sorted(self._bond_instruments), fh, indent=0)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except Exception as exc:
            print(f"[ibkr] WARNING: could not persist bond-identity state to "
                  f"{path}: {exc!r} (a restart may need leg_meta to re-derive "
                  f"bond routing)")

    def _remember_bond(self, instrument):
        if instrument not in self._bond_instruments:
            self._bond_instruments.add(instrument)
            self._persist_bond_state()

    # -- shadow bookkeeping ----------------------------------------------

    def _shadow(self):
        """Lazily build the local shadow book (pure-python; no ib_insync)."""
        if self._book is None:
            from pathlib import Path
            from .simulator import Simulator
            self._book = Simulator(books_root=Path(self._books_root) / "_ibkr_shadow",
                                   verbose=False)
        return self._book

    def ledger(self, sleeve_name):
        """The shadow sub-ledger for `sleeve_name`. Its presence is what lets the
        orchestrator run the per-sleeve kill switches and the book rollup on the
        live path (risk.evaluate_sleeve / portfolio.rollup gate on this method)."""
        return self._shadow().ledger(sleeve_name)

    # -- connection -------------------------------------------------------

    def connect(self):
        """Import ib_insync (LAZY — first touch here), open the paper socket,
        return self. In tests an injected `ib_insync_module` is used and no
        real import or socket happens."""
        if self._ib_insync is None:
            # Prefer `ib_async`, the maintained fork with the identical surface
            # (IB/Stock/Bond/MarketOrder/LimitOrder/util). `ib_insync` 0.9.86 is
            # unmaintained and hangs in its asyncio handshake on Python 3.12+:
            # TWS answers a raw socket handshake normally while the library
            # never returns, which looks exactly like a dead gateway.
            try:
                import ib_async as _ib       # noqa: F401  (only imported here)
            except ImportError:
                import ib_insync as _ib      # noqa: F401
            self._ib_insync = _ib
        ib = self._ib_insync.IB()
        ib.connect(self.config.host, self.config.port,
                   clientId=self.config.client_id, readonly=self.config.readonly)
        self.ib = ib
        return self

    def disconnect(self):
        if self.ib is not None:
            self.ib.disconnect()
            self.ib = None

    def register_sleeve(self, sleeve_name, alloc_type, spec, costs, capital_usd,
                        instruments, mark_fn=None, greeks_fn=None,
                        option_half_spread_usd=0.02):
        self._sleeves[sleeve_name] = {"alloc_type": alloc_type,
                                      "instruments": list(instruments),
                                      "capital_usd": float(capital_usd),
                                      "mark_fn": mark_fn, "greeks_fn": greeks_fn}
        # Wire the matching shadow sub-ledger (idempotent; reloads on-disk state).
        self._shadow().register_sleeve(
            sleeve_name, alloc_type, spec, costs, capital_usd, instruments,
            mark_fn=mark_fn, greeks_fn=greeks_fn,
            option_half_spread_usd=option_half_spread_usd)
        # Seed per-sleeve attribution from any persisted shadow book so a restart
        # continues the tag map instead of re-establishing full positions. (May
        # trail the account by one in-flight day; reconcile() surfaces drift.)
        try:
            lg = self.ledger(sleeve_name)
            held = lg.held_shares() if hasattr(lg, "held_shares") else lg.held()
            seed = {k: float(v) for k, v in (held or {}).items()
                    if k != CASH and abs(float(v)) > 1e-12}
            if not seed:
                # The ledger is the normal attribution source, but it can be
                # missing -- on 2026-07-31 a costs.yaml KeyError froze it at the
                # funding row while the account filled $2.07M gross. When that
                # happens `_attribution.json`, rebuilt from broker fills by
                # scripts/ops/reconcile_attribution.py, supplies the same fact.
                #
                # This is attribution ONLY. `arm()` still overwrites the
                # quantities from ib.positions() for anything solely owned, so a
                # stale file cannot put a wrong share count into a live diff --
                # it can only say which sleeve a contested symbol belongs to.
                seed = self._attribution_seed(sleeve_name)
            if seed:
                self._live_positions.setdefault(sleeve_name, {}).update(seed)
        except Exception:
            pass
        # Re-seed bond identity for the restart case: an implicit flatten of a
        # held-but-unmentioned bond is built WITHOUT meta, so the Bond/Stock
        # routing decision must survive the process boundary. Two sources,
        # both idempotent: the persisted bond_instruments.json state file, and
        # the shadow sub-ledger's recovered leg_meta (bond legs carry
        # asset='corporate_bond' / a cusip, stamped by odd_lot.leg_meta).
        self._load_bond_state()
        try:
            lg = self.ledger(sleeve_name)
            for inst, m in (getattr(lg, "leg_meta", {}) or {}).items():
                if isinstance(m, dict) and (m.get("asset") == "corporate_bond"
                                            or m.get("cusip")):
                    self._remember_bond(inst)
        except Exception:
            pass

    # -- contract construction -------------------------------------------

    def _is_bond(self, pt):
        """True for a corporate-bond leg: meta stamped `asset='corporate_bond'`
        (odd_lot.leg_meta) and/or carrying a `cusip`. Once seen, the instrument
        is remembered so a later implicit flatten target (built without meta)
        still routes through the Bond path instead of the Stock path."""
        m = pt.meta or {}
        if m.get("asset") == "corporate_bond" or m.get("cusip"):
            self._remember_bond(pt.instrument)
            return True
        return pt.instrument in self._bond_instruments

    def _contract(self, pt):
        """PositionTarget -> ib_insync contract. Options read underlier/expiry/
        strike/opt_type from `pt.meta`. Bond legs map by CUSIP on SMART
        (recon §7; `meta['cusip']` preferred, else the instrument id IS the
        CUSIP)."""
        ibi = self._ib_insync
        if pt.kind == OPTION:
            m = pt.meta or {}
            return ibi.Option(m["underlier"], m["expiry"], float(m["strike"]),
                              m["opt_type"], m.get("exchange", "SMART"),
                              multiplier=str(int(m.get("multiplier", 100))))
        if self._is_bond(pt):
            m = pt.meta or {}
            cusip = str(m.get("cusip") or pt.instrument)
            exch = m.get("exchange", "SMART")
            if hasattr(ibi, "Bond"):        # ib_insync/ib_async helper (route b)
                return ibi.Bond(secIdType="CUSIP", secId=cusip,
                                exchange=exch, currency="USD")
            c = ibi.Contract()              # route (a): CUSIP in the symbol field
            c.secType, c.symbol = "BOND", cusip
            c.exchange, c.currency = exch, "USD"
            return c
        return ibi.Stock(pt.instrument, "SMART", "USD")

    def _order(self, pt, qty):
        """A MarketOrder for equities, a marketable limit for options. Bond
        legs NEVER come through here — `_place_bond` builds their limit-only
        orders (recon §4: no market orders on odd-lot corporates).

        A sleeve may request `meta['order_type'] = 'MOC'` (market-on-close).
        This matters for any strategy whose signal is only computable AFTER the
        close: a plain market order submitted in the evening rests overnight and
        fills at the next pre-open or open, which is the widest-spread, most
        volatile print of the session and is NOT what the research measured.
        An MOC instead executes in the next closing auction — the deepest,
        tightest liquidity of the day, and the price the backtest assumed.
        Observed 2026-07-31: overnight market orders filled at 07:27 ET, two
        hours before the exchange opened, at up to 2.9% away from the decision
        price. That is what this exists to prevent.
        """
        ibi = self._ib_insync
        action = "SELL" if qty < 0 else "BUY"
        want = str((pt.meta or {}).get("order_type", "")).upper()
        if pt.kind == OPTION:
            lim = float((pt.meta or {}).get("limit_price", 0.0))
            return ibi.LimitOrder(action, abs(qty), lim)
        if want in ("MOC", "MARKETONCLOSE"):
            o = ibi.Order()
            o.action = action
            o.totalQuantity = abs(qty)
            o.orderType = "MOC"
            o.tif = "DAY"          # IB rejects an MOC with an empty TIF
            return o
        return ibi.MarketOrder(action, abs(qty))

    # -- bond legs (build B3) ---------------------------------------------

    @staticmethod
    def _bond_face_per_unit(pt):
        """$ face represented by ONE ledger unit of this leg (per-100-par
        pricing -> $100/unit unless the meta overrides)."""
        face = float((pt.meta or {}).get(
            "face_per_unit_usd", DEFAULT_BOND_FACE_PER_LEDGER_UNIT_USD))
        return face if face > 0 else DEFAULT_BOND_FACE_PER_LEDGER_UNIT_USD

    def _bond_min_increment(self, pt, contract):
        """(min_units, increment_units) in IBKR $1k-face units for this issue.

        Defaults 1/1 ($1k practical floor, recon §2); a sleeve that knows the
        issue's denomination stamps `min_size_units` / `size_increment_units`.
        When the connected API exposes `reqContractDetails`, the per-issue
        `ContractDetails.minSize` / `sizeIncrement` are read once, cached, and
        take precedence when LARGER (conservative direction only — an API
        answer can tighten the floor, never loosen a stamped one)."""
        m = pt.meta or {}
        min_u = max(1, int(m.get("min_size_units", 1) or 1))
        inc_u = max(1, int(m.get("size_increment_units", 1) or 1))
        if pt.instrument not in self._bond_size_cache:
            details = None
            if self.ib is not None and hasattr(self.ib, "reqContractDetails"):
                try:
                    cds = self.ib.reqContractDetails(contract) or []
                    if cds:
                        ms = float(getattr(cds[0], "minSize", 0) or 0)
                        si = float(getattr(cds[0], "sizeIncrement", 0) or 0)
                        details = (int(ms) if ms > 0 else None,
                                   int(si) if si > 0 else None)
                except Exception:
                    details = None
            self._bond_size_cache[pt.instrument] = details
        details = self._bond_size_cache[pt.instrument]
        if details:
            if details[0]:
                min_u = max(min_u, details[0])
            if details[1]:
                inc_u = max(inc_u, details[1])
        return min_u, inc_u

    def _place_bond(self, pt, delta, sleeve_name, asof, market_state):
        """Transmit ONE bond leg: ledger delta -> $1k-face units (rounded DOWN
        to the issue increment, refused below the issue minimum), limit order
        only, then record any paper fill to the odd-lot side channel and return
        the fills scaled BACK to ledger units so the tag book stays consistent.
        Warned skips leave the residual visible to `reconcile()` — never
        silent."""
        m = pt.meta or {}
        contract = self._contract(pt)
        face = self._bond_face_per_unit(pt)
        min_u, inc_u = self._bond_min_increment(pt, contract)
        raw_units = abs(float(delta)) * face / BOND_FACE_PER_IBKR_UNIT_USD
        units = int(math.floor(raw_units / inc_u)) * inc_u
        if units < min_u:
            print(f"[ibkr] WARNING {pd.Timestamp(asof).date()} {sleeve_name}: "
                  f"bond {pt.instrument} delta {delta:+.1f} ledger units = "
                  f"${abs(delta) * face:,.0f} face < issue minimum "
                  f"{min_u} x $1k (increment {inc_u}); no order sent — residual "
                  f"stays in the shadow ledger and reconcile() will show it.")
            return []
        limit = m.get("limit_price")
        if limit is None:
            limit = self._last_close(getattr(market_state, "prices", None),
                                     pt.instrument, asof)
        if limit is None or not float(limit) > 0:
            print(f"[ibkr] WARNING {pd.Timestamp(asof).date()} {sleeve_name}: "
                  f"bond {pt.instrument} has no limit price (no meta "
                  f"limit_price, no local close) — bonds are LIMIT-ONLY "
                  f"(recon §4); no order sent.")
            return []
        action = "SELL" if delta < 0 else "BUY"
        order = self._ib_insync.LimitOrder(action, units, float(limit))
        try:
            order.tif = str(m.get("tif", "DAY"))
            order.orderRef = str(sleeve_name or "")
        except Exception:
            pass
        trade = self.ib.placeOrder(contract, order)
        # Side channel: raw paper fills (in $1k units, per-100-par price) are
        # recorded for reconciliation only — no P&L path reads them back
        # (FORCED_FLOW_PREREG decision 1; the shadow ledger charges the
        # odd-lot model instead).
        for f in getattr(trade, "fills", []) or []:
            try:
                from pathlib import Path
                from ..v2.odd_lot import record_broker_fill
                ex = f.execution
                record_broker_fill(
                    Path(self._books_root) / "_ibkr_shadow" / str(sleeve_name),
                    pt.instrument,
                    "SELL" if float(ex.shares) < 0 or
                              getattr(ex, "side", "") == "SLD" else "BUY",
                    abs(float(ex.shares)), float(ex.price), asof)
            except Exception as exc:
                print(f"[ibkr] bond paper-fill side-channel record failed for "
                      f"{pt.instrument}: {exc!r} (order already transmitted)")
        # Scale fills back to LEDGER units (tag book + orchestrator currency).
        scale = BOND_FACE_PER_IBKR_UNIT_USD / face
        return self._fills_from_trade(trade, pt, asof, qty_scale=scale)

    # -- weight -> qty sizing --------------------------------------------

    @staticmethod
    def _last_close(prices, instrument, asof):
        """Latest local close for `instrument` on or before `asof`, or None."""
        if prices is None or getattr(prices, "empty", True):
            return None
        sub = prices[(prices["ticker"] == instrument)
                     & (prices["date"] <= pd.Timestamp(asof))]
        if sub.empty:
            return None
        px = float(sub.sort_values("date")["close"].iloc[-1])
        return px if px > 0 else None

    def _sleeve_nav(self, sleeve_name):
        """NAV base for weight sizing — the shadow sub-ledger's marked NAV, or
        the registered capital before it is funded."""
        try:
            lg = self.ledger(sleeve_name)
            if lg is not None and not lg.nav.empty:
                nav = float(lg.nav_series().iloc[-1])
                if nav > 0:
                    return nav
        except Exception:
            pass
        return float(self._sleeves.get(sleeve_name, {}).get("capital_usd", 0.0))

    def _resolve_qty(self, pt, market_state, asof, sleeve_name):
        """Signed target qty for one PositionTarget. FLAT -> 0. qty-expressed ->
        the signed qty. weight-expressed -> floor(nav * |weight| / price) with
        the side's sign (same rule as the sim sub-ledger). Returns None only if a
        weight target cannot be priced (caller warns and skips — never silent)."""
        if pt.side == FLAT:
            return 0.0
        if pt.qty is not None:
            return pt.signed_qty()
        if pt.weight is not None:
            if pt.kind == OPTION:
                # Our option sleeve (short-vol) always sizes by qty; a weight-
                # expressed option has no unambiguous share->contract mapping.
                return None
            price = self._last_close(getattr(market_state, "prices", None),
                                     pt.instrument, asof)
            if price is None:
                return None
            mult = float((pt.meta or {}).get("multiplier", 1.0)) or 1.0
            nav = self._sleeve_nav(sleeve_name)
            mag = math.floor(nav * abs(float(pt.weight)) / (price * mult))
            return float(-mag if pt.side == SHORT else mag)
        return None

    # -- Broker API -------------------------------------------------------

    def sync_positions(self, sleeve_name=None) -> dict:
        """Signed positions. With a `sleeve_name`, returns THAT sleeve's own
        tag-tracked book (never the account net, so shared symbols do not
        cross-contaminate). With no name, returns the account-level net from
        `ib.positions()` (used by `reconcile()`)."""
        if self.ib is None:
            raise RuntimeError("IBKRBroker.connect() must be called first")
        if sleeve_name is None:
            out = {}
            for p in self.ib.positions():
                sym = getattr(p.contract, "localSymbol", None) or p.contract.symbol
                out[sym] = out.get(sym, 0.0) + float(p.position)
            return out
        return dict(self._live_positions.get(sleeve_name, {}))

    def cash(self, sleeve_name=None) -> float:
        if self.ib is None:
            raise RuntimeError("IBKRBroker.connect() must be called first")
        for row in self.ib.accountSummary():
            if row.tag in ("TotalCashValue", "CashBalance") and \
                    getattr(row, "currency", "USD") in ("USD", "BASE"):
                return float(row.value)
        return 0.0

    def reconcile(self, tol=1e-6) -> dict:
        """Book-level guard: the SUM of the per-sleeve tag books must equal the
        account net, RESTRICTED to instruments this book actually trades.

        Returns {ok, drift, account, sleeves_sum, ignored}; `ok` is False and
        `drift` names each instrument whose account net disagrees with the tagged
        sum (a shared-symbol attribution error or an unattributed manual trade).

        The scoping is not a loosening — it is what makes the check mean
        anything here. This repo runs ONE PROCESS PER BOOK against a single
        paper account, so an unscoped comparison charges the CEF book with the
        null trader's 14 ETFs plus 5 leftover benchmark legs and reports drift on
        all of them, every session, forever. A guard that always fires is one
        nobody reads. Instruments outside the registered sleeves are returned
        under `ignored` so they stay visible without being alarming.
        """
        if self.ib is None:
            raise RuntimeError("IBKRBroker.connect() must be called first")
        account = self.sync_positions(None)
        mine = {i for m in self._sleeves.values() for i in m.get("instruments", ())}
        shared = self._foreign_book_claims()
        booked = {}
        for pos in self._live_positions.values():
            for inst, q in pos.items():
                booked[inst] = booked.get(inst, 0.0) + float(q)
        drift, ignored, shared_rows = {}, {}, {}
        for inst in set(account) | set(booked):
            a = float(account.get(inst, 0.0))
            b = float(booked.get(inst, 0.0))
            if inst not in mine:
                if abs(a) > tol:
                    ignored[inst] = a
                continue
            if inst in shared:
                # Another book in this account trades it too, so the account net
                # SHOULD exceed our tagged share — measured 2026-07-31: the
                # account holds 823 HYG of which null_trader owns 541 and the
                # benchmark books own the other 282. Calling that drift would
                # make this guard cry wolf on every session.
                shared_rows[inst] = {"account": a, "ours": b, "other_books": a - b}
                continue
            if abs(a - b) > tol:
                drift[inst] = {"account": a, "sleeves_sum": b, "diff": a - b}
        return {"ok": not drift, "drift": drift, "account": account,
                "sleeves_sum": booked, "ignored": ignored, "shared": shared_rows}

    def _attribution_seed(self, sleeve_name) -> dict:
        """`{instrument: qty}` for `sleeve_name` from `_attribution.json`, or {}.

        Written by `scripts/ops/reconcile_attribution.py` from broker fills. Read
        only when the shadow ledger has nothing, so a healthy book never touches
        it. Never raises: a missing or malformed file just means no attribution,
        and `arm()` then refuses on contested symbols rather than guessing.
        """
        from pathlib import Path
        try:
            path = Path(self._books_root) / "_attribution.json"
            if not path.exists():
                return {}
            with open(path) as fh:
                data = json.load(fh)
            book = data.get(str(sleeve_name)) or {}
            # Zeros are KEPT, unlike the ledger seed above. An explicit 0 is a
            # real claim -- "this sleeve owns none of that contested symbol" --
            # and is what lets arm() resolve a name the sleeve deliberately holds
            # flat while another book holds it long.
            return {k: float(v) for k, v in book.items() if k != CASH}
        except Exception:
            return {}

    def _foreign_book_claims(self) -> set:
        """Instruments traded by sleeves belonging to OTHER books in this account.

        Every book here runs as its own process against one shared paper account,
        so `self._sleeves` sees only part of the picture. Without this, a symbol
        two books both hold looks solely-owned and `arm()` hands the whole account
        net to one of them.

        Sibling specs are read from the directory holding the book JSONs -- the
        parent of `books_root` (`ops/books/phase0_live` -> `ops/books`). A file
        counts as a book spec if it parses and carries a `sleeves` list; anything
        whose sleeves are all registered HERE is this book and is skipped.

        Deliberately fail-open on unreadable files but fail-safe on ambiguity: a
        spec we cannot parse simply contributes no claims, and the shared-symbol
        branch in `arm()` then refuses on a missing ledger entry anyway.
        """
        from pathlib import Path
        claims, mine = set(), set(self._sleeves)
        try:
            root = Path(self._books_root).resolve().parent
        except Exception:
            return claims
        for path in sorted(root.glob("*.json")):
            try:
                with open(path) as fh:
                    spec = json.load(fh)
            except Exception:
                continue
            sleeves = spec.get("sleeves")
            if not isinstance(sleeves, list) or not sleeves:
                continue
            names = {s.get("name") or s.get("sleeve_id") or s.get("id")
                     for s in sleeves if isinstance(s, dict)}
            if names and names <= mine:
                continue                       # this book — not foreign
            for s in sleeves:
                if not isinstance(s, dict):
                    continue
                frozen = s.get("spec")
                if frozen is None and s.get("spec_path"):
                    try:
                        with open(s["spec_path"]) as fh:
                            frozen = json.load(fh)
                    except Exception:
                        continue
                for key in ("universe", "instruments", "tickers"):
                    found = _deep_get(frozen, key)
                    if isinstance(found, (list, tuple)):
                        claims.update(str(x) for x in found)
                        break
        return claims

    def arm(self, adopt=True) -> dict:
        """Adopt BROKER truth into the per-sleeve tag books, then decide whether
        it is safe to transmit orders. Returns the arming report; sets `_armed`.

        WHY THIS EXISTS. `register_sleeve` seeds `_live_positions` from the shadow
        sub-ledger, which is the only per-sleeve ATTRIBUTION we have. But the
        ledger is a local reconstruction and the account is the fact. On
        2026-07-31 the two disagreed completely — ledger flat, account holding
        ~$2.07M gross — and because `place_targets` diffs targets against the
        ledger seed, the next run would have re-bought both books entire.

        The split of authority this method enforces:
          * the BROKER is authoritative for how many shares exist,
          * the shadow LEDGER is authoritative for which sleeve owns them.

        So we keep the ledger's attribution and overwrite its quantities. A
        position is only unexplainable — and therefore a halt — when attribution
        is genuinely ambiguous, not merely stale.

        Symbols the account holds that NO registered sleeve trades are ignored,
        not flagged: this repo runs one process per book against a single paper
        account, so a CEF run legitimately sees the null trader's 14 credit ETFs
        in `ib.positions()` and must not treat them as drift.

        CROSS-BOOK CLAIMS. `self._sleeves` only holds the sleeves of the book
        running in THIS process, so "exactly one owner" was originally decided
        against an incomplete picture. Measured 2026-07-31: arming the phase0
        book reported ok=True while mis-attributing 9 symbols, because
        null_trader is the only sleeve in its process and therefore looked like
        the sole owner of HYG — of which it holds 541 while the ACCOUNT holds
        823, the other 282 belonging to bench_b1_hyg and bench_b6_ew_credit.
        Adopting 823 would have made the next run sell 282 shares it never
        bought. So sibling book specs are consulted too, and a symbol another
        book also trades is never adopted from the account net.
        """
        if self.ib is None:
            raise RuntimeError("IBKRBroker.connect() must be called first")
        account = self.sync_positions(None)
        claimed_elsewhere = self._foreign_book_claims()

        owners = {}
        for name, meta in self._sleeves.items():
            for inst in meta.get("instruments", ()):
                owners.setdefault(inst, []).append(name)

        problems, adopted, changes, foreign = [], {}, [], {}
        for sym, qty in account.items():
            who = owners.get(sym, [])
            if not who:
                foreign[sym] = qty
                continue
            if len(who) == 1 and sym not in claimed_elsewhere:
                adopted.setdefault(who[0], {})[sym] = float(qty)
                continue
            if len(who) == 1:
                # Sole owner in THIS process, but another book in the same
                # account trades it too, so the account net is not ours to take.
                # The ledger is the only attribution that exists; trust it, and
                # refuse when it has nothing to say rather than guessing.
                tagged = self._live_positions.get(who[0], {}).get(sym)
                if tagged is None:
                    problems.append(
                        f"{sym}: account holds {qty:+g} and {who[0]} trades it, "
                        f"but so does another book and this sleeve's ledger has "
                        f"no entry — cannot tell how much of it is ours")
                else:
                    adopted.setdefault(who[0], {})[sym] = float(tagged)
                continue
            # Shared symbol: keep the ledger's split only if it explains the
            # account exactly. If it does not, no rule can tell us who owns what
            # and guessing is precisely how a sleeve flattens a leg it never took.
            tagged = {n: float(self._live_positions.get(n, {}).get(sym, 0.0))
                      for n in who}
            if abs(sum(tagged.values()) - float(qty)) <= 1e-6:
                for n, q in tagged.items():
                    adopted.setdefault(n, {})[sym] = q
            else:
                problems.append(
                    f"{sym}: account holds {qty:+g} but the tag books across "
                    f"{', '.join(who)} sum to {sum(tagged.values()):+g} — "
                    f"attribution is ambiguous, refusing to guess")

        # Anything a tag book claims that the account does NOT hold went to zero.
        for name, book in self._live_positions.items():
            for sym, q in book.items():
                if abs(float(q)) > 1e-9 and sym not in account:
                    adopted.setdefault(name, {})
                    changes.append(f"{name}/{sym}: ledger {q:+g} -> broker 0 "
                                   f"(position is not in the account)")

        for name in self._sleeves:
            before = dict(self._live_positions.get(name, {}))
            after = adopted.get(name, {})
            for sym in set(before) | set(after):
                b, a = float(before.get(sym, 0.0)), float(after.get(sym, 0.0))
                if abs(a - b) > 1e-9 and sym in account:
                    changes.append(f"{name}/{sym}: ledger {b:+g} -> broker {a:+g}")

        report = {"ok": not problems, "problems": problems, "changes": changes,
                  "foreign": foreign, "account": account, "adopted": adopted}
        if adopt and not problems:
            self._live_positions = {n: dict(v) for n, v in adopted.items()}
            for name in self._sleeves:
                self._live_positions.setdefault(name, {})
        self._armed = not problems
        self._arm_report = report

        if self.verbose or changes or problems:
            print(f"[ibkr] arm: account has {len(account)} position(s), "
                  f"{len(foreign)} belonging to another book (ignored)")
            for c in changes:
                print(f"[ibkr] arm: ADOPTED broker truth {c}")
            for p in problems:
                print(f"[ibkr] arm: BLOCKED {p}")
            print(f"[ibkr] arm: {'ARMED' if self._armed else 'NOT ARMED'}")
        return report

    def place_targets(self, sleeve_name, targets, asof, market_state) -> list:
        """Diff `targets` vs this sleeve's OWN tag-tracked positions and trade the
        delta. Weight-expressed targets are sized to integer shares first (they
        are NOT dropped). Legs sharing a `combo_id` are grouped into one combo
        order. After sending, the sleeve's tag book is updated from the reported
        fills and the shadow sub-ledger is advanced for NAV/risk/reporting."""
        if self.ib is None:
            raise RuntimeError("IBKRBroker.connect() must be called first")
        if not self._armed:
            raise NotArmed(
                f"refusing to transmit orders for {sleeve_name}: arm() has not "
                f"confirmed the account is explainable by the registered "
                f"sleeves. Diffing targets against an unverified position book "
                f"is what would have doubled both books on 2026-07-31.")
        asof = pd.Timestamp(asof)
        held = dict(self._live_positions.get(sleeve_name, {}))

        desired, pt_by_inst = {}, {}
        for pt in targets:
            q = self._resolve_qty(pt, market_state, asof, sleeve_name)
            if q is None:
                # A weight target we could not price: warn — never drop silently.
                print(f"[ibkr] WARNING {asof.date()} {sleeve_name}: cannot size "
                      f"weight target for {pt.instrument} (no local price); no "
                      f"live order sent for this leg.")
                continue
            desired[pt.instrument] = q
            pt_by_inst[pt.instrument] = pt
        # Held-but-unmentioned -> drive to flat (mirror the sub-ledger).
        for inst, qh in held.items():
            if inst not in desired and abs(float(qh)) > 1e-9:
                desired[inst] = 0.0
                pt_by_inst.setdefault(
                    inst, PositionTarget(instrument=inst, side=FLAT, qty=0.0))

        combos, singles = {}, []
        for inst, tqty in desired.items():
            delta = float(tqty) - float(held.get(inst, 0.0))
            if abs(delta) < 1e-9:
                continue
            pt = pt_by_inst[inst]
            # Bond legs are never BAG combo legs (recon §4) — always singles.
            if pt.combo_id is not None and not self._is_bond(pt):
                combos.setdefault(pt.combo_id, []).append((pt, delta))
            else:
                singles.append((pt, delta))

        fills = []
        for pt, delta in singles:
            if self._is_bond(pt):
                fills.extend(self._place_bond(pt, delta, sleeve_name, asof,
                                              market_state))
                continue
            trade = self.ib.placeOrder(self._contract(pt), self._order(pt, delta))
            fills.extend(self._fills_from_trade(trade, pt, asof))
        for combo_id, legs in combos.items():
            trade = self._place_combo(combo_id, legs, sleeve_name)
            for pt, delta in legs:
                fills.extend(self._fills_from_trade(trade, pt, asof))

        # Update this sleeve's tag book from the reported fills.
        lp = self._live_positions.setdefault(sleeve_name, {})
        for f in fills:
            signed = f.qty if f.side == "BUY" else -f.qty
            lp[f.instrument] = lp.get(f.instrument, 0.0) + signed
            if abs(lp[f.instrument]) < 1e-9:
                lp.pop(f.instrument, None)

        # Advance the shadow sub-ledger (NAV / risk / rollup / reporting). Needs
        # local prices; skipped only when none were supplied (unit stubs).
        prices = getattr(market_state, "prices", None)
        if prices is not None and not getattr(prices, "empty", True):
            try:
                self._shadow().place_targets(sleeve_name, targets, asof, market_state)
            except Exception as exc:
                self._record_desync(sleeve_name, asof, fills, exc)
                raise ShadowLedgerDesync(
                    f"{sleeve_name} @ {pd.Timestamp(asof).date()}: the shadow "
                    f"sub-ledger failed to record {len(fills)} fill(s) that were "
                    f"ALREADY TRANSMITTED to the broker ({exc!r}). The fills are "
                    f"saved to _desync/ and ops/HALT.md is written; the next "
                    f"session will refuse to trade until the ledger is rebuilt.") from exc
        return fills

    def _record_desync(self, sleeve_name, asof, fills, exc):
        """Persist everything a desync would otherwise destroy, then halt the book.

        The orders are gone — they are at the exchange. What we can still save is
        the record of them, which is exactly what the old swallowed handler let
        fall on the floor: the fills lived only in memory and the process exited.
        Three artefacts, in increasing order of how loudly they shout:
          1. `_desync/<sleeve>_<date>.json` — the fills, so the ledger can be
             rebuilt from what actually happened rather than re-derived,
          2. the full traceback, because one repr() line cost us a whole session
             of diagnosis on 2026-07-31,
          3. `ops/HALT.md`, which `ops/preflight.py` reads as a hard gate.
        """
        import json
        import traceback
        from pathlib import Path

        asof = pd.Timestamp(asof)
        root = Path(self._books_root) / "_ibkr_shadow" / "_desync"
        root.mkdir(parents=True, exist_ok=True)
        payload = {
            "sleeve": sleeve_name,
            "asof": str(asof.date()),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "transmitted_fills": [
                {"instrument": f.instrument, "side": f.side, "qty": float(f.qty),
                 "price": float(f.price), "cost_usd": float(f.cost_usd),
                 "asof": str(pd.Timestamp(f.asof).date()), "reason": str(f.reason)}
                for f in fills],
            "tag_book_after_fills": {
                k: float(v) for k, v in
                self._live_positions.get(sleeve_name, {}).items()},
        }
        path = root / f"{sleeve_name}_{asof.date()}.json"
        path.write_text(json.dumps(payload, indent=2))
        print(f"[ibkr] DESYNC {sleeve_name} @ {asof.date()}: shadow ledger did "
              f"NOT record {len(fills)} transmitted fill(s)")
        print(traceback.format_exc())
        print(f"[ibkr] transmitted fills saved to {path}")
        try:
            from ops.halt import write_halt
            write_halt(
                reason=f"shadow ledger desync in {sleeve_name} @ {asof.date()}",
                detail=(f"{exc!r}\n\n{len(fills)} fill(s) were transmitted to the "
                        f"broker but NOT recorded in the shadow sub-ledger. The "
                        f"ledger now understates the account. Rebuild it from "
                        f"{path} (and the broker's execution history) and confirm "
                        f"broker.arm() returns ok before re-arming.\n\n"
                        f"{traceback.format_exc()}"),
                source="ibkr.place_targets")
        except Exception as halt_exc:            # never let alerting mask the fault
            print(f"[ibkr] WARNING could not write HALT record: {halt_exc!r}")

    def _place_combo(self, combo_id, legs, sleeve_name):
        """Group `combo_id` legs into one BAG combo order (atomic fill). The
        order action/quantity is derived from the legs' signed deltas so an
        opening (sell-to-open) straddle and a closing (buy-to-close) roll both
        transmit in the correct direction rather than a hardcoded BUY."""
        ibi = self._ib_insync
        bag = ibi.Contract()
        bag.symbol = (legs[0][0].meta or {}).get("underlier", legs[0][0].instrument)
        bag.secType = "BAG"
        bag.currency = "USD"
        bag.exchange = "SMART"
        combo_legs = []
        for pt, delta in legs:
            con = self._contract(pt)
            leg = ibi.ComboLeg()
            leg.conId = getattr(con, "conId", 0)
            leg.ratio = int(abs(delta)) or 1
            leg.action = "SELL" if delta < 0 else "BUY"
            leg.exchange = "SMART"
            combo_legs.append(leg)
        bag.comboLegs = combo_legs
        # One unit of the BAG; the per-leg ratios carry the size. Direction of
        # the package follows the first leg's delta (all legs of a straddle move
        # together — both sold to open, both bought to close).
        pkg_action = "SELL" if legs[0][1] < 0 else "BUY"
        order = ibi.MarketOrder(pkg_action, 1)
        order.orderRef = str(sleeve_name or "")
        return self.ib.placeOrder(bag, order)

    def snapshot(self, sleeve_name, asof, market_state) -> AccountSnapshot:
        return AccountSnapshot(cash=self.cash(sleeve_name),
                               positions=self.sync_positions(sleeve_name),
                               nav=float("nan"), asof=asof)

    @staticmethod
    def _fills_from_trade(trade, pt, asof, qty_scale=1.0):
        """Fills reported by one trade. `qty_scale` converts broker quantity
        units back to ledger units (bond legs: $1k-face units -> per-100-par
        ledger units); 1.0 for everything else."""
        out = []
        for f in getattr(trade, "fills", []) or []:
            ex = f.execution
            out.append(Fill(instrument=pt.instrument,
                            side="SELL" if float(ex.shares) < 0 or
                                 getattr(ex, "side", "") == "SLD" else "BUY",
                            qty=abs(float(ex.shares)) * float(qty_scale),
                            price=float(ex.price),
                            cost_usd=float(getattr(f.commissionReport, "commission", 0.0)),
                            asof=asof, reason=pt.reason, combo_id=pt.combo_id,
                            kind=pt.kind))
        return out
