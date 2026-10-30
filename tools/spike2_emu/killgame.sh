#!/bin/bash
# killgame.sh - emergency stop. Kills every emulated game process.
#
# Run this any time WSL / vmmemWSL is burning CPU. Orphaned game processes spin
# at ~140% CPU each and never exit on their own, because the game installs its
# own SIGINT/SIGTERM handler (0x1b4f0) and ignores polite signals. SIGKILL only.
#
#   wsl -e bash $RIG/killgame.sh
#
# Note: vmmemWSL itself can NOT be killed from Task Manager - it is the WSL VM's
# memory process and Windows denies access. Kill the guest processes (this
# script) or shut the whole VM down with `wsl --shutdown` from Windows.
#
# ** INSIDE WSL, and this script now enforces it. ** Run from Git Bash on
# Windows it fails on the first pkill ("command not found") and then prints
#   killed 0; still running: 0
# which reads exactly like success, because the "still running" half asks
# alive.sh, whose pgrep sees only Windows processes there. 2026-08-06 that pair
# of confident zeros led to a second full run being started on top of a live
# one. Same /proc test as alive.sh, same reason: refuse rather than reassure.
. "$(dirname "$0")/padpath.sh"
if [ ! -d /proc/1 ] || ! grep -qs . /proc/1/comm 2>/dev/null; then
    echo "killgame.sh: this is not a Linux shell - nothing here can see the rig." >&2
    echo "  Run it inside WSL:  wsl -e bash \$0" >&2
    exit 2
fi
# THE LEASE (riglock.sh): a Stop on a slot another session is using now would
# end ITS run - refused; ours, or free, and the Stop goes ahead.
pad_slot_use stop || exit 1
#
# THE COUNTING LIVES IN alive.sh, NOT HERE. This script used to keep its own
# copy of the process list, and the two drifted: alive.sh grew the audio player
# and this one did not, then BOTH missed the Windows-interop stubs and the card
# mounts, and a machine with seven leaked stubs on it reported "clean". One list,
# one place. If you add something to the rig, add it to alive.sh.
SELF=$(cd "$(dirname "$0")" && pwd)
total() { bash "$SELF/alive.sh" --total; }

before=$(total)
echo "rig processes running: $before"
[ "$before" -gt 0 ] && bash "$SELF/alive.sh" | sed -n '/--- what is still up ---/,$p'

