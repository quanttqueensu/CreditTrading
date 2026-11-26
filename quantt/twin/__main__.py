"""`python3 -m quantt.twin {probe,epoch,send,approve,verify,compare,cancel-open,feed}` (quantt/twin/__init__.py).

Environment (every one required where the phase reads it; none has a default):
  QUANTT_STATE_DIR                the twin's state directory, named `twin`
  QUANTT_TWIN_CEF_STATE / _C4_STATE / _EVENTS_STATE   the books' state directories (read-only)
  QUANTT_ENV_FILE, QUANTT_TWIN_ALPACA_DATA_BOOK       Alpaca keys for market data only
  QUANTT_IBKR_HOST / _PORT / _CLIENT_ID / _ACCOUNT    the Gateway and the expected paper account
  QUANTT_IBKR_FEED_DIR            feed only: the feed directory the shadow user reads (quantt/twin/feed.py)
  DRY_RUN                         transmits only when exactly "0" (rule 4); the feed sends nothing
  QUANTT_TWIN_STAGING             set to anything: nothing can transmit
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path


def _deps(env):
    from quantt.broker.ibkr import IBKRClient, IBKRConfig
    from quantt.session import records as rec
    from quantt.twin import config
    from quantt.twin.market import MarketData
    from quantt.twin.run import Deps
    state = rec.state_dir_from_env(env)
    cfg = IBKRConfig.from_env(env)
    lock = config.gateway_lock_path(state)       # B10: never connected while the feed is (config.py)
    return Deps(env=env, state=state, market=MarketData.from_environment(env),
                ibkr=lambda mode: IBKRClient(cfg, mode=mode, session_lock=lock,
                                             lock_wait_s=config.TWIN_LOCK_WAIT_S))


def _feed_deps(env):
    """The feed's (quantt/twin/feed.py): a READ client only, which never waits for the lock."""
    from quantt.broker.ibkr import IBKRClient, IBKRConfig
    from quantt.session import records as rec
    from quantt.twin import config, feed
    from quantt.twin.market import MarketData
    state = rec.state_dir_from_env(env)
    cfg = IBKRConfig.from_env(env)
    lock = config.gateway_lock_path(state)
    import signal
    return feed.FeedDeps(env=env, state=state, feed=feed.feed_dir_from_env(env),
                         market=MarketData.from_environment(env),
                         read_client=lambda: IBKRClient(cfg, mode="read", session_lock=lock, lock_wait_s=0.0),
                         alarm=signal.alarm)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m quantt.twin", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe")
    sub.add_parser("epoch")
    s = sub.add_parser("send")
    s.add_argument("--dry", action="store_true", help="everything but the transmission; any day")
    s.add_argument("--session", type=dt.date.fromisoformat, default=None, help="with --dry: that session's plans")
    s.add_argument("--approve", default=None, metavar="PLAN_SHA")
    a = sub.add_parser("approve")
    a.add_argument("--sha", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--date", type=dt.date.fromisoformat, default=None)
    c = sub.add_parser("compare")
    c.add_argument("--aggregates", action="store_true")
    x = sub.add_parser("cancel-open")
    x.add_argument("--confirm", type=int, default=None, metavar="N")
    fd = sub.add_parser("feed", help="B10: read-only IBKR bars (and intraday quotes) into the feed directory")
    fd.add_argument("--slot", required=True, choices=("after-close", "evening", "intraday"))
    fd.add_argument("--require-sandbox", action="store_true", help="refuse unless inside its systemd sandbox")
    args = ap.parse_args(argv)
    env = dict(os.environ)
    if args.cmd == "feed":
        try:
            fdeps = _feed_deps(env)
        except Exception as e:  # noqa: BLE001 -- named, exit FAIL; never a default
            print(f"FAIL before the feed could start: {type(e).__name__}: {e}")
            return 20
        from quantt.twin import feed
        return feed.run(fdeps, slot=args.slot, require_sandbox=args.require_sandbox)
    if args.cmd == "compare":
        from quantt.session import records as rec
        from quantt.twin import compare
        print(compare.render(rec.state_dir_from_env(env), aggregates=args.aggregates))
        return 0
    try:
        deps = _deps(env)
    except Exception as e:  # noqa: BLE001 -- named, exit FAIL; never a default
        print(f"FAIL before the twin could start: {type(e).__name__}: {e}")
        return 20
    from quantt.twin import run, verify
    if args.cmd == "probe":
        return run.probe(deps)
    if args.cmd == "epoch":
        return run.epoch(deps)
    if args.cmd == "send":
        return run.send(deps, dry=args.dry, session=args.session, approve=args.approve)
    if args.cmd == "approve":
        return run.approve(deps, sha=args.sha)
    if args.cmd == "verify":
        return verify.verify(deps, date=args.date)
    if args.cmd == "cancel-open":
        return run.cancel_open(deps, confirm=args.confirm)
    return 2


if __name__ == "__main__":
    sys.exit(main())
