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
