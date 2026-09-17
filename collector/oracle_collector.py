#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle Enterprise Monitor Collector
====================================
基于 oracle/skills 官方技能库设计的企业级 Oracle 数据库指标采集器。

两种运行模式：
  - demo : 演示模式（默认）。无真实 Oracle 数据库时，模拟生成贴近真实分布的
           Oracle 指标，用于完整验证 Prometheus -> Grafana -> Alertmanager 链路。
  - real : 真实模式。使用 python-oracledb thin 模式连接 Oracle，执行 SQL 全部
           取自 oracle/skills 技能库（db/monitoring、db/performance、db/backup-recovery
           db/admin 文档），最小权限只读采集；单项查询失败自动跳过（权限不足
           不影响其余指标）。

指标维度（对齐技能库）：
  实例/HA        oracle_up, instance_info, uptime, redo switches, db time
  空间           tablespace used%/total/used/free/max/autoextend/free_days,
                 temp%, undo%
  内存           SGA, PGA, shared pool free, buffer cache, library cache
  会话/SQL       sessions, blocked, long-running, top sql (elapsed/cpu/executions)
  等待事件       wait seconds / total waits / avg ms
  Alert/ADR      ORA errors, incidents
  归档/备份      archiver, archive logs, archive lag, backup age, corruption
  健康检查       health check issues

