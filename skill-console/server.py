#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle Skill Console —— oracle/skills 技能选择前端后端服务
============================================================
实现 Oracle 博客《Route, Don't Flood》的路由思想：
  - 把 db/SKILL.md 路由表可视化，按角色 / 按任务选择技能
  - 查看单个技能详情（SQL / 最佳实践 / 常见坑 / 版本约束）
  - 一键执行技能诊断（复用 skills_engine），手册落盘 reports/
  - 聚合监控状态（采集器指标 + Prometheus 告警）与技能联动

API：
  GET  /                    前端页面
  GET  /api/skills          技能地图（目录 + 子技能）
  GET  /api/skill?path=...  技能详情
  GET  /api/routes          按角色/任务推荐路由
  GET  /api/alertmap        告警 -> 技能 映射
  POST /api/run             执行技能诊断 {alert_type, context}
  GET  /api/reports         诊断报告历史
  GET  /api/status          监控状态聚合

运行：python skill-console/server.py --port 8090 --repo <repo 绝对路径>
"""

import argparse
import json
import os
import re
import sys
import threading
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONSOLE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = os.path.normpath(os.path.join(CONSOLE_DIR, "..", "oracle-skills"))
REPORTS_DEFAULT = os.path.normpath(os.path.join(CONSOLE_DIR, "..", "collector", "reports"))

# ---- 按角色推荐路由（来源：Oracle 博客 Route Don't Flood + db/SKILL.md）----
PERSONA_ROUTES = [
    {
        "persona": "DBA / 数据库运维",
        "icon": "🛠",
        "desc": "性能诊断与安全加固是 DBA 的第一战场：先 performance 再 security。",
        "steps": [
            {"name": "性能技能（performance）", "detail": "explain-plan → wait-events → optimizer-stats → awr-reports",
             "dirs": ["db/performance"]},
            {"name": "监控技能（monitoring）", "detail": "space-management / alert-log-analysis / top-sql-queries",
             "dirs": ["db/monitoring"]},
            {"name": "安全技能（security）", "detail": "权限设计、审计、加密的 Oracle 术语与最小权限落地",
             "dirs": ["db/security"]},
        ],
    },
    {
        "persona": "应用开发工程师",
        "icon": "💻",
        "desc": "先定框架层连接与驱动，再按需补应用特性。",
        "steps": [
            {"name": "框架技能（frameworks）", "detail": "Spring JPA / Django / SQLAlchemy / MyBatis 等连接配置与方言选择",
             "dirs": ["db/frameworks"]},
            {"name": "应用开发技能（appdev）", "detail": "JSON / Spatial / Text / 连接池 / 事务的 Oracle 专属细节",
             "dirs": ["db/appdev"]},
        ],
    },
    {
        "persona": "AI 工程师",
        "icon": "🤖",
        "desc": "Agent 碰库先学行为约束，再做 AI 特性（向量检索 / NL2SQL）。",
        "steps": [
            {"name": "Agent 行为（agent）", "detail": "schema-discovery → destructive-op-guards → idempotency-patterns",
             "dirs": ["db/agent"]},
            {"name": "AI 特性（features）", "detail": "ai-profiles → vector-search → dbms-vector（注意 26ai 版本门槛）",
             "dirs": ["db/features"]},
        ],
    },
    {
        "persona": "迁移负责人",
        "icon": "🚚",
        "desc": "迁移评估与交付机制是同一件事的两半。",
        "steps": [
            {"name": "迁移技能（migrations）", "detail": "migration-assessment → 各源库 migrate-* → 割接策略",
             "dirs": ["db/migrations"]},
            {"name": "DevOps 技能（devops）", "detail": "schema-migrations / online operations / EBR / 测试",
             "dirs": ["db/devops"]},
        ],
    },
]

# ---- 按任务推荐路由（来源：db/SKILL.md Common Multi-Step Flows）----
TASK_ROUTES = [
    {"task": "慢查询诊断", "steps": ["explain-plan", "wait-events", "optimizer-stats", "awr-reports"],
     "dir": "db/performance", "desc": "先读真实执行计划（DISPLAY_CURSOR），计划正常再查等待事件，估算偏差先修统计信息。"},
    {"task": "表空间告警处理", "steps": ["space-management", "alert-log-analysis"], "dir": "db/monitoring",
     "desc": "DBA_TABLESPACE_USAGE_METRICS 分级（95/85/75），评估自动扩展与 HWM 后再扩容/收缩。"},
    {"task": "RAG on Oracle", "steps": ["ai-profiles", "vector-search", "dbms-vector"], "dir": "db/features",
     "desc": "先定 AI Profile（模型与可见对象），再学检索与编排，注意 26ai 版本门槛。"},
    {"task": "Agent 安全变更", "steps": ["schema-discovery", "destructive-op-guards", "idempotency-patterns", "schema-migrations"],
     "dir": "db/agent|db/migrations", "desc": "先发现，再防损，后幂等，最后才进受审计的迁移流程。"},
    {"task": "SQLcl MCP 接入", "steps": ["sqlcl-basics", "deep-data-security", "sqlcl-mcp-server"], "dir": "db/sqlcl|db/security",
     "desc": "保存连接 → 最小权限 → 启动 MCP，路由完成后再进入执行层。"},
]


class SkillsIndex:
    """索引 oracle/skills 仓库：路由表 + 目录树 + 子技能元数据。"""

    def __init__(self, repo):
        self.repo = repo
        self.categories = []      # [{topic, dir, desc}]
        self.skills = {}          # relpath -> {title, file, size}
        self._load()

    def _load(self):
        skill_md = os.path.join(self.repo, "db", "SKILL.md")
        if os.path.exists(skill_md):
            with open(skill_md, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            # 解析 Category Routing 表格
            for m in re.finditer(r"\|\s*([^|]+?)\s*\|\s*`?([^`|]+)`?\s*\|", text):
                pass
            in_table = False
            for line in text.splitlines():
                if line.strip().startswith("| Topic | Directory |"):
                    in_table = True
                    continue
                if in_table and re.match(r"^\|[-:\s|]+$", line):
                    continue
                if in_table:
                    if not line.strip().startswith("|"):
                        in_table = False
                        continue
                    cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
                    if len(cells) >= 2 and cells[0] and cells[1].startswith("db/"):
                        self.categories.append({"topic": cells[0], "dir": cells[1], "desc": cells[2] if len(cells) > 2 else ""})
        # 遍历 db 目录收集子技能
        db = os.path.join(self.repo, "db")
        if os.path.isdir(db):
            for root, _dirs, files in os.walk(db):
                for fn in files:
                    if fn.endswith(".md") and fn != "SKILL.md":
                        p = os.path.join(root, fn)
                        rel = os.path.relpath(p, self.repo).replace("\\", "/")
                        title = ""
                        with open(p, "r", encoding="utf-8", errors="replace") as f:
                            first = f.readline()
                            m = re.match(r"^#\s+(.+)$", first)
                            if m:
                                title = m.group(1).strip()
                        self.skills[rel] = {"title": title or fn.replace(".md", ""), "file": rel,
                                            "size": os.path.getsize(p)}

    def skill_detail(self, rel):
        rel = rel.replace("\\", "/").lstrip("/")
        p = os.path.normpath(os.path.join(self.repo, rel))
        if not p.startswith(os.path.normpath(self.repo)) or not os.path.isfile(p):
            return None
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        title = ""
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if m:
            title = m.group(1).strip()
        sql_blocks = re.findall(r"```sql\s*\n(.*?)```", text, re.S)
        sections = []
        for m in re.finditer(r"^##\s+(.+)$", text, re.M):
            sections.append(m.group(1).strip())
        bp = []
        m = re.search(r"## Best Practices\s*\n(.*?)(?=\n## |\Z)", text, re.S)
        if m:
            bp = [x.strip().lstrip("123456789. ").strip() for x in m.group(1).strip().splitlines()
                  if x.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "- "))]
        cm = []
        m = re.search(r"## Common Mistakes and How to Avoid Them\s*\n(.*?)(?=\n## |\Z)", text, re.S)
        if m:
            cm = [x.strip() for x in m.group(1).strip().splitlines() if x.strip() and not x.strip().startswith("**")]
        ver = ""
        m = re.search(r"## Oracle Version Notes.*?\n(.*?)(?=\n## |\Z)", text, re.S)
        if m:
            ver = " ".join(l.strip() for l in m.group(1).splitlines() if l.strip())
        return {"title": title, "file": rel, "sections": sections,
                "sql_blocks": [b.strip() for b in sql_blocks],
                "best_practices": bp, "common_mistakes": cm, "version_notes": ver,
                "size": len(text)}


class ConsoleState:
    def __init__(self, repo, reports_dir, collector_url, prometheus_url):
        self.index = SkillsIndex(repo)
        sys.path.insert(0, os.path.join(CONSOLE_DIR, "..", "collector"))
        from skills_engine import SkillsEngine, ALERT_ROUTES
        self.engine = SkillsEngine(repo)
        self.alert_routes = ALERT_ROUTES
        self.reports_dir = reports_dir
        os.makedirs(reports_dir, exist_ok=True)
        self.collector_url = collector_url
        self.prometheus_url = prometheus_url
        self._alertmap = [
            {"alert": "OracleTablespaceCritical/Warning/Watch", "alert_type": "tablespace",
             "skill": "db/monitoring/space-management.md", "threshold": ">=95 / >=85 / >=75"},
            {"alert": "OracleAlertLogCriticalError", "alert_type": "alertlog",
             "skill": "db/monitoring/alert-log-analysis.md", "threshold": "任何 ORA 错误"},
            {"alert": "OracleInstanceDown", "alert_type": "instance_down",
             "skill": "db/monitoring/alert-log-analysis.md", "threshold": "oracle_up == 0"},
            {"alert": "OracleSlowSQL", "alert_type": "slow_sql",
             "skill": "db/monitoring/top-sql-queries.md", "threshold": "Top SQL 耗时 > 30min"},
            {"alert": "OracleTopWaitEvent", "alert_type": "wait_events",
             "skill": "db/performance/wait-events.md", "threshold": "Top 等待 > 1h"},
            {"alert": "OracleBufferCacheHitRatioLow", "alert_type": "memory",
             "skill": "db/performance/memory-tuning.md", "threshold": "命中率 < 95%"},
            {"alert": "OracleArchiverFailed", "alert_type": "alertlog",
             "skill": "db/monitoring/alert-log-analysis.md", "threshold": "归档失败"},
        ]

    # ---- 监控状态聚合 ----
    def status(self):
        out = {"collector": None, "alerts": [], "metrics": {}}
        try:
            with urllib.request.urlopen(self.collector_url + "/metrics", timeout=3) as r:
                text = r.read().decode("utf-8", "replace")
            out["collector"] = "up"
            for line in text.splitlines():
                if line.startswith("oracle_up{"):
                    out["metrics"]["oracle_up"] = line.split()[-1]
                elif line.startswith("oracle_tablespace_used_percent{"):
                    m = re.match(r'^oracle_tablespace_used_percent\{tablespace="([^"]+)".*\}\s+([\d.]+)$', line)
                    if m:
                        out["metrics"].setdefault("tablespaces", {})[m.group(1)] = float(m.group(2))
                elif line.startswith("oracle_alertlog_errors_total{"):
                    m = re.match(r'^oracle_alertlog_errors_total\{error="([^"]+)".*\}\s+([\d.]+)$', line)
                    if m:
                        out["metrics"].setdefault("ora_errors", {})[m.group(1)] = int(float(m.group(2)))
                elif line.startswith("oracle_archive_logs_24h_total"):
                    out["metrics"]["archives_24h"] = line.split()[-1]
        except Exception:
            out["collector"] = "down"
        try:
            with urllib.request.urlopen(self.prometheus_url + "/api/v1/alerts", timeout=3) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            for a in data.get("data", {}).get("alerts", []):
                out["alerts"].append({"name": a["labels"].get("alertname"),
                                      "state": a["state"], "severity": a["labels"].get("severity"),
                                      "summary": a.get("annotations", {}).get("summary", "")})
        except Exception:
            pass
        return out

    def run_diagnosis(self, alert_type, context=None):
        try:
            runbook = self.engine.runbook(alert_type, context)
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        fname = os.path.join(self.reports_dir, f"{ts}_{alert_type}.txt")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(runbook)
        return {"ok": True, "file": os.path.basename(fname), "runbook": runbook}

    def reports(self):
        items = []
        if os.path.isdir(self.reports_dir):
            for fn in sorted(os.listdir(self.reports_dir), reverse=True):
                if fn.endswith(".txt"):
                    p = os.path.join(self.reports_dir, fn)
                    items.append({"name": fn, "size": os.path.getsize(p),
                                  "time": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S"),
                                  "content": open(p, "r", encoding="utf-8", errors="replace").read()})
        return items


class Handler(BaseHTTPRequestHandler):
    state = None

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        qs = {}
        if "?" in self.path:
            for kv in self.path.split("?", 1)[1].split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    qs[k] = urllib.parse.unquote_plus(v)
        try:
            if path == "/" or path == "/index.html":
                html = open(os.path.join(CONSOLE_DIR, "index.html"), "r", encoding="utf-8").read()
                self._send(200, html, "text/html; charset=utf-8")
            elif path == "/api/skills":
                self._send(200, json.dumps({"categories": self.state.index.categories,
                                            "skills": self.state.index.skills}, ensure_ascii=False))
            elif path == "/api/skill":
                d = self.state.index.skill_detail(qs.get("path", ""))
                if d is None:
                    self._send(404, json.dumps({"error": "skill not found"}, ensure_ascii=False))
                else:
                    self._send(200, json.dumps(d, ensure_ascii=False))
            elif path == "/api/routes":
                self._send(200, json.dumps({"personas": PERSONA_ROUTES, "tasks": TASK_ROUTES}, ensure_ascii=False))
            elif path == "/api/alertmap":
                self._send(200, json.dumps(self.state._alertmap, ensure_ascii=False))
            elif path == "/api/reports":
                self._send(200, json.dumps(self.state.reports(), ensure_ascii=False))
            elif path == "/api/status":
                self._send(200, json.dumps(self.state.status(), ensure_ascii=False))
            else:
                self._send(404, json.dumps({"error": "not found"}, ensure_ascii=False))
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))

    def do_POST(self):
        if self.path == "/api/run":
            try:
                n = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(n).decode("utf-8"))
                res = self.state.run_diagnosis(payload.get("alert_type", ""),
                                               payload.get("context"))
                self._send(200 if res.get("ok") else 400, json.dumps(res, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}, ensure_ascii=False))

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description="Oracle Skill Console")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--reports-dir", default=REPORTS_DEFAULT)
    ap.add_argument("--collector", default="http://127.0.0.1:9161")
    ap.add_argument("--prometheus", default="http://127.0.0.1:9090")
    args = ap.parse_args()

    Handler.state = ConsoleState(args.repo, args.reports_dir, args.collector, args.prometheus)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[skill-console] http://127.0.0.1:{args.port}  技能库: {args.repo}")
    print(f"[skill-console] 技能索引: {len(Handler.state.index.skills)} 个技能 / "
          f"{len(Handler.state.index.categories)} 个分类")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[skill-console] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
