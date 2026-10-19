# The event engine's free pilot: a rules-only baseline, and a subagent reading pilot made ready — 2026-10-19

**What this is.** `results/events/EVENT_ENGINE_DESIGN_2026-10-15.md` §11 asked
for about $49 of API spend, to run Haiku 5.5, Sonnet 5.5 and Opus 5.5 once each
over its 50-filing gold set. On 2026-10-19 the team lead declined that spend and
chose both free options:

- **(a) a rules-only baseline**: deterministic, with no model. It is built,
  run and scored here (§1).
- **(b) a pilot read by Claude Code subagents** on the subscription, with no API
  key. It is prepared here (§2) for the lead agent to launch last today. **It has
  not run, and no model score appears in this note.**

**Zero trials.** No return, P&L or signal is computed, and no counter moves. No
price is read and no holdout is touched. **No API was called and no key was
read.** Every input is the public EDGAR text already cached for the design
note: 50 texts, each byte-identical to the manifest's sha256.

**Reproduce.**

```bash
python3 scripts/events/event_engine_rules.py --version 1   # rules v1 as first frozen -> event_engine/rules_v1/, scores
python3 scripts/events/event_engine_rules.py               # rules v2 (current)       -> event_engine/rules/, scores
python3 scripts/events/event_engine_pilot.py references    # pass A, pass B, rules v1/v2 on the pilot's cells
python3 scripts/events/event_engine_pilot.py prepare --root <ROOT>   # the pilot's inputs, batches, brief (out of tree)
python3 scripts/events/event_engine_pilot.py collect --root <ROOT>   # after the subagents: copy, validate, score
python3 -m pytest scripts/events/tests/test_event_engine_pilot.py
```

The scripts need the 50 texts in the gitignored
`results/events/_cache_event_engine/text/` (`event_engine_sample.py --offline`
rebuilds them). The rules also need the 50 raw submissions in
`results/events/_cache_edgar/`. In this worktree both were copied from the
`ss-event-engine` worktree, and every text was checked against
`sample_manifest.csv`'s sha256: 50 of 50 matched, and so did re-rendering the
raw submissions. `load_texts` raises on any mismatch.

**Labels.** [V] means measured by the scripts above on 2026-10-19. [S] means
sourced and not re-measured. [U] means uncertain. The sources are in
`docs/REFERENCES.md` §12aj and §12z.

---

## 0. The answer

- **Rules get triage almost free, but only about 60% of the terms.**
  - Rules v2 on the whole text: kind 0.98 (49 of 50), document role 1.00,
    fund type 0.92.
  - On the 389 gold term values: precision 0.886, recall 0.658 [V].
  - **On the 25 filings whose texts the rule-writer never opened: 0.875 /
    0.612**. That is the honest figure.
  - Against that, the prototype's Opus 5.5 readers scored 0.961 / 0.961 (pass
    A) and 0.977 / 0.979 (pass B) on the same gold [V].
- **When a rule fires, it is usually right.** On the test filings, numbers,
  dates and flags have precision 1.00, so a wrong rule value is rare. Recall is
  where a model earns its cost:
  - numbers 0.42, dates 0.75 and percents 0.71 (test);
  - condition sets 0.13;
  - free text 0.17.
- **What rules read reliably** (recall and precision ≥ 0.875 on all 50):
  - the Schedule TO cover's share class, % of NAV, pro-ration and expiry;
  - nearly every rights-offering term;
  - a merger's exchange basis.

  This supports the design's §5.5 dual extraction for "the easy fields", which
  rules can carry.
- **What rules cannot read:**
  - closing-condition sets (0 of 19 merger sets exact);
  - the number of targets (no rule was written);
  - trigger origin, a judgement;
  - results printed in tables;
  - the stated expected close;
  - merger outside dates.
- **The pilot** (§2) reads the first 120,000 characters of each filing, cut at a
  line break, in full, with no searching.
  - Of the design's input candidates, this one recovers the most gold values
    that fit a subagent: 353 of 389 (0.91) [V].
  - It cannot answer the design's whole-filing question for the 25% of merger
    values that sit deeper in the filing, mostly condition sets and outside
    dates (§2.2).
  - The work is 18 batches per model, 54 subagents in all. The brief, the
    batches and the collector are ready (§2.4).
