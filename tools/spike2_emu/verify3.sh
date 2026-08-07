#!/bin/bash
# verify3.sh <log> [seconds] - run with the audio-worker gate workaround and
# report. verify2.sh remains the BASELINE (no env, crashes at the queue null);
# this is the "past the wall" configuration.
#
#   PAD_THREAD_ENTRY=1  wraps every thread start so entry can be observed
#   PAD_AUDIO_UNGATE=1  makes the audio streaming worker (body 0x459604) do
#                       the re-reading wait on 0x7acb54 that its own code
#                       fails to do, because it loads the byte once and then
#                       spins on the register.
. "$(dirname "$0")/padpath.sh"
cd $HOME
L=${1:-gz91.log}
T=${2:-45}
S=$(date +%s)
# Via runlim.sh, NOT `timeout` - see the comment in runlim.sh. timeout leaves
# the game running forever at ~140% CPU because it only signals the shell.
bash $RIG/runlim.sh "$L" "$T" PAD_THREAD_ENTRY=1 PAD_AUDIO_UNGATE=1
E=$(date +%s)
echo "elapsed: $((E-S)) s   (the run is stopped by the time limit; it does not exit on its own)"
echo "=== milestone ==="
printf '  scenes with bytes read > 0 : %s / %s\n' \
  "$(awk '/\[scenebytes\]/ && $2+0>0' $L | wc -l)" "$(grep -ca '\[scenebytes\]' $L)"
printf '  Radium warnings            : %s\n' "$(grep -ca 'Radium Warning' $L)"
printf '  segv                       : %s\n' "$(grep -ca '\[segv\]' $L)"
printf '  frames presented           : %s\n' "$(grep -a '\[eglshim\].*fps' $L | tail -1)"
printf '  leftover game processes    : %s (MUST be 0)\n' \
  "$(ps -eo args | grep -c '[g]odzilla_pro/game')"
printf '  exceptions thrown          : %s\n' "$(grep -ca '\[throw\]' $L)"
printf '  ExchangeData errors        : %s\n' "$(grep -ca ExchangeData $L)"
echo "=== audio worker ==="
grep -a 'waited .* ms for gate' $L
printf '  ALSA writei calls          : %s\n' "$(grep -ca 'snd_pcm_writei' $L)"
echo "=== new numbered fatals ==="
tail -4 spike2root/dump/debug_log.txt
