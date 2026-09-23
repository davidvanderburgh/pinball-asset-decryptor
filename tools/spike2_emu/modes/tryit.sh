#!/bin/bash
# tryit.sh - the rig side of the Modes tab's Try it (item 127).
#
#   tryit.sh check                 BEFORE the app builds anything: the same ownership test
#                                  install runs, and nothing else. Exit 0 and "the rig is
#                                  ready for the modes", or exit 1 with install's sentence.
#                                  A build is minutes; this is a second, so it goes first
#   tryit.sh install <stage dir>   before the run: <stage>/pad_mode.so -> $ROOT/lib/pad_mode.so
#                                  (PAD_MODE_SO=/lib/pad_mode.so), <stage>/game.port ->
#                                  $ROOT/dump/game.port, <stage>/mode*.cfg and each code mode's
#                                  <stage>/<slug>.assets (sdk/pad_mode_assets.h) -> $ROOT/dump,
#                                  after clearing the mode files, triggers and mode.log a
#                                  previous run left there. cardmodes.sh calls this too, for
#                                  the modes a CARD carries (run_game.sh, every card boot)
#   tryit.sh start [K]             start slot K now: touch $ROOT/dump/mode.start (K = 0) or
#                                  modeK.start - the runtime starts it when a game is in play
#   tryit.sh start-code <name>     start the CODE mode named now: touch $ROOT/dump/<name>.start
#                                  (its folder name, [a-z0-9_] only, the rule stop uses)
#   tryit.sh stop [NAME...]        end the running mode: touch $ROOT/dump/mode.stop, and
#                                  NAME.stop for each CODE mode named (its folder name,
#                                  [a-z0-9_] only: a code mode reads only its own trigger)
#   tryit.sh push <file> <K>       an edited mode file in as slot K while the game runs; the
#                                  runtime re-reads its files twice a second (hot reload)
#
# WHERE THE GUEST'S / IS, ASKED OF padpath.sh, which knows whose rig this is (a root
# launch's $HOME is /root, where no rig lives). Every copy lands under a temporary name
# and is renamed into place, so the running game never reads half a file - and a
# replaced object is a new inode, never one rewritten under a game that has it mapped.
# The temporary name is unique PER CALL: two pushes of one slot at once (the tab's
# hot reload and a Try it install can overlap) must not copy over each other's
# half-written file, and whichever renames last is the one the game reads.
# Paths come in as arguments, never through a shell string: wsl.exe re-parses its
# command line and a $ in it would expand on the wrong side.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$HERE/../padpath.sh"
DUMP=$ROOT/dump
LIB=$ROOT/lib

die() { echo "[tryit] $*" >&2; exit 1; }
put() {   # put <src> <dest>
    # $$ tells two scripts apart; $RANDOM tells two puts of one script apart, and
    # keeps a re-used pid (a script that ends and another that starts) from
    # meeting a temp file the first left behind after a kill.
    local t="$2.tryit.$$.$RANDOM.tmp"
    cp "$1" "$t" && mv -f "$t" "$2" || { rm -f "$t"; return 1; }
}
code_mode_name() {   # code_mode_name <name>  -> dies unless it is a plain [a-z0-9_] folder name
    case "$1" in
        # letters spelled out, not a-z: macOS's bash 3.2 matches a range by the
        # locale's collation, where a-z also takes capitals
        ""|*[!abcdefghijklmnopqrstuvwxyz0123456789_]*)
            die "a code mode's trigger name is [a-z0-9_] only, not '$1'" ;;
    esac
}
slot_name() {   # slot_name <K> <suffix>
    case "$1" in
        0) echo "mode.$2" ;;
        [1-7]) echo "mode$1.$2" ;;
        *) die "a slot is 0 to 7, not '$1'" ;;
    esac
}
#: WHO STOPS THIS ACCOUNT WRITING <dir>, printed, and 0 - or nothing, and 1, when it can.
#: The Emulate tab's Start with save states launches as root, and a first Start on a
#: machine UNPACKS the guest filesystem as root (PAD-140 met it), so its lib belongs to
#: root. Try it installs as the desktop user; cp's "Permission denied" names no remedy.
blocker() {   # blocker <dir>
    [ -w "$1" ] && [ -x "$1" ] && return 1
    echo "$1 belongs to $(stat -c %U "$1" 2>/dev/null || echo another account), not $(id -un)"
}
#: THE COMMAND THAT HANDS <dir> BACK, for the person to paste into a Windows prompt. A
#: machine with more than one distro (PAD-Runtime beside a Ubuntu) runs a bare `wsl` in
#: its DEFAULT distro, which is not always the one the rig lives in; inside WSL the
#: distro's own name is in WSL_DISTRO_NAME, so the command names it when it can.
fix_line() {   # fix_line <dir>
    if [ -n "${WSL_DISTRO_NAME:-}" ]; then
        echo "wsl -d $WSL_DISTRO_NAME -u root chown -R $(id -un):$(id -gn) $1"
    else
        echo "wsl -u root chown -R $(id -un):$(id -gn) $1"
    fi
}
#: Dies, with the sentence and the fix, when this account cannot write the two
#: directories an install writes. check and install run exactly this, so what check
#: passes install passes - the whole point of asking before a build.
refuse_if_blocked() {
    for d in "$LIB" "$DUMP"; do
        why=$(blocker "$d") && die "cannot put the modes in the emulator: $why (an emulator run" \
            "as root made it). Hand it back with: $(fix_line "$d")"
    done
    return 0
}

