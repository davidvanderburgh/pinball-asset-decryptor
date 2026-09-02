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

# WHOSE rig is this? $HOME IS NOT THE ANSWER WHEN RUNNING AS ROOT, and that is
# not an edge case - it is how the app starts and stops every run
# (`wsl.exe -u root ...`). As root $HOME is /root, where this rig has never
# lived, so every path and every pkill pattern built from $HOME silently points
# at a directory that does not exist. Nothing errors; the globs just match
# nothing and the patterns just match nothing.
#
# THAT COST AN HOUR ON 2026-08-11. killgame.sh globs "$HOME/card/"*/ to unmount
# the card and matches "^tail ... $HOME/padvid\.log" to kill the event feed.
# Run as root both became /root/..., so the card was never unmounted and the
# tail never killed - while alive.sh, counting the same things by other
# patterns, correctly reported them still up. The teardown then printed
# PAD_STOP_NEEDS_WSL_RESTART, which reads as "this needs a VM restart" and
# invites someone to kill fuse2fs by hand - and killing the fuse daemon instead
# of unmounting leaves the kernel holding a mount with no userspace behind it,
# so the NEXT run dies at "Transport endpoint is not connected" before it can
# even create its mountpoint. One wrong $HOME, three failures deep.
#
# So: resolve the rig's home ONCE, here, and let every script use it. An
# explicit PAD_HOME always wins; after that the order below applies.
#
# ROOT IS ELEVATION, NOT OWNERSHIP, and that is the rule that makes this work.
# The rig belongs to a human's home; root is only how the scripts get the caps
# to mount and chroot. So when $HOME is /root we do NOT trust it - not even if
# /root/spike2root exists, because it usually does: any earlier root-without-
# HOME run leaves a half-built one there, and this machine has exactly that
# from 2026-08-08. Picking it would be the same silent-wrong-path bug in a new
# costume, and worse, because it would look like a real rig.
_pad_hasrig() { [ -d "$1/spike2root" ] || [ -d "$1/card" ]; }
if [ -z "${PAD_HOME:-}" ]; then
    if [ "$(id -u)" != 0 ] && _pad_hasrig "$HOME"; then
        PAD_HOME=$HOME                       # ordinary user: their own rig
    elif [ -n "${SUDO_USER:-}" ] && _pad_hasrig "/home/$SUDO_USER"; then
        PAD_HOME=/home/$SUDO_USER            # sudo names the human; believe it
    else
        for _h in /home/*/; do               # the one /home/* that has a rig
            if _pad_hasrig "${_h%/}"; then PAD_HOME=${_h%/}; break; fi
        done
        unset _h
    fi
    # Nothing found: fall back to $HOME. On a fresh machine that is where a rig
    # should be built; as root with no user rig it is at least honest about
    # where it looked.
    : "${PAD_HOME:=$HOME}"
fi
export PAD_HOME

: "${PAD_ROOT:=$PAD_HOME/spike2root}"
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

# ---- WHAT A CHECKPOINTABLE BOOT NEEDS AND AN ORDINARY ONE DOES NOT --------
#
# PAD_PIVOT=1 (item 13, save states) gives the guest its own root with
# pivot_root instead of chroot, because criu cannot dump a chroot'd task. The
# host tree is then dropped with one lazy umount - and the program that does
# that umount runs AFTER the pivot, with the host tree already gone, so it has
# to be a NATIVE STATIC binary sitting inside the rootfs. The rootfs's own
# busybox is ARM and would need the qemu we are about to exec into, so it
# cannot do it. `busybox-static` puts a native one at /bin/busybox; noble's
# busybox-initramfs is DYNAMIC and is not a substitute.
#
# ONE DEFINITION, because three places ask the same question: run_game.sh does
# the pivot, watch.sh decides whether to ask for one, and setupcheck.sh
# predicts the answer for the Emulate tab before Start is pressed. Two copies
# of this is exactly how the tab clears a machine that the run then refuses -
# the rule this rig keeps writing down (alive.sh and killgame.sh disagreeing
# about what a running rig is has already cost a session).
pad_static_busybox() {
    head -c4 /bin/busybox 2>/dev/null | grep -q ELF || return 1
    ! ldd /bin/busybox 2>&1 | grep -q '=>'
}

# ---- ...AND THE PROGRAM THAT ACTUALLY DOES THE FREEZING --------------------
#
# criu dumps the guest and restores it (savestate.sh / restorestate.sh). A
# pivot boot with no criu behind it is a boot shape nobody can use.
#
# IT IS NOT AN APT INSTALL, and that is the whole reason this function exists.
# Ubuntu 24.04 publishes NO criu at all - `apt-cache policy criu` prints an
# empty version table, not a package with no candidate - so every script here
# defaulted to /var/tmp/criubuild/criu/criu/criu, which is one developer's
# hand-built v4.1 on one machine. Eight scripts carried that literal, so save
# states could not work for any other user even with busybox-static: the boot
# was checkpointable, the playfield offered Save and Load, and the press
# answered "no criu at /var/tmp/criubuild/..." - a path that user had never
# heard of. getcriu.sh is how a machine gets one; this is how every script
# finds whichever one is there.
#
# ORDER, AND EACH ENTRY IS A DIFFERENT MACHINE: /usr/local/bin is where
# getcriu.sh installs the build, PATH is a distro that packages criu (Debian
# does), and the /var/tmp path is the developer build that predates all of
# this and must keep working. $CRIU still wins everywhere - callers ask for
# ${CRIU:-$(pad_criu)}, so an explicit one is never second-guessed.
pad_criu() {
    local c
    for c in /usr/local/bin/criu "$(command -v criu 2>/dev/null)" \
             /var/tmp/criubuild/criu/criu/criu; do
        [ -n "$c" ] && [ -x "$c" ] && { printf '%s\n' "$c"; return 0; }
    done
    return 1
}

# THE OTHER HALF OF A PIVOT, AND THE HALF NOBODY CHECKED: the program that
# performs it. Reported 2026-08-11 by the same user as the busybox fault above,
# one release later and on the very next run - he installed the package the tab
# had just asked him for, the run got PAST pad_static_busybox, and died two
# lines further on:
#
#     [run] PAD_PIVOT: checkpointable boot (pivot_root, explicit qemu)
#     bash: line 98: pivot_root: command not found
#     [run] pivot_root failed
#     [watch] the game never started.
#
# So the repair the app offered is what took his emulator away: without
# busybox-static the request was withdrawn and the game ran, and WITH it the
# run reached a pivot this machine cannot spell. That is the PAD-53 fault a
# second time in a different program, and the lesson is the one that file
# already wrote down - what a pivot needs is a LIST, and a gate that tests one
# item of it clears machines the run then refuses.
#
# WHERE IT CAN COME FROM, cheapest first, because two different faults produce
# that one message and this answers both:
#
#   * `pivot_root` on PATH - util-linux, essential, /usr/sbin. What every
#     healthy machine answers with.
#   * its absolute paths. A root shell launched by `wsl.exe -u root -e` carries
#     whatever PATH WSL built for it rather than a login shell's, and /usr/sbin
#     is the only directory outside /usr/bin this rig needs from it - so a PATH
#     without it fails HERE and nowhere earlier, which is exactly the shape of
#     the report.
#   * busybox's own applet. Free to rely on: a pivot already requires the
#     static busybox above, and Debian and Ubuntu both build it with pivot_root
#     in. Measured on 2026-08-11 against a real namespace - it pivots and the
#     lazy umount of the old root works the same as util-linux's.
#
# `command -v` IS NOT AN EXECUTABLE TEST WHEN THIS RUNS AS ROOT, and a pivot
# ALWAYS runs as root (watch.sh launches PAD_PIVOT sessions with `wsl.exe -u
# root`). Measured here on 2026-08-11 with a non-executable file in
# /usr/sbin/pivot_root's place: `command -v pivot_root` printed the path and
# returned 0, while `type` said not found and running it said Permission
# denied. So every candidate is confirmed with -f -x, which for root means "a
# regular file with an execute bit", and the busybox applet is confirmed by
# RUNNING busybox. A resolver that hands back something unrunnable is the
# `command not found` fault again, one directory deeper.
#
# Prints the ABSOLUTE path it resolved to, so no caller has to know which of
# the three it got and the pivot itself does not depend on a PATH - the inner
# namespace in run_game.sh has fewer reasons to trust one than anywhere else in
# this rig. The busybox form is two words on purpose: callers run it unquoted
# ($PIVOTROOT . oldroot), which splits it correctly.
pad_pivot_root_cmd() {
    local c p
    for c in pivot_root /usr/sbin/pivot_root /sbin/pivot_root; do
        p=$(command -v "$c" 2>/dev/null) || continue
        [ -n "$p" ] && [ -f "$p" ] && [ -x "$p" ] || continue
        printf '%s\n' "$p"
        return 0
    done
    for c in /bin/busybox "$(command -v busybox 2>/dev/null)"; do
        [ -n "$c" ] && [ -f "$c" ] && [ -x "$c" ] || continue
        "$c" --list 2>/dev/null | grep -qx pivot_root || continue
        printf '%s pivot_root\n' "$c"
        return 0
    done
    return 1
}

#: CAN THIS MACHINE BOOT A CHECKPOINTABLE GUEST AT ALL - the whole question in
#: one call, and the thing watch.sh and setupcheck.sh must ask. Both used to
#: ask pad_static_busybox, which was half of it; asking half a question is how
#: the tab cleared a machine and the run then refused it.
#:
#: THREE PROGRAMS, NOT TWO, and the third arrived from the other side of the
#: same week: busybox-static and pivot_root are what the BOOT SHAPE needs
#: (PAD-53, PAD-54), and criu is what the boot shape is FOR. A pivot with no
#: criu behind it is a boot nobody can use - the Save and Load buttons appear
#: and every press answers "no criu" - so asking two thirds of the question
#: leaves exactly the hole the first two fixes were written to close.
#:
#: WITHDRAWING IS THE SAFE DIRECTION and that is why all three belong in one
#: gate. A machine that fails this does not lose its emulator: watch.sh drops
#: PAD_PIVOT, the guest boots the ordinary chroot way, the game plays, and only
#: save states are absent. The fault both PAD-53 and PAD-54 record is the
#: opposite one - a gate that CLEARS a machine the run then refuses - so a gate
#: that asks for more can only ever fail safe.
#:
#: criu is deliberately NOT a required setup tool (setupcheck.sh keeps it at
#: `:0`): no Ubuntu publishes it, so making it required would tell a machine
#: that could not build it that it cannot emulate at all, which is false and is
#: PAD-53's fault a third time. Required for the PIVOT, optional for the RIG.
#: TWO PREDICATES, because the SETUP TAB and the RUN ask different questions.
#: pad_pivot_programs is the apt-fixable part - the two programs the boot shape
#: needs - and it is what the tab's busybox row tests, because that row's
#: repair is `apt install busybox-static` and offering it to a machine whose
#: only gap is criu would be advice that cannot help. criu has its own row with
#: its own repair (getcriu.sh). pad_can_pivot is the whole question and is what
#: the RUN asks, because a run does not care which third is missing.
pad_pivot_programs() {
    pad_static_busybox && pad_pivot_root_cmd >/dev/null 2>&1
}

pad_can_pivot() {
    pad_pivot_programs && pad_criu >/dev/null 2>&1
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

# ---- WHAT THE BOOT SELECTOR IS BUILT FROM, THE SAME WAY (item 90) ---------
#
# codeselect is the ARM menu a multi-image card boots into before the game:
# on the machine it is installed in the rootfs by mkmulticard.py, in the
# emulator buildselect.sh cross-compiles it into $ROOT and run_game.sh runs
# it (chroot, no shim) before the game on a PAD_SELECT run. Its sources live
# in codeselect/ with their own Makefile - the build is `make install`, not a
# gcc line here - so the list is RIG-relative paths and carries the Makefile
# and select.sh too: a change to how it is built or hooked is a change to
# what runs, and the digest has to see it. Same rule as the three lists
# above: one list, the copy and the staleness check both read it - and
# buildselect.sh copies ONLY this list into the staging directory, so a
# source the Makefile needs and this list lacks is a build that fails on a
# missing file (tests/test_spike2_codeselect_rig.py checks the two agree).
# images.conf.example is on it because `make install` installs it. art.c
# (PNG/GIF decode + blit) and audio.c / audio_fifo.c / audio_alsa.c (the WAV
# mixer and its two sinks) are item 90's media pass.
PAD_SELECT_SRCS="codeselect/codeselect.c codeselect/conf.c codeselect/conf.h codeselect/gfx.c codeselect/gfx.h codeselect/egl_stern.c codeselect/egl_stern.h codeselect/input.c codeselect/input.h codeselect/input_hw.c codeselect/input_padsw.c codeselect/log.c codeselect/log.h codeselect/art.c codeselect/art.h codeselect/audio.c codeselect/audio.h codeselect/audio_fifo.c codeselect/audio_alsa.c codeselect/Makefile codeselect/select.sh codeselect/images.conf.example codeselect/third_party/stb_truetype.h codeselect/third_party/stb_image.h"
export PAD_SELECT_SRCS

#: The installed selector, and what it was built from - stamped beside it,
#: in the directory the Makefile's `install` creates.
PAD_SELECT_BIN=$ROOT/usr/local/codeselect/codeselect
PAD_SELECT_STAMP=$ROOT/usr/local/codeselect/codeselect.srcs
export PAD_SELECT_BIN PAD_SELECT_STAMP
pad_select_hash() { pad_src_hash "${1:-$RIG}" $PAD_SELECT_SRCS; }

#: WHERE THE CHOICE LANDS, as the GUEST spells it: /dump is $ROOT/dump
#: self-bound, so the host reads the same file at "$ROOT$PAD_SELECT_CHOICE".
#: One line, '<index>\n', written by codeselect on a confirmed choice and
#: read by run_game.sh to pick the partition to bind. Defined ONCE, here,
#: because the selector is told it on its command line and run_game.sh reads
#: it back - two spellings of that path is how a choice goes unread.
PAD_SELECT_CHOICE=/dump/select.choice
export PAD_SELECT_CHOICE

# ---- IS THE MENU WANTED ON THIS RUN? (item 90, 2026-09-02) ----------------
#
# PAD_SELECT IS A THREE-WAY SWITCH, AND THIS IS THE ONLY PLACE THAT READS IT:
#
#   unset  ->  ASK THE CARD. parts.py --multiboot is the one definition of
#              "this card boots into a menu" (the rootfs holds the selector
#              and its images.conf names two or more images).
#   1      ->  show the menu, whatever the card looks like.
#   0      ->  do not, whatever the card looks like.
#
# WHY THE DEFAULT MOVED. David, 2026-09-02: "i shouldn't have to check off
# 'boot selector' in the emulate tab. if it has multi-boot, i expect to see
# the multi-boot screen." A tickbox that has to be found and ticked is a
# second place where the answer lives, and it was wrong by default on every
# multi-boot card.
#
# THE ANSWER IS A VERDICT IN THE EXIT STATUS (0 = show the menu, 1 = do not)
# AND TWO VARIABLES BESIDE IT:
#
#   PAD_SELECT_WHY   the sentence to print - written HERE, beside the branch
#                    that chose it, because "this card carries a menu" and
#                    "the menu was asked for" are different facts and a caller
#                    that re-worded them from the exit status alone would
#                    eventually claim the first while doing the second.
#   PAD_SELECT_AUTO  1 when THE CARD decided, 0 when a human did.
#
# WHY THE PROVENANCE TRAVELS, AND WHY IT IS NOT A SENTENCE ON STDOUT
# (2026-09-02, the review of the tri-state). Every gate downstream - the
# selector build, the extra mounts, the menu preparation - was written when
# PAD_SELECT meant "somebody asked for a menu", and refusing the run when one
# could not be given was the right answer to that. Now the CARD asks, and the
# SAME refusals would let a card make the emulator refuse to start: a rig with
# no cross compiler, a partition that will not mount, and a card that booted
# yesterday is dead today over a menu nobody wanted. So each gate needs to
# know WHO asked, and it cannot work that out from a resolved 1 - hence
# PAD_SELECT_AUTO, set only in the branches below where the card answered, and
# exported by watch.sh so run_game.sh inherits it.
#
# These are plain variables and not stdout because `SEL=$(pad_select_wanted)`
# runs the function in a SUBSHELL, where anything it learns about provenance
# dies with the subshell. This function is sourced; it can simply say so.
#
# NEVER AUTO-ON WITHOUT A CARD. An extracted title under games/ has nothing
# to choose between, and probing an empty path would be a python3 start for
# nothing; an explicit PAD_SELECT=1 is still honoured there, exactly as it
# was. A card that cannot be read (no debugfs, not a card, exit 2) is a "no"
# with its reason said out loud - the safe direction, since the alternative
# is a menu with nothing on it in front of a game that was asked for.
pad_select_wanted() {
    local card line rc
    card=${1:-}
    PAD_SELECT_AUTO=0
    case "${PAD_SELECT:-}" in
        0|no|off|false|NO|OFF|FALSE)
            PAD_SELECT_WHY="PAD_SELECT=$PAD_SELECT - the menu is switched off for this run"
            return 1 ;;
        "") ;;
        *)
            PAD_SELECT_WHY="PAD_SELECT=$PAD_SELECT - the menu was asked for"
            return 0 ;;
    esac
    if [ -z "$card" ]; then
        PAD_SELECT_WHY="no card image on this run - nothing to choose between"
        return 1
    fi
    line=$(python3 "$RIG/parts.py" --multiboot "$card" 2>/dev/null)
    rc=$?
    case "$line" in
        "multiboot: "*) line=${line#multiboot: } ;;
        *) line="parts.py could not be asked about $card" ;;
    esac
    line=${line#yes - }; line=${line#no - }; line=${line#unknown - }
    # From here on the CARD is the one answering, whichever way it answers.
    PAD_SELECT_AUTO=1
    if [ "$rc" = 0 ]; then
        PAD_SELECT_WHY="this card carries a menu ($line) - showing it; PAD_SELECT=0 skips it"
        return 0
    fi
    PAD_SELECT_WHY="no menu on this card ($line); PAD_SELECT=1 forces one"
    return 1
}

if pad_is_wsl; then IS_WSL=1; else IS_WSL=0; fi

# ---- IS THERE A DISPLAY TO PUT THE GAME WINDOW ON? -----------------------
#
# `[ -n "$DISPLAY" ]` WAS THE WHOLE TEST, AND IT IS NOT THE QUESTION. WSLg sets
# DISPLAY when the distro starts and never takes it back, so the variable says
# only that this WSL was BUILT with a GUI - not that a client can reach the
# server today. A machine where it cannot gets the one failure this rig is
# worst at: the renderer stays headless, and everything else works. The guest
# boots, the LEDs decode, the sound plays and the virtual playfield says
# "emulator up" - with NO PICTURE ANYWHERE and no line anyone would read,
# because padglhost's own explanation goes to ~/padglhost.log and stops there.
# That is a user's report on 2026-08-11, and it is the ffmpeg fault (PAD-49)
# wearing different clothes: a run that succeeds all the way to nothing.
#
# WHERE A LOCAL DISPLAY ACTUALLY IS. `:N` and `unix:N` mean the UNIX socket
# /tmp/.X11-unix/XN, which is what libX11 opens - so its absence is not a hint,
# it is the answer. A DISPLAY with a HOSTNAME in it is TCP to somewhere this
# rig knows nothing about (VcXsrv, X410, a Linux box across the room), and the
# only honest verdict there is silence.
#
# AND THE ONE WAY IT GOES MISSING ON WSL, which is why `masked` is a state of
# its own rather than a kind of "no". WSLg's socket lives in its own tmpfs and
# WSL bind-mounts it into the distro; measured here 2026-08-11:
#
#     $ findmnt /tmp/.X11-unix
#     none[/.X11-unix]  /tmp/.X11-unix  tmpfs  ro,relatime
#     $ stat -c%n /mnt/wslg/.X11-unix/X0 /tmp/.X11-unix/X0
#     /mnt/wslg/.X11-unix/X0
#     /tmp/.X11-unix/X0            <- the SAME socket, in two places
#
# Anything that mounts a fresh /tmp over that bind hides it - systemd's
# tmp.mount is the common one, and this rig already knows systemd-in-WSL is
# ordinary (setupcheck.sh reports it as `wslconf`). Reproduced exactly, with
# the real renderer, in a private mount namespace:
#
#     # unshare -m bash -c 'mount -t tmpfs tmpfs /tmp; padglhost /tmp/ring'
#     [padglhost] PAD_GL_WINDOW=1 but XOpenDisplay failed (DISPLAY=:0);
#                 staying headless
#     # ...and after `mount --bind /mnt/wslg/.X11-unix /tmp/.X11-unix`
#     [padglhost] window opened 1445x827 on DISPLAY=:0
#
# So the socket is still THERE, one directory away, and putting it back is a
# bind mount - which the app's own launch can do, because it runs as root.
#: Overridable so the states above can be tested without a WSL, an X server or
#: a mount: the tests point both at directories under tmp_path.
PAD_X11_DIR=${PAD_X11_DIR:-/tmp/.X11-unix}
PAD_WSLG_X11_DIR=${PAD_WSLG_X11_DIR:-/mnt/wslg/.X11-unix}
export PAD_X11_DIR PAD_WSLG_X11_DIR

# The socket file $DISPLAY names, for a LOCAL display only. Non-zero for a
# hostname (TCP) or an unparseable value, so every caller's "I have nothing to
# say about this machine" branch is the same one.
pad_x_socket() {
    local d=${DISPLAY:-} host num
    [ -n "$d" ] || return 1
    host=${d%%:*}
    num=${d#*:}; num=${num%%.*}
    case $host in ""|unix) ;; *) return 1 ;; esac
    case $num in ''|*[!0-9]*) return 1 ;; esac
    printf '%s/X%s\n' "$PAD_X11_DIR" "$num"
}

# What this machine's display IS, in one word:
#
#   none      DISPLAY is unset. No GUI at all.
#   remote    DISPLAY names a host. Not ours to judge - say nothing.
#   ok        the local socket is there.
#   masked    it is not there, and WSLg's copy of it IS - repairable.
#   nosocket  it is not there and there is nothing to put back.
#
# `-e` rather than `-S` deliberately: what matters is whether libX11 finds
# something at that path, a non-socket sitting there is a broken machine by any
# reading, and a test can create a file where it cannot create a socket.
pad_display_state() {
    local sock
    [ -n "${DISPLAY:-}" ] || { echo none; return 0; }
    sock=$(pad_x_socket) || { echo remote; return 0; }
    [ -e "$sock" ] && { echo ok; return 0; }
    [ -e "$PAD_WSLG_X11_DIR/${sock##*/}" ] && { echo masked; return 0; }
    echo nosocket
}

