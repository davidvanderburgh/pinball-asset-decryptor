#!/bin/bash
# watch.sh [minutes] - WATCH the emulated game in a real window.
#
#   wsl -e bash $RIG/watch.sh
#
# Opens a window on the Windows desktop (via WSLg) showing Godzilla Pro running
# under emulation at 60 fps on the GPU. Close the window to stop everything.
#
# WHY THIS SCRIPT EXISTS SEPARATELY FROM runbridge.sh: runbridge.sh is built for
# timed measurement runs - it sleeps for N seconds and then kills. Watching needs
# the opposite: run until the human says stop. The stop signal here is the window
# closing, which padglhost turns into its normal SIGINT-equivalent shutdown.
#
# SAFETY, which matters more here than anywhere else in the rig because this is
# the one script meant to be run by hand and left running:
#   - orphaned guests spin at ~140% CPU forever and ignore polite signals, so
#     every exit path below ends in SIGKILL and then VERIFIES with alive.sh.
#   - the trap covers Ctrl-C, SIGTERM, the window closing, the host dying, and
#     the guest dying. Previously Ctrl-C leaked both processes, because both are
#     setsid'd into their own sessions and the script sat in `sleep`.
#   - a wall-clock cap still applies (default 30 min) as a backstop, so a
#     forgotten window cannot burn a core all night. Pass minutes to change it,
#     or 0 for no cap.
#   - `timeout` is deliberately NOT used anywhere: it signals only its direct
#     child, which here is a setsid wrapper, so the guest survives it.
set -u
. "$(dirname "$0")/padpath.sh"
. "$(dirname "$0")/ensurebuild.sh"
cd "$HOME"

# ---- WHAT RUNS IS BUILT, AND BUILT FROM THESE SOURCES ----------------------
#
# Both of these used to be assumed. The shim was rebuilt here from v0.113.0 and
# the renderer was not checked at all, which is how a user got
# `env: './padglhost': No such file or directory` ten seconds after Start said
# "Starting...". ensurebuild.sh holds the whole rule and the reasoning; it is
# sourced rather than copied so runbridge.sh gets the same answer.
#
# MISSING blocks the start, STALE never does. What is already built still runs
# the game, so a machine that cannot rebuild keeps its emulator; but a binary
# that was never built means no hardware or no picture at all, and starting the
# guest anyway just leaves a 140%-CPU process to kill.
#
# AND THAT IT RUNS. "The guest filesystem is there" and "a program can be
# started inside it" are different questions, and a user whose rootfs answered
# yes to the first and no to the second got `chroot: failed to run command
# '/bin/sh': No such file or directory` and then sixty seconds of waiting for a
# game that had already died. Asked BEFORE the shim and the renderer, because
# both build into a filesystem that has to work first.
pad_ensure_rootfs || exit 1
pad_ensure_guest_exec || exit 1
pad_ensure_shim || exit 1
pad_ensure_bridge || exit 1

MINS=${1:-30}
LOG=${LOG:-$HOME/gzwatch.log}
# FAIL NOW if it cannot be written, not at the game start 400 lines down. A bad
# LOG used to surface as one bash "No such file or directory" over a run that
# then looked normal forever: the start's `> "$LOG"` redirect failed, so the
# game simply never ran. macOS hit exactly this with a WSL home path handed
# into the container. `>>` on purpose - this is a writability probe, and the
# truncation stays where it always was, at the game start itself.
: >> "$LOG" || { echo "[watch] LOG=$LOG is not writable here - nothing would start. Fix or unset LOG." >&2; exit 1; }
HOSTLOG=$HOME/padglhost.log
# The virtual playfield's own log, on the same rule as autoattract's and the
# ball feeder's: a helper that is started in the background writes somewhere a
# human can read afterwards. This one was the exception - both its streams went
# to /dev/null - and that is why "the playfield window never appeared" has never
# had an answer in any log on any machine (2026-08-11, james_bond_pro).
PFLOG=$HOME/padplayfield.log
RING_HOST=$ROOT/dump/padgl
RING_GUEST=/dump/padgl
# The keyboard channel. Same host-path/guest-path split as the GL ring: the
# native renderer owns the window and so is the only thing that can see a key,
# the shim inside the emulated game is the only thing that can press a switch.
SW_HOST=$ROOT/dump/padsw
# Live LED state (padled.h): the shim decodes the insert boards' per-LED writes
# and publishes them here, so the virtual playfield needs no log and no
# PAD_NB_LOG - raising that quadruples the boot.
LED_HOST=$ROOT/dump/padled
LED_GUEST=/dump/padled
SW_GUEST=/dump/padsw
# Audio: the guest writes PCM into a FIFO, a native ffmpeg drains it into WSLg's
# PulseAudio. Same host-path/guest-path split as the GL ring and the keyboard.
# PAD_AUDIO=0 turns it off.
AUD_HOST=$ROOT/dump/audio.fifo
AUD_GUEST=/dump/audio.fifo
AUD_FMT_HOST=$ROOT/dump/audio.fmt
AUD_FMT_GUEST=/dump/audio.fmt
AUD_RATE=${PAD_AUDIO_RATE:-48000}   # fallback only; the guest reports the real one
# Video: the guest has no H.264 decoder at all, so the HOST decodes with ffmpeg
# and publishes raw I420 frames into a shared ring. Same split as the GL bridge
# and the audio player. PAD_VID=0 turns it off.
VID_HOST=$ROOT/dump/padvid
VID_GUEST=/dump/padvid
S=$RIG

export PAD_GL_W=${PAD_GL_W:-1360}
export PAD_GL_H=${PAD_GL_H:-768}
export GALLIUM_DRIVER=${GALLIUM_DRIVER:-d3d12}   # without this Mesa picks llvmpipe

# WHICH GPU, because this machine has two and Mesa picks the wrong one.
#
# Measured 2026-08-06 with gpuprobe, which renders the game's actual workload
# and glFinish()es before it stops the clock:
#     default                              D3D12 (AMD Radeon(TM) Graphics)   1.096 ms/frame
#     MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA  D3D12 (NVIDIA GeForce RTX 5090)  0.026 ms/frame
# The desktop is a 4K 120 Hz display on the RTX 5090; the AMD part is an
# integrated Radeon driving no display at all. So the rig was rendering every
# frame on the iGPU - which has no VRAM and takes its bandwidth out of SYSTEM
# memory, i.e. out of everything else running on the machine - and the result
# then had to cross to the NVIDIA adapter to be shown. That is item 18's
# territory: a cost that no CPU counter can see, which is exactly the shape of
# a machine that "feels sluggish" while every throughput number says it is idle.
#
# A SUBSTRING of the adapter name. Unset leaves Mesa's own choice alone, so
# this changes nothing until it is asked for.
[ -n "${PAD_GL_ADAPTER:-}" ] && export MESA_D3D12_DEFAULT_ADAPTER_NAME="$PAD_GL_ADAPTER"

# WHICH TITLE. PAD_GAME picks it; run_game.sh has the full rule and prints what
# it chose. Everything below that is per-title reads it from here.
# PAD_CARD runs a title straight off its card image with no extraction; the
# title name then comes from the card, so ask cardmount.sh rather than guess.
GAME=${PAD_GAME:-}
# Set below only when THIS run creates the card mount, so teardown unmounts what
# it mounted and leaves a card someone else mounted alone. DECLARED HERE, ABOVE
# the block that sets it: the first version of this initialised it down with the
# other teardown variables, which is BELOW this block, so every card run wiped
# its own answer and quietly left the mount behind. The symptom was the exact
# thing being fixed, which is a good way to waste a run.
CARD_MNT=""
if [ -n "${PAD_CARD:-}" ]; then
    # Keep the WHOLE output, not just the path: it is the only place that says
    # whether this run created the mount or joined one that already existed,
    # and teardown must not unmount a card someone else is using. The [card]
    # lines are republished because $(...) swallows them, and "which image, from
    # the cache or from D:" is worth having in the run log.
    CARD_OUT=$(bash "$S/cardmount.sh" "$PAD_CARD")
    printf '%s\n' "$CARD_OUT" | grep '^\[card\]'
    CARD_PATH=$(printf '%s\n' "$CARD_OUT" | tail -1)
    [ -d "$CARD_PATH" ] || { echo "[watch] could not mount $PAD_CARD" >&2; exit 1; }
    case "$CARD_OUT" in
        *"already mounted"*) CARD_MNT="" ;;
        *)                   CARD_MNT=$(dirname "$CARD_PATH") ;;
    esac
    GAME=$(basename "$CARD_PATH")
    # The video host reads clips itself, outside the chroot, so it needs the
    # card's real path - the title is not under spike2root/games at all.
    export PAD_CARD PAD_VID_ROOT="$CARD_PATH"
elif [ -n "${PAD_GAME_DIR:-}" ]; then
    # A title directory anywhere on disk, bind mounted the same way.
    GAME=$(basename "${PAD_GAME_DIR%/}")
    export PAD_GAME_DIR PAD_VID_ROOT="${PAD_GAME_DIR%/}"
fi
[ -z "$GAME" ] && { GAME=$(readlink "$ROOT/games/game" 2>/dev/null); GAME=${GAME%/game}; }
GAME=${GAME:-godzilla_pro}
export PAD_GAME="$GAME"

# UNPOPULATED NODES ARE PER TITLE, AND ARE NOW DERIVED FROM THE TITLE.
# The shim answers all 64 node addresses, so an absent board looks present, and
# slot 2 is the one board whose "registered" bit is board[+144] != 0 - a
# manufactured node 2 can never be suppressed and sits on Tech Alerts forever.
# Staying silent for it is the accurate behaviour, not a workaround.
#
# THIS USED TO BE `case "$GAME"` WITH ONE ENTRY (godzilla_pro|godzilla_le -> 2),
# so Godzilla cleared its Tech Alerts and every other title sat on one. That is
# what David hit on Jaws: "it got past the initial service screen, but said node
# 2 wasn't registered". The list was never Godzilla-specific in principle - it
# was just the only title anyone had measured - and the answer is in every
# title's own binary, so nodecensus.py reads it there. Same shape as mktables.py:
# derived from the title, nothing committed, nothing to add per title.
#
# It is asked with an EXPLICIT binary path because this runs BEFORE the game
# starts, so `dump/title` does not exist yet and gameinfo would fall back to the
# empty `games/<title>` stub that a card run bind-mounts over later.
#
# A title whose device table cannot be read silences NOTHING, which is the safe
# direction and is exactly what every non-Godzilla title did before: an extra
# board answering is a Tech Alert you can see, whereas silencing a board that IS
# populated loses its devices with no message at all. John Wick LE is the live
# example - it names connector 2a on 288 records, so its node 2 is real and a
# blanket "silence 2" would have cost it 288 devices while looking like a fix.
if [ -n "${CARD_PATH:-}" ]; then GAME_ELF="$CARD_PATH/game"
elif [ -n "${PAD_GAME_DIR:-}" ]; then GAME_ELF="${PAD_GAME_DIR%/}/game"
else GAME_ELF="$ROOT/games/$GAME/game"; fi

