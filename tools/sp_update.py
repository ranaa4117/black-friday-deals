#!/usr/bin/env python3
"""Self-Portrait Spain — sale monitor for midi dresses, maxi dresses and bags.

Reads the public product feeds of the official Spain store
(eu.self-portrait.com/es-es) for three sale collections, keeps only products
that are genuinely discounted (compare-at price above the selling price),
fetches a live EUR->SAR rate, reads each product's official size guide
(dress measurements or bag dimensions) from its product page, and merges the
result into self-portrait/data.json while keeping history.

Usage:
  python3 tools/sp_update.py            # live check (GitHub Action)
  SG_LIMIT=600 python3 tools/sp_update.py   # read more size guides this run
Standard library only.
"""
import datetime as dt
import html
import json
import os
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from html.parser import HTMLParser

STORE = "https://eu.self-portrait.com/es-es"
CATEGORIES = [("midi", "sale-midi-dresses"), ("maxi", "sale-maxi-dresses"), ("bags", "sale-handbags")]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "self-portrait", "data.json")      # light file the site loads first
MORE = os.path.join(HERE, "..", "self-portrait", "more.json")     # photos, details, size guides (loaded on demand)
FULL = os.path.join(HERE, "..", "self-portrait", "full.json")     # complete state, used only by this script
UA = "Mozilla/5.0 (personal sale tracker; github.com/ranaa4117/black-friday-deals)"
SG_LIMIT = int(os.environ.get("SG_LIMIT", "60"))       # size guides read per run
SG_MAX_AGE = 3 * 24 * 3600                              # re-read a guide every 3 days
DEBUG = os.environ.get("SG_DEBUG") == "1"
FORCE = os.environ.get("SG_FORCE") == "1"                # re-read every guide this run
ACC_IMG = re.compile(r"https://cld\.accentuate\.io/[^\"'\s,?]+\.(?:png|jpe?g|webp|svg|avif)", re.I)


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def age_s(iso):
    try:
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()
    except Exception:  # noqa: BLE001
        return 1e12


