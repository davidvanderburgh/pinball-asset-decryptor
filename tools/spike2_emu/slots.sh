#!/bin/bash
# slots.sh - list, relabel and delete save-state slots. (item 13's GUI half)
#
#   wsl -u root -e bash slots.sh list
#   wsl -u root -e bash slots.sh label <slot> <new label...>
#   wsl -u root -e bash slots.sh delete <slot>
#
# The ONE place both GUIs (the app's Emulate tab manager and the playfield's
# slot picker) learn what exists and what it costs. Root because savegame.sh
# writes slots as root, so listing sizes and deleting need it too.
#
# Machine-readable output, one record per line, pipe-separated:
#   root|<rootfs saves dir>
#   slot|<name>|<bytes>|<game>|<label>|<mtime epoch>
#   total|<bytes>
#   free|<bytes free on that filesystem>
# The label is last-but-one and may contain anything except | and newline
# (savegame/label sanitise those); parsers split on | with maxsplit.
#
# WHERE THE SLOTS LIVE: <rootfs>/saves. The rootfs comes from the running
# guest when there is one (its own PAD_ROOT, the proven path), else from any
# slot.meta a known location holds, else the conventional /home/*/spike2root.
# Same ladder loadgame.sh climbs, for the same reason: a cold app with no
# game up must still be able to show and clean the slots.

set -u
CMD=${1:-list}

[ "$(id -u)" = 0 ] || { echo "slots: needs root. Use: wsl -u root -e bash $0 ..."; exit 2; }

# --- find the saves dir ---------------------------------------------------
find_root() {
    local pid r d
    pid=$(pgrep -x game | head -1)
    if [ -n "$pid" ]; then
        r=$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null \
            | sed -n 's/^PAD_ROOT=//p' | head -1)
        [ -n "$r" ] && [ -d "$r/saves" ] && { echo "$r/saves"; return 0; }
    fi
    for d in /home/*/spike2root/saves /root/spike2root/saves; do
        [ -d "$d" ] && { echo "$d"; return 0; }
    done
    return 1
}
SAVES=$(find_root) || { echo "slots: no saves directory found"; exit 1; }

# A name component is a FILENAME under $SAVES, never a path - it reaches
# rm -rf.
ok_name() {
    case "$1" in ""|*[!A-Za-z0-9_.-]*|.|..) return 1 ;; esac
    return 0
}
# ★ ITEM 39: SLOTS ARE PER GAME - $SAVES/<game>/<slot>. David: "i thought we
# had 10 slots per game?" They were 10 GLOBAL slots that every game shared,
# which is how turtles' picker came to offer a godzilla save as slot 1. A
# slot is now addressed as <game>/<slot>; a bare name is a LEGACY slot still
# at the top level (pre-migration, or one whose meta never recorded a game).
slot_ref() {  # validates $1, bare or game/slot; both components filename-safe
    case "$1" in
    */*)
        g=${1%%/*}; s=${1#*/}
        case "$s" in */*) return 1 ;; esac
        ok_name "$g" && ok_name "$s" ;;
    *)
        ok_name "$1" ;;
    esac
}
# Only ever touch a directory that really is a slot (has the checkpoint's
# metadata), so a stray directory someone made by hand cannot be deleted.
is_slot() { [ -f "$SAVES/$1/slot.meta" ] || [ -f "$SAVES/$1/restore.env" ]; }

meta() {  # meta <slot> <key>
    sed -n "s/^$2=//p" "$SAVES/$1/slot.meta" 2>/dev/null | head -1
}

# --- MIGRATE LEGACY SLOTS the moment any caller arrives -------------------
# A top-level slot whose meta names its game moves into that game's
# directory: same filesystem, so the mv is a rename, not a copy of 60 MB.
# One with no recorded game stays bare and keeps working as before.
for _d in "$SAVES"/*/; do
    [ -d "$_d" ] || continue
    _s=${_d%/}; _s=${_s##*/}
    is_slot "$_s" || continue
    _g=$(meta "$_s" game)
    ok_name "$_g" || continue
    mkdir -p "$SAVES/$_g"
    [ -e "$SAVES/$_g/$_s" ] || mv "$SAVES/$_s" "$SAVES/$_g/$_s"
done

case "$CMD" in
list)
    # Both levels: per-game slots as <game>/<slot>, plus any legacy bare
    # slot the migration could not place. The name field IS the reference
    # every other command takes, so a parser can hand it straight back.
    echo "root|$SAVES"
    total=0
    for d in "$SAVES"/*/ "$SAVES"/*/*/; do
        [ -d "$d" ] || continue
        s=${d%/}; s=${s#"$SAVES"/}
        is_slot "$s" || continue
        bytes=$(du -sb "$SAVES/$s" 2>/dev/null | cut -f1)
        bytes=${bytes:-0}
        total=$((total + bytes))
        mt=$(stat -c %Y "$SAVES/$s/slot.meta" 2>/dev/null \
             || stat -c %Y "$SAVES/$s" 2>/dev/null || echo 0)
        printf 'slot|%s|%s|%s|%s|%s\n' \
            "$s" "$bytes" "$(meta "$s" game)" \
            "$(meta "$s" label | tr '|' ' ')" "$mt"
    done
    echo "total|$total"
    echo "free|$(df -B1 --output=avail "$SAVES" 2>/dev/null | tail -1 | tr -d ' ')"
    ;;
label)
    SLOT=${2:?usage: slots.sh label <game/slot> <label...>}
    shift 2
    LABEL=$(printf '%s' "$*" | tr '\n\r|' '   ')
    slot_ref "$SLOT" || { echo "slots: bad slot name '$SLOT'"; exit 2; }
    is_slot "$SLOT" || { echo "slots: no such slot '$SLOT'"; exit 1; }
    M=$SAVES/$SLOT/slot.meta
    [ -f "$M" ] || : > "$M"
    sed -i '/^label=/d' "$M"
    [ -n "$LABEL" ] && echo "label=$LABEL" >> "$M"
    echo "slots: '$SLOT' label is now '${LABEL:-<none>}'"
    ;;
