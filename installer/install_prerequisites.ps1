<#
.SYNOPSIS
    Per-manufacturer prerequisite installer for Pinball Asset Decryptor.

.DESCRIPTION
    Each manufacturer plugin needs a different set of host- or WSL-side
    tools.  Pick the manufacturers you actually plan to use; this script
    installs only the union of tools those plugins need.

    Tool layout:
      - WSL-side  (apt inside Ubuntu): partclone, debugfs, gpg-in-WSL,
        xorriso, pigz, zstd, ffmpeg-in-WSL, etc.
      - Host-side (winget on Windows): GnuPG (gpg.exe), ffmpeg
        (Spooky uses these directly; BOF and JJP use WSL versions
        through the executor).

    Safe to re-run: anything already present is skipped.

.NOTES
    Must run as Administrator (WSL install + admin-scope winget).
#>

# --- Console encoding ----------------------------------------------------
# winget emits its progress bars as UTF-8 box characters (U+2588, U+2592).
# PowerShell 5.1 defaults to OEM/Windows-1252 for [Console]::OutputEncoding,
# which renders those characters as mojibake (the "ΓûêΓûê" garbage).
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

# wsl.exe defaults to UTF-16LE output, which when captured by PowerShell
# turns "Ubuntu" into "U\0b\0u\0n\0t\0u\0" and breaks every -match check.
# WSL_UTF8=1 makes wsl.exe emit UTF-8 instead.  We also defensively strip
# nulls below in Get-WslDistros for older wsl.exe builds that ignore the
# env var.
$env:WSL_UTF8 = "1"

# --- Require admin -------------------------------------------------------
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "This script must be run as Administrator." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

$ErrorActionPreference = "Continue"
$needsReboot = $false
$results = @()


# --- Refresh-PATH helper -------------------------------------------------
# winget edits the persistent Machine/User PATH but the current process
# keeps its inherited copy.  Without this the post-install probe always
# fails ("[SKIP] (verify in new shell)") even when the install succeeded.
function Update-SessionPath {
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath    = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = ($machinePath, $userPath | Where-Object { $_ }) -join ";"
}

