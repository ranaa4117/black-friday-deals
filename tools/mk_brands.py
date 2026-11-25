#!/usr/bin/env python3
"""Makeup brands from their official US stores (the ones whose public catalog can be read automatically).
Writes self-portrait/mk_brands.json:
  - discounted makeup products (official compare-at price above the selling price), shades as variants
  - genuine sets / kits / bundles (gifts), with the number of products inside when the official text lists it
Rules: a failed read keeps the last confirmed data (marked stale); a discount that ends keeps the product at its
official regular price; a product is removed only after it is missing from the catalog 3 times over 24 hours."""
import json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mk_common as mk

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "self-portrait", "mk_brands.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
SHOPIFY = {   # brand key → official US store
    "mario": "https://www.makeupbymario.com", "westman": "https://www.westman-atelier.com", "saie": "https://saiehello.com",
    "tarte": "https://tartecosmetics.com", "kosas": "https://kosas.com", "refy": "https://us.refybeauty.com",
    "mac": "https://www.maccosmetics.com", "huda": "https://hudabeauty.com", "fenty": "https://fentybeauty.com", "rare": "https://www.rarebeauty.com",
}
NOT_READABLE = {"ct": "Charlotte Tilbury", "nars": "NARS", "toofaced": "Too Faced"}   # covered through Sephora USA
MAKEUP_TYPES = r"makeup|make-up|cosmetic|lip|eye|brow|lash|mascara|liner|face|cheek|blush|bronz|highlight|foundation|conceal|powder|primer|setting|palette|brush|sponge|tint|gloss"
SKIP_TYPES = r"skin ?care|cleanser|moistur|serum(?!.*foundation)|body|hair|fragrance|perfume|candle|gift card|sample|merch|apparel|tote|bag$|accessor"
GONE_CHECKS, GONE_SPAN_H = 3, 24


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(6 * (i + 1) ** 2); continue
            raise
        except Exception:
            if i < tries - 1:
                time.sleep(5 * (i + 1)); continue
            raise


def us_store(base):
    """The store must be the US store selling in US dollars (Shopify's public shop info)."""
    try:
        m = get(f"{base}/meta.json")
        return (m.get("currency") == "USD", f"{m.get('country') or '?'} / {m.get('currency') or '?'}")
    except Exception as e:
        return (None, f"shop info not readable ({type(e).__name__})")


