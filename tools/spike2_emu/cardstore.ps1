<#
cardstore.ps1 - the SHARED CARD STORE: one ext4 disk file on the NVMe, mounted into every WSL distro at
/mnt/wsl/cards, where cardmount.sh keeps its card cache (PAD-651).

    powershell -ExecutionPolicy Bypass -File cardstore.ps1 create [-SizeGB 400] [-Path C:\wsl\cards.vhdx]
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 mount                 (idempotent; what the logon task runs)
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 status

WHY. A Spike 2 card on any Windows drive boots through 9p under fuse2fs (79-130 s to attract) against 23 s from a
copy on a WSL ext4 disk, so every sweep copied its cards into a cache first - a cache per distro (Ubuntu's, the
app's runtime, the app's data disk), each too small for the library, so a 78-build sweep re-copied most of it every
pass off a spinning disk, and two tickets in two distros copied the same card twice (2026-10-20, measured in
docs/plans/game_speed.md and rig_slots.md). `wsl --mount --vhd ... --name cards` attaches one disk file to the WSL
VM and every distro sees it at /mnt/wsl/cards; cardmount.sh prefers /mnt/wsl/cards/cardcache when it is there. The
newest build of every title (56 images, ~320 GB of used blocks) is pre-cached once (precache.sh) and D: is never
read during a sweep again.

