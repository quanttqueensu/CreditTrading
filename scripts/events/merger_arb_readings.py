"""Hand readings of the 20-deal reading sample (merger_arb_feasibility.py, part 6). Data only.

WHY THIS FILE
-------------
The reading problem is measured by comparing what a regex reader pulls out of
an announcement 8-K (`merger_arb_feasibility.machine_terms`) with what a reader
finds in the SAME document. A reading that cannot be checked is an anecdote,
so every field that states a term carries a verbatim quote from the document,
and `verify` re-finds each quote in the fetched filing on every run (after
`conditional_tender_census.normalise`: case, curly quotes, dashes and spacing
only, so a different number never matches). A quote that is not found raises.

Fields (None = the document does not state it; never a guess):
  role             'target' (scored field by field) | 'acquirer' (the anchor is a buyer's share-issuance
                   vote) | 'reorganisation' | 'wrong_document' (the 8-K picked is not the deal's)
  consideration    'cash' | 'stock' | 'mixed'
  cash_per_share   str, as printed ("$36.00")
  ratio            str, as printed ("0.4500")
  collar           True / False (a collar, floor, cap or VWAP-dependent ratio)
  election         True / False (holder elects cash or stock, with proration)
  cvr              True / False
  outside_date     str, as printed, with any automatic extension in `outside_ext`
  approvals        list of regulatory approvals the document names as conditions
  vote             'target' | 'acquirer' | 'both' | 'none (tender)' | 'written consent'
  financing_cond   False if the document says there is none; None if silent
  term_fee         str, as printed
  quotes           {field: verbatim text from the document}
  notes            free text: what made this deal hard to read
"""
from __future__ import annotations

# THE SAMPLE. The rule (`merger_arb_feasibility.run`, written before any deal was
# read): among in-scope deals announced on or after 2026-01-01 whose announcement
# document is the target's own 8-K item 1.01, the 10 most recent cash deals and
# the 10 most recent stock-involved deals (a 425 lists the target), by d0, ties
# by CIK. It was applied once, on the run date in SAMPLE_DRAWN, and the 20
# accessions it picked are frozen here BEFORE any of them was read, so a later
# run (more anchors, a refreshed index) reads the same 20.
SAMPLE_DRAWN: str | None = "2026-10-18"   # run date; EDGAR index to 2026-10-16
SAMPLE_ACCESSIONS: tuple[str, ...] = (
    "0001140361-26-037107",
    "0000950103-26-013874",
    "0001104659-26-114571",
    "0001104659-26-103936",
    "0001193125-26-406024",
    "0001193125-26-341431",
    "0001104659-26-106499",
    "0001193125-26-290439",
    "0001609151-26-000100",
    "0001104659-26-085824",
    "0001140361-26-035986",
    "0001193125-26-384457",
    "0001140361-26-031930",
    "0001104659-26-089425",
    "0001493152-26-035196",
    "0001628280-26-049232",
    "0001193125-26-310388",
    "0001104659-26-083891",
    "0001104659-26-078482",
    "0001140361-26-026434",
)