# ★ THE GUEST'S PID-NAMESPACE INIT GOES FIRST (item 90), AND IT IS NOT THE
# unshare WRAPPER. run_game.sh starts the guest as
#     unshare $USERNS -m -p -f [setsid] bash -s "$R" ...
# and unshare itself stays in OUR pid namespace - measured, 2026-09-02:
# /proc/<unshare>/ns/pid is this shell's, and killing it does not kill anything
# inside. The bash it forks is PID 1 in the NEW namespace (`NSpid: 42142 1`),
# and that bash is the whole second half of run_game.sh: the big INNER heredoc.
# It is still a shell for as long as the boot selector's menu is up. Only at
# the foot of that script does it exec the game, which is why every other
# teardown here has been able to treat comm=game as "the guest".
#
# A STOP WITH THE MENU UP USED TO START A GAME. `pkill -9 -x codeselect` below
# reads, inside that script, as "the selector exited 137" - and the selector's
# exit status is what it takes for the CHOICE - so it printed
# "[select] fallback: primary" and fell through to the exec. Measured in the
# app's own launch shape (root, PAD_PIVOT, three-image card): the sweep killed
# 17 processes and PID 42142 - the `bash -s` above - came back a moment later
# as `game /.padqemu/game ./game`, a BRAND NEW guest, started by the very stop
# that was meant to end the run. The count then said "still running: 2",
# STILL NOT CLEAN, and the app offered to restart WSL over a game it had just
# started itself.
#
# Killing the namespace's init first shuts that door for the whole class and
# not for one shape of it: the kernel SIGKILLs every member of a PID namespace
# whose init dies, so nothing in there can outlive this sweep or start
# anything after it, whatever the inner script was in the middle of. The
# unshare wrapper is deliberately NOT this kill - it is outside the namespace,
# and it is killed further down with the other run scripts, which is what
# releases its -m namespace's hold on the card mounts.
#
# THE PATTERN IS EXACT. `bash -s` is invoked in exactly one place in this rig
# (run_game.sh's INNER heredoc) and $ROOT pins it to this rootfs, so it cannot
# match an ordinary shell that merely mentions the path. Both launch shapes
# match: a root PAD_PIVOT run's `setsid` EXECs that bash rather than forking it
# (measured - NSpid says the bash itself is PID 1), so argv[0] is `bash`
# either way, and the optional `setsid ` covers a machine whose setsid forks.
# A NON-SELECT RUN IS UNCHANGED BY THIS: by the time its guest is up this same
# PID has already exec'd the game, its command line is the game's and not a
# shell's, and the next line is what ends it - the same process, the same
# signal, in the same order as before.
pad_pkill -9 -f "^(setsid )?bash -s $ROOT "
pad_pkill -9 -x game
pad_pkill -9 -f 'arm-binfmt|qemu-arm'
# The boot selector (item 90): the ARM menu run_game.sh runs BEFORE the game
# on a PAD_SELECT run. Under WSL the binfmt pattern above already reaches it;
# in the macOS container only its comm does. alive.sh counts it.
pad_pkill -9 -x codeselect
pad_pkill -9 -x padglhost
pad_pkill -9 -f nodebus.py
pad_pkill -9 -f 'autoattract.sh'
# The ball feeder (item 21b). It exits on its own when dump/padled goes away,
# but that file is removed further down this script, so leaving it to notice
# would mean a few seconds of a helper still driving trough switches after a
# stop was asked for. alive.sh counts it.
pad_pkill -9 -f 'ballfeed[.]py'
# PAD-204's root pause keeper. alive.sh counts it.
pad_pkill -9 -f 'pausekeep[.]py'
# The background table builder watch.sh starts on a title that already
# has artwork. It waits in a poll loop for the guest's switch table, so
# it outlives a run that ends first. alive.sh counts it.
pad_pkill -9 -f 'mktables[.]py'
# The switch exerciser (item 59), both halves. The shell half sleeps in a poll
# loop for the guest's switch table and would outlive a run that ends first;
# the python half drives ~44 switch ids over ~10 s, so a stop asked for mid
# exercise must not leave it pressing switches into whatever runs next. Killed
# BEFORE the shell half's own `up()` check could notice, deliberately - the
# same argument as the ball feeder above. alive.sh counts both.
pad_pkill -9 -f 'swexercise[.]sh'
pad_pkill -9 -f 'swexercise[.]py'
# The event feed. An orphaned `tail -F` never exits by itself.
#
# $PAD_HOME AND NOT $HOME, and padpath.sh's own header carries the full story:
# this script is normally run as ROOT (the app stops a run with `wsl.exe -u
# root`), so $HOME is /root and this pattern used to match nothing at all. The
# feed survived every stop, alive.sh went on counting it, and the run never
# read as clean.
pad_pkill -9 -f "^tail -q -n 0 -F $PAD_LOGDIR/padvid\.log"
# The awk on the other end of that pipe is NOT killed here on purpose: it reads
# the tail's stdout, so it takes EOF and leaves by itself the moment the tail
# above dies. It only ever survived because the tail did.
#
# The PIVOT run's game-log tail, which alive.sh has always counted and this
# script never killed - so a pivot run (every run the app starts) could not
# reach zero by stopping it. Same shape as the feed above: an orphaned `tail -F`
# holds the file forever and never exits on its own.
pad_pkill -9 -f '^tail -F .*dump/game\.out'
pad_pkill -9 -f 'padvidhost\.py'
pad_pkill -9 -f 'playaudio.sh'
# ^-anchored, and matched on the fifo not on '-f pulse': a severed player
# command line (see playaudio.sh) had no pulse output yet still held the fifo.
pad_pkill -9 -f '^ffmpeg .*audio\.fifo'
# The Windows-sink relay, and the native player when there is no bridge.
# Killing the relay also ends the run's audio for the Windows player, which sees
# EOF on the socket and leaves on its own - the kernel closes the socket even
# when this is a SIGKILL.
pad_pkill -9 -f 'padrelay\.py'
pad_pkill -9 -f 'padplay\.py'
# The virtual playfield is a WINDOWS process reached through interop; its
# WSL-side stub is what is visible here. Removing the LED block below is the
# POLITE close (playfield.py notices and leaves, which is also how it saves its
# window position), so give that a moment before killing the stub - but do kill
# it, because measured reality is that a stub whose interop Relay has died sits
# in poll() forever with no Windows process behind it. Seven had accumulated,
# oldest 2.5 h, while alive.sh said the machine was clean.
#
# The run scripts go before the wait so nothing restarts under us.
# run_game.sh is in this list as of 2026-08-09, and so is the unshare wrapper
# it starts, because neither was and the stop path wedged on exactly that:
# killing the guest is supposed to make unshare reap it and exit, taking
# run_game.sh's bash with it - and twice in one afternoon it did not. The
# dead guest sat as a `[game] <defunct>` under a live unshare for half an
# hour, pgrep -x game still counted it, so the app's button said Stop, Stop
# killed nothing, and the card mounts could not unmount either - the wedged
# unshare's OWN mount namespace (-m) still held a reference to every fuse
# mount, so fusermount's detach never reached fuse2fs. Kill the wrapper and
# all of that unwinds: the zombie reparents to init, init reaps it, and the
# mount reference dies with the namespace. The pattern is run_game.sh's exact
# shape (`unshare $USERNS -m -p -f ...`, -r absent for a root PIVOT run);
# restorestate.sh's `unshare -m bash` is deliberately NOT matched.
# cardmount.sh joined the list at item 74: its sync cache_wait can be looping
# for minutes under a boot, holding watch.sh's merged output pipe - a Stop
# that leaves it running keeps wsl.exe from reaching EOF, so the GUI sat out
# its full 20 s wait timeout on every mid-copy Stop. The DETACHED copier is
# deliberately not matched: it survives a Stop on purpose, so the copy is not
# lost, and its output goes to the cardcache log, not the pipe. So is a
# library sweep's copier (cardmount.sh --cache-now): it has no slot, and a
# Stop on rig 0 took it for its own (PAD-632, padslot.sh).
_rs=$(pad_run_script_pids)
# shellcheck disable=SC2086
[ -n "$_rs" ] && kill -9 $_rs 2>/dev/null
pad_pkill -9 -f '^unshare (-r )?-m -p -f'
# longplay.sh is started BESIDE a run rather than by one, so it is not in the
# group above - and watch.sh's own teardown was the only thing that ever killed
# it. Anything that stops a run through THIS script (abrun.ps1 does) would
# otherwise leave it poking ramp optos into the next run. alive.sh already
# counts it, so the leak was visible, but visible is not the same as fixed.
# Anchored exactly as watch.sh and alive.sh anchor it: an unanchored
# 'longplay.sh' matches any shell with the name on its command line, and this
# one KILLS.
pad_pkill -9 -f '^bash [^ ]*longplay\.sh'
# PAD-764: THE RUN'S RECORDING GETS ITS SWITCH LOG HERE, for the same reason
# the LCD block is kept below: Stop and app-quit come through this script, and
# the kills above take watch.sh down before its teardown could write it. The
# guest is gone, so the log is whole (runrec.py; once only, so a teardown that
# did run first leaves nothing to do).
[ "${PAD_RECORD:-1}" != 0 ] && command -v python3 >/dev/null 2>&1 \
    && python3 "$(dirname "$0")/runrec.py" finish "$PAD_LOGDIR" 2>&1
