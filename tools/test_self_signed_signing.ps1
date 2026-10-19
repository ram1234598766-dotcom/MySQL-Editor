param(
    [Parameter(Mandatory = $true)]
    [string]$Target
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $Target -PathType Leaf)) {
    throw "Signing smoke-test target does not exist: $Target"
}
if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw "RUNNER_TEMP must be configured for the signing smoke test."
}

$smokeSource = Join-Path $env:WINDIR "System32\where.exe"
if (!(Test-Path -LiteralPath $smokeSource -PathType Leaf)) {
    throw "A small Windows executable for the signing smoke test was not found: $smokeSource"
}

$testId = [Guid]::NewGuid().ToString("N")
$testDirectory = Join-Path $env:RUNNER_TEMP ("mysql-editor-signing-smoke-{0}" -f $testId)
New-Item -ItemType Directory -Path $testDirectory -Force | Out-Null
$testTarget = Join-Path $testDirectory "SigningSmoke.exe"
$pfxPath = Join-Path $testDirectory "smoke-test-certificate.pfx"
$password = "Temporary-Smoke-Only-$testId"
$securePassword = ConvertTo-SecureString $password -AsPlainText -Force
$certificate = $null

try {
    # Check that the product build exists, but sign a small disposable PE executable
    # to avoid making the CI smoke test depend on the size of the packaged application.
    Write-Host "Preparing a small disposable executable for signing verification."
    Copy-Item -LiteralPath $smokeSource -Destination $testTarget

    Write-Host "Creating a temporary RSA code-signing certificate."
    $certificate = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject "CN=MySQL Editor CI Temporary Signing Test" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -Provider "Microsoft Enhanced RSA and AES Cryptographic Provider" `
        -KeySpec Signature `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddDays(30)

    Write-Host "Exporting the temporary signing certificate."
    Export-PfxCertificate -Cert $certificate -FilePath $pfxPath -Password $securePassword | Out-Null

    $env:WINDOWS_SIGNING_CERTIFICATE_BASE64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($pfxPath))
    $env:WINDOWS_SIGNING_CERTIFICATE_PASSWORD = $password
    $env:WINDOWS_SIGNING_CERTIFICATE_TYPE = "self-signed"
    Remove-Item Env:WINDOWS_SIGNING_TIMESTAMP_URL -ErrorAction SilentlyContinue

    Write-Host "Invoking the same signing helper used by release builds."
    & (Join-Path $PSScriptRoot "sign_windows_artifacts.ps1") -Targets @($testTarget) -SkipTimestamp

    Write-Host "Checking the resulting Authenticode signature."
    $signature = Get-AuthenticodeSignature -FilePath $testTarget
    if ($signature.SignatureType -ne "Authenticode" -or $null -eq $signature.SignerCertificate) {
        throw "The temporary executable did not retain an Authenticode signature."
    }
    if ($signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
        throw "The temporary executable was signed by an unexpected certificate."
    }
    Write-Host "Self-signed signing smoke test passed. Only a disposable copy of a small Windows executable was modified."
} finally {
    Remove-Item Env:WINDOWS_SIGNING_CERTIFICATE_BASE64 -ErrorAction SilentlyContinue
    Remove-Item Env:WINDOWS_SIGNING_CERTIFICATE_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:WINDOWS_SIGNING_CERTIFICATE_TYPE -ErrorAction SilentlyContinue
    Remove-Item Env:WINDOWS_SIGNING_TIMESTAMP_URL -ErrorAction SilentlyContinue

    if ($certificate) {
        Remove-Item -LiteralPath ("Cert:\CurrentUser\My\{0}" -f $certificate.Thumbprint) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $testDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
