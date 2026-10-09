#!/bin/bash
# rigbatch.sh - run one job over a list of builds, spread across several rigs.
#
#   rigbatch.sh [-n RIGS] [--who PAD-n] [--out DIR] [--speed K] [--fps F]
#               [--stage DIR | --no-stage] [--stage-keep GB]
#               <list> [-- <command> [args...]]
#
# <list>: one build per line, `key|card|ENV=v ENV2=v` (the format every
# library sweep has used; `#` comments and blank lines skipped). <command> is
# run once per line as `<command> [args...] <key> <card>`, with the line's
# ENV, PAD_SLOT (its rig) and PAD_LABEL (--who) in its environment. Default:
# bootcheck.sh (does the build boot to attract). A job's last `VERDICT ...`
# line is its result; with none, exit 0 is pass.
#
# WHY. A ticket that changes the emulator or the runtime has to prove it on the
# whole Spike 2 library - 36 builds at a median 3 minutes is two hours one at a
# time, and every sweep so far was a throwaway serial loop holding the one rig
# lock. Rig slots (padpath.sh) made several complete rigs possible; this
# spreads a list across them: one worker per rig, each taking the next build
# off a shared queue until it is empty.
#
# HOW MANY RIGS. -n, else as many as the CPU feeds at full speed: a rig costs
# ~2 cores at the sweep's 15 pictures a second (--fps below; PAD-488 measured
# 1.7 over four rigs' busiest 30 s), so nproc*10/20, and ~2.8 at the machine's
# 30 (nproc*10/28) - and never more than the free rigs. Over-committing is not merely slower: an emulated game starved of
# CPU misses its own timings (ball-save windows, drains, a 150 s start) and a
# healthy build reads as failed. Taking a rig mounts it, which needs root:
# run this as root (`wsl -u root -e env HOME=/home/<you> bash rigbatch.sh ...`),
# or mount the rigs first with `slot.sh up N`.
#
# CARDS ON A WINDOWS DRIVE ARE STAGED ONTO THE WSL DISK (cardstage.sh cache).
# Several rigs booting several images off one hard disk make it seek between
# them until a read stalls past the game's own ten-second watchdog (5 of 12
# builds, measured), so one copier moves each card ahead of the rigs. Since
# PAD-484 it moves them into cardmount.sh's local cache on the WSL disk, for
# ONE rig as well as several and for cards on C: as well as D:, and every job
# runs with PAD_CARD_CACHE=1: a card on any Windows drive boots through 9p
# under fuse2fs, where the validator's and the scene loader's reads are
# latency-bound - Godzilla Pro 1.16 reached attract in 79-130 s from C: and in
# 23 s from the cache. The cache keeps itself (least recently booted first,
# 30 GB of the WSL disk left free). --stage DIR copies to DIR instead, as
# before (kept up to --stage-keep GB, default 100); --no-stage boots every card
# where it lies.
#
# --speed K (PAD-484): every job's game runs its clock K times the wall's once
# it is in attract (PAD_SPEED, padspeed.py) - a sweep's time goes on the game's
# own waiting, not on the CPU. The rig's helpers (ball feeder, plunger, switch
# presses, gamecheck.sh) keep the game's time by the same K. A job that has to
# see real-time behaviour (a clip played frame by frame) leaves it out, or
# says PAD_SPEED=1 on its own line.
#
# --fps F (PAD-488): every job's game builds at most F pictures a second (60,
# 30, 20 or 15; PAD_SWAP_VBLANKS=60/F, eglshim.c). DEFAULT 15, half the
# machine's 30: a sweep's rig is hidden and every picture is drawn in software,
# so the renderer's CPU goes with F - and a renderer with CPU to spare draws
# all 30 while the game builds them, so at 30 the VM stayed saturated. Four
# rigs at 4x over the 7-build check, two rounds: the busiest 30 s of the VM
# was 8.8-9.0 of 10 cores on the old renderer, 8.2-9.2 at 30, 6.9 and 6.9 at
# 15, every job passing (docs/plans/game_speed.md). The game skips a build
# while the renderer is busy (PAD-301), as on a machine with a slow GPU, and
# its own clock and logic do not change. A job that judges the pictures' own
# cadence passes --fps 30, or says PAD_SWAP_VBLANKS=2 on its own line.
#
# Out: DIR (default $PAD_HOME/rigbatch/<list>-<time>/) holds progress.txt,
# results.tsv (key, rig, verdict, seconds, the VERDICT line) and one log per
# build. The rigs show on the board as held by --who, noting each build as it
# starts - the triage dashboard and the Emulate tab see the sweep live.
# Ctrl-C / SIGTERM stops every worker, stops each rig's run, frees the rigs.
. "$(dirname "$0")/padpath.sh"
set -u

