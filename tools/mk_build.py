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


OVR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mk_overrides.json")
try:
    OVR = json.load(open(OVR_PATH))     # owner/admin decisions: product-only photo, gift-set size after manual review
except Exception:
    OVR = {"images": {}, "giftSize": {}}


def price_rule(r, pinfo):
    """Add-on (SAR): gift sets 250 / 120 / 60 by the set's real size (manual review when unknown);
    single products 30 / 40 / 60, large eyeshadow palettes 80."""
    info = pinfo.get(r.get("pid") or "") or {}
    if r.get("set"):
        contents = r.get("contents") or info.get("contents") or []
        cls, why = mk.gift_class(r.get("title", ""), contents, info.get("desc", ""))
        if OVR.get("giftSize", {}).get(r.get("id")):
            cls, why = OVR["giftSize"][r["id"]], "size set by manual review"
        r["contents"] = contents
        if cls:
            r.update(add=mk.GIFT_ADD[cls], addClass="gift_" + cls, addWhy=why)
        else:
            r.update(add=None, addClass=None, addWhy="حجم المجموعة غير واضح من المصدر الرسمي — تحتاج مراجعة يدوية ولا تظهر للعميلات")
        return r
    cat = r.get("cat") or mk.category(r.get("title", ""))
    r["cat"] = cat
    detail = " ".join([r.get("variation", ""), info.get("size", ""), info.get("variation", ""), (info.get("desc") or "")[:800]])
    cls, why = mk.add_class(r.get("title", ""), cat, mk.size_of(r.get("variation", "") + " " + info.get("size", "")),
                            top=r.get("top") or mk.top_of(r.get("title", "")), detail=detail)
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
            if re.search(r"tools?\b|korean|k-beauty", t, re.I):
                continue                                 # tools and K-beauty cards are not part of this section
            prods = [x for x in (sephora_item(x) for x in s.get("products") or []) if not mk.is_fragrance(x["title"])]
            if not today:
                prods = [x for x in prods if x.get("compare")]     # only pieces Sephora shows at a lower price
                if not prods:
                    continue
            secs.append({"kind": "deal" if today else "products", "title": t, "todayOnly": today, "validDate": read_pt.strftime("%Y-%m-%d") if today else None,
                         "more": s.get("more") or "", "moreLabel": s.get("moreLabel") or "", "products": prods})
        elif s["type"] == "PromotionList":
            continue                                     # promotion cards (sample bags, member gifts, codes…) are not shown
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
            continue
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


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


