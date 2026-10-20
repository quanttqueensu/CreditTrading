# CEFConnect terms: options for the live NAV path — 2026-10-19

**An options brief for the team lead (ruling 2026-10-19: brief today; the collector
stays unchanged until the team lead picks). Zero trials. No code changed.**
Branch `ops-cefconnect`. Every external claim is in `docs/REFERENCES.md` §12ad with
its status.

**This is not legal advice.** It quotes published terms as written and says what our
code does. Whether any use is permitted is for the data owners, or a lawyer, to say.

Fetches were made between 15:00 and 15:15 UTC on 2026-10-19 unless a row says
otherwise. Raw pages were kept in session scratch only, never committed, because the
repository is public and the pages are vendor content. Labels: **[V]** read today on
the owner's own page or in our own code or files; **[S]** sourced, not re-read;
**[U]** not established, with what was tried.

**Reproduce (§7).** These are page reads and a `git grep`, not a data series, so
there is no new script. The one count, Alpaca's asset list, reads the cache that
`scripts/data/cef_families_universe.py` wrote on 2026-10-12. The live-path line
numbers are as of main 832aeaa.

---

## 0. Read this first

1. **The terms are unchanged.** CEFConnect's page still says "These Terms were last
   updated on June 5, 2013", and every clause recorded in §12y on 2026-10-15 is word
   for word the same [V]. The site also carries **Morningstar's** notice that its
   information "may not be copied or distributed" [V]. So Nuveen's permission may not
   be enough on its own [U].
2. **CEFConnect is not the primary NAV source.** The primary is yfinance's `X<TK>X`
   symbol (Yahoo). CEFConnect is the session's fallback, the session gate's referee,
   and the collector's cross-check and arrival log (§1). Without it the primary does
   not change. What goes is the fill for a NAV Yahoo lacks, the stale-NAV gate's
   second trigger and every one of its resolutions, the only independent live NAV
   check, and the arrival measurement.
3. **Yahoo's terms forbid the same thing** (checked today; this answers the [U] left
   at `results/events/PREDICTION_MARKETS_ALT_DATA_2026-10-15.md` lines 133 and 587).
   They forbid collecting data "using any automated means ... for any purpose without
   our express, prior permission", and say "you may not access or reuse the Services
   ... for any commercial purpose" [V]. So the live NAV path's terms problem is not
   CEFConnect's alone.
4. **No free replacement is clean.** All five sponsors' terms restrict commercial or
   automated use [V]. EDGAR is free to reuse, but it carries no daily NAV [V]. Nasdaq
   Fund Network carries CEF NAVs, but its own data policy forbids their use "for any
   trading, advisory or marketing purposes" [V]. Alpaca's asset list holds no NAV
   symbol [V on 2026-10-12].
5. **Recommendation (§5).** First, send the Nuveen letter (§4) now. Second, keep the
   stale-NAV gate in `report` until Nuveen answers. Third, decide whether real capital
   needs a licensed NAV feed, because the primary source has the same problem. That
   reopens the 2026-09-08 decision "Free channels only" (`docs/SYSTEM.md`, the
   2026-09-08 table, row "NAV source"). If it does, test before buying: take a
   one-month commercial trial to measure CEF NAV coverage and timing on the 13
   names.

---

## 1. Inventory: every code path that fetches cefconnect.com

**Method.** `git grep -n -i cefconnect -- '*.py'` (33 files), then a grep for the
URL forms (`cefconnect\.com`, `api/v3`), then each caller traced by hand. Every
endpoint is unauthenticated JSON under `https://www.cefconnect.com/api/v3/`.

**Every live read goes through one function**, `scripts/cef/fetch_daily.py:137`
`_cefconnect_navs`: `GET .../pricinghistory/{TK}/1Y`, with the header
`User-Agent: Mozilla/5.0` (`:83`). It returns CEFConnect's NAV dated exactly D, and
D−1 when asked. It never reads CEFConnect's price or any other field. Each request
returns the fund's whole one-year daily window.

### 1.1 Live path (prod runs these unattended)