# The command that puts a masked socket back, printed for a user who is not
# root and run by us when we are. ONE STRING, so what is advised and what is
# done cannot drift.
pad_display_fix_cmd() {
    printf 'mount --bind %s %s\n' "$PAD_WSLG_X11_DIR" "$PAD_X11_DIR"
}

# WHAT THE RENDERER DID WITH ITS WINDOW, out of the renderer's own log - the
# only place that knows, and a place nothing showed the user until this ticket.
# padglhost prints exactly one of:
#
#     [padglhost] window opened 1445x827 on DISPLAY=:0
#     [padglhost] PAD_GL_WINDOW=1 but XOpenDisplay failed (...); staying headless
#     [padglhost] eglCreateWindowSurface failed 0x...; falling back to headless
#
# A HEADLESS LINE WINS OVER AN "OPENED" ONE, and that ordering is the whole
# reason this is a function rather than a grep. The window is created and
# mapped BEFORE the EGL surface is asked for, so the third case above prints
# BOTH lines, "opened" first - and that run has a window sitting on the desktop
# that can never show a picture. Reading the first match would call it a
# healthy run.
pad_window_line() {
    local log=${1:-} head
    [ -n "$log" ] && [ -r "$log" ] || return 1
    head=$(grep -a -m1 headless "$log" 2>/dev/null)
    if [ -n "$head" ]; then printf '%s\n' "$head"; return 0; fi
    head=$(grep -a -m1 'window opened' "$log" 2>/dev/null)
    [ -n "$head" ] || return 1
    printf '%s\n' "$head"
}

