"""What the twin reads from Alpaca: the clock, the calendar, corporate actions and closing prints. Nothing else.

WHY ALPACA AT ALL (contract §4.7). The books already read their calendar, closing-auction prints
and corporate actions from Alpaca's market data, and the twin must judge a session by the same
clock and score fills against the same official close the Alpaca books are scored on, or the
comparison is not like for like. None of these reads trades.

WHY A FACADE. The reads use an existing book's Alpaca keys (`QUANTT_TWIN_ALPACA_DATA_BOOK`, the
core's on the VM), and an `AlpacaClient` holding those keys can also submit an order to that
book's paper account. So the twin never holds the client: it holds this object, which keeps the
client private and exposes no order method. `quantt/twin/tests/test_no_alpaca_orders.py` proves
the package never names `submit_order` and that this class has no attribute that sends.
"""
from __future__ import annotations

import datetime as dt

ENV_DATA_BOOK = "QUANTT_TWIN_ALPACA_DATA_BOOK"
CONDITION = "M"     # the official close, as the Alpaca books' verify scores (quantt/session/verify.py)


class MarketData:
    __slots__ = ("_client",)

    def __init__(self, client):
        object.__setattr__(self, "_client", client)

    def __setattr__(self, k, v):
        raise AttributeError("MarketData is read-only")

    @classmethod
    def from_environment(cls, env) -> "MarketData":
        book = env.get(ENV_DATA_BOOK, "")
        if not book:
            raise RuntimeError(f"{ENV_DATA_BOOK} is not set: it names the Alpaca book whose keys read "
                               "market data (the twin never trades through them)")
        from quantt.broker.alpaca import AlpacaClient
        return cls(AlpacaClient.from_environment(book))

    def clock(self) -> dict:
        return self._client.clock()

    def calendar(self, start: dt.date, end: dt.date) -> list:
        return self._client.calendar(start, end)

    def corporate_actions(self, *a, **kw):
        return self._client.corporate_actions(*a, **kw)

    def official_closes(self, symbols, day: dt.date):
        """`quantt.session.verify.fetch_prints`: the primary exchange's condition-M print per
        symbol, a gap with the fetcher's reason where there is none (never a bar close)."""
        from quantt.session.verify import fetch_prints
        return fetch_prints(self._client, symbols, day, condition=CONDITION)

    def daily_closes(self, symbols, day: dt.date, utcnow: dt.datetime) -> dict:
        """`quantt.sleeves.prices.closes`: {symbol: daily-bar close of `day`}, for ESTIMATES only
        (sequencing and buying power of a symbol no plan priced); a symbol with no bar is absent."""
        from quantt.sleeves.prices import closes
        return closes(self._client, symbols, day, utcnow)
