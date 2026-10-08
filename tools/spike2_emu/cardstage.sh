#!/bin/bash
# cardstage.sh - copy a sweep's card images to fast storage, one at a time,
# a few builds ahead of the rigs that will boot them. Run by rigbatch.sh:
#
#   cardstage.sh <batch-out-dir> <stage-dir> <ahead> <keep-gb>
#   cardstage.sh --trim <stage-dir> <keep-gb>
#
# WHY. The card images live on D:, which on David's PC is a spinning disk
# (ST4000DM005). One rig boots fine from it; three rigs booting three
# different images at once make its heads seek between them, a read stalls
# past ten seconds, and the GAME'S OWN WATCHDOG ends the run - "GAME EXIT
# DISPATCH TIMEOUT". Measured 2026-09-27: 5 of 12 builds of a 3-rig library
# sweep died that way, with 3-4 processes in disk wait at every vmstat sample,
# and every one of them boots when run alone. A spinning disk is fast at one
# long SEQUENTIAL read and slow at interleaved random ones, so this turns the
# sweep's disk use into the first kind: ONE copier, reading one whole image
# after another onto the NVMe, where the rigs' random reads are cheap.
#
# Protocol with rigbatch's workers, in <batch-out-dir>/stage/:
#   <i>        the staged path of queue line i - the worker boots from it
#   <i>.fail   why line i could not be staged - the worker records a fail
#   <i>.done   the worker has finished with it
# At most <ahead> lines are ready-and-not-done at once, so the copier never
# runs further ahead than the rigs can use.
#
# KEPT BETWEEN SWEEPS, up to <keep-gb>: the usual next step after a sweep is
# re-running its failures, and a card already on the NVMe (same size and
# mtime as its source, recorded beside it) is used again without a copy.
# Least recently used copies go first; a copy a worker is using never does.
# `<batch-out-dir>/stop` ends the copier between cards.
#
# The copy is Windows' own robocopy when there is one (91 s for an 8 GB card,
# against 111 s through WSL's cp, and no WSL CPU), else cp.
set -u
GB=$((1024 * 1024 * 1024))
# Free space always left on the staging disk (PAD_STAGE_SPARE_GB, default 30).
SPARE=$(( ${PAD_STAGE_SPARE_GB:-30} * GB ))

staged_bytes() {                  # <stage-dir>
    find "$1" -maxdepth 1 -type f ! -name '*.src' -printf '%s\n' 2>/dev/null \
        | awk '{s += $1} END {print s + 0}'
}

in_use() {                        # <batch-out-dir>: staged paths ready and not done
    local f
    for f in "$1"/stage/[0-9]*; do
        case "$f" in *.done|*.fail) continue ;; esac
        [ -f "$f" ] && [ ! -e "$f.done" ] && cat "$f"
    done 2>/dev/null
}

# Evict least-recently-used copies not in use until `need` more bytes fit
# under the cap AND leave the disk 30 GB free.
make_room() {                     # <stage-dir> <keep-bytes> <need-bytes> [<batch-out-dir>]
    local dir=$1 keep=$2 need=$3 out=${4:-} busy f free
    busy=$( [ -n "$out" ] && in_use "$out")
    while :; do
        free=$(( $(df -B1 --output=avail "$dir" | tail -1) ))
        if [ $(( $(staged_bytes "$dir") + need )) -le "$keep" ] && \
           [ "$free" -ge $(( need + SPARE )) ]; then
            return 0
        fi
        f=$(find "$dir" -maxdepth 1 -type f ! -name '*.src' -printf '%T@ %p\n' 2>/dev/null \
            | sort -n | while read -r _ p; do
                grep -qxF "$p" <<<"$busy" || { echo "$p"; break; }
            done)
        # Nothing left to evict: go ahead if the DISK has room (the cap is a
        # preference; in-use copies are what they are), else fail this card.
        [ -n "$f" ] || { [ "$free" -ge $(( need + SPARE )) ]; return; }
        echo "$(date +%T) evict $(basename "$f")"
        rm -f "$f" "$f.src"
    done
}

if [ "${1:-}" = --trim ]; then
    make_room "$2" $(( ${3:-100} * GB )) 0
    exit 0
fi

OUT=${1:?usage: cardstage.sh <batch-out-dir> <stage-dir> <ahead> <keep-gb>}
STAGE=${2:?}
AHEAD=${3:-2}
KEEP=$(( ${4:-100} * GB ))
S=$OUT/stage
# THIS batch's own folder for copies in flight (PAD-420): several batches stage into one folder at once, and a
# batch's end used to empty the shared .partial - a copy another batch had in flight vanished under it (.inflight:
# a batch still running the old code empties .partial at its end)
P=$STAGE/.inflight/$(printf %s "$OUT" | md5sum | cut -c1-12)
mkdir -p "$S" "$P" || exit 1
TOTAL=$(wc -l < "$OUT/queue")
ROBO=/mnt/c/Windows/System32/robocopy.exe

pending() {
    local n=0 f
    for f in "$S"/[0-9]*; do
        case "$f" in *.done|*.fail) continue ;; esac
        [ -f "$f" ] && [ ! -e "$f.done" ] && n=$((n + 1))
    done
    echo "$n"
}

copy() {                          # <src> <dest-dir>
    if [ "${PAD_STAGE_COPY:-robocopy}" = robocopy ] && [ -x "$ROBO" ] \
       && command -v wslpath >/dev/null 2>&1; then
        "$ROBO" "$(wslpath -w "$(dirname "$1")")" "$(wslpath -w "$2")" \
            "$(basename "$1")" /J /NP /NFL /NDL /NJH /NJS > /dev/null 2>&1 < /dev/null
        [ $? -lt 8 ]              # robocopy: 0-7 is success
    else
        cp -f "$1" "$2/"
    fi
}

for i in $(seq 0 $((TOTAL - 1))); do
    [ -e "$OUT/stop" ] && exit 0
    card=$(sed -n "$((i + 1))p" "$OUT/queue" | cut -d'|' -f2 | tr -d '\r' \
           | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
    while [ "$(pending)" -ge "$AHEAD" ]; do
        [ -e "$OUT/stop" ] && exit 0
        sleep 2
    done
    case "$card" in "$STAGE"/*) echo "$card" > "$S/$i"; continue ;; esac
    if [ ! -f "$card" ]; then
        echo "no card at $card" > "$S/$i.fail"; continue
    fi
    name=$(basename "$card")
    dest=$STAGE/$name
    stamp="$card $(stat -c '%s %Y' "$card")"
    if [ -f "$dest" ] && [ "$(cat "$dest.src" 2>/dev/null)" = "$stamp" ]; then
        touch "$dest"
        echo "$(date +%T) reuse $name"
        echo "$dest" > "$S/$i"
        continue
    fi
    size=$(stat -c %s "$card")
    if ! make_room "$STAGE" "$KEEP" "$size" "$OUT"; then
        echo "no room on $STAGE for $name ($((size / GB)) GB) with ${PAD_STAGE_SPARE_GB:-30} GB to spare" > "$S/$i.fail"
        continue
    fi
    t0=$(date +%s)
    rm -f "$P/$name"
    if copy "$card" "$P" && [ -f "$P/$name" ]; then
        mv -f "$P/$name" "$dest"
        echo "$stamp" > "$dest.src"
        echo "$(date +%T) staged $name  $((size / 1048576)) MB in $(( $(date +%s) - t0 ))s"
        echo "$dest" > "$S/$i"
    else
        rm -f "$P/$name"
        echo "copying $card to $STAGE failed" > "$S/$i.fail"
    fi
done
