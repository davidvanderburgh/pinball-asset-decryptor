<#
cardstore.ps1 - the SHARED CARD STORE: one ext4 disk file on the NVMe, attached to the WSL VM by name so EVERY
distro sees it at /mnt/wsl/cards, where cardmount.sh keeps its card cache (PAD-651).

    powershell -ExecutionPolicy Bypass -File cardstore.ps1 create [-SizeGB 400] [-Path <vhdx>]
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 mount                 (idempotent; the logon task runs it)
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
#>
param(
    [Parameter(Position = 0)] [ValidateSet('create', 'mount', 'status', 'task')] [string] $Cmd = 'status',
    [int] $SizeGB = 400,
    [string] $Path = (Join-Path $env:LOCALAPPDATA 'pinball_decryptor\data\pad-cards.vhdx'),
    [string] $Distro = 'Ubuntu',
    # the copy of this script the logon task runs: the main checkout's, which outlives a ticket's worktree
    [string] $TaskScript = ''
)
$ErrorActionPreference = 'Stop'
$Name = 'cards'
$MountPoint = "/mnt/wsl/$Name"

function Say($t) { Write-Host $t }
function Wsl([string[]] $a) { $o = & wsl.exe @a 2>&1 | ForEach-Object { "$_" -replace "`0", '' }; return ($o -join "`n").Trim() }
function WslRoot($d, $cmd) { & wsl.exe -d $d -u root -- bash -c $cmd 2>&1 | ForEach-Object { "$_" -replace "`0", '' } }
function Mounted($d) { return ((WslRoot $d "mountpoint -q $MountPoint && echo yes || echo no") -join '') -match 'yes' }
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