def best_selling(base, pages=5):
    """The store's own 'Best selling' order (official popularity signal), handle → rank."""
    order = []
    for pg in range(1, pages + 1):
        try:
            req = urllib.request.Request(f"{base}/collections/all?sort_by=best-selling&page={pg}", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                html_ = r.read().decode("utf-8", "replace")
        except Exception:
            break
        found = [h for h in re.findall(r'href="/(?:[a-z-]+/)?products/([a-z0-9-]+)', html_) if h not in order]
        if not found:
            break
        order += list(dict.fromkeys(found)); time.sleep(1)
    return {h: i + 1 for i, h in enumerate(order)}


def announcements(base):
    """What the US store's own home page announces (for the admin audit): lines mentioning % off, sale, code, free."""
    try:
        req = urllib.request.Request(base + "/", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=45) as r:
            t = mk.text_of(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return [f"home page not readable ({type(e).__name__})"]
    lines = [ln for ln in t.split("\n") if 6 < len(ln) < 160 and re.search(r"(?i)\d+\s*% off|\bsale\b|\bcode\b|free gift|gift with|bogo|buy \d|black friday|cyber", ln)]
    return list(dict.fromkeys(lines))[:8]


def promo_collections(base):
    """Official promotion collections linked from the store's own pages, whose own title states one exact
    discount ("CYBERFEST 30% Off"). Returns {handle: (pct, title)}. 'Up to' titles are not used."""
    found = {}
    for page in ("/", "/collections/sale", "/pages/sale", "/collections/all"):
        try:
            req = urllib.request.Request(base + page, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                h = r.read().decode("utf-8", "replace")
        except Exception:
            continue
        for handle in set(re.findall(r'/collections/([a-z0-9-]*?\d{2}-?(?:percent-|pct-)?off[a-z0-9-]*)', h)):
            if handle in found:
                continue
            try:
                c = get(f"{base}/collections/{handle}.json").get("collection") or {}
            except Exception:
                continue
            title = c.get("title") or ""
            m = re.search(r"(?i)(?<!up to )\b(\d{2})\s*%\s*off\b", title)
            if m and not re.search(r"(?i)up to", title):
                found[handle] = (int(m.group(1)), title)
        time.sleep(1)
    return found


def catalog(base):
    out, page = [], 1
    while page <= 40:
        d = get(f"{base}/products.json?limit=250&page={page}")
        ps = d.get("products") or []
        out += ps
        if len(ps) < 250:
            break
        page += 1; time.sleep(1.5)
    if not out:
        raise RuntimeError("empty catalog")
    return out


def money(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def record(brand, base, p):
    title, ptype, tags = p.get("title") or "", p.get("product_type") or "", p.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    desc = p.get("body_html") or ""
    imgs = [i.get("src") for i in p.get("images") or [] if i.get("src")]
    by_id = {i.get("id"): i.get("src") for i in p.get("images") or []}
    variants = []
    for v in p.get("variants") or []:
        price, comp = money(v.get("price")), money(v.get("compare_at_price"))
        if price is None or price <= 0:
            continue
        img = by_id.get(v.get("image_id")) or ((v.get("featured_image") or {}).get("src")) or (imgs[0] if imgs else "")
        variants.append({"id": str(v.get("id")), "name": "" if (v.get("title") or "") == "Default Title" else v.get("title"),
                         "price": price, "compare": comp if comp and comp > price else None, "a": bool(v.get("available")), "image": img})
    if not variants:
        return None
    if mk.not_beauty(title, ptype):
        return None
    if mk.is_fragrance(title, ptype):                     # no fragrance anywhere on the site
        return None
    is_set = mk.is_set(title, ptype, tags)
    cat = mk.category(title, ptype)
    if not is_set:
        typed = f"{ptype} {' '.join(tags)}".lower()
        if re.search(SKIP_TYPES, typed) and not re.search(MAKEUP_TYPES, ptype.lower()):
            return None
        if cat == "other" and not re.search(MAKEUP_TYPES, f"{ptype} {title}".lower()):
            return None
    disc = [v for v in variants if v["compare"]]
    show = [v for v in (disc or variants) if v["a"]] or (disc or variants)
    best = min(show, key=lambda v: v["price"])
    size = mk.size_of(" ".join([title] + [v["name"] or "" for v in variants]) + " " + mk.text_of(desc)[:600])
    rec = {"id": f"mk-{brand}-{p.get('handle')}", "brand": brand, "src": "brand", "retailer": mk.BRANDS[brand], "title": title,
           "url": f"{base}/products/{p.get('handle')}", "type": ptype, "cat": cat, "set": is_set,
           "image": best["image"] or (imgs[0] if imgs else ""), "images": imgs[:8], "variants": variants,
           "price": best["price"], "compare": best["compare"], "available": any(v["a"] for v in variants)}
    if rec["compare"]:
        rec["discPct"] = round(100 * (1 - rec["price"] / rec["compare"]))
    if is_set:
        n, how = mk.set_items(title, desc)
        rec.update(items=n, itemsHow=how)                   # the fee is decided in the build by the set's size
        rec["contents"] = contents_list(desc)
        if mk.is_fragrance(" ".join(rec["contents"])):      # a set with a fragrance inside is left out entirely
            return None
        if not rec["contents"]:
            rec["descText"] = mk.text_of(desc)[:1200]     # kept so the admin can see why the count is missing
    else:
        cls, why = mk.add_class(title, cat, size, top=mk.top_of(f"{title} {ptype}"), detail=" ".join([v["name"] or "" for v in variants]) + " " + mk.text_of(desc)[:800])
        rec.update(add=mk.ADD[cls], addClass=cls, addWhy=why, sizeMl=round(size) if size else None)
    return rec


SPLIT = re.compile(r"\s+[—–]\s+")


def group_shades(brand, recs):
    """Some stores sell each shade as its own product ("Name — Shade"). Shown as one product with shades."""
    groups = {}
    for r in recs:
        parts = SPLIT.split(r["title"], maxsplit=1)
        key = parts[0].strip().lower() if len(parts) == 2 else r["id"]
        groups.setdefault(key, []).append((r, parts[1].strip() if len(parts) == 2 else ""))
    out = {}
    for key, items in groups.items():
        if len(items) == 1 and not items[0][1]:
            out[items[0][0]["id"]] = items[0][0]; continue
        items.sort(key=lambda x: x[1])
        base = dict(items[0][0]); base["title"] = SPLIT.split(base["title"], maxsplit=1)[0].strip()
        base["id"] = f"mk-{brand}-g-" + re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:80]
        vs = []
        for r, shade in items:
            for v in r["variants"]:
                vs.append(dict(v, name=shade + (" / " + v["name"] if v.get("name") else ""), url=r["url"]))
        base["variants"] = vs
        disc = [v for v in vs if v.get("compare") and v.get("a")] or [v for v in vs if v.get("compare")] or vs
        best = min(disc, key=lambda v: v["price"])
        base.update(price=best["price"], compare=best.get("compare"), image=best.get("image") or base.get("image"), url=best.get("url") or base["url"],
                    available=any(v.get("a") for v in vs), firstSeen=min(r.get("firstSeen", "") for r, _ in items),
                    storeRank=min([r["storeRank"] for r, _ in items if r.get("storeRank")] or [None]) if any(r.get("storeRank") for r, _ in items) else None)
        base.pop("discPct", None)
        if base["compare"]:
            base["discPct"] = round(100 * (1 - base["price"] / base["compare"]))
        out[base["id"]] = base
    return out


def contents_list(desc):
    t = mk.text_of(desc)
    m = re.search(r"(?is)(?:includes?|contains?|what'?s inside)\s*:?\s*\n(.+)", t)
    if not m:
        return []
    out = []
    for ln in m.group(1).split("\n"):
        ln = ln.strip(" •-–*·\t")
        if not ln:
            if out:
                break
            continue
        if re.match(r"(?i)^(how to|what it is|why|benefits|ingredients|key|formulation)", ln):
            break
        out.append(ln[:140])
    return out[:30]


def main():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        old = json.load(open(OUT))
    except Exception:
        old = {"products": [], "meta": {}}
    last = (old.get("meta") or {}).get("updatedAt", "")
    if last and os.environ.get("MK_FORCE") != "1":
        age = (now - datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
        if age < 175 * 60:
            print("mk_brands: checked", round(age / 60), "minutes ago — next check after 3 hours"); return
    old_by = {p["id"]: p for p in old.get("products", [])}
    out, status = {}, {}
    for brand, base in SHOPIFY.items():
        ok_us, us_note = us_store(base)
        if ok_us is False:                                  # not a US-dollar store: nothing from it is shown
            status[brand] = {"ok": False, "at": ts, "error": f"not the US store ({us_note})"}
            print(brand, "NOT US", us_note); continue
        try:
            cat = catalog(base)
            ranks = best_selling(base)
        except Exception as e:
            status[brand] = {"ok": False, "at": ts, "error": f"{type(e).__name__}: {str(e)[:160]}", "lastOk": (old.get("meta", {}).get("brands", {}).get(brand) or {}).get("lastOk")}
            for p in old.get("products", []):    # keep the last confirmed data, marked for re-check
                if p["brand"] == brand:
                    out[p["id"]] = dict(p, stale=True)
            print(brand, "FAILED", e); continue
        seen = set(); n_disc = n_set = 0
        promo_of, promos = {}, {}                           # product handle → (pct, official collection title)
        try:
            promos = promo_collections(base)
            ann = announcements(base)
            print(brand, "home page offers:", ann)
            print(brand, "promotion collections:", {h: t for h, (pc, t) in promos.items()})
            for handle, (pct, title) in promos.items():
                for pr in get(f"{base}/collections/{handle}/products.json?limit=250").get("products") or []:
                    if pct > promo_of.get(pr["handle"], (0, ""))[0]:
                        promo_of[pr["handle"]] = (pct, title)
        except Exception as e:
            print(brand, "promo collections not read:", e)
        import collections as _c
        tagc = _c.Counter(t for p in cat for t in ((p.get("tags") or []) if isinstance(p.get("tags"), list) else str(p.get("tags") or "").split(","))
                          if re.search(r"(?i)off|save|sale|promo|bf|cyber|black|discount|deal|exclu", t))
        print(brand, "promotion tags:", dict(tagc.most_common(15)))
        for p in cat:
            tags = p.get("tags") if isinstance(p.get("tags"), list) else [t.strip() for t in str(p.get("tags") or "").split(",")]
            for t in tags:                                  # the product's own official promotion tag, e.g. "_visibleSave_25" / "tag:25% OFF"
                m = re.match(r"(?i)^(?:_visibleSave_(\d{2})|tag:\s*(\d{2})% ?off)$", t.strip())
                if m and p.get("handle") not in promo_of:
                    promo_of[p["handle"]] = (int(m.group(1) or m.group(2)), f"{int(m.group(1) or m.group(2))}% Off")
        for p in cat:
            r = record(brand, base, p)
            if r and not r["compare"] and p.get("handle") in promo_of:
                pct, ptitle = promo_of[p["handle"]]          # the store's own collection says this product is N% off
                for v in r["variants"]:
                    if not v.get("compare"):
                        v["compare"] = v["price"]; v["price"] = round(v["price"] * (1 - pct / 100), 2)
                r["compare"], r["price"] = r["price"], round(r["price"] * (1 - pct / 100), 2)
                r["discPct"], r["promo"] = pct, {"pct": pct, "label": ptitle, "applied": "checkout"}
            if not r:
                continue
            prev = old_by.get(r["id"])
            if not (r["compare"] or r["set"] or prev):     # Makeup Sale lists discounted pieces; gifts list every set
                continue
            r["firstSeen"] = (prev or {}).get("firstSeen", ts)
            r["storeRank"] = ranks.get(p.get("handle"))
            r["source"] = f"{base} (official US store, {us_note})"
            r["checkedAt"] = ts
            if prev and prev.get("compare") and not r["compare"]:
                r["discEndedAt"] = ts                      # discount ended: stays at the official regular price
            out[r["id"]] = r; seen.add(r["id"])
            n_disc += bool(r["compare"]); n_set += r["set"]
        out.update(group_shades(brand, [out.pop(i) for i in [k for k in list(out) if k in seen and not out[k]["set"]]]))
        handles = {x.get("handle") for x in cat}
        live_urls = {v.get("url") or r["url"] for r in out.values() if r["brand"] == brand for v in r.get("variants", [])} | {r["url"] for r in out.values() if r["brand"] == brand}
        for p in old.get("products", []):                  # missing from the catalog: removed only after 3 misses over 24 h
            if p["brand"] != brand or p["id"] in seen or p["id"] in out or p.get("url") in live_urls:
                continue
            if (p.get("url") or "").rstrip("/").split("/")[-1] in handles:
                continue                                   # still sold, but now excluded by the rules (not makeup / fragrance / not beauty)                                   # still there (possibly now shown together with its other shades)
            g = p.get("gone") or {"n": 0, "first": ts}
            g = {"n": g["n"] + 1, "first": g.get("first", ts)}
            span = (now - datetime.strptime(g["first"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
            if g["n"] >= GONE_CHECKS and span >= GONE_SPAN_H:
                print("removed (gone 3× / 24h):", p["id"]); continue
            out[p["id"]] = dict(p, gone=g)
        status[brand] = {"ok": True, "at": ts, "lastOk": ts, "catalog": len(cat), "discounted": n_disc, "sets": n_set, "us": us_note, "ranked": len(ranks),
                         "promoCollections": [t for _, t in promos.values()], "announcements": ann if 'ann' in dir() else [], "promoProducts": sum(1 for r in out.values() if r["brand"] == brand and r.get("promo"))}
        print(brand, "catalog", len(cat), "discounted", n_disc, "sets", n_set)
        time.sleep(2)
    for b, name in NOT_READABLE.items():
        status[b] = {"ok": None, "at": ts, "note": f"{name}: the official store can't be read automatically; its offers come from Sephora USA."}
    data = {"meta": {"updatedAt": ts, "brands": status}, "products": sorted(out.values(), key=lambda p: (p["brand"], p["title"]))}
    json.dump(data, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
    print("mk_brands:", len(out), "products")


if __name__ == "__main__":
    main()
