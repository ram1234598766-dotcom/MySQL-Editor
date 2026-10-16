# Windows signing and release trust

The Windows workflow builds packages but does not sign them with a publisher certificate. An unsigned installer can show an unknown-publisher or SmartScreen warning.

## Before publishing broadly

1. Obtain a legitimate code-signing certificate from a reputable certificate authority. Do not present a self-signed certificate as trusted publisher verification.
2. Store private signing material in GitHub Actions secrets, not in source control or workflow logs.
3. Add a signing step to the Windows workflow that imports the certificate into the temporary runner and signs the portable executable and installer.
4. Verify the final signatures with SignTool and add trusted timestamping.
5. Publish hashes for the final signed artifacts and smoke-test those exact files.

The current workflow makes no signing claim. A successful build cannot guarantee that SmartScreen or antivirus products will show no warning. Do not bypass security checks by obfuscating the executable, renaming files to evade scanners or disabling endpoint protection.