# ★ ITEM 51: THE TITLE'S NODE DIRECTORY, DERIVED BEFORE ANYTHING CONSUMES IT.
# Each game ELF statically declares its node ids and board types; nbdir.py
# reads that (validated to reproduce godzilla's measured claims exactly) and
# the shim answers the game's identity requests from the result instead of
# from godzilla's hard-coded table - which is what had star_wars looping
# "UPDATING NODE BOARD RUNTIME 12 / UPDATE FAILED" over attract: nodes
# 10/11/13/15 claimed as firmware-0.1.0 pinnodes it never had. Written
# tmp+mv so a failed derivation cannot half-write the file; failure keeps
# the shim's built-in fallback, which is exactly the pre-item-51 behaviour.
NBID="$PAD_TABLES/$GAME/node_ident.txt"
mkdir -p "$PAD_TABLES/$GAME" 2>/dev/null
if python3 "$RIG/nbdir.py" "$GAME_ELF" --hexdir "${GAME_ELF%/*}" \
        --out "$NBID.tmp" 2>/dev/null && grep -q '^node=' "$NBID.tmp"; then
    mv -f "$NBID.tmp" "$NBID"
    echo "[watch] node identity: $(grep -c '^node=' "$NBID") boards derived" \
         "from $GAME's own node directory"
else
    rm -f "$NBID.tmp" 2>/dev/null
    if [ -f "$NBID" ]; then
        echo "[watch] node identity: derivation failed; keeping the previous" \
             "run's table"
    else
        echo "[watch] node identity: derivation failed; the shim keeps its" \
             "built-in (godzilla) table"
    fi
fi
#
# THE SWITCH LIST IS PASSED TOO, as the fallback for a title whose device table
# cannot be parsed at all. star_wars_le is why: it yields ZERO device records,
# so the census declined and the title kept the fault - David's 2026-08-10
# recording is Star Wars sitting on `Check Node Board 2 : Not Registered`,
# flickering, unplayable. The switch list comes from the shim's own dump on a
# previous run of the title, so it needs no address and no binary parsing.
# nodecensus.silent_nodes() documents exactly how this weaker evidence could be
# wrong and why no known title trips it.
NB_SILENT_DEFAULT=$(python3 "$RIG/nodecensus.py" --elf "$GAME_ELF" \
    --switches "$PAD_TABLES/$GAME/switch_list.txt" \
    --nodedir "$NBID" --silent 2>/dev/null)
export PAD_NB_SILENT=${PAD_NB_SILENT:-$NB_SILENT_DEFAULT}
# WHY, in the run's own log. The item that asked for this asked for the evidence
# as well as the decision, and a silenced board is invisible by construction -
# if it is ever wrong, this line is the only place that will say so.
#
# THE REASON IS ASKED FOR RATHER THAN ASSERTED. The first version of this line
# said "$GAME's own device table names no board there" whatever the evidence
# was, and printed exactly that for star_wars_le - whose device table does not
# read at all, and whose answer came from the switch list. A log line that
# names the wrong source is worse than one that names none, because the whole
# point of printing it is that a silenced board is otherwise invisible.
NB_WHY=$(python3 "$RIG/nodecensus.py" --elf "$GAME_ELF" \
    --switches "$PAD_TABLES/$GAME/switch_list.txt" \
    --nodedir "$NBID" 2>/dev/null \
    | sed -n 's/^because: //p')
if [ -n "${PAD_NB_SILENT:-}" ]; then
    echo "[watch] node census: silencing node(s) $PAD_NB_SILENT on $GAME -" \
         "${NB_WHY:-reason unavailable}"
else
    echo "[watch] node census: silencing nothing on $GAME -" \
         "${NB_WHY:-reason unavailable}"
fi

# ---- A CHECKPOINTABLE BOOT IS AN EXTRA, NOT A CONDITION OF STARTING -------
#
# THE FAULT THIS FIXES, reported 2026-08-11 against star_wars_le and
# iron_maiden_pro, both of which had run on that machine before:
#
#     [run] PAD_PIVOT needs a STATIC busybox at /bin/busybox
#     [watch] the game never started.
#
# Since v0.126.0 the app asks for PAD_PIVOT=1 on EVERY start, because that is
# the only shape criu can dump and the save-state controls are simply on. The
# pivot needs one thing an ordinary boot does not (pad_static_busybox, and see
# there for why), that thing is a package no machine has by default, and it
# was on NO prerequisite list - so the release that added save states took the
# emulator away from everyone who did not happen to have busybox-static.
#
# run_game.sh's answer to a pivot it cannot do is `exit 1`, which is right for
# a run that ASKED for one by hand. Here it is wrong: the boot this rig has
# always done still works perfectly, and losing an extra must not cost the
# whole run. So the request is withdrawn, out loud, and the run continues in
# the shape it had before item 13 existed. Withdrawn HERE, before the cfg dump
# below and before anything reads PAD_PIVOT, so the log names the shape that
# actually ran and the playfield does not offer Save/Load buttons that could
# only fail (see PF_STATES).
#
# THREE PROGRAMS ARE MISSABLE, NOT ONE, and each was found by a different
# user report in the same week. busybox-static (PAD-53) and pivot_root
# (PAD-54) are what the BOOT SHAPE needs; criu is what the boot shape is FOR -
# no Ubuntu publishes it at all, so every save-state script used to default to
# one developer's hand-built copy under /var/tmp. Miss any one and the Save and
# Load buttons appear over something that cannot work.
#
# pad_can_pivot() asks all three (padpath.sh). Which one is missing only
# decides what this SAYS, because the outcome is the same either way: run
# without save states, everything else untouched. Withdrawing is the safe
# direction - PAD-53 and PAD-54 are both the opposite fault, a gate that
# CLEARED a machine the run then refused, and that is what took a user's
# emulator away.
#
# THE REPAIR DIFFERS PER CAUSE, which is the whole reason this names them
# separately: apt fixes two of them and cannot fix the third, so a message that
# guessed would send a third of the users to a package that does not exist.
if [ -n "${PAD_PIVOT:-}" ] && ! pad_can_pivot; then
    echo "[watch] this run cannot be checkpointed, so save states are off:"
    if ! pad_static_busybox; then
        # busybox-static carries a pivot_root applet as well as the static
        # binary, so it repairs BOTH boot-shape halves at once.
        echo "[watch]   no static busybox here, which the boot shape needs"
        echo "[watch]   sudo apt install busybox-static"
    elif ! pad_pivot_root_cmd >/dev/null 2>&1; then
        # busybox IS installed and its applet was not found either, so telling
        # someone to install what they have is worse than saying nothing:
        # /usr/sbin/pivot_root comes from util-linux.
        echo "[watch]   this machine has no pivot_root"
        echo "[watch]   sudo apt install --reinstall util-linux"
    fi
    if ! pad_criu >/dev/null 2>&1; then
        echo "[watch]   there is no criu, which is what freezes the game."
        echo "[watch]   No Ubuntu packages it, so it is built once, from source:"
        echo "[watch]   wsl -u root -e bash $RIG/getcriu.sh"
    fi
    echo "[watch] starting WITHOUT them - nothing else about the run changes."
    unset PAD_PIVOT
fi

# ---- WHAT THIS RUN ACTUALLY IS, in the run's own log ----------------------
#
# REMAINING item 16 (replay a session from its log) was filed believing this
# already existed - "the launch line is logged verbatim with PAD_CARD=". It did
# not: nothing here has ever echoed its own configuration, and PAD_CARD appears
# in zero of the run logs on this disk. So a log recorded the INPUTS and not the
# machine they were delivered to, and replaying one meant remembering by hand
# which card and which flags produced it. The flags are half the experiment in
# this rig - PAD_VID_ALT_SIZE, PAD_SW_LATCH, PAD_NB_SILENT and PAD_COIL_PROBE
# each change what the run IS - and a run log that does not name them cannot be
# reproduced from, only read.
#
# Every PAD_* that is set, one per line so it greps and parses, plus the two
# things that are not environment variables. Values are printed raw: the only
# PAD_* that is ever a path is a card image, which is exactly what a replay
# needs to find again.
echo "[watch] cfg argv=$*"
echo "[watch] cfg GAME=$GAME"
echo "[watch] cfg MINS=$MINS"
# WHICH COPY OF THE RIG IS RUNNING. Not a detail any more: the emulator ships
# with the app, so a development machine has at least two - the installed one
# under Program Files and the repo - and they can differ. A log that does not
# name the one it came from cannot answer "was that the release or my working
# copy?", which is the same lesson as PAD_CARD one line down.
echo "[watch] cfg RIG=$RIG"
# GALLIUM_DRIVER and MESA_* are in here beside the PAD_* set because they
# decide WHICH GPU renders the run, which is as much "what this run IS" as any
# PAD_ flag - and a log that does not name the adapter cannot be replayed or
# compared. That is item 16's lesson applied the moment a second such variable
# appeared, rather than after it had cost a comparison.
for _v in $(set | sed -n 's/^\(PAD_[A-Z0-9_]*\|MESA_[A-Z0-9_]*\|GALLIUM_DRIVER\)=.*/\1/p' | sort -u); do
    eval "_val=\${$_v:-}"
    [ -n "$_val" ] && echo "[watch] cfg $_v=$_val"
done
unset _v _val

# ★ ROOT RUNS THE GUEST; THE DESKTOP USER RUNS EVERYTHING ELSE (item 13).
#
# A checkpointable guest has to be root: `unshare -r`'s unprivileged user
# namespace disables setgroups, and criu cannot restore a process into it
# ("Can't setgroups([7 gids]): -22"). Matching criu's own groups does NOT help,
# because the check happens INSIDE that namespace, where the user's gids are
# not mapped at all. So PAD_PIVOT sessions are launched as root.
#
# But root must NOT run the helpers, and this was measured the hard way: as
# root, padglhost cannot attach to the WSLg X server's shared memory - the log
# fills with "MESA: error: Failed to attach to x11 shm" and THE WINDOW IS
# BLACK - and the ring files come out root-owned, so the playfield says
# "dump/padled not readable". The display, audio and Windows-interop helpers
# all belong to the ordinary desktop user.
#
# So: as root, every helper is dropped back to that user, and the rings are
# created owned by them. The guest still reads and writes those rings because
# root ignores file permissions. Not root (an ordinary run) - nothing changes.
PAD_USER=${PAD_USER:-${SUDO_USER:-}}
if [ -z "$PAD_USER" ] && [ "$(id -u)" = 0 ]; then
    # whoever owns the rootfs is the desktop user whose session this is
    PAD_USER=$(stat -c %U "$ROOT" 2>/dev/null)
    [ "$PAD_USER" = root ] && PAD_USER=""
