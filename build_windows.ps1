$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host '== MySQL IDLE release builder ==' -ForegroundColor Cyan
$Python = Get-Command py -ErrorAction SilentlyContinue
if (-not $Python) {
    throw 'Python Launcher (py.exe) is required on the BUILD machine. End users do not need Python after packaging.'
}

py -3.15 --version
py -3.15 -m pip install --upgrade pip
py -3.15 -m pip install -r requirements.txt pyinstaller==6.22.3 pillow==12.3.0
py -3.15 -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency consistency check failed.' }

py -3.15 tools/sync_logo_resources.py
if ($LASTEXITCODE -ne 0) { throw 'Exact logo resource sync failed.' }

py -3.15 tools/generate_brand_assets.py
if ($LASTEXITCODE -ne 0) { throw 'Brand asset generation failed.' }

py -3.15 -m unittest -v test_mysql_idle.py test_mobile_companion.py test_feature_governor.py test_password_auth.py test_packaging_branding.py
if ($LASTEXITCODE -ne 0) { throw 'Automated tests failed; packaging was stopped.' }

if (Test-Path .\build) { Remove-Item .\build -Recurse -Force }
if (Test-Path .\dist\mysql_idle) { Remove-Item .\dist\mysql_idle -Recurse -Force }
if (Test-Path .\dist\MySQLIDLE_Portable.exe) { Remove-Item .\dist\MySQLIDLE_Portable.exe -Force }
# Do not accidentally ship an installer left behind by an older local build.
if (Test-Path .\dist\installer\MySQLIDLE-Setup.exe) {
    Remove-Item .\dist\installer\MySQLIDLE-Setup.exe -Force
}

py -3.15 -m PyInstaller --clean --noconfirm mysql_idle.spec
if ($LASTEXITCODE -ne 0) { throw 'Folder build failed.' }
py -3.15 -m PyInstaller --clean --noconfirm mysql_idle_portable.spec
if ($LASTEXITCODE -ne 0) { throw 'Portable one-file build failed.' }

if (-not (Test-Path .\dist\mysql_idle\mysql_idle.exe)) {
    throw 'Expected one-folder executable was not produced.'
}
if (-not (Test-Path .\dist\MySQLIDLE_Portable.exe)) {
    throw 'Expected portable executable was not produced.'
}

$Iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($Iscc) {
    & $Iscc.Source '.\MySQLIDLE.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup installer compilation failed.' }
    Write-Host 'Installer: dist\installer\MySQLIDLE-Setup.exe' -ForegroundColor Green
} else {
    Write-Warning 'Inno Setup is not installed. The portable EXE and application folder were built, but no setup installer was created. Install Inno Setup and run: ISCC.exe MySQLIDLE.iss'
}
Write-Host 'Portable executable: dist\MySQLIDLE_Portable.exe' -ForegroundColor Green
Write-Host 'Folder build: dist\mysql_idle\mysql_idle.exe (keep the whole folder together)' -ForegroundColor Green
