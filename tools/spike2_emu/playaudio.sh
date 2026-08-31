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
. "$(dirname "$0")/padpath.sh"
set -u
FIFO=${1:-$ROOT/dump/audio.fifo}
RATE=${2:-48000}
CH=${3:-2}
FMT=${4:-$ROOT/dump/audio.fmt}

command -v ffmpeg >/dev/null || { echo "[play] no ffmpeg" >&2; exit 1; }
# The WSLg pulse socket materialises on demand, so it can genuinely be absent for
# a moment at startup and present by the time ffmpeg connects. Wait rather than
# warn about a race.
#
# ONLY ON WSL. /mnt/wslg does not exist on a Linux desktop, so unconditionally
# waiting for it spent 10 s and then printed a warning about a missing WSL
# component on a machine that has no WSL - the kind of message that teaches
# people to ignore warnings.
if pad_is_wsl; then
    for i in $(seq 1 40); do [ -S /mnt/wslg/PulseServer ] && break; sleep 0.25; done
    [ -S /mnt/wslg/PulseServer ] || echo "[play] WARNING: no /mnt/wslg/PulseServer after 10 s" >&2
fi

rm -f "$FIFO" "$FMT"
mkfifo "$FIFO" || exit 1

# DO NOT GUESS THE RATE. The guest writes it to $FMT the moment the game
# configures its card, which is long before the first frame. Guessing 48000 when
# the stream is 44100 plays everything ~9% sharp and sounds like a codec fault.
# It cannot be sent over the fifo itself: the guest's open is non-blocking and
# fails until a reader exists, and the reader would be waiting for the rate.
#
# UNLESS THE CALLER DECLARES IT. The Spike 1 rig knows its format statically
# (44100x2, from the game ELF) and passes it as args; PAD_AUDIO_FMT_FIXED=1
# says "the args ARE the format", skipping this wait. It exists because the
# obvious alternative - the caller pre-writing $FMT - RACES: the `rm -f $FMT`
# above runs after this script's WSLg-socket wait, up to 10 s in, and deleted
# a Spike 1 fmt written 2 s after launch, leaving this poll waiting a full
# 60 s for a file nobody would write again (sound arrived, but a minute
# late, which reads as "sound is not working").
if [ -z "${PAD_AUDIO_FMT_FIXED:-}" ]; then
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
else
    echo "[play] caller-declared format: ${RATE} Hz x ${CH} ch"
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
# WSLg's audio link to Windows is the weak part of this whole rig, and how badly
# is measurable: play a known file through it, record the speakers, align the
# recording to the source and subtract (audioscore.py). Windows playing that file
# itself scores -13.6 dB of residual; through WSLg's PulseAudio it scores
# +16.4 dB, i.e. THE ERROR IS LOUDER THAN THE SIGNAL. Buffer size, sample rate
# and CPU load all leave that untouched.
#
# BEWARE THE TEST THAT SAYS IT IS FINE. A pure sine comes back clean through
# this path - clean at the sink AND clean at the speakers - while music through
# it at the same moment is wrecked. A sine survives a bad path nearly intact, so
# a tone test can only ever produce a false negative here.
#
# So DO NOT USE THAT HOP. The guest's PCM is already raw s16le in a FIFO; serve
# it over TCP and let a WINDOWS python running padplay.py be the speaker.
# PulseAudio, Weston and RDP all drop out of the audio path. Two facts make it
# work: WSL can execute a Windows binary directly (interop), and WSL2 forwards
# Windows' localhost onto listeners inside the VM, so the player connects to
# 127.0.0.1. Scored the same way, that path is -14.7 dB: level with Windows
# playing the file directly.
# is_wsl lived here as its own copy; padpath.sh now owns the answer, because
# two scripts defining one fact is how alive.sh and killgame.sh once
# disagreed about what a running rig even is.
is_wsl() { pad_is_wsl; }

# A Windows Python that can actually open a sound device. THE SEARCH ITSELF now
# lives in padpath.sh as pad_win_python, because setupcheck.sh asks the same
# question so the Emulate tab can answer it before a run instead of during one,
# and one fact with two definitions is how this rig has been bitten before.
find_winpython() { pad_win_python; }

