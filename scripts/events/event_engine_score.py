"""Score the event-engine prototype: span checks, pass-to-pass agreement, precision/recall against the gold, and cost.

    python3 scripts/events/event_engine_score.py           # reads results/events/event_engine/{pass_a,pass_b,gold}/
    python3 scripts/events/event_engine_score.py --volume  # filings a year in the frame (EDGAR cache, offline)
    python3 scripts/events/event_engine_score.py --spot-sample  # the seeded agreed cells to re-read by hand

ZERO TRIALS. No return, no P&L, no signal. This scores READING: how well an
extraction of EDGAR filings into the schema of `scripts/events/event_store.py`
matches what the filings say. Design note:
`results/events/EVENT_ENGINE_DESIGN_2026-10-15.md`.

WHAT IS COMPARED
----------------
* pass A and pass B: two independent readings of the same 50 filings
  (`event_engine_sample.py`), each by a separate reader that never saw the
  other's output; each reader is the stand-in for the extraction model.
* the gold: the reconciliation. Where A and B agree the agreed value stands
  (a seeded random subset of the agreements is re-read against the text,
  `SPOT_CHECK_N`, to estimate how often two readers agree and are both
  wrong); where they disagree the text decides, with the reason recorded.

Per field (the first event of each filing, plus triage):
  TP: pass non-null and equal to gold non-null;
  FP: pass non-null and gold null or different;
  FN: gold non-null and pass null or different
  (a wrong value is both an FP and an FN, the slot-filling convention);
  precision = TP/(TP+FP), recall = TP/(TP+FN).
A field is compared only under the gold's kind; a pass that chose another
kind scores every gold value as missed and every value it gave as false.

Equality: numbers and percents to 1e-6 relative; dates exact; enums and
bools exact; sets as sets; text fields are not scored (names are reported).

COST
----
Tokens are NOT counted with a tokenizer: the team lead has not approved API
keys (2026-10-15), and Anthropic's counter is an API endpoint. They are
ESTIMATED from characters with the ratio Anthropic publishes: "a token
represents approximately 3.5 English characters" on models before Claude 4.7,
and the tokenizer of Claude 4.7 and later "produces approximately 30 percent
more tokens for the same text" (platform.claude.com glossary and pricing
pages, fetched 2026-10-15). So `CHARS_PER_TOKEN = 3.5 / 1.30` for the 5.5
models, labelled [S] wherever it is used; filings are dense with numbers and
tables, which tokenise worse than prose, so the estimate is more likely low
than high [U]. Prices are the pricing page's rows, fetched 2026-10-15 [V].
"""
from __future__ import annotations

import json
import math
from datetime import time
import random
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.events import event_store as E  # noqa: E402

OUT = REPO / "results" / "events" / "event_engine"
TEXT_DIR = REPO / "results" / "events" / "_cache_event_engine" / "text"
MANIFEST = OUT / "sample_manifest.csv"
SPOT_CHECK_N = 40
SPOT_CHECK_SEED = 20261015

# --- token and price inputs (sources in the module docstring) ---------------
CHARS_PER_TOKEN_OLD = 3.5            # [S] glossary: models before Claude 4.7
NEW_TOKENIZER_FACTOR = 1.30          # [S] pricing page / glossary: "approximately 30%" more tokens
CHARS_PER_TOKEN = CHARS_PER_TOKEN_OLD / NEW_TOKENIZER_FACTOR
PRICES = {  # USD per million tokens, https://platform.claude.com/docs/en/about-claude/pricing, fetched 2026-10-15 [V]
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "batch_input": 0.05,
                         "batch_output": 0.25, "long_prompt_tokens": 100_000,
                         "long": {"input": 0.50, "output": 2.50, "cache_read": 0.05, "batch_input": 0.25,
                                  "batch_output": 1.25}},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.10, "batch_input": 1.00,
                          "batch_output": 5.00},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "batch_input": 2.00,
                        "batch_output": 10.00},
}
TOOL_SYSTEM_TOKENS = 286   # [V] pricing page: tool-use system prompt, auto tool_choice, all three models
WINDOWS = (8_000, 20_000, 50_000, 120_000)   # characters of the filing's text sent to the model


# ============================================================ loading

