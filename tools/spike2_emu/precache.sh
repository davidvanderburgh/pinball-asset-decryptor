#!/bin/bash
# precache.sh [<folder>] - copy every card image in the library folder into the card cache, one at a time, so no
# sweep ever reads D: again (PAD-651). Default folder: the Spike 2 library, D:\Pinball\images\Stern\spike2, which
# since 2026-10-20 holds the NEWEST build of every title only (its `older versions` subfolder is archival and is
# never read - David: "we should never use these images"). Run as root in Ubuntu with HOME=/home/<you>:
#
#   wsl -u root -e bash -c 'export HOME=/home/david; bash <rig>/precache.sh'
#
# Each card goes through `cardmount.sh <card> --cache-now` (cardcopy.py: used blocks only, ~5 GB a card, under the
# machine-wide copy lock cardstage.sh uses, so a sweep's own copy and this one never read the disk at once). A card
# already cached and valid is skipped in a second. The cache is wherever cardmount.sh keeps it - the shared store
# /mnt/wsl/cards/cardcache when it is mounted (cardstore.ps1). PAD_PROGRESS=PAD-n reports each card to the triage
# dashboard (ptc progress --step).
set -u
RIG=$(cd "$(dirname "$0")" && pwd)
LIB=${1:-/mnt/d/Pinball/images/Stern/spike2}
[ -d "$LIB" ] || { echo "precache: no folder at $LIB" >&2; exit 2; }
COPY_LOCK=${PAD_COPY_LOCK:-}
if [ -z "$COPY_LOCK" ]; then
    if [ -d /mnt/wsl ] && [ -w /mnt/wsl ]; then COPY_LOCK=/mnt/wsl/pad-cardstage-copy.lock; else COPY_LOCK=/tmp/pad-cardstage-copy.lock; fi
fi
[ -e "$COPY_LOCK" ] || ( umask 0; : > "$COPY_LOCK" ) 2>/dev/null
PTC=/mnt/c/Users/david/Documents/development/pad-triage/padtriage_cli.py
report() {   # <done> <total> <text>
    [ -n "${PAD_PROGRESS:-}" ] || return 0
    python.exe "$(wslpath -w "$PTC")" progress "$PAD_PROGRESS" --step "pre-cache" --count "$1/$2" "$3" > /dev/null 2>&1 < /dev/null || true
}
mapfile -t CARDS < <(find "$LIB" -maxdepth 1 -type f -name '*.raw' | sort)
TOTAL=${#CARDS[@]}
[ "$TOTAL" -gt 0 ] || { echo "precache: no *.raw in $LIB" >&2; exit 2; }
CACHE=$(bash "$RIG/cardmount.sh" --cache-dir 2>/dev/null)
echo "$(date +%T) $TOTAL cards in $LIB -> cache $CACHE"
n=0 done_=0 skipped=0 failed=0 T0=$(date +%s)
for card in "${CARDS[@]}"; do
    n=$((n + 1))
    name=$(basename "$card")
    t0=$(date +%s)
    out=$( exec 9< "$COPY_LOCK"; flock 9; bash "$RIG/cardmount.sh" "$card" --cache-now 2>&1 )
    got=$(printf '%s\n' "$out" | tail -1)
    secs=$(( $(date +%s) - t0 ))
    case "$got" in
        */cardcache/*)
            if printf '%s' "$out" | grep -q "using local cache"; then
                skipped=$((skipped + 1)); echo "$(date +%T) [$n/$TOTAL] cached already  $name"
            else
                done_=$((done_ + 1)); echo "$(date +%T) [$n/$TOTAL] cached in ${secs}s  $name"
            fi ;;
        *)
            failed=$((failed + 1)); echo "$(date +%T) [$n/$TOTAL] NOT cached  $name: $(printf '%s\n' "$out" | grep -a '\[card\]' | tail -1 | cut -c1-120)" ;;
    esac
    report "$n" "$TOTAL" "$name: $( [ "$failed" = 0 ] && echo ok || echo "$failed not cached" ) ($done_ copied, $skipped already there)"
done
echo "$(date +%T) done: $done_ copied, $skipped already cached, $failed not cached, $(( ($(date +%s) - T0) / 60 )) min"
df -h "$CACHE" 2>/dev/null | tail -1
[ "$failed" = 0 ]
