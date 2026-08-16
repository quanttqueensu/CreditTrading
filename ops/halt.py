"""Durable halt records and the alerting that makes a halt impossible to miss.

WHY THIS FILE EXISTS
--------------------
On 2026-07-31 two separate faults produced total silence:

  1. 09:35 — the launchd job died with exit 126 (`getcwd: Operation not
     permitted`, a TCC/Full-Disk-Access fault). It wrote two lines to a log and
     transmitted nothing.
  2. 16:33 — the CEF job DID trade, then the shadow ledger KeyErrored on a
     missing cost entry. The exception was caught and printed as one `repr()`
     line inside an otherwise successful-looking run that ended with "ok".

In both cases the operator learned nothing until a human went reading logs. For
a book that is supposed to run unattended, "the failure is in a log file" is the
same as no failure handling at all — logs are pull, and an unattended system
needs push.

So a halt here is three things at once, in increasing order of loudness:

  * `ops/HALT.md`   — durable, greppable, and read by `ops/preflight.py` as a
                      HARD GATE. This is the one that actually stops the money:
                      it survives reboots and outlives any notification.
  * macOS banner + spoken alert — reaches the operator if they are at the machine.
  * email           — reaches them if they are not.

The ordering matters. Alerting is best-effort and must NEVER be able to mask the
fault it is reporting, so every notification path is individually wrapped: an
SMTP timeout cannot prevent HALT.md from being written, and a failed banner
cannot swallow the traceback. The file write happens FIRST and unguarded.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HALT_PATH = REPO_ROOT / "ops" / "HALT.md"
HALT_ARCHIVE = REPO_ROOT / "ops" / "halts"

DEFAULT_ALERT_TO = "simon.jarvis0@gmail.com"


# -- environment ----------------------------------------------------------

def _load_env_file(path=REPO_ROOT / "config" / ".env") -> dict:
    """Parse config/.env. A launchd job inherits almost no environment, so the
    alert credentials cannot be assumed to be exported — read them from disk."""
    out = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def _cfg(key, default=None):
    return os.environ.get(key) or _load_env_file().get(key) or default


# -- the durable record ---------------------------------------------------

def write_halt(reason: str, detail: str = "", source: str = "") -> Path:
    """Record a halt and alert on it. Returns the path to `ops/HALT.md`.

    Writing the file is deliberately NOT wrapped in try/except: if we cannot
    persist the halt we would rather crash than continue believing the book is
    protected. Every alert channel after it IS wrapped, for the opposite reason.
    """
    stamp = datetime.now()
    HALT_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing = HALT_PATH.read_text() if HALT_PATH.exists() else ""
    entry = (f"## {stamp:%Y-%m-%d %H:%M:%S}  {reason}\n\n"
             f"- **source**: `{source or 'unspecified'}`\n"
             f"- **state**: trading is BLOCKED until this file is cleared\n\n"
             f"{detail.strip()}\n\n"
             f"To clear once the cause is genuinely fixed:\n\n"
             f"    python3 -c \"from ops.halt import clear_halt; "
             f"clear_halt('what you fixed')\"\n\n---\n\n")

    header = ("# HALT — automated trading is blocked\n\n"
              "`ops/preflight.py` reads this file before every scheduled session "
              "and will not arm live orders while it exists. Data collection and "
              "logging continue regardless: a halted book still records, it just "
              "does not trade.\n\n"
              "Most recent halt first.\n\n---\n\n")
    body = existing.split("---\n\n", 1)[1] if "---\n\n" in existing else ""
    HALT_PATH.write_text(header + entry + body)

    alert(subject=f"QUANTT HALT: {reason}",
          body=f"{reason}\n\nsource: {source}\n\n{detail}",
          speak="Quant book halted. Trading is blocked.")
    return HALT_PATH


def read_halt():
    """The active halt as {'reason', 'when', 'text'}, or None if clear."""
    if not HALT_PATH.exists():
        return None
    text = HALT_PATH.read_text()
    reason, when = "unknown", ""
    for line in text.splitlines():
        if line.startswith("## "):
            head = line[3:].strip()
            when, _, reason = head.partition("  ")
            break
    return {"reason": reason.strip() or "unknown", "when": when.strip(),
            "text": text, "path": str(HALT_PATH)}


def clear_halt(note: str = "") -> bool:
    """Archive the active halt. Deliberately a manual, attributed act.

    Self-clearing would defeat the point: the preflight gate can re-arm itself
    when its CHECKS pass, but a desync that required a ledger rebuild needs a
    human to say the rebuild happened and was correct.
    """
    if not HALT_PATH.exists():
        print("[halt] no active halt")
        return False
    HALT_ARCHIVE.mkdir(parents=True, exist_ok=True)
    dest = HALT_ARCHIVE / f"HALT_{datetime.now():%Y%m%d_%H%M%S}.md"
    shutil.move(str(HALT_PATH), dest)
    if note:
        dest.write_text(dest.read_text() +
                        f"\n\nCLEARED {datetime.now():%Y-%m-%d %H:%M:%S}: {note}\n")
    print(f"[halt] cleared -> {dest}")
    alert(subject="QUANTT halt cleared",
          body=f"{note}\n\narchived to {dest}", speak="Quant halt cleared.")
    return True


# -- alerting -------------------------------------------------------------

def alert(subject: str, body: str = "", speak: str = "") -> dict:
    """Best-effort push on every configured channel. Never raises.

    Returns per-channel outcomes so a caller (and the daily log) can see which
    ones actually delivered — a silent alerting system is the exact failure this
    module exists to prevent, so "we tried to tell you" must itself be visible.
    """
    out = {}
    out["notification"] = _notify_macos(subject, body)
    if speak:
        out["speech"] = _speak(speak)
    out["email"] = _email(subject, body)
    for channel, res in out.items():
        if res is not True:
            print(f"[alert] {channel}: {res}")
    return out


def _notify_macos(title: str, body: str):
    try:
        msg = (body or "").replace('"', "'").replace("\n", " ")[:240]
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{msg}" with title "{title[:120]}"'],
            check=True, capture_output=True, timeout=10)
        return True
    except Exception as exc:
        return f"failed ({exc!r})"


def _speak(phrase: str):
    try:
        subprocess.run(["say", phrase[:200]], check=True,
                       capture_output=True, timeout=20)
        return True
    except Exception as exc:
        return f"failed ({exc!r})"


def _email(subject: str, body: str):
    """SMTP over STARTTLS. Configured entirely from config/.env:

        ALERT_EMAIL_TO=simon.jarvis0@gmail.com
        ALERT_SMTP_HOST=smtp.gmail.com
        ALERT_SMTP_PORT=587
        ALERT_SMTP_USER=simon.jarvis0@gmail.com
        ALERT_SMTP_PASS=<16-char Google app password, NOT the account password>

    Gmail rejects a plain account password over SMTP, so this needs an App
    Password from https://myaccount.google.com/apppasswords (requires 2FA on).
    Absent credentials is a configuration state, not an error — it returns a
    message saying so rather than raising, because a missing mail password must
    never stop a halt from being recorded.
    """
    to = _cfg("ALERT_EMAIL_TO", DEFAULT_ALERT_TO)
    host = _cfg("ALERT_SMTP_HOST", "smtp.gmail.com")
    port = int(_cfg("ALERT_SMTP_PORT", "587"))
    user = _cfg("ALERT_SMTP_USER")
    password = _cfg("ALERT_SMTP_PASS")
    if not (user and password):
        return ("not configured — add ALERT_SMTP_USER and ALERT_SMTP_PASS "
                "(a Google App Password) to config/.env to enable email alerts")
    try:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = subject[:200]
        msg["From"] = user
        msg["To"] = to
        msg.set_content(f"{body}\n\n-- \nQUANTT automated book, "
                        f"{datetime.now():%Y-%m-%d %H:%M:%S} local\n"
                        f"host: {os.uname().nodename}\n")
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
        return True
    except Exception as exc:
        return f"failed ({exc!r})"


# -- heartbeat ------------------------------------------------------------

HEARTBEAT_PATH = REPO_ROOT / "ops" / "heartbeat.json"


def beat(job: str, status: str, detail: dict | None = None) -> Path:
    """Record that `job` reached `status` just now.

    Silence and success are indistinguishable to an unattended system — a job
    that never fired looks exactly like one that fired and did nothing. The
    heartbeat makes the difference observable: `ops/preflight.py` compares the
    last beat against the NYSE calendar and alerts on a session that produced no
    beat at all, which is the ONLY way the 09:35 exit-126 failure would have been
    caught automatically.
    """
    hist = {}
    if HEARTBEAT_PATH.exists():
        try:
            hist = json.loads(HEARTBEAT_PATH.read_text())
        except Exception:
            hist = {}
    hist[job] = {"status": status, "at": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
                 "date": f"{datetime.now():%Y-%m-%d}", "detail": detail or {}}
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(json.dumps(hist, indent=2))
    return HEARTBEAT_PATH


def last_beat(job: str):
    if not HEARTBEAT_PATH.exists():
        return None
    try:
        return json.loads(HEARTBEAT_PATH.read_text()).get(job)
    except Exception:
        return None
