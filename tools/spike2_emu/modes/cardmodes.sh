#!/bin/bash
# cardmodes.sh - EMULATING A CARD RUNS ITS OWN MODES (the item 149 family follow-up).
#
#   cardmodes.sh <card.raw>        called by run_game.sh before every boot; by hand it
#   cardmodes.sh ""                is safe too (it only ever touches $ROOT/lib/pad_mode.so
#                                  and the mode files in $ROOT/dump)
#
# ON A MACHINE a card that carries modes of our own loads them itself: the hook in its
# /etc/init.d/game_monitor (modehook.py) preloads /usr/local/padmode/mode.so into the game,
# and the object reads game.port and mode.cfg, mode1.cfg .. mode7.cfg beside it
# (mode_install.py lays them out on the rootfs partition, p2); a CODE mode compiled into the object
# has a <slug>.assets beside it instead (sdk/pad_mode_assets.h). THE RIG NEVER RUNS A CARD'S
# BOOT CHAIN - it execs ./game directly - so until this script a card with modes booted here
# with no runtime at all. And a mode's screen is authored VISIBLE and hidden by the runtime
# (plugins/stern/scene_write.py), so that boot showed every mode's panel over the HUD all
# game: a picture the machine never shows.
#
# So the rig asks the card, the way the boot selector asks it for its menu and its media
# (run_game.sh, parts.py --rootfs-dir: debugfs, no mount, no root): /usr/local/padmode is
# pulled out of the card's rootfs into a throwaway stage and put in the guest by
# modes/tryit.sh install - the ONE installer, the same one the Modes tab's Try it and the
# Emulate tab's override set use (object into $ROOT/lib, port and mode files into $ROOT/dump,
# each under a temporary name and renamed, after clearing what a previous run left). The card
# calls the object mode.so; the stage wants pad_mode.so, so it is renamed on the way.
#
# WHAT IT ANSWERS: the LAST LINE ON STDOUT is the guest path to preload (run_game.sh exports
# it as PAD_MODE_SO), or there is no stdout at all and the run is what it always was.
# Everything said to a human goes to stderr as "[modes] ...", which lands in the run's log;
# watch.sh republishes those lines on its own stdout, which is what the Emulate tab shows.
#
# THE RULES
#   * PAD_MODE_SO ALREADY SET WINS. The project's override set (Emulate tab, item 149), the
#     Modes tab's Try it and a run scripted by hand all name their own runtime and have put
#     their own files in the guest. The card's modes are left out, one line says so, and
#     NOTHING in the guest is touched.
#   * PAD_CARD_MODES=0 opts out: the card is not asked at all.
#   * A CARD WITHOUT /usr/local/padmode IS TODAY'S RUN: no output, no files, no line.
#   * A card whose game_monitor does not load the object would not run its modes on a
#     machine either, so it does not here: emulating a card means what booting it means.
#   * A MULTI-BOOT CARD HAS ONE ROOTFS, the primary's, so its /usr/local/padmode is image 0's
#     set. Since PAD-226 the build carries every OTHER image's set to
#     /usr/local/codeselect/modes/img<N>/ and the machine's select.sh binds the booted image's
#     set (or modes/none) over /usr/local/padmode. PAD_CARD_IMAGE=<N> asks for that image the
#     same way: run_game.sh asks again once its menu has chosen image N. On a card with a
#     modes/ directory an image with no img<N> runs NO modes (not the primary's); a card
#     built before per-image modes has no such directory and every image gets the primary's
#     set, exactly as that card behaves on a machine.
#   * NOTHING LEAKS INTO A LATER RUN. An install of ours leaves a marker beside the files
#     ($ROOT/dump/cardmodes.from). A later run that installs nothing - a stock card, an
#     extracted title, the opt-out - finds the marker and takes those files out again.
#     tryit.sh install removes the marker with the files it replaces, so the marker only
#     ever describes files this script put there. No marker: nothing is removed, ever.
#   * IT NEVER STOPS A RUN. The card asked for this, nobody typed it (the boot selector's
#     rule, run_game.sh): a card that cannot be read, or a guest this account cannot write
#     to, is a line in the log and the boot the rig has always done.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$HERE/../padpath.sh"
CARD=${1:-}
IMAGE=${PAD_CARD_IMAGE:-0}
case "$IMAGE" in ''|*[!0-9]*) IMAGE=0 ;; esac
MODES_DIR=/usr/local/codeselect/modes     # PAD-226: images 1..N's own sets on a multi-boot card
DUMP=$ROOT/dump
MARK=$DUMP/cardmodes.from
CARD_DIR=/usr/local/padmode
HOOK="LD_PRELOAD=$CARD_DIR/mode.so"
OBJECT=/lib/pad_mode.so                 # where tryit.sh install puts it, as the guest sees it

say() { echo "[modes] $*" >&2; }

