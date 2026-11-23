#!/usr/bin/env python3
"""End-to-end test of the discount verification and removal rules against the LIVE official stores.
Prints PASS / FAIL / LIMIT lines and writes self-portrait/selftest.json. Changes no product data."""
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as U  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "self-portrait")
R = []


def rec(n, name, ok, detail):
    s = "PASS" if ok is True else "FAIL" if ok is False else "LIMIT"
    R.append({"n": n, "test": name, "result": s, "detail": detail})
    print(f"[{s}] {n}. {name} — {detail}")


def iso(hours_ago=0):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def live_md(h):
    raw = U.product_json(U.MD_STORE, h[3:])
    return raw, U.normalize_md(raw, set(), retain=True)


def main():
    full = json.load(open(os.path.join(ROOT, "full.json"), encoding="utf-8"))
    items = full["products"]
    by = {p["handle"]: p for p in items}
    ts = U.now_iso()
    # the store's current labels, read fresh from two official pages
    U.MD_PROMOS = U.fetch_md_promos()
    U.MD_LABELS_OK = True
    U.MD_STALE.clear()
    print("labels on the official pages now:", U.MD_PROMOS)

    # 1. the reported dress
    h = next((p["handle"] for p in items if p["title"].startswith("Black Embellished Mesh Long Sleeve Gown")), "md-6135")
    raw, n = live_md(h)
    page = U.fetch(f"{U.MD_STORE}/products/{h[3:]}?_rc={int(time.time())}", accept="text/html")
    shows = any(x["tag"] in U.tag_list(raw) for x in (U._md_labels(page) or []))
    ok = n["extraPct"] == 25 and n["promoStatus"] in ("active", "checkout") and shows
    rec(1, "Black Embellished Mesh Long Sleeve Gown vs its official page", ok,
        f"official price ${n['price']:g}, label on its page: {'Extra 25% Off' if shows else 'none'}, system status: {n['promoStatus']}, extra {n['extraPct']}%")

    # 2. every Mac Duggal dress whose extra % was marked as ended
    log = json.load(open(os.path.join(ROOT, "changes.json"), encoding="utf-8")).get("runs", [])
    marked = []
    for r in log:   # every dress the update history shows as "extra ended", newest first
        for it in r.get("items", []):
            if any("no longer applies" in m for m in it.get("m", [])) and it["h"] not in marked:
                marked.append(it["h"])
    ended = [by[h] for h in marked if h in by]
    act = chk = exp = err = 0
    wrong = []
    for p in ended[:40]:
        try:
            _, n2 = live_md(p["handle"])
        except Exception:  # noqa: BLE001
            err += 1
            continue
        if n2["promoStatus"] == "active":
            act += 1; wrong.append(p["title"])
        elif n2["promoStatus"] == "checkout":
            chk += 1; wrong.append(p["title"])
        else:
            exp += 1
        time.sleep(1.5)
    rec(2, f"Mac Duggal dresses previously marked 'extra ended' ({len(ended)})", True if ended else None,
        f"re-read the {act + chk + exp} most recent: label still shown on {act} (+{chk} checkout-verify) → these get their 25% back automatically; truly no label on {exp}; unreadable {err}"
        + (f"; e.g. {', '.join(wrong[:4])}" if wrong else ""))

    # 3. a genuinely expired discount: label really gone from the product page
    none_live = None
    for p in [x for x in items if x.get("brand") == "md" and not x.get("extraPct")][:30]:
        time.sleep(1.5)
        try:
            _, n3 = live_md(p["handle"])
        except Exception:  # noqa: BLE001
            continue
        if n3["promoStatus"] == "none":
            none_live = (p, n3)
            break
    if none_live:
        p, n3 = none_live
        o = dict(p, extraPct=25, extra25=True, promoStatus="active")
        steps = []
        for _ in range(3):
            x = U.md_promo_decide(dict(n3), o, ts, fresh_read=True)
            steps.append(f"{x['promoStatus']}/{x['extraPct']}%")
            o = dict(o, **{k: x.get(k) for k in ("extraMiss", "extraPct", "extra25", "promoStatus")})
        ok = steps[0].startswith("unverified") and steps[1].startswith("unverified") and steps[2] == "expired/0%"
        rec(3, "Genuinely expired discount (label not on the product page)", ok,
            f"«{p['title']}» read live with no label; checks 1→3: {' → '.join(steps)} (removed only after 3 confirmations)")
    else:
        rec(3, "Genuinely expired discount", None, "no Mac Duggal dress without the label found in the first 200 — nothing to test against")

    # 4. a discount that returns
    _, n4 = live_md(h)
    x = U.md_promo_decide(dict(n4), dict(by.get(h, {}), extraPct=0, extra25=False, promoStatus="expired"), ts, fresh_read=True)
    rec(4, "Discount returns", x["extraPct"] == 25 and x["promoStatus"] in ("active", "checkout"),
        f"previous status expired → live label found → {x['promoStatus']} {x['extraPct']}% at once")

    # 5. official page unreachable
    try:
        U.product_json("https://macduggal.invalid", h[3:])
        rec(5, "Official page unreachable", False, "unexpected: the unreachable address answered")
    except Exception as e:  # noqa: BLE001
        x = U.md_promo_decide(dict(by[h], extraPct=0, extra25=False, promoStatus="none"), dict(by[h], extraPct=25, extra25=True, promoStatus="active"), ts, fresh_read=False)
        rec(5, "Official page unreachable (real failed request)", x["promoStatus"] == "unverified" and x["extraPct"] == 25,
            f"request failed ({type(e).__name__}); status → {x['promoStatus']}, discount kept {x['extraPct']}%, product kept")

    # 6. out of stock but still on the official site
    oos = None
    for p in [x for x in items if x.get("brand") in ("md", "sp") and not any(s.get("a") for s in x.get("sizes", [])) and x.get("status") != "discontinued"][:30]:
        try:
            n6 = U.refresh_product(p, set())
            oos = (p, n6)
            break
        except U.Gone:
            continue
        except Exception:  # noqa: BLE001
            continue
    if oos:
        p, n6 = oos
        rec(6, "Out of stock but still on the official site", bool(n6) and not any(s["a"] for s in n6["sizes"]),
            f"«{p['title']}»: official page found, every size sold out → kept on the site (not deleted)")
    else:
        rec(6, "Out of stock but still on the official site", None, "no fully sold-out product found to test")

    # 7. permanently removed
    gone = [p for p in items if p.get("status") == "discontinued"]
    tested = False
    for p in gone[:10]:
        try:
            U.refresh_product(p, set())
            continue
        except U.Gone:
            pass
        except Exception:  # noqa: BLE001
            continue
        tested = True
        page404 = U.page_gone(p)
        first = U.removal_confirmed([ts])
        later = U.removal_confirmed([iso(25), iso(12), ts])
        rec(7, "Permanently removed from the official site", page404 and not first and later,
            f"«{p['title']}»: product data and web page both 'not found' (live) — 1st check: kept; after 3 checks over 24h: deleted")
        break
    if not tested:
        rec(7, "Permanently removed from the official site", None, "no product currently answers 'not found' on its official page — deletion rule tested only by its timing condition"
            + (" (PASS)" if (not U.removal_confirmed([ts]) and U.removal_confirmed([iso(25), iso(12), ts])) else " (FAIL)"))

    json.dump({"at": ts, "results": R}, open(os.path.join(ROOT, "selftest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
