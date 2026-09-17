# ============================================================
# Oracle 企业监控 —— 打包脚本（可移植包）
# 生成：oracle-monitoring-portable.zip（解压即用，含全部二进制与技能库）
# 用法：.\package.ps1
# ============================================================
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = $root
$staging = Join-Path (Split-Path $root) "oracle-monitoring-portable"
$zip = Join-Path (Split-Path $root) "oracle-monitoring-portable.zip"

# 0. 清理旧打包目录
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
if (Test-Path $zip) { Remove-Item $zip -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

Write-Host "[1/5] 复制核心目录 ..."

# 1. 复制配置目录（剔除运行时数据）
foreach ($d in @("prometheus", "alertmanager", "grafana")) {
    $dst = Join-Path $staging $d
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Get-ChildItem (Join-Path $src $d) -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring((Join-Path $src $d).Length + 1)
        # 跳过运行时数据目录
        if ($rel -match "^data\\|^data$") { return }
        $target = Join-Path $dst $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        Copy-Item $_.FullName $target -Force
    }
}

# 2. 复制采集器（全部文件 + 一份示例诊断报告）
$collDst = Join-Path $staging "collector"
New-Item -ItemType Directory -Force -Path $collDst | Out-Null
Copy-Item (Join-Path $src "collector\*.py") $collDst
Copy-Item (Join-Path $src "collector\*.json") $collDst
Copy-Item (Join-Path $src "collector\*.sql") $collDst
Copy-Item (Join-Path $src "collector\*.txt") $collDst
Copy-Item (Join-Path $src "collector\*.ps1") $collDst
$reportDst = Join-Path $collDst "reports"
New-Item -ItemType Directory -Force -Path $reportDst | Out-Null
Get-ChildItem (Join-Path $src "collector\reports") -File -ErrorAction SilentlyContinue |
    Select-Object -First 1 | ForEach-Object { Copy-Item $_.FullName $reportDst }

# 2.5 复制技能控制台（前端选择界面）
$scDst = Join-Path $staging "skill-console"
New-Item -ItemType Directory -Force -Path $scDst | Out-Null
Copy-Item (Join-Path $src "skill-console\server.py") $scDst
Copy-Item (Join-Path $src "skill-console\index.html") $scDst

# 3. 复制 oracle/skills 技能库（自包含）
Write-Host "[2/5] 复制 oracle/skills 技能库 ..."
Copy-Item (Join-Path $src "..\oracle-skills") (Join-Path $staging "oracle-skills") -Recurse

# 4. 复制二进制
Write-Host "[3/5] 复制 Prometheus/Alertmanager/Grafana 二进制（约 500MB，请稍候）..."
$binDst = Join-Path $staging "bin\extracted"
New-Item -ItemType Directory -Force -Path $binDst | Out-Null
Get-ChildItem (Join-Path $src "bin\extracted") -Directory | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $binDst $_.Name) -Recurse
}

# 5. 复制文档与脚本
Write-Host "[4/5] 复制文档与脚本 ..."
Copy-Item (Join-Path $src "README.md") $staging
Copy-Item (Join-Path $src "start-all.ps1") $staging
Copy-Item (Join-Path $src "stop-all.ps1") $staging
Copy-Item (Join-Path $src "docker-compose.yml") $staging
Copy-Item (Join-Path $src "linux") (Join-Path $staging "linux") -Recurse

# 压缩（用 bsdtar 生成 zip，兼容任意时间戳）
Write-Host "[5/5] 压缩为 zip（约 450MB，请稍候）..."
tar.exe -a -c -f $zip -C $staging .
if ($LASTEXITCODE -ne 0) { throw "tar 压缩失败" }

# 清理暂存目录
Remove-Item $staging -Recurse -Force

$sizeMB = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "打包完成: $zip" -ForegroundColor Green
Write-Host "包大小  : $sizeMB MB" -ForegroundColor Green
Write-Host "目标机器: 解压到任意目录 -> 安装 Python(oracledb) -> 运行 start-all.ps1" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
