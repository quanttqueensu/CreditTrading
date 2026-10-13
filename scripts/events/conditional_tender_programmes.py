"""The conditional-tender census, as read from the filings: programmes, windows, exclusions.

WHY THIS IS A HAND-CODED TABLE, AND WHY THAT IS NOT A HAND-COPIED SERIES
-----------------------------------------------------------------------
`CLAUDE.md` forbids hand-copying a data series. This file is not a series; it
is the coding of ~45 legal texts (press releases, offer documents, annual
reports) into fields: which fund, which window, which threshold, which
outcome. No parser reads "the 12 calendar weeks prior to a date in the second
quarter designated by the Board" reliably, so a reader did, on 2026-10-13.
What keeps it honest is that EVERY coded fact carries its source:

  * `ev` = (CIK, accession, quote). `conditional_tender_census.verify_evidence`
    fetches the filing through `scripts/data/edgar_client.py` (cache first) and
    RAISES if the quote is not in it (after whitespace, case, quote-mark and
    dash normalisation, `normalise`). A published average is only coded if the
    quote that carries it contains the number, so a mistyped figure fails the
    run instead of entering the CSV.
  * Outcomes the filings never state ("no tender followed") are coded
    `not_triggered_inferred` and carry no quote. The census script checks them
    against the EDGAR index instead: the fund must have filed no SC TO-C /
    SC TO-I in the 180 days after the window ended (`check_inferred`). An
    inference that the index contradicts raises.
  * The BlackRock 2024-26 programmes publish a TABLE per window (15-19 funds).
    Those rows are not typed here at all: `TABLES` names the filing and the
    census parses it (`conditional_tender_census.parse_dmp_table`, tested), and
    cross-checks every parsed trigger against the fund's own SC TO-C filings.

Labels: a quote-verified row is [V] as of the fetch; a `_inferred` row is [V]
for "no tender was filed", [U] for why. Dates are as the filings state them.

SCOPE (the task, 2026-10-13): US-listed CEFs and BDCs, windows ending 2010-01-01
or later, where a fund COMMITS to a tender (not merely "will consider") if an
AVERAGE discount over a STATED window passes a STATED threshold. Hybrids that
add a second condition (a minimum take-up in a prior tender) are kept and
flagged `hybrid`. Tenders conditional only on a vote, a merger, NAV
performance, or a point-in-time premium test are excluded and listed in
`EXCLUDED` with the reason, so every discovery hit is accounted for.

SIGN CONVENTION. `avg` is the published average premium(+)/discount(-) in
percent, the panel's convention (close/NAV - 1). A release that says "average
daily discount of 10.20%" is coded -10.20. `threshold` is the discount
magnitude in percent; the trigger is avg < -threshold (`cmp` ">"), or
avg <= -threshold (`cmp` ">=").
"""
from __future__ import annotations

# ----------------------------------------------------------------- vocabulary
OUTCOMES = (
    "triggered",               # a filing states the condition was met
    "triggered_inferred",      # a tender was filed under the policy; no filing states the average
    "not_triggered",           # a filing states the condition was not met
    "not_triggered_inferred",  # no statement; no SC TO filed within 180 days (checked against the index)
    "triggered_cancelled",     # met, then the tender was cancelled (replaced by a settlement)
    "withdrawn",               # the board withdrew the window before it ended
    "waived",                  # the obligation was waived in advance (a pending merger)
    "suspended",               # the board suspended the policy during the window
    "superseded",              # the fund merged or the programme was replaced before the window ran
    "unknown",                 # no outcome found
)
DOCUMENTED = ("triggered", "not_triggered", "triggered_cancelled")
TRIGGERED = ("triggered", "triggered_inferred", "triggered_cancelled")
NOT_TRIGGERED = ("not_triggered", "not_triggered_inferred")

# Metric bases. Only `daily_close` can be checked against our close/NAV panels to
# the basis point; the others are approximated by it and labelled so.
BASES = ("daily_close", "daily_vwap", "weekly_close", "run_10d_vwap", "calendar_month_vwap",
         "unspecified_daily", "unspecified")

