# rigboard.sh - every emulator's runs on the rig board (PAD-296).  Sourced.
#
# The board is %USERPROFILE%\.pad-rig on the Windows side: the one place the
# triage dashboard, the app's window and every WSL distro can all read (see
# tools/spike2_emu/padpath.sh, "RIG SLOTS: THE BOARD").  The Spike 2 rig has
# always posted slot-N.run there; nothing else did, so a HIDDEN run of any
# other emulator played with no window and no pill anywhere - David could
# hear Beetlejuice and not find it (PAD-296).
#
# A run of emulator <emu> on its rig <n> is one line of JSON in
#
#   <emu>-<n>.run   {"emu","slot","game","title","label","distro","pid",
#                    "started","hidden","audio"}
#
# keyed by emulator AND rig because the rigs are numbered per emulator (AP
# rig 1 and Spike 2 rig 1 are two different machines).  Spike 2 keeps its own
# slot-N.run, written by its watch.sh.
#
# A detached beater touches the record every 10 s while the game's pid lives
# and removes it when the pid goes, so a run killed any way at all - its
# killgame.sh, a crash, `wsl --terminate` - stops beating; the dashboard calls
# a record stale after RUN_FRESH_S (120 s) without a beat.
#
#   rigboard_post <emu> <slot> <pid> <game> <title> <visible> <audio>
#       after the game is up; <visible>/<audio> are the run's 0/1 (its
#       --visible / --audio).  <title> is the name a person reads
#       ("Legends of Valhalla"); empty, the dashboard makes one from <game>.
#   rigboard_clear <emu> <slot>
#       from killgame.sh, so a stop clears the pill at once.
#   VISIBLE=$(rigboard_visible)
#       before the launch: whether the run's windows go on the desktop
#       (PAD-309) - what the caller said, else hidden for a labelled run.
#   AUDIO=$(rigboard_audio <visible> <audio>)
#       before the launch: a HIDDEN run never plays sound unless the person
#       asked for it in words (PAD_AUDIO_ASKED=1) - a sound nobody can find
#       the source of is the worst case (PAD-266).  Prints the 0/1 to use.
#
# Posting never fails a run: no board, no write, no word.

RIGBOARD_HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

#: The board as this side opens it: PAD_BOARD (the app passes it, tests set
#: it); else the Windows profile these tools live under (a checkout or an
#: install under /mnt/<d>/Users/<name>/); else ask Windows for its profile.
rigboard_dir() {
    if [ -n "${PAD_BOARD:-}" ]; then echo "$PAD_BOARD"; return 0; fi
    case "$RIGBOARD_HERE" in
        /mnt/[a-z]/Users/*/*)
            local u=${RIGBOARD_HERE#/mnt/?/Users/}
            echo "${RIGBOARD_HERE%%/Users/*}/Users/${u%%/*}/.pad-rig"
            return 0 ;;
    esac
    local w
    w=$(timeout 5 /mnt/c/Windows/System32/cmd.exe /d /c 'echo %USERPROFILE%' 2>/dev/null \
        | tr -d '\r' | tail -1)
    case "$w" in
        [A-Za-z]:\\*)
            w=$(printf '%s' "$w" | tr '\\' '/')
            echo "/mnt/$(printf %s "${w%%:*}" | tr 'A-Z' 'a-z')${w#?:}/.pad-rig" ;;
    esac
}

#: One field of a record written here (flat one-line JSON).
rigboard_field() {                  # <file> <key>
    [ -f "$1" ] || return 0
    sed -n -e "s/.*\"$2\": *\"\\([^\"]*\\)\".*/\\1/p" \
           -e "t" -e "s/.*\"$2\": *\\([0-9-][0-9]*\\).*/\\1/p" "$1" 2>/dev/null | head -1
}

#: Printable, quote-free: a record is written with printf, not a JSON library.
rigboard_clean() { printf '%s' "$1" | tr -cd "A-Za-z0-9 ._/:#+()&,!'-" | cut -c1-60; }

#: Whose run this is: the ticket.  The app's windows label themselves "PAD",
#: which says nothing on a board where every run is PAD's - so PAD_TICKET
#: (the triage app sets it on everything it launches) wins over that one.
rigboard_label() {
    local l=${PAD_LABEL:-}
    case "$l" in ""|PAD) l=${PAD_TICKET:-$l} ;; esac
    [ "$l" = PAD ] && l=
    rigboard_clean "$l"
}

