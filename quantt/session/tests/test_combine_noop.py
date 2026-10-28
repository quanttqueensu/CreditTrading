"""The combiner is DARK: the released book json decides byte-identically to de6e9c5.

WHAT IS PROVED (quantt/session/combine.py, OFF BY DEFAULT). With the book json
as released (one sleeve, `cef_discount`, no `risk_budget`), `load_sleeves`
returns None and the session takes the single-spec path; that path must give
the same targets, orders, plan.json and plan_sha as the code BEFORE the
combiner, de6e9c5 (release-20261028-1, what prod runs). Four tests:

  1. `test_the_released_book_json_takes_the_single_sleeve_path`: the released
     json, read by `load_sleeves` and by `default_deps` (broker client faked),
     gives `sleeves=None`. That is the bridge: tests 2 and 3 drive the session
     with `sleeves` absent, which is what None means.
  2. `test_synthetic_book_is_the_code_before_the_combiner` (NEVER SKIPS). A
     generated 13-fund panel (integer LCG and IEEE + - x / only, so the inputs
     are the same bytes on any machine; `panel` in the pin is their hash) and a
     fixture spec, decided as of 2026-09-25 on a flat and a held book, then the
     full session three ways: the late-market DECIDE, its SEND at 15:52:30 on
     the session date (armed, so orders go to the fake broker), and a `cls`
     evening run that decides and sends. Every output is hashed and compared
     with hashes COMPUTED BY de6e9c5's CODE. The generator and the fixture spec
     are copied from `test_c4_synthetic_pin.py` on branch `simon` (made for the
     same purpose at 66ec3df); the pins are this tree's own.
  3. `test_real_sleeve_on_the_real_panel_is_the_code_before_the_combiner`. The
     same on the real sleeve, the live spec and a copy of the real panels'
     universe rows through 2026-09-25 (the `test_nav_gate.py` and
     `test_c4_keys_noop.py` pattern: half the day-one book held, so the band
     trades and holds). A pin is only a proof on the inputs it was made on, so
     the copy's content and the live spec are hashed, and when either is not
     what the pin was made on the test WARNS and skips, naming both. Test 2 is
     the one that never skips.
  4. `test_one_sleeve_through_the_combiner_sends_what_the_single_sleeve_book_sends`,
     on the synthetic panel and (if present) the real one. Not a pin. It is a
     check of the combiner's arithmetic: the live spec as the only sleeve at
     risk_budget 1.0 must send the same orders, with the same plan_sha, as the
     single-sleeve path. plan.json differs only where it must: each target is a
     netted `qty`, every reason says which sleeve wanted it, and `combine` is
     added.

HOW THE PINS WERE MADE. `git archive de6e9c5` into a scratch directory (the
real `data/` symlinked in, read only), this file copied into that tree, and
`_hashes(_session(...))` run there: the synthetic pin unseeded and under
PYTHONHASHSEED 1, 2 and 3, the real-panel pin unseeded and under 1 (identical
every time); then on the combiner tree (identical again). To re-derive one --
after a deliberate change of the single-sleeve path, a pandas or numpy upgrade,
or a panel revision through 2026-09-25 -- do exactly that again and paste the
result; never edit a hash by hand.

SEED INDEPENDENCE. Where the sleeve's `max_gross_stress` BINDS on a held
book, its last ulp depends on the hash seed (the band's set union fixes the
order `_cap_gross` sums in; 11790b5's commit message, branch `simon`). It does
not bind on either held book here, and both tests assert so.

Hermetic: test_run's FakeClient for the broker, fixed clocks, no refresh, no
close-history reader (the pre-flight records UNMEASURED, a fixed string), and
the stale-NAV gate and the drawdown check off: their own report-mode proofs
(test_nav_gate.py, test_drawdown.py) compare off with report on this tree, so
with test 3 they carry over. netguard refuses any socket.
"""
import datetime as dt
import hashlib
import json
import platform
import warnings

import pandas as pd
import pytest

