"""Read secrets from Azure Key Vault with the VM's managed identity.

This is the Azure half of the boot-time key fetch. `quantt.deploy.boot_secrets`
calls `fetch` and writes what it returns to the file the runner reads.

WHY THIS EXISTS
---------------
Prod moves from the laptop to an Azure VM (team lead, 2026-10-07: Azure for
Students; the laptop missed the send on 3 of 6 trading days 2026-09-30..10-07
because it was asleep or offline). ROADMAP 6.2: the Alpaca keys reach the VM
through the provider's secrets manager, never as a file copied from a laptop.
The VM has a system-assigned managed identity holding "Key Vault Secrets User"
on one vault. At boot, `quantt-secret.service` runs boot_secrets, which calls
`fetch` here. No credential is ever written to the VM's disk, and no
credential is needed to obtain one: the identity is the VM itself.

THE PROVIDER SEAM
-----------------
This module is the only code that knows about Azure. Its interface is
`fetch(config, names) -> {name: value}`:

  * `config` holds the provider's own settings, from the unit's `--config k=v`.
    Here that is exactly `vault`.
  * `names` are the secret names to read.

boot_secrets owns everything else: the mapping to environment-variable names,
the validation, and the 0600 file. A different provider is a different module
with the same `fetch`, registered in `boot_secrets.PROVIDERS`. The systemd
units, the bootstrap and the installer do not change.

THE PROTOCOL [V: Microsoft Learn, fetched 2026-10-07]
-----------------------------------------------------
1. **A token from IMDS** ("Use managed identities on a virtual machine to
   acquire access token", learn.microsoft.com/entra/identity/
   managed-identities-azure-resources/how-to-use-vm-token):

       GET http://169.254.169.254/metadata/identity/oauth2/token
           ?api-version=2018-02-01&resource=https://vault.azure.net
       header  Metadata: true    ("in all lower case"; an SSRF mitigation)

   A 200 returns JSON with `access_token`. Learn's retry guidance:
   - retry 404 ("IMDS endpoint is updating"), 429, 5xx and time-outs;
   - 410 means IMDS "will be available within 70 seconds";
   - any other 4xx is a design-time error: "Don't retry".
   `IMDS_DELAYS` sums past 70 seconds so that a 410 is outlasted. IMDS "isn't
   intended to be used behind a proxy", so this request bypasses any proxy set
   in the environment.

2. **Each secret** (Key Vault REST "Get Secret",
   learn.microsoft.com/rest/api/keyvault/secrets/get-secret/get-secret):

       GET https://<vault>.vault.azure.net/secrets/<name>?api-version=7.4
       header  Authorization: Bearer <token>

   The version segment of the path is left out, and per the reference, "If not
   specified, the latest version of the secret is returned." A 200 returns JSON
   whose `value` is the secret. Errors return `{"error": {"code", "message"}}`.
   The token's resource is the vault scope that same page names,
   `https://vault.azure.net/.default`.

   Why api-version 7.4: it is the version MEASURED working on the prod VM
   (2026-10-07). From quantt-prod, an IMDS token plus this exact GET returned
   both secrets, and those keys authenticated to Alpaca paper. The Learn
   reference now documents 2025-07-01, which has not been tried from the VM.
   Stable data-plane versions are not retired by the 2027-02-27 control-plane
   retirement: "This retirement doesn't affect data plane APIs"
   (learn.microsoft.com/azure/key-vault/general/migrate-api-version). Change
   this only after the new version has been measured from the VM.

3. **Names** (learn.microsoft.com/azure/key-vault/general/
   about-keys-secrets-certificates):
   - a vault name is "a 3-24 character string, containing only 0-9, a-z, A-Z,
     and not consecutive -";
   - a secret name is "a 1-127 character string, containing only 0-9, a-z,
     A-Z, and -";
   - the Azure public cloud's vault DNS suffix is `.vault.azure.net`.

   Both names are checked BEFORE any request, because the vault name becomes a
   host name. `evil.example/x` must never become a URL that receives the
   bearer token. Redirects are refused for the same reason: urllib would
   forward the Authorization header to wherever a 3xx pointed.

WHAT IT NEVER DOES
------------------
* Prints, logs or raises with a token or a secret value. An error names the
  step, the secret NAME, the HTTP status and the service's error CODES. It never
  includes the message body: a Key Vault RBAC 403 message carries the tenant,
  the caller's object id and the vault's /subscriptions/... resource id.
* Falls back. A missing, empty or disabled secret raises, and nothing is
  substituted.
* Imports anything outside the standard library at module level, so the test
  suite can import it without opening a socket (`pytest.ini` testpaths rule).
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, NamedTuple

IMDS_TOKEN_URL = "http://169.254.169.254/metadata/identity/oauth2/token"
IMDS_API_VERSION = "2018-02-01"
KEYVAULT_RESOURCE = "https://vault.azure.net"
KEYVAULT_DNS_SUFFIX = ".vault.azure.net"
KEYVAULT_API_VERSION = "7.4"            # measured on the VM 2026-10-07; see docstring

# Delays BEFORE each retry, in seconds. IMDS: Learn's exponential schedule
# (~2, ~6, ~14, ~30) plus one more 30 so the total (82 s) outlasts a 410's
# "available within 70 seconds". Key Vault: short, since its only retryable
# answers are throttling and transient server errors.
IMDS_DELAYS = (2, 6, 14, 30, 30)
KEYVAULT_DELAYS = (1, 2, 4)
IMDS_RETRY_STATUS = frozenset({404, 410, 429})      # plus every 5xx
KEYVAULT_RETRY_STATUS = frozenset({429})            # plus every 5xx
TIMEOUT_S = 10

# 3-24 characters; alphanumerics and '-'; no "--". The first and last characters
# must be alphanumeric, because the name is a DNS label inside the vault's host
# name, and a DNS label cannot start or end with '-'.
VAULT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){2,23}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9-]{1,127}$")


class SecretFetchError(RuntimeError):
    """A secret could not be fetched. The message names what, never a value."""


class Response(NamedTuple):
    status: int
    body: bytes


class TransportError(Exception):
    """No HTTP status came back (DNS failure, refused connection, timeout)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every 3xx. urllib's default handler re-sends the request headers to
    the new location, Authorization included."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_get(url: str, headers: dict, *, timeout: float, proxy: bool) -> Response:
    """One GET. Returns the status and body for ANY HTTP status (a 3xx included,
    since redirects are refused), or raises TransportError if none came back.

    `proxy=False` builds the opener with an empty ProxyHandler. That bypasses
    http_proxy/https_proxy in the environment, which IMDS requires.
    """
    handlers = [_NoRedirect()]
    if not proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(req, timeout=timeout) as r:
            return Response(r.status, r.read())
    except urllib.error.HTTPError as e:
        return Response(e.code, e.read())
    except (urllib.error.URLError, OSError) as e:      # TimeoutError is an OSError
        raise TransportError(f"{type(e).__name__}: {e}") from e


