# scripts/_archive

Research code kept because it is the **sole code behind a number that is still
quoted**, and deleting it would make that number unfalsifiable. Nothing here is
imported by anything, and nothing here is on a live path.

The test W0 Part D applies: *what does deleting it cost if you are wrong?* A
research script that is the only code behind a published figure costs you the
ability to reproduce that figure — archive it. A one-off with its output already
committed costs nothing — delete it.

---

## `cef_sleeve.py`, `cef_sleeve_v2.py`

The first two research implementations of the CEF discount sleeve, both dated
2026-07-31. Superseded by `src/deploy/sleeves/cef_discount.py`, which is the
deployed strategy.

**Zero references anywhere in the repo** — verified 2026-09-10 by searching for
the module path (not the basename; basenames here collide with English, and
`signal`, `costs`, `book`, `trials` and `pairs` each match dozens of prompt files
as ordinary words).

**Kept because their outputs are cited evidence.** These scripts produced

```
results/cef/cef_sleeve_daily.parquet        (v1)
results/cef/cef_sleeve_v2_daily.parquet     (v2)
results/cef/cef_sleeve_v3_daily.parquet     (v3, from a later revision)
```

which are the daily return paths behind figures in `docs/RESEARCH_STATE.md` and
`results/cef/ESTIMATOR_NOTE.md`. **The parquets stay where they are** — they are
results, not code, and moving them would break the citations. Deleting the
scripts would leave those parquets as numbers nobody could regenerate or check.

Their docstrings are also the clearest surviving statement of *why* the z-score
is against each fund's own history rather than the cross-section — the argument
that a levered muni CEF structurally trades wider, so ranking on the raw discount
is a permanent long-muni bet in costume. That reasoning is load-bearing and is
repeated in the live sleeve, but this is where it was first written down.

Archived 2026-09-10 (W0 Part D). **Do not run them**: they read panels that have
moved on and they do not implement the band, so their output would not be
comparable to anything current. Read them; do not execute them.
