#!/usr/bin/env python3
"""Open the LIVE site in a real browser and check the Victoria's Secret pages: sections, products, prices, and that
every Victoria's Secret photo actually loads for a shopper (prints only)."""
import asyncio, json, os
from playwright.async_api import async_playwright
SITE = os.environ.get("LIVE", "https://ranaa4117.github.io/black-friday-deals/self-portrait/")

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 420, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        for route in ["vs", "vs-pajamas", "vs-slippers", "vs-robes", "vs-vsbags"]:
            await pg.goto(SITE + "#" + route, wait_until="networkidle", timeout=90000)
            await pg.wait_for_timeout(4000)
            imgs = await pg.eval_on_selector_all(".grid img", "e => e.map(i => [i.currentSrc || i.src, i.complete && i.naturalWidth > 0])")
            ok = sum(1 for _, x in imgs if x)
            print(f"{route}: {len(imgs)} product photos, loaded {ok}", [u for u, x in imgs if not x][:3])
        for h in ["vs-5000000360", "vs-5000008347", "vs-5000007992", "vs-5000011698"]:
            await pg.goto(SITE + "#item-" + h, wait_until="networkidle", timeout=90000)
            await pg.wait_for_timeout(4000)
            t = (await pg.inner_text("main"))[:260].replace("\n", " | ")
            imgs = await pg.eval_on_selector_all("img", "e => e.filter(i => /victoriassecret/.test(i.src)).map(i => i.complete && i.naturalWidth > 0)")
            print("ITEM", h, "| photos loaded", sum(imgs), "of", len(imgs), "|", t)
        print("page errors:", errs)
        await b.close()
asyncio.run(main())
