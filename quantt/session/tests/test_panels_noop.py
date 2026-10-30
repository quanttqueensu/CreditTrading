"""Plan row 6A is DARK: the session `default_deps` builds for today's book json is byte-identical to 5e627ff.

WHAT ROW 6A CHANGED (results/cef/C4_DEPLOY_PLAN_2026-10-27.md §1 row 6A, §2
step 5; quantt/session/run.py PER-SLEEVE PANELS). `default_deps` used to read
every close, NAV date and close history, and point the stale-NAV gate, at the
core paths `cef_discount.PX_PATH` / `NAV_PATH`; it now reads each name from the
panel its own sleeve decides on (`BookPanels`), and `sleeve_targets` takes
MarketState's prices from the sleeve's own price file. For the released book
(one sleeve, the core spec) that is the same file, read by the same call.

WHY A NEW PIN. The pins of test_combine_noop.py, test_missing_nav_hold.py and
test_c4_synthetic_pin.py drive `run_session` with deps they build themselves,
reading `cefmod.PX_PATH` directly, so they prove `run_session` and
`sleeve_targets` unchanged but never run the readers `default_deps` builds,
which are what row 6A rewired. Here the session is built BY `default_deps` from
today's book json -- late_market with bp_shortfall "scale", the stale-NAV gate
and the drawdown check in `report` -- with only what must be faked replaced
after it is built: the broker client (test_run's FakeClient), the refresh (a
fixture exit code), the halts, the clock, the log, and the stale-NAV gate's
CEFConnect reader (refusing every request, as prod's has since 2026-10-21).
The closes, NAVs, close history, targets, execution, gates and sleeves are
`default_deps`' own.

TODAY'S BOOK JSON, BOTH WAYS. `data.missing_nav = "hold"` (with
`missing_nav_max_sessions` 2) is being set by a separate change, so the book is
pinned with the key ABSENT and with it SET, each built from the released file
(`_book`): the runner-read keys of each variant are hashed into the pin's
`input`, so a later edit of the released json that changes what the runner
reads fails here, naming it, instead of passing on a book nobody pinned.

SCENARIOS (test_missing_nav_hold's, so the same branches are reached): a
complete day (the evening DECIDE, then its SEND at 15:52:30, armed) and a day
with one as-of NAV missing (the evening decide, the final check in late-market
mode, and the final check in `cls` mode, armed). Each is hashed by
test_missing_nav_hold's `_hashes`: exit, plan.json, plan_sha, orders, targets,
refusals, the run record, nav_gate.csv, send.json and what reached the broker.
With the key absent every missing-NAV day is refused; with it set, the final
check holds the fund and decides (and the cls run sends).

  * `test_synthetic_default_deps_is_5e627ff` NEVER SKIPS: test_combine_noop's
    generated 13-fund panel and fixture spec.
  * `test_real_panel_default_deps_is_5e627ff`: the live spec and a copy of the
    real panels through 2026-09-25 (test_combine_noop's input pin); it warns and
    skips when the copy or the spec is not what that pin was made on.

HOW THE PINS WERE MADE. `git archive 5e627ff` (release-20261029-2, prod's code)
into a scratch directory with the real data/ symlinked in, read only; this file
copied into that tree; `print_pins()` run there in a fresh process, unseeded
and under PYTHONHASHSEED 1; then on the row-6A tree (identical every time).
Every tmp path is replaced by `<WORK>` before hashing. To re-derive, do exactly
that again; never edit a hash by hand. This file uses only names that exist at
5e627ff for that reason; the behaviour row 6A adds is tested in
test_sleeve_panels.py.

Hermetic: no network (netguard; the CEFConnect reader raises), no key file (the
client factory is faked), state under tmp_path, the real panels read only.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from quantt.session import run as rn
from quantt.session.tests.test_combine_noop import (
    LIVE_SPEC_PATH,
    PINNED_INPUT as COMBINE_PINNED_INPUT,
    SYN_SPEC,
    RealPanelPinNotApplicable,
    _client,
    _frozen_copy,
    _real_panel_ready,
    _write_synthetic,
)
from quantt.session.tests.test_missing_nav_hold import (
    ASOF,
    CLS_SCALE,
    EVE,
    FINAL,
    HOLD,
    MAX_SESSIONS,
    REAL_MISSING,
    SEND,
    SESSION,
    SYN_MISSING,
    _Quiet,
    _hashes,
    _held_book,
    _prior_plan,
    _refused,
    _scenario_panel,
    _write_priors,
)

MISSING_NAV_KEYS = ("missing_nav", "missing_nav_max_sessions", "_missing_nav_note")


def _sha(b) -> str:
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()


def _runner_keys(book: dict) -> dict:
    """The book json as the runner reads it: every block, notes (`_` keys) dropped."""
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if not k.startswith("_")}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v
    return strip(book)


def _book(work: Path, spec_path: Path, key: bool) -> tuple:
    """(Book, sha of its runner-read keys): the released book json with the
    missing-NAV keys removed (`key` False) or set to the team lead's values
    (True), its one sleeve naming `spec_path`. A spec outside the repository is
    named by its absolute path, which `combine.load_sleeves` resolves as itself."""
    book = json.loads(rn.BOOKS["cef"].book_path.read_text())
    data = {k: v for k, v in (book.get("data") or {}).items() if k not in MISSING_NAV_KEYS}
    if key:
        data.update(missing_nav=HOLD, missing_nav_max_sessions=MAX_SESSIONS)
    book["data"] = data
    assert len(book["sleeves"]) == 1, book["sleeves"]
    try:
        sp = spec_path.relative_to(rn.REPO).as_posix()
        shown = sp
    except ValueError:
        sp, shown = str(spec_path), "<SPEC>"
    book["sleeves"] = [dict(book["sleeves"][0], spec_path=sp)]
    path = work / ("book_hold.json" if key else "book_absent.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=1))
    pinned = _runner_keys(book)
    pinned["sleeves"] = [dict(pinned["sleeves"][0], spec_path=shown)]
    return (rn.Book("cef", "cef", spec_path, path),
            _sha(json.dumps(pinned, sort_keys=True)))


def _session(work: Path, book, spec, held, now, mp, *, refresh_exit, key: bool,
             execution=None, armed=False):
    """One run_session on deps built by `default_deps(book, spec, env)`, with
    only the fakes the module docstring names replaced after it is built."""
    from ops.schedule.nyse_calendar import previous_trading_day
    from quantt.broker import alpaca
    from src.deploy.sleeves import cef_discount as cefmod
    p = rn.spec_params(spec)
    state = work / "state"
    state.mkdir(parents=True, exist_ok=True)
    if key:
        # The previous session's record, every NAV dated: the age limit's count is 0.
        prev = previous_trading_day(SESSION)
        _write_priors(state, {prev: _prior_plan(prev)})
    if armed:
        (state / "AUTO_ARMED").touch()
    closes = {s: v[0] for s, v in rn.last_closes(cefmod.PX_PATH, ASOF, p["universe"]).items()}
    c = _client(state, held, closes, now)
    mp.setattr(alpaca.AlpacaClient, "from_environment",
               classmethod(lambda cls, name, **kw: c))
    deps = rn.default_deps(book, spec, {"QUANTT_ENV_FILE": "unused"})
    assert deps.client is c and deps.sleeves is None
    assert (deps.missing_nav == HOLD) is key
    deps.env = {"QUANTT_STATE_DIR": str(state), "DRY_RUN": "0"}
    deps.refresh = lambda a, t: rn.RefreshResult(exit=refresh_exit, tail="fixture")
    deps.halts = lambda: []
    deps.utcnow = lambda: now.astimezone(dt.timezone.utc)
    deps.out = _Quiet()
    deps.nav_gate.reader = _refused
    if execution is not None:
        deps.execution = execution
    code = rn.run_session(book, spec, deps)
    return code, state, c


def _scenarios(work: Path, base: Path, mp, spec, spec_path: Path, missing: str,
               key: bool) -> dict:
    book, book_sha = _book(work, spec_path, key)
    out = {"book": book_sha}
    _scenario_panel(base, work / "complete" / "panel", mp, ASOF)
    held = _held_book(spec, ASOF, rn.spec_params(spec)["capital_usd"])
    w = work / "complete"
    code, state, c = _session(w, book, spec, held, EVE, mp, refresh_exit=0, key=key)
    out["complete|decide"] = _hashes(w, state, code, c)
    code, state, c = _session(w, book, spec, held, SEND, mp, refresh_exit=0, key=key,
                              armed=True)
    out["complete|send"] = _hashes(w, state, code, c, send=True)
    for label, now, ex, armed in (("eve", EVE, None, False), ("final", FINAL, None, False),
                                  ("final_cls", FINAL, CLS_SCALE, True)):
        w = work / f"missing_{label}"
        _scenario_panel(base, w / "panel", mp, ASOF, nav=(missing,))
        code, state, c = _session(w, book, spec, held, now, mp, refresh_exit=4, key=key,
                                  execution=ex, armed=armed)
        out[f"missing|{label}"] = _hashes(w, state, code, c)
    return out


def _synthetic_pins(work: Path, mp) -> dict:
    base = work / "base"
    base.mkdir(parents=True)
    _, _, _, panel_sha = _write_synthetic(base)
    spec_path = work / "synthetic.frozen.json"
    spec_path.write_text(json.dumps(SYN_SPEC))
    out = {"panel": panel_sha}
    for name, key in (("absent", False), ("hold", True)):
        out[name] = _scenarios(work / name, base, mp, SYN_SPEC, spec_path, SYN_MISSING, key)
    return out


def _real_pins(work: Path, mp) -> dict | None:
    """None when the real copy or the live spec is not what the pin was made on."""
    spec = json.loads(LIVE_SPEC_PATH.read_text())
    base = work / "base"
    base.mkdir(parents=True)
    got = {"panel": _frozen_copy(base, mp, spec["frozen"]["universe"]),
           "spec": _sha(LIVE_SPEC_PATH.read_bytes())}
    if got != COMBINE_PINNED_INPUT:
        return None
    return {name: _scenarios(work / name, base, mp, spec, LIVE_SPEC_PATH, REAL_MISSING, key)
            for name, key in (("absent", False), ("hold", True))}


def print_pins():
    """Print both pins (module docstring, HOW THE PINS WERE MADE)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d, pytest.MonkeyPatch.context() as mp:
        print("SYN_PINNED =", json.dumps(_synthetic_pins(Path(d) / "syn", mp), indent=1,
                                          sort_keys=True))
    with tempfile.TemporaryDirectory() as d, pytest.MonkeyPatch.context() as mp:
        print("REAL_PINNED =", json.dumps(_real_pins(Path(d) / "real", mp), indent=1,
                                           sort_keys=True))


