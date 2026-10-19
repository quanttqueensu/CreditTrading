"""SPAC mechanics as read from the declared sample's filings: every fact carries its quote.

WHY THIS IS A HAND-CODED TABLE (and why that is not a hand-copied series)
-----------------------------------------------------------------------
The census (`spac_trust_census.py`) measures counts, prices and trust levels
by rule. The MECHANICS (who may redeem, when, through what, at what fee, what
the trust may hold, what comes out of it before a holder is paid) are legal
text that no regex reads reliably, so a reader read them on 2026-10-15 and
coded each fact here WITH the quote that states it. `spac_trust_census.
verify_mechanics` fetches every cited document through the EDGAR client
(cache first) and RAISES if a quote is not in it after whitespace, case,
quote-mark and dash normalisation. A quote that carries a number is only
coded if the number is in the quote, so a mistyped figure fails the run.

THE SAMPLE WAS DECLARED BEFORE ANY OF IT WAS READ (2026-10-15)
-------------------------------------------------------------
Order: sha256("spac-census-2026-10-15:<cik>"), `spac_trust_census.declared_order`.
  * 6 live SPACs with an Alpaca-tradable common, first in that order;
  * 3 SPACs that completed a deal before 2023-01-01, first in that order;
  * 3 SPACs that liquidated (delisted) before 2023-01-01, first in that order;
  * for extensions, which the 12 above barely touch (the live six are 2025-26
    IPOs that have not reached a deadline): the first 4 in that order among
    SPACs with at least one text-confirmed extension-vote 8-K.
`spac_trust_census.declared_sample` recomputes the draw; the census raises if
a CIK coded below is not in it.

ONE DISCLOSED CHANGE TO THE DRAW (2026-10-15). The extension draw depends on
which 8-Ks the text rule confirms as extension votes. Its first run admitted
Cerberus Telecom (CIK 1824577), whose 8-K was a DEAL vote that only mentioned
"the potential failure to obtain an extension"; reading it showed the rule was
wrong, the rule was tightened (`EXTENSION_RE`), and the redrawn four are
CHP, Iron Horse, Zalatoris II and Aurora/Better Home. The rule changed because
it misclassified, not because of what the drawn SPAC said; Cerberus stays in
the sample as a completed SPAC (it is also first in the completed draw).

The successor reader (2026-10-18) kept the draw and added quotes from the two
members that had none (Maywood 2, the live six's fifth; Social Capital
Hedosophia IV, a liquidated member), and the trust deposit per unit.

Each entry: cik, accession, doc (the primary document), field, quote.
"""
from __future__ import annotations

# ------------------------------------------------------------- prospectuses (424B4)

RRE = (2123969, "0001193125-26-199374", "d114015d424b4.htm")       # RRE Ventures Acquisition Corp. (2026)
JATT2 = (2112446, "0001213900-26-044954", "ea0286555-424b4_jatt2acq.htm")   # JATT II Acquisition Corp. (2026)
IPFX = (2102041, "0001213900-26-035878", "ea0270234-07.htm")       # Inflection Point Acquisition Corp. VI (2026)
BCSS = (2064355, "0001193125-25-225161", "d947702d424b4.htm")       # Bain Capital GSS Investment Corp. (2025)
MYX = (2080087, "0001477932-26-002206", "mayau_424b4.htm")          # Maywood Acquisition Corp. 2 (2026)
BLUW = (2050501, "0001641172-25-014598", "form424b4.htm")           # Blue Water Acquisition Corp. III (2025)
KING = (1824577, "0001193125-20-275511", "d60143d424b4.htm")        # completed 2021 (now "KING LLC MERGER SUB")
CHASERG = (1743725, "0001213900-18-013601", "f424b4100418_chaserg.htm")    # ChaSerg (Grid Dynamics), completed 2020
IPV = (1789029, "0001213900-20-002614", "f424b40120_interprivate.htm")    # InterPrivate (Aeva), completed 2021
CHP = (1785041, "0001140361-19-021348", "nt10004133x13_424b4.htm")  # CHP Merger Corp., liquidated 2022

