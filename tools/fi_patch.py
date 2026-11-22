"""Merge a sync patch into friday-index/data.json (used by the scheduled publish task).

Usage: python3 tools/fi_patch.py patch.json

patch.json = {
  "deals":   { "<deal id>": { ...FULL document exactly as in the Claude database..., "_v": <db version> } },
  "status":  { ...meta/status fields..., "_v": <version> },
  "sources": { ...meta/sources map..., "_v": <version> },
  "runs":    [ { ...run log entries... } ]
}
Deals are replaced whole (never merged). Runs are appended, keeping the newest 60.
"""
import json, sys, datetime
path = "friday-index/data.json"
data = json.load(open(path, encoding="utf-8"))
patch = json.load(open(sys.argv[1], encoding="utf-8"))
n = 0
for did, doc in (patch.get("deals") or {}).items():
    if not isinstance(doc, dict) or not doc.get("store") or doc.get("market") not in ("us", "sa"):
        sys.exit(f"deal {did}: refusing to write a document without store/market")
    data["deals"][did] = doc; n += 1
for k in ("status", "sources"):
    if patch.get(k): data[k] = patch[k]
runs = data.get("runs", []) + list(patch.get("runs") or [])
seen = {}; [seen.__setitem__(r.get("at"), r) for r in runs]
data["runs"] = sorted(seen.values(), key=lambda r: r.get("at", ""))[-60:]
data["generatedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"ok: {n} deals written, {len(data['deals'])} total, {len(data['runs'])} runs")
