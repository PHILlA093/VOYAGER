# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build spec for Voyager 1.
#   pip install pyinstaller
#   pyinstaller Voyager1.spec
# Output: dist/Voyager1/Voyager1.exe
# Note: config.json is NOT bundled; place it next to the exe after building.


a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'PySide6.QtMultimedia', 'PySide6.Qt3DCore', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtQuick3D', 'PySide6.QtPdf', 'matplotlib', 'numpy', 'pandas'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Voyager1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    upx=True,
    upx_exclude=[],
    name='Voyager1',
)
