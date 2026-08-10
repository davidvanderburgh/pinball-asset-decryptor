#!/bin/bash
# winreset.sh - forget where the emulator windows were, so the next run opens
# them where a first-ever run would.  (queue item 37)
#
#   wsl -e bash winreset.sh            reset, then say what was thrown away
#   wsl -e bash winreset.sh --show     print what is remembered, change nothing
#   wsl -e bash winreset.sh --force    reset even with a run up (see the gate)
#
# WHY A BUTTON NEEDS THIS AT ALL: the remembered geometry is restored with no
# on-screen check anywhere. padglhost reads `game` and `legend` out of
# ~/.pad_windows (winpos_get, padglhost.c:913) and XMoveWindows both there -
# there is no DisplayWidth/bounds test in that file - and it CREATES the game
# window at the saved `w h` as well (:1269). So a window dragged onto a second
# monitor that is later unplugged, or a size left silly by an experiment, comes
# back exactly as it was every run, and a window that is fully off every
# monitor cannot be dragged back. Before this script the only cure was knowing
# the file existed and editing it inside WSL.
#
# WHAT "DEFAULT" MEANS, read off the source rather than chosen here: with NO
# line for a key, win_open() leaves win_w/win_h at fb_w/fb_h - PAD_GL_W and
# PAD_GL_H, which watch.sh sets to 1360x768 (watch.sh:92) - and the delayed
# restore marks itself settled at once (`game_settled = !game_want_pos`,
# padglhost.c:1494), so no XMoveWindow is ever issued and the compositor's own
# placement stands. Deleting the line IS the reset; there is no default
# position to write, because WSLg ignores the one asked for at create time.
#
# THE TWO FILES, AND WHY THIS SCRIPT CANNOT ALWAYS DO BOTH:
#
#   ~/.pad_windows          padglhost's `game` and `legend`. ALWAYS rig-side -
#                           padglhost is an X client and runs where this
#                           script runs.
#   ~/.pad_playfield.json   playfield.py's `playfield_pos`. Rig-side ONLY when
#                           the playfield is a local Tk process, which is the
#                           Linux-desktop and container case (watch.sh's
#                           IS_WSL=0 branch). Under WSL this WSL has no Tk at
#                           all, so the playfield is a WINDOWS process reached
#                           through interop and its ~ is the Windows profile -
#                           a home this script cannot see. There the app's
#                           Reset windows button clears it, on its own side of
#                           the boundary, and the touch below finds no file
#                           and correctly does nothing.
#
# LEFT ALONE ON PURPOSE: ~/.pad_windows_win.json. padwinpos.py writes it and
# NOTHING restores from it - watch.sh's closing comment records why the
# Windows-side mover was withdrawn (SetWindowPos on a RAIL window made both
# windows undraggable). It is a diagnosis record, so clearing it would destroy
# evidence and reset nothing.
#
# OUT OF SCOPE, and it is why the gate below refuses rather than tries: moving
# the windows of a LIVE run. That can only be done from inside X, per the
# standing non-negotiable, and padglhost has no channel to ask it through.
set -u

SHOW=0
FORCE=0
for a in "$@"; do
    case "$a" in
        --show)    SHOW=1 ;;
        --force)   FORCE=1 ;;
        -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
        *) echo "winreset: unknown argument '$a'" >&2; exit 2 ;;
    esac
done

HERE=$(cd "$(dirname "$0")" && pwd)
WINF="$HOME/.pad_windows"
PFF="$HOME/.pad_playfield.json"

