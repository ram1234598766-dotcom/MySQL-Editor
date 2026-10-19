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

$testId = [Guid]::NewGuid().ToString("N")
$testDirectory = Join-Path $env:RUNNER_TEMP ("mysql-editor-signing-smoke-{0}" -f $testId)
New-Item -ItemType Directory -Path $testDirectory -Force | Out-Null
$testTarget = Join-Path $testDirectory ([IO.Path]::GetFileNameWithoutExtension($Target) + "-SelfSignedSmoke.exe")
$pfxPath = Join-Path $testDirectory "smoke-test-certificate.pfx"
$password = "Temporary-Smoke-Only-$testId"
$securePassword = ConvertTo-SecureString $password -AsPlainText -Force
$certificate = $null

try {
    Copy-Item -LiteralPath $Target -Destination $testTarget
    $certificate = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject "CN=MySQL Editor CI Temporary Signing Test" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddDays(30)

    Export-PfxCertificate -Cert $certificate -FilePath $pfxPath -Password $securePassword | Out-Null

    $env:WINDOWS_SIGNING_CERTIFICATE_BASE64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($pfxPath))
    $env:WINDOWS_SIGNING_CERTIFICATE_PASSWORD = $password
    $env:WINDOWS_SIGNING_CERTIFICATE_TYPE = "self-signed"
    Remove-Item Env:WINDOWS_SIGNING_TIMESTAMP_URL -ErrorAction SilentlyContinue

    & (Join-Path $PSScriptRoot "sign_windows_artifacts.ps1") -Targets @($testTarget) -SkipTimestamp

    $signature = Get-AuthenticodeSignature -FilePath $testTarget
    if ($signature.SignatureType -ne "Authenticode" -or $null -eq $signature.SignerCertificate) {
        throw "The temporary executable did not retain an Authenticode signature."
    }
    if ($signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
        throw "The temporary executable was signed by an unexpected certificate."
    }
    Write-Host "Self-signed signing smoke test passed. The actual release artifact was not modified."
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
