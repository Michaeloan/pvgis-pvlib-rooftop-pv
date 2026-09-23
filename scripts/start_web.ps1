$pvRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pvPython = Join-Path $pvRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pvPython)) {
    throw '缺少项目虚拟环境。请先在项目目录执行 python -m venv .venv，然后运行 .\.venv\Scripts\python.exe -m pip install -e ".[weather,web]"。'
}
Push-Location -LiteralPath $pvRoot
try {
    & $pvPython -m streamlit run (Join-Path $pvRoot 'web\app.py')
    if ($LASTEXITCODE -ne 0) { throw '网页服务未能启动。请检查是否已安装 .[weather,web]。' }
} finally {
    Pop-Location
}