# THE DEFAULT IS `auto`, AND AUTO MEANS "BRIDGE ON WSL, NATIVE EVERYWHERE ELSE".
#
# That is the cross-platform answer, not a Windows-shaped compromise. macOS and
# Linux have no WSL boundary, so there is nothing to bypass and pulse/alsa/
# CoreAudio is simply the right path. WSL is the one platform whose audio hop is
# broken, so it is the one platform that gets bypassed.
#
# And the hop really is broken, measured rather than guessed. Playing a known
# file through it and subtracting the original from a recording of the speakers
# (see resid.py in the session scratchpad) scores +16 dB of damage - the error
# is louder than the signal - while Windows playing that same file scores
# -13.6 dB. Buffer size, sample rate and CPU load all make no difference to it.
# The bridge over the same measurement scores -14.8 dB, i.e. level with Windows
# playing the file itself.
#
# =pulse forces the old path back, =win forces the bridge and fails loudly.
SINK=${PAD_AUDIO_SINK:-auto}
WINPY=""
# NO PROBE FOR THE SINKS THAT DO NOT NEED ONE. The Windows-python search runs
# .exe files through WSL interop, and interop is TIED TO THE wsl.exe SESSION
# THAT SPAWNED THIS SCRIPT: a launcher that exits right after backgrounding us
# (the Spike 1 tab's start.sh does, by design — READY is its handshake) takes
# the interop socket with it, and the probe then hangs FOREVER, before this
# script has started a relay or printed a word. Measured live 2026-08-31:
# David's fresh app start, four wedged playaudio processes 151 s old, the
# probe's python.exe never existing on the Windows side, and no sound. A
# relay/pulse sink never execs a Windows binary, so it never probes.
if [ "$SINK" != pulse ] && [ "$SINK" != relay ]; then
    is_wsl && WINPY=$(find_winpython)
fi
if [ "$SINK" = auto ]; then
    [ -n "$WINPY" ] && SINK=win || SINK=pulse
fi
# THE ADVICE IS ASKED OF THIS MACHINE, not written down here - PAD-95.  `py`
# is an optional tick in the Windows installer, so a fixed line can name a
# program the reader does not have ("py" wurde nicht als Name eines Cmdlet
# erkannt), and the answer for a PAD install is not a command at all but its
# own prerequisite installer.  pad_sounddevice_hint (padpath.sh) is the one
# definition; the Emulate tab says the same thing from setupcheck.sh's facts.
# `--user` stays part of it where a command is right: an all-users Python
# lives under C:\Program Files, where pip cannot write without an elevated
# terminal - it fails with WinError 5 and suggests this flag itself.
if [ "$SINK" = win ] && [ -z "$WINPY" ]; then
    echo "[play] PAD_AUDIO_SINK=win but no Windows Python with sounddevice." >&2
    pad_sounddevice_hint | sed 's/^/[play]   /' >&2
    exit 1
fi
# Falling back rather than exiting: a degraded speaker beats a silent one, but
# say so, because this path is the known-bad one and a quiet downgrade is how
# it goes unnoticed for weeks.
if [ "$SINK" = pulse ] && is_wsl && [ "${PAD_AUDIO_SINK:-auto}" = auto ]; then
    echo "[play] NOTE: no Windows Python with sounddevice, falling back to WSLg" >&2
    echo "[play] audio, which is measurably damaged. Fix with:" >&2
    pad_sounddevice_hint | sed 's/^/[play]   /' >&2
fi

# ---- relay sink: the macOS CONTAINER ---------------------------------------
# There is no audio server inside the box and VNC carries no sound, so the
# PCM leaves the same way it leaves WSL: raw bytes over loopback TCP. Only the
# LISTENER runs here - padbox.sh publishes the port, polls the guest's fmt
# file for the rate (docker exec), and runs the Mac-side speaker; when this
# script dies the kernel closes the socket and takes that player with it.
# Same padrelay.py as the win sink below, for the same load-bearing reason:
# it listens FIRST and opens the FIFO only once a player attaches, where an
# ffmpeg would block on the silent FIFO and never open the socket at all.
if [ "$SINK" = relay ]; then
    PORT=${PAD_AUDIO_PORT:-45997}
    echo "[play] fifo $FIFO  ${RATE} Hz x ${CH} ch s16le -> host player (tcp/$PORT)"
    python3 "$(dirname "$0")/padrelay.py" "$FIFO" "$PORT" &
    SRV=$!
    trap 'kill $HOLD $SRV 2>/dev/null; rm -f "$FIFO"' EXIT
    wait $SRV
    exit 0
fi

