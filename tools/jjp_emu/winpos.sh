#!/bin/bash
# Remember where the game window was, and put it back there next time.
#
# The window is Xephyr's (display.sh).  Xephyr cannot position its own host
# window - its -screen +X+Y and -origin place a screen inside the VIRTUAL X
# screen, not on the desktop - and WSLg does not persist it, so every launch
# dropped the game wherever the compositor chose.  On a multi-monitor desktop
# that is usually the wrong screen.
#
#   winpos.sh save    [game|matrix]   - record where a window is (before teardown)
#   winpos.sh restore [game|matrix]   - put a newly-opened one back (after launch)
#
# BOTH windows need this, for different reasons.  The game window is Xephyr's
# and Xephyr cannot place it.  The matrix is a Tk window that tries to place
# ITSELF and cannot either: under WSLg, Tk reports its own position as -32768,
# so jjpsw.py was writing "1450x1754+-32768+-32768" - which its own restore
# regex then refused to match, silently throwing the geometry away on every
# launch.  Tk gets the SIZE right, so it keeps that; position is settled here,
# where there is one mechanism that works for both windows.
#
# Both are best-effort and NEVER fatal.  A window position is a convenience;
# failing a launch over one would be absurd.
#
# THIS MOVES THE WINDOW THROUGH X, NOT THROUGH WIN32, AND THAT IS THE WHOLE
# POINT.  The first version used SetWindowPos, and it could not work: measured
# 2026-08-20, a Win32 move changed what WINDOWS reported (508,4 -> 628,94 ->
# 508,4) while X went on reporting +800+65 the entire time.  Windows and Weston
# then disagree about where the surface is, which is what left a window the user
# could no longer drag by its title bar - and an earlier attempt that also
# restored the SIZE killed the nested X server outright ("X connection to :1
# broken", XIO fatal) and took the game with it.
#
# An X move propagates BOTH ways: xdotool windowmove moved X +800+65 -> +306+147
# and Windows followed, 508,4 -> 179,59.  So the compositor stays in step and
# the window keeps behaving like a window.  Everything below is therefore in X
# coordinates; the Windows side is never consulted.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

: "${JJP_UI_DISPLAY:=:0}"
#: How long restore waits for the window to appear.  Xephyr maps its window a
#: moment after the process starts, so a single check right after launch misses.
: "${JJP_WIN_WAIT:=15}"

export DISPLAY=$JJP_UI_DISPLAY

# Which window, and where its position is kept.  The game's title carries the
# MOUNTED title so the rig stays title-agnostic; xdotool --name is a REGEX and
# WSLg appends " (Ubuntu)", so neither pattern is anchored at the end.
TARGET=${2:-game}
case "$TARGET" in
    game)   win_regex() { printf 'JJP %s - emulated' "$(jjp_title)"; }
            : "${JJP_WIN_FILE:=/var/tmp/jjp_window.json}" ;;
    matrix) win_regex() { printf 'JJP switch matrix'; }
            : "${JJP_WIN_FILE:=/var/tmp/jjp_matrix_window.json}" ;;
    *) echo "winpos: unknown window '$TARGET' (game|matrix)" >&2; exit 64 ;;
esac

find_win() { xdotool search --name "$(win_regex)" 2>/dev/null | head -1; }

# X,Y as xdotool itself reports them, so save and restore speak one language.
geom() {
    xdotool getwindowgeometry --shell "$1" 2>/dev/null \
        | sed -n 's/^\(X\|Y\)=\(-\?[0-9]\+\)$/\1=\2/p'
}

have_xdotool() { command -v xdotool >/dev/null 2>&1; }

case "${1:-}" in
    save)
        have_xdotool || { echo "winpos: xdotool not installed - nothing saved"; exit 0; }
        W=$(find_win)
        [ -n "$W" ] || { echo "winpos: no $TARGET window to remember"; exit 0; }
        eval "$(geom "$W")"
        if [ -z "${X:-}" ] || [ -z "${Y:-}" ]; then
            echo "winpos: could not read the window position"; exit 0
        fi
        # A minimised or unmapped window reports nonsense; remembering it would
        # restore the game somewhere it cannot be seen, which reads as a failed
        # launch.  Only a rect that parses AND is sane is ever written, so a bad
        # read can never overwrite a good remembered position.
        if [ "$X" -lt -20000 ] || [ "$Y" -lt -20000 ]; then
            echo "winpos: window is not on screen - keeping the previous position"
            exit 0
        fi
        printf '{"x":%s,"y":%s}\n' "$X" "$Y" > "$JJP_WIN_FILE"
        chmod 666 "$JJP_WIN_FILE" 2>/dev/null
        echo "winpos: remembered $TARGET at ${X},${Y}"
        ;;
    restore)
        have_xdotool || { echo "winpos: xdotool not installed - not restoring"; exit 0; }
        [ -s "$JJP_WIN_FILE" ] || { echo "winpos: nothing remembered yet"; exit 0; }
        eval "$(sed -n 's/.*"x":\(-\?[0-9]\+\).*"y":\(-\?[0-9]\+\).*/TX=\1 TY=\2/p' "$JJP_WIN_FILE")"
        if [ -z "${TX:-}" ] || [ -z "${TY:-}" ]; then
            echo "winpos: remembered position is unreadable; leaving the window alone"
            exit 0
        fi
        W=""
        for _ in $(seq 1 "$JJP_WIN_WAIT"); do
            W=$(find_win); [ -n "$W" ] && break
            sleep 1
        done
        [ -n "$W" ] || { echo "winpos: the $TARGET window never appeared"; exit 0; }

        # windowmove takes a FRAME coordinate and getwindowgeometry reports the
        # window's, and the two differ by the decoration - so asking for the
        # remembered number lands close but not on it.  Rather than hard-code a
        # decoration size that every WM would disagree about, move, measure, and
        # correct by the error.  Converges in one step and needs to know nothing.
        xdotool windowmove "$W" "$TX" "$TY" 2>/dev/null
        sleep 1
        eval "$(geom "$W")"
        if [ -n "${X:-}" ] && [ -n "${Y:-}" ] \
           && { [ "$X" != "$TX" ] || [ "$Y" != "$TY" ]; }; then
            xdotool windowmove "$W" $((TX + TX - X)) $((TY + TY - Y)) 2>/dev/null
            sleep 1
            eval "$(geom "$W")"
        fi
        echo "winpos: restored $TARGET to ${X:-?},${Y:-?} (wanted ${TX},${TY})"
        ;;
    *)
        echo "usage: winpos.sh save|restore [game|matrix]" >&2
        exit 64 ;;
esac