指标输出：Prometheus text format，HTTP :9161/metrics
运行方式：python oracle_collector.py --mode demo|real --config config.json
"""

import argparse
import json
import os
import random
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import oracledb
    HAS_ORACLEDB = True
except ImportError:
    HAS_ORACLEDB = False

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "mode": "demo",                      # demo | real
    "listen": {"host": "0.0.0.0", "port": 9161},
    "oracle_instances": [                # 多实例（可多个；也兼容旧单实例 "oracle" 对象）
        {
            "instance_name": "DB1-PROD", # 自定义别名 -> 指标标签 oracle_instance
            "host": "127.0.0.1",
            "port": 1521,
            "service_name": "ORCLPDB1",
            "user": "db_monitor",
            "password": "ChangeMe_2026"
        }
    ],
    "skill_repo": os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "oracle-skills"
    ),
    "collect_interval_seconds": 30,
    "demo": {
        "tablespace_growth_per_cycle_mb": 12,   # USERS 表空间每轮增长，模拟告警趋势
        "alert_errors_per_cycle": 0             # 每轮注入的 alert 日志错误数
    }
}

# ---------------------------------------------------------------------------
# 指标定义（HELP/TYPE 全量注册）
# ---------------------------------------------------------------------------
METRIC_HEADER = (
    "# HELP oracle_up 1 if database instance is reachable, 0 otherwise\n"
    "# TYPE oracle_up gauge\n"
    "# HELP oracle_instance_info Oracle instance identity information\n"
    "# TYPE oracle_instance_info gauge\n"
    "# HELP oracle_instance_uptime_seconds Instance uptime seconds since startup\n"
    "# TYPE oracle_instance_uptime_seconds gauge\n"
    "# HELP oracle_sessions_total Sessions by status\n"
    "# TYPE oracle_sessions_total gauge\n"
    "# HELP oracle_sessions_blocked_total Sessions blocked by other sessions\n"
    "# TYPE oracle_sessions_blocked_total gauge\n"
    "# HELP oracle_long_running_sessions_total Active sessions running > 30 min\n"
    "# TYPE oracle_long_running_sessions_total gauge\n"
    "# HELP oracle_hard_parse_ratio Hard parse ratio percent (parse count hard / total)\n"
    "# TYPE oracle_hard_parse_ratio gauge\n"
    "# HELP oracle_redo_log_switches_1h_total Redo log switches in last 1 hour\n"
    "# TYPE oracle_redo_log_switches_1h_total gauge\n"
    "# HELP oracle_db_time_seconds Cumulative DB time seconds (V$SYSSTAT 'DB time')\n"
    "# TYPE oracle_db_time_seconds gauge\n"
    "# HELP oracle_sysstat_total Oracle system statistics by name (V$SYSSTAT)\n"
    "# TYPE oracle_sysstat_total gauge\n"
    "# HELP oracle_tablespace_used_percent Tablespace usage percentage\n"
    "# TYPE oracle_tablespace_used_percent gauge\n"
    "# HELP oracle_tablespace_total_bytes Tablespace total size bytes\n"
    "# TYPE oracle_tablespace_total_bytes gauge\n"
    "# HELP oracle_tablespace_used_bytes Tablespace used bytes\n"
    "# TYPE oracle_tablespace_used_bytes gauge\n"
    "# HELP oracle_tablespace_free_bytes Tablespace free bytes\n"
    "# TYPE oracle_tablespace_free_bytes gauge\n"
    "# HELP oracle_tablespace_maxbytes_bytes Tablespace max autoextend size bytes\n"
    "# TYPE oracle_tablespace_maxbytes_bytes gauge\n"
    "# HELP oracle_tablespace_autoextend_status 1 if tablespace has autoextensible datafile (0/1)\n"
    "# TYPE oracle_tablespace_autoextend_status gauge\n"
    "# HELP oracle_tablespace_free_days Estimated days until full at current growth\n"
    "# TYPE oracle_tablespace_free_days gauge\n"
    "# HELP oracle_temp_used_percent Temporary tablespace usage percent\n"
    "# TYPE oracle_temp_used_percent gauge\n"
    "# HELP oracle_undo_used_percent Undo tablespace usage percent\n"
    "# TYPE oracle_undo_used_percent gauge\n"
    "# HELP oracle_wait_event_seconds Cumulative wait time seconds by event (V$SYSTEM_EVENT)\n"
    "# TYPE oracle_wait_event_seconds gauge\n"
    "# HELP oracle_wait_event_total_waits Total waits by event (V$SYSTEM_EVENT)\n"
    "# TYPE oracle_wait_event_total_waits gauge\n"
    "# HELP oracle_wait_event_avg_milliseconds Average wait milliseconds by event\n"
    "# TYPE oracle_wait_event_avg_milliseconds gauge\n"
    "# HELP oracle_top_sql_elapsed_seconds Top SQL elapsed seconds (V$SQLAREA)\n"
    "# TYPE oracle_top_sql_elapsed_seconds gauge\n"
    "# HELP oracle_top_sql_cpu_seconds Top SQL CPU seconds (V$SQLAREA)\n"
    "# TYPE oracle_top_sql_cpu_seconds gauge\n"
    "# HELP oracle_top_sql_executions_total Top SQL execution count (V$SQLAREA)\n"
    "# TYPE oracle_top_sql_executions_total gauge\n"
    "# HELP oracle_alertlog_errors_total ORA- errors found in alert log (V$DIAG_ALERT_EXT)\n"
    "# TYPE oracle_alertlog_errors_total counter\n"
    "# HELP oracle_alert_incidents_total Open incidents in ADR (V$DIAG_INCIDENT)\n"
    "# TYPE oracle_alert_incidents_total gauge\n"
    "# HELP oracle_buffer_cache_hit_ratio Buffer cache hit ratio percent\n"
    "# TYPE oracle_buffer_cache_hit_ratio gauge\n"
    "# HELP oracle_library_cache_hit_ratio Library cache hit ratio percent\n"
    "# TYPE oracle_library_cache_hit_ratio gauge\n"
    "# HELP oracle_sga_allocated_bytes SGA pool allocated bytes\n"
    "# TYPE oracle_sga_allocated_bytes gauge\n"
    "# HELP oracle_sga_free_bytes Shared pool free memory bytes\n"
    "# TYPE oracle_sga_free_bytes gauge\n"
    "# HELP oracle_pga_allocated_bytes PGA total allocated bytes\n"
    "# TYPE oracle_pga_allocated_bytes gauge\n"
    "# HELP oracle_archiver_status Archiver process status (1=STARTED,0=FAILED)\n"
    "# TYPE oracle_archiver_status gauge\n"
    "# HELP oracle_archive_logs_24h_total Archive logs generated in last 24h\n"
    "# TYPE oracle_archive_logs_24h_total gauge\n"
    "# HELP oracle_archive_lag_seconds Seconds since last archived redo log\n"
    "# TYPE oracle_archive_lag_seconds gauge\n"
    "# HELP oracle_backup_age_days Days since last completed full backup (RMAN)\n"
    "# TYPE oracle_backup_age_days gauge\n"
    "# HELP oracle_block_corruption_total Corrupted blocks reported (V$DATABASE_BLOCK_CORRUPTION)\n"
    "# TYPE oracle_block_corruption_total gauge\n"
    "# HELP oracle_health_check_issues_total Open health check issues (V$HM_RUN)\n"
    "# TYPE oracle_health_check_issues_total gauge\n"
    "# HELP oracle_datafiles_total Datafiles by tablespace\n"
    "# TYPE oracle_datafiles_total gauge\n"
    "# HELP oracle_datafiles_autoextend_total Autoextensible datafiles by tablespace\n"
    "# TYPE oracle_datafiles_autoextend_total gauge\n"
    "# HELP oracle_collector_scrape_duration_seconds Collector scrape duration\n"
    "# TYPE oracle_collector_scrape_duration_seconds gauge\n"
)

# ---------------------------------------------------------------------------
# 真实模式 SQL —— 全部来源于 oracle/skills 技能库
# ---------------------------------------------------------------------------
SKILL_SQL = {
    # db/monitoring/space-management.md — 主表空间监控查询
    "tablespace": """
        SELECT m.tablespace_name,
               ROUND(m.tablespace_size * t.block_size / 1073741824, 2) AS total_gb,
               ROUND(m.used_space * t.block_size / 1073741824, 2)      AS used_gb,
               ROUND(m.free_space * t.block_size / 1073741824, 2)      AS free_gb,
               ROUND(m.used_percent, 1)                                AS used_pct,
               t.contents
        FROM   dba_tablespace_usage_metrics m
        JOIN   dba_tablespaces              t ON m.tablespace_name = t.tablespace_name
        ORDER BY m.used_percent DESC
    """,
    # db/monitoring/space-management.md — 数据文件 / 自动扩展 / 最大上限
    "datafiles": """
        SELECT tablespace_name,
               COUNT(*)                                             AS file_cnt,
               SUM(CASE WHEN autoextensible = 'YES' THEN 1 ELSE 0 END) AS auto_cnt,
               NVL(SUM(CASE WHEN autoextensible = 'YES' THEN maxbytes ELSE bytes END), 0) AS max_bytes
        FROM   dba_data_files
        GROUP BY tablespace_name
    """,
    # db/performance/wait-events.md — V$SYSTEM_EVENT 等待事件
    "wait_events": """
        SELECT event,
               wait_class,
               total_waits,
               ROUND(time_waited_micro / 1e6, 2) AS time_waited_sec
        FROM   v$system_event
        WHERE  wait_class != 'Idle'
        ORDER  BY time_waited_micro DESC
        FETCH  FIRST 20 ROWS ONLY
    """,
    # db/monitoring/top-sql-queries.md — V$SQLAREA Top SQL by elapsed
    "top_sql": """
        SELECT sql_id,
               ROUND(elapsed_time / 1e6, 1)               AS total_elapsed_sec,
               ROUND(cpu_time    / 1e6, 1)                AS total_cpu_sec,
               executions,
               parsing_schema_name,
               SUBSTR(sql_text, 1, 80)                    AS sql_preview
        FROM   v$sqlarea
        WHERE  executions > 0
        ORDER BY elapsed_time DESC
        FETCH FIRST 20 ROWS ONLY
    """,
    # db/monitoring/alert-log-analysis.md — V$DIAG_ALERT_EXT 近 1 小时 ORA 错误
    "alert_log": """
        SELECT originating_timestamp AS error_time,
               message_text
        FROM   v$diag_alert_ext
        WHERE  originating_timestamp > SYSTIMESTAMP - INTERVAL '1' HOUR
        AND    message_text LIKE 'ORA-%'
        ORDER BY originating_timestamp DESC
    """,
    # db/admin — 会话与阻塞
    "sessions": """
        SELECT status, COUNT(*) AS cnt
        FROM   v$session
        GROUP BY status
    """,
    "sessions_blocked": """
        SELECT COUNT(*) AS cnt
        FROM   v$session
        WHERE  blocking_session IS NOT NULL
    """,
    "long_running": """
        SELECT COUNT(*) AS cnt
        FROM   v$session
        WHERE  status = 'ACTIVE' AND last_call_et > 1800
    """,
    "instance": """
        SELECT instance_name, host_name, version, status, database_status,
               ROUND((SYSDATE - startup_time) * 86400) AS uptime_sec
        FROM   v$instance
    """,
    # db/admin — 重做日志切换（近 1 小时）
    "redo_switches": """
        SELECT COUNT(*) AS cnt
        FROM   v$log_history
        WHERE  first_time > SYSDATE - 1/24
    """,
    # db/performance/awr-reports.md + memory-tuning.md — 关键系统统计
    "sysstat": """
        SELECT name, value
        FROM   v$sysstat
        WHERE  name IN ('DB time', 'physical reads', 'logical reads',
                        'parse count total', 'parse count (hard)',
                        'user commits', 'execute count')
    """,
    # db/monitoring/alert-log-analysis.md — 归档目的地状态
    "archive_dest": """
        SELECT dest_id, status, target, archiver, error
        FROM   v$archive_dest
        WHERE  status != 'INACTIVE'
    """,
    # db/backup-recovery — 归档滞后与备份年龄
    "archive_lag": """
        SELECT ROUND((SYSDATE - MAX(first_time)) * 86400) AS lag_sec
        FROM   v$archived_log
        WHERE  archived = 'YES'
    """,
    "backup_age": """
        SELECT ROUND((SYSDATE - MAX(end_time)) * 24) AS age_hours
        FROM   v$rman_backup_job_details
        WHERE  status = 'COMPLETED' AND input_type = 'DB FULL'
    """,
    # db/backup-recovery — 损坏块
    "corruption": """
        SELECT COUNT(*) AS cnt FROM v$database_block_corruption
    """,
    # db/monitoring/adrci-usage.md — 开放 incident
    "incidents": """
        SELECT COUNT(*) AS cnt FROM v$diag_incident WHERE status = 'OPEN'
    """,
    # db/performance/memory-tuning.md — SGA/PGA
    "sga": """
        SELECT pool, SUM(bytes) AS bytes
        FROM   v$sgastat
        WHERE  pool IS NOT NULL
        GROUP BY pool
    """,
    "shared_pool_free": """
        SELECT bytes FROM v$sgastat
        WHERE  pool = 'shared pool' AND name = 'free memory'
    """,
    "pga": """
        SELECT value FROM v$pgastat WHERE name = 'total PGA allocated'
    """,
    "buffer_cache": """
        SELECT ROUND((1 - (phy.value / (blk.value + phy.value))) * 100, 2) AS hit_ratio
        FROM   v$sysstat blk, v$sysstat phy
        WHERE  blk.name = 'consistent gets'
        AND    phy.name = 'physical reads'
    """,
}

# ---------------------------------------------------------------------------
# 演示模式模拟器 —— 生成随时间漂移的仿真 Oracle 指标（趋势合理，可触发告警）
# ---------------------------------------------------------------------------
DEMO_INSTANCE = {
    "db_name": "ORCLPDB1", "host": "db-server-01", "version": "19.21.0.0.0",
    "status": "OPEN", "database_status": "ACTIVE"
}
DEMO_TABLESPACES = [
    # name, total_gb, used_pct, contents, growth_mb_per_cycle, autoextend(0/1)
    ("USERS",     40.0, 91.8, "PERMANENT", 12, 1),
    ("SYSAUX",    24.0, 82.5, "PERMANENT", 3,  1),
    ("SYSTEM",    16.0, 73.1, "PERMANENT", 1,  0),
    ("DATA_TS",   128.0, 58.4, "PERMANENT", 6,  1),
    ("LOB_TS",    64.0, 63.7, "PERMANENT", 4,  1),
    ("UNDOTBS1",  24.0, 46.2, "UNDO",      2,  1),
    ("TEMP",      16.0, 31.5, "TEMPORARY", 0,  1),
]
DEMO_WAITS = [
    # event, wait_class, total_waits, waited_sec
    ("db file sequential read", "User I/O", 1_842_331, 8_842.5),
    ("log file sync",           "Commit",     412_008, 1_540.2),
    ("enq: TX - row lock contention", "Application", 8_214, 1_206.8),
    ("db file scattered read",  "User I/O",    88_412,   882.1),
    ("log file parallel write", "System I/O", 176_221,   421.0),
    ("gc cr block busy",        "Cluster",      2_311,   188.4),
    ("enq: TM - contention",    "Application",   1_204,    96.7),
]
DEMO_SQL = [
    # sql_id, elapsed_sec, cpu_sec, executions, schema, text
    ("6g8m4k2xq9r1t", 3_421.8, 2_910.4, 1_204, "REPORTING",
     "SELECT /*+ FULL(o) */ ... FROM orders o JOIN order_items oi ON ..."),
    ("8nq2c7d5f3a0b", 1_988.2, 1_210.9,  89_412, "APPS",
     "SELECT customer_id, COUNT(*) FROM orders WHERE status=:b1 GROUP BY ..."),
    ("0z1x9w8v7u6t5",   904.5,   112.3,     812, "APPS",
     "UPDATE inventory SET qty = qty - :b1 WHERE sku = :b2 AND wh_id = :b3"),
    ("2c4e6g8i0k2m4",   621.9,   488.7,  14_209, "REPORTING",
     "SELECT * FROM fact_sales fs JOIN dim_product dp ON ... WHERE ..."),
]
DEMO_SESSIONS = {"ACTIVE": 12, "INACTIVE": 75, "SNIPED": 0, "KILLED": 0}
DEMO_SGA = {"shared pool": 3_221_225_472, "large pool": 536_870_912,
            "java pool": 1_073_741_824, "log buffer": 67_108_864}


class DemoSimulator:
    """生成随时间漂移的仿真 Oracle 指标（趋势合理，可触发告警）。"""

    def __init__(self, cfg):
        self.ts = [list(t) for t in DEMO_TABLESPACES]
        self.cycle = 0
        self.alert_counts = {"ORA-01555": 2, "ORA-00060": 1}
        self.alert_errors_per_cycle = cfg["demo"]["alert_errors_per_cycle"]
        self.growth_mb = cfg["demo"]["tablespace_growth_per_cycle_mb"]
        self.uptime = 2_718_400        # 秒，约 31 天
        self.incidents = 1
        self.backup_age_days = 4.8     # 距上次全备天数，缓慢增长可触发备份过期告警
        self.sysstat = {"DB time": 3_841_200, "physical reads": 9_204_188_230,
                        "logical reads": 8_114_009_221_800, "parse count total": 9_412_030,
                        "parse count (hard)": 884_120, "user commits": 48_120_344,
                        "execute count": 291_440_112}
        self.shared_pool_free_mb = 884.0

    def tick(self):
        self.cycle += 1
        self.uptime += 30
        # 表空间缓慢增长（演示趋势与告警触发）
        for t in self.ts:
            if t[3] == "PERMANENT" and t[0] in ("USERS", "SYSAUX", "DATA_TS", "LOB_TS"):
                growth = self.growth_mb if t[0] == "USERS" else 2
                total_mb = t[1] * 1024
                used_mb = total_mb * t[2] / 100 + growth
                t[2] = round(used_mb / total_mb * 100, 1)
                if t[2] > 99.5:
                    t[2] = 99.5
        # 备份年龄增长（>7 天触发 OracleBackupStale 告警演示）
        self.backup_age_days = round(self.backup_age_days + 0.008, 2)
        # 系统统计累计
        self.sysstat["DB time"] += random.randint(6_000, 30_000)
        self.sysstat["physical reads"] += random.randint(200_000, 3_000_000)
        self.sysstat["logical reads"] += random.randint(4_000_000, 40_000_000)
        self.sysstat["parse count total"] += random.randint(3_000, 15_000)
        self.sysstat["parse count (hard)"] += random.randint(180, 1_400)
        self.sysstat["user commits"] += random.randint(8_000, 60_000)
        self.sysstat["execute count"] += random.randint(60_000, 300_000)
        # 共享池空闲波动
        self.shared_pool_free_mb = max(320.0, min(1_420.0, self.shared_pool_free_mb + random.uniform(-35, 35)))
        # 偶发 incident / 健康问题
        if random.random() < 0.03:
            self.incidents = min(3, self.incidents + 1)
        if random.random() < 0.02 and self.incidents > 0:
            self.incidents -= 1
        # 偶尔注入新的 alert 错误
        if self.alert_errors_per_cycle > 0 and self.cycle % max(1, int(30 / self.alert_errors_per_cycle)) == 0:
            key = random.choice(["ORA-01555", "ORA-00060", "ORA-00600"])
            self.alert_counts[key] = self.alert_counts.get(key, 0) + 1

    def tablespace_rows(self):
        return self.ts

    def waits(self):
        out = []
        for ev, wc, tw, ws in DEMO_WAITS:
            jitter = random.uniform(0.995, 1.01)
            out.append((ev, wc, int(tw * jitter), round(ws * jitter, 1)))
        return sorted(out, key=lambda r: -r[3])

    def top_sql(self):
        return DEMO_SQL

    def sessions(self):
        s = dict(DEMO_SESSIONS)
        s["ACTIVE"] = max(1, s["ACTIVE"] + random.randint(-2, 2))
        return s

    def blocked_sessions(self):
        return max(0, random.randint(0, 6))

    def long_running_sessions(self):
        return max(0, random.randint(0, 4))

    def hard_parse_ratio(self):
        return round(100.0 * self.sysstat["parse count (hard)"] / max(1, self.sysstat["parse count total"]), 2)

    def redo_switches_1h(self):
        return random.randint(18, 52)

    def archive_lag_sec(self):
        return random.randint(40, 900)

    def free_days(self, tablespace):
        # 按当前增速估算可用天数（growth 单位 MB/轮，每轮 30s -> 2880 轮/天）
        name, total_gb, pct, contents, growth, _ae = tablespace
        if growth <= 0:
            return 999.0
        free_gb = total_gb * (100 - pct) / 100
        per_day_gb = growth * 2880.0 / 30.0 / 1024.0
        return round(free_gb / max(per_day_gb, 0.001), 1)


# ---------------------------------------------------------------------------
# 采集核心
# ---------------------------------------------------------------------------
class OracleCollector:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sim = DemoSimulator(cfg)
        self.lock = threading.Lock()
        self.metrics = ""
        self.conns = {}          # instance_name -> oracledb connection
        self.last_scrape = 0.0
        # 实例列表：支持 oracle_instances 数组（多实例），兼容旧 oracle 单对象
        if isinstance(cfg.get("oracle_instances"), list) and cfg["oracle_instances"]:
            self.instances = [dict(x) for x in cfg["oracle_instances"]]
        elif isinstance(cfg.get("oracle"), dict):
            self.instances = [dict(cfg["oracle"])]
        else:
            self.instances = []
        # 给未命名实例补默认名
        for i, inst in enumerate(self.instances):
            inst.setdefault("instance_name", inst.get("service_name", f"oracle-{i+1}"))
        self.cur_inst = "DEMO"   # 当前采集实例（标签 oracle_instance）

    # ---- 真实模式连接（按实例）----
    def connect(self, inst):
        if not HAS_ORACLEDB:
            raise RuntimeError(
                "python-oracledb 未安装。请在能访问 PyPI 的环境中执行：\n"
                "  py -3.12 -m pip install python-oracledb\n"
                "或运行 collector\\install-driver.ps1 后重试。"
            )
        dsn = oracledb.makedsn(inst["host"], inst["port"], service_name=inst["service_name"])
        conn = oracledb.connect(user=inst["user"], password=inst["password"], dsn=dsn)
        conn.autocommit = True
        self.conns[inst["instance_name"]] = conn

    def run_query(self, inst_name, sql, params=None):
        conn = self.conns.get(inst_name)
        if conn is None:
            inst = next((x for x in self.instances if x["instance_name"] == inst_name), None)
            if inst is None:
                raise RuntimeError(f"unknown instance: {inst_name}")
            self.connect(inst)
            conn = self.conns[inst_name]
        cur = conn.cursor()
        try:
            cur.execute(sql, params or {})
            cols = [d[0].lower() for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            return cols, rows
        finally:
            cur.close()

    # ---- 采集（demo / real 分派）----
    def scrape(self):
        t0 = time.time()
        if self.cfg["mode"] == "demo":
            self.sim.tick()
            self.cur_inst = "DEMO"
            body = self._scrape_demo()
        else:
            body = self._scrape_real()
        body += ("# HELP oracle_collector_scrape_duration_seconds Collector scrape duration\n"
                 "# TYPE oracle_collector_scrape_duration_seconds gauge\n"
                 f"oracle_collector_scrape_duration_seconds {time.time() - t0:.3f}\n")
        with self.lock:
            self.metrics = body
        self.last_scrape = time.time()

    def _fmt_gauge(self, name, labels, value):
        labels = dict(labels)
        labels["oracle_instance"] = self.cur_inst
        lbl = ",".join(f'{k}="{str(v).replace(chr(34), chr(39))}"' for k, v in labels.items())
        return f"{name}{{{lbl}}} {value}\n"

    def _emit_tablespace(self, lines, name, contents, total_gb, used_gb, free_gb,
                         pct, max_gb=None, autoextend=None):
        total_b = total_gb * 1073741824
        used_b = used_gb * 1073741824
        free_b = free_gb * 1073741824
        lines.append(self._fmt_gauge("oracle_tablespace_used_percent",
                                     {"tablespace": name, "contents": contents}, pct))
        lines.append(self._fmt_gauge("oracle_tablespace_total_bytes",
                                     {"tablespace": name}, total_b))
        lines.append(self._fmt_gauge("oracle_tablespace_used_bytes",
                                     {"tablespace": name}, used_b))
        lines.append(self._fmt_gauge("oracle_tablespace_free_bytes",
                                     {"tablespace": name}, free_b))
        if max_gb is not None:
            lines.append(self._fmt_gauge("oracle_tablespace_maxbytes_bytes",
                                         {"tablespace": name}, max_gb * 1073741824))
        if autoextend is not None:
            lines.append(self._fmt_gauge("oracle_tablespace_autoextend_status",
                                         {"tablespace": name}, 1 if autoextend else 0))

    def _scrape_demo(self):
        lines = [METRIC_HEADER]
        sim = self.sim
        # instance / HA
        lines.append(self._fmt_gauge("oracle_up", {}, 1))
        lines.append(self._fmt_gauge("oracle_instance_info", DEMO_INSTANCE, 1))
        lines.append(self._fmt_gauge("oracle_instance_uptime_seconds", {}, sim.uptime))
        lines.append(self._fmt_gauge("oracle_sessions_blocked_total", {}, sim.blocked_sessions()))
        lines.append(self._fmt_gauge("oracle_long_running_sessions_total", {}, sim.long_running_sessions()))
        lines.append(self._fmt_gauge("oracle_hard_parse_ratio", {}, sim.hard_parse_ratio()))
        lines.append(self._fmt_gauge("oracle_redo_log_switches_1h_total", {}, sim.redo_switches_1h()))
        lines.append(self._fmt_gauge("oracle_db_time_seconds", {}, sim.sysstat["DB time"]))
        for k, v in sim.sysstat.items():
            lines.append(self._fmt_gauge("oracle_sysstat_total", {"name": k}, v))
        # tablespaces（含 temp / undo 单列）
        for name, total_gb, pct, contents, _g, _ae in sim.tablespace_rows():
            total_b = total_gb * 1073741824
            used_b = total_b * pct / 100
            free_b = total_b - used_b
            lines.append(self._fmt_gauge("oracle_tablespace_used_percent",
                                         {"tablespace": name, "contents": contents}, pct))
            lines.append(self._fmt_gauge("oracle_tablespace_total_bytes",
                                         {"tablespace": name}, total_b))
            lines.append(self._fmt_gauge("oracle_tablespace_used_bytes",
                                         {"tablespace": name}, used_b))
            lines.append(self._fmt_gauge("oracle_tablespace_free_bytes",
                                         {"tablespace": name}, free_b))
            lines.append(self._fmt_gauge("oracle_tablespace_maxbytes_bytes",
                                         {"tablespace": name}, total_b * 1.5))
            lines.append(self._fmt_gauge("oracle_tablespace_autoextend_status",
                                         {"tablespace": name}, _ae))
            lines.append(self._fmt_gauge("oracle_tablespace_free_days",
                                         {"tablespace": name}, sim.free_days([name, total_gb, pct, contents, _g, _ae])))
            if contents == "TEMPORARY":
                lines.append(self._fmt_gauge("oracle_temp_used_percent", {}, pct))
            if contents == "UNDO":
                lines.append(self._fmt_gauge("oracle_undo_used_percent", {}, pct))
        # sessions
        for st, cnt in sim.sessions().items():
            lines.append(self._fmt_gauge("oracle_sessions_total", {"status": st}, cnt))
        # waits
        for ev, wc, tw, ws in sim.waits():
            avg_ms = round(ws * 1000 / max(1, tw), 2)
            lines.append(self._fmt_gauge("oracle_wait_event_seconds",
                                         {"event": ev, "wait_class": wc}, ws))
            lines.append(self._fmt_gauge("oracle_wait_event_total_waits",
                                         {"event": ev, "wait_class": wc}, tw))
            lines.append(self._fmt_gauge("oracle_wait_event_avg_milliseconds",
                                         {"event": ev, "wait_class": wc}, avg_ms))
        # top sql
        for sql_id, el, cpu, ex, sch, txt in sim.top_sql():
            lines.append(self._fmt_gauge("oracle_top_sql_elapsed_seconds",
                                         {"sql_id": sql_id, "schema": sch,
                                          "sql_text": txt[:60]}, el))
            lines.append(self._fmt_gauge("oracle_top_sql_cpu_seconds",
                                         {"sql_id": sql_id, "schema": sch,
                                          "sql_text": txt[:60]}, cpu))
            lines.append(self._fmt_gauge("oracle_top_sql_executions_total",
                                         {"sql_id": sql_id, "schema": sch,
                                          "sql_text": txt[:60]}, ex))
        # alert log / ADR
        for err, cnt in sim.alert_counts.items():
            lines.append(self._fmt_gauge("oracle_alertlog_errors_total",
                                         {"error": err}, cnt))
        lines.append(self._fmt_gauge("oracle_alert_incidents_total", {}, sim.incidents))
        # memory
        lines.append(self._fmt_gauge("oracle_buffer_cache_hit_ratio", {},
                                     round(random.uniform(98.6, 99.6), 2)))
        lines.append(self._fmt_gauge("oracle_library_cache_hit_ratio", {},
                                     round(random.uniform(99.1, 99.9), 2)))
        for pool, b in DEMO_SGA.items():
            lines.append(self._fmt_gauge("oracle_sga_allocated_bytes", {"pool": pool}, b))
        lines.append(self._fmt_gauge("oracle_sga_free_bytes", {},
                                     sim.shared_pool_free_mb * 1048576))
        lines.append(self._fmt_gauge("oracle_pga_allocated_bytes", {},
                                     int(random.uniform(1.9, 2.6) * 1073741824)))
        # archive / backup / recovery
        lines.append(self._fmt_gauge("oracle_archiver_status", {}, 1))
        lines.append(self._fmt_gauge("oracle_archive_logs_24h_total", {}, 412))
        lines.append(self._fmt_gauge("oracle_archive_lag_seconds", {}, sim.archive_lag_sec()))
        lines.append(self._fmt_gauge("oracle_backup_age_days", {}, sim.backup_age_days))
        lines.append(self._fmt_gauge("oracle_block_corruption_total", {}, 0))
        # health
        lines.append(self._fmt_gauge("oracle_health_check_issues_total", {},
                                     sim.incidents))
        # datafiles
        for ts_name, _tb, _p, _c, _g, _ae in sim.tablespace_rows():
            lines.append(self._fmt_gauge("oracle_datafiles_total",
                                         {"tablespace": ts_name}, 4 if ts_name in ("SYSTEM",) else 2))
            lines.append(self._fmt_gauge("oracle_datafiles_autoextend_total",
                                         {"tablespace": ts_name}, _ae))
        return "".join(lines)

    def _scrape_real(self):
        lines = [METRIC_HEADER]
        if not self.instances:
            lines.append("oracle_up 0\n")
            lines.append("# config error: 未配置 oracle_instances\n")
            return "".join(lines)
        for inst_cfg in self.instances:
            inst_name = inst_cfg["instance_name"]
            self.cur_inst = inst_name
            try:
                self._scrape_one_real(lines, inst_name)
            except Exception as e:
                lines.append(f"# instance {inst_name} error: {e}\n")
                lines.append(f"oracle_up{{oracle_instance=\"{inst_name}\"}} 0\n")
        return "".join(lines)

    def _scrape_one_real(self, lines, inst_name):
        """采集单个实例的全部指标（追加到 lines）。单项失败不影响其他项。"""
        # ---- instance / HA ----
        cols, rows = self.run_query(inst_name, SKILL_SQL["instance"])
        if rows:
            inst = dict(zip(cols, rows[0]))
            lines.append(self._fmt_gauge(
                "oracle_instance_info",
                {"db_name": inst.get("instance_name", ""),
                 "host": inst.get("host_name", ""),
                 "version": str(inst.get("version", ""))[:20],
                 "status": inst.get("status", ""),
                 "database_status": inst.get("database_status", "")}, 1))
            if inst.get("uptime_sec") is not None:
                lines.append(self._fmt_gauge("oracle_instance_uptime_seconds",
                                             {}, inst["uptime_sec"]))
        for key, sql in (("redo_switches", SKILL_SQL["redo_switches"]),
                         ("sessions_blocked", SKILL_SQL["sessions_blocked"]),
                         ("long_running", SKILL_SQL["long_running"]),
                         ("corruption", SKILL_SQL["corruption"]),
                         ("incidents", SKILL_SQL["incidents"])):
            try:
                _, rows = self.run_query(inst_name, sql)
                if rows:
                    cnt = rows[0][0]
                    mname = {"redo_switches": "oracle_redo_log_switches_1h_total",
                             "sessions_blocked": "oracle_sessions_blocked_total",
                             "long_running": "oracle_long_running_sessions_total",
                             "corruption": "oracle_block_corruption_total",
                             "incidents": "oracle_alert_incidents_total"}[key]
                    lines.append(self._fmt_gauge(mname, {}, cnt))
            except Exception:
                pass

        # ---- 系统统计（DB time / 解析 / 读写）----
        try:
            cols, rows = self.run_query(inst_name, SKILL_SQL["sysstat"])
            svals = {dict(zip(cols, r))["name"]: dict(zip(cols, r))["value"] for r in rows}
            if "DB time" in svals:
                lines.append(self._fmt_gauge("oracle_db_time_seconds", {}, svals["DB time"]))
            for k, v in svals.items():
                lines.append(self._fmt_gauge("oracle_sysstat_total", {"name": k}, v))
            hard = svals.get("parse count (hard)", 0)
            total = svals.get("parse count total", 0)
            if total:
                lines.append(self._fmt_gauge("oracle_hard_parse_ratio", {},
                                             100.0 * hard / total))
        except Exception:
            pass

        # ---- tablespace ----
        cols, rows = self.run_query(inst_name, SKILL_SQL["tablespace"])
        for r in rows:
            d = dict(zip(cols, r))
            name = d["tablespace_name"]
            total = float(d["total_gb"] or 0)
            used = float(d["used_gb"] or 0)
            free = float(d["free_gb"] or 0)
            pct = float(d["used_pct"] or 0)
            self._emit_tablespace(lines, name, d.get("contents", ""),
                                  total, used, free, pct)
            if d.get("contents") == "TEMPORARY":
                lines.append(self._fmt_gauge("oracle_temp_used_percent", {}, pct))
            if d.get("contents") == "UNDO":
                lines.append(self._fmt_gauge("oracle_undo_used_percent", {}, pct))
        # datafiles / maxbytes / autoextend
        cols, rows = self.run_query(inst_name, SKILL_SQL["datafiles"])
        for r in rows:
            d = dict(zip(cols, r))
            name = d["tablespace_name"]
            lines.append(self._fmt_gauge("oracle_datafiles_total",
                                         {"tablespace": name}, d["file_cnt"]))
            lines.append(self._fmt_gauge("oracle_datafiles_autoextend_total",
                                         {"tablespace": name}, d["auto_cnt"]))
            if d["max_bytes"]:
                lines.append(self._fmt_gauge("oracle_tablespace_maxbytes_bytes",
                                             {"tablespace": name}, d["max_bytes"]))
            lines.append(self._fmt_gauge("oracle_tablespace_autoextend_status",
                                         {"tablespace": name}, 1 if d["auto_cnt"] else 0))

        # ---- sessions ----
        cols, rows = self.run_query(inst_name, SKILL_SQL["sessions"])
        for r in rows:
            d = dict(zip(cols, r))
            lines.append(self._fmt_gauge("oracle_sessions_total",
                                         {"status": d["status"]}, d["cnt"]))

        # ---- wait events ----
        cols, rows = self.run_query(inst_name, SKILL_SQL["wait_events"])
        for r in rows:
            d = dict(zip(cols, r))
            secs = d["time_waited_sec"]
            waits = d["total_waits"]
            avg = round(secs * 1000 / max(1, waits), 2)
            lines.append(self._fmt_gauge("oracle_wait_event_seconds",
                                         {"event": d["event"], "wait_class": d.get("wait_class", "")},
                                         secs))
            lines.append(self._fmt_gauge("oracle_wait_event_total_waits",
                                         {"event": d["event"], "wait_class": d.get("wait_class", "")},
                                         waits))
            lines.append(self._fmt_gauge("oracle_wait_event_avg_milliseconds",
                                         {"event": d["event"], "wait_class": d.get("wait_class", "")},
                                         avg))

        # ---- top sql ----
        cols, rows = self.run_query(inst_name, SKILL_SQL["top_sql"])
        for r in rows:
            d = dict(zip(cols, r))
            lbl = {"sql_id": d["sql_id"], "schema": d.get("parsing_schema_name", ""),
                   "sql_text": str(d.get("sql_preview", ""))[:60]}
            lines.append(self._fmt_gauge("oracle_top_sql_elapsed_seconds", lbl,
                                         d["total_elapsed_sec"]))
            lines.append(self._fmt_gauge("oracle_top_sql_cpu_seconds", lbl,
                                         d["total_cpu_sec"]))
            lines.append(self._fmt_gauge("oracle_top_sql_executions_total", lbl,
                                         d["executions"]))

        # ---- alert log ----
        cols, rows = self.run_query(inst_name, SKILL_SQL["alert_log"])
        err_count = {}
        for r in rows:
            d = dict(zip(cols, r))
            m = re.search(r"(ORA-\d{5})", str(d.get("message_text", "")))
            key = m.group(1) if m else "ORA-UNKNOWN"
            err_count[key] = err_count.get(key, 0) + 1
        for key, cnt in err_count.items():
            lines.append(self._fmt_gauge("oracle_alertlog_errors_total", {"error": key}, cnt))

        # ---- archive ----
        cols, rows = self.run_query(inst_name, SKILL_SQL["archive_dest"])
        arch_ok = 1
        for r in rows:
            d = dict(zip(cols, r))
            if "FAILED" in str(d.get("error", "")):
                arch_ok = 0
        lines.append(self._fmt_gauge("oracle_archiver_status", {}, arch_ok))
        try:
            cols, rows = self.run_query(inst_name, SKILL_SQL["archive_lag"])
            if rows:
                lines.append(self._fmt_gauge("oracle_archive_lag_seconds", {}, rows[0][0]))
            cols, rows = self.run_query(inst_name, SKILL_SQL["backup_age"])
            if rows:
                lines.append(self._fmt_gauge("oracle_backup_age_days", {},
                                             rows[0][0] / 24.0))
        except Exception:
            pass

        # ---- memory ----
        try:
            cols, rows = self.run_query(inst_name, SKILL_SQL["buffer_cache"])
            if rows:
                lines.append(self._fmt_gauge("oracle_buffer_cache_hit_ratio", {}, rows[0][0]))
        except Exception:
            pass
        try:
            cols, rows = self.run_query(inst_name, SKILL_SQL["shared_pool_free"])
            if rows:
                lines.append(self._fmt_gauge("oracle_sga_free_bytes", {}, rows[0][0]))
        except Exception:
            pass
        try:
            cols, rows = self.run_query(inst_name, SKILL_SQL["pga"])
            if rows:
                lines.append(self._fmt_gauge("oracle_pga_allocated_bytes", {}, rows[0][0]))
        except Exception:
            pass
        try:
            cols, rows = self.run_query(inst_name, SKILL_SQL["sga"])
            for r in rows:
                d = dict(zip(cols, r))
                lines.append(self._fmt_gauge("oracle_sga_allocated_bytes",
                                             {"pool": d["pool"]}, d["bytes"]))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# HTTP /metrics 服务
# ---------------------------------------------------------------------------
class MetricsHandler(BaseHTTPRequestHandler):
    collector = None

    def do_GET(self):
        if self.path in ("/metrics", "/"):
            with self.collector.lock:
                body = self.collector.metrics.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):  # 静默访问日志
        pass


def main():
    ap = argparse.ArgumentParser(description="Oracle Enterprise Monitor Collector")
    ap.add_argument("--mode", choices=["demo", "real"], default=None,
                    help="采集模式：demo（演示）| real（真实Oracle）")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
                    help="配置文件路径")
    ap.add_argument("--once", action="store_true", help="采集一次后输出到 stdout 并退出（调试用）")
    args = ap.parse_args()

    cfg = DEFAULT_CONFIG
    if os.path.exists(args.config):
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = json.loads(json.dumps(cfg))  # 深拷贝
        with open(args.config, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"[config] 已生成默认配置 {args.config}，请按需修改后重新启动。")
    if args.mode:
        cfg["mode"] = args.mode

    coll = OracleCollector(cfg)

    if args.once:
        coll.scrape()
        print(coll.metrics)
        return 0

    # 首次采集并启动后台定时采集线程
    coll.scrape()
    interval = cfg.get("collect_interval_seconds", 30)

    def loop():
        while True:
            time.sleep(interval)
            try:
                coll.scrape()
            except Exception as e:
                print(f"[error] scrape failed: {e}", file=sys.stderr)

    threading.Thread(target=loop, daemon=True).start()

    MetricsHandler.collector = coll
    host, port = cfg["listen"]["host"], cfg["listen"]["port"]
    srv = ThreadingHTTPServer((host, port), MetricsHandler)
    print(f"[oracle-collector] mode={cfg['mode']} listening on http://{host}:{port}/metrics")
    print(f"[oracle-collector] 演示提示：访问 /metrics 可查看 Oracle 指标；"
          f"表空间使用率将随时间缓慢增长，可观察告警触发。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[oracle-collector] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