[ -d "$ROOT" ] || die "no guest rootfs at $ROOT - set up the emulator first"
mkdir -p "$DUMP" || die "cannot create $DUMP"
cmd=${1:-}
case "$cmd" in
    check)
        refuse_if_blocked
        echo "[tryit] the rig is ready for the modes"
        ;;
    install)
        S=${2:-}
        [ -d "$S" ] || die "no stage folder: $S"
        [ -f "$S/pad_mode.so" ] || die "the stage has no pad_mode.so"
        [ -f "$S/game.port" ] || die "the stage has no game.port"
        refuse_if_blocked
        # cardmodes.from is cardmodes.sh's marker over the files IT put here (a card's own
        # modes): they go, so its marker goes with them, and it re-writes it after an
        # install of its own. A marker left over files that are now somebody else's would
        # have a later stock run take THOSE out.
        rm -f "$DUMP"/mode.cfg "$DUMP"/mode[1-7].cfg "$DUMP"/mode.start "$DUMP"/mode[1-7].start \
              "$DUMP"/mode.stop "$DUMP"/mode.clip "$DUMP"/mode.log "$DUMP"/cardmodes.from \
              "$DUMP"/*.assets
        put "$S/pad_mode.so" "$LIB/pad_mode.so" || die "could not copy the mode object into $LIB"
        put "$S/game.port" "$DUMP/game.port" || die "could not copy the port into $DUMP"
        n=0
        for f in "$S"/mode.cfg "$S"/mode[1-7].cfg; do
            [ -f "$f" ] || continue
            put "$f" "$DUMP/$(basename "$f")" || die "could not copy $(basename "$f")"
            n=$((n + 1))
        done
        a=0
        for f in "$S"/*.assets; do       # a code mode's own assets (the build's carriers)
            [ -f "$f" ] || continue
            put "$f" "$DUMP/$(basename "$f")" || die "could not copy $(basename "$f")"
            a=$((a + 1))
        done
        # ROOT IS ELEVATION, NOT OWNERSHIP (padpath.sh, and cardmodes.sh does the same over
        # what IT installs): the Emulate tab's Start with save states is a root launch
        # carrying the desktop user's rig, so an install made through it lands root-owned,
        # and the user's next Try it, which installs as them, is refused by blocker above.
        # Only what this call put there goes back, never the directories' other contents.
        # A give-back that fails costs nothing today (the files are in place and the
        # game reads them as root), so it is said, not fatal.
        if [ "$(id -u)" = 0 ]; then
            given=("$LIB/pad_mode.so" "$DUMP/game.port")
            for f in "$DUMP"/mode.cfg "$DUMP"/mode[1-7].cfg "$DUMP"/*.assets; do
                [ -f "$f" ] && given+=("$f")
            done
            pad_give_back "${given[@]}"
            owner=$(pad_owner "$PAD_HOME") || owner=""
            if [ -n "$owner" ] && [ "$owner" != root ] && \
               [ "$(pad_owner "$LIB/pad_mode.so")" != "$owner" ]; then
                echo "[tryit] could not hand the installed files back to $owner; a Try it as" \
                    "$owner may be refused until they are: $(fix_line "$LIB")" >&2
            fi
        fi
        echo "[tryit] installed the mode object, the port, $n mode file(s) and $a code mode asset file(s) in $ROOT"
        ;;
    start)
        name=$(slot_name "${2:-0}" start) || exit 1
        touch "$DUMP/$name" || die "could not write $DUMP/$name"
        echo "[tryit] $name"
        ;;
    start-code)
        n=${2:-}
        code_mode_name "$n"
        touch "$DUMP/$n.start" || die "could not write $DUMP/$n.start"
        echo "[tryit] $n.start"
        ;;
    stop)
        shift
        for n in "$@"; do       # every name checked BEFORE anything is written
            code_mode_name "$n"
        done
        touch "$DUMP/mode.stop" || die "could not write $DUMP/mode.stop"
        echo "[tryit] mode.stop"
        for n in "$@"; do
            touch "$DUMP/$n.stop" || die "could not write $DUMP/$n.stop"
            echo "[tryit] $n.stop"
        done
        ;;
    push)
        f=${2:-}
        [ -f "$f" ] || die "no mode file: $f"
        name=$(slot_name "${3:-}" cfg) || exit 1
        put "$f" "$DUMP/$name" || die "could not copy it in as $name"
        echo "[tryit] pushed $name"
        ;;
    *)
        die "usage: tryit.sh check | install <stage> | start [K] | start-code <name> | stop [NAME...] | push <file> <K>"
        ;;
esac