# What an earlier install OF OURS left, taken out again - and only that (see the marker rule).
forget() {
    [ -f "$MARK" ] || return 0
    rm -f "$DUMP"/mode.cfg "$DUMP"/mode[1-7].cfg "$DUMP/game.port" \
          "$DUMP"/mode.start "$DUMP"/mode[1-7].start "$DUMP/mode.stop" "$DUMP/mode.clip" \
          "$DUMP/mode.log" "$DUMP"/*.assets "$DUMP/stock.cfg" "$DUMP/clips.cfg" "$MARK" 2>/dev/null
    return 0
}

# "name   ATOMIC BREATH" -> ATOMIC BREATH, one per mode file, in slot order, then one per code
# mode's <slug>.assets (in slug order), comma separated.
names_of() {   # names_of <dir>
    local f n out=""
    for f in "$1"/mode.cfg "$1"/mode[1-7].cfg "$1"/*.assets; do
        [ -f "$f" ] || continue
        n=$(tr -d '\r' < "$f" | awk '$1 == "name" { $1 = ""; sub(/^[ \t]+/, ""); print; exit }')
        [ -n "$n" ] || n=$(basename "$f")
        out="${out:+$out, }$n"
    done
    echo "$out"
}
count_of() {   # count_of <dir>
    local f n=0
    for f in "$1"/mode.cfg "$1"/mode[1-7].cfg "$1"/*.assets; do [ -f "$f" ] && n=$((n + 1)); done
    echo "$n"
}

if [ "${PAD_CARD_MODES:-1}" = 0 ]; then
    [ -n "${PAD_MODE_SO:-}" ] || forget
    [ -n "$CARD" ] && say "PAD_CARD_MODES=0: the card is not asked for modes of its own"
    exit 0
fi
if [ -z "$CARD" ] || [ ! -f "$CARD" ]; then
    [ -n "${PAD_MODE_SO:-}" ] || forget
    exit 0
fi

STAGE=$(mktemp -d "${TMPDIR:-/tmp}/padcardmodes.XXXXXX" 2>/dev/null) || {
    say "no temporary folder to read the card's modes into: this run boots without them"
    exit 0
}
trap 'rm -rf "$STAGE"' EXIT

# Absent is not an error and says nothing: parts.py prints the folder it made, or nothing.
WHO="this card"
S=""
if [ "$IMAGE" != 0 ]; then
    # IMAGE N OF A MULTI-BOOT CARD (PAD-226): its own set, when the card keeps per-image sets
    python3 "$RIG/parts.py" --rootfs-dir "$MODES_DIR" "$STAGE" "$CARD" >/dev/null 2>&1
    if [ -d "$STAGE/modes" ]; then
        if [ ! -f "$STAGE/modes/img$IMAGE/mode.so" ]; then
            [ -n "${PAD_MODE_SO:-}" ] || forget
            say "image $IMAGE of this card runs no custom modes of its own (the primary's stay with the primary)"
            exit 0
        fi
        S=$STAGE/modes/img$IMAGE
        WHO="image $IMAGE of this card"
    fi
fi
if [ -z "$S" ]; then
    python3 "$RIG/parts.py" --rootfs-dir "$CARD_DIR" "$STAGE" "$CARD" >/dev/null 2>&1
    S=$STAGE/padmode
fi
if [ ! -f "$S/mode.so" ]; then
    [ -n "${PAD_MODE_SO:-}" ] || forget
    exit 0
fi
N=$(count_of "$S")
NAMES=$(names_of "$S")
WHAT="$N mode(s) of its own${NAMES:+ ($NAMES)}"
# PAD-446: clips.cfg (clips that play one of several at random) is a reason of its own to run
# the object: a card whose only change of that kind is its random clips has no mode file
CLIPS=0
[ -f "$S/clips.cfg" ] && CLIPS=$(grep -c "^clip	" "$S/clips.cfg" 2>/dev/null)
case "$CLIPS" in ''|*[!0-9]*) CLIPS=0 ;; esac
if [ "$CLIPS" != 0 ]; then
    if [ "$N" = 0 ]; then WHAT="$CLIPS clip(s) that play one of several at random"
    else WHAT="$WHAT and $CLIPS clip(s) that play one of several at random"; fi
fi

if ! python3 "$RIG/parts.py" --rootfs-file /etc/init.d/game_monitor "$CARD" 2>/dev/null \
        | grep -qF "$HOOK"; then
    [ -n "${PAD_MODE_SO:-}" ] || forget
    say "$WHO holds $WHAT, but the card's game_monitor does not load them:"
    say "  a machine would not run them either, so this run does not"
    exit 0
fi
if [ -n "${PAD_MODE_SO:-}" ]; then
    say "$WHO carries $WHAT, and this run brings a mode runtime of its own" \
        "(PAD_MODE_SO=$PAD_MODE_SO): that one runs, the card's own modes are left out"
    exit 0
fi
if [ ! -f "$S/game.port" ] || { [ "$N" = 0 ] && [ "$CLIPS" = 0 ]; }; then
    forget
    say "$WHO carries a mode object but no $([ -f "$S/game.port" ] && echo "mode file" || echo "port file") beside it:"
    say "  nothing the emulator can run. This run boots without it"
    exit 0
fi

mv "$S/mode.so" "$S/pad_mode.so"
if ! said=$(bash "$HERE/tryit.sh" install "$S" 2>&1); then
    forget
    say "$WHO carries $WHAT, and they could NOT be put in the emulator:"
    printf '%s\n' "$said" | sed 's/^/[modes]   /' >&2
    say "  this run boots WITHOUT them (their screens may sit over the game's own)"
    exit 0
fi
{ echo "card=$CARD"; echo "image=$IMAGE"; echo "modes=$N"; } > "$MARK" 2>/dev/null
# ROOT IS ELEVATION, NOT OWNERSHIP (padpath.sh): the app's Start is a root launch carrying the
# desktop user's rig, and what it installs goes back to that user so a later Try it of theirs
# can replace it. A failure here costs nothing: tryit.sh removes by directory, not by owner.
if [ "$(id -u)" = 0 ]; then
    _o=$(stat -c %U "$PAD_HOME" 2>/dev/null)
    [ -n "$_o" ] && [ "$_o" != root ] && chown "$_o" "$ROOT$OBJECT" "$DUMP/game.port" \
        "$DUMP"/mode.cfg "$DUMP"/mode[1-7].cfg "$DUMP"/*.assets "$DUMP"/stock.cfg "$DUMP"/clips.cfg "$MARK" 2>/dev/null
fi
say "$WHO carries $WHAT: their runtime runs in this game, as on the machine"
echo "$OBJECT"
