#!/usr/bin/env python3
"""Open Elisabetta Franchi outlet pages in a real browser (Chrome) and print the prices exactly as a shopper sees them."""
import asyncio, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
        pg = await b.new_page(locale="it-IT", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
        await pg.goto(u.EF_PAGE, wait_until="networkidle", timeout=90000)
        await pg.wait_for_timeout(6000)
        tiles = await pg.eval_on_selector_all(".product-hit__price, [class*=product-hit__price]", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")
        print("LISTING tile prices:", tiles[:30])
        for href in u.ef_page_links()[:3]:
            await pg.goto(u.EF_SITE + href, wait_until="networkidle", timeout=90000)
            await pg.wait_for_timeout(5000)
            pr = await pg.eval_on_selector_all("[class*=product-price], [class*=ProductPrice], [class*=badge]", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim()).filter(Boolean)")
            print("PRODUCT", href.rsplit('/',1)[-1], "->", pr[:8])
        await b.close()
asyncio.run(main())
