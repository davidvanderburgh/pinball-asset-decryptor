#!/bin/bash
# Give the jail a working sound path: ALSA -> PulseAudio -> WSLg -> Windows.
#
# THE PROBLEM.  The game logs `aplay: no soundcards found` and its own
# scripts/audio/setup.pl gives up, because both look for a real ALSA card - a
# USB or PCI codec - and WSL has neither.  What WSL *does* have is a PulseAudio
# server (WSLg's, on /mnt/wslg/PulseServer, feeding an RDP sink that comes out
# of the Windows audio device).
#
# THE FIX is one config file.  liballegro_audio links libpulse-simple, libpulse
# AND libasound, and the image already ships ALSA's pulse plugin
# (libasound_module_pcm_pulse.so), so pointing ALSA's default PCM at pulse makes
# BOTH paths work at once - the game's Allegro audio and the shell tools
# (aplay/aplay -l) that the image's own scripts probe with.
#
# Note this does not try to satisfy setup.pl's `ps aux | grep pulseaudio
# --system=yes` test - that process genuinely does not exist here, setup.pl
# only logs about it, and the game does not care.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

[ "$(id -u)" = "0" ] || { echo "audio.sh: must run as root" >&2; exit 2; }
mountpoint -q "$JJP_JAIL" || { echo "audio.sh: jail not mounted; run jail.sh" >&2; exit 3; }

# 0. MUTED, when asked.  PAD_AUDIO=0 is the Spike 2 rig's knob and the rule
#    every run here follows unless somebody wants sound (David works beside
#    the runs): ALSA's default becomes the null device, so the game plays
#    into nothing, and the pulse cookie is not handed in.  The rest of this
#    script is skipped - there is no path to prove.
if [ "${PAD_AUDIO:-1}" = "0" ]; then
    cat > "$JJP_JAIL/etc/asound.conf" <<'ASOUND'
# Written by tools/jjp_emu/audio.sh with PAD_AUDIO=0 - the game is MUTED:
# every ALSA client plays into the null device.
pcm.!default {
    type null
}
ctl.!default {
    type null
}
ASOUND
    rm -f "$JJP_JAIL$JJPEDIR/$(jjp_title)/allegro5.cfg"
    echo "audio: muted (PAD_AUDIO=0) - ALSA default is the null device"
    exit 0
fi

# 1. ALSA -> pulse.  `fallback` keeps a bare `aplay` from hard-failing if the
#    server ever goes away mid-run.
cat > "$JJP_JAIL/etc/asound.conf" <<'ASOUND'
# Written by tools/jjp_emu/audio.sh - routes ALSA at PulseAudio, because WSL
# has no sound card but WSLg has a PulseAudio server.
pcm.!default {
    type pulse
    fallback "null"
}
ctl.!default {
    type pulse
    fallback "null"
}
ASOUND

# 2. The desktop user's cookie: PulseAudio refuses a root client with
#    "Access denied" because the socket belongs to them, not to root.
if [ -f "$JJP_PULSE_COOKIE" ]; then
    mkdir -p "$JJP_JAIL/root/.config/pulse"
    cp -f "$JJP_PULSE_COOKIE" "$JJP_JAIL/root/.config/pulse/cookie"
    chmod 600 "$JJP_JAIL/root/.config/pulse/cookie"
else
    echo "warning: no pulse cookie at $JJP_PULSE_COOKIE - audio will be denied" >&2
fi

# 3. ASK THE SERVER FIRST, from inside the jail, the way the game will.
#    Allegro told `driver=pulseaudio` with no PulseAudio behind it does NOT
#    fall back: the game exits 255 the instant it starts, with nothing in any
#    log - which is how David's Start from the tab read "Stopped" for no
#    visible reason on 2026-09-13, after WSLg's PulseAudio had died
#    ("Connection refused" on /mnt/wslg/PulseServer; the socket file stays).
#    A dead server therefore means a MUTED run that starts, said plainly,
#    never a silent one that does not.
GAMEDIR="$JJP_JAIL$JJPEDIR/$(jjp_title)"
PROBE=$(chroot "$JJP_JAIL" /bin/bash -c "export PULSE_SERVER=$JJP_PULSE HOME=/root; pactl info 2>&1 | head -12")
case "$PROBE" in
    *"Server String"*) ;;                       # answered
    *"command not found"*) echo "(no pactl inside the image - the server is not checked)" ;;
    *)
        cat > "$JJP_JAIL/etc/asound.conf" <<'ASOUND'
# Written by tools/jjp_emu/audio.sh - PulseAudio did not answer, so the game
# is MUTED: every ALSA client plays into the null device.
pcm.!default {
    type null
}
ctl.!default {
    type null
}
ASOUND
        rm -f "$GAMEDIR/allegro5.cfg"
        echo "audio: PulseAudio is not answering at $JJP_PULSE ($(printf '%s' "$PROBE" | head -1))"
        echo "audio: the game runs MUTED so that it starts at all; sound comes back once WSLg's"
        echo "audio: PulseAudio is up again (wsl --shutdown from Windows restarts it - it takes the rig down too)"
        exit 0 ;;
esac

# 4. Tell Allegro to use PulseAudio directly rather than discovering ALSA first.
#    Allegro reads allegro5.cfg from the executable's directory.  Use the title
#    actually mounted (jjp_title), not the JJP_GAME default - otherwise for any
#    title but Wonka this wrote into a directory that does not exist and the
#    audio config was silently never applied.
if [ -d "$GAMEDIR" ]; then
    cat > "$GAMEDIR/allegro5.cfg" <<'ACFG'
# Written by tools/jjp_emu/audio.sh
[audio]
driver=pulseaudio
ACFG
fi

# 5. Prove it end to end rather than declaring success.
echo "--- pulse server, as seen from inside the jail ---"
printf '%s\n' "$PROBE" | head -4
echo "--- aplay -l inside the jail ---"
chroot "$JJP_JAIL" /bin/bash -c 'aplay -l 2>&1 | head -4'
