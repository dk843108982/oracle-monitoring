#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle 连接自检工具 connect-check.py
=====================================
用途：接入真实 Oracle 数据库前的"连接 + 权限 + 指标"三合一验证。
支持多实例（oracle_instances 数组，或兼容旧 oracle 单对象）。
在切换采集器到 real 模式前运行，确认：
  1) 网络与账号能否连通（thin 模式直连 1521）
  2) 采集 SQL 所需视图权限是否齐全（逐视图探测）
  3) 能取到哪些关键指标样例（表空间 / 等待事件 / 会话 / alert 错误）

用法：
  py -3.12 collector/connect-check.py                  # 读默认 config.json
  py -3.12 collector/connect-check.py --config 你的配置.json

流程（三步）：
  1) 在每个目标库以 SYSDBA 执行 grants.sql（创建 db_monitor 最小权限账号）
  2) 编辑 config.json：mode 改 "real"，填 oracle_instances 数组
  3) 运行本脚本，全部 PASS 后重启采集器
"""

import argparse
import json
import os
import sys
import time


def check_one(oracledb, o):
    """检查单个实例：连接 + 权限 + 指标样例。返回 0=PASS 1=连接失败 2=权限缺失。"""
    # ---- 1. 连接 ----
    try:
        dsn = oracledb.makedsn(o["host"], o["port"], service_name=o["service_name"])
        t0 = time.time()
        conn = oracledb.connect(user=o["user"], password=o["password"], dsn=dsn, tcp_connect_timeout=8)
        print(f"[PASS] 连接成功（{int((time.time()-t0)*1000)}ms）")
    except oracledb.InterfaceError as e:
        print(f"[FAIL] 网络/协议错误: {e}")
        print("       检查: 主机名可达? 防火墙放行 1521? 服务名是否正确?")
        print("       tnsping 等价测试: 用 SQL Developer / SQLcl 同参数试连一次")
        return 1
    except oracledb.DatabaseError as e:
        err, = e.args
        print(f"[FAIL] 数据库错误 ORA-{err.code}: {err.message}")
        if err.code == 1017:
            print("       账号或密码错误，或该用户未获远程登录权限")
        elif err.code in (12514, 12505):
            print("       服务名 SERVICE_NAME 不存在，检查是否拼写正确")
        elif err.code == 28000:
            print("       账号被锁定，需 SYSDBA 执行 ALTER USER ... ACCOUNT UNLOCK;")
        elif err.code == 28001:
            print("       密码已过期，需 SYSDBA 执行 ALTER USER ... IDENTIFIED BY ...;")
        return 1

    cur = conn.cursor()

    # ---- 2. 库基本信息 ----
    try:
        cur.execute("SELECT banner FROM v$version WHERE ROWNUM=1")
        ver = cur.fetchone()[0].strip()
        print(f"[INFO] 版本: {ver}")
    except Exception:
        ver = "?"
    try:
        cur.execute("SELECT instance_name, host_name, version, status FROM v$instance")
        i = cur.fetchone()
        print(f"[INFO] 实例: {i[0]} @ {i[1]}  status={i[3]}")
    except Exception:
        pass
    try:
        cur.execute("SELECT sys_context('USERENV','CON_NAME') FROM dual")
        print(f"[INFO] 当前容器: {cur.fetchone()[0]}")
    except Exception:
        pass

    # ---- 3. 权限逐项探测 ----
    checks = [
        ("v$instance",                 "SELECT count(*) FROM v$instance"),
        ("v$version",                  "SELECT count(*) FROM v$version"),
        ("v$session",                  "SELECT count(*) FROM v$session"),
        ("v$system_event",             "SELECT count(*) FROM v$system_event"),
        ("v$sqlarea",                  "SELECT count(*) FROM v$sqlarea"),
        ("v$sgastat",                  "SELECT count(*) FROM v$sgastat"),
        ("v$diag_alert_ext",           "SELECT count(*) FROM v$diag_alert_ext"),
        ("v$archive_dest",             "SELECT count(*) FROM v$archive_dest"),
        ("v$log_history",              "SELECT count(*) FROM v$log_history"),
        ("v$archived_log",             "SELECT count(*) FROM v$archived_log"),
        ("v$pgastat",                  "SELECT count(*) FROM v$pgastat"),
        ("dba_tablespace_usage_metrics", "SELECT count(*) FROM dba_tablespace_usage_metrics"),
        ("dba_tablespaces",            "SELECT count(*) FROM dba_tablespaces"),
        ("dba_data_files",             "SELECT count(*) FROM dba_data_files"),
        ("dba_hist_snapshot",          "SELECT count(*) FROM dba_hist_snapshot"),
    ]
    print("\n[权限探测] 采集 SQL 所需视图（采集器会用到）")
    missing = []
    for name, sql in checks:
        try:
            cur.execute(sql)
            cur.fetchone()
            print(f"  [PASS] {name}")
        except oracledb.DatabaseError as e:
            err, = e.args
            if err.code in (942, 1031, 903, 904):
                missing.append(name)
                print(f"  [FAIL] {name}  ORA-{err.code}")
            else:
                print(f"  [WARN] {name}  ORA-{err.code} {err.message.splitlines()[0][:60]}")

    # ---- 4. 指标样例 ----
    print("\n[指标样例] 切换到 real 后采集器将获取的数据")
    try:
        cur.execute("""
            SELECT tablespace_name, used_percent, used_space*8192/1024/1024/1024 AS used_gb,
                   tablespace_size*8192/1024/1024/1024 AS size_gb
            FROM dba_tablespace_usage_metrics ORDER BY used_percent DESC FETCH FIRST 5 ROWS ONLY""")
        print("  表空间 TOP5（按使用率）:")
        for t in cur.fetchall():
            print(f"    {t[0]:<30} {float(t[1]):6.1f}%  {float(t[2]):8.1f}/{float(t[3]):8.1f} GB")
    except Exception:
        pass
    try:
        cur.execute("""
            SELECT event, total_waits, time_waited_micro/1e6 AS secs
            FROM v$system_event
            WHERE wait_class <> 'Idle' AND time_waited_micro > 0
            ORDER BY time_waited_micro DESC FETCH FIRST 5 ROWS ONLY""")
        print("  等待事件 TOP5:")
        for t in cur.fetchall():
            print(f"    {t[0]:<40} waits={t[1]}  {float(t[2]):.1f}s")
    except Exception:
        pass
    try:
        cur.execute("SELECT status, count(*) FROM v$session GROUP BY status")
        print("  会话: " + ", ".join(f"{s}={c}" for s, c in cur.fetchall()))
    except Exception:
        pass

    conn.close()
    if missing:
        print(f"\n[实例 {o['instance_name']}] 缺 {len(missing)} 项视图权限")
        print("      修复: 以 SYSDBA 执行 collector/grants.sql（或仅补授缺失视图）")
        print("      缺失: " + ", ".join(missing))
        return 2
    return 0


def main():
    ap = argparse.ArgumentParser(description="Oracle 连接自检")
    ap.add_argument("--config",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 实例列表：支持 oracle_instances 数组（多实例），兼容旧 oracle 单对象
    if isinstance(cfg.get("oracle_instances"), list) and cfg["oracle_instances"]:
        instances = [dict(x) for x in cfg["oracle_instances"]]
    elif isinstance(cfg.get("oracle"), dict):
        instances = [dict(cfg["oracle"])]
    else:
        print("[FAIL] 配置中既无 oracle_instances 数组也无 oracle 对象，请检查 config.json")
        return 1
    for i, inst in enumerate(instances):
        inst.setdefault("instance_name", inst.get("service_name", f"oracle-{i+1}"))

    print("=" * 62)
    print(f" Oracle 连接自检（{len(instances)} 个实例）  模式: {cfg.get('mode')}")
    print("=" * 62)

    try:
        import oracledb
    except ImportError:
        print("[FAIL] python-oracledb 未安装。\n"
              "       执行: py -3.12 -m pip install \"git+https://github.com/oracle/python-oracledb.git@v26.0.0\"")
        return 1

    worst = 0
    for o in instances:
        print(f"\n### 实例 [{o['instance_name']}] {o['host']}:{o['port']}/{o['service_name']} (账号: {o['user']})")
        rc = check_one(oracledb, o)
        worst = max(worst, rc)

    print("\n" + "=" * 62)
    if worst == 0:
        print("结论: 全部实例 PASS —— 可以切换 real 模式")
        print("步骤: 1) config.json 确保 mode=\"real\"（oracle_instances 已含全部实例）")
        print("      2) 重启采集器: .\\stop-all.ps1 然后 .\\start-all.ps1")
        print("      3) 验证: http://localhost:9161/metrics 每个实例都有 oracle_up=1")
        print("      4) Grafana 顶部下拉 oracle_instance 可切换实例（http://localhost:3000）")
    else:
        print(f"结论: {worst} 个实例存在问题，请根据上方报错修复后重跑本脚本")
    return 0 if worst == 0 else (1 if worst == 1 else 2)


if __name__ == "__main__":
    sys.exit(main())
