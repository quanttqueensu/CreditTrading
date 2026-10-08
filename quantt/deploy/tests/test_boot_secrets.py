"""The boot-time key fetch writes exactly the vault's values, privately, and never shows them.

Each test pins one promise from `boot_secrets` or `azure_keyvault`. These are
the ones that fail silently in prod:

  * a key printed into a log;
  * a retry loop that gives up too early (IMDS takes up to 70 s to come back),
    or one that retries a missing role assignment forever;
  * a vault name that becomes somebody else's host name;
  * a value that python-dotenv reads back differently from what the vault holds.

Hermetic. HTTP is a fake `http(url, headers, timeout=, proxy=)`, so nothing
opens a socket (the root conftest's netguard would refuse it anyway), and
sleeps are recorded, not slept. The output files live under tmp_path.
"""
from __future__ import annotations

import ast
import os
import sys
import types
from pathlib import Path

import pytest

from quantt.deploy import azure_keyvault as akv
from quantt.deploy import boot_secrets as bs

TOKEN = "eyJ-token-sentinel-that-must-never-be-printed"
KEY_ID = "PKSENTINELKEYID0001"
SECRET = "sentinelSecretValue/with+chars=9"
VAULT = "example-vault-x1"
NAMES = ["alpaca-cef-key-id", "alpaca-cef-secret-key"]
MAP = ["alpaca-cef-key-id=ALPACA_CEF_KEY_ID", "alpaca-cef-secret-key=ALPACA_CEF_SECRET_KEY"]
VALUES = {"alpaca-cef-key-id": KEY_ID, "alpaca-cef-secret-key": SECRET}
IMDS_URL = ("http://169.254.169.254/metadata/identity/oauth2/token"
            "?api-version=2018-02-01&resource=https%3A%2F%2Fvault.azure.net")


def kv_url(name, vault=VAULT):
    return f"https://{vault}.vault.azure.net/secrets/{name}?api-version=7.4"


def ok(doc):
    import json
    return akv.Response(200, json.dumps(doc).encode())


def err(status, code="Forbidden", message="Caller is not authorized"):
    import json
    return akv.Response(status, json.dumps({"error": {"code": code, "message": message}}).encode())


class FakeHttp:
    """Scripted answers: `script[key]` is a list consumed in order (the last
    answer repeats); key "imds" or a secret name. An answer that is an
    exception instance is raised."""

    def __init__(self, script=None):
        self.script = script or {}
        self.calls = []

    def __call__(self, url, headers, *, timeout, proxy):
        self.calls.append({"url": url, "headers": dict(headers), "proxy": proxy})
        if url.startswith("http://169.254.169.254/"):
            key = "imds"
        else:
            key = url.split("/secrets/", 1)[1].split("?", 1)[0]
        answers = self.script.get(key)
        if answers is None:
            answers = [ok({"access_token": TOKEN, "token_type": "Bearer"})] if key == "imds" \
                else [ok({"value": VALUES[key], "id": f"{kv_url(key)}/abc"})]
        a = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(a, Exception):
            raise a
        return a


class Sleeps(list):
    def __call__(self, s):
        self.append(s)


def fetch(http, sleep=None, config=None, names=NAMES):
    return akv.fetch({"vault": VAULT} if config is None else config, names, http=http,
                     sleep=Sleeps() if sleep is None else sleep)


# -- the protocol ------------------------------------------------------------

def test_fetch_asks_imds_then_the_vault_exactly_as_documented():
    http = FakeHttp()
    assert fetch(http) == VALUES
    imds, a, b = http.calls
    assert imds["url"] == IMDS_URL
    assert imds["headers"] == {"Metadata": "true"}
    assert imds["proxy"] is False                       # IMDS must bypass any proxy
    assert [a["url"], b["url"]] == [kv_url(n) for n in NAMES]
    for c in (a, b):
        assert c["headers"] == {"Authorization": f"Bearer {TOKEN}"}


def test_imds_transient_answers_are_retried_on_the_learn_schedule():
    http = FakeHttp({"imds": [akv.Response(410, b""), akv.Response(429, b""),
                              akv.Response(404, b""), akv.TransportError("timed out"),
                              akv.Response(503, b""),
                              ok({"access_token": TOKEN})]})
    sleeps = Sleeps()
    assert fetch(http, sleeps) == VALUES
    assert sleeps == list(akv.IMDS_DELAYS)
    assert sum(akv.IMDS_DELAYS) > 70        # outlasts a 410's "within 70 seconds"


