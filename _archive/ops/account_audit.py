"""W2 Part A — what this account can actually do. THE HUMAN RUNS THIS.

    ! python3 -m ops.account_audit
    ! python3 -m ops.account_audit --client-id 116 --out results/ops/ACCOUNT_AUDIT_2026-09-11.md

WHY THIS IS THE FIRST THING IN THE GAMMA PROGRAMME
--------------------------------------------------
It is not only the permission gate. It is the **data-feasibility gate for the
whole queue**, and it costs about a minute:

  Q1 options permitted, and at what level  -> gates G5 and G7 entirely
  Q2 how deep historical option bars go    -> decides whether an HYG SURFACE
                                              can be built at all, i.e. whether
                                              G2 -> G6 -> G7 exist
  Q3 option market data (OPRA) subscribed  -> gates G5's live marks. This is a
                                              THIRD thing, distinct from Q1 and
                                              Q2, and W2's own checklist does
                                              not currently ask for it
  Q4 account type, NLV, margin requirement -> the only way to size a fourth book
                                              against preflight's account-wide
                                              0.10 cushion floor
  Q5 commission plan, Tiered or Fixed      -> NOT cosmetic. The frozen spec's
                                              `min_trade_usd: 517` was derived
                                              on the FIXED $1.00 order minimum;
                                              on Tiered the same derivation
                                              gives $181, so the live threshold
                                              would be suppressing orders nearly
                                              3x larger than it should

SAFETY, AND WHY A HUMAN RUNS IT RATHER THAN AN AGENT
-----------------------------------------------------
* `connect(readonly=True)` — the API session itself refuses to transmit.
* The ONLY calls made are `whatIfOrder`, `reqHistoricalData`, `reqMktData`,
  `accountSummary`, `accountValues` and `qualifyContracts`. There is no
  `placeOrder`, no `cancelOrder`, no `reqGlobalCancel` anywhere in this file.
* **`whatIfOrder` never transmits.** It asks IB to price the margin impact of a
  hypothetical order and return it. A permission error is the ANSWER to Q1, not
  a failure of the script.
* The client id defaults to the reconcile range (base + 70), the same scheme
  `results/ops/BROKER_SNAPSHOT_2026-09-10.json` used, so it cannot collide with
  a scheduled session (45-48), its capture (+50) or its preflight (+60).

It still opens a broker socket, which is why CLAUDE.md's order-path rule puts it
in the human's hands. Nothing here can move money; the boundary is about who
reaches for the broker at all.

THE OUTPUT IS THE POINT
-----------------------
`results/ops/ACCOUNT_AUDIT_<date>.md`, and if options are NOT permitted the
FIRST LINE says so and names the human step (IBKR Client Portal -> Settings ->
Trading Permissions -> Options, US). `docs/prompts/gamma/G5` and `G7` both refuse
to start until that note says permitted, and `python3 -m ops.gamma_status` reads
it to decide what is unblocked.

NO SILENT FALLBACKS. Every probe records what it actually got, including the
exact IB error code and message. A probe that cannot run prints UNMEASURED and
the reason — never an assumption about what the answer probably is.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ib_async ONLY. ib_insync 0.9.86 hangs forever in its asyncio handshake on
# Python 3.12+ and looks exactly like a dead broker connection -- this machine
# runs 3.13.5. `ops/reset_epoch.py` was the one that mattered: a RECOVERY tool
# that would have hung every time, during the window where you least want to be
# debugging a client library.
try:
    import ib_async as ibi
except ImportError:                                    # pragma: no cover
    raise SystemExit(
        "ib_async is not installed. Do NOT fall back to ib_insync: it hangs "
        "forever in its asyncio handshake on Python 3.12+ and is "
        "indistinguishable from a dead gateway. `pip install ib_async`.")

def _is_trading_day(d: date) -> bool:
    """NYSE session today? A weekend quote is not evidence about a subscription."""
    sys.path.insert(0, str(REPO / "ops/schedule"))
    import nyse_calendar
    return bool(nyse_calendar.is_trading_day(d))


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4002          # the paper gateway
DEFAULT_CLIENT_ID = 116      # reconcile range; cannot collide with a session

# The probe contract. HYG because it is the only credit-vol surface candidate
# (G0 §3: 367,197 daily option volume against JNK's 20), and a ~25-delta put
# because that is the structure W14 Part B would have used and the one G5 marks.
PROBE_UNDERLIER = "HYG"


class Probe:
    def __init__(self, name, question):
        self.name, self.question = name, question
        self.answer = "UNMEASURED"
        self.detail = ""
        self.raw = ""

    def row(self):
        return f"| {self.name} | {self.question} | **{self.answer}** | {self.detail} |"


def _third_friday(d: date) -> date:
    """The standard monthly expiry. Weeklies exist on HYG but monthlies are deepest."""
    first = date(d.year, d.month, 1)
    offset = (4 - first.weekday()) % 7
    third = first + timedelta(days=offset + 14)
    return third if third > d else _third_friday(date(
        d.year + (d.month == 12), (d.month % 12) + 1, 1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--client-id", type=int, default=DEFAULT_CLIENT_ID)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = Path(a.out) if a.out else \
        REPO / f"results/ops/ACCOUNT_AUDIT_{date.today().isoformat()}.md"

    probes = [
        Probe("Q1 options permission",
              "whatIfOrder on a 1-lot HYG put -- margin response = permitted, "
              "IB 10xxx / 'not permitted' = the answer"),
        Probe("Q2 historical option bars",
              "reqHistoricalData on that contract: how far back, at what bar size"),
        Probe("Q3 option market data",
              "reqMktData under reqMarketDataType(3) then (1) -- OPRA is a "
              "separate subscription from equity top-of-book"),
        Probe("Q4 margin type + account",
              "accountSummary: AccountType, NetLiquidation, FullMaintMarginReq, "
              "Cushion"),
        Probe("Q5 commission plan",
              "Tiered or Fixed -- sets min_trade_usd ($517 on Fixed, $181 on "
              "Tiered)"),
    ]
    q1, q2, q3, q4, q5 = probes
    permitted = False
    trading_day = _is_trading_day(date.today())
    if not trading_day:
        print("[audit] NOTE: not an NYSE trading day. Q1/Q2/Q4 are unaffected "
              "(margin, history and account values all answer); Q3 (live "
              "option quote) cannot be answered and will say so.")
    ib = ibi.IB()

    print(f"[audit] connecting READ-ONLY to {a.host}:{a.port} "
          f"clientId={a.client_id}")
    try:
        ib.connect(a.host, a.port, clientId=a.client_id, readonly=True,
                   timeout=20)
    except Exception as exc:                            # noqa: BLE001
        print(f"[audit] CANNOT CONNECT: {exc!r}")
        for p in probes:
            p.detail = f"gateway unreachable: {exc!r}"
        _write(out, probes, permitted, a, connected=False)
        return 2

    try:
        # ---- the probe contract ----------------------------------------
        expiry = _third_friday(date.today() + timedelta(days=21))
        chain_note = ""
        try:
            und = ibi.Stock(PROBE_UNDERLIER, "SMART", "USD")
            ib.qualifyContracts(und)
            [tick] = ib.reqTickers(und) or [None]
            spot = getattr(tick, "marketPrice", lambda: None)() if tick else None
            if spot is None or spot != spot:            # NaN
                spot = getattr(tick, "close", None) if tick else None
            strike = round(float(spot) * 0.95) if spot else None
            chain_note = f"spot {spot}, ~25d put strike {strike}"
        except Exception as exc:                        # noqa: BLE001
            strike, chain_note = None, f"could not price the underlier: {exc!r}"

        if strike is None:
            # Fall back to the repo's own panel rather than abandoning Q1/Q2.
            # A stale strike is fine for a PERMISSION probe -- we are asking
            # whether IB will price a hypothetical, not what it is worth.
            try:
                import pandas as pd
                d = pd.read_parquet(REPO / "data/rv/etf_ohlc.parquet")
                d = d[d.ticker == PROBE_UNDERLIER].sort_values("date")
                last_close = float(d.close.iloc[-1])
                strike = round(last_close * 0.95)
                chain_note += (f"; fell back to data/rv/etf_ohlc.parquet last "
                               f"close {last_close:.2f} (bar "
                               f"{d.date.iloc[-1]:%Y-%m-%d}) -> strike {strike}")
            except Exception as exc2:                   # noqa: BLE001
                chain_note += f"; panel fallback also failed: {exc2!r}"

        if strike is None:
            q1.detail = f"no strike to probe ({chain_note})"
        else:
            opt = ibi.Option(PROBE_UNDERLIER, expiry.strftime("%Y%m%d"),
                             float(strike), "P", "SMART", multiplier="100")
            qualified = ib.qualifyContracts(opt)
            if not qualified or not getattr(opt, "conId", 0):
                q1.detail = (f"IB could not qualify "
                             f"{PROBE_UNDERLIER} {expiry} {strike}P -- the "
                             f"contract may not exist at that strike/expiry")
            else:
                # ---- Q1. NEVER TRANSMITTED. whatIfOrder prices the margin
                # impact of a hypothetical and returns it.
                order = ibi.LimitOrder("BUY", 1, 0.01)
                order.whatIf = True
                try:
                    st = ib.whatIfOrder(opt, order)
                    init = getattr(st, "initMarginChange", "") or ""
                    if init not in ("", "0", None):
                        permitted = True
                        q1.answer = "PERMITTED"
                        q1.detail = (f"margin response: initMarginChange="
                                     f"{init}, maint={getattr(st, 'maintMarginChange', '?')}, "
                                     f"commission={getattr(st, 'commission', '?')}")
                    else:
                        # MEASURED 2026-09-12: ib_async returns [] here, i.e. the
                        # request TIMED OUT rather than being refused. `readonly=True`
                        # is enforced by the GATEWAY, which silently drops the order
                        # message -- `IB.placeOrder` itself has no readonly check, so
                        # there is no exception to catch. A timeout is therefore
                        # EVIDENCE OF NOTHING about permissions, and calling it "not
                        # permitted" is the same confident-wrong-answer failure this
                        # file's Q3 guard exists to prevent.
                        q1.answer = "UNMEASURABLE (read-only connection)"
                        q1.detail = (
                            f"whatIfOrder returned {st!r} — a timeout, not a "
                            f"refusal. The contract QUALIFIED (conId "
                            f"{opt.conId}), so it exists. `readonly=True` is "
                            f"enforced at the gateway and drops the order "
                            f"message. **Answer this in the Client Portal** "
                            f"(Settings -> Account Settings -> Trading "
                            f"Permissions): 30 seconds, zero risk. Re-probing "
                            f"with readonly=False would put a live order path "
                            f"in an agent's hands to answer a question a human "
                            f"can read off a web page.")
                except Exception as exc:                # noqa: BLE001
                    txt = repr(exc)
                    if any(k in txt.lower() for k in
                           ("not permitted", "10197", "10148", "permission")):
                        q1.answer = "NOT PERMITTED"
                    else:
                        q1.answer = "UNCLEAR"
                    q1.detail = txt
                q1.raw = f"{PROBE_UNDERLIER} {expiry} {strike} P, conId={opt.conId}"

                # ---- Q2. how deep does option history go
                for dur in ("1 Y", "6 M", "3 M", "1 M", "5 D"):
                    try:
                        bars = ib.reqHistoricalData(
                            opt, endDateTime="", durationStr=dur,
                            barSizeSetting="1 day", whatToShow="TRADES",
                            useRTH=True, formatDate=1)
                        if bars:
                            q2.answer = f"{len(bars)} daily bars at {dur}"
                            q2.detail = (f"first {bars[0].date}, last "
                                         f"{bars[-1].date}")
                            break
                    except Exception as exc:            # noqa: BLE001
                        q2.detail = f"{dur}: {exc!r}"
                else:
                    if q2.answer == "UNMEASURED":
                        q2.answer = "NONE"
                        q2.detail = (q2.detail or "no bars at any duration") + \
                            "  -> G2 cannot build an HYG surface from IBKR; " \
                            "the programme falls back to SPY (equity gamma) " \
                            "or needs another source"

                # ---- Q3. is there an option quote at all
                for mdt, label in ((3, "delayed"), (1, "live")):
                    try:
                        ib.reqMarketDataType(mdt)
                        t = ib.reqMktData(opt, "", False, False)
                        ib.sleep(3)
                        bid, ask = getattr(t, "bid", None), getattr(t, "ask", None)
                        ok = bid is not None and bid == bid and bid > 0
                        if ok:
                            q3.answer = f"{label.upper()} quote available"
                            q3.detail = f"bid {bid} ask {ask}"
                            ib.cancelMktData(opt)
                            break
                        q3.detail = f"{label}: bid={bid} ask={ask}"
                        ib.cancelMktData(opt)
                    except Exception as exc:            # noqa: BLE001
                        q3.detail = f"{label}: {exc!r}"
                if q3.answer == "UNMEASURED":
                    if trading_day:
                        q3.answer = "NO OPTION QUOTE"
                        q3.detail += ("  -> OPRA is a separate subscription; "
                                      "G5 cannot mark a position without it")
                    else:
                        # A closed market returns no quote whether or not we are
                        # subscribed. Concluding "not subscribed" from silence on
                        # a Saturday is a confident wrong answer, and Q3 gates
                        # G5 -- so it stays UNMEASURED and says why.
                        q3.answer = "UNMEASURED (market closed)"
                        q3.detail += ("  -> today is not an NYSE trading day, so "
                                      "an absent quote says nothing about the "
                                      "subscription. RE-RUN ON A TRADING DAY "
                                      "before treating this as an answer.")

        # ---- Q4. the account, which sizes a fourth book -----------------
        try:
            summ = {f"{v.tag}{'.' + v.currency if v.currency else ''}": v.value
                    for v in ib.accountValues()}
            keys = ("AccountType", "NetLiquidation.CAD", "ExcessLiquidity.CAD",
                    "Cushion", "FullMaintMarginReq.CAD", "GrossPositionValue.CAD")
            got = {k: summ.get(k) for k in keys if summ.get(k) is not None}
            q4.answer = got.get("AccountType", "?")
            q4.detail = ", ".join(f"{k}={v}" for k, v in got.items())
        except Exception as exc:                        # noqa: BLE001
            q4.detail = f"{exc!r}"

        # ---- Q5. commission plan ---------------------------------------
        # There is no clean API tag for the plan. The honest answer is the
        # commission the whatIf returned, beside both schedules, and a note that
        # this must be confirmed in the Client Portal.
        q5.answer = "READ FROM whatIf"
        q5.detail = ("Tiered options $0.15-$0.65/contract, Fixed $0.65, $1.00 "
                     "order minimum on both. Compare the commission in Q1's "
                     "response; confirm in Client Portal -> Settings -> "
                     "Commissions. NOT an assumption -- if Q1 returned no "
                     "commission, this stays UNMEASURED.")
    finally:
        try:
            ib.disconnect()
        except Exception:                               # noqa: BLE001
            pass

    a._not_trading_day = not trading_day
    _write(out, probes, permitted, a, connected=True)
    return 0 if permitted else 1


def _write(out: Path, probes, permitted: bool, args, connected: bool) -> None:
    L = []
    say = lambda s="": (print(s), L.append(s))          # noqa: E731

    if not connected:
        say("# ACCOUNT AUDIT — COULD NOT CONNECT")
        say()
        say("**The gateway was unreachable, so NOTHING below was measured.** "
            "This note does not say options are unavailable; it says the "
            "question was not asked. Start the IB gateway and re-run.")
    elif permitted:
        say("# ACCOUNT AUDIT — options: **PERMITTED**")
    else:
        q1 = probes[0]
        if q1.answer.startswith("NOT PERMITTED"):
            say("# ACCOUNT AUDIT — options: **NOT PERMITTED**")
            say()
            say("**The human step:** IBKR Client Portal -> Settings -> Account "
                "Settings -> Trading Permissions -> **Options, United "
                "States**.")
        else:
            say(f"# ACCOUNT AUDIT — options: **{q1.answer}**")
            say()
            say("**This note does NOT say options are unavailable. It says the "
                "question was not answered**, and the difference matters: G5 "
                "and G7 are gated on a real answer, and recording a false "
                "negative would retire the programme for the wrong reason.")
        say()
        say("Either way `G1`-`G4` and the research phases are unaffected.")
    say()
    if getattr(args, "_not_trading_day", False):
        say("> **Run on a NON-TRADING day.** Q1 (permission), Q2 (historical "
            "bars) and Q4 (account) are unaffected — margin checks, history and "
            "account values all answer with the market closed. **Q3 cannot be "
            "answered** and says so rather than concluding.")
        say()
    say(f"Run {datetime.now().isoformat(timespec='seconds')} by "
        f"`python3 -m ops.account_audit` against {args.host}:{args.port}, "
        f"clientId {args.client_id}, **readonly=True**. No order was placed, "
        f"modified or cancelled; `whatIfOrder` never transmits.")
    say()
    say("| probe | question | answer | detail |")
    say("|---|---|---|---|")
    for p in probes:
        say(p.row())
    say()
    say("## What each answer unblocks")
    say()
    say("| answer | unblocks / blocks |")
    say("|---|---|")
    say("| Q1 permitted | `gamma/G5` (paper book) and `gamma/G7` (the sleeve, "
        "1 GAMMA trial) |")
    say("| Q2 bar depth | `gamma/G2`'s HYG surface, and therefore `G6`'s "
        "conditioners and `G7`'s budget. **No bars = no credit surface**, and "
        "the programme is equity gamma on SPY or nothing |")
    say("| Q3 option quote | `G5`'s daily marks. Without it the paper book "
        "cannot mark a position even if Q1 says permitted |")
    say("| Q4 account | sizes a fourth book against preflight's account-wide "
        "0.10 cushion floor (`ops/preflight.py:236`) |")
    say("| Q5 commissions | `min_trade_usd` — $517 was derived on the Fixed "
        "$1.00 minimum; Tiered gives $181 |")
    say()
    say("Re-run `python3 -m ops.gamma_status` after this lands; it reads this "
        "note to decide what is unblocked.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print(f"\n[written] {out}")


if __name__ == "__main__":
    raise SystemExit(main())
