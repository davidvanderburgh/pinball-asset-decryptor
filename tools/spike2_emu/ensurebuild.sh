#!/bin/bash
# ensurebuild.sh - SOURCED, never run. "Is what is about to run actually built,
# and built from THESE sources?"
#
#   . "$(dirname "$0")/ensurebuild.sh"
#   pad_ensure_rootfs || exit 1
#   pad_ensure_guest_exec || exit 1
#   pad_ensure_shim
#   pad_ensure_bridge || exit 1
#
# WHY THIS IS ITS OWN FILE. The rig compiles three things - the ARM hardware
# shim (build.sh) and the GL bridge's two halves (buildbridge.sh) - and each of
# them was built ONCE, by hand, when the rig was first set up, and never looked
# at again. That was harmless while the rig and its sources were one working
# copy on one developer's disk. It stopped being harmless the moment the
# emulator SHIPPED WITH THE APP, and it failed in both possible directions
# within two releases of each other:
#
#   * the shim was PRESENT BUT OLD. An update delivered new hwshim.c to Program
#     Files while the .so that actually ran stayed whatever was built months
#     ago, so a fix could install, be believed, and not run (fixed v0.113.0).
#   * the renderer was ABSENT ENTIRELY. `buildbridge.sh` is step three of a
#     three-step setup that rootfs.sh only PRINTS as advice, so a user who
#     stopped after step two got
#
#         env: './padglhost': No such file or directory
#
#     ten seconds after Start said "Starting...", with nothing on the tab that
#     could tell them what to do about it (fixed here).
#
# Both are the same question asked about different binaries, so it is answered
# in ONE place - this rig's own rule, the one alive.sh and killgame.sh had to
# be taught after they disagreed about what a running rig is. watch.sh and
# runbridge.sh both source this, so a fix reaches the measurement path too.
#
# THE STANCE, and it is deliberately asymmetric:
#
#   MISSING and needed to run at all -> build it, and FAIL LOUDLY if that does
#     not work. There is nothing to fall back to.
#   STALE -> rebuild, but never fatally. What is already there still runs the
#     game, and refusing to start because a cross compiler is missing would
#     take the emulator away from someone whose only problem is that they
#     cannot rebuild it.
#   NEVER UNDERNEATH A LIVE RUN. The linker truncates and rewrites its output
#     in place; a running guest has hwshim.so MAPPED (SIGBUS) and a running
#     padglhost is its own text file (ETXTBSY). Two copies of the rig on one
#     machine is exactly how that arises - start from the repo, then start
#     again from the installed app.
#
# Sourced AFTER padpath.sh, which owns the source lists, the stamps and the
# digests these decisions are made from.

#: Is a run live?  `alive.sh --total` is the rig's own definition of that and
#: the only one - killgame.sh asks it the same way rather than keeping a second
#: list.  An unreadable /proc makes alive.sh refuse rather than reassure, and an
#: unparseable answer is read as "something is running", which is the safe
#: direction for every caller here.
_pad_run_live() {
    [ "$(bash "$RIG/alive.sh" --total 2>/dev/null)" != 0 ]
}

#: Is <binary> older than the sources it was built from?  0 = stale.
#:
#: THE DIGEST WINS WHENEVER THERE IS ONE, for the reason pad_src_hash records:
#: it is the only test that answers the same way in both directions, and the
#: rig now exists in more than one copy.  With no stamp - a rig built before
#: the stamps existed - timestamps are what is left, and they are right in the
#: common case of an edit followed by a run.  The first rebuild lays a stamp
#: down and that branch is never taken again on that machine.
_pad_stale() {           # <binary> <stamp> <want-digest> <src>...
    local bin=$1 stamp=$2 want=$3 src
    shift 3
    [ -e "$bin" ] || return 0
    if [ -f "$stamp" ]; then
        [ "$(cat "$stamp" 2>/dev/null)" = "$want" ] && return 1
        return 0
    fi
    for src in "$@"; do
        [ -f "$RIG/$src" ] || continue
        [ "$RIG/$src" -nt "$bin" ] && return 0
    done
    return 1
}