def test_imds_gives_up_after_bounded_attempts():
    http = FakeHttp({"imds": [akv.Response(500, b"")]})
    sleeps = Sleeps()
    with pytest.raises(akv.SecretFetchError, match=r"after 6 attempts"):
        fetch(http, sleeps)
    assert sleeps == list(akv.IMDS_DELAYS)


def test_imds_design_time_error_is_not_retried_and_names_the_identity():
    http = FakeHttp({"imds": [akv.Response(400, b'{"error":"invalid_request",'
                                                b'"error_description":"Identity not found"}')]})
    sleeps = Sleeps()
    with pytest.raises(akv.SecretFetchError, match="managed identity") as e:
        fetch(http, sleeps)
    assert sleeps == []
    assert "invalid_request" in str(e.value)
    assert "Identity not found" not in str(e.value)     # review 2026-10-07: codes only


def test_missing_role_is_not_retried_and_names_secret_and_role_never_the_token():
    http = FakeHttp({"alpaca-cef-key-id": [err(403)]})
    sleeps = Sleeps()
    with pytest.raises(akv.SecretFetchError) as e:
        fetch(http, sleeps)
    msg = str(e.value)
    assert "alpaca-cef-key-id" in msg and "Key Vault Secrets User" in msg and "403" in msg
    assert TOKEN not in msg
    assert sleeps == []


# A realistic RBAC refusal (shape of Key Vault's ForbiddenByRbac answer). The
# message carries the caller's tenant and object id and the vault's full
# resource id. All of them are invented here, but on prod they would be real,
# and the logs must never repeat them.
SUB = "0b1f6471-1bf0-4dda-aec3-111122223333"
RBAC_403 = ('{"error":{"code":"Forbidden","message":"Caller is not authorized to perform '
            'action on resource.\\r\\nCaller: appid=9a8b7c6d-0000-4000-8000-aaaabbbbcccc;'
            'oid=11112222-3333-4444-5555-666677778888;iss=https://sts.windows.net/'
            '99998888-7777-6666-5555-444433332222/\\r\\nAction: \'Microsoft.KeyVault/vaults/'
            'secrets/getSecret/action\'\\r\\nResource: \'/subscriptions/' + SUB +
            '/resourcegroups/quantt-prod/providers/microsoft.keyvault/vaults/example-vault-x1/'
            'secrets/alpaca-cef-key-id\'\\r\\nAssignment: (not found)\\r\\n",'
            '"innererror":{"code":"ForbiddenByRbac"}}}').encode()


def test_an_rbac_refusal_logs_codes_and_hint_never_the_message(run_dir, capsys):
    http = FakeHttp({"alpaca-cef-key-id": [akv.Response(403, RBAC_403)]})
    with pytest.raises(akv.SecretFetchError) as e:
        fetch(http)
    msg = str(e.value)
    for leak in (SUB, "/subscriptions/", "oid=", "sts.windows.net", "appid=", "Caller"):
        assert leak not in msg, leak
    assert "403" in msg and "Forbidden" in msg and "ForbiddenByRbac" in msg
    assert "Key Vault Secrets User" in msg
    # and through the command line, which is what lands in secret.err.log
    http = FakeHttp({"alpaca-cef-key-id": [akv.Response(403, RBAC_403)]})
    assert main(run_dir / "alpaca.env", azure_module(http)) == 1
    err = capsys.readouterr().err
    assert SUB not in err and "/subscriptions/" not in err and "oid=" not in err


def test_imds_errors_log_the_error_code_not_the_description():
    body = (b'{"error":"invalid_request","error_description":"Identity not found '
            b'for /subscriptions/' + SUB.encode() + b'/resourceGroups/quantt-prod"}')
    with pytest.raises(akv.SecretFetchError) as e:
        fetch(FakeHttp({"imds": [akv.Response(400, body)]}))
    assert "invalid_request" in str(e.value) and SUB not in str(e.value)


