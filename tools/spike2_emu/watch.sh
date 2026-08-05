#!/bin/bash
# watch.sh [minutes] - WATCH the emulated game in a real window.
#
#   wsl -e bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/watch.sh
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
cd /home/david

MINS=${1:-30}
LOG=${LOG:-/home/david/gzwatch.log}
HOSTLOG=/home/david/padglhost.log
RING_HOST=/home/david/spike2root/dump/padgl
RING_GUEST=/dump/padgl
# The keyboard channel. Same host-path/guest-path split as the GL ring: the
# native renderer owns the window and so is the only thing that can see a key,
# the shim inside the emulated game is the only thing that can press a switch.
SW_HOST=/home/david/spike2root/dump/padsw
# Live LED state (padled.h): the shim decodes the insert boards' per-LED writes
# and publishes them here, so the virtual playfield needs no log and no
# PAD_NB_LOG - raising that quadruples the boot.
LED_HOST=/home/david/spike2root/dump/padled
LED_GUEST=/dump/padled
SW_GUEST=/dump/padsw
# Audio: the guest writes PCM into a FIFO, a native ffmpeg drains it into WSLg's
# PulseAudio. Same host-path/guest-path split as the GL ring and the keyboard.
# PAD_AUDIO=0 turns it off.
AUD_HOST=/home/david/spike2root/dump/audio.fifo
AUD_GUEST=/dump/audio.fifo
AUD_FMT_HOST=/home/david/spike2root/dump/audio.fmt
AUD_FMT_GUEST=/dump/audio.fmt
AUD_RATE=${PAD_AUDIO_RATE:-48000}   # fallback only; the guest reports the real one
# Video: the guest has no H.264 decoder at all, so the HOST decodes with ffmpeg
# and publishes raw I420 frames into a shared ring. Same split as the GL bridge
# and the audio player. PAD_VID=0 turns it off.
VID_HOST=/home/david/spike2root/dump/padvid
VID_GUEST=/dump/padvid
S=/mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu

export PAD_GL_W=${PAD_GL_W:-1360}
export PAD_GL_H=${PAD_GL_H:-768}
export GALLIUM_DRIVER=${GALLIUM_DRIVER:-d3d12}   # without this Mesa picks llvmpipe

# WHICH TITLE. PAD_GAME picks it; run_game.sh has the full rule and prints what
# it chose. Everything below that is per-title reads it from here.
# PAD_CARD runs a title straight off its card image with no extraction; the
# title name then comes from the card, so ask cardmount.sh rather than guess.
GAME=${PAD_GAME:-}
if [ -n "${PAD_CARD:-}" ]; then
    CARD_PATH=$(bash "$S/cardmount.sh" "$PAD_CARD" | tail -1)
    [ -d "$CARD_PATH" ] || { echo "[watch] could not mount $PAD_CARD" >&2; exit 1; }
    GAME=$(basename "$CARD_PATH")
    # The video host reads clips itself, outside the chroot, so it needs the
    # card's real path - the title is not under spike2root/games at all.
    export PAD_CARD PAD_VID_ROOT="$CARD_PATH"
elif [ -n "${PAD_GAME_DIR:-}" ]; then
    # A title directory anywhere on disk, bind mounted the same way.
    GAME=$(basename "${PAD_GAME_DIR%/}")
    export PAD_GAME_DIR PAD_VID_ROOT="${PAD_GAME_DIR%/}"
fi
[ -z "$GAME" ] && { GAME=$(readlink /home/david/spike2root/games/game 2>/dev/null); GAME=${GAME%/game}; }
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

HOSTPG=""; GAMEPG=""; AUDPG=""; AUTOPG=""; VIDPG=""

