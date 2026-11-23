"""Automatic brand health check (runs inside GitHub Actions right after the updater).

Re-reads a sample of products from each official store and compares them with what the site shows,
checks that the site is up and that every data file is fresh, then records the result (in Arabic)
at the start of self-portrait/audit.json, which the Admin page shows.

It never changes product data and never deletes anything: a difference is reported, and the
updater corrects it from the official store on its next run.
"""
import datetime as dt
import json
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import sp_update as U  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "self-portrait")
AUDIT = os.path.join(ROOT, "audit.json")
SAMPLE = int(os.environ.get("AUDIT_SAMPLE", "6"))
NAMES = {"sp": "Self-Portrait", "md": "Mac Duggal", "ef": "Elisabetta Franchi"}


def load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def last_commit_age_h(path):
    try:
        t = subprocess.check_output(["git", "log", "-1", "--format=%ct", "--", path], cwd=os.path.join(ROOT, ".."), text=True).strip()
        return (time.time() - int(t)) / 3600 if t else None
    except Exception:  # noqa: BLE001
        return None


def pick(items):
    """Products most likely to be wrong first (off the sale list, carrying an extra %, recently changed), then random."""
    risky = [p for p in items if p.get("listed") is False and p.get("status") != "discontinued"]
    risky += [p for p in items if p.get("extraPct") and p not in risky]
    random.shuffle(risky)
    rest = [p for p in items if p not in risky]
    random.shuffle(rest)
    return (risky[: SAMPLE // 2] + rest)[:SAMPLE]


def diff(stored, live, keys):
    out = []
    for k in keys:
        a, b = stored.get(k), live.get(k)
        if k == "extraPct":
            a, b = a or 0, b or 0
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(a - b) > 0.011:
                out.append(f"{k} {a} ← الموقع الرسمي {b}")
        elif a != b:
            out.append(f"{k} {a} ← الموقع الرسمي {b}")
    return out


def any_stock(sizes):
    return any(x.get("a") for x in sizes or [])


def check_brand(code, items, meta):
    checked, problems = 0, []
    for p in pick(items):
        h = p["handle"]
        try:
            if code == "sp":
                raw = U.product_json(U.STORE, h)
                live = raw and U.normalize(raw, p.get("cat", "midi"), retain=True)
                keys = ("price", "compare")
            elif code == "md":
                raw = U.product_json(U.MD_STORE, h[3:])
                live = raw and U.normalize_md(raw, set(), retain=True)
                keys = ("price", "compare", "extraPct")
            else:
                d = U.ef_product(p["url"].replace(U.EF_SITE, ""))
                live = {"price": round(d["price"], 2), "compare": round(d["compare"] if d["compare"] > d["price"] else d["price"], 2),
                        "sizes": [{"s": k, "a": a} for k, a in d["sizes"].items()]} if d.get("price") else None
                keys = ("price", "compare")
        except U.urllib.error.HTTPError as e:
            if e.code in (404, 410):
                if p.get("status") != "discontinued":
                    problems.append(f"{NAMES[code]}: «{p.get('title', h)}» لم يعد في المتجر الرسمي — سيُعلَّم كغير متوفر في التحديث القادم (لم يُحذف)")
                checked += 1
                continue
            print("audit: could not read", h, e)
            continue
        except Exception as e:  # noqa: BLE001
            print("audit: could not read", h, e)
            continue
        finally:
            time.sleep(0.8)
        checked += 1
        if not live:
            continue
        if p.get("status") == "discontinued":
            problems.append(f"{NAMES[code]}: «{p.get('title', h)}» معلَّم كغير متوفر لكنه موجود في المتجر الرسمي — سيُعاد فحصه")
            continue
        d = diff(p, live, keys)
        if any_stock(p.get("sizes")) != any_stock(live.get("sizes")):
            d.append("التوفر " + ("متوفر" if any_stock(live.get("sizes")) else "نفد") + " في الموقع الرسمي")
        if d:
            problems.append(f"{NAMES[code]}: «{p.get('title', h)}» يختلف عن الموقع الرسمي ({'، '.join(d)}) — سيُصحَّح في التحديث القادم")
    return checked, problems


def site_up():
    notes = []
    for url, must in (("https://raghad-outlet.pages.dev/", "Raghad"),
                      ("https://ranaa4117.github.io/black-friday-deals/self-portrait/data.json", '"products"')):
        try:
            body = U.fetch(url + ("?t=%d" % time.time()), accept="text/html,application/json")
            if must not in body:
                notes.append(f"الموقع: الصفحة {url} تعمل لكن محتواها غير متوقع")
        except Exception as e:  # noqa: BLE001
            notes.append(f"الموقع: تعذّر فتح {url} ({e})")
    return notes


def main():
    try:
        audits = load("audit.json").get("audits", [])
    except Exception:  # noqa: BLE001
        audits = []
    last_auto = next((a for a in audits if a.get("auto")), None)
    if last_auto and U.age_s(last_auto["at"]) < 55 * 60 and os.environ.get("AUDIT_FORCE") != "1":
        print("brand audit: ran less than an hour ago — skipped")
        return
    full = load("full.json")
    meta = full.get("meta", {})
    items = full.get("products", [])
    promos = meta.get("mdPromos") or ([meta["mdPromo"]] if meta.get("mdPromo") else [])
    U.MD_PROMOS = [{k: v for k, v in x.items() if k != "miss"} for x in promos]
    U.MD_PROMO = U.MD_PROMOS[0] if U.MD_PROMOS else None

    problems, info = [], []
    total = 0
    for code in ("sp", "md", "ef"):
        mine = [p for p in items if p.get("brand", "sp") == code]
        if not mine:
            problems.append(f"{NAMES[code]}: لا توجد منتجات في الملف")
            continue
        n, pr = check_brand(code, mine, meta)
        total += n
        problems += pr
        if n == 0:
            problems.append(f"{NAMES[code]}: تعذّرت قراءة المتجر الرسمي في هذا الفحص")
    info.append(f"تمت مقارنة {total} منتجاً مع المواقع الرسمية (Self-Portrait وMac Duggal وElisabetta Franchi)")

    problems += site_up()

    for f, name in (("full.json", "الماركات الأوروبية وMac Duggal"), ("winter.json", "Macy's — التخفيضات الشتوية"), ("shoes.json", "Macy's — الأحذية")):
        age = last_commit_age_h("self-portrait/" + f)
        limit = 1.5 if f == "full.json" else 3
        if age is not None and age > limit:
            problems.append(f"{name}: آخر تحديث قبل {age:.0f} ساعة")

    if meta.get("lastError"):
        problems.append("آخر تحديث سجّل خطأً: " + str(meta["lastError"])[:160])

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entry = {"at": now, "ok": not problems, "problems": len(problems), "fixed": 0, "auto": True,
             "notes": problems + info if problems else info}
    # a run of "all fine" automatic checks is shown as one line with the latest time
    if entry["ok"] and audits and audits[0].get("auto") and audits[0].get("ok"):
        audits[0] = entry
    else:
        audits.insert(0, entry)
    with open(AUDIT, "w", encoding="utf-8") as f:
        json.dump({"audits": audits[:30]}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(json.dumps(entry, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