#: Run one of the rig's build scripts and republish what it said, indented.
#: Returns what the build returned; says nothing about what to do with that.
#:
#: A FAILED BUILD IS REPORTED BY ITS ERRORS, NOT BY ITS LAST EIGHT LINES.
#:
#: `tail -8` was the whole report, and it reached a user on 2026-08-07 as a bug
#: report that nobody - them, or us - could act on:
#:
#:     [build] the hardware shim is not built yet; building it
#:     [build]   476 |   VLOG("[vid] ch%d pre-arming hw ch%d: %s\n",
#:     [build]       |                                        ^~
#:     ... five more lines of the same -Wformat-truncation note ...
#:     [build]   build FAILED, and the game has no hardware without it.
#:
#: Every line of that is a WARNING about code that compiled perfectly, and those
#: eight lines are byte for byte the tail of a SUCCESSFUL build here. The three
#: `implicit declaration of function` errors that actually stopped it were never
#: printed at all.
#:
#: THAT IS STRUCTURAL, not bad luck. gcc is handed every source at once and
#: compiles ALL of them before it gives up, so the errors sit wherever the
#: broken file happened to be on the command line while the tail belongs to
#: whichever file came last - here gstvid.c, which has warned about the same
#: harmless snprintf for months. The one arrangement `tail` can never show is
#: the common one: an error early, noise after it.
#:
#: So the ERROR LINES are what is republished, first ones first - the first
#: error is the cause and the rest are usually its cascade - and the tail is
#: kept only as the fallback for a failure that matches none of these words.
#: The FULL output goes to a file that is NAMED, because the next fault will be
#: one this pattern does not know, and a user who can send that file is a user
#: whose problem can be read instead of guessed at.
_pad_build() {           # <script> [args...]
    local script=$1 out rc errs log
    shift
    out=$(bash "$RIG/$script" "$@" 2>&1); rc=$?
    if [ $rc = 0 ]; then
        printf '%s\n' "$out" | sed 's/^/[build]   /'
        return 0
    fi
    log=${TMPDIR:-/tmp}/pad-${script%.sh}.log
    printf '%s\n' "$out" > "$log" 2>/dev/null
    # gcc and ld say "error:"; ld's own failures ("cannot find -l:libc.so.6",
    # "undefined reference to") do not, and neither does the shell when the
    # build dies on a missing file, a full disk or the OOM killer.
    errs=$(printf '%s\n' "$out" | grep -E \
        'error:|undefined reference|cannot find|No such file|command not found|Permission denied|No space left|Killed|Segmentation fault' \
        | head -8)
    [ -n "$errs" ] || errs=$(printf '%s\n' "$out" | tail -8)
    printf '%s\n' "$errs" | sed 's/^/[build]   /' >&2
    [ -s "$log" ] && echo "[build]   full build output: $log" >&2
    return $rc
}

# ---------------------------------------------------------------------------
# The ARM hardware shim
# ---------------------------------------------------------------------------
# Non-zero only when the shim is missing and cannot be built, for the same
# reason as the renderer below: `LD_PRELOAD=/lib/hwshim.so` against a file that
# is not there is a WARNING, not an error - ld.so says "cannot be preloaded:
# ignored" and runs the game with no hardware at all, which then fails as
# something else entirely.
pad_ensure_shim() {
    local so=$ROOT/lib/hwshim.so
    if [ ! -f "$so" ]; then
        # No rootfs at all is not this function's business - the run says so
        # itself, in words about the rootfs, which is the accurate news. A
        # rootfs that IS there and simply never had `build.sh` run against it
        # is the renderer's fault in a different binary, and gets the same
        # answer: build it rather than explain it.
        [ -d "$ROOT/lib" ] || return 0
        if ! command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; then
            echo "[build] the hardware shim is not built, and there is no" >&2
            echo "[build] arm-linux-gnueabihf-gcc here to build it (on" >&2
            echo "[build] Debian/Ubuntu: apt install gcc-arm-linux-gnueabihf)." >&2
            echo "[build] Expected at: $so" >&2
            return 1
        fi
        echo "[build] the hardware shim is not built yet; building it"
        _pad_build build.sh && return 0
        echo "[build]   build FAILED, and the game has no hardware without it." >&2
        return 1
    fi
    _pad_stale "$so" "$PAD_SHIM_STAMP" "$(pad_shim_hash "$RIG")" $PAD_SHIM_SRCS \
        || return 0
    if _pad_run_live; then
        echo "[build] the hardware shim is older than its source, but a run is" >&2
        echo "[build] still up and the shim cannot be rewritten underneath it." >&2
        echo "[build] Stop it (killgame.sh) and start again to pick up the fix." >&2
        return 0
    fi
    if ! command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; then
        echo "[build] the hardware shim is older than its source, but there is no" >&2
        echo "[build] arm-linux-gnueabihf-gcc here to rebuild it. Running as built." >&2
        return 0
    fi
    echo "[build] the hardware shim is older than its source; rebuilding"
    _pad_build build.sh \
        || echo "[build]   rebuild FAILED; running the shim already built" >&2
    return 0
}

