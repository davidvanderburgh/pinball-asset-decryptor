#!/bin/bash
# Stop the Spike 1 emulator: kill the game, the node-bus responder, the CUSE
# device daemons and the viewer windows, and hand the kernel's ARM binfmt
# handler back to the stock qemu so the Spike 2 rig is unaffected.  Run as root.
#
# Idempotent and safe to run when nothing is up.  Prints a short human line
# (this is only ever invoked directly, never parsed).
BF=/proc/sys/fs/binfmt_misc
HERE="$(cd "$(dirname "$0")" && pwd)"

pkill -KILL -f qemu-arm-pad  2>/dev/null
# a PIVOTED or criu-RESTORED guest's cmdline is "/.padqemu/game ./game" — no
# qemu-arm-pad substring — and a restored guest is detached from emu_root's
# tree besides, so kill by comm too (found when a restored guest SURVIVED
# stop.sh, item 87).
#
# BY PID, from s1own.sh, and NOT the global `pkill -KILL -x game` this used to
# copy from Spike 2's killgame.sh: comm=game is what BOTH rigs call their
# guest, so that line killed a live Spike 2 game whenever this script ran —
# and the app runs it on quit whenever it thinks a Spike 1 game is up, which a
# Spike 2 run alone was enough to make it think (PAD-98).
s1own() { S1_WORK="${S1_WORK:-}" bash "$HERE/s1own.sh" "$1" 2>/dev/null; }
killours() { local p; p=$(s1own "$1"); [ -n "$p" ] && kill -KILL $p 2>/dev/null; }

killours game
pkill -KILL -f emu_root.sh   2>/dev/null
pkill -KILL -f s1hwshim      2>/dev/null
# again, now that the restart loop is gone: the loop relaunches the game the
# moment the old one dies, and a guest born in that window is one this script
# was asked to stop.
killours game
# ours, not the Spike 2 rig's nodebus.py (same PAD-98 mix-up, and this one
# would have taken its node bus out from under a live run).
killours nodebus
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
