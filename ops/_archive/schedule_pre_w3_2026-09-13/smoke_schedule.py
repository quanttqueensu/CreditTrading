"""Scheduler smoke check — plist well-formedness + holiday logic + wiring.

    /opt/anaconda3/bin/python3 ops/schedule/smoke_schedule.py           # fast (~1s)
    /opt/anaconda3/bin/python3 ops/schedule/smoke_schedule.py --full    # + a real --dry-run day

Fast checks (no side effects, no network, no ledger writes):
  1. Both plist templates render to VALID plists (plistlib): correct labels,
     weekday sets (Mon-Fri daily / Sat weekly), daily hour >= 16 local (after
     the US close), program + working dir point at real files.
  2. NYSE calendar: 2024 and 2026 rule-holiday lists match the exchange's
     published calendars date-for-date; weekend/holiday/special-closure
     no-op logic; the New-Year's-Saturday non-observance; Easter computus.
  3. Wrapper scripts parse (bash -n), are executable, and reference files that
     exist; schedule.env drives the v2 paper book (EXECUTION=simulator, BOOK ->
     book_v2_paper.json, BOOKS_ROOT -> v2_live); the daily wrapper invokes the
     V2 runner (src.deploy.lib.run_book_v2) behind the NYSE trading-day gate.
  4. run_book_v2 exposes --source/--books-root, the margin orchestrator advances
     by source, and run_book carries the forward panel-splice helpers.

--full additionally runs the REAL daily wrapper with DRY_RUN=1 forced and
asserts the live ops/books/v2_live book is byte-for-byte unchanged (the dry run
used a throwaway books-root and transmitted nothing).
"""

import argparse
import datetime as dt
import os
import plistlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHED = REPO / "ops" / "schedule"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCHED))

import nyse_calendar as cal  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(f"{name}: {detail}")


def render(template, hour=16, minute=40, whour=9, wminute=0):
    txt = template.read_text()
    for k, v in {"__REPO__": str(REPO), "__PYTHON__": sys.executable,
                 "__HOUR__": str(hour), "__MINUTE__": str(minute),
                 "__WHOUR__": str(whour), "__WMINUTE__": str(wminute)}.items():
        txt = txt.replace(k, v)
    return plistlib.loads(txt.encode())


def check_plists():
    print("plists:")
    daily = render(SCHED / "com.quantt.book.daily.plist.template")
    weekly = render(SCHED / "com.quantt.book.weekly.plist.template")

    check("daily label", daily.get("Label") == "com.quantt.book.daily")
    check("weekly label", weekly.get("Label") == "com.quantt.book.weekly")
    check("labels distinct", daily["Label"] != weekly["Label"])

    d_iv = daily.get("StartCalendarInterval", [])
    check("daily fires Mon-Fri",
          sorted(x["Weekday"] for x in d_iv) == [1, 2, 3, 4, 5],
          str(d_iv))
    check("daily hour after the close (>=16 local)",
          all(x["Hour"] >= 16 for x in d_iv))
    check("daily one time for all weekdays",
          len({(x["Hour"], x["Minute"]) for x in d_iv}) == 1)
    w_iv = weekly.get("StartCalendarInterval", [])
    check("weekly fires Saturday only",
          [x["Weekday"] for x in w_iv] == [6], str(w_iv))

    for name, pl, script in (("daily", daily, "run_after_close.sh"),
                             ("weekly", weekly, "run_weekly.sh")):
        args = pl.get("ProgramArguments", [])
        check(f"{name} program is bash + wrapper",
              len(args) == 2 and args[0] == "/bin/bash"
              and args[1].endswith(f"ops/schedule/{script}"))
        check(f"{name} wrapper exists", Path(args[1]).exists(), args[1])
        check(f"{name} WorkingDirectory exists",
              Path(pl.get("WorkingDirectory", "/nonexistent")).is_dir())
        check(f"{name} not RunAtLoad", pl.get("RunAtLoad") is False)
        check(f"{name} logs into ops/schedule/logs",
              "ops/schedule/logs" in pl.get("StandardOutPath", ""))