def load_dir(d: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(d.glob("*.json")):
        j = json.loads(p.read_text())
        acc = j.get("accession") or p.stem
        if acc != p.stem:
            raise ValueError(f"{p}: accession {acc} != file name")
        out[acc] = j
    return out


def first_event(x: dict) -> dict:
    ev = x.get("events") or []
    return ev[0] if ev else {"kind": "none", "terms": {}}


def kind_of(x: dict) -> str:
    k = (x.get("triage") or {}).get("kind")
    if k is None:
        raise ValueError(f"{x.get('accession')}: no triage kind")
    return k


# ============================================================ normalising values

def _num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError(f"bool where a number was expected: {v}")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("$", "").replace("%", "").strip()
    return float(s)


def norm_value(v, dtype: str):
    if v is None:
        return None
    if dtype in ("number", "percent"):
        return _num(v)
    if dtype == "date":
        return str(v)[:10]
    if dtype == "bool":
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("true", "yes"):
            return True
        if s in ("false", "no"):
            return False
        raise ValueError(f"not a bool: {v!r}")
    if dtype == "set":
        return frozenset(str(x).strip().lower() for x in v) if v else frozenset()
    if dtype == "enum":
        return str(v).strip().lower()
    return re.sub(r"[^a-z0-9]+", " ", str(v).lower()).strip()


def equal(a, b, dtype: str) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if dtype in ("number", "percent"):
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)
    return a == b


def field_values(x: dict, kind: str) -> dict:
    """field -> normalised value for `kind`'s fields (None where absent or null), plus triage fields."""
    out = {}
    ev = first_event(x)
    terms = ev.get("terms") or {}
    same_kind = kind_of(x) == kind
    for s in E.FIELDS[kind]:
        fv = terms.get(s.name) if same_kind else None
        v = fv.get("value") if isinstance(fv, dict) else None
        if s.dtype == "set" and v == []:
            v = None   # an empty set is "nothing stated"
        out[s.name] = norm_value(v, s.dtype)
    tri = x.get("triage") or {}
    for s in E.TRIAGE:
        out["triage." + s.name] = norm_value(tri.get(s.name), "enum")
    return out


def dtype_of(kind: str, name: str) -> str:
    return "enum" if name.startswith("triage.") else E.field_spec(kind, name).dtype


# ============================================================ span checks

def span_failures(x: dict, text: str) -> list[dict]:
    ev = first_event(x)
    k = ev.get("kind", "none")
    if k == "none":
        return []
    terms = {n: fv for n, fv in (ev.get("terms") or {}).items() if isinstance(fv, dict)}
    bad = [n for n in terms if n not in {s.name for s in E.FIELDS[k]}]
    out = [{"field": n, "reason": "field_not_in_schema", "detail": ""} for n in bad]
    terms = {n: fv for n, fv in terms.items() if n not in bad}
    out += [vars(f) for f in E.verify_spans(k, terms, text)]
    return out


def n_nonnull(x: dict) -> int:
    ev = first_event(x)
    return sum(1 for fv in (ev.get("terms") or {}).values() if isinstance(fv, dict) and fv.get("value") not in (None, []))


# ============================================================ agreement and P/R

def compare_passes(a: dict, b: dict, man: pd.DataFrame) -> pd.DataFrame:
    """One row per (filing, field) under A's kind if the kinds agree, else a kind-disagreement row."""
    rows = []
    for acc in man["accession"]:
        xa, xb = a[acc], b[acc]
        ka, kb = kind_of(xa), kind_of(xb)
        rows.append({"accession": acc, "kind": ka, "field": "triage.kind", "dtype": "enum",
                     "a": ka, "b": kb, "agree": ka == kb})
        for f in ("triage.fund_type", "triage.doc_role"):
            va, vb = field_values(xa, ka)[f], field_values(xb, kb)[f]
            rows.append({"accession": acc, "kind": ka, "field": f, "dtype": "enum", "a": va, "b": vb,
                         "agree": va == vb})
        if ka != kb or ka == "none":
            continue
        fa, fb = field_values(xa, ka), field_values(xb, ka)
        for s in E.FIELDS[ka]:
            if not s.scored:
                continue
            rows.append({"accession": acc, "kind": ka, "field": s.name, "dtype": s.dtype,
                         "a": fa[s.name], "b": fb[s.name], "agree": equal(fa[s.name], fb[s.name], s.dtype)})
    return pd.DataFrame(rows)


