# abrun.ps1 - run ONE arm of an item-18 A/B and profile it, identically every time.
#
#   powershell -File abrun.ps1 -Label amd
#   powershell -File abrun.ps1 -Label nvidia -RunEnv "PAD_GL_ADAPTER=NVIDIA"
#   powershell -File abrun.ps1 -Label small  -RunEnv "PAD_GL_W=680,PAD_GL_H=384"
#   powershell -File abrun.ps1 -Label idle   -NoRun          # baseline, no emulator
#
# WHY THIS EXISTS. Item 18 is a sequence of one-variable A/B tests - which GPU,
# how big the window, how many WSLg windows - and each arm costs a multi-minute
# emulator run that cannot be parallelised. Driving that by hand puts operator
# variance on top of the effect being measured: the first pass's two arms had
# different warm-up times, and one of them was silently contaminated by a
# Defender scan and by a subagent running `find /` inside WSL. Both arms now go
# through exactly the same steps in the same order, and the run refuses to start
# at all when the machine is not fit to measure.
#
# WHAT IT WILL NOT DO, because these are standing rules in plans/TODO.md:
#   * it never wraps a run in `timeout` - watch.sh's own MINS backstop is the
#     cap and killgame.sh is the teardown.
#   * it never starts a run when one is already up. Two concurrent runs share
#     one ring and spoil each other, and the older script's teardown kills the
#     newer run mid-boot.
#   * it never moves or resizes a window from the Windows side.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Label,
    # Comma-separated VAR=VAL passed to the run. These are what the arm IS.
    [string]$RunEnv = "",
    [int]$Secs = 90,          # profiling window, once attract is reached
    [int]$Backstop = 12,      # minutes; watch.sh's own wall-clock cap
    [int]$AttractWaitSecs = 240,
    [switch]$NoRun,           # baseline: profile the desktop with no emulator
    # Profile an actual GAME rather than attract. Asked on 2026-08-06 when the
    # sluggishness shows up, David said "mostly during a game" - and every
    # capture before that had been attract mode, which runs less video, less
    # audio and almost no switch traffic. longplay.sh is what puts a ball in
    # play and keeps it alive; it is started BESIDE the run, never by it, so
    # that "never run two measurement runs at once" stays checkable by looking
    # at one thing.
    [switch]$Game,
    [int]$GameSettleSecs = 45,
    [switch]$SkipQuietCheck,
    [string]$Out = "C:\tmp\spike2_item18"
)

$ErrorActionPreference = "Stop"
$EMU_WIN = "C:\Users\david\Documents\development\pinball-asset-decryptor\tools\spike2_emu"
$EMU_WSL = "<rig>"
$WINPROF = Join-Path $EMU_WIN "winprof.py"
New-Item -ItemType Directory -Force $Out | Out-Null

function Say($m) { Write-Host "[abrun] $m" }

# --- 1. the rig must be clean, and the question must be asked INSIDE WSL ------
# Git Bash's pgrep sees only Windows processes and prints a confident 0 over a
# fully live rig; alive.sh now refuses to answer there, but this goes through
# wsl.exe so it gets the real answer either way.
Say "checking the rig is clean"
$alive = (wsl -e bash "$EMU_WSL/alive.sh" --total).Trim()
if ($alive -ne "0") {
    Say "REFUSING TO START: alive.sh says $alive things are still running."
    Say "Find out whether David is playing before killing anything."
    wsl -e bash "$EMU_WSL/alive.sh"
    exit 1
}

# --- 2. the MACHINE must be quiet, which is a separate question ---------------
# A rig-clean machine can still be a useless one to measure on. On 2026-08-06 a
# baseline read vmmemWSL 79.80% and 121,604 context switches - busier than the
# emulator run it was the control for - because a subagent was running `find /`
# inside WSL. The capture said nothing at the time. This is that check, moved
# to BEFORE the expensive part instead of after it.
if (-not $SkipQuietCheck) {
    Say "checking the machine is quiet enough to measure on (12 s)"
    & py -3 $WINPROF --secs 12 --label "_preflight" --out $env:TEMP --quiet | Out-Null
    # The thresholds live in winprof.py's quiet_check(), which is also what
    # --compare uses to disown an untrustworthy baseline. Asking it rather than
    # re-testing here keeps one definition of "quiet", which is the rule this
    # rig has been bitten by twice.
    $pf = Get-Content (Join-Path $env:TEMP "winprof__preflight.json") -Raw | ConvertFrom-Json
    $complaints = & py -3 -c @"
import json, sys
sys.path.insert(0, r'$EMU_WIN')
import winprof
print('\n'.join(winprof.quiet_check(json.load(open(sys.argv[1])))))
"@ (Join-Path $env:TEMP "winprof__preflight.json")
    if ($complaints) {
        Say "REFUSING TO START: the machine is not quiet enough to measure on."
        $complaints | ForEach-Object { if ($_) { Say "  $_" } }
        Say "Stop whatever that is and try again, or pass -SkipQuietCheck and"
        Say "expect the numbers to be worth less than the run cost."
        exit 1
    }
    Say ("quiet: WSL VM {0:N2}%, {1:N0} ctx/s, machine {2:N1}%" -f `
         [double]$pf.wsl_vm_cpu.mean, [double]$pf.scalars.ctx_switches.mean, `
         [double]$pf.scalars.hv_logical.mean)
}