fi
DROP=0
[ "$(id -u)" = 0 ] && [ -n "$PAD_USER" ] && DROP=1
as_user() {
    if [ "$DROP" = 1 ]; then runuser -u "$PAD_USER" -- "$@"; else "$@"; fi
}
# Every helper is started `setsid ... &`, and the pgid is what teardown kills.
# runuser must therefore go OUTSIDE setsid so the session leader is still the
# thing $! names: `runuser -u u -- setsid cmd`, not `setsid runuser ...`.
setsid_as_user() {
    if [ "$DROP" = 1 ]; then runuser -u "$PAD_USER" -- setsid "$@"; else setsid "$@"; fi
}
# IS THE PLAYFIELD PROCESS THERE? One definition, because there are now five
# places that ask - four in teardown and the post-start check - and this rig's
# standing rule is that two copies of one fact eventually disagree. `/init` is
# the WSL side of a Windows pythonw.exe reached through interop; `python3` is
# the same window on a Linux desktop, where it is an ordinary local process.
pf_up() { pgrep -f '^(/init|python3?) .*playfield\.py' >/dev/null; }
if [ "$(id -u)" = 0 ] && [ "$DROP" = 0 ]; then
    # ★ THE BLACK WINDOW, AND THE ONE CONFIGURATION THAT CAUSES IT.
    #
    # The block above says why root must not run the helpers: as root the
    # renderer cannot attach to the WSLg X server's shared memory, so the game
    # window OPENS AND STAYS BLACK. The drop dance exists to stop that, and it
    # is skipped in exactly one case - root with nobody to drop to, which is a
    # WSL whose DEFAULT USER IS ROOT. Then $HOME is /root, $ROOT is
    # /root/spike2root, it is root-owned, PAD_USER comes out empty, and this
    # runs the renderer as root without a word.
    #
    # REPORTED 2026-08-12 (PAD-63) AND IT COST THE WHOLE TICKET. The user got a
    # black game window beside a perfectly good playfield - the playfield is a
    # WINDOWS process on that machine, so it is the one thing root cannot spoil
    # - and his log was flawless everywhere else: card mounted, guest booted,
    # attract reached, his own clips decoded and handed over at 30.0/s, the
    # renderer at 40.9 fps over 4210 frames. Mesa says what is wrong
    # ("MESA: error: Failed to attach to x11 shm", carried to the app's pane
    # by the event filter as of this commit) but only in the renderer's own
    # log, and nothing said the run was in this state at all.
    #
    # NOT FATAL, for the reason the ffmpeg guard gives: the guest boots, the
    # sound plays, the switches and the playfield work, and a machine that is
    # one `adduser` away from a picture should not be refused.
    #
    # AND NO AUTOMATIC DROP HERE, deliberately. The X socket names the desktop
    # user, so guessing one is easy - and wrong: with HOME=/root, $ROOT lives
    # under a 0700 /root that the dropped helper cannot even traverse, so it
    # would trade a black window for a renderer that cannot open the ring. The
    # fix is which user the run STARTS as, which is the app's decision and the
    # user's setting, not something to patch over from in here.
    echo "[watch] THIS WSL RUNS AS ROOT, and its game window will be BLACK." >&2
    echo "[watch]   Everything else on this run is real - sound, switches, the" >&2
    echo "[watch]   playfield - but as root the renderer cannot attach to the X" >&2
    echo "[watch]   server's shared memory, so no picture reaches the window." >&2
    echo "[watch]   Nothing in the emulator can fix that from in here: it is" >&2
    echo "[watch]   which account this distro logs in as." >&2
    echo "[watch]   The cure, once, in a Windows terminal:" >&2
    echo "[watch]     wsl -u root adduser <name>" >&2
    echo "[watch]     wsl -u root usermod -aG sudo <name>" >&2
    echo "[watch]     wsl -u root sh -c 'printf \"[user]\\ndefault=<name>\\n\" >> /etc/wsl.conf'" >&2
    echo "[watch]   then 'Restart WSL...' on the Emulate tab and start again." >&2
    echo "[watch]   (A distro that already has an ordinary account needs only" >&2
    echo "[watch]   the last line.)" >&2
fi
if [ "$DROP" = 1 ]; then
    echo "[watch] running the guest as root, helpers as $PAD_USER"
    # Hand the log files back, or the NEXT ordinary run cannot truncate them:
    # `>` needs write permission on the FILE, and a root-owned 644 log in the
    # user's own home refuses it. That would break plain watch.sh runs after a
    # single PAD_PIVOT one, which is a nasty thing to leave behind.
    for f in "$LOG" "$HOSTLOG" "$HOME/padvid.log" "$HOME/padauto.log" \
             "$HOME/padball.log" "$HOME/padaudio.log" "$HOME/padtables.log" \
             "$PFLOG"; do
        [ -e "$f" ] || : > "$f" 2>/dev/null
        chown "$PAD_USER" "$f" 2>/dev/null
    done
fi

HOSTPG=""; GAMEPG=""; AUDPG=""; AUTOPG=""; VIDPG=""; EVTPG=""; TBLPG=""
BALLPG=""
# PAD_PIVOT run only: the guest logs to $ROOT/dump/game.out (its stdout points
# inside the container - see run_game.sh), so a tail folds that back into $LOG
# and every existing reader (autoattract, the [sw]/[segv] greps, gamestate)
# works unchanged. Empty on a normal run.
GAMEOUTTAIL=""
# NOTE: CARD_MNT is deliberately NOT reset here - it is set above, and this is
# below that. See the comment on its declaration.

