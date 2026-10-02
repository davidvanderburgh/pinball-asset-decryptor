#!/bin/bash
# cache.sh --list | --drop <name>... - the Emulate Spooky tab's Cache window
# (tools/ap_emu/cache.sh's protocol): what the rig keeps in the app's Linux,
# and deleting it.  As root.
#
#   --list    one line per entry, key=value, then a `disk=` line:
#               entry=<name> kind=build kb=<size> used=<epoch> src=<update or "">
#             `used` is when a game last started from it (run_game.sh touches
#             <build>/used) - or, before it ever has, when it was unpacked.
#               disk=<free kb> <total kb>
#   --drop    delete those builds.  One a running game uses is refused
#             (`refused=<name> in use`).  A deleted build is unpacked again
#             on its next Start - nothing is lost (settings and high scores
#             live in $SPK_ROOT/nv<slot>, not in the cache).
# Last line of --drop is `dropped=<count>`.
# The P-ROC games' builds (proc/prepare.py: rm_<date>, ac_<version>) are
# listed and dropped here too - one window for every Spooky game.
. "$(dirname "$0")/spkpath.sh"
PROC_CACHE=$SPK_PROC_ROOT/cache

in_use() {          # the builds running games use, one per line
    local r p
    for r in "$SPK_ROOT"/rig*/ "$SPK_PROC_ROOT"/rig*/; do
        p=$(cat "$r/game.pid" 2>/dev/null)
        [ -n "$p" ] && kill -0 "$p" 2>/dev/null && basename "$(cat "$r/build" 2>/dev/null)"
    done
}

case "${1:-}" in
    --list)
        for b in "$SPK_CACHE"/*/; do
            # Texas Chainsaw's and Evil Dead's game is in uptest/
            exe=$b/main.x86_64; [ -x "$exe" ] || exe=$b/uptest/main.x86_64
            [ -x "$exe" ] || continue
            n=$(basename "$b")
            echo "entry=$n kind=build kb=$(du -sk "$b" 2>/dev/null | cut -f1)" \
                "used=$(stat -c %Y "$b/used" 2>/dev/null || stat -c %Y "$exe")" \
                "src=$(cat "$b/src" 2>/dev/null)"
        done
        for b in "$PROC_CACHE"/*/; do
            [ -f "$b/title" ] || continue
            n=$(basename "$b")
            echo "entry=$n kind=build kb=$(du -sk "$b" 2>/dev/null | cut -f1)" \
                "used=$(stat -c %Y "$b/used" 2>/dev/null || stat -c %Y "$b/title")" \
                "src=$(cat "$b/src" 2>/dev/null)"
        done
        mkdir -p "$SPK_ROOT"
        echo "disk=$(df -Pk "$SPK_ROOT" | awk 'NR==2 {print $4, $2}')"
        ;;
    --drop)
        shift
        used=$(in_use)
        n=0
        for e in "$@"; do
            case "$e" in */*|.|..|"") echo "refused=$e not a cache entry"; continue ;; esac
            d=$SPK_CACHE/$e
            [ -d "$d" ] || d=$PROC_CACHE/$e
            [ -d "$d" ] || { echo "refused=$e not a cache entry"; continue; }
            echo "$used" | grep -qx "$e" && { echo "refused=$e in use"; continue; }
            rm -rf --one-file-system "$d"
            echo "dropped $e"
            n=$((n + 1))
        done
        echo "dropped=$n"
        ;;
    *) echo "usage: cache.sh --list | --drop <name>..." >&2; exit 2 ;;
esac