- **The gold is Opus 5.5's own reading** (§2.3). An Opus subagent scored
  against it is partly scored against itself. Read every model-versus-gold
  disagreement against the text before calling a gap between models a gap in
  reading skill.

---

## 1. The rules-only baseline

### 1.1 What the rules read, and how they were written

The extractor is `scripts/events/event_engine_rules.py`. It reads:

- the EDGAR form type;
- the SEC header's company names (used only for the ETF test);
- regular expressions over the same rendered text the readers had. These cover
  the Schedule TO cover, the 424B cover, the N-14 letter and notice, the
  "Conditions of the Offer" and "Conditions Precedent" sections, and
  keyword-anchored clauses anywhere in the text.

Its output is the readers' JSON shape. Every non-null value carries the exact
substring it came from and its `doc_seq`. **Span and value-in-span failures:
0 of 294 values (v2) and 0 of 287 (v1)** [V].

**There are no silent defaults.** A field no rule reads is null. The
extractor carries two of the gold's written rules (design §7.2), because each
is a reading of words, not a prior:

- "equal to the net asset value" means 100% of NAV;
- the commencement date is the Offer to Purchase's date.

**The split was drawn before any rule was written.** `split()` is seeded
(20261019) and grouped:

- T and M by episode, so an offer and its final amendment fall on one side;
- R by filing agent, so the Clough/Liberty template sits on one side.

That gives 25 **dev** filings, whose texts the author read while writing rules,
and 25 **test** filings, whose texts were never opened.

**Two leaks remain:**

1. The author printed the gold values of all 50 filings once, before the split,
   to learn the output shape.
2. The Eaton Vance tender template is on both sides (EFT and EVF in dev, EVG in
   test).

Both flatter the test score, so the test numbers are an upper bound for unseen
filings of these kinds.

**Two versions:**

- **v1** was frozen and scored first.
- **v2** changed nine rules. Each change is motivated in its docstring by a
  named *dev* failure, and each is gated on the version, so `--version 1`
  reproduces v1 byte for byte (checked).
- **One defect is known and deliberately left in.** It was found from *test*
  errors and not fixed, so that the test score stays clean. The rights
  "market" pattern accepts "85% of the *reported* net asset value", which
  turns Clough's "85% of NAV or 95% of market, whichever is higher" into
  price 85% (3 test misses).

### 1.2 Scores [V] (`rules_v1_scores.json`, `rules_v2_scores.json`)

The convention is the design's: a wrong value counts as both a false positive
and a false negative; triage fields are scored separately.

| reader | filings | kind | fund type | doc role | term cell accuracy | term precision / recall |
|---|---:|---:|---:|---:|---:|---|
| rules v1, all | 50 | 0.98 | 0.84 | 0.94 | 0.726 | 0.826 / 0.609 |
| rules v1, test | 25 | 0.96 | 0.92 | 0.96 | 0.749 | 0.841 / 0.607 |
| rules v2, all | 50 | 0.98 | 0.92 | 1.00 | 0.768 | 0.886 / 0.658 |
| rules v2, dev | 25 | 1.00 | 0.92 | 1.00 | 0.779 | 0.894 / 0.699 |
| **rules v2, test** | **25** | **0.96** | **0.92** | **1.00** | **0.756** | **0.875 / 0.612** |
| pass A (Opus 5.5, whole filing, agentic) | 50 | 1.00 | | | 0.968 | 0.961 / 0.961 |
| pass B (the same, batched differently) | 50 | 1.00 | | | 0.983 | 0.977 / 0.979 |

- **v2's gains were on dev**: recall rose from 0.612 to 0.699. On test,
  recall moved only from 0.607 to 0.612, and precision rose from 0.841 to
  0.875. This is the expected signature of fixing rules on the filings you read.
