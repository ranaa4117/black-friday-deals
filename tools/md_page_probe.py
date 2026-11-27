#!/usr/bin/env python3
"""Mac Duggal: which promotion-label set do the official pages serve, with and without a cache-busting query (prints only)."""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_update as u

def cfg(url):
    try:
        h = u.fetch(url, accept="text/html")
    except Exception as e:  # noqa: BLE001
        return "ERR " + str(e)[:60]
    m = re.search(r"cardHighlights\s*=\s*(\[.*?\])\s*;", h, re.S)
    if not m:
        return "no config"
    return sorted({(re.search(r'label:\s*"([^"]*)"', o) or [0, ""])[1] + "→" + (re.search(r'tag:\s*"([^"]*)"', o) or [0, ""])[1] for o in re.findall(r"\{[^{}]*\}", m.group(1)) if 'market: "core"' in o})

for path in ["/", "/products/6135", "/products/30777", "/products/11782", "/products/11779", "/products/13003", "/collections/full-length-maxi"]:
    for i in range(3):
        print(path, "plain  ", cfg(u.MD_STORE + path))
        print(path, "busted ", cfg(u.MD_STORE + path + ("&" if "?" in path else "?") + "_rc=%d%d" % (time.time(), i)))
        time.sleep(1)

# Product pages that the data feed no longer finds: what the official page answers (status, final address, title).
for hd in [x for x in os.environ.get("MD_HANDLES", "").split(",") if x.strip()]:
    for path in ("/products/%s" % hd.strip(), "/products/%s.json" % hd.strip(), "/products/%s.js" % hd.strip()):
        try:
            r = u.urllib.request.urlopen(u.urllib.request.Request(u.MD_STORE + path + "?_rc=%d" % time.time(),
                                         headers={"User-Agent": u.UA, "Accept": "text/html,application/json"}), timeout=40)
            body = r.read().decode("utf-8", "replace")
            t = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
            print(hd, path, r.status, "→", r.geturl(), "| title:", re.sub(r"\s+", " ", t.group(1)).strip()[:120] if t else body[:160])
        except u.urllib.error.HTTPError as e:
            print(hd, path, "HTTP", e.code, "→", e.geturl())
        except Exception as e:  # noqa: BLE001
            print(hd, path, "ERR", str(e)[:120])
        time.sleep(1)
