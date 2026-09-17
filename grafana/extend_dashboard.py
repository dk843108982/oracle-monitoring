#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扩展 Grafana Oracle 大盘：18 面板 -> 33 面板。追加到现有分组末尾 + 新增分组。"""
import json, copy

DASH = r"C:\Users\Administrator\Doubao\chats\2026-09-17\new-chat\oracle-monitoring\grafana\dashboards\oracle_enterprise.json"

def panel(pid, ptype, title, expr, legend, w=6, h=4, unit=None, decimals=1,
          transform=None, extra_targets=None):
    p = {
        "id": pid, "type": ptype, "title": title,
        "gridPos": {"h": h, "w": w, "x": 0, "y": 0},
        "datasource": None,
        "fieldConfig": {"defaults": {"color": {"mode": "palette-classic"},
                                      "custom": {"fillOpacity": 12, "lineWidth": 1,
                                                 "showPoints": "never", "spanNulls": False}},
                         "overrides": []},
        "targets": [{"refId": "A", "expr": expr, "legendFormat": legend}],
        "options": {}
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    if ptype == "stat":
        p["fieldConfig"]["defaults"]["mappings"] = []
        p["options"] = {"colorMode": "value", "graphMode": "area", "justifyMode": "auto",
                        "orientation": "auto", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}
    if ptype == "timeseries":
        p["options"] = {"tooltip": {"mode": "multi"}, "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}}
    if ptype == "table":
        p["fieldConfig"]["defaults"]["custom"] = {"fillOpacity": 12, "lineWidth": 1, "showPoints": "never", "spanNulls": False}
        p["options"] = {"showHeader": True, "sortBy": [{"displayName": "值", "desc": True}]}
        p["transformations"] = [{"id": "organize", "options": {}}]
    if extra_targets:
        p["targets"].extend(extra_targets)
    return p

with open(DASH, encoding="utf-8") as f:
    d = json.load(f)

panels = d["panels"]
# 分组: 找到各 row 及其内容面板
rows = {}   # row_title -> {panel_indexes:[...], row_idx}
order = []
for i, p in enumerate(panels):
    if p["type"] == "row":
        order.append((p["title"], i))
        rows[p["title"]] = {"row_idx": i, "children": []}
    else:
        if order:
            rows[order[-1][0]]["children"].append(i)

def append_to_row(title, new_panels):
    """在指定 row 的内容末尾追加面板，计算 y 位置。"""
    group = rows[title]
    children = group["children"]
    # 找行内最大 y（考虑多行面板）
    max_y = -1
    for idx in children:
        gp = panels[idx]["gridPos"]
        max_y = max(max_y, gp["y"] + gp["h"])
    # 从 max_y 开始平铺，w 拼接
    y = max_y
    x = 0
    for np in new_panels:
        np["gridPos"]["y"] = y
        np["gridPos"]["x"] = x
        x += np["gridPos"]["w"]
        if x >= 24:
            x = 0
            y += np["gridPos"]["h"]
    # 若行内只有 row 本身
    if not children:
        np_first = new_panels[0]
        np_first["gridPos"]["y"] = panels[group["row_idx"]]["gridPos"]["y"] + 1
    panels.extend(new_panels)
    group["children"].extend(range(len(panels) - len(new_panels), len(panels)))

nid = 1000
def nxt():
    global nid
    nid += 1
    return nid

# ---- 实例与HA 追加 ----
append_to_row("实例总览", [
    panel(nxt(), "stat", "实例运行时长", "oracle_instance_uptime_seconds", "{{instance}}",
          w=4, unit="s", decimals=0),
    panel(nxt(), "timeseries", "会话健康（阻塞/长事务/活跃）",
          'oracle_sessions_blocked_total', "阻塞", w=8),
    panel(nxt(), "timeseries", "会话健康（续）",
          'oracle_long_running_sessions_total', "长事务", w=4),
    panel(nxt(), "timeseries", "硬解析率",
          'oracle_hard_parse_ratio', "hard parse %", w=8, unit="percent", decimals=2),
    panel(nxt(), "timeseries", "日志切换（近1小时）",
          'oracle_redo_log_switches_1h_total', "switches", w=4, decimals=0),
    panel(nxt(), "timeseries", "DB Time（累计）",
          'oracle_db_time_seconds', "DB time", w=8, unit="s", decimals=0),
])

# ---- 表空间 追加 ----
append_to_row("表空间", [
    panel(nxt(), "stat", "临时表空间使用率", "oracle_temp_used_percent", "TEMP", w=4, unit="percent", decimals=1),
    panel(nxt(), "stat", "UNDO 使用率", "oracle_undo_used_percent", "UNDO", w=4, unit="percent", decimals=1),
    panel(nxt(), "table", "表空间预计可用天数",
          'oracle_tablespace_free_days', "{{tablespace}}", w=12, unit="d", decimals=1),
])

# ---- 等待事件 追加 ----
append_to_row("等待事件（V$SYSTEM_EVENT）", [
    panel(nxt(), "timeseries", "Top 等待次数",
          'topk(5, oracle_wait_event_total_waits)', "{{event}}", w=12, decimals=0),
])

# ---- Top SQL 追加 ----
append_to_row("Top SQL（V$SQLAREA）", [
    panel(nxt(), "table", "Top SQL 执行次数",
          'topk(10, oracle_top_sql_executions_total)', "{{sql_id}} {{sql_text}}", w=12, decimals=0),
])

# ---- Alert 日志错误 追加 ----
append_to_row("Alert 日志错误", [
    panel(nxt(), "stat", "ADR 开放 Incident", "oracle_alert_incidents_total", "incidents", w=4, decimals=0),
    panel(nxt(), "stat", "数据块损坏", "oracle_block_corruption_total", "corrupt blocks", w=4, decimals=0),
])

# ---- 新增分组：内存与备份 ----
new_row = {
    "id": nxt(), "type": "row", "title": "内存与备份", "collapsed": False,
    "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
    "panels": [], "datasource": None
}
# 新 row 放在最后一个 row 之后：找最后一个 row 的 y，新 row y = 最后一组内容 max_y
last_row_title = order[-1][0]
group = rows[last_row_title]
max_y = panels[group["row_idx"]]["gridPos"]["y"]
for idx in group["children"]:
    gp = panels[idx]["gridPos"]
    max_y = max(max_y, gp["y"] + gp["h"])
new_row["gridPos"]["y"] = max_y
panels.append(new_row)
rows["内存与备份"] = {"row_idx": len(panels) - 1, "children": []}

append_to_row("内存与备份", [
    panel(nxt(), "timeseries", "SGA 共享池空闲 / PGA",
          'oracle_sga_free_bytes/1048576', "SGA free MB", w=8, unit="decmbytes", decimals=1),
    panel(nxt(), "timeseries", "PGA",
          'oracle_pga_allocated_bytes/1073741824', "PGA GB", w=4, unit="decmbytes", decimals=2),
    panel(nxt(), "stat", "Library Cache 命中率",
          'oracle_library_cache_hit_ratio', "hit %", w=4, unit="percent", decimals=2),
    panel(nxt(), "timeseries", "归档滞后",
          'oracle_archive_lag_seconds', "lag s", w=8, unit="s", decimals=0),
    panel(nxt(), "stat", "备份年龄（天）",
          'oracle_backup_age_days', "days", w=4, unit="d", decimals=2),
    panel(nxt(), "stat", "归档日志（24h）",
          'oracle_archive_logs_24h_total', "logs", w=4, decimals=0),
])

# 修正：新 row 的面板 y 计算时 append_to_row 用的是 max_y 初始 -1 逻辑
# 重新计算"内存与备份"内容面板位置
grp = rows["内存与备份"]
children = grp["children"]
max_y = new_row["gridPos"]["y"] + 1
x = 0
for idx in children:
    gp = panels[idx]["gridPos"]
    gp["y"] = max_y
    gp["x"] = x
    x += gp["w"]
    if x >= 24:
        x = 0
        max_y += gp["h"]

# 移除 panels 中 type=row 且 collapsed 标志为 True 的占位（无）
with open(DASH, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

print(f"面板总数: {len(panels)}")
for p in panels:
    if p["type"] == "row":
        print(f"  [ROW] {p['title']} y={p['gridPos']['y']}")
print("done")
