#!/bin/bash
# killgame.sh - emergency stop. Kills every emulated game process.
#
# Run this any time WSL / vmmemWSL is burning CPU. Orphaned game processes spin
# at ~140% CPU each and never exit on their own, because the game installs its
# own SIGINT/SIGTERM handler (0x1b4f0) and ignores polite signals. SIGKILL only.
#
#   wsl -e bash $RIG/killgame.sh
#
# Note: vmmemWSL itself can NOT be killed from Task Manager - it is the WSL VM's
# memory process and Windows denies access. Kill the guest processes (this
# script) or shut the whole VM down with `wsl --shutdown` from Windows.
#
# ** INSIDE WSL, and this script now enforces it. ** Run from Git Bash on
# Windows it fails on the first pkill ("command not found") and then prints
#   killed 0; still running: 0
# which reads exactly like success, because the "still running" half asks
# alive.sh, whose pgrep sees only Windows processes there. 2026-08-06 that pair
# of confident zeros led to a second full run being started on top of a live
# one. Same /proc test as alive.sh, same reason: refuse rather than reassure.
. "$(dirname "$0")/padpath.sh"
if [ ! -d /proc/1 ] || ! grep -qs . /proc/1/comm 2>/dev/null; then
    echo "killgame.sh: this is not a Linux shell - nothing here can see the rig." >&2
    echo "  Run it inside WSL:  wsl -e bash \$0" >&2
    exit 2
fi
#
# THE COUNTING LIVES IN alive.sh, NOT HERE. This script used to keep its own
# copy of the process list, and the two drifted: alive.sh grew the audio player
# and this one did not, then BOTH missed the Windows-interop stubs and the card
# mounts, and a machine with seven leaked stubs on it reported "clean". One list,
# one place. If you add something to the rig, add it to alive.sh.
SELF=$(cd "$(dirname "$0")" && pwd)
total() { bash "$SELF/alive.sh" --total; }

before=$(total)
echo "rig processes running: $before"
[ "$before" -gt 0 ] && bash "$SELF/alive.sh" | sed -n '/--- what is still up ---/,$p'

pkill -9 -x game
pkill -9 -f 'arm-binfmt'
pkill -9 -x padglhost
pkill -9 -f nodebus.py
pkill -9 -f 'autoattract.sh'
# The background table builder watch.sh starts on a title that already
# has artwork. It waits in a poll loop for the guest's switch table, so
# it outlives a run that ends first. alive.sh counts it.
pkill -9 -f 'mktables[.]py'
# The event feed. An orphaned `tail -F` never exits by itself.
pkill -9 -f "^tail -q -n 0 -F "$HOME/padvid"\.log"
pkill -9 -f 'padvidhost\.py'
pkill -9 -f 'playaudio.sh'
# ^-anchored, and matched on the fifo not on '-f pulse': a severed player
# command line (see playaudio.sh) had no pulse output yet still held the fifo.
pkill -9 -f '^ffmpeg .*audio\.fifo'
# The Windows-sink relay, and the native player when there is no bridge.
# Killing the relay also ends the run's audio for the Windows player, which sees
# EOF on the socket and leaves on its own - the kernel closes the socket even
# when this is a SIGKILL.
pkill -9 -f 'padrelay\.py'
pkill -9 -f 'padplay\.py'
# The virtual playfield is a WINDOWS process reached through interop; its
# WSL-side stub is what is visible here. Removing the LED block below is the
# POLITE close (playfield.py notices and leaves, which is also how it saves its
# window position), so give that a moment before killing the stub - but do kill
# it, because measured reality is that a stub whose interop Relay has died sits
# in poll() forever with no Windows process behind it. Seven had accumulated,
# oldest 2.5 h, while alive.sh said the machine was clean.
#
# The run scripts go before the wait so nothing restarts under us.
pkill -9 -f '^bash .*(watch|runbridge|nbrun)\.sh'
# longplay.sh is started BESIDE a run rather than by one, so it is not in the
# group above - and watch.sh's own teardown was the only thing that ever killed
# it. Anything that stops a run through THIS script (abrun.ps1 does) would
# otherwise leave it poking ramp optos into the next run. alive.sh already
# counts it, so the leak was visible, but visible is not the same as fixed.
# Anchored exactly as watch.sh and alive.sh anchor it: an unanchored
# 'longplay.sh' matches any shell with the name on its command line, and this
# one KILLS.
pkill -9 -f '^bash [^ ]*longplay\.sh'
# The LED block doubles as the virtual playfield's liveness signal; removing
# it lets that window close itself instead of surviving the kill.
rm -f "$ROOT/dump/padled"
for _ in 1 2 3 4 5 6; do
    pgrep -f '^/init .*playfield\.py' >/dev/null || break
    sleep 0.5
