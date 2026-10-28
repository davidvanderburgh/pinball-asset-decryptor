#!/bin/bash
# riglock.sh - who holds which rig slot. The lock a session takes before it
# builds, runs, stops or mutates anything in a rig.
#
#   riglock.sh take --any <who> [what...]       first free slot >= 1; prints slot=N
#   riglock.sh take --slot N <who> [what...]    that slot or nothing
#   riglock.sh use N <who> [what...]            "I am using N now": keep mine, take it
#                                               if free or lapsed, refuse if it is
#                                               someone else's and in use
#   riglock.sh note N <what...>                 say what you are doing now
#   riglock.sh release N [<who>]                give it back (refused while a run is up)
#   riglock.sh list [--json]                    every slot: holder, doing, age, run
#   riglock.sh free                             the first free slot >= 1, or exit 1
#
# A LOCK IS A LEASE, HELD ONLY WHILE THE RIG IS IN USE (David, 2026-09-27: "it
# only locks when it is ACTIVELY using it"). A held slot is RUNNING while a run
# is up in it, ACTIVE for PAD_LOCK_IDLE seconds (default 300) after its holder
# last used it - a run ending, a rig command, a note - and LAPSED after that.
# A lapsed lock is CLEARED - by every take, use, free and list, and by the
# app's and the triage dashboard's reads of the board - and the holder's own
# next rig command takes the slot straight back if nobody else did
# (watch.sh, killgame.sh and restorestate.sh call `use` before they act - see
# pad_slot_use in padpath.sh). So a session never has to remember to release,
# and a ticket that was merged, or a window that was killed, holds nothing
# five minutes later.
#
# <who> names the holder the way every window of its run will: the item branch
# (item/48), the triage ticket (PAD-231) or the feature branch. <what> is a few
# words for what is UP right now - "godzilla run", "build", "app" - because
# that is what the next session and David's dashboard need to read.
#
# RUN IT AS ROOT TO TAKE A SLOT >= 1 (`wsl -u root -e bash riglock.sh take
# ...`): taking the slot also mounts its rootfs, which is an overlay and needs
# root (see padpath.sh, "RIG SLOTS"). As the plain user it still takes the
# lock and prints the one line that mounts the slot.
#
# THE RECORDS ARE ON THE WINDOWS SIDE (%USERPROFILE%\.pad-rig\slot-N.lock) so
# the app, the triage dashboard and a rig in any WSL distro all read the same
# ones - see pad_board_dir. Creation is `set -C` (O_EXCL), atomic on drvfs as
# on ext4: two sessions racing for one slot get one winner and one refusal.
#
# SLOT 0 IS THE ORDINARY RIG (~/spike2root), and the pre-slot lock file
# /home/<user>/.pad_rig_lock still means "slot 0 is held". Sessions that
# predate slots only know that file, so a slot 0 take writes both and a slot
# 0 listing reads both.
. "$(dirname "$0")/padpath.sh"
set -u

BOARD=$(pad_board_dir)
LEGACY=$PAD_HOME/.pad_rig_lock
# A run record older than this without a heartbeat is a run that died hard.
RUN_FRESH=${PAD_RUN_FRESH:-120}
# A held slot nobody has used for this long has LAPSED (see the top).
IDLE=${PAD_LOCK_IDLE:-300}

die() { echo "riglock: $*" >&2; exit 1; }
clean() { printf '%s' "$*" | tr -d '"\\\r\n' | tr -cd '[:print:]' | cut -c1-80; }
now() { date +%s; }
lockf() { echo "$BOARD/slot-$1.lock"; }
runf() { echo "$BOARD/slot-$1.run"; }
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }   # GNU, then BSD/macOS

valid_slot() {
    case "$1" in ''|*[!0-9]*) die "not a slot number: '$1'" ;; esac
    [ "$1" -le "$PAD_SLOTS_MAX" ] || die "slot $1 is past this machine's $PAD_SLOTS_MAX (PAD_SLOTS_MAX)"
}

# Is a run up in slot N? Two witnesses, because each is blind somewhere: the
# board's run record (heartbeat) sees a run in ANY distro and one started as
# root, which this account may not be able to see in /proc; alive.sh sees a
# run that died without its teardown and left processes behind.
run_up() {
    local f
    f=$(runf "$1")
    if [ -f "$f" ] && [ $(( $(now) - $(mtime "$f") )) -lt "$RUN_FRESH" ]; then
        return 0
    fi
    [ "$(PAD_SLOT=$1 bash "$RIG/alive.sh" --total 2>/dev/null || echo 0)" != 0 ]
}

