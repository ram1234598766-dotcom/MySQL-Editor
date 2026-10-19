param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$outputDirectory = Split-Path -Parent $OutputPath
if ([string]::IsNullOrWhiteSpace($outputDirectory)) {
    throw "OutputPath must include a directory."
}
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

$compilerCandidates = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
)
$compiler = $compilerCandidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($compiler)) {
    throw "The .NET Framework C# compiler (csc.exe) was not found on this Windows runner."
}

$sourcePath = Join-Path $outputDirectory ("signing-smoke-{0}.cs" -f [Guid]::NewGuid().ToString("N"))
try {
    @"
using System;

internal static class SigningSmoke
{
    private static void Main()
    {
    }
}
"@ | Set-Content -LiteralPath $sourcePath -Encoding ascii

    Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
    Write-Host "Compiling a minimal, unsigned Windows executable for signing verification."
    & $compiler /nologo /target:winexe ("/out:{0}" -f $OutputPath) $sourcePath
    if ($LASTEXITCODE -ne 0) {
        throw "The C# compiler failed to build the disposable signing target (exit code $LASTEXITCODE)."
    }
    if (!(Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
        throw "The C# compiler did not create the disposable signing target: $OutputPath"
    }

    $signature = Get-AuthenticodeSignature -FilePath $OutputPath
    if ($signature.Status.ToString() -ne "NotSigned") {
        throw "The signing smoke-test target must begin unsigned; got status '$($signature.Status)'."
    }
    Write-Host "Created unsigned signing target: $OutputPath"
} finally {
    Remove-Item -LiteralPath $sourcePath -Force -ErrorAction SilentlyContinue
}