param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string[]]$Targets
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($env:WINDOWS_SIGNING_CERTIFICATE_BASE64)) {
    throw "WINDOWS_SIGNING_CERTIFICATE_BASE64 is required."
}
if ([string]::IsNullOrWhiteSpace($env:WINDOWS_SIGNING_CERTIFICATE_PASSWORD)) {
    throw "WINDOWS_SIGNING_CERTIFICATE_PASSWORD is required."
}
if ([string]::IsNullOrWhiteSpace($env:WINDOWS_SIGNING_TIMESTAMP_URL)) {
    throw "WINDOWS_SIGNING_TIMESTAMP_URL is required."
}
if ($Targets.Count -eq 0) {
    throw "At least one executable target must be specified."
}

$certificatePath = Join-Path $env:RUNNER_TEMP ("mysql-editor-signing-{0}.pfx" -f [Guid]::NewGuid().ToString("N"))
try {
    $certificateBytes = [Convert]::FromBase64String($env:WINDOWS_SIGNING_CERTIFICATE_BASE64)
    [System.IO.File]::WriteAllBytes($certificatePath, $certificateBytes)

    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $signToolCandidates = @(
        Get-ChildItem -Path $kitsRoot -Filter signtool.exe -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '[\\/]x64[\\/]signtool\.exe$' }
    )
    if ($signToolCandidates.Count -eq 0) {
        throw "SignTool.exe was not found in the Windows SDK x64 tools directory."
    }
    $signTool = $signToolCandidates[0].FullName

    foreach ($relativeTarget in $Targets) {
        $target = (Resolve-Path -LiteralPath $relativeTarget).Path
        & $signTool sign /fd SHA256 /tr $env:WINDOWS_SIGNING_TIMESTAMP_URL /td SHA256 /f $certificatePath /p $env:WINDOWS_SIGNING_CERTIFICATE_PASSWORD $target
        if ($LASTEXITCODE -ne 0) {
            throw "SignTool failed to sign $target (exit code $LASTEXITCODE)."
        }

        & $signTool verify /pa /all /v $target
        if ($LASTEXITCODE -ne 0) {
            throw "SignTool failed to verify the Authenticode signature for $target (exit code $LASTEXITCODE)."
        }
        Write-Host "Signed and verified: $(Split-Path $target -Leaf)"
    }
} finally {
    Remove-Item -LiteralPath $certificatePath -Force -ErrorAction SilentlyContinue
}
