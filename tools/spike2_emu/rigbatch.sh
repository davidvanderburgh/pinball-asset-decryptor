#!/bin/bash
# rigbatch.sh - run one job over a list of builds, spread across several rigs.
#
#   rigbatch.sh [-n RIGS] [--who PAD-n] [--out DIR]
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
# ~2.8 cores (measured, ~/.wslconfig), so nproc*10/28, and never more than the
# free rigs. Over-committing is not merely slower: an emulated game starved of
# CPU misses its own timings (ball-save windows, drains, a 150 s start) and a
# healthy build reads as failed. Taking a rig mounts it, which needs root:
# run this as root (`wsl -u root -e env HOME=/home/<you> bash rigbatch.sh ...`),
# or mount the rigs first with `slot.sh up N`.
#
# CARDS ON A SPINNING DISK ARE STAGED (cardstage.sh). Several rigs booting
# several images off one hard disk make it seek between them until a read
# stalls past the game's own ten-second watchdog (5 of 12 builds, measured).
# So with more than one rig and any card on a Windows drive other than C:,
# one copier moves each card to /mnt/c/tmp/pad_cardstage (the NVMe) ahead of
# the rigs, and each rig boots its copy. Copies stay for the next sweep up to
# --stage-keep GB (default 100). --stage DIR stages to DIR instead (any card
# not already there); --no-stage boots every card where it lies.
#
# Out: DIR (default $PAD_HOME/rigbatch/<list>-<time>/) holds progress.txt,
# results.tsv (key, rig, verdict, seconds, the VERDICT line) and one log per
# build. The rigs show on the board as held by --who, noting each build as it
# starts - the triage dashboard and the Emulate tab see the sweep live.
# Ctrl-C / SIGTERM stops every worker, stops each rig's run, frees the rigs.
. "$(dirname "$0")/padpath.sh"
set -u

N="" WHO="" OUT="" STAGE="" NOSTAGE=0 KEEP=100
while [ $# -gt 0 ]; do
    case "$1" in
        -n) N=$2; shift 2 ;;
        --who) WHO=$2; shift 2 ;;
        --out) OUT=$2; shift 2 ;;
        --stage) STAGE=$2; shift 2 ;;
        --no-stage) NOSTAGE=1; shift ;;
        --stage-keep) KEEP=$2; shift 2 ;;
        -h|--help) sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) break ;;
    esac
done
LIST=${1:?usage: rigbatch.sh [-n RIGS] [--who PAD-n] [--out DIR] <list> [-- command...]}
shift
[ "${1:-}" = -- ] && shift
if [ $# -gt 0 ]; then CMD=("$@"); else CMD=(bash "$RIG/bootcheck.sh"); fi
[ -f "$LIST" ] || { echo "rigbatch: no list at $LIST" >&2; exit 2; }
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
fit=$(( cpu * 10 / 28 )); [ "$fit" -ge 1 ] || fit=1
[ -n "$N" ] || N=$fit
[ "$N" -gt "$TOTAL" ] && N=$TOTAL
if [ "$N" -gt "$fit" ]; then
    say "WARNING: $N rigs on $cpu cores (~2.8 each fits $fit) - builds may fail on timing, not on their own"
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
say "$TOTAL builds on rig(s) ${SLOTS[*]} for $WHO; job: ${CMD[*]}"

# ---- stage the cards (cardstage.sh) ----------------------------------------
if [ "$NOSTAGE" = 0 ] && [ -z "$STAGE" ] && [ "${#SLOTS[@]}" -gt 1 ] && [ -d /mnt/c ] \
   && cut -d'|' -f2 "$OUT/queue" | grep -q '^[[:space:]]*/mnt/[abd-z]/'; then
    STAGE=/mnt/c/tmp/pad_cardstage
fi
SPID=""
if [ "$NOSTAGE" = 0 ] && [ -n "$STAGE" ]; then
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
    if [ -n "$STAGE" ]; then
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
        env $envs PAD_SLOT="$slot" PAD_LABEL="$WHO" "${CMD[@]}" "$key" "$card" > "$log" 2>&1 < /dev/null &
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
    setsid bash -c "$(declare -f say worker); P='$P' OUT='$OUT' TOTAL=$TOTAL RIG='$RIG' WHO='$WHO' STAGE='$STAGE'; \
        CMD=($(printf '%q ' "${CMD[@]}")); worker $s" < /dev/null &
    WPIDS+=("$!")
done
for p in "${WPIDS[@]}"; do wait "$p"; done
trap - INT TERM
finish

WALL=$(( $(date +%s) - T0 ))
SUM=$(awk -F'\t' '{s += $4} END {print s + 0}' "$OUT/results.tsv")
PASS=$(awk -F'\t' '$3 == "pass"' "$OUT/results.tsv" | wc -l)
[ -n "$STAGE" ] && say "staging: $(grep -c ' staged ' "$OUT/stage.log" 2>/dev/null) copied," \
    "$(grep -c ' reuse ' "$OUT/stage.log" 2>/dev/null) already on $STAGE"
say "ALL DONE: $PASS/$TOTAL pass in $((WALL / 60))m$((WALL % 60))s on ${#SLOTS[@]} rig(s)" \
    "(one after another: $((SUM / 60))m$((SUM % 60))s)"
awk -F'\t' '$3 != "pass" {print "  FAIL " $5}' "$OUT/results.tsv" | tee -a "$P"
echo "results: $OUT/results.tsv"
[ "$PASS" = "$TOTAL" ]
