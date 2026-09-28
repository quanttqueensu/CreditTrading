"""Read-only access to the team's Cloudflare R2 bucket (a WRDS mirror) through DuckDB.

WHAT THIS IS FOR, AND WHAT IT IS NEVER FOR
------------------------------------------
The research and backtest departments read CRSP, TRACE, Fama-French, FRB rates
and the options tick archive from R2 (layout in `docs/DATA.md`). The LIVE book
never does: the sleeve decides on `data/cef/*.parquet`, refreshed by
`scripts/cef/fetch_daily.py` from yfinance + CEFConnect. R2 is a mirror that is
refreshed on WRDS's schedule, not ours -- CRSP daily lands in annual/quarterly
vintages -- so a session that read it would be deciding on a panel whose last
date nobody on the desk controls. `docs/RUNNER.md` makes it a module boundary:
nothing under `quantt/` imports this module, and `tests/test_r2.py` fails if
anything does.

WHY IT WAS REBUILT (2026-09-28)
-------------------------------
The pre-clean-slate version (`git show pre-clean-slate:src/data/r2.py`) had
three silent fallbacks, each of which the house rules forbid:

  * the bucket name DEFAULTED to a literal when `R2_BUCKET` was unset, so a
    mis-set environment read whatever bucket that literal named and nothing
    said so;
  * it called `load_dotenv()` three times -- repo `config/.env`, then
    `./config/.env` relative to the CWD, then a bare `.env` in the CWD -- so
    which credentials were used depended on where the caller happened to be
    standing, and it EXPORTED them into `os.environ`, where every child
    process and every crash dump could see them;
  * it accepted alias names (`R2_KEY_ID`, `R2_SECRET`) as second choices, so
    two half-configured files could combine into one working-looking config.

It also configured DuckDB with `SET s3_access_key_id = '<key>'` statements. A
SET is a global setting: it applies to every S3 URL the connection touches,
not just our bucket. This version uses one TEMPORARY secret SCOPED to
`s3://<bucket>`, which DuckDB keeps in memory only (a PERSISTENT secret would
be written to disk under ~/.duckdb in plain text) and which `duckdb_secrets()`
shows with the secret redacted.

THE CONTRACT NOW
----------------
  * The env file is `$QUANTT_ENV_FILE` if that variable is set and non-empty,
    else `<repo>/config/.env` -- both absolute, neither CWD-relative. The
    file must exist; it is read with `dotenv_values` (never exported to
    `os.environ`), and `os.environ` is NOT consulted for the R2_* values, so
    there is exactly one place a credential can come from.
  * Every one of `REQUIRED_VARS` must be present and non-empty. A missing one
    raises `R2ConfigError` naming the variable(s) and the file -- never a
    value. There are no aliases and no defaults.
  * No function here prints, logs or returns a credential. `R2Config.__repr__`
    redacts the key and secret so a stray `print(cfg)` or a traceback's
    locals cannot leak them.
  * Only reads. DuckDB's `read_parquet` over httpfs issues GET/HEAD; nothing
    here writes to the bucket, and `tests/test_r2.py` fails if a `COPY ... TO`
    or a write-capable statement appears in this file.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

# Repo root = parent of src/ (this file is src/data/r2.py). Absolute, so the
# answer does not depend on the caller's working directory.
REPO = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO / "config" / ".env"
ENV_FILE_VAR = "QUANTT_ENV_FILE"

# Exactly these names; no aliases (see module docstring, third fallback).
REQUIRED_VARS = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")

# S3 bucket-name rule (3-63 chars of lowercase letters, digits, dot, hyphen).
# Checked because the bucket is interpolated into every SQL path string; a
# value outside this set is either a typo or something that should not be in
# a SQL literal.
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")
# WRDS schema/table names on the mirror, and option underlyings. Same reason:
# they go into a SQL string, so they are validated rather than escaped.
_IDENT_RE = re.compile(r"^[a-z0-9_]+$")
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class R2ConfigError(RuntimeError):
    """The R2 configuration is missing or malformed. Names what, never a value."""


@dataclass(frozen=True)
class R2Config:
    """The four values a connection needs. The repr never shows the key or secret."""

    endpoint_host: str
    bucket: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    source: Path = field(default=DEFAULT_ENV_FILE)

    def __repr__(self) -> str:  # explicit, so a future field cannot leak by default
        return (f"R2Config(endpoint_host={self.endpoint_host!r}, bucket={self.bucket!r}, "
                f"access_key_id=<redacted>, secret_access_key=<redacted>, "
                f"source={str(self.source)!r})")


def env_file_path(environ: "dict | os._Environ | None" = None) -> Path:
    """The one env file credentials may come from.

    `$QUANTT_ENV_FILE` when set and non-empty (the laptop prod clone and the
    session runner set it, docs/RUNNER.md), else `<repo>/config/.env`. This is
    the path the task contract names explicitly, not a search: exactly one
    candidate is ever looked at, and a missing file raises rather than moving
    on to another.
    """
    environ = os.environ if environ is None else environ
    raw = environ.get(ENV_FILE_VAR)
    path = Path(raw).expanduser() if raw else DEFAULT_ENV_FILE
    if not path.is_absolute():
        # A relative path would resolve against the CWD -- the exact
        # where-am-I-standing dependence this rebuild removed.
        raise R2ConfigError(f"{ENV_FILE_VAR} must be an absolute path; got a relative one")
    return path


def _read_env(path: Path) -> dict:
    """key=value pairs from `path`, NOT exported to os.environ."""
    if not path.exists():
        raise R2ConfigError(f"env file {path} does not exist (set {ENV_FILE_VAR} or create it)")
    from dotenv import dotenv_values  # imported here: keep module import cheap
    return {k: v for k, v in dotenv_values(path).items() if v}


def _endpoint_host(endpoint: str) -> str:
    """R2_ENDPOINT -> the bare host DuckDB's ENDPOINT wants.

    Accepts `https://<acct>.r2.cloudflarestorage.com` or the bare host. Refuses
    `http://` (credentials over plaintext) and any path component (DuckDB
    would build URLs under it and every read would 404 with a message that
    does not mention the endpoint). Error messages never echo the value.
    """
    s = endpoint.strip()
    if "://" in s:
        parts = urlsplit(s)
        if parts.scheme != "https":
            raise R2ConfigError("R2_ENDPOINT must use https:// (or be a bare host)")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise R2ConfigError("R2_ENDPOINT must be a host only, with no path or query")
        host = parts.netloc
    else:
        host = s.rstrip("/")
        if "/" in host:
            raise R2ConfigError("R2_ENDPOINT must be a host only, with no path")
    if not host or "'" in host or " " in host:
        raise R2ConfigError("R2_ENDPOINT does not look like a host name")
    return host


def load_config(environ: "dict | os._Environ | None" = None) -> R2Config:
    """Build the config from the env file, or raise naming every missing variable."""
    path = env_file_path(environ)
    env = _read_env(path)
    missing = [n for n in REQUIRED_VARS if not env.get(n)]
    if missing:
        raise R2ConfigError(
            f"{', '.join(missing)} not set in {path}. All of {', '.join(REQUIRED_VARS)} "
            "are required; there are no defaults and no alias names.")
    bucket = env["R2_BUCKET"].strip()
    if not _BUCKET_RE.match(bucket):
        raise R2ConfigError("R2_BUCKET is not a valid S3 bucket name")
    return R2Config(endpoint_host=_endpoint_host(env["R2_ENDPOINT"]), bucket=bucket,
                    access_key_id=env["R2_ACCESS_KEY_ID"].strip(),
                    secret_access_key=env["R2_SECRET_ACCESS_KEY"].strip(), source=path)


def check_keys(environ: "dict | os._Environ | None" = None) -> dict[str, bool]:
    """Which REQUIRED_VARS are set in the env file -- booleans only, no network.

    The CLAUDE.md way to test a key: print whether it is set, never its value.
    """
    env = _read_env(env_file_path(environ))
    return {n: bool(env.get(n)) for n in REQUIRED_VARS}


def _sql_str(v: str) -> str:
    """A SQL string literal. DuckDB's CREATE SECRET takes no bound parameters."""
    return "'" + v.replace("'", "''") + "'"


