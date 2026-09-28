"""The R2 access module takes credentials from one place, requires all of them,
never leaks one, only reads, and is never reachable from the live path.

Plus the pure logic of the two research scripts built on it
(`scripts/data/r2_catalog.py`, `scripts/data/cef_crosscheck_crsp.py`).

Every property here was a real defect in the pre-clean-slate module (see the
`src/data/r2.py` docstring) or is the kind that rots silently: a default bucket
name, a CWD-relative `.env`, an alias that half-configures, a `SET` that scopes
the key to every S3 URL. Hermetic: env files live in tmp_path, DuckDB runs in
memory against local parquet, and the root conftest's netguard fails any test
that opens a socket.
"""
from __future__ import annotations

import ast
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from src.data import r2

REPO = Path(__file__).resolve().parents[3]
KEY = "AKIA-key-id-that-must-never-appear"
SECRET = "secret-that-must-never-appear"
GOOD = {
    "R2_ENDPOINT": "https://acct123.r2.cloudflarestorage.com",
    "R2_ACCESS_KEY_ID": KEY,
    "R2_SECRET_ACCESS_KEY": SECRET,
    "R2_BUCKET": "test-bucket",
}


def _envfile(tmp_path: Path, values: dict) -> dict:
    p = tmp_path / "test.env"
    p.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    return {r2.ENV_FILE_VAR: str(p)}


# --------------------------------------------------------------------------
# Where credentials come from
# --------------------------------------------------------------------------

def test_env_file_is_quantt_env_file_when_set(tmp_path):
    environ = _envfile(tmp_path, GOOD)
    assert r2.env_file_path(environ) == tmp_path / "test.env"
    cfg = r2.load_config(environ)
    assert cfg.bucket == "test-bucket" and cfg.source == tmp_path / "test.env"


def test_env_file_defaults_to_repo_config_not_cwd(tmp_path, monkeypatch):
    # The path only -- this test never opens the real file. Run from another
    # directory so a CWD-relative default cannot coincide with the repo path.
    monkeypatch.chdir(tmp_path)
    assert r2.env_file_path({}) == REPO / "config" / ".env"
    assert r2.env_file_path({r2.ENV_FILE_VAR: ""}) == REPO / "config" / ".env"


def test_relative_env_file_refused():
    with pytest.raises(r2.R2ConfigError, match="absolute"):
        r2.env_file_path({r2.ENV_FILE_VAR: "config/.env"})


def test_missing_env_file_raises(tmp_path):
    with pytest.raises(r2.R2ConfigError, match="does not exist"):
        r2.load_config({r2.ENV_FILE_VAR: str(tmp_path / "nope.env")})


@pytest.mark.parametrize("var", r2.REQUIRED_VARS)
def test_each_missing_var_raises_naming_it(tmp_path, var):
    vals = {k: v for k, v in GOOD.items() if k != var}
    with pytest.raises(r2.R2ConfigError) as ei:
        r2.load_config(_envfile(tmp_path, vals))
    msg = str(ei.value)
    assert var in msg
    assert KEY not in msg and SECRET not in msg


def test_bucket_has_no_default(tmp_path):
    """The old module defaulted the bucket to a literal. Now: raise."""
    vals = dict(GOOD, R2_BUCKET="")
    with pytest.raises(r2.R2ConfigError, match="R2_BUCKET"):
        r2.load_config(_envfile(tmp_path, vals))


