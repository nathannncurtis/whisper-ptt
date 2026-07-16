; Inno Setup script for WhisperPTT. Built by CI (see .github/workflows/release.yml):
;   iscc /DMyAppVersion=x.y.z installer\whisper-ptt.iss
; Expects:
;   dist\WhisperPTT.exe                 compiled AHK front-end
;   dist\whisper-ptt-backend\           PyInstaller onedir backend
;   dist\companion\                     self-contained WPF companion

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "WhisperPTT"
#define MyAppPublisher "Nathan Curtis"
#define MyAppURL "https://github.com/nathannncurtis/whisper-ptt"
#define MyAppExeName "WhisperPTT.exe"
#define MyCompanionExeName "WhisperPTT.Companion.exe"

[Setup]
AppId={{7F7C3C7E-2C1A-4B77-9A64-3D8A51C0B6E2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
UsePreviousAppDir=no
DisableDirPage=yes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
Compression=lzma
SolidCompression=yes
OutputDir=Output
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
WizardStyle=dynamic
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Start {#MyAppName} when I sign in"

[UninstallDelete]
; Models (~150 MB+) and logs are created at runtime under {app}; clean them up
; on uninstall. config.ini is deliberately left behind (see [Files]).
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\logs"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\whisper-ptt-backend\*"; DestDir: "{app}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\companion\*"; DestDir: "{app}\companion"; Flags: ignoreversion recursesubdirs createallsubdirs
; Never overwrite the user's edited config on upgrade; never uninstall it either.
Source: "..\config.ini"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{#MyAppName} Settings"; Filename: "{app}\companion\{#MyCompanionExeName}"; WorkingDir: "{app}"
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startup

[Run]
; First-run experience: the setup wizard picks a language, scans the NPU,
; recommends and downloads the right model, and writes config.ini.
Filename: "{app}\companion\{#MyCompanionExeName}"; Parameters: "--setup"; Description: "Run first-time setup (pick language && model)"; Flags: postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: postinstall nowait skipifsilent
