"""Verify a broker endpoint, then repoint the book at it.

    python3 -m ops.switch_broker --verify           # check 4002, change nothing
    python3 -m ops.switch_broker --verify --port 4002
    python3 -m ops.switch_broker --to 4002          # verify, then rewrite config/.env
    python3 -m ops.switch_broker --rollback         # restore the previous config/.env

WHY A SCRIPT AND NOT A ONE-LINE EDIT
------------------------------------
Moving from TWS (7497) to IB Gateway (4002) is one line in `config/.env`, and
that is exactly what makes it dangerous: `IBKR_PORT` is the only thing that
decides which brokerage account this repo trades. Point it at a socket that
happens to answer and every guard downstream still passes -- `arm()` will
happily adopt "broker truth" from an account that is not yours, and
`place_targets` will diff a $500k book against it.

So the port is never changed without proving three things about the target:

  1. it speaks the API, not just TCP.  A listening socket is not a logged-in
     gateway. The August outage looked identical at the TCP layer to a gateway
     that was up but not authenticated.
  2. it is the SAME account.  Compared by account id against the currently
     configured endpoint when that is still reachable, and against what the
     shadow ledgers claim when it is not.
  3. its positions are recognisable.  A right-account-wrong-mode connection
     (paper login pointed at live, or vice versa) shows up here as a position
     set that does not overlap the ledgers at all.

Only then is `config/.env` rewritten, and the previous copy is kept so
`--rollback` is always available.

CUTOVER ORDER MATTERS. IBKR allows one market-data session per username, so
Gateway and TWS running at once will fight over it and produce failures that
read like config bugs. Stop TWS BEFORE starting Gateway, then run --verify.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ENV_PATH = REPO_ROOT / "config" / ".env"
BACKUP_SUFFIX = ".switch_broker.bak"

# Reserved so a probe never collides with a live session: the books use 17/45/46
# and the read-only tools use +50/+60/+70 on those.
PROBE_CLIENT_ID = 199


def _probe(host, port, client_id=PROBE_CLIENT_ID, timeout=20) -> dict:
    """Open a read-only API session. Returns {} if the endpoint is not usable."""
    import ib_async as ibapi

    app = ibapi.IB()
    try:
        app.connect(host, int(port), clientId=int(client_id),
                    readonly=True, timeout=timeout)
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}
    try:
        accounts = list(app.managedAccounts() or [])
        pos = {}
        for p in app.positions():
            s = p.contract.symbol
            pos[s] = pos.get(s, 0.0) + float(p.position)
        nlv = None
        for row in app.accountSummary():
            if row.tag == "NetLiquidation":
                nlv = float(row.value)
                break
        return {"ok": True, "accounts": accounts, "positions": pos, "nlv": nlv}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}
    finally:
        try:
            app.disconnect()
        except Exception:
            pass


def _ledger_claims() -> dict:
    """{symbol: shares} summed across every book's shadow ledgers."""
    from ops.reconcile_orders import ALL_BOOKS, _sleeves, ledger_positions
    out = {}
    for bpath, broot in ALL_BOOKS:
        bpath, broot = REPO_ROOT / bpath, REPO_ROOT / broot
        if not bpath.exists():
            continue
        try:
            for sl in _sleeves(bpath):
                for s, q in ledger_positions(broot, sl).items():
                    out[s] = out.get(s, 0.0) + q
        except Exception:
            continue
    return out


def _read_env() -> list[str]:
    return ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []


def _current_port(lines) -> str | None:
    for ln in lines:
        if ln.strip().startswith("IBKR_PORT="):
            return ln.split("=", 1)[1].strip()
    return None


def _current_host(lines) -> str:
    for ln in lines:
        if ln.strip().startswith("IBKR_HOST="):
            return ln.split("=", 1)[1].strip()
    return "127.0.0.1"