| # | caller | runs when | requests | used for | without CEFConnect |
|---|---|---|---|---|---|
| L1 | **Session refresh, the missing-NAV fallback.** `quantt/session/run.py:516` passes `--nav-fallback cefconnect`; the fill is at `scripts/cef/fetch_daily.py:258-274` | each decide attempt (evening 22:00–01:00 ET, morning backstop 06:00–15:15 ET, at :00 and :30) until a plan is decided | one per deployed name whose yfinance NAV dated D is **missing**; none otherwise | NAV(D) is written into `cef_nav.parquet` and logged to `data/cef/nav_fallback_log.csv` as `cefconnect` | that name has no NAV dated D, so `fetch_daily` exits 4 and gate 5 refuses. The next slot retries. If Yahoo never fills D before the cutoff, the day is missed. **How often it has fired:** the laptop prod clone (`~/prod/quantt-alpaca`, panel to 2026-10-07) has no `nav_fallback_log.csv`, so on the laptop the fallback never wrote a NAV [V, read 2026-10-19]. The VM era is [U] (not read: no ssh). |
| L2 | **Session stale-NAV gate.** `quantt/session/nav_gate.py:416` `PanelGate.run` → `cefconnect_navs` (`:153`) → the function above. Mode from `ops/books/cef_discount_book.json` `data.stale_nav`: **`report`** today | each decide attempt whose refresh passed (`run.py:640`) | one per deployed name (13) per attempt: D−1 and D in one request | trigger (2) `cc_prev`, NAV(D) = CEFConnect's NAV(D−1). The **resolution of every triggered name**: CEFConnect's D separates a stale copy (`on`: replaced, logged `cefconnect_stale_copy`) from a genuine repeat (kept) | trigger (2) never fires, and every name trigger (1) catches becomes `unverified` (`judge`, `nav_gate.py:286`). **In `report` no order changes**; only the record of what `on` would do is lost. **In `on`** every repeat defers to the morning, then is HELD from the final check. A day with many repeats holds the whole book: on the laptop replay, 9 names on 2026-10-05 (§12s). |
| L3 | **Collector `nav_crosscheck`.** `quantt/collect/collect.py:316`; the reader is wired at `:836` | every 30 minutes (:10, :40) until done, after `prices_nav` | one per deployed name (13) per attempt. Normally one attempt per data day; repeated each slot after a read error | **the only independent check** of the panel's NAV(D) (report only); also flags `nav_repeat_unverified` | a read error raises `StepFailed`: the day is `INCOMPLETE` (exit 5) at every slot and retried indefinitely. It never blocks trading. Without the step there is no live NAV cross-check at all. |
| L4 | **Collector `cefconnect_arrival`** (a watch step). `quantt/collect/collect.py:658` | every 30 minutes, from the data day's first slot until every name's D row has appeared or D moves on | one per not-yet-seen name per slot: up to 13 per slot, 48 slots a day. **The only step that reads at every slot** | when CEFConnect publishes D, logged to `<state>/cefconnect_arrival.csv`. It exists to set the gate's final-check time (`nav_gate.py` docstring, "WHY 90 MINUTES") | nothing trades on it. The measurement stops, and without CEFConnect it has no purpose. |

**Two consumers do not fetch.** `src/deploy/sleeves/cef_discount.py:220` `_nav_hold`
holds the names the gate holds. `quantt/collect/collect.py:304` `_fallback_names`
reads the fallback log.

**The send phase never reads CEFConnect.** It loads the decided plan and does not
re-decide (`run.py` docstring, "PAPER EXECUTION").

### 1.2 Correction to the record

`docs/REFERENCES.md` §12y (the "CEFConnect terms PROHIBIT" row, line 1169 before this
commit) said "The live **collector's** NAV fallback". The collector runs `fetch_daily`
**without** the fallback, on purpose (`quantt/collect/collect.py:281-292`, review
2026-09-29). The fallback is the **session's** refresh (`quantt/session/run.py:516`).
`docs/DATA.md` §2 has it right. The task brief for this note repeated the slip.
Corrected in place, dated, in this commit.

### 1.3 Request volume

**Not measured here.** The counts are in the VM's state (`<state>/data/<D>/status.json`
`polls`, `<state>/nav_gate.csv`, `<state>/cefconnect_arrival.csv`), which was not
read: no ssh [U]. From the code:

- L2: 13 requests per decide attempt.
- L3: 13 per attempt.
- L4: up to 13 for each slot until the D rows arrive.
- In the worst case one fund can be read four times in a half-hour. A collector slot
  can run L3 and L4 for the same name. A session attempt can run L1 and then L2.

