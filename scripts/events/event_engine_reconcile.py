"""The event-engine prototype's gold: pass A and pass B reconciled, every decision written down.

    python3 scripts/events/event_engine_reconcile.py    # pass_a/ + pass_b/ -> gold/ and reconciliation.csv

ZERO TRIALS. Reconciles two independent readings of the 50 sampled filings
(`results/events/event_engine/pass_a/`, `pass_b/`; design note §7). Every cell
where A and B disagree (the triage fields and the scored terms of the first
event) must have a decision in `D` or `EXTRA`, or the script RAISES; a
decision with no disagreement behind it raises too, so the table cannot drift
from the passes. Gold starts from pass A's JSON: "A" keeps it, "B" copies B's
field, "V" edits a set (drop / add elements, each added element with its own
quote). `AUDIT` holds cells where A and B AGREE and are both wrong under the
gold's rules: found by auditing one field across the stratum (the pre-closing
distribution condition) after a disagreement exposed the rule. A gold quote
that is not verbatim takes the other reader's quote of the same value
("span_repair"), or the script raises. The adjudication rules are stated in
the design note §7.2.
"""
import copy
import json
import sys
from pathlib import Path

import pandas as pd

WT = Path(__file__).resolve().parents[2]
if str(WT) not in sys.path:
    sys.path.insert(0, str(WT))
from scripts.events import event_store as E  # noqa: E402
from scripts.events import event_engine_score as S  # noqa: E402

ROOT = WT / "results" / "events" / "event_engine"
A_DIR, B_DIR, OUT = ((Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])) if len(sys.argv) == 4
                     else (ROOT / "pass_a", ROOT / "pass_b", ROOT / "gold"))

# cause: reading (one reader missed or misread what the text states) | definition (the schema left the
# field ambiguous; gold applies the rule given) | text_conflict (the filing contradicts itself) |
# judgement (a classification resting on inference)
D = {
    # ---------------- tender stratum
    ("0001140361-21-005674", "commencement_date"): ("B", "definition",
        "Offer to Purchase dated 2021-02-22, but the letters say the offer period begins 'on or before March 1, 2021' and "
        "26 April is '40 business days after the commencement' (= 1 March): no single stated date"),
    ("0001140361-22-019368", "trigger_origin"): ("B", "judgement",
        "a quarterly repurchase programme of a then non-traded fund ('tender offers conducted during such period')"),
    ("0001193125-21-119537", "proration_factor_pct"): ("A", "definition",
        "'all ... were accepted' states no pro-ration factor; the schema wants a printed factor"),
    ("0001550913-21-000032", "commencement_date"): ("B", "definition",
        "rule: the date of the Offer to Purchase the filing names ('dated March 19, 2021'), absent a different stated start"),
    ("0001550913-21-000032", "shares_tendered"): ("B", "text_conflict",
        "'received and accepted ... 13,303,521.4954 Shares' contradicts '$353,386.47' paid at $6 (= 58,897.7444) and "
        "'0.4% of the outstanding'; no consistent tendered count"),
    ("0001550913-21-000032", "shares_accepted"): ("B", "text_conflict",
        "58,897.7444 x $6 = $353,386.47, the stated cash; 13.3M is inconsistent with it and with 0.4%"),
    ("0000940394-21-001125", "trigger_origin"): ("A", "judgement",
        "the filing attaches the Standstill Agreement dated 2021-05-12 as exhibit (d)(i)"),
    ("0001558370-21-004185", "conditions"): ("B", "reading",
        "the violation-of-law condition is stated outside the enumerated list ('Notwithstanding any other provision')"),
    ("0000940394-21-001127", "proration_factor_pct"): ("A", "definition",
        "the results table prints 'N/A'; 'will purchase all shares properly tendered' states no factor"),
    ("0001398344-21-014671", "commencement_date"): ("B", "definition",
        "rule: the date of the Offer to Purchase the filing names ('dated June 21, 2021')"),
    ("0001387131-21-010988", "commencement_date"): ("B", "definition",
        "rule: the Schedule TO 'originally filed ... on October 12, 2021' is filed on the commencement date (Rule 13e-4)"),
    ("0001287032-21-000418", "trigger_origin"): ("B", "judgement",
        "a board decision to retire notes before maturity; no programme, settlement or merger"),
    # ---------------- merger stratum
    ("0001104659-21-055075", "conditions"): ("A", "reading",
        "the no-material-adverse-effect condition is a closing condition ('other')"),
    ("0001193125-21-162187", "conditions"): ("V", "definition",
        "a board's right to terminate (s.11.1(c)) is a termination right, not a closing condition (B right); "
        "and s.7.4, in Article VII 'Conditions precedent', requires the pre-closing distribution (both missed it)",
        {"base": "B", "drop": [], "add": [("ric_or_tax_status", "Prior to the Valuation Time, such Target Fund will have declared the dividends and/or distributions contemplated by Section 8.5")]}),
    ("0001193125-21-021815", "triage.doc_role"): ("A", "judgement",
        "the deal's first EDGAR communication (Rule 425 shareholder Q&A)"),
    ("0001193125-21-021815", "security_class"): ("B", "definition",
        "the filing says 'DNP shares', never which class; the schema wants a stated class"),
    ("0001104659-21-012810", "security_class"): ("B", "definition",
        "open-end share classes (Class A, Investor, I, R6) are not common stock; 'other' (schema gap for open-end funds)"),
    ("0001104659-21-012810", "conditions"): ("V", "definition",
        "gold = A without board_discretion (a termination right) = B plus ric_or_tax_status (the pre-closing "
        "distribution of all income, a RIC condition)",
        {"base": "A", "drop": ["board_discretion"], "add": []}),
    ("0001104659-21-012810", "record_date"): ("B", "definition",
        "an information statement with no vote: the 'Record Date' fixes share counts only; the schema's record date is for the vote"),
    ("0001193125-21-048962", "conditions"): ("A", "reading",
        "the pre-closing distribution of all income is a stated condition (ric_or_tax_status)"),
    # ---------------- rights stratum
    ("0001398344-21-011202", "price_reference"): ("B", "definition",
        "'85% of NAV or 95% of market, whichever is higher': the enum's greater_of_nav_and_market; schema 0.1 cannot hold two percents"),
    ("0001398344-21-011203", "price_reference"): ("B", "definition", "as 011202"),
    ("0001398344-21-011204", "price_reference"): ("B", "definition", "as 011202"),
}
EXTRA = {
    ("0000894189-21-000100", "conditions"): ("A", "reading",
        "s.8.6 in the conditions article: the Target Fund 'shall have declared and paid a dividend' (ric_or_tax_status)"),
}
# Cells where A and B AGREE and both are wrong under the gold's rules, found by auditing one field
# across the stratum (the pre-closing distribution condition) or by the seeded spot check.
AUDIT = {
    ("0001193125-21-196361", "conditions"): ({"base": "A", "drop": [], "add": [("ric_or_tax_status", "Prior to the Valuation Time, such Target Fund will have declared the dividends and/or distributions contemplated by Section 8.5")]},
        "both_wrong", "s.7.4 in Article VII 'Conditions precedent' requires the pre-closing distribution; both readers omitted it"),
    ("0001193125-22-014885", "conditions"): ({"base": "A", "drop": [], "add": [("ric_or_tax_status",
        "Prior to the Valuation Time, the Target Fund will have declared the dividends and/or distributions contemplated by Section 8.5")]},
        "both_wrong", "s.7.4 in Article VII 'Conditions precedent' requires the pre-closing distribution; both readers omitted it"),
}