N="" WHO="" OUT="" STAGE="" NOSTAGE=0 KEEP=100 SPEED="" FPS=15
while [ $# -gt 0 ]; do
    case "$1" in
        -n) N=$2; shift 2 ;;
        --who) WHO=$2; shift 2 ;;
        --out) OUT=$2; shift 2 ;;
        --stage) STAGE=$2; shift 2 ;;
        --no-stage) NOSTAGE=1; shift ;;
        --stage-keep) KEEP=$2; shift 2 ;;
        --speed) SPEED=$2; shift 2 ;;
        --fps) FPS=$2; shift 2 ;;
        -h|--help) awk 'NR == 1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"; exit 0 ;;
        *) break ;;
    esac
done
LIST=${1:?usage: rigbatch.sh [-n RIGS] [--who PAD-n] [--out DIR] <list> [-- command...]}
shift
[ "${1:-}" = -- ] && shift
if [ $# -gt 0 ]; then CMD=("$@"); else CMD=(bash "$RIG/bootcheck.sh"); fi
[ -f "$LIST" ] || { echo "rigbatch: no list at $LIST" >&2; exit 2; }
case $FPS in
    60|30|20|15) VBL=$((60 / FPS)) ;;
    *) echo "rigbatch: --fps is 60, 30, 20 or 15 (a swap is a whole number of 60 Hz refreshes)" >&2; exit 2 ;;