delete)
    SLOT=${2:?usage: slots.sh delete <game/slot>}
    slot_ref "$SLOT" || { echo "slots: bad slot name '$SLOT'"; exit 2; }
    is_slot "$SLOT" || { echo "slots: no such slot '$SLOT'"; exit 1; }
    rm -rf "${SAVES:?}/$SLOT"
    # A game directory with nothing left in it is noise, not state.
    rmdir "$SAVES/${SLOT%%/*}" 2>/dev/null
    echo "slots: deleted '$SLOT'"
    ;;
pack)
    # Compress a RAW slot in place (new saves pack themselves; this is for
    # slots from before packing existed). Same tar|zstd shape as savegame.sh,
    # slot.meta kept plain beside the pack.
    SLOT=${2:?usage: slots.sh pack <game/slot>}
    slot_ref "$SLOT" || { echo "slots: bad slot name '$SLOT'"; exit 2; }
    is_slot "$SLOT" || { echo "slots: no such slot '$SLOT'"; exit 1; }
    [ -f "$SAVES/$SLOT/slot.tar.zst" ] \
        && { echo "slots: '$SLOT' is already packed"; exit 0; }
    command -v zstd >/dev/null 2>&1 || { echo "slots: no zstd"; exit 1; }
    # tr, because the ref may carry the game's slash and the scratch file
    # must stay a single name at the top level.
    PACK=$SAVES/.pack.$(printf '%s' "$SLOT" | tr / _).$$
    if tar -C "$SAVES/$SLOT" -cf - --exclude='./slot.meta' . 2>/dev/null \
            | zstd -3 -T0 -q -f -o "$PACK"; then
        find "$SAVES/$SLOT" -mindepth 1 ! -name slot.meta -delete
        mv "$PACK" "$SAVES/$SLOT/slot.tar.zst"
        echo "slots: packed '$SLOT' to $(du -h "$SAVES/$SLOT/slot.tar.zst" | cut -f1)"
    else
        rm -f "$PACK"
        echo "slots: packing '$SLOT' failed - the slot is unchanged"
        exit 1
    fi
    ;;
*)
    echo "usage: slots.sh list | label <game/slot> <text...> |" \
         "delete <game/slot> | pack <game/slot>"
    exit 2
    ;;
esac