def verify(port, host=None, quiet=False) -> tuple[bool, dict]:
    lines = _read_env()
    host = host or _current_host(lines)
    cur_port = _current_port(lines)

    def say(*a):
        if not quiet:
            print(*a)

    say(f"[switch] target   {host}:{port}")
    say(f"[switch] current  {host}:{cur_port}")

    tgt = _probe(host, port)
    if not tgt.get("ok"):
        say(f"[switch] [FAIL] target does not speak the API: {tgt.get('error')}")
        say("         A listening socket is not a logged-in gateway. If you just")
        say("         started it, give IBC a minute to complete the login.")
        return False, tgt
    say(f"[switch] [PASS] target answers: accounts={tgt['accounts']} "
        f"NLV={tgt['nlv']:,.0f}" if tgt.get("nlv") is not None
        else f"[switch] [PASS] target answers: accounts={tgt['accounts']}")
    say(f"[switch]        {len(tgt['positions'])} position(s)")

    problems = []

    # -- same account? --------------------------------------------------
    cur = _probe(host, cur_port) if cur_port and str(cur_port) != str(port) else None
    if cur and cur.get("ok"):
        say(f"[switch] current endpoint also live: accounts={cur['accounts']}")
        if set(cur["accounts"]) != set(tgt["accounts"]):
            problems.append(
                f"account mismatch: current {cur['accounts']} vs target "
                f"{tgt['accounts']} — this would repoint the book at a "
                f"DIFFERENT account")
        else:
            say("[switch] [PASS] same account id on both endpoints")
        both = set(cur["positions"]) | set(tgt["positions"])
        diff = [s for s in both
                if abs(cur["positions"].get(s, 0.0)
                       - tgt["positions"].get(s, 0.0)) > 1e-6]
        if diff:
            problems.append(
                f"{len(diff)} symbol(s) differ between endpoints ({', '.join(sorted(diff)[:8])}"
                f"{'...' if len(diff) > 8 else ''}) — same account id but "
                f"different holdings means different trading mode")
        else:
            say(f"[switch] [PASS] identical positions on both endpoints "
                f"({len(both)} symbol(s))")
        say("\n[switch] NOTE both endpoints answered at once. IBKR allows one")
        say("         market-data session per username — stop the old one before")
        say("         you rely on the new one, or they will fight over it.")
    else:
        # Either the old endpoint is gone (expected: you stopped TWS before
        # starting Gateway), or target IS current and there is nothing to
        # compare it to. Both fall back to asking whether the target looks like
        # OUR account, but they are not the same situation, so say which.
        if cur_port and str(cur_port) == str(port):
            say("[switch] target is the currently configured endpoint; "
                "comparing against ledger claims")
        else:
            say("[switch] current endpoint unreachable; comparing target "
                "against ledger claims instead")
        claims = _ledger_claims()
        if not claims:
            problems.append("no ledger positions to compare against, and the "
                            "current endpoint is unreachable — cannot confirm "
                            "this is the right account")
        else:
            overlap = [s for s in claims if s in tgt["positions"]]
            frac = len(overlap) / max(len(claims), 1)
            say(f"[switch]        {len(overlap)}/{len(claims)} claimed symbol(s) "
                f"present at target ({frac:.0%})")
            if frac < 0.8:
                problems.append(
                    f"only {frac:.0%} of ledger-claimed symbols are present at "
                    f"the target — this does not look like the account the "
                    f"books have been trading")
            else:
                say("[switch] [PASS] target holds the book's positions")

    if problems:
        say("\n[switch] REFUSING TO SWITCH")
        for p in problems:
            say(f"  - {p}")
        return False, tgt
    say("\n[switch] verification passed")
    return True, tgt


def switch(port, host=None) -> int:
    ok, _ = verify(port, host)
    if not ok:
        return 1
    lines = _read_env()
    if not lines:
        print(f"[switch] {ENV_PATH} does not exist — nothing to rewrite")
        return 1
    backup = ENV_PATH.with_suffix(ENV_PATH.suffix + BACKUP_SUFFIX)
    shutil.copy2(ENV_PATH, backup)
    stamp = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    out, replaced = [], False
    for ln in lines:
        if ln.strip().startswith("IBKR_PORT="):
            out.append(f"# switched by ops/switch_broker.py at {stamp} "
                       f"(was: {ln.strip()})")
            out.append(f"IBKR_PORT={port}")
            replaced = True
        else:
            out.append(ln)
    if not replaced:
        out.append(f"# added by ops/switch_broker.py at {stamp}")
        out.append(f"IBKR_PORT={port}")
    ENV_PATH.write_text("\n".join(out) + "\n")
    print(f"[switch] {ENV_PATH} -> IBKR_PORT={port}")
    print(f"[switch] previous copy at {backup}")
    print("[switch] run `python3 -m ops.preflight` style checks, or just run a "
          "book, to confirm end to end.")
    return 0


def rollback() -> int:
    backup = ENV_PATH.with_suffix(ENV_PATH.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        print(f"[switch] no backup at {backup}")
        return 1
    shutil.copy2(backup, ENV_PATH)
    print(f"[switch] restored {ENV_PATH} from {backup}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verify", action="store_true",
                    help="check the endpoint and change nothing")
    ap.add_argument("--to", type=int, default=None,
                    help="verify, then repoint config/.env at this port")
    ap.add_argument("--port", type=int, default=4002,
                    help="port to verify (default 4002, paper IB Gateway)")
    ap.add_argument("--host", default=None)
    ap.add_argument("--rollback", action="store_true")
    a = ap.parse_args(argv)

    if a.rollback:
        return rollback()
    if a.to is not None:
        return switch(a.to, a.host)
    if a.verify:
        ok, _ = verify(a.port, a.host)
        return 0 if ok else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
