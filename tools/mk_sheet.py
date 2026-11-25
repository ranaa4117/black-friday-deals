#!/usr/bin/env python3
"""Contact sheets of the main photo of every brand-store Makeup product, for a visual check
(no model-body photos). MK_SHEET_IDS="id1,id2" instead shows every gallery photo of those products."""
import io, json, os, sys, urllib.request
from PIL import Image, ImageDraw

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "self-portrait")
OUT = "/tmp/mksheet"; os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
T = 150


def thumb(url):
    if "cdn.shopify.com" in url or "/cdn/shop/" in url:
        url += ("&" if "?" in url else "?") + "width=300"
    req = urllib.request.Request(url if url.startswith("http") else "https:" + url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        im = Image.open(io.BytesIO(r.read())).convert("RGB")
    im.thumbnail((T, T)); return im


def sheet(items, name, cols=8):
    rows = (len(items) + cols - 1) // cols
    S = Image.new("RGB", (cols * (T + 6), rows * (T + 22)), "white"); d = ImageDraw.Draw(S)
    for i, (label, url) in enumerate(items):
        x, y = (i % cols) * (T + 6), (i // cols) * (T + 22)
        try:
            S.paste(thumb(url), (x, y + 18))
        except Exception:
            d.text((x + 4, y + 60), "ERR", fill="red")
        d.text((x + 2, y + 2), label[:34], fill="black")
    S.save(f"{OUT}/{name}.jpg", quality=80)


def main():
    d = json.load(open(os.path.join(ROOT, "mk_brands.json")))
    ps = d["products"]
    ids = [x for x in os.environ.get("MK_SHEET_IDS", "").split(",") if x]
    index = {}
    if os.environ.get("MK_SHEET_IDS") == "gifts":
        m = json.load(open(os.path.join(ROOT, "makeup.json")))
        un = [g for g in m["gifts"] if g.get("add") is None and g.get("image")]
        global T
        T = 190
        for n in range(0, len(un), 30):
            chunk = un[n:n + 30]
            sheet([(f"{n + i} {g.get('title', '')[:30]}", g["image"]) for i, g in enumerate(chunk)], f"gifts_{n // 30:02d}", cols=6)
            for i, g in enumerate(chunk):
                index[n + i] = {"id": g["id"], "title": g["title"], "brand": g.get("brand"), "price": g.get("price"), "contents": g.get("contents", [])[:12]}
    elif ids:
        for k, pid in enumerate(ids):
            p = next((x for x in ps if x["id"] == pid), None)
            if not p: continue
            imgs = list(dict.fromkeys([p.get("image")] + (p.get("images") or []) + [v.get("image") for v in p.get("variants", []) if v.get("image")]))[:24]
            sheet([(f"{k}.{j}", u) for j, u in enumerate(imgs)], f"alt_{k}")
            index[k] = {"id": pid, "images": imgs}
    else:
        items = [(p["id"], p["image"]) for p in ps if p.get("image")]
        for n in range(0, len(items), 48):
            chunk = items[n:n + 48]
            sheet([(str(n + i), u) for i, (_, u) in enumerate(chunk)], f"sheet_{n // 48:02d}")
            for i, (pid, u) in enumerate(chunk):
                index[n + i] = {"id": pid, "image": u}
    json.dump(index, open(f"{OUT}/index.json", "w"), indent=0)
    print("sheets written", len(index))


main()
