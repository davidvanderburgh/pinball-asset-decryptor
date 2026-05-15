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
      - Host-side (winget on Windows): Gpg4win, ffmpeg-on-host
        (Spooky uses these directly; BOF and JJP use WSL versions
        through the executor).

    Safe to re-run: anything already present is skipped.

.NOTES
    Must run as Administrator (WSL install + admin-scope winget).
#>

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
            @{ command="gpg";    winget="GnuPG.Gpg4win"; label="Gpg4win"; manualUrl="https://www.gpg4win.org/download.html"; reason="UM/H78 .pkg decryption + Beetlejuice signing" }
            @{ command="ffmpeg"; winget="Gyan.FFmpeg";   label="ffmpeg";  manualUrl="https://www.gyan.dev/ffmpeg/builds/";    reason="Audio resampling on Write + P3 VID-to-MP4 conversion" }
        )
    }

    "Barrels of Fun" = @{
        Description  = "Labyrinth, Dune, Winchester (.fun files)"
        WslPackages  = @(
            @{ probe="gpg"; pkg="gnupg"; label="gnupg (in WSL)"; reason=".fun GPG decryption / re-encryption" }
            @{ probe="tar"; pkg="tar";   label="tar (in WSL)";   reason="Archive packing/unpacking" }
        )
        HostPackages = @()
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
}

$wslPlan  = @($wslByProbe.Values)
$hostPlan = @($hostByCmd.Values)

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
    Write-Host "  WSL-side (inside Ubuntu):"
    foreach ($p in $wslPlan) {
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
                winget install --id $p.winget --silent --accept-package-agreements --accept-source-agreements 2>&1 |
                    ForEach-Object { Write-Host "    $_" }
                # Re-check (winget puts things on PATH but the current shell may not see them
                # immediately; we attempt the probe and fall back to a manual-install hint)
                try {
                    & $p.command --version 2>&1 | Out-Null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Installed $p.label
                    } else {
                        Write-Host ("  Installed but not yet on PATH - open a new terminal and re-run this script to verify.") -ForegroundColor Yellow
                        Write-SKIP ("{0} (installed; verify in new shell)" -f $p.label)
                    }
                } catch {
                    Write-SKIP ("{0} (installed; verify in new shell)" -f $p.label)
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
        $install = Read-Host "  WSL2 not detected. Install WSL2 + Ubuntu now? (y/n)"
        if ($install -eq 'y') {
            Write-Host "  Installing WSL2 with Ubuntu (this may take several minutes)..." -ForegroundColor Cyan
            wsl --install -d Ubuntu 2>&1 | ForEach-Object { Write-Host "    $_" }
            $needsReboot = $true
            Write-Installed "WSL2 + Ubuntu (reboot required)"
        } else {
            Write-SKIP "WSL2"
        }
    }

    Write-Step "Checking Ubuntu distribution..."
    if ($wslAvailable) {
        try {
            $distros = wsl --list --quiet 2>&1 | Out-String
            if ($distros -match 'Ubuntu') { $ubuntuFound = $true; Write-OK "Ubuntu" }
        } catch {}
    }
    if (-not $ubuntuFound -and $wslAvailable -and -not $needsReboot) {
        $install = Read-Host "  Install Ubuntu now? (y/n)"
        if ($install -eq 'y') {
            wsl --install -d Ubuntu 2>&1 | ForEach-Object { Write-Host "    $_" }
            if ($LASTEXITCODE -eq 0) { $ubuntuFound = $true; Write-Installed "Ubuntu" }
            else                     { Write-FAIL "Ubuntu (installation failed)" }
        } else {
            Write-SKIP "Ubuntu"
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
