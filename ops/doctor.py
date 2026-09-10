"""Is this machine actually able to run the books unattended?

    python3 -m ops.doctor              # full check
    python3 -m ops.doctor --quick      # skip the broker probe

WHY
---
Every failure this system has had was silent, and each one was invisible to the
guards that existed at the time:

  2026-07-31  launchd could not read the repo (TCC). Exit 126, no log.
  2026-08-01  TWS down for 21 consecutive sessions. Preflight blocked
              correctly every time; nobody was reading preflight.
  2026-08-31  the repo moved. `REPO` in launch_job.py still pointed at the old
              path, which `mkdir(parents=True)` then silently RECREATED.
  2026-09-01  four plists still carried WorkingDirectory=<old path>. launchd
              refused to spawn them (EX_CONFIG 78) — no process, no log, no
              heartbeat, no alert. One of the four was the WATCHDOG, so the
              job whose entire purpose is reporting stopped jobs was killed by
              the same fault and could not report itself.

The pattern is always the same: a guard that lives *inside* a job cannot catch
a job that never starts, and a guard that shares a broken assumption with the
thing it guards is not a guard. So this runs OUTSIDE all of them, checks the
plumbing rather than the strategy, and is meant to be run by the watchdog every
day and by a human after any move, upgrade or reinstall.

It changes nothing. FAIL means unattended operation is broken right now; WARN
means it will break later or you will not hear about it when it does.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LAUNCH_JOB = Path.home() / "Library/Application Support/quantt/launch_job.py"
AGENTS = Path.home() / "Library/LaunchAgents"
JOBS = ["cef", "benchmarks", "phase0", "collect", "watchdog", "weekly"]

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, name, msg, fix=""):
        self.rows.append((level, name, msg, fix))

    def render(self):
        w = max((len(n) for _, n, _, _ in self.rows), default=10)
        for level, name, msg, _ in self.rows:
            print(f"  [{level}] {name:<{w}}  {msg}")
        fails = [r for r in self.rows if r[0] == FAIL]
        warns = [r for r in self.rows if r[0] == WARN]
        print()
        if fails:
            print("UNATTENDED OPERATION IS BROKEN:")
            for _, n, m, fix in fails:
                print(f"  - {n}: {m}")
                if fix:
                    print(f"      fix: {fix}")
        if warns:
            print("WILL BREAK LATER, OR YOU WILL NOT HEAR ABOUT IT:")
            for _, n, m, fix in warns:
                print(f"  - {n}: {m}")
                if fix:
                    print(f"      fix: {fix}")
        if not fails and not warns:
            print("All checks pass. The books can run unattended.")
        return 1 if fails else 0


def _plist_path(job):
    for cand in (AGENTS / f"com.quantt.{job}.daily.plist",
                 AGENTS / f"com.quantt.{job}.plist"):
        if cand.exists():
            return cand
    return None


def check_entrypoint(r):
    """The launchd entry point, and the REPO it resolves."""
    if not LAUNCH_JOB.exists():
        r.add(FAIL, "entrypoint", f"missing {LAUNCH_JOB}")
        return None
    repo = None
    for line in LAUNCH_JOB.read_text().splitlines():
        if line.startswith("REPO = Path("):
            repo = Path(line.split('"')[1])
            break
    if repo is None:
        r.add(WARN, "entrypoint", "could not parse REPO from launch_job.py")
        return None
    if not (repo / "ops").is_dir():
        r.add(FAIL, "repo-path", f"REPO={repo} has no ops/ — nothing will run",
              f"edit REPO in {LAUNCH_JOB}")
    elif repo.resolve() != REPO_ROOT.resolve():
        r.add(FAIL, "repo-path",
              f"REPO={repo} is not this repo ({REPO_ROOT}) — the scheduler is "
              f"driving a different checkout",
              f"edit REPO in {LAUNCH_JOB}")
    else:
        r.add(PASS, "repo-path", f"{repo}")
    return repo


def check_plists(r):
    """The 2026-09-01 fault: a stale WorkingDirectory stops launchd spawning."""
    for job in JOBS:
        p = _plist_path(job)
        if p is None:
            r.add(WARN, f"plist:{job}", "no plist installed")
            continue
        try:
            d = plistlib.load(open(p, "rb"))
        except Exception as exc:
            r.add(FAIL, f"plist:{job}", f"unreadable: {exc!r}")
            continue
        wd = d.get("WorkingDirectory")
        if wd and not Path(wd).is_dir():
            r.add(FAIL, f"plist:{job}",
                  f"WorkingDirectory={wd} does not exist — launchd will refuse "
                  f"to spawn this job (EX_CONFIG 78), silently",
                  f"remove the WorkingDirectory key from {p.name}, then reload it")
            continue
        args = d.get("ProgramArguments") or []
        if args and not Path(args[0]).exists():
            r.add(FAIL, f"plist:{job}", f"interpreter {args[0]} does not exist")
            continue
        prog = [a for a in args[1:] if a.endswith(".py")]
        if prog and not Path(prog[0]).exists():
            r.add(FAIL, f"plist:{job}", f"script {prog[0]} does not exist")
            continue
        r.add(PASS, f"plist:{job}", "paths resolve")


def check_launchd(r):
    """Loaded, and what did each last exit with?"""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=20).stdout
    except Exception as exc:
        r.add(WARN, "launchd", f"could not query: {exc!r}")
        return
    loaded = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2].startswith("com.quantt."):
            loaded[parts[2]] = parts[1]
    for job in JOBS:
        label = None
        p = _plist_path(job)
        if p:
            label = p.stem
        if label not in loaded:
            r.add(WARN, f"loaded:{job}", "not loaded — it will never fire",
                  f"launchctl bootstrap gui/$(id -u) {p}" if p else "")
            continue
        code = loaded[label]
        if code not in ("0", "-"):
            hint = (" (EX_CONFIG — almost always a bad path in the plist)"
                    if code == "78" else "")
            r.add(FAIL, f"loaded:{job}", f"last exit {code}{hint}",
                  "fix the plist, then bootout + bootstrap it to reload")
        else:
            r.add(PASS, f"loaded:{job}", "loaded, last exit 0")


def check_env_paths(r):
    """BOOK / BOOKS_ROOT in the job envs must exist.

    Only envs belonging to a REAL job are checked. launch_job.py loads
    `ops/schedule/<job>.env` and nothing else, so schedule.env — a leftover
    pointing at a v2 book that was never built — is dead config, not a broken
    dependency. Reporting it as a failure would train the reader to skim past
    this list, which is the failure mode this whole file exists to prevent.
    """
    for env in sorted((REPO_ROOT / "ops" / "schedule").glob("*.env")):
        if env.name.endswith(".bak") or env.stem not in JOBS:
            continue
        bad = []
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() in ("BOOK", "BOOKS_ROOT") and not Path(v.strip()).exists():
                bad.append(f"{k.strip()}={v.strip()}")
        if bad:
            r.add(FAIL, f"env:{env.stem}", "; ".join(bad) + " does not exist",
                  f"correct the paths in {env}")
        else:
            r.add(PASS, f"env:{env.stem}", "book paths resolve")


def check_broker(r, quick=False):
    if quick:
        r.add(WARN, "broker", "skipped (--quick)")
        return
    try:
        from src.deploy.broker.ibkr import IBKRConfig
        cfg = IBKRConfig.from_env()
    except Exception as exc:
        r.add(FAIL, "broker", f"cannot read config: {exc!r}")
        return
    try:
        from ops.switch_broker import _probe
        res = _probe(cfg.host, cfg.port)
    except Exception as exc:
        r.add(FAIL, "broker", f"probe failed: {exc!r}")
        return
    if not res.get("ok"):
        r.add(FAIL, "broker",
              f"{cfg.host}:{cfg.port} does not answer the API "
              f"({res.get('error')}) — no book can trade",
              "start IB Gateway (and IBC, so it logs itself back in)")
        return
    r.add(PASS, "broker",
          f"{cfg.host}:{cfg.port} account={res['accounts']} "
          f"{len(res['positions'])} position(s)")


def check_ibc(r):
    """Gateway alone is not unattended — something must answer the daily login."""
    # Match on DISTINCTIVE launcher names only. A bare "ibc" substring test
    # matches almost anything -- including this process's own command line when
    # the check is run from a one-liner -- and produced a false PASS on
    # 2026-09-01, i.e. the check reported the gateway was supervised when no
    # IBC existed at all. A check that can pass while the thing is absent is
    # worse than no check.
    running = False
    try:
        out = subprocess.run(["ps", "axo", "pid=,command="], capture_output=True,
                             text=True, timeout=20).stdout
        me = str(os.getpid())
        for line in out.splitlines():
            line = line.strip()
            pid, _, cmd = line.partition(" ")
            if pid == me:
                continue                      # never match ourselves
            low = cmd.lower()
            if any(tok in low for tok in
                   ("ibcstart", "gatewaystart", "ibcontroller", "ibc.jar",
                    "ibcalpha")):
                running = True
                break
    except Exception:
        pass
    ini = Path.home() / "ibc" / "config.ini"
    installed = (Path.home() / "ibc" / "IBC.jar").exists()
    if not installed:
        r.add(FAIL, "ibc",
              "IBC is not installed. IB Gateway restarts daily and will sit at "
              "a login prompt with nothing to answer it — the book dies "
              "tomorrow exactly as it did on 2026-08-01",
              "see deploy/ibgw/README.md")
        return

    # Installed. Now: is it configured, and is it actually up?
    cfg = {}
    try:
        for line in ini.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    except Exception as exc:
        r.add(WARN, "ibc", f"installed but config.ini unreadable: {exc!r}")
        return

    if cfg.get("TradingMode") != "paper":
        # Worth its own FAIL: this repo's specs, cost model and kill rules are
        # all written for the paper account. `live` is IBC's shipped default.
        r.add(FAIL, "ibc-mode",
              f"config.ini TradingMode={cfg.get('TradingMode')!r}, expected "
              f"'paper' — this repo is a paper deployment",
              f"set TradingMode=paper in {ini}")

    if not cfg.get("IbLoginId") or not cfg.get("IbPassword"):
        r.add(FAIL, "ibc",
              "IBC is installed and configured but has NO CREDENTIALS, so it "
              "cannot log the gateway in. Everything else is ready",
              f"set IbLoginId and IbPassword in {ini} (chmod 600), then: "
              f"launchctl bootstrap gui/$(id -u) "
              f"~/Library/LaunchAgents/com.quantt.ibgateway.plist")
        return

    if running:
        r.add(PASS, "ibc", "IBC is managing the gateway")
    else:
        r.add(FAIL, "ibc",
              "IBC is installed and has credentials but is not running — the "
              "gateway will stop at the login prompt after its daily restart",
              "launchctl bootstrap gui/$(id -u) "
              "~/Library/LaunchAgents/com.quantt.ibgateway.plist")


def check_sleep(r):
    try:
        sched = subprocess.run(["pmset", "-g", "sched"], capture_output=True,
                               text=True, timeout=20).stdout.lower()
    except Exception as exc:
        r.add(WARN, "sleep", f"could not read pmset: {exc!r}")
        return
    if "wakeorpoweron" in sched or "poweron" in sched:
        r.add(PASS, "sleep", "a repeating wake is scheduled")
        return

    # No scheduled wake. Is the no-sudo substitute at least holding it awake?
    # com.quantt.awake runs `caffeinate -s` 09:00-20:00 on weekdays. That is a
    # PARTIAL fix and must not report as PASS: caffeinate prevents idle sleep
    # but cannot WAKE a sleeping Mac, and does not defeat clamshell sleep.
    awake = False
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=20).stdout
        awake = any(line.endswith("com.quantt.awake") or
                    line.split("\t")[-1].strip() == "com.quantt.awake"
                    for line in out.splitlines())
    except Exception:
        pass
    if awake:
        r.add(WARN, "sleep",
              "no scheduled wake, but com.quantt.awake holds the machine awake "
              "09:00-20:00 on weekdays. That covers the battery-idle case; a "
              "CLOSED LID still sleeps and no session will fire",
              "sudo pmset repeat wakeorpoweron MTWRF 09:20:00 (the real fix)")
    else:
        r.add(FAIL, "sleep",
              "no repeating wake — on battery this Mac sleeps after 1 minute "
              "and launchd coalesces missed events to a single firing at wake. "
              "This ate collect and watchdog on 2026-08-31",
              "sudo pmset repeat wakeorpoweron MTWRF 09:20:00")


def check_heartbeats(r):
    try:
        import pandas as pd
        from ops import halt as halt_mod
        sys.path.insert(0, str(REPO_ROOT / "ops" / "schedule"))
        today = pd.Timestamp.today().normalize()
    except Exception as exc:
        r.add(WARN, "heartbeat", f"could not evaluate: {exc!r}")
        return
    for job in ("cef", "benchmarks", "phase0", "collect"):
        beat = halt_mod.last_beat(job)
        if beat is None:
            r.add(WARN, f"beat:{job}", "has never reported")
            continue
        missed = len(pd.bdate_range(pd.Timestamp(beat["date"]), today)) - 1
        if missed > 1:
            r.add(FAIL, f"beat:{job}",
                  f"last ran {beat['date']} ({beat['status']}), "
                  f"{missed} session(s) ago")
        else:
            r.add(PASS, f"beat:{job}", f"{beat['date']} ({beat['status']})")


def check_alerts(r):
    env = REPO_ROOT / "config" / ".env"
    txt = env.read_text() if env.exists() else ""
    have = all(f"{k}=" in txt and txt.split(f"{k}=", 1)[1].splitlines()[0].strip()
               for k in ("ALERT_SMTP_USER", "ALERT_SMTP_PASS"))
    if have:
        r.add(PASS, "alerts", "email configured")
    else:
        r.add(WARN, "alerts",
              "email not configured — alerts reach only the macOS banner and "
              "the speech synthesiser, which is nobody when you are away from "
              "the machine",
              "add ALERT_SMTP_USER and ALERT_SMTP_PASS (a Google App Password) "
              "to config/.env")


def failures(quick=False) -> list[str]:
    """[(name: message)] for every FAIL. Used by the watchdog.

    Silent, and never raises: a doctor that crashes the watchdog would take
    down the one job that reports everything else, which is precisely the
    2026-09-01 fault (the watchdog died of the same bad path it should have
    reported).
    """
    r = Report()
    for fn, args in ((check_entrypoint, ()), (check_plists, ()),
                     (check_launchd, ()), (check_env_paths, ()),
                     (check_broker, (quick,)), (check_ibc, ()),
                     (check_sleep, ()), (check_heartbeats, ()),
                     (check_alerts, ()), (check_panels, ())):
        try:
            fn(r, *args)
        except Exception as exc:
            r.add(WARN, fn.__name__, f"check raised {exc!r}")
    return [f"{n}: {m}" for lvl, n, m, _ in r.rows if lvl == FAIL]


# ---------------------------------------------------------------------------
# Panel staleness.
#
# WHY THIS IS A DOCTOR CHECK AND NOT A PREFLIGHT CHECK
# ----------------------------------------------------
# Preflight already gates the two panels the SESSION cannot trade without --
# price and NAV -- and refuses to arm on a stale pair, because a stale NAV is a
# blind signal, not a cheap fund. That is the right behaviour for the order
# path.
#
# This is the other half: the panels that RESEARCH depends on, which no session
# ever blocks on. Those rot quietly. Measured 2026-09-10, with the price panel
# current to the previous session:
#
#     cef_distributions.parquet   48 days behind   feeds the return convention
#                                                  and the ex-date calendar
#     etf_ohlc.parquet            43 days behind   feeds every ETF proxy
#     etf_daily.parquet           52 days behind
#
# Nothing announced any of that. A script joining a 48-day-old distribution
# panel to a current price panel does not fail; it silently applies the wrong
# correction, or none, and returns a number.
#
# "A stale input that fails loudly is an inconvenience; a stale input that
# fails silently is a wrong number."
#
# WARN rather than FAIL on purpose: a stale research panel does not stop the
# book trading tonight, and doctor's FAIL level means "unattended operation is
# broken right now". Overloading it would train the operator to ignore it.
# ---------------------------------------------------------------------------

# (path, max sessions behind the price panel before it is worth saying, why)
PANELS = [
    ("data/cef/cef_prices.parquet", 3,
     "the signal's own price panel"),
    ("data/cef/cef_nav.parquet", 3,
     "the signal's own NAV panel"),
    ("data/cef/cef_distributions.parquet", 21,
     "total-return convention (W4) and the ex-date calendar (W9)"),
    ("data/rv/etf_ohlc.parquet", 21,
     "ETF proxies in W10/W13 and gamma/G3's variance work"),
    ("data/cef/cef_borrow.csv", 10,
     "borrow cost and availability; drives short-side sizing"),
    # Fund attributes change slowly, so the limit is a quarter rather than a
    # fortnight -- but "slowly" is not "never", and an undated snapshot silently
    # applying today's attributes to 2005 is the look-ahead this flags.
    ("data/cef/cef_facts.csv", 63,
     "per-fund attributes; a SNAPSHOT, never join it to history un-dated"),
]

# Undated snapshots that LOOK like fact tables. Joining one to a historical
# panel is a look-ahead error with no error message.
UNDATED = [
    ("data/cef/cef_facts.csv", "fetched_at",
     "a single undated yfinance snapshot: 13 of 46 columns are 100% null and "
     "sector/industry are constant across all rows. Anything joining it to a "
     "27-year panel is committing look-ahead"),
]


# A date this project could plausibly hold. Outside this window the column is
# not dates, whatever it is called.
_PLAUSIBLE = (dt.date(1985, 1, 1), dt.date.today() + dt.timedelta(days=370))


def _panel_last_date(path):
    """Newest plausible date in a panel, or None.

    Never raises -- a monitor that dies on a malformed input is the failure
    mode it exists to catch.

    The plausibility window is not decoration. `pd.to_datetime` reads a bare
    integer as NANOSECONDS SINCE EPOCH, so a column named `date` holding 3
    returns 1970-01-01, and one holding 20260909 returns 1970 as well. Without
    this guard the check would confidently report a panel as ~20,000 sessions
    stale, or -- for the right integer -- as current. That is precisely the
    class of silent wrong answer this check exists to catch, so it must not
    commit it itself. Caught by ops/tests/test_doctor_panels.py.
    """
    try:
        import pandas as pd
        if path.suffix == ".csv":
            df = pd.read_csv(path)
        else:
            df = pd.read_parquet(path)
        # `fetched_at` counts: a snapshot's stamp is its date. Without this a
        # file stamped by the fetcher would still read as undated.
        cols = [c for c in df.columns
                if "date" in str(c).lower() or "fetched" in str(c).lower()]
        # A stamp beats a content date -- it says when we LEARNED the row, which
        # is what staleness means for a snapshot.
        cols.sort(key=lambda c: 0 if "fetched" in str(c).lower() else 1)
        for col in cols:
            parsed = pd.to_datetime(df[col], errors="coerce").dropna()
            if parsed.empty:
                continue
            last = parsed.max()
            if _PLAUSIBLE[0] <= last.date() <= _PLAUSIBLE[1]:
                return last
        return None
    except Exception:
        return None


def check_panels(r):
    """Are the panels research depends on current enough to trust?"""
    try:
        import pandas as pd
    except ImportError:
        r.add(WARN, "panels", "pandas unavailable; cannot check staleness")
        return

    ref_path = REPO_ROOT / "data/cef/cef_prices.parquet"
    ref = _panel_last_date(ref_path)
    if ref is None:
        r.add(WARN, "panels", "cannot read the price panel; staleness unknown")
        return

    try:
        sys.path.insert(0, str(REPO_ROOT / "ops/schedule"))
        import nyse_calendar as cal
    except Exception:
        cal = None

    def sessions_between(a, b):
        """NYSE sessions strictly after a, through b. Calendar days if the
        calendar module is unavailable -- stated, not silently substituted."""
        if cal is None:
            return (b - a).days, "cal-days"
        n, d = 0, a
        while d < b and n < 400:
            d += dt.timedelta(days=1)
            if cal.is_trading_day(d):
                n += 1
        return n, "sessions"

    for rel, limit, why in PANELS:
        path = REPO_ROOT / rel
        name = f"panel:{Path(rel).stem}"
        if not path.exists():
            r.add(WARN, name, f"missing — {why}")
            continue
        last = _panel_last_date(path)
        if last is None:
            r.add(WARN, name,
                  f"no date column; freshness unknowable — {why}",
                  fix="add a date or fetched_at column to the fetcher's output")
            continue
        n, unit = sessions_between(last.date(), ref.date())
        if n > limit:
            r.add(WARN, name,
                  f"{n} {unit} behind the price panel "
                  f"(ends {last.date()}, prices end {ref.date()}) — {why}",
                  fix=f"refresh it; any note quoting it must state {last.date()}")
        else:
            r.add(PASS, name, f"{n} {unit} behind prices (ends {last.date()})")

    for rel, wanted, why in UNDATED:
        path = REPO_ROOT / rel
        name = f"panel:{Path(rel).stem}"
        if not path.exists():
            continue
        try:
            head = path.read_text(errors="replace").splitlines()[0]
        except Exception:
            continue
        if wanted not in head:
            r.add(WARN, name, f"has no `{wanted}` column — {why}",
                  fix=f"add {wanted} in the fetcher, or supersede the file")
        else:
            r.add(PASS, name, f"carries `{wanted}`")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true",
                    help="skip the broker probe")
    a = ap.parse_args(argv)

    print(f"[doctor] repo   {REPO_ROOT}")
    print(f"[doctor] python {sys.executable}")
    print()
    r = Report()
    check_entrypoint(r)
    check_plists(r)
    check_launchd(r)
    check_env_paths(r)
    check_broker(r, quick=a.quick)
    check_ibc(r)
    check_sleep(r)
    check_heartbeats(r)
    check_alerts(r)
    check_panels(r)
    return r.render()


if __name__ == "__main__":
    sys.exit(main())