def fetch(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def get_json(url):
    return json.loads(fetch(url))


def clean_text(body):
    raw = re.sub(r"(?i)<br\s*/?>|</(p|li|div|h\d)>", "\n", body or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = "\n".join(re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in text.split("\n"))
    return re.sub(r"\n{2,}", "\n", text).strip()


def keep(cat, p):
    t = (p.get("title") or "").lower()
    ptype = (p.get("product_type") or "").lower()
    if cat == "midi":
        return "midi" in t and "mini" not in t and "maxi" not in t
    if cat == "maxi":
        return "mini" not in t and "midi" not in t and "bag" not in ptype
    if cat == "bags":
        return "bag" in ptype or any(w in t for w in ("bag", "clutch", "tote", "pouch"))
    return False


def normalize(p, cat, retain=False):
    variants = p.get("variants") or []
    prices = [float(v["price"]) for v in variants if v.get("price")]
    comps = [float(v.get("compare_at_price") or 0) for v in variants]
    if not prices or (not retain and not keep(cat, p)):
        return None
    price, compare = min(prices), max(comps)
    if compare <= price:
        if not retain:
            return None  # not discounted (sale lists only)
        compare = price   # kept product, currently at its regular price
    imgs = [i["src"] for i in (p.get("images") or []) if i.get("src")]
    return {
        "handle": p["handle"],
        "cat": cat,
        "title": p["title"].strip(),
        "image": imgs[0] if imgs else "",
        "images": imgs[:12],
        "details": clean_text(p.get("body_html"))[:1200],
        "price": round(price, 2),
        "compare": round(compare, 2),
        "sizes": [{"s": (v.get("option1") or v.get("title") or "").strip(), "a": bool(v.get("available"))} for v in variants],
        "publishedAt": (p.get("published_at") or "")[:10],
    }


def fetch_collection(handle):
    items, page = [], 1
    while page <= 30:
        batch = get_json(f"{STORE}/collections/{handle}/products.json?limit=250&page={page}").get("products") or []
        items += batch
        if len(batch) < 250:
            break
        page += 1
        time.sleep(2)
    return items


# ---------- Mac Duggal (official US store, maxi dresses) ----------
MD_STORE = "https://macduggal.com"
MD_MAXI = "full-length-maxi"        # the store's own floor-length / maxi collection
MD_BF = "black-friday"              # the store's Black Friday Sale collection
MD_PROMO_TAG = "BFCM25"             # the store shows "+25% Off In Cart" on products with this tag (window.cardHighlights)
MD_NOT_MAXI = re.compile(r"\b(mini|midi|short|tea length|cocktail dress|jumpsuit|romper|top|blouse|skirt|pants?|trousers?|blazer|jacket|coat|cape|shawl|bag|clutch|earrings?)\b", re.I)


def fetch_md_collection(handle):
    items, page = [], 1
    while page <= 20:
        batch = get_json(f"{MD_STORE}/collections/{handle}/products.json?limit=250&page={page}").get("products") or []
        items += batch
        if len(batch) < 250:
            break
        page += 1
        time.sleep(2)
    return items


MD_PROMO = {"tag": MD_PROMO_TAG, "pct": 25, "label": "+25% Off In Cart"}
MD_PROMOS = [MD_PROMO]   # every extra-%-off label the store shows right now (a product gets the first one whose tag it carries)


def fetch_md_promos():
    """Mac Duggal's own product-label promotions (window.cardHighlights): which tag gets which extra % off.
    Returns every extra-discount label for the main (core) market — [] when the store shows none —
    or raises when the page can't be read. Labels that say "Price as marked" are not an extra discount."""
    h = fetch(MD_STORE + "/", accept="text/html")
    m = re.search(r"cardHighlights\s*=\s*(\[.*?\])\s*;", h, re.S)
    if not m:
        return []
    out = []
    for obj in re.findall(r"\{[^{}]*\}", m.group(1)):
        val = lambda k: (re.search(k + r'\s*:\s*"([^"]*)"', obj) or [None, ""])[1]
        label, tag, market = val("label"), val("tag"), val("market")
        if not label or not tag or re.search(r"price\s+as\s+marked", label, re.I):
            continue
        pct = re.search(r"(\d{1,2})\s*%", label)
        if pct and (not market or market == "core") and tag not in {p["tag"] for p in out}:
            out.append({"tag": tag, "pct": int(pct.group(1)), "label": label})
    return out


def fetch_md_promo():
    """First extra-discount label (kept for diagnostics)."""
    found = fetch_md_promos()
    return found[0] if found else None


def md_promo_for(p):
    tags = set(tag_list(p))
    return next((x for x in MD_PROMOS if x.get("tag") in tags), None)


def tag_list(p):
    t = p.get("tags") or []
    return [x.strip() for x in t.split(",")] if isinstance(t, str) else list(t)


def normalize_md(p, bf_handles, retain=False):
    title = (p.get("title") or "").strip()
    ptype = (p.get("product_type") or "").upper()
    if "mac duggal" not in (p.get("vendor") or "").strip().lower():
        return None  # only Mac Duggal's own lines (Mac Duggal, Ieena for Mac Duggal, Mac Duggal Collection)
    if not retain and (MD_NOT_MAXI.search(title) or ptype in ("KIDS", "HANDBAGS", "READY TO WEAR", "SAMPLES")):
        return None
    variants = p.get("variants") or []
    if not variants:
        return None
    opts = [o.get("name", "").lower() for o in p.get("options", [])]
    ci = opts.index("color") if "color" in opts else None
    si = opts.index("size") if "size" in opts else None
    cheapest = min(variants, key=lambda v: float(v.get("price") or 1e9))
    price = float(cheapest["price"])
    compare = float(cheapest.get("compare_at_price") or 0)
    markdown = compare > price
    hit = md_promo_for(p)
    promo = bool(hit)
    if not markdown and not promo and not retain:
        return None  # full price and not eligible for the cart promotion
    sizes, colors = {}, []
    for v in variants:
        vals = [v.get("option1"), v.get("option2"), v.get("option3")]
        size = (vals[si] if si is not None else v.get("title")) or ""
        color = (vals[ci] if ci is not None else "") or ""
        if size:
            sizes[size] = sizes.get(size, False) or bool(v.get("available"))
        if color and color not in colors:
            colors.append(color)
    imgs = [i["src"] for i in (p.get("images") or []) if i.get("src")]
    return {
        "handle": "md-" + p["handle"],
        "brand": "md",
        "cat": "maxi",
        "cur": "USD",
        "url": f"{MD_STORE}/products/{p['handle']}",
        "title": title,
        "image": imgs[0] if imgs else "",
        "images": imgs[:6],
        "details": clean_text(p.get("body_html"))[:500],
        "price": round(price, 2),
        "compare": round(compare if markdown else price, 2),
        "bf": markdown and p["handle"] in bf_handles,
        "markdown": markdown,
        "extra25": promo and hit["pct"] == 25,
        "extraPct": hit["pct"] if promo else 0,
        "colors": colors[:8],
        "sizes": [{"s": k, "a": a} for k, a in sizes.items()],
        "publishedAt": (p.get("published_at") or "")[:10],
    }


MD_RAW = {}   # this run's official feed, by our handle (used to re-read dresses that left the sale list)


def fetch_md():
    maxi = fetch_md_collection(MD_MAXI)
    MD_RAW.clear()
    MD_RAW.update({"md-" + p["handle"]: p for p in maxi if p.get("handle")})
    time.sleep(1.5)
    bf = {p["handle"] for p in fetch_md_collection(MD_BF)}
    out = {}
    for p in maxi:
        n = normalize_md(p, bf)
        if n:
            out[n["handle"]] = n
    return list(out.values()), len(maxi)


def fetch_md_chart():
    """Mac Duggal's official size chart page (tables as published)."""
    page = fetch(f"{MD_STORE}/pages/size-chart", accept="text/html")
    tp = TableParser()
    tp.feed(page)
    tables = []
    for t in tp.tables:
        rows = [[c for c in r] for r in t if any(c.strip() for c in r)]
        if len(rows) >= 2 and len(rows[0]) >= 2:
            tables.append(rows)
    titles = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m))).strip()
              for m in re.findall(r"<h[1-4][^>]*>(.*?)</h[1-4]>", page, re.S)]
    if DEBUG or os.environ.get("MD_CHART_DEBUG"):
        print("md chart tables:", len(tables), [len(t) for t in tables], "headings:", titles[:15])
        for t in tables[:4]:
            print("   ", t[:4])
    return {"tables": tables[:8], "headings": [x for x in titles if x][:12], "url": f"{MD_STORE}/pages/size-chart", "at": now_iso()}


