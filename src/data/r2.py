"""Cloudflare R2 (WRDS mirror) access via DuckDB httpfs.

Usage:
    from src.data.r2 import connect, r2_path, q
    con = connect()
    df = q(con, f"SELECT * FROM read_parquet('{r2_path('ff_all', 'factors_daily')}') LIMIT 3")

Credentials live in config/.env at the repo root (never committed):
    R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
Shorter aliases R2_KEY_ID / R2_SECRET are also accepted.
"""

import os
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

# Repo root = parent of src/ (this file is src/data/r2.py), so imports work
# no matter which directory the caller runs from (repo root, scripts/, etc.).
REPO_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_BUCKET = "quantt-historical-market-data"


def _load_env() -> None:
    """Load credentials from config/.env (absolute path first, then relative fallbacks)."""
    load_dotenv(REPO_ROOT / "config" / ".env")
    load_dotenv("config/.env")  # fallback if the module was vendored elsewhere
    load_dotenv()               # plain .env in cwd, lowest precedence


def _env(*names: str, default: str | None = None) -> str | None:
    """First non-empty environment variable among `names`."""
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


def connect() -> duckdb.DuckDBPyConnection:
    """Return an in-memory DuckDB connection configured to read the R2 bucket."""
    _load_env()
    endpoint = _env("R2_ENDPOINT")
    key_id = _env("R2_ACCESS_KEY_ID", "R2_KEY_ID")
    secret = _env("R2_SECRET_ACCESS_KEY", "R2_SECRET")
    if not (endpoint and key_id and secret):
        raise RuntimeError(
            "Missing R2 credentials: set R2_ENDPOINT, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY in config/.env"
        )

    con = duckdb.connect()
    # DuckDB wants the endpoint host only (no scheme); R2 needs path-style URLs.
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_endpoint = '{endpoint.replace('https://', '')}';")
    con.execute(f"SET s3_access_key_id = '{key_id}';")
    con.execute(f"SET s3_secret_access_key = '{secret}';")
    con.execute("SET s3_region = 'auto';")
    con.execute("SET s3_url_style = 'path';")
    return con


def r2_path(schema: str, table: str) -> str:
    """S3 path of a mirrored WRDS parquet table, e.g. r2_path('tr_ds_fut', 'wrds_fut_series')."""
    _load_env()
    bucket = _env("R2_BUCKET", default=_DEFAULT_BUCKET)
    return f"s3://{bucket}/wrds/{schema}/{table}.parquet"


def q(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    """Run SQL on the given connection and return a pandas DataFrame."""
    return con.execute(sql).df()
