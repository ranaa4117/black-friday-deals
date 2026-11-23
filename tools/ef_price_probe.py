#!/usr/bin/env python3
"""Elisabetta Franchi: official promotion data per product (prints only)."""
import os, re, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u

def ctx(h, kw, n=3, w=300):
    for m in list(re.finditer(kw, h))[:n]:
        print("     ", re.sub(r"\s+", " ", h[max(0, m.start() - w):m.end() + w]))

lst = u.fetch(u.EF_PAGE, accept="text/html")
print("LIST promo ids:", sorted(set(re.findall(r'"promotionId":"([^"]+)"', lst))))
for kw in [r"calloutMsg", r"promotionalPrice", r"promotionPrice", r"promo_outlet", r"product-price__(?!final)\w+", r"ProductHitBadges__[\w-]+\"[^>]*>[^<]{1,40}<"]:
    print(f"[list] {kw}: {len(re.findall(kw, lst))}"); ctx(lst, kw, 2)
for href in u.ef_page_links()[:23]:
    h = u.fetch(u.EF_SITE + href, accept="text/html")
    promos = re.findall(r'"productPromotions":(\[[^\]]*\])', h)
    prices = sorted(set(re.findall(r'"price":([\d.]+)', h)))
    print("PRODUCT", href.rsplit("/", 1)[-1], "| promos:", promos[:2], "| prices:", prices, "| finals:", re.findall(r'product-price__\w+">([^<]+)<', h)[:4])
    time.sleep(1)
h = u.fetch(u.EF_SITE + u.ef_page_links()[0], accept="text/html")
for kw in [r"calloutMsg", r"promotionalPrice", r"promo_outlet", r"35\s*%", r"product-price__(?!final)\w+", r"strikethrough|crossed|list-price"]:
    print(f"[product] {kw}: {len(re.findall(kw, h))}"); ctx(h, kw, 4)
