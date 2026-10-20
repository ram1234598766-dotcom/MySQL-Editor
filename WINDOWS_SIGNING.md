# Windows signing and release trust

**Preview policy:** Pull-request builds, main-branch preview builds, and preview version tags stay **unsigned**, even if signing secrets are configured. A stable version-tag push builds and signs a candidate artifact but does **not** publish a stable GitHub Release. Publication requires a separate manual workflow dispatch on that exact tag with `publish_release` explicitly set to `true`, after the signed artifact has been reviewed and the manual Windows acceptance checklist is complete. Preview version tags continue to publish prereleases automatically.

**Selected certificate policy:** The workflow defaults to a **self-signed code-signing certificate**. The signature can be checked, but Windows does not trust this certificate on recipient PCs by default. A self-signed signature does not establish a publicly trusted publisher identity and does not eliminate SmartScreen or unknown-publisher warnings. A trusted CA-issued certificate is also supported by setting the repository variable described below.

## 1. Create a self-signed code-signing certificate

Run PowerShell on a trusted Windows machine. Keep the resulting PFX and its password private; do not commit or upload them as ordinary repository files.

```powershell
$cert = New-SelfSignedCertificate `
  -Type CodeSigningCert `
  -Subject "CN=MySQL Editor Release Signing" `
  -CertStoreLocation "Cert:\CurrentUser\My" `
  -KeyAlgorithm RSA `
  -KeyLength 3072 `
  -HashAlgorithm SHA256 `
  -KeyExportPolicy Exportable `
  -NotAfter (Get-Date).AddYears(3)

$pfxPassword = Read-Host "Choose a strong PFX password" -AsSecureString
Export-PfxCertificate -Cert $cert -FilePath ".\mysql-editor-signing.pfx" -Password $pfxPassword

[Convert]::ToBase64String([System.IO.File]::ReadAllBytes(".\mysql-editor-signing.pfx"))
```

Store the PFX securely and keep the same certificate for the signing identity where possible. Losing the PFX/private key prevents later signing with that certificate. The Base64 command prints the encoded PFX; it does not make the private key safe to share publicly.

## 2. Configure GitHub Actions

Add these repository Actions **secrets**:

- `WINDOWS_SIGNING_CERTIFICATE_BASE64` — the complete Base64 output from the previous step.
- `WINDOWS_SIGNING_CERTIFICATE_PASSWORD` — the password chosen for the PFX.

The workflow defaults to self-signed mode. The optional repository **variable** `WINDOWS_SIGNING_CERTIFICATE_TYPE` accepts `self-signed` or `trusted`; leave it unset or set it to `self-signed` for the selected policy. Use `trusted` only when the supplied certificate is issued by a certificate authority and validates against Windows trust policy.

Configure both secrets or neither. Partial configuration fails. Signing secrets are not made available to pull-request workflows. The self-signed test step creates a short-lived test certificate and signs a **temporary, freshly compiled unsigned EXE**; it does not sign or mutate a distributed preview artifact. On a push to `main`, when the signing secrets are configured, the workflow also compiles an unsigned disposable Windows executable and signs/verifies it against the approved certificate fingerprint. That check does not publish a release and does not change the preview binaries; if the secrets are absent, the optional certificate smoke step is skipped while stable tags remain blocked.

The PFX currently configured in the repository has signer SHA-256 thumbprint `88FA4DE793F0883E7B8DA30EE6C3E76D555CB5F4`. The workflow pins this public certificate identity and checks it against the signer on a disposable executable. The PFX and its password are not changed by this code; update the fingerprint only when deliberately changing the configured certificate.

## 3. Stable-release signing and verification

For a stable version tag (for example, `v1.0.0`), the Windows release workflow:

1. Requires both signing secrets. A push of a stable version tag creates a signed candidate in the Actions artifact only; it does not publish a release. Publication is a separate manual workflow dispatch on the same tag with `publish_release = true`, and only after the candidate and manual Windows acceptance checklist have been reviewed.
2. Checks that the PFX contains a currently valid Code Signing certificate and private key.
3. For a self-signed certificate, the helper does **not** modify the hosted runner's certificate stores. It checks `Get-AuthenticodeSignature` status and the signer thumbprint. It accepts `Valid`, or accepts `UnknownError`/`NotTrusted` only when Windows' status message explicitly reports an untrusted root chain—the expected trust limitation for a self-signed certificate. A hash mismatch, expired/revoked certificate, missing signer, or unrelated verification error fails. This checks signature integrity and signer identity without claiming that the publisher is trusted on recipient PCs.
4. Signs the app-folder executable, portable EXE, and setup installer with SHA-256 Authenticode and an RFC 3161 timestamp from DigiCert.
5. In self-signed mode, the helper requires a matching signer thumbprint and either a `Valid` signature status or the specifically identified untrusted-root-chain status; every other status fails. In `trusted` mode, it runs `SignTool verify /pa /all /v` so Windows policy and certificate trust are verified.
6. Creates the folder ZIP, release manifest, and SHA-256 checksums after signing, so those hashes describe the final signed artifacts.

The manifest records the signing status, certificate type, verification scope, and whether recipient trust is established by default. For the selected self-signed certificate, it reports `certificate_type = "self-signed"`, `trust_scope = "signature-integrity-only"`, and `recipient_trust = "not-trusted-by-default"`. Self-signed verification does not modify the runner's trust store; it checks Authenticode status/status message and signer thumbprint, accepting only the specific untrusted-root-chain result in lieu of a trusted-chain status. A trusted CA certificate uses Windows trust-policy verification instead; SmartScreen behavior still depends on reputation and client environment.

Timestamping preserves the time at which the signature was applied after the signing certificate later expires, when the timestamp service and signature remain valid. It is not a safety certification.

## 4. Explicit publication gate

The workflow is intentionally two-stage for stable versions:

1. Push the version tag. The workflow runs the test matrix, signs and verifies the application-folder executable, portable EXE, and setup installer, generates the manifest and `SHA256SUMS`, and uploads the candidate as the `MySQLEditor-Windows` Actions artifact. No stable GitHub Release is created by that tag push.
2. Inspect that exact artifact, manifest, checksums, and signature evidence; complete `RELEASE-CANDIDATE-CHECKLIST.md`, including the required hands-on Windows acceptance.
3. From Actions, run **MySQL Editor Windows packages** on that exact version tag and explicitly set `publish_release` to `true`. The write-enabled publication job requires this input and only then creates the GitHub Release. Leaving it false reruns the validation/build without publishing.

This prevents a newly pushed stable tag from immediately publishing before a reviewer checks the signed files. The isolated publish job remains the only job with `contents: write`.

## 5. Limitations recipients should understand

- A self-signed signature can detect post-signing changes and identify the certificate embedded in the signature, but **does not make that certificate trusted on other PCs**.
- Recipients may see unknown-publisher, SmartScreen, or antivirus warnings. Do not promise warning-free installation.
- Do not advise users to disable SmartScreen or certificate validation globally. If an organization intentionally distributes a self-signed certificate internally, its administrators must distribute and trust the certificate through their own managed policy.
- SHA-256 checksums verify file equality against the published values. They do not prove that software is safe or establish publisher trust.
