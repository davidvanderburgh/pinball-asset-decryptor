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
echo "[play] fifo $FIFO  ${RATE} Hz x ${CH} ch s16le -> pulse"

# -re is deliberately NOT used: the guest already paces itself in real time
# against snd_pcm_avail(), so the FIFO arrives at wall-clock speed. Adding -re
# would pace it twice and drift.
# The read end must stay open across gaps in the guest's writes, or ffmpeg sees
# EOF the moment the game goes quiet and exits; holding a writer open ourselves
# keeps the FIFO alive for the whole session.
sleep infinity > "$FIFO" &
HOLD=$!
trap 'kill $HOLD 2>/dev/null; rm -f "$FIFO"' EXIT

# PAD_AUDIO_LATENCY_MS is the PulseAudio side of the latency budget, and it is
# only ONE of three terms. The others are the guest's own write-ahead
# (PAD_AUDIO_BUFFER, reported as `latency=` on the [aud] line) and whatever is
# already sitting in the FIFO. Lower it and callouts arrive sooner; lower it too
# far and pulse underruns, which sounds like crackle, not like lateness.
LAT=${PAD_AUDIO_LATENCY_MS:-40}
echo "[play] pulse buffer ${LAT} ms"

exec ffmpeg -hide_banner -loglevel error \
     -f s16le -ar "$RATE" -ac "$CH" -i "$FIFO" \
# The pulse stream name carries the title, so a mixer shows which game is
# playing - and so teardown's pkill pattern still matches whatever ran.
     -f pulse -buffer_duration "$LAT" "${PAD_GAME:-Spike 2} emulator"