done
pkill -9 -f '^/init .*playfield\.py'
# BACKSTOPS for Windows children that did not take the hint. Matched on the
# SCRIPT (and, for the player, the PORT), never on the image name alone: killing
# every python.exe would take out whatever else the user is running, and the
# version of this that matched ffplay.exe would have killed PAD's own audio
# preview.
#
# `Name -like 'python*'` is NOT decoration - it is the Windows-side version of
# the self-match trap this rig already knows from pgrep. This very command line
# CONTAINS the string '*spike2_emu\playfield.py*', so a CommandLine-only filter
# matches the powershell.exe running the query and Stop-Process shoots itself
# mid-pipeline. Requiring a python interpreter excludes it by construction.
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command \
  "Get-CimInstance Win32_Process |
   Where-Object { \$_.Name -like 'python*' -and
                  ((\$_.CommandLine -like '*padplay.py*' -and
                    \$_.CommandLine -like '* 45997 *') -or
                   \$_.CommandLine -like '*spike2_emu\playfield.py*') } |
   ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1

# CARD MOUNTS. cardmount.sh setsid's fuse2fs deliberately - a run's process-group
# kill used to take the mount out from under the game it had just started, and
# the game then sat at "Startup In Progress" forever with every read failing and
# no error printed anywhere - so nothing in any teardown has ever reached them.
# Three were found orphaned in one session. Unmounting is safe here BECAUSE this
# script has just killed everything that could have been reading one, and the
# expensive part (the local image cache under ~/cardcache) is a file that
# survives: a remount is a fraction of a second.
for m in "$HOME/card/"*/; do
    mountpoint -q "$m" 2>/dev/null || continue
    fusermount -u "$m" 2>/dev/null || fusermount3 -u "$m" 2>/dev/null
    rmdir "$m" 2>/dev/null
    echo "unmounted card $m"
done
sleep 1

after=$(total)
echo "killed $((before - after)); still running: $after"
echo "load average: $(cut -d' ' -f1-3 /proc/loadavg)"

# ★ A SURVIVOR IS NOT ALWAYS SOMETHING THAT CAN BE KILLED, and reporting a bare
# number while that is true is how this script sent someone hunting for a signal
# that does not exist. A zombie is already dead; it needs REAPING, by its parent.
# When the parent is a WSL interop relay (comm 'Relay(NNN)' or 'init', argv
# '/init'), that parent ignores SIGKILL from inside the VM - measured, against a
# `[game] <defunct>` left by a closed window. No amount of pkill clears it.
#
# FILTERED TO RIG PROCESSES, because the unfiltered version cries wolf: WSL
# leaves a `[SessionLeader] <defunct>` under /init after ordinary session exits,
# and printing "the only cure is wsl --shutdown" over that noise is how a real
# warning gets trained out of a human. Same comm list as alive.sh.
Z=$(ps -eo pid,ppid,stat,comm --no-headers 2>/dev/null \
    | awk '$3 ~ /^Z/ && $4 ~ /^(game|padglhost|fuse2fs|ffmpeg|pythonw\.exe|python3?)$/')
if [ -n "$Z" ]; then
    echo "--- zombies (already dead; they need reaping, not killing) ---"
    echo "$Z" | while read -r zpid zppid _ zcomm; do
        pcomm=$(ps -o comm= -p "$zppid" 2>/dev/null)
        pargs=$(ps -o args= -p "$zppid" 2>/dev/null)
        echo "  $zpid [$zcomm] held by $zppid ($pcomm)"
        case "$pcomm$pargs" in
            *Relay*|*/init*)
                echo "  ^ that parent is a WSL INTEROP RELAY. It ignores SIGKILL from"
                echo "    inside the VM, so this zombie can NOT be cleared from here."
                echo "    The only cure, from Windows:   wsl --shutdown" ;;
        esac
    done
fi

[ "$after" -eq 0 ] || echo "STILL NOT CLEAN - run alive.sh to see what survived"