#: CAN THIS MACHINE BUILD A NATIVE BINARY? Asked by compiling one.
#:
#: `command -v gcc` IS THE WRONG QUESTION, and it is the wrong question in both
#: directions at once. A machine can have gcc and be unable to use it - the gcc
#: package only RECOMMENDS libc6-dev, so a slim WSL image, or one where gcc
#: arrived as somebody else's dependency, has the compiler on PATH and not one
#: header to give it. `#include <stdio.h>` is the first line of padglhost.c.
#: install_prerequisites.ps1 learned this for the JJP dongle hooks and probes
#: them by compiling; the renderer is the second thing here that is built
#: natively, and it was still asking the PATH.
#:
#: AN UNWRITABLE TEMP DIRECTORY IS NOT A MISSING COMPILER. If the probe cannot
#: even lay its own source file down it says yes on the strength of the PATH
#: rather than accusing a machine whose toolchain is fine - the same direction
#: everything else here takes when it cannot tell.
#:
#: setupcheck.sh calls THIS, so what the Emulate tab predicts before the run and
#: what the run itself decides are one function - the rule _pad_binfmt_arm is
#: already held to.
_pad_cc_works() {
    local t rc
    command -v gcc >/dev/null 2>&1 || return 1
    t=$(mktemp -d 2>/dev/null) || return 0
    if printf '#include <stdio.h>\nint main(void){return 0;}\n' \
            > "$t/probe.c" 2>/dev/null; then
        gcc -o "$t/probe" "$t/probe.c" >/dev/null 2>&1; rc=$?
    else
        rc=0
    fi
    rm -rf "$t" 2>/dev/null
    return $rc
}

