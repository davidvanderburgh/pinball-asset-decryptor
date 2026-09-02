#!/bin/bash
# overrides.sh <override-dir> - stage the app's OVERRIDE SET on the Linux disk
# and print where it landed (last line, like cardmount.sh).
#
#   overrides.sh /mnt/c/Users/david/.../gz/build/emulator-overrides
#   -> $HOME/override                    (and prints it)
#
# WHAT AN OVERRIDE SET IS. PAD builds one instead of a whole new card image
# when you want to hear an edited callout on the PC (PAD-103): it holds only
# the card FILES your edits touch, already patched - typically `image.bin` and
# the `.sidx` record beside it - laid out exactly as they sit on the games
# partition. run_game.sh bind-mounts each of them over the read-only card mount,
# which is the same trick that masks james_bond_60th's boot_display_cmd (item
# 45), so the guest reads your bytes with nothing copied and nothing rebuilt.
# `overrides.json` is the manifest and is NEVER bound; it is also what says a
# directory is a set at all. `overrides.delta` is not bound either: it is what
# THIS script reads, below.
#
# WHY THE SET IS COPIED HERE RATHER THAN BOUND WHERE IT LIES. The same reason
# the card itself is copied (item 74): a set built on Windows lives on /mnt/c,
# every read of it crosses 9p, and the biggest file in a set is `image.bin` -
# the sound bank, which the game reads for the whole run. The card cache exists
# because that path was measured at roughly half of native; putting the sounds
# back on it would undo item 74 for exactly the runs this feature is for. The
# copy is skipped when the staged set already matches (size+mtime+name of every
# file), so only a REBUILT set costs anything, and a set of two replaced videos
# costs milliseconds either way.
#
# AND A REBUILT SET IS USUALLY NOT A NEW ONE. The app builds each set by
# patching the one before it and writes down what that changed
# (`overrides.delta`: a generation, the parent it came from, and the byte
# ranges). When the stage holds exactly that parent, this brings it forward
# with those ranges - a few MB for an edited callout - instead of copying a
# 1.4 GB image.bin across 9p again. Change one sound, press Start, and neither
# side copies the sound bank: that is the whole point of PAD-103, and staging
# it whole every time would have handed most of the cost straight back.
#
# PAD_OVERRIDE_STAGE=0 binds straight from where the set is, for a Linux
# desktop where there is no 9p to avoid.
set -u

SELF=$(cd "$(dirname "$0")" && pwd)
# $PAD_HOME for the same reason cardmount.sh uses it: the GUI starts a run as
# root (PAD_PIVOT) and $HOME is then /root, where this rig has never lived.
. "$SELF/padpath.sh"
STAGE=$PAD_HOME/override
# The stamp lives BESIDE the stage, never in it: run_game.sh binds every file it
# finds under the staged tree over the card, and a stamp inside would be one
# more file with no card path to land on - i.e. a failed run.
STAMP=$PAD_HOME/override.src
MANIFEST=overrides.json
DELTA=overrides.delta
# Which generation of the set the stage holds. Beside the stage like the stamp
# and for the same reason: run_game.sh binds every file it finds inside it.
GENF=$PAD_HOME/override.gen

die() { echo "[ovr] $*" >&2; exit 1; }

SRC=${1:-}
[ -n "$SRC" ] || die "usage: overrides.sh <override-dir>"
SRC=${SRC%/}
[ -d "$SRC" ] || die "no such override folder: $SRC"
[ -f "$SRC/$MANIFEST" ] || die "$SRC holds no $MANIFEST - not an override set"

# HAND FILES BACK when this runs as root, exactly as cardmount.sh does: the
# stage lives under the desktop user's home, and a root-owned tree there is one
# the next ordinary run can neither overwrite nor delete.
give_back() {
    [ "$(id -u)" = 0 ] || return 0
    local o
    o=$(stat -c %U "$PAD_HOME" 2>/dev/null)
    [ -n "$o" ] && [ "$o" != root ] && chown -R "$o" "$@" 2>/dev/null
    return 0
}

# The identity of a set: every file's path, size and mtime, taken from the
# SOURCE and remembered in the stamp. NOT a content hash - the point of this
# feature is a fast turnaround, and re-reading a 1.4 GB image.bin over 9p to
# decide whether to copy it costs as much as copying it. A rebuild always moves
# an mtime, which is the case that has to invalidate.
#
# NOT a signature of the STAGE compared against the source, which is what this
# did first and is why the check never once fired in testing: `cp` does not
# preserve mtimes, so a freshly staged copy never matched the thing it had just
# been copied from and every run re-staged the whole set.
signature() {   # <dir>
    ( cd "$1" && find . -type f -printf '%P %s %T@\n' 2>/dev/null | LC_ALL=C sort )
}

