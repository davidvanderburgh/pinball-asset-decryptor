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
# directory is a set at all.
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

# Rewritten WHOLE, never merged: a file the user reverted since the last build
# is absent from the new set, and a leftover copy of it would go on being bound
# over the card - the run would look like it was testing the current edits while
# playing an old one.
#
# The stamp goes FIRST, so a copy that dies half way cannot leave one that says
# the stage is current.
rm -f "$STAMP"
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
give_back "$STAGE" "$STAMP"
echo "[ovr] staged $(find "$STAGE" -type f ! -name "$MANIFEST" | wc -l) file(s)" >&2
echo "$STAGE"