# THE GATE. A reset under a live run is not merely useless, it is a lie: the
# button reports success and the next start comes up in the same wrong place.
# padglhost re-saves on ConfigureNotify and again at close once the restore has
# settled (winpos_save_all, padglhost.c:1533/1572/1645), so clearing the file
# under a live run just writes the off-screen coordinates straight back.
#
# `--procs` and not `--total`: alive.sh's own header calls --procs the "is a
# run up" answer and --total the "is the machine clean" one, the difference
# being idle card mounts. A stranded fuse2fs mount is not padglhost and cannot
# write this file, so it must not block a reset - the same reasoning alive.sh
# gives for not letting it say Stop on the app's button.
if [ "$SHOW" = 0 ] && [ "$FORCE" = 0 ]; then
    up=$(bash "$HERE/alive.sh" --procs 2>/dev/null || true)
    case "${up:-}" in
        ""|*[!0-9]*)
            # alive.sh refuses outright rather than guess when /proc is not
            # readable (Git Bash), and a wrong "clean" here would edit the
            # wrong home entirely. Refusing is the only honest answer.
            echo "winreset: alive.sh could not say whether a run is up ('${up:-}')." >&2
            echo "  Run this inside the rig's own shell:  wsl -e bash \$0" >&2
            exit 2 ;;
    esac
    if [ "$up" != 0 ]; then
        echo "winreset: a run is up ($up processes) - nothing changed."
        echo "  Stop the emulator first. padglhost saves the window geometry"
        echo "  as the windows move and again when it closes, so a reset now"
        echo "  would be written straight back at the end of this run."
        exit 1
    fi
fi

# --- what is remembered ---------------------------------------------------
# Reported before anything is touched, and printed for --show as well, so the
# log of a reset says what was thrown away rather than only that something was.
found=0
if [ -f "$WINF" ]; then
    while IFS= read -r line; do
        case "${line%% *}" in
            game|legend) echo "winreset: remembered $line"; found=1 ;;
        esac
    done < "$WINF"
fi
if [ -f "$PFF" ] && grep -q '"playfield_pos"' "$PFF" 2>/dev/null; then
    echo "winreset: remembered playfield_pos $(tr -d ' \n' < "$PFF" \
        | sed -n 's/.*"playfield_pos":\(\[[^]]*\]\).*/\1/p')"
    found=1
fi
if [ "$found" = 0 ]; then
    # Say this and stop, rather than say it and then report a reset as well:
    # two sentences that contradict each other in the app's log is how a user
    # learns not to read it.
    echo "winreset: nothing is remembered - the windows are already at their defaults."
    exit 0
fi
[ "$SHOW" = 1 ] && exit 0

# --- ~/.pad_windows -------------------------------------------------------
# EVERY OTHER LINE IS KEPT BYTE FOR BYTE. winpos_put's own comment
# (padglhost.c:931) records why: it re-reads the file with a 3-field sscanf and
# reformatting a 5-field line through that is exactly how a size gets lost. A
# reset that quietly rewrote an unrelated key would be the same bug from the
# other side, so this matches on field 1 alone and copies the rest through.
if [ -f "$WINF" ]; then
    tmp=$(mktemp "$WINF.XXXXXX") || { echo "winreset: cannot write $WINF" >&2; exit 1; }
    while IFS= read -r line || [ -n "$line" ]; do
        case "${line%% *}" in
            game|legend) ;;
            *) printf '%s\n' "$line" >> "$tmp" ;;
        esac
    done < "$WINF"
    mv "$tmp" "$WINF"
fi

# --- ~/.pad_playfield.json ------------------------------------------------
# Only playfield_pos goes; the file holds other keys (window state the
# playfield keeps across runs) and dropping them would be a second, silent
# reset nobody asked for. python3 is present wherever the rig runs - watch.sh
# uses it for mktables on every single boot - so this is not a new dependency.
if [ -f "$PFF" ]; then
    python3 - "$PFF" <<'PY'
import json, sys
p = sys.argv[1]
try:
    with open(p) as f:
        st = json.load(f)
except Exception:
    sys.exit(0)                      # unreadable or not JSON: leave it alone
if isinstance(st, dict) and st.pop("playfield_pos", None) is not None:
    with open(p, "w") as f:
        json.dump(st, f, indent=1)
PY
fi

echo "winreset: reset. The next run opens the game window at its default size"
echo "  (PAD_GL_W x PAD_GL_H, 1360x768 unless you set them) wherever the"
echo "  compositor puts it, and the playfield window at its own default."
