# PyInstaller spec for a stable, fast-starting one-folder desktop build.
# Build with: pyinstaller --clean mysql_idle.spec
# Output: dist/mysql_idle/mysql_idle.exe on Windows.

# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['mysql_idle.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/mysqlidle.ico', 'assets'), ('assets/mysqlidle-logo.png', 'assets')],
    hiddenimports=['pymysql', 'pymysql.cursors', 'mobile_companion'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mysql_idle',
    icon='assets/mysqlidle.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    name='mysql_idle',
)