# --- 3. the baseline arm needs no emulator at all -----------------------------
if ($NoRun) {
    Say "baseline arm: profiling $Secs s of desktop with no run"
    Say "(progress prints every 10 s; it is NOT stuck if it pauses briefly)"
    # -u for unbuffered. Without it Python block-buffers stdout whenever it is
    # not attached to a console, so nothing appears for the whole capture and it
    # looks like a hang.
    & py -3 -u $WINPROF --secs $Secs --label $Label --out $Out
    exit 0
}

# --- 4. start the run --------------------------------------------------------
# `wsl -e env VAR=VAL bash ...` rather than a shell string: wsl.exe re-parses a
# command line, so $var and $(subst) inside one expand to nothing. env(1) takes
# the assignments literally and there is no shell in the path to eat them.
$envArgs = @()
if ($RunEnv) { $envArgs = $RunEnv.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
Say ("starting the run" + $(if ($envArgs) { " with " + ($envArgs -join " ") } else { " with no extra env (control)" }))

$wslArgs = @("-e", "env") + $envArgs + @("bash", "$EMU_WSL/watch.sh", "$Backstop")
$runLog = Join-Path $Out "run_$Label.log"
$proc = Start-Process wsl -ArgumentList $wslArgs -PassThru -WindowStyle Hidden `
                          -RedirectStandardOutput $runLog -RedirectStandardError "$runLog.err"

# --- 5. wait for ATTRACT, not for a timer ------------------------------------
# gamestate.sh is the single definition of "past Tech Alerts": the attract
# light show is running - the shim prints `[led] light show running` once, at
# the 10th lamp-class command. The clip-based test (filesrc) joined the
# DISCREDITED list on 2026-08-10: star_wars_le serves clips while sitting ON
# the Tech Alerts screen, so it read "attract" over a screen full of alerts.
Say "waiting for attract mode"
$reached = $false
$t0 = Get-Date
while (((Get-Date) - $t0).TotalSeconds -lt $AttractWaitSecs) {
    Start-Sleep -Seconds 5
    if ($proc.HasExited) { Say "the run exited before reaching attract"; break }
    # A three-word pattern with no quote characters in it, deliberately: the
    # exact bracketed pattern gamestate.sh uses needs escaping, and a quote
    # crossing PowerShell -> wsl.exe -> bash is how the first version of this
    # wait silently matched nothing for 200 seconds.
    $n = (wsl -e grep -ac "light show running" ~/gzwatch.log)
    if ([int]$n -ge 1) {
        $reached = $true
        Say ("reached attract after {0:N0}s" -f ((Get-Date) - $t0).TotalSeconds)
        break
    }
}
if (-not $reached) { Say "WARNING: never reached attract; profiling anyway, say so in the report" }

# --- 5b. put a ball in play, if this arm is about a GAME ----------------------
# 1x1 as the "watch for this clip size" argument is deliberate: it can never
# match, which suppresses longplay's window-grab side effect. shotwin.py falls
# back to COPY MODE on RAIL windows and grabs whatever is on top, so those grabs
# are both useless here and a source of variance in the middle of a measurement.
if ($Game) {
    Say "starting longplay to put a ball in play and keep it alive"
    $lp = Join-Path $Out "longplay_$Label.log"
    Start-Process wsl -ArgumentList "-e", "bash", "$EMU_WSL/longplay.sh", `
                      "~/gzwatch.log", "$Backstop", "1x1" `
                  -PassThru -WindowStyle Hidden -RedirectStandardOutput $lp | Out-Null
    Say "letting the game settle for $GameSettleSecs s before profiling"
    Start-Sleep -Seconds $GameSettleSecs
    # There is NO reliable "a game has started" test in this rig - gamestate.sh
    # says so in terms, and deliberately does not try to tell attract from a
    # ball in play. So report what longplay itself claims and let the human
    # judge, rather than inventing a detector here. Inventing one is exactly how
    # the discredited factory_make test got written.
    $blocks = (Select-String -Path $lp -Pattern "new ball" -ErrorAction SilentlyContinue).Count
    Say "longplay reports $blocks ball(s) started (it cannot prove a game is on screen)"
}

# --- 6. which adapter did it ACTUALLY use ------------------------------------
# Read it back from the renderer's own log rather than trusting the environment
# we set. An env var that did not reach padglhost would otherwise produce two
# arms that were secretly the same arm, which is the worst possible A/B failure
# because it looks like a null result.
$adapter = (wsl -e grep -am1 "D3D12" ~/padglhost.log)
Say "renderer says: $adapter"

# --- 7. profile both sides of the boundary, in the same window ---------------
Say "profiling $Secs s (progress every 10 s; it is NOT stuck if it pauses)"
$rig = Start-Process wsl -ArgumentList "-e", "python3", "$EMU_WSL/rigprof.py", `
                         "--secs", "$Secs", "--label", $Label, "--out", "~" `
                     -PassThru -WindowStyle Hidden
& py -3 -u $WINPROF --secs $Secs --label $Label --out $Out
$rig.WaitForExit()

# --- 8. teardown, then VERIFY it, because "it stops itself" has been wrong ---
Say "stopping the run"
wsl -e bash "$EMU_WSL/killgame.sh" | Out-Null
Start-Sleep -Seconds 2
$after = (wsl -e bash "$EMU_WSL/alive.sh" --total).Trim()
if ($after -ne "0") {
    Say "*** THE RIG IS NOT CLEAN AFTER THIS ARM (alive.sh says $after) ***"
    wsl -e bash "$EMU_WSL/alive.sh"
} else {
    Say "rig clean"
}

wsl -e cp "~/rigprof_$Label.json" /mnt/c/tmp/spike2_item18/ 2>$null
Say "adapter for this arm: $adapter"
Say "captures in $Out"