# ---------------------------------------------------------------------------
# The GL bridge
# ---------------------------------------------------------------------------
# Non-zero ONLY when the native renderer is unusable, because that is the one
# case with no fallback: without padglhost there is no window, no keyboard and
# no picture, and starting the guest anyway just leaves a 140%-CPU process to
# be killed.
pad_ensure_bridge() {
    # ---- the native renderer, which is what the user's error was ----------
    if [ ! -x "$PAD_GLHOST_BIN" ]; then
        # No live-run guard here on purpose: a file that does not exist cannot
        # be mapped by anything, so there is nothing to protect and a guard
        # could only refuse to fix the very thing that is broken.
        if ! _pad_cc_works; then
            echo "[build] the GL renderer is not built, and this machine cannot" >&2
            echo "[build] compile it. It is a NATIVE binary and needs gcc AND the" >&2
            echo "[build] C headers - gcc only recommends those, so having the" >&2
            echo "[build] compiler is not enough (on Debian/Ubuntu: apt install" >&2
            echo "[build] gcc libc6-dev) - and then start again." >&2
            echo "[build] Expected at: $PAD_GLHOST_BIN" >&2
            return 1
        fi
        echo "[build] the GL renderer is not built yet; building it (a few seconds)"
        if ! _pad_build buildbridge.sh --host; then
            echo "[build]   build FAILED, and nothing can render without it." >&2
            return 1
        fi
    elif _pad_stale "$PAD_GLHOST_BIN" "$PAD_GLHOST_STAMP" \
                    "$(pad_glhost_hash "$RIG")" $PAD_GLHOST_SRCS; then
        if _pad_run_live; then
            echo "[build] the GL renderer is older than its source, but a run is" >&2
            echo "[build] still up and its binary cannot be rewritten underneath" >&2
            echo "[build] it. Stop it (killgame.sh) to pick up the fix." >&2
        elif ! _pad_cc_works; then
            echo "[build] the GL renderer is older than its source, but this" >&2
            echo "[build] machine cannot compile it (gcc + libc6-dev). Running" >&2
            echo "[build] as built." >&2
        else
            echo "[build] the GL renderer is older than its source; rebuilding"
            _pad_build buildbridge.sh --host \
                || echo "[build]   rebuild FAILED; running the renderer already built" >&2
        fi
    fi

    # ---- the guest half, which speaks the same protocol -------------------
    #
    # "IT IS THERE" PROVES NOTHING HERE, and this is the one place the shim's
    # reasoning does not carry across. $ROOT/usr/lib/libGLESv2.so.2 EXISTS on a
    # brand new rootfs - the rootfs is the machine's own filesystem, and that is
    # STERN'S library. buildbridge.sh replaces it with the bridge encoder. So an
    # untouched setup looks, to a bare `[ -f ]`, exactly like a finished one,
    # and the run that follows draws nothing while every check says fine.
    #
    # The stamp is the only positive evidence that OUR half is what is
    # installed, so no stamp means build it, not assume it.
    local guest=$ROOT/usr/lib/libGLESv2.so.2 why fatal=0
    [ -d "$ROOT/usr/lib" ] || return 0      # no rootfs: not this script's news
    if [ ! -f "$guest" ]; then
        # The guest links against it by name. Absent, the game does not start:
        # `libGLESv2.so.2 => not found`, which is a worse message than this one.
        why="is not there at all"; fatal=1
    elif [ ! -f "$PAD_GLGUEST_STAMP" ]; then
        why="has never been recorded as built from these sources"
    elif _pad_stale "$guest" "$PAD_GLGUEST_STAMP" "$(pad_glguest_hash "$RIG")" \
                    $PAD_GLGUEST_SRCS; then
        # padgl.h is on both source lists, so a protocol change lands here as
        # well as on the host - the two are never allowed to move apart.
        why="is older than its source"
    elif ! grep -aq glTexDirectVIV "$guest" 2>/dev/null; then
        # THE STAMP CAN BE FRESH AND THE FILE STILL BE THE WRONG BACKEND.
        # buildgl.sh - the pre-bridge raster builder, still useful for
        # debugging the software rasteriser - writes glraster.c over this
        # exact file and updates NO stamp, so every check above passes while
        # the installed pad_gl_proc returns 0 for every name: eglGetProcAddress
        # answers "NO-OP (not implemented)" for the VIV upload procs, the
        # window bridge never attaches, and the game plays into a black
        # window with every other counter healthy. Measured 2026-08-10: two
        # full Jaws runs lost to exactly this before anything named it. The
        # bridge encoder EXPORTS glTexDirectVIV, so its name must appear in
        # the file; the raster build has no such string. grep -a because the
        # file is binary and this must not depend on nm being installed.
        why="is the raster backend, not the bridge (buildgl.sh installs over it)"
    else
        return 0
    fi
    if [ "$fatal" = 0 ] && _pad_run_live; then
        echo "[build] the guest GL bridge $why, but a run is still" >&2
        echo "[build] up. Stop it (killgame.sh) to pick up the fix." >&2
        return 0
    fi
    if ! command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; then
        echo "[build] the guest GL bridge $why, and there is no" >&2
        echo "[build] arm-linux-gnueabihf-gcc here to build it (on Debian/Ubuntu:" >&2
        echo "[build] apt install gcc-arm-linux-gnueabihf)." >&2
        [ "$fatal" = 1 ] && { echo "[build] Expected at: $guest" >&2; return 1; }
        echo "[build] Running what is installed." >&2
        return 0
    fi
    echo "[build] the guest GL bridge $why; building it"
    _pad_build buildbridge.sh --guest && return 0
    [ "$fatal" = 1 ] && {
        echo "[build]   build FAILED, and the game will not start without it." >&2
        return 1
    }
    echo "[build]   rebuild FAILED; running the bridge already built" >&2
    return 0
}

