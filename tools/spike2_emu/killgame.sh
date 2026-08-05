#!/bin/bash
# killgame.sh - emergency stop. Kills every emulated game process.
#
# Run this any time WSL / vmmemWSL is burning CPU. Orphaned game processes spin
# at ~140% CPU each and never exit on their own, because the game installs its
# own SIGINT/SIGTERM handler (0x1b4f0) and ignores polite signals. SIGKILL only.
#
#   wsl -e bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/killgame.sh
#
# Note: vmmemWSL itself can NOT be killed from Task Manager - it is the WSL VM's
# memory process and Windows denies access. Kill the guest processes (this
# script) or shut the whole VM down with `wsl --shutdown` from Windows.

# This used to kill ONLY the guest, and count it with
#     ps -eo args | grep -c '[g]odzilla_pro/game'
# Two problems with that, both now fixed:
#   - it ignored padglhost and nodebus.py entirely. A bridged run starts three
#     processes; an orphaned padglhost busy-polls its ring at 5000 wakeups/s and
#     this script would happily report "still running: 0" with it burning CPU.
#   - `ps | grep` also matches the shell running the check, so the counts could
#     be inflated. pgrep excludes itself, and `-x` matches comm exactly.
# See alive.sh for why the guest's comm is 'game'.
count() { local c; c=$(pgrep -c "$@" 2>/dev/null); echo "${c:-0}"; }
total() { echo $(( $(count -x game) + $(count -f arm-binfmt) \
                 + $(count -x padglhost) + $(count -f nodebus.py) )); }

before=$(total)
echo "rig processes running: $before"
if [ "$before" -gt 0 ]; then
    ps -eo pid,etime,pcpu,comm,args --sort=-pcpu \
      | grep -E 'arm-binfmt|padglhost|nodebus\.py' | grep -v grep | head -20
fi

pkill -9 -x game
pkill -9 -f 'arm-binfmt'
pkill -9 -x padglhost
pkill -9 -f nodebus.py
pkill -9 -f 'autoattract.sh'
pkill -9 -f 'playaudio.sh'
# ^-anchored, and matched on the fifo not on '-f pulse': a severed player
# command line (see playaudio.sh) had no pulse output yet still held the fifo.
pkill -9 -f '^ffmpeg .*audio\.fifo'
# The Windows-sink relay. Killing it also ends the run's audio for the native
# Windows ffplay, which sees EOF on the socket and leaves on its own (-autoexit)
# - the kernel closes the socket even when this is a SIGKILL.
pkill -9 -f 'audiotcp\.py'
# BACKSTOP for a Windows player that did not take the hint. Matched on the PORT,
# never on the image name: `taskkill /IM ffplay.exe` would also kill PAD's own
# audio preview, which is a different ffplay doing legitimate work.
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command \
  "Get-CimInstance Win32_Process -Filter \"Name='ffplay.exe'\" |
   Where-Object { \$_.CommandLine -like '*:45997*' } |
   ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1
# The LED block doubles as the virtual playfield's liveness signal; removing
# it lets that window close itself instead of surviving the kill.
rm -f /home/david/spike2root/dump/padled
sleep 1

after=$(total)
echo "killed $((before - after)); still running: $after"
echo "load average: $(cut -d' ' -f1-3 /proc/loadavg)"
[ "$after" -eq 0 ] || echo "STILL NOT CLEAN - run alive.sh to see what survived"
