#!/bin/bash
# rigjob.sh - what a rigbatch JOB is made of: boot a build in this rig, drive it in the GAME'S time, say one
# VERDICT, leave the rig clean. Sourced, not run.
#
#   #!/bin/bash
#   . "$(dirname "$0")/rigjob.sh"            # a job beside the rig's scripts; `. "$RIG/rigjob.sh"` from anywhere
#   job_begin "$1" "$2"                      # <key> <card>: in the rig rigbatch gave (PAD_SLOT), stopped if left running
#   job_boot                                 # the run - hidden, muted, off the cached card - in the background
#   job_wait_attract || job_fail "$JOB_WHY"  # until the attract show (a first boot's Guided Setup left on the way)
#   job_press 60; job_sleep 3                # a switch (its id in the title's switch list); a wait in the game's time
#   job_start_game || job_fail "$JOB_WHY"    # credits + Start + the launch: a ball in play, or 1
#   job_wait_log "$DUMP/mode.log" 'armed:' 20 || job_fail "$JOB_WHY"   # a line the game or the runtime prints
#   job_shot "$JOB_OUT/frame.png"            # the rendered frame (glshot.sh)
#   job_pass "what was seen"                 # or job_fail "why": the VERDICT line, the rig stopped, exit
#
# WHY (PAD-649). Every sweep job so far was written from scratch (PAD-420's, PAD-641's, PAD-643's, PAD-645's), and
# each paid again for the same lessons: a `sleep` that is the wall's while rigbatch runs the game at 4x; a loop
# waiting 600 s for a line a dead run would never print (10-17 minutes a failing build); Guided Setup on a title's
# first boot in a fresh rig, handled by a copy of a script in C:\tmp; a Start the game ignored because its scenes
# were still loading. The library has them once. Everything that MODELS the game's time (a hand between two
# presses, a ball in play, a deadline for a line the game prints) is in game seconds and gets shorter by
# rigbatch's --speed; a wait FOR a state (boot to attract) is on the wall, because that is the CPU's time - and
# every wait ends the moment the run dies, with JOB_WHY saying how.
#
# After job_begin a job may read: KEY, CARD, GAME (the key's title: `godzilla_pro-1.16` -> `godzilla_pro`), ROOT
# (the slot's rootfs), DUMP ($ROOT/dump: the shim's and the runtime's files), LIST (this title's switch list, once
# mktables has written it), JOB_OUT (the job's folder: watch.log, timeline.txt, killgame.txt, its pictures; set it
# before job_begin to put them elsewhere), JOB_WHY (why the last job_* said no), JOB_ATTRACT_S / JOB_GAME_S (when
# attract / a game came, seconds from job_begin). job_say "<text>" goes to the timeline and stdout; job_elapsed
# prints the seconds since job_begin; job_state is status.sh's state word; job_alive the rig's process count.
#
# A job that ends any other way than job_pass / job_fail - an error under set -e, rigbatch's --job-cap - still
# stops the rig and prints a VERDICT fail saying so (job_cleanup, on EXIT).
RIG=${RIG:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}
. "$RIG/padpath.sh"
set -u

JOB_T0=0 JOB_WHY="" JOB_WPID="" JOB_DONE="" JOB_ATTRACT_S="" JOB_GAME_S=""
JOB_OUT=${JOB_OUT:-}

job_elapsed() { echo $(( $(date +%s) - JOB_T0 )); }
job_say() { echo "$(date +%T) +$(job_elapsed)s $*" | tee -a "$JOB_OUT/timeline.txt"; }
job_alive() { bash "$RIG/alive.sh" --total 2>/dev/null < /dev/null | tail -1; }
job_state() { bash "$RIG/status.sh" 2>/dev/null < /dev/null | sed -n 's/^state=//p' | head -1; }
#: the run is gone: watch.sh has ended and nothing of the rig is left running
job_dead() {
    [ -n "$JOB_WPID" ] && kill -0 "$JOB_WPID" 2>/dev/null && return 1
    [ "$(job_alive)" = 0 ]
}
#: the rig's own last word on how a run ended (bootcheck.sh's filter: report lines only, not echoed program text)
job_died_why() {
    grep -aE '^\[(watch|segv|run|card)\] ' "$JOB_OUT/watch.log" 2>/dev/null | grep -av '^\[watch\] cfg' \
        | grep -aiE 'watchdog|segv|refus|cannot|fail|died|never|stopped responding' \
        | grep -av 'segv\]   ' | tail -1 | cut -c1-200
}

