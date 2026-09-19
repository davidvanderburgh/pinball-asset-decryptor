#!/bin/bash
# firereq130.sh <req> <reference.wav> [tag] - fire ONE sound request straight at the
# game, in quiet attract, and score what comes out.
#
# WHY NOT THROUGH THE MODE. Firing via the mode buries the sound in thirty seconds of
# game audio and ties it to one moment nobody can point at afterwards. padmode.so has
# a trigger for exactly this: /dump/padmode.sound holding "<req>" calls
# sound_request_play(req) from the game's own tick and logs
#   [trigger] sound_request_play(<req>) returned <rc>
# so the RETURN CODE comes back too - which says whether the worker even accepted it.
#
# THIS IS HALF OF A CONTROL. Run it first on the STOCK bank against the stock record's
# own decoded WAV: a high score there proves trigger -> play -> capture -> correlate
# works end to end. Only then does the same command on the re-pointed bank mean
# anything. Every earlier negative in item 130 rested on that chain being assumed.
cd /mnt/c/Users/david/Documents/development/pinball-asset-decryptor-wt/item-130/tools/spike2_emu || exit 1
. ./padpath.sh
REQ=${1:?usage: firereq130.sh <req> <reference.wav> [tag]}
WAV=${2:?need a reference wav}
TAG=${3:-fire}
D=$ROOT/dump
[ -f "$WAV" ] || { echo "no reference wav at $WAV" >&2; exit 1; }

echo "=== bank that is live ==="
bash modes/install_mode_sound.sh status 2>&1 | tail -1
echo "reference: $WAV"
echo "request:   $REQ"

A0=$(stat -c %s "$D/audio.raw" 2>/dev/null || echo 0)
P0=$(wc -l < "$D/padmode.log" 2>/dev/null || echo 0)
echo "mark: audio.raw $A0  padmode.log $P0"

# Attract is quiet, which is the point: fire into silence, five times, well spaced,
# so the capture has five clean chances and the envelope shows each one.
for i in 1 2 3 4 5; do
  echo "$REQ" > "$D/padmode.sound"
  sleep 8
done
sleep 4

echo "=== what the probe said (the return code is the interesting part) ==="
tail -n +$((P0 + 1)) "$D/padmode.log" | grep -a 'sound_request_play' | tail -10
echo "=== every sound event in the window ==="
tail -n +$((P0 + 1)) "$D/padmode.log" | grep -ac '\[sound\]'

A1=$(stat -c %s "$D/audio.raw")
echo "=== capture grew $A0 -> $A1 (+$((A1 - A0))) ==="
tail -c +$((A0 + 1)) "$D/audio.raw" > "/tmp/cap_$TAG.raw"
python3 "$RIG/modes/score_capture.py" "/tmp/cap_$TAG.raw" "$WAV" 48000 2 2>&1 | tail -6
echo "=== envelope, to see the five firings ==="
python3 "$RIG/modes/capture_envelope.py" "/tmp/cap_$TAG.raw" "$WAV" 48000 2 44 2>&1 | sed -n '1,20p'
echo "=== faults ==="
echo "segv $(grep -ac '\[segv\] pc' "$D/game.out")  fatal $(grep -ac 'uncaught target signal' "$D/game.out")"