def test_alias_names_not_accepted(tmp_path):
    vals = {k: v for k, v in GOOD.items() if k not in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")}
    vals.update({"R2_KEY_ID": KEY, "R2_SECRET": SECRET})
    with pytest.raises(r2.R2ConfigError, match="R2_ACCESS_KEY_ID"):
        r2.load_config(_envfile(tmp_path, vals))


def test_process_environment_is_not_consulted(tmp_path, monkeypatch):
    """One source only: a var in os.environ does not fill a gap in the file."""
    monkeypatch.setenv("R2_BUCKET", "from-os-environ")
    vals = {k: v for k, v in GOOD.items() if k != "R2_BUCKET"}
    with pytest.raises(r2.R2ConfigError, match="R2_BUCKET"):
        r2.load_config(_envfile(tmp_path, vals))


def test_env_file_is_not_exported_to_os_environ(tmp_path, monkeypatch):
    import os
    for k in GOOD:
        monkeypatch.delenv(k, raising=False)
    r2.load_config(_envfile(tmp_path, GOOD))
    assert not any(k in os.environ for k in GOOD)


# --------------------------------------------------------------------------
# Validation of what goes into SQL
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ep,host", [
    ("https://acct.r2.cloudflarestorage.com", "acct.r2.cloudflarestorage.com"),
    ("https://acct.r2.cloudflarestorage.com/", "acct.r2.cloudflarestorage.com"),
    ("acct.r2.cloudflarestorage.com", "acct.r2.cloudflarestorage.com"),
])
def test_endpoint_host(ep, host):
    assert r2._endpoint_host(ep) == host


@pytest.mark.parametrize("ep", ["http://acct.r2.cloudflarestorage.com",
                                "https://acct.r2.cloudflarestorage.com/some/path",
                                "acct.r2.cloudflarestorage.com/path", "a'b"])
def test_bad_endpoint_refused(ep):
    with pytest.raises(r2.R2ConfigError):
        r2._endpoint_host(ep)


@pytest.mark.parametrize("bucket", ["Upper", "a", "has space", "x'y"])
def test_bad_bucket_refused(tmp_path, bucket):
    with pytest.raises(r2.R2ConfigError, match="R2_BUCKET"):
        r2.load_config(_envfile(tmp_path, dict(GOOD, R2_BUCKET=bucket)))


def test_paths(tmp_path):
    cfg = r2.load_config(_envfile(tmp_path, GOOD))
    assert r2.r2_path("crsp_a_stock", "dsf", cfg) == "s3://test-bucket/wrds/crsp_a_stock/dsf.parquet"
    assert r2.options_path("SPY", "2024-06", cfg) == "s3://test-bucket/options/SPY/tick/2024-06.parquet"
    for bad in [("crsp a", "dsf"), ("crsp", "dsf'; --"), ("CRSP", "dsf")]:
        with pytest.raises(ValueError):
            r2.r2_path(*bad, cfg)
    with pytest.raises(ValueError):
        r2.options_path("spy", "2024-06", cfg)
    with pytest.raises(ValueError):
        r2.options_path("SPY", "2024-13", cfg)


# --------------------------------------------------------------------------
# No leaks
# --------------------------------------------------------------------------

def test_repr_redacts_credentials(tmp_path):
    cfg = r2.load_config(_envfile(tmp_path, GOOD))
    s = repr(cfg) + str(cfg)
    assert KEY not in s and SECRET not in s and "redacted" in s


def test_check_keys_prints_booleans_only(tmp_path, monkeypatch, capsys):
    environ = _envfile(tmp_path, dict(GOOD, R2_BUCKET=""))
    assert r2.check_keys(environ) == {"R2_ENDPOINT": True, "R2_ACCESS_KEY_ID": True,
                                      "R2_SECRET_ACCESS_KEY": True, "R2_BUCKET": False}
    monkeypatch.setenv(r2.ENV_FILE_VAR, environ[r2.ENV_FILE_VAR])
    assert r2.main(["--check-keys"]) == 0
    out = capsys.readouterr().out
    assert KEY not in out and SECRET not in out and "acct123" not in out
    assert "NOT SET" in out


# --------------------------------------------------------------------------
# The DuckDB connection: a scoped, in-memory secret, not global SETs
# --------------------------------------------------------------------------

def test_connect_creates_temporary_scoped_secret(tmp_path):
    cfg = r2.load_config(_envfile(tmp_path, GOOD))
    con = r2.connect(cfg)
    rows = con.execute("SELECT name, type, persistent, scope, secret_string "
                       "FROM duckdb_secrets()").fetchall()
    assert len(rows) == 1
    name, typ, persistent, scope, s = rows[0]
    assert typ == "s3" and persistent is False
    assert scope == ["s3://test-bucket"]
    assert SECRET not in s                   # DuckDB redacts it
    assert "endpoint=acct123.r2.cloudflarestorage.com" in s
    assert "url_style=path" in s and "region=auto" in s
    # No global key setting, which would apply to every S3 URL.
    assert con.execute("SELECT current_setting('s3_access_key_id')").fetchone()[0] in ("", None)


