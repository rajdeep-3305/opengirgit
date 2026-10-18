; Inno Setup script: per-user Windows installer for the PyInstaller bundle.
;
; Build (from the repository root, after PyInstaller produced dist\OpenGirGit):
;
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\install-windows.iss
;
; Result: dist\OpenGirGit-windows-x64-setup.exe — installs to
; %LOCALAPPDATA%\Programs\OpenGirGit without an admin prompt (PrivilegesRequired
; = lowest), so no UAC dialog and no machine-wide leftovers. The GitHub release
; workflow compiles this script on every v* tag; see packaging/README.md.

#define AppName "OpenGirGit"
; Keep in sync with client/opengirgit/version.py and server/app/config.py.
#define AppVersion "0.2.0"
#define AppPublisher "OpenGirGit contributors"
#define AppURL "https://github.com/rajdeep-3305/opengirgit"

[Setup]
AppId={{2C7B4F6E-9D31-4A8C-8E4B-6F0A5D9C3E72}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename={#AppName}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; OpenGirGit supports Windows 11 only: build 22000 is the first Windows 11 release.
MinVersion=10.0.22000
UninstallDisplayIcon={app}\{#AppName}.exe
LicenseFile=..\LICENSE
SetupIconFile=OpenGirGit.ico
; No auto-update on purpose: updating means running a newer installer.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\OpenGirGit\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