def test_a_non_json_error_body_is_never_echoed():
    body = b"<html>proxy error for /subscriptions/" + SUB.encode() + b"</html>"
    with pytest.raises(akv.SecretFetchError) as e:
        fetch(FakeHttp({"imds": [akv.Response(502, body)]}))
    assert SUB not in str(e.value) and "non-JSON" in str(e.value)


def test_an_odd_error_code_is_not_echoed_verbatim():
    body = b'{"error":{"code":"/subscriptions/' + SUB.encode() + b'","message":"x"}}'
    with pytest.raises(akv.SecretFetchError) as e:
        fetch(FakeHttp({"alpaca-cef-key-id": [akv.Response(403, body)]}))
    assert SUB not in str(e.value)


def test_missing_secret_raises_naming_it():
    http = FakeHttp({"alpaca-cef-secret-key": [err(404, "SecretNotFound", "not found")]})
    with pytest.raises(akv.SecretFetchError, match="alpaca-cef-secret-key.*404"):
        fetch(http)


def test_empty_or_absent_value_raises_rather_than_writing_nothing():
    for body in ({"value": ""}, {"id": "x"}):
        http = FakeHttp({"alpaca-cef-secret-key": [ok(body)]})
        with pytest.raises(akv.SecretFetchError, match="alpaca-cef-secret-key.*no value"):
            fetch(http)


def test_keyvault_throttling_is_retried_boundedly():
    http = FakeHttp({"alpaca-cef-key-id": [akv.Response(429, b""), ok({"value": KEY_ID})]})
    sleeps = Sleeps()
    assert fetch(http, sleeps) == VALUES
    assert sleeps == [akv.KEYVAULT_DELAYS[0]]


@pytest.mark.parametrize("vault", ["evil.example/x", "vault.azure.net", "a", "ab", "a--b",
                                   "-abc", "abc-", "x" * 25, "kv_1", "", "kv 1"])
def test_bad_vault_names_are_refused_before_any_request(vault):
    http = FakeHttp()
    with pytest.raises(akv.SecretFetchError, match="not a Key Vault name"):
        fetch(http, config={"vault": vault})
    assert http.calls == []


@pytest.mark.parametrize("vault", ["abc", "example-vault-x1", "A1-b2-C3", "a" * 24])
def test_good_vault_names_pass(vault):
    assert akv.check_vault_name(vault) == vault


def test_bad_secret_names_and_duplicates_are_refused_before_any_request():
    for names in (["has_underscore"], ["x" * 128], ["dup", "DUP"], []):
        http = FakeHttp()
        with pytest.raises(akv.SecretFetchError):
            fetch(http, names=names)
        assert http.calls == []


def test_config_is_exactly_the_vault():
    for config in ({}, {"vault": VAULT, "region": "x"}, {"Vault": VAULT}):
        with pytest.raises(akv.SecretFetchError, match="exactly one config key"):
            fetch(FakeHttp(), config=config)


def test_redirects_are_refused_so_the_token_never_follows_one():
    """urllib's default handler re-sends the request headers, Authorization
    included, to wherever a 3xx points."""
    assert akv._NoRedirect().redirect_request(None, None, 302, "Found", {},
                                              "https://elsewhere.example/") is None


# -- boot_secrets: the file ---------------------------------------------------

@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "run" / "quantt"
    d.mkdir(parents=True)
    os.chmod(d, 0o700)
    return d


def azure_module(http):
    """The real azure_keyvault.fetch over a fake HTTP, in the module shape boot_secrets loads."""
    return types.SimpleNamespace(
        fetch=lambda config, names: akv.fetch(config, names, http=http, sleep=Sleeps()),
        SecretFetchError=akv.SecretFetchError)


def main(out, module, *, mapping=MAP, vault=VAULT):
    argv = ["--provider", "azure-keyvault", "--config", f"vault={vault}", "--out", str(out)]
    for m in mapping:
        argv += ["--secret", m]
    return bs.main(argv, module=module)


