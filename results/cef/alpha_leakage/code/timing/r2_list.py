"""Read-only: list every top-level prefix in the R2 bucket and every wrds/<schema>/ object
whose name hints at intraday data. Prints redacted keys only; writes nothing."""
import sys, re, collections
sys.path.insert(0, "/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027")
from src.data import r2
cfg = r2.load_config()
con = r2.connect(cfg)
base = f"s3://{cfg.bucket}" if hasattr(cfg, "bucket") else None
assert base, "R2Config has no bucket attribute"
rows = [r[0] for r in con.execute("SELECT file FROM glob(?)", [f"{base}/**"]).fetchall()]
red = [f.replace(base, "s3://<bucket>", 1) for f in rows]
top = collections.Counter("/".join(f.split("/")[3:5]) for f in red)
print("objects:", len(red))
for k, v in sorted(top.items()):
    if not k.startswith("options/"): print(f"  {k:<40} {v}")
print("option underlyings:", sorted({f.split('/')[4] for f in red if '/options/' in f}))
hint = [f for f in red if re.search(r"taq|intraday|minute|ctm|cqm|nbbo|_ms_|wct|ticks?(?!/)", f.lower()) and "/options/" not in f]
print("intraday-looking non-option objects:", hint[:20], len(hint))
print("---- all top-level prefixes (non-wrds, non-options) ----")
for k, v in sorted(top.items()):
    if not k.startswith(("options/", "wrds/")): print(f"  {k:<40} {v}")
print("---- every object with 'taq' or 'midas' in the key ----")
for f in red:
    if re.search(r"taq|midas", f.lower()): print("  ", f)
