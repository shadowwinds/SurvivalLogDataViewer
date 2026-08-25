# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata


PROJECT_DIR = Path(SPECPATH).resolve()
streamlit_datas, streamlit_binaries, streamlit_hiddenimports = collect_all("streamlit")

datas = streamlit_datas + copy_metadata("streamlit", recursive=True)
datas.extend(
    (str(PROJECT_DIR / filename), ".")
    for filename in (
        "图鉴前端.py",
        "图鉴数据库.py",
        "图鉴存档解析.py",
        "图鉴解析工具.py",
    )
)


a = Analysis(
    [str(PROJECT_DIR / "图鉴启动器.py")],
    pathex=[str(PROJECT_DIR)],
    binaries=streamlit_binaries,
    datas=datas,
    hiddenimports=streamlit_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["UnityPy"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SurvivalLog图鉴",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
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
    name="SurvivalLog图鉴",
)
