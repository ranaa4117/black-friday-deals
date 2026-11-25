#!/usr/bin/env python3
"""Build self-portrait/makeup.json for the Makeup section from:
  - Sephora USA snapshots (read by the Claude browser on the owner's computer, stored in Supabase)
  - mk_brands.json (official brand stores)
Nothing is invented: every product, price, code, condition and date comes from those official pages.
Old snapshots are kept and flagged for re-check; today-only deals are tied to the day Sephora published them."""
import json, os, re, sys, urllib.request
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mk_common as mk

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "self-portrait")
OUT, BR = os.path.join(ROOT, "makeup.json"), os.path.join(ROOT, "mk_brands.json")
SB = "https://qhuerltbkvihmqzsphpv.supabase.co/rest/v1/rpc/sephora_latest"
PUB = "sb_publishable_K35x9gcJMqTGCuj2MFj_7w_PsQSF8mU"
PT = timezone(timedelta(hours=-8))   # Sephora USA dates its daily deals in Pacific Time (PST in Nov–Mar)
TOP = {"makeup": "Makeup", "skincare": "Skincare", "hair": "Hair", "fragrance": "Fragrance", "bath": "Bath & Body", "tools": "Tools & Brushes"}
LIST_TOP = {"sale-makeup": "makeup", "sale-skincare": "skincare", "sale-hair": "hair", "sale-fragrance": "fragrance", "sale-bath": "bath", "sale-tools": "tools"}


