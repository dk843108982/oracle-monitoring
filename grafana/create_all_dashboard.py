# -*- coding: utf-8 -*-
"""合并 oracle-enterprise / oracle-rac / oracle-dg 三个看板为一个综合看板（oracle-all）。

v2（本次重构）：
- 不再机械按源看板 row 拼接（源看板分组错位会把无关面板塞进同一分组）
- 改为【主题白名单分类】：按面板标题精确映射到规范分组，未匹配的面板丢弃（如 OS 面板已拆到 oracle-os）
- 面板 id 从 1001 起重排；重复标题自动去重
- 表空间分组内置增长趋势预测面板（predict_linear，30 天）
- 基于 Grafana 12.4.2 dashboard 模型，POST 覆盖创建，可重复执行
"""
import copy
import json
import urllib.request

BASE = "http://localhost:3000"
AUTH = "Basic YWRtaW46YWRtaW4="

# 标题 -> 规范分组（精确匹配；不在映射表中的面板一律丢弃）
GROUP_MAP = {
    "实例总览": ["实例状态", "数据库信息", "实例运行时长", "会话数（按状态）",
                 "Buffer Cache 命中率", "归档状态"],
    "表空间": ["表空间使用率", "表空间增长趋势（实线=实际，虚线=30天线性预测）",
               "临时表空间使用率", "UNDO 使用率", "表空间预计可用天数"],
    "会话与事务": ["会话健康（阻塞/长事务/活跃）", "会话健康（续）", "硬解析率",
                   "日志切换（近1小时）", "DB Time（累计）"],
    "等待事件": ["Top 等待事件（累计秒）", "等待事件明细", "Top 等待次数",
                "Top 集群等待事件（累计秒）", "等待事件按类聚合（累计秒）"],
    "Top SQL": ["Top SQL 耗时排行", "Top SQL 执行次数"],
    "Alert 日志": ["ORA 错误计数（V$DIAG_ALERT_EXT）", "ADR 开放 Incident",
                   "数据块损坏", "24h 归档日志数", "SGA 分配总量",
                   "数据文件数 / 自动扩展"],
    "内存与备份": ["SGA 共享池空闲 / PGA", "PGA", "Library Cache 命中率",
                  "归档滞后", "备份年龄（天）", "归档日志（24h）"],
    "RAC 集群": ["集群实例状态", "实例清单", "各实例会话（按状态）",
                "Cache Fusion 块传输速率（5m 增量）", "DLM 消息速率（5m 增量）"],
    "Data Guard": ["DG 角色", "保护模式 / 级别", "开放模式", "日志模式 / 强制日志",
                   "DG 配置拓扑（V$DATAGUARD_CONFIG）",
                   "归档目的地状态（V$ARCHIVE_DEST_STATUS）",
                   "传输滞后（Transport Lag）", "应用滞后（Apply Lag / Finish）",
                   "MRP / Managed Standby 进程（V$MANAGED_STANDBY）",
                   "归档 GAP 数", "Standby Redo Log（V$STANDBY_LOG）"],
}

GROUP_ORDER = ["实例总览", "表空间", "会话与事务", "等待事件", "Top SQL",
               "Alert 日志", "内存与备份", "RAC 集群", "Data Guard"]

# 综合看板中手工追加的面板（趋势预测），构建一次后从看板里取，避免重复定义
TREND_TITLE = "表空间增长趋势（实线=实际，虚线=30天线性预测）"


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


# 1. 读取三套看板，收集全部非 row 面板
sources = [get_dash(u) for u in ("oracle-enterprise", "oracle-rac", "oracle-dg")]
all_panels = []
for d in sources:
    for p in d["panels"]:
        if p["type"] == "row":
            continue
        all_panels.append(copy.deepcopy(p))

# 2. 按标题分类；重复标题（同一 expr）去重
groups = {g: [] for g in GROUP_ORDER}
seen = set()
dropped = []
for p in all_panels:
    t = p.get("title", "")
    target = next((g for g, titles in GROUP_MAP.items() if t in titles), None)
    if target is None:
        dropped.append(t)
        continue
    expr_sig = json.dumps([tg.get("expr") for tg in p.get("targets", [])], ensure_ascii=False)
    key = (target, t, expr_sig)
    if key in seen:
        continue
    seen.add(key)
    groups[target].append(p)