job_begin() {                     # <key> <card>
    KEY=${1:?job_begin <key> <card>}; CARD=${2:?job_begin <key> <card>}
    GAME=${KEY%-*}
    DUMP=$ROOT/dump
    LIST=$DUMP/tables/$GAME/switch_list.txt
    JOB_OUT=${JOB_OUT:-$PAD_LOGDIR/rigjob.$KEY}
    rm -rf "$JOB_OUT"; mkdir -p "$JOB_OUT"
    JOB_T0=$(date +%s)
    # the card read in place through the cache (rigbatch's PAD_CARD_CACHE=1; 0 = where it lies), no sound, no
    # playfield window, no game window on the desktop (PAD-230; PAD_HIDDEN=0 to watch one)
    export PAD_CARD=$CARD PAD_CARD_CACHE=${PAD_CARD_CACHE:-1} PAD_AUDIO=0
    export PAD_PLAYFIELD=${PAD_PLAYFIELD:-0} PAD_HIDDEN=${PAD_HIDDEN:-1}
    unset PAD_GAME PAD_CARD_IMAGE
    trap job_cleanup EXIT
    trap 'exit 143' TERM
    trap 'exit 130' INT
    if [ "$(job_alive)" != 0 ]; then
        job_say "a run was left in rig ${PAD_SLOT:-0}: stopping it first"
        (cd "$RIG" && bash killgame.sh) > /dev/null 2>&1 < /dev/null
    fi
    job_say "rig ${PAD_SLOT:-0} ($ROOT): $KEY off $CARD, x${PAD_SPEED:-1} once in attract"
}

job_boot() {                      # [minutes the run may last, default 30]
    local mins=${1:-30}
    setsid bash "$RIG/watch.sh" "$mins" > "$JOB_OUT/watch.log" 2>&1 < /dev/null &
    JOB_WPID=$!
    disown "$JOB_WPID" 2>/dev/null
    job_say "run started (watch.sh $mins; $JOB_OUT/watch.log)"
}

#: Guided Setup, a title's first boot in a fresh rig (modes/gamecheck.sh's walk): the red row down with SERVICE
#: PLUS until the last row, Save & Exit, is the red one (menurow.py reads a glshot.sh frame), then SERVICE SELECT.
#: job_guided_setup <backs>: a row's EDITOR is not the menu; up to <backs> SERVICE BACKs close it first.
#: 0 = Save & Exit was pressed; 1 = not that menu (or no switch list yet).
job_guided_setup() {
    [ -s "$LIST" ] || return 1
    LIST=$LIST bash "$RIG/guidedsetup.sh" "${1:-0}" < /dev/null
}

#: job_wait_attract [wall seconds, default 300]: until status.sh says attract (the game's own light show,
#: gamestate.sh). On the WALL, not the game's clock: the boot is the CPU-bound part and runs at 1x (PAD-484; the
#: speed is asked for from attract). 1 the moment the run dies, or at the deadline - JOB_WHY says which. A title's
#: first boot in a fresh rig opens Guided Setup, which nothing leaves by itself: from 45 s in, every 20 s (a look
#: that finds no menu costs ~3 s), the menu is looked for and left.
job_wait_attract() {
    local deadline=${1:-300} t0 st el next=45
    t0=$(date +%s)
    while :; do
        st=$(job_state)
        case "$st" in
            attract|running)
                JOB_ATTRACT_S=$(job_elapsed)
                job_say "attract at ${JOB_ATTRACT_S}s (state=$st)"
                return 0 ;;
        esac
        if job_dead; then
            JOB_WHY="the run ended by itself at $(job_elapsed)s: $(job_died_why)"
            job_say "$JOB_WHY"; return 1
        fi
        el=$(( $(date +%s) - t0 ))
        if [ "$el" -ge "$deadline" ]; then
            JOB_WHY="no attract in ${deadline}s (state=${st:-?})"
            job_say "$JOB_WHY"; return 1
        fi
        if [ "$el" -ge "$next" ] && [ -s "$LIST" ]; then
            next=$((el + 20))
            job_guided_setup 0 && job_say "first boot: left Guided Setup by Save & Exit"
        fi
        sleep 3
    done
}