### 1.4 Research (run by hand; never on the live path)

| caller | endpoint | used for |
|---|---|---|
| `scripts/data/cef_families_universe.py:70` | `DailyPricing`, one call: the CEF list with its Morningstar category, sponsor and `NavTicker` | C4 universe |
| `scripts/data/fetch_cef_families_cefconnect.py:70` | `pricinghistory/{TK}/{1Y,All}` | C4 NAV check |
| `scripts/data/fetch_cefconnect_distributions.py:84` | `distributionhistory/fund/{TK}/{start}/{end}` | C4's third distribution source |
| `scripts/data/fetch_cefconnect_closes.py:76` | `pricinghistory/{TK}/{1Y,All}`, the **close** as well as the NAV | C5 holdout: the second close source for 2025–26 (CRSP ends 2024-12-31) |
| `scripts/data/live_nav_quality.py:440` | `pricinghistory/{TK}/{1Y,All}` | the live NAV quality study (§12n) |
| `scripts/data/nav_gate_replay.py:185` | through `nav_gate.cefconnect_navs` | the gate replay (§12s) |
| `scripts/events/fetch_term_cef_live.py:53` | `pricinghistory/{T}/1Y` | term-CEF event candidates |
| `scripts/cef/wait_for_nav.py:89` | `pricinghistory/{TK}/1Y` | **dormant.** An IBKR-era poll that nothing schedules or imports; only a docstring at `ops/common.py:380` names it |
| `.claude/settings.json:42` | `WebFetch(domain:www.cefconnect.com)` | agents' manual page reads |

