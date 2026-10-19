"""Zero-trial deal counts for the E1 pre-registration draft (2026-10-19).

    python3 scripts/events/e1_prereg_counts.py                    # reads crsp_events.CACHE
    python3 scripts/events/e1_prereg_counts.py --cache <dir>      # a CRSP cache pulled elsewhere

WHAT THIS IS FOR
----------------
`results/events/PREREG_E1_MERGER_PAIR_2026-10-19.md` (a DRAFT awaiting the team
lead) declares which CEF/BDC merger deals are E1's fit, which are held out, and
which are excluded, before any E1 return exists. This script counts each set by
segment so the draft can state its sizes and the power of its holdout rule.

WHAT IT DOES NOT DO (zero trials)
---------------------------------
It computes no return of any kind. From CRSP's delisting table it reads ONLY
`DELIST_COLUMNS` (permno, delisting date, delisting code, acquirer permno): the
delisting return, the amount and the price are never loaded, and a test pins
that (`test_e1_prereg_counts.py`). The name table carries no return. No daily
`dsf` file is opened. So the 2023-24 deals here are counted, never priced: the
2023-01-01 time holdout stays sealed, and no `cef_universe.csv` name is priced,
so the 27-name set is not consumed by this script.

THE DECLARED PARTITION (the draft's §4; each deal falls in exactly one)
----------------------------------------------------------------------
The deal universe is `merger_pairs.build_events` on 2010-01-01 .. 2024-12-31
completions (CRSP's delistings end 2024-12-31), kept to stock-for-stock deals
with an acquirer permno -- the published E1 sample's own filter
(`merger_pairs.pairable_events`, without its universe exclusion). Then:

  excluded_spec : the target or the acquirer is one of the frozen spec's names
                  (read through scripts/cef/spec.py, never written here). The
                  live sleeve cannot trade them beside the CEF book (draft §1);
  time_holdout  : completion on or after 2023-01-01;
  name_holdout  : completion before 2023 and a `cef_universe.csv` name on either
                  side (ticker or permno, `merger_pairs.flag_universe`): pair
                  returns on these deals have never been computed;
  fit_seen      : the rest. Their at-announcement pair returns were published
                  on 2026-10-12 (`results/events/EDGAR_EVENTS_2026-10-12.md` §3),
                  so they are not out of sample.

Groups are acquirer permno x completion date (G1c's clustering). The trial
clusters on acquirer x EDGAR announcement date, which needs the EDGAR dates and
is counted at its Stage 0; a group that would straddle two sets raises, because
one board's announcement cannot be half fit and half holdout.

Failed and withdrawn deals are NOT here: CRSP's delisting table holds completed
deals only. The draft's data gate DG-E1-3 builds them from EDGAR.

ENVIRONMENT: `compute.use_numexpr` off, as every script in scripts/events/
(scripts/events/numexpr_fault.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

pd.set_option("compute.use_numexpr", False)

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # run as a script, not -m
    sys.path.insert(0, str(REPO))

from scripts.events import crsp_events as ce  # noqa: E402
from scripts.events import merger_pairs as mp  # noqa: E402

OUT = REPO / "results" / "events" / "e1_prereg_counts_2026-10-19.json"
START, END = pd.Timestamp("2010-01-01"), pd.Timestamp("2024-12-31")
# The only delisting columns this script may read. dlret, dlretx, dlamt and
# dlprc carry the merger's payoff; loading them is how a "count" quietly turns
# into a return, so they are not loaded at all.
DELIST_COLUMNS = ("permno", "dlstdt", "dlstcd", "nwperm")
PARTS = ("fit_seen", "name_holdout", "time_holdout", "excluded_spec")


def load(cache: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(names, delistings) from a crsp_events cache, delistings column-limited."""
    nm = pd.read_parquet(cache / "dsenames.parquet")
    for c in ("namedt", "nameendt"):
        nm[c] = pd.to_datetime(nm[c])
    dl = pd.read_parquet(cache / "dsedelist.parquet", columns=list(DELIST_COLUMNS))
    dl["dlstdt"] = pd.to_datetime(dl["dlstdt"])
    return nm, dl


