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
# nulls below in Get-WslInstallPlan for older wsl.exe builds that ignore
# the env var.
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

# --- Which distro do our probes actually run in, and is it WSL 2? --------
# `wsl --status` exits 0 on a machine whose only distro is WSL 1, and
# losetup is present in WSL 1's util-linux like anywhere else - so on such
# a machine this installer used to report [OK] WSL2, [OK] Ubuntu and [OK]
# util-linux while the app's own strip stayed red, because a WSL 1 distro
# owns no loop devices.  A user bounced between the two for a whole
# support round-trip (PAD-73).  Read the VERSION column instead.
#
# `wsl -l -v` marks the default distro with * and puts the version last:
#     NAME      STATE      VERSION
#   * Ubuntu    Running    2
# The header is localized, so nothing here reads it; the * line is split
# from the right so a distro name with spaces survives.  NULs are stripped
# for the same reason Get-WslInstallPlan strips them - wsl.exe builds older
# than 0.64 ignore WSL_UTF8 and answer in UTF-16LE.
function Get-WslDefaultDistro {
    if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) { return $null }
    $out = ""
    try {
        $out = ((& wsl -l -v 2>&1 | Out-String) -replace "`0", "")
    } catch { return $null }
    foreach ($line in ($out -split "`r?`n")) {
        if ($line -match '^\s*\*\s*(.+?)\s+\S+\s+(\d+)\s*$') {
            return @{ Name = $Matches[1].Trim(); Version = [int]$Matches[2] }
        }
    }
    return $null
}

# --- wsl --install capability probe --------------------------------------
# Older inbox wsl.exe builds (pre-Store WSL) reject options they don't
# know by printing usage and exiting -1 WITHOUT installing anything, so
# hardcoding --no-launch turned the whole Ubuntu install into a silent
# no-op on those machines (PAD-19: summary showed "wsl --install exit -1"
# while WSL2 itself reported OK).  Build the argument list from the flags
# THIS machine's wsl.exe actually advertises in its own help text.
function Get-WslInstallPlan {
    $help = ""
    try {
        # Strip NULs: older wsl.exe ignores WSL_UTF8 and emits UTF-16LE,
        # which a PowerShell 5.1 capture renders with interleaved NULs.
        $help = ((& wsl --help 2>&1 | Out-String) -replace "`0", "")
    } catch {}
    # --no-launch skips the interactive 'create UNIX user' first boot; we
    # only ever exec via 'wsl -u root' so a default user isn't needed.
    $installArgs = @("--install", "-d", "Ubuntu")
    if ($help -match '--no-launch') { $installArgs += "--no-launch" }
    @{
        InstallArgs = $installArgs
        NoLaunch    = [bool]($help -match '--no-launch')
        # --web-download fetches the distro from Microsoft's CDN — the
        # fallback when the Store is broken, blocked, or signed out.
        WebDownload = [bool]($help -match '--web-download')
    }
}

# --- Firmware virtualization probe ---------------------------------------
# WSL2 boots a real utility VM, so with virtualization switched off in the
# BIOS/UEFI every install/first-launch dies with 0x80370102 ("virtualization
# is not enabled").  wsl.exe does print that, but in plain console color —
# it scrolled past a user unnoticed through three support round-trips while
# the colored text around it drew the eye (PAD-21).  HypervisorPresent=True
# means a hypervisor is already running, which is fine regardless of what
# the firmware flag reads (Windows reports it False once a hypervisor owns
# the CPU).  Only trust "disabled" when no hypervisor is running AND the
# firmware flag explicitly reads False; a query error means "don't know",
# never "disabled".
function Test-VirtualizationDisabled {
    try {
        $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
        if ($cs.HypervisorPresent) { return $false }
        $cpu = @(Get-CimInstance Win32_Processor -ErrorAction Stop)[0]
        if ($null -eq $cpu.VirtualizationFirmwareEnabled) { return $false }
        return (-not $cpu.VirtualizationFirmwareEnabled)
    } catch { return $false }
}