# Do it. Root only, and only when there is genuinely something to bind: this
# mount ADDS the socket WSL itself put there, so it cannot take anything away,
# but a bind over a directory that already works would still be a change made
# for no reason. Verifies by asking pad_display_state again rather than by
# trusting mount's exit code.
pad_display_repair() {
    local sock
    [ "$(pad_display_state)" = masked ] || return 1
    [ "$(id -u)" = 0 ] || return 1
    sock=$(pad_x_socket) || return 1
    mkdir -p "$PAD_X11_DIR" 2>/dev/null
    mount --bind "$PAD_WSLG_X11_DIR" "$PAD_X11_DIR" 2>/dev/null || return 1
    [ "$(pad_display_state)" = ok ]
}

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

# WHERE `py` KEEPS ITS PYTHONS - the Windows launcher itself, or "".
#
# THE LAUNCHER IS THE AUTHORITY, AND PAD-94 IS WHY. A user was told "no Windows
# Python with sounddevice, run `py -m pip install sounddevice`", ran exactly
# that, pip installed it - and this rig went on saying no. His Python was an
# all-users install in `C:\Program Files\Python313`, which is what the
# python.org installer writes when "Install for all users" is ticked, and the
# glob list below had never looked there. The advice and the check were about
# two different sets of interpreters, so following the advice could not change
# the answer, and there was nothing in the message to say so.
#
# `py -0p` lists the interpreters `py` ITSELF would run, which makes the set we
# check and the set the advice changes the same set by construction, whatever
# layout a machine's installer chose.
#
# PATH FIRST: with interop on, Windows' PATH is appended to this shell's and
# carries the all-users launcher (`C:\Windows\py.exe`). The fixed paths are for
# a distro with `appendWindowsPath=false`, where nothing Windows is on PATH at
# all.
pad_win_py_launcher() {
    local c
    # PAD_WINPY_LAUNCHER is the same kind of override PAD_WINPYTHON already is,
    # one level up: it names the launcher when it is somewhere neither PATH nor
    # the two fixed paths reach - and it is how this search is tested at all,
    # since there is no Windows on the other side of a test runner.
    if [ -n "${PAD_WINPY_LAUNCHER:-}" ] && [ -x "$PAD_WINPY_LAUNCHER" ]; then
        echo "$PAD_WINPY_LAUNCHER"
        return
    fi
    c=$(command -v py.exe 2>/dev/null || true)
    if [ -n "$c" ]; then echo "$c"; return; fi
    for c in /mnt/c/Windows/py.exe \
             /mnt/c/Users/*/AppData/Local/Programs/Python/Launcher/py.exe; do
        if [ -x "$c" ]; then echo "$c"; return; fi
    done
    echo ""
}

# Every Windows Python worth trying, best first, ONE PER LINE.
#
# THE `*` LINE LEADS because that is the interpreter `py -m pip install` puts
# packages into - so the first candidate tried is the one the advice acts on.
# `py -0p` prints `-V:3.13 *        C:\...\python.exe`; the path starts at the
# drive letter and may contain spaces, so it is cut from there to the end of
# the line rather than picked out as a field. A line that is not a path at all
# (an old launcher prints a header first) survives that cut and then fails the
# -x test in pad_win_python_usable, which is where it belongs.
#
# ONE PER LINE AND READ WITH `read -r`, never a `for` over a command
# substitution: `C:\Program Files\...` is a path with a space in it, and word
# splitting would tear in half the very install this exists to find.
# Run a command under a 10 s bound WHERE A BOUND EXISTS. GNU timeout(1) is on
# every WSL/Linux host — the only place the bound matters, because the hang it
# guards (a Windows interop exec whose owning wsl.exe session already exited,
# the 2026-08-31 silent-audio wedge) can only happen there. macOS's BSD
# userland has no timeout(1), and prefixing it unconditionally broke the whole
# Windows-python search on the mac CI runner (v0.175.0 was yanked for exactly
# this) — so fall back to running unbounded where no interop boundary exists.
pad_bounded() {
    if command -v timeout >/dev/null 2>&1; then
        timeout 10 "$@"
    else
        "$@"
    fi
}

pad_win_pythons() {
    local py raw w c
    # PAD'S OWN INTERPRETER LEADS, and on Windows the app always passes it
    # (emulate_tab.rig_cmd puts it here). EVERY PACKAGED WINDOWS INSTALL SHIPS
    # ONE: an embeddable Python with pip at `{app}\python\python.exe`, which
    # WSL runs straight off /mnt/c like any other .exe. PAD-95: the search
    # below hunts only for a Python the USER installed, so a PC with none was
    # told to go and install one - while the interpreter this needs was
    # sitting in the same folder as the program printing the message.
    [ -n "${PAD_WINPYTHON:-}" ] && printf '%s\n' "$PAD_WINPYTHON"
    py=$(pad_win_py_launcher)
    if [ -n "$py" ] && command -v wslpath >/dev/null 2>&1; then
        # STDIN CLOSED, and it matters: a Windows child inherits this
        # shell's stdin across interop and can drain it - which, when the
        # caller is itself a script being fed on stdin, eats the rest of
        # that script. A probe must not consume the input of whatever
        # asked it.
        # BOUNDED: an interop exec whose owning wsl.exe session has exited
        # hangs forever (no Windows process ever starts), and a probe that can
        # hang is a chain that can wedge before its first log line — the
        # 2026-08-31 no-sound report. 10 s is geological for `py -0p`.
        raw=$(pad_bounded "$py" -0p 2>/dev/null </dev/null | tr -d '\r')
        { printf '%s\n' "$raw" | grep '\*'
          printf '%s\n' "$raw" | grep -v '\*'; } \
            | grep -o '[A-Za-z]:\\.*$' \
            | while IFS= read -r w; do wslpath -u "$w" 2>/dev/null; done
    fi
    # THE INTERPRETER WITHOUT THE LAUNCHER IN FRONT OF IT. `py` is an OPTIONAL
    # tick in the Windows installer, so a machine can carry a perfectly good
    # python.exe and answer nothing at all above - which is the second half of
    # PAD-95: the reporter's terminal said `py` wurde nicht als Name eines
    # Cmdlet erkannt, i.e. the program our advice named was not on his PC.
    # PATH carries the Windows one into this shell whenever interop is on, and
    # a Microsoft Store alias arriving this way is a zero-byte stub that
    # pad_win_python_usable already rejects.
    for w in python.exe python3.exe; do
        c=$(command -v "$w" 2>/dev/null || true)
        [ -n "$c" ] && printf '%s\n' "$c"
    done
    # THE OLD FIXED LIST STAYS, as the fallback: the launcher can be left out
    # at install time, and a distro that cannot see it can still see the
    # directories. Widened by the two `Program Files` ones - the layout that
    # started all this - and the quoting is what keeps that space from
    # splitting the pattern before the glob ever runs.
    printf '%s\n' /mnt/c/Python3*/python.exe \
        "/mnt/c/Program Files"/Python3*/python.exe \
        "/mnt/c/Program Files (x86)"/Python3*/python.exe \
        /mnt/c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe
}

