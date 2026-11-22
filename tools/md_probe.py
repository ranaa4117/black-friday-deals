#!/usr/bin/env python3
"""Diagnostics for the Mac Duggal US store: collection sizes, markdowns, promotion tags, live promo text."""
import collections, json, re, time, urllib.request
UA = "Mozilla/5.0 (personal sale tracker; github.com/ranaa4117/black-friday-deals)"
def get(u, acc="application/json"):
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept": acc}), timeout=45) as r:
        return r.read().decode("utf-8", "replace")
def coll(h):
    out, page = [], 1
    while page < 20:
        b = json.loads(get(f"https://macduggal.com/collections/{h}/products.json?limit=250&page={page}"))["products"]
        out += b
        if len(b) < 250: break
        page += 1; time.sleep(1.5)
    return out
for h in ["full-length-maxi", "black-friday", "sale"]:
    try:
        ps = coll(h)
        md = [p for p in ps if any(float(v.get("compare_at_price") or 0) > float(v["price"]) for v in p["variants"])]
        tags = collections.Counter(t for p in ps for t in p.get("tags", []) if re.search(r"25|promo|sale|bf|black|cart|final|exclu|discount|markdown", t, re.I))
        print(f"== {h}: {len(ps)} products, {len(md)} marked down")
        print("   promo-ish tags:", tags.most_common(25))
        print("   product types:", collections.Counter(p.get("product_type") for p in ps).most_common(8))
        if ps:
            p = ps[0]; print("   sample:", p["title"], "| options:", [o["name"] for o in p.get("options", [])], "| variant:", {k: p["variants"][0].get(k) for k in ("option1","option2","price","compare_at_price","available")})
    except Exception as e:
        print("==", h, "failed", e)
for u in ["https://macduggal.com/", "https://macduggal.com/collections/black-friday"]:
    try:
        html = get(u, "text/html")
        hits = set(re.sub(r"\s+", " ", m.group(0)) for m in re.finditer(r"[^<>\"]{0,120}(25%|In Cart|BF25|code)[^<>\"]{0,120}", html, re.I))
        print("== text on", u); [print("   ", h[:240]) for h in list(hits)[:25]]
    except Exception as e:
        print("text failed", u, e)