# ---- THE GUEST FILESYSTEM, WHICH IS STEP ONE AND WAS NOT CHECKED EITHER -----
#
# run_game.sh chroots into $ROOT, and $ROOT is what rootfs.sh builds out of a
# card image. On a machine where somebody once ran that by hand it is simply
# there - which is every machine this rig was developed on, and no machine a
# user installs the app onto.
#
# THE SYMPTOM WAS FOUR UNRELATED ERRORS AND NO MENTION OF THE ROOTFS. macOS,
# a fresh container volume, v0.114.0:
#
#     dd: failed to open '/pad/rootfs/dump/padled': No such file or directory
#     mkfifo: cannot create fifo '/pad/rootfs/dump/audio.fifo': ...
#     FileNotFoundError: ... '/pad/rootfs/dump/padvid'
#     [watch] the renderer died on startup: open ring: No such file or directory
#
# Not one of those names the thing that is actually missing. This file's own
# header claimed "no rootfs at all is not this function's business - the run
# says so itself, in words about the rootfs", and that was simply not true: the
# run says it four times, in words about a ring, a fifo and two files.
#
# SO IT IS BUILT, not merely reported. Everything needed is already here - the
# user has chosen a card image, which is what pressing Start means, and
# rootfs.sh needs no root - and the alternative is telling someone who installed
# a GUI to run a shell script inside a container, which is not an instruction
# anybody can act on. Minutes, once, with every line of it in the log.
pad_ensure_rootfs() {
    # SCRATCH, AND REMADE EVERY RUN. dump/ holds this run's rings, fifos and
    # derived tables; it is not part of the guest image and only ever existed
    # because rootfs.sh made it on the way past. A rootfs built before a change
    # here, or one whose volume was cleared, otherwise loses every ring
    # separately and one error at a time.
    mkdir -p "$ROOT/dump" 2>/dev/null

    [ -d "$ROOT/usr/lib" ] && return 0          # already built

    _card=${PAD_CARD:-}
    if [ -z "$_card" ] || [ ! -f "$_card" ]; then
        echo "[build] There is no guest filesystem at $ROOT, and that is what" >&2
        echo "[build] the game runs inside - it is built once, from a card" >&2
        echo "[build] image, and this machine has not done it yet." >&2
        echo "[build] Pick a card image and start again and it is built for" >&2
        echo "[build] you (a few minutes, once)." >&2
        return 1
    fi
    echo "[build] FIRST RUN ON THIS MACHINE: building the guest filesystem the"
    echo "[build] game runs inside, from $_card."
    echo "[build] A few minutes, and only this once."
    if ! bash "$RIG/rootfs.sh" "$_card"; then
        echo "[build] the guest filesystem could not be built - see above" >&2
        return 1
    fi
    mkdir -p "$ROOT/dump" 2>/dev/null
    echo "[build] guest filesystem ready"
    return 0
}

# ---- AND WHETHER IT CAN RUN ANYTHING, WHICH IS A DIFFERENT QUESTION --------
#
# A guest filesystem that EXISTS is not one that RUNS, and the gap between
# those two reached a user on 2026-08-07 as a single line with nothing in it
# to act on:
#
#     chroot: failed to run command '/bin/sh': No such file or directory
#
# printed a minute after the window opened, followed by "the game never
# started". Every check the rig had passed: the directories were there, the
# shim was built, the renderer was built, the card mounted, the tables were
# derived. The one thing nobody asked was whether a program could be started
# inside the thing at all.
#
# IT IS ASKED BY DOING IT. The probe is the run's own first step - a user
# namespace, a chroot, /bin/sh - and it costs about 30 ms. Everything below it
# runs ONLY when that fails, so a healthy machine pays a fork and nothing else,
# and a broken one is told which of the four possible faults it has instead of
# waiting 60 seconds to be told the game never started.
#
# The four, all of which produce that ONE message and no other clue:
#
#   * /bin/sh does not resolve inside the rootfs - an extraction that was
#     interrupted, or one made where the WSL disk filled up. REPAIRABLE: the
#     card that was chosen to run is the same card it is built from.
#   * the ARM loader is gone, so the kernel cannot start the shell it found.
#     Same cause, same repair.
#   * the kernel has no handler for 32-bit ARM binaries. Needs root, once, and
#     WSL forgets it on restart unless systemd is enabled - so the message says
#     both how to do it now and how to make it stick.
#   * a handler that is registered WITHOUT the F flag, whose interpreter the
#     kernel then looks for INSIDE the chroot, where it is not. REPAIRABLE
#     with no root at all: put a copy of the interpreter there.

