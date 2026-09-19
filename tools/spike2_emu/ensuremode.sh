#!/bin/bash
# ensuremode.sh [card.raw] - the mode objects, BUILT and where a card build takes
# them from. Item 128.
#
#   wsl -e bash <rig>/ensuremode.sh /mnt/d/Pinball/images/godzilla_pro.raw
#
# THE SAME SHAPE AS ensureselect.sh, and for the same reason. That script exists
# because the Multi-boot tab would build a selector for its PREVIEW, install
# nothing, and then fail the actual card build seconds later with a sentence
# naming a directory the person had never heard of. The lesson written into it is
# to ASK THE DIRECTORY what is there rather than trust a build that said it
# worked, and to refuse NAMING THE MISSING FILE.
#
# A card build that ships without mode.so is worse than a refusal: the card boots
# perfectly, plays stock, and nothing anywhere says why the mode never ran. The
# hook is guarded on the .so existing (modehook.py), so a missing object is
# SILENT by design - which is exactly why the check belongs here, before the
# build, and not in a log afterwards.
#
# WHAT IT CHECKS, in the order a build needs them:
#   1. the cross compiler and the guest filesystem, via build_modes.sh, which
#      links against the CARD's own libc (glibc 2.21 symbol versions) - a mode
#      built against this PC's glibc loads on no machine at all;
#   2. mode.so actually present in the stage afterwards;
#   3. a mode FILE to go with it - mode.so with no mode file runs nothing, and
#      logs "no mode file at ... yet - polling" forever.
. "$(dirname "$0")/padpath.sh"

#: How this script spells a refusal. Same prefix convention as ensureselect.sh:
#: one line each, however long, because a caller shows the LAST line carrying
#: the prefix and a sentence split over three of them arrives as its last third.
ERR="[mode] error:"

MODE_CFG=${PAD_MODE_CFG:-$RIG/modes/kaiju_rush.mode}

if [ -n "${1:-}" ]; then
    PAD_CARD=$1
    export PAD_CARD
fi

if ! pad_stage >/dev/null 2>&1; then
    echo "$ERR there is no build stage to put the mode objects in - see the lines above" >&2
    exit 1
fi

echo "[mode] building mode.so against the card's own filesystem"
if ! bash "$RIG/modes/build_modes.sh"; then
    if ! command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; then
        echo "$ERR the mode could not be built: this Linux has no arm-linux-gnueabihf-gcc (on Debian/Ubuntu: apt install gcc-arm-linux-gnueabihf), and that is what builds it" >&2
    elif [ ! -d "$ROOT/lib" ]; then
        echo "$ERR the mode is compiled against the machine's own filesystem and this PC has not unpacked one yet - there is no $ROOT/lib to link against" >&2
    else
        echo "$ERR the mode could not be built - see the lines above. It belongs at $PAD_STAGE/mode.so" >&2
    fi
    exit 1
fi

# WHAT THE INSTALLER WILL ACTUALLY LOOK FOR, asked of the stage rather than taken
# on trust from a build that printed "built ok".
missing=
[ -f "$PAD_STAGE/mode.so" ] || missing="$missing mode.so"
[ -f "$MODE_CFG" ] || missing="$missing $(basename "$MODE_CFG")"
if [ -n "$missing" ]; then
    echo "$ERR missing$missing, so a card built now would carry no mode (the hook is guarded on the .so, so the card would boot and play stock with nothing to say why)" >&2
    exit 1
fi

# The mode file has to fit mode.c's parser: CFG_MAX is 4096 and there is no
# allocator, so a longer file is silently truncated at the read.
sz=$(stat -c %s "$MODE_CFG")
if [ "$sz" -gt 4096 ]; then
    echo "$ERR $MODE_CFG is $sz bytes; mode.so reads at most 4096 (CFG_MAX, fixed buffer, no allocator) and would silently use only the first 4096" >&2
    exit 1
fi

echo "[mode] object:    $PAD_STAGE/mode.so ($(stat -c %s "$PAD_STAGE/mode.so") bytes)"
echo "[mode] mode file: $MODE_CFG ($sz bytes)"
echo "[mode] install with: python3 $RIG/mode_install.py install <card.raw> --so $PAD_STAGE/mode.so --cfg $MODE_CFG"
