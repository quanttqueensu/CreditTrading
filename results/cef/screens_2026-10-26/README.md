# Five zero-trial screens, 2026-10-26

The team lead asked what to do next as PM, whether macro regime filters would help, and which
event angles to try. They chose these five screens and asked for gross P&L only: "don't
overcomplicate it with costs". **No trial was spent and no counter moved.** Every return is dated
on or before 2022-12-30, which each script asserts. The 2023-01-01 time holdout and the 27 sealed
`cef_universe.csv` names were not read.

| folder | question | verdict | headline [V] |
|---|---|---|---|
| `r1_macro_state/` | Does a group's own macro observable (HY OAS; SIFMA; repo) change the deployed signal's within-group IC? This is a zero-trial preview of C2 Part D. | **NOTHING** | No own-observable split reaches \|t\| 2. The mismatched-observable control scores the same. Within-muni IC is −0.077 to −0.123 in every SIFMA state. |
| `r2_macro_days/` | Do discount moves on FOMC/CPI/NFP days revert more than same-size moves on other days? | **NOTHING** | Extra price-leg reversion −6.9bp per unit (t −0.36). Placebo weeks score +19.1 (t +0.97). Ordinary-day reversion runs through price, −37.3 (t −3.39), not NAV. |
| `r3_c4_exdate/` + `r3_review/` + `r6_exdrift/` | Is C4's ex-date P&L concentration (82.1% committed / 52.6% corrected holdout; 33.1% fit) real? | **MIXED** after the independent review | The post-ex drift is real and generic, and shorting into any ex-date earns it. Once that profile is removed, the C4-specific window excess is t 1.69 against the 2.0 bar. Paper overstates C4: price-only Sharpe 1.360 vs total-return 1.217 on the fit. |
| `r4_index_rebal/` | Do YYY/PCEF/XMPT reconstitutions force flow ≥ 1 ADV that a `shift(2)` book can trade? | **INFEASIBLE** without R2 | A full add or drop is 1.65–4.1 days of ADV. Only 7 dated qualifying events, against the 30 needed. |
| `r5_bdc/` | Does the discount z-score work on BDCs? | **INFEASIBLE** without R2 | 0 BDCs have ≥ 20 quarters of point-in-time NAV in 2012–22 locally. |

## The finding that came out of r3: the post-ex-date drift

A second method in `r6_exdrift/` is independent of `c4_families.py`. It computes its own total returns,
measured against the same-date equal-weight mean.

- On C4's families, a short at the ex-date close covered at +3 earns **CAR(+1..+3) −34.3bp (t −14.9,
  month-clustered) on 2005–22**, and −30.1bp (t −5.6) on every year in the panel (1982–2022).
  *Corrected 2026-10-27: this line first gave the 1982–2022 figure without saying so.*
  - With Eaton Vance excluded it is −34.8bp (t −14.3) on 2005–22, and −30.0bp on 1982–2022.
  - It is negative in 2005–09, 2010–15 and 2016–22.
  - It is larger for larger distributions.
- On the 17 credit CEFs it is **−20.5bp (t −6.8)**.

**It was found after the fit window was seen, so it is a hypothesis, not evidence.** *Provenance, corrected 2026-10-27:* W4 recorded the same pattern first, on the credit funds (`results/cef/W4_ARTIFACTS_2026-10-11.md` §1, "Ex-date arithmetic": the discount falls a further −0.306pp and −0.197pp over the two sessions after the ex-date, "a post-ex-date price pattern, not arithmetic"), as an observation it did not test. The 2026-10-26 review rediscovered it. A
pre-registration draft is with the team lead.

## How to reproduce

The runs used an export of `simon` at `dff4b5c`, with `data/` linked in, and **cwd = the repo root**.
Paths inside the scripts are relative to each script's own folder (`HERE`), so run them from the root:

```bash
python3 -B results/cef/screens_2026-10-26/r1_macro_state/r1_macro_state.py
python3 -B results/cef/screens_2026-10-26/r2_macro_days/r2_macro_days.py
python3 -B results/cef/screens_2026-10-26/r6_exdrift/check.py .
python3 -B results/cef/screens_2026-10-26/r6_exdrift/check_credit.py .
```

What is not in the repo, and why:

- **Fetched raw files** (FRED, SIFMA, the Fed's FOMC pages, Wayback snapshots) were left out
  because this repository is public. Re-fetch them with each folder's `fetch_*.py` into its `raw/`.
  Each NOTE.md names its sources and fetch times.
- **CRSP data.** `r3_c4_exdate/`, `r3_review/` and `r5_bdc/` read CRSP from local research-worktree caches
  (licensed; never committed). Those runs need the same caches staged first.
