"""C4 step 1, the no-op pin that never skips: a synthetic book hashed on the code BEFORE the keys.

WHY THIS EXISTS (independent review of 11790b5, 2026-10-27). The real-panel pin
in `test_c4_keys_noop.py` is only a proof on the inputs it was made on, so it
SKIPS on the VM's panel and after any revision of the panel's history; and its
companion only compares the new code with itself (keys absent against keys at
their defaults). Neither would notice a later edit that moved the absent path
on a machine whose panel is not the pinned one. This test has no such escape:
its panel is generated here, its spec is a fixture, and its expected hashes
were computed by the sleeve, registry and runner AT 66ec3df -- the tree before
any C4 key existed -- so a change to the keys-absent path fails it everywhere.

HOW THE PIN WAS MADE. `git archive 66ec3df` into a scratch directory, this file
copied into that tree, and `_synthetic_hashes` run there in a fresh process,
once unseeded and under PYTHONHASHSEED 1, 2 and 3 (identical every time); then
on 11790b5 and on the tree that carries this file (identical again). To
re-derive it -- after a deliberate change of the absent path, a pandas or numpy
upgrade, or on a platform where the floats come out differently -- do exactly
that again and paste the result; never edit a hash by hand.

THE PANEL. Thirteen synthetic funds `SYA`..`SYM` (no fund either real panel
holds), 480 sessions to 2026-09-25, built from an integer LCG and IEEE
add/multiply/divide only (no RNG library, no libm), so the inputs themselves are
the same bytes on any machine; `panel` in the pin is their hash, so a
generator drift is told apart from a code change. It reaches every branch the
keys touch: a flat and a held book, the band's HOLD and TRADE, the dust filter,
a name dropped as illiquid, a missing NAV row, and a date on which only 5 names
are eligible, so `min_names` flattens a held book. On the decision date
`max_gross_stress` does not bind on the held book: where it binds the sleeve's
last ulp depends on the hash seed (the band's set union fixes the order
`_cap_gross` sums in; 11790b5's commit message), and a pin there would flake.

THE FIXTURE SPEC is a test input chosen to reach those branches, not the live
book's parameters (those are read from `ops/specs/` wherever a test needs them).

Against the UNFIXED code this test passes by construction -- it is a no-op
proof, and 66ec3df and 11790b5 are both the no-op. What makes it fail is any
change to the keys-absent path: the mutation check changes the discount to an
algebraically equal expression (`px / nav - 1`) and it fails.
"""
import pandas as pd

from quantt.session import run as rn
from quantt.session.tests.test_c4_keys_noop import ASOF, _session_hashes, _sha
from src.deploy.registry import build_sleeve
from src.deploy.sleeve import SHORT, MarketState
from src.deploy.tests.test_group_cap import _fingerprint

