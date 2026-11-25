"""Automatic brand health check (runs inside GitHub Actions right after the updater, once an hour).

* Re-reads products from the official stores and compares them with what the site shows
  (every product that already has an open problem first, then a sample).
* Checks every product has its own direct official product link.
* Checks the site is up, data files are fresh, and products the updater could not verify.
* Keeps self-portrait/fixes.json — the Admin page's "Problems & Fixes" list — up to date:
  new problems are added, problems are marked resolved ONLY after the fix is verified,
  resolved problems are kept, and a problem that comes back is recorded as a new occurrence.

It never changes product data and never deletes anything.
"""
import datetime as dt
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import sp_update as U  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "self-portrait")
SAMPLE = int(os.environ.get("AUDIT_SAMPLE", "6"))
NAMES = {"sp": "Self-Portrait", "md": "Mac Duggal", "ef": "Elisabetta Franchi", "rl": "Lauren Ralph Lauren"}
MACYS = {"rl", "jc", "bj", "kl", "ck", "inc", "sm"}


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(name, default=None):
    try:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def save(name, obj):
    with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def bname(p):
    return NAMES.get(p.get("brand", "sp"), "Macy's")


# ---------- direct official product links ----------
def official_url(p):
    b = p.get("brand", "sp")
    return p.get("url") or ("https://eu.self-portrait.com/es-es/products/" + p["handle"] if b == "sp" else "")


def url_problem(p):
    """None when the product has its own direct official product page link, else a short reason."""
    if p.get("manual"):
        return None
    u, h, b = official_url(p), p["handle"], p.get("brand", "sp")
    if not u:
        return "لا يوجد رابط مباشر للقطعة"
    if b == "sp":
        ok = u == "https://eu.self-portrait.com/es-es/products/" + h
    elif b == "md":
        ok = u == "https://macduggal.com/products/" + h[3:]
    elif b == "ef":
        code = h[3:].upper()
        ok = u.startswith(U.EF_SITE + "/") and u.endswith(".html") and code in u.upper()
    elif b in MACYS:
        pid = h.split("-", 1)[-1]
        ok = u.startswith("https://www.macys.com/shop/product/") and re.search(r"[?&]ID=" + re.escape(pid) + r"(&|$)", u) is not None
    else:
        ok = u.startswith("https://")
    return None if ok else "الرابط لا يطابق صفحة القطعة نفسها"


# ---------- official-store comparison ----------
def read_live(p):
    """Returns (live dict or None, error text or None). Raises U.Gone when the store no longer has it."""
    b, h = p.get("brand", "sp"), p["handle"]
    try:
        if b == "sp":
            raw = U.product_json(U.STORE, h)
            return (raw and U.normalize(raw, p.get("cat", "midi"), retain=True)), None
        if b == "md":
            raw = U.product_json(U.MD_STORE, h[3:])
            return (raw and U.normalize_md(raw, set(), retain=True)), None
        if b == "ef":
            d = U.ef_product(p["url"].replace(U.EF_SITE, ""))
            if not d.get("price"):
                return None, None
            return U.ef_record(d, h[3:]), None
    except U.urllib.error.HTTPError as e:
        if e.code in (404, 410):
            raise U.Gone() from e
        return None, str(e)
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    finally:
        time.sleep(0.8)
    return None, None


def any_stock(sizes):
    return any(x.get("a") for x in sizes or [])


def compare(p, live):
    """What differs, in easy Arabic (empty when the site matches the official store)."""
    out = []
    if abs((p.get("price") or 0) - (live.get("price") or 0)) > 0.011:
        out.append("السعر")
    if abs((p.get("compare") or 0) - (live.get("compare") or 0)) > 0.011:
        out.append("السعر الأصلي")
    if p.get("brand") == "md" and (p.get("extraPct") or 0) != (live.get("extraPct") or 0):
        out.append("الخصم الإضافي")
    if any_stock(p.get("sizes")) != any_stock(live.get("sizes")):
        out.append("التوفر")
    return out


