#!/usr/bin/env python3
"""Real-browser check of Elisabetta Franchi prices: opens the authorized outlet page (page 2) in Chrome, exactly as a
shopper sees it, and reads every product's original price, discount % and discounted price.
Writes self-portrait/ef_verify.json; the hourly audit compares it with the site. Changes no product data."""
import asyncio
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as U  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "self-portrait", "ef_verify.json")
JS = """() => {
  const out = [];
  document.querySelectorAll('[class*="product-hit__price"]').forEach(pr => {
    let el = pr, a = null;
    for (let i = 0; i < 8 && el && !a; i++) { el = el.parentElement; a = el && el.querySelector('a[href*=".html"]'); }
    if (a) out.push({ href: a.getAttribute('href'), text: pr.innerText.replace(/\\s+/g, ' ').trim() });
  });
  return out;
}"""


def num(x):
    if re.search(r",\d{2}$", x):                       # 1.234,50
        return float(x.replace(".", "").replace(",", "."))
    if re.search(r"^\d{1,3}([.,]\d{3})+$", x):          # 1.234 / 1,234 (thousands, no cents)
        return float(re.sub(r"[.,]", "", x))
    return float(x.replace(",", ""))


def parse(text):
    m = re.match(r"€\s*([\d.,]+)\s*-(\d{1,2})%\s*€\s*([\d.,]+)", text)
    if m:
        return {"orig": num(m.group(1)), "pct": int(m.group(2)), "sale": num(m.group(3))}
    m = re.match(r"€\s*([\d.,]+)$", text)
    if m:
        return {"orig": num(m.group(1)), "pct": 0, "sale": num(m.group(1))}
    return None


async def read():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
        pg = await b.new_page(locale="it-IT", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
        await pg.goto(U.EF_PAGE, wait_until="domcontentloaded", timeout=90000)
        await pg.wait_for_timeout(12000)
        tiles = await pg.evaluate(JS)
        await b.close()
        return tiles


def main():
    at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        prev = json.load(open(OUT, encoding="utf-8"))
        if U.age_s(prev.get("at", "")) < 55 * 60 and os.environ.get("AUDIT_FORCE") != "1":
            print("ef verify: ran less than an hour ago — skipped")
            return
    except Exception:  # noqa: BLE001
        pass
    allowed = {h.rsplit("-", 1)[-1].replace(".html", "").lower() for h in U.ef_page_links()}   # page 2 only
    items, err = {}, ""
    try:
        for t in asyncio.run(read()):
            code = t["href"].rsplit("-", 1)[-1].replace(".html", "").split("?")[0].lower()
            if code not in allowed:
                continue
            v = parse(t["text"])
            if v:
                items["ef-" + code] = dict(v, shown=t["text"])
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    res = {"at": at, "ok": bool(items) and not err, "page": U.EF_PAGE, "listed": len(allowed), "read": len(items), "error": err, "items": items}
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"ef verify: page 2 lists {len(allowed)}, read in the browser {len(items)}", err)
    for k, v in items.items():
        print("  ", k, v["shown"])


if __name__ == "__main__":
    main()
