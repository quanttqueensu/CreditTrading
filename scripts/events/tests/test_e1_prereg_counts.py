"""E1 pre-registration counts: the declared partition and the no-return guard.

Synthetic frames only: these test the counting code, never a market claim.
Nothing here reads R2, CRSP or Alpaca (the root conftest blocks the network).
"""
import pandas as pd
import pytest

from scripts.events import e1_prereg_counts as e1


def _deals():
    return pd.DataFrame({
        "nwperm":    [1, 1, 2, 3, 4, 5],
        "dlstdt":    pd.to_datetime(["2015-06-05", "2015-06-05", "2016-09-09",
                                     "2023-04-14", "2021-04-16", "2023-07-28"]),
        "touch_uni": [False, False, True, True, True, True],
        "spec_touch": [False, False, False, False, True, True],
    })


def test_partition_puts_each_deal_in_exactly_the_declared_set():
    x = _deals()
    got = e1.partition(x).tolist()
    assert got == ["fit_seen", "fit_seen",          # no universe name, pre-2023
                   "name_holdout",                  # a universe name, pre-2023
                   "time_holdout",                  # completion in 2023 beats the name rule
                   "excluded_spec", "excluded_spec"]  # a spec name beats both holdouts
    assert set(got) <= set(e1.PARTS)


def test_time_holdout_starts_on_2023_01_01_exactly():
    x = pd.DataFrame({"nwperm": [1, 2], "dlstdt": pd.to_datetime(["2022-12-30", "2023-01-03"]),
                      "touch_uni": [False, False], "spec_touch": [False, False]})
    assert e1.partition(x).tolist() == ["fit_seen", "time_holdout"]


def test_a_group_straddling_two_sets_raises():
    x = _deals()
    x["part"] = e1.partition(x)
    e1.assert_groups_whole(x)                       # the declared frame is whole
    x.loc[1, "part"] = "name_holdout"               # one target of acquirer 1's deal moved
    with pytest.raises(AssertionError, match="straddle"):
        e1.assert_groups_whole(x)


def test_no_payoff_column_is_ever_loaded():
    # The delisting return, its ex-distribution twin, the amount and the price
    # are the merger's payoff. A count that loads them can become a return.
    for col in ("dlret", "dlretx", "dlamt", "dlprc"):
        assert col not in e1.DELIST_COLUMNS
    assert set(e1.DELIST_COLUMNS) == {"permno", "dlstdt", "dlstcd", "nwperm"}


def test_load_reads_only_the_declared_delisting_columns(tmp_path):
    pd.DataFrame({"permno": [1], "dlstdt": ["2015-06-05"], "dlstcd": [231], "nwperm": [2],
                  "dlret": [0.5], "dlamt": [9.0]}).to_parquet(tmp_path / "dsedelist.parquet")
    pd.DataFrame({"permno": [1], "namedt": ["2000-01-01"], "nameendt": ["2015-06-05"],
                  "ticker": ["AAA"]}).to_parquet(tmp_path / "dsenames.parquet")
    _, dl = e1.load(tmp_path)
    assert list(dl.columns) == list(e1.DELIST_COLUMNS)