# --------------------------------------------------------------- programmes
# pid: sponsor-yyyy. `ann` is the announcement date the filings give (EDGAR
# filing date where only that is known: an upper bound). `ann_ev` cites it.
PROGRAMMES = [
    dict(pid="WA-GFY-2009", fixed_dates=False, sponsor="Legg Mason", origin="board (Western Asset sub-adviser)", asset="loans / floating rate",
         funds={"GFY": 1299393}, ann="2009-02-04",
         ann_ev=(1299393, "0001104659-10-001377", "conditional tender offer for common shares of the Fund announced by the Fund on February 4, 2009"),
         threshold=10.0, cmp=">", basis="weekly_close", size="up to 20%", price=98.0, hybrid="price trigger (NAV >= $16.00) opens the window",
         window_rule="12 weeks after a NAV price trigger is first hit",
         terms_ev=(1299393, "0001104659-10-001377", "as computed by measuring the average discount based on the Fund’s per share closing NAV and market price as of the last business day of each week during the Measuring Period"),
         channel="scan"),
    dict(pid="NB-2009", fixed_dates=False, sponsor="Neuberger Berman", origin="board", asset="muni (3), REIT (NRO), high yield (NHS)",
         funds={"NBW": 1178840, "NBH": 1178839, "NBO": 1178841, "NRO": 1261166, "NHS": 1487610}, ann=None,
         ann_ev=None, threshold=10.0, cmp=">", basis="unspecified_daily", size="5%-20% (board sets)", price=98.0, hybrid="",
         window_rule="four 12-week periods per fund, dates set by the boards",
         terms_ev=(1261166, "0000898432-10-000724", "if a Fund’s common stock trades at an average daily discount to net asset value per share (“NAV”) of greater than 10% during a 12-week measurement period, the Fund would conduct a tender offer for between 5% and 20%"),
         channel="scan"),
    dict(pid="NB-NRO-2016", fixed_dates=False, sponsor="Neuberger Berman", origin="board", asset="REIT",
         funds={"NRO": 1261166}, ann="2016-07-26",
         ann_ev=(1261166, "0000898432-16-002783", "during the measurement period from December 31, 2015 through September 30, 2016, the Fund will conduct a tender offer for up to 15%"),
         threshold=10.0, cmp=">", basis="unspecified_daily", size="up to 15% (2016); at least 8% (2017)", price=98.0, hybrid="",
         window_rule="one 2016 window (announced after it began) then two 12-week windows in 2017",
         terms_ev=(1261166, "0000898432-16-002783", "the Fund will conduct a tender offer for at least 8% of its outstanding shares"),
         channel="scan"),
    dict(pid="DWS-2010", fixed_dates=False, sponsor="Deutsche (DWS)", origin="board", asset="equity (Europe)",
         funds={"EEA": 791718, "GF": 858706}, ann=None, ann_ev=None,
         threshold=10.0, cmp=">", basis="unspecified", size="up to 5%", price=98.0, hybrid="",
         window_rule="up to four semi-annual 12-week windows",
         terms_ev=(791718, "0000088053-10-001697", "up to four, consecutive, semi-annual tender offers each for up to 5% of the Fund’s outstanding shares of common stock at a price equal to 98% of net asset value"),
         channel="scan"),
    dict(pid="DWS-2012", fixed_dates=False, sponsor="Deutsche (DWS)", origin="board", asset="equity (Europe)",
         funds={"EEA": 791718, "GF": 858706, "CEE": 860489}, ann="2012-07-18",
         ann_ev=(791718, "0001193125-12-314459", "On July 18, 2012, the Fund announced that the Board approved the first measurement period under the new Program"),
         threshold=10.0, cmp=">", basis="unspecified", size="up to 5%", price=98.0, hybrid="",
         window_rule="up to four semi-annual 12-week windows",
         terms_ev=(860489, "0001193125-14-305103", "Pursuant to the Fund’s discount management program adopted in July 2012"),
         channel="scan"),
    dict(pid="DWS-2014", fixed_dates=False, sponsor="Deutsche (DWS)", origin="board", asset="equity (Europe)",
         funds={"EEA": 791718, "GF": 858706, "CEE": 860489}, ann=None, ann_ev=None,
         threshold=10.0, cmp=">", basis="unspecified", size="up to 5%", price=98.0, hybrid="",
         window_rule="one 15-week window between 2014-08-01 and 2015-07-31",
         terms_ev=(791718, "0001193125-15-017640", "This program provides for one contingent tender offer during the period from August 1, 2014 through July 31, 2015"),
         channel="scan"),
    dict(pid="MS-2011", fixed_dates=False, sponsor="Morgan Stanley", origin="board (amended policy)", asset="equity (Asia)",
         funds={"APF": 919808, "MF": 811797}, ann="2011-04-08",
         ann_ev=(919808, "0001104659-11-019349", "The first 12-week measurement period under the amended Policy will commence July 11, 2011"),
         threshold=10.0, cmp=">=", basis="unspecified_daily", size="up to 5%", price=98.0, hybrid="",
         window_rule="up to four semi-annual 12-week windows",
         terms_ev=(919808, "0001104659-11-055103", "if the Fund’s shares trade at an average discount of at least 10% over a 12-week period"),
         channel="scan"),
    dict(pid="SWZ-2011", fixed_dates=False, sponsor="Swiss Helvetia (Hottinger)", origin="board", asset="equity (Switzerland)",
         funds={"SWZ": 813623}, ann=None, ann_ev=None,
         threshold=10.0, cmp=">", basis="unspecified", size="up to 5%", price=98.0, hybrid="",
         window_rule="two 12-week windows in 2011",
         terms_ev=(813623, "0001193125-11-149954", "if the Fund’s shares trade at an average discount to NAV of more than 10% during the applicable twelve-week measurement period"),
         channel="scan"),
    dict(pid="LMP-SCD-2011", fixed_dates=True, sponsor="Legg Mason", origin="board", asset="equity income",
         funds={"SCD": 1270131}, ann="2011-03-09",
         ann_ev=(1270131, "0001104659-11-013292", "The measuring periods for the three conditional tenders will be July 20 to August 19, 2011, October 19 to November 18, 2011 and January 19 to February 18, 2012, respectively"),
         threshold=5.0, cmp=">", basis="daily_close", size="up to 5%", price=98.0, hybrid="",
         window_rule="three fixed 30-day windows",
         terms_ev=(1270131, "0001104659-11-013292", "average daily discount from net asset value of more than 5%"),
         channel="scan"),
    dict(pid="NOMURA-KEF-2011", fixed_dates=True, sponsor="Nomura", origin="board", asset="equity (Korea)",
         funds={"KEF": 912023}, ann="2011-06-07",
         ann_ev=(912023, "0000905148-11-001141", "if the Fund’s shares trade at a volume-weighted average discount of more than 7.5% for a period of ten consecutive trading days during the third quarter of 2011"),
         threshold=7.5, cmp=">", basis="run_10d_vwap", size="up to 10%", price=None, hybrid="a 10-consecutive-day run, not a window average",
         window_rule="any 10 consecutive trading days in Q3 2011",
         terms_ev=(912023, "0000905148-11-001141", "if the Fund’s shares trade at a volume-weighted average discount of more than 7.5% for a period of ten consecutive trading days during the third quarter of 2011"),
         channel="scan"),
    dict(pid="GCH-2011", fixed_dates=True, sponsor="Greater China Fund (Baring)", origin="board", asset="equity (China)",
         funds={"GCH": 887546}, ann=None, ann_ev=None,
         threshold=10.0, cmp=">", basis="unspecified", size="up to 5%", price=None, hybrid="",
         window_rule="two windows; replaced mid-window by an unconditional 20% tender",
         terms_ev=(887546, "0001193125-11-236597", "provided that a tender offer would be made only if the average discount to the Fund’s net asset value per share (“NAV”) of the per share trading price of the Fund’s shares on the NYSE was greater than 10% during the applicable measurement period"),
         channel="scan"),
    dict(pid="SUNAMERICA-2010", fixed_dates=False, sponsor="SunAmerica", origin="board", asset="equity",
         funds={"FGF": 1327129, "FGI": 1338170}, ann="2010-09-14",
         ann_ev=(1327129, "0001193125-10-209469", "The Fund also intends to conduct, in each of 2011 and 2012, a cash tender offer for a portion of its shares"),
         threshold=10.0, cmp=">", basis="daily_vwap", size="up to 10% (2011), 5% (2012)", price=98.0, hybrid="",
         window_rule="one 12-week window in each of 2011 and 2012, dates to be set by the board",
         terms_ev=(1327129, "0001193125-10-209469", "if the Fund’s shares trade at a volume-weighted average discount to NAV of more than 10% over a 12-week measurement period to be established by the Board"),
         channel="scan"),
    dict(pid="MACQ-MGU-2012", fixed_dates=True, sponsor="Macquarie", origin="activist settlement (Western Investment)", asset="infrastructure equity",
         funds={"MGU": 1326390}, ann="2012-10-17",
         ann_ev=(1326390, "0001193125-12-424922", "if the Fund’s shares have traded at a market price that represents an average daily discount from net asset value of more than 8% during the measuring period"),
         threshold=8.0, cmp=">", basis="daily_close", size="up to 10%", price=92.0, hybrid="and more than 25% tendered in the initial tender",
         window_rule="20 business days, 2013-01-15 to 2013-02-12",
         terms_ev=(1326390, "0001193125-12-424922", "at a price equal to 92% of the net asset value per share"),
         channel="scan"),
    dict(pid="IRL-2012", fixed_dates=True, sponsor="New Ireland Fund (Kleinwort Benson)", origin="board (Herzfeld recommendation)", asset="equity (Ireland)",
         funds={"IRL": 858707}, ann="2012-05-10",
         ann_ev=(858707, "0000919574-12-003536", "On May 10, 2012, the Board approved an issuer tender offer"),
         threshold=10.0, cmp=">=", basis="daily_close", size="up to 5%", price=98.0, hybrid="and more than 50% tendered in the first tender",
         window_rule="calendar Q1 2013",
         terms_ev=(858707, "0000919574-12-003536", "is equal to or greater than 10% (based upon daily closing prices) in the first calendar quarter of 2013"),
         channel="rescore"),
    dict(pid="EV-ETJ-2013", fixed_dates=True, sponsor="Eaton Vance", origin="board", asset="equity (collared)",
         funds={"ETJ": 1395325}, ann="2013-11-14",
         ann_ev=(1395325, "0000940394-13-001309", "has authorized a conditional one-time cash tender offer for 10% of the Fund’s outstanding shares"),
         threshold=9.75, cmp=">", basis="calendar_month_vwap", size="10%", price=96.0, hybrid="",
         window_rule="each of the months February-May 2014",
         terms_ev=(1395325, "0000940394-13-001309", "averages more than 9.75% for any of the months of February, March, April or May 2014"),
         channel="scan"),
    dict(pid="NUV-DRA-2014", fixed_dates=False, sponsor="Nuveen", origin="board (at IPO)", asset="real assets / multi-asset",
         funds={"DRA": 1598085}, ann="2014-09-01",
         ann_ev=(1598085, "0001193125-15-340936", "In connection with the fund’s launch in September 2014, the fund announced that it would conduct a tender offer for up to 10 percent"),
         threshold=10.0, cmp=">", basis="unspecified_daily", size="up to 10%", price=99.0, hybrid="",
         window_rule="one window set by the board",
         terms_ev=(1598085, "0001193125-15-340936", "if the fund’s shares traded at an average daily discount to NAV of more than 10 percent during the measurement period"),
         channel="scan"),
    dict(pid="ZWEIG-2016", fixed_dates=True, sponsor="Virtus (Zweig)", origin="activist settlement (Karpus)", asset="balanced / equity",
         funds={"ZTR": 836412, "ZF": 812090}, ann="2016-04-05",
         ann_ev=(836412, "0001571049-17-002592", "under the terms of a tender offer program that was originally announced on April 5, 2016"),
         threshold=8.0, cmp=">", basis="daily_vwap", size="up to 5% each", price=98.0, hybrid="",
         window_rule="12 full calendar weeks after each prior tender closes (two conditional tenders)",
         terms_ev=(836412, "0001571049-16-014465", "The VWAP shall be the price as displayed under the heading “Bloomberg VWAP” for the Fund"),
         channel="scan"),
    dict(pid="ZWEIG-DCA-2016", fixed_dates=False, sponsor="Virtus (Zweig)", origin="board", asset="balanced",
         funds={"DCA": 1310445}, ann="2016-09-07",
         ann_ev=(1310445, "0001571049-16-018076", "consisting of two tender offers (one unconditional and one conditional), each up to 5 percent of shares"),
         threshold=None, cmp=None, basis="unspecified", size="up to 5%", price=None, hybrid="",
         window_rule="not stated in the filings read",
         terms_ev=(1310445, "0001571049-16-018076", "consisting of two tender offers (one unconditional and one conditional), each up to 5 percent of shares"),
         channel="scan"),
    dict(pid="MFS-CXH-2017", fixed_dates=True, sponsor="MFS", origin="activist settlement (Karpus)", asset="muni",
         funds={"CXH": 847411}, ann="2017-07-11",
         ann_ev=(847411, "0001193125-17-226148", "provided that the Conditional Tender Offer will take place only if the average trading discount of the Shares to NAV is greater than 6 percent"),
         threshold=6.0, cmp=">", basis="daily_close", size="up to 7.5%", price=98.0, hybrid="",
         window_rule="days 90-180 after the initial tender completes",
         terms_ev=(847411, "0001193125-18-079336", "calculated based on the simple average of the trading discounts (and premiums, as the case may have been) on each day the NYSE was open for trading"),
         channel="scan"),
    dict(pid="BLK-DSU-2017", fixed_dates=False, sponsor="BlackRock", origin="board", asset="loans / multi-sector credit",
         funds={"DSU": 1051003}, ann=None, ann_ev=None,
         threshold=7.5, cmp=">", basis="unspecified_daily", size="10% then at least 5%", price=98.0, hybrid="",
         window_rule="three 3-month windows, Dec-Feb",
         terms_ev=(1051003, "0001193125-18-084821", "the Fund intends to offer to purchase up to 10% of its outstanding Shares for the First Measurement Period"),
         channel="scan"),
    dict(pid="DEL-DDF-STANDING", fixed_dates=False, end_date_public=False, sponsor="Delaware", origin="prospectus commitment (1993), threshold set in a 2010 proxy", asset="equity income",
         funds={"DDF": 896923}, ann="2010-09-03",
         ann_ev=(896923, "0001206774-14-001854", "in the Fund’s proxy statement dated September 3, 2010"),
         threshold=10.0, cmp=">", basis="weekly_close", size="not stated in the passage read", price=None, hybrid="",
         window_rule="12 calendar weeks before a Q2 date the board designates (end date not public in advance)",
         terms_ev=(896923, "0001206774-14-001854", "as of the last trading day in each week during such twelve-week period"),
         channel="web"),
    dict(pid="DEL-DGF-STANDING", fixed_dates=False, end_date_public=False, sponsor="Delaware", origin="prospectus commitment (1994)", asset="global equity income",
         funds={"DGF": 916713}, ann="1994-02-25",
         ann_ev=(916713, "0001206774-11-001319", "a commitment made in the Fund’s prospectus, dated February 25, 1994"),
         threshold=3.0, cmp=">", basis="weekly_close", size="not stated in the passage read", price=None, hybrid="",
         window_rule="12 calendar weeks before a Q2 date the board designates (end date not public in advance)",
         terms_ev=(916713, "0001206774-11-001319", "at an average discount from NAV of more than 3% as of the last trading day in each week during such twelve-week period"),
         channel="rescore"),
    dict(pid="DEL-DEX-2018", fixed_dates=False, end_date_public=False, sponsor="Delaware", origin="board", asset="global equity income",
         funds={"DEX": 1396167}, ann="2018-05-24",
         ann_ev=(1396167, "0001680359-18-000228", "commencing in 2019, if the Fund is trading at an average discount of more than 10% during a 12-week measurement period established each year by the Board during the second calendar quarter of the year"),
         threshold=10.0, cmp=">", basis="weekly_close", size="5% (as conducted)", price=98.0, hybrid="",
         window_rule="12 calendar weeks before a Q2 date the board designates (end date not public in advance)",
         terms_ev=(1396167, "0001206774-19-001806", "as of the last trading day in each week during such twelve-week period"),
         channel="scan"),
    dict(pid="NUV-NBB-2018", fixed_dates=True, sponsor="Nuveen", origin="board (merger condition)", asset="taxable muni",
         funds={"NBB": 1478888}, ann="2018-11-19",
         ann_ev=(1478888, "0001193125-19-000838", "the fund announced that it would conduct a tender offer if the fund’s shares traded, on average, below net asset value over the 10 trading days from December 14, 2018 to December 28, 2018"),
         threshold=0.0, cmp=">", basis="unspecified_daily", size="up to 20%", price=100.0, hybrid="",
         window_rule="10 trading days",
         terms_ev=(1478888, "0001193125-19-000838", "will purchase up to 20 percent of its outstanding common shares for cash at a price per share equal to 100 percent of the net asset value"),
         channel="scan"),
    dict(pid="ABRDN-AEF-2018", fixed_dates=True, sponsor="Aberdeen", origin="activist settlement (City of London)", asset="equity (EM)",
         funds={"AEF": 846676}, ann="2018-04-30",
         ann_ev=(846676, "0001104659-18-028610", "undertaking a 15% tender offer if the average discount exceeds 11% of NAV over any rolling 12-month period commencing on April 30, 2018 and ending on December 31, 2019"),
         threshold=11.0, cmp=">", basis="unspecified", size="15%", price=None, hybrid="rolling 12-month windows; at most one tender",
         window_rule="any rolling 12 months between 2018-04-30 and 2019-12-31",
         terms_ev=(846676, "0001104659-18-028610", "undertaking a 15% tender offer if the average discount exceeds 11% of NAV over any rolling 12-month period"),
         channel="rescore"),
    dict(pid="EV-EIM-2019", fixed_dates=True, sponsor="Eaton Vance", origin="board", asset="muni",
         funds={"EIM": 1176984}, ann="2019-03-27",
         ann_ev=(1176984, "0000940394-19-000574", "The Board also authorized the Fund to conduct two conditional cash tender offers to follow the Firm Tender Offer"),
         threshold=6.0, cmp=">", basis="daily_vwap", size="up to 5% each", price=98.0, hybrid="",
         window_rule="two 120-day windows, the second only if the first triggered",
         terms_ev=(1176984, "0000940394-19-000635", "based on volume-weighted average market price and NAV each business day during the period"),
         channel="scan"),
    dict(pid="HERZ-2019", fixed_dates=True, sponsor="Thomas J. Herzfeld Advisors", origin="board", asset="equity (Caribbean); credit from 2024",
         funds={"CUBA": 880406}, ann="2019-05-31",
         ann_ev=(880406, "0001398344-20-024710", "that was previously announced on May 31, 2019"),
         threshold=10.0, cmp=">", basis="unspecified", size="5% (10-20% once)", price=97.5, hybrid="",
         window_rule="each fiscal year (July-June)",
         terms_ev=(880406, "0001398344-20-024710", "of 5% of outstanding shares of the Fund at 97.5% of NAV if the average discount was greater than 10% for the fiscal year just ended"),
         channel="rescore"),
    dict(pid="EV-2021", fixed_dates=True, sponsor="Eaton Vance", origin="board (after the Saba contests)", asset="loans",
         funds={"EFT": 1288992, "EFR": 1258623, "EVF": 1070732}, ann="2021-05-12",
         ann_ev=(1288992, "0000940394-21-000952", "it will conduct cash tender offers by the end of the fourth quarter of each of 2022, 2023 and 2024"),
         threshold=10.0, cmp=">", basis="daily_vwap", size="up to 10%", price=98.0, hybrid="",
         window_rule="January-August of 2022, 2023 and 2024",
         terms_ev=(1288992, "0000940394-23-001020", "based upon the Fund’s volume-weighted average market price and NAV on business days during the period"),
         channel="scan"),
    dict(pid="FT-GIM-2021", fixed_dates=False, sponsor="Franklin Templeton", origin="board", asset="global bonds",
         funds={"GIM": 828803}, ann=None, ann_ev=None,
         threshold=8.0, cmp=">=", basis="unspecified", size="up to 20%", price=98.0, hybrid="",
         window_rule="one window (dates not found); withdrawn 2021-10-13",
         terms_ev=(828803, "0001137439-21-001003", "If the Fund’s shares traded at an average discount from NAV of 8% or more during the Measurement Period, the Board would commence a tender offer for up to 20%"),
         channel="scan"),
    dict(pid="TORT-2022", fixed_dates=False, sponsor="Tortoise", origin="board", asset="energy infrastructure",
         funds={"TYG": 1268533, "NTG": 1490286, "TTP": 1526329, "NDP": 1547158, "TPZ": 1408201}, ann=None, ann_ev=None,
         threshold=10.0, cmp=">", basis="unspecified", size="5%", price=98.0, hybrid="",
         window_rule="two windows ending 2022-07-31 and 2023-07-31",
         terms_ev=(1268533, "0001140361-22-030648", "if its shares trade at an average discount to NAV of more than 10% during either of the designated measurement periods"),
         channel="scan"),
    dict(pid="BLK-2024Q", fixed_dates=True, sponsor="BlackRock", origin="activist settlement (Karpus standstill 2024-05-03)", asset="equity (14), muni (MVF)",
         funds="TABLES", ann="2024-05-03",
         ann_ev=(835948, "0001193125-24-182254", "Discount Management Program Standstill Agreement among the Fund, Karpus Management, Inc. and BlackRock Advisors, LLC, dated May 3, 2024"),
         threshold=7.5, cmp=">", basis="unspecified_daily", size="2.5%", price=98.0, hybrid="",
         window_rule="calendar quarters from 2024-04-01: four (equity) or six (MVF)",
         terms_ev=(835948, "0001193125-24-173637", "if the Fund’s common shares trade at an average daily discount to net asset value (“NAV”) of greater than 7.50% during a Measurement Period"),
         channel="scan"),
    dict(pid="BLK-2025E", fixed_dates=True, sponsor="BlackRock", origin="board (renewal)", asset="equity",
         funds={"BCAT": 1809541, "ECAT": 1864843, "BSTZ": 1768666, "BOE": 1320375, "BGR": 1306550, "BGY": 1393299,
                "CII": 1278895, "BDJ": 1332283, "BST": 1616678, "BME": 1314966, "BCX": 1506289, "BUI": 1528988},
         ann="2025-02-28",
         ann_ev=(1320375, "0001193125-26-093621", "On February 28, 2025, the Board approved the renewal of each Trust’s Program (excluding BMEZ and BTX)"),
         threshold=10.0, cmp=">", basis="unspecified_daily", size="minimum 5%", price=98.0, hybrid="",
         window_rule="2025-01-01 to 2025-09-30 (announced after it began)",
         terms_ev=(1320375, "0001193125-26-093621", "traded at an average daily discount to NAV of more than 10% during the 9-month measurement period"),
         channel="manual (annual reports)"),
    dict(pid="BLK-BKT-2025", fixed_dates=True, sponsor="BlackRock", origin="board", asset="MBS / taxable bonds",
         funds={"BKT": 832327}, ann=None, ann_ev=None,
         threshold=7.5, cmp=">", basis="unspecified_daily", size="minimum 5% (search summary)", price=None, hybrid="",
         window_rule="12 weeks, 2025-07-09 to 2025-09-30",
         terms_ev=(832327, "0001193125-26-093646", "traded at an average daily discount to NAV of more than 7.50% during the measurement period"),
         channel="manual (annual reports)"),
    dict(pid="BLK-2026E", fixed_dates=True, sponsor="BlackRock", origin="board (renewal)", asset="equity",
         funds="TABLES", ann="2025-11-14",
         ann_ev=(1320375, "0001193125-26-093621", "On November 14, 2025, the Board approved the renewal of each Trust’s Program (excluding BTX)"),
         threshold=10.0, cmp=">", basis="unspecified_daily", size="minimum 5%", price=98.0, hybrid="",
         window_rule="2026-01-01 to 2026-09-30",
         terms_ev=(1785971, "0001193125-26-410845", "a minimum of 5% of its outstanding common shares at a price equal to 98% of the Fund’s NAV"),
         channel="scan"),
    dict(pid="BLK-2026M-FEB09", fixed_dates=True, sponsor="BlackRock", origin="board (on completing mergers)", asset="muni",
         funds="TABLES", ann="2026-02-09",
         ann_ev=(1034665, "0001193125-26-043126", "each of the Survivor Funds, as identified below, adopted a Discount Management Program"),
         threshold=10.0, cmp=">", basis="unspecified_daily", size="minimum 5%", price=98.0, hybrid="",
         window_rule="2026-01-01 to 2026-09-30 (announced after it began)",
         terms_ev=(1034665, "0001193125-26-043126", "January 1, 2026 September 30, 2026 More than -10.00% Minimum of 5% of outstanding shares 98% of NAV"),
         channel="manual (Form 425)"),
    dict(pid="BLK-2026M-FEB23", fixed_dates=True, sponsor="BlackRock", origin="board (on completing mergers)", asset="muni",
         funds="TABLES", ann="2026-02-23",
         ann_ev=(890196, "0001193125-26-064386", "each of the Survivor Funds, as identified below, adopted a Discount Management Program"),
         threshold=10.0, cmp=">", basis="unspecified_daily", size="minimum 5%", price=98.0, hybrid="",
         window_rule="2026-01-01 to 2026-09-30 (announced after it began)",
         terms_ev=(1785971, "0001193125-26-410845", "if a Fund’s common shares trade at an average daily discount to net asset value (“NAV”) of greater than 10.00% during the 9-month measurement period"),
         channel="manual (Form 425)"),
    dict(pid="BLK-BKT-2026", fixed_dates=True, sponsor="BlackRock", origin="board (renewal)", asset="MBS / taxable bonds",
         funds={"BKT": 832327}, ann="2025-11-14",
         ann_ev=(832327, "0001193125-26-093646", "On November 14, 2025, the Board approved the renewal of the Program, which will consist of one measurement period beginning on July 9, 2026 and ending on September 30, 2026"),
         threshold=7.5, cmp=">", basis="unspecified_daily", size="not stated in the passage read", price=None, hybrid="",
         window_rule="12 weeks, 2026-07-09 to 2026-09-30",
         terms_ev=(832327, "0001193125-26-093646", "trade at an average daily discount to NAV of more than 7.50% during the 12-week measurement period"),
         channel="manual (annual reports)"),
    dict(pid="ZTR-2024", fixed_dates=True, sponsor="Virtus (Zweig)", origin="board", asset="global multi-asset",
         funds={"ZTR": 836412}, ann="2024-03-11",
         ann_ev=(836412, "0001193125-24-064620", "is equal to or greater than 12% during the consecutive 180 calendar day period beginning 30 days after the expiration of the Tender Offer"),
         threshold=12.0, cmp=">=", basis="unspecified", size="10%", price=98.0, hybrid="second window threshold 10%",
         window_rule="180 days from 30 days after the 2024 tender, then a second window",
         terms_ev=(836412, "0001193125-24-064620", "A first conditional tender offer for up to 10% of the Fund’s then outstanding shares at a price equal to 98% of the Fund’s NAV"),
         channel="scan"),
    dict(pid="EV-EIM-2024", fixed_dates=True, sponsor="Eaton Vance", origin="activist settlement (Karpus)", asset="muni",
         funds={"EIM": 1176984}, ann="2024-05-06",
         ann_ev=(1176984, "0000940394-24-000768", "EVM agreed to propose an initial conditional tender offer for 5% of the Fund’s outstanding Shares at 98% of NAV"),
         threshold=7.5, cmp=">", basis="daily_vwap", size="5% each", price=98.0, hybrid="",
         window_rule="two 4-month windows",
         terms_ev=(1176984, "0000940394-24-000620", "based upon the average of the difference between its volume-weighted average market price and NAV each business day during the period"),
         channel="scan"),
    dict(pid="JOF-2025", fixed_dates=True, sponsor="Nomura", origin="board", asset="equity (Japan)",
         funds={"JOF": 859796}, ann="2025-06-06",
         ann_ev=(859796, "0001140361-26-023437", "On June 6, 2025, the Board announced the adoption of a policy pursuant to which the Fund would conduct a conditional tender offer for 10% of its outstanding shares"),
         threshold=9.0, cmp=">=", basis="unspecified_daily", size="10%", price=98.0, hybrid="",
         window_rule="2025-07-01 to 2026-03-31",
         terms_ev=(859796, "0001140361-26-023437", "provided that the Fund’s shares trade at an average daily market price discount of 9% or greater to NAV"),
         channel="scan"),
]

