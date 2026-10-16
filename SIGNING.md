# Release signing setup

The workflow never publishes a debug APK as a GitHub Release. A signed Android APK can be published once all four Android secrets are configured. Windows release files are included whenever the Windows build succeeds; when Windows signing secrets are absent, those assets are unsigned and a WINDOWS-SIGNING-STATUS.txt notice is attached.

## 1. Android release keystore

Create a long-lived Android signing key on a trusted computer. Back up the keystore securely; losing it means the existing self-managed APK cannot be updated in place with the same app identity. Do **not** commit the keystore to Git.

With a JDK installed, run:

```powershell
keytool -genkeypair -v -keystore mysqlidle-release.jks -alias mysqlidle -keyalg RSA -keysize 4096 -validity 10000
```

Use passwords you generate and store safely. When prompted for certificate identity, enter the publisher information you want embedded in the Android certificate. Keep the `.jks` file and both passwords backed up in a secure location separate from GitHub.

Convert the keystore to a single-line Base64 value in PowerShell:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path .\mysqlidle-release.jks))) | Set-Clipboard
```

In the repository, open **Settings → Secrets and variables → Actions → New repository secret** and add these secrets:

| Secret name | Value |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | Clipboard value containing the Base64-encoded `.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | The keystore/store password entered when you created or changed the `.jks` file |
| `ANDROID_KEY_ALIAS` | The exact key alias inside that keystore, e.g. `mysqlidle` if you used that alias |
| `ANDROID_KEY_PASSWORD` | The private-key password for that alias (it may be the same as the store password, but does not have to be) |

**Do not swap the two password secrets.** `ANDROID_KEYSTORE_PASSWORD` must open the keystore file; `ANDROID_KEY_PASSWORD` unlocks the private key inside it. If Gradle reports that the keystore password is incorrect, verify `ANDROID_KEYSTORE_PASSWORD` against the same keystore file you encoded. If the keystore and key use different passwords, keep the values separate.

Before Gradle packaging, CI now validates the store password, alias, and private-key password with `keytool`. Diagnostics name the failing secret variable but never print secret values. The completed APK is still checked with Android's `apksigner`.

## 2. Trusted Windows code-signing certificate

Obtain a **valid publicly trusted code-signing certificate** from a certificate authority or use Microsoft's Artifact Signing service. A self-signed certificate can create a cryptographic signature but does not establish trusted publisher identity for general Windows users and does not solve the SmartScreen trust issue. Microsoft notes that even signed new applications can still get SmartScreen warnings while reputation builds: https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation.

For a PFX/P12 certificate file that includes its private key, create a single-line Base64 value in PowerShell:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path .\publisher-code-signing.pfx))) | Set-Clipboard
```

Add these repository Actions secrets:

| Secret name | Value |
| --- | --- |
| `WINDOWS_CERTIFICATE_BASE64` | Base64 value for the trusted code-signing `.pfx`/ `.p12` file |
| `WINDOWS_CERTIFICATE_PASSWORD` | PFX password |

The certificate must be valid for code signing and include its private key. Do not send the PFX or passwords in chat or commit them to Git. The workflow uses SignTool with SHA-256 file digests and an RFC 3161 timestamp, signs the portable EXE, EXEs within the folder build, and installer, then verifies each signature before archiving/uploading.

## 3. Produce a signed release

After all four Android secrets are set, open **Actions → Build Windows EXE and Android APK → Run workflow** on `main`. The workflow builds, verifies, and publishes the release-signed Android APK as a prerelease asset. Only the APK is generated for Android distribution; it is intended for direct installation/testing. If the Windows build succeeds, its portable EXE, folder archive, and installer are also included. With the Windows secrets configured, CI signs and verifies those binaries; without them, CI includes the files with an explicit unsigned warning.

Check the workflow run for successful signature-verification steps. The release APK will be named `MySQLEditor-Mobile-release.apk`. Windows downloads keep their regular filenames, and Authenticode signatures must verify and identify your publisher certificate.

## 3A. Google Play distribution and installation warnings

A signed APK can still trigger Play Protect or Android's unrecognized-developer warning when users install it directly from a website. The build pipeline cannot force a Google reputation verdict and must not disable or work around the user's device protections. This repository's workflow is configured for APK-only output. Before distributing through an app store, review that store's current submission requirements separately and preserve signing-key continuity for existing installs. If Google Play Protect incorrectly classifies the app as harmful, use Google's official app-verification appeal process: https://support.google.com/googleplay/android-developer/answer/2992033.

## 4. Recovery signing identity generated by CI

If the supplied keystore cannot be decoded or its password, alias, or private-key password cannot be validated, the workflow first tries the encrypted backup artifact from an earlier run. If neither the supplied keystore nor a saved backup is usable, **CI stops release signing by default** so it cannot silently replace the app's signing identity.

Only when you intentionally want to initialize a new signing identity (for example, before any public release, or after explicitly accepting that existing installations cannot update in place) should you create a repository Actions **variable** named `ANDROID_ALLOW_NEW_SIGNING_KEY` with value `true`. This variable is an explicit opt-in, not a signing secret. The workflow then generates a self-managed release key with alias `mysqlidle-release`, using the current `ANDROID_KEYSTORE_PASSWORD` as both keystore and private-key password. A different key cannot update an app installed with another signing certificate, so do not enable this variable merely to get past a decoding or password error.

When CI restores or explicitly creates a recovery key, it uploads a separate Actions artifact named `MySQLIDLE-SigningKey-Backup`. The private keystore is encrypted using AES-256-CBC with PBKDF2 (600,000 iterations) and `ANDROID_KEYSTORE_PASSWORD`; the encrypted backup is not included in the public Release downloads. The workflow can reuse the backup from a prior run while the artifact is retained (90 days), and refreshes it during later successful builds. Keep the password unchanged until you have saved and migrated the key; losing the password or encrypted key prevents future updates with the same identity.

For a durable long-term backup, download `MySQLIDLE-SigningKey-Backup` from the successful workflow run and decrypt `MySQLIDLE-SigningKey.jks.enc` on your own computer. With OpenSSL installed, PowerShell can decrypt it without displaying the password:

```powershell
$secure = Read-Host "ANDROID_KEYSTORE_PASSWORD" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:ANDROID_KEYSTORE_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -in .\MySQLIDLE-SigningKey.jks.enc -out .\mysqlidle-release.jks -pass env:ANDROID_KEYSTORE_PASSWORD
} finally {
    if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    Remove-Item Env:ANDROID_KEYSTORE_PASSWORD -ErrorAction SilentlyContinue
}
```

To stop depending on the temporary Actions backup, encode the decrypted key as Base64 and update the repository secrets: set `ANDROID_KEYSTORE_BASE64` to the clipboard value, set `ANDROID_KEY_ALIAS` to `mysqlidle-release`, and set `ANDROID_KEY_PASSWORD` to the same password as `ANDROID_KEYSTORE_PASSWORD`. Keep the keystore itself and its password in secure offline backups.

## 5. Important boundaries

- Android's release keystore and Windows' publisher certificate are distinct signing identities.
- This project currently uses application ID `com.mysqlidle.mobile`. If you later publish to Google Play, review Play App Signing and its upload-key model before your first release.
- Code signing is not malware scanning or an automatic guarantee that Windows SmartScreen will stop warning. Use a consistent trusted publisher identity and never modify signed files after signing.
- Do not upload signing credentials to workflow artifacts, commit them, or print them in CI logs.
