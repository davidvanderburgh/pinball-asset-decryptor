#!/bin/bash
# Spike 1 extracted-game cache.
#
# The Spike 1 game is EXTRACTED from a card (build_rootfs.py -> rootfs + game),
# which takes ~1 minute.  Rather than overwrite one extraction each time the card
# changes, each card's extraction is kept under $WORK/cache/<label>/{rootfs,game}
# and the active one is exposed as the symlinks $WORK/rootfs -> and $WORK/game ->,
# so the rest of the rig (emu_root.sh, nodebus.py) is unchanged.  This is the
# Spike 1 analog of the Spike 2 card cache (tools/spike2_emu/cardmount.sh): keyed
# by the card's size+mtime (not its path), LRU-evicted with a free-space floor.
#
# Subcommands (WORK defaults to /home/<user>/s1emu):
#   cache.sh label  <card>                 -> the cache label for a card
#   cache.sh stamp  <card>                 -> "<size> <mtime>" identity
#   cache.sh entry  <card> [work]          -> the cache entry dir for a card
#   cache.sh valid  <card> [work]          -> exit 0 iff a matching extraction exists
#   cache.sh activate <label> [work]       -> point work/rootfs,game at that entry
#   cache.sh evict  [work] [keep_free_gb]  -> LRU-evict to keep some free space
#   cache.sh list   [work]                 -> one TSV row per entry (for the GUI)
#   cache.sh drop   <label> [work]         -> remove one entry (refuses the active one)
set -u

: "${S1_DESKTOP_USER:=$(getent passwd 1000 2>/dev/null | cut -d: -f1)}"
DEF_WORK="/home/${S1_DESKTOP_USER:-david}/s1emu"

cache_label() {
    local b; b=$(basename "$1")
    b=${b%.iso}; b=${b%.img}; b=${b%.raw}; b=${b%.vhd}; b=${b%.vhdx}
    b=${b%.Release}
    printf '%s' "$b" | tr -c 'A-Za-z0-9_.-' '_'
}

cache_stamp() { stat -c '%s %Y' "$1" 2>/dev/null; }

_active_label() {   # the label the work/game symlink currently points at
    local work="$1" t
    t=$(readlink "$work/game" 2>/dev/null) || return 0
    t=${t%/game}; basename "$t" 2>/dev/null
}

cmd=${1:-}; shift 2>/dev/null || true
case "$cmd" in
label) cache_label "$1" ;;
stamp) cache_stamp "$1" ;;
entry)
    work=${2:-$DEF_WORK}; echo "$work/cache/$(cache_label "$1")" ;;
valid)
    work=${2:-$DEF_WORK}; entry="$work/cache/$(cache_label "$1")"
    [ -f "$entry/game/game" ] || exit 1
    [ "$(cat "$entry/.src" 2>/dev/null)" = "$(cache_stamp "$1")" ] || exit 1
    ;;
activate)
    label="$1"; work=${2:-$DEF_WORK}; entry="$work/cache/$label"
    [ -d "$entry" ] || { echo "no such cache entry: $label" >&2; exit 1; }
    # replace any real dirs left by the pre-cache layout, then symlink
    [ -L "$work/rootfs" ] || rm -rf "$work/rootfs" 2>/dev/null
    [ -L "$work/game" ]   || rm -rf "$work/game"   2>/dev/null
    ln -sfn "$entry/rootfs" "$work/rootfs"
    ln -sfn "$entry/game"   "$work/game"
    touch "$entry/.boot"        # LRU: last-activated marker
    ;;
evict)
    work=${1:-$DEF_WORK}; keep_gb=${2:-5}; cdir="$work/cache"
    [ -d "$cdir" ] || exit 0
    active=$(_active_label "$work")
    # drop least-recently-activated entries until keep_gb GiB is free
    while :; do
        free_kb=$(df -Pk "$cdir" 2>/dev/null | awk 'NR==2{print $4}')
        [ -n "$free_kb" ] && [ "$free_kb" -lt $((keep_gb * 1024 * 1024)) ] || break
        victim=$(ls -1dt "$cdir"/*/.boot 2>/dev/null | tail -1)
        [ -n "$victim" ] || break
        victim=$(dirname "$victim"); vlabel=$(basename "$victim")
        [ "$vlabel" = "$active" ] && break     # never evict the active one
        rm -rf "$victim" || break
    done
    ;;
list)
    work=${1:-$DEF_WORK}; cdir="$work/cache"; active=$(_active_label "$work")
    if [ -d "$cdir" ]; then
        for e in "$cdir"/*/; do
            [ -d "$e" ] || continue
            label=$(basename "$e")
            kb=$(du -sk "$e" 2>/dev/null | cut -f1)
            boot=$(stat -c '%Y' "$e/.boot" 2>/dev/null || echo 0)
            game=$(tr -d '[:space:]' < "$e/game/.game_name" 2>/dev/null)
            act=0; [ "$label" = "$active" ] && act=1
            printf 'entry\t%s\t%s\t%s\t%s\t%s\n' \
                   "$label" "${kb:-0}" "${boot:-0}" "${game:-?}" "$act"
        done
    fi
    avail=$(df -Pk "$work" 2>/dev/null | awk 'NR==2{print $4}')
    printf 'disk\t%s\n' "${avail:-0}"
    ;;
drop)
    label="$1"; work=${2:-$DEF_WORK}
    [ "$label" = "$(_active_label "$work")" ] && {
        echo "refusing to drop the active game" >&2; exit 2; }
    rm -rf "$work/cache/$label" && echo "dropped $label"
    ;;
*)
    echo "usage: cache.sh {label|stamp|entry|valid|activate|evict|list|drop} …" >&2
    exit 2 ;;
esac