READINGS: dict[str, dict] = {
    # ---------------------------------------------------------------- the 10 cash-class deals
    "0001140361-26-037107": {   # Mistras Group (MG)
        "role": "target", "consideration": "cash", "cash_per_share": "$20.35", "ratio": None, "collar": False,
        "election": False, "cvr": False, "outside_date": None, "outside_ext": None,
        "approvals": ["HSR", "certain other required regulatory approvals"], "vote": "target",
        "financing_cond": False, "term_fee": "$27.5 million",
        "quotes": {
            "consideration": "will be automatically converted into the right to receive $20.35 in cash, without interest",
            "outside_date": "if the Merger has not been consummated by the Outside Date (as defined in the Merger Agreement)",
            "approvals": "the expiration or termination of the applicable waiting period under the Hart-Scott-Rodino "
                         "Antitrust Improvements Act of 1976, as amended, and the receipt of certain other required "
                         "regulatory approvals",
            "vote": "by the holders of a majority of the outstanding shares of Company Common Stock entitled to vote on the matter",
            "financing_cond": "The Merger is not subject to a financing condition.",
            "term_fee": "the Company will pay Parent a termination fee of approximately $27.5 million",
            "go_shop": "a reduced termination fee equal to 50% of the full Company Termination Fee",
        },
        "notes": "Outside date not in the 8-K ('as defined in the Merger Agreement'): reading it needs Exhibit 2.1. "
                 "40-day go-shop at a half fee; voting agreements on about 31%; sponsor buyer (H.I.G.) with equity "
                 "and debt commitments. The 8-K reports the September signing; the pipeline's d0 is the later proxy.",
    },
    "0000950103-26-013874": {   # Baldwin Insurance Group (BWIN)
        "role": "target", "consideration": "cash", "cash_per_share": "$32.50", "ratio": None, "collar": False,
        "election": False, "cvr": False, "outside_date": "June 14, 2027",
        "outside_ext": "automatically to September 14, 2027 if only regulatory conditions remain",
        "approvals": ["HSR", "certain other regulatory approvals"], "vote": "target", "financing_cond": False,
        "term_fee": "$170,334,000",
        "quotes": {
            "consideration": "will automatically be converted into the right to receive $32.50 in cash, without interest",
            "outside_date": "if the Mergers have not been consummated on or before June 14, 2027",
            "outside_ext": "the Initial End Date will automatically be extended to September 14, 2027",
            "approvals": "waiting periods applicable to the consummation of the Mergers under the Hart-Scott-Rodino "
                         "Antitrust Improvements Act of 1976",
            "vote": "by the holders of at least a majority of the outstanding shares entitled to vote thereon, voting "
                    "together as a single class",
            "written_consent": "have executed and delivered a written consent approving and consenting to the "
                               "transactions contemplated by the Merger Agreement",
            "financing_cond": "The Mergers are not subject to any financing condition.",
            "term_fee": "a termination fee of $170,334,000",
            "reverse_fee": "a termination fee of $276,218,000",
        },
        "notes": "Up-C: OpCo LLC units convert beside the Class A shares, Class B is cancelled for nothing, and the "
                 "Class B holders' written consent is already delivered. Special committee; buyer is Michael Dell's "
                 "family office (DFO) with a limited guarantee; reverse fee $276,218,000. The regex reader took the "
                 "EXTENDED date (September 14, 2027) as the outside date.",
    },
    "0001104659-26-114571": {   # Pacira BioSciences (PCRX)
        "role": "target", "consideration": "cash", "cash_per_share": "$36.50", "ratio": None, "collar": False,
        "election": False, "cvr": False, "outside_date": None, "outside_ext": None, "approvals": ["HSR"],
        "vote": "none (tender)", "financing_cond": None, "term_fee": "$62.0 million",
        "quotes": {
            "consideration": "at an offer price of $36.50 per Share in cash",
            "vote": "Purchaser will commence a cash tender offer",
            "minimum": "would represent at least one Share more than 50% of the total number of Shares at the time of "
                       "the expiration of the Offer",
            "approvals": "applicable to the Offer under the Hart-Scott-Rodino Antitrust Improvements Act of 1976",
            "term_fee": "a termination fee of an amount in cash equal to $62.0 million",
        },
        "notes": "Tender offer, majority minimum condition, HSR. The 8-K states no outside date and says nothing on "
                 "financing. The regex reader missed the fee ('termination fee of an amount in cash equal to').",
    },
    "0001104659-26-103936": {   # Victory Capital (VCTR)
        "role": "acquirer", "consideration": None,
        "quotes": {
            "role": "the Company will pay and/or issue, as applicable, to Seller a combination of (a) cash, (b) newly "
                    "issued shares of common stock",
            "vote": "The issuance of the shares of the Company Common Stock and the Company Convertible Preferred Stock "
                    "is subject to the approval of the Company stockholders",
        },
        "notes": "NOT A TARGET. Victory Capital is the BUYER of a private business (First Eagle); its proxy asks "
                 "holders to approve a share issuance. No listed target, no spread. Anchored as a 'deal' because a "
                 "merger proxy is a target-only form only most of the time.",
    },
    "0001193125-26-406024": {   # SoundThinking (SSTI)
        "role": "target", "consideration": "cash", "cash_per_share": "$8.00", "ratio": None, "collar": False,
        "election": False, "cvr": True, "outside_date": "March 28, 2027", "outside_ext": "subject to extension",
        "approvals": [], "vote": "none (tender)", "financing_cond": False, "term_fee": "$4,500,000",
        "quotes": {
            "consideration": "for (i) $8.00 per Share, net to the stockholder of such Share in cash, without interest",
            "cvr": "plus (ii) one non-transferable contingent value right per Share",
            "cvr_value": "one contingent cash payment of up to $3.00 per CVR",
            "outside_date": "if the Offer has not been consummated by March 28, 2027, subject to extension under certain "
                            "circumstances",
            "vote": "Parent will cause Merger Sub to commence a tender offer",
            "minimum": "would represent at least one Share more than 50% of the total number of Shares outstanding",
            "financing_cond": "are not subject to a condition that any financing be received by Parent or Merger Sub",
            "term_fee": 'Company Termination Fee") of $4,500,000',
        },
        "notes": "Cash plus a NON-TRANSFERABLE CVR (up to $3.00 on milestones): the CVR cannot be sold, so the long "
                 "carries an option the book cannot mark. No regulatory approval is named in the 8-K. The regex "
                 "reader missed the price ('net to the stockholder of such Share in cash'), the date, the fee and the "
                 "no-financing statement.",
    },
    "0001193125-26-341431": {   # Bowman Consulting (BWMN)
        "role": "target", "consideration": "cash", "cash_per_share": "$43.00", "ratio": None, "collar": False,
        "election": False, "cvr": False, "outside_date": "February 9, 2027",
        "outside_ext": "automatically to May 10, 2027 if the Regulatory Condition is unsatisfied",
        "approvals": ["HSR"], "vote": "target", "financing_cond": None, "term_fee": "$26,861,672",
        "quotes": {
            "consideration": "converted into the right to receive cash in an amount per share equal to $43.00, without "
                             "interest thereon",
            "outside_date": "has not occurred by 11:59 p.m., Eastern time, on February 9, 2027",
            "outside_ext": "automatically extended (without any further action by any party) to 11:59 p.m., Eastern "
                           "time, on May 10, 2027",
            "approvals": "any applicable waiting period under the Hart-Scott-Rodino Antitrust Improvements Act of 1976, "
                         "as amended, relating to the Merger",
            "vote": "the holders of a majority of the outstanding shares of Company Common Stock entitled to vote in "
                    "accordance with the DGCL",
            "term_fee": "pay Parent a termination fee of $26,861,672 in cash",
        },
        "notes": "Sponsor buyer (BCP funds) with equity and debt commitments; go-shop. The regex reader took the "
                 "termination fee ('$26,861,672 in cash') as the price per share and missed the $43.00.",
    },
    "0001104659-26-106499": {   # Swarmer (SWMR)
        "role": "acquirer", "consideration": None,
        "quotes": {
            "role": "the Company will pay consideration to the Sellers for the Acquisition of (i) an estimated $7.2 "
                    "million in cash",
            "vote": "Pursuant to Nasdaq Listing Rule 5635(a), the issuance of the Stock Consideration",
        },
        "notes": "NOT A TARGET. Swarmer buys a private business for cash and shares; its proxy is a Nasdaq 5635(a) "
                 "share-issuance vote.",
    },
    "0001193125-26-290439": {   # MarineMax (HZO)
        "role": "wrong_document", "consideration": None,
        "quotes": {"role": "refinanced its existing Credit Agreement with Manufacturers and Traders Trust Company"},
        "notes": "WRONG DOCUMENT. The 8-K item 1.01 in the wide window is a June 2026 credit-facility refinancing, "
                 "not a merger agreement. What the anchoring proxy concerns was not read.",
    },
    "0001609151-26-000100": {   # Weave Communications (WEAV)
        "role": "target", "consideration": "cash", "cash_per_share": "$7.40", "ratio": None, "collar": False,
        "election": False, "cvr": False, "outside_date": "February 18, 2027",
        "outside_ext": "automatically until May 18, 2027 under certain circumstances", "approvals": ["HSR"],
        "vote": "target", "financing_cond": None, "term_fee": "$22.8 million",
        "quotes": {
            "consideration": "will be converted automatically into the right to receive $7.40 in cash, without interest",
            "outside_date": "the Merger is not consummated on or before February 18, 2027",
            "outside_ext": "which date will be automatically extended until May 18, 2027",
            "approvals": "Antitrust Improvements Act of 1976, as amended; and (3) the absence of any order",
            "vote": "the affirmative vote of the holders of a majority of the outstanding Shares entitled to vote thereon",
            "term_fee": "pay Parent a termination fee of $22.8 million",
            "reverse_fee": "Parent will be required to pay the Company a termination fee of $39 million",
        },
        "notes": "The HSR condition is printed with NON-BREAKING hyphens (U+2011, 'Hart-Scott-Rodino'), so the regex "
                 "reader's HSR test failed; it also took the extended date (May 18, 2027) as the outside date.",
    },
    "0001104659-26-085824": {   # NovaGold Resources (NG)
        "role": "reorganisation", "consideration": None,
        "quotes": {"role": "will be exchanged for one share of voting common stock of New NovaGold"},
        "notes": "NOT AN ARBITRAGE. A plan of arrangement that exchanges each NovaGold share one-for-one into a new "
                 "holding company while Paulson contributes its Donlin interests. There is no offer price to converge to.",
    },
    # ---------------------------------------------------------------- the 10 stock-involved deals
    "0001140361-26-035986": {   # Centerspace (CSR) <- IRT
        "role": "target", "consideration": "stock", "cash_per_share": None, "ratio": "3.8", "collar": False,
        "election": False, "cvr": False, "outside_date": None, "outside_ext": None, "approvals": [],
        "vote": "both", "financing_cond": None, "term_fee": "$45 million",
        "quotes": {
            "ratio": "will be converted into the right to receive 3.8 (as may be adjusted pursuant to the Merger Agreement",
            "vote": "adoption by holders of Centerspace Common Stock of the Merger Agreement and approval by holders of IRT "
                    "Common Shares of the issuance of shares of IRT Common Stock in the Merger",
            "term_fee": "Centerspace will be required to pay a termination fee to IRT of $45 million",
            "dividend": "Centerspace may not pay such regular quarterly cash dividend",
        },
        "notes": "Ratio printed with ONE decimal ('3.8'), which the regex reader's two-to-six-decimal pattern misses; "
                 "'as may be adjusted' without saying how. Both votes. The closing quarter's dividend rule changes "
                 "the carry of the pair. No outside date and no named regulatory approval in the 8-K.",
    },
    "0001193125-26-384457": {   # Eagle Financial Services (EFSI) <- JMSB
        "role": "target", "consideration": "stock", "cash_per_share": None, "ratio": "2.00", "collar": False,
        "election": False, "cvr": False, "outside_date": "September 30, 2027", "outside_ext": None,
        "approvals": ["Federal Reserve Board", "Virginia Bureau of Financial Institutions"], "vote": "both",
        "financing_cond": None, "term_fee": "$10,100,000",
        "quotes": {
            "ratio": "will be converted into the right to receive 2.00 shares (the",
            "outside_date": "are not consummated by September 30, 2027 (the",
            "approvals": "including from the Board of Governors of the Federal Reserve System, and the Virginia Bureau "
                         "of Financial Institutions",
            "vote": "approval of the JMSB Share Issuance by the requisite vote of the JMSB shareholders",
            "term_fee": "A termination fee in the amount of $10,100,000 will be payable by either EFSI or JMSB",
        },
        "notes": "The ratio and the date each print BEFORE their defined terms ('2.00 shares (the Exchange Ratio)', "
                 "'September 30, 2027 (the Termination Date)'), which defeats both regexes; so does 'termination fee "
                 "in the amount of'.",
    },
    "0001140361-26-031930": {   # Cherry Hill Mortgage (CHMI) <- MITT
        "role": "target", "consideration": "mixed", "cash_per_share": "$0.93", "ratio": "0.3063", "collar": False,
        "election": False, "cvr": False, "outside_date": "March 9, 2027",
        "outside_ext": "by an additional 60 days if only regulatory approvals remain",
        "approvals": ["certain regulatory approvals (unnamed)"], "vote": "both", "financing_cond": None,
        "term_fee": "$4,700,000",
        "quotes": {
            "ratio": "0.3063 validly issued, fully paid and nonassessable shares of the common stock",
            "collar": "pursuant to a fixed exchange ratio",
            "cash_parent": "$0.41 per share in cash",
            "cash_manager": "$0.52 per share in cash",
            "outside_date": "on or before March 9, 2027 (subject to extension by an additional 60 days",
            "approvals": "the receipt of certain regulatory approvals arising in connection with the proposed transaction",
            "vote": "by the affirmative vote of a majority of the votes cast by the holders of the outstanding shares of "
                    "Parent Common Stock",
            "term_fee": "in the case of payment by the Company, $4,700,000",
        },
        "notes": "Two cash legs from two payers ($0.41 from Parent and $0.52 from Parent's external manager: $0.93 in "
                 "all), plus preferred-for-preferred exchanges. The regex reader found the first cash leg only.",
    },
    "0001104659-26-089425": {   # Supernus (SUPN) <- Indivior
        "role": "target", "consideration": "stock", "cash_per_share": None, "ratio": "1.5401", "collar": False,
        "election": False, "cvr": False, "outside_date": "six months after the date of the Merger Agreement",
        "outside_ext": "to nine, then twelve, months after signing if antitrust or the financing is outstanding",
        "approvals": ["HSR"], "vote": "both", "financing_cond": None, "term_fee": "$101 million",
        "quotes": {
            "ratio": "will be converted into the right to receive 1.5401 shares of common stock",
            "collar": "The Exchange Ratio is fixed and will not be adjusted",
            "outside_date": "has not been consummated by the date that is six months after the date of the Merger Agreement",
            "outside_ext": "either party may extend the Termination Date to a date up to nine months, and thereafter up "
                           "to twelve months",
            "approvals": "the expiration or termination of the waiting period applicable to the Merger under the "
                         "Hart-Scott-Rodino Antitrust Improvements Act of 1976",
            "vote": "The issuance of Indivior Shares as Merger Consideration",
            "term_fee": "a termination fee in an amount equal to $101 million",
        },
        "notes": "Merger of equals. The outside date is RELATIVE (six months from signing, extendable to twelve) and "
                 "one extension trigger is 'the financing', so the deal can wait on financing although no financing "
                 "condition is stated in the 8-K.",
    },
    "0001493152-26-035196": {   # Sanara MedTech (SMTI) <- MDXG
        "role": "target", "consideration": "mixed", "cash_per_share": "$33.00", "ratio": "0.4735", "collar": False,
        "election": False, "cvr": False, "outside_date": "July 29, 2027",
        "outside_ext": "to January 29, 2028 if antitrust approvals are outstanding",
        "approvals": ["HSR", "certain other applicable regulatory approvals"], "vote": "target", "financing_cond": False,
        "term_fee": "$22,540,785.00",
        "quotes": {
            "cash_per_share": "the right to receive $33.00 per share in cash, without interest",
            "ratio": "and 0.4735 shares of Parent Common Stock",
            "stock_value": "The Per Share Stock Consideration represents a value of $2.00 per share",
            "outside_date": "the Merger has not been consummated on or before July 29, 2027",
            "outside_ext": "may extend the End Date to January 29, 2028",
            "financing_cond": "The Merger is not subject to a financing condition",
            "approvals": "all applicable waiting periods under the Hart-Scott-Rodino Antitrust Improvements Act",
            "vote": "the affirmative vote of the holders of a majority of the outstanding shares of Common Stock entitled "
                    "to vote thereon",
            "term_fee": "a termination fee of $22,540,785.00 in cash",
        },
        "notes": "Mixed, but the stock leg is worth about $2.00 of $35.00: shorting 0.4735 MDXG hedges about 6% of "
                 "the consideration, so this is a cash deal in all but name. The regex reader took the extended date.",
    },
    "0001628280-26-049232": {   # BioLife Solutions (BLFS) <- Repligen
        "role": "target", "consideration": "mixed", "cash_per_share": "$11.25", "ratio": "0.1442", "collar": False,
        "election": False, "cvr": False, "outside_date": "January 31, 2027",
        "outside_ext": "by 180 days (antitrust) or by 90 days (if the S-4 is not effective by November 30, 2026)",
        "approvals": ["HSR", "antitrust consents of specified jurisdictions"], "vote": "target",
        "financing_cond": None, "term_fee": "$59,000,000",
        "quotes": {
            "ratio": "0.1442 validly issued, fully paid and nonassessable shares of Repligen common stock",
            "cash_per_share": "$11.25 in cash, without interest",
            "outside_date": "New York time on January 31, 2027 (the",
            "outside_ext": "subject to automatically extend by 180 days",
            "approvals": "the receipt of consents required under antitrust laws of specified jurisdictions",
            "vote": "by the holders of a majority of the outstanding shares of BioLife Common Stock entitled to vote thereon",
            "term_fee": "pay Repligen a termination fee of $59,000,000",
        },
        "notes": "Two automatic extensions with different triggers (antitrust; S-4 effectiveness). The date prints "
                 "before its defined term, so the regex reader missed it.",
    },
    "0001193125-26-310388": {   # Finward Bancorp (FNWD) <- First Financial (FFBC)
        "role": "target", "consideration": "stock", "cash_per_share": None, "ratio": "1.35", "collar": False,
        "election": False, "cvr": False, "outside_date": "one year from the date of the Merger Agreement",
        "outside_ext": None,
        "approvals": ["Federal Reserve Board", "Ohio Division of Financial Institutions"], "vote": "target",
        "financing_cond": None, "term_fee": "$9.0 million",
        "quotes": {
            "ratio": "will be converted into the right to receive 1.35 shares of common stock, no par value, of Buyer",
            "outside_date": "if the Merger is not consummated within one year from the date of the Merger Agreement",
            "approvals": "including from the Board of Governors of the Federal Reserve System and the Ohio Department of "
                         "Commerce, Division of Financial Institutions",
            "vote": "(a) approval of the Merger by the Company",
            "term_fee": "a termination fee of $9.0 million will be payable by the Company to Buyer",
        },
        "notes": "Relative outside date (one year from signing). Bank deal: Federal Reserve and Ohio DFI approvals; "
                 "no buyer vote named.",
    },
    "0001104659-26-083891": {   # TriCo Bancshares (TCBK) <- First Hawaiian (FHB)
        "role": "target", "consideration": "stock", "cash_per_share": None, "ratio": "2.095", "collar": False,
        "election": False, "cvr": False, "outside_date": None, "outside_ext": None,
        "approvals": ["Federal Reserve Board", "FDIC", "Hawaii Division of Financial Institutions",
                      "California DFPI"], "vote": "both", "financing_cond": None, "term_fee": "$80,000,000",
        "quotes": {
            "ratio": "will be converted into the right to receive 2.095 shares (the",
            "approvals": "the approval of the Board of Governors of the Federal Reserve System, the Federal Deposit "
                         "Insurance Corporation",
            "vote": "receipt of the FHI Stockholder Approval and the TriCo Shareholder Approval",
            "term_fee": "a termination fee of $80,000,000 will be payable by either TriCo or FHI",
        },
        "notes": "Four bank regulators; no outside date in the 8-K; the ratio prints before its defined term, so the "
                 "regex reader missed it.",
    },
    "0001104659-26-078482": {   # Iridium (IRDM) <- Rocket Lab (RKLB)
        "role": "target", "consideration": "mixed", "cash_per_share": "$27.00", "ratio": None, "collar": True,
        "election": False, "cvr": False, "outside_date": "June 28, 2027",
        "outside_ext": "to September 28, 2027 and December 28, 2027",
        "approvals": ["HSR", "FCC", "foreign investment, satellite and telecommunications laws"], "vote": "target",
        "financing_cond": None, "term_fee": "$223.62 million",
        "quotes": {
            "cash_per_share": "will be converted into the right to receive (i) $27.00 in cash",
            "collar_low": "is equal to or less than $67.50, then the Exchange Ratio will be 0.4000",
            "collar_high": "is equal to or greater than $112.50, then the Exchange Ratio will be 0.2400",
            "collar_vwap": "the volume weighted average price per share of Rocket Lab Common Stock",
            "outside_date": "has not been completed on or before June 28, 2027",
            "outside_ext": "which date may be extended to September 28, 2027 and December 28, 2027",
            "approvals": "consent of the U.S. Federal Communications Commission",
            "approvals_foreign": "other specified foreign investment and satellite and telecommunications laws",
            "vote": "the affirmative vote of the holders of a majority of the outstanding Iridium Common Stock",
            "term_fee": "a termination fee of $223.62 million",
        },
        "notes": "FIXED-VALUE COLLAR: between $67.50 and $112.50 (Rocket Lab's 10-day VWAP) the stock leg is worth "
                 "a fixed $27.00, so the acquirer short is not a fixed number of shares and the hedge ratio moves "
                 "with RKLB. The regex reader saw neither the collar nor a ratio.",
    },
    "0001140361-26-026434": {   # Synaptics (SYNA) <- onsemi (ON)
        "role": "target", "consideration": "stock", "cash_per_share": None, "ratio": "1.350", "collar": False,
        "election": False, "cvr": False, "outside_date": "June 25, 2027",
        "outside_ext": "extensions up to 21 months from signing for regulatory approvals",
        "approvals": ["antitrust (jurisdictions not named)", "foreign direct investment laws"], "vote": "target",
        "financing_cond": None, "term_fee": "$235,000,000",
        "quotes": {
            "ratio": "shall be converted into the right to receive 1.350 validly issued, fully paid and non-assessable "
                     "shares of common stock of Parent",
            "outside_date": "does not occur on or before 11:59 Pacific Time on June 25, 2027",
            "outside_ext": "subject to certain extensions aggregating to up to 21 months from the date of the Merger Agreement",
            "approvals": "any required approvals under applicable foreign direct investment laws",
            "vote": "the affirmative vote of the holders of a majority of the issued and outstanding shares of Company "
                    "Common Stock entitled to vote thereon",
            "term_fee": "the Company will be required to pay Parent a termination fee of $235,000,000",
            "regulatory_fee": "a regulatory termination fee equal to $320,000,000",
        },
        "notes": "No HSR by name ('applicable antitrust waiting periods'); a $320m regulatory reverse fee says "
                 "antitrust is the risk. The regex reader found no regulatory condition and missed the outside date.",
    },
}

FIELDS = ("role", "consideration", "cash_per_share", "ratio", "collar", "election", "cvr", "outside_date",
          "outside_ext", "approvals", "vote", "financing_cond", "term_fee")


def verify(reading: dict, text: str, accession: str) -> None:
    """Raise unless every quote of `reading` occurs in the fetched document `text`."""
    from scripts.events.conditional_tender_census import quote_in
    quotes = reading.get("quotes") or {}
    if not quotes:
        raise ValueError(f"{accession}: a reading with no quotes is an anecdote")
    missing = [k for k, q in quotes.items() if not quote_in(text, q)]
    if missing:
        raise AssertionError(f"{accession}: quote(s) not found in the filing: {missing}")


def flatten(reading: dict | None) -> dict:
    """The reading's fields for the sample table, prefixed `r_`; `read` says whether one exists."""
    if reading is None:
        return {"read": False}
    out = {"read": True}
    for k in FIELDS:
        v = reading.get(k)
        out[f"r_{k}"] = "; ".join(v) if isinstance(v, list) else v
    out["r_notes"] = reading.get("notes")
    return out
