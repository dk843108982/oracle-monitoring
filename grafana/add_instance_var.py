#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 Grafana 大盘加 oracle_instance 实例下拉变量，并给全部面板 expr 注入实例过滤。"""
import json, re

DASH = r"C:\Users\Administrator\Doubao\chats\2026-09-17\new-chat\oracle-monitoring\grafana\dashboards\oracle_enterprise.json"

with open(DASH, encoding="utf-8") as f:
    d = json.load(f)

# 1. 变量列表：oracle_instance 放在最前（表空间变量依赖它）
templ = d.setdefault("templating", {}).setdefault("list", [])
inst_var = {
    "name": "oracle_instance",
    "type": "query",
    "datasource": {"type": "prometheus", "uid": "prometheus"},
    "query": {"query": "label_values(oracle_up, oracle_instance)", "refId": "A"},
    "label": "数据库实例",
    "includeAll": True,
    "multi": True,
    "allValue": ".*",
    "current": {"text": "All", "value": "$__all"},
    "refresh": 1,
}
# 去掉旧表空间变量的实例依赖（原样保留），插入实例变量
templ.insert(0, inst_var)

# 2. 表空间变量也按实例过滤
for v in templ:
    if v.get("name") == "tablespace":
        q = v.get("query", {})
        if isinstance(q, dict):
            q["query"] = 'label_values(oracle_tablespace_used_percent{oracle_instance=~"$oracle_instance"}, tablespace)'
        elif isinstance(q, str):
            v["query"] = 'label_values(oracle_tablespace_used_percent{oracle_instance=~"$oracle_instance"}, tablespace)'

# 3. 全部面板 expr 注入 oracle_instance 过滤
def inject(expr):
    e = expr.strip()
    if "oracle_instance" in e:
        return expr
    # topk(N, metric) 或 topk by (..) (metric) 形式
    m = re.match(r"^(topk\([^)]*,\s*)([a-z_][a-z0-9_]*)(\))$", e)
    if m:
        return m.group(1) + m.group(2) + '{oracle_instance=~"$oracle_instance"}' + m.group(3)
    # 纯指标名 / 指标名+运算
    m = re.match(r"^([a-z_][a-z0-9_]*)(.*)$", e)
    if m and not e.startswith("#"):
        return m.group(1) + '{oracle_instance=~"$oracle_instance"}' + m.group(2)
    return expr

n_injected = 0
for p in d.get("panels", []):
    if p.get("type") == "row":
        continue
    for t in p.get("targets", []):
        old = t.get("expr", "")
        if old and "oracle_up" not in old:
            new = inject(old)
            if new != old:
                t["expr"] = new
                n_injected += 1

with open(DASH, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

print(f"注入实例过滤的 target: {n_injected}")
print(f"变量: {[v['name'] for v in templ]}")
