#!/usr/bin/env python3
"""Diagnostics for the Mac Duggal US store: where the '+25% Off In Cart' badge and promo terms come from."""
import json, re, urllib.request
UA = "Mozilla/5.0 (personal sale tracker; github.com/ranaa4117/black-friday-deals)"
def get(u, acc="text/html"):
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept": acc}), timeout=45) as r:
        return r.read().decode("utf-8", "replace")
KEYS = re.compile(r"In Cart|BFCM|Exempt Styles|No Promo|25% ?off|extra 25|sitewide|Final ?Sale|exclusion", re.I)
def ctx(text, label, limit=14):
    seen = set()
    for m in KEYS.finditer(text):
        s = re.sub(r"\s+", " ", text[max(0, m.start() - 160): m.end() + 200])
        k = s[100:220]
        if k in seen: continue
        seen.add(k); print(f"  [{label}]", s[:420])
        if len(seen) >= limit: break
home = get("https://macduggal.com/")
print("== homepage"); ctx(home, "home")
prod = json.loads(get("https://macduggal.com/collections/black-friday/products.json?limit=250", "application/json"))["products"]
elig = next(p for p in prod if "BFCM25" in p["tags"] and "Exempt Styles - No Promo" not in p["tags"])
ex = next((p for p in prod if "Exempt Styles - No Promo" in p["tags"]), None)
for p in [elig, ex]:
    if not p: continue
    print("== product page", p["handle"], p["tags"][:30])
    ctx(get(f"https://macduggal.com/products/{p['handle']}"), "product")
assets = sorted(set(re.findall(r"(?:https:)?//macduggal\.com/cdn/shop/t/\d+/assets/[\w.\-]+\.js[^\"' ]*|/cdn/shop/t/\d+/assets/[\w.\-]+\.js[^\"' ]*", home)))
print("== theme scripts:", len(assets))
for a in assets[:40]:
    u = a if a.startswith("http") else ("https:" + a if a.startswith("//") else "https://macduggal.com" + a)
    try:
        js = get(u, "*/*")
        if KEYS.search(js): print("== script", u.split("/assets/")[-1][:60]); ctx(js, "js", 8)
    except Exception as e:
        print("  script failed", u[-60:], e)
links = sorted(set(re.findall(r'href="(/pages/[^"#?]+)"', home)))
print("== /pages links:", links[:40])
for l in [x for x in links if re.search(r"promo|offer|term|sale|black|bf|discount|exclu", x, re.I)][:6]:
    try: print("== page", l); ctx(get("https://macduggal.com" + l), "page", 10)
    except Exception as e: print("  failed", e)