teardown() {
    trap - INT TERM EXIT
    echo
    echo "[watch] stopping..."
    [ -n "$GAMEPG" ] && kill -9 -"$GAMEPG" 2>/dev/null
    # The only two patterns that actually match the guest; see alive.sh for why
    # the rig's historic 'godzilla_pro/game' pattern never could.
    pkill -9 -x game 2>/dev/null
    pkill -9 -f arm-binfmt 2>/dev/null
    [ -n "$HOSTPG" ] && kill -INT -"$HOSTPG" 2>/dev/null
    pkill -INT -x padglhost 2>/dev/null
    sleep 1
    [ -n "$HOSTPG" ] && kill -9 -"$HOSTPG" 2>/dev/null
    pkill -9 -x padglhost 2>/dev/null
    pkill -9 -f nodebus.py 2>/dev/null
    [ -n "$VIDPG" ] && kill -9 -"$VIDPG" 2>/dev/null
    pkill -9 -f 'padvidhost.py' 2>/dev/null
    [ -n "$AUTOPG" ] && kill -9 -"$AUTOPG" 2>/dev/null
    pkill -9 -f 'autoattract.sh' 2>/dev/null
    [ -n "$AUDPG" ] && kill -9 -"$AUDPG" 2>/dev/null
    pkill -9 -f 'playaudio.sh' 2>/dev/null
    pkill -9 -f 'ffmpeg.*-f pulse' 2>/dev/null
    rm -f "$AUD_HOST" "$AUD_FMT_HOST"
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
    echo "[watch]   du -sh /home/david/gz*.log   to see the worst offenders." >&2
fi

rm -f "$RING_HOST" "$SW_HOST"
# The guest opens the LED block O_RDWR and will NOT create it, so make it here.
# One page, zeroed: the shim stamps the magic once it maps it.
rm -f "$LED_HOST"
dd if=/dev/zero of="$LED_HOST" bs=4096 count=1 status=none

# Audio player first, so the FIFO exists before the game's first frame. It is
# started with its own session and killed in teardown like everything else.
if [ "${PAD_AUDIO:-1}" != 0 ]; then
    setsid bash "$S/playaudio.sh" "$AUD_HOST" "$AUD_RATE" 2 "$AUD_FMT_HOST" \
        > /home/david/padaudio.log 2>&1 &
    AUDPG=$!
    for i in $(seq 1 40); do [ -p "$AUD_HOST" ] && break; sleep 0.05; done
    if [ -p "$AUD_HOST" ]; then
        echo "[watch] audio: $AUD_HOST -> pulse"
        export PAD_AUDIO_PLAY="$AUD_GUEST"
        export PAD_AUDIO_FMT="$AUD_FMT_GUEST"
    else
        echo "[watch] audio: player did not come up, continuing silent" >&2
        tail -3 /home/david/padaudio.log >&2
    fi
fi

if [ "${PAD_VID:-1}" != 0 ]; then
    rm -f "$VID_HOST"
    setsid python3 "$S/padvidhost.py" "$VID_HOST" > /home/david/padvid.log 2>&1 &
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
        tail -3 /home/david/padvid.log >&2
        export PAD_VID=0
    fi
fi

echo "[watch] starting renderer (window opens when the game's first frame arrives)"
setsid env PAD_GL_WINDOW=1 PAD_GL_DUMP="${PAD_GL_DUMP:-}" \
           PAD_SW_SHM="$SW_HOST" PAD_GL_LEGEND="${PAD_GL_LEGEND:-1}" \
           PAD_VID_SHM="${VID_FOR_GL:-}" \
           ./padglhost "$RING_HOST" > "$HOSTLOG" 2>&1 &
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
           bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/run_game.sh > "$LOG" 2>&1 &
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
if [ "${PAD_PLAYFIELD:-1}" != 0 ] && [ -d "$S/games/$GAME" ]; then
    PF_PY=${PAD_PF_PYTHON:-pythonw.exe}
    PF_WIN='C:\Users\david\Documents\development\pinball-asset-decryptor\tools\spike2_emu\playfield.py'
    # The title goes on the COMMAND LINE, not in the environment: this is a
    # Windows process started through interop and only variables named in
    # WSLENV cross that boundary, which is one more thing to keep in step.
    if command -v "$PF_PY" >/dev/null 2>&1; then
        setsid "$PF_PY" "$PF_WIN" "$GAME" </dev/null >/dev/null 2>&1 &
        echo "[watch] virtual playfield window opening (PAD_PLAYFIELD=0 to skip)"
    else
        echo "[watch] no Windows interop; run playfield.py yourself:" >&2
        echo "[watch]   pythonw tools\\spike2_emu\\playfield.py" >&2
    fi
fi

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
    setsid bash "$S/autoattract.sh" "$LOG" > /home/david/padauto.log 2>&1 &
    AUTOPG=$!
    echo "[watch] auto-advance on: it will press Service Back until the game"
    echo "[watch] leaves Tech Alerts (PAD_AUTO_ATTRACT=0 to do it yourself)."
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
