#!/usr/bin/env python3
"""Access test: can Macy's product pages be read from GitHub's servers? Prints status and whether prices are present."""
import re, urllib.request, urllib.error
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
URLS = [
  "https://www.macys.com/shop/product/lauren-ralph-lauren-womens-crested-quilted-jacket?ID=26712533",
  "https://www.macys.com/shop/product/lauren-ralph-lauren-womens-collared-coat?ID=26712518",
  "https://www.macys.com/shop/product/?ID=26968208",
]
for u in URLS:
    try:
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            print(r.status, len(body), u[-30:])
            print("   prices:", re.findall(r"\$\d{2,3}\.\d\d", body)[:6], "| blocked:", "Access Denied" in body or "captcha" in body.lower())
            for k in ("\"salePrice\"", "\"retailPrice\"", "\"price\":", "Black Friday Deal", "% off"):
                i = body.find(k); print("   ", k, i, body[i:i+120].replace("\n"," ") if i >= 0 else "")
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, u[-30:])
    except Exception as e:
        print("ERR", type(e).__name__, str(e)[:120], u[-30:])
