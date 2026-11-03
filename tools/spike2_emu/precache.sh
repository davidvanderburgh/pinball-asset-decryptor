#!/bin/bash
# precache.sh [<intake folder>] - take every card image in the intake folder INTO the library on the store, once,
# compact (PAD-966). Default intake: D:\Pinball\images\Stern\spike2, where David's downloads land and which since
# 2026-10-20 holds the NEWEST build of every title only (its `older versions` subfolder is archival and is never
# read - David: "we should never use these images"). Run as root in Ubuntu with HOME=/home/<you>:
#
#   wsl -u root -e bash -c 'export HOME=/home/david; bash <rig>/precache.sh'
#
# The library is /mnt/wsl/cards/library (cardmount.sh: STORE_LIBRARY), one file per card under the card's own name
# with the original's mtime, used blocks only (cardcopy.py: ~55% of a raw), and a card there is booted where it
# lies - no cache entry, no second copy. A card already in the library with the original's size+mtime is skipped
# in a moment; a valid cache entry of it (the store before PAD-966 held the library as cache copies) is MOVED in,
# a rename on one disk; anything else is copied under the machine-wide copy lock cardstage.sh uses, so a sweep's
# own copy and this one never read the disk at once. Without the store the library is the intake folder itself and
# this fills the cache as it did before (PAD-651). PAD_PROGRESS=PAD-n reports each card to the triage dashboard.
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
    python.exe "$(wslpath -w "$PTC")" progress "$PAD_PROGRESS" --step "library" --count "$1/$2" "$3" > /dev/null 2>&1 < /dev/null || true
}
mapfile -t CARDS < <(find "$LIB" -maxdepth 1 -type f -name '*.raw' | sort)
TOTAL=${#CARDS[@]}
[ "$TOTAL" -gt 0 ] || { echo "precache: no *.raw in $LIB" >&2; exit 2; }
CACHE=$(bash "$RIG/cardmount.sh" --cache-dir 2>/dev/null)
DEST=""
if [ "$CACHE" = /mnt/wsl/cards/cardcache ]; then
    DEST=/mnt/wsl/cards/library
    mkdir -p "$DEST" && chmod 1777 "$DEST" 2>/dev/null
fi
OWNER=$(stat -c %U "${PAD_HOME:-$HOME}" 2>/dev/null)
echo "$(date +%T) $TOTAL cards in $LIB -> ${DEST:-cache $CACHE}"
n=0 done_=0 moved=0 skipped=0 failed=0 T0=$(date +%s)
ident() { stat -c '%s %Y' "$1" 2>/dev/null; }
label_of() { local l; l=$(basename "$1"); l=${l%%.Release*}; l=${l%%.raw}; echo "$l"; }
for card in "${CARDS[@]}"; do
    n=$((n + 1))
    name=$(basename "$card")
    t0=$(date +%s)
    if [ -z "$DEST" ]; then
        # no store: the cache is the fast copy, as before PAD-966
        out=$( exec 9< "$COPY_LOCK"; flock 9; bash "$RIG/cardmount.sh" "$card" --cache-now 2>&1 )
        got=$(printf '%s\n' "$out" | tail -1)
        case "$got" in
            */cardcache/*)
                if printf '%s' "$out" | grep -q "using local cache"; then
                    skipped=$((skipped + 1)); echo "$(date +%T) [$n/$TOTAL] cached already  $name"
                else
                    done_=$((done_ + 1)); echo "$(date +%T) [$n/$TOTAL] cached in $(( $(date +%s) - t0 ))s  $name"
                fi ;;
            *)
                failed=$((failed + 1)); echo "$(date +%T) [$n/$TOTAL] NOT cached  $name: $(printf '%s\n' "$out" | grep -a '\[card\]' | tail -1 | cut -c1-120)" ;;
        esac
        report "$n" "$TOTAL" "$name: $( [ "$failed" = 0 ] && echo ok || echo "$failed not cached" ) ($done_ copied, $skipped already there)"
        continue
    fi
    dest=$DEST/$name
    key=$(ident "$card")
    if [ -f "$dest" ] && [ "$(ident "$dest")" = "$key" ]; then
        skipped=$((skipped + 1)); echo "$(date +%T) [$n/$TOTAL] in the library  $name"
        report "$n" "$TOTAL" "$name: in the library ($moved moved, $done_ copied, $skipped there, $failed failed)"
        continue
    fi
    label=$(label_of "$card")
    rm -f "$dest.partial"
    if [ -f "$CACHE/$label.raw" ] && [ "$(sed 's/.* \([0-9]* [0-9]*\)$/\1/' "$CACHE/$label.src" 2>/dev/null)" = "$key" ] \
       && ! pgrep -f "fuse2fs.*$CACHE/$label.raw" > /dev/null 2>&1 \
       && mv "$CACHE/$label.raw" "$dest.partial" 2>/dev/null; then
        # the store's cache copy of this very card: moved, not copied (one disk), and its sidecars go with it
        rm -f "$CACHE/$label.src" "$CACHE/$label.boot" "$CACHE/$label.log" "$CACHE/$label.pid" "$CACHE/$label.need"
        how=moved; moved=$((moved + 1))
    else
        ( exec 9< "$COPY_LOCK"; flock 9
          if [ "${PAD_CARD_COPY_USED:-1}" != 0 ] && python3 "$RIG/cardcopy.py" "$card" "$dest.partial" > /dev/null 2>&1; then :
          else rm -f "$dest.partial"; dd if="$card" of="$dest.partial" bs=4M conv=sparse status=none; fi )
        how=copied; done_=$((done_ + 1))
    fi
    if [ -f "$dest.partial" ] && [ "$(stat -c %s "$dest.partial")" = "$(stat -c %s "$card")" ] \
       && touch -r "$card" "$dest.partial" && mv -f "$dest.partial" "$dest"; then
        [ "$(id -u)" = 0 ] && [ -n "$OWNER" ] && [ "$OWNER" != root ] && chown "$OWNER" "$dest" 2>/dev/null
        echo "$(date +%T) [$n/$TOTAL] $how in $(( $(date +%s) - t0 ))s  $name"
    else
        rm -f "$dest.partial"
        [ "$how" = moved ] && moved=$((moved - 1)) || done_=$((done_ - 1))
        failed=$((failed + 1)); echo "$(date +%T) [$n/$TOTAL] NOT taken in  $name (the copy did not land whole: disk full?)"
    fi
    report "$n" "$TOTAL" "$name: $how ($moved moved, $done_ copied, $skipped there, $failed failed)"
done
if [ -n "$DEST" ]; then
    extra=0
    for f in "$DEST"/*.raw; do [ -e "$f" ] && [ ! -e "$LIB/$(basename "$f")" ] && extra=$((extra + 1)); done
    echo "$(date +%T) done: $moved moved from the cache, $done_ copied, $skipped in the library already, $failed failed, $(( ($(date +%s) - T0) / 60 )) min"
    echo "library: $(ls "$DEST"/*.raw 2>/dev/null | wc -l) cards in $DEST ($extra not in $LIB), $(du -sh "$DEST" 2>/dev/null | cut -f1) used"
else
    echo "$(date +%T) done: $done_ copied, $skipped already cached, $failed not cached, $(( ($(date +%s) - T0) / 60 )) min"
fi
df -h "${DEST:-$CACHE}" 2>/dev/null | tail -1
[ "$failed" = 0 ]
