"""The Alpaca REST client for the runner: reads the paper account, sends one kind of order.

WHY THIS EXISTS, AND WHY IT IS THIS SMALL
-----------------------------------------
`docs/RUNNER.md` gives this module one job: be the only thing in `quantt/` that
speaks HTTP to Alpaca, and decide nothing. The session (`quantt/session/run.py`)
decides what to send and whether the gates allow it; `verify.py` decides what a
fill means. This client turns Alpaca's JSON into checked Python and back, and it
refuses every shape it was not built for. Two failure histories shape it:

  * Confident wrong numbers. The IBKR-era book once sized every displayed target
    against an invented $500k equity because a missing field had a default
    (CLAUDE.md). Alpaca documents only `id` and `status` as required on the
    account (docs, fetched 2026-09-28), and sends every number as a string. So
    every field the runner reads is required here, parsed here, and a missing or
    unparseable one raises naming the endpoint and the field. There is no
    `.get(field, default)` on any value that reaches a decision.
  * The doubled book. The trade phase is not idempotent and the broker does not
    dedupe: `client_order_id` is unique only among ACTIVE orders (Alpaca Learn,
    [V] 2026-09-28), and an open MOC order is not yet a position. A client that
    "helpfully" retried a POST after a read timeout could put a second copy of
    the order into the same auction. So `submit_order` is called once and never
    retried by this module; a transport failure after the request may have left
    raises `AmbiguousSubmit`, whose message tells the caller to look the id up
    with `order_by_client_id` and never to resend blind.

WHAT IT WILL NOT DO
-------------------
  * Talk to anything but `https://paper-api.alpaca.markets` for trading and
    `https://data.alpaca.markets` for market data. Neither is configurable to
    another value: the constructor raises, and `submit_order` checks again,
    because a live endpoint anywhere is a test failure (RUNNER.md).
  * Send anything but `type=market, time_in_force=cls` (CLAUDE.md order-path
    rule 3: overnight market orders realised 100.5bp against a 32.6bp
    breakeven on 2026-07-31). There is no parameter for either. If Alpaca
    rejects `cls` -- Alpaca Learn says OPG/CLS are "only available to Elite
    Smart Router users" and nobody has yet shown what paper does [U] -- the
    rejection is raised as `OrderRejected`; nothing falls back to `day`.
  * Send a fractional or non-positive quantity. Alpaca cannot short fractions
    or send them `cls` [V: docs]; the sign of a trade lives in `side`, never in
    a negative qty.
  * Cancel or replace. There is no DELETE or PATCH in this module; the runner's
    design does not need one, and a cancel path is a second way to lose track of
    what is headed for the auction.
  * Retry a write. Only GETs retry, on 429/5xx/transport errors, a bounded
    number of times, because a GET changes nothing at the broker.

CREDENTIALS
-----------
Loaded with `dotenv_values` from the file the caller names -- in the runner,
the path in the required env var `QUANTT_ENV_FILE` (`from_environment`) -- as
`ALPACA_<BOOK>_KEY_ID` / `ALPACA_<BOOK>_SECRET_KEY`. They go into the HTTP
session's headers and nowhere else: not an attribute, not `repr`, not a log
line, not an exception message (every message is scrubbed of both values
before it is raised, in case Alpaca ever echoes a header back). A missing key
raises naming the variable; another book's key is never substituted, because
two books on one key would share one account, which is the wash-trade
collision the per-book accounts exist to prevent (CLAUDE.md landmine 2).

Uncertain API facts are coded defensively, never assumed: see the docstrings of
`positions` (short qty sign), `orders` (time-cursor pagination), `calendar`
(timezone) and `closing_auction_prints` (which print is "the" official close).
Source for every [V]/[S]/[U] claim: `results/ops/ALPACA_API_FACTS_2026-09-28.md`.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

from quantt.broker.alpaca_probe import MissingCredential, env_names

NY = ZoneInfo("America/New_York")   # the exchange clock; auction windows are ET days

# The only two hosts this client will ever address. Not configurable on
# purpose: the constructor accepts the arguments RUNNER.md names so a caller
# can SAY which endpoint it expects, and raises if that is anything else.
PAPER_BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"

# GET retry schedule, seconds slept BEFORE attempts 2..N. Five attempts, about
# a minute in total: Alpaca throttles at "200 requests per minute, per account"
# [S: support page dated Dec 2022], so a 429 can need most of a minute to
# clear. Bounded, because the session has a 15:45 ET deadline to meet and a
# client that retries forever turns a broker outage into a silent miss.
GET_BACKOFF_S = (2, 5, 15, 30)

# (connect, read) timeout for every request. A read timeout on a GET is retried;
# on the POST it is AmbiguousSubmit.
TIMEOUT_S = (10, 30)

ORDERS_MAX_LIMIT = 500          # GET /v2/orders: "limit ... max 500" [V]
FILL_PAGE_SIZE = 100            # GET /v2/account/activities: page_size max 100 [V]
AUCTIONS_MAX_LIMIT = 10000      # GET /v2/stocks/auctions: limit max 10000 [V]
MAX_PAGES = 1000                # a pagination loop that runs this long is a bug, not data

# Symbols as Alpaca writes US equities (e.g. PDI, BRK.B). Anything else is
# refused before it can reach a URL path or an order.
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
# client_order_id: Alpaca documents only "<= 128 characters" [V]; the allowed
# characters are undocumented [U]. The runner's ids are
# `cef-<YYYYMMDD>-<SYMBOL>-<leg>`, so this conservative set is all it needs,
# and anything outside it is refused rather than discovered at the broker.
_CID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HHMM_RE = re.compile(r"^\d{2}:\d{2}$")


# --------------------------------------------------------------------- errors

class AlpacaError(RuntimeError):
    """Base for everything this client raises about Alpaca. Messages never hold a key."""


class UnexpectedResponse(AlpacaError):
    """Alpaca answered 2xx with a body this client was not built for (a missing
    field, a wrong type, a sign conflict). Raised instead of guessing."""


class AlpacaHTTPError(AlpacaError):
    """A non-2xx answer to a GET (after retries, for the retryable ones)."""

    def __init__(self, msg: str, *, status: int | None):
        super().__init__(msg)
        self.status = status


class AssetNotFound(AlpacaHTTPError):
    """GET /v2/assets/<sym> returned 404: Alpaca does not list the symbol."""


class OrderRejected(AlpacaError):
    """Alpaca answered the POST with a 4xx: the order was NOT accepted.

    `status` and `body` are Alpaca's (e.g. 403 buying power / wash trade, 422
    duplicate client_order_id). Whether and how to try again is the session's
    decision, never this client's.
    """

    def __init__(self, msg: str, *, status: int, client_order_id: str):
        super().__init__(msg)
        self.status = status
        self.client_order_id = client_order_id


class AmbiguousSubmit(AlpacaError):
    """The POST may or may not have reached Alpaca: a timeout, a dropped
    connection, a 5xx, or an unreadable 2xx body.

    The one thing the caller must not do is send it again: if the first copy
    was accepted, the second fills in the same auction and the position
    doubles (CLAUDE.md order-path rule 2). Look the id up with
    `order_by_client_id`; only an answer of "not found" says it did not land.
    """

    def __init__(self, msg: str, *, client_order_id: str):
        super().__init__(msg)
        self.client_order_id = client_order_id


class SubmitResponseInvalid(AlpacaError):
    """Alpaca ACCEPTED the order (2xx) but echoed something other than what was
    sent -- a different symbol, side, qty, type or time_in_force. The order
    exists at the broker; do not resend. Stop and look at it."""

    def __init__(self, msg: str, *, client_order_id: str, order_id: str | None):
        super().__init__(msg)
        self.client_order_id = client_order_id
        self.order_id = order_id


class MissingAuctionPrint(AlpacaError):
    """No official closing-auction print for these symbols on the date asked.
    A bar close is never substituted: it is updated by condition 6, not M
    [V: bars reference], and is not the same number."""

    def __init__(self, msg: str, *, symbols: list[str]):
        super().__init__(msg)
        self.symbols = symbols


class AmbiguousAuctionPrint(AlpacaError):
    """The primary exchange reported the requested condition at more than one
    price (Alpaca shows each price/exchange/condition triplet once [V], so one
    exchange CAN appear twice with different prices)."""


class UnmappedExchange(AlpacaError):
    """A symbol's primary listing exchange could not be turned into exactly one
    SIP exchange code. Raised rather than scoring against another venue."""


# Asset `exchange` (GET /v2/assets) -> the exact NAME that GET
# /v2/stocks/meta/exchanges gives that market; the live endpoint then supplies
# the code. ONLY verified pairs are here:
#   * every name in the book's universe has asset exchange "NYSE" [V: probe
#     results/ops/alpaca_probe/2026-09-28_cef.json, all 17 names];
#   * "N": "New York Stock Exchange" is the example in Alpaca's reference for
#     /v2/stocks/meta/exchanges [V: docs.alpaca.markets/us/reference/
#     stockmetaexchanges-1, fetched 2026-09-28].
# Any other asset exchange raises UnmappedExchange: a name that moves listing
# needs a new, sourced row here, never a guessed one.
ASSET_EXCHANGE_SIP_NAME = {"NYSE": "New York Stock Exchange"}


# ------------------------------------------------------------ small parsers

def _require(obj: dict, fields, where: str) -> None:
    if not isinstance(obj, dict):
        raise UnexpectedResponse(f"{where}: expected a JSON object, got {type(obj).__name__}")
    missing = [f for f in fields if f not in obj]
    if missing:
        raise UnexpectedResponse(f"{where}: missing field(s) {missing}")


def _num(obj: dict, field: str, where: str) -> float:
    """A numeric field Alpaca sends as a string (or number). None/''/junk raises."""
    v = obj[field]
    if v is None or isinstance(v, bool):
        raise UnexpectedResponse(f"{where}: field {field!r} is {v!r}, not a number")
    try:
        return float(Decimal(str(v)))
    except InvalidOperation:
        raise UnexpectedResponse(f"{where}: field {field!r} = {v!r} is not a number") from None


def _whole(obj: dict, field: str, where: str) -> int:
    """A share count that must be a whole number (the runner never holds a fraction)."""
    v = obj[field]
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise UnexpectedResponse(f"{where}: field {field!r} = {v!r} is not a number") from None
    if v is None or isinstance(v, bool) or d != d.to_integral_value():
        raise UnexpectedResponse(f"{where}: field {field!r} = {v!r} is not a whole number of shares")
    return int(d)


def _bool(obj: dict, field: str, where: str) -> bool:
    v = obj[field]
    if not isinstance(v, bool):
        raise UnexpectedResponse(f"{where}: field {field!r} = {v!r} is not a JSON boolean")
    return v


def parse_ts(s, where: str) -> dt.datetime:
    """RFC-3339 -> aware datetime. Alpaca can send nanoseconds, which
    `fromisoformat` rejects, so the fraction is cut to microseconds. A
    timestamp with no offset raises: a naive time is a guess about the zone."""
    if not isinstance(s, str):
        raise UnexpectedResponse(f"{where}: timestamp {s!r} is not a string")
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$", s)
    if not m:
        raise UnexpectedResponse(f"{where}: timestamp {s!r} is not RFC-3339 with an offset")
    frac = (m.group(2) or "")[:7]          # '.' + at most 6 digits
    off = "+00:00" if m.group(3) == "Z" else m.group(3)
    return dt.datetime.fromisoformat(m.group(1) + frac + off)


def _iso_param(v, name: str) -> str:
    """A time filter for Alpaca. Aware datetimes and RFC-3339 strings pass;
    a naive datetime raises rather than being read in some default zone."""
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            raise ValueError(f"{name}={v!r} is naive; pass a timezone-aware datetime")
        return v.isoformat()
    if isinstance(v, str):
        parse_ts(v, name)
        return v
    raise ValueError(f"{name}={v!r} must be an aware datetime or an RFC-3339 string")


def _date_param(v, name: str) -> dt.date:
    if isinstance(v, dt.datetime) or not isinstance(v, dt.date):
        raise ValueError(f"{name}={v!r} must be a datetime.date")
    return v


class Positions(NamedTuple):
    """`qty` is {symbol: signed whole shares}, long > 0, short < 0; `raw` is
    Alpaca's list as received, for the record."""
    qty: dict
    raw: list


