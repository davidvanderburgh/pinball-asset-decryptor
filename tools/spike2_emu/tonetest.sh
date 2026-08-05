#!/bin/bash
# tonetest.sh - IS THE CRACKLE OURS? Twenty seconds, and it answers the only
# question worth asking first.
#
# WHY THIS EXISTS. On 2026-08-05 audio crackled and an entire afternoon went
# into instrumenting the emulator's audio path. Every measurement came back
# clean and every one of them was irrelevant:
#
#   - the guest's PCM: 0.002% clipped, 0.008% discontinuities (i.e. fine)
#   - the sink's output vs its input: byte-faithful, roughness 0.103 -> 0.095
#   - the sink delivered everything the guest produced
#   - halving the window's pixels changed nothing
#   - the suspected shim rebuild was 47 lines of logging
#
# All true. All beside the point. The damage was in the WSLg -> Windows RDP
# audio hop, which is DOWNSTREAM OF EVERY INSTRUMENT THAT EXISTS INSIDE WSL.
# `wsl --shutdown` fixed it in seconds.
#
# THE IDEA: a sine is clean BY CONSTRUCTION. Play one down the same path. If it
# crackles, no property of the emulator can be responsible - not its sample
# rate, not its buffer size, not its CPU load, not anything you changed today.
#
# THE TRAP THIS TOOL EXISTS TO AVOID: you cannot answer this by capturing
# RDPSink.monitor. That capture sits UPSTREAM of the broken hop and comes back
# pure whether or not the room is hearing static - measured, 0 of 280490
# samples off a perfect sine while it was audibly breaking up. There is no
# software oracle for this on the WSL side. IT HAS TO BE EARS.
#
# Usage: run it, listen to the TONE (not the game - the tone), answer honestly.
set -u

cat <<'EOF'
================================================================
 Listen to the TONE, not the game. It warbles on purpose - the
 pulsing is the test signal, NOT the fault. Listen for roughness,
 fizzing or breakup riding ON TOP of the tone.

   A: 44100 Hz, 40 ms buffer   (the game player's exact settings)
   ... 3 s silence ...
   B: 48000 Hz, 200 ms buffer  (sink's native rate, no resample)
================================================================
EOF

tone() {  # tone <rate> <buffer_ms> <label>
    ffmpeg -hide_banner -loglevel error \
        -f lavfi -i "sine=frequency=440:duration=10:sample_rate=$1" \
        -af "volume=6dB, tremolo=f=0.5:d=0.7" \
        -ac 2 -f pulse -buffer_duration "$2" "$3" 2>&1 | grep -v '^$' || true
}

echo "[tone] A ..."
tone 44100 40 "TONE A - game settings"
sleep 3
echo "[tone] B ..."
tone 48000 200 "TONE B - native rate, big buffer"

cat <<'EOF'

================================================================
 BOTH crackled   -> NOT THE EMULATOR. It is the WSLg -> Windows
                    audio hop. Close the game, then from Windows:
                        wsl --shutdown
                    Relaunch and it will be clean. If it survives
                    that, check Windows Sound > your output device
                    > Advanced: sample rate, and turn off any
                    "audio enhancements".

 ONLY A crackled -> the path is fine and our player's settings are
                    not: it feeds 44100 into a 48000 sink with a
                    40 ms buffer. Raise PAD_AUDIO_LATENCY_MS, and
                    consider resampling to 48000 in playaudio.sh.

 NEITHER crackled-> the path and the settings are both fine, so
                    the fault is specific to the live streamed
                    audio, which a pre-rendered tone does not
                    exercise. NOW go and instrument the rig.
================================================================
EOF
