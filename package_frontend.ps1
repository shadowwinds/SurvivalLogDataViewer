$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) {
    throw "找不到 Python。打包机需要安装 Python 和 PyInstaller。"
}

$database = Join-Path $PSScriptRoot "survival_log_codex.sqlite3"
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
    throw "找不到数据库：$database"
}

$web = Join-Path $PSScriptRoot "web"
if (-not (Test-Path -LiteralPath $web -PathType Container)) {
    throw "找不到网页资源目录：$web"
}

& $python.Source -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "survival_log_codex.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}

$package = Join-Path $PSScriptRoot "dist\SurvivalLogDataViewer"
if (-not (Test-Path -LiteralPath $package -PathType Container)) {
    throw "构建完成但找不到分发目录：$package"
}

$packagedDatabase = Join-Path $package "SurvivalLogDataViewer.sqlite3"
& $python.Source (Join-Path $PSScriptRoot "codex_database.py") `
    --package-copy-from $database `
    --database $packagedDatabase
if ($LASTEXITCODE -ne 0) {
    throw "打包数据库准备失败，退出码：$LASTEXITCODE"
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.md") -Destination (Join-Path $package "README.md") -Force

$forbidden = @("streamlit", "pyarrow", "numpy", "pandas", "plotly", "matplotlib")
$forbiddenFound = Get-ChildItem -LiteralPath $package -Force -Recurse | Where-Object {
    $forbidden -contains $_.Name.ToLowerInvariant()
}
if ($null -ne $forbiddenFound) {
    $names = ($forbiddenFound | Select-Object -ExpandProperty FullName) -join ", "
    throw "轻量分发包仍包含不应打包的依赖：$names"
}

$bytes = (Get-ChildItem -LiteralPath $package -File -Recurse | Measure-Object Length -Sum).Sum
$sizeMiB = [math]::Round($bytes / 1MB, 2)
Write-Host "轻量独立版构建完成：$package"
Write-Host "运行文件：$(Join-Path $package '生存日志图鉴.exe')"
Write-Host "分发目录大小：$sizeMiB MiB"
