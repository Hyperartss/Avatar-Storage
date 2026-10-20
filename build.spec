# -*- coding: utf-8 -*-
# PyInstaller spec for INF Avis
# Build: pyinstaller build.spec

import sys
import os
from pathlib import Path

# Project root
ROOT = Path(__file__).parent.resolve()

# ---- platform detection ----
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# ---- hidden imports ----
hiddenimports = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtSvg",
    "requests",
    "PIL",
    "PIL.Image",
    "sqlite3",
    "json",
    "datetime",
    "pathlib",
    "ssl",
    "certifi",
]

# ---- data files ----
# (source, dest) pairs for non-Python files
datas = [
    (str(ROOT / "gui"), "gui"),
    (str(ROOT / "api"), "api"),
    (str(ROOT / "database.py"), "."),
    (str(ROOT / "paths.py"), "."),
    (str(ROOT / "requirements.txt"), "."),
]

# ---- binaries ----
binaries = []

# ---- exe config ----
exe_name = "INF Avis" if IS_WINDOWS else "inf-avis"
icon = str(ROOT / "assets" / "icon.ico") if IS_WINDOWS and (ROOT / "assets" / "icon.ico").exists() else None

# ---- analysis ----
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas", "scipy",
        "jupyter", "notebook", "IPython", "pytest",
        "sphinx", "docutils", "setuptools", "pip", "wheel",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# ---- PYZ ----
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ---- EXE ----
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
    version_file=None,
)

# ---- coll (Linux/macOS) ----
if IS_LINUX:
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name=exe_name,
    )

# ---- app (macOS) ----
if IS_MACOS:
    app = BUNDLE(
        exe,
        name="INF Avis.app",
        icon=icon,
        bundle_identifier="com.infavis",
        info_plist={
            "CFBundleName": "INF Avis",
            "CFBundleDisplayName": "INF Avis",
            "CFBundleVersion": "1.0.0",
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )