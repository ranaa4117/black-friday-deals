#!/usr/bin/env python3
"""Makeup sources probe: can the updater read Sephora USA and the 13 brand stores?
Plain HTTP first, then a real browser (Chrome). Saves page HTML and a summary to /tmp/mk for checking."""
import asyncio, json, os, re, urllib.request, ssl

OUT = "/tmp/mk"; os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
SEPHORA = {
    "sephora_home": "https://www.sephora.com/",
    "sephora_sale": "https://www.sephora.com/sale",
    "sephora_offers": "https://www.sephora.com/beauty/beauty-offers",
    "sephora_cyber": "https://www.sephora.com/beauty/cyber-week-deals",
    "sephora_bf": "https://www.sephora.com/beauty/black-friday-deals",
    "sephora_gifts": "https://www.sephora.com/shop/gift-sets",
}
BRANDS = {
    "mario": "https://www.makeupbymario.com/",
    "westman": "https://www.westman-atelier.com/",
    "saie": "https://saiehello.com/",
    "tarte": "https://tartecosmetics.com/",
    "huda": "https://hudabeauty.com/us/en_US/",
    "ct": "https://www.charlottetilbury.com/us",
    "nars": "https://www.narscosmetics.com/",
    "kosas": "https://kosas.com/",
    "refy": "https://refybeauty.com/",
    "mac": "https://www.maccosmetics.com/",
    "toofaced": "https://www.toofaced.com/",
    "fenty": "https://fentybeauty.com/",
    "rare": "https://www.rarebeauty.com/",
}

def plain(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json", "Accept-Language": "en-US"})
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
            b = r.read()
            return r.status, len(b), b.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, 0, ""
    except Exception as e:
        return "ERR " + type(e).__name__, 0, ""

def shopify(base):
    st, n, body = plain(base.rstrip("/") + "/products.json?limit=5")
    try:
        ps = json.loads(body).get("products", [])
        return {"status": st, "products": len(ps), "sample": [p["title"] for p in ps[:3]]}
    except Exception:
        return {"status": st, "products": None}

async def browser(items):
    from playwright.async_api import async_playwright
    res = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
        ctx = await b.new_context(user_agent=UA, locale="en-US", viewport={"width": 1366, "height": 900})
        for k, url in items.items():
            pg = await ctx.new_page()
            try:
                r = await pg.goto(url, wait_until="domcontentloaded", timeout=60000)
                await pg.wait_for_timeout(8000)
                html = await pg.content()
                open(f"{OUT}/{k}.html", "w").write(html)
                await pg.screenshot(path=f"{OUT}/{k}.png")
                res[k] = {"status": r.status if r else None, "final": pg.url, "title": await pg.title(), "bytes": len(html),
                          "linkStore": "linkStore" in html, "nextData": "__NEXT_DATA__" in html,
                          "blocked": bool(re.search(r"Access Denied|captcha|px-captcha|verify you are human|Pardon Our Interruption", html, re.I))}
            except Exception as e:
                res[k] = {"error": str(e)[:200]}
            await pg.close()
        await b.close()
    return res

def main():
    summary = {"plain": {}, "shopify": {}, "browser": {}}
    for k, u in {**SEPHORA, **BRANDS}.items():
        st, n, body = plain(u)
        summary["plain"][k] = {"status": st, "bytes": n, "linkStore": "linkStore" in body,
                               "blocked": bool(re.search(r"Access Denied|captcha|Pardon Our Interruption", body, re.I))}
        if n: open(f"{OUT}/{k}_plain.html", "w").write(body)
    for k, u in BRANDS.items():
        summary["shopify"][k] = shopify(u)
    try:
        summary["browser"] = asyncio.run(browser({**SEPHORA, **BRANDS}))
    except Exception as e:
        summary["browser"] = {"error": str(e)[:300]}
    json.dump(summary, open(f"{OUT}/summary.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))

main()
