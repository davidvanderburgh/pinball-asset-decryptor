#!/bin/bash
# setupcheck.sh - "can this machine emulate AT ALL?", answered as key=value
# facts, before a run rather than half way through one.
#
# WHY THIS EXISTS. Every tool the rig needs was discovered ONE AT A TIME, by
# failing on it: rootfs.sh dies without debugfs, the guest-exec probe dies
# without a registered qemu-arm, build.sh dies without the ARM cross compiler.
# Each of those prints a good sentence naming its own missing package, and a
# user who is missing three of them meets those sentences on three separate
# runs, minutes apart. A tester reached the second one on 2026-08-07 - no ARM
# handler, on a machine that had never had qemu-user-static - and what he saw
# was a wall of log text arriving after Start appeared to work.
#
# THIS ASKS ALL OF IT AT ONCE, COSTS ONE ROUND TRIP, AND CHANGES NOTHING. It is
# read-only on purpose: what to DO about the answer is setupfix.sh, and the two
# are separate so that looking is never something a user has to consent to.
#
# NO SECOND SOURCE OF TRUTH. The ARM handler is found by ensurebuild.sh's own
# _pad_binfmt_arm, and the command that would register it by its own
# _pad_binfmt_advice - the same functions the real run uses, so this can never
# disagree with the thing it is predicting. That rule is this rig's oldest one
# (alive.sh and killgame.sh disagreeing about what a running rig is has already
# cost a session).
#
# OUTPUT: key=value lines, one per fact, parsed by the Emulate tab.
#
#   qemu|armgcc|debugfs|fuse   1 = the tool is on PATH, 0 = it is not
#   binfmt                     1 = a 32-bit ARM handler is registered and
#                              enabled, disabled = registered but switched
#                              off, 0 = the kernel has none
#   entry                      the binfmt_misc file, when there is one
#   advice                     the command that would register it ON THIS
#                              MACHINE (Ubuntu 24.04 and Debian differ, which
#                              is why this is asked rather than assumed)
#   wslconf                    1 = this distro boots systemd, so the
#                              registration survives a restart. Only
#                              meaningful on WSL, where it is the difference
#                              between fixing this once and fixing it weekly.
#   iswsl                      1 = WSL, 0 = a Linux machine or a container

. "$(dirname "$0")/padpath.sh"
. "$(dirname "$0")/ensurebuild.sh"

_have() { command -v "$1" >/dev/null 2>&1 && echo 1 || echo 0; }

echo "qemu=$(_have qemu-arm-static)"
echo "armgcc=$(_have arm-linux-gnueabihf-gcc)"
echo "debugfs=$(_have debugfs)"
echo "fuse=$(_have fusermount3)"

entry=$(_pad_binfmt_arm)
if [ -z "$entry" ]; then
    echo "binfmt=0"
elif [ "$(head -1 "$entry" 2>/dev/null)" = disabled ]; then
    echo "binfmt=disabled"
    echo "entry=$entry"
else
    echo "binfmt=1"
    echo "entry=$entry"
fi

echo "advice=$(_pad_binfmt_advice)"

if pad_is_wsl; then
    echo "iswsl=1"
    # The registration lives in the RUNNING kernel and is put back at boot by
    # systemd-binfmt. A distro started without systemd loses it on every
    # `wsl --shutdown`, so this is not cosmetic: without it the same repair is
    # needed again next week, and the user has no way to know why.
    if [ "$(ps -p 1 -o comm= 2>/dev/null)" = systemd ]; then
        echo "wslconf=1"
    else
        echo "wslconf=0"
    fi
else
    echo "iswsl=0"
    echo "wslconf=1"
fi
