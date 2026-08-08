#!/bin/bash
# Can CRIU checkpoint and restore a QEMU-USER process? (item 13, save states)
#
#   wsl -u root -e bash tools/spike2_emu/criuladder.sh
#
# Needs root (criu does). Starts NO emulator run, touches nothing the rig
# owns, and never goes near the game. Takes about 30 seconds.
#
# WHY IT EXISTS. Item 13's whole design rests on one untested assumption: that
# criu can dump and restore the guest, which is qemu-arm-static with a JIT and
# a multi-gigabyte reserved guest address space. Nobody had ever pointed criu
# at a qemu-user process. If it cannot, the design dies whatever else is true,
# and it dies cheaply here rather than expensively inside a live game.
#
# THE LADDER, and the order is the point - each rung adds exactly one thing, so
# a failure names its own cause instead of leaving a shrug:
#   A. an ordinary x86-64 process          -> is criu working AT ALL here
#   B. the same program built for ARM,
#      running under qemu-arm-static       -> can criu dump QEMU-USER
#
# HOW EACH RUNG IS JUDGED, and this is the part that matters. A restored
# process and a freshly restarted one look IDENTICAL from outside - both are
# alive, both are writing. This repo has been fooled by exactly that shape
# before ("alive after 2 s proves nothing", item 12). So the test program
# counts, and a rung passes only if the counter CONTINUES: a restart begins at
# 1 again and fails on its own evidence. Alive is not the test; continuity is.

set -u
WORK=/var/tmp/criuladder
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}

[ "$(id -u)" = 0 ] || { echo "criuladder: needs root (criu does). Use: wsl -u root -e bash $0"; exit 2; }
[ -x "$CRIU" ] || { echo "criuladder: no criu at $CRIU - build it first, or set CRIU="; exit 2; }

rm -rf "$WORK"; mkdir -p "$WORK/dumpA" "$WORK/dumpB"
cd "$WORK" || exit 2

# ---------------------------------------------------------------- the subject
# Single process, no forks, no held fds: it re-opens the count file each pass
# and closes it. That is deliberate. These rungs answer "can the address space
# come back", and holding fds would fold a second question into the same
# answer. What that leaves untested is listed at the end rather than assumed.
cat > count.c <<'EOF'
#include <stdio.h>
#include <unistd.h>
int main(int argc, char **argv)
{
    long i = 0;
    for (;;) {
        FILE *f = fopen(argv[1], "w");
        if (f) { fprintf(f, "%ld\n", ++i); fclose(f); }
        usleep(200000);
    }
    return 0;
}
EOF

echo "=== building the subject"
gcc -O0 -o countx86 count.c || { echo "  x86 build FAILED"; exit 1; }
echo "  countx86 ok"
ARMOK=0
if command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; then
    # STATIC on purpose: a dynamic ARM binary would drag the rig's rootfs and
    # its loader into a test that is not about them.
    if arm-linux-gnueabihf-gcc -O0 -static -o countarm count.c 2>/dev/null; then
        ARMOK=1; echo "  countarm ok (static ARM)"
    else
        echo "  countarm build FAILED (no static libc for the cross target?)"
    fi
else
    echo "  no arm-linux-gnueabihf-gcc - rung B will be skipped"
fi