# Is this candidate something this shell can actually RUN?
#
# -s AS WELL AS -x: a Microsoft Store install leaves a ZERO-BYTE app-execution
# alias in `WindowsApps`, which is executable to every test /mnt/c can make and
# is not a program from here. An unmatched glob arrives as its own pattern and
# fails the same way.
pad_win_python_usable() {
    [ -n "${1:-}" ] && [ -x "$1" ] && [ -s "$1" ]
}

# A WINDOWS Python that can actually open a sound device, or "".
#
# BOTH HALVES MATTER: an interpreter without sounddevice is no use, and finding
# that out at startup is what turns a silent downgrade into an actionable
# message. playaudio.sh routes WSL audio through it because the WSLg hop is
# measurably damaged (+16 dB of error against -14.8 dB for this path; the
# measurement is in playaudio.sh's own header).
#
# IT LIVES HERE, NOT IN playaudio.sh, BECAUSE TWO PLACES NOW ASK. setupcheck.sh
# reports it so the Emulate tab can say the sound will be poor BEFORE a run
# rather than in one line of a log during one, and this rig's standing rule is
# that two scripts defining one fact eventually disagree - alive.sh and
# killgame.sh did, about what a running rig even is.
#
# AND IT NEEDS INTEROP, which is worth knowing when reading its answer: every
# candidate is a Windows .exe, so a distro that cannot start Windows programs
# answers "" here however many Pythons are installed. setupcheck.sh reports
# interop separately for exactly that reason - otherwise the advice that
# follows ("install sounddevice") is addressed to the wrong fault.
pad_win_python() {
    pad_win_pythons | while IFS= read -r c; do
        # bounded: see pad_win_pythons — a dead-interop exec hangs forever,
        # and this probe is the exact line the 2026-08-31 silent-audio wedge
        # stood on for 151 s. A healthy import answers in well under 10 s.
        if pad_win_python_usable "$c" \
           && pad_bounded "$c" -c "import sounddevice" >/dev/null 2>&1 </dev/null
        then
            echo "$c"
            break
        fi
    done
}