job_press() {                     # <switch id> [ms, default 150]
    python3 "$RIG/swpoke.py" "${1:?job_press <switch-id> [ms]}" "${2:-150}" > /dev/null 2>&1 < /dev/null \
        || job_say "swpoke $1 failed"
}
job_sleep() { pad_gsleep "${1:?job_sleep <game seconds>}"; }

#: job_wait_log <file> <regex> [game seconds, default 30]: 0 when a line matches; 1 the moment the run dies or at
#: the deadline (a deadline in the GAME'S seconds: a line the game prints N seconds after a press comes N/k
#: seconds of the wall later at speed k)
job_wait_log() {
    local f=$1 re=$2 gs=${3:-30} end
    end=$(awk -v s="$gs" -v k="$(pad_speed)" -v t="$(date +%s)" \
          'BEGIN { if (k + 0 <= 0) k = 1; printf "%d", t + s / k + 1 }')
    while :; do
        grep -aEq -- "$re" "$f" 2>/dev/null && return 0
        job_dead && { JOB_WHY="the run ended while waiting for '$re': $(job_died_why)"; return 1; }
        [ "$(date +%s)" -ge "$end" ] && { JOB_WHY="no '$re' in $(basename "$f") within $gs game-seconds"; return 1; }
        sleep 0.5
    done
}

#: credits, Start and the launch (plunge.py game: the order that works), up to three tries - a Start the game
#: ignored (a service screen autoattract opened for a moment, a first boot's menu) is tried again after leaving
#: any menu. 0 once a ball was launched (the game ejected one: a game is on); 1 with JOB_WHY otherwise.
job_start_game() {
    local attempt out
    for attempt in 1 2 3; do
        if out=$(python3 "$RIG/plunge.py" game 2>&1 < /dev/null); then
            JOB_GAME_S=$(job_elapsed)
            job_say "a game is on at ${JOB_GAME_S}s (try $attempt)"
            return 0
        fi
        job_dead && { JOB_WHY="the run ended while starting a game: $(job_died_why)"; return 1; }
        if job_guided_setup 2; then
            job_say "left Guided Setup by Save & Exit"; pad_gsleep 3
        else
            job_say "no game yet (try $attempt): $(tail -1 <<<"$out")"; pad_gsleep 8
        fi
    done
    JOB_WHY="no game started after three tries"
    return 1
}

job_shot() { bash "$RIG/glshot.sh" "${1:?job_shot <png>}" > /dev/null 2>&1 < /dev/null; }

job_stop() {
    (cd "$RIG" && bash killgame.sh) > "$JOB_OUT/killgame.txt" 2>&1 < /dev/null
    job_say "rig stopped: $(job_alive) process(es) left (must be 0)"
}
job_verdict() {                   # pass|fail [why]
    local v=$1; shift
    JOB_DONE=1
    job_stop
    echo "VERDICT $KEY $v $(job_elapsed)s${1:+ $*}"
    [ "$v" = pass ]
}
job_pass() { job_verdict pass "$@"; exit 0; }
job_fail() { job_verdict fail "$@"; exit 1; }
job_cleanup() {
    [ -n "$JOB_DONE" ] && return 0
    JOB_DONE=1
    [ "$(job_alive)" = 0 ] || (cd "$RIG" && bash killgame.sh) > /dev/null 2>&1 < /dev/null
    echo "VERDICT ${KEY:-?} fail $(job_elapsed)s the job ended without a verdict${JOB_WHY:+ ($JOB_WHY)}"
}
