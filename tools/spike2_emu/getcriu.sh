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

# ---- 2a. the one SOURCE patch this pinned tree needs ----------------------
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
#
# 2b's dialect pin below would settle this probe too - in C17 the redefinition
# is an error again, which is what the probe is asking. This stays anyway,
# because the failure message tells the user the tree is left at $SRC "so it
# can be looked at or built again by hand", and a hand `make` in there gets
# none of 2b.
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

# ---- 2b. the C DIALECT this tag was written in ----------------------------
#
# This holds the build in the language criu v4.1 was written and PROVEN in,
# which is worth doing on its own: it is the dialect criuladder.sh's seven
# rungs were run against, and in C17 the rseq redefinition 2a patches is an
# error again, so the probe there is asked its question twice over.
#
# WHAT IT DOES NOT DO - and v0.130.1 shipped believing it did - IS FIX 2c
# BELOW. That is written up there in full; the short version is that the C23
# str*chr change is gated on a glibc feature macro that criu's own
# -D_GNU_SOURCE turns on no matter what -std= says, so a dialect never
# reaches it. Reported again 2026-08-13 by a second user, on a build that
# already had this block.
#
# criu's own USERCFLAGS is the documented seam, and its Makefile folds it into
# CFLAGS on line 171, BEFORE Makefile.config is included on line 232 - so the
# feature probes in 2a compile in the same dialect the sources do, and cannot
# answer a question one way for a build that then happens the other way.
#
# NOT WERROR=0, here or in 2c: it works, and blinds the build to every other
# complaint a compiler this much newer than the pin has, including the ones
# that mean something. It is a statement about not wanting to hear.
#
# Probed, not assumed: -std=gnu17 wants GCC 8 or clang 6, and a compiler old
# enough to refuse it is old enough not to have the problem. An empty STD is
# then exactly the build every machine got before this block existed.
STD=
if echo 'int main(void) { return 0; }' |
   "${CC:-cc}" -std=gnu17 -x c - -o /dev/null 2>/dev/null; then
    STD=-std=gnu17
    echo "building it as C17, which is the dialect criu $CRIU_VERSION was"
    echo "written and proven in"
else
    echo "${CC:-cc} does not take -std=gnu17; building with its own default"
fi

# AND THE TREE MAY ALREADY HOLD OBJECTS BUILT THE OTHER WAY. make compares
# timestamps, not command lines: nothing here is a file, so a flag change is
# invisible to it and a reused tree would link C17 objects to C23 ones. That
# tree is reused ON PURPOSE (step 2 says so), which is exactly what makes this
# necessary. So the flags are recorded beside it, and a change costs the
# objects once - never the download, and never on a fresh clone, which has no
# objects to lose.
STAMP=$WORK/.pad-build-flags
if [ "$(cat "$STAMP" 2>/dev/null)" != "$STD" ] &&
   [ -n "$(find "$SRC" -name '*.o' -print -quit 2>/dev/null)" ]; then
    echo "this tree was last built with different flags - clearing its objects"
    echo "so the whole binary is one dialect"
    _run make -C "$SRC" clean || true
fi
printf '%s\n' "$STD" > "$STAMP" 2>/dev/null || true

# ---- 2c. the one line C23 made wrong, and upstream has already fixed ------
#
# REPORTED TWICE, by two different people, and v0.130.1's answer to the first
# one did not work. The build stops ~250 files after the parasite:
#
#   CC criu/tty.o
#   criu/tty.c:262:21: error: initialization discards 'const' qualifier from
#                             pointer target type [-Werror=discarded-qualifiers]
#   262 |     char *pos = strrchr(link->name, '/');
#
# THE LINE IS NOT WRONG BY THE RULES IT WAS WRITTEN UNDER. `link` is a `const
# struct fd_link *`, so `link->name` is a `const char *`, and C's strrchr has
# always taken a const char * and handed back a plain `char *` - a deliberate
# hole in the type system every compiler agreed to. C23 closed it: strchr,
# strrchr, memchr, strstr and strpbrk became TYPE-GENERIC, so a const argument
# gives a const result, and this pinned tag predates the change.
#
# WHY 2b's DIALECT PIN DOES NOT REACH IT, which is the whole lesson of this
# ticket, because -std=gnu17 looks like it must. The gate is five links long
# and NOT ONE OF THEM ASKS WHAT -std= IS:
#
#   criu Makefile:114     DEFINES += -D_GNU_SOURCE        (unconditional)
#   glibc features.h      _GNU_SOURCE  => _ISOC23_SOURCE 1
#   glibc features.h      _ISOC23_SOURCE => __GLIBC_USE_ISOC23 1
#   glibc sys/cdefs.h     __glibc_const_generic exists whenever the compiler
#                         has _Generic (__GNUC_PREREQ(4,9)), not by dialect
#   glibc string.h        #if __GLIBC_USE (ISOC23) && defined
#                            __glibc_const_generic => the const-generic macros
#
# So criu asks for the C23 str*chr behaviour ITSELF, in DEFINES, every time it
# compiles anything - and DEFINES lands on the command line AFTER USERCFLAGS.
# Confirmed on this box (glibc 2.39): `-std=gnu17 -D_GNU_SOURCE` reports
# __GLIBC_USE(ISOC2X)=1, and criu's own line under the real glibc macros gives
# the reporter's exact error in gnu17 and gnu2x alike, clean only when
# _GNU_SOURCE is removed - which criu cannot do.
#
# AND -Wno-error=discarded-qualifiers IS NOT THE WAY OUT EITHER: USERCFLAGS
# lands BEFORE $(WARNINGS), which ends in -Werror, so it is turned straight
# back on. That leaves the line, which is where the fault actually is.
#
# IT IS ONE LINE, AND THAT IS MEASURED, NOT GUESSED. The worry that stopped
# this last time was that the tree calls str*chr 84 times and a glibc 2.39 box
# cannot see which take a const argument. It can: build v4.1 with the five
# macros above forced in ahead of it and WERROR=0, and every affected site
# warns at once. The whole tree, criu binary and all, yields EXACTLY ONE -
# this one. tty.c:514's `char *pos = strrchr(orig->rfe->name, '/')` is not
# const and is deliberately left alone, which is why the match below is
# anchored to `link->name`.
#
# THE FIX IS UPSTREAM'S OWN, from the same release 2a already borrows from:
# criu v4.2.1 declares it `const char *pos`. Everything the function then does
# with pos - the bounds compare and atoi(pos + 1) - is fine on a const char *.
# Applied here rather than by moving the pin, for the reason 2a gives. Drop
# this block whenever the pin moves to v4.2.1 or later; the grep leaves an
# already-fixed tree alone, so a rebuild costs nothing.
TTY=$SRC/criu/tty.c
if [ -f "$TTY" ] && grep -q '^[[:space:]]*char \*pos = strrchr(link->name' "$TTY"
then
    sed -i 's/^\([[:space:]]*\)char \*pos = strrchr(link->name/\1const char *pos = strrchr(link->name/' \
        "$TTY" 2>/dev/null
    if grep -q 'const char \*pos = strrchr(link->name' "$TTY"; then
        echo "patched criu's tty.c (v4.2.1's fix): C23 made strrchr return const"
        echo "for a const argument and this tag predates that"
    else
        # Never silent, and never fatal: a tree this does not match still
        # builds perfectly on every compiler older than C23, which is most.
        echo "could not patch criu's tty.c - this tree does not have the line"
        echo "where it was; building it as it came"
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
       make -j"$(nproc 2>/dev/null || echo 2)" USERCFLAGS="$STD" criu 2>&1 |
       sed -u 's/^/  /' ); then
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
