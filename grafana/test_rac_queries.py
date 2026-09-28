# -*- coding: utf-8 -*-
"""测试 RAC dashboard 各面板 PromQL 在 Grafana 查询层是否有效。"""
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

queries = [
    ("集群实例状态", 'oracle_rac_instance_up{oracle_instance=~".*"}'),
    ("各实例会话", 'sum(oracle_rac_sessions_total{oracle_instance=~".*"}) by (inst_id, status)'),
    ("Top 等待事件", 'topk(8, oracle_rac_wait_event_seconds{oracle_instance=~".*"})'),
    ("Cache Fusion", 'increase(oracle_rac_cache_transfer{metric=~"gc (cr|current) blocks (served|received)",oracle_instance=~".*"}[5m])'),
    ("DLM 消息", 'increase(oracle_rac_dlm_stats{name=~"gcs messages sent|ges messages sent",oracle_instance=~".*"}[5m])'),
]
for name, expr in queries:
    body = {
        "queries": [{
            "refId": "A",
            "expr": expr,
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "intervalMs": 15000,
            "maxDataPoints": 800,
        }],
        "from": "now-6h",
        "to": "now",
    }
    try:
        resp = api("/api/ds/query", "POST", body)
        res = resp.get("results", {}).get("A", {})
        frames = res.get("frames", [])
        n = 0
        for f in frames:
            for s in f.get("schema", {}).get("fields", []):
                n += len(s.get("values", []))
        err = res.get("error")
        print(f"{name}: frames={len(frames)} values={n} error={err}")
    except Exception as e:
        print(f"{name}: EXC {e}")
