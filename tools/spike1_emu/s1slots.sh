#!/bin/bash
# s1slots.sh - list, relabel and delete Spike 1 save-state slots. (item 87)
#
#   wsl -u root -e bash s1slots.sh list
#   wsl -u root -e bash s1slots.sh label <game/slot> <new label...>
#   wsl -u root -e bash s1slots.sh delete <game/slot>
#
# The one place the app's Spike 1 slot manager learns what exists and what it
# costs.  Same pipe protocol as the Spike 2 rig's slots.sh so the GUI parsers
# match:
#   root|<saves dir>
#   slot|<game/slot>|<bytes>|<game>|<label>|<mtime epoch>
#   total|<bytes>
#   free|<bytes free on that filesystem>
# Slots are per cache label ($S1_WORK/saves/<label>/<slot>); <game> in the
# record is the cache label, which carries title AND card version - the honest
# compatibility key.
set -u
CMD=${1:-list}
S1_WORK=${S1_WORK:-/home/david/s1emu}
SAVES="$S1_WORK/saves"
[ "$(id -u)" = 0 ] || { echo "s1slots: needs root. Use: wsl -u root -e bash $0 ..."; exit 2; }

ok_name() {
    case "$1" in ""|*[!A-Za-z0-9_.-]*|.|..) return 1 ;; esac
    return 0
}
slot_ref() {   # <game>/<slot>, both components filename-safe
    case "$1" in
    */*)
        ok_name "${1%%/*}" && ok_name "${1#*/}" && [ "${1#*/}" = "${1##*/}" ]
        return $? ;;
    *)  return 1 ;;
    esac
}
meta() {   # meta <dir> <key>
    sed -n "s/^$2=//p" "$1/slot.meta" 2>/dev/null | head -1
}

case "$CMD" in
list)
    echo "root|$SAVES"
    total=0
    if [ -d "$SAVES" ]; then
        for d in "$SAVES"/*/*/; do
            [ -d "$d" ] || continue
            [ -e "$d/restore.env" ] || continue
            g=$(basename "$(dirname "$d")")
            s=$(basename "$d")
            bytes=$(du -sb "$d" 2>/dev/null | cut -f1); : "${bytes:=0}"
            label=$(meta "$d" label | tr '|\n' '  ')
            ep=$(meta "$d" epoch)
            [ -n "$ep" ] || ep=$(stat -c %Y "$d" 2>/dev/null || echo 0)
            echo "slot|$g/$s|$bytes|$g|$label|$ep"
            total=$((total + bytes))
        done
    fi
    echo "total|$total"
    echo "free|$(df -B1 --output=avail "$S1_WORK" 2>/dev/null | tail -1 | tr -d ' ')"
    ;;
label)
    REF=${2:?usage: s1slots.sh label <game/slot> <label...>}
    shift 2
    slot_ref "$REF" || { echo "s1slots: bad slot ref '$REF'"; exit 2; }
    d="$SAVES/$REF"
    [ -d "$d" ] || { echo "s1slots: no slot $REF"; exit 1; }
    L=$(printf '%s' "$*" | tr '|\n' '  ')
    if grep -q '^label=' "$d/slot.meta" 2>/dev/null; then
        sed -i "s/^label=.*/label=$(printf '%s' "$L" | sed 's/[&/\]/\\&/g')/" "$d/slot.meta"
    else
        echo "label=$L" >> "$d/slot.meta"
    fi
    echo "ok"
    ;;
delete)
    REF=${2:?usage: s1slots.sh delete <game/slot>}
    slot_ref "$REF" || { echo "s1slots: bad slot ref '$REF'"; exit 2; }
    d="$SAVES/$REF"
    [ -d "$d" ] || { echo "s1slots: no slot $REF"; exit 1; }
    rm -rf "$d"
    rmdir "$(dirname "$d")" 2>/dev/null   # tidy an emptied per-game dir
    echo "ok"
    ;;
*)
    echo "s1slots: unknown command '$CMD' (list|label|delete)"; exit 2 ;;
esac
