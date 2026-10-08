"""At boot, write the book's Alpaca keys from the cloud secret store to a private tmpfs file.

This is what `quantt-secret.service` runs on the prod VM:

    python -m quantt.deploy.boot_secrets --provider azure-keyvault \\
        --config vault=<vault-name> \\
        --secret alpaca-cef-key-id=ALPACA_CEF_KEY_ID \\
        --secret alpaca-cef-secret-key=ALPACA_CEF_SECRET_KEY \\
        --out /run/quantt/alpaca.env

WHY THIS EXISTS
---------------
The runner reads its keys from the dotenv file named by QUANTT_ENV_FILE, parsed
by python-dotenv in `quantt.broker.alpaca._load_keys`. On the laptop the team
lead wrote that file. ROADMAP 6.2 says that on the VM the keys come from the
provider's secrets manager, never from a copied file. So at boot this module
writes the same file format into /run/quantt, where:

  * /run is a tmpfs, so the keys never reach a disk (systemd.exec(5));
  * the directory is mode 0700, owned by the service user, and removed when
    the service stops (RuntimeDirectory=);
  * the file is mode 0600.

A SUCCESSFUL fetch runs once per boot (`RemainAfterExit=yes` keeps the service
active), so secret reads stay negligible. A FAILED fetch leaves the service
inactive, and every job start pulls it in again (`Wants=`). That is
self-healing: a role assignment fixed later works at the next firing. The cost
is that each job waits for the retry, up to about 4 minutes when every request
times out. That is IMDS: 6 attempts x 10 s plus 82 s of backoff, about 142 s.
Then about 47 s for each secret: 4 attempts x 10 s plus 7 s
(azure_keyvault.IMDS_DELAYS, KEYVAULT_DELAYS, TIMEOUT_S). A 4xx answer ends it
at once.

THE SEAM
--------
Each provider is one module exposing `fetch(config, names) -> {name: value}`,
registered in PROVIDERS (today only `azure-keyvault` ->
`quantt.deploy.azure_keyvault`). This module knows nothing about any provider.
It does four things:

  * parses the `--secret name=ENV_VAR` mapping;
  * checks that the provider returned exactly the names asked for;
  * checks every value;
  * writes the file, then proves it reads back as exactly the fetched values
    when parsed by the same python-dotenv the runner uses.

The systemd units, the bootstrap and the installer know only this command
line. Changing provider means one new module plus a different `--provider`.

WHAT IT NEVER DOES
------------------
* Prints a value. stdout gets one line naming the file and the variable NAMES.
* Leaves a partial file. Everything is fetched and checked first, then written
  under a temp name and renamed. The runner sees all the keys or none.
* Writes into a directory that group or other can enter (it must be 0700 or
  stricter) or that this user does not own.
* Writes a value that python-dotenv would read back differently. A value with
  a newline, surrounding whitespace, or anything else dotenv would rewrite is
  refused, naming the variable. Quietly mangling a key would surface later as
  an unexplained 401 from Alpaca.
"""
from __future__ import annotations

import argparse
import importlib
import io
import os
import re
import sys
from pathlib import Path

PROVIDERS = {"azure-keyvault": "quantt.deploy.azure_keyvault"}

ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class BootSecretError(RuntimeError):
    """The key file cannot be written safely. The message names what, never a value."""


def _pairs(items, what: str) -> list:
    out = []
    for item in items:
        k, sep, v = item.partition("=")
        if not sep or not k or not v:
            raise BootSecretError(f"{what} {item!r} is not of the form name=value")
        out.append((k, v))
    return out


def parse_secret_map(items) -> dict:
    """['secret-name=ENV_VAR', ...] -> {secret-name: ENV_VAR}; refuses duplicates."""
    pairs = _pairs(items, "--secret")
    if not pairs:
        raise BootSecretError("at least one --secret name=ENV_VAR is required")
    mapping = {}
    envs = set()
    for name, env in pairs:
        if not ENV_NAME_RE.match(env):
            raise BootSecretError(f"--secret {name}={env}: {env!r} is not an "
                                  f"UPPER_CASE environment variable name")
        if name in mapping or env in envs:
            raise BootSecretError(f"--secret {name}={env} repeats a secret or variable name")
        mapping[name] = env
        envs.add(env)
    return mapping


def parse_config(items) -> dict:
    config = {}
    for k, v in _pairs(items, "--config"):
        if k in config:
            raise BootSecretError(f"--config {k} given twice")
        config[k] = v
    return config


