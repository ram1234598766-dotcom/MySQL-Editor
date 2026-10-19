param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string[]]$Targets,

    [Parameter(Mandatory = $false)]
    [switch]$SkipTimestamp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($env:WINDOWS_SIGNING_CERTIFICATE_BASE64)) {
    throw "WINDOWS_SIGNING_CERTIFICATE_BASE64 is required."
}
if ([string]::IsNullOrWhiteSpace($env:WINDOWS_SIGNING_CERTIFICATE_PASSWORD)) {
    throw "WINDOWS_SIGNING_CERTIFICATE_PASSWORD is required."
}
if (-not $SkipTimestamp -and [string]::IsNullOrWhiteSpace($env:WINDOWS_SIGNING_TIMESTAMP_URL)) {
    throw "WINDOWS_SIGNING_TIMESTAMP_URL is required for release signing."
}
if ($Targets.Count -eq 0) {
    throw "At least one executable target must be specified."
}

$certificateType = $env:WINDOWS_SIGNING_CERTIFICATE_TYPE
if ([string]::IsNullOrWhiteSpace($certificateType)) {
    $certificateType = "self-signed"
}
$certificateType = $certificateType.Trim().ToLowerInvariant()
if ($certificateType -notin @("self-signed", "trusted")) {
    throw "WINDOWS_SIGNING_CERTIFICATE_TYPE must be 'self-signed' or 'trusted'."
}

$certificatePath = Join-Path $env:RUNNER_TEMP ("mysql-editor-signing-{0}.pfx" -f [Guid]::NewGuid().ToString("N"))
$certificatePublicPath = Join-Path $env:RUNNER_TEMP ("mysql-editor-signing-public-{0}.cer" -f [Guid]::NewGuid().ToString("N"))
$rootThumbprint = $null
$certificate = $null
try {
    Write-Host "Decoding the supplied PFX payload."
    $certificateBytes = [Convert]::FromBase64String($env:WINDOWS_SIGNING_CERTIFICATE_BASE64)
    [System.IO.File]::WriteAllBytes($certificatePath, $certificateBytes)
    Write-Host "Loading the PFX certificate and private key."

    $certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
        $certificatePath,
        $env:WINDOWS_SIGNING_CERTIFICATE_PASSWORD,
        [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
    )
    Write-Host "PFX loaded; validating private key and certificate metadata."
    if (-not $certificate.HasPrivateKey) {
        throw "The supplied PFX does not contain a usable private key."
    }
    $nowUtc = [DateTime]::UtcNow
    if ($nowUtc -lt $certificate.NotBefore.ToUniversalTime() -or $nowUtc -gt $certificate.NotAfter.ToUniversalTime()) {
        throw "The code-signing certificate is not currently within its validity period."
    }

    $hasCodeSigningEku = $false
    foreach ($extension in $certificate.Extensions) {
        if ($extension -is [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]) {
            foreach ($usage in $extension.EnhancedKeyUsages) {
                if ($usage.Value -eq "1.3.6.1.5.5.7.3.3") {
                    $hasCodeSigningEku = $true
                }
            }
        }
    }
    if (-not $hasCodeSigningEku) {
        throw "The supplied certificate does not declare the Code Signing EKU."
    }

    if ($certificateType -eq "self-signed") {
        if (-not [StringComparer]::Ordinal.Equals($certificate.Subject, $certificate.Issuer)) {
            throw "The certificate type is self-signed, but its subject and issuer do not match."
        }

        # SignTool policy verification requires a root of trust. Temporarily add this
        # certificate only to the hosted runner's CurrentUser\Root store and remove it
        # in finally. This does not make recipients trust the certificate.
        $rootStorePath = "Cert:\CurrentUser\Root"
        $thumbprintStorePath = Join-Path $rootStorePath $certificate.Thumbprint
        $existingRoot = Get-Item -LiteralPath $thumbprintStorePath -ErrorAction SilentlyContinue
        if ($null -eq $existingRoot) {
            [System.IO.File]::WriteAllBytes(
                $certificatePublicPath,
                $certificate.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
            )
            Write-Host "Temporarily trusting the self-signed certificate for this runner only."
            Import-Certificate -FilePath $certificatePublicPath -CertStoreLocation $rootStorePath | Out-Null
            $rootThumbprint = $certificate.Thumbprint
            Write-Host "Temporary certificate trust installed."
        }
        Write-Host "Self-signed certificate trust is temporary and local to this runner; recipient PCs will not trust it by default."
    }

    $programFilesX86 = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
    $kitsRoot = Join-Path $programFilesX86 "Windows Kits\10\bin"
    Write-Host "Locating SignTool in installed Windows SDK version directories."
    $signToolCandidates = @()
    if (Test-Path -LiteralPath $kitsRoot -PathType Container) {
        $sdkDirectories = Get-ChildItem -LiteralPath $kitsRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object -Property Name -Descending
        foreach ($sdkDirectory in $sdkDirectories) {
            $candidate = Join-Path $sdkDirectory.FullName "x64\signtool.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $signToolCandidates += $candidate
            }
        }
        $directCandidate = Join-Path $kitsRoot "x64\signtool.exe"
        if ((Test-Path -LiteralPath $directCandidate -PathType Leaf) -and $signToolCandidates.Count -eq 0) {
            $signToolCandidates += $directCandidate
        }
    }
    if ($signToolCandidates.Count -eq 0) {
        throw "SignTool.exe was not found in the Windows SDK x64 tools directory under $kitsRoot."
    }
    $signTool = $signToolCandidates[0]
    Write-Host "Using SignTool: $signTool"

    if ($SkipTimestamp) {
        Write-Host "Timestamping skipped for the temporary signing smoke test only; release signing must timestamp."
    }

    foreach ($relativeTarget in $Targets) {
        $target = (Resolve-Path -LiteralPath $relativeTarget).Path
        $signArgs = @("sign", "/fd", "SHA256")
        if (-not $SkipTimestamp) {
            $signArgs += @("/tr", $env:WINDOWS_SIGNING_TIMESTAMP_URL, "/td", "SHA256")
        }
        $signArgs += @("/f", $certificatePath, "/p", $env:WINDOWS_SIGNING_CERTIFICATE_PASSWORD, $target)
        Write-Host "Signing target: $target"
        & $signTool @signArgs
        if ($LASTEXITCODE -ne 0) {
            throw "SignTool failed to sign $target (exit code $LASTEXITCODE)."
        }

        Write-Host "Verifying Authenticode signature: $target"
        & $signTool verify /pa /all /v $target
        if ($LASTEXITCODE -ne 0) {
            throw "SignTool failed to verify the Authenticode signature for $target (exit code $LASTEXITCODE)."
        }
        Write-Host "Signed and verified: $(Split-Path $target -Leaf) (certificate type: $certificateType)"
    }
} finally {
    if ($rootThumbprint) {
        Remove-Item -LiteralPath ("Cert:\CurrentUser\Root\{0}" -f $rootThumbprint) -Force -ErrorAction SilentlyContinue
    }
    if ($certificate) {
        $certificate.Dispose()
    }
    Remove-Item -LiteralPath $certificatePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $certificatePublicPath -Force -ErrorAction SilentlyContinue
}
