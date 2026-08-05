#!/bin/bash
# playaudio.sh [fifo] [rate] [channels] - play the emulated game's PCM out of
# WSL to the Windows speakers.
#
# The guest's fake ALSA card (alsastub.c) writes every frame the game plays into
# a FIFO when PAD_AUDIO_PLAY names one. This drains that FIFO into WSLg's
# PulseAudio, which is what carries sound from WSL to Windows.
#
# WHY ffmpeg AND NOT paplay: this distro has no pulseaudio client tools at all
# (no paplay, pacat, pactl, aplay) but it does have ffmpeg, whose `pulse` muxer
# talks the same protocol. Checked, not assumed.
#
# The FIFO is the safety boundary. The guest opens and writes it NON-BLOCKING and
# drops on EAGAIN, so nothing here - a slow reader, a dead reader, no reader at
# all - can stall the emulated game. Worst case is silence.
set -u
FIFO=${1:-/home/david/spike2root/dump/audio.fifo}
RATE=${2:-48000}
CH=${3:-2}
FMT=${4:-/home/david/spike2root/dump/audio.fmt}

command -v ffmpeg >/dev/null || { echo "[play] no ffmpeg" >&2; exit 1; }
# The WSLg pulse socket materialises on demand, so it can genuinely be absent for
# a moment at startup and present by the time ffmpeg connects. Wait rather than
# warn about a race.
for i in $(seq 1 40); do [ -S /mnt/wslg/PulseServer ] && break; sleep 0.25; done
[ -S /mnt/wslg/PulseServer ] || echo "[play] WARNING: no /mnt/wslg/PulseServer after 10 s" >&2

rm -f "$FIFO" "$FMT"
mkfifo "$FIFO" || exit 1

# DO NOT GUESS THE RATE. The guest writes it to $FMT the moment the game
# configures its card, which is long before the first frame. Guessing 48000 when
# the stream is 44100 plays everything ~9% sharp and sounds like a codec fault.
# It cannot be sent over the fifo itself: the guest's open is non-blocking and
# fails until a reader exists, and the reader would be waiting for the rate.
echo "[play] waiting for the guest to report its PCM format..."
for i in $(seq 1 240); do [ -s "$FMT" ] && break; sleep 0.25; done
if [ -s "$FMT" ]; then
    read -r r c < "$FMT"
    [ -n "${r:-}" ] && RATE=$r
    [ -n "${c:-}" ] && CH=$c
    echo "[play] guest reports ${RATE} Hz x ${CH} ch"
else
    echo "[play] no format after 60 s, falling back to ${RATE} Hz x ${CH} ch" >&2
fi
# -re is deliberately NOT used: the guest already paces itself in real time
# against snd_pcm_avail(), so the FIFO arrives at wall-clock speed. Adding -re
# would pace it twice and drift.
# The read end must stay open across gaps in the guest's writes, or ffmpeg sees
# EOF the moment the game goes quiet and exits; holding a writer open ourselves
# keeps the FIFO alive for the whole session.
sleep infinity > "$FIFO" &
HOLD=$!
trap 'kill $HOLD 2>/dev/null; rm -f "$FIFO"' EXIT

# ---- WHICH SPEAKER: Windows directly, or WSLg's PulseAudio ----------------
#
# WSLg's audio link to Windows is the weak part of this whole rig. It degrades
# on a live session - measured 2026-08-05: a pure sine came back mathematically
# perfect off pulse's own monitor (0 of 280490 samples off a sine) while it was
# audibly breaking up in the room, and a WAV played by Windows itself at the
# same moment was clean. So the fault is entirely in the WSLg -> Windows hop,
# nothing inside WSL can see it, and `wsl --shutdown` was the only cure.
#
# So DO NOT USE THAT HOP. The guest's PCM is already raw s16le in a FIFO; serve
# it over TCP and let a WINDOWS ffplay.exe be the speaker. PulseAudio, Weston
# and RDP all drop out of the audio path. Two facts make it work: WSL can
# execute a Windows binary directly (interop), and WSL2 forwards Windows'
# localhost onto listeners inside the VM, so the player connects to 127.0.0.1.
#
# PAD_AUDIO_SINK=pulse forces the old path back (it is still correct, just
# fragile); =win forces this one and fails loudly if ffplay is missing; the
# default picks Windows when ffplay.exe can be found and falls back otherwise.
find_ffplay() {
    [ -n "${PAD_FFPLAY:-}" ] && { echo "$PAD_FFPLAY"; return; }
    # The app passes PAD_FFPLAY (it already resolves ffplay for audio preview).
    # For a terminal run, look where Windows actually puts it. The WinGet path
    # carries a package hash, so glob it rather than spelling it out.
    local c
    for c in /mnt/c/Users/*/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/*/bin/ffplay.exe \
             /mnt/c/ffmpeg/bin/ffplay.exe \
             "/mnt/c/Program Files/ffmpeg/bin/ffplay.exe"; do
        [ -x "$c" ] && { echo "$c"; return; }
    done
    echo ""
}

SINK=${PAD_AUDIO_SINK:-auto}
FFPLAY=$(find_ffplay)
if [ "$SINK" = auto ]; then
    [ -n "$FFPLAY" ] && SINK=win || SINK=pulse