These read cached CEFConnect data without fetching: `scripts/cef/c4_families.py`,
`scripts/cef/c4_feasibility.py`, `scripts/cef/c5_open_auction.py` (`CC_FILE`),
`scripts/data/cef_families_quality.py`, `scripts/data/fetch_cef_families_yf.py` (NAV
symbols from CEFConnect's `NavTicker`) and `scripts/events/conditional_tender_census.py`
(`FAM_CC`). Without CEFConnect, C4 and
C5 lose an independent source on any re-fetch. Their gitignored caches are named in
the code; their contents were not re-read today.

---

## 2. The terms, re-fetched 2026-10-19T15:00:31Z

The page is `https://www.cefconnect.com/footer/legal.aspx` (HTTP 200).

- "These Terms were last updated on June 5, 2013."
- "All Content is solely for your personal, non-commercial use or that of your
  clients. Accordingly, you may not copy, reproduce, modify, sell, reuse, republish,
  post, frame, deep link, transmit, display, distribute or use for any commercial or
  unlawful purpose any Content ... without Nuveen's express written permission."
- Users may not, "without Nuveen's express prior written permission":
  - "use devices (including software) that are designed to provide repeated
    automated access to the Web Site/Mobile Apps other than those made generally
    available by Nuveen;"
  - "deep link or employ software or any automatic device, technology or algorithm,
    to "crawl", "scrape", search or monitor the Web Site/Mobile Apps, provided that
    generally available third-party web browsers may be used without Nuveen's
    authorization;"
  - "make use of any data mining, robots, or similar data gathering and extraction
    tools;"
  - "reproduce, duplicate, copy, sell, resell, visit, or otherwise exploit for any
    commercial purpose the Web Site/Mobile Apps."
- "CEFConnect.com data are supplied by the service provider, Morningstar."
- **Morningstar's notice** (`/Footer/MorningstarDisclaimer.aspx`): "The information
  contained herein: (1) is proprietary to Morningstar and/or its content providers;
  (2) may not be copied or distributed; and (3) is not warranted to be accurate,
  complete or timely."
- The terms are governed by Illinois law, with suits in Cook County or the Northern
  District of Illinois.
- **Where to write.** "Communications to Nuveen ... may be sent by mail to: Nuveen,
  LLC, 333 West Wacker Dr., Chicago, IL 60606, Attn: Webmaster." The CEFConnect
  Feedback form offers only "Fund Data Issues" and "Login/Registration Issues", and
  says "we are not able to respond to every inquiry". nuveen.com lists 800-257-8787
  (individual investors) and 800-752-8700 (financial professionals), each with an
  e-mail form.
- `https://www.cefconnect.com/robots.txt` returns 404: none is published. That
  neither permits nor forbids anything; the terms govern.
- No document was found in which Nuveen makes the `api/v3` endpoints "generally
  available" [U]. They are what the site's own pages call.

**Unchanged against §12y (2026-10-15).** The date and every quoted clause are
identical. The page's bytes differ between fetches by construction, because it embeds
an ASP.NET view state. So "unchanged" means the text, not a hash.

---

## 3. Replacement candidates

### 3.1 The sponsors' own sites

The 13 names come from `scripts/cef/spec.py` `UNIVERSE`, read 2026-10-19. Sponsors
are from `longName` in `data/cef/cef_facts.csv`. Only the date each NAV was "as of"
is recorded below, not the NAV values.

| sponsor | names | dated daily NAV on its own site? | terms, quoted | terms dated |
|---|---|---|---|---|
| PIMCO | PCN, PDI, PDO, PFN, PHK, PTY | **[U]**: no fund page found. `/us/en/investments/closed-end-funds` returns 404, the product finder renders only in a browser, three guessed fund URLs returned 404, and two searches found none | "Limited portions of the Content ... may be accessed, printed and downloaded on an occasional basis for personal, scholarly, research or non-commercial purposes". It also says you may not "“scrape,” data mine, or otherwise use any information or material obtained from or through this Site, without written permission from the PIMCO Companies". Permission: "650 Newport Center Drive, Newport Beach, CA 92660, 800-387-4626" | "Dated: June 2024" |
| BlackRock | BIT, HYT, MHD, MQY | **yes for MQY [V]**: its product page showed "NAV as of Oct 16, 2026" at 15:05Z. The other three were not opened | "Such content is solely for your personal, non-commercial use". You may not "Use any robot, spider, intelligent agent, other automatic device, or manual process to search, monitor or copy this Website or the reports, data, information, ... without BlackRock's permission" | none shown |
| Nuveen | JFR | **yes [V]**. The fund page fills from `api.nuveen.com/CEF/v2/productdetail/bycusip/67072T108`, which returned `dailypricing.navdate` 2026-10-16 and `navticker` XJFRX at 15:04Z | the CEFConnect clauses, word for word (nuveen.com terms) | "last updated on February 6, 2018" |
| DoubleLine | DSL | **yes [V]**. The page's "Daily NAV" block (`POST doubleline.com/wp-json/pedl/v1/block/`, `block_type=dnmp`) read "As of October 16, 2026" at 15:04Z. NAV symbol XDSLX | grants a "personal, revocable, non-exclusive, non-transferable, non- sublicensable right to view and use"; "You may not copy, reproduce, ... or otherwise use the Material in any other way for commercial or public purposes without prior written permission of the Company" | none shown |
| AllianceBernstein | AWF | **[U]**: no fund page found. The listing renders only in a browser, and three guessed URLs returned 404 | "You may not distribute, modify, transmit, reuse, repost, or use the content of this site for public or commercial purposes ... without AB's written permission"; "AB L.P. will aggressively enforce its intellectual property rights" | none shown |

**What this route would mean.**

- Five permissions, one per sponsor, instead of one.
- Three undocumented internal endpoints found, and two sponsors' pages not found.
- No sponsor documents a posting time (`docs/BRIEF.md` §3), and nothing found today
  changes that.
- In its favour: the NAV is the fund's own, which makes it the best referee for a
  stale copy, if it is there in time.

### 3.2 EDGAR

- **Reuse is free.** SEC: "All Government-created content on sec.gov and EDGAR
  public filing content are free to access and reuse" (§12y). The fair-access limit
  is 10 requests a second (§12g).
- **No daily NAV is filed.** Form N-PORT (the reference copy effective 2023-12-11,
  OMB expiry 2027-11-30) reports in Part B "Total assets", "Total liabilities" and
  "Net assets" (B.1). It also reports "Monthly total returns of the Fund for each of
  the preceding three months" (B.5). A text search finds no NAV-per-share item and
  no shares-outstanding item [V].
- **N-PORT is public late.** Only data "for the third month of each Fund’s fiscal
  quarter will be made publicly available upon filing". Reports for a quarter are
  filed "no later than 60 days after the end of such fiscal quarter" (rule 30b1-9 as
  in force; the monthly amendment is delayed to 2027-11-17 or 2028-05-18) [V].
- **NAV per share is in the shareholder report.** The report is "transmitted within
  60 days after the close of the period" (rule 30e-1(d)). N-CSR is filed "not later
  than 10 days after the transmission" (rule 30b2-1(a)). So it is semi-annual and up
  to about 70 days late [V].
- Offering documents (424B, 497) carry a NAV on particular dates, e.g. BIT's rights
  offering (§12n).
- **Verdict:** EDGAR cannot serve L1–L4. It is good only for period-end audits.

### 3.3 The consolidated tape, Nasdaq Fund Network, and Alpaca

- **Nasdaq Fund Network (NFN, formerly MFQS) covers CEFs.** The NFN Access
  Agreement's listing standards (PDF metadata dated 2025-12-22) have a tier "News
  Media List – Closed End Funds, Business Development Companies, Interval Funds,
  Tender Offer Funds", with "$60 million in net assets" to join and $30 million to
  stay [V]. The same document's sentence on what NFN supports "as of 2026" does not
  name closed-end funds; the tier table does. Both are reported as found. The
  `X<TK>X` symbols Yahoo serves have NFN's shape, but whether Yahoo's NAVs come from
  NFN is [U].
- **NFN's own licence forbids trading use.** The NFN Data Policies and Procedures
  v2.7 (2024-04-22), §6, say: "In no event shall a Distributor or Recipient use the
  information ... for any trading, advisory or marketing purposes" [V]. Other terms
  in the same document:
  - "Use of NFN Data to for validation or confirmation of any field ... is deemed to
    be the intellectual property of Nasdaq and must be licensed accordingly."
  - Non-display use "always requires the Recipient to License directly with Nasdaq".
  - Fees are "on the price list published on NasdaqTrader", which was **not
    fetched**: nasdaqtrader.com answered every request with a bot challenge [U].
  - "To enquire about specific use cases that may be fee exempt, please contact your
    Nasdaq sales representative."

  The contact is nasdaqfundnetwork@nasdaq.com (NFN fact sheet). **As written, NFN's
  licence forbids this book's use.**
- **The consolidated tape (CTS) spec has NAV suffixes.** The CTS Pillar output
  specification (v2.11b, 2026-01-29) lists, among its "symbol and index suffix
  examples", `.NV`: "Net Asset Value per share as at the close on the previous day’s
  close of trading". It also lists `.IV`: "Intra-Day Net Asset Value per share" [V].
  Whether NYSE disseminates a `.NV` value for any of our 13 CEFs is [U]; the table
  lists examples only. The UTP binary output specification (v4.1, September 2026)
  has no NAV or mutual-fund field (text search) [V].
- **Alpaca (documentation only, no key).**
  - "Securities coverage | US Stocks & ETFs" (About Market Data, updatedAt
    2026-10-06).
  - The SIP feed "covers all US exchanges ... consolidated by the Securities
    Information Processors: UTP (Nasdaq) and CTA (NYSE)". OTC data needs a
    broker-partner subscription.
  - No page mentions fund NAV symbols or index values [V].
  - Alpaca's active US-equity asset list, read 2026-10-12T18:27Z (14,401 assets,
    cached by `scripts/data/cef_families_universe.py`), contains none of the 13
    `X<TK>X` symbols, no five-letter `X???X` symbol at all, and no `.NV` symbol [V
    on that date].
  - Whether the data API would answer a NAV symbol was not tested, because no key
    may be used here [U]. Nothing documented suggests it would.