# --------------------------------------------------------------- windows
# One row per fund x measurement window. ev = (cik, accession, quote) that states
# the outcome (and the average, if `avg` is given). `wev` cites the window dates
# where the outcome quote does not. `pr` = final (or preliminary, flagged) pro-ration.
def W(pid, tk, start, end, outcome, ev=None, avg=None, wev=None, pr=None, pr_ev=None, note=""):
    return dict(pid=pid, ticker=tk, start=start, end=end, outcome=outcome, ev=ev, avg=avg,
                wev=wev, proration_pct=pr, pr_ev=pr_ev, note=note)


WINDOWS = [
    W("WA-GFY-2009", "GFY", "2010-01-12", "2010-04-01", "triggered", avg=-10.03,
      wev=(1299393, "0001104659-10-001377", "the Fund has commenced a “Measuring Period” to determine whether to proceed with a tender offer"),
      ev=(1299393, "0001104659-10-021765", "At the end of the Measurement Period on April 1, 2010, the average discount to the net asset value was 10.03% per Share"),
      pr=35.487, pr_ev=(1299393, "0001104659-10-031822", "35.487% of shares for each stockholder who properly tendered shares have been accepted")),
    # Neuberger Berman 2009 programme, windows 2-4 (window 1 was in 2009, out of scope)
    W("NB-2009", "NRO", "2010-02-19", "2010-05-14", "triggered", avg=-10.20,
      ev=(1261166, "0000898432-10-000724", "traded at an average daily discount to NAV of 10.20% for the Measurement Period"),
      wev=(1178839, "0000898432-10-000179", "shall commence on February 19, 2010 and end on May 14, 2010")),
    *[W("NB-2009", tk, "2010-02-19", "2010-05-14", "not_triggered",
        ev=(1261166, "0000898432-10-000724", "each of NBH, NBO and NBW traded at an average daily discount to NAV of less than 10%"))
      for tk in ("NBH", "NBO", "NBW")],
    W("NB-2009", "NRO", "2010-08-18", "2010-11-10", "triggered", avg=-10.30,
      ev=(1261166, "0000898432-10-001439", "NRO traded at an average daily discount to NAV of 10.30% for the Measurement Period"),
      wev=(1178839, "0000898432-10-001127", "shall commence on August 18, 2010 and end on November 10, 2010")),
    *[W("NB-2009", tk, "2010-08-18", "2010-11-10", "not_triggered",
        ev=(1261166, "0000898432-10-001439", "each of NHS, NBH, NBO and NBW traded at an average daily discount to NAV of less than 10%"))
      for tk in ("NHS", "NBH", "NBO", "NBW")],
    W("NB-2009", "NRO", "2011-07-11", "2011-10-04", "triggered", avg=-11.04,
      ev=(1261166, "0000898432-11-001115", "its average daily discount to NAV was 11.04% for the Measurement Period"),
      wev=(1178839, "0000898432-11-000717", "shall commence on July 11, 2011 and end on October 4, 2011")),
    *[W("NB-2009", tk, "2011-07-11", "2011-10-04", "not_triggered",
        ev=(1261166, "0000898432-11-001115", "each of NBH, NBO and NBW traded at an average daily discount to NAV of less than 10%"))
      for tk in ("NBH", "NBO", "NBW")],
    W("NB-2009", "NHS", "2011-07-11", "2011-10-04", "not_triggered",
      ev=(1261166, "0000898432-11-001115", "NHS traded at an average daily premium to NAV")),
    W("NB-2009", "NHS", "2012-04-23", "2012-07-16", "not_triggered_inferred",
      wev=(1487610, "0000898432-12-000503", "shall commence on April 23, 2012 and end on July 16, 2012")),
    # NRO 2016 conditional, then the 2017 programme
    W("NB-NRO-2016", "NRO", "2015-12-31", "2016-09-30", "triggered", avg=-11.80,
      ev=(1261166, "0000898432-16-003018", "the Fund’s average daily discount to NAV for the Measurement Period was 11.80%")),
    W("NB-NRO-2016", "NRO", "2017-01-03", "2017-03-28", "not_triggered_inferred",
      wev=(1261166, "0000898432-17-000001", "will commence on January 3, 2017 and end on March 28, 2017")),
    W("NB-NRO-2016", "NRO", "2017-07-10", "2017-10-02", "not_triggered", avg=-6.99,
      wev=(1261166, "0000898432-17-000688", "will commence on Monday, July 10, 2017 and end on Monday, October 2, 2017"),
      ev=(1261166, "0000898432-17-000968", "traded at an average daily discount to net asset value per share of -6.99%")),
    # DWS 2010 programme
    W("DWS-2010", "EEA", "2010-09-01", "2010-11-24", "triggered", avg=-10.02,
      ev=(791718, "0000950123-11-001521", "began on September 1, 2010 and concluded on November 24, 2010, shares of common stock of the Fund traded at an average discount to net asset value of -10.02%"),
      pr=12.0, pr_ev=(791718, "0000088053-11-000233", "approximately 12% of the Fund’s shares that were tendered have been accepted for payment"),
      note="pro-ration stated as 'approximately 12%'"),
    W("DWS-2010", "GF", "2010-09-01", "2010-11-24", "not_triggered_inferred",
      note="GF's average is not stated; only EEA's tender was announced"),
    *[W("DWS-2010", tk, "2011-03-07", "2011-05-27", "not_triggered_inferred",
        wev=(791718, "0000088053-10-001697", "the next measurement period will commence on March 7, 2011 and will expire on May 27, 2011"))
      for tk in ("EEA", "GF")],
    W("DWS-2010", "EEA", "2012-03-05", "2012-05-25", "triggered", avg=-10.17,
      ev=(791718, "0000088053-12-000607", "EEA had traded at an average discount to net asset value (“NAV”) of -10.17%"),
      pr=9.95, pr_ev=(791718, "0000088053-12-000957", "9.95% of EEA’s shares, and 8.07% of GF’s shares")),
    W("DWS-2010", "GF", "2012-03-05", "2012-05-25", "triggered", avg=-10.51,
      ev=(791718, "0000088053-12-000607", "GF had traded at an average discount to NAV of -10.51 %"),
      pr=8.07, pr_ev=(791718, "0000088053-12-000957", "9.95% of EEA’s shares, and 8.07% of GF’s shares")),
    # DWS 2012 programme (EEA, GF, CEE)
    W("DWS-2012", "EEA", "2012-09-10", "2012-11-30", "not_triggered", avg=-9.79,
      wev=(791718, "0001193125-12-314459", "which will commence on Monday, September 10, 2012 and will expire on Friday, November 30, 2012"),
      ev=(860489, "0000088053-12-001308", "EEA had traded at an average discount to net asset value (“NAV”) of -9.79%")),
    W("DWS-2012", "GF", "2012-09-10", "2012-11-30", "not_triggered", avg=-9.90,
      wev=(858706, "0001193125-12-314461", "which will commence on Monday, September 10, 2012 and will expire on Friday, November 30, 2012"),
      ev=(860489, "0000088053-12-001308", "GF had traded at an average discount to NAV of -9.90%")),
    W("DWS-2012", "CEE", "2012-09-10", "2012-11-30", "triggered", avg=-10.18,
      ev=(860489, "0000088053-12-001308", "CEE had traded at an average discount to NAV of -10.18%"),
      pr=6.87, pr_ev=(860489, "0000088053-13-000296", "6.87% of the Fund’s shares that were tendered have been accepted")),
    W("DWS-2012", "CEE", "2013-03-25", "2013-06-14", "triggered", avg=-10.16,
      ev=(860489, "0000088053-13-000688", "CEE had traded at an average discount to net asset value (“NAV”) of -10.16%"),
      pr=6.99, pr_ev=(860489, "0000088053-13-001045", "6.99% of CEE’s shares and 8.08% of GF’s shares")),
    W("DWS-2012", "EEA", "2013-03-25", "2013-06-14", "not_triggered", avg=-9.93,
      ev=(860489, "0000088053-13-000688", "EEA had traded at an average discount to NAV of -9.93%")),
    W("DWS-2012", "GF", "2013-03-25", "2013-06-14", "triggered", avg=-10.77,
      ev=(860489, "0000088053-13-000688", "GF had traded at an average discount to NAV of -10.77%"),
      pr=8.08, pr_ev=(860489, "0000088053-13-001045", "6.99% of CEE’s shares and 8.08% of GF’s shares")),
    W("DWS-2012", "CEE", "2013-09-16", "2013-12-06", "triggered", avg=-10.36,
      ev=(860489, "0000088053-13-001397", "CEE had traded at an average discount to net asset value (“NAV”) of -10.36%"),
      pr=7.56, pr_ev=(860489, "0000088053-14-000309", "7.56% of the Fund’s shares that were tendered has been accepted")),
    W("DWS-2012", "EEA", "2013-09-16", "2013-12-06", "not_triggered", avg=-9.33,
      ev=(860489, "0000088053-13-001397", "EEA had traded at an average discount to NAV of -9.33%")),
    W("DWS-2012", "GF", "2013-09-16", "2013-12-06", "not_triggered", avg=-9.06,
      ev=(860489, "0000088053-13-001397", "GF had traded at an average discount to NAV of –9.06%")),
    W("DWS-2012", "CEE", "2014-04-07", "2014-06-27", "triggered", avg=-10.15,
      ev=(860489, "0000088053-14-000856", "CEE had traded at an average discount to net asset value (“NAV”) of -10.15%"),
      pr=7.33, pr_ev=(860489, "0000088053-14-001249", "7.33% of the Fund’s shares that were tendered has been accepted")),
    W("DWS-2012", "EEA", "2014-04-07", "2014-06-27", "not_triggered", avg=-9.9996888,
      ev=(860489, "0000088053-14-000856", "EEA had traded at an average discount to NAV of just under 10.00% (-9.9996888%)"),
      note="missed the 10% trigger by 0.0003 percentage points"),
    W("DWS-2012", "GF", "2014-04-07", "2014-06-27", "not_triggered", avg=-9.98,
      ev=(860489, "0000088053-14-000856", "GF had traded at an average discount to NAV of -9.98%")),
    # DWS 2014: one 15-week window per fund
    W("DWS-2014", "EEA", "2014-09-02", "2014-12-12", "triggered", avg=-10.93,
      ev=(791718, "0000088053-14-001619", "EEA had traded at an average discount to NAV of -10.93%"),
      pr=10.51, pr_ev=(791718, "0000088053-15-000224", "10.51% of the Fund’s shares that were tendered has been accepted")),
    W("DWS-2014", "GF", "2014-09-02", "2014-12-12", "not_triggered", avg=-8.99,
      ev=(791718, "0000088053-14-001619", "GF had traded at an average discount to NAV of -8.99%")),
    W("DWS-2014", "CEE", "2015-01-12", "2015-04-24", "triggered", avg=-10.01,
      ev=(860489, "0000088053-15-000427", "shares of common stock of the Fund had traded at an average discount to NAV of -10.01%"),
      pr=7.49, pr_ev=(860489, "0000088053-15-000811", "7.49% of the Fund’s shares that were tendered has been accepted")),
    # Morgan Stanley 2011 amended policy
    W("MS-2011", "APF", "2011-07-11", "2011-09-30", "triggered", avg=-11.20,
      wev=(919808, "0001104659-11-019349", "The first 12-week measurement period under the amended Policy will commence July 11, 2011"),
      ev=(919808, "0001104659-11-055103", "For the 12-week measurement period ended September 30, 2011, shares of the Fund traded at an average daily discount to NAV of 11.20%"),
      pr=9.93, pr_ev=(919808, "0001104659-11-064180", "the pro-ration for each tendering stockholder is estimated to be 9.93 percent"), note="pro-ration preliminary"),
    W("MS-2011", "APF", "2012-01-09", "2012-03-30", "triggered", avg=-10.44,
      ev=(919808, "0001104659-12-033676", "For the 12-week measurement period ended March 30, 2012, shares of the Fund traded at an average daily discount to NAV of 10.44 percent"),
      wev=(919808, "0001104659-11-056263", "will commence on January 9, 2012"),
      pr=9.39, pr_ev=(919808, "0001104659-12-043856", "the pro-ration for each tendering stockholder is estimated to be 9.39 percent"), note="pro-ration preliminary"),
    W("MS-2011", "APF", "2012-07-09", "2012-09-28", "triggered", avg=-11.12,
      ev=(919808, "0001104659-12-067941", "For the 12-week measurement period ended September 28, 2012, shares of the Fund traded at an average daily discount to NAV of 11.12 percent"),
      wev=(919808, "0001104659-12-038043", "will commence on July 9, 2012"),
      pr=9.33, pr_ev=(919808, "0001104659-12-078906", "the pro-ration for each tendering stockholder is estimated to be 9.33 percent"), note="pro-ration preliminary"),
    W("MS-2011", "APF", "2013-01-07", "2013-03-28", "triggered", avg=-10.85,
      ev=(919808, "0001104659-13-040826", "For the 12-week measurement period ended March 28, 2013, shares of the Fund traded at an average daily discount to NAV of 10.85%"),
      wev=(919808, "0001104659-12-070146", "will commence on January 7, 2013"),
      pr=6.38, pr_ev=(919808, "0001104659-13-048373", "the pro-ration for each tendering stockholder is estimated to be 6.38 percent"), note="pro-ration preliminary"),
    W("MS-2011", "MF", "2011-07-11", "2011-09-30", "triggered", avg=-10.06,
      wev=(811797, "0001104659-11-027753", "The next 12-week measurement period under the amended discount management program will commence on July 11, 2011"),
      ev=(811797, "0001104659-11-055102", "traded at an average daily discount to NAV of 10.06%"),
      pr=18.75, pr_ev=(811797, "0001104659-11-066508", "the pro-ration for each tendering stockholder is estimated to be 18.75 percent"), note="pro-ration preliminary"),
    W("MS-2011", "MF", "2012-01-09", None, "unknown",
      wev=(811797, "0001104659-11-056264", "will commence on January 9, 2012"),
      note="no later filing by the fund in the 2008+ index; end date not stated"),
    # Swiss Helvetia 2011
    W("SWZ-2011", "SWZ", "2011-03-01", "2011-05-24", "triggered", avg=-10.23,
      ev=(813623, "0001193125-11-149954", "which began on March 1, 2011 and concluded on May 24, 2011, the Fund’s shares traded at an average discount to NAV of 10.23%"),
      pr=10.16, pr_ev=(813623, "0001193125-11-183848", "approximately 10.16% of the Fund’s shares that were tendered were accepted")),
    W("SWZ-2011", "SWZ", "2011-08-01", None, "not_triggered_inferred",
      wev=(813623, "0001193125-11-183848", "moving up the start date of the second measurement period from September 1, 2011 to August 1, 2011"),
      note="a twelve-week window; end date not stated"),
    # LMP Capital & Income: three 30-day windows, all followed by a tender
    *[W("LMP-SCD-2011", "SCD", s, e, "triggered", ev=(1270131, acc, q))
      for s, e, acc, q in (
          ("2011-07-20", "2011-08-19", "0001193125-11-228834", "average daily discount from net asset value of more than 5% during a July 20th to August 19th measuring period"),
          ("2011-10-19", "2011-11-18", "0001193125-11-321001", "during an October 19, 2011 to November 18, 2011 measuring period"),
          ("2012-01-19", "2012-02-18", "0001193125-12-070630", "during a January 19, 2012 to February 18, 2012 measuring period"))],
    W("NOMURA-KEF-2011", "KEF", "2011-07-01", "2011-09-30", "triggered",
      ev=(912023, "0000905148-12-000209", "The Fund’s shares traded at such a discount")),
    W("GCH-2011", "GCH", "2011-07-01", "2011-09-16", "superseded",
      ev=(887546, "0001193125-11-236597", "with the first period commencing on July 1, 2011 and being scheduled to end on September 16, 2011"),
      note="replaced mid-window by a one-time unconditional tender for 20%"),
    *[W("SUNAMERICA-2010", tk, None, None, "superseded",
        note="no window dates found; the fund filed N-8F (deregistration) on 2012-03-07") for tk in ("FGF", "FGI")],
    W("MACQ-MGU-2012", "MGU", "2013-01-15", "2013-02-12", "triggered",
      ev=(1326390, "0001193125-13-077364", "Both of these conditions have been met")),
    W("IRL-2012", "IRL", "2013-01-01", "2013-03-31", "not_triggered_inferred",
      note="hybrid: also needed more than 50% take-up in the 2012 tender; which leg failed is not stated"),
    *[W("EV-ETJ-2013", "ETJ", s, e, "not_triggered_inferred",
        wev=(1395325, "0000940394-13-001309", "averages more than 9.75% for any of the months of February, March, April or May 2014"))
      for s, e in (("2014-02-01", "2014-02-28"), ("2014-03-01", "2014-03-31"), ("2014-04-01", "2014-04-30"), ("2014-05-01", "2014-05-31"))],
    W("NUV-DRA-2014", "DRA", "2015-07-10", "2015-10-07", "triggered", avg=-10.91,
      ev=(1598085, "0001193125-15-340936", "The fund’s shares traded at an average daily discount to NAV of -10.91 percent during the measurement period")),
    # Zweig 2016 (Karpus): conditional tenders #2 and #3
    W("ZWEIG-2016", "ZTR", None, None, "triggered",
      ev=(836412, "0001571049-17-002592", "This tender offer follows tender offers that were completed in May and December 2016 for 15 percent and 5 percent"),
      note="conditional tender #2: window = first 12 full calendar weeks after tender #1 (closed May 2016); dates not stated"),
    W("ZWEIG-2016", "ZTR", None, "2017-03-17", "triggered",
      ev=(836412, "0001571049-17-002592", "That condition was met as of March 17, 2017"),
      note="conditional tender #3; 12-week window ending 2017-03-17"),
    W("ZWEIG-2016", "ZF", None, None, "triggered",
      ev=(812090, "0001571049-16-020850", "the pro-ration for each tendering stockholder is estimated to be 14.4967 percent"),
      note="conditional tender #2 was conducted (Nov-Dec 2016); window dates not stated"),
    W("ZWEIG-2016", "ZF", None, None, "superseded",
      ev=(1310445, "0001571049-16-018120", "the shareholders of ZF will be asked to approve the reorganization of ZF into DCA"),
      note="conditional tender #3 overtaken by ZF's merger into DCA"),
    W("ZWEIG-DCA-2016", "DCA", None, None, "unknown", note="the conditional tender's terms and outcome were not found"),
    W("MFS-CXH-2017", "CXH", None, "2018-03-09", "triggered",
      ev=(847411, "0001193125-18-079336", "That condition was met as of March 9, 2018, the end of the 90-day period"),
      pr=22.7, pr_ev=(847411, "0001193125-18-150833", "estimated to be approximately 22.7 percent"), note="pro-ration preliminary"),
    W("BLK-DSU-2017", "DSU", "2017-12-01", "2018-02-28", "triggered", avg=-8.5,
      ev=(1051003, "0001341004-18-000162", "The Fund's average daily discount to NAV during the First Measurement Period was 8.5%")),
    W("BLK-DSU-2017", "DSU", "2018-12-01", "2019-02-28", "triggered", avg=-12.9,
      ev=(1051003, "0001193125-19-061173", "During the Second Measurement Period, the Fund’s average daily discount to NAV was -12.9%")),
    W("BLK-DSU-2017", "DSU", "2019-12-02", "2020-02-28", "triggered", avg=-8.5,
      ev=(1051003, "0001193125-20-059161", "During the Third Measurement Period, the Fund’s average daily discount to NAV was 8.5%")),
    # Delaware standing policies: only the years a tender followed are documented
    *[W("DEL-DDF-STANDING", "DDF", None, None, "triggered", ev=(896923, acc, "Those conditions have been met"),
        note=f"{yr}: window end is a board-designated Q2 date, not stated")
      for yr, acc in ((2014, "0001206774-14-001854"), (2016, "0001206774-16-006118"), (2017, "0001206774-17-001757"))],
    W("DEL-DGF-STANDING", "DGF", None, None, "triggered", ev=(916713, "0001206774-11-001319", "Those conditions have been met"),
      note="2011: window end is a board-designated Q2 date, not stated"),
    *[W("DEL-DEX-2018", "DEX", None, None, "triggered", ev=(1396167, acc, "Those conditions have been met"),
        note=f"{yr}: window end is a board-designated Q2 date, not stated")
      for yr, acc in ((2019, "0001206774-19-001806"), (2021, "0001206774-21-001537"), (2022, "0001206774-22-001460"))],
    W("DEL-DEX-2018", "DEX", "2020-01-01", "2020-06-30", "not_triggered_inferred",
      note="2020: the board-designated window is not stated; dates are the calendar half-year that contains it"),
    W("NUV-NBB-2018", "NBB", "2018-12-14", "2018-12-28", "triggered", avg=-7.97,
      ev=(1478888, "0001193125-19-000838", "the fund’s shares traded at an average daily discount to NAV of -7.97 percent")),
    W("ABRDN-AEF-2018", "AEF", "2018-04-30", "2019-04-30", "triggered", avg=-11.55,
      ev=(846676, "0001104659-19-027846", "For the period from April 30, 2018 through April 30, 2019, the Fund’s average discount to NAV was 11.55%")),
    W("EV-EIM-2019", "EIM", "2019-06-04", "2019-10-01", "triggered",
      ev=(1176984, "0000940394-19-001307", "during a 120-day period that commenced on June 4, 2019 and ended on October 1, 2019")),
    W("EV-EIM-2019", "EIM", "2020-01-22", "2020-05-20", "triggered",
      ev=(1176984, "0000940394-20-000961", "during a 120-day period that commenced on January 22, 2020 and ended on May 20, 2020")),
    W("HERZ-2019", "CUBA", "2019-07-01", "2020-06-30", "suspended",
      ev=(880406, "0001398344-20-024710", "The Self-Tender Policy component of the Plan was suspended by the Board as announced on June 5, 2020")),
    W("HERZ-2019", "CUBA", "2020-07-01", "2021-06-30", "triggered",
      ev=(880406, "0001398344-21-016620", "The average discount for the fiscal year ended June 30, 2021 exceeded the 10% threshold")),
    W("HERZ-2019", "CUBA", "2021-07-01", "2022-06-30", "triggered_inferred",
      ev=(880406, "0001387131-22-010233", "if the average discount was greater than 10% for the fiscal year just ended")),
    W("HERZ-2019", "CUBA", "2022-07-01", "2023-06-30", "triggered",
      ev=(880406, "0001999371-23-000497", "As the average discount for the fiscal year ending June 30, 2023 exceeded 10%")),
    W("HERZ-2019", "CUBA", "2023-07-01", "2024-06-30", "triggered_inferred",
      ev=(880406, "0001999371-24-012904", "has undertaken to commence a tender offer by October 31, 2024")),
    W("HERZ-2019", "CUBA", "2024-07-01", "2025-06-30", "triggered_inferred",
      ev=(880406, "0001999371-25-011966", "has undertaken to commence a tender offer by October 31, 2025")),
    W("HERZ-2019", "CUBA", "2025-07-01", "2026-06-30", "triggered_inferred",
      ev=(880406, "0001398344-26-016904", "has undertaken to commence a tender offer by October 31, 2026")),
    # Eaton Vance 2021: January-August windows
    *[W("EV-2021", tk, "2022-01-01", "2022-08-31", "not_triggered_inferred") for tk in ("EFT", "EFR", "EVF")],
    *[W("EV-2021", tk, "2023-01-01", "2023-08-31", "triggered",
        ev=(1288992, "0000940394-23-001020", "it has been determined that the conditions precedent to a cash tender in the fourth quarter of 2023 have been met for each Fund"))
      for tk in ("EFT", "EVF")],
    W("EV-2021", "EFR", "2023-01-01", "2023-08-31", "not_triggered_inferred"),
    W("EV-2021", "EFT", "2024-01-01", "2024-08-31", "not_triggered",
      ev=(1288992, "0001193125-26-317148", "The condition to trigger a tender offer by the Trust in the fourth quarter of 2024 was not met")),
    *[W("EV-2021", tk, "2024-01-01", "2024-08-31", "not_triggered_inferred") for tk in ("EFR", "EVF")],
    W("FT-GIM-2021", "GIM", None, None, "withdrawn",
      ev=(828803, "0001137439-21-001003", "the Board formally withdrew the previously announced tender offer measurement period"),
      note="the fund said its average was below 8% to date when it withdrew the window"),
    *[W("TORT-2022", tk, None, "2022-07-31", "triggered",
        ev=(1268533, "0001140361-22-030648", "The first measurement period for 2022 ended on July 31, 2022 and it has been determined that a tender offer will be executed in each fund"),
        note="first window: start date not found")
      for tk in ("TYG", "NTG", "TTP", "NDP", "TPZ")],
    *[W("TORT-2022", tk, "2022-08-01", "2023-07-31", "triggered",
        ev=(1268533, "0001140361-23-040066", "The measurement period for 2023 ended on July 31, 2023 and it has been determined that a tender offer will be executed in each Fund"))
      for tk in ("TYG", "NTG", "TTP", "NDP", "TPZ")],
    *[W("BLK-2025E", tk, "2025-01-01", "2025-09-30", "not_triggered",
        ev=(1809541 if tk in ("BCAT", "ECAT") else 1320375,
            "0001193125-26-093580" if tk in ("BCAT", "ECAT") else "0001193125-26-093621",
            "The discount trigger was not met and therefore no tender offers were conducted with respect to this measurement period"))
      for tk in ("BCAT", "ECAT", "BSTZ", "BOE", "BGR", "BGY", "CII", "BDJ", "BST", "BME", "BCX", "BUI")],
    W("BLK-BKT-2025", "BKT", "2025-07-09", "2025-09-30", "not_triggered",
      ev=(832327, "0001193125-26-093646", "The discount trigger was not met and therefore no tender offer was conducted")),
    W("BLK-BKT-2026", "BKT", "2026-07-09", "2026-09-30", "unknown",
      note="window ended 2026-09-30; no result filing in the index read (last filing date 2026-10-09)"),
    W("ZTR-2024", "ZTR", "2024-05-31", "2024-11-26", "triggered", avg=-12.51,
      ev=(836412, "0001193125-24-284229", "The average trading discount during this measurement period was 12.51%"),
      pr=30.53, pr_ev=(836412, "0001193125-25-024907", "approximately 30.53% of the shares tendered")),
    W("ZTR-2024", "ZTR", "2025-04-01", "2025-09-26", "triggered", avg=-11.41,
      ev=(836412, "0001193125-25-229427", "The average trading discount during this measurement period was 11.41%"),
      pr=37.25, pr_ev=(836412, "0001193125-25-311337", "approximately 37.25% of the shares tendered"),
      note="second window: threshold 10%"),
    W("EV-EIM-2024", "EIM", "2024-07-09", "2024-11-08", "triggered",
      ev=(1176984, "0000940394-24-001035", "The Fund has determined that the conditions of the First Trigger Event have been met")),
    W("EV-EIM-2024", "EIM", "2025-03-10", "2025-07-09", "triggered",
      ev=(1176984, "0001076598-25-000273", "The Fund has determined that the conditions of the Trigger Event have been met")),
    W("JOF-2025", "JOF", "2025-07-01", "2026-03-31", "triggered", avg=-10.5,
      ev=(859796, "0001140361-26-023437", "traded at an average daily market price discount of 10.5% to the Fund’s net asset value during such nine-month period"),
      pr=12.87958, pr_ev=(859796, "0001140361-26-028294", "approximately 12.87958% of the shares tendered")),
]

