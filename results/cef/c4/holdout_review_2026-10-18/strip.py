import sys, re, html
for p in sys.argv[1:]:
    t = open(p, "rb").read().decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
    t = html.unescape(re.sub(r"(?s)<[^>]+>", " ", t))
    t = re.sub(r"\s+", " ", t)
    print("=====", p.split("/")[-1], len(t)); print(t[:6000])
