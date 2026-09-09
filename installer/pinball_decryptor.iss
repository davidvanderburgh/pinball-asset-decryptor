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

; --- Spike 2 emulator rig ------------------------------------------------
; The Emulate tab runs the machine's own game binary under qemu-user inside
; WSL, and this is that rig.  It was deliberately NOT shipped for a while, on
; the grounds that it needs WSL, a C toolchain and a card image before it does
; anything - but the result was an Emulate tab that could never work for anyone
; who installed the app rather than cloning it, telling them only that the rig
; "was not found".  3.3 MB of scripts is a poor reason to make a whole feature
; unreachable, so it ships.
;
; NOTHING HERE IS WRITTEN TO AT RUN TIME, which is what makes {app} a safe home
; for it: build.sh copies the C sources to ~/emusrc inside WSL and compiles
; there (drvfs is too slow to compile on), rootfs.sh refuses to build into a
; /mnt path at all, and the derived per-title tables live under the rootfs.
; Program Files being read-only for the user therefore costs nothing.
Source: "{#ProjectDir}\tools\spike2_emu\*"; DestDir: "{app}\tools\spike2_emu"; \
    Flags: recursesubdirs ignoreversion; \
    Excludes: "__pycache__\*,*.pyc,*.pyo,games\*,shots\*,*.log,*.dis,*.png,*.raw"
; The Spike 1 rig (tools/spike1_emu) drives the Emulate tab for the DMD era.
; Just sources — the patched qemu and the extracted game are built/cached under
; the user's WSL home at run time (see tools/spike1_emu/start.sh), never here.
Source: "{#ProjectDir}\tools\spike1_emu\*"; DestDir: "{app}\tools\spike1_emu"; \
    Flags: recursesubdirs ignoreversion; \
    Excludes: "__pycache__\*,*.pyc,*.pyo,*.log,*.png,*.raw,*.cap,*.bin,rootfs\*,game\*"

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

{ ---------------------------------------------------------------- uninstall

  WHAT THIS APP LEAVES OUTSIDE ITS OWN FOLDER, and why uninstalling has to
  ask about it.

  Since the app started bringing its own Linux there are three things under
  %LOCALAPPDATA% that Inno knows nothing about, and together they are the
  largest thing on the disk by far:

    * PAD-Runtime, a registered WSL distro (~1 GB unpacked).  Removing the
      folder is NOT enough and is actively wrong - WSL keeps its own registry
      entry, and a distro whose disk vanished underneath it is a broken entry
      the user then has to unregister by hand.  So it is unregistered through
      wsl.exe, which is the only thing that removes both halves.
    * pad-data.vhdx, the rigs' work disk - extracted games, cached cards,
      save states.  Measured in gigabytes, and it is the user's own work.
    * the payload cache: the runtime image and emulator binaries as
      downloaded, kept so a repair needs no second download.

  ASKED, NOT ASSUMED, and asked as two separate questions, because they are
  two different kinds of thing.  The runtime and the cache are ours and can
  be rebuilt by pressing one button in a reinstalled app; the work disk is
  the user's and cannot.  Defaulting either to "yes" would make an uninstall
  a data loss, and defaulting both to "no" would leave gigabytes behind on a
  machine whose owner thinks the app is gone.  So: one question each, and the
  work disk's question says what is on it.

  Silent uninstalls remove nothing extra.  A script that cannot answer a
  question must not have data deleted on its behalf.

  AND THIS RUNS ELEVATED (PrivilegesRequired=admin), so the localappdata
  constant below is the ELEVATING account's - note that a brace pair cannot
  be written inside a Pascal comment here, because the first closing brace
  ENDS the comment and everything after it is parsed as code, which is how
  this block first failed to compile - while the app itself ran unelevated as
  its owner.  On
  the ordinary machine those are one account and UAC only raised it.  Where
  they are not - a standard user who typed an administrator's password - the
  paths below simply do not exist, both questions are skipped, and nothing is
  removed.  That is the right way round: a wrong guess here costs disk space,
  and the other wrong guess would cost somebody's extracted games. }

procedure RemoveTheRuntimeDistro;
var
  ResultCode: Integer;
begin
  { Hidden: this is the only thing on screen at this point and a console
    flashing past says nothing a user could act on.  A failure leaves the
    distro registered, which the app's own Fix setup can still remove. }
  Exec(ExpandConstant('{sys}\wsl.exe'), '--unregister PAD-Runtime',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  DelTree(ExpandConstant('{localappdata}\pinball_decryptor\runtime'),
          True, True, True);
  DelTree(ExpandConstant('{localappdata}\pinball_decryptor\payloads'),
          True, True, True);
end;

procedure RemoveTheWorkDisk;
var
  ResultCode: Integer;
  Disk: String;
begin
  Disk := ExpandConstant('{localappdata}\pinball_decryptor\data\pad-data.vhdx');
  { Detached first: the file is held open while the WSL VM has it attached,
    and a delete would simply fail. }
  Exec(ExpandConstant('{sys}\wsl.exe'), '--unmount "' + Disk + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  DelTree(ExpandConstant('{localappdata}\pinball_decryptor\data'),
          True, True, True);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  HasRuntime, HasDisk: Boolean;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if UninstallSilent() then
    Exit;

  HasRuntime := DirExists(ExpandConstant('{localappdata}\pinball_decryptor\runtime'))
             or DirExists(ExpandConstant('{localappdata}\pinball_decryptor\payloads'));
  HasDisk := FileExists(ExpandConstant(
               '{localappdata}\pinball_decryptor\data\pad-data.vhdx'));

  if HasRuntime then
    if MsgBox('Also remove the Linux this app installed (PAD-Runtime) and the '
              'files it downloaded?' + #13#10 + #13#10 +
              'This is about a gigabyte. It is not your data, and a '
              'reinstalled app can fetch it again.',
              mbConfirmation, MB_YESNO) = IDYES then
      RemoveTheRuntimeDistro();

  if HasDisk then
    if MsgBox('Also delete the emulator''s work disk?' + #13#10 + #13#10 +
              'This holds extracted games, cached cards and save states, and '
              'it can be many gigabytes. It is YOUR work, and deleting it '
              'cannot be undone.' + #13#10 + #13#10 +
              'Choose No to keep it for a future install.',
              mbConfirmation, MB_YESNO) = IDYES then
      RemoveTheWorkDisk();
end;