from quantt.session import run as rn
from quantt.session.tests.test_run import BOOK, LATE, FakeClient
from src.deploy.registry import build_sleeve
from src.deploy.sleeve import SHORT, MarketState
from src.deploy.tests.test_group_cap import _fingerprint

ET = rn.gt.ET
ASOF = dt.date(2026, 9, 25)                                  # a Friday; plans for Monday 09-28
EVE = dt.datetime(2026, 9, 25, 22, 0, tzinfo=ET)
SEND = dt.datetime(2026, 9, 28, 15, 52, 30, tzinfo=ET)       # inside 15:52-15:58 ET
SESSION_DIR = "2026-09-28"
LIVE_SPEC_PATH = rn.REPO / "ops/specs/cef_discount.frozen.json"


class RealPanelPinNotApplicable(UserWarning):
    """The real-panel pin skipped: a bare skip shows one `s` under `-q`, so it
    also warns, and the warning lands in every run's summary (review of
    11790b5, branch `simon`)."""


class _Quiet:
    def write(self, s):
        return None

    def flush(self):
        return None


def _sha(x) -> str:
    return hashlib.sha256(x if isinstance(x, bytes) else x.encode()).hexdigest()


def _real_panel_ready() -> bool:
    from src.deploy.sleeves import cef_discount as cefmod
    return cefmod.PX_PATH.exists() and cefmod.NAV_PATH.exists()


def _client(state, held, closes, clock_ts):
    c = FakeClient(state, positions=held, clock_ts=clock_ts)
    c.long_mv = sum(q * closes[s] for s, q in held.items() if q > 0)
    c.short_mv = sum(q * closes[s] for s, q in held.items() if q < 0)
    c.maint = 0.5 * (c.long_mv - c.short_mv)                 # fixture, not a measurement
    return c


def _deps(state, spec, client, execution, now, **extra):
    """The proofs' deps: the real readers on the sleeve's (patched) panel paths.
    `extra` is empty on de6e9c5; the combiner tree passes `sleeves=` in test 4."""
    from src.deploy.sleeves import cef_discount as cefmod
    cap = rn.spec_params(spec)["capital_usd"]
    return rn.Deps(
        client=client, env={"QUANTT_STATE_DIR": str(state), "DRY_RUN": "0"},
        refresh=lambda a, t: rn.RefreshResult(exit=0, tail="fixture"),
        closes=lambda a, u: rn.last_closes(cefmod.PX_PATH, a, u),
        navs=lambda a, u: rn.last_navs(cefmod.NAV_PATH, a, u),
        targets=lambda a, h, eq, op, **kw: rn.sleeve_targets(spec, cap, a, h, eq, op, **kw),
        halts=lambda: [], utcnow=lambda: now.astimezone(dt.timezone.utc),
        out=_Quiet(), execution=execution, **extra)


def _sent(client) -> list:
    """What reached the fake broker, in order: the wire fields."""
    return [[o["client_order_id"], o["symbol"], o["side"], o["qty"], o["time_in_force"]]
            for o in client.accepted.values()]


