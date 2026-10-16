#define MyAppName "MySQL IDLE"
#define MyAppVersion "3.0.0"
#define MyAppPublisher "MySQL IDLE"
#define MyAppExeName "mysql_idle.exe"
#define MyDistDir "dist\mysql_idle"

[Setup]
AppId={{8E9A39E8-9F59-4FA3-AD4E-7B0A54A93F11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/ram1234598766-dotcom/MySQL-Editor
AppSupportURL=https://github.com/ram1234598766-dotcom/MySQL-Editor/issues
AppUpdatesURL=https://github.com/ram1234598766-dotcom/MySQL-Editor/releases
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=MySQL IDLE SQL Workspace
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\MySQL IDLE
DefaultGroupName=MySQL IDLE
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename=MySQLIDLE-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern dynamic includetitlebar
SetupIconFile=assets\mysqlidle.ico
WizardImageFile=assets\wizard-image.bmp
WizardSmallImageFile=assets\wizard-small.bmp
WizardImageFileDynamicDark=assets\wizard-image.bmp
WizardSmallImageFileDynamicDark=assets\wizard-small.bmp
UninstallDisplayIcon={app}\_internal\assets\mysqlidle.ico
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; The desktop shortcut is always created so the installed app is easy to find.

[Files]
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MySQL IDLE"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\assets\mysqlidle.ico"; IconIndex: 0
Name: "{autodesktop}\MySQL IDLE"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\assets\mysqlidle.ico"; IconIndex: 0

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch MySQL IDLE"; Flags: nowait postinstall skipifsilent
