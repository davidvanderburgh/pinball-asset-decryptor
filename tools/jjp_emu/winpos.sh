#!/bin/bash
# Remember where the game window was, and put it back there next time.
#
# The window is Xephyr's (display.sh), and nothing on either side of WSLg
# persists its position - so every launch dropped the game wherever the
# compositor chose, which on a multi-monitor desktop is usually the wrong
# screen.  winpos.ps1 does the actual Win32 work and explains why it has to be
# done from the Windows side; this is the rig's half: where the state lives,
# what the window is called, and when to save or restore.
#
#   winpos.sh save      - record the window's rect (called before teardown)
#   winpos.sh restore   - put a newly-opened window back (called after launch)
#
# Both are best-effort and NEVER fatal.  A window position is a convenience;
# failing a launch over one would be absurd.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

: "${JJP_WIN_FILE:=/var/tmp/jjp_window.json}"
#: How long restore waits for the window to appear.  Xephyr maps its window a
#: moment after the process starts, and WSLg takes a further beat to surface it
#: on the Windows desktop, so a single check right after launch reliably misses.
: "${JJP_WIN_WAIT:=15}"

# WSLg appends " (Ubuntu)" - or whatever the distro is called - to every window
# title, so match on a PREFIX and never on equality.  The title itself comes
# from display.sh and carries the mounted title, so this stays title-agnostic.
win_pattern() {
    printf 'JJP %s - emulated*' "$(jjp_title)"
}

ps_exe() {
    command -v powershell.exe >/dev/null 2>&1 && { echo powershell.exe; return; }
    echo /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
}

# The .ps1 has to be named in WINDOWS terms for powershell.exe to open it.
ps_script() {
    if command -v wslpath >/dev/null 2>&1; then
        wslpath -w "$HERE/winpos.ps1" 2>/dev/null && return
    fi
    # Fallback for a checkout under /mnt/<drive>: /mnt/c/x -> C:\x
    printf '%s' "$HERE/winpos.ps1" | sed -E 's#^/mnt/([a-z])/#\U\1:/#; s#/#\\#g'
}

run_ps() {
    "$(ps_exe)" -NoProfile -ExecutionPolicy Bypass -File "$(ps_script)" "$@" 2>/dev/null
}

case "${1:-}" in
    save)
        OUT=$(run_ps -Action get -Pattern "$(win_pattern)")
        # key=value in, JSON out.  Only a rect that actually parses is written,
        # so a failed read can never overwrite a good remembered position.
        X=$(printf '%s\n' "$OUT" | sed -n 's/^x=\(-\?[0-9]\+\)\r\?$/\1/p')
        Y=$(printf '%s\n' "$OUT" | sed -n 's/^y=\(-\?[0-9]\+\)\r\?$/\1/p')
        W=$(printf '%s\n' "$OUT" | sed -n 's/^w=\([0-9]\+\)\r\?$/\1/p')
        H=$(printf '%s\n' "$OUT" | sed -n 's/^h=\([0-9]\+\)\r\?$/\1/p')
        if [ -z "$X" ] || [ -z "$Y" ]; then
            echo "winpos: no game window to remember"
            exit 0
        fi
        # A minimised window reports a nonsense rect (-32000).  Remembering it
        # would restore the game off-screen, where it looks like a failed launch.
        if [ "$X" -lt -30000 ] || [ "$Y" -lt -30000 ]; then
            echo "winpos: window is minimised - keeping the previous position"
            exit 0
        fi
        printf '{"x":%s,"y":%s,"w":%s,"h":%s}\n' "$X" "$Y" "${W:-0}" "${H:-0}" \
            > "$JJP_WIN_FILE"
        chmod 666 "$JJP_WIN_FILE" 2>/dev/null
        echo "winpos: remembered ${X},${Y} ${W}x${H}"
        ;;
    restore)
        [ -s "$JJP_WIN_FILE" ] || { echo "winpos: nothing remembered yet"; exit 0; }
        eval "$(sed -n 's/.*"x":\(-\?[0-9]\+\).*"y":\(-\?[0-9]\+\).*"w":\([0-9]\+\).*"h":\([0-9]\+\).*/X=\1 Y=\2 W=\3 H=\4/p' "$JJP_WIN_FILE")"
        if [ -z "${X:-}" ] || [ -z "${Y:-}" ]; then
            echo "winpos: remembered position is unreadable; leaving the window alone"
            exit 0
        fi
        # WAIT for the window.  Xephyr maps a moment after it starts and WSLg
        # surfaces it a beat later, so restoring immediately moves nothing.
        for _ in $(seq 1 "$JJP_WIN_WAIT"); do
            run_ps -Action get -Pattern "$(win_pattern)" | grep -q '^x=' && break
            sleep 1
        done
        run_ps -Action set -Pattern "$(win_pattern)" \
               -X "$X" -Y "$Y" -W "${W:-0}" -H "${H:-0}" \
            | tr -d '\r' | sed 's/^/winpos: /'
        ;;
    *)
        echo "usage: winpos.sh save|restore" >&2
        exit 64 ;;
esac