def _session(work, spec, **extra) -> dict:
    """The raw outputs of one as-of: the sleeve's day-one and held-book targets;
    a late-market DECIDE on the held book (evening), its SEND (15:52:30 on the
    session date, AUTO_ARMED); and a `cls` evening run, armed, that decides and
    sends. `work` is a fresh directory."""
    from src.deploy.sleeves import cef_discount as cefmod
    p = rn.spec_params(spec)
    cap, uni = p["capital_usd"], p["universe"]
    day1 = rn.sleeve_targets(spec, cap, ASOF, {}, cap, True)
    closes = {s: v[0] for s, v in rn.last_closes(cefmod.PX_PATH, ASOF, uni).items()}
    # Half the day-one book, so the band has trades to make and holds to keep.
    held = {t.instrument: int(0.5 * cap * float(t.weight) / closes[t.instrument])
            for t in day1 if t.weight}
    held = {s: q for s, q in held.items() if q}
    held_targets = rn.sleeve_targets(spec, cap, ASOF, held, cap, False)
    late = {**LATE, "bp_shortfall": "scale"}

    st = work / "late" / "state"
    st.mkdir(parents=True)
    code = rn.run_session(BOOK, spec, _deps(st, spec, _client(st, held, closes, EVE), late, EVE,
                                            **extra))
    plan_raw = (st / SESSION_DIR / "plan.json").read_bytes()
    (st / "AUTO_ARMED").touch()
    cs = _client(st, held, closes, SEND)
    send_code = rn.run_session(BOOK, spec, _deps(st, spec, cs, late, SEND, **extra))
    send_raw = (st / SESSION_DIR / "send.json").read_bytes()

    sc = work / "cls" / "state"
    sc.mkdir(parents=True)
    (sc / "AUTO_ARMED").touch()
    cc = _client(sc, held, closes, EVE)
    cls_code = rn.run_session(BOOK, spec, _deps(sc, spec, cc, {"mode": "cls",
                                                                "bp_shortfall": "scale"},
                                                EVE, **extra))
    cls_raw = (sc / SESSION_DIR / "plan.json").read_bytes()
    return {"day1": day1, "held_targets": held_targets, "exit": code, "plan_raw": plan_raw,
            "send_exit": send_code, "send_sent": _sent(cs), "send_raw": send_raw,
            "cls_exit": cls_code, "cls_sent": _sent(cc), "cls_raw": cls_raw}


def _hashes(r) -> dict:
    plan = json.loads(r["plan_raw"])
    return {"exit": r["exit"], "status": plan["status"], "n_orders": len(plan["orders"]),
            "band_holds": sum("band hold" in t["reason"] for t in plan["targets"].values()),
            "day_one_targets": _sha(_fingerprint(r["day1"])),
            "held_targets": _sha(_fingerprint(r["held_targets"])),
            "orders": _sha(json.dumps(plan["orders"], sort_keys=True)),
            "plan_targets": _sha(json.dumps(plan["targets"], sort_keys=True)),
            "plan_sha": plan["plan_sha"],
            "plan_json": _sha(r["plan_raw"]),
            "send_exit": r["send_exit"], "send_sent": _sha(json.dumps(r["send_sent"])),
            "send_json": _sha(r["send_raw"]),
            "cls_exit": r["cls_exit"], "cls_sent": _sha(json.dumps(r["cls_sent"])),
            "cls_plan_json": _sha(r["cls_raw"])}


def _assert_not_vacuous(r):
    """The sessions decided, sent and kept band holds, and the sleeve's gross cap
    did not bind on the held book (SEED INDEPENDENCE)."""
    plan = json.loads(r["plan_raw"])
    assert r["exit"] == rn.EXIT_PLANNED and plan["orders"]
    assert any("band hold" in t["reason"] for t in plan["targets"].values())
    assert r["send_exit"] == rn.EXIT_SENT and r["send_sent"]
    assert r["cls_exit"] == rn.EXIT_SENT and r["cls_sent"]
    assert not any("*x" in t.reason for t in r["held_targets"])


# -------------------------------------------------- 1. the released json is the old path

def test_the_released_book_json_takes_the_single_sleeve_path(monkeypatch):
    from quantt.session import combine as cmb
    b = rn.BOOKS["cef"]
    assert cmb.load_sleeves(b.book_path, b.spec_path, rn.REPO, rn._sleeve_target_fn) is None
    # And through default_deps, which main() builds (the broker client faked:
    # no key file is read).
    from quantt.broker import alpaca
    monkeypatch.setattr(alpaca.AlpacaClient, "from_environment",
                        classmethod(lambda cls, book, **kw: object()))
    deps = rn.default_deps(b, rn.load_spec(b.spec_path), {"QUANTT_ENV_FILE": "unused"})
    assert deps.sleeves is None
    # The released json: one sleeve, enabled, the book's own spec, no budget.
    book = json.loads(b.book_path.read_text())
    assert [(e["name"], e["enabled"], e["spec_path"], "risk_budget" in e)
            for e in book["sleeves"]] == [("cef_discount", True,
                                           "ops/specs/cef_discount.frozen.json", False)]


