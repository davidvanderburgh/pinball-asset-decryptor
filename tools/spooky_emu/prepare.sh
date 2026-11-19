#!/bin/bash
# prepare.sh <update file> - unpack a Spooky game update into the build
# cache and print its name.  What it takes (spktitles.py says which game it
# is from what is inside):
#   Beetlejuice   v<date>.beetlejuice  GPG-SIGNED (not encrypted) tar.gz
#   Halloween     code_H78.pkg         GPG-SYMMETRIC tar.gz (the passphrase
#   Ultraman      code_UM.pkg          is the app's Spooky plugin's)
#   Scooby-Doo    v<date>.scooby       tar.gz
#   Evil Dead     <date>.ed            tar.gz
#   Texas Chainsaw Massacre tcm-*.pkg  tar.gz
#   Looney Tunes  <date>.looney        plain tar (one Godot binary)
# - Spooky's, or one the Write tab built.
#
#   stdout:  progress <0-100>   while unpacking (repeatable)
#            build=<name>       last line on success (run_game.sh <name>)
#   exit:    0 ok, 2 bad args, 3 no space, 4 unpack failed or not a game
#            this emulator runs (the reason on stderr), 5 no game in it
#
# The name is <title>_<version.txt>.  The same file again (name, size and
# time) starts at once.  Only SPK_CACHE_KEEP builds are kept (default 6; a
# Unity build is 1-2 GB unpacked); the oldest idle ones go first.  The update
# is only ever read.  One prepare at a time machine-wide (PAD-1418: several
# tickets' rigs share the cache, and a second prepare's clean-up deleted the
# first one's unpack.partial half way: "could not unpack ... damaged").
set -u
. "$(dirname "$0")/spkpath.sh"
UPD=${1:-}
[ -f "$UPD" ] || { echo "prepare.sh: no such file: $UPD" >&2; exit 2; }
KEEP=${SPK_CACHE_KEEP:-6}
NAME=$(basename "$UPD")

# Spooky's other boards, known by the name before anything is unpacked.
case "$NAME" in
    rm-gamecode*|ac-gamecode*|tna-gamecode*)
        echo "prepare.sh: $NAME is a P-ROC game (Rick and Morty, Alice Cooper or Total Nuclear Annihilation) - this emulator answers the Warden and Pinotaur boards; proc/ runs Rick and Morty and Alice Cooper" >&2
        exit 4 ;;
esac

