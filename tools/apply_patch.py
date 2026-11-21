"""Merge a patch into data.json (used by the scheduled monitoring runs).

Usage: python3 tools/apply_patch.py patch.json

patch.json = {
  "stores": { "<store-id>": { ...the FULL store document exactly as now in the Claude database..., "_v": <db version> } },
  "status": { ...meta/status fields to set... },
  "runs":   [ { ...run log entry... } ]
}
Stores are replaced whole (not merged). Runs are appended, keeping the newest 60.
"""
import json, sys, datetime

path = "data.json"
data = json.load(open(path, encoding="utf-8"))
patch = json.load(open(sys.argv[1], encoding="utf-8"))

for sid, doc in (patch.get("stores") or {}).items():
    if not isinstance(doc, dict) or "name" not in doc or "offers" not in doc:
        sys.exit(f"store {sid}: refusing to write a document without name/offers")
    data["stores"][sid] = doc
if patch.get("status"):
    data.setdefault("status", {}).update(patch["status"])
if patch.get("config"):
    data.setdefault("config", {}).update(patch["config"])
runs = data.get("runs", []) + list(patch.get("runs") or [])
runs.sort(key=lambda r: r.get("at", ""))
data["runs"] = runs[-60:]
data["generatedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=0, separators=(",", ":"))
print(f"ok: {len(patch.get('stores') or {})} stores written, {len(data['stores'])} total, {len(data['runs'])} runs")
