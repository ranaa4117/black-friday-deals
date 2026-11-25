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
    "tarte": "https://tartecosmetics.com", "kosas": "https://kosas.com", "refy": "https://refybeauty.com",
    "mac": "https://www.maccosmetics.com", "fenty": "https://fentybeauty.com", "rare": "https://www.rarebeauty.com",
}
NOT_READABLE = {"ct": "Charlotte Tilbury", "nars": "NARS", "huda": "HUDA BEAUTY", "toofaced": "Too Faced"}   # covered through Sephora USA
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
        rec.update(items=n, itemsHow=how, add=n * mk.ADD["per_item"] if n else None, addWhy=f"{n} × 20" if n else how)
        rec["contents"] = contents_list(desc)
    else:
        cls, why = mk.add_class(title, cat, size)
        rec.update(add=mk.ADD[cls], addClass=cls, addWhy=why, sizeMl=round(size) if size else None)
    return rec


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
        try:
            cat = catalog(base)
        except Exception as e:
            status[brand] = {"ok": False, "at": ts, "error": f"{type(e).__name__}: {str(e)[:160]}", "lastOk": (old.get("meta", {}).get("brands", {}).get(brand) or {}).get("lastOk")}
            for p in old.get("products", []):    # keep the last confirmed data, marked for re-check
                if p["brand"] == brand:
                    out[p["id"]] = dict(p, stale=True)
            print(brand, "FAILED", e); continue
        seen = set(); n_disc = n_set = 0
        for p in cat:
            r = record(brand, base, p)
            if not r:
                continue
            prev = old_by.get(r["id"])
            if not (r["compare"] or r["set"] or prev):     # Makeup Sale lists discounted pieces; gifts list every set
                continue
            r["firstSeen"] = (prev or {}).get("firstSeen", ts)
            r["checkedAt"] = ts
            if prev and prev.get("compare") and not r["compare"]:
                r["discEndedAt"] = ts                      # discount ended: stays at the official regular price
            out[r["id"]] = r; seen.add(r["id"])
            n_disc += bool(r["compare"]); n_set += r["set"]
        for p in old.get("products", []):                  # missing from the catalog: removed only after 3 misses over 24 h
            if p["brand"] != brand or p["id"] in seen:
                continue
            g = p.get("gone") or {"n": 0, "first": ts}
            g = {"n": g["n"] + 1, "first": g.get("first", ts)}
            span = (now - datetime.strptime(g["first"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
            if g["n"] >= GONE_CHECKS and span >= GONE_SPAN_H:
                print("removed (gone 3× / 24h):", p["id"]); continue
            out[p["id"]] = dict(p, gone=g)
        status[brand] = {"ok": True, "at": ts, "lastOk": ts, "catalog": len(cat), "discounted": n_disc, "sets": n_set}
        print(brand, "catalog", len(cat), "discounted", n_disc, "sets", n_set)
        time.sleep(2)
    for b, name in NOT_READABLE.items():
        status[b] = {"ok": None, "at": ts, "note": f"{name}: the official store can't be read automatically; its offers come from Sephora USA."}
    data = {"meta": {"updatedAt": ts, "brands": status}, "products": sorted(out.values(), key=lambda p: (p["brand"], p["title"]))}
    json.dump(data, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
    print("mk_brands:", len(out), "products")


if __name__ == "__main__":
    main()
