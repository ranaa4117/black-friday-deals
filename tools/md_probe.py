#!/usr/bin/env python3
"""Why do some Mac Duggal dresses drop out of the feed? (prints only)"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u
for attempt in range(2):
    items = u.fetch_md_collection(u.MD_MAXI)
    hs = {p["handle"]: p for p in items}
    tagged = sum(1 for p in items if "BFCM25" in u.tag_list(p))
    print(f"run {attempt}: {len(items)} items, {len(hs)} unique, BFCM25-tagged {tagged}")
    for h in ["56086-gold", "49981-navy"]:
        p = hs.get(h)
        print("  in feed:", h, bool(p), "| tagged:", p and "BFCM25" in u.tag_list(p))
        j = u.get_json(f"{u.MD_STORE}/products/{h}.json")["product"]
        print("  product.json tagged:", "BFCM25" in u.tag_list(j), "| price", j["variants"][0]["price"], j["variants"][0].get("compare_at_price"))
    time.sleep(5)
