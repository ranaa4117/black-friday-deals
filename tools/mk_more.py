#!/usr/bin/env python3
"""Official US stores that are not Shopify: Charlotte Tilbury (/us), NARS (/USA), Too Faced (US site).
Writes self-portrait/mk_more.json in the same product format as mk_brands.json.
Only prices and discounts the official US page itself shows are used:
  - Charlotte Tilbury: each product's listing price and purchase price (USD) in the page data
  - NARS: each product's own "N% Off" badge on the US listing, with the code the US site shows
  - Too Faced: the US Sale page's two prices per product (read in a real browser)
A failed read keeps the last confirmed data (marked stale)."""
import asyncio, html as H, json, os, re, sys, time, urllib.request
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mk_common as mk

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "self-portrait", "mk_more.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def rec(brand, pid, title, url, image, price, compare, cat_hint="", promo=None, available=True):
    if mk.not_beauty(title) or mk.is_fragrance(title, cat_hint):
        return None
    is_set = mk.is_set(title, cat_hint)
    r = {"id": f"mk-{brand}-{pid}", "brand": brand, "src": "brand", "retailer": mk.BRANDS[brand], "title": title, "url": url, "type": cat_hint,
         "cat": mk.category(title, cat_hint), "set": is_set, "image": image, "images": [image] if image else [],
         "variants": [{"id": pid, "name": "", "price": price, "compare": compare if compare and compare > price else None, "a": available, "image": image}],
         "price": price, "compare": compare if compare and compare > price else None, "available": available}
    if r["compare"]:
        r["discPct"] = round(100 * (1 - price / r["compare"]))
    if promo:
        r["promo"] = promo
    return r


def charlotte():
    out = []
    for path, hint in (("/us/products/makeup", "makeup"), ("/us/products/gifts/value-sets", "set")):
        h = fetch("https://www.charlottetilbury.com" + path)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', h, re.S)
        d = json.loads(m.group(1))
        prods = d["props"]["initialState"]["page"]["model"]["products"]
        for i, p in enumerate(prods):
            pr = p.get("price") or {}
            lp, pp = (pr.get("listingPrice") or {}), (pr.get("purchasePrice") or {})
            if lp.get("currencyCode") != "USD" or pp.get("currencyCode") != "USD":
                continue
            img = (p.get("image") or {}).get("imageSrc") or ""
            img = ("https:" + img if img.startswith("//") else img) + ("?w=800&fm=jpg&bg=rgb%3Affffff" if img else "")
            title = (p.get("title") or "").strip()
            sub = (p.get("cardDescription") or p.get("category") or "")
            r = rec("ct", p.get("href"), title.title() if title.isupper() else title, f"https://www.charlottetilbury.com/us/product/{p.get('href')}",
                    img, float(pp["value"]), float(lp["value"]), f"{hint} {sub}", available=(p.get("availability") or "").upper() != "OUT_OF_STOCK")
            if r:
                if hint == "set":
                    r["set"] = True
                r["storeRank"] = i + 1
                out.append(r)
    return out


def nars():
    home = fetch("https://www.narscosmetics.com/")
    code = (re.search(r"CODE:\s*([A-Z0-9]{3,20})", H.unescape(re.sub(r"<[^>]+>", " ", home))) or [None, None])[1]
    h = fetch("https://www.narscosmetics.com/USA/makeup?sz=600")
    m = re.search(r"var productData = (\{.+?\});\s*\n", h, re.S)
    data = json.loads(m.group(1)) if m else {"product": []}
    badges = {}
    for tile in re.finditer(r'data-itemid="([^"]+)"(.{0,4000}?)END: \.product-tile', h, re.S):
        b = re.search(r"badge-product--text[^>]*>\s*(\d{2})% Off\s*<", tile.group(2), re.I)
        href = re.search(r'data-href="([^"]+)"', tile.group(0))
        if b:
            badges[tile.group(1)] = (int(b.group(1)), H.unescape(href.group(1)).split("?")[0] if href else "")
    out = []
    for i, p in enumerate(data.get("product") or []):
        if p.get("id") not in badges or not p.get("price"):
            continue
        pct, url = badges[p["id"]]
        price = float(p["price"])
        r = rec("nars", p["id"], p.get("name", ""), url or f"https://www.narscosmetics.com/USA/{p['id']}.html", p.get("img_url", "").replace("sw=856&sh=750", "sw=800&sh=800"),
                round(price * (1 - pct / 100), 2), price, f"{p.get('subCategory', '')} {p.get('subSubCategory', '')}",
                promo={"pct": pct, "label": f"{pct}% Off", "code": code, "applied": "code" if code else "checkout"},
                available=p.get("productOutOfStock") != "OUT_OF_STOCK")
        if r:
            r["storeRank"] = i + 1
            out.append(r)
    return out


