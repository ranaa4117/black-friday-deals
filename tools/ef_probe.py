#!/usr/bin/env python3
"""Elisabetta Franchi outlet access test (prints only)."""
import re, urllib.request
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html,*/*", "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.status, r.read().decode("utf-8", "replace")
B = "https://outlet.elisabettafranchi.com/it-it/abbigliamento/abiti/abiti-lunghi/"
for u in [B, B + "?page=2"]:
    try:
        st, h = get(u)
        pids = list(dict.fromkeys(re.findall(r'data-pid="([^"]+)"', h)))
        print(st, len(h), u, "pids:", len(pids), pids[:30])
        print("  hrefs:", len(set(re.findall(r'href="([^"]+\.html)"', h))), "| 'start=' links:", re.findall(r'[?&]start=\d+[^"\']*', h)[:4], "| page links:", sorted(set(re.findall(r'\?page=\d+', h)))[:6])
        i = h.find('class="price"'); print("  price html:", re.sub(r"\s+", " ", h[i:i+600]) if i >= 0 else "none")
        for k in ("strike-through", "list", "sales", "discount", "%"):
            print("  ", k, h.count(k))
    except Exception as e:
        print("ERR", u, e)
P = "https://outlet.elisabettafranchi.com/it-it/abbigliamento/abiti/red-carpet/abito-red-carpet-in-crepe-con-stampa-pitone-ABR2857E2110.html"
try:
    st, h = get(P)
    print("PDP", st, len(h))
    i = h.find('class="price"'); print("  price html:", re.sub(r"\s+", " ", h[i:i+700]) if i >= 0 else "none")
    for pat in [r'data-attr-value="([^"]+)"', r'"size"[^\]]{0,300}', r'Lunghezza[^<]{0,80}', r'lungo|longuette|midi|mini', r'"availability"[^,]{0,80}']:
        print("  ", pat[:20], re.findall(pat, h, re.I)[:20])
    j = h.find('application/ld+json'); print("  ld:", re.sub(r"\s+", " ", h[j:j+1200]) if j >= 0 else "none")
except Exception as e:
    print("ERR PDP", e)