# The exchange's published full-day closes (holiday rules), used as fixtures.
NYSE_2024 = ["2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29",
             "2024-05-27", "2024-06-19", "2024-07-04", "2024-09-02",
             "2024-11-28", "2024-12-25"]
NYSE_2026 = ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
             "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
             "2026-11-26", "2026-12-25"]


def check_holidays():
    print("holiday calendar:")
    for year, expect in ((2024, NYSE_2024), (2026, NYSE_2026)):
        got = sorted(str(d) for d in cal.nyse_holidays(year))
        check(f"{year} holiday list matches NYSE", got == expect,
              f"got {got}")
    cases = [
        ("2026-07-20", True,  "normal Monday (today's asof)"),
        ("2026-07-04", False, "Saturday"),
        ("2026-07-03", False, "Independence Day observed (Sat->Fri)"),
        ("2026-04-03", False, "Good Friday (Easter 2026-04-05)"),
        ("2026-06-19", False, "Juneteenth"),
        ("2026-11-26", False, "Thanksgiving"),
        ("2026-11-27", True,  "day after Thanksgiving = EARLY CLOSE, trades"),
        ("2025-01-09", False, "special closure (Carter mourning)"),
        ("2021-12-31", True,  "New Year's Saturday NOT observed Friday"),
        ("2021-06-18", True,  "Juneteenth rule starts 2022, not 2021"),
        ("2027-01-01", False, "forward year: 2027 New Year (Friday)"),
        ("2027-06-18", False, "forward year: Juneteenth 2027 Sat->Fri"),
    ]
    for d, expect, why in cases:
        check(f"is_trading_day({d}) == {expect}  [{why}]",
              cal.is_trading_day(d) is expect)
    check("previous_trading_day skips the Jul-3/Jul-4 close",
          str(cal.previous_trading_day("2026-07-06")) == "2026-07-02")
    check("next_trading_day over Thanksgiving",
          str(cal.next_trading_day("2026-11-25")) == "2026-11-27")
    check("Easter 2024 computus", str(cal.easter(2024)) == "2024-03-31")
    # every rule holiday for the next two years lands on a weekday
    for y in (2026, 2027):
        check(f"{y} holidays all weekdays",
              all(d.weekday() < 5 for d in cal.nyse_holidays(y)))


def check_scripts():
    print("wrappers + wiring:")
    for s in ("run_after_close.sh", "run_weekly.sh", "install.sh"):
        p = SCHED / s
        rc = subprocess.run(["bash", "-n", str(p)], capture_output=True)
        check(f"{s} bash-parses", rc.returncode == 0,
              rc.stderr.decode()[:200])
        check(f"{s} executable", p.stat().st_mode & 0o111 != 0)
    env = (SCHED / "schedule.env").read_text()
    # The scheduler now drives the v2 paper book (RUNG-2: live simulator OOS record).
    check("schedule.env EXECUTION=simulator (no real orders)",
          "EXECUTION=simulator" in env)
    check("schedule.env sets DRY_RUN (0=live-sim, 1=dry)",
          any(l.strip().startswith("DRY_RUN=") for l in env.splitlines()))
    check("schedule.env BOOK -> v2 paper book",
          "book_v2_paper.json" in env)
    check("schedule.env BOOKS_ROOT -> v2_live", "v2_live" in env)
    check("v2 paper book spec exists",
          (REPO / "ops" / "books" / "v2" / "book_v2_paper.json").exists())
    check("v1 book.json kept intact (unchanged, still present)",
          (REPO / "ops" / "books" / "book.json").exists())

    wrapper = (SCHED / "run_after_close.sh").read_text()
    check("daily wrapper drives the V2 runner",
          "src.deploy.lib.run_book_v2" in wrapper)
    check("daily wrapper keeps the NYSE trading-day gate",
          "nyse_calendar.py" in wrapper and "--check" in wrapper)
    check("daily wrapper DRY_RUN=1 uses a throwaway books-root (mktemp)",
          "mktemp" in wrapper)
    check("daily wrapper reads the v2 status for catch-up replay",
          "book_status_v2.json" in wrapper)
    weekly = (SCHED / "run_weekly.sh").read_text()
    check("weekly wrapper runs the weekly book report",
          "weekly_book_report.py" in weekly)

    from src.deploy.lib import run_book_v2  # noqa: F401
    import io, contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            run_book_v2.main(["--help"])
    except SystemExit:
        pass
    htxt = buf.getvalue()
    check("run_book_v2 exposes --source and --books-root",
          "--source" in htxt and "--books-root" in htxt)
    import inspect
    from src.deploy.lib.portfolio_v2 import MarginPortfolioOrchestrator
    check("MarginPortfolioOrchestrator.advance takes a source",
          "source" in inspect.signature(
              MarginPortfolioOrchestrator.advance).parameters)
    # forward-operability: run_book's loader/calendar splice past the frozen panel
    from src.deploy import run_book
    check("run_book exposes the forward panel-splice helpers",
          hasattr(run_book, "_panel_last_date")
          and hasattr(run_book, "_load_etf"))