MECHANICS = [
    # -- the trust per share at the IPO (added 2026-10-18)
    dict(src=RRE, field="trust_per_unit", quote="$250.0 million, or $287.5 million if the underwriter’s overallotment option is exercised in full ($10.00 per unit in either case), will be placed into a U.S.-based trust account with Continental Stock Transfer & Trust Company acting as trustee"),
    dict(src=KING, field="trust_per_unit", quote="$250,000,000, or $287,500,000 if the underwriters’ over-allotment option is exercised in full ($10.00 per unit in either case), will be deposited into a U.S. based trust account at J.P. Morgan Chase Bank, N.A. with Continental Stock Transfer & Trust Company acting as trustee"),
    # -- the deadline, and what happens at it
    dict(src=RRE, field="deadline", quote="We have until the date that is 24 months from the closing of this offering or until such earlier liquidation date as our board of directors may approve, to consummate our initial business combination."),
    dict(src=BCSS, field="deadline_auto_extension", quote="24 months from the closing of this offering (or 27 months from the closing of this offering if we have executed a letter of intent, agreement in principle or definitive agreement for our initial business combination within 24 months from the closing of this offering"),
    dict(src=JATT2, field="deadline_by_amendment", quote="We will have (i) 24 months from the closing of this offering or such earlier date as our board of directors may approve, or (ii) such other time period pursuant to an amendment to our articles to complete our initial business combination"),
    dict(src=CHASERG, field="deadline", quote="If we are unable to complete our initial business combination within 18 months from the closing of this offering, we will redeem 100% of the public shares for cash"),
    dict(src=IPV, field="deadline", quote="If we are unable to consummate an initial business combination within 21 months from the closing of this offering, we will redeem 100% of the public shares for a pro rata portion of the trust account"),
    dict(src=KING, field="deadline", quote="If we have not consummated an initial business combination within 24 months from the closing of this offering, we will redeem 100% of the public shares for cash"),
    dict(src=RRE, field="liquidation_amount", quote="we will redeem 100% of the public shares at a per share price, payable in cash, equal to the aggregate amount then on deposit in the trust account, including interest earned thereon (which interest shall be net of taxes payable and up to $100,000 of interest to pay dissolution expenses)"),
    dict(src=BLUW, field="liquidation_amount", quote="net of amounts withdrawn to pay our taxes (but without deduction for any excise or similar tax that may be due or payable) and up to $100,000 of interest income to pay dissolution expenses"),
    dict(src=BCSS, field="liquidation_timing", quote="redeem the public shares, at a per-share price, payable in cash, equal to the aggregate amount then on deposit in the trust account, including interest earned on the funds held in the trust account and not previously released to us for permitted withdrawals (less up to $100,000 of interest to pay dissolution expenses)"),
    # -- the deal-vote redemption price
    dict(src=RRE, field="deal_redemption_amount", quote="equal to the aggregate amount then on deposit in the trust account described below as of two business days prior to the consummation of our initial business combination"),
    dict(src=IPFX, field="working_capital_withdrawals", quote="net of amounts withdrawn to fund our working capital requirements, subject to an annual limit of $500,000 (plus the rollover of unused amounts from prior years)"),
    # -- what the trust may hold
    dict(src=RRE, field="trust_investments", quote="initially be invested only in cash, U.S. government treasury obligations with a maturity of 185 days or less, or in money market funds meeting certain conditions under Rule 2a-7"),
    dict(src=JATT2, field="trust_investments", quote="held only (i) uninvested as cash, (ii) in an interest-bearing or non-interest bearing demand deposit account at a U.S. chartered commercial bank with consolidated assets of $100 billion or more"),
    # -- who may redeem: no vote needed, no record-date holding needed
    dict(src=RRE, field="record_date", quote="or whether they were a public shareholder on the record date for the general meeting held to approve the proposed transaction"),
    dict(src=JATT2, field="record_date", quote="regardless of whether they hold public shares on the record date established in connection with our initial business combination"),
    dict(src=CHP, field="vote_not_needed", quote="Each public stockholder may elect to redeem their public shares without voting, and if they do vote, irrespective of whether they vote for or against the proposed transaction."),
    dict(src=CHP, field="net_tangible_assets_limit", quote="we will only redeem our public shares so long as (after such redemptions) our net tangible assets will be at least $5,000,001"),
    # -- how much one holder may redeem
    dict(src=RRE, field="holder_cap", quote="will be restricted from redeeming its shares with respect to more than an aggregate of 15% of the shares sold in this offering without our prior consent"),
    dict(src=JATT2, field="holder_cap", quote="will be restricted from redeeming its public shares with respect to more than an aggregate of 20% of the public shares sold in this offering, without our prior consent"),
    # -- how a holder redeems, and what the transfer agent charges
    dict(src=RRE, field="procedure", quote="deliver their shares to our transfer agent electronically using the Depository Trust Company’s DWAC (Deposit/Withdrawal At Custodian) system, prior to the date set forth in the proxy materials or tender offer documents, as applicable. In the case of proxy materials, this date may be up to two business days prior to the scheduled vote on the proposal to approve the initial business combination."),
    dict(src=RRE, field="transfer_agent_fee", quote="The transfer agent will typically charge the broker submitting or tendering shares a fee of approximately $100 and it would be up to the broker whether or not to pass this cost on to the redeeming holder."),
    dict(src=BCSS, field="transfer_agent_fee", quote="The transfer agent will typically charge the tendering broker a fee of approximately $80.00 and it would be up to the broker whether or not to pass this cost on to the redeeming holder."),
    dict(src=CHASERG, field="transfer_agent_fee", quote="The transfer agent will typically charge the tendering broker $80.00 and it would be up to the broker whether or not to pass this cost on to the redeeming holder."),
    # added 2026-10-18 by the successor reader, so every live member of the sample is cited
    dict(src=MYX, field="record_date", quote="Each public shareholder may elect to redeem their public shares irrespective of whether they vote for or against the proposed transaction, or whether they do not vote or abstain from voting on the proposed transaction, or whether they were a public shareholder on the record date for the general meeting held to approve the proposed transaction."),
    dict(src=MYX, field="transfer_agent_fee", quote="The transfer agent will typically charge the broker submitting or tendering shares a fee of approximately $100 and it would be up to the broker whether or not to pass this cost on to the redeeming holder."),
]