fi
if [ "$SINK" = win ] && [ -z "$FFPLAY" ]; then
    echo "[play] PAD_AUDIO_SINK=win but no ffplay.exe found; set PAD_FFPLAY" >&2
    exit 1
fi

if [ "$SINK" = win ]; then
    PORT=${PAD_AUDIO_PORT:-45997}
    case "$CH" in 1) LAYOUT=mono ;; *) LAYOUT=stereo ;; esac
    echo "[play] fifo $FIFO  ${RATE} Hz x ${CH} ch s16le -> WINDOWS ffplay (tcp/$PORT)"
    echo "[play] bypassing WSLg audio entirely: $FFPLAY"

    # The FIFO, handed out as raw bytes. This is audiotcp.py and NOT another
    # ffmpeg, and the reason is load-bearing: ffmpeg opens its INPUT before its
    # OUTPUT, so `-i $FIFO ... -f s16le tcp://...?listen=1` blocks on a FIFO
    # that stays empty until the game first makes a sound and NEVER OPENS THE
    # SOCKET. The player then finds nothing to connect to and the run is
    # silent. audiotcp.py listens first and opens the FIFO only once a player
    # has attached.
    python3 "$(dirname "$0")/audiotcp.py" "$FIFO" "$PORT" &
    SRV=$!

    # TEARING DOWN A WINDOWS CHILD. The player is a native Windows process
    # reached through interop, so it is invisible to pgrep and to killgame.sh -
    # exactly the orphan class this rig exists to avoid.
    #
    # The normal path needs no help: `-autoexit` makes ffplay leave when its
    # input ends, and the socket ends whenever the server goes, INCLUDING on
    # SIGKILL, because the kernel closes a dead process's sockets. The backstop
    # below is only for a player that never connected or has wedged.
    #
    # It matches on OUR PORT, not on the image name: `taskkill /IM ffplay.exe`
    # would also kill the audio preview in PAD itself, which is a different
    # ffplay doing legitimate work for the user.
    WINPID=""
    win_kill() {
        /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile \
            -Command "Get-CimInstance Win32_Process -Filter \"Name='ffplay.exe'\" |
                      Where-Object { \$_.CommandLine -like '*:$PORT*' } |
                      ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" \
            >/dev/null 2>&1 || true
    }
    trap 'kill $HOLD $SRV 2>/dev/null; [ -n "$WINPID" ] && kill $WINPID 2>/dev/null;
          win_kill; rm -f "$FIFO"' EXIT

    # NO READINESS PROBE HERE, deliberately. The obvious one - connect to the
    # port to see whether it is up yet - IS ITSELF A CLIENT: audiotcp.py
    # accepts it as the player, opens the FIFO for it and then sees it hang up
    # ("player connected" / "player went away" in the log for a player that was
    # never there). The retry loop below covers a listener that is not ready,
    # which is what the probe was for, so the probe only ever added a fake
    # connection.
    #
    # ffplay 8.x has no -ac; channels come from -ch_layout. The low-delay flags
    # matter: the default buffering is fine for a file and useless for a
    # machine that has to answer a flipper button.
    #
    # RESTARTED IF IT DIES, because it is the speaker and a run that quietly
    # loses it is the "audio was silently dead for weeks" failure this rig has
    # already had once. The loop exits with the relay.
    (
        while kill -0 $SRV 2>/dev/null; do
            "$FFPLAY" -hide_banner -loglevel error -nodisp -autoexit \
                -fflags nobuffer -flags low_delay -probesize 32 \
                -analyzeduration 0 \
                -f s16le -ar "$RATE" -ch_layout "$LAYOUT" \
                -i "tcp://127.0.0.1:$PORT" >/dev/null 2>&1
            kill -0 $SRV 2>/dev/null || break
            echo "[play] Windows player exited; restarting it" >&2
            sleep 1
        done
    ) &
    WINPID=$!
    wait $SRV
    exit 0
fi

echo "[play] fifo $FIFO  ${RATE} Hz x ${CH} ch s16le -> pulse"

# PAD_AUDIO_LATENCY_MS is the PulseAudio side of the latency budget, and it is
# only ONE of three terms. The others are the guest's own write-ahead
# (PAD_AUDIO_BUFFER, reported as `latency=` on the [aud] line) and whatever is
# already sitting in the FIFO. Lower it and callouts arrive sooner; lower it too
# far and pulse underruns, which sounds like crackle, not like lateness.
LAT=${PAD_AUDIO_LATENCY_MS:-40}
echo "[play] pulse buffer ${LAT} ms"

# The pulse stream name carries the title, so a mixer shows which game is
# playing - and so teardown's pkill pattern still matches whatever ran.
#
# NOTHING MAY COME BETWEEN THESE LINES, not even a comment. A `\` continuation
# followed by a comment line does not continue anything: the backslash-newline
# is removed FIRST, so the `#` lands inside the command and eats the rest of it.
# ffmpeg then ran with an input and NO OUTPUT, said "At least one output file
# must be specified", and exited - and because this is `exec`, the player was
# gone. Every run since that comment was added has been silent, and the script
# still passes `bash -n` because the orphaned last line is valid on its own.
exec ffmpeg -hide_banner -loglevel error \
     -f s16le -ar "$RATE" -ac "$CH" -i "$FIFO" \
     -f pulse -buffer_duration "$LAT" "${PAD_GAME:-Spike 2} emulator"
