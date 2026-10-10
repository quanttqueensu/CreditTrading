"""Name-based family classifier for ETFs at Alpaca (active us_equity snapshot 2026-10-08).

ETF universe = Alpaca assets that are (a) CRSP shrcd 73 alive 2024-12-31 by ticker, or
(b) name contains 'ETF', or (c) listed ARCA/BATS and absent from CRSP; minus ETNs,
preferred lines (symbol with '.') and OTC. First matching family wins. Leveraged/inverse
and option-overlay bond products are EXCLUDED and counted separately. Manual overrides
are listed in OVERRIDE with a reason each.
"""
import json, re, sys
import pandas as pd

SCR = sys.argv[1]
a = pd.DataFrame(json.load(open(f"{SCR}/alpaca_assets_active_us_equity.json")))
a["N"] = a.name.str.upper()
dn = pd.read_parquet(f"{SCR}/crsp_dsenames_alive_20241231.parquet")
dn = dn.sort_values("namedt").groupby("permno").tail(1)
crsp_by_tk = dn.drop_duplicates("ticker", keep="last").set_index("ticker")
a["crsp_shrcd"] = a.symbol.map(lambda s: int(crsp_by_tk.loc[s, "shrcd"]) if s in crsp_by_tk.index else None)
is_etn = a.N.str.contains(r"\bETNS?\b|EXCHANGE TRADED NOTE|\bNOTES? DUE\b", regex=True)
etf = a[((a.crsp_shrcd == 73) | a.N.str.contains(r"\bETF\b", regex=True) |
         (a.exchange.isin(["ARCA", "BATS"]) & a.crsp_shrcd.isna()))
        & ~is_etn & ~a.symbol.str.contains(".", regex=False) & (a.exchange != "OTC")].copy()

LEV = (r"\b[23]X\b|-[123]X\b|ULTRAPRO|PROSHARES (TRUST )?ULTRA|PROSHARES (TRUST )?SHORT|INVERSE|"
       r"DAILY .*(BULL|BEAR)|\bBOND BULL\b|\bBEAR\b|MICROSECTORS")
OPT = (r"BUYWRITE|BUY-WRITE|COVERED CALL|OPTION INCOME|PREMIUM INCOME|BUFFER|PUTWRITE|YIELDMAX|"
       r"TARGET INCOME|WEEKLYPAY|AUTOCALL|BARRIER|YIELDBOOST|ENHANCED INCOME|HIGH INCOME ETF|"
       r"\bFLOOR\b|% TARGET|% OPTION|INCOME BOOST|INTEREST RATE HEDGE ETF")
CRYPTO = r"BITCOIN|ETHER|CRYPTO|SOLANA|\bXRP\b"