# The LED block doubles as the virtual playfield's liveness signal; removing
# it lets that window close itself instead of surviving the kill.
rm -f "$ROOT/dump/padled"
# The LCD block is PRESERVED before it is removed (item 83), exactly as
# watch.sh's own teardown does - and this copy matters MORE than that one,
# because Stop and app-quit come through here, and the pkills above take
# watch.sh down before its teardown can run. The first run after the ring
# existed ended through this line and lost its transcript, which was the
# ring's whole reason to exist. lcdring.py reads the copy. -s, not -f: a
# title with no lcdnode leaves the block all-zero, and clobbering a real
# padlcd.last with an empty page would erase the last lcdnode run's
# evidence every time some OTHER title is stopped.
[ -s "$ROOT/dump/padlcd" ] && head -c 4 "$ROOT/dump/padlcd" | grep -q PLCD \
    && cp -f "$ROOT/dump/padlcd" "$ROOT/dump/padlcd.last" 2>/dev/null
rm -f "$ROOT/dump/padlcd"
for _ in 1 2 3 4 5 6; do
    [ -n "$(pad_pids -f '^(/init|python3?) .*playfield\.py')" ] || break
    sleep 0.5
done
pad_pkill -9 -f '^(/init|python3?) .*playfield\.py'
# BACKSTOPS for Windows children that did not take the hint. Matched on the
# SCRIPT (and, for the player, the PORT), never on the image name alone: killing
# every python.exe would take out whatever else the user is running, and the
# version of this that matched ffplay.exe would have killed PAD's own audio
# preview.
#
# `Name -like 'python*'` is NOT decoration - it is the Windows-side version of
# the self-match trap this rig already knows from pgrep. This very command line
# CONTAINS the string '*spike2_emu\playfield.py*', so a CommandLine-only filter
# matches the powershell.exe running the query and Stop-Process shoots itself
# mid-pipeline. Requiring a python interpreter excludes it by construction.
#
# RIG SLOTS: a Windows process has no PAD_SLOT anyone here can read, so the
# slot is on its COMMAND LINE. The player's is its port (45997 + slot); the
# playfield of a slot >= 1 carries `--pad-slot=N` (watch.sh adds it), and slot
# 0's is the one WITHOUT that marker - so neither Stop reaches the other's.
_port=${PAD_AUDIO_PORT:-45997}
if [ "$PAD_SLOT" = 0 ]; then
    _pfslot="-notlike '*--pad-slot=*'"
