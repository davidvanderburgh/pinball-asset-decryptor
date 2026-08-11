#!/bin/bash
# getcriu.sh - RUN AS ROOT. Build criu from source, because no Ubuntu ships it.
#
#   wsl -u root -e bash tools/spike2_emu/getcriu.sh        (from Windows)
#   sudo bash tools/spike2_emu/getcriu.sh                  (on Linux)
#
# WHY THIS EXISTS, and it is the plainest fault in the save-state feature.
# criu is what freezes the guest and thaws it again (savestate.sh /
# restorestate.sh). Every one of those scripts defaulted to
#
#     /var/tmp/criubuild/criu/criu/criu
#
# which is ONE developer's hand-built v4.1, on ONE machine, in a directory
# nobody else has ever had. And it could not simply be added to the
# prerequisite list beside busybox-static, because:
#
#     $ apt-cache policy criu
#     criu:
#       Installed: (none)
#       Candidate: (none)
#       Version table:
#
# an EMPTY table - Ubuntu 24.04 does not publish criu at all, in any component
# (the only criu-named package in the archive is a Go binding). So there was
# nothing to install and nothing to tell anyone to install, and save states
# could not work for a single user however carefully they set their machine up.
# They would get the checkpointable boot, the Save and Load buttons, and then
# `savestate: no criu at /var/tmp/criubuild/...` on the press.
#
# THE .deb FROM ANOTHER RELEASE IS NOT THE WAY OUT, before anyone tries it.
# setupfix.sh's _fetch_foreign exists for exactly one package and says why:
# qemu-user-static Depends on NOTHING, so it cannot drag another release's
# library chain in behind it. criu links against libprotobuf-c, libnl-3,
# libnet, libbsd and libuuid; cross-installing that is how "the emulator will
# not start" becomes "apt is broken". Debian packages criu and Ubuntu does
# not, which makes it worse, not better.
#
# So it is built here, from the pinned tag that this rig's whole save-state
# ladder was proven against (criuladder.sh, 2026-08-07). About three minutes
# on six cores.
#
# WHAT IT TOUCHES, all of it named in the app's consent dialog before it runs:
#   * apt-get install of the documented build dependencies
#   * a source tree under /var/tmp/pad-criu (kept, so a rebuild is cheap;
#     /var/tmp and NOT /tmp, which this WSL wipes on every restart)
#   * /usr/local/bin/criu - the conventional home for a from-source build, and
#     the first place pad_criu looks
# Nothing is removed, nothing is downgraded, and no package source is changed.
#
# Output is plain lines for the log pane, then a final `result=` line.

set -u
RIG=$(cd "$(dirname "$0")" && pwd)
. "$RIG/padpath.sh"

