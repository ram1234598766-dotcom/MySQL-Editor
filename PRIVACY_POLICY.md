# Privacy Policy — MySQL IDLE Mobile

**Effective date:** October 15, 2026

> **Release checklist:** Before submitting to Google Play, replace the support-contact placeholder below with a real, monitored email address or privacy-request form. Keep the Play Console contact and this policy current.

**App:** MySQL IDLE Mobile  
**Android package:** `com.mysqlidle.mobile`  
**Developer/support contact:** `[REPLACE WITH A MONITORED SUPPORT EMAIL OR PRIVACY CONTACT URL]`

## Overview

MySQL IDLE Mobile is a companion interface for MySQL IDLE on Windows. It is designed to connect to a Windows desktop companion chosen by the user over a trusted private network. It does not include a MySQL server or a MySQL IDLE cloud account service.

The Android app does not contain advertising or analytics SDKs in the current release. The developer does not operate a backend service that receives the app's SQL statements, query results, MySQL credentials, master password, or pairing code.

## Information used by the app

To provide the feature the user requests, the app can handle the following information:

- **Desktop connection details:** The HTTPS address of the Windows companion is saved in Android app preferences so the user does not need to re-enter it each time. The certificate fingerprint is entered for the active connection and held in memory for verification.
- **Pairing and authentication:** The user enters the Windows MySQL IDLE master password and a temporary pairing code. The values are sent to the user-configured Windows companion over HTTPS to verify and establish a session. The app does not intentionally save the master password or pairing code in persistent Android preferences.
- **Database connection information:** After pairing, the user can enter a MySQL host, port, username, password, database name and optional TLS/CA settings. These details are sent over the encrypted connection to the user's Windows companion, which makes the MySQL/MariaDB connection. The Android app does not intentionally store the MySQL password in persistent app preferences.
- **SQL and query results:** SQL statements, query metadata and result data are sent to or received from the user's Windows companion to run the functions the user requests. Query history is kept in page memory for the active session and cleared on disconnect or session expiry. If the user exports query results, the resulting file may be saved to a location the user chooses.
- **Technical/network data:** The app necessarily uses the user-supplied private-network endpoint and network connection status to communicate with the Windows companion.

A SQL statement or query result can itself contain personal, confidential or other sensitive information from the database chosen by the user. Users should apply the same care to SQL and results as to the underlying database.

## How information is used and where it goes

The information above is used to verify the selected desktop, pair the app with that desktop, connect to the database through the desktop, run SQL requested by the user, display results, and support optional result export.

The expected data path is:

1. The Android app connects to the Windows companion at the HTTPS address chosen by the user.
2. The app checks the desktop certificate against the SHA-256 fingerprint that the user has compared with the value shown on Windows.
3. The user provides the master password and temporary pairing code to the Windows companion over that HTTPS connection.
4. Once paired, the Windows companion receives database connection details and SQL requests, connects to the database server, and returns the results to the app.

The app is designed for a trusted private LAN. The developer does not receive these values through an app-operated cloud service. Information is sent to the Windows computer and database endpoint chosen by the user, which may be operated by the user or their organization.

## Sharing

The current Android app does not include advertising networks or analytics SDKs that receive data from the app. The app shares information with the Windows companion and the MySQL/MariaDB server the user configures as necessary for the app's core functionality. Those systems may process or retain information under their own configuration and policies.

If a user configures a desktop or database endpoint operated by another person or organization, that operator may be able to access the information handled by that endpoint. Users should only connect to a desktop certificate they have independently verified and a database they are authorized to use.

## Security

- The Android app requires HTTPS for the desktop companion and validates a user-provided SHA-256 certificate fingerprint.
- The app rejects endpoints outside supported private/local IPv4 ranges.
- Cleartext HTTP traffic is disabled in the Android manifest.
- The app requests the Android `INTERNET` permission for network connectivity.
- The master password, temporary pairing code and MySQL password are not intended to be saved in persistent Android app preferences.

No software or network protocol can guarantee perfect security. Use trusted devices and networks, verify the desktop certificate fingerprint, use least-privilege database accounts, and do not expose the Windows companion to the public internet.

## Retention and deletion

MySQL IDLE Mobile does not operate a central developer database for the information described here. The HTTPS desktop address is retained locally in Android app preferences until the user changes it or clears the app's data/uninstalls the app. Pairing credentials and database passwords are not intended to be persisted by the Android app. Mobile query history and session state are kept in page/session memory and cleared on disconnect or session expiry.

The Windows desktop and MySQL/MariaDB server have separate local settings, logs, database records and file behavior. Their administrators control those records and should review the desktop app's documentation and server policies for retention and deletion. Exported CSV files are under the user's control and should be deleted by the user when no longer required.

To request privacy information about the Android app, contact the support contact stated at the top of this policy. Do not send passwords, pairing codes, database credentials or query results in a support request.

## Children's privacy

MySQL IDLE Mobile is a technical database client, not designed specifically for children. The app does not knowingly collect children's information through a developer-operated online service. If you believe a child has sent personal information to the developer through a support channel, use the contact above to request review or deletion.

## Changes to this policy

This policy may be updated when the app's functionality or data handling changes. The current version will be published at the policy URL linked from the app and its Google Play listing. Material changes will be reflected in the effective date above.

## Contact

**Before publishing, replace the placeholder support contact at the top of this policy with a real, monitored contact.** The developer named in the Google Play listing should be identifiable in this policy.