def spec_touch(x: pd.DataFrame, nm: pd.DataFrame, spec_names: set) -> pd.Series:
    """True where the target or the acquirer is a spec name, by ticker or by
    permno (a universe fund under an older ticker counts, as in flag_universe)."""
    up = ce.universe_permnos(nm)
    perm2tk = {p: tk for tk, ps in up.items() for p in ps}
    tkt = x["permno"].map(perm2tk).fillna(x["ticker"])
    tka = x["nwperm"].map(perm2tk).fillna(x["a_ticker"])
    return tkt.isin(spec_names) | tka.isin(spec_names)


def partition(x: pd.DataFrame) -> pd.Series:
    """The draft's §4 partition. Needs columns spec_touch, touch_uni, dlstdt."""
    part = pd.Series("fit_seen", index=x.index)
    part[x["touch_uni"]] = "name_holdout"
    part[x["dlstdt"] >= ce.TIME_HOLDOUT] = "time_holdout"
    part[x["spec_touch"]] = "excluded_spec"   # last: exclusion overrides both holdouts
    return part


def assert_groups_whole(x: pd.DataFrame) -> None:
    """One acquirer x completion-date group must sit in one set."""
    n = x.groupby(["nwperm", "dlstdt"])["part"].nunique()
    split = n[n > 1]
    if len(split):
        raise AssertionError(f"{len(split)} acquirer x date group(s) straddle two sets: "
                             f"{list(split.index[:5])}")


def counts(x: pd.DataFrame) -> list[dict]:
    rows = []
    for (part, seg), g in x.groupby(["part", "seg"]):
        rows.append({"set": part, "segment": seg, "events": int(len(g)),
                     "groups_acq_x_completion": int(g.groupby(["nwperm", "dlstdt"]).ngroups),
                     "events_on_the_27": int(g["touch_comparison27"].sum())})
    for part, g in x.groupby("part"):
        rows.append({"set": part, "segment": "ALL", "events": int(len(g)),
                     "groups_acq_x_completion": int(g.groupby(["nwperm", "dlstdt"]).ngroups),
                     "events_on_the_27": int(g["touch_comparison27"].sum())})
    return rows


def build(nm: pd.DataFrame, dl: pd.DataFrame, spec_names: set) -> pd.DataFrame:
    x = mp.build_events(nm, dl, start=START, end=END)
    x = mp.flag_universe(x, nm)
    x = x[(x["dlstcd"] == 231) & (x["kind"] == "stock") & (x["nwperm"] > 0)].copy()
    x["seg"] = x["comnam"].map(mp.classify)
    x["spec_touch"] = spec_touch(x, nm, spec_names)
    x["part"] = partition(x)
    assert_groups_whole(x)
    return x


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, default=ce.CACHE,
                    help="directory holding dsenames.parquet and dsedelist.parquet "
                         "(crsp_events' cache; default results/events/_cache_crsp)")
    a = ap.parse_args(argv)
    for f in ("dsenames.parquet", "dsedelist.parquet", "_manifest.json"):
        if not (a.cache / f).exists():
            raise FileNotFoundError(f"{a.cache / f} is missing: run crsp_events' pulls "
                                    "(scripts/events/merger_pairs.py) or pass --cache")
    sys.path.insert(0, str(REPO / "scripts" / "cef"))
    import spec  # noqa: E402  (the frozen spec is the only authority on the live universe)
    spec_names = set(spec.frozen("universe"))
    nm, dl = load(a.cache)
    x = build(nm, dl, spec_names)
    manifest = json.loads((a.cache / "_manifest.json").read_text())
    res = {
        "what": "E1 pre-registration draft, deal counts by declared set and segment. "
                "Counts only: no return, delisting return or amount was read.",
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "spec_id": spec.spec()["spec_id"],
        "n_spec_names": len(spec_names),
        "completions": [str(START.date()), str(END.date())],
        "crsp_pulled_utc": {k: manifest[k]["pulled_utc"] for k in ("dsenames", "dsedelist")},
        "filter": "dlstcd 231, kind 'stock', acquirer permno > 0 (merger_pairs.pairable_events "
                  "without its universe exclusion)",
        "counts": counts(x),
    }
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    t = pd.DataFrame(res["counts"]).pivot_table(index="segment", columns="set",
                                                values=["events", "groups_acq_x_completion"],
                                                aggfunc="sum").fillna(0).astype(int)
    print(t.to_string())
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