teardown() {
    trap - INT TERM EXIT
    echo
    echo "[watch] stopping..."
    [ -n "$GAMEPG" ] && kill -9 -"$GAMEPG" 2>/dev/null
    # The only two patterns that actually match the guest; see alive.sh for why
    # the rig's historic 'godzilla_pro/game' pattern never could.
    pkill -9 -x game 2>/dev/null
    pkill -9 -f arm-binfmt 2>/dev/null
    # PAD_PIVOT runs exec qemu explicitly (no binfmt) and fold the guest log in
    # through a tail; kill it too. -F holds the file open forever otherwise.
    [ -n "$GAMEOUTTAIL" ] && kill -9 "$GAMEOUTTAIL" 2>/dev/null
    # SIGINT, THEN WAIT FOR IT, and only then SIGKILL. The old flat `sleep 1`
    # then SIGKILL fired whether or not the renderer was already on its way out,
    # and padglhost's shutdown now includes destroying its X windows so WSLg's
    # RAIL mirror sees them go (see the end of main() in padglhost.c). Killing
    # it in the middle of that is a plausible way to strand a window on the
    # desktop with nothing behind it. Escalation is still guaranteed, just no
    # longer premature - and it SAYS SO when it has to, because a renderer that
    # needs SIGKILL is a fact worth seeing rather than a silent 1 s wait.
    [ -n "$HOSTPG" ] && kill -INT -"$HOSTPG" 2>/dev/null
    pkill -INT -x padglhost 2>/dev/null
    for _ in 1 2 3 4 5 6; do
        pgrep -x padglhost >/dev/null || break
        sleep 0.5
    done
    if pgrep -x padglhost >/dev/null; then
        echo "[watch] the renderer did not stop on SIGINT; killing it"
        [ -n "$HOSTPG" ] && kill -9 -"$HOSTPG" 2>/dev/null
        pkill -9 -x padglhost 2>/dev/null
    fi
    pkill -9 -f nodebus.py 2>/dev/null
    [ -n "$VIDPG" ] && kill -9 -"$VIDPG" 2>/dev/null
    pkill -9 -f 'padvidhost.py' 2>/dev/null
    [ -n "$AUTOPG" ] && kill -9 -"$AUTOPG" 2>/dev/null
    pkill -9 -f 'autoattract.sh' 2>/dev/null
    [ -n "$BALLPG" ] && kill -9 -"$BALLPG" 2>/dev/null
    pkill -9 -f 'ballfeed[.]py' 2>/dev/null
    # longplay.sh is started BESIDE a run rather than by it, so it has no pgid
    # here - but a leaked one keeps poking ramp optos, and it would do that
    # into the NEXT run. It watches the guest and exits on its own; this is the
    # backstop for when that check is the thing that broke.
    # Anchored the same way alive.sh counts it: an unanchored 'longplay.sh'
    # matches any shell with the name on its command line, and this one KILLS.
    pkill -9 -f '^bash [^ ]*longplay\.sh' 2>/dev/null
    # $EVTPG is the awk at the END of the event pipeline (that is what $! means
    # for a pipeline); the tail at its head is caught by name. Both matter: an
    # orphaned tail -F never exits by itself.
    [ -n "$EVTPG" ] && kill -9 "$EVTPG" 2>/dev/null
    pkill -9 -f "tail -q -n 0 -F "$HOME/padvid"[.]log" 2>/dev/null
    # The background table builder, if this run started one. It sits in a poll
    # loop waiting for the guest to publish its switch table, so a run that
    # ends first leaves it with nothing to wait for. Added to alive.sh and
    # killgame.sh the same day, per this rig's own rule about anything a run
    # starts.
    [ -n "$TBLPG" ] && kill -9 -"$TBLPG" 2>/dev/null
    pkill -9 -f 'mktables[.]py' 2>/dev/null
    [ -n "$AUDPG" ] && kill -9 -"$AUDPG" 2>/dev/null
    pkill -9 -f 'playaudio.sh' 2>/dev/null
    # padrelay.py had NO pattern here and leaked twice on 2026-08-08, both
    # times in PAD_PIVOT sessions - runuser in setsid_as_user changes the
    # process-group topology, so the AUDPG group kill that catches it in an
    # ordinary run misses it there. A live relay also keeps the Windows
    # padplay.py connected forever; killing the relay closes the socket and
    # takes the player with it (measured - that is the relay's own teardown
    # design). alive.sh already counted both, which is how the leak was seen.
    pkill -9 -f 'padrelay\.py' 2>/dev/null
    pkill -9 -f '^ffmpeg .*audio\.fifo' 2>/dev/null
    rm -f "$AUD_HOST" "$AUD_FMT_HOST"
    # The LED block is the virtual playfield's liveness signal: it polls the
    # file and closes itself once a run it has seen is gone (playfield.py,
    # emu_gone). Removing it here is what makes closing the emulator window
    # close the playfield too. A new run recreates it before launching one.
    rm -f "$LED_HOST"

    # ...AND THEN VERIFY IT, because "it closes itself" was only ever true of
    # the WINDOW. The playfield is a Windows process reached through interop,
    # and its WSL-side stub outlived the window seven times over in one session
    # (oldest 2.5 h) while alive.sh reported the machine clean: once the stub's
    # interop Relay has died, the stub sits in poll() forever with nothing
    # behind it. Wait for the polite exit first - that is what lets it save its
    # window position (GONE_POLLS is ~2 s) - then kill what is left.
    #
    # AND KILLING THE STUB IS NOT ENOUGH. The two halves are NOT symmetric, both
    # directions measured 2026-08-05:
    #   kill the WINDOWS process -> the stub exits by itself. Clean.
    #   kill the STUB            -> the Windows process lives on. The playfield
    #                               window sat on the desktop with nothing
    #                               behind it, showing "no emulator" forever.
    # So the forced path asks Windows FIRST and only then sweeps the stub.
    # Matched on the SCRIPT PATH, never on the image name alone: killing every
    # pythonw.exe would take out whatever else the user is running.
    #
    # Both loops give the polite close a real chance (5 s, against the ~2 s
    # GONE_POLLS window) because it is worth having: the polite exit is what
    # saves the window position, and it is what usually happens. It failed in
    # one card run out of three, so this path is not theoretical.
    #
    # ...AND WHEN PAD OPENED THE WINDOW, NONE OF THIS APPLIES AND MUST NOT BE
    # "FIXED" TO. A window the app launched (PF_WINLAUNCH, above) has no
    # WSL-side stub to find, so the pgrep is correctly false - and the forced
    # path below is a powershell.exe call, which is INTEROP, i.e. the very
    # thing that was missing and sent the launch to the app in the first
    # place. Removing the LED block is what closes that window (it polls for
    # it), and the app holds the process handle for the case where it does
    # not. Whoever owns the launch owns the teardown.
    if [ "${PF_WINLAUNCH:-0}" != 1 ] && pf_up; then
        for _ in $(seq 1 10); do
            sleep 0.5
            pf_up || break
        done
        if pf_up; then
            echo "[watch] the playfield did not close itself; closing it the hard way"
            # `Name -like 'python*'` excludes THIS query: its own command line
            # contains the pattern string, so a CommandLine-only filter kills
            # the powershell.exe running it. Same self-match trap as pgrep.
            /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile \
              -Command "Get-CimInstance Win32_Process |
                        Where-Object { \$_.Name -like 'python*' -and
                                       \$_.CommandLine -like '*spike2_emu\playfield.py*' } |
                        ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" \
              >/dev/null 2>&1
            pkill -9 -f '^(/init|python3?) .*playfield\.py'
        fi
    fi

    # The card mount, IF THIS RUN MADE IT. cardmount.sh setsid's fuse2fs on
    # purpose - a process-group kill used to take the mount out from under the
    # game it had just started, which the game reports as sitting at "Startup
    # In Progress" forever with no error anywhere - so no teardown has ever
    # reached one, and three were found orphaned in a single session. The
    # expensive part of a card boot is the local image CACHE, which is a file
    # and survives; remounting costs a fraction of a second. -z as the fallback
    # so a straggler holding a file cannot strand the mount for good.
    # It SAYS which way it went, always. The first version printed only on
    # success, and a run that quietly left a mount behind was then
    # indistinguishable from one that had no card at all - which is how the
    # leak being fixed here stayed invisible in the first place.
    if [ -n "$CARD_MNT" ]; then
        if mountpoint -q "$CARD_MNT" 2>/dev/null; then
            fusermount -u "$CARD_MNT" 2>/dev/null \
                || fusermount3 -u "$CARD_MNT" 2>/dev/null \
                || fusermount -uz "$CARD_MNT" 2>/dev/null
            rmdir "$CARD_MNT" 2>/dev/null
            if mountpoint -q "$CARD_MNT" 2>/dev/null; then
                echo "[watch] could NOT unmount the card at $CARD_MNT"
            else
                echo "[watch] unmounted the card"
            fi
        else
            echo "[watch] the card was already unmounted"
        fi
    elif [ -n "${PAD_CARD:-}" ]; then
        echo "[watch] leaving the card mounted: it was mounted before this run"
    fi
    sleep 0.5
    echo "--- what is still running (all must be 0) ---"
    bash "$S/alive.sh"
}
trap 'teardown; exit 130' INT TERM
trap 'teardown' EXIT

# ★ IS THERE A DISPLAY, AND CAN A CLIENT REACH IT? See pad_display_state in
# padpath.sh for what each word means and how the `masked` one happens. This
# used to be `[ -z "$DISPLAY" ]`, which passes on every WSLg machine whether or
# not the socket it names still exists - and the machine where it does not is
# the one that gets a run with no picture and no complaint.
#
# REPAIR BEFORE REFUSE, AND REFUSE BEFORE RUN. The renderer is started a few
# hundred lines below and everything after it takes ~15 s to boot; finding out
# there is no window then, from a Mesa message inside another log, is what this
# is here to stop.
case $(pad_display_state) in
    ok|remote) ;;
    none)
        # AN UNSET DISPLAY IS NOT ONE FAULT, and this used to name only the
        # rarest of them, in a sentence that invited the user to CREATE the
        # setting that causes it. A tester met this on 2026-08-12, went looking
        # for %USERPROFILE%\.wslconfig, HAD NO SUCH FILE, and set about writing
        # one: "I followed instructions online to create the .wslconfig text
        # file but unsure if I just dump those strings in there or what". The
        # only string this message had given him was guiApplications=false -
        # so one paste would have switched GUI apps OFF on a machine where they
        # were on, and this message would have caused the fault it describes.
        # A restart cured his.
        #
        # Hence the order and the wording: the cure that usually works first,
        # the settings file second and only as something to LOOK AT, said as
        # plainly as it can be said that there is nothing to add there. And
        # third the one that no amount of restarting fixes - a WSL too old to
        # have WSLg at all, which is not something anything in here can see.
        echo "[watch] DISPLAY is unset - WSLg is not available, so there is no window to open." >&2
        if [ "$IS_WSL" = 1 ]; then
            echo "[watch]   WSLg sets DISPLAY when the distro starts, so an unset one" >&2
            echo "[watch]   usually means this session came up without it. Restart WSL" >&2
            echo "[watch]   ('Restart WSL...' on the Emulate tab, or 'wsl --shutdown' in" >&2
            echo "[watch]   a Windows terminal), then start the emulator again." >&2
            echo "[watch]   If it comes back after that, GUI apps are switched off for" >&2
            echo "[watch]   this PC. That switch is %USERPROFILE%\\.wslconfig on the" >&2
            echo "[watch]   WINDOWS side, and it is OPTIONAL: no such file means GUI apps" >&2
            echo "[watch]   are ON, so there is nothing to put in one - do not create it." >&2
            echo "[watch]   Only if it already exists and says guiApplications=false," >&2
            echo "[watch]   change that word to true (or delete the line) and restart WSL." >&2
            echo "[watch]   A WSL too old to have WSLg at all does this too, and no" >&2
            echo "[watch]   restart cures that one: 'wsl --update' in a Windows terminal." >&2
        else
            echo "[watch]   Nothing here can open a window. Start the emulator from a" >&2
            echo "[watch]   desktop session, or point DISPLAY at one this machine can" >&2
            echo "[watch]   reach." >&2
        fi
        exit 1 ;;
    masked)
        # WSLg's socket is where WSL put it and something has mounted over the
        # copy libX11 opens. As root (the app's own launch) put it back and get
        # on with the run; otherwise print the one command that fixes it.
        if pad_display_repair; then
            echo "[watch] the X socket at $PAD_X11_DIR was hidden by another" \
                 "mount - WSLg's own copy is bound back over it for this" \
                 "session, so the game window can open."
        else
            echo "[watch] there is an X server, and this distro cannot see it:" >&2
            echo "[watch]   $DISPLAY resolves to $(pad_x_socket), which does not" >&2
            echo "[watch]   exist, while WSLg's own copy of it does. Something" >&2
            echo "[watch]   (systemd's /tmp is the usual one) is mounted over it." >&2
            echo "[watch]   Fix it for this session with:" >&2
            echo "[watch]     sudo $(pad_display_fix_cmd)" >&2
            exit 1
        fi ;;
    *)
        # nosocket. On WSL that is conclusive - a local DISPLAY is that socket
        # and nothing else - so stop and say so rather than boot a guest nobody
        # can see. On a Linux desktop the same reading is only PROBABLE (an X
        # server can be started in ways this rig has never met), and refusing a
        # machine that works is the worse mistake, so there it is a warning.
        echo "[watch] DISPLAY is $DISPLAY and there is no X server at" \
             "$(pad_x_socket)." >&2
        echo "[watch]   Nothing can open a window here: the game would run" \
             "with no picture at all." >&2
        if [ "$IS_WSL" = 1 ]; then
            echo "[watch]   'wsl --shutdown' and start the emulator again is" \
                 "the usual cure." >&2
            exit 1
        fi
        echo "[watch]   Continuing anyway - this is a Linux desktop, and its" \
             "X server may live somewhere this rig has not met." >&2 ;;
esac

# Disk guard. A single long run writes an unbounded trace log - one earlier
# session left 188 GB of them and took the WSL disk to 98% full, which is the
# kind of failure that shows up as something else entirely. Warn loudly rather
# than refuse, since a short run is fine even when space is tight.
FREE_G=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "${FREE_G:-999}" -lt 10 ]; then
    echo "[watch] WARNING: only ${FREE_G}G free on /. Run logs grow fast." >&2
    echo "[watch]   du -sh "$HOME/gz"*.log   to see the worst offenders." >&2
fi