def check_vault_name(vault: str) -> str:
    if not isinstance(vault, str) or not VAULT_RE.match(vault):
        raise SecretFetchError(
            f"vault name {vault!r} is not a Key Vault name (3-24 characters of "
            f"0-9 a-z A-Z and non-consecutive '-', starting and ending alphanumeric)")
    return vault


def check_secret_name(name: str) -> str:
    if not isinstance(name, str) or not SECRET_RE.match(name):
        raise SecretFetchError(
            f"secret name {name!r} is not a Key Vault secret name "
            f"(1-127 characters of 0-9 a-z A-Z and '-')")
    return name


# An Azure error code is an identifier like `Forbidden`, `ForbiddenByRbac` or
# `invalid_request`. Anything else in a `code` field is not echoed.
_CODE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _code(v) -> str | None:
    return v if isinstance(v, str) and _CODE_RE.match(v) else None


def _error_summary(body: bytes) -> str:
    """The service's error CODES for a non-200 body, never its message.

    IMDS errors are `{"error", "error_description"}`; Key Vault errors are
    `{"error": {"code", "message", "innererror": {"code"}}}`. Only the code
    fields are shown, and only when they look like codes.

    Why never the message (review 2026-10-07): a Key Vault RBAC 403's message
    names the caller's tenant and object id and the vault's full resource id,
    /subscriptions/<id>/..., and these logs are read and pasted. The HTTP
    status, the codes and our own hint say enough to act on. No code branches
    on the text either: Learn says error descriptions "can change at any time".
    """
    try:
        doc = json.loads(body)
    except ValueError:
        return f"(non-JSON body, {len(body)} bytes, not shown)"
    err = doc.get("error") if isinstance(doc, dict) else None
    if isinstance(err, dict):
        inner = err.get("innererror")
        codes = [_code(err.get("code")), _code(inner.get("code")) if isinstance(inner, dict) else None]
    elif isinstance(err, str):
        codes = [_code(err)]
    else:
        return "(no error object in body)"
    shown = "/".join(c for c in codes if c)
    return shown or "(error code not shown)"