# ---------------------------------------------------------------- the client

class AlpacaClient:
    """One book's Alpaca paper account. See the module docstring for the rules."""

    def __init__(self, book: str, env_file, base_url: str = PAPER_BASE,
                 data_url: str = DATA_BASE, *, session=None, sleep=time.sleep):
        # Exact equality, not startswith: "https://paper-api.alpaca.markets.evil"
        # and a trailing path both start with the paper host.
        if base_url != PAPER_BASE:
            raise ValueError(f"refusing trading endpoint {base_url!r}: this client "
                             f"talks only to the paper endpoint {PAPER_BASE}")
        if data_url != DATA_BASE:
            raise ValueError(f"refusing data endpoint {data_url!r}: expected {DATA_BASE}")
        if not isinstance(book, str) or not re.fullmatch(r"[a-z0-9]+", book):
            raise ValueError(f"book {book!r} must be a lowercase name like 'cef'")
        self.book = book
        self._base = base_url
        self._data = data_url
        self._sleep = sleep
        key_id, secret = _load_keys(book, Path(env_file))
        if session is None:
            import requests
            session = requests.Session()
        # Header names from Alpaca's authentication docs [V]. The keys live
        # here and only here; `_scrub` reads them back from this dict.
        session.headers.update({"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret})
        self._session = session

    @classmethod
    def from_environment(cls, book: str, **kw) -> "AlpacaClient":
        """The runner's constructor: keys from the file named by QUANTT_ENV_FILE,
        which is required (RUNNER.md) -- an unset variable raises rather than
        falling back to `config/.env`, so a prod clone never silently reads a
        dev tree's keys."""
        path = os.environ.get("QUANTT_ENV_FILE", "")
        if not path:
            raise MissingCredential("QUANTT_ENV_FILE is not set: it must name the file "
                                    "holding this book's Alpaca keys")
        return cls(book, path, **kw)

    def __repr__(self) -> str:
        return f"AlpacaClient(book={self.book!r}, base_url={self._base!r}, data_url={self._data!r})"

    __str__ = __repr__

    # ------------------------------------------------------------ transport

    def _scrub(self, text: str) -> str:
        """Remove both key values from any text before it leaves this object."""
        for h in ("APCA-API-KEY-ID", "APCA-API-SECRET-KEY"):
            v = self._session.headers.get(h)
            if v:
                text = text.replace(v, "<redacted>")
        return text

    def _get(self, base: str, path: str, params: dict | None = None, *,
             allow_404: bool = False):
        """GET with bounded retry on 429, 5xx and transport errors.

        Retrying is safe only because a GET changes nothing at the broker; the
        POST path never comes through here. Returns decoded JSON, or None for a
        404 when `allow_404`. Any other non-200, or a body that is not JSON,
        raises with the path and Alpaca's message -- never the request headers.
        """
        import requests
        url = base + path
        attempts = len(GET_BACKOFF_S) + 1
        last = ""
        for i in range(attempts):
            if i:
                self._sleep(GET_BACKOFF_S[i - 1])
            try:
                r = self._session.get(url, params=params, timeout=TIMEOUT_S)
            except (requests.Timeout, requests.ConnectionError) as e:
                last = f"{type(e).__name__}: {e}"
                status = None
                continue
            status = r.status_code
            if status == 404 and allow_404:
                return None
            if status == 429 or 500 <= status < 600:
                last = f"HTTP {status}: {r.text[:300]}"
                continue
            if status != 200:
                cls = AssetNotFound if (status == 404 and path.startswith("/v2/assets/")) else AlpacaHTTPError
                raise cls(self._scrub(f"GET {path} -> HTTP {status}: {r.text[:300]}"), status=status)
            try:
                return r.json()
            except ValueError:
                raise UnexpectedResponse(self._scrub(
                    f"GET {path} -> HTTP 200 with a body that is not JSON: {r.text[:300]}")) from None
        raise AlpacaHTTPError(self._scrub(
            f"GET {path} failed after {attempts} attempts; last: {last}"), status=status)

    # -------------------------------------------------------------- account

    ACCOUNT_NUMERIC = ("equity", "last_equity", "cash", "buying_power", "regt_buying_power",
                       "initial_margin", "maintenance_margin", "long_market_value",
                       "short_market_value")
    ACCOUNT_BOOL = ("shorting_enabled", "trading_blocked", "account_blocked",
                    "trade_suspended_by_user")

    def account(self) -> dict:
        """GET /v2/account, every field the runner may read required and parsed.

        Returns {"id", "status", "currency", "multiplier" (str: 1|2|4 [V]),
        the ACCOUNT_NUMERIC fields as float, the ACCOUNT_BOOL fields as bool,
        "raw"}. Alpaca marks only id/status required [V], but all of these were
        present in the 2026-09-28 probe of the cef account; if one ever goes
        missing the session must stop, not size against a default.
        `equity` is "cash + long_market_value + short_market_value" [V].
        """
        raw = self._get(self._base, "/v2/account")
        w = "GET /v2/account"
        _require(raw, ("id", "status", "currency", "multiplier",
                       *self.ACCOUNT_NUMERIC, *self.ACCOUNT_BOOL), w)
        out = {"id": raw["id"], "status": raw["status"], "currency": raw["currency"],
               "multiplier": str(raw["multiplier"]), "raw": raw}
        out.update({f: _num(raw, f, w) for f in self.ACCOUNT_NUMERIC})
        out.update({f: _bool(raw, f, w) for f in self.ACCOUNT_BOOL})
        return out

    def positions(self) -> Positions:
        """GET /v2/positions -> Positions(qty={symbol: signed int}, raw=[...]).

        The sign comes from `side` (long|short, documented [V]); the docs do not
        say whether `qty` is itself negative for a short [U, open question]. So
        a short with qty "-100" or "100" both become -100, and the one
        combination that is a contradiction under either convention -- a
        negative qty on a `long` -- raises. A fractional or zero qty raises: the
        runner only ever sends whole shares, so either is something it did not
        do and must not trade on top of. A symbol listed twice raises.
        """
        raw = self._get(self._base, "/v2/positions")
        if not isinstance(raw, list):
            raise UnexpectedResponse(f"GET /v2/positions: expected a list, got {type(raw).__name__}")
        qty: dict[str, int] = {}
        for i, p in enumerate(raw):
            w = f"GET /v2/positions[{i}]"
            _require(p, ("symbol", "qty", "side"), w)
            sym, side = p["symbol"], p["side"]
            n = _whole(p, "qty", f"{w} ({sym})")
            if n == 0:
                raise UnexpectedResponse(f"{w}: {sym} listed with qty 0")
            if side == "long":
                if n < 0:
                    raise UnexpectedResponse(f"{w}: {sym} side=long but qty={p['qty']!r} is negative")
                signed = n
            elif side == "short":
                signed = -abs(n)
            else:
                raise UnexpectedResponse(f"{w}: {sym} side={side!r} is not long|short")
            if sym in qty:
                raise UnexpectedResponse(f"GET /v2/positions: {sym} listed twice")
            qty[sym] = signed
        return Positions(qty=qty, raw=raw)

    # --------------------------------------------------------------- orders

    ORDER_FIELDS = ("id", "client_order_id", "status", "symbol", "side", "type",
                    "time_in_force", "submitted_at", "filled_qty")

    def orders(self, *, status: str, after=None, until=None,
               limit: int = ORDERS_MAX_LIMIT, nested: bool = False) -> list[dict]:
        """GET /v2/orders, every page, oldest first.

        `status` has no default on purpose (Alpaca's is `open` [V]): gate 6 asks
        "any order TODAY", which is `all`, and a silent `open` would hide an
        order that already filled. `after`/`until` filter on submission time,
        exclusive [V].

        Alpaca has no page token here [V]. This pages by time with
        `direction=asc` and `after=<cursor>`. The trap: `after` is exclusive, so
        advancing the cursor to the LAST order's `submitted_at` would skip any
        order that shares that timestamp but fell past the page boundary. So
        the cursor goes back to the last timestamp STRICTLY earlier than the
        page's final one, the overlap is re-fetched, and orders are deduplicated
        by id. A full page whose orders all share one timestamp cannot be paged
        without that risk, and raises. A page not in ascending order raises
        (the method's correctness rests on it). `before_order_id` /
        `after_order_id` are not used: they may not be combined with after/until [V].
        """
        if status not in ("open", "closed", "all"):
            raise ValueError(f"status={status!r} must be open|closed|all")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= ORDERS_MAX_LIMIT:
            raise ValueError(f"limit={limit!r} must be an int in 1..{ORDERS_MAX_LIMIT}")
        base = {"status": status, "limit": limit, "direction": "asc",
                "nested": "true" if nested else "false"}
        if until is not None:
            base["until"] = _iso_param(until, "until")
        cursor = _iso_param(after, "after") if after is not None else None
        cursor_dt = parse_ts(cursor, "after") if cursor else None

        out: list[dict] = []
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            params = dict(base)
            if cursor is not None:
                params["after"] = cursor
            page = self._get(self._base, "/v2/orders", params)
            if not isinstance(page, list):
                raise UnexpectedResponse(f"GET /v2/orders: expected a list, got {type(page).__name__}")
            times = []
            for i, o in enumerate(page):
                w = f"GET /v2/orders[{i}]"
                _require(o, self.ORDER_FIELDS, w)
                times.append(parse_ts(o["submitted_at"], f"{w}.submitted_at"))
                if o["id"] not in seen:
                    seen.add(o["id"])
                    out.append(o)
            if any(b < a for a, b in zip(times, times[1:])):
                raise UnexpectedResponse("GET /v2/orders: page not in ascending submitted_at "
                                         "order; time-cursor pagination would skip orders")
            if len(page) < limit:
                return out
            last = times[-1]
            earlier = [(t, o["submitted_at"]) for t, o in zip(times, page) if t < last]
            if not earlier:
                raise UnexpectedResponse(
                    f"GET /v2/orders: a full page of {limit} orders all submitted at "
                    f"{page[-1]['submitted_at']}; cannot page on time without skipping")
            new_dt, new_cursor = earlier[-1]
            if cursor_dt is not None and new_dt <= cursor_dt:
                raise UnexpectedResponse("GET /v2/orders: pagination made no progress")
            cursor, cursor_dt = new_cursor, new_dt
        raise UnexpectedResponse(f"GET /v2/orders: more than {MAX_PAGES} pages")

    def order_by_client_id(self, client_order_id: str) -> dict | None:
        """The order with this client_order_id, or None if Alpaca has none (404).

        This is how an AmbiguousSubmit is resolved, so the two answers must
        never be confused: 404 -> None, and every other failure (401, 5xx after
        retries, a body with a different id) raises. Behaviour when an id was
        reused after a fill is undocumented [U]; the runner never reuses one.
        """
        if not isinstance(client_order_id, str) or not _CID_RE.match(client_order_id):
            raise ValueError(f"client_order_id {client_order_id!r} is not a valid id")
        o = self._get(self._base, "/v2/orders:by_client_order_id",
                      {"client_order_id": client_order_id}, allow_404=True)
        if o is None:
            return None
        w = "GET /v2/orders:by_client_order_id"
        _require(o, self.ORDER_FIELDS, w)
        if o["client_order_id"] != client_order_id:
            raise UnexpectedResponse(f"{w}: asked for {client_order_id!r}, got "
                                     f"{o['client_order_id']!r}")
        return o

    def submit_order(self, symbol: str, qty: int, side: str, client_order_id: str) -> dict:
        """POST /v2/orders: one market-on-close order. Called once; never retried here.

        Always `type=market, time_in_force=cls` (CLAUDE.md rule 3; there is no
        argument for either). `qty` is a positive Python int -- a float, even
        100.0, is refused, because a float qty is how a fraction gets in. The
        refusals happen before anything is sent.

        Outcomes:
          2xx, echo matches          -> the order dict
          2xx, echo differs          -> SubmitResponseInvalid (the order EXISTS)
          4xx                        -> OrderRejected (not accepted)
          5xx / timeout / connection
          error / unreadable 2xx     -> AmbiguousSubmit (look it up; never resend)
        A 5xx is ambiguous rather than rejected because a gateway can fail
        after the order service has accepted the order.
        """
        # --- refusals: nothing has been sent yet -------------------------
        if self._base != PAPER_BASE:                   # constructor checks too; belt and braces
            raise ValueError(f"refusing to submit to non-paper endpoint {self._base!r}")
        if not isinstance(symbol, str) or not _SYMBOL_RE.match(symbol):
            raise ValueError(f"symbol {symbol!r} is not an upper-case equity symbol")
        if type(qty) is not int or qty <= 0:
            raise ValueError(f"qty {qty!r} must be a positive int (whole shares; "
                             f"the side carries the sign)")
        if side not in ("buy", "sell"):
            raise ValueError(f"side {side!r} must be 'buy' or 'sell'")
        if not isinstance(client_order_id, str) or not _CID_RE.match(client_order_id):
            raise ValueError(f"client_order_id {client_order_id!r} must be 1-128 of [A-Za-z0-9._-]")

        import requests
        payload = {"symbol": symbol, "qty": str(qty), "side": side, "type": "market",
                   "time_in_force": "cls", "client_order_id": client_order_id}
        cid = client_order_id
        look = f"look it up with order_by_client_id({cid!r}); do NOT resend"
        try:
            r = self._session.post(PAPER_BASE + "/v2/orders", json=payload, timeout=TIMEOUT_S)
        except (requests.Timeout, requests.ConnectionError) as e:
            raise AmbiguousSubmit(self._scrub(
                f"POST /v2/orders {cid}: {type(e).__name__} -- the order may or may not "
                f"be at Alpaca; {look}"), client_order_id=cid) from None
        status = r.status_code
        if 400 <= status < 500:
            raise OrderRejected(self._scrub(
                f"POST /v2/orders {cid} ({side} {qty} {symbol} cls) rejected: "
                f"HTTP {status}: {r.text[:300]}"), status=status, client_order_id=cid)
        if not 200 <= status < 300:
            raise AmbiguousSubmit(self._scrub(
                f"POST /v2/orders {cid}: HTTP {status}: {r.text[:300]} -- {look}"),
                client_order_id=cid)
        try:
            o = r.json()
        except ValueError:
            raise AmbiguousSubmit(self._scrub(
                f"POST /v2/orders {cid}: HTTP {status} with an unreadable body -- {look}"),
                client_order_id=cid) from None

        # --- the order exists; check Alpaca recorded what we sent ---------
        w = f"POST /v2/orders {cid}"
        oid = o.get("id") if isinstance(o, dict) else None
        problems = []
        if not isinstance(o, dict):
            problems.append(f"body is {type(o).__name__}, not an object")
        else:
            for f, want in (("client_order_id", cid), ("symbol", symbol), ("side", side),
                            ("type", "market"), ("time_in_force", "cls")):
                if o.get(f) != want:
                    problems.append(f"{f}={o.get(f)!r} (sent {want!r})")
            try:
                if Decimal(str(o.get("qty"))) != qty:
                    problems.append(f"qty={o.get('qty')!r} (sent {qty})")
            except InvalidOperation:
                problems.append(f"qty={o.get('qty')!r} (sent {qty})")
            if not oid:
                problems.append("no order id")
        if problems:
            raise SubmitResponseInvalid(self._scrub(
                f"{w}: Alpaca ACCEPTED an order (HTTP {status}) but " + "; ".join(problems)
                + f" -- the order exists; {look}"), client_order_id=cid, order_id=oid)
        return o

    # ---------------------------------------------------------- clock etc.

    def clock(self) -> dict:
        """GET /v2/clock -> {"timestamp", "next_open", "next_close" (aware
        datetimes), "is_open" (bool), "raw"}.

        `is_open` means the market is open RIGHT NOW [V], not "today is a
        trading day"; gate 4 should use `calendar` for the latter.
        """
        raw = self._get(self._base, "/v2/clock")
        w = "GET /v2/clock"
        _require(raw, ("timestamp", "is_open", "next_open", "next_close"), w)
        return {"timestamp": parse_ts(raw["timestamp"], f"{w}.timestamp"),
                "is_open": _bool(raw, "is_open", w),
                "next_open": parse_ts(raw["next_open"], f"{w}.next_open"),
                "next_close": parse_ts(raw["next_close"], f"{w}.next_close"),
                "raw": raw}

    def calendar(self, start: dt.date, end: dt.date) -> list[dict]:
        """GET /v2/calendar for [start, end] inclusive [V] ->
        [{"date": date, "open": "HH:MM", "close": "HH:MM", "raw"}].

        `open`/`close` are returned as Alpaca's wall-clock strings and NOT
        attached to a timezone: the docs do not state one [U]. Presumably ET;
        the caller that turns them into a cutoff must say so explicitly. A day
        outside the range asked for raises.
        """
        start, end = _date_param(start, "start"), _date_param(end, "end")
        if end < start:
            raise ValueError(f"end {end} is before start {start}")
        raw = self._get(self._base, "/v2/calendar",
                        {"start": start.isoformat(), "end": end.isoformat()})
        if not isinstance(raw, list):
            raise UnexpectedResponse(f"GET /v2/calendar: expected a list, got {type(raw).__name__}")
        out = []
        for i, row in enumerate(raw):
            w = f"GET /v2/calendar[{i}]"
            _require(row, ("date", "open", "close"), w)
            if not (isinstance(row["date"], str) and _DATE_RE.match(row["date"])):
                raise UnexpectedResponse(f"{w}: date {row['date']!r} is not YYYY-MM-DD")
            d = dt.date.fromisoformat(row["date"])
            if not start <= d <= end:
                raise UnexpectedResponse(f"{w}: {d} is outside the requested {start}..{end}")
            for f in ("open", "close"):
                if not (isinstance(row[f], str) and _HHMM_RE.match(row[f])):
                    raise UnexpectedResponse(f"{w}: {f} {row[f]!r} is not HH:MM")
            out.append({"date": d, "open": row["open"], "close": row["close"], "raw": row})
        return out

    ASSET_BOOL = ("tradable", "shortable", "marginable", "fractionable")

    def asset(self, symbol: str) -> dict:
        """GET /v2/assets/<symbol>, required fields present and typed; the raw
        dict is returned. 404 raises AssetNotFound.

        `borrow_status` (easy_to_borrow|hard_to_borrow [V]) is checked against
        its enum when present but not required, and `easy_to_borrow` is not
        read: only the former is in the schema [V]. Whether gate 7 needs
        `easy_to_borrow` status as well as `shortable` is a team-lead question.
        Both change daily; a result is true on its date only.
        """
        if not isinstance(symbol, str) or not _SYMBOL_RE.match(symbol):
            raise ValueError(f"symbol {symbol!r} is not an upper-case equity symbol")
        raw = self._get(self._base, f"/v2/assets/{symbol}")
        w = f"GET /v2/assets/{symbol}"
        _require(raw, ("symbol", "status", "exchange", *self.ASSET_BOOL), w)
        for f in self.ASSET_BOOL:
            _bool(raw, f, w)
        if raw["symbol"] != symbol:
            raise UnexpectedResponse(f"{w}: returned symbol {raw['symbol']!r}")
        if "borrow_status" in raw and raw["borrow_status"] not in ("easy_to_borrow", "hard_to_borrow"):
            raise UnexpectedResponse(f"{w}: borrow_status {raw['borrow_status']!r} is not a documented value")
        return raw

    FILL_FIELDS = ("id", "activity_type", "order_id", "symbol", "side", "qty", "price",
                   "cum_qty", "leaves_qty", "transaction_time", "type", "order_status")

    def activities_fills(self, date: dt.date) -> list[dict]:
        """GET /v2/account/activities/FILL for one date, every page, oldest first.

        Pages with `page_token` = the id of the last row [V], `page_size` 100
        (the max [V]); a short page ends it, a repeated token raises. `date`
        filters on created_at, not settlement [V]. Rows are returned raw after
        their fields are checked; `qty`/`price` stay strings for the caller to
        parse with its own provenance. Partial fills are expected on paper
        ("a random size 10% of the time" [V]).
        """
        date = _date_param(date, "date")
        out, seen, token = [], set(), None
        for _ in range(MAX_PAGES):
            params = {"date": date.isoformat(), "direction": "asc", "page_size": FILL_PAGE_SIZE}
            if token is not None:
                params["page_token"] = token
            page = self._get(self._base, "/v2/account/activities/FILL", params)
            if not isinstance(page, list):
                raise UnexpectedResponse(f"GET /v2/account/activities/FILL: expected a list, "
                                         f"got {type(page).__name__}")
            for i, a in enumerate(page):
                w = f"GET /v2/account/activities/FILL[{i}]"
                _require(a, self.FILL_FIELDS, w)
                if a["activity_type"] != "FILL":
                    raise UnexpectedResponse(f"{w}: activity_type {a['activity_type']!r}")
                if a["type"] not in ("fill", "partial_fill"):
                    raise UnexpectedResponse(f"{w}: type {a['type']!r} is not fill|partial_fill")
                if a["id"] not in seen:
                    seen.add(a["id"])
                    out.append(a)
            if len(page) < FILL_PAGE_SIZE:
                return out
            nxt = page[-1]["id"]
            if nxt == token:
                raise UnexpectedResponse("GET /v2/account/activities/FILL: page_token did not advance")
            token = nxt
        raise UnexpectedResponse(f"GET /v2/account/activities/FILL: more than {MAX_PAGES} pages")

    # ---------------------------------------------------------- market data

    def stock_exchanges(self) -> dict:
        """GET {DATA_BASE}/v2/stocks/meta/exchanges: {SIP code: exchange name} [V,
        schema "additionalProperties: string"]. Every key and value must be a
        non-empty string; any other shape raises (including a wrapped object,
        which the reference does not show -- first live read is [U])."""
        w = "GET /v2/stocks/meta/exchanges"
        body = self._get(self._data, "/v2/stocks/meta/exchanges")
        if not isinstance(body, dict) or not body:
            raise UnexpectedResponse(f"{w}: expected a non-empty object, got "
                                     f"{type(body).__name__}")
        for k, v in body.items():
            if not (isinstance(k, str) and k and isinstance(v, str) and v):
                raise UnexpectedResponse(f"{w}: entry {k!r}: {v!r} is not code -> name strings")
        return dict(body)

    def primary_sip_code(self, symbol: str, exchanges: dict) -> str:
        """The SIP exchange code of `symbol`'s primary listing, today.

        WHY. "On open/on close orders are routed to the primary exchange" [V],
        so the official closing-auction print is the PRIMARY exchange's.
        Several market centers publish a condition-M "official close" each day
        [V], and on a day the primary had no auction trade another venue's M
        print may be the only one -- accepting it would score fills against a
        price the order never saw. Asset `exchange` -> name
        (ASSET_EXCHANGE_SIP_NAME) -> code (`exchanges`, from
        `stock_exchanges()`), with exactly one match or UnmappedExchange.
        The asset is read today; a listing move between the session and
        verify is not detected [U].
        """
        ex = self.asset(symbol)["exchange"]
        name = ASSET_EXCHANGE_SIP_NAME.get(ex)
        if name is None:
            raise UnmappedExchange(f"{symbol}: asset exchange {ex!r} has no verified SIP "
                                   f"name in ASSET_EXCHANGE_SIP_NAME")
        codes = sorted(k for k, v in exchanges.items() if v == name)
        if len(codes) != 1:
            raise UnmappedExchange(f"{symbol}: {len(codes)} SIP codes named {name!r} in "
                                   f"/v2/stocks/meta/exchanges ({codes}); need exactly one")
        return codes[0]

    def closing_auction_prints(self, symbols, date: dt.date, *, exchange_codes: dict,
                               condition: str = "M") -> dict:
        """The official closing-auction print per symbol on `date`, from the data API.

        GET {DATA_BASE}/v2/stocks/auctions, feed=sip ("Only sip is valid for
        auctions" [V]), start=end=date, every page. Returns
        {symbol: {"price": float, "exchange": x, "condition": c, "t": str}}.

        WHICH PRINT. Alpaca returns several closing prints per day from
        different exchanges [V]. `condition` defaults to "M", "Market Center
        Official Close" in Alpaca's condition table [V]; "6" is "Market Center
        Closing Trade" (M vs 6 is still a design choice [U]). `exchange_codes`
        is REQUIRED and must name the primary listing's SIP code for every
        symbol (`primary_sip_code`); only that exchange's prints count.
        (Review 2026-09-28: the first build accepted any exchange's print when
        they agreed, so a day the primary had no auction scored against
        another venue's close -- a confident wrong number.)

        A symbol with no matching print from its primary exchange raises
        MissingAuctionPrint naming every such symbol: another venue's print
        and a daily bar close are never substituted. Two prices from the
        primary at `condition` raise AmbiguousAuctionPrint.
        """
        date = _date_param(date, "date")
        if isinstance(symbols, str):
            raise ValueError("symbols must be a list of symbols, not one string")
        syms = sorted(set(symbols))
        if not syms:
            raise ValueError("symbols is empty")
        for s in syms:
            if not isinstance(s, str) or not _SYMBOL_RE.match(s):
                raise ValueError(f"symbol {s!r} is not an upper-case equity symbol")
        if not isinstance(exchange_codes, dict):
            raise ValueError("exchange_codes must be {symbol: primary SIP code}")
        no_code = [s for s in syms if not (isinstance(exchange_codes.get(s), str)
                                           and exchange_codes[s])]
        if no_code:
            raise ValueError(f"no primary-exchange SIP code for {no_code}; another venue's "
                             f"print is never used")

        # EXPLICIT TIMESTAMPS, NOT A BARE DATE. With end=<date> Alpaca reads the
        # window as running up to now, and the Basic plan refuses any SIP query
        # that touches the last 15 minutes: HTTP 403 "subscription does not
        # permit querying recent SIP data", for every symbol, every day [V: run
        # 2026-09-28 19:50 ET against the cef paper account]. The same query
        # with start/end as timestamps returned the day's prints. The window is
        # the whole ET calendar day up to 16:30 ET -- the closing auction prints
        # at 16:00 (13:00 on an early close), and verify runs at 17:30, so the
        # end is always more than 15 minutes old by then.
        start_ts = dt.datetime.combine(date, dt.time(0, 0), NY).astimezone(dt.timezone.utc)
        end_ts = dt.datetime.combine(date, dt.time(16, 30), NY).astimezone(dt.timezone.utc)
        days: dict[str, list] = {}
        token = None
        for _ in range(MAX_PAGES):
            params = {"symbols": ",".join(syms),
                      "start": start_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "end": end_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "feed": "sip", "limit": AUCTIONS_MAX_LIMIT}
            if token is not None:
                params["page_token"] = token
            body = self._get(self._data, "/v2/stocks/auctions", params)
            w = "GET /v2/stocks/auctions"
            _require(body, ("auctions",), w)
            auctions = body["auctions"]
            if auctions is None:           # a page with no data at all
                auctions = {}
            if not isinstance(auctions, dict):
                raise UnexpectedResponse(f"{w}: auctions is {type(auctions).__name__}, not an object")
            for sym, rows in auctions.items():
                if sym not in syms:
                    raise UnexpectedResponse(f"{w}: returned unrequested symbol {sym!r}")
                if not isinstance(rows, list):
                    raise UnexpectedResponse(f"{w}: auctions[{sym}] is not a list")
                days.setdefault(sym, []).extend(rows)
            nxt = body.get("next_page_token")
            if not nxt:
                break
            if nxt == token:
                raise UnexpectedResponse(f"{w}: next_page_token did not advance")
            token = nxt
        else:
            raise UnexpectedResponse(f"GET /v2/stocks/auctions: more than {MAX_PAGES} pages")

        out, missing = {}, []
        for sym in syms:
            prints = []
            for j, day in enumerate(days.get(sym, [])):
                w = f"GET /v2/stocks/auctions {sym}[{j}]"
                _require(day, ("d",), w)
                # `d` is documented as the date [V]; its exact format is not
                # shown, so only its first ten characters are compared.
                if not (isinstance(day["d"], str) and _DATE_RE.match(day["d"][:10])):
                    raise UnexpectedResponse(f"{w}: d {day['d']!r} does not start with YYYY-MM-DD")
                if day["d"][:10] != date.isoformat():
                    raise UnexpectedResponse(f"{w}: day {day['d']!r} is not the requested {date}")
                closes = day.get("c") or []
                if not isinstance(closes, list):
                    raise UnexpectedResponse(f"{w}: c is not a list")
                for k, p in enumerate(closes):
                    _require(p, ("t", "x", "p", "c"), f"{w}.c[{k}]")
                    if p["c"] == condition:
                        prints.append(p)
            prints = [p for p in prints if p["x"] == exchange_codes[sym]]
            if not prints:
                missing.append(sym)
                continue
            prices = {_num(p, "p", f"auction {sym}") for p in prints}
            if len(prices) > 1:
                pairs = sorted((p["x"], p["p"]) for p in prints)
                raise AmbiguousAuctionPrint(
                    f"{sym} {date}: primary exchange {exchange_codes[sym]!r} has more than one "
                    f"condition {condition!r} price {pairs}")
            p = prints[0]
            out[sym] = {"price": prices.pop(), "exchange": p["x"], "condition": p["c"],
                        "t": p["t"]}
        if missing:
            raise MissingAuctionPrint(
                f"no closing-auction print with condition {condition!r} on {date} for "
                f"{missing} from the primary exchange "
                f"{ {s: exchange_codes[s] for s in missing} }; another venue's print and a bar "
                f"close are not substituted", symbols=missing)
        return out


def _load_keys(book: str, env_file: Path) -> tuple[str, str]:
    """(key_id, secret) for `book` from `env_file`, or raise naming what is unset.

    Reads with `dotenv_values`, which does not export to os.environ, so a key
    loaded for one book is never visible to code reading another's. The
    message names the file and the variables, never a value.
    """
    if not env_file.is_file():
        raise MissingCredential(f"Alpaca key file {env_file} does not exist")
    from dotenv import dotenv_values
    env = dotenv_values(env_file)
    kid_name, sec_name = env_names(book)
    missing = [n for n in (kid_name, sec_name) if not env.get(n)]
    if missing:
        raise MissingCredential(
            f"book {book!r}: {', '.join(missing)} not set in {env_file}. Each book has "
            f"its own Alpaca paper account and keys; no other book's key is substituted.")
    return env[kid_name], env[sec_name]
