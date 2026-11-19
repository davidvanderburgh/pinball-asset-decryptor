<#
padcompact.ps1 - hand the space freed inside PAD's virtual disks back to Windows, once a week, unattended (PAD-1453).

    powershell -ExecutionPolicy Bypass -File padcompact.ps1               (a run: does nothing unless due and idle)
    powershell -ExecutionPolicy Bypass -File padcompact.ps1 -Force        (now, if idle, whatever the date)
    powershell -ExecutionPolicy Bypass -File padcompact.ps1 -DryRun       (say what it would compact)
    powershell -ExecutionPolicy Bypass -File padcompact.ps1 -Register     (the daily 04:00 task that runs it)

WHY. David, 2026-11-19: "our pad storage on disk c has gotten way out of control". A WSL disk file only ever grows:
deleting a 9 GB scratch build inside Ubuntu frees nothing on C: (rigdata.py: `--set-sparse` is "currently disabled due
to potential data corruption"), so every clean-up - the space keeper's, the ticket sweep's, the card cache's cap -
stopped the growth and gave nothing back. Measured that day: Ubuntu's file 242 GB for 232 GB used, then 217 GB used
after the sweeps; the card store's file 580 GB for 365 GB used. Compacting is the only way back, and it needs WSL
down and an administrator, so it was a button nobody pressed.

WHAT. Each disk - the card store, the rigs' data disk, the app's Linux (PAD-Runtime), the machine's default distro -
is measured: its file's size against what its filesystem uses. If any holds -MinSlackGB (20) more than it uses, and
the last compaction is -EveryDays (7) old, and NOTHING IS RUNNING (no rig lease touched in 10 minutes, no process in
any distro tagged with a ticket, no emulator, no fuse2fs card mount), then: fstrim every mounted filesystem (so freed
blocks are unmapped and the compact can drop them), `wsl --shutdown`, `diskpart compact vdisk` each one with slack, and
attach the card store again. Busy: it says why and tries again tomorrow (the task runs daily; this decides).

Log: %LOCALAPPDATA%\pinball_decryptor\compact.log (before and after sizes). State: compact_state.json beside it.
#>
param(
    [switch] $Force,
    [switch] $DryRun,
    [switch] $Register,
    [int] $MinSlackGB = 20,
    [int] $EveryDays = 7,
    # only these disks, by name as the log calls them (card store, rigs' data disk, PAD-Runtime, <default distro>)
    [string[]] $Only = @()
)
$ErrorActionPreference = 'Stop'
# through -File a list arrives as ONE string ("Ubuntu,PAD-Runtime")
$Only = @($Only | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$Root = Join-Path $env:LOCALAPPDATA 'pinball_decryptor'
$Place = Join-Path $Root 'wsl_place.json'
$DataRoot = $Root
if (Test-Path $Place) { try { $s = (Get-Content $Place -Raw | ConvertFrom-Json).root; if ($s) { $DataRoot = $s } } catch { } }
$Log = Join-Path $Root 'compact.log'
$State = Join-Path $Root 'compact_state.json'
$TaskName = 'PAD weekly compact'

function Say($t) { $l = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $t"; Write-Host $l; Add-Content -Path $Log -Value $l -Encoding utf8 }
function Clean($o) { ($o | ForEach-Object { "$_" -replace "`0", '' }) }
# -e, not --: with -- wsl.exe runs the line through a shell of its own first, which expands every $var before bash
# sees it (the busy scan below read every process as "$p" = "" that way)
function WslIn($d, $cmd) { Clean (& wsl.exe -d $d -u root -e bash -c "{ $cmd ; } 2>&1") }
function IsAdmin { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }

if ($Register) {
    if (-not (IsAdmin)) {
        Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Register')
        exit 0
    }
    # the main checkout's copy, which outlives a ticket's worktree (pad-triage removes a closed ticket's): ALWAYS that
    # path when the checkout is there, even before this script reaches main - the task finds it once it lands
    $repo = Join-Path $env:USERPROFILE 'Documents\development\pinball-asset-decryptor'
    $main = Join-Path $repo 'tools\spike2_emu\padcompact.ps1'
    $script = if (Test-Path $repo) { $main } else { $PSCommandPath }
    $act = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
    $trg = New-ScheduledTaskTrigger -Daily -At 4am
    $set = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)
    $pri = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskName -Action $act -Trigger $trg -Settings $set -Principal $pri -Force | Out-Null
    Say "registered '$TaskName': daily 04:00, runs $script (compacts only when due and idle)"
    exit 0
}

# ---- what is due -----------------------------------------------------------------------------------------------
$last = 0
if (Test-Path $State) { try { $last = [double](Get-Content $State -Raw | ConvertFrom-Json).last } catch { } }
$now = [double][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
if (-not $Force -and -not $DryRun -and ($now - $last) -lt ($EveryDays * 86400)) { exit 0 }

$running = @(Clean (& wsl.exe -l --running -q) | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })
$default = $null
try {
    $lx = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    $g = (Get-ItemProperty $lx).DefaultDistribution
    $default = (Get-ItemProperty "$lx\$g").DistributionName
    $defaultVhdx = Join-Path (Get-ItemProperty "$lx\$g").BasePath 'ext4.vhdx'
} catch { }
$probe = if ($running -contains $default) { $default } elseif ($running.Count) { $running[0] } else { $default }

function UsedGB($distro, $path) {
    $o = WslIn $distro "mountpoint -q $path && df -k --output=used $path | tail -1"
    $v = ($o -join '').Trim()
    if ($v -match '^\d+$') { return [double]$v / 1MB } else { return $null }
}
$disks = @()
$disks += @{ name = 'card store'; vhdx = (Join-Path $DataRoot 'data\pad-cards.vhdx'); distro = $probe; path = '/mnt/wsl/cards' }
$disks += @{ name = 'rigs'' data disk'; vhdx = (Join-Path $DataRoot 'data\pad-data.vhdx'); distro = $probe; path = '/mnt/wsl/paddata' }
# a user's card cache on its own XFS disk (PAD-1459): evicted cards free blocks inside it, compacting gives them to C:
$disks += @{ name = 'card cache'; vhdx = (Join-Path $DataRoot 'data\pad-cardcache.vhdx'); distro = $probe; path = '/mnt/wsl/padcache' }
$disks += @{ name = 'PAD-Runtime'; vhdx = (Join-Path $DataRoot 'runtime\ext4.vhdx'); distro = 'PAD-Runtime'; path = '/' }
if ($default -and $default -ne 'PAD-Runtime') { $disks += @{ name = $default; vhdx = $defaultVhdx; distro = $default; path = '/' } }
$todo = @()
foreach ($d in $disks) {
    if (-not (Test-Path $d.vhdx)) { continue }
    if ($Only.Count -and $Only -notcontains $d.name) { continue }
    $size = (Get-Item $d.vhdx).Length / 1GB
    $used = UsedGB $d.distro $d.path
    if ($null -eq $used) { Say ("{0}: {1:N1} GB file, not mounted - skipped" -f $d.name, $size); continue }
    $slack = $size - $used
    Say ("{0}: {1:N1} GB file, {2:N1} GB used, {3:N1} GB to give back" -f $d.name, $size, $used, $slack)
    if ($slack -ge $MinSlackGB) { $d.size = $size; $todo += $d }
}
if (-not $todo.Count) {
    Say "nothing holds $MinSlackGB GB more than it uses"
    if (-not $Only.Count) { @{ last = $now } | ConvertTo-Json | Set-Content $State }   # a narrowed run says nothing of the rest
    exit 0
}

# ---- is anything running? ------------------------------------------------------------------------------------------
$why = @()
$board = Join-Path $env:USERPROFILE '.pad-rig'
if (Test-Path $board) {
    $fresh = @(Get-ChildItem $board -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '\.(run|lock)$' -and $_.LastWriteTime -gt (Get-Date).AddMinutes(-10) })
    if ($fresh.Count) { $why += "rig leases in use: $(($fresh | ForEach-Object Name) -join ', ')" }
}
# (single quotes only inside: Windows PowerShell 5.1 mangles double quotes in a native command's argument)
# a ticket's process, an emulator, a card mount, or anything working on the shared disks (a copy, a migrate, a sweep)
$scan = "for p in /proc/[0-9]*; do e=`$(tr '\0' '\n' < `$p/environ 2>/dev/null | grep -m1 '^PAD_TICKET='); c=`$(cat `$p/comm 2>/dev/null); case `$e`$c in *PAD_TICKET=*|*qemu*|*fuse2fs*) echo `$e `$c; continue ;; esac; readlink `$p/cwd `$p/fd/* 2>/dev/null | grep -q '^/mnt/wsl/' && echo `$c on /mnt/wsl; done | sort -u | head -5; echo SCAN_DONE"
foreach ($r in $running) {
    $out = @(WslIn $r $scan | Where-Object { $_.Trim() })
    # FAILS CLOSED: a scan that did not finish is a reason not to shut WSL down
    if (-not ($out -contains 'SCAN_DONE')) { $why += "$r could not be checked: $($out -join '; ')"; continue }
    $hits = @($out | Where-Object { $_ -ne 'SCAN_DONE' })
    if ($hits.Count) { $why += "$r busy: $($hits -join '; ')" }
}
if ($why.Count) { Say "not now - $($why -join ' | '). Tomorrow's run tries again."; exit 0 }
if ($DryRun) { Say "would compact: $(($todo | ForEach-Object { $_.name }) -join ', ')"; exit 0 }
if (-not (IsAdmin)) { Say "compacting needs an administrator: run elevated, or -Register the task"; exit 1 }

# ---- compact --------------------------------------------------------------------------------------------------------
# every distro that holds a disk on the list, started if it is not (a stopped one's deleted blocks are still mapped)
foreach ($r in @($todo | ForEach-Object { $_.distro } | Select-Object -Unique)) {
    WslIn $r '/usr/sbin/fstrim -av 2>&1 | tail -5' | ForEach-Object { Say "  fstrim ($r): $_" }
}
$s = Join-Path $env:TEMP 'padcompact.dpt'
function Free($v) { try { $fs = [IO.File]::Open($v, 'Open', 'ReadWrite', 'None'); $fs.Close(); return $true } catch { return $false } }
foreach ($d in $todo) {
    # WSL comes back the moment anything calls wsl.exe (the triage app, a session, a terminal), so it is shut down
    # right before EACH compact and the compact retried when it lost the race (as core/wsl_disk.reclaim does)
    $out = @()
    for ($try = 1; $try -le 4; $try++) {
        & wsl.exe --shutdown
        for ($i = 0; $i -lt 30 -and -not (Free $d.vhdx); $i++) { Start-Sleep 1; if ($i % 10 -eq 9) { & wsl.exe --shutdown } }
        @("select vdisk file=`"$($d.vhdx)`"", 'attach vdisk readonly', 'compact vdisk', 'detach vdisk', 'exit') | Set-Content $s -Encoding ascii
        $out = @(Clean (diskpart /s $s))
        if (-not ($out -match 'used by another process')) { break }
        Say "  $($d.name): WSL took the disk back (try $try) - again"
        @("select vdisk file=`"$($d.vhdx)`"", 'detach vdisk', 'exit') | Set-Content $s -Encoding ascii
        diskpart /s $s | Out-Null
    }
    $after = (Get-Item $d.vhdx).Length / 1GB
    Say ("{0}: {1:N1} GB -> {2:N1} GB; C: {3:N1} GB free" -f $d.name, $d.size, $after, ((Get-PSDrive C).Free / 1GB))
    if ($after -ge $d.size - 0.5) { Say "  diskpart: $(($out | Select-Object -Last 4) -join ' | ')" }
}
if (-not $Only.Count) { @{ last = $now } | ConvertTo-Json | Set-Content $State }
# the card store back where every distro looks for it (the app attaches it at a rig start too)
$cs = Join-Path $PSScriptRoot 'cardstore.ps1'
if (Test-Path $cs) { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $cs mount -NoFill *>&1 | ForEach-Object { Say "  $_" } }
Say "done"