else
    _pfslot="-like '*--pad-slot=$PAD_SLOT*'"
fi
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command \
  "Get-CimInstance Win32_Process |
   Where-Object { \$_.Name -like 'python*' -and
                  ((\$_.CommandLine -like '*padplay.py*' -and
                    \$_.CommandLine -like '* $_port *') -or
                   (\$_.CommandLine -like '*spike2_emu\playfield.py*' -and
                    \$_.CommandLine $_pfslot)) } |
   ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1

# ZOMBIE HOLDERS the patterns above did not know. A rig zombie cannot be
# killed, only reaped, and its holder is whatever process is refusing to do
# that - so the generic move is to kill the HOLDER and let init reap the
# orphan. The unshare kill above is this same move for the one shape that has
# actually wedged; this loop is the backstop for the next shape, so a future
# holder nobody enumerated does not bring back the frozen-Stop wedge. Two
# holders are left alone: an interop Relay//init (SIGKILL from inside the VM
# does not work on it - measured; that case falls through to the wsl
# --shutdown report below), and anything on a real tty, because a zombie
# under an INTERACTIVE shell means someone's terminal, and killing a user's
# shell to tidy a zombie is a worse trade than reporting it.
ps -eo pid=,ppid=,stat=,comm= 2>/dev/null \
  | awk '$3 ~ /^Z/ && $4 ~ /^(game|padglhost|fuse2fs|ffmpeg|pythonw\.exe|python3?)$/ {print $2}' \
  | sort -u | while read -r hp; do
    [ -z "$hp" ] || [ "$hp" -le 1 ] && continue
    hcomm=$(ps -o comm= -p "$hp" 2>/dev/null)
    hargs=$(ps -o args= -p "$hp" 2>/dev/null)
    htty=$(ps -o tty= -p "$hp" 2>/dev/null | tr -d ' ')
    case "$hcomm" in ''|init|Relay*) continue ;; esac
    case "$hargs" in /init*) continue ;; esac
    [ "$htty" = "?" ] || continue
    # Only a holder in THIS slot: another slot's wedged wrapper is its own
    # Stop's business, and killing it would end that slot's run.
    _hs=$(pad_slot_of "$hp")
    [ "$_hs" = "$PAD_SLOT" ] || { [ "$_hs" = '?' ] && [ "$PAD_SLOT" = 0 ]; } || continue
    echo "killing $hp ($hcomm): it is holding a dead rig process instead of reaping it"
    kill -9 "$hp" 2>/dev/null
