# Security notes

## Credentials and SQL history

- The desktop and mobile apps do not persist the MySQL password entered in the connection dialog. Connection preferences contain host, port, user, database, TLS choice and optional CA path only.
- Desktop SQL history is memory-only by default. To explicitly opt into disk persistence, set `MYSQLIDLE_SAVE_HISTORY=1` in the environment before launching MySQL IDLE. Upgrading from a version that stored SQL history scrubs the saved history on the next launch when the option is disabled.
- Mobile query history is held in page memory only and is cleared on disconnect or session expiry.
- Prefer a dedicated MySQL account with only the permissions needed for the work. The application intentionally executes arbitrary SQL for authenticated sessions; pairing does not reduce database privileges.

## Mobile companion network security

- The mobile companion is disabled unless the user explicitly starts it. It binds to one selected private IPv4 interface and refuses wildcard/public addresses.
- The service uses HTTPS with a short-lived self-signed TLS certificate. Before connecting, the user must compare the complete SHA-256 certificate fingerprint displayed on the desktop with the fingerprint entered on the Android app. Android only proceeds through the self-signed trust error when the presented certificate fingerprint matches exactly; hostname and certificate-date errors remain blocking errors. The fingerprint changes when the desktop companion restarts, so it must be verified again for the new session.
- The Android app rejects non-private hosts and outbound navigation to origins other than the verified desktop endpoint. Cleartext HTTP is disabled by the Android manifest.
- The companion has temporary pairing codes, constant-time code comparison, rate-limited pairing attempts, ephemeral bearer tokens, session limits, a 30-minute idle expiry, Host/Origin checks, JSON-only POST requests, a 512 KiB request-body limit, a bounded request-worker pool and a 512 MiB result export limit.
- Stop the companion when it is not needed. Do not expose it with router port forwarding or on public Wi-Fi; use a trusted VPN/private tunnel for remote access. TLS certificate pinning secures the desktop-to-phone HTTP service connection, but it does not make an untrusted network or compromised desktop safe.

## MySQL transport security

- Windows direct MySQL connections use certificate-optional TLS by default for localhost/self-signed compatibility; TLS is attempted when supported but the server certificate and hostname are not verified. Users can enable verification and provide the MySQL CA certificate path. The paired Android companion continues to require verified MySQL TLS by default. Its HTTPS session to the desktop separately checks a user-supplied SHA-256 fingerprint.
- Certificate-optional TLS does not authenticate the server identity and is more vulnerable to network interception. For production or networks you do not fully trust, enable certificate/hostname verification and provide a trusted CA; keep the compatibility default limited to localhost or trusted networks.
- The mobile CA path is resolved on the desktop computer, since the desktop process makes the actual MySQL connection.

## Files, packaging and releases

- Query results are streamed to temporary CSV files instead of being retained entirely in memory; the mobile service stops exports above its configured size limit. The application attempts to remove temporary result files when sessions close or the application stops.
- CI tests cover SQL parsing, configuration privacy, result streaming, TLS connection-option wiring, mobile HTTPS headers, certificate fingerprints, Host/Origin validation, oversized request bodies and result-export limits.
- Android release APKs are signed and verified with `apksigner`. The recovery signing identity has an encrypted keystore backup artifact in GitHub Actions; download and securely retain that artifact and its password before its 90-day retention window expires. A new signing identity cannot update an app signed with a different certificate.
- Windows executables and installers are not code-signed unless a trusted Windows code-signing certificate is configured. Unsigned binaries can trigger Windows SmartScreen warnings. A successful build or valid Android APK signature is not a guarantee that all software vulnerabilities have been eliminated.

Report a suspected vulnerability privately to the repository owner rather than publishing exploit details in a public issue.
