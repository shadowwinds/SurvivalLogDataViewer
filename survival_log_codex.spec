# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


PROJECT_DIR = Path(SPECPATH).resolve()
VENDOR_DIR = PROJECT_DIR / "_vendor_unitypy"
if VENDOR_DIR.is_dir() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))


def include_unitypy_module(name: str) -> bool:
    """Keep the parser/runtime graph and omit UnityPy's unused export tooling."""

    return not name.startswith(("UnityPy.export", "UnityPy.cli", "UnityPy.tools")) and name != "UnityPy.__main__"


UNITYPY_HIDDENIMPORTS = (
    collect_submodules("UnityPy", filter=include_unitypy_module)
    if VENDOR_DIR.is_dir()
    else []
)

DATA_FILES = [
    (str(PROJECT_DIR / "web"), "web"),
    (str(PROJECT_DIR / "achievement_conditions.json"), "."),
]
if VENDOR_DIR.is_dir():
    DATA_FILES.extend(collect_data_files("UnityPy", include_py_files=False))


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
        "UnityPy.export",
        "UnityPy.cli",
        "UnityPy.tools",
        "astc_encoder",
        "etcpak",
        "texture2ddecoder",
        "fmod_toolkit",
        "pyfmodex",
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