# PINNED 2026-10-29 on 5e627ff (release-20261029-2); module docstring: how, and how
# to re-derive. The key-absent entries equal test_missing_nav_hold.py's pins, made
# on bd87144 with hand-built deps: default_deps builds what those deps build.
SYN_PINNED = {
    "absent": {
        "book": "485fe7f7f1ff8c99cd559f049a43c8f5ba75f358f59aa7a25075004e60446e42",
        "complete|decide": {
            "exit": 6,
            "n_orders": 7,
            "nav_gate_csv": "a43fad90c4741dc4b1cc9cef3f7eb697a360c4779d3ac981ee8df218e287a845",
            "orders": "e628eb451ee60ed44c2a3432437a51e54f7759a97439d112ce119d11e3271024",
            "plan_json": "6d81b758b730f5c5901cc307decf1f6ea354da71d7cc3dd0b0f4c181d8835368",
            "plan_sha": "aa3cc8b1827344eac6a143892be4faa969df5bcb1431b09903b93b8c229a780e",
            "refusals": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "run_record": "fef25235298115511f49fb9e859527400d2f4e51f24338506c2c0e7032cd2779",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "decided",
            "targets": "732894a285fe4821a443ae4ce9d9d609cc3e382edc831ccb239c03e155f5fb6f"
        },
        "complete|send": {
            "exit": 0,
            "run_record": "2ba2408c6f4f2039f65594d86948e8d88ef22afaf654b6d118f60f35dc3babee",
            "send_json": "28900ab87d89f8716cc885b35b3612f9f9b33ca0be117b85d12659cbd5624819",
            "sent": "5409c95d63e197ab80437a44fa71fb69e234f2578348b84b75cc9217193f6aaf"
        },
        "missing|eve": {
            "exit": 11,
            "n_orders": 0,
            "nav_gate_csv": None,
            "orders": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "plan_json": "eac2080f6b0e3099dd1b535da8d0434a75d3717f32da5f61e1a314629bd5f7b6",
            "plan_sha": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "refusals": "630bfc011cbaf9c3a07f35493598a808548ddb9c617fbcb8e42f2a19bc5d25ed",
            "run_record": "676630c02f863db9e92089d8e63f55171e62b598acbdd6b5bf9600d67a900c98",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "refused",
            "targets": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        },
        "missing|final": {
            "exit": 11,
            "n_orders": 0,
            "nav_gate_csv": None,
            "orders": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "plan_json": "eac2080f6b0e3099dd1b535da8d0434a75d3717f32da5f61e1a314629bd5f7b6",
            "plan_sha": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "refusals": "630bfc011cbaf9c3a07f35493598a808548ddb9c617fbcb8e42f2a19bc5d25ed",
            "run_record": "f241e3222dc6c112b0cb1bedab8baf0b9988505404d6a991ec969a7979c38b83",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "refused",
            "targets": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        },
        "missing|final_cls": {
            "exit": 11,
            "n_orders": 0,
            "nav_gate_csv": None,
            "orders": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "plan_json": "9edca0afad5cacdaed81517f4048bf86c3a39ccfb7f595c5f2f1b75cccc9fdc5",
            "plan_sha": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "refusals": "630bfc011cbaf9c3a07f35493598a808548ddb9c617fbcb8e42f2a19bc5d25ed",
            "run_record": "1f4caf668b2f85cc257816187e5cc00bafb93538350a5f7b942b7357926d4066",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": None,
            "targets": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        }
    },
    "hold": {
        "book": "22356114d717b84f473c7b146adaf4b1d5525a47299b6f257f43b47411785455",
        "complete|decide": {
            "exit": 6,
            "n_orders": 7,
            "nav_gate_csv": "a43fad90c4741dc4b1cc9cef3f7eb697a360c4779d3ac981ee8df218e287a845",
            "orders": "e628eb451ee60ed44c2a3432437a51e54f7759a97439d112ce119d11e3271024",
            "plan_json": "8a419869b91ed92c14e6bbc1b4881fdf00ab64b5f599626abfba35f28f5ae720",
            "plan_sha": "aa3cc8b1827344eac6a143892be4faa969df5bcb1431b09903b93b8c229a780e",
            "refusals": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "run_record": "ce6efea304c72a4585826377403a017b11fe37f465e1bde7aac4a52d9bcb07cf",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "decided",
            "targets": "732894a285fe4821a443ae4ce9d9d609cc3e382edc831ccb239c03e155f5fb6f"
        },
        "complete|send": {
            "exit": 0,
            "run_record": "2ba2408c6f4f2039f65594d86948e8d88ef22afaf654b6d118f60f35dc3babee",
            "send_json": "28900ab87d89f8716cc885b35b3612f9f9b33ca0be117b85d12659cbd5624819",
            "sent": "5409c95d63e197ab80437a44fa71fb69e234f2578348b84b75cc9217193f6aaf"
        },
        "missing|eve": {
            "exit": 11,
            "n_orders": 0,
            "nav_gate_csv": "a43fad90c4741dc4b1cc9cef3f7eb697a360c4779d3ac981ee8df218e287a845",
            "orders": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "plan_json": "13a0b7b2b75614aa4d6eb3841d666ab2312641b4147df66a06c955942603cedf",
            "plan_sha": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "refusals": "0d32802d42ce7301e6a64fd20245a41f44cf43cb6831cad8175bff9375748d66",
            "run_record": "80c8df9a59d20ef25fb9bfc081be216b07cee5929c5ee328260f7fdadfcd50c0",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "refused",
            "targets": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        },
        "missing|final": {
            "exit": 6,
            "n_orders": 6,
            "nav_gate_csv": "8c5ca313d8bddeb168b5f6b56f8f909f90e67576f2309c9dde7157d758097d86",
            "orders": "8e83a5fab26db52c76fcfbc357e9d9674bb742cca88049155b4f2a64e7f63d9a",
            "plan_json": "e7df59e91474884e49aa3ed87e4a752cfc4f021a286b19bafbf98280a4cb40a2",
            "plan_sha": "dabc5f382dc87baecf74fe4782e0c5f07902dc744eb7c5ae8bf5e0e59cdcb500",
            "refusals": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "run_record": "8ae2bf7126afc593fa4bfda3113196f6867722a38222efdc07f296cad6204103",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "decided",
            "targets": "ad3fafebc78bba0add3d0f9c46c1c629d3d30a6e15a852a9cc04ed8594c0f9c0"
        },
        "missing|final_cls": {
            "exit": 0,
            "n_orders": 6,
            "nav_gate_csv": "8c5ca313d8bddeb168b5f6b56f8f909f90e67576f2309c9dde7157d758097d86",
            "orders": "97bb764435fad43e59e6fe5be9480eccf28231974fd49bc8555bbdba79fa5a88",
            "plan_json": "c1d1366fbafbaa92c94f52a7e4840ee628a60b08eff9f6674132c35a776e1bf3",
            "plan_sha": "11b246acc248978f8cfb0e8f0d9ba58b4cead022b23bfa9284e31de4d7db92cb",
            "refusals": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "run_record": "9191f3f986c4831a2ea07cc2d33e4219df0ec8ec2fb5047ae00073719eece36f",
            "sent": "178635e34eccb5810101fda355a3f703e6f4f17a7bef24cee399e3a9e60afbc5",
            "status": None,
            "targets": "ad3fafebc78bba0add3d0f9c46c1c629d3d30a6e15a852a9cc04ed8594c0f9c0"
        }
    },
    "panel": "172d57548229a8776518927875787e15e3c5476f9e57cd9df99e90c78738b277"
}
# PINNED 2026-10-29 on 5e627ff, on the laptop's dev panels (test_combine_noop's
# input pin; only rows through 2026-09-25 are read).
REAL_PINNED = {
    "absent": {
        "book": "9b0aa0cbdf97c496ee859c2af47430f6728495152143a41ebec0362017658c27",
        "complete|decide": {
            "exit": 6,
            "n_orders": 6,
            "nav_gate_csv": "18734cfdbe33cc779a2277bef135248fcafa1c90de9b2a0c203ae82a729af304",
            "orders": "f198dd92f1f473578190d104e61bd70d8bb2352ecb253bc12ccc6c9b23d75a2c",
            "plan_json": "46a4beb72f9164c126769a765a2c350144262d9cc2c77240f3e7be5fa39a7d30",
            "plan_sha": "e69a46f6680840664ed3b44e21eb767cf4d9f641e0b3f9ee0fd07e45fa084e05",
            "refusals": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "run_record": "ef7329ad8ebfaccef04d1e0eb58d8b9a719bb1369f3be2407e2a23c5a3ecc6c3",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "decided",
            "targets": "978e2df32387f0be9e49a3a5966369bed1866e780b1ca8d79d562d11f2c37f56"
        },
        "complete|send": {
            "exit": 0,
            "run_record": "8003b25c902c0bc09863598ac0910fe44e0ca3ce245b912b05e8f07c28d37003",
            "send_json": "ac1adb88597ac75eb557fc634eae9f879b5196a07c03cdbbcfc05fa2a46d6a9b",
            "sent": "b30cc665d139dfebf931d9cac73299e66c22518a92a49e5c70d6a68e9532139d"
        },
        "missing|eve": {
            "exit": 11,
            "n_orders": 0,
            "nav_gate_csv": None,
            "orders": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "plan_json": "52e45d9baa3c8d5cd7a2e9e0cee5341c5f7f0d3347e7b2b6dc86b24953f752f3",
            "plan_sha": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "refusals": "0bd11e7d2acb6a4d1333ffa81814bd978c4247336c94639a7005ddcefcb9a865",
            "run_record": "35f91aaac82e1f8865858e33dfce21928282a0da31889e7e3a3cd692e3258931",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "refused",
            "targets": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        },
        "missing|final": {
            "exit": 11,
            "n_orders": 0,
            "nav_gate_csv": None,
            "orders": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "plan_json": "52e45d9baa3c8d5cd7a2e9e0cee5341c5f7f0d3347e7b2b6dc86b24953f752f3",
            "plan_sha": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "refusals": "0bd11e7d2acb6a4d1333ffa81814bd978c4247336c94639a7005ddcefcb9a865",
            "run_record": "ace60f3823f434048528b0a37871dabde32a64435cb42cff43fb096a0ad70fc7",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "refused",
            "targets": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        },
        "missing|final_cls": {
            "exit": 11,
            "n_orders": 0,
            "nav_gate_csv": None,
            "orders": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "plan_json": "f783d446fc82ca1ca6f78e2a8caa3b7973224132afbe2905e7b7dd32d34fda0c",
            "plan_sha": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "refusals": "0bd11e7d2acb6a4d1333ffa81814bd978c4247336c94639a7005ddcefcb9a865",
            "run_record": "494b3176742219873c4938795cf82efa8dce534907245657dbdfe9bb436d015a",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": None,
            "targets": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        }
    },
    "hold": {
        "book": "8dd27cdf6ed7909842a55380a22b1c0a1bbb9a505aa5fa2abb47d5d092d414b9",
        "complete|decide": {
            "exit": 6,
            "n_orders": 6,
            "nav_gate_csv": "18734cfdbe33cc779a2277bef135248fcafa1c90de9b2a0c203ae82a729af304",
            "orders": "f198dd92f1f473578190d104e61bd70d8bb2352ecb253bc12ccc6c9b23d75a2c",
            "plan_json": "da8602893fb148bae6227dcea166fde9de26bcdbb9f5c84cc0c831e41f2352f6",
            "plan_sha": "e69a46f6680840664ed3b44e21eb767cf4d9f641e0b3f9ee0fd07e45fa084e05",
            "refusals": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "run_record": "6b2f5e2fc5095a03715c90e674db43af24748d2a6d68a3d864a17c9d563bdc4b",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "decided",
            "targets": "978e2df32387f0be9e49a3a5966369bed1866e780b1ca8d79d562d11f2c37f56"
        },
        "complete|send": {
            "exit": 0,
            "run_record": "8003b25c902c0bc09863598ac0910fe44e0ca3ce245b912b05e8f07c28d37003",
            "send_json": "ac1adb88597ac75eb557fc634eae9f879b5196a07c03cdbbcfc05fa2a46d6a9b",
            "sent": "b30cc665d139dfebf931d9cac73299e66c22518a92a49e5c70d6a68e9532139d"
        },
        "missing|eve": {
            "exit": 11,
            "n_orders": 0,
            "nav_gate_csv": "18734cfdbe33cc779a2277bef135248fcafa1c90de9b2a0c203ae82a729af304",
            "orders": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "plan_json": "07ed83190bad6371138f20035962beabde965b77ad3704210271814e598f5337",
            "plan_sha": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "refusals": "45fb724cc5c4f4b809d81561866376313a6deee1633f27933aef93a6c4e09b03",
            "run_record": "55e1e0a78a4394c47e0f5f81cbede1488ea42402dd2a2e2a2b455b95a62caf96",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "refused",
            "targets": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        },
        "missing|final": {
            "exit": 6,
            "n_orders": 5,
            "nav_gate_csv": "3e17b6fc3741ec740818874935a3a078f2b300f7ee49a86dd1204828f1597100",
            "orders": "8eed4bbdede1d23018a30be99b635b0de15d950e92dcb109a205e7f3b7df6369",
            "plan_json": "35d665a545dc2ce046281af36231e8ad4dbbac4418c0237aa2ec80dd8f884b03",
            "plan_sha": "335ff6880608490519e3c98bbf824d94ddc3bbaebd968290892c099fa1f32d44",
            "refusals": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "run_record": "26c1009974d0499ce407c9c9207f2fe04d0291280d82ea7eafc3fb6af7877548",
            "sent": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "status": "decided",
            "targets": "76f210ae5b86000c56d0cee23a8d046725f78b6795ec4c543d242ffd81561947"
        },
        "missing|final_cls": {
            "exit": 0,
            "n_orders": 5,
            "nav_gate_csv": "3e17b6fc3741ec740818874935a3a078f2b300f7ee49a86dd1204828f1597100",
            "orders": "0dc9a3fc8ed8347907e3c97b0dedbde02770b1eb34384b693e41cf45afcc11bd",
            "plan_json": "89ff6f5513af313530b83baf8b63633f8d916e1fb9e6d99c96e22590faabfedc",
            "plan_sha": "11a7e458821ae6b6f380183d33fde28c9dd4d406533cb4ec512c70506513ed14",
            "refusals": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            "run_record": "9bd6b7e00277111f3889514b0034c1d580edb84374d6b60fa761ac253022b5c2",
            "sent": "64329bbbd615fe4d2ae0d658f443b9fde2e006213c9b0bfbd0f130572f7f0d93",
            "status": None,
            "targets": "76f210ae5b86000c56d0cee23a8d046725f78b6795ec4c543d242ffd81561947"
        }
    }
}


