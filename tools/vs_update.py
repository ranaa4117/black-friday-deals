#!/usr/bin/env python3
"""Victoria's Secret (official US site only, Victoria's Secret-branded items only) → self-portrait/vs.json

Sections:  pajamas · robes · vsbags  = a FIXED list chosen by the owner (exact official names)
           slippers                  = every Victoria's Secret slipper that is discounted right now (found automatically)

Every product is read from its own official product page (the data the page itself shows: prices per colour and size,
colours, sizes, gallery, description, fabric). Pajama/robe photos: product-only views (no models), plus the gallery's
final fabric/feature image when there is one.

Rules: never invent anything; a discount ends only after 3 reads in a row confirm it; a failed read never ends a
discount (product kept at its last verified data, marked unverified); a product is deleted only when its official page
is confirmed gone 3 times over 24 hours. Every change is recorded in changes.json.
"""
import asyncio
import collections
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as U  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "self-portrait")
OUT = os.path.join(ROOT, "vs.json")
SITE = "https://www.victoriassecret.com"
IMG = SITE + "/p/760x1013/{}.jpg"
FIXED = [  # (official product id, catalog, section, exact official name)
    ("5000000360", "sleepwear-and-lingerie-catalog", "pajamas", "CozyFlannel™ Cotton Long Pajama Set"),
    ("5000007337", "sleepwear-and-lingerie-catalog", "pajamas", "SoSoft™ Modal Long Pajama Set"),
    ("5000000279", "sleepwear-and-lingerie-catalog", "pajamas", "Signature Satin Long Pajama Set"),
    ("5000008347", "sleepwear-and-lingerie-catalog", "robes", "Cozy Plush Robe"),
    ("5000012041", "sleepwear-and-lingerie-catalog", "robes", "CozyFlannel™ Cotton Reversible Faux Fur-Lined Robe"),
    ("5000007992", "accessories-catalog", "vsbags", "4-Piece Makeup Bag"),
    ("5000008768", "accessories-catalog", "vsbags", "2-Piece Makeup Bag"),
    ("5000011697", "accessories-catalog", "vsbags", "4-Piece Nested Beauty Case Set"),
]
SLIPPERS_PAGE = SITE + "/us/vs/sleepwear/slippers"
GAL = {}
NO_MODEL = {"offModelFront", "offModelBack", "offModelSide", "digitalOffModelFront", "digitalOffModelBack", "detail", "flat", "flatFront", "flatBack"}


def now():
    return U.now_iso()