FAM = [
 ("rate_hedged_credit", r"INTEREST RATE HEDGED|RATE HEDGED|ZERO DURATION|NEGATIVE DURATION|DURATION HEDGED"),
 ("clo", r"\bCLO\b|COLLATERALIZED LOAN"),
 ("bank_loan", r"SENIOR LOAN|BANK LOAN|LEVERAGED LOAN|FLOATING RATE LOAN|SENIOR SECURED|FLOATING RATE INCOME ETF|SECURED CREDIT"),
 ("tips", r"\bTIPS\b|INFLATION-PROTECT|INFLATION PROTECT|INFLATION-LINKED|INFLATION LINKED|INFLATION HEDGED CORP"),
 ("muni", r"\bMUNI|TAX-EXEMPT|TAX EXEMPT|TAX-FREE|TAX FREE|AMT-FREE|AMT FREE"),
 ("em_debt", r"(EMERGING|\bEM\b).*(BOND|DEBT|SOVEREIGN|LOCAL|CORPORATE|HIGH YIELD|FIXED|CREDIT|TREASUR|GOVERNMEN)|CHINA BOND|ASIA PACIFIC HIGH INCOME"),
 ("preferred", r"PREFERRED|\bPFD\b"),
 ("convertible", r"CONVERTIBLE"),
 ("mbs_securitized", r"\bMBS\b|MORTGAGE-BACKED|MORTGAGE BACKED|SECURITIZED|ASSET-BACKED|ASSET BACKED|\bABS\b|\bCMBS\b|AGENCY BOND|AGENCY MBS|\bGNMA\b|STRUCTURED CREDIT|MORTGAGE PLUS|MORTGAGE OPPORTUNIT"),
 ("float_ultrashort", r"FLOATING RATE|FLOATING-RATE|\bFLOAT\b|FLOATER|VARIABLE RATE|ULTRA SHORT|ULTRA-SHORT|ULTRASHORT|ENHANCED SHORT MATURITY|SHORT MATURITY|MONEY MARKET|\bBOX ETF\b|1-3 MONTH BOX"),
 ("treasury", r"TREASUR|GOVERNMENT BOND|GOVT BOND|GOVERNMENT SECURITIES|GOVERNMENT ACTIVE|\bSTRIPS\b|U\.?S\.? GOVERNMENT|EXTENDED DURATION|\bT-BILL|\bBILL\b|\bBILLS\b|ZERO COUPON"),
 ("hy_corp", r"HIGH YIELD|HIGH-YIELD|\bJUNK\b|FALLEN ANGEL|\bBB RATED|BB-RATED|B-RATED|CCC-RATED|\bBB-B\b|SHORT DURATION HIGH|\bHY\b"),
 ("ig_corp", r"INVESTMENT GRADE|CORPORATE BOND|CORP BOND|\bCORPORATE ETF|CREDIT BOND|\bIG\b|BBB RATED|AAA - A RATED|TERM CORPORATE|CORPORATE LADDER|PUBLIC & PRIVATE CREDIT|GOVERNMENT/CREDIT"),
 ("agg_core_multisector", r"AGGREGATE|CORE BOND|CORE PLUS|CORE-PLUS|TOTAL BOND|TOTAL RETURN BOND|MULTI-SECTOR|MULTISECTOR|MULTI SECTOR|MUTI-SECTOR|FIXED INCOME|STRATEGIC INCOME|FLEXIBLE INCOME|UNIVERSAL USD BOND|SHORT-TERM BOND|INTERMEDIATE-TERM BOND|LONG-TERM BOND|SHORT DURATION BOND|LOW DURATION|LIMITED DURATION|SHORT DURATION INCOME|SHORT DURATION CORE|ACTIVE BOND|OPPORTUNISTIC BOND|TOTAL RETURN ETF|INCOME OPPORTUNITIES ETF|CREDIT OPPORTUNITIES|CREDIT INCOME|OPPORTUNISTIC (INCOME|CORE|CREDIT)|\bBOND (ETF|FUND)|BOND FACTOR|INTERNATIONAL BOND|WORLD BOND|GREEN BOND|IMPACT BOND|HYBRID BOND|USD BOND|PRIVATE CREDIT"),
 ("multi_asset", r"MANAGED FUTURES|RISK PARITY|ALL WEATHER|ALL-WEATHER|GLOBAL MACRO|\bMACRO\b|MULTI-ASSET|MULTI ASSET|ASSET ALLOCATION|ALLOCATION ETF|BALANCED|RETURN STACKED|\bCTA\b|PURE TREND|TREND ETF|AHL TREND|MULTI-STRATEGY|MULTI STRATEGY|HEDGE MULTI|HEDGE FUND|MULTI-QIS|SYSTEMATIC ALTERNATIVES|ALTERNATIVE INCOME|ALTERNATIVES ETF|FLEXIBLE ALLOCATION|DYNAMIC ALLOCATION|GLOBAL ALLOCATION|CAPITAL ALLOCATION|MODERATE ALLOCATION|30/70|40/60|60/40|80/20|MULTI-ASSET REAL RETURN|ALTERNATIVE ASSET ALLOC"),
]
AGG_EXCL = r"EQUITY|DIVIDEND|NASDAQ|S&P 500|\bGOLD\b|SILVER|NVDA|TSLA|REAL ESTATE|REALTY|INFRASTRUCTURE|ENERGY|MIDSTREAM|NUCLEAR|DEFENSE|GROWTH & INCOME|LARGE CAP|SMALL.CAP|CHINA A|REAL ASSET|TECH|RESIDENTIAL|OIL|MAGNIFICENT|BERKSHIRE|QUALITY INCOME|\bWMT\b|CASH COWS|OPTIONS"
MULTI_EXCL = r"EQUITY|COMMODITY|TRENDPILOT|SECTOR|MEGATREND|HARVEST|ASSET MANAGER|\bCAP\b|LARGE CAP|SMALL CAP|MID CAP|DIVERSIFIED RETURN|SENTIMENT|TAIL RISK|ROTATION|THEMATIC|FACTOR|BITCOIN|ENERGY"
MULTI_KEEP = r"MANAGED FUTURES|RETURN STACKED|ALLOCATION|BALANCED|RISK PARITY|ALL WEATHER|ALL-WEATHER"

