#!/usr/bin/env python3
"""Dry run of the Mac Duggal collection (prints a summary, writes nothing)."""
import collections, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u
items, raw = u.fetch_md()
c = collections.Counter(("BF" if p["bf"] else "sale" if p["markdown"] else "-") + "+" + ("25" if p["extra25"] else "no25") for p in items)
print(f"MD dry run: {raw} in maxi collection -> {len(items)} eligible; by type {dict(c)}")
print("in stock:", sum(1 for p in items if any(s["a"] for s in p["sizes"])), "| no image:", sum(1 for p in items if not p["image"]))
print("sizes seen:", collections.Counter(s["s"] for p in items for s in p["sizes"]).most_common(20))
print("colors seen:", collections.Counter(c for p in items for c in p["colors"]).most_common(40))
for p in items[:4] + [x for x in items if x["bf"] and x["extra25"]][:2]:
    print("  sample:", p["title"], p["price"], p["compare"], "bf" if p["bf"] else "", "25" if p["extra25"] else "", p["url"])
print("usd rate:", u.fetch_usd_rate())