def test_secret_with_quote_is_escaped_not_injected(tmp_path):
    cfg = r2.load_config(_envfile(tmp_path, dict(GOOD, R2_SECRET_ACCESS_KEY="ab'c")))
    con = r2.connect(cfg)
    assert len(con.execute("SELECT * FROM duckdb_secrets()").fetchall()) == 1


def _exec_sql_literals(path: Path) -> list[str]:
    """The string pieces of every `.execute(...)` first argument in `path`."""
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute" and node.args):
            for sub in ast.walk(node.args[0]):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.append(sub.value.upper())
    return out


@pytest.mark.parametrize("rel", ["src/data/r2.py", "scripts/data/r2_catalog.py",
                                 "scripts/data/cef_crosscheck_crsp.py"])
def test_sql_is_read_only_and_never_global(rel):
    """Only reads; no global `SET s3_*`, no network INSTALL, no on-disk secret."""
    lits = " ".join(_exec_sql_literals(REPO / rel))
    assert lits, "no execute() calls found -- the scan is broken"
    for bad in ("SET S3_", "COPY ", "INSERT ", "INSTALL ", "PERSISTENT", "ATTACH ",
                "CREATE TABLE", "EXPORT "):
        assert bad not in lits, (rel, bad)


def test_r2_never_calls_load_dotenv():
    """load_dotenv exports into os.environ; only dotenv_values is allowed."""
    tree = ast.parse((REPO / "src" / "data" / "r2.py").read_text())
    names = {n.attr if isinstance(n, ast.Attribute) else n.id
             for n in ast.walk(tree) if isinstance(n, (ast.Name, ast.Attribute))}
    assert "load_dotenv" not in names and "dotenv_values" in names


def test_live_path_never_imports_r2():
    """docs/RUNNER.md: src/data/r2.py is never imported by quantt/ or the sleeve."""
    offenders = []
    roots = [REPO / "quantt", REPO / "src" / "deploy"]
    for root in roots:
        for f in root.rglob("*.py"):
            tree = ast.parse(f.read_text(), filename=str(f))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
                if any(m == "src.data" or m.startswith("src.data.") or m.startswith("scripts.data")
                       for m in mods):
                    offenders.append(str(f.relative_to(REPO)))
    assert not offenders, offenders


# --------------------------------------------------------------------------
# scripts/data/r2_catalog.py -- against a local "bucket"
# --------------------------------------------------------------------------

def _local_bucket(tmp_path: Path) -> str:
    base = tmp_path / "bucket"
    (base / "wrds" / "ff_all").mkdir(parents=True)
    (base / "wrds" / "crsp_a_stock").mkdir(parents=True)
    pd.DataFrame({"date": pd.to_datetime(["2020-01-02", "2020-01-03", "2021-06-30"]).date,
                  "mktrf": [0.1, 0.2, 0.3]}).to_parquet(base / "wrds/ff_all/factors_daily.parquet")
    pd.DataFrame({"permno": [1, 2], "datestr": ["20200102", "20200103"]}).to_parquet(
        base / "wrds/crsp_a_stock/dsf.parquet")
    return str(base)


def test_catalog_describe_measures_rows_and_date_range(tmp_path):
    from scripts.data import r2_catalog as rc
    base = _local_bucket(tmp_path)
    con = duckdb.connect()
    t = rc.describe_table(con, base, "ff_all", "factors_daily")
    assert t.present and t.rows == 3 and t.error is None
    assert t.date_ranges == {"date": ("2020-01-02", "2021-06-30")}
    assert ("mktrf", "DOUBLE") in t.columns