# -------------------------------------------------- 2. the synthetic pin (never skips)

SYN_TICKERS = tuple(f"SY{c}" for c in "ABCDEFGHIJKLM")
SYN_SPEC = {
    "spec_id": "synthetic.combiner-noop.v1", "status": "test", "capital_usd": 100_000.0,
    "allocation": {"type": "cef_discount"},
    "rebalance": {"min_trade_usd": 0.0},
    "risk": {"max_gross_exposure_usd": 260_000.0},
    "frozen": {"universe": list(SYN_TICKERS), "z_window": 252, "rebalance_days": 2,
               "vol_target_annual": 0.06, "min_adv_usd": 3_000_000.0, "max_nav_age_bd": 3,
               "min_names": 6, "min_abs_weight": 0.005, "gross_leverage": 1.0,
               "order_type": "MOC", "band_width": 0.048, "max_gross_stress": 1.8},
}
N_DAYS = 480
THIN = range(N_DAYS - 200, N_DAYS - 100)        # 8 names illiquid here: the flatten date's window
FLATTEN_I = N_DAYS - 101                        # 5 eligible, under min_names 6
FLATTEN_HELD = {"SYA": 1000.0, "SYF": -700.0}


def _lcg(seed: int):
    x = seed
    while True:
        x = (1103515245 * x + 12345) % 2147483648
        yield x


def _write_synthetic(dst):
    """The panel, in the live schema, at `dst`; returns (px_path, nav_path, dates, sha)."""
    dates = pd.bdate_range(end=pd.Timestamp(ASOF), periods=N_DAYS)
    px_rows, nav_rows = [], []
    for i, tk in enumerate(SYN_TICKERS):
        g = _lcg(20261027 + i)
        u = lambda: ((next(g) % 20001) - 10000) / 10000.0          # noqa: E731, in [-1, 1]
        level = -0.06 + 0.01 * i
        nav, d = 10.0 + i / 2.0, level
        for t, day in enumerate(dates):
            if t:
                nav = nav * (1.0 + 0.006 * u())
                d = 0.97 * d + 0.03 * level + 0.02 * u()
            if t >= N_DAYS - 40:                                     # today's z-scores spread
                d = d + (0.0005 if i % 2 else -0.0005)
            vol = 800_000 + next(g) % 400_001
            if i >= 5 and t in THIN:
                vol = 50_000
            if tk == "SYM" and t >= N_DAYS - 80:                     # illiquid on the decision date
                vol = 100_000
            px_rows.append({"date": day, "ticker": tk, "close": nav * (1.0 + d),
                            "volume": int(vol),
                            "grp": "muni" if i < 5 else ("hy", "loan", "multi")[i % 3]})
            if not (tk == "SYC" and t == N_DAYS - 3):                # a missing NAV row
                nav_rows.append({"date": day, "nav": nav, "ticker": tk})
    px, nv = dst / "cef_prices.parquet", dst / "cef_nav.parquet"
    P, N = pd.DataFrame(px_rows), pd.DataFrame(nav_rows)
    P.to_parquet(px)
    N.to_parquet(nv)
    return px, nv, dates, _sha(P.to_csv(index=False) + N.to_csv(index=False))


def _synthetic_sleeve(asof, holdings, opening):
    sl = build_sleeve(SYN_SPEC, SYN_SPEC["capital_usd"])
    ms = MarketState(asof=pd.Timestamp(asof), prices=pd.DataFrame(), holdings=dict(holdings),
                     extras={"sleeve_nav": SYN_SPEC["capital_usd"], "opening_session": opening})
    return sl.target_positions(pd.Timestamp(asof), ms)


def _half(day1, close):
    held = {}
    for t in day1:
        if t.weight:
            q = int(0.5 * SYN_SPEC["capital_usd"] * abs(float(t.weight)) / close[t.instrument])
            if q:
                held[t.instrument] = float(-q if t.side == SHORT else q)
    return held


