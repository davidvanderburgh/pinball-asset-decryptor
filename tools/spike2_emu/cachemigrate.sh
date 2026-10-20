#!/bin/bash
# cachemigrate.sh [<old cache dir>] - move the VALID entries of an old per-distro card cache into the shared store
# (cardmount.sh --cache-dir, /mnt/wsl/cards/cardcache when mounted; PAD-651), so they are not read off D: again.
# Valid = the .src stamp still names an existing image with the same size and mtime (an older version moved to the
# archive folder is invalid and simply dropped). The copy is sparse-preserving (ext4 to ext4, NVMe to NVMe) and the
# old entry goes once the new one matches in size. Run as root in the distro that owns the old cache:
#
#   wsl -u root -e bash -c 'export HOME=/home/david; bash <rig>/cachemigrate.sh'            (Ubuntu's ~/cardcache)
#   wsl -d PAD-Runtime -u root -e bash -c 'export HOME=/home/pad; bash <rig>/cachemigrate.sh /home/pad/cardcache'
set -u
RIG=$(cd "$(dirname "$0")" && pwd)
NEW=$(bash "$RIG/cardmount.sh" --cache-dir 2>/dev/null)
OLD=${1:-${PAD_HOME:-$HOME}/cardcache}
[ -n "$NEW" ] && [ -d "$NEW" ] || { echo "cachemigrate: no cache dir from cardmount.sh" >&2; exit 2; }
[ "$(realpath "$OLD")" != "$(realpath "$NEW")" ] || { echo "cachemigrate: $OLD is the store itself; nothing to do"; exit 0; }
[ -d "$OLD" ] || { echo "cachemigrate: no old cache at $OLD"; exit 0; }
moved=0 dropped=0 kept=0 bytes=0
for src in "$OLD"/*.src; do
    [ -e "$src" ] || break
    label=$(basename "$src" .src)
    raw=$OLD/$label.raw
    [ -f "$raw" ] || { rm -f "$src"; continue; }
    stamp=$(cat "$src")
    img=${stamp%% *}; rest=${stamp#* }
    if [ ! -f "$img" ] || [ "$(stat -c '%s %Y' "$img" 2>/dev/null)" != "$rest" ]; then
        echo "drop  $label  (its image is gone or changed: an older version, or a rebuilt card)"
        rm -f "$raw" "$raw.partial" "$src" "$OLD/$label.boot" "$OLD/$label.log" "$OLD/$label.pid"
        dropped=$((dropped + 1)); continue
    fi
    if pgrep -f "fuse2fs.*$label" > /dev/null 2>&1; then
        echo "keep  $label  (mounted by a run right now)"; kept=$((kept + 1)); continue
    fi
    if [ -f "$NEW/$label.raw" ] && [ "$(cat "$NEW/$label.src" 2>/dev/null)" = "$stamp" ]; then
        echo "have  $label  (the store has it already)"
        rm -f "$raw" "$src" "$OLD/$label.boot" "$OLD/$label.log" "$OLD/$label.pid"; continue
    fi
    t0=$(date +%s)
    if cp --sparse=always -p "$raw" "$NEW/$label.raw.partial" \
       && [ "$(stat -c %s "$NEW/$label.raw.partial")" = "$(stat -c %s "$raw")" ]; then
        mv -f "$NEW/$label.raw.partial" "$NEW/$label.raw"
        cp -p "$src" "$NEW/$label.src"
        [ -f "$OLD/$label.boot" ] && cp -p "$OLD/$label.boot" "$NEW/$label.boot"
        used=$(du -B1 "$NEW/$label.raw" | cut -f1)
        rm -f "$raw" "$src" "$OLD/$label.boot" "$OLD/$label.log" "$OLD/$label.pid"
        moved=$((moved + 1)); bytes=$((bytes + used))
        echo "moved $label  $((used / 1000000000)) GB in $(( $(date +%s) - t0 ))s"
    else
        rm -f "$NEW/$label.raw.partial"
        echo "FAILED $label  (copy did not land whole; the old entry stays)"; kept=$((kept + 1))
    fi
done
echo "done: $moved moved ($((bytes / 1000000000)) GB), $dropped dropped (stale), $kept left in $OLD"
df -h "$NEW" | tail -1