def test_catalog_does_not_parse_string_dates(tmp_path):
    from scripts.data import r2_catalog as rc
    con = duckdb.connect()
    t = rc.describe_table(con, _local_bucket(tmp_path), "crsp_a_stock", "dsf")
    assert t.present and t.date_ranges == {}
    md = rc.render("T", {}, [t])
    assert "no DATE/TIMESTAMP-typed column" in md


def test_catalog_absent_table_is_a_finding_and_fails_run(tmp_path, monkeypatch):
    from scripts.data import r2_catalog as rc
    base = _local_bucket(tmp_path)
    con = duckdb.connect()
    t = rc.describe_table(con, base, "frb_all", "rates_daily")
    assert not t.present
    monkeypatch.setattr(rc, "LIST_SCHEMAS", ("ff_all",))
    monkeypatch.setattr(rc, "OPTION_SYMBOLS", ())
    monkeypatch.setattr(rc, "CURATED", (("ff_all", "factors_daily"), ("frb_all", "rates_daily")))
    md, ok = rc.run(con, base, "2026-09-28 00:00:00")
    assert ok is False and "**ABSENT**" in md
    monkeypatch.setattr(rc, "CURATED", (("ff_all", "factors_daily"),))
    md, ok = rc.run(con, base, "2026-09-28 00:00:00")
    assert ok is True and "wrds/ff_all/factors_daily.parquet" in md


def test_catalog_enumerates_option_underlyings(tmp_path):
    from scripts.data import r2_catalog as rc
    base = tmp_path / "bucket"
    for sym, months in {"SPY": ["2014-06", "2026-07"], "HYG": ["2020-01"]}.items():
        (base / "options" / sym / "tick").mkdir(parents=True)
        for m in months:
            pd.DataFrame({"x": [1]}).to_parquet(base / "options" / sym / "tick" / f"{m}.parquet")
    got = rc.list_option_underlyings(duckdb.connect(), str(base))
    assert got == {"HYG": (1, "2020-01", "2020-01"), "SPY": (2, "2014-06", "2026-07")}


def test_catalog_redacts_bucket():
    from scripts.data import r2_catalog as rc
    assert rc._redact("s3://real-bucket/wrds/x.parquet", "s3://real-bucket") == \
        "s3://<bucket>/wrds/x.parquet"


# --------------------------------------------------------------------------
# scripts/data/cef_crosscheck_crsp.py -- pure logic
# --------------------------------------------------------------------------

D = pd.to_datetime


def _names():
    # AAA: permno 10 until 2015, then the ticker is recycled to permno 20.
    # BBB: two overlapping name records with different permnos in 2020 (ambiguous).
    return pd.DataFrame({
        "permno": [10, 20, 30, 31],
        "ticker": ["AAA", "AAA", "BBB", "BBB"],
        "namedt": D(["2000-01-01", "2016-01-01", "2019-01-01", "2020-01-01"]),
        "nameenddt": D(["2015-12-31", "2024-12-31", "2024-12-31", "2020-12-31"]),
    })


def test_permno_map_by_date_range():
    from scripts.data import cef_crosscheck_crsp as cc
    panel = pd.DataFrame({"ticker": ["AAA", "AAA", "BBB", "BBB", "CCC"],
                          "date": D(["2015-12-31", "2016-01-01",
                                     "2019-06-03", "2020-06-01", "2020-06-01"]),
                          "close": [1.0] * 5})
    m = cc.map_permnos(panel, _names()).set_index(["ticker", "date"])
    assert m.loc[("AAA", D("2015-12-31")), "permno"] == 10       # inclusive end
    assert m.loc[("AAA", D("2016-01-01")), "permno"] == 20       # recycled ticker
    assert m.loc[("BBB", D("2019-06-03")), "map_status"] == "MAPPED"
    assert m.loc[("BBB", D("2020-06-01")), "map_status"] == "AMBIGUOUS"
    assert np.isnan(m.loc[("BBB", D("2020-06-01")), "permno"])  # never picked
    assert m.loc[("CCC", D("2020-06-01")), "map_status"] == "UNMAPPED"