# ------------------------------------------------------------- extension proxies and 8-Ks

CHP_PROXY = (1785041, "0001140361-21-035968", "ny20000740x2_def14a.htm")    # extension proxy, 2021-10-29
CHP_EXT = (1785041, "0001140361-21-039392", "brhc10031228_8k.htm")         # extension result, 2021-11-24
IROH_PROXY = (1901203, "0001213900-25-049446", "ea0242415-02.htm")         # Iron Horse extension proxy, 2025-05-30
ZAL_PROXY23 = (1853397, "0001104659-23-079672", "tm2320843-1_def14a.htm")  # XPAC (later Zalatoris II), 2023-07-10
ZAL_PROXY24 = (1853397, "0001213900-24-061405", "ea0209457-def14a_zalator2.htm")  # Zalatoris II, 2024-07-15
ZAL_EXT24 = (1853397, "0001213900-24-065834", "ea0210644-8k425_zal2.htm")  # extension result, 2024-08-07
AURC_PROXY = (1835856, "0001104659-23-011784", "tm233683-2_def14a.htm")    # Aurora (later Better Home), 2023-02-07
AURC_EXT = (1835856, "0001104659-23-027925", "tm233683d8_8k.htm")          # extension result, 2023-03-02
VTIQ_LIQ = (1823884, "0001104659-22-124142", "tm2231563d1_8k.htm")         # VectoIQ II early liquidation, 2022-12-02
IPOD_LIQ = (1818876, "0001104659-22-101307", "tm2225964d1_8k.htm")         # Social Capital Hedosophia IV, liquidation at the deadline, 2022-09