# Window thresholds that differ from the programme's.
WINDOW_THRESHOLD = {("ZTR-2024", "2025-09-26"): 10.0}

# --------------------------------------------- BlackRock tables, parsed not typed
# (pid, window start, window end, cik, accession). Every row of the table becomes
# a window for that pid; `pid_of` routes a ticker to a pid where one table serves
# several programmes (the 2026 table lists the equity renewal and both muni groups).
TABLES = [
    ("BLK-2024Q", "2024-04-01", "2024-06-30", 835948, "0001193125-24-173637"),
    ("BLK-2024Q", "2024-07-01", "2024-09-30", 835948, "0001193125-24-230317"),
    ("BLK-2024Q", "2024-10-01", "2024-12-31", 835948, "0001193125-25-000824"),
    ("BLK-2024Q", "2025-01-01", "2025-03-31", 835948, "0001193125-25-070678"),
    ("BLK-2024Q", "2025-04-01", "2025-06-30", 835948, "0001193125-25-154060"),
    ("BLK-2026", "2026-01-01", "2026-09-30", 1785971, "0001193125-26-410845"),
]
BLK_2026_ROUTE = {"MHD": "BLK-2026M-FEB09", "MYN": "BLK-2026M-FEB09", "MUC": "BLK-2026M-FEB09",
                  "MQY": "BLK-2026M-FEB23", "MYI": "BLK-2026M-FEB23", "MUA": "BLK-2026M-FEB23"}  # else BLK-2026E
