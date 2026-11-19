<#
cardstore.ps1 - the SHARED CARD STORE: one ext4 disk file on the NVMe, attached to the WSL VM by name so EVERY
distro sees it at /mnt/wsl/cards, where cardmount.sh keeps its card cache (PAD-651).

    powershell -ExecutionPolicy Bypass -File cardstore.ps1 create [-SizeGB 400] [-Path <vhdx>]
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 mount [-NoFill]       (idempotent; the logon task runs it)
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 fill                  (top the library up, in the background)
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 task                  (register / repoint the logon task)
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 status
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 prune [-KeepDays 30] [-DryRun]   (PAD-966, below)
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 migrate [-SizeGB 400]  (PAD-1453: a new XFS store, filled while the old one works)
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 swap                   (PAD-1453: catch up, verify, put the XFS store in its place)
    powershell -ExecutionPolicy Bypass -File cardstore.ps1 dedupe [-DryRun]       (PAD-1453: share identical blocks; `fill` runs it after)

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

PRUNED (PAD-966). The copier makes room one entry at a time and only when a copy needs it, so a store nothing new
goes into keeps every dead copy for good: two weeks in, David's 590 GB store held 548 GB, 173 GB of it the library
and the rest copies no boot could use (30 stamped against themselves after their cache paths were booted as cards,
older versions, ticket scratch, superseded custom builds) - while 29 newest builds had been pushed out. `prune`
runs cardmount.sh --cache-prune: dead entries go, so does anything not the library's and not booted in -KeepDays
days (0: the library alone stays), never a card in use or being copied; then `fill` puts back any newest build that
is missing. -DryRun lists what would go and takes nothing. The space reaches Windows only when the VHDX is compacted
(fstrim does not shrink it; Manage disk space > Reclaim, with the store attached, or diskpart compact vdisk).

THE LIBRARY, ONCE (PAD-966). David: "I want to be storing ONE copy of a disk image since they are so large". The
library now lives on the store itself, /mnt/wsl/cards/library (Windows: \\wsl.localhost\<distro>\mnt\wsl\cards\library),
one compact file per card under its own name and mtime; a card there boots where it lies, and a boot of the raw in
the intake folder (D:\Pinball\images\Stern\spike2) is served from the library file, so the raws on D: are intake and
archive, not a working copy. `fill` is the intake (precache.sh): a new raw in the folder is taken in once, in the
background. Not on D: itself: a SATA hard disk gives five rigs 95 random reads a second between them, and a
330 GB sweep is 39+ minutes of its time against nothing from the NVMe (measured 2026-11-03).

SHARED BLOCKS (PAD-1453). David, 2026-11-19: "our pad storage on disk c has gotten way out of control". The store's
file was 550 GB on C: and held 431 GiB of data - of which only 189 GiB was unique, 4 KiB block by block: an LE card
and its Pro are the same OS, videos and sounds; a custom build or a ticket's scratch build is a library card with a
few files changed. zstd found 16% (H.264 and compressed audio); sharing finds 56%. So the store is XFS with reflink,
and storededupe.py has the kernel share every identical block (FIDEDUPERANGE: the kernel byte-compares under a lock,
so nothing that differs is ever merged; a write to a shared block is copied first, so no file can change another).
Files read exactly as before - boots, the copier and the clean-ups see no difference.
  `migrate` makes the XFS store beside the old one (pad-cards.xfs.vhdx, attached as /mnt/wsl/cards-new) and copies
  everything in, sharing as each file lands, so the new file grows only to the unique data. The old store keeps
  working meanwhile. `swap` (with no rig on the store) copies what changed since, byte-verifies every file, and
  puts the new file in the old one's place (the old one stays as pad-cards.ext4-old.vhdx until you delete it).
  `dedupe` shares what new cards brought; `fill` runs it after every intake, and it reads only files it has not seen.