def _synthetic_panel(tmp_path, monkeypatch):
    from src.deploy.sleeves import cef_discount as cefmod
    (tmp_path / "panel").mkdir()
    px, nv, dates, panel_sha = _write_synthetic(tmp_path / "panel")
    monkeypatch.setattr(cefmod, "PX_PATH", px)
    monkeypatch.setattr(cefmod, "NAV_PATH", nv)
    monkeypatch.setattr(cefmod, "GRP_PATH", px)
    return px, dates, panel_sha


def _synthetic_hashes(tmp_path, monkeypatch, reasons=None) -> dict:
    """Every output the pin covers, hashed: the sleeve on four dates (flat and
    held books), then `_session` as of ASOF. `reasons`, a dict if given,
    receives each book's reason strings (kept out of the hash)."""
    px, dates, panel_sha = _synthetic_panel(tmp_path, monkeypatch)
    P = pd.read_parquet(px)
    out = {"panel": panel_sha}
    for label, i in (("asof", N_DAYS - 1), ("asof-1", N_DAYS - 2), ("t-40", N_DAYS - 40),
                     ("flatten", FLATTEN_I)):
        day = dates[i]
        close = P[P["date"] == day].set_index("ticker")["close"].to_dict()
        day1 = _synthetic_sleeve(day, {}, True)
        held = _half(day1, close) if label != "flatten" else dict(FLATTEN_HELD)
        for b, targets in {"flat": day1, "held": _synthetic_sleeve(day, held, False)}.items():
            out[f"{label}|{b}"] = _sha(_fingerprint(targets))
            if reasons is not None:
                reasons[f"{label}|{b}"] = [t.reason for t in targets]
    r = _session(tmp_path / "run", SYN_SPEC)
    if reasons is not None:
        reasons["_session"] = r
    out.update(_hashes(r))
    return out


# WHICH ENTRIES ARE EXACT EVERYWHERE. The pin was made on an arm64 Mac; another
# CPU may differ in the last ulp of pandas rolling sums and numpy reductions,
# which only the `repr`-of-float target fingerprints can see. Everything else --
# whole-share orders, plan targets, plan.json and plan_sha, what was sent, the
# counts, the exits and the panel's own hash -- is integers and rounded text. So
# on the pin machine every entry must match; on any other the stable entries
# must match exactly (a change to what the book DECIDES still fails) and a moved
# float fingerprint is a warning naming the entries, never silent.
PIN_MACHINE = "arm64"
FLOAT_KEYS = frozenset({"asof|flat", "asof|held", "asof-1|flat", "asof-1|held",
                        "t-40|flat", "t-40|held", "flatten|flat", "flatten|held",
                        "day_one_targets", "held_targets"})