def test_main_writes_a_0600_file_that_the_runner_reads_back_exactly(run_dir, capsys):
    out = run_dir / "alpaca.env"
    assert main(out, azure_module(FakeHttp())) == 0
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    from dotenv import dotenv_values           # the parser quantt.broker.alpaca uses
    assert dotenv_values(out) == {"ALPACA_CEF_KEY_ID": KEY_ID, "ALPACA_CEF_SECRET_KEY": SECRET}
    assert sorted(p.name for p in run_dir.iterdir()) == ["alpaca.env"]   # no temp left
    shown = capsys.readouterr()
    for s in (KEY_ID, SECRET, TOKEN):
        assert s not in shown.out and s not in shown.err
    assert "ALPACA_CEF_KEY_ID, ALPACA_CEF_SECRET_KEY" in shown.out


def test_provider_failure_writes_nothing_and_shows_no_value(run_dir, capsys):
    out = run_dir / "alpaca.env"
    http = FakeHttp({"alpaca-cef-secret-key": [err(403)]})
    assert main(out, azure_module(http)) == 1
    assert not out.exists() and list(run_dir.iterdir()) == []
    shown = capsys.readouterr()
    assert "FAILED" in shown.err and "alpaca-cef-secret-key" in shown.err
    for s in (KEY_ID, SECRET, TOKEN):
        assert s not in shown.out and s not in shown.err


def test_directory_others_can_enter_is_refused(run_dir, capsys):
    os.chmod(run_dir, 0o755)
    out = run_dir / "alpaca.env"
    assert main(out, azure_module(FakeHttp())) == 1
    assert not out.exists()
    assert "0o755" in capsys.readouterr().err


def test_missing_directory_is_refused(tmp_path, capsys):
    out = tmp_path / "no-such-dir" / "alpaca.env"
    assert main(out, azure_module(FakeHttp())) == 1
    assert "RuntimeDirectory" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["twoX9\nlinesX9", " leadX9", "trailX9 ", "abcX9 #comment",
                                 "crX9\rreturnX9"])
def test_value_dotenv_would_misread_is_refused_naming_the_variable_not_the_value(
        run_dir, capsys, bad):
    values = dict(VALUES, **{"alpaca-cef-secret-key": bad})
    module = types.SimpleNamespace(fetch=lambda c, n: dict(values),
                                   SecretFetchError=akv.SecretFetchError)
    out = run_dir / "alpaca.env"
    assert main(out, module) == 1
    assert not out.exists()
    shown = capsys.readouterr().err
    assert "ALPACA_CEF_SECRET_KEY" in shown
    assert bad.strip() not in shown


def test_provider_returning_other_names_is_refused(run_dir, capsys):
    for got in ({"alpaca-cef-key-id": KEY_ID},
                dict(VALUES, extra="x")):
        module = types.SimpleNamespace(fetch=lambda c, n, got=got: dict(got),
                                       SecretFetchError=akv.SecretFetchError)
        assert main(run_dir / "alpaca.env", module) == 1
        assert "expected exactly" in capsys.readouterr().err
    assert list(run_dir.iterdir()) == []


@pytest.mark.parametrize("mapping", [
    ["alpaca-cef-key-id=ALPACA_CEF_KEY_ID", "alpaca-cef-key-id=OTHER"],     # secret twice
    ["a=ALPACA_CEF_KEY_ID", "b=ALPACA_CEF_KEY_ID"],                         # variable twice
    ["alpaca-cef-key-id=lower_case"],
    ["no-equals-sign"],
    [],
])
def test_bad_secret_mapping_is_refused(run_dir, mapping):
    assert main(run_dir / "alpaca.env", azure_module(FakeHttp()), mapping=mapping) == 1
    assert list(run_dir.iterdir()) == []


def test_unknown_provider_is_rejected_by_the_command_line():
    with pytest.raises(SystemExit):
        bs.main(["--provider", "gcp", "--out", "/run/quantt/alpaca.env"])


def test_registered_provider_module_has_the_seam_interface():
    for name, path in bs.PROVIDERS.items():
        mod = bs.load_provider(name)
        assert callable(mod.fetch) and issubclass(mod.SecretFetchError, Exception), path


# -- import hygiene (pytest.ini testpaths rule) --------------------------------

@pytest.mark.parametrize("mod", [bs, akv])
def test_module_level_imports_are_standard_library_only(mod):
    tree = ast.parse(Path(mod.__file__).read_text())
    top = set()
    for n in tree.body:
        if isinstance(n, ast.Import):
            top |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            top.add((n.module or "").split(".")[0])
    assert top - {"__future__"} <= set(sys.stdlib_module_names), top
