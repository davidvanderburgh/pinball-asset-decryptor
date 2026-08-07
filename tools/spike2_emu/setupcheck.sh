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
#   need                       the packages that would supply the missing
#                              ones, in apt's spelling
#   nocand                     those of `need` that apt CANNOT install on this
#                              machine - see below
#   universe                   1 = nothing to say. 0 = this is Ubuntu, a
#                              needed package is unavailable, and the
#                              `universe` component that carries it is
#                              switched off in apt's sources
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

#: WHAT THE EMULATOR NEEDS BEYOND THE RIG: fact key, the tool that IS the
#: fact, and the package that is only how apt spells it. THE RIG'S ONE COPY -
#: setupfix.sh installs what this reports as missing rather than keeping a
#: second list, because two lists in two scripts is exactly how the thing that
#: is explained and the thing that is installed stop being the same four.
PAD_SETUP_TOOLS="qemu:qemu-arm-static:qemu-user-static
armgcc:arm-linux-gnueabihf-gcc:gcc-arm-linux-gnueabihf
debugfs:debugfs:e2fsprogs
fuse:fusermount3:fuse3"

need=
for _t in $PAD_SETUP_TOOLS; do
    _key=${_t%%:*}; _rest=${_t#*:}; _tool=${_rest%%:*}; _pkg=${_rest#*:}
    echo "$_key=$(_have "$_tool")"
    command -v "$_tool" >/dev/null 2>&1 || need="$need $_pkg"
done
echo "need=${need# }"

#: CAN apt actually install them? "Missing" and "installable" are two
#: different facts, and only asking the first is what put a tester in front of
#:
#:     E: Package 'qemu-user-static' has no installation candidate
#:
#: after the tab had told him a button would install it. That message is not a
#: download that failed: it is apt saying it knows the NAME and has no VERSION
#: - which on Ubuntu means the `universe` component that carries
#: qemu-user-static is switched off. `main` packages beside it in the same
#: command resolve fine, which is why exactly one of his four was named.
#:
#: Asked only about what is already missing, so a healthy machine pays nothing.
nocand=
if [ -n "$need" ] && command -v apt-cache >/dev/null 2>&1; then
    for _pkg in $need; do
        apt-cache policy -- "$_pkg" 2>/dev/null |
            sed -n 's/^[[:space:]]*Candidate:[[:space:]]*//p' |
            grep -qv '^(none)$' || nocand="$nocand $_pkg"
    done
fi
echo "nocand=${nocand# }"

#: ...and if that is why, say so, because it is repairable. Ubuntu only: on
#: Debian qemu-user-static is in `main` and an unavailable package means
#: something else entirely, which a wrong-but-confident answer would hide.
#: apt-get indextargets is apt's own view of what is configured, so a country
#: mirror, ports.ubuntu.com and a deb822 ubuntu.sources all answer correctly
#: where grepping a file for a hostname would not.
if [ -n "$nocand" ] &&
   grep -qs '^ID=ubuntu' /etc/os-release &&
   ! apt-get indextargets --format '$(COMPONENT)' 2>/dev/null |
       grep -qx universe; then
    echo "universe=0"
else
    echo "universe=1"
fi

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