#: The tag, not a moving branch. v4.1 is what criuladder.sh's seven rungs were
#: run against and what `criu check` was confirmed on for the WSL2 6.6 kernel;
#: "whatever master is today" would make every future save-state failure a
#: question about which criu the user happens to have built.
CRIU_VERSION=${PAD_CRIU_VERSION:-v4.1}
CRIU_REPO=${PAD_CRIU_REPO:-https://github.com/checkpoint-restore/criu.git}
WORK=${PAD_CRIU_WORK:-/var/tmp/pad-criu}
DEST=${PAD_CRIU_DEST:-/usr/local/bin/criu}

#: THE DEPENDENCIES, and two of them are not on criu's own documented list.
#: `uuid-dev` is the one the build aborts on WITHOUT NAMING IT - a bare
#: "Makefile.config: no such thing" style stop that costs a session to work
#: out - and libbsd-dev is picked up the same silent way. The rest are the
#: documented set. Test-only deps (libaio-dev, python3-yaml) are deliberately
#: absent: this builds the binary, it does not run criu's own test suite.
DEPS="build-essential git pkg-config libprotobuf-dev libprotobuf-c-dev
protobuf-c-compiler protobuf-compiler python3-protobuf libnl-3-dev
libnet1-dev libcap-dev libbsd-dev uuid-dev"

if [ "$(id -u)" != 0 ]; then
    echo "getcriu.sh must run as root - it installs build packages and writes"
    echo "to $DEST."
    echo "  wsl -u root -e bash $0        (from Windows)"
    echo "  sudo bash $0                  (on Linux)"
    echo "result=notroot"
    exit 1
fi

#: Same shape as setupfix.sh's: indent the output and keep the STATUS, which a
#: bare `cmd | sed` throws away (a pipeline reports sed's success, so a failed
#: build reads as a clean one).
_run() {
    local out rc
    out=$("$@" 2>&1); rc=$?
    [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/  /'
    return $rc
}

# ---- 0. is one already here? ----------------------------------------------
#
# Asked of pad_criu, which is what the rig's own scripts ask, so this can never
# install a second copy beside a working one - or, worse, report success about
# a criu the scripts do not use.
if have=$(pad_criu); then
    echo "criu is already here: $have"
    "$have" --version 2>&1 | sed 's/^/  /'
    echo "result=present"
    exit 0
fi

echo "This machine has no criu, and no Ubuntu release publishes one, so it has"
echo "to be built. Three or four minutes, once."

# ---- 1. what the build needs ----------------------------------------------
echo "installing the build dependencies: $(echo $DEPS | tr -s ' ')"
export DEBIAN_FRONTEND=noninteractive
# `update` first for the same reason setupfix.sh does it: a WSL image that has
# sat unused for months has an index too old to resolve anything, and the
# failure that produces ("Unable to locate package") reads like the package
# does not exist. Not fatal on its own - the install below decides.
_run apt-get update -qq
if ! _run apt-get install -y -qq $DEPS; then
    echo "could not install the build dependencies - see above. Nothing else"
    echo "was attempted, and nothing on this machine was changed."
    echo "result=nodeps"
    exit 1
fi

# ---- 2. the source, at a pinned tag ---------------------------------------
mkdir -p "$WORK" || { echo "cannot create $WORK"; echo "result=nosource"; exit 1; }
SRC=$WORK/criu
if [ -d "$SRC/.git" ]; then
    # A previous run left it. Reuse rather than re-download 50 MB - and say so,
    # because "it was fast" must never look like "it did nothing".
    echo "reusing the source already at $SRC"
    _run git -C "$SRC" fetch --depth 1 origin "$CRIU_VERSION" || true
    if ! _run git -C "$SRC" checkout -q FETCH_HEAD; then
        echo "the existing source tree is not usable; removing it and cloning"
        rm -rf "$SRC"
    fi
fi
if [ ! -d "$SRC/.git" ]; then
    echo "downloading criu $CRIU_VERSION from $CRIU_REPO"
    if ! _run git clone --depth 1 --branch "$CRIU_VERSION" "$CRIU_REPO" "$SRC"
    then
        echo "could not download the source. This step needs the internet from"
        echo "inside WSL; if that machine is behind a proxy, git has to know"
        echo "about it. Nothing was installed."
        echo "result=nosource"
        exit 1
    fi
fi

# ---- 2a. the one patch this pinned tree needs on a 2026 compiler ----------
#
# THE SAME SHAPE AS v0.119.1's hwshim fault, in someone else's source tree:
# the user's compiler is newer than the one this pin was proven with, and it
# answers a question differently. Reported 2026-08-11 from a fresh WSL install,
# where the build stopped on the FIRST file of criu's parasite:
#
#   criu/include/linux/rseq.h:33:1: error: conflicting redefinition of enum
#                                          'enum rseq_flags'
#   criu/include/linux/rseq.h:39:1: error: ... 'enum rseq_cs_flags_bit'
#   criu/include/linux/rseq.h:45:1: error: ... 'enum rseq_cs_flags'
#
# WHY, and the log names it precisely. criu carries a spare copy of the four
# rseq enums for C libraries too old to have them, and defines it only when
# CONFIG_HAS_NO_LIBC_RSEQ_DEFS is set. That flag is decided by COMPILING a
# probe (scripts/feature-tests.mak): the probe declares `enum rseq_cpu_id_state`
# after including <sys/rseq.h>, and if that compile FAILS the libc evidently
# has the definitions already. glibc has had them since 2.35.
#
# GCC 15 defaults to -std=gnu23, and C23 allows a tag to be redefined when the
# two definitions agree - which the probe's does, exactly. So the probe now
# COMPILES on a machine whose libc has the enums, criu concludes they are
# missing, and its spare copy lands on top of the real one. THE FINGERPRINT IS
# IN WHICH THREE FAILED: `enum rseq_cpu_id_state` on line 29 is the one enum
# the probe declares and the one that did NOT error - it is the redefinition
# that compiler accepts. The other three it does not.
#
# THE FIX IS UPSTREAM'S OWN, one release old: criu v4.2.1 (2026-07-20) renames
# the probe's enumerators so the redefinition can never agree with the libc's
# and the probe fails, as it must, on every machine that already has them.
# v4.1, v4.1.1 and v4.2 all carry the original. Applied HERE rather than by
# moving the pin, because v4.1 is the tag criuladder.sh's seven rungs and
# `criu check` were proven against and a save-state ladder is not something to
# re-prove from a build script. Drop this block whenever the pin moves to
# v4.2.1 or later - the `grep` below already leaves such a tree alone.
#
# IT COSTS A REBUILD, AND THAT IS THE POINT: criu's generated config header
# depends on scripts/feature-tests.mak, so a tree that was already built with
# the wrong answer regenerates it and recompiles rather than reusing objects
# built around a definition that is not there.
FEATURES=$SRC/scripts/feature-tests.mak
if [ -f "$FEATURES" ] && ! grep -q RSEQ_CPU_CRIU_TEST "$FEATURES"; then
    # Confined to the one probe by the address range: those enumerator names
    # are criu's own elsewhere in the tree and mean something there.
    sed -i '/^define FEATURE_TEST_NO_LIBC_RSEQ_DEFS$/,/^endef$/{
                s/RSEQ_CPU_ID_UNINITIALIZED/RSEQ_CPU_CRIU_TEST/
                s/RSEQ_CPU_ID_REGISTRATION_FAILED/RSEQ_CPU_CRIU_TEST2/
            }' "$FEATURES" 2>/dev/null
    if grep -q RSEQ_CPU_CRIU_TEST "$FEATURES"; then
        echo "patched criu's rseq probe (v4.2.1's fix): a C23 compiler answers"
        echo "the original wrongly and the build stops in parasite.c"
    else
        # Never silent, and never fatal: an unpatched tree still builds
        # perfectly on every compiler older than this, which is most of them.
        echo "could not patch criu's rseq probe - this tree does not have the"
        echo "probe where it was; building it as it came"
    fi
fi

# ---- 3. build it ----------------------------------------------------------
#
# `make criu`, NOT `make`. The default target is `all: criu lib crit
# cuda_plugin` - the Python bindings, the crit tool and a GPU plugin, none of
# which this rig has ever used and every one of which is another way for the
# build to fail on a machine that is about to work perfectly.
#
# The output is NOT swallowed by _run here. A silent three minutes in the app's
# log pane is indistinguishable from a hang, and criu's build prints one short
# line per file, which is exactly the progress this needs.
echo "building criu $CRIU_VERSION (this is the slow part)..."
#
# pipefail, because the status of `make | sed` is SED's - and sed always
# succeeds. Without it a build that failed on line three reports success and
# the missing binary is discovered two steps later, blamed on something else.
if ! ( cd "$SRC" && set -o pipefail &&
       make -j"$(nproc 2>/dev/null || echo 2)" criu 2>&1 | sed -u 's/^/  /' ); then
    echo "the build failed - the errors are above. The source is left at $SRC"
    echo "so it can be looked at or built again by hand."
    echo "result=buildfailed"
    exit 1
fi
BIN=$SRC/criu/criu
[ -x "$BIN" ] || {
    echo "the build reported success but produced no binary at $BIN"
    echo "result=buildfailed"
    exit 1
}

# ---- 4. does it work ON THIS KERNEL, which is a different question ---------
#
# criu is a kernel-features program: it needs specific /proc interfaces,
# ptrace shapes and namespace support, and WSL2 runs Microsoft's own kernel.
# `criu check` is criu's own answer about the machine it is standing on, and
# it is asked BEFORE the binary is installed on purpose - installing one that
# cannot dump anything would turn the tab's "save states need criu" notice
# off while leaving the buttons just as broken, which is the exact fault this
# whole pass exists to stop. (Plain `check`, not `--all`: --all fails on
# nftables locking and one dev:ino probe on a perfectly good WSL kernel, and
# neither is anything the guest uses.)
echo "checking that criu works on this kernel:"
"$BIN" --version 2>&1 | sed 's/^/  /'
if ! _run "$BIN" check; then
    echo "criu built, but it says this kernel cannot support it - so it has"
    echo "NOT been installed: a criu that cannot dump would only turn the"
    echo "warning off and leave the Save buttons failing. The build is at $BIN"
    echo "if you want to look into it."
    echo "result=checkfailed"
    exit 1
fi

# ---- 5. install ------------------------------------------------------------
if ! _run install -m 0755 "$BIN" "$DEST"; then
    echo "could not install to $DEST"
    echo "result=installfailed"
    exit 1
fi
# PROVE IT, through the same function the rig's scripts use, rather than
# reporting the step that was taken. `install` succeeding says the file was
# copied; this says the save-state scripts will find it.
found=$(pad_criu) || {
    echo "installed to $DEST, but pad_criu still cannot find a criu - which"
    echo "means the rig would not use it either."
    echo "result=installfailed"
    exit 1
}
echo "criu $CRIU_VERSION is installed at $found"
echo "Save states will work from the next time you start a title."
echo "result=ok"