def connect(config: R2Config | None = None):
    """An in-memory DuckDB connection that can read `s3://<bucket>/...`.

    httpfs is LOADed, not INSTALLed: INSTALL would download an extension from
    the network as a side effect of opening a connection. If it is not
    installed, this raises and says so; installing it is a deliberate step.
    """
    import duckdb
    cfg = config if config is not None else load_config()
    con = duckdb.connect()
    try:
        con.execute("LOAD httpfs")
    except duckdb.Error as exc:
        con.close()
        raise R2ConfigError(
            "DuckDB httpfs extension is not installed; run once, deliberately: "
            "python3 -c \"import duckdb; duckdb.connect().execute('INSTALL httpfs')\"") from exc
    # TEMPORARY: in memory only, never written to ~/.duckdb. SCOPE: applies to
    # our bucket and nothing else. URL_STYLE path + REGION auto: what R2's S3
    # API needs (Cloudflare R2 docs, S3 compatibility).
    con.execute(
        "CREATE TEMPORARY SECRET quantt_r2 ("
        " TYPE s3,"
        f" KEY_ID {_sql_str(cfg.access_key_id)},"
        f" SECRET {_sql_str(cfg.secret_access_key)},"
        f" ENDPOINT {_sql_str(cfg.endpoint_host)},"
        " REGION 'auto',"
        " URL_STYLE 'path',"
        f" SCOPE {_sql_str('s3://' + cfg.bucket)})")
    return con


def r2_path(schema: str, table: str, config: R2Config | None = None) -> str:
    """`s3://<bucket>/wrds/<schema>/<table>.parquet` for a mirrored WRDS table."""
    for name, v in (("schema", schema), ("table", table)):
        if not _IDENT_RE.match(v):
            raise ValueError(f"{name} {v!r} is not a lowercase WRDS identifier")
    cfg = config if config is not None else load_config()
    return f"s3://{cfg.bucket}/wrds/{schema}/{table}.parquet"


def options_path(symbol: str, month: str, config: R2Config | None = None) -> str:
    """`s3://<bucket>/options/<SYM>/tick/<YYYY-MM>.parquet` for one month of ticks."""
    if not _SYMBOL_RE.match(symbol):
        raise ValueError(f"symbol {symbol!r} is not an upper-case ticker")
    if not _MONTH_RE.match(month):
        raise ValueError(f"month {month!r} is not YYYY-MM")
    cfg = config if config is not None else load_config()
    return f"s3://{cfg.bucket}/options/{symbol}/tick/{month}.parquet"


def q(con, sql: str, params: list | None = None):
    """Run SQL (with optional bound parameters) and return a pandas DataFrame."""
    return (con.execute(sql, params) if params is not None else con.execute(sql)).df()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R2 (WRDS mirror) access; read-only.")
    ap.add_argument("--check-keys", action="store_true",
                    help="print only whether each R2_* variable is SET; no network")
    args = ap.parse_args(argv)
    if not args.check_keys:
        ap.print_help()
        return 2
    print(f"env file: {env_file_path()}")
    for name, is_set in check_keys().items():
        print(f"{name:<22} {'SET' if is_set else 'NOT SET'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