EF_SITE = "https://outlet.elisabettafranchi.com"
EF_PAGE = EF_SITE + "/it-it/abbigliamento/abiti/abiti-lunghi/?page=2"   # the owner's exact page — never other pages
EF_NOT_MAXI = re.compile(r"\b(mini ?abito|miniabito|mini|midi|longuette|corto|body|tuta|jumpsuit|top|gonna|blazer|giacca)\b", re.I)
EF_LIST_KEYS = ("listPrice", "standardPrice", "originalPrice", "fullPrice", "compareAtPrice", "strikePrice", "regularPrice", "priceBefore")


def ef_page_links():
    html = fetch(EF_PAGE, accept="text/html")
    links = []
    for href in re.findall(r'href="(/it-it/[^"#?]+\.html)"', html):
        if href not in links:
            links.append(href)
    return links


def ef_product(href, debug=False):
    url = EF_SITE + href
    h = fetch(url, accept="text/html")
    ld = None
    for blk in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
        try:
            j = json.loads(blk)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(j, dict) and j.get("@type") == "Product":
            ld = j
            break
    if not ld:
        raise RuntimeError("no product data")
    name = html.unescape(ld.get("name") or "").strip()
    color = html.unescape(str(ld.get("color") or "")).strip()
    desc = html.unescape(ld.get("description") or "")
    length = re.search(r"Lunghezza\s+(\d{2,3})\s*cm", h)
    length = int(length.group(1)) if length else None
    variants = re.findall(r'\{"orderable":(true|false),"price":([\d.]+),"productId":"\d+".{0,600}?"size":"([^"]+)","color":"([^"]+)"\}', h)
    prices = sorted({float(v[1]) for v in variants})
    sizes = {}
    for orderable, _, size, _ in variants:
        sizes[size] = sizes.get(size, False) or orderable == "true"
    offers = ld.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = prices[0] if prices else float(offers.get("price") or 0)
    compare = 0.0
    books = {}
    for pr, pb in re.findall(r'"price":([\d.]+),"pricebook":"([^"]+)"', h):
        books[pb] = min(books.get(pb, 1e9), float(pr))
    if len(set(books.values())) > 1:
        compare = max(books.values())
        price = min(min(books.values()), price) if price else min(books.values())
    for k in EF_LIST_KEYS:   # a crossed-out official price, only if the store publishes one
        m = re.search(r'"%s"\s*:\s*\{?[^}]{0,80}?"?(?:value|amount)?"?\s*:?\s*"?([\d.]+)' % k, h)
        if not compare and m and float(m.group(1)) > price:
            compare = float(m.group(1))
            break
    imgs = ld.get("image") or []
    imgs = list(dict.fromkeys([i for i in (imgs if isinstance(imgs, list) else [imgs]) if i]))
    code = re.search(r"([A-Z0-9]{9})_([A-Z0-9]{3})_0\.jpg", " ".join(imgs))
    if code:   # every official photo of this colour (…_0.jpg, _1.jpg …) as listed in the page
        more = sorted(set(re.findall(r"(https://[^\"'\s]*?/images/zoom/%s_%s_\d\.jpg)" % (code.group(1), code.group(2)), h)))
        imgs = list(dict.fromkeys(imgs + more))
    if debug:
        print("  EF", name, color, "| length", length, "| prices", prices, "| sizes", sizes, "| compare", compare,
              "| keys:", {k: h.count('"' + k + '"') for k in EF_LIST_KEYS}, "| pricebooks", sorted(set(re.findall(r'"pricebook":"([^"]+)"', h))))
    return {"url": url, "name": name, "color": color, "desc": desc, "length": length, "price": price, "compare": compare,
            "sizes": sizes, "images": imgs, "avail": "InStock" in str(offers.get("availability", "")) or any(sizes.values())}


