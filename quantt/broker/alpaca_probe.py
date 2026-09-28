"""Read-only probe of the Alpaca PAPER accounts: can each book trade what its spec names?

WHY THIS EXISTS
---------------
The move to Alpaca (team lead, 2026-09-28) rests on facts the public docs do not
settle for OUR instruments. Fetched 2026-09-28 from docs.alpaca.markets: no page
mentions closed-end funds at all; `shortable` and `borrow_status`
(easy_to_borrow / hard_to_borrow) are per-asset fields; ETB shorts carry no
borrow fee, HTB shorts need a paid locate; fractional shares cannot be shorted
or sent `cls`. Whether PDI, PTY, NVG... are tradable and shortable at Alpaca is
therefore a per-symbol measurement, and this is the instrument that takes it.
Nothing downstream -- the broker adapter, the sizing, the v7 `max_gross_stress`
re-derivation -- may assume an answer this probe has not recorded.

WHAT IT DOES, AND THE ONE THING IT CANNOT DO
-------------------------------------------
For each book (one Alpaca paper account per book, team lead 2026-09-28) it
GETs the account, its configuration, every spec-universe asset, the open
positions and the open orders, and writes what came back, verbatim, to
`results/ops/alpaca_probe/<date>_<book>.json`. It cannot place, replace or
cancel anything: `_get` is the only function that talks to the network and it
issues GET and nothing else. There is no code path to a POST or DELETE here, and
`test_alpaca_probe.py` fails if one appears.

It refuses to run against anything but the paper endpoint. A live key pointed
at this probe would still only read, but the order path is not the only thing
worth separating: a live account's snapshot is not evidence about a paper one.

CREDENTIALS
-----------
Read from `config/.env` (never committed, never printed): per book,
`ALPACA_<BOOK>_KEY_ID` and `ALPACA_<BOOK>_SECRET_KEY`, e.g. `ALPACA_CEF_KEY_ID`.
Only whether each is SET is ever displayed. A missing key raises naming the
variable, never guessing another account's key: two books sharing one key would
silently put them in one account, which is exactly the wash-trade collision the
per-book accounts exist to prevent.

`borrow_status` CHANGES DAILY. A snapshot from this probe is true on its date
only; the adapter must re-read it before every session that shorts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV_FILE = REPO / "config" / ".env"
OUT_DIR = REPO / "results" / "ops" / "alpaca_probe"

# The only endpoint this probe will talk to. Not configurable on purpose: see
# the module docstring.
PAPER_BASE = "https://paper-api.alpaca.markets"

# Book -> frozen spec. Only the two books the team lead kept (2026-09-28):
# the CEF strategy and the b6 equal-weight credit benchmark.
BOOK_SPECS = {
    "cef": REPO / "ops" / "specs" / "cef_discount.frozen.json",
    "b6": REPO / "ops" / "specs" / "bench_b6_ew_credit.frozen.json",
}

# Asset fields the migration decides on. Shown in the summary as returned, or
# as ABSENT when Alpaca did not send the field -- a missing field is itself a
# finding (the docs list `easy_to_borrow` only in an example payload, not the
# schema), so it is never filled in.
ASSET_FIELDS = ("status", "class", "exchange", "tradable", "shortable",
                "easy_to_borrow", "borrow_status", "marginable",
                "margin_requirement_long", "margin_requirement_short",
                "fractionable")

ACCOUNT_FIELDS = ("status", "currency", "equity", "cash", "buying_power",
                  "multiplier", "shorting_enabled", "trading_blocked",
                  "account_blocked", "transfers_blocked")


class MissingCredential(RuntimeError):
    """A book's Alpaca key is not set. Names the variable, never a value."""


def env_names(book: str) -> tuple[str, str]:
    b = book.upper()
    return f"ALPACA_{b}_KEY_ID", f"ALPACA_{b}_SECRET_KEY"


def load_credentials(book: str, env: dict) -> tuple[str, str]:
    """Return (key_id, secret) for `book` from `env`, or raise naming what is unset.

    `env` is passed in (not read from os.environ here) so the tests can prove
    the refusal without a real `.env` and without touching the process
    environment.
    """
    kid_name, sec_name = env_names(book)
    missing = [n for n in (kid_name, sec_name) if not env.get(n)]
    if missing:
        raise MissingCredential(
            f"book {book!r}: {', '.join(missing)} not set in {ENV_FILE}. "
            f"Each book has its own Alpaca paper account and its own keys; "
            f"no other book's key is substituted.")
    return env[kid_name], env[sec_name]