### 3.4 Licensed feeds with a published price

| vendor | published price, read 2026-10-19 | coverage it claims | the catch |
|---|---|---|---|
| EODHD | Commercial "Internal use / Single-company use": **$399.00 a month** ($3,990 a year). Enterprise: $2,499.00 a month. Personal plans start at $19.99 a month and are for personal use only. A professional user is anyone using the data "As part of a business activity" | end-of-day data "for stocks, ETFs, mutual funds"; "US mutual funds ... update only the next morning, starting at 3-4 am ET and usually ending at 5-6 am ET" | Coverage of CEF NAV symbols is [U]. Its own disclaimer says "prices are indicative and not appropriate for trading purposes", sourced from "OTC, peer to peer trades and trading platforms over 100+ sources". The upstream licence for fund NAVs is [U] |
| Tiingo | "$30/month (or $300/year) for individuals and $50/month (or $499/year) for internal commercial use"; "Internal use means you may only use the data for your own personal use" (quoted through WebFetch) | "ETFs & Mutual Funds" | NAV coverage is not stated, so CEF NAVs are [U]. Whether "internal use = personal use" covers a fund book is [U] |
| Bloomberg, LSEG, FactSet, Morningstar data feeds, ICE | no published price found | — | [U]: price only on request; not pursued |