def _not_vacuous(got: dict):
    """Both variants decide and send a complete day; the key absent refuses every
    missing-NAV day; the key set holds the fund at the final check and decides."""
    for v in ("absent", "hold"):
        assert got[v]["complete|decide"]["exit"] == rn.EXIT_PLANNED
        assert got[v]["complete|decide"]["n_orders"] > 0
        assert got[v]["complete|send"]["exit"] == rn.EXIT_SENT
        assert got[v]["missing|eve"]["exit"] == rn.EXIT_REFUSED
    assert {got["absent"][f"missing|{x}"]["exit"] for x in ("final", "final_cls")} == \
        {rn.EXIT_REFUSED}
    assert got["hold"]["missing|final"]["exit"] == rn.EXIT_PLANNED
    assert got["hold"]["missing|final_cls"]["exit"] == rn.EXIT_SENT


def test_synthetic_default_deps_is_5e627ff(tmp_path, monkeypatch):
    got = _synthetic_pins(tmp_path, monkeypatch)
    for v in ("absent", "hold"):
        assert got[v]["book"] == SYN_PINNED[v]["book"], (
            f"today's book json ({v}) is not the one this pin was made on: what the runner "
            f"reads from it changed. Re-derive the pin on the release it ships with (module "
            f"docstring)")
    assert got == SYN_PINNED
    _not_vacuous(got)


