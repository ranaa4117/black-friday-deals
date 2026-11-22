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
from html.parser import HTMLParser

STORE = "https://eu.self-portrait.com/es-es"
CATEGORIES = [("midi", "sale-midi-dresses"), ("maxi", "sale-maxi-dresses"), ("bags", "sale-handbags")]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "self-portrait", "data.json")
UA = "Mozilla/5.0 (personal sale tracker; github.com/ranaa4117/black-friday-deals)"
SG_LIMIT = int(os.environ.get("SG_LIMIT", "60"))       # size guides read per run
SG_MAX_AGE = 3 * 24 * 3600                              # re-read a guide every 3 days
DEBUG = os.environ.get("SG_DEBUG") == "1"


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


def normalize(p, cat):
    variants = p.get("variants") or []
    prices = [float(v["price"]) for v in variants if v.get("price")]
    comps = [float(v.get("compare_at_price") or 0) for v in variants]
    if not prices or not keep(cat, p):
        return None
    price, compare = min(prices), max(comps)
    if compare <= price:
        return None  # not discounted
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


def read_guides(products, prev_by_handle):
    budget, done = SG_LIMIT, 0
    for p in products:
        old = prev_by_handle.get(p["handle"], {})
        if old.get("guide") is not None and age_s(old.get("guideAt", "")) < SG_MAX_AGE:
            p["guide"], p["guideAt"] = old["guide"], old["guideAt"]
            continue
        if budget <= 0:
            if "guide" in old:
                p["guide"], p["guideAt"] = old["guide"], old.get("guideAt", "")
            continue
        budget -= 1
        try:
            page = fetch(f"{STORE}/products/{p['handle']}", accept="text/html")
            p["guide"], p["guideAt"] = parse_guide(page, p["cat"]), now_iso()
            done += 1
            if DEBUG and done == 1 and not p["guide"]:
                i = page.find("<table")
                print("no tables parsed; first table html:", page[i:i + 1500] if i >= 0 else "(no <table> in page)")
        except Exception as e:  # noqa: BLE001
            print("guide failed", p["handle"], e)
            if "guide" in old:
                p["guide"], p["guideAt"] = old["guide"], old.get("guideAt", "")
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
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"meta": {}, "products": [], "removed": []}


def size_msgs(old, new):
    o = {x["s"]: x["a"] for x in old}
    return [f"{x['s']} {'back in stock' if x['a'] else 'sold out'}" for x in new if x["s"] in o and o[x["s"]] != x["a"]]


def write(data):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


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

    old = {p["handle"]: dict(p, cat=p.get("cat", "midi")) for p in prev.get("products", [])}
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
            ok_cats.add(cat)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{cat}: {e}")
        time.sleep(1.5)

    if not ok_cats:
        meta["lastError"] = f"{ts}: could not read the store ({'; '.join(errors)}). Showing data from the last successful check."
        prev["meta"] = meta
        write(prev)
        print(meta["lastError"])
        return

    # categories that failed this run keep their previous products
    for h, p in old.items():
        if p["cat"] not in ok_cats and h not in fresh:
            fresh[h] = p

    baseline = {c for c, _ in CATEGORIES if not any(p["cat"] == c for p in old.values())}
    added, changed = [], []
    for h, n in fresh.items():
        o = old.get(h)
        if n["cat"] in ok_cats:
            n["verifiedAt"] = ts
        if not o:
            if n["cat"] in baseline:  # first time this category is tracked: starting stock, not "new"
                base = meta.get("initialImport", ts)
                n.update(firstSeen=base, lastChanged=ts, changes=[])
            else:
                n.update(firstSeen=ts, lastChanged=ts, changes=["Newly discovered on sale"])
                added.append(h)
            continue
        n["firstSeen"] = o.get("firstSeen", ts)
        msgs = []
        if o.get("price") != n["price"]:
            msgs.append(f"Sale price €{o.get('price', 0):g} → €{n['price']:g}")
        if o.get("compare") != n["compare"]:
            msgs.append(f"Original price €{o.get('compare', 0):g} → €{n['compare']:g}")
        if o.get("image") != n["image"]:
            msgs.append("Image updated")
        msgs += size_msgs(o.get("sizes", []), n["sizes"])
        if msgs:
            n.update(lastChanged=ts, changes=msgs)
            changed.append(h)
        else:
            n.update(lastChanged=o.get("lastChanged", ts), changes=o.get("changes", []))

    gone = [dict(p, removedAt=ts) for h, p in old.items() if h not in fresh and p["cat"] in ok_cats]
    removed = (gone + [r for r in prev.get("removed", []) if r["handle"] not in fresh])[:120]
    for r in removed:
        r.pop("guide", None)

    products = sorted(fresh.values(), key=lambda p: p.get("firstSeen", ""), reverse=True)
    guides = read_guides(products, old)

    counts = {c: sum(1 for p in products if p["cat"] == c) for c, _ in CATEGORIES}
    meta.update(lastSuccess=ts, lastError=("; ".join(errors) and f"{ts}: partial check — {'; '.join(errors)}"),
                count=len(products), counts=counts, storeCounts=raw_counts,
                collections={c: f"{STORE}/collections/{h}" for c, h in CATEGORIES})
    meta.setdefault("initialImport", ts)
    log = meta.get("log", [])
    log.insert(0, {"at": ts, "added": len(added), "removed": len(gone), "changed": len(changed), "guides": guides})
    meta["log"] = log[:40]
    write({"meta": meta, "products": products, "removed": removed})
    print(f"ok: {counts} (store feed {raw_counts}), +{len(added)} new, -{len(gone)} removed, "
          f"{len(changed)} changed, {guides} size guides read, rate {meta.get('rate', {}).get('value')}, errors {errors}")


if __name__ == "__main__":
    main()