Both published-price vendors need a paid key before CEF NAV coverage, timing and
agreement with the sponsors' NAVs can be tested. A one-month trial measures all three.

*Update 2026-10-19 (`results/ops/NAV_SOURCE_WORKAROUND_2026-10-19.md` §2; REFERENCES
§12ar):* coverage is no longer [U]. Tiingo's public ticker list has all 13 `X<TK>X`
symbols under exchange code `NMFQS` (NFN), and EODHD has a public page for each.
EODHD's page shows an adjusted series, and its upstream is still [U]. Tiingo's terms
require "an organization or business" to use its Commercial plan, and forbid storing
data on a trial plan.

### 3.5 Yahoo, the primary source

This was not in the brief, but it changes the answer. Yahoo's terms
(`legal.yahoo.com/us/en/yahoo/terms/otos/index.html`, foot of page "Last updated: 4
August 2026") say users must not "access or collect data, or attempt to access or
collect data, from our Services using any automated means, devices, programs,
algorithms or methodologies, including but not limited to robots, spiders, scrapers,
data mining tools, or data gathering or extraction tools, for any purpose without our
express, prior permission". They also say "Unless otherwise expressly stated, you may
not access or reuse the Services, or any portion thereof, for any commercial purpose"
[V]. yfinance's own README says "Remember - the Yahoo! finance API is intended for
personal use only" [V]. No commercial data licence from Yahoo was looked for [U].

---

## 4. Draft permission request to Nuveen

The team lead sends this from their own address. Bracketed items are theirs to fill or
delete. It names no account, server or vault.

> **To:** Nuveen, LLC, 333 West Wacker Dr., Chicago, IL 60606, Attn: Webmaster
> (and through the "Send us an email" form under "Contact us" on nuveen.com, or
> the CEFConnect Feedback form)
> **Subject:** Request for written permission: automated access to CEFConnect NAV
> history for 13 funds
>
> Dear Nuveen CEFConnect team,
>
> I run QUANTT, a small systematic research team [organisation, if any]. We study
> closed-end funds and trade a paper account, with real money planned. Our software
> reads CEFConnect's daily NAV history automatically. Your Terms of Use (last updated
> 5 June 2013) require Nuveen's express written permission for automated access and
> for commercial use, and we are asking for it. If this is the wrong place to ask,
> please tell us who to write to.
>
> **What we read.** `https://www.cefconnect.com/api/v3/pricinghistory/{TICKER}/1Y`
> for 13 funds: AWF, BIT, DSL, HYT, JFR, MHD, MQY, PCN, PDI, PDO, PFN, PHK, PTY. We
> use only the dated NAV. It checks our primary NAV source, and it replaces a value
> that source has left stale. Occasionally, for research, we also read
> `/api/v3/pricinghistory/{TICKER}/All`, `/api/v3/DailyPricing` and
> `/api/v3/distributionhistory/fund/{TICKER}/{start}/{end}`, for at most a few
> hundred funds, a few times a year.
>
> **How often.** We propose at most [one] request per fund per 30 minutes, from one
> server, with a User-Agent that names us and gives a contact address. We will keep to
> any lower limit you set. [Optional: Since September 2026 our software has read
> these endpoints more often than this at times; we are writing now that we have read
> your terms.]
>
> **What we do with it.** Internal use only. We do not display, publish, resell or
> redistribute the data. [Optional: our code is public, but the data are never stored
> in it.] We will delete the data on request.
>
> The site says the data are supplied by Morningstar. If Morningstar's consent is also
> needed, please tell us whom to ask.
>
> If you would rather we did not access the site this way, please tell us and we will
> stop.
>
> Yours sincerely,
> [Name] · [e-mail] · [telephone]

---

## 5. Options