write_lock() {                    # <slot> <who> <what> <taken> -> stdout JSON
    printf '{"slot":%s,"who":"%s","what":"%s","distro":"%s","user":"%s","taken":%s}\n' \
        "$1" "$2" "$3" "$(clean "${WSL_DISTRO_NAME:-$(uname -n)}")" \
        "$(clean "${SUDO_USER:-$(id -un 2>/dev/null)}")" "$4"
}

held() {                          # <slot> -> 0 if held (any form)
    [ -f "$(lockf "$1")" ] && return 0
    [ "$1" = 0 ] && [ -f "$LEGACY" ] && return 0
    return 1
}

last_use() {                      # <slot> -> epoch: the newest of lock, legacy file, run record
    local m=0 x p
    for p in "$(lockf "$1")" "$(runf "$1")"; do
        [ -f "$p" ] || continue
        x=$(mtime "$p"); [ "$x" -gt "$m" ] && m=$x
    done
    if [ "$1" = 0 ] && [ -f "$LEGACY" ]; then
        x=$(mtime "$LEGACY"); [ "$x" -gt "$m" ] && m=$x
    fi
    echo "$m"
}

# Is slot N being USED - by what it is running, not by what the machine is?
# The run record is the witness everywhere. alive.sh's process count is asked
# only for slots >= 1: on slot 0 it also counts every process whose
# environment this account cannot read (another account's run in ANY slot -
# padslot.sh), so it would keep slot 0's lease alive for somebody else's run.
running() {                       # <slot>
    local f
    f=$(runf "$1")
    if [ -f "$f" ] && [ $(( $(now) - $(mtime "$f") )) -lt "$RUN_FRESH" ]; then
        return 0
    fi
    [ "$1" != 0 ] || return 1
    [ "$(PAD_SLOT=$1 bash "$RIG/alive.sh" --total 2>/dev/null || echo 0)" != 0 ]
}

state() {                         # <slot> -> free | running | active | lapsed
    held "$1" || { echo free; return 0; }
    if running "$1"; then echo running
    elif [ $(( $(now) - $(last_use "$1") )) -lt "$IDLE" ]; then echo active
    else echo lapsed; fi
}

# Take a LAPSED slot's lock away from its old holder. The rename is the atomic
# step: of two sessions seizing one slot, one moves the file and the other finds
# nothing to move. The moved file is judged again, because its holder may have
# used the slot between our look and our move: then it goes back.
seize() {                         # <slot> -> 0 if the slot is now unheld
    local f tmp prev
    f=$(lockf "$1"); tmp="$f.seize.$$"
    if [ -f "$f" ]; then
        mv "$f" "$tmp" 2>/dev/null || return 1
        if [ $(( $(now) - $(mtime "$tmp") )) -lt "$IDLE" ] || running "$1"; then
            ( set -C; cat "$tmp" > "$f" ) 2>/dev/null
            rm -f "$tmp"
            return 1
        fi
        prev=$(pad_board_field "$tmp" who)
        rm -f "$tmp"
        echo "riglock: slot $1 was ${prev:-somebody}'s, unused for $(age "$IDLE")+ - lapsed, cleared" >&2
    fi
    [ "$1" = 0 ] && rm -f "$LEGACY"
    return 0
}

take_one() {                      # <slot> <who> <what>
    local f t
    f=$(lockf "$1")
    t=$(now)
    if held "$1"; then
        [ "$(state "$1")" = lapsed ] || return 1
        seize "$1" || return 1
    fi
    # shellcheck disable=SC2094
    if ! ( set -C; write_lock "$1" "$2" "$3" "$t" > "$f" ) 2>/dev/null; then
        return 1
    fi
    if [ "$1" = 0 ]; then
        # The pre-slot protocol's file, same atomic create. Losing THAT race
        # means an old-protocol session got slot 0 first: give ours back.
        if ! ( set -C; echo "$2 $3" > "$LEGACY" ) 2>/dev/null; then
            rm -f "$f"
            return 1
        fi
        pad_give_back "$LEGACY"
    fi
    return 0
}

# LAPSED LOCKS ARE CLEARED, not only shown as lapsed (David, 2026-09-27: the
# tickets must "auto-clear them themselves when they are not in use"). Every
# take, use, free and list sweeps them first, and so do the app's and the
# triage dashboard's reads of the board (core/rigslot.py, pad-triage
# rigboard.py) - the dashboard polls all day, so an unused lock is gone within
# seconds of lapsing whether or not any session runs this script.
sweep() {
    local n
    for n in $(seq 0 "$PAD_SLOTS_MAX"); do
        held "$n" && [ "$(state "$n")" = lapsed ] && seize "$n"
    done
    return 0
}

