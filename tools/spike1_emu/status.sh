#!/bin/bash
# Spike 1 emulator status — one key=value per line, for the GUI control panel.
# Ordinary-user safe (only reads process state + file sizes); never mutates.
#
# The GUI parses this (pinball_decryptor/gui/_rig.parse_status), so every line
# MUST be key=value and nothing here may print prose to stdout.
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${S1_DESKTOP_USER:=$(getent passwd 1000 2>/dev/null | cut -d: -f1)}"
: "${S1_WORK:=/home/${S1_DESKTOP_USER:-david}/s1emu}"
: "${S1_QEMU:=/home/${S1_DESKTOP_USER:-david}/qemubuild/qemu-arm}"

echo "wsl=1"
echo "work=$S1_WORK"
# the distro name lets the GUI reach the run-dir files over \\wsl.localhost\<d>\
echo "distro=${WSL_DISTRO_NAME:-}"

# one-time setup present?
[ -x "$S1_QEMU" ] && echo "qemu_built=1" || echo "qemu_built=0"
[ -x "$S1_WORK/s1hwshim" ] && echo "hwshim_built=1" || echo "hwshim_built=0"
[ -f "$S1_WORK/game/game" ] && echo "game_ready=1" || echo "game_ready=0"

# the emulated game.  By COMM, not cmdline: pgrep -f qemu-arm-pad counted the
# restart-loop wrapper pair and never the game itself (the binfmt guest's
# cmdline is "./game"), and a PIVOTED or criu-RESTORED guest (item 87) says
# "/.padqemu/game" — no qemu-arm-pad anywhere, so a live restored game read
# as "Not running".  comm=game is the rig's one stable guest identity.
procs=$(pgrep -c -x game 2>/dev/null || echo 0)
echo "game_procs=$procs"
if [ "$procs" != "0" ]; then
    # uptime + CPU/RSS of the busiest guest (a slam-tilt restart can briefly
    # leave two; busiest-by-CPU is the live one)
    pid=$(ps -eo pid,comm --sort=-pcpu 2>/dev/null | awk '$2=="game"{print $1; exit}')
    if [ -n "$pid" ]; then
        secs=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')
        echo "game_uptime_s=${secs:-0}"
        read -r cpu rss <<EOF
$(ps -o pcpu=,rss= -p "$pid" 2>/dev/null)
EOF
        [ -n "$cpu" ] && echo "cpu=${cpu}"
        [ -n "$rss" ] && echo "rss_mb=$((rss / 1024))"
    fi
fi

# the node-bus responder + its viewers
pgrep -f "nodebus.py" >/dev/null 2>&1 && echo "responder=1" || echo "responder=0"
pgrep -f "s1dmd.py" >/dev/null 2>&1 && echo "dmd_view=1" || echo "dmd_view=0"
pgrep -f "s1view.py" >/dev/null 2>&1 && echo "sw_view=1" || echo "sw_view=0"

# DMD activity: frames captured (2048 bytes each), and the capture path so the
# GUI can render a live DMD preview in the tab (reads the last 2048-byte frame).
cap="$S1_WORK/spi0.cap"
echo "dmd_cap=$cap"
if [ -f "$cap" ]; then
    sz=$(stat -c%s "$cap" 2>/dev/null || echo 0)
    echo "dmd_frames=$((sz / 2048))"
fi

# node registration: the game reads a REGISTERED node's board id with cmd 0xf9
# (GetFullBoardID) and, once booted, continuously polls its switches with cmd
# 0x11 — so either frame in the node-bus capture proves the boot got past
# "LOCATING NODE BOARDS".  Both frames are `<node> <len> <cmd> …`; the board-id
# frame is len 3 (cmd,page,checksum -> bytes 03 f9) and the switch poll is len 2
# (cmd,checksum -> bytes 02 11).  The OLD check looked for `02 f9` (len 2 + cmd
# f9), which NO real frame carries, so it matched only on a coincidental data
# byte pair in the growing capture — making the GUI flap between "Booting…" and
# "Running".  Match the real frames instead: switch polling (continuous, so it
# is present and stable the moment the game is scanning) OR a board-id read.
# save-state slots: the saves dir's mtime, so the GUI re-lists only when
# something changed (a save, a delete) instead of shelling the lister per poll.
if [ -d "$S1_WORK/saves" ]; then
    echo "saves_mtime=$(find "$S1_WORK/saves" -mindepth 2 -maxdepth 2 -printf '%T@\n' 2>/dev/null | sort -rn | head -1)"
else
    echo "saves_mtime="
fi

nbcap="$S1_WORK/ttyS4.cap"
if [ -f "$nbcap" ]; then
    if grep -qaE $'\x02\x11|\x03\xf9' "$nbcap" 2>/dev/null; then
        echo "nodes_registered=1"
    else
        echo "nodes_registered=0"
    fi
fi
