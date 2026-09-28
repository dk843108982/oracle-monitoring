# -*- coding: utf-8 -*-
"""合并 oracle-enterprise / oracle-rac / oracle-dg 三个看板为一个综合看板（oracle-all）。

- 保留各看板的 Row 分组标题，面板按行重排布局
- 面板 id 重新分配（避免跨看板冲突）
- 基于 Grafana 12.4.2 现有 dashboard 模型，POST 覆盖创建
"""
import copy
import json
import urllib.request

BASE = "http://localhost:3000"
AUTH = "Basic YWRtaW46YWRtaW4="

def api(path, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Authorization", AUTH)
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def get_dash(uid):
    code, data = api("/api/dashboards/uid/%s" % uid)
    if code != 200:
        raise RuntimeError("get %s failed: %s" % (uid, data))
    return data["dashboard"]

def collect_rows(d):
    """提取 (row_title, [panels])，非 row 面板挂到当前 row。"""
    rows = []
    cur = None
    for p in d["panels"]:
        if p["type"] == "row":
            cur = (p["title"], [])
            rows.append(cur)
        elif cur is not None:
            cur[1].append(p)
        else:
            rows.append(("未分组", [p])) if False else None
    # 没有 row 前缀的面板单独成行
    orphan = []
    # 上面循环已处理全部，直接返回
    return rows

# 1. 读取三套看板模型
ent = get_dash("oracle-enterprise")
rac = get_dash("oracle-rac")
dg = get_dash("oracle-dg")

# 2. 按顺序收集行（enterprise -> rac -> dg）
rows = []
rows.extend(collect_rows(ent))
rows.extend(collect_rows(rac))
rows.extend(collect_rows(dg))

# 2.1 追加 OS 层监控区（node_exporter 采集 RAC 双节点）
def os_ts(title, expr, unit, h=4, w=6):
    return {
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "custom": {"drawStyle": "line", "fillOpacity": 10, "lineWidth": 1,
                           "showPoints": "never", "spanNulls": False,
                           "stacking": {"group": "A", "mode": "none"},
                           "thresholdsStyle": {"mode": "off"}},
                "mappings": [], "unit": unit,
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": 0},
                                                             {"color": "red", "value": 80}]},
            },
            "overrides": [],
        },
        "gridPos": {"h": h, "w": w, "x": 0, "y": 0},
        "id": 0,
        "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
                    "tooltip": {"hideZeros": False, "mode": "multi", "sort": "none"}},
        "targets": [{"expr": expr, "legendFormat": "{{rac_node}}", "refId": "A"}],
        "title": title,
        "type": "timeseries",
    }

os_panels = [
    os_ts("节点 CPU 使用率", '100 - avg by (rac_node) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100', "percent", 4, 6),
    os_ts("节点内存使用率", '100 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100', "percent", 4, 6),
    os_ts("根分区磁盘使用率", '100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})', "percent", 4, 6),
    os_ts("节点网络吞吐", 'rate(node_network_receive_bytes_total{device!="lo"}[5m])', "Bps", 4, 6),
    os_ts("节点网络发送", 'rate(node_network_transmit_bytes_total{device!="lo"}[5m])', "Bps", 4, 6),
    os_ts("节点负载 (1m)", "node_load1", "short", 4, 6),
]
rows.append(("节点 OS（node_exporter）", os_panels))

# 2.2 表空间增长趋势预测面板（追加到"表空间"分组）
ts_trend = {
    "datasource": {"type": "prometheus", "uid": "prometheus"},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "custom": {"drawStyle": "line", "fillOpacity": 8, "lineWidth": 1,
                       "showPoints": "never", "spanNulls": False,
                       "stacking": {"group": "A", "mode": "none"},
                       "thresholdsStyle": {"mode": "off"}},
            "mappings": [], "unit": "decbytes",
            "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": 0},
                                                         {"color": "red", "value": 80}]},
        },
        "overrides": [],
    },
    "gridPos": {"h": 8, "w": 24, "x": 0, "y": 0},
    "id": 0,
    "options": {"legend": {"calcs": ["max"], "displayMode": "table", "placement": "bottom", "showLegend": True},
                "tooltip": {"hideZeros": False, "mode": "multi", "sort": "none"}},
    "targets": [
        {"expr": "sum by (tablespace) (oracle_tablespace_used_bytes)", "legendFormat": "{{tablespace}}", "refId": "A"},
        {"expr": "predict_linear(sum by (tablespace) (oracle_tablespace_used_bytes)[7d], 86400*30)",
         "legendFormat": "{{tablespace}} 预测(30d)", "refId": "B"},
    ],
    "title": "表空间增长趋势（实线=实际，虚线=30天线性预测）",
    "type": "timeseries",
}
for row_title, ps in rows:
    if row_title == "表空间":
        ps.append(ts_trend)
        break

# 3. 重排布局：每行一个 row 头（h=1），其下按原相对位置平铺
new_panels = []
next_id = 1001
y_cursor = 0
for row_title, ps in rows:
    if not ps:
        continue
    new_panels.append({
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y_cursor},
        "id": next_id, "panels": [], "title": row_title, "type": "row",
    })
    next_id += 1
    y_cursor += 1
    if not ps:
        continue
    min_y = min(g["gridPos"]["y"] for g in ps)
    row_h = max(g["gridPos"]["y"] + g["gridPos"]["h"] for g in ps) - min_y
    # 按 (y, x) 排序保持视觉顺序
    for p in sorted(ps, key=lambda g: (g["gridPos"]["y"], g["gridPos"]["x"])):
        np = copy.deepcopy(p)
        np["id"] = next_id
        next_id += 1
        g = np["gridPos"]
        np["gridPos"] = {"h": g["h"], "w": g["w"], "x": g["x"], "y": y_cursor + (g["y"] - min_y)}
        new_panels.append(np)
    y_cursor += row_h

# 4. 以 enterprise 模型为基础生成综合看板
cur = copy.deepcopy(ent)
cur.pop("id", None)
cur["title"] = "Oracle 综合监控（单实例 + RAC + Data Guard）"
cur["uid"] = "oracle-all"
cur["tags"] = ["oracle", "rac", "dg", "all"]
cur["panels"] = new_panels
cur["templating"] = copy.deepcopy(ent["templating"])
cur["refresh"] = "30s"
cur["time"] = {"from": "now-6h", "to": "now"}
cur["version"] = 1

code, resp = api("/api/dashboards/db", "POST", {"dashboard": cur, "overwrite": True})
print("status:", code)
print("resp:", resp)