# --- WSL "do we have an apt-based distro?" helper -----------------------
# Capability-based detection: instead of parsing 'wsl --list' (whose
# UTF-16LE output is fragile in PowerShell 5.1) and matching a distro
# name (whose exact spelling varies — Ubuntu, Ubuntu-22.04, Debian...),
# we directly test the ONE thing every WSL package install needs:
# the ability to run 'apt-get' as root inside the default distro.
function Test-WslHasApt {
    if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) {
        return $false
    }
    try {
        & wsl -u root -- bash -c "command -v apt-get >/dev/null 2>&1" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Write-Step($msg)  { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-OK($n)        { Write-Host "  [OK] $n"        -ForegroundColor Green;  $script:results += [PSCustomObject]@{Name=$n;Status="OK"} }
function Write-Installed($n) { Write-Host "  [INSTALLED] $n" -ForegroundColor Green;  $script:results += [PSCustomObject]@{Name=$n;Status="Installed"} }
function Write-FAIL($n)      { Write-Host "  [MISSING] $n"   -ForegroundColor Red;    $script:results += [PSCustomObject]@{Name=$n;Status="Missing"} }
function Write-SKIP($n)      { Write-Host "  [SKIP] $n"      -ForegroundColor Yellow; $script:results += [PSCustomObject]@{Name=$n;Status="Skipped"} }

# =========================================================================
# Per-manufacturer prerequisite manifest
# =========================================================================
# Each entry maps a manufacturer to the WSL-side and host-side packages it
# needs.  WSL packages are installed via apt inside Ubuntu.  Host packages
# are installed via winget.
#
# Tool labels include the *reason* so the user understands what they get.

$ManufacturerPrereqs = [ordered]@{
    "Pinball Brothers" = @{
        Description  = "ABBA, Alien, Queen, Predator (.upd files + Clonezilla ISOs)"
        WslPackages  = @(
            @{ probe="debugfs"; pkg="e2fsprogs"; label="e2fsprogs/debugfs"; reason="Clonezilla .iso extraction (Alien / Queen)" }
        )
        HostPackages = @()
    }

    "Spooky Pinball" = @{
        Description  = "Beetlejuice, Evil Dead, R&M, Halloween, Looney Tunes + many more"
        WslPackages  = @(
            @{ probe="partclone.ext4";   pkg="partclone";              label="partclone";          reason="Clonezilla restore image extraction" }
            @{ probe="debugfs";          pkg="e2fsprogs";              label="e2fsprogs/debugfs";  reason="ext4 filesystem extraction" }
            @{ probe="zstd";             pkg="zstd python3-zstandard"; label="zstd + python3-zstandard"; reason="zstd-compressed Clonezilla images (Beetlejuice, Looney Tunes)" }
        )
        HostPackages = @(
            @{ command="gpg";    winget="GnuPG.GnuPG";   label="GnuPG (gpg)"; manualUrl="https://gnupg.org/download/"; reason="UM/H78 .pkg decryption + Beetlejuice signing" }
            @{ command="ffmpeg"; winget="Gyan.FFmpeg";   label="ffmpeg";  manualUrl="https://www.gyan.dev/ffmpeg/builds/";    reason="Audio resampling on Write + P3 VID-to-MP4 conversion" }
        )
    }

    "Barrels of Fun" = @{
        Description  = "Labyrinth, Dune, Winchester (.fun files)"
        WslPackages  = @(
            @{ probe="gpg";      pkg="gnupg"; label="gnupg (in WSL)";    reason=".fun GPG decryption / re-encryption" }
            @{ probe="tar";      pkg="tar";   label="tar (in WSL)";      reason="Archive packing/unpacking" }
            @{ probe="curl";     pkg="curl";  label="curl (in WSL)";     reason="Downloads GDRE Tools release zip" }
            @{ probe="unzip";    pkg="unzip"; label="unzip (in WSL)";    reason="Unpacks GDRE Tools release zip" }
            @{ probe="xvfb-run"; pkg="xvfb";  label="xvfb (in WSL)";     reason="Headless X server for GDRE Tools on WSL/Linux" }
            @{ probe="cwebp";    pkg="webp";  label="webp / cwebp (in WSL)"; reason="Texture re-import during Write pipeline" }
        )
        HostPackages = @()
        # Custom post-install: GDRE Tools doesn't live in apt; we
        # fetch the latest GitHub release and install it to
        # /opt/gdre_tools/ with a /usr/local/bin/gdre_tools wrapper.
        # See InstallGdreTools below.
        Custom       = @("InstallGdreTools")
    }

    "Chicago Gaming Company" = @{
        Description  = "Medieval Madness Remake, AFM Remake, MB Remake, Pulp Fiction (.img installer images)"
        WslPackages  = @(
            @{ probe="debugfs"; pkg="e2fsprogs"; label="e2fsprogs/debugfs"; reason="ext4 read/write on installer P3 + emmc.img P2" }
            @{ probe="xxd";     pkg="xxd";       label="xxd";              reason="Reading the inner emmc.img MBR partition table" }
        )
        HostPackages = @()
        PipPackages  = @(
            @{ probe="faster_whisper"; pkg="faster-whisper"; label="faster-whisper"; reason="Auto-transcribe samples to callouts.csv (Whisper tiny.en on CPU)" }
        )
    }

    "Jersey Jack Pinball" = @{
        Description  = "Wonka, GnR, Hobbit, Wizard of Oz, Avatar, etc. (.iso disk images)"
        WslPackages  = @(
            @{ probe="partclone.ext4"; pkg="partclone";          label="partclone";              reason="ISO partition extraction" }
            @{ probe="debugfs";        pkg="e2fsprogs";          label="e2fsprogs/debugfs";      reason="ext4 filesystem extraction" }
            @{ probe="xorriso";        pkg="xorriso";            label="xorriso";                reason="ISO rebuild for Write pipeline" }
            @{ probe="pigz";           pkg="pigz";               label="pigz";                   reason="Parallel gzip - speeds up large image work" }
            @{ probe="ffmpeg";         pkg="ffmpeg";             label="ffmpeg (in WSL)";        reason="Audio processing for Write pipeline" }
            @{ probe="python3";        pkg="python3-zstandard";  label="python3-zstandard";      reason="zstd-compressed images" }
        )
        HostPackages = @()
    }

    "Stern Pinball" = @{
        Description  = "Spike 2: Godzilla, Jurassic Park, Deadpool, Star Wars, Iron Maiden + more (SD-card images)"
        WslPackages  = @()
        HostPackages = @(
            @{ command="ffmpeg"; winget="Gyan.FFmpeg"; label="ffmpeg + ffplay"; manualUrl="https://www.gyan.dev/ffmpeg/builds/"; reason="Replace Audio/Video preview (ffplay), spectrogram + format conversion (ffmpeg)" }
        )
        # The Spike 2 audio engine is pure-Python (no WSL) but needs these pip
        # packages.  As of v0.15.x the installer bundles them into the app's
        # Python already, so on a fresh install these usually report [OK]; this
        # entry is what lets an EXISTING install pick them up via Install
        # Missing (previously there was no Spike 2 option at all).
        PipPackages  = @(
            @{ probe="unicorn";        pkg="unicorn";        label="unicorn";        reason="ARM emulator that drives the card's firmware to recover the audio codec keystream" }
            @{ probe="capstone";       pkg="capstone";       label="capstone";       reason="Locates the codec's companding point when re-encoding replaced audio" }
            @{ probe="numpy";          pkg="numpy";          label="numpy";          reason="Audio sample array math in the decode / re-encode pipeline" }
            @{ probe="faster_whisper"; pkg="faster-whisper"; label="faster-whisper"; reason="Auto-name call-outs: transcribe spoken voice clips to name the WAVs" }
        )
    }
}

# =========================================================================
# Manufacturer picker
# =========================================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Pinball Asset Decryptor - Prerequisite Installer"          -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Pick the manufacturers you plan to use.  We'll install only"
Write-Host "the tools those plugins actually need."
Write-Host ""

$mfrList = @($ManufacturerPrereqs.Keys)
for ($i = 0; $i -lt $mfrList.Count; $i++) {
    $name = $mfrList[$i]
    $desc = $ManufacturerPrereqs[$name].Description
    Write-Host ("  [{0}] {1}" -f ($i + 1), $name) -ForegroundColor White
    Write-Host ("       {0}" -f $desc)            -ForegroundColor Gray
}
Write-Host ("  [a] All of the above")             -ForegroundColor White
Write-Host ""
$pick = Read-Host "Enter numbers separated by commas (e.g. '2,4'), or 'a' for all"

$selected = @()
if ($pick.Trim().ToLower() -eq "a") {
    $selected = $mfrList
} else {
    foreach ($tok in ($pick -split "[,\s]+")) {
        $tok = $tok.Trim()
        if ($tok -match '^\d+$') {
            $idx = [int]$tok - 1
            if ($idx -ge 0 -and $idx -lt $mfrList.Count) {
                $selected += $mfrList[$idx]
            }
        }
    }
}

if ($selected.Count -eq 0) {
    Write-Host "`nNo manufacturers selected - nothing to install." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 0
}

Write-Host ""
Write-Host "Selected: $($selected -join ', ')" -ForegroundColor Green

# =========================================================================
# Build the deduplicated install set
# =========================================================================
# WSL probes deduped by .probe, host commands deduped by .command.  Each
# tool tracks WHICH manufacturers asked for it so we can show that to
# the user.

$wslByProbe  = @{}
$hostByCmd   = @{}
$pipByProbe  = @{}

foreach ($mfr in $selected) {
    foreach ($pkg in $ManufacturerPrereqs[$mfr].WslPackages) {
        $key = $pkg.probe
        if ($wslByProbe.ContainsKey($key)) {
            $wslByProbe[$key].for += $mfr
        } else {
            $copy = $pkg.Clone()
            $copy["for"] = @($mfr)
            $wslByProbe[$key] = $copy
        }
    }
    foreach ($pkg in $ManufacturerPrereqs[$mfr].HostPackages) {
        $key = $pkg.command
        if ($hostByCmd.ContainsKey($key)) {
            $hostByCmd[$key].for += $mfr
        } else {
            $copy = $pkg.Clone()
            $copy["for"] = @($mfr)
            $hostByCmd[$key] = $copy
        }
    }
    # PipPackages is optional on a manufacturer entry; default to empty.
    $pipEntries = $ManufacturerPrereqs[$mfr].PipPackages
    if ($pipEntries) {
        foreach ($pkg in $pipEntries) {
            $key = $pkg.probe
            if ($pipByProbe.ContainsKey($key)) {
                $pipByProbe[$key].for += $mfr
            } else {
                $copy = $pkg.Clone()
                $copy["for"] = @($mfr)
                $pipByProbe[$key] = $copy
            }
        }
    }
}

$wslPlan  = @($wslByProbe.Values)
$hostPlan = @($hostByCmd.Values)
$pipPlan  = @($pipByProbe.Values)

# Show the install plan
Write-Host ""
Write-Host "Install plan:" -ForegroundColor Cyan
if ($hostPlan.Count -gt 0) {
    Write-Host "  Host-side (Windows):"
    foreach ($p in $hostPlan) {
        Write-Host ("    - {0,-30} for: {1}" -f $p.label, ($p.for -join ", ")) -ForegroundColor Gray
        Write-Host ("        {0}" -f $p.reason) -ForegroundColor DarkGray
    }
}
if ($wslPlan.Count -gt 0) {
    Write-Host "  WSL framework (required for the WSL packages below):"
    Write-Host "    - WSL2 + Ubuntu                  for: $($selected -join ', ')" -ForegroundColor Gray
    Write-Host "        Linux runtime that the WSL-side tools live in" -ForegroundColor DarkGray
    Write-Host "  WSL-side (inside Ubuntu):"
    foreach ($p in $wslPlan) {
        Write-Host ("    - {0,-30} for: {1}" -f $p.label, ($p.for -join ", ")) -ForegroundColor Gray
        Write-Host ("        {0}" -f $p.reason) -ForegroundColor DarkGray
    }
}
if ($pipPlan.Count -gt 0) {
    Write-Host "  Python packages (pip, installed into the same Python the app uses):"
    foreach ($p in $pipPlan) {
        Write-Host ("    - {0,-30} for: {1}" -f $p.label, ($p.for -join ", ")) -ForegroundColor Gray
        Write-Host ("        {0}" -f $p.reason) -ForegroundColor DarkGray
    }
}
Write-Host ""

$proceed = Read-Host "Proceed with install? (y/n)"
if ($proceed -ne 'y') {
    Write-Host "Cancelled." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 0
}

# =========================================================================
# 1. Host-side packages (winget)
# =========================================================================
if ($hostPlan.Count -gt 0) {
    $wingetAvailable = $false
    try {
        winget --version 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $wingetAvailable = $true }
    } catch {}

    foreach ($p in $hostPlan) {
        Write-Step ("Checking {0} on Windows host (for: {1})" -f $p.label, ($p.for -join ", "))
        $found = $false
        try {
            & $p.command --version 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { $found = $true; Write-OK $p.label }
        } catch {}

        if (-not $found) {
            if ($wingetAvailable) {
                Write-Host ("  Installing {0} via winget..." -f $p.label) -ForegroundColor Cyan
                # Don't pipe winget through ForEach-Object - that runs every
                # line through PowerShell's string layer and corrupts the
                # encoding of progress bars / status spinners.
                # --disable-interactivity stops winget drawing the box-char
                # progress bars at all (which look fine on Win11 Terminal but
                # render garbled in Win10 conhost).
                winget install --id $p.winget --silent --disable-interactivity `
                    --accept-package-agreements --accept-source-agreements
                $wingetExit = $LASTEXITCODE

                # winget edits PATH in the registry but the running process
                # has a stale copy.  Reload from Machine + User PATH.
                Update-SessionPath

                # Re-probe with a fresh PATH lookup
                $reFound = $false
                try {
                    & $p.command --version 2>&1 | Out-Null
                    if ($LASTEXITCODE -eq 0) { $reFound = $true }
                } catch {}

                # winget exit codes that mean "package is installed,
                # nothing more to do":
                #   0           = success
                #   -1978335189 = APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE
                #                 ("Found existing package; no newer version
                #                 available" - i.e. already at latest).
                $wingetSuccess = ($wingetExit -eq 0 -or
                                  $wingetExit -eq -1978335189)

                if ($reFound) {
                    Write-Installed $p.label
                } elseif ($wingetSuccess) {
                    Write-Host ("  Installed, but {0} isn't on PATH for THIS shell - open a new terminal to use it." -f $p.command) -ForegroundColor Yellow
                    Write-Installed ("{0} (restart shell to pick up PATH)" -f $p.label)
                } else {
                    Write-Host ("  winget exited with code {0}." -f $wingetExit) -ForegroundColor Red
                    Write-Host ("  Manual install: {0}" -f $p.manualUrl) -ForegroundColor Yellow
                    Write-FAIL $p.label
                }
            } else {
                Write-Host ("  winget not available - install {0} manually from:" -f $p.label) -ForegroundColor Yellow
                Write-Host ("    {0}" -f $p.manualUrl) -ForegroundColor Yellow
                Write-FAIL $p.label
            }
        }
    }
}

# =========================================================================
# 2. WSL2 + Ubuntu (only if any WSL packages are needed)
# =========================================================================
$needsWsl = $wslPlan.Count -gt 0
$wslAvailable = $false
$ubuntuFound = $false

if ($needsWsl) {
    Write-Step "Checking WSL2..."
    try {
        wsl --status 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $wslAvailable = $true; Write-OK "WSL2" }
    } catch {}

    if (-not $wslAvailable) {
        # User already approved the install plan, which listed "WSL2 + Ubuntu"
        # as required.  Just install it - asking again would be a useless
        # confirmation that, if declined, leaves nothing to install.
        Write-Host "  Installing WSL2 + Ubuntu (this may take several minutes)..." -ForegroundColor Cyan
        wsl --install -d Ubuntu --no-launch
        $needsReboot = $true
        Write-Installed "WSL2 + Ubuntu (reboot required)"
    }

    Write-Step "Checking for an apt-based WSL distro..."
    if ($wslAvailable -and (Test-WslHasApt)) {
        $ubuntuFound = $true
        Write-OK "Ubuntu / apt-based distro"
    }

    if (-not $ubuntuFound -and $wslAvailable -and -not $needsReboot) {
        # No usable distro yet - install Ubuntu directly.
        # --no-launch skips the interactive 'create UNIX user' prompt; we
        # only ever exec via 'wsl -u root' so a default user isn't needed.
        # We let wsl write its output to the console directly (no capture)
        # because PowerShell 5.1's pipeline mangles its UTF-16LE output.
        Write-Host "  Installing Ubuntu into WSL (this may take a few minutes)..." -ForegroundColor Cyan
        & wsl --install -d Ubuntu --no-launch
        $installExit = $LASTEXITCODE

        # Don't trust the install exit code (ERROR_ALREADY_EXISTS shows
        # up as a non-zero exit but means "already there, all good").
        # Re-test the actual capability we need.
        Start-Sleep -Seconds 2
        if (Test-WslHasApt) {
            $ubuntuFound = $true
            Write-Installed "Ubuntu / apt-based distro"
        } elseif ($installExit -eq 0) {
            # Fresh install + first-boot may still be initializing;
            # trust wsl's success signal.
            $ubuntuFound = $true
            Write-Installed "Ubuntu (queued; first boot may still be initializing)"
        } else {
            Write-FAIL ("Ubuntu (wsl --install exit {0}; try: wsl --list --verbose)" -f $installExit)
        }
    } elseif ($needsReboot -and -not $ubuntuFound) {
        Write-SKIP "Ubuntu (will install after WSL2 reboot)"
    } elseif (-not $wslAvailable) {
        Write-SKIP "Ubuntu (WSL2 not available yet)"
    }
}

# =========================================================================
# 3. WSL-side packages (apt)
# =========================================================================
if ($wslPlan.Count -gt 0) {
    if ($wslAvailable -and $ubuntuFound) {
        Write-Step "Refreshing apt indexes (one-time)..."
        wsl -u root -- bash -c "apt-get update -qq" 2>&1 |
            ForEach-Object { Write-Host "    $_" }

        foreach ($p in $wslPlan) {
            Write-Step ("Checking {0} in WSL (for: {1})" -f $p.label, ($p.for -join ", "))
            $found = $false
            try {
                wsl -u root -- which $p.probe 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { $found = $true; Write-OK $p.label }
            } catch {}

            if (-not $found) {
                Write-Host ("  Installing {0}..." -f $p.label) -ForegroundColor Cyan
                $cmd = "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq " + $p.pkg
                wsl -u root -- bash -c $cmd 2>&1 | ForEach-Object { Write-Host "    $_" }
                try {
                    wsl -u root -- which $p.probe 2>&1 | Out-Null
                    if ($LASTEXITCODE -eq 0) { Write-Installed $p.label }
                    else                     { Write-FAIL $p.label }
                } catch {
                    Write-FAIL $p.label
                }
            }
        }
    } else {
        foreach ($p in $wslPlan) {
            Write-SKIP ("{0} (WSL/Ubuntu not available yet)" -f $p.label)
        }
    }
}

# =========================================================================
# 4. Per-mfr custom post-install steps
# =========================================================================
function Install-GdreTools {
    Write-Step "Installing GDRE Tools (Godot RE Tools) inside WSL..."
    if (-not ($wslAvailable -and $ubuntuFound)) {
        Write-SKIP "GDRE Tools (WSL/Ubuntu not available yet)"
        return
    }
    # Check if it's already installed.
    wsl -u root -- bash -c "test -x /opt/gdre_tools/gdre_tools.x86_64" *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "GDRE Tools (already installed at /opt/gdre_tools)"
        return
    }
    # The install logic lives in install_gdre.sh — a real shell script
    # (pinned to LF via .gitattributes) shared verbatim with the Linux
    # installer.  We hand WSL the file directly instead of piping an
    # embedded here-string: the old here-string approach glued a UTF-8
    # BOM onto line 1 and left CRLFs that broke the script's heredoc.
    $gdreSh = Join-Path $PSScriptRoot "install_gdre.sh"
    if (-not (Test-Path -LiteralPath $gdreSh)) {
        Write-FAIL "GDRE Tools (install_gdre.sh missing beside the installer)"
        return
    }
    $wslSh = (wsl -u root -- wslpath -a "$gdreSh").Trim()
    wsl -u root -- bash $wslSh 2>&1 | ForEach-Object { Write-Host "    $_" }
    wsl -u root -- bash -c "test -x /usr/local/bin/gdre_tools" *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Installed "GDRE Tools (wrapper at /usr/local/bin/gdre_tools)"
    } else {
        Write-FAIL "GDRE Tools"
    }
}

foreach ($mfr in $selected) {
    $custom = $ManufacturerPrereqs[$mfr].Custom
    if ($custom) {
        foreach ($step in $custom) {
            switch ($step) {
                "InstallGdreTools" { Install-GdreTools }
                default            { Write-SKIP "Unknown custom step: $step" }
            }
        }
    }
}

# =========================================================================
# Pip packages -- installed into the same Python that runs the app.
# =========================================================================
# We use `python -m pip install` rather than calling `pip` directly so
# the package lands in the right interpreter's site-packages.  The
# Windows app bundles an embeddable Python (with pip) at {app}\python\;
# we install into that one so the app's `python:` prereq probe — which
# checks the interpreter the app actually runs on — finds the package.
if ($pipPlan.Count -gt 0) {
    # Prefer the bundled interpreter beside this installer.  A packaged
    # install has no `python` on PATH at all (that is what silently
    # skipped faster-whisper), and a system `python`, if present, is
    # the wrong interpreter.  PATH is only a fallback for running from
    # source, where there is no bundled Python.
    $pythonCmd = $null
    $pipTarget = $null
    $bundledPython = Join-Path $PSScriptRoot "python\python.exe"
    if (Test-Path -LiteralPath $bundledPython) {
        $pythonCmd = $bundledPython
        $pipTarget = Join-Path $PSScriptRoot "python\Lib\site-packages"
    } else {
        foreach ($cand in @("python", "python3", "py")) {
            try {
                & $cand --version 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { $pythonCmd = $cand; break }
            } catch {}
        }
    }
    if (-not $pythonCmd) {
        foreach ($p in $pipPlan) {
            Write-Host ("No Python found -- skipping pip install of {0}." -f $p.label) -ForegroundColor Yellow
            Write-SKIP $p.label
        }
    } else {
        foreach ($p in $pipPlan) {
            Write-Step ("Checking pip package {0} (for: {1})" -f $p.label, ($p.for -join ", "))
            $importCheck = "import importlib, sys; sys.exit(0 if importlib.util.find_spec('$($p.probe)') else 1)"
            & $pythonCmd -c $importCheck 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-OK $p.label
            } else {
                Write-Host ("  Installing {0} via {1} -m pip install..." -f $p.label, $pythonCmd) -ForegroundColor Cyan
                if ($pipTarget) {
                    # Bundled Python: install into its site-packages
                    # explicitly, the same way build.ps1 seeds the bundle.
                    & $pythonCmd -m pip install --no-warn-script-location --target $pipTarget $p.pkg
                } else {
                    & $pythonCmd -m pip install --upgrade $p.pkg
                }
                if ($LASTEXITCODE -eq 0) {
                    Write-Installed $p.label
                } else {
                    Write-Host ("  pip install failed (exit {0})." -f $LASTEXITCODE) -ForegroundColor Red
                    Write-Host ("  Manual install: {0} -m pip install {1}" -f $pythonCmd, $p.pkg) -ForegroundColor Yellow
                    Write-FAIL $p.label
                }
            }
        }
        if ($pipTarget) {
            # The installer runs elevated.  Packages pip writes under
            # Program Files — and sometimes the bundled Python tree
            # itself — can carry ACLs the normal-user app process cannot
            # read, so importing faster_whisper *or one of its deps*
            # (e.g. typing_extensions) fails at runtime with
            # [Errno 13] Permission denied.
            #
            # A plain `/grant Users:RX` (the v0.6.3 attempt) only ADDS an
            # allow ACE; it cannot override a stray DENY ACE or repair
            # broken ACL inheritance.  `/reset` is decisive: it strips
            # every explicit ACE from each file so the whole tree
            # re-inherits the parent ACL — Program Files grants the Users
            # group read+execute by default.  We then add an explicit
            # Users (SID S-1-5-32-545) read+execute grant as a
            # belt-and-suspenders guard for hardened systems whose
            # Program Files ACL is non-standard.  Run unconditionally —
            # this also repairs an install whose perms are already wrong,
            # which the find_spec check above cannot detect.
            $pythonDir = Split-Path -Parent $bundledPython
            Write-Step "Fixing bundled-Python file permissions..."
            $aclOut = @()
            $aclOut += & icacls $pythonDir /reset /T /C /Q 2>&1
            $aclOut += & icacls $pythonDir /grant '*S-1-5-32-545:(OI)(CI)RX' `
                /T /C /Q 2>&1
            $aclFail = $aclOut | Where-Object {
                $_ -match 'Failed processing' -and
                $_ -notmatch 'Failed processing 0 ' }
            if ($aclFail) {
                Write-Host ("  icacls reported errors: {0}" -f `
                    ($aclFail -join '; ')) -ForegroundColor Yellow
            } else {
                Write-Host ("  [OK] Users group can now read the bundled " +
                    "Python packages.") -ForegroundColor Green
            }
        }
    }
}

# =========================================================================
# Summary
# =========================================================================
Write-Host "`n"
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Prerequisites Summary"                                       -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
foreach ($r in $results) {
    $color = switch ($r.Status) {
        "OK"        { "Green" }
        "Installed" { "Green" }
        "Missing"   { "Red" }
        "Skipped"   { "Yellow" }
        default     { "White" }
    }
    Write-Host ("  {0,-40} {1}" -f $r.Name, $r.Status) -ForegroundColor $color
}

if ($needsReboot) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host "  A REBOOT IS REQUIRED to finish WSL2 setup."                -ForegroundColor Yellow
    Write-Host "  Re-run this script from the Start Menu after reboot to"   -ForegroundColor Yellow
    Write-Host "  install the remaining WSL packages."                       -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Yellow
    $reboot = Read-Host "  Reboot now? (y/n)"
    if ($reboot -eq 'y') { Restart-Computer -Force }
} else {
    $missing = ($results | Where-Object { $_.Status -eq "Missing" }).Count
    $skipped = ($results | Where-Object { $_.Status -eq "Skipped" }).Count
    if ($missing -eq 0 -and $skipped -eq 0) {
        Write-Host "`n  All prerequisites for the selected manufacturer(s) are installed." -ForegroundColor Green
    } elseif ($skipped -gt 0) {
        Write-Host "`n  Some prerequisites were skipped - re-run any time." -ForegroundColor Yellow
    }
}

Write-Host ""
Read-Host "Press Enter to exit"