def fetch_ef(debug=False):
    """Maxi dresses listed on the owner's exact Elisabetta Franchi outlet page (page 2 only)."""
    out, links = [], ef_page_links()
    print("EF page links:", len(links))
    for href in links:
        try:
            d = ef_product(href, debug)
        except Exception as e:  # noqa: BLE001
            print("  EF product failed:", href, e)
            continue
        time.sleep(1)
        why = None
        if EF_NOT_MAXI.search(d["name"]):
            why = "not a maxi dress (name)"
        elif not d["name"].lower().startswith("abito"):
            why = "not a dress"
        elif d["length"] is not None and d["length"] < 125:
            why = f"length {d['length']} cm — not maxi"
        if not d["price"]:
            why = why or "no price"
        if why:
            print("  EF excluded:", d["name"], d["color"], "—", why)
            continue
        code = href.rsplit("-", 1)[-1].replace(".html", "")
        out.append({
            "handle": "ef-" + code.lower(), "brand": "ef", "cat": "maxi", "cur": "EUR", "url": d["url"],
            "title": d["name"] + (" — " + d["color"] if d["color"] else ""), "image": d["images"][0] if d["images"] else "",
            "images": d["images"][:6], "details": d["desc"][:500], "price": round(d["price"], 2),
            "compare": round(d["compare"] if d["compare"] > d["price"] else d["price"], 2),
            "colors": [d["color"]] if d["color"] else [], "sizes": [{"s": "IT " + k, "a": a} for k, a in d["sizes"].items()],
            "lengthCm": d["length"], "publishedAt": "",
        })
    if not links:
        raise RuntimeError("page listed no products")
    return out, len(links)


SP_PROMO_PAGES = ["/collections/sale-last-chance", "/collections/sale", ""]
SP_PROMO_RE = re.compile(r"extra\s+(\d{1,2})\s*%\s*(?:off\s+)?(?:sale|rebajas)|(\d{1,2})\s*%\s*(?:extra|adicional)\s+(?:en\s+)?(?:sale|rebajas)", re.I)


def fetch_sp_promo():
    """Self-Portrait's store-wide extra discount on sale items (e.g. 'Black Friday - Extra 20% off sale'),
    read from the store's own banners. Returns the promo, None when no page shows one, or raises if no page could be read."""
    read = 0
    for path in SP_PROMO_PAGES:
        try:
            html = fetch(STORE + path, accept="text/html")
        except Exception as e:  # noqa: BLE001
            print("sp promo page failed:", path, e)
            continue
        read += 1
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)))
        m = SP_PROMO_RE.search(text)
        if m:
            pct = int(m.group(1) or m.group(2))
            start = max(0, m.start() - 40)
            banner = text[start:m.end() + 30].strip()
            if 5 <= pct <= 60:
                return {"pct": pct, "text": banner[:140], "source": STORE + path, "appliesTo": "sale items (not full price), automatically at checkout"}
    if not read:
        raise RuntimeError("no Self-Portrait page could be read")
    return None


def write_sitemap(products):
    """sitemap.xml + robots.txt for the public address; only rewritten when the list of pages changes."""
    site = "https://raghad-outlet.pages.dev/"
    extra = []
    for name in ("winter.json", "shoes.json"):
        try:
            with open(os.path.join(os.path.dirname(OUT), name), encoding="utf-8") as fh:
                extra += [p for p in json.load(fh).get("products", []) if p.get("status") != "verify"]
        except Exception:  # noqa: BLE001
            pass
    secs = ["dresses", "dresses-sp", "dresses-md", "dresses-ef", "dresses-ef-maxi", "dresses-sp-midi", "dresses-sp-maxi", "bags", "shoes", "winter",
            "winter-jackets", "winter-coats", "winter-scarves"]
    urls = [site] + [f"{site}?c={c}" for c in secs] + sorted(f"{site}?p={urllib.parse.quote(p['handle'])}" for p in list(products) + extra)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + \
        "".join(f"  <url><loc>{u.replace('&', '&amp;')}</loc></url>\n" for u in urls) + "</urlset>\n"
    path = os.path.join(os.path.dirname(OUT), "sitemap.xml")
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == xml:
                return
    except FileNotFoundError:
        pass
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(xml)
    print("sitemap:", len(urls), "pages")


def fetch_usd_rate():
    try:
        d = get_json("https://open.er-api.com/v6/latest/USD")
        if d.get("result") == "success":
            return {"value": round(d["rates"]["SAR"], 4), "source": "open.er-api.com (USD→SAR)", "asOf": d.get("time_last_update_utc", "")}
    except Exception as e:  # noqa: BLE001
        print("usd rate failed:", e)
    return {"value": 3.75, "source": "SAR/USD official peg 3.75", "asOf": ""}


# ---------- official size guide (tables in the product page) ----------
class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._t, self._row, self._cell, self._depth = [], None, None, None, 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._t = []
        elif self._t is not None and tag == "tr":
            self._row = []
        elif self._row is not None and tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._t is not None:
            if any(self._row):
                self._t.append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
            if self._depth == 0 and self._t:
                self.tables.append(self._t)
                self._t = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


NUM = re.compile(r"^-?\d+(\.\d+)?$")


def parse_guide(page_html, cat):
    tp = TableParser()
    tp.feed(page_html)
    out = []
    for t in tp.tables:
        if len(t) < 2 or len(t[0]) < 2:
            continue
        head = t[0]
        rows = [r for r in t[1:] if len(r) == len(head) and r[0] and all(NUM.match(c.replace(",", ".")) for c in r[1:] if c)]
        if not rows:
            continue
        sizes = head[1:]
        if all(NUM.match(s) for s in sizes):
            first = float(sizes[0])
            system = "FR" if first >= 30 else "UK"
        else:
            system = ""
        kind = "Dimensions" if cat == "bags" else ("Body measurements" if system == "FR" else "Garment measurements")
        table = {"kind": kind, "system": system, "sizes": sizes,
                 "rows": [[r[0].strip().title()] + [c.replace(",", ".") for c in r[1:]] for r in rows]}
        if table not in out:
            out.append(table)
    if DEBUG and out:
        print("guide sample:", json.dumps(out)[:600])
    return out


