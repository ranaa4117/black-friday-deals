#!/usr/bin/env python3
"""Victoria's Secret: can the official site be read from here, and where is the product data (prints only)."""
import os, re, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u
for url in ["https://www.victoriassecret.com/us/vs/sleepwear-and-lingerie-catalog/5000000360",
            "https://www.victoriassecret.com/us/vs/sleepwear/pajamas",
            "https://api.victoriassecret.com/products/v41/page/5000000360?activeCountry=US&brand=vs&isPersonalized=false&platform=web&perzConsent=false",
            "https://www.victoriassecret.com/us/vs/shoes-catalog"]:
    try:
        h = u.fetch(url, accept="text/html,application/json")
        print("OK", len(h), url)
        for kw in [r"__NEXT_DATA__", r'"salePrice"', r'"price"', r'"originalPrice"', r"application/ld\+json", r'"images?"', r"api\.victoriassecret\.com[^\"' ]{0,120}"]:
            ms = list(re.finditer(kw, h))
            print(f"   {kw}: {len(ms)}", re.sub(r"\s+", " ", h[ms[0].start():ms[0].start()+300]) if ms else "")
    except Exception as e:  # noqa: BLE001
        print("FAIL", url, e)