# PINNED 2026-10-28 on de6e9c5 (module docstring: how, and how to re-derive).
SYN_PINNED = {
    "asof-1|flat": "c96d532c3b5a9345fe87ea1f93d4a68724e8886532cb79fa0c373ad1c7fe2ae5",
    "asof-1|held": "5f3a3ae553dd0120c70bbfad6476dd464a3dd154e3daa96396635fd71d466f8f",
    "asof|flat": "919661d53041707542747ec84c0b5d6a358f8fb8aef3b65e3364a93bf42c5d71",
    "asof|held": "d8106417461bfa90b094ab4cfb0993f3bdc4b02fe8d674f07b07fffc965dc82b",
    "band_holds": 5,
    "cls_exit": 0,
    "cls_plan_json": "92d11e888ceafa44614f3f01067fe5a0ab65dd8f424c4da083ec70cb57f61e02",
    "cls_sent": "6e4f097e25d3baddfa5d4beda0c51ff007eda0d6e421dee51208892b8baa48ff",
    "day_one_targets": "919661d53041707542747ec84c0b5d6a358f8fb8aef3b65e3364a93bf42c5d71",
    "exit": 6,
    "flatten|flat": "d7476eddef84cf9172a80137dd6bb810d8208773ddc0c3d6b3c779e8c3a173f1",
    "flatten|held": "d7476eddef84cf9172a80137dd6bb810d8208773ddc0c3d6b3c779e8c3a173f1",
    "held_targets": "d8106417461bfa90b094ab4cfb0993f3bdc4b02fe8d674f07b07fffc965dc82b",
    "n_orders": 7,
    "orders": "e628eb451ee60ed44c2a3432437a51e54f7759a97439d112ce119d11e3271024",
    "panel": "172d57548229a8776518927875787e15e3c5476f9e57cd9df99e90c78738b277",
    "plan_json": "329a99ae4129552a3fa5b10fd9e7ffe82a82155823d0e706d9dbfd7f4e2e61c2",
    "plan_sha": "aa3cc8b1827344eac6a143892be4faa969df5bcb1431b09903b93b8c229a780e",
    "plan_targets": "732894a285fe4821a443ae4ce9d9d609cc3e382edc831ccb239c03e155f5fb6f",
    "send_exit": 0,
    "send_json": "28900ab87d89f8716cc885b35b3612f9f9b33ca0be117b85d12659cbd5624819",
    "send_sent": "5409c95d63e197ab80437a44fa71fb69e234f2578348b84b75cc9217193f6aaf",
    "status": "decided",
    "t-40|flat": "cb20ef6940fb809c4c06cadf7200e74798f28fd60546e30fcaa0496b2bde9553",
    "t-40|held": "92174d671ec1ff2cd7d113c89be4458df8dcaa2ac408a5c9a1e7c16c5db6ca86",
}


def _compare(got: dict, pinned: dict, what: str):
    assert FLOAT_KEYS & set(pinned) and set(got) == set(pinned)
    if platform.machine() == PIN_MACHINE:
        assert got == pinned
        return
    stable = {k: v for k, v in pinned.items() if k not in FLOAT_KEYS}
    assert {k: got[k] for k in stable} == stable
    moved = sorted(k for k in FLOAT_KEYS & set(pinned) if got[k] != pinned[k])
    if moved:
        warnings.warn(f"{what}: float fingerprints {moved} differ on {platform.machine()} from "
                      f"the {PIN_MACHINE} pin; the orders, plan and counts match exactly. "
                      f"Re-derive on this machine per the module docstring if this platform "
                      f"should be pinned too.")


def test_synthetic_book_is_the_code_before_the_combiner(tmp_path, monkeypatch):
    reasons = {}
    got = _synthetic_hashes(tmp_path, monkeypatch, reasons)
    _compare(got, SYN_PINNED, "combiner synthetic pin")
    # Not vacuous: the branches the generator was built to reach are reached.
    every = [x for k, rs in reasons.items() if k != "_session" for x in rs]
    assert any("band hold" in x for x in every) and any("cef discount z=" in x for x in every)
    assert any("illiquid" in x for x in every) and any("below min weight" in x for x in every)
    assert set(reasons["flatten|held"]) == {"cef: only 5 eligible names"}
    assert not any("*x" in x for x in reasons["asof|held"])
    _assert_not_vacuous(reasons["_session"])


# -------------------------------------------------- 3. the real-panel pin

