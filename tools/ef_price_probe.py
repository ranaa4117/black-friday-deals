#!/usr/bin/env python3
"""Elisabetta Franchi: where the official outlet puts original / discounted prices and discount % (prints only)."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u

def ctx(h, kw, n=3, w=260):
    for m in list(re.finditer(kw, h))[:n]:
        print("     ", re.sub(r"\s+", " ", h[max(0, m.start() - w):m.end() + w]))

lst = u.fetch(u.EF_PAGE, accept="text/html")
print("LIST length", len(lst))
for kw in [r"strike", r"line-through", r"list-price|listPrice|price--list|price-list", r"sales|price__sales|price-sales", r"sconto|discount|-\d{1,2}\s*%|\d{1,2}\s*%", r"€\s*\d", r"pricebook", r"promotion|promo"]:
    c = len(re.findall(kw, lst, re.I))
    print(f"[list] {kw}: {c}")
    ctx(lst, kw, 2)
href = u.ef_page_links()[0]
h = u.fetch(u.EF_SITE + href, accept="text/html")
print("PRODUCT", href, "length", len(h))
for kw in [r"strike", r"line-through", r"list-price|listPrice|price--list|price-list", r"price__sales|price-sales|\"sales\"", r"sconto|discount|-\d{1,2}\s*%", r"pricebook", r"promotion|promo", r'"price"\s*:', r"€\s*\d"]:
    c = len(re.findall(kw, h, re.I))
    print(f"[product] {kw}: {c}")
    ctx(h, kw, 3)
