#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle Skills Engine
====================
oracle/skills 技能库消费引擎 —— 让 Oracle 官方 DBA 技能真正"用起来"。

职责：
  1. 索引克隆的 oracle/skills 仓库（db/monitoring、db/performance 等目录）
  2. 解析每个技能文件的 SQL 代码块、Best Practices、Common Mistakes
  3. 提供告警类型 -> 技能文件 -> 诊断步骤 的路由
  4. 生成标准化 DBA 诊断手册（可在告警触发时由 Agent / 人工使用）

用法：
  python skills_engine.py --list                      列出全部可用技能
  python skills_engine.py --alert tablespace         输出表空间告警诊断手册
  python skills_engine.py --alert alertlog --detail
  python skills_engine.py --alert wait_events --json
"""

import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# 告警类型 -> 技能文件 路由表（与 Prometheus 告警规则一一对应）
# ---------------------------------------------------------------------------
ALERT_ROUTES = {
    "instance_down": {
        "skill": "db/monitoring/alert-log-analysis.md",
        "title": "实例失联 / 宕机诊断",
        "summary": "检查监听、alert.log、v$instance 状态与 ORA 错误，定位实例崩溃原因。",
    },
    "tablespace": {
        "skill": "db/monitoring/space-management.md",
        "title": "表空间空间告警诊断",
        "summary": "基于 DBA_TABLESPACE_USAGE_METRICS 评估使用率、自动扩展、HWM 与碎片，"
                   "按阈值分级（>=95 CRITICAL / >=85 WARNING / >=75 WATCH）给出处理方案。",
    },
    "alertlog": {
        "skill": "db/monitoring/alert-log-analysis.md",
        "title": "Alert 日志 ORA 错误诊断",
        "summary": "通过 V$DIAG_ALERT_EXT 抓取 ORA 错误，区分严重级别，关联 trace 文件定位根因。",
    },
    "slow_sql": {
        "skill": "db/monitoring/top-sql-queries.md",
        "title": "慢 SQL / Top SQL 诊断",
        "summary": "基于 V$SQLAREA / V$SQL 按 CPU / 耗时 / 物理读定位 Top SQL，结合执行计划优化。",
    },
    "wait_events": {
        "skill": "db/performance/wait-events.md",
        "title": "等待事件诊断",
        "summary": "分析 V$SYSTEM_EVENT / V$SESSION_WAIT 等待事件，按等待类定位性能瓶颈。",
    },
    "awr": {
        "skill": "db/performance/awr-reports.md",
        "title": "AWR 性能基线诊断",
        "summary": "生成 AWR 报告、对比快照、分析负载趋势与 Top 等待/事件/SQL。",
    },
    "ash": {
        "skill": "db/performance/ash-analysis.md",
        "title": "ASH 实时会话诊断",
        "summary": "利用 ASH 采样定位活跃会话、阻塞链与热点 SQL。",
    },
    "memory": {
        "skill": "db/performance/memory-tuning.md",
        "title": "内存调优诊断",
        "summary": "检查 SGA/PGA 配置、buffer cache 命中率与共享池压力。",
    },
    "backup": {
        "skill": "db/backup-recovery/",
        "title": "备份恢复诊断",
        "summary": "RMAN 备份状态、归档日志可用性、恢复策略检查。",
    },
}


class SkillsEngine:
    def __init__(self, repo_root):
        self.repo_root = repo_root
        self.index = {}   # alert_type -> {skill_file, parsed}

    # ---- 解析技能 markdown ----
    @staticmethod
    def parse_markdown(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        title = ""
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if m:
            title = m.group(1).strip()
        # SQL 代码块
        sql_blocks = re.findall(r"```sql\s*\n(.*?)```", text, re.S)
        # Best Practices 区块
        bp = []
        m = re.search(r"## Best Practices\s*\n(.*?)(?=\n## |\Z)", text, re.S)
        if m:
            bp = [x.strip().lstrip("- ").strip() for x in m.group(1).strip().splitlines()
                  if x.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "- "))]
        # Common Mistakes 区块
        cm = []
        m = re.search(r"## Common Mistakes and How to Avoid Them\s*\n(.*?)(?=\n## |\Z)", text, re.S)
        if m:
            cm = [x.strip() for x in m.group(1).strip().splitlines() if x.strip()]
        # 版本注意事项
        ver = ""
        m = re.search(r"## Oracle Version Notes.*?\n(.*?)(?=\n## |\Z)", text, re.S)
        if m:
            ver = m.group(1).strip()
        return {"title": title, "sql_blocks": sql_blocks,
                "best_practices": bp, "common_mistakes": cm, "version_notes": ver,
                "file": os.path.relpath(path, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))}

    def load_alert(self, alert_type):
        if alert_type not in ALERT_ROUTES:
            raise KeyError(f"未知告警类型: {alert_type}，可用: {list(ALERT_ROUTES)}")
        route = ALERT_ROUTES[alert_type]
        skill_rel = route["skill"]
        base = os.path.join(self.repo_root, skill_rel)
        if os.path.isdir(base):
            # 目录型技能：优先取目录内主文档
            candidates = sorted(os.listdir(base))
            md = [c for c in candidates if c.endswith(".md")]
            path = os.path.join(base, md[0]) if md else base
        else:
            path = base
        parsed = self.parse_markdown(path) if os.path.exists(path) else None
        return {"alert_type": alert_type, "title": route["title"],
                "summary": route["summary"], "skill_file": skill_rel,
                "parsed": parsed}

    def list_skills(self):
        out = []
        for at, route in ALERT_ROUTES.items():
            out.append({"alert_type": at, "title": route["title"],
                        "skill": route["skill"], "summary": route["summary"]})
        return out

    # ---- 生成诊断手册 ----
    def runbook(self, alert_type, context=None):
        info = self.load_alert(alert_type)
        p = info["parsed"]
        lines = []
        lines.append("=" * 78)
        lines.append(f"【Oracle 技能诊断手册】{info['title']}")
        lines.append(f"告警类型      : {alert_type}")
        lines.append(f"技能来源      : oracle/skills -> {info['skill_file']}")
        lines.append(f"技能摘要      : {info['summary']}")
        if context:
            lines.append(f"告警上下文    : {json.dumps(context, ensure_ascii=False)}")
        lines.append("=" * 78)
        if p is None:
            lines.append("[技能文件缺失] 请确认 oracle-skills 仓库已克隆，路径: %s" % self.repo_root)
            return "\n".join(lines)
        lines.append(f"\n技能文档: {p['title']}")
        if p["sql_blocks"]:
            lines.append(f"\n[诊断 SQL] 共 {len(p['sql_blocks'])} 条（来源：官方技能库）")
            for i, sql in enumerate(p["sql_blocks"], 1):
                clean = "\n".join(l for l in sql.strip().splitlines() if l.strip())
                lines.append(f"\n  --- SQL {i} ---")
                for l in clean.splitlines():
                    lines.append("  " + l)
        if p["best_practices"]:
            lines.append(f"\n[最佳实践] 共 {len(p['best_practices'])} 条")
            for i, bp in enumerate(p["best_practices"], 1):
                lines.append(f"  {i}. {bp}")
        if p["common_mistakes"]:
            lines.append(f"\n[常见坑（必须规避）] 共 {len(p['common_mistakes'])} 条")
            for i, cm in enumerate(p["common_mistakes"], 1):
                lines.append(f"  {i}. {cm}")
        if p["version_notes"]:
            lines.append("\n[版本注意事项]")
            for l in p["version_notes"].splitlines():
                if l.strip():
                    lines.append("  " + l)
        lines.append("\n" + "=" * 78)
        lines.append("下一步建议（按此顺序执行）:")
        if alert_type == "tablespace":
            lines.append("  1. 执行 SQL 1 确认当前使用率与阈值级别（>=95 立即处理，>=85 当日处理）")
            lines.append("  2. 检查是否开启自动扩展、数据文件是否达 MAXSIZE 上限")
            lines.append("  3. 定位占用空间最大的段（dba_segments Top 30），评估 HWM 回收")
            lines.append("  4. 低峰期执行 SHRINK SPACE COMPACT -> SHRINK SPACE，避免业务高峰 DDL")
        elif alert_type in ("alertlog", "instance_down"):
            lines.append("  1. 用 V$DIAG_ALERT_EXT 确认错误码与发生时间，关联 trace 文件")
            lines.append("  2. ORA-00600 / ORA-07445 属内部错误，收集参数与 trace 提交 Oracle 支持")
            lines.append("  3. 检查 'checkpoint not complete' 等非 ORA 关键信息，评估 redo 配置")
        elif alert_type == "slow_sql":
            lines.append("  1. 从 Top SQL 列表按耗时/CPU/物理读定位目标 SQL")
            lines.append("  2. 对目标 SQL 生成执行计划（explain plan），检查全表扫描与索引缺失")
            lines.append("  3. 结合 AWR 历史对比负载趋势，评估优化器统计信息新鲜度")
        elif alert_type == "wait_events":
            lines.append("  1. 按 time_waited 排序识别 Top 等待事件与等待类")
            lines.append("  2. 结合 V$SESSION_WAIT / ASH 定位具体会话与 SQL")
            lines.append("  3. I/O 类等待检查磁盘性能与 buffer cache；锁类等待检查阻塞链")
        lines.append("=" * 78)
        return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Oracle Skills Engine")
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                   "..", "..", "oracle-skills"),
                    help="oracle/skills 仓库路径")
    ap.add_argument("--list", action="store_true", help="列出全部可用技能")
    ap.add_argument("--alert", choices=list(ALERT_ROUTES), help="告警类型")
    ap.add_argument("--context", default=None, help="告警上下文 JSON，例如 '{\"tablespace\":\"USERS\",\"used_pct\":92}'")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    if not os.path.isdir(args.repo):
        print(f"[error] 找不到 oracle/skills 仓库: {args.repo}", file=sys.stderr)
        sys.exit(1)

    engine = SkillsEngine(args.repo)

    if args.list:
        skills = engine.list_skills()
        if args.json:
            print(json.dumps(skills, ensure_ascii=False, indent=2))
        else:
            print(f"{'告警类型':<16}{'技能文件':<48}{'说明'}")
            print("-" * 110)
            for s in skills:
                print(f"{s['alert_type']:<16}{s['skill']:<48}{s['summary'][:40]}")
        return 0

    if args.alert:
        ctx = None
        if args.context:
            try:
                ctx = json.loads(args.context)
            except json.JSONDecodeError:
                ctx = {"raw": args.context}
        if args.json:
            info = engine.load_alert(args.alert)
            print(json.dumps(info, ensure_ascii=False, indent=2, default=str))
        else:
            print(engine.runbook(args.alert, ctx))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