def page_data(html):
    m = re.search(r'<script id="clientProps" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        return None
    d = json.loads(m.group(1))
    stack = [d]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if "productData" in o and isinstance(o["productData"], dict):
                return o["productData"]
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None


def read_page(url, tries=3):
    """The product's own official page. Returns productData, raises U.Gone on 404/410, RuntimeError when unreadable."""
    last = None
    for i in range(tries):
        try:
            h = U.fetch(url + ("&" if "?" in url else "?") + "_rc=%d" % time.time(), accept="text/html")
        except U.urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise U.Gone() from e
            last = e
            time.sleep(5 * (i + 1))
            continue
        pd = page_data(h)
        if pd:
            return pd
        last = RuntimeError("page did not include its product data")
        time.sleep(8 * (i + 1))
    raise RuntimeError(str(last))


def size_label(k, s):
    a, b = s.get("size1") or "", s.get("size2") or ""
    if b and b not in ("Regular",) and not a.endswith(b):
        return f"{a} / {b}".strip(" /")
    if b == "Regular":
        return f"{a} / Regular"
    return a or k


def gallery(images, section):
    """Product-only pictures for clothing (no models); the gallery's last picture is kept when it is a
    detail/feature card (fabric, lining, construction). Bags/slippers: every product picture."""
    if section in ("pajamas", "robes"):
        keep = [i["image"] for i in images if i.get("type") in NO_MODEL]
        if images and images[-1].get("type") in ("alternate", "detail") and images[-1]["image"] not in keep:
            keep.append(images[-1]["image"])
        return keep
    return [i["image"] for i in images if not str(i.get("type", "")).startswith("onModel") or section in ("vsbags", "slippers")]


def build(pid, catalog, section, name, pd):
    """One site product from the official page data: the main price group (the price most colours are sold at)."""
    groups = [g for g in pd.values() if (g.get("shortDescription") or "").strip() == name] or \
             [g for g in pd.values() if (g.get("shortDescription") or "").strip().lower() == name.lower()]
    if not groups:
        return None, "the page does not show a product called «%s»" % name
    choices = []
    for g in groups:
        for code, c in (g.get("choices") or {}).items():
            sizes = c.get("availableSizes") or {}
            avail = {k: s for k, s in sizes.items() if s.get("isAvailable")}
            prices = collections.Counter((s.get("originalPriceNumerical"), s.get("salePriceNumerical") or s.get("originalPriceNumerical")) for s in (avail or sizes).values())
            if not prices:
                continue
            choices.append({"g": g, "code": code, "c": c, "avail": avail, "sizes": sizes, "price": prices.most_common(1)[0][0]})
    if not choices:
        return None, "no colours with a price on the page"
    tally = collections.Counter(ch["price"] for ch in choices if ch["avail"]) or collections.Counter(ch["price"] for ch in choices)
    (orig, sale) = tally.most_common(1)[0][0]
    main = [ch for ch in choices if ch["price"] == (orig, sale)]
    g0 = main[0]["g"]
    url = f"{SITE}/us/vs/{catalog}/{pid}"
    variants, images, colors, size_set = [], [], [], {}
    for ch in main:
        gal = gallery(ch["c"].get("images") or [], section)
        if not gal:
            continue
        label = ch["c"].get("label") or ch["code"]
        if label in colors:
            label = f"{label} ({ch['g'].get('label') or ch['code']})"
        colors.append(label)
        variants.append({"color": label, "image": IMG.format(gal[0]), "images": [IMG.format(x) for x in gal[:6]],
                         "url": f"{url}?genericId={ch['g'].get('genericId') or ''}&choice={ch['code']}".replace("genericId=&", ""),
                         "a": bool(ch["avail"])})
        if not images:
            images = [IMG.format(x) for x in gal[:8]]
        for k, s in ch["sizes"].items():
            lab = size_label(k, s)
            size_set[lab] = size_set.get(lab, False) or bool(s.get("isAvailable"))
    if not variants:
        return None, "no product-only pictures on the page"
    order = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XS/S", "M/L", "XL/XXL", "One Size", "O/S"]
    sk = lambda x: (order.index(x.split(" / ")[0]) if x.split(" / ")[0] in order else 99, x)
    desc = re.sub(r"<[^>]+>", "\n", g0.get("longDescription") or "")
    desc = re.sub(r"\n\s*\n+", "\n", re.sub(r"&quot;", '"', desc)).strip()
    fab = re.sub(r"<[^>]+>", "\n", g0.get("fabrication") or "")
    fab = re.sub(r"\n\s*\n+", "\n", fab).strip()
    pct = round((1 - sale / orig) * 100) if orig and sale and sale < orig else 0
    return {
        "handle": "vs-" + pid, "brand": "vs", "src": "vs", "cat": section, "cur": "USD", "title": name, "url": url,
        "image": images[0], "images": images, "variants": variants, "colors": colors,
        "sizes": [{"s": k, "a": v} for k, v in sorted(size_set.items(), key=lambda kv: sk(kv[0]))],
        "price": round(sale, 2), "compare": round(orig, 2), "discPct": pct,
        "promoStatus": "active" if pct else "none", "details": desc[:900], "fabric": fab[:400],
        "status": "ok" if any(v["a"] for v in variants) else "unavailable",
    }, None


async def rendered_cards(url):
    """Open a collection page in a real browser (as a shopper), scroll to the end, and read every product card."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
        pg = await b.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
        await pg.goto(url, wait_until="domcontentloaded", timeout=90000)
        await pg.wait_for_timeout(6000)
        last = -1
        for _ in range(40):
            n = await pg.evaluate("document.querySelectorAll('a[href*=\"-catalog/\"]').length")
            if n == last:
                break
            last = n
            await pg.mouse.wheel(0, 6000)
            await pg.wait_for_timeout(1500)
            for sel in ("button:has-text('Load More')", "button:has-text('Show More')"):
                if await pg.locator(sel).count():
                    await pg.locator(sel).first.click()
                    await pg.wait_for_timeout(2500)
        cards = await pg.evaluate("""() => {
          const out = []; const seen = new Set();
          document.querySelectorAll('a[href*="-catalog/"]').forEach(a => {
            const m = a.getAttribute('href').match(/\\/(accessories|sleepwear-and-lingerie|shoes|clothing)-catalog\\/(\\d+)/); if (!m) return;
            let el = a; for (let i = 0; i < 6 && el && !(el.innerText || '').match(/\\$\\d/); i++) el = el.parentElement;
            const t = el ? el.innerText.replace(/\\s+/g, ' ').trim() : '';
            const key = m[2] + '|' + t.slice(0, 80); if (seen.has(key)) return; seen.add(key);
            out.push({ id: m[2], catalog: m[1] + '-catalog', text: t });
          });
          return out;
        }""")
        await b.close()
        return cards


def find_slippers():
    """Victoria's Secret-branded slippers on the official slippers page that show a sale price right now."""
    cards = asyncio.run(rendered_cards(SLIPPERS_PAGE))
    found = {}
    for c in cards:
        t = c["text"]
        if not t.startswith("Victoria's Secret") and "Victoria's Secret " not in t[:40]:
            continue
        m = re.search(r"Victoria's Secret\s*(.+?)(?:\s+(?:Limited Time Offer|Clearance|New Color|Just Dropped|Trending|Low Stock|Top Seller)\b|\s+\$)", t)
        name = (m.group(1) if m else "").strip()
        if not name or re.search(r"(?i)sock", name) or not re.search(r"(?i)slipper|slide|scuff|mule|bootie", name):
            continue
        prices = [float(x) for x in re.findall(r"\$(\d+(?:\.\d{2})?)", t)]
        if len(prices) >= 2 and min(prices) < max(prices):
            found.setdefault(c["id"], (c["catalog"], name))
    print(f"slippers page: {len(cards)} cards read, {len(found)} discounted Victoria's Secret slipper styles")
    return found


def decide(n, o, ts):
    """Same discount rule as the other brands: ends only on the 3rd read in a row without it; comes back at once."""
    had = o.get("discPct") or 0
    if n.get("discPct"):
        n.pop("discMiss", None)
        return n
    if had:
        miss = o.get("discMiss", 0) + 1
        if miss < 3:
            n.update(price=o["price"], compare=o["compare"], discPct=had, discMiss=miss, promoStatus="unverified")
            return n
        n.update(promoStatus="expired", promoEndedAt=ts)
    return n


def main():
    ts = now()
    try:
        prev = json.load(open(OUT, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        prev = {"products": [], "meta": {}}
    if U.age_s((prev.get("meta") or {}).get("updatedAt", "")) < 25 * 60 and os.environ.get("VS_FORCE") != "1":
        print("vs: checked less than 25 minutes ago — skipped")
        return
    old = {p["handle"]: p for p in prev.get("products", [])}
    ar = (prev.get("meta") or {}).get("ar", {})
    meta = {"updatedAt": ts, "ar": ar, "errors": [], "slipperIds": (prev.get("meta") or {}).get("slipperIds", [])}
    targets = list(FIXED)
    try:
        sl = find_slippers()
        meta["slippersReadAt"] = ts
        ids = set(meta["slipperIds"]) | set(sl)
        meta["slipperIds"] = sorted(ids)
        for pid in sorted(ids):
            cat, nm = sl.get(pid) or (old.get("vs-" + pid, {}).get("catalog") or "accessories-catalog", old.get("vs-" + pid, {}).get("title"))
            if nm:
                targets.append((pid, cat, "slippers", nm))
    except Exception as e:  # noqa: BLE001
        meta["errors"].append(f"slippers page: {e}")
        for pid in meta["slipperIds"]:
            p = old.get("vs-" + pid)
            if p:
                targets.append((pid, p.get("catalog", "accessories-catalog"), "slippers", p["title"]))
    out, items, deleted = [], [], []
    for pid, catalog, section, name in targets:
        h = "vs-" + pid
        o = old.get(h)
        try:
            pd = read_page(f"{SITE}/us/vs/{catalog}/{pid}")
            n, why = build(pid, catalog, section, name, pd)
            if os.environ.get("VS_DEBUG") == "1":
                GAL[h] = [{"g": g.get("label"), "choice": code, "color": c.get("label"), "images": c.get("images")}
                          for g in pd.values() if (g.get("shortDescription") or "").strip() == name for code, c in (g.get("choices") or {}).items()]
            if not n:
                raise RuntimeError(why)
        except U.Gone:
            if o:
                checks = [t for t in o.get("goneChecks", []) if t] + [ts]
                if U.removal_confirmed(checks):
                    deleted.append(o)
                    it = U.change_item(o, ["Permanently removed by the store"], o)
                    it.update(removed=True, url=o.get("url", ""), n={})
                    items.append(it)
                    continue
                out.append(dict(o, status="unavailable", goneChecks=checks))
            print("  not found:", pid, name)
            continue
        except Exception as e:  # noqa: BLE001
            meta["errors"].append(f"{name}: {e}")
            print("  could not read:", pid, name, e)
            if o:
                out.append(dict(o, promoStatus="unverified" if o.get("discPct") else o.get("promoStatus", "none"), verifyFail=ts))
            continue
        time.sleep(2)
        n["catalog"] = catalog
        n["checkedAt"] = ts
        n["firstSeen"] = (o or {}).get("firstSeen", ts)
        if o:
            decide(n, o, ts)
            msgs = []
            if abs((o.get("price") or 0) - n["price"]) > 0.001:
                msgs.append(f"Sale price ${o.get('price')} → ${n['price']}")
            if abs((o.get("compare") or 0) - n["compare"]) > 0.001:
                msgs.append(f"Original price ${o.get('compare')} → ${n['compare']}")
            if (o.get("discPct") or 0) != (n.get("discPct") or 0):
                msgs.append(f"Discount {o.get('discPct') or 0}% → {n.get('discPct') or 0}%")
            if o.get("status") != n.get("status"):
                msgs.append("No longer sold by the store" if n["status"] == "unavailable" else "Available again")
            if msgs:
                n["lastChanged"], n["changes"] = ts, msgs
                items.append(U.change_item(n, msgs, o))
            else:
                n["lastChanged"], n["changes"] = o.get("lastChanged", ts), o.get("changes", [])
        else:
            n["lastChanged"], n["changes"] = ts, ["Newly discovered on sale"]
            items.append(U.change_item(n, ["Newly discovered on sale"]))
        n["arDesc"] = ar.get(h, "")
        out.append(n)
        print(f"  {section:8} {name} | ${n['compare']} → ${n['price']} ({n['discPct']}%) | colours {len(n['colors'])} | sizes {len(n['sizes'])} | {n['status']}")
    # keep anything previously listed that this run did not reach (never dropped silently)
    seen = {p["handle"] for p in out} | {p["handle"] for p in deleted}
    for h, o in old.items():
        if h not in seen:
            out.append(o)
    meta["counts"] = dict(collections.Counter(p["cat"] for p in out))
    json.dump({"meta": meta, "products": out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    if items or meta["errors"]:
        U.save_changes(ts, [dict(i, b="vs") for i in items], meta["errors"][:3] or None)
    print("vs:", meta["counts"], "errors:", meta["errors"])
    if os.environ.get("VS_DEBUG") == "1":   # save each product's chosen pictures for a visual check
        os.makedirs("/tmp/vs/img", exist_ok=True)
        json.dump(GAL, open("/tmp/vs/gallery.json", "w"), indent=1)
        for p in out:
            ch = (GAL.get(p["handle"]) or [{}])
            for j, chx in enumerate(ch[:2]):
                for img in chx.get("images") or []:
                    u = IMG.format(img["image"])
                    try:
                        req = U.urllib.request.Request(u, headers={"User-Agent": U.UA})
                        with U.urllib.request.urlopen(req, timeout=30) as r:
                            open(f"/tmp/vs/img/{p['handle']}_{j}_{img['type']}.jpg", "wb").write(r.read())
                    except Exception as e:  # noqa: BLE001
                        print("img fail", u, e)
        for p in []:
            for i, u in enumerate([]):
                try:
                    req = U.urllib.request.Request(u, headers={"User-Agent": U.UA})
                    with U.urllib.request.urlopen(req, timeout=30) as r:
                        open(f"/tmp/vs/img/{p['handle']}_{i}.jpg", "wb").write(r.read())
                except Exception as e:  # noqa: BLE001
                    print("img fail", u, e)


if __name__ == "__main__":
    main()