rm -f "$RING_HOST" "$SW_HOST"
# The key-bind export too (item 39): padglhost rewrites it once it is up, and
# a stale one from the LAST title would hand the playfield's key panel another
# game's switch ids for the seconds in between. Absent is the state the panel
# expects and polls through; wrong is the state nothing would notice.
rm -f "$ROOT/dump/padbinds"
# The guest opens the LED block O_RDWR and will NOT create it, so make it here.
# One page, zeroed: the shim stamps the magic once it maps it.
rm -f "$LED_HOST"
dd if=/dev/zero of="$LED_HOST" bs=4096 count=1 status=none
# This session's identity. savestate copies it into the slot; restorestate
# compares to tell a SAME-SESSION load (renderer already holds the guest's GL
# world) from a CROSS-SESSION one (it holds none of it - the game plays but
# its artwork rebuilds only as new scenes are built, so the picture is
# incomplete until then). The warning it prints is the honest label for that.
cat /proc/sys/kernel/random/uuid > "$ROOT/dump/boot.id" 2>/dev/null || \
    date +%s%N > "$ROOT/dump/boot.id"
# The rings must belong to the DESKTOP user: the helpers that read and write
# them (padglhost, the playfield over \\wsl.localhost, padvidhost) run as that
# user, and a root-owned padled is exactly what made the playfield report
# "dump/padled not readable". The guest is root and ignores the permissions.
if [ "$DROP" = 1 ]; then
    chown "$PAD_USER" "$LED_HOST" 2>/dev/null
    chown "$PAD_USER" "$ROOT/dump" 2>/dev/null
fi

# HOW LONG THIS WSL SESSION HAS BEEN UP, because it predicts a fault nothing
# here can detect.
#
# 2026-08-05: audio crackled through a whole afternoon and every instrument
# inside WSL said it was fine - the guest's PCM was clean, the sink's output
# was byte-faithful to it, and a pure sine captured off RDPSink.monitor was
# mathematically perfect (0 of 280490 samples off a sine) WHILE IT WAS AUDIBLY
# BREAKING UP in the room. The damage is in the WSLg -> Windows RDP audio hop,
# which is downstream of every microphone we have. `wsl --shutdown` fixed it
# instantly; the session had been up ~2 hours and had been fine that morning.
#
# So this CANNOT be a self-test - one would always pass. It is a risk hint and
# nothing more: print the session age, and say the magic words only once it is
# old enough to be a plausible suspect, so the next person who hears crackle
# reaches for the 20-second answer (tonetest.sh) instead of the whole
# afternoon. /proc/uptime is the VM's, shared by every distro.
if [ -r /proc/uptime ]; then
    UPS=$(cut -d. -f1 /proc/uptime)
    printf '[watch] WSL session up %dh %dm\n' $((UPS / 3600)) $(((UPS % 3600) / 60))
    if [ "$UPS" -gt 10800 ]; then
        echo "[watch] NOTE: WSLg audio can degrade on a long session. If sound" \
             "crackles, it is almost certainly NOT the emulator - run" \
             "tonetest.sh (20 s) to confirm, then 'wsl --shutdown'."
    fi
fi

# ffmpeg IS BOTH HELPERS, so it is asked about ONCE, here, before either is
# started. padvidhost.py spawns it per clip (the guest's gstreamer-0.10 has no
# software H.264 element - its only h264 decoder is the i.MX6 hardware one, and
# there is no i.MX6 here) and playaudio.sh uses its `pulse` muxer because this
# distro ships no pulseaudio client tools at all.
#
# WITHOUT THE CHECK, ITS ABSENCE IS INVISIBLE UNTIL IT IS DEAFENING. Nothing
# below fails to START: the mmap gets created, so "video: host decoder up" is
# printed by a decoder that cannot decode, and the failure arrives instead as
# every clip in the game dying on
#
#     ch0 decode failed: [Errno 2] No such file or directory: 'ffmpeg'
#
# a hundred lines a second, each one blocking the guest's thread until the host
# acks, behind a window that is simply black. That is what a user sat in front
# of on 2026-08-08 (PAD-49) while the tab reported every prerequisite OK.
#
# It is a WARNING and not a stop, because the rest of the run is real - the
# guest boots, the playfield works and the keys work, which is worth having on
# a machine that is one apt away.
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[watch] NO ffmpeg IN THIS LINUX. The game decodes neither its video" \
         "nor its audio itself, so both are done out here - this run will show" \
         "a BLACK SCREEN where the picture goes, and be silent." >&2
    echo "[watch] Fix it once:  sudo apt install ffmpeg" >&2
    echo "[watch] (or Stop, then 'Set up emulator...' on the Emulate tab)" >&2
    # The existing degraded path, not a new one. Left running against a video
    # bridge it can never fill, the guest re-arms the same clip forever and
    # blocks on each one; telling it up front that there is no bridge costs the
    # same black screen without the storm.
    export PAD_VID=0
fi

# Audio player first, so the FIFO exists before the game's first frame. It is
# started with its own session and killed in teardown like everything else.
if [ "${PAD_AUDIO:-1}" != 0 ]; then
    setsid_as_user bash "$S/playaudio.sh" "$AUD_HOST" "$AUD_RATE" 2 "$AUD_FMT_HOST" \
        > "$HOME/padaudio.log" 2>&1 &
    AUDPG=$!
    for i in $(seq 1 40); do [ -p "$AUD_HOST" ] && break; sleep 0.05; done
    if [ -p "$AUD_HOST" ]; then
        echo "[watch] audio: $AUD_HOST -> pulse"
        export PAD_AUDIO_PLAY="$AUD_GUEST"
        export PAD_AUDIO_FMT="$AUD_FMT_GUEST"
    else
        echo "[watch] audio: player did not come up, continuing silent" >&2
        tail -3 "$HOME/padaudio.log" >&2
    fi
fi

if [ "${PAD_VID:-1}" != 0 ]; then
    rm -f "$VID_HOST"
    setsid_as_user python3 "$S/padvidhost.py" "$VID_HOST" > "$HOME/padvid.log" 2>&1 &
    VIDPG=$!
    for i in $(seq 1 40); do [ -s "$VID_HOST" ] && break; sleep 0.05; done
    if [ -s "$VID_HOST" ]; then
        echo "[watch] video: host decoder up"
        export PAD_VID=1 PAD_VID_SHM="$VID_GUEST"
        # The RENDERER opens the same block, under its own path: the guest hands
        # it a byte offset for each video frame rather than 1.5 MB of pixels.
        VID_FOR_GL="$VID_HOST"
    else
        echo "[watch] video: host decoder did not come up, continuing without" >&2
        tail -3 "$HOME/padvid.log" >&2
        export PAD_VID=0
    fi
fi

echo "[watch] starting renderer (it opens the game window; the picture arrives"
echo "[watch] with the guest's first frame, ~15 s later)"
# PAD_GL_LEGEND passes through UNSET (item 39): the Controls window is
# retired - the playfield's key panel carries its content - and padglhost
# only opens it on an explicit =1, so a caller who wants the old window
# back exports that and nothing here overrides them.
setsid_as_user env PAD_GL_WINDOW=1 PAD_GL_DUMP="${PAD_GL_DUMP:-}" \
           PAD_SW_SHM="$SW_HOST" PAD_GL_LEGEND="${PAD_GL_LEGEND:-}" \
           PAD_VID_SHM="${VID_FOR_GL:-}" \
           "$PAD_GLHOST_BIN" "$RING_HOST" > "$HOSTLOG" 2>&1 &
# PADGL_DEBUG / PADGL_SEQ_* are NOT listed here on purpose: `env A=B cmd` keeps
# the rest of the environment, so exporting them before watch.sh already reaches
# padglhost, and naming them here would pass "" when they are unset - which
# padglhost's atoi() reads as a real 0 and which would silently switch the
# op-sequence window off.
HOSTPG=$!

for i in $(seq 1 100); do [ -s "$RING_HOST" ] && break; sleep 0.1; done
sleep 0.3
if ! pgrep -x padglhost >/dev/null; then
    echo "[watch] the renderer died on startup:" >&2
    tail -20 "$HOSTLOG" >&2
    exit 1
fi
grep -aE 'window opened|GL |ring |ready' "$HOSTLOG" | head -4

# ★ DID THE WINDOW OPEN? SAY SO, HERE, IN THIS SCRIPT'S OWN OUTPUT.
#
# The renderer answers this itself and always has - "window opened WxH on
# DISPLAY=..." or one of two headless lines - but it answers into $HOSTLOG,
# which nobody reads and which the app's event feed did not forward. So the
# state a user reported on 2026-08-11 (playfield up, "emulator up", NO GAME
# WINDOW) looked from out here exactly like a healthy run, all the way to the
# end of it.
#
# THE TWO OUTCOMES ARE DIFFERENT PROBLEMS AND WANT DIFFERENT SENTENCES, which
# is the whole reason this is a verdict rather than another warning:
#
#   * headless - there is no window, and padglhost's own line says why. Nothing
#     out here has to guess.
#   * opened - the window EXISTS. If the desktop shows none, then what is
#     missing is WSLg's mirror of it, not the window, and that is one restart
#     away. Nothing inside this Linux can see the Windows desktop, so this is
#     the furthest the rig can honestly go - and it is far enough to point at
#     the right cure instead of at the emulator.
#
# The renderer creates the ring BEFORE it opens the window, so the wait above
# can be over a fraction of a second early; poll rather than assume, and take
# whichever line lands first. NEVER FATAL: a headless run still boots the
# guest, plays sound and answers the playfield, and taking that away over a
# window would be a worse trade than saying so plainly.
GLWIN=""
for i in $(seq 1 30); do
    GLWIN=$(pad_window_line "$HOSTLOG") && break
    sleep 0.1
