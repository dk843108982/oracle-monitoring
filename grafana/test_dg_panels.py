# -*- coding: utf-8 -*-
"""逐个 panel 测试 POST，定位非法 panel。"""
import json, urllib.request

BASE = "http://localhost:3000"
AUTH = "Basic YWRtaW46YWRtaW4="

def api(path, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Authorization", AUTH)
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as r:
            return 200, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

code, data = api("/api/dashboards/uid/oracle-enterprise")
cur = data["dashboard"]
with open(r"C:\Users\Administrator\Doubao\chats\2026-09-17\new-chat\oracle-monitoring\grafana\dg-dashboard.json", encoding="utf-8") as f:
    mine = json.load(f)["dashboard"]

# 逐 panel 测试
for p in mine["panels"]:
    test = dict(cur)
    test["uid"] = "oracle-dg-test"
    test["title"] = "DG TEST"
    test["panels"] = [p]
    code, resp = api("/api/dashboards/db", "POST", {"dashboard": test, "overwrite": True})
    print(f"panel id={p['id']} type={p['type']} title={p['title'][:20]!r} -> {code} {resp[:160] if isinstance(resp, str) else resp}")
