# -*- coding: utf-8 -*-
"""从现有 oracle-enterprise dashboard 模型生成 Data Guard dashboard 并 POST 到 Grafana。"""
import json
import urllib.request

BASE = "http://localhost:3000"
AUTH = "Basic YWRtaW46YWRtaW4="

def api(path, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Authorization", AUTH)
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data) as r:
        return json.loads(r.read().decode())

# 1. 读取现有 dashboard 完整模型（确保字段与当前 Grafana 版本完全兼容）
cur = api("/api/dashboards/uid/oracle-enterprise")["dashboard"]
# 2. 读取我的 DG panels 定义
with open(r"C:\Users\Administrator\Doubao\chats\2026-09-17\new-chat\oracle-monitoring\grafana\dg-dashboard.json", encoding="utf-8") as f:
    mine = json.load(f)["dashboard"]

# 3. 以现有模型为基础，替换关键字段
cur.pop("id", None)          # 让 Grafana 分配新 dashboard id（旧 id 已被其他面板占用）
cur["title"] = "Oracle Data Guard 监控"
cur["uid"] = "oracle-dg"
cur["tags"] = ["oracle", "dg", "dataguard"]
cur["panels"] = mine["panels"]
cur["templating"] = mine["templating"]
cur["refresh"] = "30s"
cur["time"] = {"from": "now-6h", "to": "now"}
cur["version"] = 1

# 4. POST 创建
payload = {"dashboard": cur, "overwrite": True}
resp = api("/api/dashboards/db", "POST", payload)
print("status:", resp.get("status"))
print("url:", resp.get("url"))