def field_dict(x, name):
    ev = S.first_event(x)
    f = (ev.get("terms") or {}).get(name)
    return copy.deepcopy(f) if isinstance(f, dict) else None


def edit_set(xa, xb, name, spec):
    base = field_dict(xa if spec["base"] == "A" else xb, name)
    keep = [(v, sp) for v, sp in zip(base["value"] or [], base["spans"] or []) if v not in spec["drop"]]
    for v, sp in spec["add"]:
        if v not in [k for k, _ in keep]:
            keep.append((v, sp))
    return {"value": [v for v, _ in keep], "spans": [sp for _, sp in keep], "doc_seq": base.get("doc_seq")}


def main():
    D.update(EXTRA)
    man = pd.read_csv(S.MANIFEST)
    a, b = S.load_dir(A_DIR), S.load_dir(B_DIR)
    OUT.mkdir(parents=True, exist_ok=True)
    rows, used = [], set()
    for acc in man.accession:
        xa, xb = a[acc], b[acc]
        g = copy.deepcopy(xa)
        g["reconciled_from"] = "pass_a with the decisions in reconciliation.csv"
        ka, kb = S.kind_of(xa), S.kind_of(xb)
        cells = []
        if ka != kb:
            cells.append(("triage.kind", ka, kb))
        for f in ("fund_type", "doc_role"):
            if xa["triage"].get(f) != xb["triage"].get(f):
                cells.append((f"triage.{f}", xa["triage"].get(f), xb["triage"].get(f)))
        if ka == kb and ka != "none":
            va, vb = S.field_values(xa, ka), S.field_values(xb, ka)
            for s in E.FIELDS[ka]:
                if s.scored and not S.equal(va[s.name], vb[s.name], s.dtype):
                    cells.append((s.name, va[s.name], vb[s.name]))
        for name, av, bv in cells:
            key = (acc, name)
            if key not in D:
                raise KeyError(f"no decision for {key}: A={av!r} B={bv!r}")
            used.add(key)
            dec = D[key]
            pick, cause, reason = dec[0], dec[1], dec[2]
            if name.startswith("triage."):
                f = name.split(".", 1)[1]
                if pick == "B":
                    g["triage"][f] = xb["triage"].get(f)
                    if f == "kind":
                        g["events"] = copy.deepcopy(xb["events"])
                        g["triage"]["kind_span"] = xb["triage"].get("kind_span")
                gv = g["triage"].get(f)
            else:
                terms = g["events"][0]["terms"]
                if pick == "B":
                    terms[name] = field_dict(xb, name)
                elif pick == "V":
                    terms[name] = edit_set(xa, xb, name, dec[3])
                gv = (terms.get(name) or {}).get("value") if isinstance(terms.get(name), dict) else None
            rows.append({"accession": acc, "field": name, "a": json.dumps(av, default=sorted), "b": json.dumps(bv, default=sorted),
                         "decision": pick, "gold": json.dumps(gv, default=str), "cause": cause, "reason": reason})
        for (aacc, name), (spec, cause, reason) in AUDIT.items():
            if aacc != acc:
                continue
            av = S.field_values(xa, ka)[name]
            if not S.equal(av, S.field_values(xb, kb)[name], E.field_spec(ka, name).dtype):
                raise ValueError(f"audit cell {aacc} {name} is a disagreement; decide it in D")
            g["events"][0]["terms"][name] = edit_set(g, g, name, spec)
            used.add((aacc, name))
            rows.append({"accession": acc, "field": name, "a": json.dumps(av, default=sorted), "b": json.dumps(av, default=sorted),
                         "decision": "audit", "gold": json.dumps(g["events"][0]["terms"][name]["value"]),
                         "cause": cause, "reason": reason})
        # Span repair: a gold value whose quote is not verbatim takes the other reader's quote for the SAME value.
        text = (S.TEXT_DIR / f"{acc}.txt").read_text()
        fails = {f["field"] for f in S.span_failures(g, text) if f["reason"] == "span_not_in_text"}
        for name in sorted(fails):
            fb = field_dict(xb, name)
            gk = S.kind_of(g)
            gvals = S.field_values(g, gk)[name]
            bvals = S.field_values(xb, gk)[name] if S.kind_of(xb) == gk else None
            if fb is None or not S.equal(gvals, bvals, E.field_spec(gk, name).dtype):
                raise ValueError(f"{acc} {name}: gold span not verbatim and B has no equal value to borrow")
            if any(f["field"] == name for f in S.span_failures({"triage": xb["triage"], "events": [{"kind": gk, "terms": {name: fb}}]}, text)):
                raise ValueError(f"{acc} {name}: B's span fails too")
            g["events"][0]["terms"][name] = fb
            rows.append({"accession": acc, "field": name, "a": "", "b": "", "decision": "span_repair",
                         "gold": json.dumps(fb.get("value"), default=str), "cause": "span_not_verbatim",
                         "reason": "pass A's quote dropped the file's cp1252 quote characters; pass B's quote of the same value is verbatim"})
        ks = g["triage"].get("kind_span")
        if ks and not E.span_in_text(ks, E.normalise(text)):
            kb_span = xb["triage"].get("kind_span")
            if S.kind_of(xb) != S.kind_of(g) or not kb_span or not E.span_in_text(kb_span, E.normalise(text)):
                raise ValueError(f"{acc}: gold kind_span not verbatim and B's cannot replace it")
            g["triage"]["kind_span"] = kb_span
            rows.append({"accession": acc, "field": "triage.kind_span", "a": "", "b": "", "decision": "span_repair",
                         "gold": json.dumps(S.kind_of(g)), "cause": "span_not_verbatim",
                         "reason": "pass A's kind quote dropped the file's cp1252 quote characters; pass B's is verbatim"})
        (OUT / f"{acc}.json").write_text(json.dumps(g, indent=1, ensure_ascii=False))
    unused = (set(D) | set(AUDIT)) - used
    if unused:
        raise KeyError(f"decisions with no disagreement behind them: {sorted(unused)}")
    pd.DataFrame(rows).to_csv(OUT.parent / "reconciliation.csv", index=False)
    print(f"{len(rows)} disagreement cells reconciled; gold written for {len(man)} filings")
    print(pd.DataFrame(rows).groupby(["cause", "decision"]).size().to_string())


if __name__ == "__main__":
    main()
