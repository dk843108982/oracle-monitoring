#!/usr/bin/env bash
# 停止全部监控组件
pkill -f "oracle_collector.py" 2>/dev/null && echo "[stop] oracle-collector"
pkill -f "alert_handler.py" 2>/dev/null && echo "[stop] alert-handler"
pkill -x prometheus 2>/dev/null && echo "[stop] prometheus"
pkill -x alertmanager 2>/dev/null && echo "[stop] alertmanager"
pkill -x grafana-server 2>/dev/null && echo "[stop] grafana-server"
echo "已停止 Oracle 监控栈。"
