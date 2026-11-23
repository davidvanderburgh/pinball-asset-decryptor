#!/bin/bash
# previewselect.sh <src-dir> <build-dir> <rootfs> - the Multi-boot tab's
# PREVIEW selector: `make all` of codeselect/ into a scratch directory,
# installing nothing, but only when its sources have changed.
#
#   bash tools/spike2_emu/previewselect.sh tools/spike2_emu/codeselect \
#        ~/emusrc/codeselect-preview ~/spike2root
#
# Exit 0 = <build-dir>/codeselect is current; anything else = it could not be
# built, and the caller falls back to the installed selector.
#
# WHY NOT JUST `make` (PAD-1534, 2026-11-23). make decides by file times, and
# the installed app's files carried times about five hours in the future (the
# installer restored the build server's UTC clock as local time). Every
# object was older than the Makefile, so EVERY preview recompiled all 23
# objects and relinked, five seconds each, and poured a few hundred gcc lines
# and "Clock skew detected" into the user's project log. The installer is
# fixed (TimeStampsInUTC), but file times on a /mnt/c tree are not something
# this build should have to trust: WSL's clock drifts after a sleep, and an
# update or a downgrade lays down times in any order.
#
# So the question is the one the installed selector's gate already asks
# (ensurebuild.sh's pad_ensure_select): a digest of PAD_SELECT_SRCS, the same
# list buildselect.sh stages, plus the rootfs the build is linked against.
# Same digest -> nothing compiles. Different -> `make -B`, a FULL rebuild,
# because a digest that moved says nothing about which file times can be
# believed.
#
# QUIET UNLESS IT FAILS. The compiler's output goes to <build-dir>/make.log;
# the log gets one line. On a failure the error lines are printed (first
# ones first - the first error is the cause, see _pad_build in
# ensurebuild.sh), then the file that holds the rest.
SRC=${1:?usage: previewselect.sh <src-dir> <build-dir> <rootfs>}
BUILD=${2:?usage: previewselect.sh <src-dir> <build-dir> <rootfs>}
SYSROOT=${3:?usage: previewselect.sh <src-dir> <build-dir> <rootfs>}

. "$(dirname "$0")/padpath.sh"

#: PAD_SELECT_SRCS names its files as codeselect/<x>, relative to the rig.
SRC_RIG=$(cd "$SRC/.." 2>/dev/null && pwd) || {
    echo "[preview] no selector sources at $SRC" >&2
    exit 1
}
BIN=$BUILD/codeselect
STAMP=$BUILD/codeselect.srcs
LOG=$BUILD/make.log
want="$(pad_src_hash "$SRC_RIG" $PAD_SELECT_SRCS) $SYSROOT"

if [ -x "$BIN" ] && [ -f "$STAMP" ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$want" ]; then
    echo "[preview] menu program up to date: $BIN"
    exit 0
fi

mkdir -p "$BUILD" 2>/dev/null
start=$(date +%s)
# A stamp is only ever laid down by a build that succeeded, and removed
# before one starts, so an interrupted build is never taken as current.
rm -f "$STAMP"
make -B -C "$SRC" BUILD="$BUILD" ROOT="$SYSROOT" all >"$LOG" 2>&1
rc=$?
if [ "$rc" = 0 ]; then
    printf '%s\n' "$want" > "$STAMP"
    echo "[preview] menu program built in $(( $(date +%s) - start )) s: $BIN"
    exit 0
fi
echo "[preview] the menu program did not build (make exit $rc):" >&2
errs=$(grep -E ': (fatal )?error:|undefined reference|No such file|command not found|No rule to make|\*\*\*' "$LOG" | head -12)
if [ -n "$errs" ]; then
    printf '%s\n' "$errs" | sed 's/^/[preview]   /' >&2
else
    tail -8 "$LOG" | sed 's/^/[preview]   /' >&2
fi
echo "[preview]   full compiler output: $LOG" >&2
exit "$rc"
