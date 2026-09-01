#!/bin/bash
# Which of the running processes belong to THIS rig — one definition, used by
# status.sh, stop.sh and s1restorestate.sh.
#
#   s1own.sh game        the pid of every guest THIS rig is running
#   s1own.sh nodebus     the pid of this rig's node-bus responder
#
# Ordinary-user safe (reads /proc, signals nothing) and prints pids, one per
# line, or nothing.
#
# WHY THIS EXISTS.  `comm` is the guest's one stable identity — binfmt keeps
# qemu off the command line, and a pivoted or criu-restored guest shows
# `/.padqemu/game` (status.sh's header has the long version) — but comm=game
# is NOT UNIQUE ON THIS MACHINE.  The Spike 2 rig names its guest exactly the
# same way on purpose: run_game.sh copies qemu to `.padqemu/game` "so comm
# stays game", and its alive.sh counts `pgrep -x game`.  So `pgrep -x game`
# answers "SOME rig is running a game", which is not the question either
# caller is asking, and answering it cost:
#
#   * PAD-98, the report: a Spike 2 game made the Spike 1 tab believe its own
#     game was up, so it opened the DMD and switch windows over the top of it;
#   * and worse, silently: on app quit that same belief ran THIS rig's stop.sh,
#     whose `pkill -KILL -x game` then killed the Spike 2 run.
#
# WHAT SEPARATES THE TWO GUESTS: the mounts they run on.  This rig binds its
# own work dir into the guest — `$S1_WORK/rootfs` as the new root under
# S1_PIVOT, the extracted game dir at `/games/<TITLE>` and the staged cpuinfo
# under the chroot boot — and those SOURCE paths are in /proc/<pid>/mountinfo.
#
# Why mountinfo and not something more obvious:
#   * /proc/<pid>/root, cwd and environ would say it directly, but they need
#     ptrace permission on a root-owned guest and status.sh runs as the
#     ordinary user (measured: readlink /proc/1/root fails as david, reading
#     /proc/1/mountinfo does not — and mountinfo is readable across a mount
#     namespace too, checked against an `unshare -m` root process).
#   * the ancestry chain would work for a booted guest but NOT for a restored
#     one: criu restores detached, so it has no ancestor of ours at all.
#   * the cmdline cannot tell them apart: under pivot BOTH rigs' guests read
#     `/.padqemu/game ./game`.
set -u
: "${S1_DESKTOP_USER:=$(getent passwd 1000 2>/dev/null | cut -d: -f1)}"
: "${S1_WORK:=/home/${S1_DESKTOP_USER:-david}/s1emu}"
# mountinfo carries resolved paths, and $S1_WORK/game is a symlink into the
# extraction cache, so compare against the canonical work dir.
W=$(readlink -f "$S1_WORK" 2>/dev/null); : "${W:=$S1_WORK}"

case "${1:-game}" in
game)
    for pid in $(pgrep -x game 2>/dev/null); do
        if mi=$(cat "/proc/$pid/mountinfo" 2>/dev/null); then
            case "$mi" in *"$W/"*) echo "$pid" ;; esac
        elif [ -d "/proc/$pid" ]; then
            # The pid is alive but its mountinfo could not be read at all (a
            # kernel that restricts it — not seen on WSL, where this was
            # measured).  Claiming it is the OLD behaviour: ambiguous, never
            # worse.  A pid that simply exited lands in neither branch.
            echo "$pid"
        fi
    done
    ;;
nodebus)
    # The responder is this rig's own script, so the PATH is the identity:
    # the Spike 2 rig has a nodebus.py too and `pgrep -f nodebus.py` matched
    # both.  Kept loose about the interpreter (an absolute python is fine) and
    # tight about the directory.
    #
    # ^-ANCHORED, per alive.sh's rule that every -f pattern is anchored or
    # comm-exact: unanchored, this matched a SHELL that merely had the command
    # in its command line (measured while testing this very script — a
    # `bash -c "… python3 …/spike1_emu/nodebus.py …"` counted as a responder).
    pgrep -f "^[^ ]*python[0-9.]* .*/spike1_emu/nodebus\.py" 2>/dev/null
    ;;
*)
    echo "usage: $(basename "$0") game|nodebus" >&2
    exit 2
    ;;
esac
exit 0
