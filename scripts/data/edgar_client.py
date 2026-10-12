"""A polite, cached, read-only client for SEC EDGAR. Every EDGAR request in this repo goes through it.

WHY THIS EXISTS
---------------
Plan item 0.7 (`results/cef/RESEARCH_PLAN_2026-10-09.md`) needs CEF and BDC
corporate-action filings from EDGAR. EDGAR is free but it is not anonymous and
it is not unlimited: the SEC's fair-access page
(https://www.sec.gov/os/accessing-edgar-data, "Last Reviewed or Updated: June
26, 2024", fetched 2026-10-12) states

  * "Current max request rate: 10 requests/second", and that the SEC "reserves
    the right to limit request rates to preserve fair access for all users";
  * "Please declare your user agent in request headers", with the sample
        User-Agent: Sample Company Name AdminContact@<sample company domain>.com
        Accept-Encoding: gzip, deflate
        Host: www.sec.gov

A scraper that ignores either gets the desk's address blocked (HTTP 403), and
with it every later EDGAR fetch. So the rules live in ONE place, here, and no
script opens its own connection to sec.gov.

THE CONTACT, AND WHERE IT COMES FROM (team lead, 2026-10-12, docs/SYSTEM.md §5)
-----------------------------------------------------------------------------
The User-Agent carries the team lead's own address. It is read from the env
file exactly as `src/data/r2.py` reads R2's values -- the file named by
`$QUANTT_ENV_FILE` if set, else `<repo>/config/.env` (`r2.env_file_path`, so
there is one rule for where a credential-like value can come from), through
`dotenv_values`, never exported to `os.environ`, never printed, never logged,
never written into the repository or the cache. A missing value RAISES naming
`SEC_USER_AGENT`; there is no default contact (the plan forbids the user's
e-mail by default, and a made-up one would misrepresent who is asking).
`EdgarClient.__repr__` redacts it so a traceback's locals cannot leak it.

RATE LIMIT AND BACK-OFF
-----------------------
One request at a time (no threads, no async: "never parallelise beyond the
stated limit"), spaced at least `MIN_INTERVAL_S` apart. 0.125 s is 8 requests a
second: under the stated 10 with room for clock jitter, so a burst can never
reach the ceiling even if two calls straddle a tick. HTTP 403, 429 and 503 are
what EDGAR returns when it throttles (403 is also what an undeclared agent
gets); each is retried after a growing pause (`BACKOFF_S`), and after the last
pause the client RAISES naming the URL and the status. It never loops forever
and never swallows a refusal. The pause lengths are this module's choice: the
SEC page states no lock-out duration [U], so the last pause is ten minutes,
the figure commonly reported for EDGAR's lock-out (unverified; erring long).

CACHE
-----
`results/events/_cache_edgar/` (gitignored by `results/**/_cache_*` and named
in `.gitignore`). EDGAR is public data, but the cache is large and re-fetchable,
so it is not committed. Each response is stored under its host and URL path;
`_manifest.json` records URL, UTC fetch time, byte count and SHA-256 -- never a
header. A caller passes `max_age_s` for documents that change (the current
quarter's index, a fund's submissions JSON); a closed quarter's index is
immutable and is fetched once.

Imports at module level are stdlib only; `requests` and `dotenv` are imported
inside the functions that need them, so the tests (which never touch the
network; the root conftest blocks it) can import this module safely.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "results" / "events" / "_cache_edgar"
ENV_VAR = "SEC_USER_AGENT"

# The SEC's stated ceiling (accessing-edgar-data, reviewed 2024-06-26) and our
# spacing beneath it. Read the docstring before raising MIN_INTERVAL_S's rate.
SEC_MAX_REQUESTS_PER_SECOND = 10
MIN_INTERVAL_S = 0.125
assert 1.0 / MIN_INTERVAL_S < SEC_MAX_REQUESTS_PER_SECOND
BACKOFF_S = (30.0, 120.0, 600.0)
THROTTLE_STATUSES = (403, 429, 503)
ALLOWED_HOSTS = ("www.sec.gov", "data.sec.gov")
TIMEOUT_S = 60

# A contact address somewhere in the agent string: the SEC's sample is
# "<name> <e-mail>". Checked so a mis-set value (a name only, a URL, a blank)
# fails here, loudly, rather than at the SEC as an anonymous-looking 403.
_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")


class EdgarConfigError(RuntimeError):
    """The SEC contact is missing or malformed. Names the variable, never its value."""


class EdgarHTTPError(RuntimeError):
    """EDGAR refused or failed a request after the allowed retries."""


class EdgarNotFound(EdgarHTTPError):
    """HTTP 404: the document does not exist (a fact about EDGAR, not a transient)."""


def validate_user_agent(ua: str) -> str:
    """Return `ua` stripped, or raise without echoing it."""
    s = (ua or "").strip()
    if not s:
        raise EdgarConfigError(f"{ENV_VAR} is empty")
    if any(c in s for c in "\r\n\0"):
        raise EdgarConfigError(f"{ENV_VAR} contains a line break or NUL (header injection)")
    if not _EMAIL_RE.search(s):
        raise EdgarConfigError(
            f"{ENV_VAR} has no contact e-mail address; the SEC's fair-access page asks for "
            "'<name> <e-mail>' (https://www.sec.gov/os/accessing-edgar-data)")
    if len(s.split()) < 2:
        raise EdgarConfigError(f"{ENV_VAR} should name who is asking as well as the address")
    return s


def load_user_agent(environ=None) -> str:
    """The contact string from the env file (never from os.environ), validated."""
    from src.data.r2 import env_file_path  # one rule for which env file is read
    path = env_file_path(environ)
    if not path.exists():
        raise EdgarConfigError(f"env file {path} does not exist (set QUANTT_ENV_FILE or create it)")
    from dotenv import dotenv_values
    raw = dotenv_values(path).get(ENV_VAR)
    if not raw:
        raise EdgarConfigError(f"{ENV_VAR} not set in {path}; the team lead supplies it "
                               "(docs/SYSTEM.md §5, 2026-10-12). There is no default.")
    return validate_user_agent(raw)


class RateLimiter:
    """At most one call per `min_interval` seconds, measured on a monotonic clock.

    `clock` and `sleep` are injectable so the spacing is tested without waiting.
    """

    def __init__(self, min_interval: float = MIN_INTERVAL_S, clock=time.monotonic, sleep=time.sleep):
        if min_interval < 1.0 / SEC_MAX_REQUESTS_PER_SECOND:
            raise ValueError(f"min_interval {min_interval}s exceeds the SEC's "
                             f"{SEC_MAX_REQUESTS_PER_SECOND} requests/second")
        self.min_interval, self._clock, self._sleep = min_interval, clock, sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            gap = self._clock() - self._last
            if gap < self.min_interval:
                self._sleep(self.min_interval - gap)
        self._last = self._clock()


_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def filing_txt_url(cik, accession: str) -> str:
    """The complete-submission text file of one filing.

    Built here, with the CIK and accession validated, because a malformed
    archive path does not 404: EDGAR answers it with HTTP 403 "Access Denied",
    which is also its throttling answer, so the client would back off for
    twelve minutes and then fail. Measured 2026-10-12: a CIK that arrived as
    the float 1195739.0 (a pandas column with a gap) produced exactly that.
    """
    if isinstance(cik, float):
        if not cik.is_integer():
            raise ValueError(f"CIK {cik!r} is not an integer")
        cik = int(cik)
    if not isinstance(cik, int) or isinstance(cik, bool) or cik <= 0:
        raise ValueError(f"CIK must be a positive integer, got {cik!r}")
    if not _ACCESSION_RE.match(str(accession)):
        raise ValueError(f"not an accession number: {accession!r}")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}.txt"


def cache_path(url: str, cache: Path = CACHE) -> Path:
    """Where `url` is cached: <cache>/<host>/<path>[__<query hash>]."""
    p = urlsplit(url)
    if p.scheme != "https" or p.netloc not in ALLOWED_HOSTS:
        raise ValueError(f"not an allowed EDGAR URL: {url}")
    rel = p.path.lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise ValueError(f"bad EDGAR path in {url}")
    if p.query:
        rel += "__" + hashlib.sha1(p.query.encode()).hexdigest()[:12]
    return cache / p.netloc / rel


class EdgarClient:
    """GET with the SEC's headers, the rate limit, back-off and a disk cache."""

    def __init__(self, user_agent: str | None = None, session=None, limiter: RateLimiter | None = None,
                 cache: Path = CACHE, backoff=BACKOFF_S, sleep=time.sleep, offline: bool = False):
        self._ua = validate_user_agent(user_agent) if user_agent is not None else (
            None if offline else load_user_agent())
        self._session = session
        self._limiter = limiter or RateLimiter()
        self.cache, self.backoff, self._sleep, self.offline = Path(cache), tuple(backoff), sleep, offline
        self.n_requests = 0
        self.n_cache_hits = 0

    def __repr__(self) -> str:  # the contact never appears in a repr or traceback
        return f"EdgarClient(user_agent=<redacted>, cache={str(self.cache)!r}, offline={self.offline})"

    def _sess(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _manifest(self, url: str, body: bytes) -> None:
        path = self.cache / "_manifest.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"url": url, "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        with path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def get(self, url: str, max_age_s: float | None = None) -> bytes:
        """The body of `url` (decoded from gzip transfer encoding), from cache if fresh.

        `max_age_s=None` means the document is immutable: a cached copy is
        always used. A cached copy older than `max_age_s` is re-fetched.
        `offline=True` reads the cache only and raises on a miss, so an
        analysis can be re-run without touching the network.
        """
        path = cache_path(url, self.cache)
        if path.exists() and (max_age_s is None or time.time() - path.stat().st_mtime < max_age_s):
            self.n_cache_hits += 1
            return path.read_bytes()
        if self.offline:
            raise EdgarHTTPError(f"offline and not cached (or stale): {url}")
        host = urlsplit(url).netloc
        headers = {"User-Agent": self._ua, "Accept-Encoding": "gzip, deflate", "Host": host}
        last_status = None
        for attempt in range(len(self.backoff) + 1):
            self._limiter.wait()
            self.n_requests += 1
            r = self._sess().get(url, headers=headers, timeout=TIMEOUT_S)
            last_status = r.status_code
            if r.status_code == 200:
                body = r.content
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(path.name + ".part")
                tmp.write_bytes(body)
                tmp.replace(path)
                self._manifest(url, body)
                return body
            if r.status_code == 404:
                raise EdgarNotFound(f"GET {url} -> HTTP 404")
            if r.status_code in THROTTLE_STATUSES and attempt < len(self.backoff):
                self._sleep(self.backoff[attempt])
                continue
            break
        raise EdgarHTTPError(f"GET {url} -> HTTP {last_status} after {attempt + 1} attempt(s)")

    def get_text(self, url: str, max_age_s: float | None = None, encoding: str = "latin-1") -> str:
        body = self.get(url, max_age_s)
        if body[:2] == b"\x1f\x8b":  # a .gz document (not transfer-encoded): unpack it here
            body = gzip.decompress(body)
        return body.decode(encoding)

    def get_json(self, url: str, max_age_s: float | None = None):
        return json.loads(self.get_text(url, max_age_s, encoding="utf-8"))