# ---------- Problems & Fixes list ----------
class Fixes:
    def __init__(self):
        self.items = (load("fixes.json") or {}).get("fixes", [])

    def latest(self, key):
        return next((x for x in self.items if x.get("key") == key), None)

    @staticmethod
    def meta_for(key):
        """Brand, priority and what was checked, for the Admin's problem details."""
        kind, _, rest = key.partition(":")
        brand = {"md": "Mac Duggal", "ef": "Elisabetta Franchi", "vs": "Victoria's Secret", "rl": "Macy's", "mc": "Macy's"}.get(rest.split("-")[0], "Self-Portrait")
        if kind in ("efprice", "ef-verify"):
            brand = "Elisabetta Franchi"
        if kind == "store":
            brand = NAMES.get(rest, rest)
        if kind == "stale":
            brand = "Macy's" if rest in ("winter.json", "shoes.json") else "Self-Portrait / Mac Duggal / Elisabetta Franchi"
        if kind in ("site", "updater-error"):
            brand = "الموقع" if kind == "site" else "النظام"
        prio = {"site": "critical", "store": "high", "updater-error": "high", "stale": "high" if rest == "full.json" else "medium",
                "data": "medium", "efprice": "high", "ef-verify": "medium", "verify": "medium", "url": "low"}.get(kind, "medium")
        how = {"data": "الفحص الآلي كل ساعة قرأ صفحة القطعة في المتجر الأصلي وقارنها بالموقع.",
               "efprice": "الفحص الآلي فتح صفحة Elisabetta Franchi المعتمدة (الصفحة ٢) في متصفح حقيقي وقارن السعر الأصلي والخصم والسعر بعد الخصم.",
               "ef-verify": "الفحص الآلي حاول فتح صفحة Elisabetta Franchi المعتمدة في متصفح حقيقي.",
               "verify": "التحديث حاول قراءة صفحة القطعة في المتجر الأصلي ولم ينجح.",
               "store": "الفحص الآلي حاول فتح المتجر الأصلي.", "site": "الفحص الآلي حاول فتح الموقع.",
               "stale": "الفحص الآلي راجع وقت آخر تحديث للملف على GitHub.", "url": "الفحص الآلي راجع رابط القطعة المحفوظ.",
               "updater-error": "مراجعة نتيجة آخر تحديث."}.get(kind, "")
        return {"brand": brand, "priority": prio, "investigation": how}

    def problem(self, key, text, status, fix):
        """Record that a problem exists now (status 'progress' or 'open'). A problem that comes back after
        being resolved is a new, linked occurrence (same key, n + 1)."""
        cur = self.latest(key)
        ts = now()
        if cur and cur.get("status") != "resolved":
            cur.update(problem=text, status=status, fix=fix, updated=ts)
            if not cur.get("desc"):
                cur["desc"] = text
            for k, v in self.meta_for(key).items():   # fill any missing detail field
                cur.setdefault(k, v)
            return
        n = (cur.get("n", 1) + 1) if cur else 1
        self.items.insert(0, dict({"key": key, "at": ts, "updated": ts, "status": status, "problem": text, "fix": fix, "n": n, "src": "auto",
                                   "desc": text, "cause": "لم يُحدَّد السبب بعد.", "verification": "", "related": []}, **self.meta_for(key)))

    def resolve(self, key, fix):
        """Only called after the fix has been verified."""
        cur = self.latest(key)
        if cur and cur.get("status") != "resolved":
            cur.update(status="resolved", fix=fix, updated=now(), verification="الفحص الآلي في " + now()[:16].replace("T", " ") + " UTC أعاد التحقق ووجد المشكلة غير موجودة.")

    def open_keys(self, prefix):
        return [x["key"] for x in self.items if x.get("key", "").startswith(prefix) and x.get("status") != "resolved"]

    def write(self):
        unresolved = sum(1 for x in self.items if x.get("status") != "resolved")
        room, out = max(0, 200 - unresolved), []
        for x in self.items:           # keep every unresolved problem and the newest resolved ones
            if x.get("status") != "resolved":
                out.append(x)
            elif room > 0:
                out.append(x)
                room -= 1
        out.sort(key=lambda x: x.get("updated") or x.get("at", ""), reverse=True)
        save("fixes.json", {"fixes": out})


def last_commit_age_h(path):
    """Hours since the file last changed on GitHub (the checkout is shallow, so ask GitHub)."""
    try:
        repo = os.environ.get("GITHUB_REPOSITORY", "ranaa4117/black-friday-deals")
        req = U.urllib.request.Request(f"https://api.github.com/repos/{repo}/commits?path={path}&per_page=1",
                                       headers={"User-Agent": U.UA, "Accept": "application/vnd.github+json",
                                                **({"Authorization": "Bearer " + os.environ["GH_TOKEN"]} if os.environ.get("GH_TOKEN") else {})})
        with U.urllib.request.urlopen(req, timeout=30) as r:
            t = json.load(r)[0]["commit"]["committer"]["date"]
        return U.age_s(t) / 3600
    except Exception as e:  # noqa: BLE001
        print("audit: could not read file history", path, e)
        return None


