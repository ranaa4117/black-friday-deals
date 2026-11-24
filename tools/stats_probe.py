#!/usr/bin/env python3
"""Is the analytics database answering? Calls the public endpoints with a WRONG key on purpose (no secrets; prints status and error text only)."""
import json, urllib.request, urllib.error
BASE = "https://qhuerltbkvihmqzsphpv.supabase.co/rest/v1/"
KEY = "sb_publishable_K35x9gcJMqTGCuj2MFj_7w_PsQSF8mU"
def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"apikey": KEY, "Authorization": "Bearer " + KEY, "Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            print(path, r.status, r.read()[:300])
    except urllib.error.HTTPError as e:
        print(path, e.code, e.read()[:500])
    except Exception as e:  # noqa: BLE001
        print(path, "ERR", e)
call("rpc/admin_stats", {"p_key": "wrong-key-test", "p_from": "2026-11-17T00:00:00Z", "p_to": "2026-11-24T18:00:00Z"})
call("rpc/admin_ok", {"p_key": "wrong-key-test"})
call("product_scores?limit=1")
call("events?limit=1")