def _frozen_copy(dst, monkeypatch, universe) -> str:
    """Copy the real panels' rows for `universe` dated at or before ASOF into
    `dst`, sorted (ticker, date) with a stable sort, point the sleeve at the copy,
    and return the sha256 of its canonical content. Rows after ASOF and other
    tickers cannot reach a decision as of ASOF, but they change with every
    refresh; the copy keeps the pin's input exactly the rows the decision reads."""
    from src.deploy.sleeves import cef_discount as cefmod
    parts, paths = [], {}
    for name, src in (("cef_prices.parquet", cefmod.PX_PATH), ("cef_nav.parquet", cefmod.NAV_PATH)):
        df = pd.read_parquet(src)
        df = df[df["ticker"].isin(universe) & (pd.to_datetime(df["date"]) <= pd.Timestamp(ASOF))]
        df = df.sort_values(["ticker", "date"], kind="mergesort").reset_index(drop=True)
        paths[name] = dst / name
        df.to_parquet(paths[name])
        parts.append(f"{name}\n{sorted((c, str(t)) for c, t in df.dtypes.items())}\n"
                     f"{df.to_csv(index=False)}")
    monkeypatch.setattr(cefmod, "PX_PATH", paths["cef_prices.parquet"])
    monkeypatch.setattr(cefmod, "NAV_PATH", paths["cef_nav.parquet"])
    monkeypatch.setattr(cefmod, "GRP_PATH", paths["cef_prices.parquet"])
    return _sha("\n".join(parts))


# PINNED 2026-10-28 on de6e9c5, on the laptop's dev panels (cef_prices to
# 2026-10-15, cef_nav to 2026-10-14; only rows through ASOF are read).
PINNED_INPUT = {
    "panel": "3c614b42a0acf9ea570afba16f2c4defd990799a8c231d9cdd0c71f5daebcc7a",
    "spec": "c05035e55eaa89172f65d38a3485cb1c68123217177343b38576edf56583c02e",
}
PINNED = {
    "band_holds": 6,
    "cls_exit": 0,
    "cls_plan_json": "30c8365833d800354de21de157fa01b62e4eeb90674400583fc756639ac36e6c",
    "cls_sent": "25b99647c913c17a63ddf53de40eb555ee25068c6c3e0b9e2851053e0e698638",
    "day_one_targets": "191edf1e76de87eb654a62068e69e1e250fffa9a64c6c19d8bbf1d99676f7d70",
    "exit": 6,
    "held_targets": "c7107831e64c5968dda563d267c23a5c631168cb5525f1d60fbadd0b761f70eb",
    "n_orders": 6,
    "orders": "f198dd92f1f473578190d104e61bd70d8bb2352ecb253bc12ccc6c9b23d75a2c",
    "plan_json": "410f7a4d24f97f08f533d8afe4c07736f277128816554474e19d8e74c9977fb8",
    "plan_sha": "e69a46f6680840664ed3b44e21eb767cf4d9f641e0b3f9ee0fd07e45fa084e05",
    "plan_targets": "978e2df32387f0be9e49a3a5966369bed1866e780b1ca8d79d562d11f2c37f56",
    "send_exit": 0,
    "send_json": "ac1adb88597ac75eb557fc634eae9f879b5196a07c03cdbbcfc05fa2a46d6a9b",
    "send_sent": "b30cc665d139dfebf931d9cac73299e66c22518a92a49e5c70d6a68e9532139d",
    "status": "decided",
}


@pytest.mark.skipif(not _real_panel_ready(), reason="real CEF panels absent (data/ is "
                                                     "gitignored); the synthetic pin still runs")
def test_real_sleeve_on_the_real_panel_is_the_code_before_the_combiner(tmp_path, monkeypatch):
    from src.deploy.sleeves import cef_discount as cefmod
    real = {f: f.read_bytes() for f in (cefmod.PX_PATH, cefmod.NAV_PATH)}
    spec = json.loads(LIVE_SPEC_PATH.read_text())
    (tmp_path / "panels").mkdir()
    got_input = {"panel": _frozen_copy(tmp_path / "panels", monkeypatch,
                                       spec["frozen"]["universe"]),
                 "spec": _sha(LIVE_SPEC_PATH.read_bytes())}
    if got_input != PINNED_INPUT:
        why = (f"REAL-PANEL COMBINER NO-OP PIN NOT APPLIED: it was made on panel/spec "
               f"{PINNED_INPUT}; this tree has {got_input} (a refresh revised rows through "
               f"{ASOF}, another machine's panel, or a spec bump). The old code's output on "
               f"these inputs is unmeasured; the synthetic pin still runs")
        warnings.warn(why, RealPanelPinNotApplicable)
        pytest.skip(why)
    assert cefmod.PX_PATH.parent == tmp_path / "panels"            # deciding on the copy
    r = _session(tmp_path / "run", spec)
    _compare(_hashes(r), PINNED, "combiner real-panel pin")
    _assert_not_vacuous(r)
    assert all(f.read_bytes() == b for f, b in real.items()), "a real panel changed"