EIGHT_K = [
    # an extension vote is a redemption window, and the redemption price is the trust
    dict(src=CHP_EXT, field="extension_terms", quote="to extend the date by which the Company must complete its initial business combination from November 26, 2021 to May 26, 2022"),
    dict(src=CHP_EXT, field="extension_redemptions", quote="Shareholders holding 11,388,997 shares of the Company’s Class A common stock exercised their right to redeem such shares for a pro rata portion of the funds in the Company’s Trust Account for approximately $114.52 million (approximately $10.06 per share)."),
    dict(src=AURC_EXT, field="extension_redemptions", quote="the holders of 25,751,449 Class A ordinary shares properly exercised their right to redeem their shares for cash at a redemption price of $10.2178 per share"),
    dict(src=ZAL_EXT24, field="extension_redemptions", quote="exercised the right to redeem such shares for cash at an approximate price of $11.15 per share"),
    # sweeteners: what the sponsor pays into the trust per month of extension
    dict(src=ZAL_PROXY24, field="extension_sweetener", quote="will deposit into the Company’s trust account (“Trust Account”), the lesser of (x) $75,000 or (y) $0.025 per share for each Public Share outstanding as of the last day of the immediately preceding Extension for each such Extension"),
    dict(src=IROH_PROXY, field="extension_sweetener", quote="up to twelve (12) times on a month -to -month basis (each an “Extension”), each such extension for an additional one -month period, to June 29, 2026 by depositing the Extension Payment into the Trust Account for each one -month Extension"),
    # what can reach the trust before a holder is paid (added 2026-10-18)
    dict(src=CHP_PROXY, field="third_party_claims", quote="to the extent any claims by a third party for services rendered or products sold to us, or a prospective target business with which we have discussed entering into a transaction agreement, reduce the amount of funds in the trust account to below the lesser of (i) $10.00 per public share and (ii) the actual amount per public share held in the trust account"),
    # the market price beside the redemption price, as each proxy prints them
    dict(src=CHP_PROXY, field="price_vs_trust", quote="The closing price of the public shares on The Nasdaq Capital Market on October 28, 2021, the most recent practicable closing price prior to the mailing of this Proxy Statement, was $10.05."),
    dict(src=IROH_PROXY, field="price_vs_trust", quote="The closing price of the Public Stock on May 29, 2025, the most recent practicable date prior to the date of this proxy statement, was $10.55 per share. The cash held in the Trust Account on May 28, 2025 was approximately $72,660,102"),
    dict(src=ZAL_PROXY23, field="price_vs_trust", quote="the redemption price per Class A Ordinary Share was approximately $10.37, based on the aggregate amount on deposit in the Trust Account of $227,731,980 as of June 30, 2023"),
    dict(src=ZAL_PROXY23, field="price_vs_trust", quote="The closing price of the Class A Ordinary Shares on Nasdaq on July 7, 2023 was $10.37."),
    dict(src=ZAL_PROXY24, field="price_vs_trust", quote="The closing price of the Company’s Class A Ordinary Shares on July 9, 2024, the record date, was $10.96. The approximate redemption price per share to be paid for redemptions is $11.09 per share"),
    dict(src=AURC_PROXY, field="price_vs_trust", quote="The closing price of the public shares on the Nasdaq Capital Market on February 6, 2023, the most recent practicable closing price prior to the mailing of this Proxy Statement, was $10.17."),
    # redemption procedure and rights at an extension vote
    dict(src=IROH_PROXY, field="procedure", quote="TENDER YOUR SHARES TO THE COMPANY’S TRANSFER AGENT AT LEAST TWO BUSINESS DAYS PRIOR TO THE INITIALLY SCHEDULED VOTE AT THE STOCKHOLDER MEETING. IN ORDER TO EXERCISE YOUR REDEMPTION RIGHTS, YOU NEED TO IDENTIFY YOURSELF AS A BENEFICIAL HOLDER"),
    dict(src=ZAL_PROXY24, field="non_redeemer_keeps_right", quote="the right to redeem your public shares for cash in the event the Business Combination is approved and completed or we have not consummated the Business Combination by the Extended Date"),
    dict(src=AURC_PROXY, field="excise_tax", quote="The excise tax is imposed on the repurchasing corporation itself, not its shareholders, from which shares are repurchased."),
    # an early liquidation (late 2022)
    # a liquidation at the deadline: the street-name holder does nothing and is paid the trust (added 2026-10-18)
    dict(src=IPOD_LIQ, field="liquidation_no_action", quote="Beneficial owners of the Public Shares held in “street name,” will not need to take any action in order to receive their pro rata portion of the Redemption Amount."),
    dict(src=IPOD_LIQ, field="liquidation_amount", quote="Based upon the amount held in the trust account as of June 30, 2022, which was $460,681,189, the Company estimates that the per-share Redemption Amount will be approximately $10.01."),
    dict(src=IPOD_LIQ, field="liquidation_amount", quote="funds held in the Company’s trust account, less $100,000 of interest to pay dissolution expenses and net of taxes payable, will be distributed to each holder of Public Shares on a pro rata basis"),
    dict(src=IPOD_LIQ, field="warrants_worthless", quote="There will be no redemption rights or liquidating distributions with respect to the Company’s warrants, which will expire worthless upon the liquidation of the Company."),
    dict(src=VTIQ_LIQ, field="early_liquidation", quote="it will redeem all of its outstanding Class A common stock, par value $0.0001 (the “Class A common stock”), effective as of December 12, 2022, because the Company will not consummate an initial business combination within the time period required by its Charter, as amended pursuant to the Charter Amendment Proposal"),
]
