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
HOSTLOG=$HOME/padglhost.log
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

# UNPOPULATED NODES ARE PER TITLE, so this is a lookup and not a constant.
# Node 2 is not populated on a Godzilla Pro: the game's own static config table
# assigns it no devices of any kind (board[+144] and its kind-1 counterpart are
# both 0, against 69/460/276 on the other ws2812node boards). The shim otherwise
# answers for all 64 addresses, which makes an absent board look present, and
# slot 2 is the one board whose "registered" bit is board[+144] != 0 - so a
# manufactured node 2 can never be suppressed and sits on Tech Alerts forever.
# Staying silent for it is the accurate behaviour, not a workaround.
#
# A title not listed here silences NOTHING, which is the safe direction: an
# extra board answering is a Tech Alert you can see and then add here, whereas
# silencing a board that IS populated loses its devices with no message at all.
case "$GAME" in
    godzilla_pro|godzilla_le) NB_SILENT_DEFAULT=2 ;;
    *)                        NB_SILENT_DEFAULT="" ;;
esac
export PAD_NB_SILENT=${PAD_NB_SILENT:-$NB_SILENT_DEFAULT}

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

HOSTPG=""; GAMEPG=""; AUDPG=""; AUTOPG=""; VIDPG=""; EVTPG=""; TBLPG=""
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
    if pgrep -f '^(/init|python3?) .*playfield\.py' >/dev/null; then
        for _ in $(seq 1 10); do
            sleep 0.5
            pgrep -f '^(/init|python3?) .*playfield\.py' >/dev/null || break
        done
        if pgrep -f '^(/init|python3?) .*playfield\.py' >/dev/null; then
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

if [ -z "${DISPLAY:-}" ]; then
    echo "[watch] DISPLAY is unset - WSLg is not available, so there is no window to open." >&2
    exit 1
fi

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
# The guest opens the LED block O_RDWR and will NOT create it, so make it here.
# One page, zeroed: the shim stamps the magic once it maps it.
rm -f "$LED_HOST"
dd if=/dev/zero of="$LED_HOST" bs=4096 count=1 status=none

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

# Audio player first, so the FIFO exists before the game's first frame. It is
# started with its own session and killed in teardown like everything else.
if [ "${PAD_AUDIO:-1}" != 0 ]; then
    setsid bash "$S/playaudio.sh" "$AUD_HOST" "$AUD_RATE" 2 "$AUD_FMT_HOST" \
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
    setsid python3 "$S/padvidhost.py" "$VID_HOST" > "$HOME/padvid.log" 2>&1 &
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

echo "[watch] starting renderer (window opens when the game's first frame arrives)"
setsid env PAD_GL_WINDOW=1 PAD_GL_DUMP="${PAD_GL_DUMP:-}" \
           PAD_SW_SHM="$SW_HOST" PAD_GL_LEGEND="${PAD_GL_LEGEND:-1}" \
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

echo "[watch] starting $GAME (boot to the first picture takes ~15 s)"
setsid env PAD_THREAD_ENTRY=1 PAD_AUDIO_UNGATE=1 PAD_GL_BRIDGE="$RING_GUEST" \
           PAD_SW_SHM="$SW_GUEST" PAD_LED_SHM="$LED_GUEST" \
           PAD_AUDIO_PLAY="${PAD_AUDIO_PLAY:-}" \
           PAD_AUDIO_FMT="${PAD_AUDIO_FMT:-}" \
           PAD_VID="${PAD_VID:-0}" PAD_VID_SHM="${PAD_VID_SHM:-}" \
           PAD_GAME="$GAME" PAD_CARD="${PAD_CARD:-}" PAD_GAME_DIR="${PAD_GAME_DIR:-}" \
           bash "$RIG/run_game.sh" > "$LOG" 2>&1 &
