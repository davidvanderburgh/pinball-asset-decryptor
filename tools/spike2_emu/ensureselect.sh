#!/bin/bash
# ensureselect.sh [card.raw] - the boot menu program, INSTALLED where a card
# build takes it from.
#
#   wsl -e bash <rig>/ensureselect.sh /mnt/d/Pinball/images/turtles_pro.raw
#
# mkmulticard.py's --selector-dir is a DIRECTORY holding codeselect (the ARM
# program the machine boots), select.sh and a font, and buildselect.sh is what
# puts those in $ROOT/usr/local/codeselect. Nothing in the app had ever run it.
# The Multi-boot tab has always built a selector for its PREVIEW - a scratch
# `make all` into ~/emusrc, installing nothing - so a person could fill the
# form in, watch their own menu animate, press Build, and get
#
#   [card] error: selector dir /home/x/spike2root/usr/local/codeselect is not a directory
#   [multi-boot] build failed (exit 2) - see the tool output.
#
# seconds later, with nothing on the tab or in that sentence to act on
# (PAD-105, 2026-09-06: "i am failing when i try to build the image").
#
# THE QUESTION IS ASKED THE WAY THE RIG ASKS EVERY OTHER "is it built" -
# ensurebuild.sh's rules, called, not a second copy of them:
#
#   * no guest filesystem   -> built from the card image the build is using
#                              (pad_ensure_rootfs; minutes, once)
#   * no menu program       -> built (buildselect.sh), and a failure here is
#                              fatal, because a card with no menu is not the
#                              card that was asked for
#   * sources have moved on -> rebuilt, but never fatally: what is installed
#                              still boots, and a missing cross compiler must
#                              not take card building away from someone whose
#                              menu is merely a version behind
#
# The card argument is only used to build the guest filesystem the first time;
# every later run finds it there and costs a digest of the selector's sources.
. "$(dirname "$0")/padpath.sh"
. "$(dirname "$0")/ensurebuild.sh"

#: Where buildselect.sh installs, which is exactly what --selector-dir is
#: given. PAD_SELECT_BIN (padpath.sh) is the file inside it.
SEL_DIR=$ROOT/usr/local/codeselect
#: How this script spells a refusal. The app reads this prefix off the log and
#: shows the sentence behind it instead of an exit code, so every one of them
#: is written to be read by somebody who has just pressed a button.
#:
#: ONE LINE EACH, however long. The app takes the LAST line carrying this
#: prefix, so a sentence split over three of them reached the tab as its last
#: third ("selector failed (exit 1) - above. Expected at ...") - measured, in
#: this ticket's own before/after run.
ERR="[selector] error:"

if [ -n "${1:-}" ]; then
    PAD_CARD=$1
    export PAD_CARD
fi

# WHY A CARD BUILD IS UNPACKING A FILESYSTEM. pad_ensure_rootfs says "the game
# runs inside" it, which is true and is not the reason here: the selector is
# compiled against the card's own glibc and GL libraries, so the rootfs is the
# sysroot this build needs. Said before its lines rather than instead of them.
if [ ! -d "$ROOT/usr/lib" ]; then
    echo "[selector] the boot menu program is compiled against the machine's"
    echo "[selector] own filesystem, and this PC has not unpacked one yet."
fi
if ! pad_ensure_rootfs; then
    echo "$ERR there is no guest filesystem at $ROOT to build the boot menu program against, and it could not be made - see the lines above" >&2
    exit 1
fi
if ! pad_ensure_select; then
    echo "$ERR the boot menu program could not be built - see the lines above. It belongs at $PAD_SELECT_BIN" >&2
    exit 1
fi

# WHAT THE BUILDER WILL ACTUALLY LOOK FOR, asked of the directory rather than
# taken on trust from a build that said it worked: mkmulticard.py refuses
# without either of these two, and it refuses after the plan, which is much
# later than here.
missing=
for f in codeselect select.sh; do
    [ -e "$SEL_DIR/$f" ] || missing="$missing $f"
done
if [ -n "$missing" ]; then
    echo "$ERR $SEL_DIR has no$missing in it, so a card built now would carry no menu" >&2
    exit 1
fi
echo "[selector] menu program: $SEL_DIR"