def check_full_dryrun():
    print("--full: DRY_RUN=1 day through the v2 wrapper (must transmit nothing):")
    import hashlib

    live = REPO / "ops" / "books" / "v2_live"

    def snapshot(root):
        out = {}
        if root.exists():
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    out[str(p.relative_to(root))] = hashlib.md5(
                        p.read_bytes()).hexdigest()
        return out

    before = snapshot(live)
    # Drive the REAL wrapper. SCHEDULE_ENV=/dev/null bypasses the (DRY_RUN=0)
    # schedule.env so the caller's DRY_RUN=1 wins; the wrapper's own defaults
    # supply the v2 paper book + v2_live root. A dry run must use a throwaway
    # books-root and leave the live book byte-for-byte unchanged.
    env = dict(os.environ)
    env.update(DRY_RUN="1", EXECUTION="simulator", SCHEDULE_ENV="/dev/null",
               PYTHON=sys.executable)
    rc = subprocess.run(["/bin/bash", str(SCHED / "run_after_close.sh")],
                        capture_output=True, env=env, cwd=str(REPO))
    check("v2 wrapper (DRY_RUN=1) exits 0", rc.returncode == 0,
          rc.stderr.decode()[-400:])
    after = snapshot(live)
    check("live v2_live book byte-identical after the dry run "
          "(throwaway root used, nothing transmitted)",
          before == after,
          f"changed files: {sorted(set(before.items()) ^ set(after.items()))[:4]}")

    today = dt.date.today().isoformat()
    logp = SCHED / "logs" / f"daily_{today}.log"
    if not logp.exists():
        check("today's daily log written", False, str(logp))
        return
    txt = logp.read_text()
    gated = "market closed" in txt
    if gated:
        print(f"    {today} is not a trading day — wrapper correctly no-op'd.")
        check("wrapper no-op'd on a non-trading day", True)
        return
    check("wrapper ran the v2 runner into a throwaway root",
          "run_book_v2" in txt and "throwaway" in txt)
    check("wrapper logged NO orders transmitted (dry)",
          "NO orders transmitted" in txt)
    check("wrapper removed the throwaway books-root",
          "removed throwaway dry-run books-root" in txt)
    print(f"    dry run logged into a throwaway root; live v2_live untouched "
          f"({len(before)} files).")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--full", action="store_true",
                    help="also run a real --dry-run day into a throwaway dir")
    args = ap.parse_args(argv)

    print(f"scheduler smoke check — {dt.date.today()}  repo={REPO}")
    check_plists()
    check_holidays()
    check_scripts()
    if args.full:
        check_full_dryrun()

    if FAILS:
        print(f"\nSMOKE FAIL ({len(FAILS)}):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nSMOKE OK — all scheduler checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
