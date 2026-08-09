@echo off
setlocal enabledelayedexpansion
REM ===========================================================================
REM  savetest.cmd - start an emulator session that CAN be save-stated.
REM
REM  Double-click it, or make a desktop shortcut to it.  It is the hand-launch
REM  that the app's Start Emulator button does NOT do: a save state is a criu
REM  checkpoint, criu cannot checkpoint a chroot'd process, so the guest has to
REM  boot in the pivot_root shape (PAD_PIVOT=1) and as root.  watch.sh drops
REM  every helper back to the desktop user, so the window, the sound and the
REM  playfield are exactly as usual.
REM
REM  WHY THIS IS A SCRIPT AND NOT A BUTTON: the app shipped that launch once,
REM  in a release nobody approved, and it was reverted (v0.120.1).  This keeps
REM  the testing path entirely out of the app until the feature is finished and
REM  the release is yours to call.
REM
REM    savetest.cmd                    - the card the app last used
REM    savetest.cmd D:\some\card.raw   - a specific card
REM    savetest.cmd D:\card.raw 30     - ...with a 30 minute backstop
REM                                      (default 120, 0 = no cap)
REM
REM  Once the playfield window is up: Save state / Load state, bottom left.
REM ===========================================================================

set "CARD=%~1"
set "MINS=%~2"
if "%MINS%"=="" set "MINS=120"

REM ---- the card: the argument, else whatever the app last ran ---------------
if "%CARD%"=="" (
    for /f "usebackq delims=" %%C in (`powershell -NoProfile -Command ^
        "try{(Get-Content \"$env:APPDATA\pinball_decryptor\settings.json\" -Raw | ConvertFrom-Json).emulate_card}catch{''}"`) do set "CARD=%%C"
)
if "%CARD%"=="" (
    echo.
    echo   No card image given, and the app has not recorded one yet.
    echo   Pass one:   savetest.cmd "D:\path\to\card.raw"
    echo.
    pause
    exit /b 1
)
if not exist "%CARD%" (
    echo.
    echo   That card image does not exist:
    echo     %CARD%
    echo.
    pause
    exit /b 1
)

REM ---- the desktop user's home, asked of WSL ITSELF -------------------------
REM  NO $ ANYWHERE ON THESE LINES, deliberately: wsl.exe re-parses its argument
REM  line, so a $HOME or a $(...) would arrive empty (the trap the JJP executor
REM  is still carrying scars from).  whoami + getent carry no $ at all, and
REM  field 6 of the passwd line is the home directory.
for /f "usebackq delims=" %%U in (`wsl.exe -e whoami`) do set "WUSER=%%U"
if "%WUSER%"=="" (
    echo   WSL did not answer. Is it installed and running?
    pause
    exit /b 1
)
for /f "usebackq tokens=6 delims=:" %%H in (`wsl.exe -e getent passwd %WUSER%`) do set "WHOME=%%H"

REM ---- paths as WSL spells them --------------------------------------------
for /f "usebackq delims=" %%P in (`wsl.exe -e wslpath -u "%CARD%"`) do set "CARDW=%%P"
REM  wslpath drops the trailing slash, so every use below adds its own "/".
for /f "usebackq delims=" %%R in (`wsl.exe -e wslpath -u "%~dp0"`) do set "RIGW=%%R"

echo.
echo   Starting a SAVE-STATE session (this is not the app's Start Emulator).
echo     card   : %CARD%
echo     user   : %WUSER%  (home %WHOME%)
echo     cap    : %MINS% min
echo.
echo   The game window takes about 15 seconds. When the virtual playfield
echo   opens, use Save state / Load state at the bottom left.
echo   Close the game window (or press Ctrl-C here) to stop everything.
echo.

REM  ONE bash -c STRING, NOT a quoted path followed by an argument.  wsl.exe
REM  re-splits its argument line, and `bash "<path>" 20` arrived at bash as the
REM  single filename "<path> 20" ("No such file or directory", with the minutes
REM  glued onto the script name).  Inside bash -c the single quotes are bash's
REM  own, so a path with spaces survives - and there is still no $ anywhere for
REM  the re-parse to eat.
wsl.exe -u root -e bash -c "env HOME='%WHOME%' PAD_PIVOT=1 PAD_CARD='%CARDW%' bash '%RIGW%/watch.sh' %MINS%"

echo.
echo   Session ended. Checking nothing was left running...
wsl.exe -e bash "%RIGW%/alive.sh"
echo.
pause
