# Build with: python -m PyInstaller --clean pyinstaller/mysql_editor.spec
from pathlib import Path

ROOT = Path(SPECPATH).parent
ASSETS = ROOT / "assets"
datas = [
    (str(ASSETS / "mysql-editor-logo.webp"), "assets"),
    (str(ASSETS / "mysql-editor.ico"), "assets"),
]
a = Analysis(
    [str(ROOT / "src" / "mysql_editor" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "mysql.connector.locales.eng",
        "mysql.connector.plugins.mysql_native_password",
        "mysql.connector.plugins.caching_sha2_password",
        "mysql.connector.plugins.sha256_password",
        "keyring.backends.Windows",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="MySQLEditor",
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
    icon=str(ASSETS / "mysql-editor.ico"),
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False,
    upx=False,
    name="MySQLEditor",
)