rigboard_audio() {                  # <visible> <audio> -> the audio to use
    if [ "${1:-1}" = 0 ] && [ "${2:-0}" = 1 ] && [ "${PAD_AUDIO_ASKED:-0}" != 1 ]; then
        echo "note: a hidden run plays no sound - muted (PAD_AUDIO_ASKED=1 if it was asked for)" >&2
        echo 0
    else
        echo "${2:-0}"
    fi
}

#: Whether a run's windows go on the desktop, 0/1 (PAD-309). The caller's
#: word wins - PAD_VISIBLE, else PAD_HIDDEN (the one Spike 2 and the
#: sessions' rules use), and the app always says. Unsaid, a run for a ticket
#: or a session (it has a label) is HIDDEN: David, 2026-10-01, "shouldn't the
#: rigs always be headless (no window) when running?". An unlabelled one -
#: David at a terminal on his own rig - is seen, as before.
rigboard_visible() {
    case "${PAD_VISIBLE:-}" in 1) echo 1; return ;; ?*) echo 0; return ;; esac
    case "${PAD_HIDDEN:-}" in 1) echo 0; return ;; ?*) echo 1; return ;; esac
    [ -n "$(rigboard_label)" ] && echo 0 || echo 1
}

rigboard_post() {                   # <emu> <slot> <pid> <game> <title> <visible> <audio>
    local emu=$1 slot pid game=$4 title=${5:-} d f hidden=false audio=false
    slot=$(printf '%s' "${2:-0}" | tr -cd 0-9); slot=${slot:-0}
    pid=$(printf '%s' "${3:-}" | tr -cd 0-9)
    [ -n "$pid" ] && [ -n "$emu" ] || return 0
    d=$(rigboard_dir); [ -n "$d" ] || return 0
    mkdir -p "$d" 2>/dev/null || return 0
    f=$d/$emu-$slot.run
    [ "${6:-1}" = 0 ] && hidden=true
    [ "${7:-0}" = 1 ] && audio=true
    # RIGBOARD_ROOT (PAD-943): the run's work dir as its own distro sees it,
    # for a Windows reader that attaches to the run's files (the Visual
    # Pinball controller reads a Spike 1 run's s1hw.state over
    # \\wsl.localhost); Spike 2's slot-N.run has carried `root` all along.
    printf '{"emu":"%s","slot":%s,"game":"%s","title":"%s","label":"%s","distro":"%s","pid":%s,"started":%s,"hidden":%s,"audio":%s,"root":"%s"}\n' \
        "$emu" "$slot" "$(rigboard_clean "$game")" "$(rigboard_clean "$title")" \
        "$(rigboard_label)" "${WSL_DISTRO_NAME:-$(uname -n)}" "$pid" "$(date +%s)" \
        "$hidden" "$audio" "$(printf '%s' "${RIGBOARD_ROOT:-}" | tr -cd 'A-Za-z0-9._/-')" \
        > "$f.tmp" 2>/dev/null && mv -f "$f.tmp" "$f" 2>/dev/null || return 0
    # The beater.  It removes the record only while the record is still ITS
    # run's: a new run on the same rig has rewritten it with another pid.
    # Detached whole (setsid -f, stdin closed), or it dies with the wsl.exe
    # that ran the launcher (tools/bof_emu learned that).
    setsid -f bash -c '
        f=$1; p=$2; t=$3
        mine() { grep -q "\"pid\":$p," "$f" 2>/dev/null; }
        # /proc first: kill -0 says "no" for a live pid of another user.
        alive() { [ -d "/proc/$p" ] || kill -0 "$p" 2>/dev/null; }
        while alive && mine; do sleep "$t"; touch -c "$f" 2>/dev/null; done
        mine && rm -f "$f"
    ' rigboard-beat "$f" "$pid" "${RIGBOARD_BEAT_S:-10}" < /dev/null > /dev/null 2>&1
    return 0
}

rigboard_clear() {                  # <emu> <slot>
    local d
    d=$(rigboard_dir); [ -n "$d" ] || return 0
    rm -f "$d/$1-${2:-0}.run" 2>/dev/null
    return 0
}
