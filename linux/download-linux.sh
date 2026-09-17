#!/usr/bin/env bash
# ============================================================
# Oracle 企业监控 —— Linux 二进制下载脚本（x86_64）
# 优先国内镜像：清华(github-release) / 华为云 / gh-proxy 加速
# 下载到 bin/downloads 并解压到 bin/extracted
# ============================================================
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DL="$ROOT/bin/downloads"
EX="$ROOT/bin/extracted"
mkdir -p "$DL" "$EX"

PROM_VER="3.13.3"
AM_VER="0.34.0"
GF_VER="12.4.2"
GF_BUILD="23531306697"   # 华为云 Grafana 构建号（随版本变化，失败时以目录内实际文件名为准）

echo "[1/3] 下载 Prometheus ${PROM_VER} (清华镜像)"
curl -fsSL -o "$DL/prometheus.tar.gz" \
  "https://mirrors.tuna.tsinghua.edu.cn/github-release/prometheus/prometheus/LatestRelease/prometheus-${PROM_VER}.linux-amd64.tar.gz"
tar -xzf "$DL/prometheus.tar.gz" -C "$EX"
rm -f "$DL/prometheus.tar.gz"

echo "[2/3] 下载 Alertmanager ${AM_VER} (gh-proxy 加速)"
curl -fsSL -o "$DL/alertmanager.tar.gz" \
  "https://gh-proxy.com/https://github.com/prometheus/alertmanager/releases/download/v${AM_VER}/alertmanager-${AM_VER}.linux-amd64.tar.gz"
tar -xzf "$DL/alertmanager.tar.gz" -C "$EX"
rm -f "$DL/alertmanager.tar.gz"

echo "[3/3] 下载 Grafana ${GF_VER} (华为云)"
curl -fsSL -o "$DL/grafana.tar.gz" \
  "https://mirrors.huaweicloud.com/grafana/${GF_VER}/grafana-enterprise_${GF_VER}_${GF_BUILD}_linux_amd64.tar.gz"
tar -xzf "$DL/grafana.tar.gz" -C "$EX"
rm -f "$DL/grafana.tar.gz"

echo "二进制就绪:"
ls -d "$EX"/*/
echo ""
echo "安装 Python 驱动（如未安装）:"
echo "  pip install python-oracledb"
echo "然后执行: ./linux/start.sh"