function Write-VirtualizationBanner {
    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Red
    Write-Host "  HARDWARE VIRTUALIZATION IS DISABLED ON THIS MACHINE"          -ForegroundColor Red
    Write-Host "  ============================================================" -ForegroundColor Red
    Write-Host "  WSL2 runs Linux in a virtual machine, and this computer's"    -ForegroundColor Red
    Write-Host "  BIOS/UEFI firmware has virtualization switched off, so the"   -ForegroundColor Red
    Write-Host "  WSL2/Ubuntu install cannot succeed no matter how many times"  -ForegroundColor Red
    Write-Host "  it is re-run.  To fix it:"                                    -ForegroundColor Red
    Write-Host "    1. Reboot into the BIOS/UEFI setup screen (usually Del,"    -ForegroundColor Yellow
    Write-Host "       F2 or F10 during power-on)."                             -ForegroundColor Yellow
    Write-Host "    2. Enable the option named Intel VT-x, AMD-V, SVM Mode,"    -ForegroundColor Yellow
    Write-Host "       or Virtualization Technology (often under Advanced or"   -ForegroundColor Yellow
    Write-Host "       CPU settings)."                                          -ForegroundColor Yellow
    Write-Host "    3. Save, boot back into Windows, re-run this installer."    -ForegroundColor Yellow
    Write-Host "  If the firmware has no such option, this machine cannot run"  -ForegroundColor Yellow
    Write-Host "  WSL2 - the WSL-side features need a different PC."            -ForegroundColor Yellow
    Write-Host ""
}