def main():
    audit = load("audit.json", {"audits": []})
    last_auto = next((a for a in audit.get("audits", []) if a.get("auto")), None)
    if last_auto and U.age_s(last_auto["at"]) < 55 * 60 and os.environ.get("AUDIT_FORCE") != "1":
        print("brand audit: ran less than an hour ago — skipped")
        return

    full = load("full.json")
    meta = full.get("meta", {})
    items = full.get("products", [])
    macys = (load("winter.json") or {}).get("products", []) + (load("shoes.json") or {}).get("products", [])
    by_h = {p["handle"]: p for p in items + macys}
    promos = meta.get("mdPromos") or ([meta["mdPromo"]] if meta.get("mdPromo") else [])
    U.MD_PROMOS = [{k: v for k, v in x.items() if k != "miss"} for x in promos]
    U.MD_PROMO = U.MD_PROMOS[0] if U.MD_PROMOS else None

    F = Fixes()
    found = checked = 0

    # 1) products: every open product problem first (to verify its fix), then a sample per brand
    todo = [k.split(":", 1)[1] for k in F.open_keys("data:")]
    for code in ("sp", "md", "ef"):
        mine = [p for p in items if p.get("brand", "sp") == code]
        risky = [p["handle"] for p in mine if p.get("listed") is False and p.get("status") != "discontinued"]
        random.shuffle(risky)
        rest = [p["handle"] for p in mine]
        random.shuffle(rest)
        todo += (risky[: SAMPLE // 2] + rest)[:SAMPLE]
    store_ok, store_fail = set(), set()
    for h in dict.fromkeys(todo):
        p = by_h.get(h)
        key = "data:" + h
        if not p or p.get("brand", "sp") not in ("sp", "md", "ef"):
            continue
        title = f"«{p.get('title', h)}» ({bname(p)})"
        try:
            live, err = read_live(p)
        except U.Gone:
            checked += 1
            if U.page_state(p) == "exists":   # page still there (sold out / hidden from the data feed): not removed
                F.resolve(key, "صفحة القطعة الأصلية موجودة (نفدت أو مخفية)، فبقيت في الموقع كـ«غير متوفرة». تم التحقق.")
                continue
            if p.get("status") == "discontinued":
                F.resolve(key, "المتجر الأصلي لم يعد يبيعها، وتظهر «غير متوفرة» في الموقع ولم تُحذف. تم التحقق.")
            else:
                found += 1
                F.problem(key, f"{title}: لم تعد في المتجر الأصلي", "progress", "ستظهر «غير متوفرة» في التحديث القادم بدون حذفها.")
            continue
        b = p.get("brand", "sp")
        if err:
            store_fail.add(b)
            continue
        store_ok.add(b)
        checked += 1
        if not live:
            continue
        if p.get("status") == "discontinued":
            found += 1
            F.problem(key, f"{title}: معلَّمة «غير متوفرة» لكنها موجودة في المتجر الأصلي", "progress", "سيُعاد فحصها وتحديثها من المتجر الأصلي.")
            continue
        d = compare(p, live)
        cur = F.latest(key)
        if d:
            found += 1
            late = bool(cur) and cur.get("status") != "resolved" and U.age_s(cur.get("at", "")) > 2 * 3600
            F.problem(key, f"{title}: {'، '.join(d)} لا يطابق المتجر الأصلي", "open" if late else "progress",
                      "لم يُصحَّح بعد رغم إعادة المحاولة — يحتاج مراجعة." if late else "سيُصحَّح تلقائياً من المتجر الأصلي في التحديث القادم.")
        elif cur:
            F.resolve(key, "تم تصحيحها من المتجر الأصلي، وتم التحقق أنها مطابقة الآن.")

    for b in ("sp", "md", "ef"):
        if b in store_fail and b not in store_ok:
            found += 1
            F.problem("store:" + b, f"{NAMES[b]}: تعذّر فتح المتجر الأصلي", "progress", "آخر الأسعار المؤكدة باقية كما هي. ستُعاد المحاولة كل ساعة.")
        elif b in store_ok:
            F.resolve("store:" + b, "عاد المتجر الأصلي يفتح وتم التحقق من المنتجات.")

    # 1b) Elisabetta Franchi: every product against the prices a shopper sees on the authorized page (real browser)
    ev = load("ef_verify.json") or {}
    efs = [p for p in items if p.get("brand") == "ef" and p.get("status") != "discontinued"]
    if ev.get("items") and U.age_s(ev.get("at", "")) < 3 * 3600:
        F.resolve("ef-verify", "صار التحقق من أسعار Elisabetta Franchi يعمل، وتم التحقق.")
        for p in efs:
            key = "efprice:" + p["handle"]
            v = ev["items"].get(p["handle"])
            title = f"«{p.get('title', p['handle'])}» (Elisabetta Franchi)"
            if not v:
                found += 1
                F.problem(key, f"{title}: لم تظهر في صفحة المتجر المعتمدة (الصفحة ٢) عند التحقق", "progress",
                          "تبقى بآخر سعر مؤكد وتُعلَّم «غير مؤكد»، ويُعاد التحقق كل ساعة.")
                continue
            same = abs(v["orig"] - (p.get("compare") or 0)) < 0.011 and v["pct"] == (p.get("discPct") or 0) and abs(v["sale"] - p["price"]) < 0.011
            if same:
                F.resolve(key, "السعر الأصلي والخصم والسعر بعد الخصم مطابقة لصفحة المتجر. تم التحقق.")
            else:
                found += 1
                F.problem(key, f"{title}: السعر في الموقع لا يطابق صفحة المتجر ({v['shown']})", "progress",
                          "سيُصحَّح من بيانات المتجر في التحديث القادم ثم يُعاد التحقق.")
    elif efs:
        found += 1
        F.problem("ef-verify", "تعذّر فتح صفحة Elisabetta Franchi المعتمدة في المتصفح للتحقق من الأسعار", "progress",
                  "الأسعار باقية من بيانات المتجر الرسمية، ويُعاد التحقق كل ساعة.")

    # 2) products the updater could not verify (store page unreachable) — kept at their last verified price
    vf = meta.get("verifyFail") or {}
    for h, v in vf.items():
        if U.age_s(v.get("since", "")) > 3600:
            found += 1
            F.problem("verify:" + h, f"«{v.get('t', h)}» ({NAMES.get(v.get('b'), '')}): تعذّر التحقق من سعرها في المتجر الأصلي",
                      "progress", "باقية على آخر سعر مؤكد ولم تُحذف. ستُعاد المحاولة تلقائياً.")
    for key in F.open_keys("verify:"):
        if key.split(":", 1)[1] not in vf:
            F.resolve(key, "تم التحقق من سعرها في المتجر الأصلي.")

    # 3) every product has its own direct official product link
    bad_links = 0
    for p in items + macys:
        why = url_problem(p)
        if why:
            bad_links += 1
            found += 1
            F.problem("url:" + p["handle"], f"«{p.get('title', p['handle'])}» ({bname(p)}): {why}", "open",
                      "لم يُخترع أي رابط. يحتاج رابط صفحة القطعة نفسها من المتجر الأصلي.")
        else:
            F.resolve("url:" + p["handle"], "صار للقطعة رابط مباشر صحيح لصفحتها في المتجر الأصلي.")

    # 4) the site is up
    for name, url, must in (("الموقع", "https://raghad-outlet.pages.dev/", "Raghad"),
                            ("بيانات المنتجات", "https://ranaa4117.github.io/black-friday-deals/self-portrait/data.json", '"products"')):
        try:
            body = U.fetch(url + ("?t=%d" % time.time()), accept="text/html,application/json")
            if must not in body:
                raise RuntimeError("unexpected content")
            F.resolve("site:" + url, "عاد يعمل وتم التحقق.")
        except Exception:  # noqa: BLE001
            found += 1
            F.problem("site:" + url, f"{name}: لا يفتح الآن", "progress", "يُعاد الفحص كل ساعة.")

    # 5) each data source is fresh
    for f, name, limit in (("full.json", "تحديث Self-Portrait وMac Duggal وElisabetta Franchi", 1.5),
                           ("winter.json", "أسعار Macy's (التخفيضات الشتوية)", 3), ("shoes.json", "أسعار Macy's (الجزم)", 3)):
        age = last_commit_age_h("self-portrait/" + f)
        if age is None:
            continue
        if age > limit:
            found += 1
            mac = f != "full.json"
            F.problem("stale:" + f, f"{name}: لم تتحدّث منذ {age:.0f} ساعة", "open" if mac else "progress",
                      "تبقى آخر الأسعار المؤكدة. الفحص الدوري يحدّثها كلما سُمح له بفتح صفحات Macy's." if mac
                      else "التحديث التلقائي يُعاد تشغيله كل ١٥ دقيقة.")
        else:
            F.resolve("stale:" + f, "عادت تتحدّث بانتظام، وتم التحقق.")

    if meta.get("lastError"):
        found += 1
        F.problem("updater-error", "آخر تحديث لم يقرأ كل المتاجر", "progress", "ما لم يُقرأ بقي على آخر بيانات مؤكدة، ويُعاد في التحديث القادم.")
    else:
        F.resolve("updater-error", "التحديثات التالية قرأت كل المتاجر بنجاح.")

    F.write()
    entry = {"at": now(), "ok": found == 0, "problems": found, "fixed": 0, "auto": True,
             "notes": [f"تمت مقارنة {checked} منتجاً مع المتاجر الأصلية؛ روابط غير مؤكدة: {bad_links}"]}
    lst = audit.get("audits", [])
    if entry["ok"] and lst and lst[0].get("auto") and lst[0].get("ok"):
        lst[0] = entry
    else:
        lst.insert(0, entry)
    save("audit.json", {"audits": lst[:30]})
    print(json.dumps(entry, ensure_ascii=False))


if __name__ == "__main__":
    main()
