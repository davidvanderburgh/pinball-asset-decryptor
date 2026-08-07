# padpath.sh - SOURCED, never run. The shell twin of padpath.py.
#
#   . "$(dirname "$0")/padpath.sh"
#
# Sets the four things every script in this rig used to carry as a literal:
#
#   RIG     this directory, from the path this file was sourced by
#   ROOT    the guest rootfs      ($PAD_ROOT, else ~/spike2root)
#   TABLES  derived per-title data ($PAD_TABLES, else $ROOT/dump/tables)
#   WINENV  the WSLENV additions a Windows child needs to find all of the above
#
# WHY $0 IS NOT GOOD ENOUGH ON ITS OWN. Several scripts here are sourced by
# others and several are run through `bash <path>`, so BASH_SOURCE is the only
# thing that names THIS file in both cases. It is a bashism and that is fine:
# every script in the rig is `#!/bin/bash` and is invoked as bash.
#
# PATHS ARE EXPORTED, not just set, because run_game.sh, playaudio.sh and the
# rest are separate processes and inherit rather than re-derive. The `:=` form
# means an caller who has already chosen a rootfs keeps it.
RIG=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)
export RIG

: "${PAD_ROOT:=$HOME/spike2root}"
export PAD_ROOT
ROOT=$PAD_ROOT

: "${PAD_TABLES:=$ROOT/dump/tables}"
export PAD_TABLES
TABLES=$PAD_TABLES

# Which distro this is, so a Windows child can ask questions of the RIGHT one.
# WSL sets WSL_DISTRO_NAME; if it is somehow unset the Windows side falls back
# to the default distro, which is right far more often than it is wrong.
: "${PAD_WSL_DISTRO:=${WSL_DISTRO_NAME:-}}"
export PAD_WSL_DISTRO

# ARE WE ON WSL, OR ON A LINUX MACHINE? ONE DEFINITION, HERE.
#
# It decides real behaviour in several places and it must not be answered twice:
# playaudio.sh carried its own copy, and this rig's own rules say never to let
# two scripts define one fact - alive.sh and killgame.sh disagreeing about what
# a running rig is has already cost a session.
#
# WHAT IT CHANGES. Almost everything the rig does is plain Linux - the chroot,
# qemu-user, the node bus, the GL host, the card mount. What WSL needs on top is
# a set of WORKAROUNDS, not features: the playfield window runs as a WINDOWS
# process because this distro has no Tk at all, and audio bridges to a Windows
# player because the WSLg audio hop degrades music. On a Linux desktop both of
# those simply go away and the simpler native path is the correct one.
#
# PAD_FORCE_NATIVE=1 makes a WSL session take the Linux branches, which is how
# the native path can be exercised at all from a Windows development machine.
pad_is_wsl() {
    [ "${PAD_FORCE_NATIVE:-0}" = 1 ] && return 1
    [ -n "${WSL_DISTRO_NAME:-}" ] && return 0
    grep -qi microsoft /proc/version 2>/dev/null
}

# Is the emulated GUEST running? Ask about BOTH process shapes, because the
# qemu interpreter's name is a PLATFORM detail, not a fact about the guest:
# WSL registers qemu under binfmt as `arm-binfmt-P` and that path appears on
# the guest's command line, so `pgrep -f arm-binfmt` works there - and ONLY
# there. In the macOS container no such string exists anywhere, and a wait
# loop grepping for it declared a run whose own log showed 55 fps "never
# started" at the 60 s mark and tore it down. comm is the basename of the
# original ELF (`game`) on every platform measured, so it leads; the
# interpreter names stay because arm-binfmt also matches the chroot's busybox
# sh in the second or two before ./game execs, and qemu-arm covers a container
# whose binfmt rewrites argv with its own interpreter path.
pad_guest_up() {
    pgrep -x game >/dev/null 2>&1 && return 0
    pgrep -f 'arm-binfmt|qemu-arm' >/dev/null 2>&1
}