| option | what changes on the live path | cost | risks | evidence |
|---|---|---|---|---|
| **A. Keep using CEFConnect and ask Nuveen** (§4) | nothing now. After a yes: an identifying User-Agent (`fetch_daily.py:83`) and whatever cap Nuveen sets | $0 and a letter | no reply, or a refusal. Permission can be revoked. Morningstar's consent may also be needed. Until then the use continues against the terms as written | terms [V]; Nuveen's answer [U] |
| **B. A, and cut the footprint while waiting** | stop L4 (the arrival poll, measurement only); L1, L2 and L3 unchanged | a small collector change, with tests | loses the arrival measurement that the gate's `on` decision rests on. Does not cure the terms | code [V] |
| **C. Stop CEFConnect on the live path, with no replacement** | the `--nav-fallback` flag, L3 and L4 go; the gate cannot resolve anything | a small code change | `on` becomes "hold every repeat". No independent NAV check. Yahoo's stale copies go unchecked: 28 of 73 checkable laptop name-days were decided on one (§12n) | §12n, §12s [V] |
| **D. The sponsors' own sites** | new per-sponsor readers for L1–L3 | no fees; five scrapers on undocumented endpoints | five permissions instead of one. PIMCO (6 names) and AB pages not found. Posting times undocumented | terms [V]; pages [V]/[U] |
| **E. EDGAR** | none possible | — | no daily NAV | [V] |
| **F. Nasdaq Fund Network, direct** | L1–L3 from the official NAV feed | price list not fetched [U] | §6 forbids trading use; needs a written waiver | policy [V] |
| **G. A commercial vendor with a published price** | a licensed fetcher for the primary NAV, the check, or both | $499 a year (Tiingo, internal commercial, annual) to $3,990 a year (EODHD internal use, annual) at the published prices, plus engineering | CEF NAV coverage and timing are [U] until a trial. EODHD says its prices are "not appropriate for trading purposes". The upstream licence is [U]. Reopens "Free channels only" | prices [V]; coverage [U] |
| **H. An enterprise feed** (Bloomberg, LSEG, FactSet, Morningstar) | as G | unpublished [U] | cost unknown | [U] |

### Recommendation

1. **A, now.**
   - It costs nothing and changes nothing on the live path.
   - It keeps the only working referee for Yahoo's stale copies.
   - One reply covers every live use; D needs five letters and covers less.
   - The alternatives are worse. C gives that referee up. E cannot serve. F
     forbids trading use as written.
2. **Keep the stale-NAV gate in `report` until Nuveen says yes, or a replacement is
   in.** Turning it `on` would make the order path depend on access the terms
   forbid.
3. **Treat Yahoo as the larger exposure.** The primary NAV source carries the same
   restriction (§3.5). Before real capital the book needs a primary NAV source it may
   use for trading.
   - A yes from Nuveen could cover the primary too, but only if CEFConnect's D rows
     arrive before the decide. The evidence so far is three laptop readings: absent
     at 00:10 ET on D+1, present by 11:41 ET on D+1, and a Friday row still absent at
     09:40 ET on Saturday (`nav_gate.py` docstring). The
     collector's arrival log (L4) measures it, which is a reason to keep L4
     running.
   - Run G as a one-month trial. EODHD's commercial internal-use plan is the
     cheapest published commercial licence found. *Corrected 2026-10-19: it is not.
     Tiingo's Commercial plan, $50 a month or $499 a year in the table in §3.4, is
     cheaper, and Tiingo's terms make it the plan "an organization or business" must
     use. Both vendors' CEF NAVs may come from NFN, whose §6 bars trading use, so
     `results/ops/NAV_SOURCE_WORKAROUND_2026-10-19.md` §5 recommends asking Nasdaq
     before any trial.* Measure, on the 13 names:
     coverage; the time NAV(D) becomes available (the vendor says 3–6 am ET the next
     morning); and agreement to the cent with the sponsors' NAVs.
   - If the trial covers all 13 names before the morning backstop, G can replace
     Yahoo as the primary and CEFConnect as the referee. If it does not, nothing
     free replaces either.
   - Ask EODHD in writing whether "not appropriate for trading purposes" excludes
     this use.
   - In parallel, ask Nasdaq (nasdaqfundnetwork@nasdaq.com) whether §6 can be waived
     and at what price.

The reason for this order: A is free and reversible. G is the only route found with
a published commercial licence. The primary source is no better placed than
CEFConnect.

### Decisions for the team lead

