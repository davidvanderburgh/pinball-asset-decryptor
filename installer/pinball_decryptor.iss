; Pinball Asset Decryptor — Inno Setup script.
; Compile with build.ps1 (recommended) or directly:
;   ISCC.exe /DAppVersion=0.1.0 /DPythonDir=build\python /DProjectDir=.. pinball_decryptor.iss

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

#ifndef ProjectDir
  #define ProjectDir ".."
#endif

#ifndef PythonDir
  #define PythonDir "build\python"
#endif

[Setup]
AppId={{B8E2D4F6-9A3C-5E7B-CAF1-4A6B8D2E0F3C}
AppName=Pinball Asset Decryptor
AppVersion={#AppVersion}
AppVerName=Pinball Asset Decryptor v{#AppVersion}
AppPublisher=David Vanderburgh
AppPublisherURL=https://github.com/davidvanderburgh/pinball-asset-decryptor
AppSupportURL=https://github.com/davidvanderburgh/pinball-asset-decryptor/issues
DefaultDirName={autopf}\Pinball Asset Decryptor
DefaultGroupName=Pinball Asset Decryptor
OutputBaseFilename=Pinball_Asset_Decryptor_v{#AppVersion}_Windows
SetupIconFile={#ProjectDir}\pinball_decryptor\icon.ico
UninstallDisplayIcon={app}\pinball_decryptor\icon.ico
LicenseFile={#ProjectDir}\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
WizardSizePercent=110
DisableProgramGroupPage=auto
VersionInfoVersion={#AppVersion}.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "runprereqs"; Description: "Install prerequisites after setup (WSL2, partclone, debugfs, gpg)"; GroupDescription: "Prerequisites:"; Flags: unchecked

[Files]
; --- Bundled Python with tkinter and pip dependencies ---------------------
Source: "{#PythonDir}\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion

; --- Application package (recursive — picks up core/, gui/, all plugins/) -
; Excludes __pycache__ and the bundled plugin Dockerfiles only at the
; top of pinball_decryptor/ — the plugin Dockerfiles live next to their
; clonezilla helpers and ARE included via recursesubdirs.
Source: "{#ProjectDir}\pinball_decryptor\*"; DestDir: "{app}\pinball_decryptor"; \
    Flags: recursesubdirs ignoreversion; \
    Excludes: "__pycache__\*,*.pyc,*.pyo"

; --- Entry point + bundled launcher --------------------------------------
Source: "{#ProjectDir}\Pinball Asset Decryptor.pyw"; DestDir: "{app}"; Flags: ignoreversion
Source: "launcher.vbs"; DestDir: "{app}"; Flags: ignoreversion

; --- Prerequisites helper (re-runnable from Start Menu) ------------------
Source: "install_prerequisites.ps1"; DestDir: "{app}"; Flags: ignoreversion
; install_gdre.sh ships beside it — install_prerequisites.ps1 hands this
; file to WSL to install GDRE Tools (shared with the Linux installer).
Source: "install_gdre.sh"; DestDir: "{app}"; Flags: ignoreversion

; --- Documentation -------------------------------------------------------
Source: "{#ProjectDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Pinball Asset Decryptor"; Filename: "wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\pinball_decryptor\icon.ico"; Comment: "Decrypt and modify pinball machine assets across multiple manufacturers"
Name: "{group}\Install Prerequisites"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_prerequisites.ps1"""; WorkingDir: "{app}"; Comment: "Install WSL2, partclone, debugfs, gpg"
Name: "{group}\{cm:UninstallProgram,Pinball Asset Decryptor}"; Filename: "{uninstallexe}"

Name: "{autodesktop}\Pinball Asset Decryptor"; Filename: "wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\pinball_decryptor\icon.ico"; Tasks: desktopicon; Comment: "Decrypt and modify pinball machine assets"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_prerequisites.ps1"""; WorkingDir: "{app}"; StatusMsg: "Installing prerequisites..."; Flags: runascurrentuser shellexec waituntilterminated; Tasks: runprereqs

; --- Repair bundled-Python file permissions ------------------------------
; install_prerequisites.ps1 pip-installs faster-whisper (and its
; dependencies) into {app}\python\Lib\site-packages while running
; elevated.  Files written by an elevated process can carry ACLs the
; normal-user app process cannot read, so "import faster_whisper" — or a
; dependency such as typing_extensions — fails at runtime with
; "[Errno 13] Permission denied".
;
; Repair the whole bundled-Python tree here, on EVERY (re)install, so a
; plain install-over-the-top fixes an already-broken machine without the
; user having to re-run the prerequisites installer.  /reset strips
; broken or explicit ACEs so each file re-inherits Program Files' default
; Users read+execute; the explicit /grant of the Users group (well-known
; SID S-1-5-32-545) is a belt-and-suspenders guard — an explicit allow
; ACE also out-ranks any inherited deny on a hardened machine.  Not gated
; behind the runprereqs Task: it must run unconditionally.
Filename: "{sys}\icacls.exe"; Parameters: """{app}\python"" /reset /T /C /Q"; StatusMsg: "Repairing Python file permissions..."; Flags: runhidden waituntilterminated
Filename: "{sys}\icacls.exe"; Parameters: """{app}\python"" /grant *S-1-5-32-545:(OI)(CI)RX /T /C /Q"; StatusMsg: "Repairing Python file permissions..."; Flags: runhidden waituntilterminated

Filename: "wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; Description: "Launch Pinball Asset Decryptor"; Flags: nowait postinstall skipifsilent

; --- In-app update relaunch ----------------------------------------------
; The app's "Install update" flow runs this installer silently
; (/SILENT /RELAUNCH=1) and exits; the postinstall entry above is
; skipifsilent, so without this the silent upgrade would end with
; nothing on screen.  Routed through launcher.vbs like every other
; entry point (self-elevation), and gated on the /RELAUNCH=1 flag so a
; plain silent install (e.g. mass deployment) stays hands-off.
Filename: "wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; Flags: nowait; Check: RelaunchRequested

[UninstallDelete]
; Wipe Python bytecode caches so the install dir is clean before removal.
Type: filesandordirs; Name: "{app}\pinball_decryptor\__pycache__"
Type: filesandordirs; Name: "{app}\pinball_decryptor\core\__pycache__"
Type: filesandordirs; Name: "{app}\pinball_decryptor\gui\__pycache__"
Type: filesandordirs; Name: "{app}\pinball_decryptor\plugins\__pycache__"
Type: filesandordirs; Name: "{app}\pinball_decryptor\plugins\pb\__pycache__"
Type: filesandordirs; Name: "{app}\pinball_decryptor\plugins\spooky\__pycache__"
Type: filesandordirs; Name: "{app}\pinball_decryptor\plugins\bof\__pycache__"
Type: filesandordirs; Name: "{app}\pinball_decryptor\plugins\jjp\__pycache__"
Type: filesandordirs; Name: "{app}\pinball_decryptor\plugins\dp\__pycache__"

[Code]
{ True when the app's in-app updater launched this install
  (/RELAUNCH=1 on the command line) — see the [Run] relaunch entry. }
function RelaunchRequested(): Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  if Version.Major < 10 then
  begin
    MsgBox('Pinball Asset Decryptor requires Windows 10 or later.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  Result := True;
end;