HOW. `wsl --mount` and diskpart need administrator rights, so this script runs its disk steps in an elevated child
(Start-Process -Verb RunAs, silent on David's PC) and everything that touches a distro's files unelevated, as the
user (an elevated rig step poisons the WSL home). A mount does not survive a reboot: `create` registers a logon
task "PAD card store" that runs `mount` with highest privileges.

create:  diskpart makes an expandable VHDX (grows as used); it is attached bare, Ubuntu formats it ext4 (label
         cards), it is detached and attached again by name; /mnt/wsl/cards/cardcache is made writable for the
         desktop user; the logon task is registered. Refused when the file exists (mount it instead).
mount:   attaches the file by name if /mnt/wsl/cards is not already a mount in Ubuntu.
status:  the file's size on disk, whether it is mounted, and the cache's use.
#>
param(
    [Parameter(Position = 0)] [ValidateSet('create', 'mount', 'status', 'task', 'elevated')] [string] $Cmd = 'status',
    [int] $SizeGB = 400,
    [string] $Path = 'C:\wsl\cards.vhdx',
    [string] $Distro = 'Ubuntu',
    [string] $Step = '',
    # the copy of this script the logon task runs (the main checkout's, which outlives a ticket's worktree)
    [string] $TaskScript = ''
)
$ErrorActionPreference = 'Stop'
$Name = 'cards'
$MountPoint = "/mnt/wsl/$Name"

function Say($t) { Write-Host $t }
function WslRoot($d, $cmd) { & wsl.exe -d $d -u root -- bash -c $cmd 2>&1 | ForEach-Object { "$_" -replace "`0", '' } }
function Mounted($d) {
    $out = WslRoot $d "mountpoint -q $MountPoint && echo yes || echo no"
    return ($out -join '') -match 'yes'
}
function Elevate($step) {
    $args2 = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", 'elevated',
               '-Step', $step, '-Path', "`"$Path`"", '-SizeGB', $SizeGB, '-Distro', $Distro, '-TaskScript', "`"$TaskScript`"")
    $p = Start-Process powershell.exe -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList $args2 -PassThru
    if ($p.ExitCode -ne 0) { throw "elevated step '$step' failed (exit $($p.ExitCode)); see $env:TEMP\cardstore_elevated.log" }
}

if ($Cmd -eq 'elevated') {
    # ---- the elevated half: disk steps only, never a distro's files ----
    $log = Join-Path $env:TEMP 'cardstore_elevated.log'
    try {
        switch ($Step) {
            'create' {
                $dir = Split-Path $Path
                if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
                $s = Join-Path $env:TEMP 'cardstore_diskpart.txt'
                "create vdisk file=`"$Path`" maximum=$($SizeGB * 1024) type=expandable" | Set-Content $s -Encoding ascii
                $out = diskpart /s $s 2>&1
                Add-Content $log "$(Get-Date -Format HH:mm:ss) diskpart create: $($out -join ' | ')"
                if ($LASTEXITCODE -ne 0) { exit 3 }
                & wsl.exe --mount $Path --vhd --bare 2>&1 | ForEach-Object { Add-Content $log ("mount --bare: " + ("$_" -replace "`0", '')) }
                if ($LASTEXITCODE -ne 0) { exit 4 }
            }
            'remount' {
                & wsl.exe --unmount $Path 2>&1 | ForEach-Object { Add-Content $log ("unmount: " + ("$_" -replace "`0", '')) }
                & wsl.exe --mount $Path --vhd --name $Name 2>&1 | ForEach-Object { Add-Content $log ("mount --name: " + ("$_" -replace "`0", '')) }
                if ($LASTEXITCODE -ne 0) { exit 5 }
            }
            'mount' {
                & wsl.exe --mount $Path --vhd --name $Name 2>&1 | ForEach-Object { Add-Content $log ("mount: " + ("$_" -replace "`0", '')) }
                if ($LASTEXITCODE -ne 0) { exit 5 }
            }
            'task' {
                # one argument for /TR, its inner quotes escaped for schtasks (\"), or schtasks reads "mount"
                # as an option of its own
                $ps = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"' + $TaskScript + '\" mount -Path \"' + $Path + '\"'
                $out = schtasks /Create /F /TN 'PAD card store' /SC ONLOGON /RL HIGHEST /TR $ps 2>&1
                Add-Content $log ("schtasks: " + ($out -join ' | '))
                if ($LASTEXITCODE -ne 0) { exit 6 }
            }
        }
        exit 0
    } catch {
        Add-Content $log "ERROR: $_"
        exit 9
    }
}

switch ($Cmd) {
    'status' {
        if (Test-Path $Path) {
            $gb = [math]::Round((Get-Item $Path).Length / 1GB, 1)
            Say "$Path  $gb GB on disk"
        } else { Say "$Path  (no disk file: cardstore.ps1 create)" }
        foreach ($d in @($Distro, 'PAD-Runtime')) {
            if (Mounted $d) {
                Say "$d  mounted at $MountPoint"
                WslRoot $d "df -h $MountPoint | tail -1; du -sh $MountPoint/cardcache 2>/dev/null; ls $MountPoint/cardcache/*.raw 2>/dev/null | wc -l | sed 's/^/cards cached: /'" | ForEach-Object { Say "  $_" }
            } else { Say "$d  not mounted" }
        }
    }
    'task' {
        if (-not $TaskScript) {
            $main = Join-Path $env:USERPROFILE 'Documents\development\pinball-asset-decryptor\tools\spike2_emu\cardstore.ps1'
            $TaskScript = if (Test-Path $main) { $main } else { $PSCommandPath }
        }
        Elevate 'task'
        Say "logon task 'PAD card store' registered: $(schtasks /Query /TN 'PAD card store' /FO LIST 2>&1 | Select-String 'Status|Next Run' | ForEach-Object { $_.Line.Trim() })"
    }
    'mount' {
        if (Mounted $Distro) { Say "already mounted at $MountPoint"; exit 0 }
        if (-not (Test-Path $Path)) { throw "$Path does not exist: cardstore.ps1 create" }
        Elevate 'mount'
        Start-Sleep 2
        if (-not (Mounted $Distro)) { throw "mounted, but $MountPoint is not a mount in $Distro" }
        Say "mounted $Path at $MountPoint"
    }
    'create' {
        if (Test-Path $Path) { throw "$Path exists already - cardstore.ps1 mount" }
        $before = (WslRoot $Distro "lsblk -dno NAME") -join ' '
        Say "creating $Path ($SizeGB GB, grows as used) and attaching it bare"
        Elevate 'create'
        Start-Sleep 2
        $after = (WslRoot $Distro "lsblk -dno NAME") -join ' '
        $new = @($after.Split(' ') | Where-Object { $_ -and ($before.Split(' ') -notcontains $_) })
        if ($new.Count -ne 1) { throw "could not tell the new block device apart (before: $before; after: $after)" }
        $dev = "/dev/$($new[0])"
        Say "formatting $dev as ext4 (label $Name) in $Distro"
        WslRoot $Distro "mkfs.ext4 -q -L $Name -m 0 $dev && echo formatted" | ForEach-Object { Say "  $_" }
        Say "attaching it by name"
        Elevate 'remount'
        Start-Sleep 2
        if (-not (Mounted $Distro)) { throw "$MountPoint is not a mount in $Distro after the remount" }
        WslRoot $Distro "mkdir -p $MountPoint/cardcache && chown 1000:1000 $MountPoint/cardcache && chmod 1777 $MountPoint $MountPoint/cardcache && df -h $MountPoint | tail -1" | ForEach-Object { Say "  $_" }
        Say "registering the logon task 'PAD card store' (re-mounts it after a reboot)"
        if (-not $TaskScript) {
            $main = Join-Path $env:USERPROFILE 'Documents\development\pinball-asset-decryptor\tools\spike2_emu\cardstore.ps1'
            $TaskScript = if (Test-Path $main) { $main } else { $PSCommandPath }
        }
        Elevate 'task'
        Say "done: $MountPoint/cardcache is the card cache for every distro (cardmount.sh). Fill it: precache.sh"
    }
}
