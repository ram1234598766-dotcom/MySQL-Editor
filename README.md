# MySQL Editor 3.0

**A desktop SQL workspace for MySQL and MariaDB, with an optional authenticated Android companion.**

MySQL Editor provides a dark, Figma-inspired desktop SQL workspace with a multiline editor, line numbers, syntax highlighting, guarded execution, saved snippets, and an in-window result grid. It runs `.sql` scripts and exports full result sets. Its optional Android companion lets a paired device use a responsive SQL workspace through an HTTPS service hosted by the Windows desktop.

![MySQL Editor logo](assets/mysqlidle-logo.png)

[![Build Windows EXE and Android APK](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/workflows/build-exe-apk.yml/badge.svg?branch=main)](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/workflows/build-exe-apk.yml)
[![Security checks](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/workflows/security.yml)

---

## Contents

- [Product identity and compatibility](#product-identity-and-compatibility)
- [Features](#features)
- [Latest downloads](#latest-downloads)
- [System requirements](#system-requirements)
- [Install on Windows](#install-on-windows)
- [Run from source](#run-from-source)
- [First launch and master password](#first-launch-and-master-password)
- [Connect to MySQL or MariaDB](#connect-to-mysql-or-mariadb)
- [Using the SQL editor](#using-the-sql-editor)
- [Feature Governance](#feature-governance)
- [Android companion setup](#android-companion-setup)
- [Security and privacy](#security-and-privacy)
- [Configuration and local files](#configuration-and-local-files)
- [Build from source](#build-from-source)
- [Tests and continuous integration](#tests-and-continuous-integration)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)
- [Known limitations](#known-limitations)
- [Contributing and security reports](#contributing-and-security-reports)
- [License](#license)

## Product identity and compatibility

- **Repository:** [`ram1234598766-dotcom/MySQL-Editor`](https://github.com/ram1234598766-dotcom/MySQL-Editor)
- **Displayed product name:** MySQL Editor (Windows desktop, installer, Android launcher and mobile workspace).
- **Desktop and Android implementation:** Python/Tkinter Windows SQL workspace plus an Android app paired with the desktop-hosted HTTPS companion.
- **Original application identity:** the Android package remains `com.mysqlidle.mobile`. Keep this application ID and the existing Android signing key stable for users to receive in-place updates.
- **Upgrade compatibility:** the Windows installer uses the previous product's installer ID and retains the existing `MySQL IDLE` install/data directory paths. These are intentional compatibility paths, not the displayed product name.
- **New download names:** the current build workflow uses `MySQLEditor-Setup.exe`, `MySQLEditor_Portable.exe`, `MySQLEditor-Folder.zip`, and `MySQLEditor-Mobile-release.apk` for Android. The workflow builds APK files only, with no additional package format.

Use the repository's [Build workflow](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/workflows/build-exe-apk.yml) for the current build result. A workflow artifact is a temporary CI output; only a published asset on the [Releases page](https://github.com/ram1234598766-dotcom/MySQL-Editor/releases) is a GitHub release download. The Android workflow intentionally does not publish a debug APK as a public release.

## Features

### Desktop SQL workspace

- Connect to MySQL or MariaDB with a host, port, username, and database.
- Edit multi-line SQL in a dedicated editor with a dark code surface, line numbers, syntax highlighting, and completion for SQL keywords, databases, tables, and columns.
- Run individual statements, multi-statement input, or a `.sql` script.
- Preview actual query results in the workspace grid or open them in a sortable table window; export full result sets to CSV.
- Stream query results in batches to temporary CSV files so large result sets do not all need to stay in memory.
- Keep the interface responsive while a query runs on a background worker thread.
- Cancel the active query with `Ctrl+Break` when the connected MySQL account has permission to do so.
- Save the current SQL buffer to a `.sql` file with **Ctrl+S**.
- Format the current statement with **Ctrl+Shift+F** without modifying quoted strings, quoted identifiers, or comments.
- Prepare an `EXPLAIN` plan for one `SELECT` using **Ctrl+Shift+E**; it inserts the statement for review and never executes it automatically.
- Copy the current SQL statement with **Ctrl+Shift+C**.
- Save and reinsert named SQL snippets; Windows stores snippets locally only after an explicit save action.
- Use guarded SQL execution and read-only policy options through **Tools → Feature Governance**.

### Optional Android companion

- Use a responsive SQL interface in the Android app, linked to the desktop-hosted companion.
- Pair with the Windows master password and a temporary code shown on the desktop.
- Verify the desktop HTTPS certificate by comparing its complete SHA-256 fingerprint before connecting.
- Keep credentials, query history, and named SQL snippets session-only rather than saving them in persistent browser storage.
- Format SQL, prepare a reviewed `EXPLAIN SELECT` statement, or copy the editor contents without leaving the mobile workspace.
- Save up to 20 named snippets in memory for the current mobile session; they are discarded when the session is cleared or the page reloads.
- Use query history and quick templates for common read-only checks, such as server version, current database, database/table lists, and server time.

### Security-minded defaults

- MySQL passwords entered in the connection form are not saved in the app's connection preferences.
- The master password is stored as a salted password verifier, not plaintext.
- The mobile companion is started explicitly and binds to a selected private IPv4 interface.
- The Android manifest requests only the `INTERNET` permission.
- The Android app disables cleartext HTTP and restricts connections to the verified desktop endpoint.
- SQL risk checks, resource limits, integration tests, and static security checks are part of the project workflow; release-signature verification is conditional on valid signing credentials.

These controls reduce risk but do not replace least-privilege database accounts, sound backups, trusted networks, or review of SQL before execution.

## Latest downloads

Check the [latest GitHub Actions runs](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/workflows/build-exe-apk.yml) for build artifacts and the [GitHub Releases page](https://github.com/ram1234598766-dotcom/MySQL-Editor/releases) for publish-ready downloads. A green CI build does not necessarily mean a public release has been published.

Android release APK/AAB publication requires all four Android signing secrets to be configured and validated. Windows packages are built when the Windows job succeeds; without trusted Windows code-signing secrets they may be unsigned and Windows can show an unknown-publisher warning. Use debug Android packages only for testing, not public distribution. See [SIGNING.md](SIGNING.md) for signing setup and key continuity.

Expected public-release filenames:

| Package | Asset filename | Intended use |
| --- | --- | --- |
| Windows installer | `MySQLEditor-Setup.exe` | Standard Windows installation |
| Windows portable executable | `MySQLEditor_Portable.exe` | Run without installing |
| Windows application folder | `MySQLEditor-Folder.zip` | Extract the entire folder and keep its files together |
| Android APK | `MySQLEditor-Mobile-release.apk` | Direct Android installation/testing |
| SHA-256 manifest | `SHA256SUMS` | Verify downloaded assets |

A valid signature and passing CI checks do **not** guarantee that Google Play Protect will classify an app as safe. If Android explicitly says an app is harmful, cancel installation rather than overriding the warning. Do not disable Play Protect or repackage the app to evade it. If a released build appears to be misclassified, use Google's [official app-verification appeal process](https://support.google.com/googleplay/android-developer/answer/2992033).

## System requirements

### To run the packaged Windows app

- A supported Windows installation capable of running the published executable/installer.
- Network access to the MySQL or MariaDB server.
- The application does not require a separate Python installation when using the packaged release.

### To run the desktop app from source

- Python 3.15 is used by the CI build and recommended for development.
- A working Tkinter installation for the desktop GUI.
- Network access to the MySQL or MariaDB server.
- Dependencies listed in [requirements.txt](requirements.txt).

### To build the Android app

- JDK 17.
- Android SDK Platform 36 and Android build tools.
- Android Gradle plugin and Gradle versions defined by `android-app/build.gradle.kts` and the CI workflow.
- A signing keystore and its secrets for a release-signed APK/AAB; debug builds are for development/testing only.

## Install on Windows

1. Download `MySQLEditor-Setup.exe` from the [latest successful GitHub release](https://github.com/ram1234598766-dotcom/MySQL-Editor/releases).
2. Run the installer. The default installation is under your Windows user's local application-data programs directory and is designed for per-user installation.
3. Use the Start Menu or desktop shortcut to launch **MySQL Editor**. The branded **Connect to MySQL** page opens automatically.
4. On first launch, create a master password and re-enter the same password in the confirmation field immediately below it. Then fill in the MySQL/MariaDB connection fields and select **Connect**.
5. On later launches, only the compact **Connect to MySQL** dialog appears initially. Enter the master password there and select **Connect**; the large SQL workspace stays hidden until the database server accepts the connection. If the connection fails, the compact dialog reopens with the connection details so you can correct them without exposing the workspace. There is no separate unlock window.

Alternative packages:

- **Portable EXE:** download `MySQLEditor_Portable.exe` and run it directly.
- **Folder ZIP:** extract the archive completely and run `mysql_idle.exe` from the extracted folder. Do not move the executable away from its accompanying `_internal` files.

The installer creates desktop and Start Menu shortcuts. For upgrades from earlier builds, the installed program folder and per-user settings directory intentionally retain the legacy `MySQL IDLE` folder name, and the Android application ID remains `com.mysqlidle.mobile`; the displayed product name and new package filenames are MySQL Editor. Uninstall uses Inno Setup's native file-and-shortcut cleanup and preserves per-user settings and logs so it cannot accidentally delete your local master-password verifier or connection preferences. To remove those files manually after uninstalling, close MySQL Editor and delete `%LOCALAPPDATA%\MySQL IDLE`. Uninstalling MySQL Editor never deletes MySQL databases.

## Run from source

The following commands are for PowerShell on Windows, from a clone of this repository:

```powershell
git clone https://github.com/ram1234598766-dotcom/MySQL-Editor.git
Set-Location MySQL-Editor

py -3.15 --version
py -3.15 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python mysql_idle.py
```

If PowerShell blocks virtual-environment activation, use the Python interpreter directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe mysql_idle.py
```

The main dependencies are:

- **PyMySQL** — connection to the MySQL/MariaDB server.
- **cryptography** — used by the desktop-hosted mobile companion for TLS certificate generation and related cryptographic functions.

Tkinter normally comes with the standard Windows Python installer. If your Python distribution was installed without Tkinter, install a distribution that includes it.

## First launch and master password

MySQL Editor opens the **Connect to MySQL** window first. The master-password controls are inside this same window, so there is no separate startup sign-in dialog.

- **First launch:** create a master password of at least 10 characters, then enter the same password again in the confirmation field directly below it.
- **Later launches:** the compact **Connect to MySQL** dialog is the only window shown at startup. Enter the saved master password; the main SQL workspace remains hidden until the database connection succeeds.
- **Connection failure:** the compact dialog returns with the connection fields prefilled so you can fix the host, account password, port, or optional TLS settings and retry.
- The master password is used to unlock MySQL Editor and to authenticate Android pairing. Only a salted PBKDF2-HMAC-SHA256 verifier is stored, not the password itself.
- The **MySQL account password** field is separate: it must contain the password configured for the MySQL/MariaDB user. The master password is not sent to MySQL as a database credential.

Keep both passwords safe. There is no plaintext master password to recover from the application's settings files.

## Connect to MySQL or MariaDB

1. Start MySQL Editor. The **Connect to MySQL** window opens automatically.
2. Enter the **MySQL Editor master password** at the top of that window. On first launch, create and confirm it there; on later launches, enter the existing master password.
3. Enter the MySQL server host, port (usually `3306`), username, the **MySQL account password**, and optional default database.
4. Select **Connect**. The app checks the master password locally, then uses the MySQL account credentials to connect to the database. No separate unlock window is shown.
5. To connect to a different database later, use **File → Connect** or press `Ctrl+N`.


### TLS options

The desktop Windows connection dialog defaults to **certificate-optional TLS** for compatibility with localhost and servers using self-signed certificates. With supported PyMySQL versions, the client attempts encrypted TLS when the server supports it, but this default does **not** verify the server certificate or identity. This is less resistant to man-in-the-middle attacks.

For managed servers and untrusted networks:

- Enable **Verify MySQL server certificate**.
- Provide the path to a trusted CA PEM file when required.
- Check that the server's certificate and hostname configuration are correct.

The CA file path is resolved on the computer running the desktop app. The Android companion uses verified MySQL TLS by default. This MySQL TLS setting is separate from the HTTPS connection between the phone and the Windows companion.

### Connection troubleshooting

- Check the host, port, username, database name and account grants.
- Make sure the database server accepts network connections from the Windows computer.
- Check server firewall rules and MySQL bind-address configuration.
- For a certificate-verification error, verify the CA, certificate hostname and device clock. For local/self-signed servers, understand the security trade-off before changing the verification setting.
- The app cannot grant database privileges the connected account does not have.

## Using the SQL editor

The SQL workspace starts with a safe `SELECT VERSION();` example. Replace it with your query or choose **Saved snippets**/**Query history** in the sidebar. The editor supports multiple statements, with or without a trailing semicolon. Press **Ctrl+Enter** to run the selected text, or the complete buffer when no text is selected. SQL is passed through Feature Governance before the background worker executes it.

| Key or command | Action |
| --- | --- |
| `Enter` | Run a complete statement |
| `Shift+Enter` | Insert a new line in a statement |
| `Up` / `Down` | Browse command history in the current session |
| `Alt+P` / `Alt+N` | Previous / next history entry |
| `Tab` | Autocomplete SQL keywords, databases, tables and columns |
| `Esc` | Clear the current input line |
| `Ctrl+N` | Open the connection dialog |
| `Ctrl+S` | Save the current SQL buffer as a `.sql` file |
| `F5` | Select and run a `.sql` script |
| `F6` | Open the last result in a grid |
| `Ctrl+L` | Clear the SQL editor and activity output |
| `Ctrl++` / `Ctrl+-` | Zoom the SQL editor text |
| `Ctrl+Break` | Request cancellation of the active MySQL query; server permissions apply |
| `help` | Show built-in help |
| Sidebar → Query history | Browse and insert a previous query |
| `exit` / `quit` | Close MySQL Editor |
| `\\c` | Cancel the statement currently being typed |

### Query results and export

- The workspace grid retains a preview of up to **1,000 rows** for a query result.
- The result grid loads up to **5,000 rows**.
- Full result sets are streamed in batches to a temporary CSV file; the preview limits do not mean only those rows were fetched.
- Temporary result data is stored locally during processing. The application attempts to remove temporary result files when sessions close or the application stops.
- Review the target database, active schema, and SQL before executing write or administrative statements.

### Scripts

Use **F5** to choose a `.sql` script. A script stops when a statement fails instead of continuing through the remaining statements. The MySQL `DELIMITER` client command is not supported, so scripts that depend on custom delimiters for stored procedures/triggers may need to be run using a database client that supports that command.

## Feature Governance

Open **Tools → Feature Governance** to set the current session's SQL policy and review recent policy decisions.

### Guarded mode

Guarded mode is the default. It can require explicit one-time approval before high-impact SQL runs, including destructive DDL, administrative/file-related operations, and `UPDATE` or `DELETE` statements without a top-level `WHERE` clause.

### Read-only mode

Read-only mode blocks statements classified by the policy engine as mutations or administrative operations. SQL is checked before it is queued and again at the execution boundary. The mobile service checks policy before executing SQL as well.

### Mobile step-up approval and audit events

High-impact mobile statements use a short-lived, random, single-use approval challenge bound to the exact SQL digest and paired session. A declined, expired, replayed or mismatched approval is rejected.

The in-memory audit log is bounded to 256 events. It records the time, decision, risk category, reason and a truncated SHA-256 statement fingerprint, not the full SQL text, literals, passwords or connection credentials.

### Enforce restrictions with environment variables

Set an environment variable before launching the desktop app:

- `MYSQLIDLE_READ_ONLY=1` — force read-only mode.
- `MYSQLIDLE_DISABLE_MOBILE=1` — disable the mobile companion.
- `MYSQLIDLE_SAVE_HISTORY=1` — explicitly opt in to persisting desktop SQL history.

Environment-enforced read-only and mobile-disable restrictions cannot be switched off in the UI. For example, to set read-only mode for a PowerShell session:

```powershell
$env:MYSQLIDLE_READ_ONLY = "1"
py mysql_idle.py
```

The policy engine uses conservative lexical SQL classification, not a complete MySQL parser. Treat it as defense in depth, not as a replacement for least-privilege database accounts, server permissions, backups, transactions, or careful review.

## Android companion setup

The Android app is a companion interface; **the MySQL connection is made by the Windows desktop service**. Keep the phone and desktop on the same trusted private network.

### On Windows

1. Launch and unlock MySQL Editor.
2. Open **Tools → Android / Mobile Companion**.
3. Explicitly start the companion service and select the appropriate private IPv4 network interface if prompted.
4. Copy the HTTPS address, temporary pairing code and complete SHA-256 certificate fingerprint shown by the desktop.
5. If Windows Firewall prompts you, allow the app on the appropriate **private** network only.

### On Android

1. Install the signed `MySQLEditor-Mobile-release.apk` from the [GitHub Releases page](https://github.com/ram1234598766-dotcom/MySQL-Editor/releases).
2. Open MySQL Editor Mobile.
3. Enter the HTTPS address shown on Windows (for example, `https://192.168.1.20:8765`).
4. Type the full SHA-256 certificate fingerprint shown on the desktop. Compare it carefully; do not accept a mismatch.
5. Tap **Verify and connect**.
6. On the pairing screen, enter the same MySQL Editor master password and the temporary code from the Windows desktop.
7. After pairing succeeds, enter the MySQL server host, port, username, and password. The host is resolved from the desktop computer's perspective; for a database running on that same PC, `localhost` may be appropriate.

### Mobile connection and session behavior

- HTTPS to the desktop is mandatory. The Android app pins the desktop certificate by its SHA-256 fingerprint and blocks unexpected certificate errors.
- The desktop's companion certificate and temporary pairing code are short-lived. The certificate fingerprint changes when the desktop companion restarts; compare and enter the new fingerprint before reconnecting.
- Pairing uses both the desktop master password and temporary code. The code has rate limits, and sessions expire after 30 minutes of inactivity.
- The app keeps the mobile query history in page memory (up to 50 entries) and clears it on disconnect or session expiry. It does not write this history to persistent browser storage.
- If the desktop companion is stopped, the phone cannot use it until you start it again.

### Mobile network safety

The companion binds to a selected private IPv4 interface, rejects wildcard/public binds, checks Host/Origin headers, limits concurrent handlers and request sizes, and aborts result exports larger than 512 MiB. These limits are not a reason to expose the service to the public internet.

Do **not** use router port forwarding or expose this service on public Wi-Fi. For remote access, use a trusted VPN or private tunnel, and keep the desktop protected. Stop the companion when it is not needed.

## Security and privacy

Read [SECURITY.md](SECURITY.md) before deploying the app in a sensitive environment.

### Credentials and history

- MySQL account passwords are not written to persistent connection preferences.
- The desktop master password is represented by a salted PBKDF2-HMAC-SHA256 verifier.
- Desktop SQL history is memory-only by default. Setting `MYSQLIDLE_SAVE_HISTORY=1` opts in to disk persistence.
- Mobile query history exists in page memory and is cleared on disconnect or session expiry.
- Connection preferences may contain non-secret information such as host, port, username, selected database, TLS preference and optional CA path.

### Network and database access

- Only start the mobile companion when you need it.
- Verify the full desktop certificate fingerprint over a trusted channel before pairing.
- Use trusted private networks and keep database server permissions minimal.
- Remember that a paired session can execute SQL under the permissions of the connected MySQL account. Pairing does not make a powerful database account less powerful.
- The desktop's certificate-optional TLS default does not authenticate the MySQL server. Use verified TLS with a trusted CA where server identity matters.
- The Android app does not embed your database password and does not run a database server.

### Android permission and installation status

The Android manifest requests `INTERNET`; cleartext HTTP is disabled. CI checks requested permissions and installs/launches an APK on an Android emulator. When all four Android signing secrets are configured and validated, CI builds a release-signed APK and verifies its signature. Without those secrets, CI builds a debug APK for CI testing and does not publish it as a public release. This workflow produces Android APK files only. The Python dependency and static-analysis security workflow runs separately.

Those checks are useful evidence about the package and source but **are not a guarantee of zero vulnerabilities or Google's Play Protect verdict**. Do not bypass a “harmful app” warning. Cancel installation and submit an appeal if you believe Google has misclassified the app; see [Google's official process](https://support.google.com/googleplay/android-developer/answer/2992033).

## Configuration and local files

On Windows, application data is stored under:

```text
%LOCALAPPDATA%\MySQL IDLE\
```

This directory contains app settings, the master-password verifier and diagnostic logs. The exact files present depend on what the application has created.

- `settings.json` — connection preferences and other local settings. The MySQL password is removed before settings are written.
- `master_password.json` — the master-password verifier, not the master password in plaintext.
- `sql_snippets.json` — only SQL statements you explicitly choose to save. Avoid storing sensitive literals in snippets; the file stays in this Windows user profile.
- `logs\` — diagnostic logs.
- Temporary query-result CSV files are stored for result processing and are normally cleaned up when the session/app closes.

Do not upload application logs or configuration files publicly without reviewing them first. The app is designed not to persist database passwords in these settings, but diagnostic files and hostnames can still reveal environment details.

## Build from source

### Build the Windows desktop app

On a Windows development machine, install Python 3.15 and make sure Tkinter is available. If you want the installer, install Inno Setup and make `ISCC.exe` accessible on `PATH`.

From the repository root in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows.ps1
```

The build script installs required Python packages, generates the branded assets, runs automated tests, and builds both desktop packaging styles.

Outputs:

- `dist\mysql_idle\mysql_idle.exe` — folder-based application (keep the entire folder).
- `dist\MySQLEditor_Portable.exe` — single-file portable build.
- `dist\installer\MySQLEditor-Setup.exe` — installer, if Inno Setup is available to the script.

### Build the Android debug app

Install JDK 17 and Android SDK Platform 36/build tools. The exact logo is already stored in the Android project; no image generator or store artwork is required.

```powershell
Set-Location android-app
gradle --no-daemon assembleDebug
```

Expected debug output:

- `app\build\outputs\apk\debug\app-debug.apk`

Debug packages are for development/testing and are not the signed public release artifacts. For a release build, configure the Android signing secrets in GitHub Actions and use the project workflow. Read [SIGNING.md](SIGNING.md) carefully before creating, replacing or migrating signing keys. Losing or rotating the signing identity can prevent installed users from updating in place.

### Android release signing

The workflow produces a release-signed APK only when the required signing secrets are configured and validated. Only the APK is produced; no additional Android package format is generated. Use the APK for direct installation/testing. Do not commit keystores, private keys, passwords, PFX files or other signing secrets to Git. See [SIGNING.md](SIGNING.md) for exact setup, recovery, signing continuity and Windows code-signing instructions.

## Tests and continuous integration

Run the Python unit and integration tests from the repository root:

```powershell
py -3.15 -m unittest -v `
  test_mysql_idle.py `
  test_mobile_companion.py `
  test_feature_governor.py `
  test_password_auth.py `
  test_packaging_branding.py
```

The GitHub Actions workflows run checks for the source and packaged application, including:

- Python dependency vulnerability auditing with `pip-audit`.
- Bandit static analysis for selected Python modules.
- SQL parsing, settings privacy, password authentication, and Feature Governance tests.
- Mobile HTTPS integration tests for pairing, TLS behavior, request validation and resource limits.
- Windows build and regression tests, including installer launch, desktop shortcut checks, and uninstall cleanup.
- Android permission auditing and emulator install/launch checks. APK signature verification and release-signed APK/AAB creation run when valid Android signing secrets are configured; without them, the debug package is CI-only.

See the [Build workflow](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/workflows/build-exe-apk.yml) and [Security workflow](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/workflows/security.yml) for current results.

## Troubleshooting

### Cannot connect to the database

- Verify the hostname and port from the Windows computer.
- Confirm the MySQL/MariaDB service is running and accepts TCP connections.
- Check network/firewall rules, the server bind address, username, default database and account grants.
- Try a known-good client to establish whether the issue is app-specific or server/network configuration.

### TLS or certificate error

- The desktop direct-connection default is certificate-optional TLS, but a server might still reject the connection or require particular TLS settings.
- If certificate verification is enabled, check the trusted CA PEM file, certificate validity, hostname, and device clock.
- Do not disable certificate checks merely to hide a warning on a network where server identity matters.
- For the Android-to-desktop connection, re-copy the HTTPS address and compare the complete SHA-256 fingerprint after restarting the companion.

### Android cannot reach the Windows companion

- Keep both devices on the same trusted private Wi-Fi/network.
- Enter the exact HTTPS URL displayed by the desktop; do not substitute the phone's `localhost`.
- Make sure the companion is still running and Windows Firewall permits private-network traffic.
- Enter the full current certificate fingerprint and temporary pairing code. A restart changes the certificate fingerprint.
- If the Android app blocks a certificate error, do not ignore it; check the URL, fingerprint and device clock.

### Android reports “This app is harmful”

Cancel installation and do not override the warning. The presence of a valid signature, passing build checks, or a new version cannot guarantee Google's classification. Confirm that the APK came from the official [MySQL-IDLE release page](https://github.com/ram1234598766-dotcom/MySQL-Editor/releases), retain the warning details, and request review using [Google's app-verification appeal process](https://support.google.com/googleplay/android-developer/answer/2992033). Do not disable Play Protect or use repackaging tricks to evade it.

### Script or query behavior is unexpected

- Review the SQL and target database carefully, especially destructive statements.
- Check whether Feature Governance is in guarded or read-only mode.
- Confirm that the database account has the necessary permissions.
- The client-side lexical policy is not a full SQL parser; the database server remains the authority for execution and permissions.
- Custom `DELIMITER` commands are unsupported.

### Need diagnostic information?

Use **Help → Check Environment** to inspect runtime and diagnostic paths. Review log/config contents for sensitive environment information before sharing them in an issue.

## Project structure

```text
MySQL-Editor/
├── mysql_idle.py                 # Desktop SQL workspace and GUI
├── mobile_companion.py           # HTTPS service hosted by the desktop
├── feature_governor.py           # SQL risk policy and audit events
├── password_auth.py              # Master-password verifier/authentication
├── requirements.txt              # Python runtime dependencies
├── assets/                       # Shared logo and generated Windows assets
├── android-app/                  # Native Android wrapper and mobile UI
├── tools/                        # Windows asset generation, exact logo sync, and build helpers
├── test_mysql_idle.py            # Desktop parsing, configuration and result tests
├── test_mobile_companion.py      # Mobile HTTPS integration tests
├── test_feature_governor.py      # Policy engine tests
├── test_password_auth.py         # Password authentication tests
├── test_packaging_branding.py    # Packaging/branding tests
├── build_windows.ps1             # Windows packaging script
├── mysql_idle.spec               # PyInstaller folder build
├── mysql_idle_portable.spec      # PyInstaller one-file build
├── MySQLIDLE.iss                 # Inno Setup installer definition
├── SECURITY.md                   # Security notes and disclosure guidance
├── SIGNING.md                    # Android and Windows signing instructions
└── .github/workflows/            # Build and security CI workflows
```

## Known limitations

- MySQL Editor is a SQL client, not a MySQL/MariaDB server or a database backup/restore system.
- SQL is executed using the connected database account's server-side privileges.
- The desktop TLS compatibility default does not verify server identity unless certificate verification is enabled.
- The Feature Governance classifier and SQL formatter are conservative lexical tools, not full MySQL SQL parsers; review formatted or safety-checked SQL before execution.
- The MySQL `DELIMITER` command is not supported for custom-delimiter scripts.
- The mobile companion should be used only on trusted private networks; it is not designed to be publicly exposed.
- Direct APK distribution may trigger Android/Google Play Protect warnings. Only Google can clear a Google-side classification.
- Windows SmartScreen reputation and code-signing status depend on the published binary and signing configuration.

## Contributing and security reports

Contributions are welcome through GitHub issues and pull requests:

1. Reproduce the issue on the current source or published build.
2. Describe the expected and actual behavior, operating system, relevant versions, and sanitized logs.
3. Run the relevant unit/integration tests before submitting a pull request.
4. Avoid posting passwords, keystores, tokens, private database details, or unsanitized logs.

For suspected vulnerabilities, follow [SECURITY.md](SECURITY.md) and contact the repository owner privately rather than publishing exploit details in a public issue.

## License

No explicit open-source license file is currently present in the repository. Unless a license is added, do not assume the project grants broad reuse, modification or redistribution rights.


## Editable UI concepts

The Windows and Android workspace concepts are maintained in [Figma](https://www.figma.com/design/EFFQpRTE8pKybt1lQR0eQH).
