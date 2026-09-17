#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle Alert Handler —— Alertmanager 与 oracle/skills 技能引擎的桥接服务
=========================================================================
职责：
  1. 接收 Alertmanager webhook 告警（POST /alert-handler）
  2. 按告警名称路由到 oracle/skills 技能（复用 skills_engine）
  3. 自动生成 DBA 诊断手册，落盘到 reports/ 目录
  4. 可扩展：将诊断结论推送到钉钉/企业微信（webhook 占位）

运行：python alert_handler.py --port 8080 --repo ..\..\oracle-skills
配套：alertmanager/alertmanager.yml 中 webhook_configs.url 指向本服务
"""

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime

# 告警名 -> 技能告警类型 映射（与 skills_engine.ALERT_ROUTES 对应）
ALERT_SKILL_MAP = {
    "OracleInstanceDown": "instance_down",
    "OracleTablespaceCritical": "tablespace",
    "OracleTablespaceWarning": "tablespace",
    "OracleTablespaceWatch": "tablespace",
    "OracleAlertLogCriticalError": "alertlog",
    "OracleTopWaitEvent": "wait_events",
    "OracleSlowSQL": "slow_sql",
    "OracleBufferCacheHitRatioLow": "memory",
    "OracleArchiverFailed": "alertlog",
    "OracleArchiveLogVolumeSpike": "alertlog",
    "OracleCollectorScrapeSlow": "alertlog",
}


class AlertHandlerServer:
    def __init__(self, repo_root, report_dir):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from skills_engine import SkillsEngine
        self.engine = SkillsEngine(repo_root)
        self.report_dir = report_dir
        os.makedirs(report_dir, exist_ok=True)
        self.last_alerts = {}

    def handle_alert(self, payload):
        alerts = payload.get("alerts", [])
        for a in alerts:
            labels = a.get("labels", {})
            name = labels.get("alertname", "unknown")
            status = a.get("status", "firing")
            alert_type = ALERT_SKILL_MAP.get(name, None)
            if alert_type is None:
                print(f"[handler] 跳过无技能映射告警: {name}", flush=True)
                continue

            context = {
                "alert": name,
                "status": status,
                "severity": labels.get("severity", ""),
                "instance": labels.get("instance", ""),
                "tablespace": labels.get("tablespace", ""),
                "error": labels.get("error", ""),
                "sql_id": labels.get("sql_id", ""),
                "event": labels.get("event", ""),
                "summary": a.get("annotations", {}).get("summary", ""),
            }
            if status == "resolved":
                print(f"[handler] {name} 已恢复，无需诊断", flush=True)
                continue
            try:
                runbook = self.engine.runbook(alert_type, context)
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                safe = name.replace(" ", "_")
                fname = os.path.join(self.report_dir, f"{ts}_{safe}.txt")
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(runbook)
                print(f"[handler] 告警 {name} -> 技能 {alert_type}，诊断手册已生成: {fname}", flush=True)
                print(runbook[:400] + "\n...", flush=True)
            except Exception as e:
                print(f"[handler] 诊断失败 {name}: {e}", flush=True)


class Handler(BaseHTTPRequestHandler):
    server_ref = None

    def do_POST(self):
        if self.path == "/alert-handler":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8"))
                threading.Thread(target=self.server_ref.handle_alert, args=(payload,), daemon=True).start()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception as e:
                print(f"[handler] 解析失败: {e}", flush=True)
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"status":"error"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description="Oracle Alert Handler")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                   "..", "..", "oracle-skills"))
    ap.add_argument("--report-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports"))
    args = ap.parse_args()

    srv = AlertHandlerServer(args.repo, args.report_dir)
    Handler.server_ref = srv
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[alert-handler] listening on http://127.0.0.1:{args.port}/alert-handler", flush=True)
    print(f"[alert-handler] 技能库: {args.repo}", flush=True)
    print(f"[alert-handler] 诊断报告目录: {args.report_dir}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[alert-handler] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
