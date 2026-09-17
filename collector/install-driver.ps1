# 安装 python-oracledb（thin 模式，无需 Oracle Instant Client）
# 注意：PyPI 若被网络策略拦截，请将 $indexUrl 改为公司内部镜像
$indexUrl = "https://pypi.org/simple/"
$py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) { $py = "py -3.12" }

Write-Host "使用 Python: $py"
& $py -m pip install python-oracledb --index-url $indexUrl
& $py -c "import oracledb; print('oracledb', oracledb.__version__, 'OK')"