#: THE ONLY TEST THAT PROVES IT. Same namespace and same chroot as
#: run_game.sh, so a pass here means the real thing gets as far as the game.
_pad_guest_probe() {
    # `-r` (a new user namespace mapping the caller to root) is how an
    # UNPRIVILEGED user gets the chroot cap. Real root already has it and does
    # NOT want the userns: as root, `unshare -r` + `chroot` into /home fails
    # "Permission denied" (and item 13's PAD_PIVOT root run drops `-r` for the
    # same reason). So probe the way the run will actually launch - without the
    # userns when we are root, with it otherwise.
    local userns="-r"
    [ "$(id -u)" = 0 ] && userns=""
    unshare $userns -m bash -c 'chroot "$1" /bin/sh -c "exit 0"' _ "$ROOT" 2>&1
}

#: The kernel's handler for 32-bit ARM binaries, if it has one. `qemu-arm` on
#: Debian and Ubuntu; anything else is matched on the ELF magic it registered
#: (e_machine 0x28 = ARM, at offset 18), because THAT is the fact and the name
#: is only a convention. aarch64 and armeb are 64-bit and big-endian and would
#: both match a sloppier test.
_pad_binfmt_arm() {
    local d=/proc/sys/fs/binfmt_misc f
    [ -d "$d" ] || return 1
    [ -f "$d/qemu-arm" ] && { printf '%s\n' "$d/qemu-arm"; return 0; }
    for f in "$d"/*; do
        case "${f##*/}" in register|status|*aarch64*|*armeb*) continue ;; esac
        [ -f "$f" ] || continue
        grep -qi '^magic .*02002800$' "$f" 2>/dev/null && {
            printf '%s\n' "$f"; return 0; }
    done
    return 1
}

#: The command that would register the ARM handler ON THIS MACHINE. Ubuntu
#: 24.04 has no /usr/share/binfmts entry for it any more - systemd imports
#: /usr/lib/binfmt.d instead - so a single printed recipe is wrong on half the
#: machines that need it. Printed only, never run: registering is the one step
#: in this rig that genuinely needs root.
_pad_binfmt_advice() {
    if [ -f /usr/lib/binfmt.d/qemu-arm.conf ]; then
        echo "sudo sh -c 'cat /usr/lib/binfmt.d/qemu-arm.conf > /proc/sys/fs/binfmt_misc/register'"
    elif [ -f /usr/share/binfmts/qemu-arm ]; then
        echo "sudo update-binfmts --import qemu-arm"
    else
        echo "sudo apt install qemu-user-static"
    fi
}