done
# ...THEN ASK ONCE MORE, because the surface failure lands a few milliseconds
# AFTER the window is mapped (pad_window_line's own comment has the ordering).
# The log only grows, so the second answer is the better one whenever there is
# one at all.
sleep 0.3
GLLATE=$(pad_window_line "$HOSTLOG") && GLWIN=$GLLATE
case "$GLWIN" in
    *"window opened"*)
        echo "[watch] game window ${GLWIN#*window }"
        # TWO CURES, AND THE ORDER MATTERS. This used to name the WSL restart
        # alone, which is right only when the window is where a user could see
        # it. The other way a window that "opened" is nowhere on the desktop is
        # that it opened at a REMEMBERED POSITION off the screen - and a
        # restart does nothing at all for that, because the coordinates come
        # back out of ~/.pad_windows on the next run too. The renderer now
        # names that case itself ("[padglhost] window: ...", carried to this
        # pane by the event filter), so the cheap, reversible cure is offered
        # first and the restart second.
        echo "[watch]   (no game window on the desktop? Two causes, in the"
        echo "[watch]   order worth trying: it opened somewhere you cannot see"
        echo "[watch]   - Stop, then 'Reset windows' on the Emulate tab, which"
        echo "[watch]   forgets where the windows were; or WSLg is not"
        echo "[watch]   mirroring it - Stop, then 'Restart WSL...'.)"
        # A WINDOW THAT IS THERE AND BLACK IS A DIFFERENT FAULT and used to get
        # the same answer, which is only right half the time: a WSL restart
        # repaints a lost mirror and does nothing at all for a picture that is
        # black where it is drawn. The renderer now says which, so point at it
        # rather than guessing here - the line arrives a few seconds later, in
        # this same pane.
        echo "[watch]   (a window that IS there and stays BLACK? The"
        echo "[watch]   '[padglhost] picture:' line below says which half it"
        echo "[watch]   is - a picture here and none on the desktop is the"
        echo "[watch]   mirror again; no picture here is the game or the"
        echo "[watch]   renderer, and no restart touches that.)" ;;
    *headless*)
        echo "[watch] THE RENDERER HAS NO WINDOW, so this run will show no" \
             "picture at all." >&2
        echo "[watch]   $GLWIN" >&2
        echo "[watch]   The game itself still boots, the sound still plays and" >&2
        echo "[watch]   the virtual playfield still works - which is why this" >&2
        echo "[watch]   is worth saying out loud rather than leaving to look" >&2
        echo "[watch]   like a black screen." >&2
        echo "[watch]   DISPLAY=${DISPLAY:-(unset)}, display state:" \
             "$(pad_display_state)" >&2
        echo "[watch]   'wsl --shutdown' and start again is the usual cure." >&2 ;;
    *)
        echo "[watch] the renderer has not said whether its window opened;" \
             "see $HOSTLOG" >&2 ;;
esac

echo "[watch] starting $GAME (boot to the first picture takes ~15 s)"
# PAD_PIVOT=1 boots a checkpointable guest (item 13). run_game.sh does the work;
# here it only means the guest's log arrives at $ROOT/dump/game.out instead of
# on stdout, so clear any stale copy before the run and fold the fresh one into
# $LOG below. Nothing else about the launch changes.
[ -n "${PAD_PIVOT:-}" ] && rm -f "$ROOT/dump/game.out"
setsid env PAD_THREAD_ENTRY=1 PAD_AUDIO_UNGATE=1 PAD_GL_BRIDGE="$RING_GUEST" \
           PAD_SW_SHM="$SW_GUEST" PAD_LED_SHM="$LED_GUEST" \
           PAD_AUDIO_PLAY="${PAD_AUDIO_PLAY:-}" \
           PAD_AUDIO_FMT="${PAD_AUDIO_FMT:-}" \
           PAD_VID="${PAD_VID:-0}" PAD_VID_SHM="${PAD_VID_SHM:-}" \
           PAD_GAME="$GAME" PAD_CARD="${PAD_CARD:-}" PAD_GAME_DIR="${PAD_GAME_DIR:-}" \
           PAD_PIVOT="${PAD_PIVOT:-}" \
           bash "$RIG/run_game.sh" > "$LOG" 2>&1 &
GAMEPG=$!
if [ -n "${PAD_PIVOT:-}" ]; then
    # -F retries until the guest creates the file a few seconds into the boot.
    # Direct (not a subshell) so $! is the tail itself and teardown's kill hits
    # it - a wrapping subshell would leave the tail holding the file forever.
    tail -F "$ROOT/dump/game.out" >> "$LOG" 2>/dev/null &
    GAMEOUTTAIL=$!
fi

# The virtual playfield: clickable switches, inserts lit from the wire.
#
# It has to run on WINDOWS - this WSL has no Python GUI toolkit at all (no
# tkinter, no gi/Gtk, no Qt) and installing one needs a sudo the rig does not
# have - but WSL can launch a Windows program through interop, so it still comes
# up by itself rather than being one more thing to remember. PAD_PLAYFIELD=0
# turns it off; set PAD_PF_PYTHON if python.exe is somewhere unusual.
#
# LAUNCH IT DIRECTLY, IN ITS OWN SESSION, AND DO NOT WAIT FOR IT. Every word of
# that is load-bearing and the first version got two of them wrong:
#
#   * NOT `cmd.exe /c start`. That combination HUNG FOREVER against pythonw.exe
#     and took the rest of this script with it - no autoattract, no wall-clock
#     backstop, and no teardown when the window closed, so a run could only be
#     stopped by hand. `start` returns promptly for a CONSOLE program because a
#     new console is allocated and the child inherits none of our handles;
#     pythonw.exe is a GUI-subsystem binary, gets no console, inherits the
#     interop pipe instead, and /init then waits for the pipe to close - which
#     it cannot until the playfield window is closed. Four leaked watch.sh trees
#     were sitting on that line before anyone noticed, because the symptom is a
#     script that looks like it is still starting up.
#   * pythonw.exe rather than python.exe, still: a GUI-subsystem interpreter is
#     what keeps a black console window from sitting beside the playfield. That
#     is the same property that broke `start`, so the two fixes are one choice.
#   * setsid, so the window is not in this script's process group and teardown's
#     group kills leave it alone. It talks to the rig only through dump/padled
#     (read) and swpoke.py (clicks), so it survives the game restarting under it.
#   * </dev/null and &, so nothing can block here again.
if [ "${PAD_PLAYFIELD:-1}" != 0 ]; then
    # THE TABLES ARE BUILT FROM THE TITLE, HERE, RATHER THAN COMMITTED. See
    # mktables.py. Three of the four need nothing but the game binary, so the
    # window can open with artwork, inserts and coils on a title's very first
    # run; the switch list only exists once the game has published its own
    # table a few seconds in, so wait a bounded while for it. Cached per title
    # afterwards, so every later run of the same title skips all of this.
    #
    # THE GATE THIS REPLACES WAS `[ -d "$S/games/$GAME" ]`, and it is why Jaws
    # opened no window at all: `games/` held two titles with hand-made tables,
    # anything else was skipped, AND NOTHING WAS PRINTED. Whatever happens now,
    # something is said.
    # MEASURED, not guessed: the shim publishes the switch table about a MINUTE
    # into a run, not 25 s. A 25 s budget got it on one pass of four titles and
    # missed it on the next pass of two, which is the worst possible shape -
    # it looks like a property of the title. `[swfind] found the switch table`
    # in the run log is the moment being waited for.
    PF_WAIT=${PAD_PF_WAIT:-120}
    TBL_OUT=$(mktemp "${TMPDIR:-/tmp}/padtables.XXXXXX")
    echo "[watch] playfield tables for $GAME:"

    # PASS ONE: everything that needs no run at all - the artwork, the device
    # positions, the insert map. Fast, and cached after the first time.
    python3 "$RIG/mktables.py" > "$TBL_OUT" 2>&1
    grep -v '^drawable=' "$TBL_OUT" | sed 's/^/[watch]   /'

    # ★ ITEM 49: PASS ONE JUST RAN AS ROOT ON A PIVOT RUN, AND PASS TWO RUNS
    # AS $PAD_USER - hand the tables tree over IN BETWEEN, or pass two cannot
    # write switch_list.txt into the per-title directory pass one created.
    # That exact deadlock is why james_bond_60th's first run never got its
    # switch table: mktables died on an uncaught PermissionError in
    # padtables.log, which nothing shows, and the dir stayed root-owned so
    # EVERY later run failed the same way (a poisoned cache, not a transient
    # miss - david could not even build it by hand without root). Recursive,
    # deliberately: it also heals any title dir an older run already
    # poisoned. Same drop-dance as $ROOT/dump and the log files above.
    # $TABLES, not a hardcoded path: every writer resolves the tree through
    # padpath's PAD_TABLES, so a machine that overrides it must have the
    # override healed, not the default nobody is using.
    if [ "$DROP" = 1 ]; then
        chown -R "$PAD_USER" "$TABLES" 2>/dev/null
    fi

    # PASS TWO IS WHERE THE WAIT GOES, AND WHETHER IT BLOCKS DEPENDS ON WHETHER
    # THERE IS ANYTHING TO LOOK AT MEANWHILE. Blocking always would delay the
    # window by a minute on every first run of a title; never blocking would
    # open an empty window for a title that has no artwork and no device table,
    # which is exactly what Led Zeppelin and Elvira are.
    if grep -q '^drawable=yes' "$TBL_OUT"; then
        echo "[watch]   opening now; the switch table follows in the background"
        setsid_as_user python3 "$RIG/mktables.py" --log "$LOG" --wait "$PF_WAIT" \
            > "$HOME/padtables.log" 2>&1 &
        TBLPG=$!
    else
        echo "[watch]   nothing to draw yet - waiting for the game's own switch list"
        # as_user (item 49): on a pivot run this used to run as ROOT and
        # re-create switch_list.txt root-owned INSIDE the tree the chown
        # above just healed - the Led Zeppelin / Elvira shape re-poisoning
        # the cache one branch below the cure. Foreground and piped, so
        # as_user (plain runuser) rather than setsid_as_user: the output is
        # the [watch] pane's, and teardown has nothing to kill here.
        as_user python3 "$RIG/mktables.py" --log "$LOG" --wait "$PF_WAIT" 2>&1 \
            | grep -v '^drawable=' | sed 's/^/[watch]   /'
    fi
    rm -f "$TBL_OUT"

    # TWO WAYS TO OPEN ONE WINDOW, AND WHICH ONE IS RIGHT IS A PROPERTY OF THE
    # MACHINE, NOT A PREFERENCE.
    #
    # On a Linux desktop the playfield is an ordinary local Tk process talking
    # to the same X server as the game, and that is all it should ever have
    # been. The elaborate path below it exists because THIS WSL HAS NO TK AT
    # ALL - no tkinter, no gi/Gtk, no Qt - and installing one needs a sudo the
    # rig does not have. Under WSL the window therefore runs as a WINDOWS
    # process reached through interop, which is why it needs a translated path,
    # WSLENV to carry anything at all, and pythonw.exe rather than python.exe.
    # Whether the playfield shows its Save/Load state controls. The app's
    # Emulate tab owns the user-facing toggle: toggle ON boots PAD_PIVOT=1
    # (the only checkpointable shape), so "pivot boot" IS the enable signal
    # and a hand-run PAD_PIVOT session keeps its buttons with no extra flag.
    # It rides the COMMAND LINE because the Windows-side window only sees
    # WSLENV-listed variables, and an argv is one less thing to keep in step.
    #
    # ...AND WHAT THE RUN TURNED OUT TO BE BEATS WHAT IT WAS ASKED TO BE. The
    # gate above withdraws a pivot this machine cannot do, but run_game.sh can
    # still be refused by the kernel at the pivot itself - and it now answers
    # that by booting the ordinary way rather than by dying. That run is up,
    # correct and NOT checkpointable, and this line is written after the guest
    # has started, so the log already says so if it happened. Buttons that can
    # only fail are the thing this flag exists to prevent; asking the log costs
    # one grep and covers the case no pre-flight can.
    PF_STATES=""
    if [ "${PAD_SAVESTATES:-${PAD_PIVOT:-0}}" = 1 ] &&
       ! grep -q '^\[run\] pivot_root failed' "$LOG" 2>/dev/null; then
        PF_STATES="--savestates"
    fi
    if [ "$IS_WSL" = 0 ]; then
        PF_PY=${PAD_PF_PYTHON:-python3}
        if "$PF_PY" -c 'import tkinter' >/dev/null 2>&1; then
            : > "$PFLOG" 2>/dev/null
            setsid_as_user "$PF_PY" "$RIG/playfield.py" "$GAME" $PF_STATES </dev/null >>"$PFLOG" 2>&1 &
            PF_LAUNCHED=1
            echo "[watch] virtual playfield window opening (PAD_PLAYFIELD=0 to skip)"
        else
            # Say what to install rather than just what is missing: on Debian
            # and Ubuntu tkinter is a separate package from python3 itself, so
            # "no module named tkinter" is a packaging surprise, not a mistake.
            echo "[watch] no tkinter, so no playfield window." >&2
            echo "[watch]   sudo apt-get install python3-tk   (or python3-tkinter)" >&2
        fi
    else
        PF_PY=${PAD_PF_PYTHON:-pythonw.exe}
        # The rig's own path, as Windows sees it. `wslpath -w` is asked rather
        # than the answer being written down: the literal here named one user's
        # checkout on one machine's C: drive.
        PF_WIN=$(pad_win "$RIG/playfield.py")
        # The title goes on the COMMAND LINE, not in the environment: this is a
        # Windows process started through interop and only variables named in
        # WSLENV cross that boundary, which is one more thing to keep in step.
        #
        # PAD_ROOT and PAD_TABLES DO cross, through pad_export_win, and they
        # must: the playfield window is a Windows process that has to open files
        # inside WSL, and `/p` makes WSL translate each value into its
        # `\\wsl.localhost` form on the way. Without it the window has to shell
        # out to `wslpath` to work out where it is reading from - which it can,
        # but paying ~200 ms per question for something this side already knows
        # is silly.
        pad_export_win
        # PAD_PF_LOG reaches the playfield ONLY through WSLENV, same mechanism.
        # The measurement that produced the 30 fps number had to bypass watch.sh
        # entirely for want of this line.
        [ -n "${PAD_PF_LOG:-}" ] && \
            export WSLENV="${WSLENV:+$WSLENV:}PAD_PF_LOG/p"
        # The two fade knobs cross the same way (no /p - they are numbers, not
        # paths). Without these lines "tunes live with no rebuild" was only
        # true for a window started by hand on the Windows side.
        [ -n "${PAD_PF_FADE_UNIT_MS:-}" ] && \
            export WSLENV="${WSLENV:+$WSLENV:}PAD_PF_FADE_UNIT_MS"
        [ -n "${PAD_PF_FADE_MS:-}" ] && \
            export WSLENV="${WSLENV:+$WSLENV:}PAD_PF_FADE_MS"
        if command -v "$PF_PY" >/dev/null 2>&1; then
            # TRUNCATE, then append: one run's log, not every run's. The window
            # is a Windows process here and its traceback would otherwise go
            # nowhere at all - pythonw.exe has no console to print one to.
            : > "$PFLOG" 2>/dev/null
            setsid_as_user "$PF_PY" "$PF_WIN" "$GAME" $PF_STATES </dev/null >>"$PFLOG" 2>&1 &
            PF_LAUNCHED=1
            echo "[watch] virtual playfield window opening (PAD_PLAYFIELD=0 to skip)"
        else
            # ---- ASK THE APP TO OPEN IT, because it is a Windows process too.
            #
            # THE FAULT: a user's WSL has interop switched off (/etc/wsl.conf,
            # [interop] enabled=false), so this distro cannot execute a Windows
            # binary at all - and the playfield window is a Windows binary,
            # because this WSL has no Tk. His window could never open itself,
            # and all the rig could do was print a command for him to type
            # before every single run.
            #
            # THE ASYMMETRY THAT MAKES THIS WORK, and it is the whole point:
            # interop is LINUX -> WINDOWS. Windows -> Linux (`wsl.exe`) is
            # unaffected, so everything the window does once it is up - reading
            # dump/padled, running swpoke.py, asking wslpath - still works. It
            # is only the LAUNCH that cannot cross, and PAD is already standing
            # on the other side: it is a Windows process, running a Python that
            # has tkinter (it is drawing its own window with it). So the run
            # asks, and the app spawns it. Same for a machine whose interop is
            # fine but has no pythonw.exe on PATH - the branch is the same and
            # so is the answer.
            #
            # THE PATHS GO WITH IT, ALREADY TRANSLATED. The window needs the
            # rootfs and the tables directory in Windows form; WSLENV's `/p`
            # normally does that during the interop exec, which is precisely
            # the step not happening here. wslpath is an ordinary Linux binary
            # in the distro, so it answers with interop off.
            PF_WINLAUNCH=1
            echo "PAD_PLAYFIELD_WINDOWS_LAUNCH game=$GAME" \
                 "savestates=$([ -n "$PF_STATES" ] && echo 1 || echo 0)" \
                 "root=$(pad_win "$ROOT" 2>/dev/null)" \
                 "tables=$(pad_win "$TABLES" 2>/dev/null)"
            echo "[watch] this WSL cannot start a Windows program (interop is"
            echo "[watch]   off, or pythonw.exe is not on its PATH), so PAD has"
            echo "[watch]   been asked to open the playfield window instead."
            echo "[watch]   Running watch.sh by hand? Open it yourself with:"
            echo "[watch]   pythonw tools\\spike2_emu\\playfield.py $GAME"
        fi
    fi
