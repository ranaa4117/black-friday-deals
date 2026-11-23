#!/usr/bin/env python3
"""Where does Mac Duggal publish its product-label promotion? (prints only)"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u
for path in ["/", "/collections/full-length-maxi", "/collections/black-friday", "/products/49981-navy"]:
    try:
        h = u.fetch(u.MD_STORE + path, accept="text/html")
        i = h.find("cardHighlights")
        print(path, len(h), "cardHighlights at", i, "|", re.sub(r"\s+", " ", h[max(0, i - 80):i + 400]) if i >= 0 else "")
        for k in ("BFCM25", "Off In Cart", "% Off"):
            j = h.find(k); print("   ", k, j, re.sub(r"\s+", " ", h[max(0, j - 150):j + 100]) if j >= 0 else "")
    except Exception as e:
        print(path, "ERR", e)