- **The one triage miss is in test.**
  - v2 reads RMR Mortgage Trust's 425 as a fund `merger`; the gold says
    `equity_mna`, because the filer is a REIT. v2's narrower REIT phrase no
    longer fires on RMR.
  - v1 got RMR right but called the Duff & Phelps 425 `equity_mna`, because
    the old REIT phrase fired on a holdings description.

**By type, v2** [V]:

| type | all 50: precision / recall | test 25: precision / recall | passes A and B (design §7.3) |
|---|---|---|---|
| flags (bool) | 0.97 / 0.94 | 1.00 / 0.94 | 1.00 |
| dates | 0.98 / 0.80 | 1.00 / 0.75 | 0.985 / 0.978 |
| classifications (enum) | 0.91 / 0.81 | 0.86 / 0.74 | 0.986 / 0.984 |
| numbers | 0.98 / 0.47 | 1.00 / 0.42 | 1.00 |
| percents | 0.92 / 0.76 | 0.83 / 0.71 | 1.00 |
| condition sets | 0.14 / 0.10 | 0.22 / 0.13 | 0.806 / 0.806 |
| free text (expected close) | 0.80 / 0.29 | 1.00 / 0.17 | (in classifications) |

By stratum (v2, all 50): rights 0.95 / 0.90, tenders 0.91 / 0.70, mergers
0.74 / 0.41.

### 1.3 Which fields rules get right, and where they fail (v2, all 50; `rules_v2_field_scores.csv`)