def render_env(values: dict) -> str:
    """{ENV_VAR: value} -> dotenv text, after proving dotenv reads it back exactly.

    The values are written unquoted, one `NAME=value` line each. python-dotenv
    is imported here, not at module level: the VM venv has it
    (requirements.txt), and importing this module in tests needs nothing
    beyond the standard library.
    """
    for env, v in values.items():
        if not ENV_NAME_RE.match(env):
            raise BootSecretError(f"{env!r} is not an UPPER_CASE environment variable name")
        if not isinstance(v, str) or v == "":
            raise BootSecretError(f"{env}: empty value")
        if any(c in v for c in "\r\n\0"):
            raise BootSecretError(f"{env}: value spans more than one line")
        if v != v.strip():
            raise BootSecretError(f"{env}: value has leading or trailing whitespace "
                                  f"(was it pasted with a space or newline?)")
    text = "".join(f"{env}={v}\n" for env, v in values.items())
    from dotenv import dotenv_values
    back = dotenv_values(stream=io.StringIO(text))
    for env, v in values.items():
        if back.get(env) != v:
            raise BootSecretError(f"{env}: value would not read back unchanged through "
                                  f"python-dotenv; refusing to write a key the runner "
                                  f"would read differently")
    if set(back) != set(values):
        raise BootSecretError(f"dotenv reads back variables {sorted(back)}, "
                              f"expected {sorted(values)}")
    return text


def write_env_file(path: Path, text: str) -> None:
    """Write `text` to `path` as a 0600 file, atomically, in a private directory."""
    if not path.is_absolute():
        raise BootSecretError(f"--out {path} must be an absolute path")
    parent = path.parent
    try:
        st = os.stat(parent)
    except FileNotFoundError:
        raise BootSecretError(
            f"{parent} does not exist; under systemd it is made by "
            f"RuntimeDirectory= (quantt-secret.service)") from None
    if st.st_mode & 0o077:
        raise BootSecretError(f"{parent} has mode {oct(st.st_mode & 0o777)}; the key "
                              f"file's directory must be 0700 or stricter")
    if st.st_uid != os.geteuid():
        raise BootSecretError(f"{parent} is owned by uid {st.st_uid}, not this user "
                              f"({os.geteuid()})")
    tmp = parent / f".{path.name}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Clean up the temp file, then re-raise: the failure still propagates.
        if tmp.exists():
            tmp.unlink()
        raise
    mode = os.stat(path).st_mode & 0o777
    if mode != 0o600:
        raise BootSecretError(f"{path} was written with mode {oct(mode)}, expected 0o600")


def load_provider(provider: str):
    """The provider module. It must define `fetch(config, names)` and the
    exception class `SecretFetchError` that its failures raise."""
    if provider not in PROVIDERS:
        raise BootSecretError(f"unknown provider {provider!r}; known: {sorted(PROVIDERS)}")
    return importlib.import_module(PROVIDERS[provider])


def run(provider: str, config: dict, secret_map: dict, out: Path, *, module=None) -> list:
    """Fetch, check and write. Returns the variable names written.

    `module` defaults to the registered provider module; tests pass a fake with
    the same two attributes.
    """
    mod = module if module is not None else load_provider(provider)
    try:
        got = mod.fetch(config, list(secret_map))
    except mod.SecretFetchError as e:
        # Same message, one error type for main(): the provider's messages name
        # steps and secret names only, by its contract.
        raise BootSecretError(f"{provider}: {e}") from e
    if not isinstance(got, dict) or set(got) != set(secret_map):
        raise BootSecretError(
            f"provider {provider} returned secrets "
            f"{sorted(got) if isinstance(got, dict) else type(got).__name__}, "
            f"expected exactly {sorted(secret_map)}")
    values = {secret_map[name]: got[name] for name in secret_map}
    write_env_file(out, render_env(values))
    return list(values)


def main(argv=None, *, module=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    ap.add_argument("--config", action="append", default=[], metavar="KEY=VALUE",
                    help="provider setting, e.g. vault=<name> for azure-keyvault")
    ap.add_argument("--secret", action="append", default=[], metavar="NAME=ENV_VAR",
                    help="secret name in the store = variable name in the file")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    try:
        written = run(a.provider, parse_config(a.config), parse_secret_map(a.secret),
                      a.out, module=module)
    except BootSecretError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    print(f"wrote {a.out} (mode 600): {', '.join(written)} from {a.provider}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