# Bring the stage forward one generation, or return 1 and let the full copy
# below deal with it. Deliberately unforgiving: every mismatch here (no delta,
# a stage of some other generation, a file the delta names that the stage does
# not have, a dd that fails) falls back to copying the set whole, because a
# stage that is PART of one build and part of another is a run that plays a
# sound the user took back while the tab says it is testing their edits.
#
# The stamps go first, so an update that dies half way cannot leave one saying
# the stage is current.
stage_delta() {
    local gen par held line kind rest rel off len mism n=0 gone=0 bytes=0
    [ -f "$SRC/$DELTA" ] || return 1
    [ -f "$STAGE/$MANIFEST" ] || return 1
    gen=$(sed -n 's/^generation //p' "$SRC/$DELTA" | head -1)
    par=$(sed -n 's/^parent //p' "$SRC/$DELTA" | head -1)
    [ -n "$gen" ] && [ -n "$par" ] && [ "$par" != - ] || return 1
    held=$(cat "$GENF" 2>/dev/null || true)
    [ -n "$held" ] && [ "$held" = "$par" ] || return 1

    rm -f "$STAMP" "$GENF"
    while IFS= read -r line; do
        case $line in ''|'#'*) continue ;; esac
        kind=${line%% *}
        rest=${line#* }
        case $kind in
        generation|parent) ;;
        remove)
            rm -f "$STAGE/$rest" || return 1
            gone=$(( gone + 1 )) ;;
        whole)
            mkdir -p "$(dirname "$STAGE/$rest")" || return 1
            cp -L "$SRC/$rest" "$STAGE/$rest" || return 1
            n=$(( n + 1 ))
            bytes=$(( bytes + $(stat -c %s "$STAGE/$rest" 2>/dev/null \
                                || echo 0) )) ;;
        range)
            # The path is LAST on the line, so a card path with a space in it
            # survives this. bs=1M with *_bytes: the ranges are byte offsets
            # into a multi-GB file and bs=1 would take all day.
            off=${rest%% *}; rest=${rest#* }
            len=${rest%% *}; rel=${rest#* }
            [ -f "$STAGE/$rel" ] || return 1
            dd if="$SRC/$rel" of="$STAGE/$rel" bs=1M status=none \
               conv=notrunc iflag=skip_bytes,count_bytes oflag=seek_bytes \
               skip="$off" seek="$off" count="$len" || return 1
            bytes=$(( bytes + len )) ;;
        *)  return 1 ;;
        esac
    done < "$SRC/$DELTA"
    cp -L "$SRC/$MANIFEST" "$STAGE/$MANIFEST" || return 1

    # AND THEN CHECK IT, cheaply, because a set is a handful of files: every
    # file the source has must now be in the stage at the same size. It does
    # not prove the bytes, but it catches the shapes of failure that matter -
    # a file the stage never had, a dd that wrote nothing - and those are the
    # ones that would otherwise be bound over the card as an older edit.
    mism=$( ( cd "$SRC" && find . -type f ! -name "$MANIFEST" \
                                          ! -name "$DELTA" \
                                          -printf '%P %s\n' ) \
            | while IFS= read -r line; do
                  rel=${line% *}
                  [ "$(stat -c %s "$STAGE/$rel" 2>/dev/null || echo -)" \
                        = "${line##* }" ] || printf 'x'
              done )
    [ -z "$mism" ] || return 1

    chmod -R u+rwX "$STAGE" 2>/dev/null
    printf '%s\n' "$WANT" > "$STAMP"
    printf '%s\n' "$gen" > "$GENF"
    give_back "$STAGE" "$STAMP" "$GENF"
    echo "[ovr] staged your changes only: $(( (bytes + 1023) / 1024 )) KB," \
         "$n file(s) replaced, $gone dropped" >&2
    return 0
}

if [ "${PAD_OVERRIDE_STAGE:-1}" = 0 ]; then
    echo "[ovr] staging off (PAD_OVERRIDE_STAGE=0) - binding from $SRC" >&2
    echo "$SRC"
    exit 0
fi

WANT=$(signature "$SRC")
if [ -f "$STAGE/$MANIFEST" ] && [ -f "$STAMP" ] \
        && [ "$WANT" = "$(cat "$STAMP" 2>/dev/null)" ]; then
    echo "[ovr] the staged set already matches $SRC" >&2
    echo "$STAGE"
    exit 0
fi

if stage_delta; then
    echo "$STAGE"
    exit 0
fi

# Rewritten WHOLE, never merged: a file the user reverted since the last build
# is absent from the new set, and a leftover copy of it would go on being bound
# over the card - the run would look like it was testing the current edits while
# playing an old one.
#
# The stamps go FIRST, so a copy that dies half way cannot leave one that says
# the stage is current.
rm -f "$STAMP" "$GENF"
rm -rf "$STAGE" || die "could not clear $STAGE"
mkdir -p "$STAGE" || die "could not create $STAGE"
KB=$(du -sk "$SRC" 2>/dev/null | cut -f1)
echo "[ovr] staging $(( ${KB:-0} / 1024 )) MB of override files -> $STAGE" >&2
# -L, and no -a: the card's own files are root's on a set built from a device,
# and preserving ownership fails a non-root copy on a permission it does not
# need. The guest only ever reads these.
cp -rL "$SRC/." "$STAGE/" || { rm -rf "$STAGE"; die "could not stage $SRC"; }
chmod -R u+rwX "$STAGE" 2>/dev/null
printf '%s\n' "$WANT" > "$STAMP"
# What the NEXT set will be patched out of. Without this every build after a
# full copy would be a full copy too, since a stage of no known generation is
# one nothing can be applied to.
sed -n 's/^generation //p' "$SRC/$DELTA" 2>/dev/null | head -1 > "$GENF"
give_back "$STAGE" "$STAMP" "$GENF"
echo "[ovr] staged $(find "$STAGE" -type f ! -name "$MANIFEST" | wc -l) file(s)" >&2
echo "$STAGE"
