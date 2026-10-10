# padslot.sh - SOURCED, never run. Which processes belong to THIS rig slot.
#
# Split out of padpath.sh so the scripts that deliberately do not source
# padpath.sh (loadgame.sh, savegame.sh and slots.sh take their rootfs from the
# running guest, and padpath would export a guess over it) can still ask the
# slot question. padpath.sh sources this; nothing here sets a path.
# PAD_SLOT is read, never defaulted into the environment.

# ---- RIG SLOTS: WHICH PROCESSES ARE THIS SLOT'S --------------------------
#
# Every pgrep/pkill in this rig used to mean "on this machine". With slots it
# has to mean "in this slot", or one session's Stop kills another session's
# guest - the collision the single rig lock was there to prevent by making
# everyone wait. PAD_SLOT is exported at the top of this file, so it is in the
# environment of every process a run starts, the guest included; these read it
# back.
#
# UNREADABLE MEANS ANOTHER ACCOUNT'S PROCESS. /proc/<pid>/environ is 0400 to
# the process's owner, so a check run as the desktop user cannot read the
# environment of a run started as root (the app's runs, every PAD_PIVOT run).
# Such a process is reported as "?" and belongs to SLOT 0 - which keeps a
# machine that never uses slots exactly as it was: a status check run as the
# user must go on seeing the root run it started. A slot >= 1 check never
# counts one; run the check as root (`wsl -u root`) for an exact answer when
# slots are in use - the Windows app's status poll does (PAD-496: run as the
# user, it read a session's game on rig 1 as rig 0's and offered David only
# Stop). It could never kill one anyway: a user cannot signal root's
# processes, which was already true before slots.
#
# GONE IS NOT UNREADABLE, and the difference was measured the first time two
# slots ran: watch.sh forks a short-lived subshell several times a second, its
# command line is watch.sh's, so pgrep lists it - and by the time its
# environment is read it has exited. Reported as "?", every such fork counted
# as a SLOT 0 run script, and a slot 0 check read two phantom runs with two
# other slots up. A process that is gone prints "-" and belongs to no one.
pad_slot_of() {                   # <pid>  -> the slot number, "?" or "-"
    local v
    # 2>/dev/null BEFORE the <: redirections apply left to right, and a failed
    # open is the redirect's error, not tr's.
    if ! v=$(tr '\0' '\n' 2>/dev/null < "/proc/$1/environ"); then
        [ -d "/proc/$1" ] && echo '?' || echo '-'
        return 0
    fi
    # A process that exited mid-read leaves an empty, "successful" read.
    [ -n "$v" ] || [ -d "/proc/$1" ] || { echo '-'; return 0; }
    v=$(printf '%s\n' "$v" | sed -n 's/^PAD_SLOT=//p' | head -1)
    case "$v" in ''|*[!0-9]*) v=0 ;; esac
    echo "$((10#$v))"
}

#: pgrep, restricted to THIS slot. Takes pgrep's matching arguments (not -c).
pad_pids() {
    local p s mine=${PAD_SLOT:-0}
    for p in $(pgrep "$@" 2>/dev/null); do
        [ "$p" = "$$" ] && continue
        s=$(pad_slot_of "$p")
        if [ "$s" = "$mine" ] || { [ "$s" = '?' ] && [ "$mine" = 0 ]; }; then
            echo "$p"
        fi
    done
}

#: `pgrep -c`, restricted to this slot. Always prints a number.
pad_count() {
    local n
    n=$(pad_pids "$@" | wc -l)
    echo "$((n + 0))"
}

#: `pkill -<SIG> <pgrep args>`, restricted to this slot. Returns 0 when it
#: signalled something, 1 when nothing matched - pkill's own contract.
pad_pkill() {                     # -<SIG> <pgrep args...>
    local sig=$1 p
    shift
    p=$(pad_pids "$@")
    [ -n "$p" ] || return 1
    # shellcheck disable=SC2086
    kill "$sig" $p 2>/dev/null
    return 0
}

