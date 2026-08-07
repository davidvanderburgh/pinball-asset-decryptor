#!/bin/bash
# ensurebuild.sh - SOURCED, never run. "Is what is about to run actually built,
# and built from THESE sources?"
#
#   . "$(dirname "$0")/ensurebuild.sh"
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
_pad_build() {           # <script> [args...]
    local script=$1 out rc
    shift
    out=$(bash "$RIG/$script" "$@" 2>&1); rc=$?
    if [ $rc = 0 ]; then
        printf '%s\n' "$out" | sed 's/^/[build]   /'
    else
        printf '%s\n' "$out" | tail -8 | sed 's/^/[build]   /' >&2
    fi
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
        if ! command -v gcc >/dev/null 2>&1; then
            echo "[build] the GL renderer is not built, and there is no gcc here" >&2
            echo "[build] to build it. It is a NATIVE binary - install gcc (on" >&2
            echo "[build] Debian/Ubuntu: apt install gcc) and start again." >&2
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
        elif ! command -v gcc >/dev/null 2>&1; then
            echo "[build] the GL renderer is older than its source, but there is" >&2
            echo "[build] no gcc here to rebuild it. Running as built." >&2
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
