#define MyAppName "MySQL Editor"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "MySQL Editor"
#define MyAppExeName "MySQLEditor.exe"

[Setup]
AppId={{3B2ED2E8-0B92-4E94-A2A2-9D217E4336D1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/ram1234598766-dotcom/MySQL-Editor
AppSupportURL=https://github.com/ram1234598766-dotcom/MySQL-Editor/issues
AppUpdatesURL=https://github.com/ram1234598766-dotcom/MySQL-Editor/releases
DefaultDirName={localappdata}\Programs\MySQL Editor
DefaultGroupName=MySQL Editor
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=MySQLEditor-Setup
SetupIconFile=..\assets\mysql-editor.ico
UninstallDisplayIcon={app}\MySQLEditor.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageFile=..\assets\wizard-image.bmp
WizardSmallImageFile=..\assets\wizard-small.bmp
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no
Uninstallable=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\MySQLEditor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MySQL Editor"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\MySQL Editor"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch MySQL Editor"; Flags: nowait postinstall skipifsilent
