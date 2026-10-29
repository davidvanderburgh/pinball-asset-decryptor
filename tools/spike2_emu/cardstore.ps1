<#
cardstore.ps1 - the SHARED CARD STORE: one ext4 disk file on the NVMe, attached to the WSL VM by name so EVERY
distro sees it at /mnt/wsl/cards, where cardmount.sh keeps its card cache (PAD-651).

    powershell -ExecutionPolicy Bypass -File cardstore.ps1 create [-SizeGB 400] [-Path <vhdx>]
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 mount [-NoFill]       (idempotent; the logon task runs it)
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 fill                  (top the library up, in the background)
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 task                  (register / repoint the logon task)
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 status

The file is %LOCALAPPDATA%\pinball_decryptor\data\pad-cards.vhdx, beside the app's work disk (pad-data.vhdx,
core/rigdata.py) and made the same way: diskpart makes an expandable VHDX and `wsl --mount --vhd` attaches it, both
UNELEVATED (measured by rigdata.py on Windows 11 Home - no administrator, no Hyper-V module); the distro formats it
ext4 after a bare attach, then it comes back by name. The app attaches it at every rig start (rigdata.ensure_cards),
and the logon task "PAD card store" attaches it after a reboot for sessions that run the rig without the app.

WHY. A Spike 2 card on any Windows drive boots through 9p under fuse2fs (79-130 s to attract) against 23 s from a
copy on a WSL ext4 disk, so every sweep copied its cards into a cache first - a cache per distro (Ubuntu's, the
app's runtime, the app's data disk), each too small for the library, so a 78-build sweep re-copied most of it every
pass off a spinning disk, and two tickets in two distros copied the same card twice (2026-10-20, measured in
docs/plans/card_store.md). The newest build of every title (~320 GB of used blocks) is pre-cached once
(precache.sh), an old per-distro cache is moved in (cachemigrate.sh), and D: is never read during a sweep again.

PERMANENT (PAD-727). Four days later 37 of those newest builds had been evicted by older versions and custom builds
booted on purpose, and a 53-build sweep copied them off D: again. cardmount.sh now never evicts an entry whose image
is the library's (cache_pinned), and every attach at logon tops the library up in the background (`fill`: precache.sh,
seconds when nothing is new, a copy for a new image dropped into the folder), so the store holds every newest build
for good. `status` says how many of them it holds.
#>
param(
    [Parameter(Position = 0)] [ValidateSet('create', 'mount', 'fill', 'status', 'task')] [string] $Cmd = 'status',
    [int] $SizeGB = 400,
    [string] $Path = '',
    [string] $Distro = 'Ubuntu',
    # the copy of this script the logon task runs: the main checkout's, which outlives a ticket's worktree
    [string] $TaskScript = '',
    [switch] $NoFill
)
$ErrorActionPreference = 'Stop'
if (-not $Path) {
    # where the app keeps its disks: moved off C: by Manage disk space > Move to another drive (PAD-819,
    # core/wsl_place.py), else beside the app's other state under LOCALAPPDATA
    $Root = Join-Path $env:LOCALAPPDATA 'pinball_decryptor'
    $Place = Join-Path $Root 'wsl_place.json'
    if (Test-Path $Place) {
        try { $saved = (Get-Content $Place -Raw | ConvertFrom-Json).root; if ($saved) { $Root = $saved } } catch { }
    }
    $Path = Join-Path $Root 'data\pad-cards.vhdx'
}
$Name = 'cards'
$MountPoint = "/mnt/wsl/$Name"

function Say($t) { Write-Host $t }
function Wsl([string[]] $a) { $o = & wsl.exe @a 2>&1 | ForEach-Object { "$_" -replace "`0", '' }; return ($o -join "`n").Trim() }
function WslRoot($d, $cmd) { & wsl.exe -d $d -u root -- bash -c $cmd 2>&1 | ForEach-Object { "$_" -replace "`0", '' } }
function Mounted($d) { return ((WslRoot $d "mountpoint -q $MountPoint && echo yes || echo no") -join '') -match 'yes' }
# The rig scripts beside this one, as the distro spells them, and the commands that run them as root for the
# desktop user (padpath.sh finds the rig's home from $HOME). One definition for `fill` and `status`.
# (forward slashes: wsl.exe hands its command line to a shell, which eats backslashes)
function RigDir() { return (Wsl @('-d', $Distro, '--', 'wslpath', '-u', ($PSScriptRoot -replace '\\', '/'))) }
$AsUser = 'export HOME=$(getent passwd 1000 | cut -d: -f6);'
$Library = '/mnt/d/Pinball/images/Stern/spike2'
function AttachByName() {
    $o = Wsl @('--mount', $Path, '--vhd', '--name', $Name)
    if ($LASTEXITCODE -ne 0) { throw "wsl --mount --name $Name failed: $o" }
}

