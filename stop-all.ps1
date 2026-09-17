# 停止全部监控组件
$names = @("prometheus", "alertmanager", "grafana-server", "oracle_collector")
foreach ($n in $names) {
    Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "[stop] $n (PID $($_.Id))"
        Stop-Process -Id $_.Id -Force
    }
}
Write-Host "已停止 Oracle 监控栈。"
