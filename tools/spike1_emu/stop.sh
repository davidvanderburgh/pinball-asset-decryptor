#!/bin/bash
# Stop the Spike 1 emulator: kill the game, the node-bus responder, the CUSE
# device daemons and the viewer windows, and hand the kernel's ARM binfmt
# handler back to the stock qemu so the Spike 2 rig is unaffected.  Run as root.
#
# Idempotent and safe to run when nothing is up.  Prints a short human line
# (this is only ever invoked directly, never parsed).
BF=/proc/sys/fs/binfmt_misc

pkill -KILL -f qemu-arm-pad  2>/dev/null
# a PIVOTED or criu-RESTORED guest's cmdline is "/.padqemu/game ./game" — no
# qemu-arm-pad substring — and a restored guest is detached from emu_root's
# tree besides, so kill by comm too (the same global -x game Spike 2's
# killgame.sh uses; found when a restored guest SURVIVED stop.sh, item 87).
pkill -KILL -x game          2>/dev/null
pkill -KILL -f emu_root.sh   2>/dev/null
pkill -KILL -f s1hwshim      2>/dev/null
pkill -KILL -f nodebus.py    2>/dev/null
pkill -KILL -f s1ball.py     2>/dev/null
pkill -KILL -f "s1dmd.py"    2>/dev/null
pkill -KILL -f "s1view.py"   2>/dev/null
# the speaker chain (start.sh 6a): playaudio.sh's own trap takes the Windows
# padplay.py child with it; TERM (not KILL) so that trap actually runs.
# Matched on this rig's FIFO so a Spike 2 run's speaker is left alone.
pkill -f "playaudio.sh /home/.*/s1emu/audio.fifo" 2>/dev/null
pkill -f "padrelay.py /home/.*/s1emu/audio.fifo"  2>/dev/null
# Reap the WINDOWS players synchronously, here, not only via playaudio's trap:
# the interop padplay.exe children survive their bash parents' TERM (bash
# defers death until the foreground child exits), so restart-loop subshells
# from EVERY prior boot lingered — and when a later boot's trap finally fired
# its port-matched kill, it reaped the LIVE player along with the zombies and
# the reconnect pile-up wedged the WSL localhost proxy (a silent run with the
# relay still "listening").  Killing them synchronously at stop time means the
# next start begins from zero players.  Port-matched, same rule as playaudio.
# `$_.Name -like 'py*'` is LOAD-BEARING: without it the query's own
# powershell.exe (whose command line contains both match strings) kills
# ITSELF mid-pipeline — observed taking the whole WSL session with it.
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile \
    -Command "Get-CimInstance Win32_Process |
              Where-Object { \$_.Name -like 'py*' -and
                             \$_.CommandLine -like '*padplay.py*' -and
                             \$_.CommandLine -like '* 45998 *' } |
              ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" \
    >/dev/null 2>&1 || true
sleep 1

# restore the stock ARM binfmt handler (the Spike 2 rig relies on it)
[ -e "$BF/qemu-arm-pad" ] && echo -1 > "$BF/qemu-arm-pad" 2>/dev/null
echo 1 > "$BF/qemu-arm" 2>/dev/null

echo "Spike 1 emulator stopped; stock qemu-arm binfmt restored."
