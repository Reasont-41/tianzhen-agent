$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    $projectPython = (Get-Command python -ErrorAction Stop).Source
}
Write-Host '田诊卫士将在 http://127.0.0.1:8000 启动。按 Ctrl+C 停止。'
& $projectPython -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