async def toofaced():
    from playwright.async_api import async_playwright
    out = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
        ctx = await b.new_context(user_agent=UA, locale="en-US", viewport={"width": 1366, "height": 900}, timezone_id="America/New_York")
        pg = await ctx.new_page()
        await pg.goto("https://www.toofaced.com/products/23791/sale", wait_until="domcontentloaded", timeout=90000)
        await pg.wait_for_timeout(9000)
        for _ in range(12):
            await pg.mouse.wheel(0, 2500); await pg.wait_for_timeout(700)
        items = await pg.evaluate("""() => [...document.querySelectorAll('.js-product-grid-item[data-product-id]')].map(e => {
            const a = e.querySelector('a[href*="/product/"]'), im = e.querySelector('img');
            return { id: e.dataset.productId, text: e.innerText, href: a ? a.href : '', img: im ? (im.currentSrc || im.src || im.dataset.src || '') : '' }; })""")
        await b.close()
    seen = set()
    for i, it in enumerate(items):
        if it["id"] in seen:
            continue
        lines = [x.strip() for x in it["text"].split("\n") if x.strip() and x.strip() not in ("SALE", "ADD TO BAG", "SOLD OUT")]
        prices = [float(x.replace("$", "").replace(",", "")) for x in re.findall(r"\$\d[\d,]*\.\d{2}", it["text"])]
        if len(prices) < 2 or not lines:
            continue
        seen.add(it["id"])
        title = lines[0]
        r = rec("toofaced", it["id"], title, it["href"].split("#")[0], it["img"], min(prices[:2]), max(prices[:2]), " ".join(lines[1:3]),
                available="SOLD OUT" not in it["text"])
        if r:
            r["storeRank"] = len(out) + 1
            out.append(r)
    return out


def main():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        old = json.load(open(OUT))
    except Exception:
        old = {"products": [], "meta": {"brands": {}}}
    last = (old.get("meta") or {}).get("updatedAt", "")
    if last and os.environ.get("MK_FORCE") != "1":
        age = (datetime.now(timezone.utc) - datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
        if age < 175 * 60:
            print("mk_more: checked", round(age / 60), "minutes ago"); return
    prods, status = [], {}
    for brand, fn in (("ct", charlotte), ("nars", nars), ("toofaced", lambda: asyncio.run(toofaced()))):
        try:
            got = fn()
            for r in got:
                r["checkedAt"] = ts
                r["source"] = r["url"].split("/")[2] + " (official US store)"
            prods += got
            status[brand] = {"ok": True, "at": ts, "lastOk": ts, "discounted": sum(1 for r in got if r["compare"] and not r["set"]), "sets": sum(1 for r in got if r["set"]), "us": "US / USD"}
            print(brand, "products", len(got))
        except Exception as e:
            keep = [dict(p, stale=True) for p in old.get("products", []) if p["brand"] == brand]
            prods += keep
            status[brand] = {"ok": False, "at": ts, "error": f"{type(e).__name__}: {str(e)[:160]}", "lastOk": ((old.get("meta") or {}).get("brands", {}).get(brand) or {}).get("lastOk")}
            print(brand, "FAILED", e)
        time.sleep(2)
    json.dump({"meta": {"updatedAt": ts, "brands": status}, "products": prods}, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
