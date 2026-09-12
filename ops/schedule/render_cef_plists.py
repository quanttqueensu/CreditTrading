#!/usr/bin/env python3
"""Render the two-session cef launchd plists (W3 Part A, 2026-09-11).

WHY THIS EXISTS SEPARATELY FROM install.sh
-------------------------------------------
`install.sh` renders `com.quantt.book.*` from templates and knows nothing about
the cef jobs -- the cef and phase0 plists in ops/schedule/rendered/ were written
by hand, still carry the pre-2026-08-31 repo path, and are NOT what launchd
runs (landmine 2 in CLAUDE.md). Rather than widen a renderer whose stale output
is already a documented trap, this emits exactly the three files this change
touches, correct and self-contained, and prints the commands a human runs to
install them. It installs NOTHING itself: `launchctl` is on the order path.

THE SCHEDULE, AND WHY EACH TIME IS WHAT IT IS
----------------------------------------------
  08:30  cef       decides on yesterday's pair, MOC for today's close. After
                   IB Gateway's 03:00 restart and its login have had five and a
                   half hours to complete, and eight hours after the pair
                   typically published (measured: 22:43 on 2026-09-08, 21:45 on
                   2026-09-09). W3: do not fire before 08:15.
  12:00  cef       the retry. A no-op when 08:30 armed, because ops/
                   session_plan.py refuses the same pair twice. Comfortably
                   inside the 15:50 ET MOC entry cutoff, which is the real
                   constraint: after 15:50 an MOC cannot be cancelled at all.
  17:30  cef_pm    capture, panel, and the fallback decision. Five minutes
                   behind benchmarks at 17:25 so the two never contend for TWS.

The awake job has to cover 08:00 through the evening fallback's 23:30 NAV
deadline, so it starts an hour earlier than the old 09:00 and runs 16 hours.
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "rendered"
PY = "/opt/anaconda3/bin/python3"
JOB = "/Users/simonjarvis/Library/Application Support/quantt/launch_job.py"
LOGDIR = "/Users/simonjarvis/Library/Application Support/quantt"

HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n')


def _cal(slots):
    """StartCalendarInterval for (hour, minute) slots on weekdays 1-5."""
    rows = []
    for hh, mm in slots:
        for wd in range(1, 6):
            rows.append(f"\t\t<dict><key>Hour</key><integer>{hh}</integer>"
                        f"<key>Minute</key><integer>{mm}</integer>"
                        f"<key>Weekday</key><integer>{wd}</integer></dict>")
    return "\t<key>StartCalendarInterval</key>\n\t<array>\n" + \
           "\n".join(rows) + "\n\t</array>\n"


def job_plist(label, arg, slots, comment):
    return (HEAD
            + f"\t<!-- {comment} -->\n"
            + f"\t<key>Label</key>\n\t<string>{label}</string>\n"
            + "\t<key>ProgramArguments</key>\n\t<array>\n"
            + f"\t\t<string>{PY}</string>\n\t\t<string>{JOB}</string>\n"
            + f"\t\t<string>{arg}</string>\n\t</array>\n"
            + "\t<key>RunAtLoad</key>\n\t<false/>\n"
            + f"\t<key>StandardErrorPath</key>\n\t<string>{LOGDIR}/launchd_{arg}.log</string>\n"
            + f"\t<key>StandardOutPath</key>\n\t<string>{LOGDIR}/launchd_{arg}.log</string>\n"
            + _cal(slots)
            + "</dict>\n</plist>\n")


AWAKE_COMMENT = """Hold the machine awake 08:00 -> midnight, which covers cef
	     08:30 and 12:00, benchmarks 17:25, cef_pm 17:30 and its 23:30 NAV
	     deadline on a fallback evening, collect 18:30 and watchdog 19:30.

	     Was 09:00 + 15h, which did not reach an 08:30 session at all.

	     -s is AC-only (man caffeinate), which is why -i is there: on
	     2026-09-10 the cef session started 17:15, the charger came off, and
	     the machine clamshell-slept at 19:51:36 on battery at 20%. The next
	     poll was 09:46 the following morning. Four MOC orders had filled at
	     the 09-10 close and their execution records were destroyed by IB's
	     03:00 restart before capture ran. A CLOSED LID still defeats both;
	     only `sudo pmset -a disablesleep 1` or an open lid survives that."""


def awake_plist():
    return (HEAD
            + f"\t<!-- {AWAKE_COMMENT} -->\n"
            + "\t<key>Label</key>\n\t<string>com.quantt.awake</string>\n"
            + "\t<key>ProgramArguments</key>\n\t<array>\n"
            + "\t\t<string>/usr/bin/caffeinate</string>\n"
            + "\t\t<string>-s</string>\n\t\t<string>-i</string>\n"
            + "\t\t<string>-t</string>\n\t\t<string>57600</string>\n\t</array>\n"
            + "\t<key>RunAtLoad</key>\n\t<true/>\n"
            + f"\t<key>StandardOutPath</key>\n\t<string>{LOGDIR}/launchd_awake.log</string>\n"
            + f"\t<key>StandardErrorPath</key>\n\t<string>{LOGDIR}/launchd_awake.log</string>\n"
            + _cal([(8, 0)])
            + "</dict>\n</plist>\n")


FILES = {
    "com.quantt.cef.daily.plist": job_plist(
        "com.quantt.cef.daily", "cef", [(8, 30), (12, 0)],
        "MORNING DECISION + noon retry (W3 Part A, 2026-09-11). Was 17:15, "
        "which raced the NAV publication; see ops/session_plan.py."),
    # Named com.quantt.cef_pm, not com.quantt.cef.pm: ops/doctor.py resolves a
    # job's plist as com.quantt.{job}[.daily].plist, so the label that matches
    # the job name is the one every existing check already finds.
    "com.quantt.cef_pm.plist": job_plist(
        "com.quantt.cef_pm", "cef_pm", [(17, 30)],
        "EVENING: capture today's fills before IB's 03:00 restart destroys "
        "them, write tonight's pair, and decide ONLY if the morning could not."),
    "com.quantt.awake.plist": awake_plist(),
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in FILES.items():
        (OUT / name).write_text(body)
        print(f"wrote {OUT / name}")
    print("\nA HUMAN installs these -- launchctl is on the order path:\n")
    print("  cd", OUT)
    for name in FILES:
        label = name[:-6]
        print(f"  cp {name} ~/Library/LaunchAgents/{name} && \\")
        print(f"    launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/{name} 2>/dev/null; \\")
        print(f"    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/{name}   # {label}")
    print("\n  launchctl list | grep quantt      # confirm all three are loaded")