# ---- WHAT THE HARDWARE SHIM IS BUILT FROM, IN ONE PLACE ------------------
#
# build.sh compiles this list and stamps its digest beside the .so; watch.sh
# compares the same digest and rebuilds when it differs. ONE LIST, for the
# reason build.sh already records in its own comment: alsastub.c was on the
# compile line and missing from the copy list, an edit was silently never
# built, and the build still said "built ok".
PAD_SHIM_SRCS="hwshim.c alsastub.c gststub.c gstvid.c padvid.h padsw.h"
export PAD_SHIM_SRCS

#: Where build.sh records what it compiled.
PAD_SHIM_STAMP=$ROOT/lib/hwshim.srcs
export PAD_SHIM_STAMP

# CONTENT, NOT TIMESTAMPS, and the difference is the whole point.
#
# The obvious test is "is hwshim.c newer than hwshim.so", and it is wrong in
# both directions the moment the rig exists in more than one copy - which it
# now does, because the emulator SHIPS WITH THE APP and a developer has the
# repo as well:
#
#   * installing an OLDER release over a locally built shim leaves every
#     source older than the .so, so nothing rebuilds and the release appears
#     to be under test while the local shim is what runs. That is precisely
#     "test what we are about to release" failing silently.
#   * switching between the two copies flips the answer back and forth on
#     file times that say nothing about what the bytes are.
#
# A digest is the same answer in every direction: different bytes, rebuild.
# Empty when nothing is there, so a caller can tell "no sources" from "these
# sources", and eol=lf is pinned for this directory (see .gitattributes), so
# the repo copy and the installed copy hash identically.
#
# THE DIGEST ITSELF TAKES A LIST, because there are now three of them - the
# shim and the bridge's two halves - and the reasoning above is the same for
# every one. Three copies of these six lines is how the rule this rig keeps
# writing down ("never let two scripts define the same fact") gets broken
# inside a single file.
pad_src_hash() {
    local d=$1 f
    shift
    for f in "$@"; do
        [ -f "$d/$f" ] && cat "$d/$f"
    done | sha256sum | cut -d' ' -f1
}
pad_shim_hash() { pad_src_hash "${1:-$RIG}" $PAD_SHIM_SRCS; }

# ---- WHAT THE GUEST NEEDS BEFORE IT CAN RUN ANYTHING AT ALL ---------------
#
# Two files, and the rig checked for neither. run_game.sh ends in
#
#     chroot "$R" /bin/sh -c "... exec ./game"
#
# and if the chroot cannot start that shell the whole run is over before the
# game is reached, with one line that names the shell and nothing else:
#
#     chroot: failed to run command '/bin/sh': No such file or directory
#
# That message is the kernel's ENOENT and it does NOT mean what it says. It is
# what you get from a rootfs whose /bin/sh is a dangling symlink (this one is
# `/bin/sh -> /bin/bash`, so bash is the file that must exist), and from one
# where the extraction stopped part way. Reported by a user on 2026-08-07 whose
# rootfs had been extracted on an older WSL; every directory the rig checked
# for was there, so nothing before this said a word.
#
# THE HOST'S OWN readlink -f IS THE WRONG TOOL and quietly gives the wrong
# answer: /bin/sh points at the ABSOLUTE path /bin/bash, which on the host is
# the host's own bash - present on every machine, and not the file the chroot
# will open. So links are followed with $ROOT as /, the way the chroot follows
# them. Defined HERE because rootfs.sh (which builds the tree) and
# ensurebuild.sh (which refuses to run against a broken one) must agree about
# what "built" means; two copies of that is the split this rig keeps paying for.