pad_ensure_guest_exec() {
    local out missing entry interp flags card

    out=$(_pad_guest_probe) && return 0

    echo "[guest] the guest filesystem is there, but nothing can be STARTED" >&2
    echo "[guest] inside it, so the game would die the moment it launched:" >&2
    printf '%s\n' "$out" | sed 's/^/[guest]   /' >&2

    # unshare refused before the chroot was ever reached, so nothing below is
    # the fault and none of it would help.
    case "$out" in
        *unshare*)
            echo "[guest] That is the sandbox, not the game: this kernel will" >&2
            echo "[guest] not let an ordinary user make a namespace, and the" >&2
            echo "[guest] run needs one. On WSL, wsl --shutdown and start" >&2
            echo "[guest] again; on Linux, check kernel.unprivileged_userns_clone." >&2
            return 1 ;;
    esac

    # ---- 1. the filesystem, which is the fault that was actually reported --
    missing=$(pad_guest_missing)
    if [ -n "$missing" ]; then
        echo "[guest] $missing is not in $ROOT. The guest filesystem is" >&2
        echo "[guest] INCOMPLETE - an extraction that stopped part way, or one" >&2
        echo "[guest] made where the disk filled up. Every directory the rig" >&2
        echo "[guest] looks for is there, which is why nothing said so before." >&2
        card=${PAD_CARD:-}
        if [ -z "$card" ] || [ ! -f "$card" ]; then
            echo "[guest] Pick a card image and start again and it is rebuilt" >&2
            echo "[guest] for you (a few minutes, once)." >&2
            return 1
        fi
        echo "[guest] Rebuilding it from $card. A few minutes, and only once."
        if ! bash "$RIG/rootfs.sh" --force "$card"; then
            echo "[guest] the rebuild failed - see above." >&2
            return 1
        fi
        out=$(_pad_guest_probe) && {
            echo "[guest] the guest starts programs again; carrying on."
            return 0
        }
        printf '%s\n' "$out" | sed 's/^/[guest]   /' >&2
    fi

    # ---- 2. the kernel's ARM handler --------------------------------------
    entry=$(_pad_binfmt_arm)
    if [ -z "$entry" ]; then
        if [ ! -d /proc/sys/fs/binfmt_misc ]; then
            echo "[guest] This machine's table of binary formats is not visible" >&2
            echo "[guest] from in here, so whether 32-bit ARM can run at all" >&2
            echo "[guest] cannot be checked - and the probe above says it did" >&2
            echo "[guest] not." >&2
            return 1
        fi
        echo "[guest] This kernel has no handler registered for 32-bit ARM" >&2
        echo "[guest] binaries, and the game is one - so nothing off the" >&2
        echo "[guest] machine can run here. That handler is qemu-user-static," >&2
        echo "[guest] and on WSL it is usually installed and then FORGOTTEN:" >&2
        echo "[guest] the registration lives in the running kernel and is put" >&2
        echo "[guest] back at boot by systemd, so a distro started without" >&2
        echo "[guest] systemd loses it every time WSL restarts." >&2
        # THE BUTTON FIRST, WHERE THERE IS ONE. Everything below is what
        # "Set up emulator..." already does - it registers the handler and
        # writes the [boot] section - and on WSL the app can do it without a
        # password (setupfix.sh's header has the whole argument). Printing two
        # root commands ahead of it is how a tester ended up hand-editing WSL
        # config files on 2026-08-12, unsure which strings went in which file,
        # with the one-click version of both sitting on the tab he had just
        # pressed Start on. The commands stay, underneath, for a terminal run
        # and for anyone who would rather see what is being done.
        if [ "${IS_WSL:-0}" = 1 ]; then
            echo "[guest] In PAD: the Emulate tab now offers 'Set up emulator...'," >&2
            echo "[guest] which registers the handler AND makes it survive the next" >&2
            echo "[guest] restart. It lists what it will change before it changes it." >&2
            echo "[guest] By hand instead:" >&2
        fi
        echo "[guest] Now:  $(_pad_binfmt_advice)" >&2
        echo "[guest] Keep: put   [boot]   and   systemd=true   in /etc/wsl.conf," >&2
        echo "[guest]       then wsl --shutdown once." >&2
        return 1
    fi
    if [ "$(head -1 "$entry" 2>/dev/null)" = disabled ]; then
        echo "[guest] The kernel's handler for 32-bit ARM binaries is" >&2
        echo "[guest] registered but DISABLED, so the game cannot start." >&2
        echo "[guest] Enable it:  sudo sh -c 'echo 1 > $entry'" >&2
        return 1
    fi

    # ---- 3. a handler whose interpreter the chroot cannot reach ------------
    #
    # Without the F ("fix binary") flag the kernel opens the interpreter by
    # PATH at exec time, and that path is resolved inside the chroot - where a
    # rootfs off a pinball machine has never heard of qemu. The kernel's ENOENT
    # then names the shell, not the interpreter, which is how this hides.
    # Copying the interpreter in needs no root and no registration change, so
    # it is done rather than explained - and then PROVED by probing again.
    flags=$(sed -n 's/^flags: *//p' "$entry")
    interp=$(sed -n 's/^interpreter *//p' "$entry")
    case "$flags" in
        *F*) ;;
        *)
            if [ -n "$interp" ] && [ -x "$interp" ] && \
               [ ! -e "$ROOT$interp" ]; then
                echo "[guest] The ARM handler is registered without the F flag," >&2
                echo "[guest] so the kernel looks for $interp" >&2
                echo "[guest] INSIDE the guest, where it is not. Putting a copy" >&2
                echo "[guest] there, which needs no root and no re-registering." >&2
                mkdir -p "$ROOT${interp%/*}" 2>/dev/null
                cp -fL "$interp" "$ROOT$interp" 2>/dev/null && \
                    chmod +x "$ROOT$interp" 2>/dev/null
                out=$(_pad_guest_probe) && {
                    echo "[guest] the guest starts programs now; carrying on."
                    return 0
                }
                printf '%s\n' "$out" | sed 's/^/[guest]   /' >&2
            fi ;;
    esac

    echo "[guest] Nothing here could repair that, so the run is stopped now" >&2
    echo "[guest] rather than after a minute of waiting for a game that has" >&2
    echo "[guest] already failed to start." >&2
    return 1
}