fi

# NO Windows-side window mover. padwinpos.py briefly restored positions with
# SetWindowPos and it made both windows UNDRAGGABLE: a programmatic move on a
# WSLg RAIL window happens behind the compositor's back, the X side and the
# Windows side then disagree about where the window is, and RAIL reasserts the
# stale position against every user drag. The script survives as a position
# RECORDER for diagnosis only. The restore fix has to move the window through
# X so the compositor owns it - see REMAINING item 5 in the handoff.

# Wait for the guest to actually EXIST before treating its absence as "it
# exited". run_game.sh has to set up a pty, a user/mount/PID namespace and a
# chroot before it execs the game, so qemu is not visible for a second or two -
# and polling immediately made the first version of this script declare "the
# game exited" 0.25 s in and kill a perfectly healthy run.
echo "[watch] waiting for the game to start..."
for i in $(seq 1 240); do
    pad_guest_up && break
    if ! pgrep -x padglhost >/dev/null; then
        echo "[watch] the renderer died while the game was starting:" >&2
        tail -20 "$HOSTLOG" >&2
        exit 1
    fi
    sleep 0.25
done
if ! pad_guest_up; then
    echo "[watch] the game never started. Last lines of its log:" >&2
    tail -20 "$LOG" >&2
    exit 1
fi

# DID THE PLAYFIELD WINDOW STAY UP? Asked HERE, and it is the whole of the
# answer to "starting Bond Pro was missing the keys window and playfield"
# (2026-08-11) - a report that arrived with a full run log in which not one
# line was about the playfield, because there was nothing anywhere to write
# one. The launch above is `... &` with both streams thrown away, so a window
# that died on its first line and a window the user closed looked identical,
# and the key list lives in that window since item 39 retired the Controls
# one: no window, no keys, no explanation.
#
# HERE, rather than at the launch, for two reasons. The guest is up, so the
# seconds this took are seconds the window had to fail in; and it costs no
# sleep of its own, which the launch site could not have avoided.
#
# NOT when PAD opened the window (PF_WINLAUNCH): that one has no WSL-side
# process to find and the app reports its own failures - the same asymmetry
# teardown documents at length. NOT when nothing was launched either.
if [ "${PF_LAUNCHED:-0}" = 1 ] && ! pf_up; then
    echo "[watch] the playfield window is not running - it started and stopped."
    if [ -s "$PFLOG" ]; then
        echo "[watch]   what it said (full log: $PFLOG):"
        tail -8 "$PFLOG" | sed 's/^/[watch]   /'
    else
        # An empty log is itself the finding: the interpreter never got as far
        # as running the script, so the fault is the LAUNCH, not the window.
        echo "[watch]   ...and wrote nothing, so $PF_PY never ran it. Open it"
        echo "[watch]   by hand to see why: $PF_PY <rig>/playfield.py $GAME"
    fi
    echo "[watch]   the game itself is unaffected."
fi

# Carry the game from Tech Alerts to attract mode without a human. It is a
# separate script and a separate process because it spends most of its life
# asleep waiting on the boot, and this loop must stay responsive to the window
# closing. It exits by itself when the game gets there, or when the game dies.
if [ "${PAD_AUTO_ATTRACT:-1}" != 0 ]; then
    setsid_as_user bash "$S/autoattract.sh" "$LOG" > "$HOME/padauto.log" 2>&1 &
    AUTOPG=$!
    echo "[watch] auto-advance on: it will press Service Back until the game"
    echo "[watch] leaves Tech Alerts (PAD_AUTO_ATTRACT=0 to do it yourself)."
fi

# THE BALL FEEDER (item 21b). The game fires its trough eject coil and waits
# for a trough switch to change; until this existed nothing answered, so a
# ball only ever moved when a human ran plunge.py and multiball could not
# happen at all. It watches dump/padled's coil counter and drives the trough
# and shooter-lane switches, so it is the one helper that moves BALLS rather
# than pressing buttons - PAD_BALL_FEED=0 turns it off and hands that back to
# plunge.py.
#
# ITS OWN LOG, like autoattract's, and NOT $LOG. $LOG is the guest's, this
# script truncates it and three readers grep it (the [sw] and [segv] tails,
# gamestate.sh); item 38's second finding is a stray writer landing inside
# alive.sh's output and eating a label off its first line, which is the same
# class of thing. `[ball]` lines go to ~/padball.log and stay legible.
if [ "${PAD_BALL_FEED:-1}" != 0 ]; then
    setsid_as_user python3 "$S/ballfeed.py" > "$HOME/padball.log" 2>&1 &
    BALLPG=$!
    echo "[watch] ball feed on: the game's own trough eject will be answered"
    echo "[watch] (PAD_BALL_FEED=0 to move balls by hand with plunge.py)."
