# -*- coding: utf-8 -*-
"""独立 OS 层监控看板（oracle-os）。

node_exporter 采集 RAC 双节点（racnode1/racnode2 :9100）：
CPU / 内存 / 磁盘 / 网络 / load1 六个面板，双节点同图对比。
Prometheus job: oracle-node（prometheus.yml 中配置）。
可重复执行（POST overwrite）。
"""
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


def os_ts(title, expr, unit):
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
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "id": 0,
        "options": {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
                    "tooltip": {"hideZeros": False, "mode": "multi", "sort": "none"}},
        "targets": [{"expr": expr, "legendFormat": "{{rac_node}}", "refId": "A"}],
        "title": title,
        "type": "timeseries",
    }


OS_FS_EXCLUDE = ('node_exporter --collector.filesystem.fs-types-exclude='
                 '"^(autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|'
                 'fusectl|hugetlbfs|iso9660|mqueue|nsfs|proc|procfs|pstore|rpc_pipefs|'
                 'securityfs|selinuxfs|squashfs|sysfs|tracefs)$"')

panels = [
    os_ts("节点 CPU 使用率", '100 - avg by (rac_node) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100', "percent"),
    os_ts("节点内存使用率", '100 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100', "percent"),
    os_ts("根分区磁盘使用率", '100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})', "percent"),
    os_ts("节点网络吞吐", 'rate(node_network_receive_bytes_total{device!="lo"}[5m])', "Bps"),
    os_ts("节点网络发送", 'rate(node_network_transmit_bytes_total{device!="lo"}[5m])', "Bps"),
    os_ts("节点负载 (1m)", "node_load1", "short"),
]

# 2 列 x 3 行布局（h=8 w=12）
next_id = 1001
y_cursor = 0
for i, p in enumerate(panels):
    p["id"] = next_id
    next_id += 1
    p["gridPos"] = {"h": 8, "w": 12, "x": 0 if i % 2 == 0 else 12, "y": y_cursor}
    if i % 2 == 1:
        y_cursor += 8

cur = {
    "annotations": {"list": []},
    "editable": True,
    "graphTooltip": 0,
    "links": [],
    "panels": panels,
    "refresh": "30s",
    "schemaVersion": 42,
    "tags": ["oracle", "rac", "os"],
    "templating": {"list": []},
    "time": {"from": "now-6h", "to": "now"},
    "timepicker": {},
    "timezone": "browser",
    "title": "节点 OS 监控（RAC node_exporter）",
    "uid": "oracle-os",
    "version": 1,
    "weekStart": "",
}

code, resp = api("/api/dashboards/db", "POST", {"dashboard": cur, "overwrite": True})
print("status:", code)
print("resp:", resp)
print("提示：node_exporter 启动参数需放开 overlay 文件系统：\n" + OS_FS_EXCLUDE)