GAMEPG=$!

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

    # PASS TWO IS WHERE THE WAIT GOES, AND WHETHER IT BLOCKS DEPENDS ON WHETHER
    # THERE IS ANYTHING TO LOOK AT MEANWHILE. Blocking always would delay the
    # window by a minute on every first run of a title; never blocking would
    # open an empty window for a title that has no artwork and no device table,
    # which is exactly what Led Zeppelin and Elvira are.
    if grep -q '^drawable=yes' "$TBL_OUT"; then
        echo "[watch]   opening now; the switch table follows in the background"
        setsid python3 "$RIG/mktables.py" --log "$LOG" --wait "$PF_WAIT" \
            > "$HOME/padtables.log" 2>&1 &
        TBLPG=$!
    else
        echo "[watch]   nothing to draw yet - waiting for the game's own switch list"
        python3 "$RIG/mktables.py" --log "$LOG" --wait "$PF_WAIT" 2>&1 \
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
    if [ "$IS_WSL" = 0 ]; then
        PF_PY=${PAD_PF_PYTHON:-python3}
        if "$PF_PY" -c 'import tkinter' >/dev/null 2>&1; then
            setsid "$PF_PY" "$RIG/playfield.py" "$GAME" </dev/null >/dev/null 2>&1 &
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
        if command -v "$PF_PY" >/dev/null 2>&1; then
            setsid "$PF_PY" "$PF_WIN" "$GAME" </dev/null >/dev/null 2>&1 &
            echo "[watch] virtual playfield window opening (PAD_PLAYFIELD=0 to skip)"
        else
            echo "[watch] no Windows interop; run playfield.py yourself:" >&2
            echo "[watch]   pythonw tools\\spike2_emu\\playfield.py $GAME" >&2
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
    pgrep -f arm-binfmt >/dev/null && break
    if ! pgrep -x padglhost >/dev/null; then
        echo "[watch] the renderer died while the game was starting:" >&2
        tail -20 "$HOSTLOG" >&2
        exit 1
    fi
    sleep 0.25
done
if ! pgrep -f arm-binfmt >/dev/null; then
    echo "[watch] the game never started. Last lines of its log:" >&2
    tail -20 "$LOG" >&2
    exit 1
fi

# Carry the game from Tech Alerts to attract mode without a human. It is a
# separate script and a separate process because it spends most of its life
# asleep waiting on the boot, and this loop must stay responsive to the window
# closing. It exits by itself when the game gets there, or when the game dies.
if [ "${PAD_AUTO_ATTRACT:-1}" != 0 ]; then
    setsid bash "$S/autoattract.sh" "$LOG" > "$HOME/padauto.log" 2>&1 &
    AUTOPG=$!
    echo "[watch] auto-advance on: it will press Service Back until the game"
    echo "[watch] leaves Tech Alerts (PAD_AUTO_ATTRACT=0 to do it yourself)."
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
    tail -q -n 0 -F "$HOME/padvid.log" "$HOME/padaudio.log" \
                    "$HOME/padglhost.log" "$LOG" 2>/dev/null | awk '
        /Radium Error/ {
            if (++n[$0] == 1 || n[$0] % 500 == 0)
                { printf "[event] %s (x%d)\n", $0, n[$0]; fflush() }
            next }
        /\[padvid / {
            if ($0 ~ /serving|superseded|did not answer|decode failed|cannot open|guest stopped|ffmpeg ended|unusable/)
                { print "[event] " $0; fflush() }
            next }
        /\[play\]/               { print "[event] " $0; fflush(); next }
        /\[padglhost\] (window opened|video block|ring |UNKNOWN)/ \
                                 { print "[event] " $0; fflush(); next }
        /\[vid\]|\[card\]/       { print "[event] " $0; fflush(); next }
        /\[sw\] |\[tap\] |\[cabchg\]/ { print "[event] " $0; fflush(); next }
        /SEGV|Segmentation|FATAL/{ print "[event] " $0; fflush(); next }
    ' &
    EVTPG=$!
fi

echo "[watch] running. CLOSE THE WINDOW to stop (or press Ctrl-C here)."
echo "[watch] CLICK a window to give it keyboard focus, then use the keys in"
echo "[watch] the Controls window: arrows = flippers, Enter/-/= = service."
[ "$MINS" != 0 ] && echo "[watch] backstop: will stop by itself after $MINS min."

# Poll instead of `wait`: we must react to EITHER end dying, and to the wall
# clock, and `wait` on a setsid'd child cannot do that. 0.25 s is responsive
# without costing anything measurable.
END=0
[ "$MINS" != 0 ] && END=$(( $(date +%s) + MINS * 60 ))
while :; do
    if ! pgrep -x padglhost >/dev/null; then
        echo "[watch] renderer exited (window closed)."
        break
    fi
    if ! pgrep -f arm-binfmt >/dev/null; then
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
