#!/usr/bin/env python3
"""Victoria's Secret: list collections through the store's own listing data (prints only)."""
import os, re, sys, time, json, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u
os.makedirs("/tmp/vs", exist_ok=True)
API = "https://api.victoriassecret.com/stacks/v45/"
for name, cid in (("slippers", "1678ea9f-3adc-4a62-aabe-dec05cde7d7c"), ("robes", "5c14bb13-c3d3-4f7b-a3ad-a6632a3f0060"), ("cosmetic", "6bf40943-0852-4c12-bbe3-ead7386ec189")):
    q = {"collectionId": cid, "brand": "vs", "orderBy": "REC", "isDomestic": "true", "isBrasOrPanties": "false", "limit": "180", "platform": "web", "activeCountry": "US"}
    try:
        d = json.loads(u.fetch(API + "?" + urllib.parse.urlencode(q)))
    except Exception as e:  # noqa: BLE001
        print("FAIL", name, e); continue
    json.dump(d, open(f"/tmp/vs/stack_{name}.json", "w"))
    seen = set()
    print("==", name, "total", d.get("TotalItems"))
    for st in d.get("stacks", []):
        for it in st.get("list", []):
            pid = re.search(r"catalog/(\d+)", it["url"]).group(1)
            k = (it["name"], pid)
            if k in seen: continue
            seen.add(k)
            print("  ", it["name"], "|", pid, "|", json.dumps(it.get("price"))[:160])
    time.sleep(2)
for k, url in {"p_revrobe": "https://www.victoriassecret.com/us/vs/sleepwear-and-lingerie-catalog/5000012041"}.items():
    open(f"/tmp/vs/{k}.html", "w").write(u.fetch(url, accept="text/html"))