esac
WHO=${WHO:-$(pad_label)}
WHO=${WHO:-rigbatch}
OUT=${OUT:-$PAD_HOME/rigbatch/$(basename "$LIST" .list)-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$OUT"
pad_give_back "$PAD_HOME/rigbatch" "$OUT"
P=$OUT/progress.txt
say() { echo "$(date +%T) $*" | tee -a "$P"; }

grep -v '^[[:space:]]*#' "$LIST" | grep -v '^[[:space:]]*$' > "$OUT/queue"
TOTAL=$(wc -l < "$OUT/queue")
[ "$TOTAL" -gt 0 ] || { echo "rigbatch: $LIST has no builds" >&2; exit 2; }
echo 0 > "$OUT/next"
: > "$OUT/results.tsv"

cpu=$(nproc 2>/dev/null || echo 2)
per=$([ "$VBL" -ge 4 ] && echo 20 || echo 28)      # tenths of a core a rig costs (HOW MANY RIGS)
fit=$(( cpu * 10 / per )); [ "$fit" -ge 1 ] || fit=1
[ -n "$N" ] || N=$fit
[ "$N" -gt "$TOTAL" ] && N=$TOTAL
if [ "$N" -gt "$fit" ]; then
    say "WARNING: $N rigs on $cpu cores (~$((per / 10)).$((per % 10)) each at $FPS fps fits $fit) - builds may fail on timing, not on their own"
fi

# ---- take the rigs ------------------------------------------------------
SLOTS=()
for _ in $(seq 1 "$N"); do
    s=$(bash "$RIG/riglock.sh" take --any "$WHO" "rigbatch $(basename "$LIST")" 2>/dev/null < /dev/null \
        | sed -n 's/^slot=//p')
    [ -n "$s" ] || break
    # (PAD_RIGBATCH_ASSUME_MOUNTED=1: the unit tests, which run on stub rigs)
    if [ "${PAD_RIGBATCH_ASSUME_MOUNTED:-0}" != 1 ] && \
       ! mountpoint -q "$PAD_HOME/padslots/$s/root" 2>/dev/null; then
        say "rig $s is free but not mounted (mounting needs root): wsl -u root -e bash $RIG/slot.sh up $s"
        bash "$RIG/riglock.sh" release "$s" "$WHO" > /dev/null 2>&1 < /dev/null
        break
    fi
    SLOTS+=("$s")
done
[ "${#SLOTS[@]}" -gt 0 ] || { say "no rig could be taken - riglock.sh list"; exit 1; }
say "$TOTAL builds on rig(s) ${SLOTS[*]} for $WHO${SPEED:+ at ${SPEED}x}, $FPS fps; job: ${CMD[*]}"

# ---- stage the cards (cardstage.sh) ----------------------------------------
if [ "$NOSTAGE" = 0 ] && [ -z "$STAGE" ] && [ -d /mnt/c ] \
   && cut -d'|' -f2 "$OUT/queue" | grep -q '^[[:space:]]*/mnt/[a-z]/'; then
    STAGE=cache
fi
SPID=""
if [ "$NOSTAGE" = 0 ] && [ "$STAGE" = cache ]; then
    mkdir -p "$OUT/stage"
    say "caching cards on the WSL disk (cardmount.sh's cache), one copy at a time, ${#SLOTS[@]} ahead"
    setsid bash "$RIG/cardstage.sh" "$OUT" cache "${#SLOTS[@]}" \
        >> "$OUT/stage.log" 2>&1 < /dev/null &
    SPID=$!
elif [ "$NOSTAGE" = 0 ] && [ -n "$STAGE" ]; then
    mkdir -p "$STAGE" "$OUT/stage"
    say "staging cards to $STAGE, one copy at a time, ${#SLOTS[@]} ahead (kept up to ${KEEP} GB)"
    setsid bash "$RIG/cardstage.sh" "$OUT" "$STAGE" "${#SLOTS[@]}" "$KEEP" \
        >> "$OUT/stage.log" 2>&1 < /dev/null &
    SPID=$!
else
    STAGE=""
fi

WPIDS=()
finish() {
    local s p
    touch "$OUT/stop"
    [ -n "$SPID" ] && { kill -TERM -- "-$SPID" 2>/dev/null; kill -TERM "$SPID" 2>/dev/null; }
    for p in "${WPIDS[@]}"; do kill -TERM -- "-$p" 2>/dev/null; kill -TERM "$p" 2>/dev/null; done
    for s in "${SLOTS[@]}"; do
        PAD_SLOT=$s PAD_LABEL="$WHO" bash "$RIG/killgame.sh" > /dev/null 2>&1 < /dev/null
        bash "$RIG/riglock.sh" release "$s" "$WHO" --force > /dev/null 2>&1 < /dev/null
    done
    if [ -n "$STAGE" ] && [ "$STAGE" != cache ]; then
        rm -rf "$STAGE/.inflight/$(printf %s "$OUT" | md5sum | cut -c1-12)"   # its own copies in flight only (cardstage.sh)
        bash "$RIG/cardstage.sh" --trim "$STAGE" "$KEEP" >> "$OUT/stage.log" 2>&1 < /dev/null
    fi
}
trap 'say "STOPPED - stopping every rig"; finish; exit 130' INT TERM

# ---- the workers ----------------------------------------------------------
worker() {
    local slot=$1 i line key card envs t0 rc v log
    while :; do
        i=$(flock "$OUT/next" bash -c 'i=$(cat "$1"); echo $((i + 1)) > "$1"; echo "$i"' _ "$OUT/next")
        [ "$i" -lt "$TOTAL" ] || return 0
        line=$(sed -n "$((i + 1))p" "$OUT/queue")
        IFS='|' read -r key card envs <<<"$line"
        key=$(echo "$key" | tr -d '[:space:]')
        [ -n "$key" ] || continue
        log=$OUT/$key.log
        card=$(echo "$card" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
        if [ -n "$STAGE" ]; then
            # the staged copy (cardstage.sh), not the slow disk's original
            bash "$RIG/riglock.sh" note "$slot" "rigbatch $key (waiting for its card)" > /dev/null 2>&1 < /dev/null
            t0=0
            while [ ! -f "$OUT/stage/$i" ] && [ ! -f "$OUT/stage/$i.fail" ]; do
                [ -e "$OUT/stop" ] && return 0
                sleep 2
                # a long copy must not let the rig's lease lapse under the batch
                t0=$((t0 + 1))
                [ $((t0 % 30)) = 0 ] && bash "$RIG/riglock.sh" use "$slot" "$WHO" > /dev/null 2>&1 < /dev/null
            done
            if [ -f "$OUT/stage/$i.fail" ]; then
                v="VERDICT $key fail staging: $(cat "$OUT/stage/$i.fail")"
                flock "$OUT/results.tsv" bash -c 'printf "%s\n" "$2" >> "$1"' _ "$OUT/results.tsv" \
                    "$(printf '%s\t%s\t%s\t%s\t%s' "$key" "$slot" fail 0 "$v")"
                say "rig $slot  $(cut -d' ' -f3- <<<"$v")"
                continue
            fi
            card=$(cat "$OUT/stage/$i")
        fi
        bash "$RIG/riglock.sh" note "$slot" "rigbatch $key" > /dev/null 2>&1 < /dev/null
        say "rig $slot  start  $key  ($((i + 1))/$TOTAL)"
        t0=$(date +%s)
        # shellcheck disable=SC2086
        # the batch's own settings first, so a line's ENV still wins: PAD_CARD_CACHE=1 when the cards were cached
        # (the job boots the original path and its mount finds the copy), PAD_SPEED for --speed, PAD_SWAP_VBLANKS for --fps
        env ${STAGE:+$( [ "$STAGE" = cache ] && echo PAD_CARD_CACHE=1 )} ${SPEED:+PAD_SPEED=$SPEED} \
            PAD_SWAP_VBLANKS=$VBL $envs \
            PAD_SLOT="$slot" PAD_LABEL="$WHO" "${CMD[@]}" "$key" "$card" > "$log" 2>&1 < /dev/null &
        jp=$!
        # THE LEASE IS KEPT WHILE THE JOB RUNS (PAD-420): it lapses PAD_LOCK_IDLE after its holder's last touch, and a
        # job that waits minutes (a media proof, a coil hold, a game check) looked free - the next batch took its slot
        # and that batch's first killgame killed this job's game.
        n=0
        while kill -0 "$jp" 2>/dev/null; do
            sleep 2; n=$((n + 1))
            [ $((n % 15)) = 0 ] && bash "$RIG/riglock.sh" use "$slot" "$WHO" > /dev/null 2>&1 < /dev/null
        done
        wait "$jp"
        rc=$?
        [ -n "$STAGE" ] && touch "$OUT/stage/$i.done"
        v=$(grep -a '^VERDICT ' "$log" | tail -1)
        [ -n "$v" ] || { [ "$rc" = 0 ] && v="VERDICT $key pass" || v="VERDICT $key fail rc=$rc"; }
        # A job that left its rig running would hand the next build a live one.
        [ "$(PAD_SLOT=$slot bash "$RIG/alive.sh" --total 2>/dev/null < /dev/null)" = 0 ] \
            || PAD_SLOT=$slot PAD_LABEL="$WHO" bash "$RIG/killgame.sh" > /dev/null 2>&1 < /dev/null
        flock "$OUT/results.tsv" bash -c 'printf "%s\n" "$2" >> "$1"' _ "$OUT/results.tsv" \
            "$(printf '%s\t%s\t%s\t%s\t%s' "$key" "$slot" "$(awk '{print $3}' <<<"$v")" \
               "$(( $(date +%s) - t0 ))" "$v")"
        say "rig $slot  $(cut -d' ' -f3- <<<"$v")"
    done
}

T0=$(date +%s)
for s in "${SLOTS[@]}"; do
    setsid bash -c "$(declare -f say worker); P='$P' OUT='$OUT' TOTAL=$TOTAL RIG='$RIG' WHO='$WHO' STAGE='$STAGE' SPEED='$SPEED' VBL='$VBL'; \
        CMD=($(printf '%q ' "${CMD[@]}")); worker $s" < /dev/null &
    WPIDS+=("$!")
done
for p in "${WPIDS[@]}"; do wait "$p"; done
trap - INT TERM
finish

WALL=$(( $(date +%s) - T0 ))
SUM=$(awk -F'\t' '{s += $4} END {print s + 0}' "$OUT/results.tsv")
PASS=$(awk -F'\t' '$3 == "pass"' "$OUT/results.tsv" | wc -l)
if [ "$STAGE" = cache ]; then
    say "staging: $(grep -c ' cached ' "$OUT/stage.log" 2>/dev/null) cached on the WSL disk," \
        "$(grep -c ' NOT cached ' "$OUT/stage.log" 2>/dev/null) booted where they lie"
elif [ -n "$STAGE" ]; then
    say "staging: $(grep -c ' staged ' "$OUT/stage.log" 2>/dev/null) copied," \
        "$(grep -c ' reuse ' "$OUT/stage.log" 2>/dev/null) already on $STAGE"
fi
say "ALL DONE: $PASS/$TOTAL pass in $((WALL / 60))m$((WALL % 60))s on ${#SLOTS[@]} rig(s)" \
    "(one after another: $((SUM / 60))m$((SUM % 60))s)"
awk -F'\t' '$3 != "pass" {print "  FAIL " $5}' "$OUT/results.tsv" | tee -a "$P"
echo "results: $OUT/results.tsv"
[ "$PASS" = "$TOTAL" ]