SYN_TICKERS = tuple(f"SY{c}" for c in "ABCDEFGHIJKLM")
SYN_SPEC = {
    "spec_id": "synthetic.c4-noop.v1", "status": "test", "capital_usd": 100_000.0,
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
    """The panel, in the live schema, at `dst`; returns (px_path, nav_path, dates)."""
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


def _sleeve(asof, holdings, opening):
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


def _synthetic_hashes(tmp_path, monkeypatch, reasons=None) -> dict:
    """Every output the pin covers, hashed. `reasons`, if a dict, receives each
    book's reason strings (kept out of the hash so the pin is exactly what the
    old code produced)."""
    from src.deploy.sleeves import cef_discount as cefmod
    (tmp_path / "panel").mkdir()
    px, nv, dates, panel_sha = _write_synthetic(tmp_path / "panel")
    monkeypatch.setattr(cefmod, "PX_PATH", px)
    monkeypatch.setattr(cefmod, "NAV_PATH", nv)
    monkeypatch.setattr(cefmod, "GRP_PATH", px)
    P = pd.read_parquet(px)
    out = {"panel": panel_sha}
    for label, i in (("asof", N_DAYS - 1), ("asof-1", N_DAYS - 2), ("t-40", N_DAYS - 40),
                     ("flatten", FLATTEN_I)):
        day = dates[i]
        close = P[P["date"] == day].set_index("ticker")["close"].to_dict()
        day1 = _sleeve(day, {}, True)
        held = _half(day1, close) if label != "flatten" else dict(FLATTEN_HELD)
        books = {"flat": day1, "held": _sleeve(day, held, False)}
        for b, targets in books.items():
            out[f"{label}|{b}"] = _sha(_fingerprint(targets))
            if reasons is not None:
                reasons[f"{label}|{b}"] = [t.reason for t in targets]
    out.update(_session_hashes(tmp_path / "run", SYN_SPEC))
    return out


# PINNED 2026-10-27 on 66ec3df (see the module docstring for how, and how to re-derive).
SYN_PINNED = {
    "asof-1|flat": "c96d532c3b5a9345fe87ea1f93d4a68724e8886532cb79fa0c373ad1c7fe2ae5",
    "asof-1|held": "5f3a3ae553dd0120c70bbfad6476dd464a3dd154e3daa96396635fd71d466f8f",
    "asof|flat": "919661d53041707542747ec84c0b5d6a358f8fb8aef3b65e3364a93bf42c5d71",
    "asof|held": "d8106417461bfa90b094ab4cfb0993f3bdc4b02fe8d674f07b07fffc965dc82b",
    "band_holds": 5,
    "day_one_targets": "919661d53041707542747ec84c0b5d6a358f8fb8aef3b65e3364a93bf42c5d71",
    "exit": 6,
    "flatten|flat": "d7476eddef84cf9172a80137dd6bb810d8208773ddc0c3d6b3c779e8c3a173f1",
    "flatten|held": "d7476eddef84cf9172a80137dd6bb810d8208773ddc0c3d6b3c779e8c3a173f1",
    "held_targets": "d8106417461bfa90b094ab4cfb0993f3bdc4b02fe8d674f07b07fffc965dc82b",
    "n_orders": 7,
    "orders": "e628eb451ee60ed44c2a3432437a51e54f7759a97439d112ce119d11e3271024",
    "panel": "172d57548229a8776518927875787e15e3c5476f9e57cd9df99e90c78738b277",
    "plan_json": "8571f5978ec7188e0f7e4f2ee7604139a882ff6e21274bc2733372f188458332",
    "plan_sha": "aa3cc8b1827344eac6a143892be4faa969df5bcb1431b09903b93b8c229a780e",
    "plan_targets": "732894a285fe4821a443ae4ce9d9d609cc3e382edc831ccb239c03e155f5fb6f",
    "status": "decided",
    "t-40|flat": "cb20ef6940fb809c4c06cadf7200e74798f28fd60546e30fcaa0496b2bde9553",
    "t-40|held": "92174d671ec1ff2cd7d113c89be4458df8dcaa2ac408a5c9a1e7c16c5db6ca86",
}


def test_synthetic_book_with_keys_absent_is_the_code_before_them(tmp_path, monkeypatch):
    assert not {"panel_source", "nav_repeat_mask", "zero_volume_mask",
                "below_min_names"} & set(SYN_SPEC["frozen"])
    reasons = {}
    got = _synthetic_hashes(tmp_path, monkeypatch, reasons)
    assert got == SYN_PINNED
    # Not vacuous: the branches the module docstring names are all reached.
    every = [r for rs in reasons.values() for r in rs]
    assert any("band hold" in r for r in every) and any("cef discount z=" in r for r in every)
    assert any("illiquid" in r for r in every) and any("below min weight" in r for r in every)
    assert set(reasons["flatten|held"]) == {"cef: only 5 eligible names"}
    assert not any("*x" in r for r in reasons["asof|held"])       # cap not binding: seed-free
    assert got["exit"] == rn.EXIT_PLANNED and got["n_orders"] > 0 and got["band_holds"] > 0