# ---------------------------------------------------------------- one rung
# name, dump dir, count file, and the command to start
rung()
{
    local NAME=$1 DDIR=$2 CFILE=$3; shift 3
    echo
    echo "=== rung $NAME"
    rm -f "$CFILE"

    # ★ THE INHERITED-PTMX TRAP, AND IT IS NOT A PROPERTY OF THIS TEST.
    # criu refuses a dump with "Found dangling tty with sid N pgid M (ptmx) on
    # peer fd 7". setsid does not help and neither does </dev/null: what it
    # objects to is an inherited FD, and MEASURED HERE, every process started
    # through wsl.exe carries TWO of them -
    #     7 -> /dev/ptmx     10 -> /dev/ptmx
    # inherited from WSL's own `login`/`bash` on pts/1 (sid 299, pgid 368).
    # The invoking shell has them, so everything it starts has them, all the
    # way down through unshare and chroot. THIS APPLIES TO THE REAL GUEST: it
    # is started by watch.sh through the same chain, so anything that ever
    # wants to checkpoint it must close these first.
    # Hence the explicit close loop rather than a redirect.
    setsid bash -c 'for fd in $(seq 3 63); do eval "exec $fd>&-" 2>/dev/null; done; exec "$@"' \
        _ "$@" "$CFILE" </dev/null >/dev/null 2>&1 &
    # $! is the subject's own pid: this script is non-interactive, so bash job
    # control is off, background jobs stay in its process group, setsid is
    # therefore NOT a group leader and does not fork - it execs straight
    # through. Verified by the pid criu reports matching this one.
    local PID=$!
    # ★ RUN IT LONG BEFORE DUMPING, AND THAT IS THE TEST'S WHOLE VALIDITY.
    # The pass condition below is "the counter is higher after the restore than
    # it was when frozen". At 5 counts/s a FRESH process reaches ~20 in the
    # 4 s observation window, so freezing at 10 would let a restart clear the
    # bar and be scored a restore - which is the exact failure this rung
    # exists to detect. Running ~12 s first puts the frozen value near 60,
    # about 3x what any restart could reach before it is read. The margin is
    # printed with the result so it can be checked rather than trusted.
    sleep 12

    if ! kill -0 "$PID" 2>/dev/null; then
        echo "  FAIL  subject died before the dump (it never ran)"
        return 1
    fi
    local V1; V1=$(cat "$CFILE" 2>/dev/null)
    echo "  subject pid $PID, counter at $V1"
    [ -n "$V1" ] || { echo "  FAIL  subject wrote no counter"; kill -9 "$PID" 2>/dev/null; return 1; }

    echo "  dumping..."
    "$CRIU" dump -t "$PID" -D "$DDIR" -v4 -o dump.log --leave-stopped 2>&1 | tail -3
    local DRC=${PIPESTATUS[0]}
    # JUDGE THE DUMP ON ITS EXIT CODE AND ITS OWN LOG, NOT ON THE IMAGES.
    # criu writes core-*.img, mm-*.img and pages-1.img BEFORE it gets to the
    # step that fails, so a dump that ends in "Dumping FAILED" still leaves a
    # convincing directory behind. The first version of this script tested for
    # those files and called a failed dump a success - the same partial-output
    # trap this repo has hit with "alive after 2 s".
    if [ "$DRC" != 0 ] || grep -aq 'Dumping FAILED' "$DDIR/dump.log" 2>/dev/null; then
        echo "  FAIL  dump failed (exit $DRC)"
        echo "  --- dump errors:"
        grep -aE 'Error' "$DDIR/dump.log" 2>/dev/null | tail -8 | sed 's/^/      /'
        kill -9 "$PID" 2>/dev/null
        return 1
    fi
    echo "  dump ok ($(du -sh "$DDIR" 2>/dev/null | cut -f1), $(ls "$DDIR"/*.img 2>/dev/null | wc -l) images)"

    # --leave-stopped leaves it SIGSTOPped; kill it so the restore cannot be
    # confused with the original still running. That confusion is not
    # hypothetical: without this the counter keeps advancing and every rung
    # "passes".
    kill -9 "$PID" 2>/dev/null
    sleep 1
    local V2; V2=$(cat "$CFILE" 2>/dev/null)
    sleep 1
    local V3; V3=$(cat "$CFILE" 2>/dev/null)
    if [ "$V2" != "$V3" ]; then
        echo "  FAIL  counter still moving after the kill ($V2 -> $V3) - the"
        echo "        original is alive, so any 'restore' below proves nothing"
        return 1
    fi
    echo "  original dead, counter frozen at $V3"

    echo "  restoring..."
    "$CRIU" restore -D "$DDIR" -v4 -o restore.log -d 2>&1 | tail -3
    sleep 3
    local V4; V4=$(cat "$CFILE" 2>/dev/null)
    local V5; sleep 1; V5=$(cat "$CFILE" 2>/dev/null)

    if [ -z "$V4" ] || [ "$V4" = "$V3" ]; then
        echo "  FAIL  nothing is counting after the restore (still $V3)"
        echo "  --- last restore errors:"
        grep -aE 'Error' "$DDIR/restore.log" 2>/dev/null | tail -10 | sed 's/^/      /'
        return 1
    fi
    if [ "$V5" = "$V4" ]; then
        echo "  FAIL  restored process is not advancing ($V4 twice) - alive but stuck"
        return 1
    fi
    # THE DISCRIMINATOR. A fresh start counts from 1; a restore resumes above
    # where the dump caught it. Anything at or below the frozen value is a
    # restart wearing a restore's clothes. See the sleep above for why the
    # frozen value is made large first - without that margin this comparison
    # is decoration.
    #
    # CEIL is what a process that started from scratch at the restore could
    # have reached by now: ~5 counts/s over the ~4 s of sleeps since. Printed
    # either way, so the margin is visible rather than claimed.
    local CEIL=25
    if [ "$V4" -le "$V3" ] 2>/dev/null; then
        echo "  FAIL  counter RESTARTED ($V3 -> $V4) - that is a new process,"
        echo "        not a restored one"
        pkill -f "$CFILE" 2>/dev/null
        return 1
    fi
    if [ "$V3" -le "$CEIL" ] 2>/dev/null; then
        echo "  FAIL  inconclusive: frozen at $V3, but a FRESH start could reach"
        echo "        ~$CEIL in the same window, so '$V4 > $V3' proves nothing."
        echo "        The subject did not run long enough before the dump."
        pkill -f "$CFILE" 2>/dev/null
        return 1
    fi

    echo "  PASS  counter continued: $V3 (frozen) -> $V4 -> $V5"
    echo "        (a fresh restart could only have reached ~$CEIL by now, so"
    echo "         $V4 is a resume and not a restart, by a margin of $((V4 - CEIL)))"
    pkill -f "$(basename "$1")" 2>/dev/null
    sleep 0.5
    return 0
}