1. **Send the §4 letter from your address?** If so, set the request cap in it and
   choose whether to keep the two bracketed optional sentences.
2. **Until Nuveen answers, A or B?** A leaves the live path exactly as it is (your
   2026-10-19 ruling). B stops the arrival poll, which is the only step that reads
   every slot. It is also the measurement that says whether CEFConnect could ever
   serve as the primary (§5, recommendation 3).
3. **Confirm the stale-NAV gate stays `report`** until permission or a replacement.
4. **The primary NAV source.** Does real capital need a licensed NAV feed? That
   revisits "Free channels only" (2026-09-08). If yes, authorise a one-month
   commercial trial (EODHD, $399 published) and the Nasdaq NFN enquiry.

---

## 6. Could not verify

- How many requests the VM's collector and session send each day, and when
  CEFConnect's D rows arrive on the VM. Both are in the VM's state, which was not
  read (no ssh).
- Whether Morningstar's consent is needed on top of Nuveen's.
- Whether Nuveen regards the `api/v3` endpoints as "made generally available".
- PIMCO's and AllianceBernstein's fund pages, and whether they show a dated daily
  NAV. Tried: the landing pages (404 or browser-only), three guessed URLs each (404),
  and two web searches each.
- The NFN price list. nasdaqtrader.com answered with a bot challenge, and WebFetch
  was redirected to an error page.
- Whether NYSE disseminates `.NV` for our CEFs over CTS.
- Whether Alpaca's data API answers a NAV symbol (untested: no key may be used).
- Whether EODHD or Tiingo carry CEF NAVs (`X<TK>X`), and from which upstream.
  *Answered 2026-10-19 (`results/ops/NAV_SOURCE_WORKAROUND_2026-10-19.md` §2): both
  list all 13; Tiingo's exchange code is `NMFQS` (NFN); EODHD's upstream is still [U].*
- Whether Yahoo's NAVs come from NFN, and whether Yahoo offers a commercial licence.
- Anything legal: this note is not legal advice.

## 7. Reproduce

There is no script: these are page reads, not a data series.

- **The terms.** `curl -sSL -A "Mozilla/5.0" https://www.cefconnect.com/footer/legal.aspx`
  and `/Footer/MorningstarDisclaimer.aspx`.
- **The sponsors' terms.** `https://www.nuveen.com/en-us/terms`,
  `https://www.blackrock.com/corporate/compliance/terms-and-conditions`,
  `https://www.pimco.com/us/en/general/legal-pages/legal-disclaimer`,
  `https://doubleline.com/terms-of-use/` and
  `https://www.alliancebernstein.com/corporate/en/footer-disclosure/terms-of-use.html`.
- **Yahoo.** `https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html`.
- **The regulations.** eCFR versioner, title 17 part 270 sections 30b1-9, 30e-1 and
  30b2-1, at 2026-10-15 (send `Accept-Encoding: gzip`). Form N-PORT at
  `https://www.sec.gov/files/formn-port.pdf`.
- **Nasdaq.** The NFN policy is
  `https://www.nasdaqtrader.com/content/AdministrationSupport/Policy/nasdaqfundnetworkpolicy.pdf`,
  and the listing standards are
  `https://m.nasdaqtrader.com/content/AdministrationSupport/AgreementsData/mfqslistingstandards.pdf`.
  Both are reachable through WebFetch only.
- **The tape specifications.** CTS is
  `https://www.ctaplan.com/publicdocs/ctaplan/CTS_Pillar_Output_Specification.pdf`
  and UTP is `https://utpplan.com/DOC/UtpBinaryOutputSpec.pdf`.
- **Alpaca.** `https://docs.alpaca.markets/us/docs/{about-market-data-api,historical-stock-data-1,market-data-faq}.md`.
- **The asset list.** `data/cef_families/raw/alpaca_assets_active_2026-10-12.json`,
  read with the standard library.
- **The vendors.** `https://eodhd.com/commercial-pricing`, `https://eodhd.com/pricing`,
  `https://eodhd.com/financial-apis/api-for-historical-data-and-volumes`,
  `https://eodhd.com/financial-apis/terms-conditions` and
  `https://www.tiingo.com/about/pricing` (WebFetch).
- **The inventory.** `git grep -n -i cefconnect -- '*.py'` and
  `git grep -n 'cefconnect\.com\|api/v3'`.