if [ "$SINK" = win ]; then
    PORT=${PAD_AUDIO_PORT:-45997}
    echo "[play] fifo $FIFO  ${RATE} Hz x ${CH} ch s16le -> WINDOWS (tcp/$PORT)"
    echo "[play] bypassing WSLg audio entirely: $WINPY"

    # The FIFO, handed out as raw bytes by a relay that makes no decisions.
    # It is padrelay.py and NOT another ffmpeg, and the reason is load-bearing:
    # ffmpeg opens its INPUT before its OUTPUT, so `-i $FIFO ... -f s16le
    # tcp://...?listen=1` blocks on a FIFO that stays empty until the game first
    # makes a sound and NEVER OPENS THE SOCKET. The player then finds nothing to
    # connect to and the run is silent. padrelay.py listens first and opens the
    # FIFO only once a player has attached.
    python3 "$(dirname "$0")/padrelay.py" "$FIFO" "$PORT" &
    SRV=$!

    # TEARING DOWN A WINDOWS CHILD. The player is a native Windows process
    # reached through interop, so it is invisible to pgrep and to killgame.sh -
    # exactly the orphan class this rig exists to avoid.
    #
    # The normal path needs no help: the player leaves when its input ends, and
    # the socket ends whenever the server goes, INCLUDING on SIGKILL, because
    # the kernel closes a dead process's sockets. The backstop below is only for
    # a player that never connected or has wedged.
    #
    # It matches on OUR PORT, not on the image name. Killing every python.exe
    # would take out whatever else the user is running, and the old version of
    # this that matched ffplay.exe would have killed PAD's own audio preview.
    WINPID=""
    # `$_.Name -like 'py*'` is LOAD-BEARING: the PowerShell process running
    # this query has '*padplay.py*' and the port in its OWN command line, so
    # without the name filter it matches ITSELF and Stop-Process kills the
    # query mid-pipeline — observed killing the invoking WSL session outright.
    win_kill() {
        /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile \
            -Command "Get-CimInstance Win32_Process |
                      Where-Object { \$_.Name -like 'py*' -and
                                     \$_.CommandLine -like '*padplay.py*' -and
                                     \$_.CommandLine -like '* $PORT *' } |
                      ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" \
            >/dev/null 2>&1 || true
    }
    trap 'kill $HOLD $SRV 2>/dev/null; [ -n "$WINPID" ] && kill $WINPID 2>/dev/null;
          win_kill; rm -f "$FIFO"' EXIT

    # item 56's volume/mute knob reaches this Windows child ONLY through
    # WSLENV, same mechanism and same trap as PAD_PF_LOG/PAD_PF_FADE_*_MS in
    # watch.sh - a Windows process reached through interop gets none of this
    # shell's environment unless the name is listed here. No `/p`: unlike
    # PAD_PF_LOG (a WSL path translated for a Windows reader), this value is
    # already a native Windows path - emulate_tab.py computed it AS a Windows
    # process, so it needs no translation in either direction. Missing this
    # line is exactly why the knob shipped inert 2026-08-18: the file was
    # being written correctly and polled for correctly, but never actually
    # seen (confirmed at the desk: `env PAD_X=1 python.exe -c "..."` through
    # WSL interop with no WSLENV entry reads back None every time).
    #
    # SAME BUG, JUST FOUND, ON THE TWO KNOBS ALREADY HERE: PAD_AUDIO_PREBUFFER_MS
    # and PAD_AUDIO_LATENCY_MS are read by padplay.py the same way and were
    # NEVER forwarded either - the "350 ms, measured" / "60 ms" comments in
    # padplay.py were true of whatever invocation measured them, not of a run
    # through this win sink, where they have silently always been the
    # hard-coded default. Carried across now for the same reason as the
    # ctl file: nobody relies on today's (broken) behaviour, since there is
    # no GUI control for either and a developer setting them by hand for a
    # tuning experiment is exactly who this was failing.
    [ -n "${PAD_AUDIO_CTL:-}" ] && \
        export WSLENV="${WSLENV:+$WSLENV:}PAD_AUDIO_CTL"
    [ -n "${PAD_AUDIO_PREBUFFER_MS:-}" ] && \
        export WSLENV="${WSLENV:+$WSLENV:}PAD_AUDIO_PREBUFFER_MS"
    [ -n "${PAD_AUDIO_LATENCY_MS:-}" ] && \
        export WSLENV="${WSLENV:+$WSLENV:}PAD_AUDIO_LATENCY_MS"

    # NO READINESS PROBE HERE, deliberately. The obvious one - connect to the
    # port to see whether it is up yet - IS ITSELF A CLIENT: the relay accepts
    # it as the player, opens the FIFO for it and then sees it hang up ("player
    # connected" / "player went away" in the log for a player that was never
    # there). The retry loop below covers a listener that is not ready, which is
    # what the probe was for, so the probe only ever added a fake connection.
    #
    # RESTARTED IF IT DIES, because it is the speaker and a run that quietly
    # loses it is the "audio was silently dead for weeks" failure this rig has
    # already had once. The loop exits with the relay.
    (
        while kill -0 $SRV 2>/dev/null; do
            "$WINPY" "$(wslpath -w "$(dirname "$0")/padplay.py")" \
                127.0.0.1 "$PORT" "$RATE" "$CH"
            kill -0 $SRV 2>/dev/null || break
            echo "[play] Windows player exited; restarting it" >&2
            sleep 1
        done
    ) &
    WINPID=$!
    wait $SRV
    exit 0
fi

# NATIVE PLAYBACK - macOS and Linux, where there is no boundary to cross.
#
# Same player as the WSL bridge, reading the FIFO directly instead of a socket,
# so all three platforms share one queue, one pre-roll and one underrun policy.
# PortAudio drives CoreAudio on macOS and ALSA/PulseAudio on Linux. Only the
# transport differs between platforms, and only because WSL forces it to.
#
# Deliberately NOT used on WSL: PortAudio there would reach the speakers through
# WSLg's PulseAudio, which is the damaged hop this whole arrangement exists to
# avoid, so the player would be identical and the sound would not.
if ! is_wsl && python3 -c "import sounddevice" >/dev/null 2>&1; then
    echo "[play] fifo $FIFO  ${RATE} Hz x ${CH} ch s16le -> PortAudio (native)"
    exec python3 "$(dirname "$0")/padplay.py" --fifo "$FIFO" "$RATE" "$CH"
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