done
# Give init a beat to reap the orphans before the mounts are tried: a freed
# mount-namespace reference is what lets the unmount below actually work.
sleep 1

# CARD MOUNTS. cardmount.sh setsid's fuse2fs deliberately - a run's process-group
# kill used to take the mount out from under the game it had just started, and
# the game then sat at "Startup In Progress" forever with every read failing and
# no error printed anywhere - so nothing in any teardown has ever reached them.
# Three were found orphaned in one session. Unmounting is safe here BECAUSE this
# script has just killed everything that could have been reading one, and the
# expensive part (the local image cache under ~/cardcache) is a file that
# survives: a remount is a fraction of a second.
#
# $PAD_HOME, NOT $HOME: as root this globbed /root/card/*/, matched nothing, and
# the loop did nothing at all - silently, because a glob that matches nothing is
# not an error. The card stayed mounted after every stop the app made.
#
# UNMOUNT, NEVER KILL, and the ordering above is what makes that possible. A
# fuse mount is a kernel mount plus a userspace daemon; `fusermount -u` retires
# both together, but SIGKILLing fuse2fs leaves the kernel half behind with
# nothing serving it. Every access then fails ENOTCONN ("Transport endpoint is
# not connected"), including the mkdir watch.sh does before mounting - so the
# next run cannot start at all, and the error names a transport nobody in this
# rig has ever configured. If a mount here will not go, report it; do not reach
# for kill.
#
# FROM /proc/self/mounts, NOT A GLOB OVER $PAD_CARDS (item 96). A card an
# ordinary user mounted has no allow_other - cardmount.sh adds it for root
# only, and /etc/fuse.conf leaves user_allow_other off - so FUSE refuses
# everyone else, root included: the glob's `*/` could not stat the mountpoint,
# matched nothing, and the whole pass was skipped, leaving "still running: 2"
# and a WSL restart. The kernel's own list names every mount whatever its
# permissions, and it is the source cardmount.sh's stale-mount test already
# trusts. The path field is octal-escaped: a space is \040, a tab \011, a
# backslash \134 (unescaped last, so an escaped backslash cannot start a
# second escape). Only mounts DIRECTLY under the card folder, as the glob had.
card_mounts() {
    local p
    p=$(readlink -f "$PAD_CARDS" 2>/dev/null) || p=$PAD_CARDS
    awk -v p="${p%/}/" '{
        m = $2
        gsub(/\\040/, " ", m); gsub(/\\011/, "\t", m); gsub(/\\134/, "\\", m)
        if (index(m, p) == 1) {
            r = substr(m, length(p) + 1)
            if (r != "" && r !~ /\//) print m
        }
    }' "${1:-/proc/self/mounts}" | sort -u
}
while IFS= read -r m; do
    if fusermount -u "$m" 2>/dev/null || fusermount3 -u "$m" 2>/dev/null \
       || umount "$m" 2>/dev/null; then
        rmdir "$m" 2>/dev/null
        echo "unmounted card $m"
    else
        echo "COULD NOT UNMOUNT $m - leave it mounted rather than killing fuse2fs;" >&2
        echo "  a killed daemon wedges the mountpoint and the next run cannot start." >&2
    fi