# The first Windows Python AT ALL, sounddevice or not, or "".
#
# THE MESSAGE NEEDS THE DIFFERENCE, which is the other half of PAD-94. "No
# Windows Python with sounddevice" is two faults in one sentence - a PC with no
# Python on it, and a PC with a Python that is missing one package - and they
# call for different actions. setupcheck.sh reports this as `winpy`, so the
# Emulate tab can name the interpreter it found instead of leaving a user to
# work out which of the two he is looking at.
pad_win_python_any() {
    pad_win_pythons | while IFS= read -r c; do
        if pad_win_python_usable "$c"; then
            echo "$c"
            break
        fi
    done
}

# ---- AND THE ONE THAT HAS TO DRAW THE PLAYFIELD WINDOW --------------------
#
# A DIFFERENT QUESTION FROM THE SOUND ONE, ASKED THE SAME WAY. The window is a
# Windows process (this WSL has no Tk at all), it is drawn with tkinter AND
# Pillow, and until PAD-99 nothing chose it: watch.sh ran whatever `pythonw.exe`
# PATH happened to hand it.
#
# WHAT THAT COST. dragonrr's PC had a python.org 3.13 on PATH, so `pythonw.exe`
# was HIS interpreter - tkinter yes, Pillow no - and playfield.py died on its
# first artwork import. He got the game window, the sound and the switches, and
# no playfield, with the fix sitting on the same disk: PAD's own bundled Python
# has both (it is what the app draws ITSELF with), it is already handed to this
# rig as PAD_WINPYTHON, and running playfield.py with it by hand opened the
# window first try. The rig simply never asked for it.
#
# So this asks the same list the sound path asks (pad_win_pythons - ours
# leads), and asks each candidate the question that actually matters: can you
# import what the window is drawn with. PATH is still in that list; it is no
# longer the whole of it.

