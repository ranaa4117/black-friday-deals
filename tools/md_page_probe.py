#!/usr/bin/env python3
"""Mac Duggal product-page diagnostics: how the official product page decides to show a promotion label (prints only)."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u

handles = (os.environ.get("MD_HANDLES") or "6135,30777,11782,11779,5679_silvernude,13003").split(",")
for hd in handles:
    print("=" * 30, hd)
    try:
        j = u.get_json(f"{u.MD_STORE}/products/{hd}.json")["product"]
        v = j["variants"][0]
        print("price", v["price"], "compare", v.get("compare_at_price"), "| tags:", u.tag_list(j))
    except Exception as e:  # noqa: BLE001
        print("json error", e)
    try:
        h = u.fetch(f"{u.MD_STORE}/products/{hd}", accept="text/html")
        print("html length", len(h))
        for kw in ("cardHighlights", "Highlights", "Extra 25", "Price as marked", "markdown", "highlight"):
            hits = list(re.finditer(re.escape(kw), h))
            print(f"  [{kw}] x{len(hits)}")
            for mm in hits[:2]:
                print("     ", re.sub(r"\s+", " ", h[max(0, mm.start() - 200):mm.end() + 250]))
    except Exception as e:  # noqa: BLE001
        print("html error", e)
