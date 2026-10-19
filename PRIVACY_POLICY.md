# Privacy policy — MySQL Editor desktop

## Summary

The clean-room MySQL Editor is a local Windows SQL client. This implementation includes no analytics, telemetry, ads or hosted account service. It connects directly to the MySQL server specified by the user.

## Data stored on the device

- Connection metadata: profile name, host, port, username, default schema, TLS policy, CA file path and timeout values. When saving is enabled, the last-used profile identifier is remembered so the app can reconnect after the master-password unlock.
- Master-password verifier: Argon2id hash; the passphrase itself is not stored.
- Saved database password: only in Windows Credential Manager when the user elects to save a profile.
- Query history: disabled by default. If enabled, SQL text, profile label, status, duration and timestamp are stored in the local SQLite settings database.
- Saved snippets: SQL text stored in the application's local saved-queries directory when saved via the snippet command.
- Temporary result spool: fetched result rows are written to a temporary SQLite file to allow bounded previews and CSV export; the worker removes the spool at shutdown.

## Network connections

The app connects to the host and port chosen in its connection dialog. SQL and credentials are sent to that database connection, subject to the selected TLS policy. Automatic TLS does not verify server identity; strict mode enables certificate and hostname verification.\n\nThe optional update checker is **disabled by default**. Only after the user enables **Settings → Updates → Automatically check for updates at startup** does the app request public stable-release metadata from GitHub at startup. The user may also trigger a manual check after enabling the feature. The request includes the installed app version in its User-Agent and normal request metadata handled by GitHub (such as the network IP address). It does not include SQL, MySQL connection details, database credentials, result rows, device identifiers, or query history. The app does not download or install updates automatically.

## User controls

Query history can be enabled or disabled from Settings. Disabling it clears history. Saved profiles and their stored passwords can be removed from the app and Windows Credential Manager. To remove local settings completely, close the app and delete its user-data directory. This does not delete MySQL data.

## No server-side collection

This desktop build does not send database credentials, SQL text, result rows or usage data to the repository owner. Users are responsible for protecting their Windows login, saved SQL files, and exported data files.