# The GUI-subsystem twin of a Windows python.exe, when one sits beside it.
#
# WHY THE TWIN AT ALL: pythonw.exe is what keeps a black console window from
# sitting beside the playfield for the whole run, and it is also what stops
# `cmd /c start` hanging on the interop pipe (watch.sh's launch block has the
# post-mortem). But pythonw.exe cannot be PROBED - a GUI-subsystem binary
# writes its traceback nowhere - so every question above is asked of the
# console spelling and only the ANSWER is translated here.
#
# Unchanged when there is no twin (an embeddable layout always has one; a
# python3.exe alias may not), so the caller still gets something to run.
pad_win_pythonw() {
    local d
    case "${1:-}" in
        */python.exe|*/python3.exe) ;;
        *) printf '%s\n' "${1:-}"; return ;;
    esac
    d=${1%/*}
    if pad_win_python_usable "$d/pythonw.exe"; then
        printf '%s\n' "$d/pythonw.exe"
    else
        printf '%s\n' "$1"
    fi
}

# A Windows Python that can actually DRAW the playfield window, or "".
#
# BOTH IMPORTS, because either one missing is the same blank desktop: tkinter
# is the window and Pillow is the artwork (playfield.py's Field.__init__ imports
# it unguarded, and the LCD panel decodes its clips with it). A python.org
# install has tkinter and no Pillow, which is exactly the machine PAD-99 came
# from, so probing for tkinter alone would have found the broken one and passed.
pad_win_pf_python() {
    pad_win_pythons | while IFS= read -r c; do
        # bounded and with stdin closed, for the reasons pad_win_python gives:
        # a dead-interop exec hangs forever, and a Windows child will drain the
        # stdin of whatever asked it.
        if pad_win_python_usable "$c" \
           && pad_bounded "$c" -c "import tkinter, PIL.ImageTk" \
                >/dev/null 2>&1 </dev/null
        then
            pad_win_pythonw "$c"
            break
        fi
    done
}

# The first Windows Python AT ALL, in the spelling the playfield wants.
#
# THE FALLBACK, AND IT IS NOT DECORATION. If no candidate can import both, the
# window still gets launched with the best one there is - because a launch that
# fails leaves a traceback in the playfield log, which watch.sh prints, and
# that names the missing package to the one person who can act on it. Refusing
# to launch would replace a diagnosable failure with a silent one, which is the
# state PAD-99 was reported from.
#
# "CAN BE RUN", NOT "IS A FILE", and that distinction is the whole difference
# between this and pad_win_python_any. -x and -s say the .exe is THERE; on a
# distro with interop switched off, every Windows binary under /mnt/c is there
# and none of them can be executed. watch.sh has a branch for that machine - it
# asks PAD to open the window, because the app is already on the Windows side -
# and handing it a path it cannot exec would swap that working answer for a
# launch that fails into a log. So ask each candidate to run the emptiest
# program there is, and believe the ones that answer.
pad_win_pf_python_any() {
    pad_win_pythons | while IFS= read -r c; do
        if pad_win_python_usable "$c" \
           && pad_bounded "$c" -c "" >/dev/null 2>&1 </dev/null
        then
            pad_win_pythonw "$c"
            break
        fi
    done
}

# WHAT TO DO ABOUT A MISSING sounddevice, in the words that fit THIS machine.
# One or more lines on stdout; the caller prefixes them.
#
# NEVER `py`, AND THAT IS PAD-95 ITSELF. The launcher is an optional tick in
# the Windows installer and the reporter did not have it, so the single line
# this rig and the Emulate tab both printed answered
#
#     "py" wurde nicht als Name eines Cmdlet ... erkannt
#
# and carried nothing to say what to do instead. Say the thing that is true
# HERE: which interpreter, or that PAD's own installer is the whole answer.
#
# A FULL PATH IS NOT A COMMAND IN POWERSHELL, which is the same trap one layer
# down from PAD-94's backticks: a quoted path as the first word of a
# PowerShell line is a STRING - printed, not run - and the paths that need the
# quotes are exactly the `C:\Program Files` ones. `cd` there and run
# `.\python.exe`: two lines that mean the same thing in both of Windows'
# shells.
pad_sounddevice_hint() {
    local py w d
    py=$(pad_win_python_any)
    if [ -n "$py" ] && [ -n "${PAD_WINPYTHON:-}" ] \
       && [ "$py" = "$PAD_WINPYTHON" ]
    then
        echo "PAD ships its own Python and that is the one to put it in."
        echo "In PAD: gear menu -> Install / repair prerequisites...,"
        echo "and tick Stern Pinball. Nothing to type."
        return
    fi
    if [ -n "$py" ]; then
        w=$(pad_win "$py" 2>/dev/null) || w=""
        if [ -n "$w" ]; then
            d=${w%\\*}
            echo "in a Windows terminal, once:"
            echo "cd \"$d\""
            echo ".\\${w##*\\} -m pip install --user sounddevice"
            return
        fi
    fi
    echo "this PC has no Windows Python. Install one from python.org"
    echo "(tick \"Add python.exe to PATH\"), then in a Windows terminal:"
    echo "python -m pip install --user sounddevice"
}