OVERRIDE = {  # symbol -> (family, reason)
 "REM": ("_mreit_equity_etf", "iShares Mortgage Real Estate ETF holds mREIT equity, not MBS"),
 "MORT": ("_mreit_equity_etf", "VanEck Mortgage REIT Income ETF holds mREIT equity"),
 "PFIX": ("_excluded_option_overlay", "rates payer-option fund, not a credit hedge"),
 "RISR": ("mbs_securitized", "MBS interest-only fund"),
 "PEY": (None, "Invesco High Yield Equity Dividend Achievers is an equity fund"),
 "VRIG": ("float_ultrashort", "Variable Rate Investment Grade = floating"),
 "BIZD": ("_bdc_etf", "BDC equity ETF"), "PBDC": ("_bdc_etf", "BDC equity ETF"), "FBDC": ("_bdc_etf", "BDC equity ETF"),
 "PCEF": ("_cef_fof_etf", "ETF of CEFs"), "YYY": ("_cef_fof_etf", "ETF of CEFs"), "FCEF": ("_cef_fof_etf", "ETF of CEFs"),
 "CEFZ": ("_cef_fof_etf", "ETF of CEFs"), "CCEF": ("_cef_fof_etf", "ETF of CEFs"),
 "HYIN": ("_cef_fof_etf", "WisdomTree Private Credit & Alt Income: holds BDCs/CEFs"),
 "DIAL": ("agg_core_multisector", "Columbia Diversified Fixed Income Allocation is a bond fund"),
 "TFFI": ("agg_core_multisector", "trend-following fixed income"),
 "PTBD": ("agg_core_multisector", "Pacer Trendpilot US Bond"),
 "HXA": (None, "corporate arbitrage, not IG credit"),
 "LMBS": ("mbs_securitized", "First Trust Low Duration Opportunities (MBS); name truncated by Alpaca"),
 "TFLO": ("float_ultrashort", "Treasury floating rate"), "USFR": ("float_ultrashort", "Treasury floating rate"),
}

def fam(sym, n):
    if sym in OVERRIDE: return OVERRIDE[sym][0]
    if re.search(LEV, n): return "_excluded_leveraged_inverse"
    for f, rx in FAM:
        if re.search(rx, n):
            if re.search(OPT, n) or re.search(CRYPTO, n): return "_excluded_option_overlay"
            if f == "agg_core_multisector" and re.search(AGG_EXCL, n): return None
            if f == "multi_asset" and re.search(MULTI_EXCL, n) and not re.search(MULTI_KEEP, n): return None
            return f
    return None

etf["family"] = [fam(s, n) for s, n in zip(etf.symbol, etf.N)]
bondish = etf.N.str.contains(r"BOND|TREASUR|CREDIT|YIELD|LOAN|\bCLO\b|\bMUNI|MORTGAGE|PREFERRED|CONVERTIBLE|TIPS|INFLATION|FLOAT|FIXED INCOME|DEBT|CORPORATE|DURATION|AGGREGATE|\bBILL", regex=True)
etf.loc[etf.family.isin(["_excluded_leveraged_inverse", "_excluded_option_overlay"]) & ~bondish, "family"] = None

def sub(r):
    n, s, f = r.N, r.symbol, r.family
    if f in ("ig_corp", "hy_corp", "treasury", "muni", "tips"):
        if re.search(r"\b(DEC|OCT) 20\d\d|20\d\d TERM|TARGET MATURITY|MY20\d\d|BULLETSHARES 20|20\d\d (HIGH YIELD|CORPORATE|MUNICIPAL)|ZERO COUPON BOND 20|DISTRIBUTING LADDER|20\d\d TAX-EXEMPT", n) \
           or re.match(r"^(BSC|BSJ|BSM|BST|BSG|IBD|IBC|IBH|IBT|IBG|IBM|IBI|MYC|MYH|MYM|VBC|ZCB)[A-Z]$", s):
            return "term"
        if re.search(r"INTERNATIONAL|EX-US|EX-U\.S|\bEURO\b|GLOBAL (GOVERNMENT|TREASURY|CORPORATE|HIGH YIELD|BOND)|US & INTL|\bINTL\b", n): return "international"
    if f in ("ig_corp", "treasury", "tips"):
        if re.search(r"BILL|0-1 Y|0-3 MONTH|1-3 MONTH|SIX MONTH|12 MONTH|ONE YEAR|3-12", n): return "bills_<1y"
        if re.search(r"0-5|1-5|1-3|SHORT|2-YEAR|2 YEAR|3-YEAR|3 YEAR|TWO YEAR|THREE YEAR|LIMITED DURATION|0-5 Y", n): return "short"
        if re.search(r"10\+|10-20|20\+|20 YEAR|25\+|30 YEAR|TWENTY|LONG|EXTENDED|STRIPS|15\+", n): return "long"
        if re.search(r"5-10|3-7|3-10|1-10|7-10|INTERMEDIATE|5 YEAR|7 YEAR|10 YEAR|FIVE YEAR|SEVEN YEAR|TEN YEAR|5-YEAR", n): return "intermediate"
        return "broad"
    if f == "em_debt":
        return "local" if re.search(r"LOCAL|DOMESTIC|CHINA BOND", n) else "hard"
    return ""

etf["sub"] = etf.apply(sub, axis=1)
# Treasury bills belong to the Treasury family's <1y bucket; keep them out of float_ultrashort.
etf.to_parquet(f"{SCR}/etf_classified.parquet")
print(len(etf), etf.family.value_counts(dropna=False).to_dict())
