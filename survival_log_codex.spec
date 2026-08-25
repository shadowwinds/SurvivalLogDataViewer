# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


PROJECT_DIR = Path(SPECPATH).resolve()
VENDOR_DIR = PROJECT_DIR.parent / "000" / "_vendor_unitypy"
if not VENDOR_DIR.is_dir():
    VENDOR_DIR = PROJECT_DIR / "_vendor_unitypy"
if VENDOR_DIR.is_dir() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))
UNITYPY_HIDDENIMPORTS = collect_submodules("UnityPy") if VENDOR_DIR.is_dir() else []

DATA_FILES = [(str(PROJECT_DIR / "web"), "web")]
if VENDOR_DIR.is_dir():
    DATA_FILES.append((str(VENDOR_DIR), "_vendor_unitypy"))


a = Analysis(
    [str(PROJECT_DIR / "codex_launcher.py")],
    pathex=[str(PROJECT_DIR), str(VENDOR_DIR)],
    binaries=[],
    datas=DATA_FILES,
    hiddenimports=UNITYPY_HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "streamlit",
        "pyarrow",
        "numpy",
        "pandas",
        "plotly",
        "matplotlib",
        "PIL",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="生存日志图鉴",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SurvivalLogDataViewer",
)
