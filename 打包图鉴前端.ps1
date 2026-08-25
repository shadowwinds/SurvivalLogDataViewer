$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) {
    throw "找不到 Python。打包机需要安装 Python、Streamlit 和 PyInstaller。"
}

$database = Join-Path $PSScriptRoot "SurvivalLog图鉴.sqlite3"
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
    throw "找不到数据库：$database"
}

& $python.Source -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "SurvivalLog图鉴.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}

$package = Join-Path $PSScriptRoot "dist\SurvivalLog图鉴"
if (-not (Test-Path -LiteralPath $package -PathType Container)) {
    throw "构建完成但找不到分发目录：$package"
}

Copy-Item -LiteralPath $database -Destination (Join-Path $package "SurvivalLog图鉴.sqlite3") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "独立版使用说明.md") -Destination (Join-Path $package "使用说明.md") -Force

Write-Host "独立版构建完成：$package"
Write-Host "运行文件：$(Join-Path $package 'SurvivalLog图鉴.exe')"
