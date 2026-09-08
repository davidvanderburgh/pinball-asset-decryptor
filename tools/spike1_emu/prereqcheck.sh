#!/bin/bash
# prereqcheck.sh - "is this machine ready to run the Spike 1 emulator, and if
# not, what exactly is missing?"  READ-ONLY: it installs nothing, builds
# nothing and writes nothing.
#
# This is the half of the Fix-setup button that looks.  The half that fixes is
# the app: it downloads the binaries WE built and pinned (core/payloads.py) and
# installs them where this script looks for them, which on an ordinary machine
# leaves nothing here to report at all.  The split is the Spike 2 rig's
# (setupcheck.sh / setupfix.sh) and exists so that finding out what is wrong is
# never something a user has to agree to.
#
# It answers in the same words start.sh would use, because it asks the same
# functions: s1_paths and s1_build_groups from prereqs.sh decide what still
# has to be built, and s1_prereq_report says what building it would need.  Two
# scripts that predict each other cannot disagree if they share the sentence.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/prereqs.sh"
s1_paths

NEED=$(s1_build_groups "$HERE")

# What the app HAS supplied, named by its own stamp, so the log says which
# emulator is installed rather than only that one is.
for f in "$S1_QEMU" "$S1_WORK/s1hwshim"; do
    stamp="$f$S1_PAYLOAD_STAMP_SUFFIX"
    if [ -f "$stamp" ]; then
        echo "Installed: $(sed -n 's/^version=//p' "$stamp") — $(basename "$f")"
    elif [ -x "$f" ]; then
        echo "Built here: $(basename "$f") (compiled on this machine)"
    fi
done

if [ -z "$NEED" ]; then
    echo "The emulator is ready — nothing to install."
    exit 0
fi

case " $NEED " in
    *" qemu "*) echo "The ARM emulator is not installed yet." ;;
esac
case " $NEED " in
    *" shim "*) echo "The device model is not installed yet, or does not match the sources shipped with this app version." ;;
esac

# Only if we would have to BUILD it here does the machine need build tools;
# the app installing our binary is the ordinary path and needs none of this.
if s1_prereq_report $NEED; then
    echo "This machine can build what is missing (Start will do it)."
fi
exit 0