# 3. 趋势面板（手工构建，保证存在）
trend_panel = None
for p in groups["表空间"]:
    if p.get("title") == TREND_TITLE:
        trend_panel = p
        break

# 3.1 表空间使用率：多实例时百分比不能加总，必须按 (tablespace, oracle_instance) 分别展示
for p in groups["表空间"]:
    if p.get("title") != "表空间使用率":
        continue
    for tg in p.get("targets", []):
        if "oracle_tablespace_used_percent" in (tg.get("expr") or ""):
            tg["expr"] = ("clamp_max(sum(oracle_tablespace_used_percent"
                          "{oracle_instance=~\"$oracle_instance\"}) by (tablespace, oracle_instance), 100)")
            tg["legendFormat"] = "{{tablespace}} {{oracle_instance}}"
            tg["refId"] = "A"
    # 多实例×多表空间 bar 较多：竖排展示，避免名字截断
    opts = p.setdefault("options", {})
    opts["orientation"] = "horizontal"
    opts["displayMode"] = "gradient"

if trend_panel is None:
    trend_panel = {
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
        "title": TREND_TITLE,
        "type": "timeseries",
    }
    groups["表空间"].append(trend_panel)

# 4. 布局：每个分组一个 row 头，其下面板按 y 排序平铺（2 列布局由原 w 决定）
new_panels = []
next_id = 1001
y_cursor = 0
_debug = []
for g in GROUP_ORDER:
    ps = groups[g]
    _debug.append("GRP %s -> %d panels" % (g, len(ps)))
    if not ps:
        continue
    new_panels.append({
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y_cursor},
        "id": next_id, "panels": [], "title": g, "type": "row",
    })
    next_id += 1
    # 面板从 row 下方开始（y > row.y，否则 Grafana 规范化会丢弃重叠面板）
    panel_y = y_cursor + 1
    sorted_ps = sorted(ps, key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"]))
    x_cursor = 0
    last_row_h = 4
    for p in sorted_ps:
        np = copy.deepcopy(p)
        np["id"] = next_id
        next_id += 1
        w = min(24, np["gridPos"]["w"] or 12)
        h = np["gridPos"]["h"] or 4
        if x_cursor + w > 24:
            x_cursor = 0
            panel_y += last_row_h
        np["gridPos"] = {"h": h, "w": w, "x": x_cursor, "y": panel_y}
        x_cursor += w
        last_row_h = max(4, h)
        new_panels.append(np)
    y_cursor = panel_y + last_row_h
    _debug.append("  -> appended %d panels, y_cursor=%d" % (len(sorted_ps), y_cursor))
with open(r"C:\Users\Administrator\Doubao\chats\2026-09-17\new-chat\oracle-monitoring\grafana\_diag8_layout.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(_debug))
    f.write("\nNEW_PANELS=%d\n" % len(new_panels))

# 5. 以 enterprise 模型为基础生成综合看板
ent = get_dash("oracle-enterprise")
cur = copy.deepcopy(ent)
cur.pop("id", None)
cur["title"] = "Oracle 综合监控（单实例 + RAC + Data Guard）"
cur["uid"] = "oracle-all"
cur["tags"] = ["oracle", "rac", "dg", "all"]
# 面板显式指定数据源（避免无 datasource 面板被 Grafana 12 规范化时剔除）
DS = {"type": "prometheus", "uid": "prometheus"}
for p in new_panels:
    if p.get("type") == "row":
        continue
    if not p.get("datasource"):
        p["datasource"] = DS
cur["panels"] = new_panels
cur["templating"] = copy.deepcopy(ent["templating"])
cur["refresh"] = "30s"
cur["time"] = {"from": "now-6h", "to": "now"}
cur["version"] = 1

with open(r"C:\Users\Administrator\Doubao\chats\2026-09-17\new-chat\oracle-monitoring\grafana\_diag7_len.txt", "w", encoding="utf-8") as f:
    f.write("PANELS_IN_BODY=%d\n" % len(cur["panels"]))
    f.write("NONROW=%d\n" % len([p for p in cur["panels"] if p.get("type") != "row"]))

code, resp = api("/api/dashboards/db", "POST", {"dashboard": cur, "overwrite": True})
print("status:", code)
print("resp:", resp)
print("DROPPED（未分类已丢弃）:", json.dumps(dropped, ensure_ascii=False))