def read_env_file(path: Path = ENV_FILE) -> dict:
    """The key=value pairs in config/.env, without exporting them to os.environ."""
    if not path.exists():
        raise MissingCredential(f"{path} does not exist")
    from dotenv import dotenv_values
    return {k: v for k, v in dotenv_values(path).items() if v}


def universe(book: str) -> list[str]:
    """The book's tradable names, from its frozen spec -- the only authority.

    The CEF spec is read through `scripts/cef/spec.py` (CLAUDE.md: never read a
    live parameter any other way). The benchmark specs have no accessor module,
    so b6 reads `frozen.universe` from its JSON and raises if it is absent.
    """
    if book == "cef":
        sys.path.insert(0, str(REPO / "scripts" / "cef"))
        import spec  # noqa: E402  (path set just above)
        return list(spec.frozen("universe"))
    d = json.loads(BOOK_SPECS[book].read_text())
    try:
        return list(d["frozen"]["universe"])
    except KeyError as e:
        raise KeyError(f"{BOOK_SPECS[book]} has no frozen.universe") from e


def _get(session, path: str, *, allow_404: bool = False):
    """GET `PAPER_BASE + path`. The ONLY network call in this module.

    Returns the decoded JSON, or None for a 404 when `allow_404` (an asset
    Alpaca does not list is a finding, recorded as such, not an error). Any
    other non-200 raises with the path, status and Alpaca's error body; the
    request headers, which hold the keys, are never included.
    """
    url = PAPER_BASE + path
    if not url.startswith(PAPER_BASE + "/"):
        raise ValueError(f"refusing non-paper URL {url!r}")
    r = session.get(url, timeout=20)
    if r.status_code == 404 and allow_404:
        return None
    if r.status_code != 200:
        raise RuntimeError(f"GET {path} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def probe_book(book: str, session) -> dict:
    """Everything this probe knows about one book's account, as fetched."""
    names = universe(book)
    assets = {}
    for sym in names:
        a = _get(session, f"/v2/assets/{sym}", allow_404=True)
        assets[sym] = a if a is not None else {"_probe": "NOT FOUND AT ALPACA (404)"}
    return {
        "book": book,
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_url": PAPER_BASE,
        "spec": str(BOOK_SPECS[book].relative_to(REPO)),
        "universe": names,
        "account": _get(session, "/v2/account"),
        "account_configurations": _get(session, "/v2/account/configurations"),
        "assets": assets,
        "positions": _get(session, "/v2/positions"),
        "open_orders": _get(session, "/v2/orders?status=open&limit=500"),
    }


def summarise(snap: dict) -> str:
    acct = snap["account"]
    lines = [f"== {snap['book']}  ({snap['fetched_at_utc']}, {snap['base_url']})",
             "account: " + "  ".join(
                 f"{k}={acct[k] if k in acct else 'ABSENT'}" for k in ACCOUNT_FIELDS),
             f"positions: {len(snap['positions'])}   open orders: {len(snap['open_orders'])}",
             "symbol  " + "  ".join(ASSET_FIELDS)]
    for sym, a in snap["assets"].items():
        if "_probe" in a:
            lines.append(f"{sym:<7} {a['_probe']}")
            continue
        lines.append(f"{sym:<7} " + "  ".join(
            f"{a[k] if k in a else 'ABSENT'}" for k in ASSET_FIELDS))
    return "\n".join(lines)


def _session(key_id: str, secret: str):
    import requests
    s = requests.Session()
    # Header names from Alpaca's Trading API authentication docs. A wrong name
    # fails loudly with 401/403 on the first GET; nothing is sent otherwise.
    s.headers.update({"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret})
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--book", choices=[*BOOK_SPECS, "all"], default="all")
    ap.add_argument("--check-keys", action="store_true",
                    help="print only whether each book's keys are SET; no network")
    args = ap.parse_args(argv)
    books = list(BOOK_SPECS) if args.book == "all" else [args.book]
    env = read_env_file()

    if args.check_keys:
        for b in books:
            for n in env_names(b):
                print(f"{n}: {'SET' if env.get(n) else 'NOT SET'}")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rc = 0
    for b in books:
        try:
            kid, sec = load_credentials(b, env)
        except MissingCredential as e:
            print(f"SKIPPED {b}: {e}")
            rc = 2
            continue
        snap = probe_book(b, _session(kid, sec))
        out = OUT_DIR / f"{snap['fetched_at_utc'][:10]}_{b}.json"
        out.write_text(json.dumps(snap, indent=1, sort_keys=True))
        print(summarise(snap))
        print(f"-> {out.relative_to(REPO)}\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
