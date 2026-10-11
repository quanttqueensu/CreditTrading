"""The ADV floor drops a name whose ADV cannot be measured (2026-10-11).

`adv` is a 63-session mean of price x volume with min_periods=21, so it is NaN
when fewer than 21 of those sessions have a volume. The floor read
`float(adv or 0.0) < min_adv`; `nan or 0.0` is nan and `nan < x` is False, so a
name with a finite z-score and no measurable liquidity passed the floor
silently (no silent fallbacks, CLAUDE.md). On the 1998-11..2026-09-25 panel this
never happened, so the fix is a no-op on history; this pins it for the future.
Synthetic panel: the group-cap tests' builder, with one name's volume removed.
"""
import pandas as pd

from src.deploy.sleeve import FLAT
from src.deploy.sleeves import cef_discount as cefmod
from src.deploy.tests.test_group_cap import _signed, _spec, _targets, _write_panel


def _blank_volume(sym, last_n):
    p = cefmod.PX_PATH
    df = pd.read_parquet(p)
    dates = sorted(df["date"].unique())[-last_n:]
    df.loc[df["ticker"].eq(sym) & df["date"].isin(dates), "volume"] = float("nan")
    df.to_parquet(p)


def test_a_name_with_unmeasured_adv_is_dropped_not_passed(tmp_path, monkeypatch):
    asof, _ = _write_panel(tmp_path, monkeypatch)
    spec = _spec(group_cap=None, max_gross_stress=None)
    assert "TAX1" in _signed(_targets(spec, asof))        # liquid and signalled: traded
    _blank_volume("TAX1", 60)                              # < 21 of the last 63 have volume
    out = {t.instrument: t for t in _targets(spec, asof)}
    assert "TAX1" not in _signed(out.values())
    assert out["TAX1"].side == FLAT and "ADV unmeasured" in out["TAX1"].reason