def test_compare_categories_and_no_trade():
    from scripts.data import cef_crosscheck_crsp as cc
    mapped = pd.DataFrame({
        "ticker": ["AAA"] * 5,
        "date": D(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]),
        "close": [10.00, 10.50, 9.90, 5.00, 7.00],
        "map_status": ["MAPPED"] * 5, "permno": [20.0] * 5})
    crsp = pd.DataFrame({
        "permno": [20, 20, 20, 20],
        "date": D(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]),
        # agree to 0.004; disagree by 0.02; negative prc = bid/ask mean; 2:1 split later
        "prc": [10.004, 10.52, -9.90, 10.00],
        "cfacpr": [1.0, 1.0, 1.0, 1.0]})
    r = cc.compare(mapped, crsp).set_index("date")
    assert list(r["category"]) == ["AGREE", "DISAGREE", "CRSP_NO_TRADE", "DISAGREE", "NOT_IN_CRSP"]
    # A negative prc is never compared as a close, even though |prc| == close.
    assert np.isnan(r.loc[D("2020-01-06"), "diff_raw"])


def test_compare_split_adjusted_is_separate_column():
    from scripts.data import cef_crosscheck_crsp as cc
    mapped = pd.DataFrame({"ticker": ["AAA"] * 2, "date": D(["2020-01-02", "2020-01-03"]),
                           "close": [5.00, 5.10], "map_status": ["MAPPED"] * 2,
                           "permno": [20.0, 20.0]})
    # 2:1 split between the dates: CRSP raw 10.00 then 5.10, cfacpr 2 then 1.
    crsp = pd.DataFrame({"permno": [20, 20], "date": D(["2020-01-02", "2020-01-03"]),
                         "prc": [10.00, 5.10], "cfacpr": [2.0, 1.0]})
    r = cc.compare(mapped, crsp).set_index("date")
    assert r.loc[D("2020-01-02"), "category"] == "DISAGREE"            # raw
    assert r.loc[D("2020-01-02"), "split_adj_category"] == "AGREE"     # adjusted
    assert r.loc[D("2020-01-02"), "crsp_split_adj"] == pytest.approx(5.00)


def test_compare_missing_cfacpr_not_filled():
    from scripts.data import cef_crosscheck_crsp as cc
    mapped = pd.DataFrame({"ticker": ["AAA"], "date": D(["2020-01-02"]), "close": [10.0],
                           "map_status": ["MAPPED"], "permno": [20.0]})
    crsp = pd.DataFrame({"permno": [20], "date": D(["2020-01-02"]), "prc": [10.0],
                         "cfacpr": [np.nan]})
    r = cc.compare(mapped, crsp)
    assert r["category"].iloc[0] == "AGREE"
    assert r["split_adj_category"].iloc[0] == "NOT_COMPARABLE"
    assert np.isnan(r["crsp_split_adj"].iloc[0])


def test_crsp_only_dates_inside_window():
    from scripts.data import cef_crosscheck_crsp as cc
    mapped = pd.DataFrame({"ticker": ["AAA"] * 2, "date": D(["2020-01-02", "2020-01-06"]),
                           "close": [1.0, 1.0], "map_status": ["MAPPED"] * 2,
                           "permno": [20.0, 20.0]})
    crsp = pd.DataFrame({"permno": [20] * 4,
                         "date": D(["2019-12-31", "2020-01-02", "2020-01-03", "2020-01-06"]),
                         "prc": [1.0] * 4})
    x = cc.crsp_only_dates(mapped, crsp)
    assert list(x["date"]) == [D("2020-01-03")]   # 2019-12-31 is outside the panel window


def test_load_panel_rejects_missing_ticker_and_duplicates(tmp_path):
    from scripts.data import cef_crosscheck_crsp as cc
    p = tmp_path / "px.parquet"
    pd.DataFrame({"date": D(["2020-01-02", "2020-01-02"]), "ticker": ["AAA", "AAA"],
                  "close": [1.0, 1.1]}).to_parquet(p)
    with pytest.raises(cc.CrossCheckError, match="BBB"):
        cc.load_panel(p, ["AAA", "BBB"])
    with pytest.raises(cc.CrossCheckError, match="duplicate"):
        cc.load_panel(p, ["AAA"])