def _get_json(step: str, url: str, headers: dict, *, http: Callable,
              sleep: Callable, delays: tuple, retry_status: frozenset,
              proxy: bool, hint: Callable[[int], str]) -> dict:
    """GET `url` with bounded retry. Returns the decoded JSON of a 200, or raises.

    Retrying is safe because a GET changes nothing. A status outside
    `retry_status`, below 500, raises at once with `hint(status)` appended. That
    covers a 403 from a missing role assignment, which no amount of retrying fixes.
    """
    attempts = len(delays) + 1
    last = ""
    for i in range(attempts):
        if i:
            sleep(delays[i - 1])
        try:
            r = http(url, headers, timeout=TIMEOUT_S, proxy=proxy)
        except TransportError as e:
            last = str(e)
            continue
        if r.status == 200:
            try:
                doc = json.loads(r.body)
            except ValueError:
                raise SecretFetchError(f"{step}: HTTP 200 but the body is not JSON") from None
            if not isinstance(doc, dict):
                raise SecretFetchError(f"{step}: HTTP 200 but the body is not a JSON object")
            return doc
        last = f"HTTP {r.status} {_error_summary(r.body)}"
        if r.status < 500 and r.status not in retry_status:
            raise SecretFetchError(f"{step} failed: {last}{hint(r.status)}")
    raise SecretFetchError(f"{step} failed after {attempts} attempts; last: {last}")


def _imds_hint(status: int) -> str:
    if status == 400:
        return (" -- does this VM have a system-assigned managed identity "
                "(az vm identity assign)?")
    return ""


def _keyvault_hint(status: int) -> str:
    return {401: " -- the token was not accepted by the vault",
            403: " -- does the VM's identity hold 'Key Vault Secrets User' on this "
                 "vault, and is the secret enabled?",
            404: " -- no secret of that name in this vault"}.get(status, "")


def fetch(config: dict, names, *, http: Callable = http_get,
          sleep: Callable = time.sleep) -> dict:
    """{secret name: value} for every name, read from the vault in `config`.

    Everything is validated before the first request. One token serves every
    secret: tokens last on the order of an hour (`expires_in` in the sample
    response is 3599), and the fetch takes seconds.
    """
    if not isinstance(config, dict) or set(config) != {"vault"}:
        raise SecretFetchError(
            f"azure-keyvault takes exactly one config key, vault=<name>; got "
            f"{sorted(config) if isinstance(config, dict) else config!r}")
    vault = check_vault_name(config["vault"])
    names = list(names)
    if not names:
        raise SecretFetchError("no secret names to fetch")
    for n in names:
        check_secret_name(n)
    # Key Vault names are case-insensitive ("compare them as case-insensitive
    # strings"), so two names differing only in case are the same secret.
    folded = [n.casefold() for n in names]
    if len(set(folded)) != len(folded):
        raise SecretFetchError(f"duplicate secret names (case-insensitive): {names}")

    query = urllib.parse.urlencode({"api-version": IMDS_API_VERSION,
                                    "resource": KEYVAULT_RESOURCE})
    tok = _get_json("IMDS managed-identity token", f"{IMDS_TOKEN_URL}?{query}",
                    {"Metadata": "true"}, http=http, sleep=sleep,
                    delays=IMDS_DELAYS, retry_status=IMDS_RETRY_STATUS,
                    proxy=False, hint=_imds_hint)
    token = tok.get("access_token")
    if not isinstance(token, str) or not token:
        raise SecretFetchError("IMDS managed-identity token: HTTP 200 without an "
                               "access_token")
    auth = {"Authorization": f"Bearer {token}"}

    out = {}
    for n in names:
        url = (f"https://{vault}{KEYVAULT_DNS_SUFFIX}/secrets/{n}"
               f"?api-version={KEYVAULT_API_VERSION}")
        doc = _get_json(f"Key Vault get secret {n!r} from vault {vault!r}", url, auth,
                        http=http, sleep=sleep, delays=KEYVAULT_DELAYS,
                        retry_status=KEYVAULT_RETRY_STATUS, proxy=True,
                        hint=_keyvault_hint)
        value = doc.get("value")
        if not isinstance(value, str) or value == "":
            raise SecretFetchError(f"Key Vault secret {n!r} in vault {vault!r} has no "
                                   f"value (missing or empty)")
        out[n] = value
    return out