size=$(stat -c %s "$UPD")
SOURCE="$NAME $size $(stat -c %Y "$UPD")"
cached() {
    for d in "$SPK_CACHE"/*/; do
        d=${d%/}
        [ -f "$d/.pad_source" ] && [ "$(cat "$d/.pad_source")" = "$SOURCE" ] || continue
        touch "$d"
        echo "build=$(basename "$d")"
        exit 0
    done
}
cached
# One unpack at a time (PAD-1419): every slot shares the cache and its unpack.partial, and the
# clean-up below removes any *.partial - two rigs preparing at once wiped each other's unpack
# ("could not unpack").  The one that waited finds the other's build in the cache if it is
# the same update.
mkdir -p "$SPK_CACHE"
exec 9>"$SPK_CACHE/.prepare.lock"
if ! flock -n 9; then
    echo "prepare.sh: another rig is unpacking an update into the cache; waiting for it" >&2
    flock -w 3600 9 || { echo "prepare.sh: the cache stayed busy for an hour" >&2; exit 3; }
fi
cached

live=$(cat "$SPK_ROOT"/rig*/build 2>/dev/null)
ls -1dt "$SPK_CACHE"/*/ 2>/dev/null | sed 's:/$::' | grep -v '\.partial$' |
    tail -n +"$KEEP" | while read -r d; do
    case "$live" in *"$d"*) continue ;; esac
    rm -rf "$d"
done
rm -rf "$SPK_CACHE"/*.partial

magic=$(head -c 2 "$UPD" | od -An -tx1 | tr -d ' ')
if [ "$magic" = 1f8b ]; then
    FMT=gz; GROW=15
elif [ "$(dd if="$UPD" bs=1 skip=257 count=5 2>/dev/null)" = ustar ]; then
    FMT=tar; GROW=10
elif PASS=$(python3 "$SPK_TOOLS/spktitles.py" passphrase "$NAME"); then
    FMT=gpgsym; GROW=11
else
    FMT=gpg; GROW=22
fi
need_kb=$(( size / 1024 * (GROW + 3) / 10 ))
free_kb=$(df -Pk "$SPK_CACHE" | awk 'NR==2 {print $4}')
if [ "$free_kb" -lt "$need_kb" ]; then
    echo "prepare.sh: need $((need_kb / 1048576 + 1)) GB free in $SPK_CACHE, have $((free_kb / 1048576)) GB" >&2
    exit 3
fi

TMP=$SPK_CACHE/unpack.partial
rm -rf "$TMP"; mkdir -p "$TMP"
GH=$(mktemp -d)
# A signed update: no key to check the signature with, gpg still unwraps the
# data (and says "Can't check signature", which is fine - the game is
# Spooky's as shipped).  A symmetric (passphrase) one fails here at once.
case $FMT in
    gz)  ( tar -xzf "$UPD" -C "$TMP" 2>/dev/null ) & ;;
    tar) ( tar -xf "$UPD" -C "$TMP" 2>/dev/null ) & ;;
    gpg) ( gpg --homedir "$GH" --batch --quiet -d "$UPD" 2>/dev/null | tar -xz -C "$TMP" ) & ;;
    gpgsym) ( printf '%s' "$PASS" | gpg --homedir "$GH" --batch --quiet \
                  --pinentry-mode loopback --passphrase-fd 0 -d "$UPD" 2>/dev/null |
              tar -xz -C "$TMP" ) & ;;
esac
job=$!
last=-1
while kill -0 $job 2>/dev/null; do
    got=$(du -sb "$TMP" 2>/dev/null | cut -f1)
    pct=$(( ${got:-0} * 100 / (size * GROW / 10) )); [ $pct -gt 99 ] && pct=99
    [ $pct -ne $last ] && echo "progress $pct" && last=$pct
    sleep 1
done
wait $job; rc=$?
rm -rf "$GH"
if [ $rc -ne 0 ]; then
    rm -rf "$TMP"
    echo "prepare.sh: could not unpack $NAME (not a Spooky game update, or damaged)" >&2
    exit 4
fi
# Texas Chainsaw's and Evil Dead's archives carry no execute bits.
chmod +x "$TMP/main.x86_64" "$TMP/uptest/main.x86_64" 2>/dev/null
if [ ! -f "$TMP/main.x86_64" ] && [ ! -f "$TMP/uptest/main.x86_64" ]; then
    rm -rf "$TMP"
    echo "prepare.sh: no game (main.x86_64) in $NAME" >&2
    exit 5
fi
if ! key=$(python3 "$SPK_TOOLS/spktitles.py" detect "$TMP"); then
    rm -rf "$TMP"
    echo "prepare.sh: $NAME is ${key#no } - not a game this emulator runs" >&2
    exit 4
fi
# Beetlejuice's version.txt says v2026.09.15.11, Scooby-Doo's v2025.12.01.09,
# Evil Dead's 2026.07.15.ed, Texas Chainsaw's "TCM V1.00", Looney's 2025_10_08.
v=$(head -1 "$TMP/version.txt" 2>/dev/null | tr -d '\r' | tr -cs 'A-Za-z0-9._-' '_' | sed 's/^_*//; s/_*$//')
# Halloween's is an empty uptest/version_118.txt, Ultraman's version_1_18.txt:
# the name is the version.
[ -z "$v" ] && v=$(cd "$TMP/uptest" 2>/dev/null && ls version_*.txt 2>/dev/null | head -1 | sed 's/^version_/v/; s/\.txt$//')
DEST=$SPK_CACHE/${key}_${v:-unknown}
# PAD-1417: an update with PAD's custom modes in it (pad/padunity.so) is the same version as
# the stock one: kept beside it, never in its place.
[ -f "$TMP/pad/padunity.so" ] || [ -f "$TMP/uptest/pad/padunity.so" ] || [ -f "$TMP/pad/pad_modes.gd" ] \
    && DEST=${DEST}_padmodes
echo "$key" > "$TMP/.pad_title"
echo "$SOURCE" > "$TMP/.pad_source"
rm -rf "$DEST"
mv "$TMP" "$DEST"
# Where it came from, for the Cache window (cache.sh).
echo "$UPD" > "$DEST/src"
echo "progress 100"
echo "build=$(basename "$DEST")"