def guide_images(page_html):
    """Official size-guide illustrations embedded in the product page (garment sketch, body figure)."""
    urls = []
    for m in ACC_IMG.finditer(page_html):
        if m.group(0) not in urls:
            urls.append(m.group(0))
    name = lambda u: u.rsplit("/", 1)[-1]
    body = [u for u in urls if "human-figure" in u.lower()]
    # size-guide sketches are named like "DRESS---Short-Sleeve-Midi--1000x1200.jpg" or "Screenshot-…png";
    # colour swatches ("Black.png", "Light-yellow.png") come from the same host and must be skipped
    sketch = re.compile(r"dress|bag|clutch|tote|screenshot|sketch|garment|measure|size|\d{3,4}x\d{3,4}", re.I)
    swatch = re.compile(r"^[a-z]+(-[a-z]+)*-(dress|bag)\.(png|jpe?g|webp)$", re.I)   # e.g. "Pale-Pink-dress.png"
    garment = [u for u in urls if "human-figure" not in u.lower() and sketch.search(name(u)) and not swatch.match(name(u))]
    return {"garment": garment[0] if garment else "", "body": body[0] if body else "", "all": urls[:12]}


def read_guides(products, prev_by_handle):
    budget, done = SG_LIMIT, 0
    for p in products:
        if p.get("brand", "sp") != "sp":
            continue
        old = prev_by_handle.get(p["handle"], {})
        if not FORCE and old.get("guide") is not None and age_s(old.get("guideAt", "")) < SG_MAX_AGE:
            p["guide"], p["guideAt"] = old["guide"], old["guideAt"]
            if "guideImg" in old:
                p["guideImg"] = old["guideImg"]
            continue
        if budget <= 0:
            if "guide" in old:
                p["guide"], p["guideAt"] = old["guide"], old.get("guideAt", "")
                if "guideImg" in old:
                    p["guideImg"] = old["guideImg"]
            continue
        budget -= 1
        try:
            page = fetch(f"{STORE}/products/{p['handle']}", accept="text/html")
            p["guide"], p["guideAt"] = parse_guide(page, p["cat"]), now_iso()
            p["guideImg"] = guide_images(page)
            done += 1
            if DEBUG and done <= 3:
                print("guide images", p["handle"], p["guideImg"])
            if DEBUG and done == 1 and not p["guide"]:
                i = page.find("<table")
                print("no tables parsed; first table html:", page[i:i + 1500] if i >= 0 else "(no <table> in page)")
        except Exception as e:  # noqa: BLE001
            print("guide failed", p["handle"], e)
            if "guide" in old:
                p["guide"], p["guideAt"] = old["guide"], old.get("guideAt", "")
                if "guideImg" in old:
                    p["guideImg"] = old["guideImg"]
        time.sleep(0.8)
    return done


def fetch_rate():
    try:
        d = get_json("https://open.er-api.com/v6/latest/EUR")
        if d.get("result") == "success":
            return {"value": round(d["rates"]["SAR"], 4), "source": "open.er-api.com (EUR→SAR)",
                    "asOf": d.get("time_last_update_utc", "")}
    except Exception as e:  # noqa: BLE001
        print("rate source 1 failed:", e)
    try:
        d = get_json("https://api.frankfurter.app/latest?from=EUR&to=USD")
        return {"value": round(d["rates"]["USD"] * 3.75, 4),
                "source": "ECB EUR→USD (frankfurter.app) × 3.75 SAR/USD peg", "asOf": d.get("date", "")}
    except Exception as e:  # noqa: BLE001
        print("rate source 2 failed:", e)
    return None


def load_prev():
    try:
        with open(FULL if os.path.exists(FULL) else OUT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"meta": {}, "products": [], "removed": []}


class Gone(Exception):
    pass


def product_json(store, handle):
    """One product from a Shopify store's own page data. /products/<h>.json has no stock flags,
    so stock is taken from the same product's /products/<h>.js (per variant)."""
    raw = get_json(f"{store}/products/{handle}.json").get("product")
    if raw:
        try:
            js = get_json(f"{store}/products/{handle}.js")
            avail = {v.get("id"): bool(v.get("available")) for v in js.get("variants") or []}
            for v in raw.get("variants") or []:
                if v.get("id") in avail:
                    v["available"] = avail[v["id"]]
        except Exception as e:  # noqa: BLE001
            print("  stock read failed:", handle, e)
    return raw


