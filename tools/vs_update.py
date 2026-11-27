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
        t = re.search(r"<title[^>]*>(.*?)</title>", h or "", re.S | re.I)
        last = RuntimeError("page did not include its product data (%d bytes, title: %s)"
                            % (len(h or ""), (t.group(1).strip()[:60] if t else "-")))
        time.sleep(8 * (i + 1))
    # The plain request sometimes gets a page without the product data (a busy/cached or protection page).
    # Second safe way: open the same official page in a real browser, as a shopper does, and read the same data.
    try:
        pd = asyncio.run(browser_page_data(url))
        if pd:
            print("   read in a real browser:", url)
            return pd
    except Exception as e:  # noqa: BLE001
        print("   browser read failed:", url, e)
    raise RuntimeError(str(last))


async def browser_page_data(url):
    """The official product page opened in a real browser; returns the same productData the page itself carries."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
        try:
            pg = await b.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
            r = await pg.goto(url, wait_until="domcontentloaded", timeout=90000)
            if r is not None and r.status in (404, 410):
                return None   # gone is decided only by the plain request rule (3 checks over 24 h), never here
            for _ in range(6):
                txt = await pg.evaluate("(document.getElementById('clientProps')||{}).textContent || ''")
                if txt:
                    pd = page_data('<script id="clientProps" type="application/json">' + txt + '</script>')
                    if pd:
                        return pd
                await pg.wait_for_timeout(3000)
            return None
        finally:
            await b.close()


def size_label(k, s):
    a, b = s.get("size1") or "", s.get("size2") or ""
    if b and b not in ("Regular",) and not a.endswith(b):
        return f"{a} / {b}".strip(" /")
    if b == "Regular":
        return f"{a} / Regular"
    return a or k


# Victoria's Secret's own fabric/feature cards (the "about the fabric" picture at the end of a gallery). Shared campaign
# banners such as "There's no fabric like cotton" are NOT fabric information and are never used.
FABRIC_CARDS = {"png/zz/26/11/09/23/112716047XKK_alt2",   # Signature Satin: soft & sleek, luxurious, smooth glossy shine, relaxed fit
                "png/zz/26/11/09/23/112534037USV_alt",    # CozyFlannel: ultra-soft, cozy, lightweight, brushed fabric
                "png/zz/26/11/09/23/1125072098S4_alt"}    # SoSoft Modal: ultra-soft, 4-way stretch, breathable, helps keep you cool


def product_only(img):
    """Victoria's Secret names its pictures by what they show: _OF_ = off figure (the product alone), _OM_ = on a model."""
    return "_OF_" in img or "_DOF" in img


def gallery(images, section):
    """Pajamas/robes: product-only pictures (no models) + the fabric card at the end when the gallery has one.
    Slippers: product-only when there are any. Bags: every picture (they are product shots)."""
    names = [i.get("image", "") for i in images]
    if section in ("pajamas", "robes"):
        rank = lambda n: 0 if "_OF_F" in n else 1 if "_OF_B" in n else 2
        prod = sorted([n for n in names if product_only(n)], key=rank)   # whole product first, then back, then close-ups
        return prod + [n for n in names if n in FABRIC_CARDS] if prod else []
    if section == "slippers":
        prod = [n for n in names if product_only(n)]
        return prod or names
    return names


SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XS/S", "M/L", "XL/XXL", "One Size", "O/S"]
LEN_ORDER = ["Short", "Regular", "Long"]


def gallery_for(images, section):
    """Product-only pictures first (no models); a colour with no product-only picture keeps its official pictures."""
    g = gallery(images, section)
    if g:
        return g
    names = [i.get("image", "") for i in images if "_alt" not in i.get("image", "")]
    return names