#: Resolve a guest-absolute path as the chroot resolves it. Prints the host
#: path it lands on; non-zero when nothing is there.
pad_guest_path() {              # <guest-absolute-path>
    local p=$1 n=0 link
    while [ -L "$ROOT$p" ] && [ "$n" -lt 20 ]; do
        link=$(readlink "$ROOT$p")
        case "$link" in
            /*) p=$link ;;
            *)  p=${p%/*}/$link ;;
        esac
        n=$((n + 1))
    done
    printf '%s\n' "$ROOT$p"
    [ -e "$ROOT$p" ]
}

#: The first thing the guest cannot start without, or nothing at all. The
#: shell is what run_game.sh execs; the ELF loader is what the kernel opens on
#: its behalf; /usr/lib is where the guest half of the GL bridge is installed.
pad_guest_missing() {
    pad_guest_path /bin/sh >/dev/null 2>&1 || { echo /bin/sh; return 0; }
    if ! pad_guest_path /lib/ld-linux-armhf.so.3 >/dev/null 2>&1 &&
       ! pad_guest_path /lib/ld-linux.so.3       >/dev/null 2>&1; then
        echo /lib/ld-linux-armhf.so.3
        return 0
    fi
    [ -d "$ROOT/usr/lib" ] || echo /usr/lib
}

# ---- WHAT THE GL BRIDGE IS BUILT FROM, THE SAME WAY -----------------------
#
# The bridge is TWO binaries either side of one shared-memory protocol
# (padgl.h): `padglhost`, a NATIVE renderer that owns the window, and
# libGLESv2.so.2 / libEGL.so.1, which are ARM and live inside the guest.
# buildbridge.sh builds them.
#
# WHY THIS EXISTS AT ALL. On 2026-08-07 a user's run died with
#
#     env: './padglhost': No such file or directory
#
# because `buildbridge.sh` had never been run on that machine - it is step
# three of a three-step setup that rootfs.sh only PRINTS - and nothing checked.
# That is the same fault the hardware shim had one release earlier, in a worse
# form: the shim at least ran something old, and this ran nothing at all while
# the tab said "Starting...".
#
# TWO LISTS AND TWO STAMPS, not one. The halves are built by different
# compilers, and a machine can have the native one and not the cross one - so
# a missing arm-linux-gnueabihf-gcc must not be able to withhold the renderer.
# padgl.h is on BOTH lists, so a change to the protocol makes both stale
# together, which is the only way the two are ever allowed to move.
PAD_GLHOST_SRCS="padglhost.c padgl.h padvid.h padsw.h i420.h"
PAD_GLGUEST_SRCS="glbridge.c eglshim.c padgl.h"
export PAD_GLHOST_SRCS PAD_GLGUEST_SRCS

#: The native renderer, and what it was built from - both in $HOME, which is
#: where buildbridge.sh has always put the binary.
PAD_GLHOST_BIN=$HOME/padglhost
PAD_GLHOST_STAMP=$HOME/padglhost.srcs
#: The guest half, stamped beside the libraries it produces.
PAD_GLGUEST_STAMP=$ROOT/usr/lib/glbridge.srcs
export PAD_GLHOST_BIN PAD_GLHOST_STAMP PAD_GLGUEST_STAMP

pad_glhost_hash()  { pad_src_hash "${1:-$RIG}" $PAD_GLHOST_SRCS; }
pad_glguest_hash() { pad_src_hash "${1:-$RIG}" $PAD_GLGUEST_SRCS; }
if pad_is_wsl; then IS_WSL=1; else IS_WSL=0; fi

# WSLENV is how any of this reaches a Windows process, and it is the only way:
# nothing in this environment crosses interop unless it is named there. `/p`
# asks WSL to translate the value from a WSL path to a Windows one, so the
# playfield window receives `\\wsl.localhost\<distro>\...` without either side
# having to know how that string is spelled on this machine.
pad_export_win() {
    WSLENV="${WSLENV:+$WSLENV:}PAD_ROOT/p:PAD_TABLES/p:PAD_WSL_DISTRO"
    export WSLENV
}

# A rig path as Windows sees it. Used to launch the playfield window, which is
# a Windows process and cannot be handed a POSIX path.
pad_win() {
    wslpath -w "$1"
}
