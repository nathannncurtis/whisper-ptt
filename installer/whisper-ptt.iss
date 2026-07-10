; Per-user installer for WhisperPTT. Built by CI (see .github/workflows/release.yml):
;   iscc /DAppVersion=x.y.z installer\whisper-ptt.iss
; Expects:
;   dist\WhisperPTT.exe                 compiled AHK front-end
;   dist\whisper-ptt-backend\           PyInstaller onedir backend

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7F7C3C7E-2C1A-4B77-9A64-3D8A51C0B6E2}
AppName=WhisperPTT
AppVersion={#AppVersion}
AppPublisher=Nathan Curtis
DefaultDirName={localappdata}\Programs\WhisperPTT
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=Output
OutputBaseFilename=WhisperPTT-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
UninstallDisplayName=WhisperPTT

[Tasks]
Name: "startup"; Description: "Start WhisperPTT when I sign in"

[Files]
Source: "..\dist\WhisperPTT.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\whisper-ptt-backend\*"; DestDir: "{app}\backend"; Flags: recursesubdirs ignoreversion
Source: "..\dist\companion\*"; DestDir: "{app}\companion"; Flags: recursesubdirs ignoreversion
; Never overwrite the user's edited config on upgrade; never uninstall it either.
Source: "..\config.ini"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{userprograms}\WhisperPTT"; Filename: "{app}\WhisperPTT.exe"; WorkingDir: "{app}"
Name: "{userprograms}\WhisperPTT Settings"; Filename: "{app}\companion\WhisperPTT.Companion.exe"; WorkingDir: "{app}"
Name: "{userstartup}\WhisperPTT"; Filename: "{app}\WhisperPTT.exe"; WorkingDir: "{app}"; Tasks: startup

[Run]
; First-run experience: the setup wizard picks a language, scans the NPU,
; recommends and downloads the right model, and writes config.ini.
Filename: "{app}\companion\WhisperPTT.Companion.exe"; Parameters: "--setup"; Description: "Run first-time setup (pick language && model)"; Flags: postinstall skipifsilent
Filename: "{app}\WhisperPTT.exe"; Description: "Launch WhisperPTT now"; Flags: postinstall nowait skipifsilent

; Models (~150 MB+) and logs are downloaded/created at runtime under {app}\models
; and {app}\logs; the uninstaller leaves them (harmless, and re-download is slow).