def build(pid, catalog, section, name, pd):
    """One site product = one official style; every official colour is its own variant with its own pictures,
    price (per size and length when they differ), sizes, lengths and availability — nothing copied between colours."""
    for gid, g in pd.items():
        g.setdefault("genericId", gid)
    groups = [g for g in pd.values() if (g.get("shortDescription") or "").strip() == name] or \
             [g for g in pd.values() if (g.get("shortDescription") or "").strip().lower() == name.lower()]
    if not groups:
        return None, "the page does not show a product called «%s»" % name
    url = f"{SITE}/us/vs/{catalog}/{pid}"
    variants, seen = [], set()
    for g in groups:
        for code, c in (g.get("choices") or {}).items():
            sizes = c.get("availableSizes") or {}
            if not sizes:
                continue
            rows = []
            for k, sz in sizes.items():
                o = sz.get("originalPriceNumerical")
                p = sz.get("salePriceNumerical") or o
                if not o:
                    continue
                s1 = (sz.get("size1") or k).strip()
                s2 = (sz.get("size2") or "").strip()
                rows.append({"s": s1, "l": s2 if s2 in LEN_ORDER else "", "a": bool(sz.get("isAvailable")), "p": round(p, 2), "c": round(o, 2)})
            if not rows:
                continue
            gal = gallery_for(c.get("images") or [], section)
            if not gal:
                continue
            label = (c.get("label") or code).strip()
            if label in seen:
                label = f"{label} ({g.get('label') or code})"
            seen.add(label)
            avail = [r for r in rows if r["a"]] or rows
            (vo, vp) = collections.Counter((r["c"], r["p"]) for r in avail).most_common(1)[0][0]
            rows.sort(key=lambda r: (SIZE_ORDER.index(r["s"]) if r["s"] in SIZE_ORDER else 99, LEN_ORDER.index(r["l"]) if r["l"] in LEN_ORDER else 9))
            variants.append({"color": label, "code": code, "style": g.get("label") or "",
                             "image": IMG.format(gal[0]), "images": [IMG.format(x) for x in gal[:8]],
                             "productOnly": any(product_only(x) for x in gal),
                             "url": f"{url}?genericId={g.get('genericId') or ''}&choice={code}".replace("genericId=&", ""),
                             "a": any(r["a"] for r in rows), "price": vp, "compare": vo,
                             "discPct": round((1 - vp / vo) * 100) if vo and vp < vo else 0, "sizes": rows})
    if not variants:
        return None, "no colours with a price and pictures on the page"
    variants.sort(key=lambda v: (not v["a"], not v["productOnly"]))
    tally = collections.Counter((v["compare"], v["price"]) for v in variants if v["a"]) or collections.Counter((v["compare"], v["price"]) for v in variants)
    (orig, sale) = tally.most_common(1)[0][0]
    g0 = groups[0]
    desc = re.sub(r"<[^>]+>", "\n", g0.get("longDescription") or "")
    desc = re.sub(r"\n\s*\n+", "\n", re.sub(r"&quot;", '"', desc)).strip()
    fab = re.sub(r"<[^>]+>", "\n", g0.get("fabrication") or "")
    fab = re.sub(r"\n\s*\n+", "\n", fab).strip()
    pct = round((1 - sale / orig) * 100) if orig and sale and sale < orig else 0
    first = next(v for v in variants if v["a"]) if any(v["a"] for v in variants) else variants[0]
    size_set = {}
    for v in variants:
        for r in v["sizes"]:
            lab = r["s"] + (" / " + r["l"] if r["l"] else "")
            size_set[lab] = size_set.get(lab, False) or r["a"]
    shoe = {m[0]: f"US {m[1]}–{m[2]}" for m in re.findall(r"\b(XS|S|M|L|XL|XXL)\s*=\s*(?:&nbsp;)?\s*(\d+(?:\.5)?)\s*,\s*(\d+(?:\.5)?)", desc.replace("\u00a0", " "))}
    return {
        "handle": "vs-" + pid, "brand": "vs", "src": "vs", "cat": section, "cur": "USD", "title": name, "url": url,
        "shoeSizes": shoe if section == "slippers" else {},
        "image": first["image"], "images": first["images"], "variants": variants, "colors": [v["color"] for v in variants],
        "sizes": [{"s": k, "a": a} for k, a in size_set.items()],
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
        last, same = -1, 0
        for _ in range(40):
            n = await pg.evaluate("document.querySelectorAll('a[href*=catalog]').length")
            same = same + 1 if n == last else 0
            if same >= 3:
                break
            last = n
            await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await pg.wait_for_timeout(2500)
            for sel in ("button:has-text('Load More')", "button:has-text('Show More')", "button:has-text('View More')"):
                if await pg.locator(sel).count():
                    await pg.locator(sel).first.click()
                    await pg.wait_for_timeout(3000)
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
    """Every product on the official slippers page, checked one by one on its own page: kept when it is a
    Victoria's Secret-branded slipper (not socks, not other brands) with a sale price right now."""
    cards = asyncio.run(rendered_cards(SLIPPERS_PAGE))
    ids = {}
    for c in cards:
        if c["catalog"] in ("accessories-catalog", "shoes-catalog"):
            ids.setdefault(c["id"], c["catalog"])
    found = {}
    for pid, catalog in ids.items():
        try:
            pd = read_page(f"{SITE}/us/vs/{catalog}/{pid}")
        except Exception as e:  # noqa: BLE001
            print("   slipper page unreadable:", pid, e)
            continue
        time.sleep(2)
        names = collections.Counter((g.get("shortDescription") or "").strip() for g in pd.values())
        name = names.most_common(1)[0][0] if names else ""
        fam = {str(g.get(k) or "") for g in pd.values() for k in ("brand", "brandName", "family", "collectionName", "masterStyleBrand") if g.get(k)}
        if os.environ.get("VS_DEBUG") == "1":
            print("   slipper candidate:", pid, name, "| brand fields:", fam)
        if not name or re.search(r"(?i)sock", name) or not re.search(r"(?i)slipper|slide|scuff|mule|bootie", name):
            continue
        if fam and not any("victoria" in x.lower() for x in fam):
            continue
        n, _ = build(pid, catalog, "slippers", name, pd)
        if n and n["discPct"] > 0:
            found[pid] = (catalog, name)
    print(f"slippers page: {len(cards)} cards, {len(ids)} products checked, {len(found)} discounted Victoria's Secret slipper styles")
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