# --- WSL2 restart-pending marker -----------------------------------------
# `wsl --install` on a machine without WSL2 enables Windows features that
# only take effect after a RESTART.  Users who skip it (or use Shut down,
# which with Fast Startup is NOT a restart) re-run the installer and used
# to get the identical "reboot required" banner with no hint that the
# restart never happened (PAD-16: a user looped on this).  We record which
# boot session ran `wsl --install`; a re-run in the SAME session can then
# say "you haven't restarted yet" instead of reinstalling into the void.
$script:RestartMarker = Join-Path $env:ProgramData `
    "Pinball Asset Decryptor\wsl_restart_pending.txt"

function Get-BootSessionId {
    # LastBootUpTime only changes on a real restart (a Fast Startup
    # "Shut down" resumes the same kernel session) — which is exactly
    # the event WSL2 setup is waiting for.
    try {
        (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToFileTime().ToString()
    } catch { "" }
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
        HostPackages = @(
            # Gyan.FFmpeg is the FULL build (bundles ffplay.exe) -- the
            # "essentials" build omits ffplay, which breaks Replace-Audio
            # preview.  ffmpeg also does the Replace-Audio format-match
            # (resample / channel / bit-depth) at Write time and the
            # optional DMD-scene MP4 assembly.
            # Probed by ffplay, not ffmpeg: an "essentials" build (or the
            # copy bundled with the app) satisfies `ffmpeg --version` while
            # leaving Replace-Audio preview with no player at all (PAD-92).
            @{ command="ffmpeg"; probe="ffplay"; winget="Gyan.FFmpeg"; label="ffmpeg + ffplay"; manualUrl="https://www.gyan.dev/ffmpeg/builds/ (pick the *full* build, not essentials)"; reason="Replace Audio: format-match replacements on Write + ffplay preview" }
        )
        PipPackages  = @(
            @{ probe="faster_whisper"; pkg="faster-whisper"; label="faster-whisper"; reason="Auto-transcribe samples to callouts.csv (Whisper tiny.en on CPU)" }
        )
    }

    "Jersey Jack Pinball" = @{
        Description  = "Wonka, GnR, Hobbit, Wizard of Oz, Avatar, etc. (.iso disk images)"
        WslPackages  = @(
            # Every JJP flow loop-mounts the ext4 image it pulls out of the
            # .iso, which is why the plugin declares the same loop-device
            # prerequisite Stern does.  Listed here so the WSL-version check
            # below (a WSL 1 distro has no loop devices at all) covers a JJP
            # user too, not only a Stern one.
            @{ probe="losetup";        pkg="util-linux mount";   label="util-linux (losetup/mount, in WSL)"; reason="Loop-mounts the game image extracted from the .iso" }
            @{ probe="partclone.ext4"; pkg="partclone";          label="partclone";              reason="ISO partition extraction" }
            @{ probe="debugfs";        pkg="e2fsprogs";          label="e2fsprogs/debugfs";      reason="ext4 filesystem extraction" }
            @{ probe="xorriso";        pkg="xorriso";            label="xorriso";                reason="ISO rebuild for Write pipeline" }
            @{ probe="pigz";           pkg="pigz";               label="pigz";                   reason="Parallel gzip - speeds up large image work" }
            @{ probe="ffmpeg";         pkg="ffmpeg";             label="ffmpeg (in WSL)";        reason="Audio processing for Write pipeline" }
            @{ probe="python3";        pkg="python3-zstandard";  label="python3-zstandard";      reason="zstd-compressed images" }
            # Probed by compiling, not by 'which gcc': the gcc package only
            # *recommends* libc6-dev, so a WSL without recommended packages
            # has the compiler but none of its headers.
            @{ probe="gcc";            pkg="gcc libc6-dev";      label="gcc + libc6-dev";        reason="Builds the decrypt/encrypt hooks for dongle extraction";
               probeCmd="gcc -include stdio.h -x c /dev/null -c -o /var/tmp/ccprobe.o" }
        )
        HostPackages = @()
    }

    "Stern Pinball" = @{
        Description  = "Spike 2: Godzilla, Jurassic Park, Deadpool, Star Wars, Iron Maiden + more (SD-card images)"
        # Blip-free callouts (v0.94.0+) and full-size video replacement grow
        # files inside the card's ext4 partition through WSL2 — without it
        # every Stern build silently falls back to the standard build with the
        # brief original-sound scrap (a tester's two-stage spinner click).
        # losetup/mount ship in Ubuntu's stock util-linux/mount packages, so
        # this entry is normally a no-op install; its real job is pulling in
        # the WSL2 + Ubuntu framework step for Stern users.
        WslPackages  = @(
            @{ probe="losetup"; pkg="util-linux mount"; label="util-linux (losetup/mount, in WSL)"; reason="Blip-free callouts + full-size video replacement: loop-mounts the card image to grow files in its ext4 partition" }
            # The Emulate tab.  These are what let the rig in tools\spike2_emu
            # build the guest and run the machine's own armhf binary; without
            # them the tab starts and the run dies at the first missing tool.
            # fuse2fs itself is NOT listed: cardmount.sh fetches it into a
            # private prefix with `apt-get download`, deliberately, because that
            # needs no root - but it does need fusermount3 to be present and
            # setuid, which is what the fuse3 package provides.
            @{ probe="qemu-arm-static";        pkg="qemu-user-static";         label="qemu-user-static";        reason="Emulate tab: runs the machine's own 32-bit ARM game binary on this PC" }
            @{ probe="arm-linux-gnueabihf-gcc"; pkg="gcc-arm-linux-gnueabihf"; label="ARM cross-compiler";      reason="Emulate tab: builds the LD_PRELOAD hardware shim the game runs against" }
            # The NATIVE compiler, which is a different one from the line
            # above and was left off this list until a user turned up with the
            # cross compiler, a shim that built fine, and no gcc — so the run
            # died half a minute in on the renderer.  Probed by compiling for
            # the same reason the JJP entry is: gcc only *recommends*
            # libc6-dev, so the compiler can be on PATH with no headers.
            @{ probe="gcc";                    pkg="gcc libc6-dev";            label="gcc + libc6-dev";         reason="Emulate tab: builds padglhost, the native renderer that draws the game's picture";
               probeCmd="gcc -include stdio.h -x c /dev/null -c -o /var/tmp/ccprobe.o" }
            @{ probe="debugfs";                pkg="e2fsprogs";                label="e2fsprogs/debugfs";       reason="Emulate tab: builds the guest filesystem out of a card image, without root" }
            @{ probe="fusermount3";            pkg="fuse3";                    label="fuse3 (fusermount3)";     reason="Emulate tab: mounts a card read-only so a title runs without extracting 6 GB" }
            # IN WSL, and that is the whole point of the line: there is an
            # ffmpeg in HostPackages below and the app bundles a third one on
            # PATH, so this machine can have two of them and still be the
            # machine that fails.  The game decodes neither its video nor its
            # audio itself; both are done Linux-side, so without this the
            # emulator starts perfectly and plays a black, silent window.
            @{ probe="ffmpeg";                 pkg="ffmpeg";                   label="ffmpeg (in WSL)";         reason="Emulate tab: decodes the game's video and sound, which the game cannot decode itself" }
            # SAVE STATES, and it is the one line here whose absence used to
            # stop the emulator dead.  Every Start since v0.126.0 boots the
            # checkpointable shape, that shape umounts the old root with a
            # NATIVE STATIC busybox after pivoting away from the host tree,
            # and no machine has one by default.  The rig now falls back to
            # the ordinary boot instead of refusing to start, so what this
            # supplies is the feature; probed by name because that is the
            # file the pivot copies (Ubuntu's busybox-initramfs is dynamic
            # and would not do).
            @{ probe="/bin/busybox";           pkg="busybox-static";           label="busybox-static";          reason="Emulate tab: save states - the guest boots in the one shape that can be frozen and reloaded";
               probeCmd="test -f /bin/busybox && ! ldd /bin/busybox 2>&1 | grep -q '=>'" }
        )
        HostPackages = @(
            # Probed by ffplay (see the CGC entry): ffmpeg alone is not
            # enough for the preview, and ffmpeg alone is what the app bundles.
            @{ command="ffmpeg"; probe="ffplay"; winget="Gyan.FFmpeg"; label="ffmpeg + ffplay"; manualUrl="https://www.gyan.dev/ffmpeg/builds/ (pick the *full* build, not essentials)"; reason="Replace Audio/Video preview (ffplay), spectrogram + format conversion (ffmpeg)" }
        )
        # The Spike 2 audio ENGINE is pure-Python and needs these pip
        # packages (WSL above is only the ext4 file-growth path, not the
        # codec).  As of v0.15.x the installer bundles them into the app's
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
            # Keyed on the COMMAND so one winget package is installed once,
            # but the stricter probe wins: the entries needing the FULL build
            # test for ffplay, and that must not be lost because another
            # manufacturer contributed the plain-ffmpeg entry first (PAD-92).
            if ($pkg.probe -and -not $hostByCmd[$key].probe) {
                $hostByCmd[$key].probe = $pkg.probe
            }
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
        # Optional per-entry probe: what has to answer for the package to
        # count as installed (defaults to the command itself).
        $probeCmd = $p.command
        if ($p.probe) { $probeCmd = $p.probe }
        $found = $false
        try {
            & $probeCmd --version 2>&1 | Out-Null
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
                    & $probeCmd --version 2>&1 | Out-Null
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
                    Write-Host ("  Installed, but {0} isn't on PATH for THIS shell - open a new terminal to use it." -f $probeCmd) -ForegroundColor Yellow
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

    if ($wslAvailable) {
        # WSL2 answers, so any earlier restart-pending state is resolved.
        if (Test-Path -LiteralPath $script:RestartMarker) {
            Remove-Item -LiteralPath $script:RestartMarker -Force `
                -ErrorAction SilentlyContinue
        }
    } else {
        $bootId = Get-BootSessionId
        $pendingSince = $null
        if (Test-Path -LiteralPath $script:RestartMarker) {
            $pendingSince = (Get-Content -LiteralPath $script:RestartMarker `
                -ErrorAction SilentlyContinue | Select-Object -First 1)
        }
        if (Test-VirtualizationDisabled) {
            # No point installing (or waiting on a restart): the VM WSL2
            # boots cannot start until the firmware setting changes.
            Write-VirtualizationBanner
            Write-FAIL "WSL2 + Ubuntu (virtualization disabled in BIOS/UEFI)"
        } elseif ($bootId -and $pendingSince -eq $bootId) {
            # Same boot session as the run that installed WSL2: the restart
            # hasn't happened yet, so running `wsl --install` again is a
            # no-op.  Say what's actually missing instead.
            Write-Host "  A previous run already installed WSL2, but Windows has NOT" -ForegroundColor Yellow
            Write-Host "  been restarted since.  WSL2 cannot finish setup until the"  -ForegroundColor Yellow
            Write-Host "  computer restarts (use Restart, not Shut down)."            -ForegroundColor Yellow
            $needsReboot = $true
            Write-SKIP "WSL2 + Ubuntu (waiting on a Windows restart)"
        } else {
            # User already approved the install plan, which listed "WSL2 + Ubuntu"
            # as required.  Just install it - asking again would be a useless
            # confirmation that, if declined, leaves nothing to install.
            Write-Host "  Installing WSL2 + Ubuntu (this may take several minutes)..." -ForegroundColor Cyan
            $plan = Get-WslInstallPlan
            $wslInstallArgs = $plan.InstallArgs
            & wsl $wslInstallArgs
            $needsReboot = $true
            Write-Installed "WSL2 + Ubuntu (restart required)"
            # Remember which boot session did this, so a pre-restart re-run
            # can tell the user the restart is the missing step.
            try {
                New-Item -ItemType Directory -Force `
                    (Split-Path -Parent $script:RestartMarker) | Out-Null
                Set-Content -LiteralPath $script:RestartMarker -Value $bootId
            } catch {}
        }
    }

    Write-Step "Checking for an apt-based WSL distro..."
    if ($wslAvailable -and (Test-WslHasApt)) {
        $ubuntuFound = $true
        Write-OK "Ubuntu / apt-based distro"
    }

    if (-not $ubuntuFound -and $wslAvailable -and -not $needsReboot -and
        (Test-VirtualizationDisabled)) {
        # `wsl --status` answers without booting anything (registry-backed),
        # but REGISTERING a distro boots the WSL2 utility VM - exactly what
        # firmware-disabled virtualization kills with 0x80370102.  This is
        # the state the PAD-21 machine retried across three releases.
        Write-VirtualizationBanner
        Write-FAIL "Ubuntu (virtualization disabled in BIOS/UEFI)"
    } elseif (-not $ubuntuFound -and $wslAvailable -and -not $needsReboot) {
        # No usable distro yet - install Ubuntu directly.
        # We let wsl write its output to the console directly (no capture)
        # because PowerShell 5.1's pipeline mangles its UTF-16LE output -
        # and if this fails, the user needs to see wsl's own error text.
        $plan = Get-WslInstallPlan
        Write-Host "  Installing Ubuntu into WSL (this may take a few minutes)..." -ForegroundColor Cyan
        if (-not $plan.NoLaunch) {
            # This wsl.exe launches Ubuntu's first-run setup itself (its
            # --install has no --no-launch).  Warn before the window opens.
            Write-Host "  Ubuntu may open its first-time setup when the download finishes." -ForegroundColor Yellow
            Write-Host "  If it asks for a UNIX username/password, pick anything you like."  -ForegroundColor Yellow
        }
        $wslInstallArgs = $plan.InstallArgs
        & wsl $wslInstallArgs
        $installExit = $LASTEXITCODE

        # Don't trust the install exit code (ERROR_ALREADY_EXISTS shows
        # up as a non-zero exit but means "already there, all good").
        # Re-test the actual capability we need.
        Start-Sleep -Seconds 2

        if (-not (Test-WslHasApt) -and $installExit -ne 0 -and $plan.WebDownload) {
            # A broken / blocked / signed-out Microsoft Store is the other
            # common way this install dies; --web-download fetches the
            # distro from Microsoft's CDN instead of the Store.
            Write-Host ("  wsl --install exited with code {0} - retrying with --web-download (skips the Microsoft Store)..." -f $installExit) -ForegroundColor Cyan
            $wslRetryArgs = $plan.InstallArgs + "--web-download"
            & wsl $wslRetryArgs
            $installExit = $LASTEXITCODE
            Start-Sleep -Seconds 2
        }

        if (Test-WslHasApt) {
            $ubuntuFound = $true
            Write-Installed "Ubuntu / apt-based distro"
        } elseif ($installExit -eq 0 -and -not $plan.NoLaunch) {
            # Install succeeded, but this wsl.exe hands registration to
            # Ubuntu's own first-run window - apt only answers once the
            # user finishes creating their UNIX account there.
            Write-Host "  Finish Ubuntu's first-time setup in its own window (create the" -ForegroundColor Yellow
            Write-Host "  username/password it asks for and wait for the green prompt)."  -ForegroundColor Yellow
            Read-Host "  Then come back here and press Enter to continue (also fine if no window appeared)"
            $ubuntuFound = $true
            if (Test-WslHasApt) {
                Write-Installed "Ubuntu / apt-based distro"
            } else {
                Write-Installed "Ubuntu (queued; first boot may still be initializing)"
            }
        } elseif ($installExit -eq 0) {
            # Fresh install + first-boot may still be initializing;
            # trust wsl's success signal.
            $ubuntuFound = $true
            Write-Installed "Ubuntu (queued; first boot may still be initializing)"
        } else {
            # Nothing worked.  wsl.exe printed its own error text above -
            # point at it, and leave routes that don't need this script.
            Write-Host ("  Ubuntu could not be installed automatically (wsl --install exit {0})." -f $installExit) -ForegroundColor Red
            Write-Host "  The error text above, from wsl.exe itself, says why.  Manual routes:" -ForegroundColor Yellow
            Write-Host "    1. In an admin PowerShell window run:   wsl --install -d Ubuntu"    -ForegroundColor Yellow
            Write-Host "       Create the username/password it asks for, type exit at the"      -ForegroundColor Yellow
            Write-Host "       Ubuntu prompt, then re-run this installer."                      -ForegroundColor Yellow
            Write-Host "    2. Or install 'Ubuntu' from the Microsoft Store app, launch it"     -ForegroundColor Yellow
            Write-Host "       once to finish its setup, then re-run this installer."           -ForegroundColor Yellow
            Write-FAIL ("Ubuntu (wsl --install exit {0}; manual: wsl --install -d Ubuntu)" -f $installExit)
        }
    } elseif ($needsReboot -and -not $ubuntuFound) {
        Write-SKIP "Ubuntu (will install after the Windows restart)"
    } elseif (-not $wslAvailable) {
        Write-SKIP "Ubuntu (WSL2 not available yet)"
    }

    # --- Is that distro WSL 2? -------------------------------------------
    # Only asked when something in the plan loop-mounts an image (Stern's
    # file growth, every JJP flow): those are the features WSL 1 cannot do
    # at all, and the ONLY fix is converting the distro.  Reporting the
    # tools green here while the app reported WSL2 missing is the loop this
    # check exists to break (PAD-73).
    $loopNeeded = @($wslPlan | Where-Object { $_.probe -eq "losetup" }).Count -gt 0
    if ($loopNeeded -and $wslAvailable -and $ubuntuFound) {
        Write-Step "Checking the WSL version of the default distro..."
        $def = Get-WslDefaultDistro
        if ($null -eq $def) {
            Write-Host "  Could not read 'wsl -l -v' - skipping the version check." -ForegroundColor Yellow
        } elseif ($def.Version -ge 2) {
            Write-OK ("WSL 2 (default distro: {0})" -f $def.Name)
        } else {
            $dn = $def.Name
            Write-Host ""
            Write-Host "  ============================================================" -ForegroundColor Yellow
            Write-Host ("  '{0}' IS REGISTERED AS WSL 1" -f $dn)                        -ForegroundColor Yellow
            Write-Host "  ============================================================" -ForegroundColor Yellow
            Write-Host "  WSL 1 has no loop devices, so it cannot mount a card or game" -ForegroundColor Yellow
            Write-Host "  image no matter which packages are installed.  This is why"   -ForegroundColor Yellow
            Write-Host "  the app keeps reporting WSL2 as missing while this installer" -ForegroundColor Yellow
            Write-Host "  reports everything as already installed.  Converting the"     -ForegroundColor Yellow
            Write-Host "  distro is the fix - nothing needs reinstalling."               -ForegroundColor Yellow
            Write-Host ("  Manual command:   wsl --set-version {0} 2" -f $dn)           -ForegroundColor Yellow
            Write-Host ""
            Write-Host "  The conversion rewrites the distro's disk and can run for"    -ForegroundColor Gray
            Write-Host "  several minutes.  Close anything using WSL before saying yes." -ForegroundColor Gray
            $ans = Read-Host ("  Convert {0} to WSL 2 now? (y/N)" -f $dn)
            if ($ans -match '^\s*y') {
                Write-Host "  Shutting WSL down..." -ForegroundColor Cyan
                & wsl --shutdown
                Write-Host ("  Converting {0} - do not close this window..." -f $dn) -ForegroundColor Cyan
                & wsl --set-version $dn 2
                $after = Get-WslDefaultDistro
                if ($after -and $after.Version -ge 2) {
                    Write-Installed ("WSL 2 (converted {0})" -f $dn)
                } else {
                    Write-Host "  The conversion did not finish.  wsl.exe's own error text is above." -ForegroundColor Red
                    Write-FAIL ("WSL 2 (conversion of {0} did not complete; manual: wsl --set-version {0} 2)" -f $dn)
                }
            } else {
                Write-FAIL ("WSL 2 (default distro {0} is WSL 1; run: wsl --set-version {0} 2)" -f $dn)
            }
        }
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

        # A package with a probeCmd is tested by running that command
        # instead of a PATH lookup — some packages (gcc) are on PATH while
        # still being unusable, so "is the binary there" is the wrong test.
        function Test-WslPkg($p) {
            try {
                if ($p.probeCmd) {
                    wsl -u root -- bash -c "$($p.probeCmd)" 2>&1 | Out-Null
                } else {
                    wsl -u root -- which $p.probe 2>&1 | Out-Null
                }
                return ($LASTEXITCODE -eq 0)
            } catch {
                return $false
            }
        }

        foreach ($p in $wslPlan) {
            Write-Step ("Checking {0} in WSL (for: {1})" -f $p.label, ($p.for -join ", "))
            $found = Test-WslPkg $p
            if ($found) { Write-OK $p.label }

            if (-not $found) {
                Write-Host ("  Installing {0}..." -f $p.label) -ForegroundColor Cyan
                $cmd = "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq " + $p.pkg
                wsl -u root -- bash -c $cmd 2>&1 | ForEach-Object { Write-Host "    $_" }
                if (Test-WslPkg $p) { Write-Installed $p.label }
                else                { Write-FAIL $p.label }
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
    Write-Host "  A RESTART IS REQUIRED to finish WSL2 setup."                -ForegroundColor Yellow
    Write-Host "  (Use Restart - with Fast Startup, Shut down is not the"     -ForegroundColor Yellow
    Write-Host "  same thing.)  After Windows restarts, open the Start Menu"  -ForegroundColor Yellow
    Write-Host "  and run:"                                                   -ForegroundColor Yellow
    Write-Host ""
    Write-Host "      Pinball Asset Decryptor  >  Install Prerequisites"      -ForegroundColor White
    Write-Host ""
    Write-Host "  to install the remaining WSL packages.  (Re-running the"    -ForegroundColor Yellow
    Write-Host "  setup .exe with 'Install prerequisites' ticked works too.)" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Yellow
    $reboot = Read-Host "  Restart now? (y/n)"
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