def refresh_product(p, bf_handles):
    """Re-read a known product from its own official page. Returns the updated record; raises Gone when the store no longer has it."""
    brand = p.get("brand", "sp")
    try:
        if brand == "sp":
            raw = product_json(STORE, p["handle"])
            n = raw and normalize(raw, p.get("cat", "midi"), retain=True)
        elif brand == "md":
            raw = product_json(MD_STORE, p["handle"][3:])
            n = raw and normalize_md(raw, bf_handles, retain=True)
        elif brand == "ef":
            d = ef_product(p["url"].replace(EF_SITE, ""))
            n = dict(p, price=round(d["price"], 2), compare=round(d["compare"] if d["compare"] > d["price"] else d["price"], 2),
                     sizes=[{"s": "IT " + k, "a": a} for k, a in d["sizes"].items()]) if d["price"] else None
        else:
            return None
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            raise Gone() from e
        raise
    if not n:
        raise Gone()
    keep_keys = ("firstSeen", "guide", "guideImg", "guideAt", "dims")
    for k in keep_keys:
        if k in p and k not in n:
            n[k] = p[k]
    return n


def size_msgs(old, new):
    o = {x["s"]: x["a"] for x in old}
    return [f"{x['s']} {'back in stock' if x['a'] else 'sold out'}" for x in new if x["s"] in o and o[x["s"]] != x["a"]]


HEAVY = ("images", "details", "guide", "guideImg", "guideAt", "changes", "verifiedAt")


def _dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def write(data):
    """full.json keeps everything; data.json is the light list; more.json holds per-product extras."""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    _dump(FULL, data)
    light, more = [], {}
    for p in data.get("products", []):
        q = {k: v for k, v in p.items() if k not in HEAVY}
        imgs = p.get("images") or []
        if len(imgs) > 1:
            q["img2"] = imgs[1]
        q["nImg"] = len(imgs)
        dims = next((t for t in (p.get("guide") or []) if t.get("kind") == "Dimensions"), None)
        if dims:
            q["dims"] = " × ".join(r[0][:1] + " " + r[1] for r in dims["rows"]) + " cm"
        light.append(q)
        extra = {k: p[k] for k in ("images", "details", "guide", "guideImg", "guideAt") if p.get(k)}
        if extra.get("guideImg"):
            extra["guideImg"] = {k: v for k, v in extra["guideImg"].items() if k != "all"}
        more[p["handle"]] = extra
    removed = [{k: r.get(k) for k in ("handle", "title", "cat", "brand", "price", "url", "removedAt")} for r in data.get("removed", [])]
    _dump(OUT, {"meta": {k: v for k, v in data.get("meta", {}).items() if k != "everSeen"}, "products": light, "removed": removed})
    _dump(MORE, more)


def probe_illustration(handle):
    """Debug helper: show how the size-guide illustration is embedded in a product page."""
    page = fetch(f"{STORE}/products/{handle}", accept="text/html")
    low = page.lower()
    print("probe page bytes", len(page), "svg count", low.count("<svg"))
    for m in re.finditer(r"<img[^>]+>", page):
        tag = m.group(0)
        if re.search(r"size|guide|measure|diagram|sketch|garment|chart", tag, re.I):
            print("probe img:", tag[:400])
    for key in ("garment measurement", "size-guide", "sizeguide", "size_guide"):
        i = low.find(key)
        if i >= 0:
            print("probe ctx", key, ":", re.sub(r"\s+", " ", page[max(0, i - 300):i + 900])[:1200])
    for m in re.finditer(r"(https?:)?//[^\"' )]+\.(svg|png|jpe?g|webp)", page):
        u = m.group(0)
        if re.search(r"size|guide|measure|diagram|sketch|garment|dress-?shape|silhouette", u, re.I):
            print("probe url:", u)


