#!/usr/bin/env python3
"""Mac Duggal diagnostics: the store's promotion labels and which feed products carry each tag (prints only)."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u

h = u.fetch(u.MD_STORE + "/", accept="text/html")
m = re.search(r"cardHighlights\s*=\s*(\[.*?\])\s*;", h, re.S)
print("cardHighlights:", m.group(1)[:3000] if m else None)
for kw in ("BFCM", "Off In Cart", "Extra 25", "Cyber", "Black Friday"):
    for mm in list(re.finditer(re.escape(kw), h))[:3]:
        print(f"  [{kw}]", re.sub(r"\s+", " ", h[max(0, mm.start() - 150):mm.end() + 150]))
print("parsed promo:", u.fetch_md_promo())

items = u.fetch_md_collection(u.MD_MAXI)
tags = {}
for p in items:
    for t in u.tag_list(p):
        if re.search(r"bfcm|markdown|sale|promo|extra|cyber|black", t, re.I):
            tags[t] = tags.get(t, 0) + 1
print("feed items:", len(items), "| promo-like tag counts:", tags)
md_mark = sum(1 for p in items if any(float(v.get("compare_at_price") or 0) > float(v.get("price") or 0) for v in p.get("variants", [])))
print("items with a compare-at markdown:", md_mark)
for hd in ["11627", "56086-gold", "68885", "27690", "11281", "11779"]:
    try:
        j = u.get_json(f"{u.MD_STORE}/products/{hd}.json")["product"]
        v = j["variants"][0]
        print(" ", hd, "| price", v["price"], "compare", v.get("compare_at_price"),
              "| tags:", [t for t in u.tag_list(j) if re.search(r"bfcm|markdown|sale|promo|extra|cyber|black", t, re.I)])
    except Exception as e:  # noqa: BLE001
        print(" ", hd, "error", e)