The filesystem type is written beside the disk (<vhdx>.fstype), because `wsl --mount` assumes ext4 unless told.
#>
param(
    [Parameter(Position = 0)] [ValidateSet('create', 'mount', 'fill', 'status', 'task', 'prune', 'migrate', 'swap', 'dedupe')] [string] $Cmd = 'status',
    [int] $SizeGB = 400,
    # prune: entries not the library's and not booted this many days stay (0 = only the library stays)
    [int] $KeepDays = 30,
    [switch] $DryRun,
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
# (stderr is folded into stdout INSIDE bash: Windows PowerShell 5.1 under 'Stop' turns any stderr line of a native
# command into a terminating NativeCommandError - storexfs.sh's "fetching" line ended `migrate` that way)
function WslRoot($d, $cmd) { & wsl.exe -d $d -u root -- bash -c "{ $cmd ; } 2>&1" | ForEach-Object { "$_" -replace "`0", '' } }
function Mounted($d) { return ((WslRoot $d "mountpoint -q $MountPoint && echo yes || echo no") -join '') -match 'yes' }
# The rig scripts beside this one, as the distro spells them, and the commands that run them as root for the
# desktop user (padpath.sh finds the rig's home from $HOME). One definition for `fill` and `status`.
# (forward slashes: wsl.exe hands its command line to a shell, which eats backslashes)
function RigDir() { return (Wsl @('-d', $Distro, '--', 'wslpath', '-u', ($PSScriptRoot -replace '\\', '/'))) }
$AsUser = 'export HOME=$(getent passwd 1000 | cut -d: -f6);'
$Intake = '/mnt/d/Pinball/images/Stern/spike2'          # where downloads land; precache.sh takes them into the library
function FsType($vhdx) {
    $f = "$vhdx.fstype"
    if (Test-Path $f) { $t = (Get-Content $f -Raw).Trim(); if ($t -in @('ext4', 'xfs')) { return $t } }
    return 'ext4'
}
# Attach <vhdx> by name, as its own filesystem type (PAD-1453); a file moved without its .fstype gets the other type
# tried, the failed attach let go first (core/rigdata.attach_cards does the same).
function AttachAs($vhdx, $as) {
    $first = FsType $vhdx
    $errs = @()
    foreach ($t in @($first) + @(@('ext4', 'xfs') | Where-Object { $_ -ne $first })) {
        $o = Wsl @('--mount', $vhdx, '--vhd', '--name', $as, '--type', $t)
        if ($LASTEXITCODE -eq 0) { return }
        $errs += "${t}: $o"
        Wsl @('--unmount', $vhdx) | Out-Null
    }
    throw "wsl --mount --name $as failed: $($errs -join ' | ')"
}
function AttachByName() { AttachAs $Path $Name }
$NewPath = Join-Path (Split-Path $Path) 'pad-cards.xfs.vhdx'
$OldPath = Join-Path (Split-Path $Path) 'pad-cards.ext4-old.vhdx'
$NewMount = "/mnt/wsl/$Name-new"
function Py($d, $args_) { WslRoot $d "python3 -I '$(RigDir)/storededupe.py' $args_" }

switch ($Cmd) {
    'status' {
        if (Test-Path $Path) { Say "$Path  $([math]::Round((Get-Item $Path).Length / 1GB, 1)) GB on disk" }
        else { Say "$Path  (no disk file: cardstore.ps1 create)" }
        foreach ($d in @($Distro, 'PAD-Runtime')) {
            if (Mounted $d) {
                Say "$d  mounted at $MountPoint"
                WslRoot $d "df -h $MountPoint | tail -1; du -sh $MountPoint/library $MountPoint/cardcache 2>/dev/null; ls $MountPoint/cardcache/*.raw 2>/dev/null | wc -l | sed 's/^/cards cached: /'" | ForEach-Object { Say "  $_" }
                if ($d -eq $Distro) {
                    # the library on the store (PAD-966) against the intake folder; before the first intake the
                    # library is the intake folder and its newest builds are held in the cache (`pinned` lines)
                    # (counted here: a bash -c line with its own quotes does not survive PowerShell 5.1's native
                    # argument passing)
                    $lib = @(WslRoot $d "ls $MountPoint/library/*.raw" | Where-Object { $_ -like '*.raw' })
                    $all = @(WslRoot $d "ls $Intake/*.raw" | Where-Object { $_ -like '*.raw' })
                    if ($lib.Count -gt 0) {
                        $taken = @($all | Where-Object { $n = Split-Path $_ -Leaf; $lib | Where-Object { (Split-Path $_ -Leaf) -eq $n } }).Count
                        Say "  library: $($lib.Count) cards on the store ($taken of the $($all.Count) in the intake folder taken in)"
                    } else {
                        $held = @(WslRoot $d "$AsUser bash '$(RigDir)/cardmount.sh' --cache-list" | Where-Object { $_ -like "pinned`t*" }).Count
                        Say "  library: not on the store yet (fill takes it in); $held of $($all.Count) newest builds held in the cache"
                    }
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
        # then, on an XFS store, share what the new cards brought (PAD-1453; reads only files it has not seen)
        $dd = "[ `$(stat -f -c %T $MountPoint) = xfs ] && nice -n 10 python3 -I '$(RigDir)/storededupe.py' dedupe $MountPoint/library $MountPoint/cardcache $MountPoint/spike3 >> $log 2>&1"
        Start-Process -WindowStyle Hidden -FilePath 'wsl.exe' -ArgumentList @('-d', $Distro, '-u', 'root', '--',
            'bash', '-c', "`"$AsUser bash '$(RigDir)/precache.sh' > $log 2>&1; $dd`"")
        Say "topping the library up in the background ($Distro`:$log)"
    }
    'prune' {
        if (-not (Mounted $Distro)) { throw "$MountPoint is not mounted: cardstore.ps1 mount" }
        $opts = "--cache-prune --keep-days $KeepDays"
        if ($DryRun) { $opts += ' --dry' }
        $verb = if ($DryRun) { 'would take' } else { 'took' }
        foreach ($line in (WslRoot $Distro "$AsUser bash '$(RigDir)/cardmount.sh' $opts")) {
            $f = "$line" -split "`t"
            switch ($f[0]) {
                'prune'  { Say ('{0}  {1,7:N1} GB  {2}  ({3})' -f $verb, ([double]$f[3] / 1MB), $f[2], $f[1]) }
                'kept'   { Say ('kept        {0,7:N1} GB  {1}  ({2})' -f ([double]$f[3] / 1MB), $f[2], $f[1]) }
                'pruned' { Say ('{0} {1} entries, {2:N1} GB; {3} kept, {4:N1} GB' -f $verb, $f[1], ([double]$f[2] / 1MB), $f[3], ([double]$f[4] / 1MB)) }
                default  { Say $line }
            }
        }
        if (-not $DryRun) { & $PSCommandPath fill -Path $Path -Distro $Distro }
    }
    'dedupe' {
        if (-not (Mounted $Distro)) { throw "$MountPoint is not mounted: cardstore.ps1 mount" }
        if (((WslRoot $Distro "stat -f -c %T $MountPoint") -join '') -notmatch 'xfs') { throw "the store is not XFS yet: cardstore.ps1 migrate" }
        $opts = if ($DryRun) { 'dedupe --dry' } else { 'dedupe' }
        Py $Distro "$opts $MountPoint/library $MountPoint/cardcache $MountPoint/spike3" | ForEach-Object { Say $_ }
    }
    'migrate' {
        # A new XFS store beside the old one, filled while the old one keeps working (PAD-1453). Safe to run again:
        # it picks up where it stopped (files already there with their size and mtime are only indexed).
        if (-not (Mounted $Distro)) { throw "$MountPoint is not mounted: cardstore.ps1 mount" }
        if (((WslRoot $Distro "stat -f -c %T $MountPoint") -join '') -match 'xfs') { Say "the store is XFS already"; exit 0 }
        $rig = RigDir
        if (-not ((WslRoot $Distro "mountpoint -q $NewMount && echo yes") -join '' -match 'yes')) {
            # a file with no .fstype was never formatted (a run that stopped between diskpart and mkfs): make it again
            if ((Test-Path $NewPath) -and -not (Test-Path "$NewPath.fstype")) { Remove-Item $NewPath }
            if (-not (Test-Path $NewPath)) {
                # room: the unique data (44% of what David's store held, measured 2026-11-19) and a margin; the
                # copy itself also stops before the drive gets under 20 GB (storededupe.py --host-min-gb)
                $usedKB = [double]((WslRoot $Distro "df -k --output=used $MountPoint | tail -1") -join '').Trim()
                $want = [math]::Ceiling($usedKB * 1KB * 0.5 / 1GB) + 20
                $free = [math]::Floor((Get-PSDrive ((Split-Path $NewPath -Qualifier).TrimEnd(':'))).Free / 1GB)
                if ($free -lt $want) { throw "the new store may need up to $want GB and $(Split-Path $NewPath -Qualifier) has $free GB free" }
                Say "creating $NewPath ($SizeGB GB maximum, grows as used)"
                $s = Join-Path $env:TEMP 'cardstore_diskpart.txt'
                "create vdisk file=`"$NewPath`" maximum=$($SizeGB * 1024) type=expandable" | Set-Content $s -Encoding ascii
                $out = diskpart /s $s 2>&1
                if ($LASTEXITCODE -ne 0) { throw "diskpart: $($out -join ' | ')" }
                # diskpart can return (exit 0, no output) before the file is there: on 2026-11-19 the attach right
                # after it answered ERROR_FILE_NOT_FOUND. Wait for it.
                for ($i = 0; $i -lt 30 -and -not (Test-Path $NewPath); $i++) { Start-Sleep 1 }
                if (-not (Test-Path $NewPath)) { throw "diskpart did not make $NewPath ($($out -join ' | '))" }
                WslRoot $Distro "bash '$rig/storexfs.sh' tools" | ForEach-Object { Say "  $_" }
                $before = @((WslRoot $Distro "lsblk -dno NAME") | Where-Object { $_ })
                $o = Wsl @('--mount', $NewPath, '--vhd', '--bare')
                if ($LASTEXITCODE -ne 0) { throw "wsl --mount --bare failed: $o" }
                try {
                    Start-Sleep 2
                    $new = @(@((WslRoot $Distro "lsblk -dno NAME") | Where-Object { $_ }) | Where-Object { $before -notcontains $_ })
                    if ($new.Count -ne 1) { throw "could not tell the new block device apart - nothing formatted" }
                    WslRoot $Distro "bash '$rig/storexfs.sh' mkfs /dev/$($new[0])" | ForEach-Object { Say "  $_" }
                } finally {
                    Wsl @('--unmount', $NewPath) | Out-Null
                }
                'xfs' | Set-Content "$NewPath.fstype" -Encoding ascii
            }
            AttachAs $NewPath "$Name-new"
            Start-Sleep 2
            WslRoot $Distro "chmod 1777 $NewMount" | Out-Null
        }
        Say "copying $MountPoint into $NewMount, sharing blocks as each file lands (the old store keeps working)"
        $hostMnt = '/mnt/' + (Split-Path $NewPath -Qualifier).TrimEnd(':').ToLower()
        Py $Distro "ingest --host $hostMnt $MountPoint $NewMount" | ForEach-Object { Say $_ }
        WslRoot $Distro "df -h $MountPoint $NewMount" | ForEach-Object { Say "  $_" }
        Say "next: cardstore.ps1 swap (with no rig on the store)"
    }
    'swap' {
        if (-not ((WslRoot $Distro "mountpoint -q $NewMount && echo yes") -join '' -match 'yes')) { throw "$NewMount is not attached: cardstore.ps1 migrate first" }
        $busy = @(WslRoot $Distro "STORE=$MountPoint bash '$(RigDir)/storexfs.sh' busy" | Where-Object { $_ })
        if ($busy.Count) { throw "the store is in use - stop these first: $($busy -join '; ')" }
        Say "catching up what changed since migrate"
        $hostMnt = '/mnt/' + (Split-Path $Path -Qualifier).TrimEnd(':').ToLower()
        Py $Distro "ingest --delete --host $hostMnt $MountPoint $NewMount" | ForEach-Object { Say $_ }
        Say "byte-comparing every file"
        $v = @(Py $Distro "verify $MountPoint $NewMount")
        $v | ForEach-Object { Say $_ }
        if (-not ($v | Where-Object { $_ -match "^verify`t\d+`t0$" })) { throw "verify failed: the old store stays in place" }
        Wsl @('--unmount', $NewPath) | Out-Null
        Wsl @('--unmount', $Path) | Out-Null
        if (Test-Path $OldPath) { throw "$OldPath is there already: delete it first" }
        Move-Item $Path $OldPath
        if (Test-Path "$Path.fstype") { Move-Item "$Path.fstype" "$OldPath.fstype" }
        Move-Item $NewPath $Path
        Move-Item "$NewPath.fstype" "$Path.fstype"
        AttachByName
        Start-Sleep 2
        if (-not (Mounted $Distro)) { throw "$MountPoint is not a mount after the swap" }
        WslRoot $Distro "stat -f -c %T $MountPoint; df -h $MountPoint | tail -1" | ForEach-Object { Say "  $_" }
        Say "swapped: the XFS store is $Path. The old one is $OldPath ($([math]::Round((Get-Item $OldPath).Length / 1GB)) GB) - delete it once a boot works."
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
