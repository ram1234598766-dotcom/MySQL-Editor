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
$certificate = $null
$rootCertificateAdded = $false
$certutil = Join-Path $env:WINDIR "System32\certutil.exe"
if (!(Test-Path -LiteralPath $certutil -PathType Leaf)) {
    throw "certutil.exe was not found at the expected Windows system path: $certutil"
}
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
        Write-Host "Preparing temporary runner-local trust so Windows can verify the self-signed Authenticode chain."
        $publicCertificateBytes = $certificate.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
        [System.IO.File]::WriteAllBytes($certificatePublicPath, $publicCertificateBytes)
        Write-Host "Adding only the public self-signed certificate to this runner's current-user Root store via certutil.exe."
        "y" | & $certutil -user -f -addstore Root $certificatePublicPath
        if ($LASTEXITCODE -ne 0) {
            throw "certutil.exe failed to add the temporary public certificate to the current-user Root store (exit code $LASTEXITCODE)."
        }
        $rootCertificateAdded = $true
        Write-Host "Temporary public-certificate trust installed for this runner."
        Write-Host "Recipient PCs will not trust this self-signed certificate by default."
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

        if ($certificateType -eq "self-signed") {
            Write-Host "Verifying Authenticode signature with temporary runner-local trust: $target"
            $signature = Get-AuthenticodeSignature -FilePath $target
            $signatureStatus = $signature.Status.ToString()
            if ($signatureStatus -ne "Valid") {
                throw "Authenticode signature verification failed for $target (status: $signatureStatus)."
            }
            if ($null -eq $signature.SignerCertificate -or
                $signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
                throw "The Authenticode signature for $target does not match the configured self-signed certificate."
            }
            & $signTool verify /pa /all /v $target
            if ($LASTEXITCODE -ne 0) {
                throw "SignTool failed to verify the Authenticode signature for $target (exit code $LASTEXITCODE)."
            }
        } else {
            Write-Host "Verifying Authenticode signature and certificate trust: $target"
            & $signTool verify /pa /all /v $target
            if ($LASTEXITCODE -ne 0) {
                throw "SignTool failed to verify the Authenticode signature for $target (exit code $LASTEXITCODE)."
            }
        }
        Write-Host "Signed and verified: $(Split-Path $target -Leaf) (certificate type: $certificateType)"
    }
} finally {
    if ($rootCertificateAdded) {
        Write-Host "Removing the temporary self-signed certificate from this runner's current-user Root store."
        & $certutil -user -delstore Root $certificate.Thumbprint
        if ($LASTEXITCODE -ne 0) {
            throw "certutil.exe failed to remove the temporary public certificate from the current-user Root store (exit code $LASTEXITCODE)."
        }
        Write-Host "Removed the temporary self-signed certificate from this runner's Root store."
    }
    if ($certificate) {
        $certificate.Dispose()
    }
    Remove-Item -LiteralPath $certificatePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $certificatePublicPath -Force -ErrorAction SilentlyContinue
}