switch ($Cmd) {
    'status' {
        if (Test-Path $Path) { Say "$Path  $([math]::Round((Get-Item $Path).Length / 1GB, 1)) GB on disk" }
        else { Say "$Path  (no disk file: cardstore.ps1 create)" }
        foreach ($d in @($Distro, 'PAD-Runtime')) {
            if (Mounted $d) {
                Say "$d  mounted at $MountPoint"
                WslRoot $d "df -h $MountPoint | tail -1; du -sh $MountPoint/cardcache 2>/dev/null; ls $MountPoint/cardcache/*.raw 2>/dev/null | wc -l | sed 's/^/cards cached: /'" | ForEach-Object { Say "  $_" }
                if ($d -eq $Distro) {
                    # the library's newest builds held for good (cardmount.sh's `pinned` lines) against its images
                    # (counted here: a bash -c line with its own quotes does not survive PowerShell 5.1's native
                    # argument passing)
                    $held = @(WslRoot $d "$AsUser bash '$(RigDir)/cardmount.sh' --cache-list" | Where-Object { $_ -like "pinned`t*" }).Count
                    $all = @(WslRoot $d "ls $Library/*.raw" | Where-Object { $_ -like '*.raw' }).Count
                    Say "  library: $held of $all newest builds held, never evicted"
                }
            } else { Say "$d  not mounted" }
        }
        $entry = Join-Path ([Environment]::GetFolderPath('Startup')) 'PAD card store.cmd'
        if (Test-Path $entry) { Say "logon entry: $entry"; Get-Content $entry | Select-Object -Last 1 | ForEach-Object { Say "  $_" } }
        else { Say "logon entry: none (cardstore.ps1 task)" }
    }
    'mount' {
        if (Mounted $Distro) { Say "already mounted at $MountPoint"; exit 0 }
        if (-not (Test-Path $Path)) { throw "$Path does not exist: cardstore.ps1 create" }
        AttachByName
        Start-Sleep 2
        if (-not (Mounted $Distro)) { throw "attached, but $MountPoint is not a mount in $Distro" }
        Say "mounted $Path at $MountPoint"
        if (-not $NoFill) { & $PSCommandPath fill -Path $Path -Distro $Distro }
    }
    'fill' {
        if (-not (Mounted $Distro)) { throw "$MountPoint is not mounted: cardstore.ps1 mount" }
        # Detached and hidden: a new image is a copy of minutes, under the machine's one copy lock, so a sweep that
        # starts meanwhile waits its turn for D: rather than seeking against it. The log is on the store itself.
        $log = "$MountPoint/precache.log"
        Start-Process -WindowStyle Hidden -FilePath 'wsl.exe' -ArgumentList @('-d', $Distro, '-u', 'root', '--',
            'bash', '-c', "`"$AsUser bash '$(RigDir)/precache.sh' > $log 2>&1`"")
        Say "topping the library up in the background ($Distro`:$log)"
    }
    'task' {
        if (-not $TaskScript) {
            $main = Join-Path $env:USERPROFILE 'Documents\development\pinball-asset-decryptor\tools\spike2_emu\cardstore.ps1'
            $TaskScript = if (Test-Path $main) { $main } else { $PSCommandPath }
        }
        # A Startup-folder entry, not a scheduled task: `schtasks /Create /SC ONLOGON` answers "Access is denied"
        # unelevated (measured 2026-10-20), and the attach itself needs no administrator - so the one thing that
        # needs none either is the way pad-triage autostarts too (a shortcut in shell:startup)
        # ($entry, not $cmd: PowerShell variables are case-insensitive and $Cmd is the validated parameter)
        $entry = Join-Path ([Environment]::GetFolderPath('Startup')) 'PAD card store.cmd'
        @("@echo off", "rem PAD card store (PAD-651): attach the shared Spike 2 card cache to WSL at logon",
          "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$TaskScript`" mount -Path `"$Path`"") |
            Set-Content -Path $entry -Encoding ascii
        Say "logon entry $entry runs: $TaskScript mount -Path $Path"
    }
    'create' {
        if (Test-Path $Path) { throw "$Path exists already - cardstore.ps1 mount" }
        $dir = Split-Path $Path
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
        $before = @((WslRoot $Distro "lsblk -dno NAME") | Where-Object { $_ })
        Say "creating $Path ($SizeGB GB maximum, grows as used)"
        $s = Join-Path $env:TEMP 'cardstore_diskpart.txt'
        "create vdisk file=`"$Path`" maximum=$($SizeGB * 1024) type=expandable" | Set-Content $s -Encoding ascii
        $out = diskpart /s $s 2>&1
        if ($LASTEXITCODE -ne 0) { throw "diskpart: $($out -join ' | ')" }
        Say "attaching it bare and formatting it ext4 (label $Name) in $Distro"
        $o = Wsl @('--mount', $Path, '--vhd', '--bare')
        if ($LASTEXITCODE -ne 0) { throw "wsl --mount --bare failed: $o" }
        try {
            Start-Sleep 2
            $after = @((WslRoot $Distro "lsblk -dno NAME") | Where-Object { $_ })
            $new = @($after | Where-Object { $before -notcontains $_ })
            if ($new.Count -ne 1) { throw "could not tell the new block device apart (before: $before; after: $after) - nothing formatted" }
            $dev = "/dev/$($new[0])"
            # rigdata.py's flags: one inode per MB (thousands of big files, not millions of small ones: the default
            # inode tables alone would materialise ~7 GB of the file), a 64 MB journal, no reserved blocks
            WslRoot $Distro "PATH=/usr/sbin:/sbin:`$PATH mkfs.ext4 -q -F -L $Name -i 1048576 -J size=64 -m 0 -E lazy_itable_init=1,lazy_journal_init=1 $dev && echo formatted" | ForEach-Object { Say "  $_" }
        } finally {
            Wsl @('--unmount', $Path) | Out-Null
        }
        AttachByName
        Start-Sleep 2
        if (-not (Mounted $Distro)) { throw "$MountPoint is not a mount in $Distro after the attach" }
        WslRoot $Distro "mkdir -p $MountPoint/cardcache && chown 1000:1000 $MountPoint/cardcache && chmod 1777 $MountPoint $MountPoint/cardcache && df -h $MountPoint | tail -1" | ForEach-Object { Say "  $_" }
        & $PSCommandPath task -Path $Path -TaskScript $TaskScript
        Say "done: $MountPoint/cardcache is the card cache for every distro (cardmount.sh). Fill it: precache.sh; an old cache: cachemigrate.sh"
    }
}
