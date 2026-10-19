"""`scripts/ops/ibkr_second_broker_names.py` on synthetic inputs. No network.

WHY THESE TESTS
---------------
The script decides which names a second broker is for, so its failure modes
are the silent ones:
* a reordered or renamed IBKR column must raise, never read the rebate as the fee;
* IBKR's '>10000000' bound must survive as a bound;
* a name IBKR does not carry, or carries twice, must raise, never vanish;
* a snapshot that lists a name in its universe but has no asset row for it must
  raise, never count as shortable;
* the 17-name 2026-09-28 snapshot must not inflate a v7 name's denominator with
  names it never carried, and a name outside a snapshot's universe gets no row.
Synthetic inputs test the code, not the market.
"""
import pytest

from scripts.ops.ibkr_second_broker_names import ibkr_rows, parse_usa_txt, snapshot_flags, tally

GOOD = (
    "#BOF|2026.10.19|10:59:08\n"
    "#SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE|\n"
    "AAA|USD|FUND A &amp; CO|1|US0|3.0|0.88|600000|\n"
    "BBB|USD|FUND B|2|US1|-1.09|4.97|>10000000|\n"
    "#EOF|2\n"
)


def test_parse_reads_stamp_fee_rebate_and_keeps_the_bound():
    df, stamp = parse_usa_txt(GOOD)
    assert stamp == "2026-10-19 10:59:08"
    a = df.set_index("symbol")
    assert a.loc["AAA", "ibkr_fee_pct"] == 0.88 and a.loc["AAA", "ibkr_rebate_pct"] == 3.0
    assert a.loc["AAA", "ibkr_name"] == "FUND A & CO"
    assert a.loc["BBB", "ibkr_available"] == 10_000_000 and bool(a.loc["BBB", "ibkr_available_gt"])
    assert not bool(a.loc["AAA", "ibkr_available_gt"])


def test_a_changed_header_raises():
    bad = GOOD.replace("REBATERATE|FEERATE", "REBATE|FEE")
    with pytest.raises(ValueError, match="header lacks"):
        parse_usa_txt(bad)


def test_no_bof_line_raises():
    with pytest.raises(ValueError, match="BOF"):
        parse_usa_txt(GOOD.split("\n", 1)[1])


def test_an_unparseable_fee_raises_naming_the_symbol():
    with pytest.raises(ValueError, match="AAA"):
        parse_usa_txt(GOOD.replace("|0.88|", "|zero|"))


def test_a_name_ibkr_does_not_carry_raises():
    with pytest.raises(ValueError, match="CCC"):
        ibkr_rows(GOOD, ["AAA", "CCC"])


def test_a_name_carried_twice_raises():
    dup = GOOD.replace("#EOF", "AAA|USD|FUND A PFD|3|US2|2.0|1.88|100|\n#EOF")
    with pytest.raises(ValueError, match="more than once"):
        ibkr_rows(dup, ["AAA"])


def _snap(universe, assets):
    return {"universe": universe, "fetched_at_utc": "t", "assets": assets}


def _a(shortable, status=None):
    return {"shortable": shortable, "easy_to_borrow": shortable,
            "borrow_status": status or ("easy_to_borrow" if shortable else "hard_to_borrow")}


def test_a_universe_name_without_an_asset_row_raises():
    snaps = {"2026-10-15": _snap(["AAA", "BBB"], {"AAA": _a(True)})}
    with pytest.raises(ValueError, match="BBB"):
        snapshot_flags(snaps, ["AAA", "BBB"])


def test_denominators_are_per_name_and_dates_are_kept():
    snaps = {
        "2026-09-28": _snap(["AAA", "OLD"], {"AAA": _a(True), "OLD": _a(False)}),
        "2026-10-10": _snap(["AAA"], {"AAA": _a(False)}),
        "2026-10-15": _snap(["AAA"], {"AAA": _a(True)}),
    }
    t = tally(snapshot_flags(snaps, ["AAA", "OLD"]))
    assert t.loc["AAA", "probe_snapshots"] == 3 and t.loc["AAA", "probe_unshortable"] == 1
    assert t.loc["AAA", "probe_unshortable_dates"] == "2026-10-10"
    assert bool(t.loc["AAA", "probe_latest_shortable"]) and t.loc["AAA", "probe_latest"] == "2026-10-15"
    assert t.loc["OLD", "probe_snapshots"] == 1 and not bool(t.loc["OLD", "probe_latest_shortable"])


def test_a_name_outside_every_universe_gets_no_row():
    snaps = {"2026-10-15": _snap(["AAA"], {"AAA": _a(True)})}
    f = snapshot_flags(snaps, ["AAA", "ZZZ"])
    assert set(f.symbol) == {"AAA"}