# THE BOARD HAS TO BE WRITABLE BY WHOEVER IS ASKING. A root run (the app's
# Emulate tab, a `wsl -u root` take) that makes the board leaves it root's, and
# a plain-user take after it could create no lock at all - and said "every
# slot is in use" under a table of free ones (PAD-803, from the Visual Pinball
# launcher). So root hands a board it touches back to the human, and a board
# that still cannot be written is said to be the problem, not the slots.
board_ready() {
    mkdir -p "$BOARD" || die "cannot create the board at $BOARD"
    pad_give_back "$BOARD"
    [ -w "$BOARD" ] && return 0
    die "cannot write the board at $BOARD (it is $(stat -c %U "$BOARD" 2>/dev/null || echo "another account")'s, and this is $(id -un 2>/dev/null)) - a run as root made it; fix once with: sudo chown $(id -un 2>/dev/null) '$BOARD'"
}

mount_hint() {
    local n=$1
    [ "$n" = 0 ] && return 0
    if [ "$(id -u)" = 0 ]; then
        PAD_SLOT=$n bash -c ". '$RIG/padpath.sh'; pad_slot_ready" || return 1
    elif ! mountpoint -q "$PAD_HOME/padslots/$n/root" 2>/dev/null; then
        echo "riglock: slot $n is yours but not mounted yet. Mount it (root, once per WSL boot):" >&2
        echo "  wsl -u root -e bash $RIG/slot.sh up $n" >&2
    fi
}

cmd_take() {
    local slot="" who what n
    case "${1:-}" in
        --any) shift ;;
        --slot) valid_slot "${2:-}"; slot=$2; shift 2 ;;
        *) die "take needs --any or --slot N" ;;
    esac
    who=$(clean "${1:-}")
    [ -n "$who" ] || who=$(pad_label)
    [ -n "$who" ] || die "take needs <who>: the item, ticket or branch this is for"
    shift || true
    what=$(clean "${*:-}")
    board_ready
    sweep
    if [ -n "$slot" ]; then
        take_one "$slot" "$who" "$what" || { cmd_show "$slot" >&2; die "slot $slot is held"; }
        echo "slot=$slot"
        mount_hint "$slot"
        return
    fi
    # Free slots first; a lapsed one only when none is free, so a holder who
    # stepped away for a while usually finds its slot (and what it built and
    # saved in it) still there when it comes back.
    for n in $(seq 1 "$PAD_SLOTS_MAX"); do
        held "$n" && continue
        take_one "$n" "$who" "$what" && { echo "slot=$n"; mount_hint "$n"; return; }
    done
    for n in $(seq 1 "$PAD_SLOTS_MAX"); do
        take_one "$n" "$who" "$what" && { echo "slot=$n"; mount_hint "$n"; return; }
    done
    cmd_list >&2
    die "every slot 1..$PAD_SLOTS_MAX is in use"
}

# "I am using slot N now" - what watch.sh, killgame.sh and restorestate.sh say
# (pad_slot_use in padpath.sh) before they touch a slot. Mine: the lease is
# renewed. Free or lapsed: it is mine now. Someone else's and in use: refused,
# because a Stop or a restore there would land on their run.
cmd_use() {
    local n=${1:-} who cur what
    valid_slot "$n"
    who=$(clean "${2:-}")
    [ -n "$who" ] || die "use needs <who>: the item, ticket or branch this is for"
    shift 2
    what=$(clean "${*:-in use}")
    cur=$(pad_board_field "$(lockf "$n")" who)
    if [ -n "$cur" ] && [ "$cur" = "$who" ]; then
        touch -c "$(lockf "$n")" 2>/dev/null
        [ "$n" = 0 ] && touch -c "$LEGACY" 2>/dev/null
        return 0
    fi
    board_ready
    sweep
    if take_one "$n" "$who" "$what"; then
        echo "riglock: slot $n is $who's now (it was free)" >&2
        return 0
    fi
    cmd_show "$n" >&2
    die "slot $n is ${cur:-held}'s and in use - take one of your own: riglock.sh take --any $who"
}

cmd_note() {
    local n=${1:-} f who taken
    valid_slot "$n"
    shift
    f=$(lockf "$n")
    [ -f "$f" ] || die "slot $n is not held"
    who=$(pad_board_field "$f" who)
    taken=$(pad_board_field "$f" taken)
    write_lock "$n" "$who" "$(clean "$*")" "${taken:-$(now)}" > "$f.tmp" && mv -f "$f.tmp" "$f"
    [ "$n" = 0 ] && [ -f "$LEGACY" ] && echo "$who $(clean "$*")" > "$LEGACY"
    return 0
}

