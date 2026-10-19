# Windows signing and release trust

The Windows release workflow can sign the application executables and installer with a trusted Authenticode certificate. If signing secrets are absent, pull-request builds and preview builds remain explicitly unsigned. Stable version tags are blocked unless signing is configured and the final signatures pass SignTool verification.

A valid signature helps Windows identify the publisher and detect changes to signed files. It does **not** guarantee that SmartScreen, antivirus, or other reputation-based warnings will never appear.

## Configure GitHub Actions secrets

Use a legitimate code-signing certificate from a reputable certificate authority. Do not present a self-signed certificate as trusted publisher verification.

Add both repository Actions secrets:

- `WINDOWS_SIGNING_CERTIFICATE_BASE64` — the PFX/P12 certificate file encoded as Base64.
- `WINDOWS_SIGNING_CERTIFICATE_PASSWORD` — the PFX/P12 password.

For example, on a trusted local machine, encode the certificate file with PowerShell:

```powershell
[Convert]::ToBase64String([System.IO.File]::ReadAllBytes("publisher-codesigning.pfx"))
```

Copy the output directly into the secret value. Keep the PFX and its password out of source control, pull-request comments, chat messages, ordinary files, and workflow logs. Never commit the private certificate.

The workflow intentionally does not expose signing secrets to `pull_request` runs. On trusted pushes or manual runs, it signs when both secrets are present. Configure both or neither; partial configuration fails.

## Signing and verification policy

When signing is enabled, the Windows workflow:

1. Writes the Base64-decoded PFX to the temporary hosted-runner directory.
2. Signs `MySQLEditor.exe`, `MySQLEditor-Portable.exe`, and `MySQLEditor-Setup.exe` with SHA-256 Authenticode and an RFC 3161 timestamp from DigiCert.
3. Verifies each signature with `SignTool verify /pa /all /v`. A signing or verification error fails the build.
4. Creates the folder ZIP, release manifest, and SHA-256 checksums **after** signing, so the digests describe the exact signed binaries.

The manifest records `signing.status = "signed"` and `authenticode_verified = true` only when the workflow reaches manifest generation after all three verifications pass. Otherwise, it records `unsigned` and does not claim verification.

Stable version tags such as `v1.0.0` require both signing secrets; publication is blocked if the certificate is missing or the signature cannot be verified. Explicit preview tags (for example, `v1.0.0-preview.1`, `v1.0.0-beta.1`, `v1.0.0-rc.1`) and normal main-branch preview builds may remain unsigned when no certificate is configured. The GitHub Release must still be marked as a pre-release for preview tags.

DigiCert's current SignTool instructions use `/tr http://timestamp.digicert.com /td SHA256 /fd SHA256`. Timestamping helps preserve signature validation after the signing certificate later expires; it does not certify that the application is safe.
