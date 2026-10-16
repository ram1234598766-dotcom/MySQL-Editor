# Single-file Windows executable. Startup is slower than the one-folder build,
# but the recipient can copy just this EXE and does not need Python installed.
# Build with: py -m PyInstaller --clean --noconfirm mysql_idle_portable.spec
# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['mysql_idle.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/mysqlidle.ico', 'assets'), ('assets/mysql-editor-logo.webp', 'assets')],
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
    a.binaries,
    a.datas,
    [],
    name='MySQLEditor_Portable',
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
