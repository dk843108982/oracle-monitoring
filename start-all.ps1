# ============================================================
# Oracle 企业监控 —— 一键启动（可移植版）
# 启动顺序：oracle-collector -> prometheus -> alertmanager -> alert-handler -> grafana
# 日志输出到 .\logs\ 目录
# 要求：解压到任意目录即可运行；Python 环境需含 oracledb（见 install-driver.ps1）
# ============================================================
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# ---- Python 自动探测：优先选择装有 oracledb 的解释器 ----
function Test-OraclePython {
    param([string[]]$cmd)
    try {
        $null = & $cmd[0] $cmd[1..($cmd.Count - 1)] -c "import oracledb" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}
function Find-OraclePython {
    $pycmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pycmd -and (Test-OraclePython @("python"))) { return "python" }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($ver in @("3.12", "3.11", "3.10")) {
            if (Test-OraclePython @("py", "-$ver")) { return "py -$ver" }
        }
    }
    if ($pycmd) { return "python" }
    if ($py) { return "py" }
    return $null
}

$pyCmd = Find-OraclePython
if (-not $pyCmd) {
    Write-Host "[error] 未找到 Python。请先安装 Python 3.10+，并执行 .\collector\install-driver.ps1 安装 oracledb。" -ForegroundColor Red
    exit 1
}
Write-Host "[info] 使用 Python: $pyCmd"

# 0. 探测二进制目录
$bin = Join-Path $root "bin\extracted"
$promDir = Get-ChildItem $bin -Directory -Filter "prometheus*" | Select-Object -First 1
$amDir   = Get-ChildItem $bin -Directory -Filter "alertmanager*" | Select-Object -First 1
$gfDir   = Get-ChildItem $bin -Directory -Filter "grafana*" | Select-Object -First 1

if (-not $promDir -or -not $amDir -or -not $gfDir) {
    Write-Host "[error] 未找到 Prometheus/Alertmanager/Grafana 二进制，请先运行 .\bin\download.ps1" -ForegroundColor Red
    exit 1
}

# 1. Oracle 采集器（默认 demo 模式；real 模式改 collector\config.json）
$collector = Join-Path $root "collector\oracle_collector.py"
$proc = Start-Process -FilePath ($pyCmd -split " ")[0] -ArgumentList (@(($pyCmd -split " ")[1..99]) + @($collector, "--mode", "demo", "--config", (Join-Path $root "collector\config.json"))) -WorkingDirectory (Join-Path $root "collector") -RedirectStandardOutput (Join-Path $logs "collector.log") -RedirectStandardError (Join-Path $logs "collector.log.err") -WindowStyle Hidden -PassThru
Write-Host "[start] oracle-collector (PID $($proc.Id)) 端口 9161"

Start-Sleep -Seconds 2

# 2. Prometheus
$promExe = Join-Path $promDir.FullName "prometheus.exe"
$proc = Start-Process -FilePath $promExe -ArgumentList @("--config.file=$(Join-Path $root 'prometheus\prometheus.yml')", "--storage.tsdb.path=$(Join-Path $root 'prometheus\data')", "--web.listen-address=127.0.0.1:9090") -WorkingDirectory (Join-Path $root "prometheus") -RedirectStandardOutput (Join-Path $logs "prometheus.log") -RedirectStandardError (Join-Path $logs "prometheus.log.err") -WindowStyle Hidden -PassThru
Write-Host "[start] prometheus (PID $($proc.Id)) 端口 9090"

# 3. Alertmanager
$amExe = Join-Path $amDir.FullName "alertmanager.exe"
$proc = Start-Process -FilePath $amExe -ArgumentList @("--config.file=$(Join-Path $root 'alertmanager\alertmanager.yml')", "--storage.path=$(Join-Path $root 'alertmanager\data')", "--web.listen-address=127.0.0.1:9093") -WorkingDirectory (Join-Path $root "alertmanager") -RedirectStandardOutput (Join-Path $logs "alertmanager.log") -RedirectStandardError (Join-Path $logs "alertmanager.log.err") -WindowStyle Hidden -PassThru
Write-Host "[start] alertmanager (PID $($proc.Id)) 端口 9093"

# 4. 告警处理器（Alertmanager -> 技能诊断桥接，端口 8080）
$ahExe = Join-Path $root "collector\alert_handler.py"
# 技能库：优先包内 .\oracle-skills，其次开发布局 ..\oracle-skills
$skillRepo = Join-Path $root "oracle-skills"
if (-not (Test-Path $skillRepo)) { $skillRepo = Join-Path (Split-Path $root) "oracle-skills" }
Write-Host "[info] 技能库: $skillRepo"
$proc = Start-Process -FilePath ($pyCmd -split " ")[0] -ArgumentList (@(($pyCmd -split " ")[1..99]) + @($ahExe, "--port", "8080", "--repo", $skillRepo)) -WorkingDirectory (Join-Path $root "collector") -RedirectStandardOutput (Join-Path $logs "alert-handler.log") -RedirectStandardError (Join-Path $logs "alert-handler.log.err") -WindowStyle Hidden -PassThru
Write-Host "[start] alert-handler (PID $($proc.Id)) 端口 8080"

# 5. Grafana（工作目录 = grafana\，provisioning 内面板路径使用相对路径 dashboards\）
$gfExe = Join-Path $gfDir.FullName "bin\grafana-server.exe"
$env:GF_PATHS_PROVISIONING = Join-Path $root "grafana\provisioning"
$env:GF_PATHS_DATA = Join-Path $root "grafana\data"
$env:GF_PATHS_LOGS = $logs
$env:GF_SECURITY_ADMIN_USER = "admin"
$env:GF_SECURITY_ADMIN_PASSWORD = "admin"
$env:GF_SERVER_HTTP_PORT = "3000"
$proc = Start-Process -FilePath $gfExe -ArgumentList @("--homepath=$($gfDir.FullName)") -WorkingDirectory (Join-Path $root "grafana") -RedirectStandardOutput (Join-Path $logs "grafana.log") -RedirectStandardError (Join-Path $logs "grafana.log.err") -WindowStyle Hidden -PassThru
Write-Host "[start] grafana (PID $($proc.Id)) 端口 3000"

# 5.5 技能控制台（oracle/skills 选择前端，端口 8090）
$sc = Join-Path $root "skill-console\server.py"
$proc = Start-Process -FilePath ($pyCmd -split " ")[0] -ArgumentList (@(($pyCmd -split " ")[1..99]) + @($sc, "--port", "8090", "--repo", $skillRepo, "--reports-dir", (Join-Path $root "collector\reports"))) -WorkingDirectory (Join-Path $root "skill-console") -RedirectStandardOutput (Join-Path $logs "skill-console.log") -RedirectStandardError (Join-Path $logs "skill-console.log.err") -WindowStyle Hidden -PassThru
Write-Host "[start] skill-console (PID $($proc.Id)) 端口 8090"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Oracle 企业监控已启动" -ForegroundColor Cyan
Write-Host "  Grafana       : http://localhost:3000   (admin/admin)" -ForegroundColor Cyan
Write-Host "  Skill Console : http://localhost:8090   (技能选择前端)" -ForegroundColor Cyan
Write-Host "  Prometheus    : http://localhost:9090" -ForegroundColor Cyan
Write-Host "  Collector     : http://localhost:9161/metrics" -ForegroundColor Cyan
Write-Host "  Alertmanager  : http://localhost:9093" -ForegroundColor Cyan
Write-Host "  AlertHandler  : http://localhost:8080/alert-handler" -ForegroundColor Cyan
Write-Host " 停止：.\stop-all.ps1" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