BLK_CIK = {"BCAT": 1809541, "ECAT": 1864843, "BIGZ": 1836057, "BMEZ": 1785971, "BSTZ": 1768666, "BOE": 1320375,
           "BGR": 1306550, "BGY": 1393299, "CII": 1278895, "BDJ": 1332283, "BST": 1616678, "BME": 1314966,
           "BCX": 1506289, "MVF": 835948, "BUI": 1528988, "MHD": 1034665, "MYN": 882150, "MUC": 1051004,
           "MQY": 890196, "MUA": 901243, "MYI": 883412}
# Table outcomes that a later filing overrode.
BLK_OVERRIDES = {
    ("BIGZ", "2024-12-31"): ("triggered_cancelled", (1836057, "0001193125-25-009580",
        "the cancellation of the applicable Fund’s tender offer for the quarterly measurement period ended December 31, 2024")),
    ("BMEZ", "2024-12-31"): ("triggered_cancelled", (1785971, "0001193125-25-009582",
        "the cancellation of the applicable Fund’s tender offer for the quarterly measurement period ended December 31, 2024")),
}
# MVF's sixth quarter had no table: the obligation was waived in advance (merger into MYI).
EXTRA_BLK_WINDOWS = [
    W("BLK-2024Q", "MVF", "2025-07-01", "2025-09-30", "waived",
      ev=(835948, "0001193125-25-159395", "Each Party hereby waives compliance of the Fund’s obligation to commence the Sixth Conditional Tender Offer")),
]
# Panel tickers where the fund's ticker changed (BIGZ became BTX, EDGAR name change 2025-02-18).
PANEL_TICKER = {"BIGZ": "BTX", "CUBA": "HERZ"}