def main():
    if DEBUG and os.environ.get("SG_PROBE"):
        try:
            probe_illustration(os.environ["SG_PROBE"])
        except Exception as e:  # noqa: BLE001
            print("probe failed", e)
    prev = load_prev()
    meta = prev.get("meta", {})
    ts = now_iso()
    meta["lastCheck"] = ts
    rate = fetch_rate()
    if rate:
        meta["rate"] = rate
    meta["usdRate"] = fetch_usd_rate()
    try:
        promo = fetch_sp_promo()
        if promo:
            meta["spPromo"] = promo
            meta["spPromoMiss"] = 0
        elif "spPromo" in meta:
            meta["spPromoMiss"] = meta.get("spPromoMiss", 0) + 1
            if meta["spPromoMiss"] >= 3:   # gone on 3 checks in a row: the promotion has ended
                print("Self-Portrait extra promotion no longer shown — removed")
                meta.pop("spPromo", None)
                meta["spPromoMiss"] = 0
    except Exception as e:  # noqa: BLE001
        print("sp promo check failed (keeping last known):", e)
    print("sp promo:", meta.get("spPromo"))
    if os.environ.get("MD_ENABLE", "1") == "1":
        try:
            chart = fetch_md_chart()
            if chart["tables"]:
                meta["mdChart"] = chart
        except Exception as e:  # noqa: BLE001
            print("md size chart failed:", e)

    old = {p["handle"]: dict(p, cat=p.get("cat", "midi")) for p in prev.get("products", [])}
    grp = lambda p: p.get("brand", "sp") + ":" + p["cat"]
    fresh, ok_cats, errors, raw_counts = {}, set(), [], {}
    for cat, handle in CATEGORIES:
        try:
            items = fetch_collection(handle)
            raw_counts[cat] = len(items)
            if not items:
                raise RuntimeError("collection returned no products")
            for p in items:
                n = normalize(p, cat)
                if n and n["handle"] not in fresh:
                    fresh[n["handle"]] = n
            ok_cats.add("sp:" + cat)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{cat}: {e}")
        time.sleep(1.5)
    if os.environ.get("MD_ENABLE", "1") != "1":
        md_items = None
    try:
        if os.environ.get("MD_ENABLE", "1") != "1":
            raise RuntimeError("Mac Duggal disabled")
        global MD_PROMO, MD_PROMOS
        known = [dict(x) for x in (meta.get("mdPromos") or ([meta["mdPromo"]] if meta.get("mdPromo") else []))]
        for x in known:
            x.setdefault("pct", int((re.search(r"(\d{1,2})\s*%", x.get("label", "")) or [0, 25])[1]))
            x.pop("source", None)
        try:
            found = fetch_md_promos()
            tags = {x["tag"] for x in found}
            promos = [dict(x, miss=0) for x in found]
            for x in known:   # a label no longer shown: confirm on 3 checks in a row before removing it everywhere
                if x.get("tag") and x["tag"] not in tags:
                    miss = x.get("miss", 0) + 1
                    if miss < 3:
                        promos.append(dict(x, miss=miss))
                    else:
                        print("Mac Duggal promotion no longer shown — removed:", x)
            meta["mdPromoMiss"] = 0
        except Exception as e:  # noqa: BLE001
            promos = known or [dict(MD_PROMO, miss=0)]
            print("md promo page failed (keeping last known):", e)
        meta["mdPromos"] = promos
        MD_PROMOS = [{k: v for k, v in x.items() if k != "miss"} for x in promos]
        MD_PROMO = MD_PROMOS[0] if MD_PROMOS else None
        print("md promos:", promos)
        md_items, raw_counts["md"] = fetch_md()
        for n in md_items:
            fresh[n["handle"]] = n
        ok_cats.add("md:maxi")
    except Exception as e:  # noqa: BLE001
        errors.append(f"macduggal: {e}")

    if os.environ.get("EF_ENABLE", "1") == "1":
        try:
            ef_items, raw_counts["ef"] = fetch_ef(DEBUG)
            for n in ef_items:
                fresh[n["handle"]] = n
            ok_cats.add("ef:maxi")
        except Exception as e:  # noqa: BLE001
            errors.append(f"elisabettafranchi: {e}")

    if not ok_cats:
        meta["lastError"] = f"{ts}: could not read the store ({'; '.join(errors)}). Showing data from the last successful check."
        prev["meta"] = meta
        write(prev)
        print(meta["lastError"])
        return

    # categories that failed this run keep their previous products
    for h, p in old.items():
        if grp(p) not in ok_cats and h not in fresh:
            fresh[h] = p
    for n in fresh.values():
        if grp(n) in ok_cats:
            n["listed"] = True     # in the store's sale list right now
            n["status"] = "ok"

    # PRODUCTS ARE NEVER DELETED AUTOMATICALLY. Anything known before (or removed by older versions of this
    # script) that is not in this run's lists stays, and is re-checked on its own official page.
    bf_set = set()
    try:
        bf_set = {p["handle"] for p in fetch_md_collection(MD_BF)} if os.environ.get("MD_ENABLE", "1") == "1" else set()
    except Exception:  # noqa: BLE001
        pass
    missing = [p for h, p in old.items() if h not in fresh]
    missing += [r for r in prev.get("removed", []) if r.get("handle") and r["handle"] not in fresh and r["handle"] not in old]
    missing.sort(key=lambda p: p.get("pageCheckedAt", ""))   # least recently checked first
    budget, refreshed, retired = int(os.environ.get("REFRESH_LIMIT", "60")), 0, 0
    for p in missing:
        h = p["handle"]
        if h in old and p.get("brand") == "md" and h in MD_RAW and "md:maxi" in ok_cats:
            # still in the official feed but no longer on sale / no longer labelled: use today's official data
            n = normalize_md(MD_RAW[h], bf_set, retain=True)
            if n:
                for k in ("firstSeen", "guide", "guideImg", "guideAt", "dims"):
                    if k in p and k not in n:
                        n[k] = p[k]
                n.update(listed=False, status="ok", pageCheckedAt=ts)
                fresh[h] = n
                refreshed += 1
                continue
        due = age_s(p.get("pageCheckedAt", "")) > 3 * 3600 or os.environ.get("RECHECK_ALL") == "1"
        if due and budget > 0 and grp(dict(p, cat=p.get("cat", "midi"))) in ok_cats:
            budget -= 1
            try:
                n = refresh_product(p, bf_set)
                if n:
                    n.update(listed=False, status="ok", pageCheckedAt=ts)
                    if h not in old:   # restored after an older version removed it: not new to the sale
                        n.update(firstSeen=p.get("firstSeen") or meta.get("initialImport", ts), restored=True)
                    fresh[h] = n
                    refreshed += 1
                    time.sleep(0.6)
                    continue
            except Gone:
                retired += 1
                fresh[h] = dict(p, listed=False, status="discontinued", pageCheckedAt=ts, compare=p.get("price", 0),
                                sizes=[dict(x, a=False) for x in p.get("sizes", [])], extra25=False, extraPct=0)
                continue
            except Exception as e:  # noqa: BLE001
                print("  re-check failed (kept as is):", h, e)
        if h in old:
            fresh[h] = dict(old[h], listed=False)   # kept exactly as last verified until its page can be re-checked
    print(f"kept off-list products: {sum(1 for p in fresh.values() if p.get('listed') is False)} "
          f"(re-checked {refreshed}, no longer sold by the store {retired})")

    groups = ["sp:" + c for c, _ in CATEGORIES] + ["md:maxi", "ef:maxi"]
    baseline = {g for g in groups if not any(grp(p) == g for p in old.values())}
    added, changed = [], []
    known_before = {r.get("handle") for r in prev.get("removed", [])} | set(meta.get("everSeen", []))
    for h, n in fresh.items():
        o = old.get(h)
        if grp(n) in ok_cats:
            n["verifiedAt"] = ts
        if not o:
            if n.pop("restored", False) or h in known_before:
                n.update(lastChanged=ts, changes=["Restored (kept permanently)"])
                continue
            if grp(n) in baseline:  # first time this category is tracked: starting stock, not "new"
                base = meta.get("initialImport", ts)
                n.update(firstSeen=base, lastChanged=ts, changes=[])
            else:
                n.update(firstSeen=ts, lastChanged=ts, changes=["Newly discovered on sale"])
                added.append(h)
            continue
        n["firstSeen"] = o.get("firstSeen", ts)
        if n.get("brand") == "md" and MD_PROMOS and (o.get("extraPct") or o.get("extra25")) and not n.get("extraPct"):
            miss = o.get("extraMiss", 0) + 1
            if miss < 3:
                n.update(extraPct=o.get("extraPct") or 25, extra25=o.get("extra25", True), extraMiss=miss)
        else:
            n.pop("extraMiss", None)
        msgs = []
        sym = "$" if n.get("cur") == "USD" else "€"
        if o.get("price") != n["price"]:
            msgs.append(f"Sale price {sym}{o.get('price', 0):g} → {sym}{n['price']:g}")
        if o.get("compare") != n["compare"]:
            msgs.append(f"Original price {sym}{o.get('compare', 0):g} → {sym}{n['compare']:g}")
        if o.get("listed", True) != n.get("listed", True):
            msgs.append("Back in the sale" if n.get("listed", True) else "Left the store's sale list")
        if o.get("status", "ok") != n.get("status", "ok"):
            msgs.append("No longer sold by the store" if n.get("status") == "discontinued" else "Available again")
        if o.get("extra25") != n.get("extra25") and n.get("brand") == "md":
            msgs.append("Extra 25% in cart " + ("now applies" if n.get("extra25") else "no longer applies"))
        if o.get("image") != n["image"]:
            msgs.append("Image updated")
        msgs += size_msgs(o.get("sizes", []), n["sizes"])
        if msgs:
            n.update(lastChanged=ts, changes=msgs)
            changed.append(h)
        else:
            n.update(lastChanged=o.get("lastChanged", ts), changes=o.get("changes", []))

    gone = []          # nothing is ever removed automatically
    removed = [r for r in prev.get("removed", []) if r["handle"] not in fresh][:120]   # older removals not restored yet

    products = sorted(fresh.values(), key=lambda p: p.get("firstSeen", ""), reverse=True)
    guides = read_guides(products, old)

    counts = {c: sum(1 for p in products if p["cat"] == c and p.get("brand", "sp") == "sp") for c, _ in CATEGORIES}
    counts["md"] = sum(1 for p in products if p.get("brand") == "md")
    counts["ef"] = sum(1 for p in products if p.get("brand") == "ef")
    meta.update(lastSuccess=ts, lastError=("; ".join(errors) and f"{ts}: partial check — {'; '.join(errors)}"),
                count=len(products), counts=counts, storeCounts=raw_counts,
                collections=dict({c: f"{STORE}/collections/{h}" for c, h in CATEGORIES}, md=f"{MD_STORE}/collections/{MD_MAXI}"),
                mdPromo=(dict(MD_PROMO, source=f"{MD_STORE} (product label shown by the official store)") if MD_PROMO else None))
    meta.setdefault("initialImport", ts)
    meta["everSeen"] = sorted(set(meta.get("everSeen", [])) | set(fresh.keys()))
    log = meta.get("log", [])
    log.insert(0, {"at": ts, "added": len(added), "removed": len(gone), "changed": len(changed), "guides": guides})
    meta["log"] = log[:40]
    write({"meta": meta, "products": products, "removed": removed})
    try:
        write_sitemap(products)
    except Exception as e:  # noqa: BLE001
        print("sitemap failed:", e)
    print(f"ok: {counts} (store feed {raw_counts}), +{len(added)} new, -{len(gone)} removed, "
          f"{len(changed)} changed, {guides} size guides read, rate {meta.get('rate', {}).get('value')}, errors {errors}")


if __name__ == "__main__":
    main()