cmd_release() {
    local n=${1:-} who=${2:-} f cur force=0
    [ "${3:-}" = --force ] && force=1
    [ "$who" = --force ] && { force=1; who=; }
    valid_slot "$n"
    f=$(lockf "$n")
    cur=$(pad_board_field "$f" who)
    if [ -n "$who" ] && [ -n "$cur" ] && [ "$(clean "$who")" != "$cur" ]; then
        die "slot $n is held by '$cur', not '$who' - release only your own"
    fi
    if [ "$force" = 0 ] && run_up "$n"; then
        die "a run is still up in slot $n - stop it first (PAD_SLOT=$n killgame.sh), or --force"
    fi
    rm -f "$f"
    [ "$n" = 0 ] && rm -f "$LEGACY"
    echo "released slot $n"
}

age() {                           # seconds -> "5s" "12m" "3h"
    local s=$1
    if [ "$s" -lt 60 ]; then echo "${s}s"
    elif [ "$s" -lt 3600 ]; then echo "$((s / 60))m"
    else echo "$((s / 3600))h$(( (s % 3600) / 60 ))m"; fi
}

cmd_show() {                      # one human line for slot N
    local n=$1 f r who what t lage run="-" game rt st
    f=$(lockf "$n"); r=$(runf "$n"); t=$(now)
    who=$(pad_board_field "$f" who); what=$(pad_board_field "$f" what)
    if [ -z "$who" ] && [ "$n" = 0 ] && [ -f "$LEGACY" ]; then
        who=$(cut -d' ' -f1 < "$LEGACY"); what=$(cut -d' ' -f2- < "$LEGACY"); f=$LEGACY
    fi
    if [ -f "$r" ]; then
        game=$(pad_board_field "$r" game)
        rt=$(( t - $(mtime "$r") ))
        st=$(pad_board_field "$r" started)
        if [ "$rt" -lt "$RUN_FRESH" ]; then run="$game up $(age $(( t - ${st:-$t} )))"
        else run="$game STALE (no heartbeat for $(age "$rt"))"; fi
    fi
    if [ -n "$who" ]; then
        case "$(state "$n")" in
            running) lage="running" ;;
            active) lage="idle $(age $(( t - $(last_use "$n") )))" ;;
            *) lage="LAPSED"; who="($who)" ;;
        esac
    else lage=""; who="(free)"; fi
    printf '%-4s %-22s %-24s %-9s %s\n' "$n" "$who" "${what:-}" "$lage" "$run"
}

cmd_list() {
    local n
    sweep
    if [ "${1:-}" = --json ]; then
        printf '{"board":"%s","max":%s,"now":%s,"slots":[' "$BOARD" "$PAD_SLOTS_MAX" "$(now)"
        for n in $(seq 0 "$PAD_SLOTS_MAX"); do
            [ "$n" = 0 ] || printf ','
            printf '{"slot":%s,"lock":%s,"lock_mtime":%s,"run":%s,"run_mtime":%s,"state":"%s","last_use":%s,"idle_limit":%s}' "$n" \
                "$( [ -f "$(lockf "$n")" ] && tr -d '\n' < "$(lockf "$n")" || echo null)" \
                "$(mtime "$(lockf "$n")")" \
                "$( [ -f "$(runf "$n")" ] && tr -d '\n' < "$(runf "$n")" || echo null)" \
                "$(mtime "$(runf "$n")")" "$(state "$n")" "$(last_use "$n")" "$IDLE"
        done
        echo ']}'
        return
    fi
    printf '%-4s %-22s %-24s %-9s %s\n' SLOT HOLDER DOING STATE RUN
    for n in $(seq 0 "$PAD_SLOTS_MAX"); do cmd_show "$n"; done
}

cmd_free() {                      # a free slot, else a lapsed one
    local n
    sweep
    for n in $(seq 1 "$PAD_SLOTS_MAX"); do
        held "$n" || { echo "$n"; return 0; }
    done
    for n in $(seq 1 "$PAD_SLOTS_MAX"); do
        [ "$(state "$n")" = lapsed ] && { echo "$n"; return 0; }
    done
    return 1
}

case "${1:-}" in
    take) shift; cmd_take "$@" ;;
    use) shift; cmd_use "$@" ;;
    note) shift; cmd_note "$@" ;;
    release) shift; cmd_release "$@" ;;
    list|"") shift || true; cmd_list "$@" ;;
    show) valid_slot "${2:-}"; cmd_show "$2" ;;
    free) cmd_free ;;
    *) sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