SEPHORA_CAMPAIGN = r"cyber|black-friday"      # the only two Sephora sections shown (owner's decision)


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
    pinfo = dict((old.get("meta") or {}).get("pinfo") or {})
    problems, pages, removed_ship = [], [], []
    try:
        snaps = snapshots(); sephora_ok = True
    except Exception as e:
        snaps, sephora_ok = [], False
        problems.append({"key": "sephora-db", "text": f"تعذّر قراءة بيانات سيفورا المحفوظة: {type(e).__name__}"})
    from mk_brands import contents_list
    for s in snaps:                                   # Sephora product pages: set contents, size, shipping flag
        if s["kind"] == "product":
            d = s["data"]
            pinfo[d.get("pid")] = {"at": s["at"], "contents": contents_list(d.get("desc") or ""), "desc": mk.text_of(d.get("desc") or "")[:1500],
                                   "size": d.get("size") or "", "variation": d.get("variation") or "", "hazmat": d.get("hazmat"),
                                   "appOnly": d.get("appOnly"), "cats": d.get("cats"), "url": d.get("url")}
    rank = {}                                         # Sephora "Bestselling" order (lists are read sorted by bestselling)
    campaigns, sale_items, gift_items, sale_meta, more_lists = [], {}, {}, {}, {}
    for s in snaps:
        age_h = (now - parse_t(s["at"])).total_seconds() / 3600
        pages.append({"kind": s["kind"], "label": s["label"], "url": s["url"], "at": s["at"], "ageH": round(age_h, 1)})
        if s["kind"] == "content" and re.search(SEPHORA_CAMPAIGN, s["label"]):
            c, _ = campaign(s, now); c["stale"] = age_h > 12; campaigns.append(c)
        elif s["kind"] == "list":
            d, lab = s["data"], s["label"]
            best = "BEST_SELLING" in (s.get("url") or "")
            sale_meta[lab] = {"total": d.get("total"), "read": len(d.get("items") or []), "complete": d.get("complete"), "at": s["at"], "stale": age_h > 30, "bestselling": best}
            items = []
            for i, t in enumerate(d.get("items") or []):
                r = tile_item(t, LIST_TOP.get(lab) or "makeup")
                if not r or r["top"] == "fragrance" or mk.is_fragrance(r["title"]):
                    continue
                if best:
                    r["rank"] = i + 1
                    rank[r["pid"]] = min(rank.get(r["pid"], 10**6), i + 1)
                items.append(r)
            if lab.startswith("more-"):
                more_lists[lab] = items
            elif lab.startswith("gifts"):
                for r in items:
                    gift_items.setdefault(r["id"], dict(r, set=True))
            elif lab in LIST_TOP:
                for r in items:
                    sale_items.setdefault(r["id"], r)
    def ok_ship(r):                                   # retailer's own hazardous-material flag = can't fly → removed
        info = pinfo.get(r.get("pid") or "") or {}
        if info.get("hazmat"):
            removed_ship.append({"id": r.get("id"), "title": f'{r.get("brand", "")} {r.get("title", "")}', "url": r.get("url"),
                                 "reason": "Sephora marks it as a hazardous material (restricted from air shipping to Hawaii/Alaska)"})
            return False
        r["ship"] = "unverified"                      # no retailer page confirms air shipping either way
        return True
    def ranked(r):
        r["rank"] = r.get("rank") or rank.get(r.get("pid") or "")
        return r
    # Sephora Cyber + Black Friday: every eligible product from the section's own "shop more" list when it was read
    need_lists = []
    for c in campaigns:
        for sec in c["sections"]:
            if "products" not in sec:
                continue
            if sec.get("more"):
                slug = "more-" + re.sub(r"[^a-z0-9]+", "-", sec["more"].split("sephora.com/")[-1].split("?")[0].lower()).strip("-")[:80]
                sep = "&" if "?" in sec["more"] else "?"
                need_lists.append({"label": slug, "url": sec["more"] + ("" if "sortBy=" in sec["more"] else sep + "sortBy=BEST_SELLING")})
                if slug in more_lists:
                    sec["products"] = [x for x in more_lists[slug] if x.get("compare")]
                    sec["allRead"] = True
            sec["products"] = sorted([price_rule(ranked(dict(p, top=mk.top_of(p["title"]))), pinfo) for p in sec["products"]
                                      if not mk.is_fragrance(p["title"]) and ok_ship(p)], key=lambda p: (p.get("rank") or 10**6))
    # Makeup Sale (13 brands): Sephora USA sale + official US brand stores, makeup only
    sale = [price_rule(r, pinfo) for r in sale_items.values() if r.get("compare")]
    by_name = {}
    for r in sale:
        r["brandKey"] = mk.SEPHORA_NAMES.get(r["brand"].lower())
        if r["brandKey"] and r.get("rank"):
            by_name[(r["brandKey"], norm(r["title"]))] = r["rank"]
    mk_sale = []
    for p in brands.get("products") or []:
        if p.get("set") or mk.is_fragrance(p["title"], p.get("type")) or mk.top_of(f'{p["title"]} {p.get("type", "")}') != "makeup":
            continue
        q = price_rule(dict(p, top="makeup", cat=mk.category(p["title"], p.get("type", ""))), pinfo)
        q["rank"] = by_name.get((p["brand"], norm(p["title"])))     # same product's place on Sephora's bestselling list
        q["ship"] = "unverified"
        mk_sale.append(q)
    for r in sale:
        if r["brandKey"] and not r["set"] and r["top"] == "makeup" and ok_ship(r):
            mk_sale.append(dict(r, brand=r["brandKey"], retailer="Sephora", src="sephora", cat=mk.category(r["title"])))
    mk_sale.sort(key=lambda p: (p.get("rank") or 10**6, p.get("storeRank") or 10**6))
    # Gifts: genuine sets, no fragrance, fee by set size
    gifts, seen = [], set()
    for p in brands.get("products") or []:
        if p.get("set") and not mk.is_fragrance(p["title"], " ".join(p.get("contents") or [])):
            q = price_rule(dict(p), pinfo); q["ship"] = "unverified"; q["rank"] = by_name.get((p["brand"], norm(p["title"]))); gifts.append(q)
    for r in [x for x in sale if x["set"]] + list(gift_items.values()):
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        info = pinfo.get(r.get("pid") or "") or {}
        if mk.is_fragrance(r["title"], " ".join(info.get("contents") or [])) or not ok_ship(r):
            continue
        gifts.append(price_rule(ranked(dict(r, brandKey=mk.SEPHORA_NAMES.get(r["brand"].lower()), retailer="Sephora", src="sephora")), pinfo))
    gifts.sort(key=lambda p: (p.get("rank") or 10**6, p.get("storeRank") or 10**6))
    # Sephora product pages still to read (shipping flag, set contents, palette size), most visible first
    shown = [p for c in campaigns for sec in c["sections"] for p in sec.get("products") or []] + \
            [p for p in mk_sale if p.get("src") == "sephora"] + [g for g in gifts if g.get("src") == "sephora"]
    need = list(dict.fromkeys(p["url"].split("?")[0] for p in shown if p.get("pid") and p["pid"] not in pinfo and p.get("url")))
    hist = {h["label"]: h for h in (old.get("history") or [])}
    for c in campaigns:
        if c["status"] == "ended":
            hist[c["label"]] = {"label": c["label"], "title": c["title"], "url": c["url"], "endedAt": c.get("endsAt") or ts, "lastRead": c["readAt"]}
    removed_ship = list({x["id"]: x for x in removed_ship}.values())
    out = {"meta": {"updatedAt": ts, "sephoraOk": sephora_ok, "pages": sorted(pages, key=lambda p: p["label"]), "sale": sale_meta,
                    "brands": (brands.get("meta") or {}).get("brands", {}), "brandsAt": (brands.get("meta") or {}).get("updatedAt"),
                    "needProducts": need[:80], "needSets": need[:80], "needLists": need_lists, "pinfo": pinfo, "problems": problems,
                    "removedShipping": removed_ship, "add": mk.ADD, "giftAdd": mk.GIFT_ADD, "cats": mk.CATS, "brandNames": mk.BRANDS, "top": TOP},
           "campaigns": campaigns, "offers": [], "sale": [], "makeup": mk_sale, "gifts": gifts,
           "history": sorted(hist.values(), key=lambda h: h.get("endedAt") or "", reverse=True)[:60]}
    if not sephora_ok and old.get("meta"):
        # the snapshot database couldn't be read: keep every Sephora part exactly as last confirmed (never wipe it)
        out["campaigns"] = old.get("campaigns", [])
        out["makeup"] += [p for p in old.get("makeup", []) if p.get("src") == "sephora"]
        out["gifts"] += [p for p in old.get("gifts", []) if p.get("src") == "sephora"]
        for k in ("pages", "sale", "needProducts", "needSets", "needLists", "removedShipping"):
            out["meta"][k] = (old.get("meta") or {}).get(k, out["meta"].get(k))
        out["meta"]["sephoraStaleSince"] = (old.get("meta") or {}).get("sephoraStaleSince") or ts
    for lst in [out["makeup"], out["gifts"]] + [sec.get("products") or [] for c in out["campaigns"] for sec in c["sections"]]:
        for p in lst:                                 # product-only photo chosen in the photo check
            if OVR.get("images", {}).get(p.get("id")):
                p["image"] = OVR["images"][p["id"]]
    json.dump(out, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"makeup.json: campaigns {len(campaigns)}, makeup sale {len(mk_sale)}, gifts {len(gifts)} (priced {sum(1 for g in gifts if g.get('add'))}), "
          f"product pages to read {len(need)}, removed for shipping {len(removed_ship)}, more-lists {len(need_lists)}")


if __name__ == "__main__":
    main()