# ---------------------------------------------------------- negative control
# ★ THE LABELLED FAILURE, and it runs FIRST on purpose.
# Rungs A and B pass only if the harness can tell a restore from a restart. So
# prove it can, on a case whose answer is known: kill the subject and START A
# NEW ONE instead of restoring. The counter goes back to 1, and the harness
# MUST call that a failure. If this control "passes", every result below it is
# worthless and the script says so and stops - a metric that cannot fail its
# own negative case has scored nothing, which is how three audio metrics in
# this repo were caught ranking a good capture below a bad one.
control()
{
    echo
    echo "=== control - a deliberate RESTART, which MUST be scored FAIL"
    local CFILE=$WORK/c.count
    rm -f "$CFILE"
    setsid bash -c 'for fd in $(seq 3 63); do eval "exec $fd>&-" 2>/dev/null; done; exec "$@"' \
        _ "$WORK/countx86" "$CFILE" </dev/null >/dev/null 2>&1 &
    local PID=$!
    sleep 12
    local V3; V3=$(cat "$CFILE" 2>/dev/null)
    kill -9 "$PID" 2>/dev/null; sleep 1
    echo "  original frozen at $V3, now starting a FRESH process"
    rm -f "$CFILE"
    setsid bash -c 'for fd in $(seq 3 63); do eval "exec $fd>&-" 2>/dev/null; done; exec "$@"' \
        _ "$WORK/countx86" "$CFILE" </dev/null >/dev/null 2>&1 &
    local NPID=$!
    sleep 4
    local V4; V4=$(cat "$CFILE" 2>/dev/null)
    kill -9 "$NPID" 2>/dev/null
    echo "  fresh process reached $V4 against a frozen $V3"
    if [ "${V4:-0}" -le "$V3" ] 2>/dev/null; then
        echo "  ok    the harness would score this FAIL (restart detected)"
        return 0
    fi
    echo "  BROKEN  the harness would score a RESTART as a PASS."
    echo "          Every rung below is meaningless. Raise the pre-dump sleep."
    return 1
}

RA=1; RB=1
if ! control; then
    echo
    echo "=== aborting: the harness failed its own negative control"
    exit 1
fi

rung "A - ordinary x86-64 process" "$WORK/dumpA" "$WORK/a.count" "$WORK/countx86" && RA=0

if [ "$ARMOK" = 1 ]; then
    rung "B - ARM binary under qemu-arm-static" "$WORK/dumpB" "$WORK/b.count" \
         /usr/bin/qemu-arm-static "$WORK/countarm" && RB=0
else
    echo; echo "=== rung B SKIPPED (no ARM binary)"
fi

echo
echo "=== verdict"
[ $RA = 0 ] && echo "  A  ok   criu dumps and restores an ordinary process on this kernel" \
            || echo "  A  NO   criu cannot even do a plain process here - nothing else matters"
if [ "$ARMOK" = 1 ]; then
    [ $RB = 0 ] && echo "  B  ok   criu dumps and restores QEMU-USER - item 13's design is not dead" \
                || echo "  B  NO   criu cannot dump qemu-user - item 13 needs a different design"
else
    echo "  B  ?    skipped"
fi
echo
echo "  NOT tested by these rungs, and each is a later rung, not an assumption:"
echo "    - held fds, and the pty the node bus binds onto /dev/ttymxc1"
echo "    - the mount namespace, the chroot, and the fuse2fs card bind mount"
echo "    - file-backed MAP_SHARED rings with a host helper writing them"
echo "    - threads (the real guest runs several; these rungs are single)"