def score_vs_gold(p: dict, gold: dict, man: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for acc in man["accession"]:
        g, x = gold[acc], p[acc]
        kg = kind_of(g)
        fg = field_values(g, kg)
        fx = field_values(x, kg)          # the pass's values under the GOLD kind (null if it chose another)
        names = ["triage.kind", "triage.fund_type", "triage.doc_role"] + [s.name for s in E.FIELDS[kg] if s.scored]
        kx = kind_of(x)
        for n in names:
            if n == "triage.kind":
                gv, xv, dt = kg, kx, "enum"
            else:
                dt = dtype_of(kg, n)
                gv, xv = fg[n], fx[n]
            tp = gv is not None and xv is not None and equal(gv, xv, dt)
            fp = xv is not None and not tp
            fn = gv is not None and not tp
            rows.append({"pass": label, "accession": acc, "kind": kg, "field": n, "dtype": dt,
                         "gold": gv, "value": xv, "tp": tp, "fp": fp, "fn": fn,
                         "both_null": gv is None and xv is None})
    return pd.DataFrame(rows)


def pr_table(s: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = s.groupby(by).agg(n=("tp", "size"), gold_nonnull=("gold", lambda v: int(v.notna().sum())),
                          tp=("tp", "sum"), fp=("fp", "sum"), fn=("fn", "sum"),
                          exact=("tp", lambda v: 0)).reset_index()
    exact = s.assign(ok=s["tp"] | s["both_null"]).groupby(by)["ok"].mean().reset_index(name="cell_accuracy")
    g = g.drop(columns="exact").merge(exact, on=by)
    g["precision"] = g["tp"] / (g["tp"] + g["fp"]).where(lambda v: v > 0)
    g["recall"] = g["tp"] / (g["tp"] + g["fn"]).where(lambda v: v > 0)
    return g


# ============================================================ windows and tokens

# Section selection: what a pipeline could send instead of the whole filing. The
# cover (first COVER_CHARS) plus every paragraph that matches a term of the
# SCHEMA. The vocabulary is taken from the field docs in event_store.FIELDS
# (prices, sizes, dates, conditions, ratios, rights), written before the
# coverage below was computed and not tuned to it.
COVER_CHARS = 8_000
SECTION_RE = re.compile(
    r"net asset value|\bnav\b|per share|subscription price|exchange ratio|conversion ratio|"
    r"pro ?rat|oversubscri|over-subscri|expir|commence|record date|meeting|"
    r"condition|terminat|outside date|collar|\bcash\b|closing|"
    r"tender offer|offer to purchase|purchase price|rights offering|\brights?\b|"
    r"accepted|tendered|outstanding (common )?shares|percent|%", re.I)


def select_sections(text: str) -> str:
    """The cover plus every paragraph (text line) after it that matches SECTION_RE."""
    head, rest = text[:COVER_CHARS], text[COVER_CHARS:]
    keep = [ln for ln in rest.splitlines() if SECTION_RE.search(ln)]
    return head + "\n" + "\n".join(keep)


def value_coverage(gold: dict, texts: dict[str, str], man: pd.DataFrame) -> pd.DataFrame:
    """Per gold value: is every one of its spans inside the first W characters, and inside the selected sections?

    A value is RECOVERABLE from an input only if all its quotes are in it (a
    condition set needs every element). Offsets are in normalised characters.
    """
    rows = []
    strat = dict(zip(man["accession"], man["stratum"]))
    for acc, g in gold.items():
        norm = E.normalise(texts[acc])
        sel = E.normalise(select_sections(texts[acc]))
        ev = first_event(g)
        k = ev.get("kind", "none")
        for n, fv in (ev.get("terms") or {}).items():
            if not isinstance(fv, dict) or fv.get("value") in (None, []):
                continue
            if k != "none" and not E.field_spec(k, n).scored:
                continue
            spans = [x for x in (fv.get("spans") or [fv.get("span")]) if x]
            offs = [norm.find(E.normalise(x)) for x in spans]
            ends = [o + len(E.normalise(x)) for o, x in zip(offs, spans)]
            rec = {"accession": acc, "stratum": strat[acc], "kind": k, "field": n,
                   "max_end": max(ends) if all(o >= 0 for o in offs) else -1,
                   "in_sections": all(E.normalise(x) in sel for x in spans),
                   "selected_chars": len(sel), "text_chars": len(norm)}
            for w in WINDOWS:
                rec[f"in_first_{w}"] = rec["max_end"] >= 0 and rec["max_end"] <= w
            rows.append(rec)
    return pd.DataFrame(rows)

def span_offsets(gold: dict, texts: dict[str, str]) -> pd.DataFrame:
    """Where each gold span sits in its filing's text, in normalised characters (position of first match)."""
    rows = []
    for acc, g in gold.items():
        norm = E.normalise(texts[acc])
        ev = first_event(g)
        for n, fv in (ev.get("terms") or {}).items():
            if not isinstance(fv, dict) or fv.get("value") in (None, []):
                continue
            spans = fv.get("spans") or [fv.get("span")]
            for s in spans:
                if not s:
                    continue
                i = norm.find(E.normalise(s))
                rows.append({"accession": acc, "field": n, "offset": i, "len_norm": len(norm)})
    return pd.DataFrame(rows)


def tokens(chars: float) -> float:
    return chars / CHARS_PER_TOKEN


def price_of(model: str, in_tok: float, out_tok: float, cached_tok: float, batch: bool) -> float:
    p = PRICES[model]
    total_prompt = in_tok + cached_tok
    if "long_prompt_tokens" in p and total_prompt > p["long_prompt_tokens"]:
        p = {**p, **p["long"]}
    ki, ko = ("batch_input", "batch_output") if batch else ("input", "output")
    cache_read = p["cache_read"] * (0.5 if batch else 1.0)   # [V] pricing page: discounts stack
    return (in_tok * p[ki] + out_tok * p[ko] + cached_tok * cache_read) / 1e6


# ============================================================ time keys

def time_keys(man: pd.DataFrame) -> pd.DataFrame:
    """Per filing: the API check, observed_at, the filing-date rule, and what an acceptance key would leak.

    `leak_hours_at_22et`: if the store keyed on ACCEPTANCE, an evening filing
    held by EDGAR until its filing date would reach a 22:00 ET decision this
    many hours before it was published (0 where acceptance is the publication).
    """
    rows = []
    for r in man.itertuples():
        hdr = pd.Timestamp(r.acceptance_header_as_et_utc).to_pydatetime()
        raw14 = hdr.astimezone(E.ET).strftime("%Y%m%d%H%M%S")
        acc, verdict = E.acceptance_from_edgar(raw14, r.acceptance_utc)
        fd = pd.Timestamp(r.date_filed).date()
        obs = E.observed_at(acc, fd)
        d0 = acc.astimezone(E.ET).date()
        decide = E.research_decision_time(d0)
        leak = (obs - decide).total_seconds() / 3600 if acc <= decide < obs else 0.0
        rows.append({"accession": r.accession, "form": r.form, "acceptance_et": acc.astimezone(E.ET).isoformat(),
                     "filing_date": str(fd), "api_check": verdict, "observed_at_utc": obs.isoformat(),
                     "held_overnight": obs > acc, "filing_date_rule_ok": E.filing_date_consistent(acc, fd, r.form),
                     "api_time_filing_date_rule_ok": E.filing_date_consistent(
                         pd.Timestamp(r.acceptance_utc).to_pydatetime(), fd, r.form),
                     "accepted_16_to_1730_on_filing_date": d0 == fd and time(16, 0) <= acc.astimezone(E.ET).time() <= time(17, 30),
                     "leak_hours_at_22et_if_keyed_on_acceptance": round(leak, 2)})
    return pd.DataFrame(rows)


# ============================================================ main

def main() -> int:
    man = pd.read_csv(MANIFEST)
    texts = {a: (TEXT_DIR / f"{a}.txt").read_text() for a in man["accession"]}
    a, b = load_dir(OUT / "pass_a"), load_dir(OUT / "pass_b")
    gold = load_dir(OUT / "gold")
    for name, d in (("pass_a", a), ("pass_b", b), ("gold", gold)):
        missing = sorted(set(man["accession"]) - set(d))
        if missing:
            raise FileNotFoundError(f"{name} is missing {len(missing)} filings: {missing[:3]}...")
    res: dict = {"n_filings": len(man)}
    tk = time_keys(man)
    tk.to_csv(OUT / "time_keys.csv", index=False)
    res["time_keys"] = {"api_check": tk["api_check"].value_counts().to_dict(),
                        "header_consistent_with_filing_date_rule": int(tk["filing_date_rule_ok"].sum()),
                        "api_time_consistent_with_filing_date_rule": int(tk["api_time_filing_date_rule_ok"].sum()),
                        "held_overnight_by_edgar": int(tk["held_overnight"].sum()),
                        "would_leak_into_a_22et_decision_if_keyed_on_acceptance": int((tk["leak_hours_at_22et_if_keyed_on_acceptance"] > 0).sum()),
                        "accepted_16_to_1730_on_filing_date": int(tk["accepted_16_to_1730_on_filing_date"].sum())}

    # span checks
    sp = []
    for label, d in (("A", a), ("B", b), ("gold", gold)):
        for acc in man["accession"]:
            fails = span_failures(d[acc], texts[acc])
            sp.append({"pass": label, "accession": acc, "nonnull": n_nonnull(d[acc]), "failures": len(fails),
                       "detail": json.dumps(fails)[:2000]})
    sp = pd.DataFrame(sp)
    res["span_checks"] = {p: {"values": int(g["nonnull"].sum()), "failures": int(g["failures"].sum()),
                              "filings_with_failure": int((g["failures"] > 0).sum())}
                          for p, g in sp.groupby("pass")}
    sp.to_csv(OUT / "span_checks.csv", index=False)

    # agreement
    ag = compare_passes(a, b, man)
    ag.to_csv(OUT / "agreement_ab.csv", index=False)
    res["agreement_ab"] = {
        "triage_kind": float(ag[ag.field == "triage.kind"]["agree"].mean()),
        "terms_cells": int((~ag.field.str.startswith("triage")).sum()),
        "terms_agree": float(ag[~ag.field.str.startswith("triage")]["agree"].mean()),
        "terms_agree_nonnull_either": float(ag[~ag.field.str.startswith("triage") & (ag.a.notna() | ag.b.notna())]["agree"].mean()),
    }

    # vs gold
    sa, sb = score_vs_gold(a, gold, man, "A"), score_vs_gold(b, gold, man, "B")
    s = pd.concat([sa, sb], ignore_index=True)
    s["stratum"] = s["accession"].map(dict(zip(man["accession"], man["stratum"])))
    s.to_csv(OUT / "field_scores_long.csv", index=False)
    by_field = pr_table(s, ["kind", "field", "dtype"])
    by_field.to_csv(OUT / "field_scores.csv", index=False)
    by_pass = pr_table(s[~s.field.str.startswith("triage")], ["pass"])
    by_dtype = pr_table(s[~s.field.str.startswith("triage")], ["dtype"])
    res["vs_gold_by_pass"] = by_pass.to_dict("records")
    res["vs_gold_by_dtype"] = by_dtype.to_dict("records")
    res["triage_kind_accuracy"] = s[s.field == "triage.kind"].groupby("pass")["tp"].mean().to_dict()

    sc = OUT / "spot_check.csv"
    if sc.exists():
        v = pd.read_csv(sc)
        if sorted(zip(v["accession"], v["field"])) != sorted(spot_check_sample(a, b, man)):
            raise ValueError("spot_check.csv is not the seeded sample of agreed cells; re-read the new sample")
        res["spot_check"] = {"cells": len(v), **v["verdict"].value_counts().to_dict()}

    # reconciliation log
    rec = OUT / "reconciliation.csv"
    if rec.exists():
        r = pd.read_csv(rec)
        res["reconciliation"] = {"rows": len(r), "by_decision": r["decision"].value_counts().to_dict()}

    # windows: where do the gold values sit?
    off = span_offsets(gold, texts)
    off.to_csv(OUT / "gold_span_offsets.csv", index=False)
    found = off[off.offset >= 0]
    res["gold_span_offsets"] = {"spans": len(off), "found": len(found),
                                **{f"share_within_{w}": float((found.offset + 1 <= w).mean()) for w in WINDOWS}}
    per_filing_max = found.groupby("accession")["offset"].max()
    res["filings_all_spans_within"] = {str(w): int((per_filing_max < w).sum()) for w in WINDOWS}

    vc = value_coverage(gold, texts, man)
    vc.to_csv(OUT / "gold_value_coverage.csv", index=False)
    sel_chars = {acc: len(select_sections(texts[acc])) for acc in man["accession"]}
    cov = {"values": len(vc),
           "recoverable_from_sections": float(vc["in_sections"].mean()),
           **{f"recoverable_from_first_{w}": float(vc[f"in_first_{w}"].mean()) for w in WINDOWS},
           "by_stratum": {st: {"values": len(g), "sections": float(g["in_sections"].mean()),
                               **{f"first_{w}": float(g[f"in_first_{w}"].mean()) for w in WINDOWS}}
                          for st, g in vc.groupby("stratum")},
           "fields_missed_by_sections": vc.loc[~vc["in_sections"], "field"].value_counts().to_dict(),
           "selected_chars_mean": float(pd.Series(sel_chars).mean()),
           "selected_chars_median": float(pd.Series(sel_chars).median()),
           "selected_share_of_text_mean": float((pd.Series(sel_chars) / man.set_index("accession")["chars_kept_text"]).mean())}
    res["value_coverage"] = cov

    # tokens and cost
    instr_chars = len((OUT / "extraction_instructions.txt").read_text())
    out_chars = [len(json.dumps(gold[x], separators=(",", ":"))) for x in man["accession"]]
    man = man.assign(out_chars=out_chars)
    tok = {"chars_per_token_assumed": CHARS_PER_TOKEN, "instructions_chars": instr_chars,
           "instructions_tokens_est": tokens(instr_chars) + TOOL_SYSTEM_TOKENS,
           "output_tokens_est_median": tokens(float(pd.Series(out_chars).median())),
           "output_tokens_est_mean": tokens(float(pd.Series(out_chars).mean()))}
    for st, g in man.groupby("stratum"):
        tok[f"text_tokens_est_{st}"] = {"median": tokens(float(g.chars_kept_text.median())),
                                       "mean": tokens(float(g.chars_kept_text.mean())),
                                       "max": tokens(float(g.chars_kept_text.max()))}
    tok["text_tokens_est_all"] = {"median": tokens(float(man.chars_kept_text.median())),
                                  "mean": tokens(float(man.chars_kept_text.mean())),
                                  "max": tokens(float(man.chars_kept_text.max()))}
    res["tokens"] = tok

    rows = []
    sys_tok = tok["instructions_tokens_est"]
    out_tok = tok["output_tokens_est_mean"]
    for w in (None,) + WINDOWS:
        chars = man.chars_kept_text if w is None else man.chars_kept_text.clip(upper=w)
        for model in PRICES:
            for batch in (False, True):
                per = [price_of(model, tokens(c), out_tok, sys_tok, batch) for c in chars]
                rows.append({"window_chars": "full" if w is None else w, "model": model, "batch": batch,
                             "mean_input_tokens_est": float(tokens(chars.mean())),
                             "usd_per_1000_filings": 1000 * float(pd.Series(per).mean())})
    sel = man["accession"].map(sel_chars)
    for model in PRICES:
        for batch in (False, True):
            per = [price_of(model, tokens(c), out_tok, sys_tok, batch) for c in sel]
            rows.append({"window_chars": "sections", "model": model, "batch": batch,
                         "mean_input_tokens_est": float(tokens(sel.mean())),
                         "usd_per_1000_filings": 1000 * float(pd.Series(per).mean())})
    cost = pd.DataFrame(rows)
    cost.to_csv(OUT / "cost_per_1000.csv", index=False)

    # Tiered: triage every filing on its cover with the small model (output = the
    # triage block only), then terms on the selected sections for the filings
    # triaged positive, with a larger model. Per 1,000 filings, as a function of
    # the positive share p (unknown for the EDGAR stream; 48 of 50 here, by design).
    tri_out = tokens(float(pd.Series([len(json.dumps(gold[x]["triage"], separators=(",", ":")))
                                       for x in man["accession"]]).mean()))
    triage_per = [price_of("claude-haiku-5-5", tokens(min(c, COVER_CHARS)), tri_out, sys_tok, b)
                  for c in man["chars_kept_text"] for b in (False,)]
    tiers = {"triage_output_tokens_est": tri_out,
             "triage_haiku_usd_per_1000": 1000 * float(pd.Series(triage_per).mean()),
             "triage_haiku_batch_usd_per_1000": 1000 * float(pd.Series(
                 [price_of("claude-haiku-5-5", tokens(min(c, COVER_CHARS)), tri_out, sys_tok, True)
                  for c in man["chars_kept_text"]]).mean())}
    for model in ("claude-sonnet-5-5", "claude-opus-5-5"):
        for batch in (False, True):
            tiers[f"terms_{model}_{'batch' if batch else 'std'}_usd_per_1000_positives"] = 1000 * float(pd.Series(
                [price_of(model, tokens(c), out_tok, sys_tok, batch) for c in sel]).mean())
    res["tiered_cost"] = tiers
    res["cost_note"] = ("system prompt counted as cache reads every call (a cache write once per batch is "
                        "ignored); output = the gold JSON's size; thinking tokens are NOT included (unmeasured)")
    (OUT / "scores.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str)[:6000])
    return 0


def annual_volume(years=(2021, 2025)) -> dict:
    """Event-form filings per year by the CEF/BDC fund set (all, and listed today), from the cached indexes.

    The scale for the cost estimate: how many filings a year the engine would
    triage. Same frame as `event_engine_sample.frame` (indexes 2008-Q1..2026-Q3,
    the 2026-10-12 ticker file), counted by unique accession. Offline: reads
    the EDGAR cache only. Excludes Schedules 13D/13G and every non-CEF filer
    (SPACs, operating companies): the activist, SPAC and equity-M&A kinds
    would add their own streams.
    """
    from datetime import date
    from scripts.data import fetch_edgar_events as F
    from scripts.data.edgar_client import EdgarClient
    c = EdgarClient(offline=True)
    idx, _ = F.fetch_indexes(c, F.LOOKBACK_START, date(2026, 9, 30), today=date(2026, 10, 15))
    rule = F.fund_set(idx)
    tk = c.get_json(F.TICKERS_URL, max_age_s=None)
    listed = {int(r[0]) for r in tk["data"]} & set(rule)
    out = {}
    for yr in years:
        base = idx[idx["form"].isin(F.FORM_KIND) & (idx["date_filed"].dt.year == yr)]
        allf = base[base["cik"].isin(set(rule))].drop_duplicates("accession")
        lst = base[base["cik"].isin(listed)].drop_duplicates("accession")
        out[str(yr)] = {"fund_set": len(allf), "listed_now": len(lst),
                        "listed_now_by_kind": lst["form"].map(F.FORM_KIND).value_counts().to_dict(),
                        "fund_set_by_kind": allf["form"].map(F.FORM_KIND).value_counts().to_dict()}
    return out


def spot_check_sample(a: dict, b: dict, man: pd.DataFrame) -> list[tuple[str, str]]:
    """The seeded sample of AGREED non-null term cells re-read against the text during reconciliation."""
    ag = compare_passes(a, b, man)
    cand = ag[ag.agree & ag.a.notna() & ~ag.field.str.startswith("triage")]
    pairs = sorted(zip(cand.accession, cand.field))
    rng = random.Random(SPOT_CHECK_SEED)
    return rng.sample(pairs, min(SPOT_CHECK_N, len(pairs)))


if __name__ == "__main__":
    if "--spot-sample" in sys.argv:   # the seeded agreed cells re-read by hand (verdicts: spot_check.csv)
        _m = pd.read_csv(MANIFEST)
        for acc, f in spot_check_sample(load_dir(OUT / "pass_a"), load_dir(OUT / "pass_b"), _m):
            print(acc, f)
        sys.exit(0)
    if "--volume" in sys.argv:
        v = annual_volume()
        (OUT / "annual_volume.json").write_text(json.dumps(v, indent=1))
        print(json.dumps(v, indent=1))
        sys.exit(0)
    sys.exit(main())