fi

# PAD_DOOR_OPEN=1 - boot with the coin door held OPEN, for servicing (item 43).
# This is a convenience, not a rendering fix any more: the video-side door
# gate is GONE (see gstvid.c's tombstone - the service pages pick their DMD
# dot mode on their own in the ASYNC preroll window, and they NEED their
# backdrop video working). Holding the door open from boot just means the
# service buttons are unlocked the moment the game is up. One early swhold is
# not enough: the rest-state writer forces the door shut once at guest start
# and the merge is last-edge-wins, so this loop re-asserts through the boot
# window. Close the door (click switch 33, or swhold.py 33 1) when done.
if [ "${PAD_DOOR_OPEN:-0}" = 1 ]; then
    (
        # The gate only trusts an EDGE-established door state (see
        # pad_sw_level), so stamp CLOSED once and then hold OPEN - the 1->0
        # transition is what makes "open" a known fact rather than a fresh
        # block's meaningless zeros. Re-asserted through the boot window
        # because the writers are last-edge-wins and the playfield stamps
        # its own rest state when it comes up.
        first=1
        for _i in $(seq 1 30); do
            if [ -f "$ROOT/dump/padsw" ]; then
                if [ -n "$first" ]; then
                    setsid_as_user python3 "$S/swhold.py" 33 1 >/dev/null 2>&1
                    first=
                fi
                setsid_as_user python3 "$S/swhold.py" 33 0 >/dev/null 2>&1
            fi
            sleep 2
        done
    ) &
    echo "[watch] coin door held OPEN through boot (PAD_DOOR_OPEN=1):"
    echo "[watch] service buttons unlocked; close the door (swhold.py 33 1)"
    echo "[watch] when done."
fi

# KEY EVENTS, on THIS script's stdout. The app's Emulate tab drains watch.sh's
# output into its log pane, and a terminal run shows the same thing - so the
# one place worth publishing "what is the run doing" is right here. The
# per-part logs stay complete on disk; this is a filtered live view of the
# handful of lines that mean something: clips starting and ending, the audio
# player coming up, bridge failures, and the game's own errors.
#
# The awk stays deliberately small: Radium repeats one error tens of times a
# second when something is wrong (14,837 identical lines in one run), so
# repeats collapse to the first sighting plus a count every 500th. fflush()
# after every print matters - awk into a pipe is block-buffered, and a "live"
# event feed that arrives four kilobytes at a time is not live.
if [ "${PAD_EVENTS:-1}" != 0 ]; then
    # tr -d NULs before awk: loading a save can truncate-EXTEND the guest log
    # (restorestate.sh grows it back to the size criu recorded), and the hole
    # reads as one giant all-NUL "line" - 341,626 NULs in one [event] line on
    # 2026-08-09, which then froze the app's log pane at every startup.
    # stdbuf -oL because tr into a pipe is block-buffered, and a "live" event
    # feed that arrives four kilobytes at a time is not live (same reasoning
    # as the fflush after every print below).
    tail -q -n 0 -F "$HOME/padvid.log" "$HOME/padaudio.log" \
                    "$HOME/padglhost.log" "$LOG" 2>/dev/null \
        | stdbuf -oL tr -d '\000' | awk '
        /Radium Error/ {
            if (++n[$0] == 1 || n[$0] % 500 == 0)
                { printf "[event] %s (x%d)\n", $0, n[$0]; fflush() }
            next }
        /\[padvid / {
            if ($0 ~ /serving|superseded|did not answer|decode failed|cannot open|guest stopped|ffmpeg ended|unusable/)
                { print "[event] " $0; fflush() }
            next }
        /\[play\]/               { print "[event] " $0; fflush(); next }
        # THE LINE THAT NAMES A BLACK WINDOW, and it is not ours: Mesa prints
        # it, into the renderer log, when the renderer is running as root and
        # cannot attach to the WSLg X server shared memory. The window opens,
        # every counter in the run reads healthy and no picture ever arrives.
        # It came a whole ticket late once (PAD-63) because nothing carried it
        # here. Collapsed like Radium: the log FILLS with it.
        /Failed to attach to x11 shm/ {
            if (++n[$0] == 1 || n[$0] % 500 == 0)
                { printf "[event] %s (x%d)\n", $0, n[$0]; fflush() }
            next }
        # `window:` joins `window opened` here for the same reason picture:
        # did - it is the renderer answering "where did the window go", and a
        # verdict nobody sees is a verdict that costs a ticket. It carries the
        # remembered position that was refused or ignored, and names the button
        # that clears it.
        # `display` carries the item 44 second-display lifecycle - opened,
        # targeted, closed-and-hidden, render target failed - every one of
        # which starts "[padglhost] display". The review caught these lines
        # missing from this alternation: a user would have seen "picture: d2
        # FIRST" with no second window on the desktop and no line saying why,
        # the exact PAD-63 gap the comments around this filter document.
        # (And no apostrophes in here, as those comments say: this text is
        # INSIDE the single-quoted awk program, and one of them ends it -
        # the first draft of THIS comment broke watch.sh at line 1328.)
        /\[padglhost\] (window opened|window:|video block|ring |UNKNOWN|picture:|display)/ \
                                 { print "[event] " $0; fflush(); next }
        # `picture:` IS THE SAME GAP ONE STEP FURTHER IN. The lines above cover
        # a window that never opened; a window that opens and stays BLACK was
        # invisible to this pane in exactly the same way, and it is the harder
        # of the two to reason about from outside (PAD-63, 2026-08-12: 4210
        # rendered frames, 28.4 video uploads/s, and a black window). The
        # picture oracle in the renderer names which half it is - see its
        # header in padglhost.c - and every one of its lines starts with the
        # word, so one pattern carries all four. (No apostrophes in here: this
        # comment is INSIDE the single-quoted awk program, and one of them ends
        # it - which is why the comments around it are written the same way.)
        # ...AND WHEN THERE IS NO WINDOW, WHICH IS THE ONE THAT WAS MISSING.
        # padglhost degrades to headless rather than dying (a broken X server
        # must not end a run that is otherwise fine), so its two explanations -
        # "XOpenDisplay failed ...; staying headless" and "eglCreateWindowSurface
        # failed ...; falling back to headless" - were the only record of a run
        # with no picture, in a log the app never showed. Matched anywhere in
        # the line because both put the word at the END of it.
        /\[padglhost\] .*headless/ { print "[event] " $0; fflush(); next }
        /\[vid\]|\[card\]/       { print "[event] " $0; fflush(); next }
        # [swpend]/[swlatch] were silently dropped here until 2026-08-13 -
        # run 6 exported PAD_SW_PEND and got a console with zero swpend
        # lines, which read as "instrument dead" until this filter was
        # checked. Forward them like [sw]; they only exist when their env
        # vars are set, so a normal run pays nothing.
        /\[sw\] |\[tap\] |\[cabchg\]|\[swpend\] |\[swlatch\] / { print "[event] " $0; fflush(); next }
        # THE CRASH SIGNATURE needs its own pattern: the shim prints
        # "[segv] pc=..." in LOWER CASE and the /SEGV/ rule below is
        # case-sensitive, so the one line naming where a crash happened was
        # the one line that could not reach the app pane. Item 41 lost two
        # turtles_pro crashes to that gap - the pane showed qemu s bare
        # "uncaught target signal 11" and nothing that said where.
        /\[segv\]/               { print "[event] " $0; fflush(); next }
        /SEGV|Segmentation|FATAL/{ print "[event] " $0; fflush(); next }
    ' &
    EVTPG=$!
fi

echo "[watch] running. CLOSE THE WINDOW to stop (or press Ctrl-C here)."
echo "[watch] CLICK the game window for keyboard play: arrows = flippers,"
echo "[watch] Enter/-/= = service. The playfield window lists every key."
[ "$MINS" != 0 ] && echo "[watch] backstop: will stop by itself after $MINS min."

# Poll instead of `wait`: we must react to EITHER end dying, and to the wall
# clock, and `wait` on a setsid'd child cannot do that. 0.25 s is responsive
# without costing anything measurable.
END=0
[ "$MINS" != 0 ] && END=$(( $(date +%s) + MINS * 60 ))
while :; do
    if ! pgrep -x padglhost >/dev/null; then
        # NOT "(window closed)" FOR EVERY WAY THE RENDERER CAN GO. This line
        # used to assert that, unconditionally, on nothing but "the process is
        # not there anymore" - so a renderer that DIED read in the log as a
        # human closing a window, and PAD-63's black-window report arrived with
        # exactly that sentence on the end of it, which is the one thing that
        # had to be established before anything else could be. padglhost says
        # why it is stopping ("window closed; stopping" / "window destroyed;
        # stopping"); when it said neither, say THAT and show its last words,
        # rather than putting it on the user.
        if grep -q 'window \(closed\|destroyed\); stopping' "$HOSTLOG" 2>/dev/null; then
            echo "[watch] renderer exited (window closed)."
        else
            echo "[watch] THE RENDERER STOPPED ON ITS OWN - it did not report" \
                 "a closed window, so this was not you closing it." >&2
            echo "[watch]   its last lines ($HOSTLOG):" >&2
            tail -3 "$HOSTLOG" 2>/dev/null | sed 's/^/[watch]   /' >&2
        fi
        break
    fi
    # A SAVE-STATE RELOAD IS NOT THE GAME EXITING (item 13). loadgame.sh kills
    # the guest and restores another one in its place, so for a second or two
    # there is no guest - and this loop used to call that "the game exited" and
    # tear the whole session down, taking the window with it. loadgame.sh raises
    # this flag before it kills and drops it when the restore is done, so the
    # session rides through. Bounded: if a reload wedges, the flag goes stale
    # and the loop stops waiting rather than hanging a dead session forever.
    if [ -f "$ROOT/dump/reloading" ]; then
        if [ "$(( $(date +%s) - $(stat -c %Y "$ROOT/dump/reloading" 2>/dev/null || echo 0) ))" -lt 120 ]; then
            sleep 0.25
            continue
        fi
        echo "[watch] a save-state reload has been in progress for 2 min; giving up on it."
        rm -f "$ROOT/dump/reloading"
    fi
    if ! pad_guest_up; then
        echo "[watch] the game exited. Last lines of its log:"
        tail -5 "$LOG"
        break
    fi
    if [ "$END" != 0 ] && [ "$(date +%s)" -ge "$END" ]; then
        echo "[watch] ${MINS} min backstop reached."
        break
    fi
    sleep 0.25
done

grep -aE 'fps|stopped' "$HOSTLOG" | tail -3