| verdict | fields (true positives / gold values) |
|---|---|
| **Right**: precision and recall ≥ 0.875 | tender `security_class` 20/20, `price_pct_nav` 14/15, `proration` 16/16 (1 false positive: GDV's preferred tender), `expiration_date` 17/18; merger `exchange_basis` 15/16; rights `rights_per_share` 8/8, `rights_per_new_share` 8/8, `record_date` 8/8, `transferable` 8/8, `over_subscription` 8/8, `security_class` 8/8, `price_floor_pct_nav` 5/5, `expiration_date` 7/8, `price_reference` 7/8; triage `kind` 49/50, `doc_role` 50/50, `fund_type` 46/50 |
| **Partial**: precision ≥ 0.875 and recall 0.5–0.8 | tender `commencement_date` 14/18, `price_basis` 15/20, `size_pct_outstanding` 10/15, `size_shares` 9/17, `shares_tendered` 4/8, `proration_factor_pct` 2/4; merger `meeting_date` 4/5, `record_date` 3/5, `security_class` 14/17; rights `max_new_shares` 5/8 |
| **Fail**: recall below 0.45 | merger `conditions` 0/19 exact sets (11 false positives); tender `conditions` 3/11 (precision 0.30); merger `n_targets` 0/19 (no rule written); tender `trigger_origin` 6/15; `shares_accepted` 2/9; `final_price_per_share` 3/8; merger `expected_close` 4/13; `termination_date` 2/6; rights `price_pct` 3/6 (the Clough defect, §1.1); the one equity M&A filing 0/7 (its kind was missed) |

**Why the failures happen:**

- **Condition sets are scored as exact sets.** A keyword map over a "Conditions"
  section finds some categories and invents others: "fiduciary" and
  "investment objective" stand for `other`, and listing covenants are not
  conditions. One missing or extra category fails the whole cell. The design
  found the same field hardest for models (0.81). For rules it is hopeless.
- **Results live in tables.** The Eaton Vance results are a four-fund table
  with one row per ticker, so reading them needs a table parser per template.
  Sentence results ("75,266,484 Shares ... were validly tendered") are read.
- **Judgement fields.** `trigger_origin` turns on why a tender exists. A
  standstill exhibit marks an activist settlement, but a merger-related tender
  in the same template (EVG) reads the same.
- **Free text is scored by equality.** `expected_close` is compared after
  lower-casing and stripping punctuation. A rule capturing "first half of 2022"
  misses the gold's "first half of calendar year 2022".
- **Counted and deep values.** `n_targets` is a count of named funds, not a
  printed number. Outside dates sit in the agreement appendix. Rules for these
  would be per-template.

### 1.4 What this says for the design

1. **Tier 0 can do more than drop forms.** Kind and document role from the
   form type plus cover rules are right on 49 and 50 of 50. The cover rules
   are the Schedule TO's final-amendment box and the 424B cover's
   rights-offering mechanics. That is the same evidence the design's tier 1
   (Haiku on the cover) would read, at no cost.
2. **Dual extraction is cheap where it matters.** On the fields where rules
   fire with precision 1.00 (numbers, dates and flags on the covers), a
   model–rules disagreement is a strong review signal at zero marginal cost.
   That is §5.5 of the design, now measured on these fields.
3. **Rules are not a substitute for the model on terms.** Rules miss a third to
   two-fifths of the gold values (recall 0.61 on test), and every hard field
   the design names (conditions, judgement fields, deep merger terms) is
   among those misses.

---

## 2. The subagent pilot, made ready

### 2.1 The input mode, and why

A subagent cannot take one whole filing as a single input: the mean is ≈ 142k
estimated tokens and the largest is ≈ 659k (design §8). A subagent left to
search a long filing measures its searching, which is what the prototype's
readers did (design §7.2). So **every model reads the same fixed input in full,
with no search**. Coverage below is the share of gold values whose every quote
lies inside the input [V]:

| input (design §7.4) | gold values recoverable | of which merger | estimated tokens: mean / largest filing | fits a subagent? |
|---|---:|---:|---|---|
| first 8,000 characters (cover) | 0.57 | 0.40 | ≈ 3k / ≈ 3k | yes; triage only |
| cover + keyword sections | 0.84 | 0.70 | ≈ 41k / **≈ 248k** (Barings N-14 8C, 666k characters) | **no**, for one filing |
| **first 120,000 characters, cut at a line break (chosen)** | **0.91 (353 of 389)** | **0.75 (84 of 112)** | **≈ 31k / ≈ 45k** | **yes** |
| whole filing | 1.00 | 1.00 | ≈ 142k / ≈ 659k | no |

The "cover + keyword sections" mode was a candidate. It is beaten on both axes:
it recovers fewer values at a larger mean size, and its largest filing does not
fit. The prefix mode was chosen from the design's own pre-declared candidates,
not from a selector tuned to the gold.

Token figures use the design's estimate of 2.69 characters a token [S, §12z].
They are not counted.

### 2.2 What the excerpt cannot answer, against the design's whole-filing question

1. **36 of 389 gold values (9%) lie beyond the cut**, and 28 of the 112 merger
   values (25%):
   - merger condition sets: 12 of 19;
   - tender commencement dates: 6;
   - merger outside dates: 5;
   - exchange basis: 3;
   - number of targets: 2;
   - security class: 2;
   - one each: a tender condition set, a size percent, the equity M&A
     condition set, a collar, an expected close and a record date.

   So the pilot **cannot say whether a model finds a condition set or an
   outside date in an agreement appendix 160k–510k characters in.** That is
   the design's hardest field and the reason its tier 2 sends the whole
   filing. The collector scores every model on all cells and on the
   recoverable cells. **The recoverable score measures reading. The all-cells
   score measures this input, not the model.**
2. **Long-context reading.** The design's question is a single call holding up
   to ~659k tokens. The pilot shows each model at most ~45k estimated tokens
   per filing, and about 90k per batch.
3. **Tokens and cost.** Subscription usage is not a token count, so no
   `count_tokens` is run and thinking tokens stay unmeasured. The design's §8
   cost table remains an estimate.
4. **The API call itself.** A subagent is an agent with a system prompt and
   tools, not a bare Messages call with a tool schema. The aliases `haiku`,
   `sonnet` and `opus` resolve to whatever model the subscription serves [U].
   The collector records each batch's self-reported model ID.
5. **What the design's pilot also could not answer:**
   - kinds absent from the sample (13D, SPAC, liquidation, conditional-tender
     programme);
   - real collars and printed pro-ration factors (2 and 4 in the sample);
   - the training-data lookahead: these are 2021 filings, read by models
     trained on later text (design §10).

### 2.3 How the gold was built, and the circularity

**How it was built** (design §7.2, `event_engine_reconcile.py`), on 2026-10-15
in the `ss-event-engine` session:

1. Two blind readings, pass A and pass B. Each was made by separate
   **Claude Opus 5.5** subagents, working agentically over whole filings from
   `extraction_instructions.txt`.
2. A reconciliation by the same session's **Opus 5.5**, under these rules:
   - where A and B agreed, the agreed value stands;
   - each of the 24 disagreeing cells was decided against the text, with a
     written cause and reason;
   - 2 more cells were changed by an audit, where both passes agreed and both
     were wrong.
3. A 40-cell spot check of agreed values by the same model: 39 right.

The note records no human reading of any cell.

**Consequences for scoring a model against it:**

- **Agreement is the gold.** On the 96% of cells where A and B agreed (design
  §7.3), the gold is Opus 5.5's own reading, checked only in the 40-cell spot
  sample. An error that Opus makes systematically scores as *right* for an Opus
  reader and *wrong* for a model that reads correctly. Such errors exist: the
  Nuveen §7.4 condition was missed by both passes and was found only by audit.
- **Definitional rulings are Opus's.** 14 of the 26 adjudicated cells were
  definition gaps resolved by Opus, choosing between Opus readings. A Sonnet or
  Haiku reader that resolves the same ambiguity differently scores wrong.
- **The pilot gives every model pass A/B's instructions unchanged.** The
  instructions lack the gold's eight rules (§7.2), so every model faces the
  same definitional gap that pass A/B faced. Adding the rules would leak
  rulings learned from these same 50 filings, so no variant with them was
  prepared.
- **So:**
  - Opus-versus-gold is an *upper-biased* estimate of Opus.
  - Sonnet- or Haiku-versus-gold mixes reading errors with convention
    differences.
  - The collector writes every disagreement to `pilot_disagreements.csv`. Read
    them against the text, or at least a seeded sample, before attributing a
    gap between models to reading skill.
- **The rules are not circular**, being deterministic. But they are scored
  against the same gold, and two of their rules copy its conventions (§1.1).

### 2.4 Running it

**The files**, written by `prepare` out of tree under `<ROOT>` (4.6 MB):

- `input/filings/<accession>.partNN.txt`: 174 parts, each at most 30,000
  characters and 1,200 lines. Lines longer than 1,000 characters are wrapped
  at a space, so the normalised text is unchanged (asserted per filing). The
  wrapping is a precaution against the Read tool cutting very long lines [U].
- `input/PILOT_INSTRUCTIONS.md`: a pilot addendum (fixed excerpt, read
  everything, no search, which files to touch, the `_batch_NN.json` report),
  then `extraction_instructions.txt` unchanged. Its sha256 is in
  `input/plan.json`.
- `input/batches/batch_NN.json`: one per batch, listing the filings and their
  part paths.
- `input/BRIEF_TEMPLATE.txt`: the brief below.
- `out/{haiku,sonnet,opus}/`: where the subagents write.

**The batches.** These are 18 per model, packed first-fit decreasing at no more
than 90k estimated input tokens and no more than 10 filings each. The same
partition serves all three models:

- 01–14: 2 filings each;
- 15: 3 filings;
- 16: 4 filings;
- 17: 5 filings;
- 18: 10 short filings, ≈ 33k tokens.

That is 1.55M estimated input tokens per model [S]. A batch plus its
instructions and output should fit a 200k-token window with room to spare.
That window size is an assumption; the subagents' limits were not measured [U].

**The brief** (`event_engine_pilot.BRIEF`). For each model, substitute `{ROOT}`,
`{NN}` = 01–18 and `{MODEL}` = `haiku` | `sonnet` | `opus`. Pass the same word
as the Agent tool's `model`.

```text
You are a reader in the QUANTT event-engine pilot (2026-10-19). Do exactly this and nothing else.

1. Read {ROOT}/input/PILOT_INSTRUCTIONS.md in full with the Read tool. It binds you.
2. Read {ROOT}/input/batches/batch_{NN}.json. It lists your filings in order, each with its part files, and gives your output directory {ROOT}/out/{MODEL}/.
3. For each filing, in the listed order: read every one of its part files in full, in order, with the Read tool; then write {ROOT}/out/{MODEL}/<accession>.json in the shape PILOT_INSTRUCTIONS.md gives (every field of the kind present, null where the excerpt does not state it); then run the parse check on it.
4. Write {ROOT}/out/{MODEL}/_batch_{NN}.json as PILOT_INSTRUCTIONS.md describes, with your exact model ID.

Forbidden: opening any other file or directory (in particular anything under the repository, its results/ folder, other batches' outputs, and config/.env or any key file); Grep, Glob or any search; any shell command except the JSON parse check; network or web access; sudo; ssh; starting agents; using outside knowledge of these funds or deals.

Hand back one line: batch {NN}, your model ID, the number of JSON files written, and any problem.
```

**The order of work:**

1. **Smoke test.** Run batch 18 with `haiku` (10 short filings), then
   `collect --root <ROOT> --partial`, and confirm a table prints.
2. **The remaining 53.** Run them in any order: the three models are
   independent.
3. **Collect.** Run `python3 scripts/events/event_engine_pilot.py collect
   --root <ROOT>` **in this worktree**, where the hash-checked texts are. It:
   - refuses malformed JSON, a missing filing (unless `--partial`, which is
     labelled) and any root inside the repository;
   - copies the outputs to `results/events/event_engine/pilot/<model>/`;
   - writes `pilot_scores.json`, `pilot_field_scores.csv` and
     `pilot_disagreements.csv`;
   - prints one table: each model and the references (pass A, pass B, rules
     v1 and v2), on all cells and on the recoverable cells. The references'
     recoverable rows are below.

**A failed batch is re-run whole.** Never patch a JSON by hand.

**References on the pilot's cells** (`event_engine_pilot.py references`;
`pilot_references.json`) [V]:

| reader | kind | precision / recall, all gold values | precision / recall, recoverable from the excerpt | span failures |
|---|---:|---|---|---|
| pass A | 1.00 | 0.961 / 0.961 | 0.966 / 0.966 | 5 of 531 |
| pass B | 1.00 | 0.977 / 0.979 | 0.989 / 0.992 | 2 of 531 |
| rules v1 | 0.98 | 0.826 / 0.609 | 0.859 / 0.640 | 0 of 287 |
| rules v2 | 0.98 | 0.886 / 0.658 | 0.917 / 0.691 | 0 of 294 |

The passes and the rules read the whole filing, so their quotes are checked
against the whole text. A pilot model's quotes are checked against the excerpt
it was given, where a quote from beyond the cut can only come from memory.

### 2.5 After the pilot

- **If a model's recoverable score is near pass B's 0.99**, the reading
  question is answered for this input. The whole-filing question (§2.2) still
  needs either API spend or a structural selector (agreement "Conditions
  precedent" and "Termination" by heading, design §7.4).
- **If Haiku or Sonnet trails Opus**, read the disagreement file first (§2.3).
  A trail made of convention differences is not a reading gap.
- **This is zero trials either way.**

---

## 3. Files

- `scripts/events/event_engine_rules.py`: the rules-only extractor (v1 and v2), the dev/test split, scoring.
- `scripts/events/event_engine_pilot.py`: the shared scorer (`score_reader`), the pilot's `prepare`, `collect` and `references`, the brief and the instructions addendum.
- `scripts/events/tests/test_event_engine_pilot.py`: rules on literal fixtures (each v2 change against v1), the split, the excerpt, parts and batches, and collector validation.
- `results/events/event_engine/` (tracked): `rules/` (v2) and `rules_v1/` (one JSON per filing); `rules_v1_scores.json`, `rules_v2_scores.json`, `rules_v1_field_scores.csv`, `rules_v2_field_scores.csv`; `pilot_references.json`. After the pilot: `pilot/<model>/`, `pilot_scores.json`, `pilot_field_scores.csv`, `pilot_disagreements.csv`.
- Out of tree: `<ROOT>/input/` and `<ROOT>/out/` (rebuilt by `prepare`).
- Gitignored: `results/events/_cache_event_engine/text/` and the 50 raw submissions under `results/events/_cache_edgar/`.
