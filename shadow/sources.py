"""The two real price sources behind `marks.build`: Alpaca's auction prints, yfinance's close.

WHY A FACADE AND NOT THE CLIENT: `quantt.broker.alpaca.AlpacaClient` can also send an
order to its paper account. A shadow book must not be able to (shadow/__init__.py), so
this module wraps the client in `ReadOnlyData`, which holds it privately and offers only
three read calls. `shadow/tests/test_boundary.py` fails if this package ever names an
order method.

WHICH KEY: the shadow user's own, for an otherwise empty paper account (team lead,
2026-11-09, docs/SYSTEM.md section 5). `book` names it: the client reads
ALPACA_<BOOK>_KEY_ID / _SECRET_KEY from the file QUANTT_ENV_FILE names, and raises if
either is missing. Nothing here prints or returns a credential.

Network imports happen inside the functions, so importing this module opens no socket
(pytest.ini's rule for a collected directory).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

# Alpaca files a dividend under a process date near its PAYABLE date, weeks after the
# ex-date (the client's `distributions` docstring), so an ex-date window is queried this
# many days wider at the end and then filtered on ex_date itself.
DIST_WINDOW_PAD_DAYS = 75


class ReadOnlyData:
    """Auction prints and distributions from Alpaca's data API. Read-only by construction."""

    def __init__(self, book: str):
        from quantt.broker.alpaca import AlpacaClient
        self.__client = AlpacaClient.from_environment(book)
        self.__exchanges = None
        self.__codes: dict = {}

    def prints(self, symbols: list, day: dt.date) -> dict:
        """{symbol: official closing-auction price} for the symbols that have one on `day`.
        A symbol whose primary exchange printed no auction is ABSENT, never filled from
        another venue or a bar close."""
        from quantt.broker.alpaca import MissingAuctionPrint
        c = self.__client
        if self.__exchanges is None:
            self.__exchanges = c.stock_exchanges()
        for s in symbols:
            if s not in self.__codes:
                self.__codes[s] = c.primary_sip_code(s, self.__exchanges)
        want = list(symbols)
        try:
            got = c.closing_auction_prints(want, day, exchange_codes={s: self.__codes[s] for s in want})
        except MissingAuctionPrint as e:
            want = [s for s in want if s not in set(e.symbols)]
            if not want:
                return {}
            # the second call names only symbols the first did not report missing
            got = c.closing_auction_prints(want, day, exchange_codes={s: self.__codes[s] for s in want})
        return {s: float(v["price"]) for s, v in got.items()}

    def distributions(self, symbols: list, first: dt.date, last: dt.date) -> list:
        evs = self.__client.distributions(list(symbols), first,
                                          last + dt.timedelta(days=DIST_WINDOW_PAD_DAYS))
        return [{"symbol": e["symbol"], "ex_date": e["ex_date"], "amount": e["amount"]}
                for e in evs if first <= e["ex_date"] <= last]

    def sessions(self, first: dt.date, last: dt.date) -> list:
        """Trading days from the exchange calendar Alpaca serves."""
        return [dt.date.fromisoformat(str(r["date"])[:10]) for r in self.__client.calendar(first, last)]


def yfinance_closes(symbols: list, first: dt.date, last: dt.date) -> pd.DataFrame:
    """Unadjusted daily closes, long: [date, symbol, close]. The CHECK source only.
    A symbol yfinance returns nothing for is simply absent, and `marks.build` then
    reports its rows as unchecked."""
    import yfinance as yf
    raw = yf.download(sorted(set(symbols)), start=first.isoformat(),
                      end=(last + dt.timedelta(days=1)).isoformat(),
                      auto_adjust=False, progress=False, group_by="column", threads=False)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "symbol", "close"])
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(sorted(set(symbols))[0])
    out = close.stack().rename("close").reset_index()
    out.columns = ["date", "symbol", "close"]
    out["date"] = pd.to_datetime(out["date"]).dt.date
    return out.dropna(subset=["close"])
