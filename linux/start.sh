#!/usr/bin/env bash
# ============================================================
# Oracle 企业监控 —— Linux 一键启动
# 用法：解压后执行  chmod +x linux/*.sh && ./linux/start.sh
# 前置：python3 + python-oracledb（见 linux/download-linux.sh 与 collector/install 说明）
# ============================================================
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"
BIN="$ROOT/bin/extracted"

PROM_DIR=$(ls -d "$BIN"/prometheus-* 2>/dev/null | head -1)
AM_DIR=$(ls -d "$BIN"/alertmanager-* 2>/dev/null | head -1)
GF_DIR=$(ls -d "$BIN"/grafana-* 2>/dev/null | head -1)
[ -n "$PROM_DIR" ] && [ -n "$AM_DIR" ] && [ -n "$GF_DIR" ] || { echo "[error] 缺少二进制，请先运行 linux/download-linux.sh"; exit 1; }

PY=$(command -v python3 || command -v python)
[ -n "$PY" ] || { echo "[error] 未找到 python3"; exit 1; }

start_bg() {
  nohup "$@" >> "$LOGS/${2##*/}.log" 2>&1 &
  echo "[start] $2 (PID $!)"
}

# 1. 采集器（demo 模式）
start_bg "$PY" "$ROOT/collector/oracle_collector.py" --mode demo --config "$ROOT/collector/config.json"
sleep 2

# 2. Prometheus
start_bg "$PROM_DIR/prometheus" --config.file="$ROOT/prometheus/prometheus.yml" \
  --storage.tsdb.path="$ROOT/prometheus/data" --web.listen-address=127.0.0.1:9090

# 3. Alertmanager
start_bg "$AM_DIR/alertmanager" --config.file="$ROOT/alertmanager/alertmanager.yml" \
  --storage.path="$ROOT/alertmanager/data" --web.listen-address=127.0.0.1:9093

# 4. 告警处理器（技能桥接）
start_bg "$PY" "$ROOT/collector/alert_handler.py" --port 8080 --repo "$ROOT/oracle-skills"

# 5. Grafana
export GF_PATHS_PROVISIONING="$ROOT/grafana/provisioning"
export GF_PATHS_DATA="$ROOT/grafana/data"
export GF_PATHS_LOGS="$LOGS"
export GF_SECURITY_ADMIN_USER=admin
export GF_SECURITY_ADMIN_PASSWORD=admin
export GF_SERVER_HTTP_PORT=3000
start_bg "$GF_DIR/bin/grafana-server" --homepath="$GF_DIR"

echo ""
echo "============================================================"
echo " Oracle 企业监控已启动"
echo "  Grafana      : http://localhost:3000   (admin/admin)"
echo "  Prometheus   : http://localhost:9090"
echo "  Collector    : http://localhost:9161/metrics"
echo "  Alertmanager : http://localhost:9093"
echo "  AlertHandler : http://localhost:8080/alert-handler"
echo " 停止：./linux/stop.sh"
echo "============================================================"
