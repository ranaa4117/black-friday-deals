#!/usr/bin/env python3
"""Elisabetta Franchi dry run (prints only, writes nothing)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u
items, n = u.fetch_ef(debug=True)
print(f"EF dry run: {n} links on page 2 -> {len(items)} maxi dresses")
for p in items:
    print("  ", p["handle"], "|", p["title"], "|", p["price"], p["compare"], "|", p.get("lengthCm"), "|", ",".join(s["s"] + ("" if s["a"] else "(x)") for s in p["sizes"]), "|", p["image"][:90])
