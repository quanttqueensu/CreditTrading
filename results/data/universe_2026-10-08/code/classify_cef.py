"""Explicit ticker classification of CRSP shrcd 14/44 (alive 2024-12-31) + mREITs + post-2024 listings.

Assignments were made by reading each CRSP comnam (and the Alpaca name where CRSP truncates).
Judgement calls are recorded in NOTES. The deployed 13 are tagged; every other CEF is the
sealed holdout: liquidity/tradability ONLY, no return statistic is computed anywhere here.
"""
import sys, pandas as pd
SCR = sys.argv[1]
W = lambda s: s.split()
BDC = W("""ARCC BCSF BBDC BXSL OBDC OBDE CION CSWC CGBD LIEN CCAP EQS FSK FDUS GLAD GAIN GSBD GBDC GECC HTGC HRZN
 ICMB KBDC LRFC MAIN MFIC MRCC MSDL NMFC NCDL OFS OCSL OXSQ PSBD PFLT PNNT PFX PTMN PSEC RAND RWAY SLRC SAR TSLX
 SCM SSSS TRIN TPVG WHF TCPC""")
BDC_NEW = W("MSIF OTF BCIC AFCG")            # at Alpaca, in SEC BDC report, not in CRSP alive set
MUNI = W("""VFL AFB DMB DSM LEO BMN BFZ BYM BKN BTA BFK BTT MUI MUA BLE MUC MUJ MHN MUE MHD MVT MVF MYD MPA MQT MQY
 MIY MYN MYI BNY BHV DMF DTF KTF EVM CEV ETX EIM EVN EOT ENX FMN VKI VCV OIA VMO VKQ VPV IQI VTN VGM IIM CXE CMU
 CXH MFM NBH NUW NVG NEA NAZ NKX NCA NAC NDMO NXC NXN NMT NMS NOM NMI NZF NMCO NMZ NUV NNY NXJ NRK NAN NQP NAD
 NIM NXP NPV MMD PZC PCQ PCK PMF PML PMX PNI PNF PYN MIO MAV MHI PMM PMO RFMZ RFM RMMZ RMM RMI SBI MMU MHF""")
PFD = W("LDP PSF PTA FPF DFP PFD PFO FFC FLC HPI HPS HPF JPC JPI NPFD")
CONV = W("AVK BCV CHI CHY CCD ECF GCV NCV NCZ ACV")
CREDIT = W("""FAX FCO ACP AWF EAD ERC FINS ARDC BANX DHF MCI BGH MPV BHK HYT BTZ DSU EGF BGT FRA BKT BLW BIT BBN BGX
 BSL BGB BWG RA CCIF CIK DHY DSL DBL DLY ECC EIC EFT EVV EFR EVF EVG FSCO FTHY FMY FCT FTF FT GUG GOF GBAB JHS
 JHI INSI VBF VLT VVR KIO MCR MGF CIF MIN MMT EDD MSD NHS HYB NPCT JQC JFR JGH JLS JMM NBB OCCI OXLC PCM GHY ISD
 SDHY PAXS PDO RCS PDCC PCN PTY PDI PDX PHK PFL PFN HNW PHD PHT PIM PPT RSF OPP SPMC TSI TEI VGI EDF WDI EMD GDO
 EHI HIX HIO HYI PAI WIA WIW DMO WEA IGI XFLT""")
CREDIT_NEW = W("HERZ FSSL")                   # Alpaca names: Herzfeld Credit Income Fund; FS Specialty Lending Fund
EQ_NEW = W("BTX BPRE VCX RVI RVII CFND AKAF")
OTHER = W("NEWT")                             # NewtekOne: ex-BDC, now a financial holding company
MREIT = W("""MITT AGNC ACR AOMR NLY ARI ABR ACRE ARR BXMT BRSP CHMI REFI CIM CMTG DX EARN EFC FBRT GPMT IVR KREF LADR
 LFT MFA NYMT NREF ORC PMT RC RWT RITM RPT SACH SEVN STWD SUNS TRTX TWO""")
DEPLOYED = W("AWF BIT DSL HYT JFR MHD MQY PCN PDI PDO PFN PHK PTY")
NOTES = {"RA": "Brookfield Real Assets Income: mostly real-asset debt -> credit (judgement)",
         "GUG": "Guggenheim Active Allocation: majority fixed income -> credit (judgement)",
         "FT": "Franklin Universal: HY plus utility equity -> credit (judgement)",
         "MSD": "CRSP comnam truncated; ticker MSD is the Morgan Stanley EM Debt fund (check Alpaca name)",
         "BBN/NBB/GBAB": "taxable munis (Build America Bonds) -> taxable credit",
         "ECC/EIC/OXLC/OCCI/PDCC/SPMC/CCIF": "registered CEFs holding CLO equity/debt -> taxable credit",
         "BRW/SABA/RIV/PCF/FOF": "funds of CEFs / activist -> equity & multi-asset",
         "AFCG": "Advanced Flower Capital: listed in SEC BDC report 2026 -> BDC"}

dn = pd.read_parquet(f"{SCR}/crsp_dsenames_alive_20241231.parquet").sort_values("namedt").groupby("permno").tail(1)
ce = dn[dn.shrcd.isin([14, 44])][["permno", "ticker", "comnam", "shrcd"]].copy()
def fam(t):
    if t in BDC: return "bdc"
    if t in MUNI: return "cef_muni"
    if t in PFD: return "cef_preferred"
    if t in CONV: return "cef_convertible"
    if t in CREDIT: return "cef_taxable_credit"
    if t in OTHER: return "_other"
    return "cef_equity_multi"
ce["family"] = ce.ticker.map(fam)
re_ = dn[dn.ticker.isin(MREIT)][["permno", "ticker", "comnam", "shrcd"]].copy(); re_["family"] = "mreit"
out = pd.concat([ce, re_])
extra = [(t, "bdc") for t in BDC_NEW] + [(t, "cef_taxable_credit") for t in CREDIT_NEW] + [(t, "cef_equity_multi") for t in EQ_NEW]
out = pd.concat([out, pd.DataFrame([{"permno": None, "ticker": t, "comnam": None, "shrcd": None, "family": f} for t, f in extra])])
out["deployed"] = out.ticker.isin(DEPLOYED)
out = out.rename(columns={"ticker": "symbol"})
out.to_parquet(f"{SCR}/cef_classified.parquet")
print(out.family.value_counts().to_dict(), "deployed found:", out.deployed.sum())
missing = set(MREIT) - set(re_.ticker)
print("mREIT tickers not in CRSP shrcd 18/48 alive:", missing)