# -------------------------------------------------- 4. one sleeve through the combiner

def _one_sleeve(tmp_path, spec_path, repo):
    """The combiner engaged on ONE sleeve, the book's own spec, at budget 1.0."""
    from quantt.session import combine as cmb
    bj = tmp_path / "book.json"
    bj.write_text(json.dumps({"book_id": "t", "sleeves": [
        {"name": "cef_discount", "enabled": True,
         "spec_path": spec_path.relative_to(repo).as_posix(), "risk_budget": 1.0}]}))
    sleeves = cmb.load_sleeves(bj, spec_path, repo, rn._sleeve_target_fn)
    assert sleeves is not None and len(sleeves) == 1
    return sleeves


def _assert_same_trades(single: dict, combined: dict, budget_nav: float):
    a, b = json.loads(single["plan_raw"]), json.loads(combined["plan_raw"])
    wire = ("client_order_id", "symbol", "side", "qty", "time_in_force", "leg", "current",
            "target", "est_price")
    assert [{k: o[k] for k in wire} for o in a["orders"]] == \
        [{k: o[k] for k in wire} for o in b["orders"]]
    assert a["plan_sha"] == b["plan_sha"]
    assert {s: (t["current"], t["target"]) for s, t in a["targets"].items()} == \
        {s: (t["current"], t["target"]) for s, t in b["targets"].items()}
    for k in ("exit", "send_exit", "send_sent", "cls_exit", "cls_sent"):
        assert single[k] == combined[k], k
    assert json.loads(single["send_raw"])["plan_sha"] == json.loads(combined["send_raw"])["plan_sha"]
    # Where plan.json must differ, and only there.
    assert "combine" not in a
    c = b.pop("combine")
    for x in (a, b):
        for o in x["orders"]:
            o.pop("reason")
        for t in x["targets"].values():
            t.pop("reason")
            t.pop("kind")
    assert a == b
    rec = c["sleeves"]["cef_discount"]
    assert rec["sleeve_nav"] == budget_nav and rec["status"] == "decided"
    assert {s: t["target"] for s, t in rec["targets"].items()} == \
        {s: t["target"] for s, t in json.loads(single["plan_raw"])["targets"].items()}


def test_one_sleeve_through_the_combiner_sends_what_the_single_sleeve_book_sends(
        tmp_path, monkeypatch):
    _synthetic_panel(tmp_path, monkeypatch)
    sp = tmp_path / "syn.frozen.json"
    sp.write_text(json.dumps(SYN_SPEC))
    single = _session(tmp_path / "single", SYN_SPEC)
    combined = _session(tmp_path / "combined", SYN_SPEC,
                        sleeves=_one_sleeve(tmp_path, sp, tmp_path))
    _assert_not_vacuous(single)
    _assert_same_trades(single, combined, budget_nav=100_000.0)


@pytest.mark.skipif(not _real_panel_ready(), reason="real CEF panels absent (data/ is "
                                                     "gitignored); the synthetic version runs")
def test_one_sleeve_through_the_combiner_on_the_real_panel(tmp_path, monkeypatch):
    spec = json.loads(LIVE_SPEC_PATH.read_text())
    (tmp_path / "panels").mkdir()
    _frozen_copy(tmp_path / "panels", monkeypatch, spec["frozen"]["universe"])
    single = _session(tmp_path / "single", spec)
    combined = _session(tmp_path / "combined", spec,
                        sleeves=_one_sleeve(tmp_path, LIVE_SPEC_PATH, rn.REPO))
    _assert_not_vacuous(single)
    _assert_same_trades(single, combined, budget_nav=100_000.0)
