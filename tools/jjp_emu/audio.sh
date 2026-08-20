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

# 3. Tell Allegro to use PulseAudio directly rather than discovering ALSA first.
#    Allegro reads allegro5.cfg from the executable's directory.  Use the title
#    actually mounted (jjp_title), not the JJP_GAME default - otherwise for any
#    title but Wonka this wrote into a directory that does not exist and the
#    audio config was silently never applied.
GAMEDIR="$JJP_JAIL$JJPEDIR/$(jjp_title)"
if [ -d "$GAMEDIR" ]; then
    cat > "$GAMEDIR/allegro5.cfg" <<'ACFG'
# Written by tools/jjp_emu/audio.sh
[audio]
driver=pulseaudio
ACFG
fi

# 4. Prove it end to end rather than declaring success.
echo "--- pulse server, as seen from inside the jail ---"
chroot "$JJP_JAIL" /bin/bash -c "export PULSE_SERVER=$JJP_PULSE HOME=/root; pactl info 2>&1 | head -4" \
    || echo "(no pactl inside the image - not fatal)"
echo "--- aplay -l inside the jail ---"
chroot "$JJP_JAIL" /bin/bash -c 'aplay -l 2>&1 | head -4'
