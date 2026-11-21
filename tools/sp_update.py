#!/usr/bin/env python3
"""Self-Portrait Spain — sale midi dress monitor.

Reads the public product feed of the official Spain store
(eu.self-portrait.com/es-es, collection "sale-midi-dresses"), keeps only
discounted midi dresses, fetches a live EUR->SAR rate, and merges the result
into self-portrait/data.json while keeping history (first seen, last changed,
what changed, items that left the sale).

Usage:
  python3 tools/sp_update.py              # live check (used by the GitHub Action)
  python3 tools/sp_update.py --seed FILE  # build data.json from a captured snapshot
Standard library only.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request

STORE = "https://eu.self-portrait.com/es-es"
COLLECTION = "sale-midi-dresses"
CDN = "https://cdn.shopify.com/s/files/1/0557/7601/8485/files/"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "self-portrait", "data.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal sale tracker; github.com/ranaa4117/black-friday-deals)",
    "Accept": "application/json",
}
KNIT = ["XS", "S", "M", "L", "XL"]


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def is_midi(title):
    t = title.lower()
    return "midi" in t and "mini" not in t and "maxi" not in t


def normalize(p):
    variants = p.get("variants") or []
    if not variants:
        return None
    prices = [float(v["price"]) for v in variants if v.get("price")]
    comps = [float(v.get("compare_at_price") or 0) for v in variants]
    if not prices:
        return None
    price, compare = min(prices), max(comps)
    if compare <= price or not is_midi(p.get("title", "")):
        return None  # full price, or not a midi dress
    imgs = p.get("images") or []
    return {
        "handle": p["handle"],
        "title": p["title"].strip(),
        "image": imgs[0]["src"] if imgs else "",
        "price": round(price, 2),
        "compare": round(compare, 2),
        "sizes": [{"s": (v.get("option1") or v.get("title") or "").strip(), "a": bool(v.get("available"))} for v in variants],
        "publishedAt": (p.get("published_at") or "")[:10],
    }


def fetch_store():
    items, page = [], 1
    while page <= 30:
        data = get_json(f"{STORE}/collections/{COLLECTION}/products.json?limit=250&page={page}")
        batch = data.get("products") or []
        items += batch
        if len(batch) < 250:
            break
        page += 1
        time.sleep(2)
    out = {}
    for p in items:
        n = normalize(p)
        if n:
            out[n["handle"]] = n
    return list(out.values()), len(items)


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


def size_diff(old, new):
    o = {x["s"]: x["a"] for x in old}
    msgs = []
    for x in new:
        if x["s"] in o and o[x["s"]] != x["a"]:
            msgs.append(f"{x['s']} {'back in stock' if x['a'] else 'sold out'}")
    return msgs


def merge(prev, fresh, ts):
    old = {p["handle"]: p for p in prev.get("products", [])}
    added, changed = [], []
    for n in fresh:
        o = old.get(n["handle"])
        if not o:
            n.update(firstSeen=ts, lastChanged=ts, changes=["Newly discovered on sale"])
            added.append(n["handle"])
            continue
        n["firstSeen"] = o.get("firstSeen", ts)
        msgs = []
        if o["price"] != n["price"]:
            msgs.append(f"Sale price €{o['price']:g} → €{n['price']:g}")
        if o["compare"] != n["compare"]:
            msgs.append(f"Original price €{o['compare']:g} → €{n['compare']:g}")
        if o.get("image") != n["image"]:
            msgs.append("Image updated")
        msgs += size_diff(o.get("sizes", []), n["sizes"])
        if msgs:
            n.update(lastChanged=ts, changes=msgs)
            changed.append(n["handle"])
        else:
            n.update(lastChanged=o.get("lastChanged", ts), changes=o.get("changes", []))
    fresh_handles = {n["handle"] for n in fresh}
    removed = [dict(p, removedAt=ts) for h, p in old.items() if h not in fresh_handles]
    keep_removed = [r for r in prev.get("removed", []) if r["handle"] not in fresh_handles]
    all_removed = (removed + keep_removed)[:80]
    return added, changed, [r["handle"] for r in removed], all_removed


def write(data):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def run_live():
    prev = load_prev()
    meta = prev.get("meta", {})
    ts = now_iso()
    meta["lastCheck"] = ts
    rate = fetch_rate()
    if rate:
        meta["rate"] = rate
    try:
        fresh, raw = fetch_store()
        if raw == 0:
            raise RuntimeError("store feed returned no products")
    except Exception as e:  # noqa: BLE001
        meta["lastError"] = f"{ts}: could not read the store ({e}). Showing data from the last successful check."
        prev["meta"] = meta
        write(prev)
        print(meta["lastError"])
        return
    added, changed, gone, removed = merge(prev, fresh, ts)
    meta.update(lastSuccess=ts, lastError="", count=len(fresh), store=f"{STORE}/collections/{COLLECTION}")
    log = meta.get("log", [])
    log.insert(0, {"at": ts, "added": len(added), "removed": len(gone), "changed": len(changed)})
    meta["log"] = log[:30]
    fresh.sort(key=lambda p: p["firstSeen"], reverse=True)
    write({"meta": meta, "products": fresh, "removed": removed})
    print(f"ok: {len(fresh)} on sale, +{len(added)} new, -{len(gone)} removed, {len(changed)} changed, rate {meta.get('rate')}")


def run_seed(path, captured_at, rate_value):
    fresh = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            handle, title, pub, img, price, comp, sz = line.split("|")
            if sz[0] == "F":
                sizes = [{"s": f"FR {32 + 2 * i}", "a": c == "1"} for i, c in enumerate(sz[1:])]
            else:
                sizes = [{"s": KNIT[i], "a": c == "1"} for i, c in enumerate(sz[1:])]
            fresh.append({"handle": handle, "title": title, "image": CDN + img, "price": float(price),
                          "compare": float(comp), "sizes": sizes, "publishedAt": pub,
                          "firstSeen": captured_at, "lastChanged": captured_at, "changes": []})
    meta = {"lastCheck": captured_at, "lastSuccess": captured_at, "lastError": "", "count": len(fresh),
            "initialImport": captured_at, "store": f"{STORE}/collections/{COLLECTION}",
            "rate": {"value": rate_value, "source": "EUR→USD 1.0968 (21 Nov 2026) × 3.75 SAR/USD peg",
                     "asOf": "2026-11-21"},
            "log": [{"at": captured_at, "added": len(fresh), "removed": 0, "changed": 0}]}
    write({"meta": meta, "products": fresh, "removed": []})
    print(f"seeded {len(fresh)} products")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--seed":
        run_seed(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else now_iso(), 4.113)
    else:
        run_live()