# ------------------------------------------------------------------ exclusions
# Every CIK the discovery scan flagged that is NOT in the census, with the reason.
EXCLUDED = {
    748691: "KF: 2017 tender unconditional; the 2020 policy is triggered by NAV performance against a benchmark",
    804123: "TWN: discount policy triggers open-market repurchases (9% on a 5-day average), not a tender",
    845379: "CHN: discount policy triggers open-market repurchases (8%; later confidential levels), not a tender",
    917100: "IFN 2013: tender conditional on a stockholder vote; the 10% 'targeted discount' commits to no action",
    864415: "Singapore Fund 2012: above a 9% quarterly average the board 'would consider' measures; no committed tender",
    866095: "JEQ 2025: tender conditional on a reorganisation",
    1368493: "CAF: NAV-performance trigger plus a point-in-time at-or-below-NAV test; no average-discount window",
    1514490: "RGT 2020: tender conditional on an advisory-agreement vote",
    1287498: "EVG 2021: tender conditional on an advisory-agreement vote",
    1074685: "EVY 2021: tender conditional on an advisory-agreement vote",
    1288795: "GLV 2017: unconditional tender within a 'discount management program'",
    1316463: "GLQ 2017: unconditional tender within a 'discount management program'",
    1350869: "GLO 2017: unconditional tender within a 'discount management program'",
    1011006: "Yahoo/Altaba: 'conditional tender' is Dutch-auction mechanics; not a discount trigger",
    1099941: "MVC Capital (BDC): Dutch-auction 'conditional tender' mechanics",
    1141299: "MCG Capital (BDC): Dutch-auction 'conditional tender' mechanics",
    1379785: "Barings BDC: Dutch-auction 'conditional tender' mechanics",
    1634452: "AB Private Credit Investors (non-traded BDC): 'conditional tender' boilerplate",
    1509470: "SuRo Capital (BDC): Dutch-auction 'conditional tender' mechanics",
    1464963: "THL Credit (BDC): Dutch-auction 'conditional tender' mechanics",
    1817825: "Steele Creek Capital (non-traded BDC): 'conditional tender' boilerplate",
    1786835: "Star Mountain (non-traded BDC): 'conditional tender' boilerplate",
    1521945: "TP Flexible Income (non-traded): 'conditional tender' boilerplate",
    1356115: "NexPoint Strategic Opportunities 2020: Dutch-auction exchange offer mechanics",
    1495584: "Firsthand Technology Value (BDC): transfer-agent fee schedule mentions conditional tenders",
    1675033: "Great Elm Capital (BDC) 2017: Dutch-auction 'conditional tender' mechanics",
}
# Found outside the scan and not admitted, with the reason.
EXCLUDED_OTHER = {
    "MXF 2026": "a June 2026 conditional tender is described only by a commentary site; no EDGAR filing found (submissions API, 2026-10-13)",
    "WIA 2020": "Karpus standstill with an unconditional 20% tender (SC TO-I 2020-11-25)",
    "CXH 2023": "Bulldog standstill: the discount trigger (7.5% for any 30 days) decides a liquidity-event PROPOSAL, not a tender",
    "BMEZ/BTX 2025": "Saba settlements (2025-01-20): unconditional tenders at 99.5% of NAV",
}
