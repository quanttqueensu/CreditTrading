"""The parsing and alignment helpers of the muni hazard-flag gate, on synthetic inputs.

WHY THESE TESTS
---------------
* `parse_state` decides which state a holding sits in, and every B2 exposure rests
  on it. The failures that matter were all seen on the real filings on 2026-10-20:
  "DE KALB CNTY GA" read as Delaware (the first code token), "Lower Colorado River
  Authority" read as Colorado (it is in Texas), and tender-option-bond rows that
  carry no state at all. An unparseable row must stay UNPARSED, never be assigned.
* `exposure_asof` is the lookahead guard: holdings filed ON the event date are not
  knowable at that day's decide, so only filings strictly before it may be used.
* `_assert_fit_only` is the holdout guard: any window touching 2023-01-01 raises.
* `ncsr_state_headings` is the second method the state parse is checked against;
  the 2026 N-CSRs write "New York" with a thin space (U+2009), which an earlier
  version silently dropped (12pp of New York).
* The FEMA aggregation must raise on a missing field or an inconsistent
  declaration rather than guess.
Synthetic inputs test the code, not the market. No network, no panel read.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.events import fetch_fema_declarations as ff
from scripts.events import muni_hazard_gate as g


@pytest.mark.parametrize("title,name,want,method", [
    ("HOUSTON TX ARPT SYS REVENUE", "City of Houston TX Airport System Revenue", "TX", "code"),
    ("DE KALB CNTY GA WTR & SWR REVENUE", "County of DeKalb GA Water & Sewerage Revenue", "GA", "code"),
    ("DENVER CO INTERNATIONAL BUSINESS CENTER CO MET DIST #1", "x", "CO", "code"),
    ("NEW JERSEY ST ECON DEV AUTH REVENUE", "New Jersey Economic Development Authority", "NJ", "name_start"),
    ("SAN FRANCISCO CALIF CITY &CNTY ARPTS COMMN INTL ARPT REV", "x", "CA", "abbrev"),
    ("City of Los Angeles Department of Airports", "Tender Option Bond Trust Receipts/Certificates", "CA", "known_issuer"),
    ("Lower Colorado River Authority", "Tender Option Bond Trust Receipts/Certificates", "TX", "known_issuer"),
    ("Wyandotte County Unified School District No 500 Kansas City", "x", "KS", "known_issuer"),
    ("MUNI ELEC AUTH OF GEORGIA", "Municipal Electric Authority of Georgia", "GA", "name_any"),
])
def test_parse_state_cases_seen_in_the_filings(title, name, want, method):
    assert g.parse_state(title, name) == (want, method)


def test_parse_state_never_assigns_a_default():
    assert g.parse_state("TENDER OPTION BOND TRUST RECEIPTS / CTFS VARIOUS STATES",
                         "Tender Option Bond Trust Receipts/Certificates") == (None, "unparsed")
    # A mixed-case word that spells a USPS code is a word, not a state.
    assert g.parse_state("Payments In Lieu Of Taxes Or Fees", "Some Authority") == (None, "unparsed")
    assert g.parse_state(None, None) == (None, "unparsed")


_NPORT = """<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/nport"><formData>
<genInfo><regName>X Fund</regName><repPdEnd>2021-04-30</repPdEnd><repPdDate>2020-10-31</repPdDate></genInfo>
<fundInfo><totAssets>150</totAssets><netAssets>100</netAssets></fundInfo>
<invstOrSec><name>City of Houston TX</name><title>HOUSTON TX ARPT SYS REVENUE</title><cusip>442349EC6</cusip>
<valUSD>10</valUSD><pctVal>10.0</pctVal><assetCat>DBT</assetCat><issuerCat>MUN</issuerCat><fairValLevel>2</fairValLevel>
<debtSec><maturityDt>2047-07-01</maturityDt><isDefault>Y</isDefault><areIntrstPmntsInArrs>N</areIntrstPmntsInArrs><isPaidKind>N</isPaidKind></debtSec>
</invstOrSec></formData></edgarSubmission>"""


def test_parse_nport_reads_the_as_of_date_not_the_fiscal_end():
    info, h = g.parse_nport("SEC-HEADER junk\n" + _NPORT)
    assert info["rep_pd_date"] == "2020-10-31" and info["net_assets"] == 100.0
    assert h.loc[0, "is_default"] == "Y" and h.loc[0, "pct_val"] == 10.0


def test_parse_nport_raises_on_missing_pieces():
    with pytest.raises(g.GateError):
        g.parse_nport("<html>not an N-PORT</html>")
    with pytest.raises(g.GateError):
        g.parse_nport(_NPORT.replace("<pctVal>10.0</pctVal>", ""))


def _sw():
    return pd.DataFrame(dict(
        fund=["MHD"] * 3, state=["NY", "NY", "TX"],
        report_date=pd.to_datetime(["2019-10-31", "2020-01-31", "2020-01-31"]),
        filing_date=pd.to_datetime(["2019-12-24", "2020-03-27", "2020-03-27"]),
        pct_nav=[20.0, 25.0, 9.0]))


def test_exposure_uses_only_filings_strictly_before_the_event():
    sw = _sw()
    # On the filing date itself the new filing is NOT yet usable.
    w, basis, fd = g.exposure_asof(sw, "MHD", "NY", pd.Timestamp("2020-03-27"))
    assert (w, basis, fd) == (20.0, "pit", pd.Timestamp("2019-12-24"))
    w, basis, fd = g.exposure_asof(sw, "MHD", "NY", pd.Timestamp("2020-03-30"))
    assert (w, basis) == (25.0, "pit")
    # Before any filing: the first filing, labelled proxy.
    w, basis, _ = g.exposure_asof(sw, "MHD", "NY", pd.Timestamp("2012-10-29"))
    assert (w, basis) == (20.0, "proxy")
    # A state the fund does not hold is a measured zero.
    assert g.exposure_asof(sw, "MHD", "CA", pd.Timestamp("2020-06-01"))[0] == 0.0


def test_holdout_guard_raises():
    g._assert_fit_only(pd.to_datetime(["2022-12-30"]))
    with pytest.raises(g.GateError):
        g._assert_fit_only(pd.to_datetime(["2022-12-30", "2023-01-03"]))


def test_window_sum_is_close_to_close():
    r = pd.DataFrame({"X": [np.nan, 0.01, 0.02, 0.03, 0.04, 0.05]})
    # close(i0+a) -> close(i0+b) sums rows i0+a+1 .. i0+b
    assert g.window_sum(r, 2, -1, 1, "X") == pytest.approx(0.02 + 0.03)
    assert g.window_sum(r, 1, -1, 1, "X") == pytest.approx(0.01 + 0.02)  # close(0) -> close(2)
    assert np.isnan(g.window_sum(r, 0, -1, 1, "X"))     # would need close(-1)
    assert np.isnan(g.window_sum(r, 4, 0, 3, "X"))      # runs off the panel


def test_ncsr_headings_sum_sections_and_handle_thin_space():
    txt = ("<p>Schedule of Investments July 31, 2026</p>\nBlackRock MuniHoldings Fund, Inc. (MHD) (Percentages)\n"
           "Municipal Bonds\nAlabama — 5.3%\nNew York — 12.0%\nTotal Municipal Bonds — 17.3%\n"
           "Municipal Bonds Transferred to Tender Option Bond Trusts\nNew York — 13.4%\n"
           "Schedule of Investments July 31, 2026\nBlackRock MuniYield Quality Fund, Inc. (MQY) (Percentages)\n"
           "Texas — 9.9%\n")
    out = g.ncsr_state_headings(txt, "BlackRock MuniHoldings Fund, Inc. (MHD)")
    assert out == {"AL": 5.3, "NY": pytest.approx(25.4)}
    with pytest.raises(g.GateError):
        g.ncsr_state_headings(txt, "Some Other Fund (ZZZ)")


def _fema_rows():
    base = dict(disasterNumber=4611, state="LA", declarationType="DR", declarationDate="2021-08-29T00:00:00.000Z",
                incidentType="Hurricane", declarationTitle="HURRICANE IDA", incidentBeginDate="2021-08-26T00:00:00.000Z",
                incidentEndDate="2021-09-03T00:00:00.000Z", incidentId="2021082901", lastRefresh="2026-01-01T00:00:00.000Z")
    return [dict(base, femaDeclarationString="DR-4611-LA", designatedArea="Orleans (Parish)", fipsCountyCode="071"),
            dict(base, femaDeclarationString="DR-4611-LA", designatedArea="Jefferson (Parish)", fipsCountyCode="051")]


def test_fema_aggregate_one_row_per_declaration():
    out = ff.aggregate(_fema_rows())
    assert len(out) == 1
    r = out.iloc[0]
    assert (r.state, r.declarationDate, r.n_areas_at_fetch, bool(r.any_statewide_at_fetch)) == ("LA", "2021-08-29", 2, False)


def test_fema_aggregate_raises_rather_than_guessing():
    rows = _fema_rows()
    rows[1]["state"] = "MS"                      # one declaration string, two states
    with pytest.raises(ff.FemaError):
        ff.aggregate(rows)
    rows = _fema_rows()
    for r in rows:
        r.pop("incidentId")
    with pytest.raises(ff.FemaError):
        ff.aggregate(rows)
    with pytest.raises(ff.FemaError):
        ff.aggregate([])


def test_posthoc_cut_drops_fire_management_and_late_declarations():
    sw = _sw()
    inc = pd.DataFrame(dict(
        fund=["MHD"] * 3, state=["NY"] * 3, incident_type=["Hurricane", "Fire", "Hurricane"],
        types=["EM", "FM", "DR"], title=["a", "b", "c"],
        t_declared=pd.to_datetime(["2021-09-02", "2021-08-01", "2020-10-02"]),
        incident_begin=pd.to_datetime(["2021-09-01", "2021-07-31", "2020-08-04"]),
        t0=pd.to_datetime(["2021-09-02", "2021-08-02", "2020-10-02"]),
        t_news=pd.to_datetime(["2021-09-01", "2021-08-02", "2020-08-04"]),
        pct_nav=[25.0, 25.0, 25.0], basis=["pit"] * 3))
    out = g.posthoc_filter(inc, sw)
    assert list(out.title) == ["a"]                      # FM-only and the 59-day-late DR are out
    assert out.iloc[0].t0 == pd.Timestamp("2021-09-01")  # re-anchored at the news date