def now_utc():
    return datetime.now(timezone.utc)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_t(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def money(s):
    m = re.search(r"\$\s?([\d,]+(?:\.\d+)?)", s or "")
    return round(float(m.group(1).replace(",", "")), 2) if m else None


def clean(s):
    return re.sub(r"\^([^^]{1,3})\^", r"\1", s or "").strip()


def snapshots():
    req = urllib.request.Request(SB, data=b"{}", headers={"apikey": PUB, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def sephora_item(sku, where=""):
    """A product as Sephora lists it in a campaign/offer section (page data)."""
    price, comp = money(sku.get("sale")) or money(sku.get("list")), money(sku.get("list")) if sku.get("sale") else None
    name, value = sku.get("name") or "", money(sku.get("value"))
    is_set = mk.is_set(name, value_price=value)
    r = {"id": "se-" + (sku.get("pid") or "") + "-" + (sku.get("sku") or ""), "pid": sku.get("pid"), "sku": sku.get("sku"), "brand": sku.get("brand") or "",
         "title": name, "url": (sku.get("url") or "").split("&icid2")[0], "image": sku.get("img") or "", "variation": sku.get("variation") or "",
         "price": price, "compare": comp if comp and price and comp > price else None, "value": value, "set": is_set, "oos": bool(sku.get("oos")),
         "bi": sku.get("bi") or "none"}
    if r["compare"]:
        r["discPct"] = round(100 * (1 - price / comp))
    return r


def tile_item(t, top):
    """A product tile from a Sephora sale/gift listing (as shown on screen)."""
    tx = t.get("t") or []
    if len(tx) < 3:
        return None
    brand, name = tx[0], tx[1]
    prices = [money(x) for x in tx if re.match(r"^\$", x)]
    rng = [x for x in tx if re.match(r"^\$", x)]
    value = next((money(x) for x in tx if re.match(r"^\(\$.*value\)$", x)), None)
    colors = next((x for x in tx if re.match(r"^\d+ Colors?$", x)), "")
    flags = [x for x in tx if x in ("NEW", "LIMITED EDITION", "ONLY AT SEPHORA", "ONLINE ONLY", "APP EXCLUSIVE", "LIMITED TIME OFFER", "EXCLUSIVE")]
    if not prices or prices[0] is None:
        return None
    price, comp = prices[0], (prices[1] if len(prices) > 1 else None)
    r = {"id": "se-" + t.get("pid", ""), "pid": t.get("pid"), "brand": brand, "title": name, "url": (t.get("url") or "").split("&icid2")[0],
         "image": re.sub(r"imwidth=\d+", "imwidth=450", t.get("img") or ""), "price": price, "compare": comp if comp and comp > price else None,
         "range": " – ".join(rng[:1]) if rng and " - " in rng[0] else "", "value": value, "colors": colors, "flags": flags, "top": top,
         "set": mk.is_set(name, value_price=value)}
    if r["compare"]:
        r["discPct"] = round(100 * (1 - price / comp))
    return r


def price_rule(r, set_cache):
    """Attach the add-on (SAR) and why. Sets: 20 SAR × products inside, only when the official contents list is known."""
    if r.get("set"):
        info = set_cache.get(r.get("pid") or r.get("id")) or {}
        n = r.get("items") or info.get("items")
        if not n:
            n, _how = mk.set_items(r.get("title", ""))          # "Duo" / "Trio" / "5-Piece" in the official name
        if n:
            r.update(items=n, add=n * mk.ADD["per_item"], addWhy=f"{n} منتجات × 20", contents=r.get("contents") or info.get("contents") or [])
        else:
            r.update(add=None, addWhy="عدد المنتجات داخل المجموعة غير منشور بعد — لا تظهر للعميلات حتى يُتحقق منه")
        return r
    cat = r.get("cat") or mk.category(r.get("title", ""))
    r["cat"] = cat
    cls, why = mk.add_class(r.get("title", ""), cat, mk.size_of(r.get("variation", "")), top=r.get("top") or mk.top_of(r.get("title", "")))
    r.update(add=mk.ADD[cls], addClass=cls, addWhy=why)
    return r


def offer_rec(o, section, page):
    el = [e for e in (o.get("eligibility") or [])]
    text = " ".join([o.get("title", ""), o.get("desc", ""), o.get("threshold", ""), (o.get("media") or {}).get("alt", "")])
    members = [e for e in el if e in ("Insider", "VIB", "Rouge")]
    app = "App" in el or bool(re.search(r"\bapp[- ]exclusive|in the sephora app|app only", text, re.I))
    online = "Online" in el and "In Store" not in el
    instore = "In Store" in el and "Online" not in el
    kind = ("sample" if re.search(r"sample|deluxe|trial", text, re.I) and not re.search(r"% off", text, re.I)
            else "gwp" if re.search(r"free gift|gift with|\bgwp\b|free\*? .*(bag|pouch|gift)|complimentary", text, re.I)
            else "points" if re.search(r"points|\bpts\b|bonus", text, re.I)
            else "subscription" if re.search(r"subscri|auto-?replenish", text, re.I)
            else "card" if re.search(r"credit card", text, re.I)
            else "code" if o.get("code")
            else "sale" if re.search(r"sale|% off|off select|hot deal|save", text, re.I) else "other")
    return {"id": o.get("id"), "title": clean(o.get("title")), "desc": clean(o.get("desc")), "code": (o.get("code") or "").upper(),
            "threshold": clean(o.get("threshold")), "minSpend": money(o.get("threshold")) if re.search(r"min", o.get("threshold") or "", re.I) else None,
            "eligibility": el, "members": members, "appOnly": app, "onlineOnly": online, "inStoreOnly": instore, "kind": kind,
            "legal": clean(o.get("legal")), "image": (o.get("media") or {}).get("src", ""), "imageAlt": clean((o.get("media") or {}).get("alt", "")),
            "url": o.get("details") or o.get("action") or page, "shop": o.get("action") or "", "sections": [section],
            "products": [sephora_item(s) for s in (o.get("skus") or [])][:24]}


def campaign(snap, now):
    d = snap["data"]; at = parse_t(snap["at"]); read_pt = at.astimezone(PT)
    hero = d.get("hero") or {}
    end = None
    m = re.search(r"(?:through|thru|until|ends?)\s+(\d{1,2})/(\d{1,2})", (hero.get("text") or "") + " " + d.get("title", ""), re.I)
    if m:
        end = datetime(read_pt.year, int(m.group(1)), int(m.group(2)), 23, 59, tzinfo=PT)
    secs, offers, starts = [], [], None
    for s in d.get("sections") or []:
        t = clean(s.get("title"))
        if s["type"] == "ProductList":
            today = bool(re.search(r"today only", t, re.I))
            prods = [sephora_item(x) for x in s.get("products") or []]
            if not today:
                prods = [x for x in prods if x.get("compare")]     # only pieces Sephora shows at a lower price
                if not prods:
                    continue
            secs.append({"kind": "deal" if today else "products", "title": t, "todayOnly": today, "validDate": read_pt.strftime("%Y-%m-%d") if today else None,
                         "more": s.get("more") or "", "moreLabel": s.get("moreLabel") or "", "products": prods})
        elif s["type"] == "PromotionList":
            ids = []
            for o in s.get("offers") or []:
                rec = offer_rec(o, t or "Offers", d.get("url")); offers.append(rec); ids.append(rec["id"])
            secs.append({"kind": "promos", "title": t, "offers": ids, "personalized": bool(s.get("personalized") and not ids)})
        elif s["type"] in ("BannerList", "Banner"):
            bs = [{"text": clean(b.get("text")), "image": (b.get("media") or {}).get("src", ""), "alt": clean((b.get("media") or {}).get("alt", "")),
                   "url": b.get("url") or "", "bg": b.get("bg") or "", "color": b.get("color") or ""} for b in s.get("banners") or []]
            OFFER = r"% off|\boff\b|free gift|free\*? sample|deal|save|savings|gift with|points|code|half off|starts|today only|black friday|cyber"
            planner = bool(re.search(r"come back|upcoming|more deals", t, re.I))
            if re.search(r"payment|delivery|tools & resources|gifts by price|gift cards?|by category|ways to shop", t, re.I):
                continue                                 # Sephora services and shopping guides, not promotions
            if not planner:
                bs = [b for b in bs if re.search(OFFER, b["text"] + " " + b["alt"], re.I)]
            if not bs:
                continue
            for b in bs:
                m2 = re.search(r"starts?\s+(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm))?", b["text"] + " " + b["alt"], re.I)
                if m2:
                    hh = int(m2.group(3) or 0) % 12 + (12 if (m2.group(5) or "").lower() == "pm" else 0)
                    st = datetime(read_pt.year, int(m2.group(1)), int(m2.group(2)), hh, int(m2.group(4) or 0), tzinfo=PT)
                    starts = min(starts, st) if starts else st
            secs.append({"kind": "banners", "title": t, "planner": planner, "banners": bs})
        elif s["type"] == "SoftLinks":
            secs.append({"kind": "links", "title": t, "links": s.get("links") or []})
    navi = d.get("navigation") or {}
    tabs = [{"label": n.get("label"), "url": (n.get("url") or "").split("?")[0], "current": n.get("current")} for n in (navi.get("items") or [])]
    status = "ended" if end and now > end else "active"
    has_deals = any(x["kind"] in ("deal", "products", "promos") for x in secs)
    if starts and now < starts and not has_deals:
        status = "preview"                       # Sephora says it starts later: shown as a preview, never as active
    if re.search(r"\bpreview\b|coming soon|sneak peek", (hero.get("text") or "") + d.get("title", ""), re.I) and not has_deals:
        status = "preview"
    return {"label": snap["label"], "url": d.get("url"), "title": d.get("title", "").replace(" | Sephora", ""), "readAt": snap["at"],
            "hero": {"text": clean(hero.get("text")), "image": (hero.get("media") or {}).get("src", ""), "alt": clean((hero.get("media") or {}).get("alt", "")), "bg": hero.get("bg", "")} if hero else None,
            "parent": {"label": navi.get("label"), "url": (navi.get("url") or "").split("?")[0]} if navi else None, "tabs": tabs,
            "endsAt": iso(end.astimezone(timezone.utc)) if end else None, "startsAt": iso(starts.astimezone(timezone.utc)) if starts else None, "status": status, "sections": secs}, offers


def main():
    now = now_utc(); ts = iso(now)
    try:
        old = json.load(open(OUT))
    except Exception:
        old = {}
    try:
        brands = json.load(open(BR))
    except Exception:
        brands = {"products": [], "meta": {}}
    set_cache = dict((old.get("meta") or {}).get("setInfo") or {})
    problems, pages = [], []
    try:
        snaps = snapshots(); sephora_ok = True
    except Exception as e:
        snaps, sephora_ok = [], False
        problems.append({"key": "sephora-db", "text": f"تعذّر قراءة بيانات سيفورا المحفوظة: {type(e).__name__}"})
    # gift-set contents read from Sephora product pages
    for s in snaps:
        if s["kind"] == "product":
            d = s["data"]; n, how = mk.set_items(d.get("name") or "", d.get("desc") or "")
            from mk_brands import contents_list
            set_cache[d.get("pid")] = {"items": n, "how": how, "contents": contents_list(d.get("desc") or ""), "at": s["at"],
                                       "appOnly": d.get("appOnly"), "onlineOnly": d.get("onlineOnly"), "cats": d.get("cats")}
    campaigns, offers = [], {}
    sale_items, gift_items = {}, {}
    sale_meta = {}
    for s in snaps:
        age_h = (now - parse_t(s["at"])).total_seconds() / 3600
        pages.append({"kind": s["kind"], "label": s["label"], "url": s["url"], "at": s["at"], "ageH": round(age_h, 1)})
        if s["kind"] == "content":
            c, offs = campaign(s, now)
            c["stale"] = age_h > 12
            for o in offs:
                if o["id"] in offers:
                    offers[o["id"]]["sections"] = sorted(set(offers[o["id"]]["sections"] + o["sections"]))
                else:
                    offers[o["id"]] = dict(o, readAt=s["at"], page=s["label"])
            campaigns.append(c)
        elif s["kind"] == "list":
            d = s["data"]; lab = s["label"]
            top = LIST_TOP.get(lab)
            sale_meta[lab] = {"total": d.get("total"), "read": len(d.get("items") or []), "complete": d.get("complete"), "at": s["at"], "stale": age_h > 30}
            for t in d.get("items") or []:
                r = tile_item(t, top or "makeup")
                if not r:
                    continue
                if lab.startswith("gifts"):
                    r["set"] = True
                    gift_items.setdefault(r["id"], r)
                elif top:
                    sale_items.setdefault(r["id"], r)
    # Sephora sale: only pieces Sephora shows with a lower price than before
    sale = [price_rule(r, set_cache) for r in sale_items.values() if r.get("compare")]
    for r in sale:
        r["brandKey"] = mk.SEPHORA_NAMES.get(r["brand"].lower())
    # Makeup Sale (13 brands): official brand stores + those brands' individual pieces in the Sephora sale
    mk_sale = []
    for p in brands.get("products") or []:
        if p.get("set"):
            continue
        mk_sale.append(price_rule(dict(p, top="makeup"), set_cache))
    for r in sale:
        if r["brandKey"] and not r["set"] and r["top"] == "makeup":
            mk_sale.append(dict(r, brand=r["brandKey"], retailer="Sephora", src="sephora"))
    # Gifts: genuine sets from the brand stores and from Sephora (sale sets + Sephora's gift-set listings)
    gifts = []
    for p in brands.get("products") or []:
        if p.get("set"):
            gifts.append(price_rule(dict(p), set_cache))
    seen = set()
    for r in [x for x in sale if x["set"]] + list(gift_items.values()):
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        gifts.append(price_rule(dict(r, brandKey=mk.SEPHORA_NAMES.get(r["brand"].lower()), retailer="Sephora", src="sephora"), set_cache))
    for c in campaigns:                      # products shown inside Sephora campaign pages and offers: same price rules
        for sec in c["sections"]:
            sec["products"] = [price_rule(dict(p, top=mk.top_of(p["title"])), set_cache) for p in sec.get("products") or []]
    for o in offers.values():
        o["products"] = [price_rule(dict(p, top=mk.top_of(p["title"])), set_cache) for p in o.get("products") or []]
    camp_sets = [p["url"] for c in campaigns for sec in c["sections"] for p in sec.get("products") or [] if p.get("set") and p.get("add") is None and p.get("pid") not in set_cache]
    need_sets = list(dict.fromkeys(camp_sets + [g["url"] for g in gifts if g.get("src") == "sephora" and g.get("add") is None and g.get("pid") not in set_cache]))[:40]
    # campaign history: campaigns that disappeared or ended stay in the admin history
    hist = {h["label"]: h for h in (old.get("history") or [])}
    for c in campaigns:
        if c["status"] == "ended":
            hist[c["label"]] = {"label": c["label"], "title": c["title"], "url": c["url"], "endedAt": c.get("endsAt") or ts, "lastRead": c["readAt"]}
    out = {"meta": {"updatedAt": ts, "sephoraOk": sephora_ok, "pages": sorted(pages, key=lambda p: p["label"]), "sale": sale_meta,
                    "brands": (brands.get("meta") or {}).get("brands", {}), "brandsAt": (brands.get("meta") or {}).get("updatedAt"),
                    "needSets": need_sets, "setInfo": set_cache, "problems": problems,
                    "add": mk.ADD, "cats": mk.CATS, "brandNames": mk.BRANDS, "top": TOP},
           "campaigns": campaigns, "offers": list(offers.values()), "sale": sale, "makeup": mk_sale, "gifts": gifts,
           "history": sorted(hist.values(), key=lambda h: h.get("endedAt") or "", reverse=True)[:60]}
    json.dump(out, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"makeup.json: campaigns {len(campaigns)}, offers {len(offers)}, sephora sale {len(sale)}, makeup sale {len(mk_sale)}, gifts {len(gifts)} (need contents: {len(need_sets)})")


if __name__ == "__main__":
    main()
