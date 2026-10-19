# Windows signing and release trust

**Preview policy:** Pull-request builds, main-branch preview builds, and preview version tags stay **unsigned**, even if signing secrets are configured. Stable version tags require the signing secrets and successful signature verification before publication.

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

## 3. Stable-release signing and verification

For a stable version tag (for example, `v1.0.0`), the Windows release workflow:

1. Requires both signing secrets; it refuses to publish a stable version tag unsigned.
2. Checks that the PFX contains a currently valid Code Signing certificate and private key.
3. For a self-signed certificate, does **not** modify the runner's trust store. It uses `Get-AuthenticodeSignature` to check signature status and signer-certificate thumbprint. `NotTrusted` is accepted only for the expected self-signed chain limitation; hash mismatches and all other statuses fail. This verifies signature integrity, not public publisher trust.
4. Signs the app-folder executable, portable EXE, and setup installer with SHA-256 Authenticode and an RFC 3161 timestamp from DigiCert.
5. For self-signed mode, checks Authenticode signature integrity and confirms each signer matches the configured certificate. For `trusted` mode, runs `SignTool verify /pa /all /v` so Windows policy and certificate trust are verified. Any signing or verification error fails the workflow.
6. Creates the folder ZIP, release manifest, and SHA-256 checksums after signing, so those hashes describe the final signed artifacts.

The manifest records the signing status, certificate type, verification scope, and whether recipient trust is established by default. For the selected self-signed certificate, it reports `certificate_type = "self-signed"`, `trust_scope = "signature-integrity-only"`, and `recipient_trust = "not-trusted-by-default"`. The self-signed verification helper does not modify the build runner's trust store; it accepts only the expected `Valid` or `NotTrusted` Authenticode status and checks that the signer thumbprint matches the configured certificate. This verifies signature integrity and certificate identity, not recipient trust. A trusted CA certificate uses Windows trust-policy verification instead; SmartScreen behavior still depends on reputation and client environment.

Timestamping preserves the time at which the signature was applied after the signing certificate later expires, when the timestamp service and signature remain valid. It is not a safety certification.

## 4. Limitations recipients should understand

- A self-signed signature can detect post-signing changes and identify the certificate embedded in the signature, but **does not make that certificate trusted on other PCs**.
- Recipients may see unknown-publisher, SmartScreen, or antivirus warnings. Do not promise warning-free installation.
- Do not advise users to disable SmartScreen or certificate validation globally. If an organization intentionally distributes a self-signed certificate internally, its administrators must distribute and trust the certificate through their own managed policy.
- SHA-256 checksums verify file equality against the published values. They do not prove that software is safe or establish publisher trust.