@pytest.mark.skipif(not _real_panel_ready(), reason="real CEF panels absent (data/ is "
                                                     "gitignored); the synthetic pin still runs")
def test_real_panel_default_deps_is_5e627ff(tmp_path, monkeypatch):
    from src.deploy.sleeves import cef_discount as cefmod
    real = {f: f.read_bytes() for f in (cefmod.PX_PATH, cefmod.NAV_PATH)}
    got = _real_pins(tmp_path, monkeypatch)
    if got is None:
        import warnings
        why = (f"REAL-PANEL ROW-6A NO-OP PIN NOT APPLIED: it was made on panel/spec "
               f"{COMBINE_PINNED_INPUT} (test_combine_noop's input pin); this tree's copy "
               f"differs. The synthetic pin still runs")
        warnings.warn(why, RealPanelPinNotApplicable)
        pytest.skip(why)
    assert got == REAL_PINNED
    _not_vacuous(got)
    assert all(f.read_bytes() == b for f, b in real.items()), "a real panel changed"


def test_the_core_books_refresh_is_the_command_it_always_was(monkeypatch):
    """The refresh `default_deps` builds for the released book runs fetch_daily
    with exactly the flags it always has (test_run.py pins refresh_subprocess's
    own list; this pins that default_deps still calls it so)."""
    from quantt.broker import alpaca
    got = {}

    def fake_run(cmd, **kw):
        got["cmd"] = cmd
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rn.subprocess, "run", fake_run)
    monkeypatch.setattr(alpaca.AlpacaClient, "from_environment",
                        classmethod(lambda cls, name, **kw: object()))
    b = rn.BOOKS["cef"]
    deps = rn.default_deps(b, rn.load_spec(b.spec_path), {"QUANTT_ENV_FILE": "unused"})
    r = deps.refresh(dt.date(2026, 9, 28), 600.0)
    assert r.exit == 0 and r.incomplete is None
    assert got["cmd"][1].endswith("scripts/cef/fetch_daily.py")
    assert got["cmd"][2:] == ["--require-asof", "2026-09-28", "--nav-fallback", "cefconnect",
                              "--book", "ops/books/cef_discount_book.json"]