done < <(card_mounts)
# A CARD MOUNTED IN A RUN'S OWN USER NAMESPACE (PAD-872: a container without
# SYS_ADMIN) is not in /proc/self/mounts out here, and fusermount out here
# cannot reach it. fuse2fs can: it was started in that namespace holding its
# capabilities, and on SIGTERM it leaves its loop and unmounts itself - the
# whole mount, kernel half and daemon, the same as fusermount -u (measured:
# the namespace, still held open by the hidden run's Xvfb, lists no card
# afterwards). TERM and not KILL, for the reason above. The sweep has
# already killed everything of the run that could be reading it.
_myns=$(readlink /proc/self/ns/mnt 2>/dev/null)
_cards=$(readlink -f "$PAD_CARDS" 2>/dev/null) || _cards=$PAD_CARDS
for _fp in $(pad_pids -x fuse2fs); do
    _ns=$(readlink "/proc/$_fp/ns/mnt" 2>/dev/null) || continue
    [ -n "$_ns" ] && [ "$_ns" != "$_myns" ] || continue
    _m=$(tr '\0' '\n' < "/proc/$_fp/cmdline" 2>/dev/null | grep -m1 "^${_cards%/}/[^/]*$") || continue
    kill -TERM "$_fp" 2>/dev/null || continue
    for _ in 1 2 3 4 5 6 7 8 9 10; do [ -d "/proc/$_fp" ] || break; sleep 0.2; done
    if [ -d "/proc/$_fp" ]; then
        echo "COULD NOT UNMOUNT $_m - its fuse2fs ($_fp, in the run's own namespace) did not stop" >&2
    else
        rmdir "$_m" 2>/dev/null
        echo "unmounted card $_m (in the run's own namespace)"
    fi
done
sleep 1

# The board's run record (riglock.sh list, the app, the triage dashboard) says
# a run is up in this slot; watch.sh's own teardown removes it, but the kills
# above take watch.sh down first.
rm -f "$(pad_board_dir)/slot-$PAD_SLOT.run" 2>/dev/null

after=$(total)
echo "killed $((before - after)); still running: $after"
echo "load average: $(cut -d' ' -f1-3 /proc/loadavg)"

# ★ A SURVIVOR IS NOT ALWAYS SOMETHING THAT CAN BE KILLED, and reporting a bare
# number while that is true is how this script sent someone hunting for a signal
# that does not exist. A zombie is already dead; it needs REAPING, by its parent.
# When the parent is a WSL interop relay (comm 'Relay(NNN)' or 'init', argv
# '/init'), that parent ignores SIGKILL from inside the VM - measured, against a
# `[game] <defunct>` left by a closed window. No amount of pkill clears it.
#
# FILTERED TO RIG PROCESSES, because the unfiltered version cries wolf: WSL
# leaves a `[SessionLeader] <defunct>` under /init after ordinary session exits,
# and printing "the only cure is wsl --shutdown" over that noise is how a real
# warning gets trained out of a human. Same comm list as alive.sh.
Z=$(ps -eo pid,ppid,stat,comm --no-headers 2>/dev/null \
    | awk '$3 ~ /^Z/ && $4 ~ /^(game|padglhost|fuse2fs|ffmpeg|pythonw\.exe|python3?)$/')
if [ -n "$Z" ]; then
    echo "--- zombies (already dead; they need reaping, not killing) ---"
    echo "$Z" | while read -r zpid zppid _ zcomm; do
        pcomm=$(ps -o comm= -p "$zppid" 2>/dev/null)
        pargs=$(ps -o args= -p "$zppid" 2>/dev/null)
        echo "  $zpid [$zcomm] held by $zppid ($pcomm)"
        case "$pcomm$pargs" in
            *Relay*|*/init*)
                echo "  ^ that parent is a WSL INTEROP RELAY. It ignores SIGKILL from"
                echo "    inside the VM, so this zombie can NOT be cleared from here."
                echo "    The only cure, from Windows:   wsl --shutdown" ;;
        esac
    done
fi

if [ "$after" -ne 0 ]; then
    echo "STILL NOT CLEAN - run alive.sh to see what survived"
    # THE LINE THE APP ACTS ON. Anything still standing at this point has
    # already beaten SIGKILL, a holder sweep and an unmount pass, and from
    # inside the VM there is no stronger move - but from Windows there is,
    # and it cures every case at once. Emitted only on WSL: it is the one
    # platform where the cure exists, and the Emulate tab's Stop watches for
    # this exact token and offers to run it. Before this line existed the
    # wedge was a locked room: the leftovers kept `procs` nonzero, nonzero
    # procs kept the button on Stop AND greyed out "Restart WSL...", and the
    # user was left with two dead controls and a log that knew the answer.
    # IS_WSL is padpath.sh's, sourced at the top - the one WSL test.
    if [ "${IS_WSL:-0}" = 1 ]; then
        echo "PAD_STOP_NEEDS_WSL_RESTART: $after leftover(s) cannot be cleared from inside WSL"
    fi
fi
