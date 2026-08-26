$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
Set-Location -LiteralPath $projectRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) {
    throw "找不到 Python。打包机需要安装 Python 和 PyInstaller。"
}

$database = Join-Path $projectRoot "data\survival_log_codex.sqlite3"
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
    throw "找不到数据库：$database"
}

$web = Join-Path $projectRoot "web"
if (-not (Test-Path -LiteralPath $web -PathType Container)) {
    throw "找不到网页资源目录：$web"
}

$distRoot = Join-Path $projectRoot "dist"
$package = Join-Path $distRoot "SurvivalLogDataViewer"
$stagingRoot = Join-Path $distRoot ".staging"
$stagingPackage = Join-Path $stagingRoot "SurvivalLogDataViewer"
$spec = Join-Path $projectRoot "survival_log_codex.spec"
$packageExecutable = Join-Path $package "生存日志图鉴.exe"

$running = @(Get-Process -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        if ($_.Path -eq $packageExecutable) {
            $_
        }
    } catch {
    }
})
if ($running.Count -gt 0) {
    throw "分发版程序正在运行，请先关闭它：$packageExecutable"
}

$existingDatabase = Join-Path $package "SurvivalLogDataViewer.sqlite3"
$existingLog = Join-Path $package "SurvivalLogDataViewer.log"
$previousPackage = Join-Path $distRoot ".previous-SurvivalLogDataViewer"

if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

try {
    & $python.Source -m PyInstaller --noconfirm --clean --distpath $stagingRoot $spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $stagingPackage -PathType Container)) {
        throw "构建完成但找不到临时分发目录：$stagingPackage"
    }

    $packagedDatabase = Join-Path $stagingPackage "SurvivalLogDataViewer.sqlite3"
    & $python.Source (Join-Path $projectRoot "codex_database.py") `
        --package-copy-from $database `
        --database $packagedDatabase
    if ($LASTEXITCODE -ne 0) {
        throw "打包数据库准备失败，退出码：$LASTEXITCODE"
    }

    if (Test-Path -LiteralPath $existingDatabase -PathType Leaf) {
        $validationCode = "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); ok=c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; c.close(); raise SystemExit(0 if ok else 1)"
        & $python.Source -c $validationCode $existingDatabase
        if ($LASTEXITCODE -eq 0) {
            Copy-Item -LiteralPath $existingDatabase -Destination $packagedDatabase -Force
        } else {
            Write-Warning "现有分发数据库完整性检查失败，使用新的空完成状态数据库：$existingDatabase"
        }
    }
    if (Test-Path -LiteralPath $existingLog -PathType Leaf) {
        Copy-Item -LiteralPath $existingLog -Destination (Join-Path $stagingPackage "SurvivalLogDataViewer.log") -Force
    }
    Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination (Join-Path $stagingPackage "README.md") -Force

    $forbidden = @("streamlit", "pyarrow", "numpy", "pandas", "plotly", "matplotlib")
    $forbiddenFound = @(Get-ChildItem -LiteralPath $stagingPackage -Force -Recurse | Where-Object {
        $forbidden -contains $_.Name.ToLowerInvariant()
    })
    if ($forbiddenFound.Count -gt 0) {
        $names = ($forbiddenFound | Select-Object -ExpandProperty FullName) -join ", "
        throw "轻量分发包仍包含不应打包的依赖：$names"
    }

    $forbiddenExtensions = @(".pyc", ".pyo", ".iobj", ".ipdb")
    $forbiddenFiles = @(Get-ChildItem -LiteralPath $stagingPackage -Force -Recurse -File | Where-Object {
        $forbiddenExtensions -contains $_.Extension.ToLowerInvariant() -or $_.DirectoryName -match "\\__pycache__(\\|$)"
    })
    if ($forbiddenFiles.Count -gt 0) {
        $names = ($forbiddenFiles | Select-Object -ExpandProperty FullName) -join ", "
        throw "分发包仍包含构建缓存或调试文件：$names"
    }

    $rawVendorFiles = @(Get-ChildItem -LiteralPath $stagingPackage -Force -Recurse | Where-Object {
        $_.FullName -match "\\_vendor_unitypy(\\|$)"
    })
    if ($rawVendorFiles.Count -gt 0) {
        $names = ($rawVendorFiles | Select-Object -ExpandProperty FullName) -join ", "
        throw "分发包不应复制源码 vendor 目录：$names"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $stagingPackage "生存日志图鉴.exe") -PathType Leaf)) {
        throw "临时分发包缺少运行文件：生存日志图鉴.exe"
    }
    if (-not (Test-Path -LiteralPath $packagedDatabase -PathType Leaf)) {
        throw "临时分发包缺少数据库：$packagedDatabase"
    }

    if (Test-Path -LiteralPath $previousPackage) {
        Remove-Item -LiteralPath $previousPackage -Recurse -Force
    }
    if (Test-Path -LiteralPath $package) {
        Move-Item -LiteralPath $package -Destination $previousPackage
    }
    try {
        Move-Item -LiteralPath $stagingPackage -Destination $package
    } catch {
        if (Test-Path -LiteralPath $previousPackage) {
            Move-Item -LiteralPath $previousPackage -Destination $package
        }
        throw
    }
    if (Test-Path -LiteralPath $previousPackage) {
        Remove-Item -LiteralPath $previousPackage -Recurse -Force
    }
} finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}

$bytes = (Get-ChildItem -LiteralPath $package -File -Recurse | Measure-Object Length -Sum).Sum
$sizeMiB = [math]::Round($bytes / 1MB, 2)
Write-Host "轻量独立版构建完成：$package"
Write-Host "运行文件：$(Join-Path $package '生存日志图鉴.exe')"
Write-Host "分发目录大小：$sizeMiB MiB"
