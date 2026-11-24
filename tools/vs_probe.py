#!/usr/bin/env python3
"""Victoria's Secret: dump listing + product pages for inspection (writes /tmp/vs/*.html)."""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u
os.makedirs("/tmp/vs", exist_ok=True)
B = "https://www.victoriassecret.com/us/vs/"
pages = {"slippers": B + "sleepwear/slippers", "slippers-robes": B + "sleepwear/slippers-and-robes", "robes": B + "sleepwear/robes",
         "cosmetic": B + "accessories/cosmetic-bags", "pajamas": B + "sleepwear/pajamas",
         "p_flannel": B + "sleepwear-and-lingerie-catalog/5000000360", "p_modal": B + "sleepwear-and-lingerie-catalog/5000007337",
         "p_satin": B + "sleepwear-and-lingerie-catalog/5000000279", "p_plush": B + "sleepwear-and-lingerie-catalog/5000008347",
         "p_4bag": B + "accessories-catalog/5000007992", "p_nested": B + "accessories-catalog/5000011697",
         "search_slipper": "https://www.victoriassecret.com/us/search?q=slippers", "shoes": B + "shoes", "sale": B + "sale"}
for k, url in pages.items():
    try:
        h = u.fetch(url, accept="text/html")
        open(f"/tmp/vs/{k}.html", "w").write(h)
        names = sorted(set(re.findall(r'"name":"([^"]{4,90})"', h)))
        print("OK", k, len(h), "names:", [n for n in names if re.search(r"(?i)slipper|robe|bag|case|pajama|slide|bootie|mule", n)][:60])
    except Exception as e:  # noqa: BLE001
        print("FAIL", k, url, e)
    time.sleep(2)
