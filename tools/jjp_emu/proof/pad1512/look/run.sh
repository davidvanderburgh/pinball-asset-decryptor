#!/bin/bash
# PAD-1512 look proof on Wonka 03.03 (Wonka's own key attached): the attract game type menu
# restyled from title.cfg alone (modes/title.cfg: box, picture, colors, the game's own fonts).
# As root in Ubuntu, hidden and muted:  bash run.sh  (rc 0 = every wait in steps.txt met)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
EMU=$(cd "$HERE/../../.." && pwd)
export PAD_HIDDEN=1 PAD_AUDIO=0 PAD_LABEL=PAD-1512 JJP_ISO=${JJP_ISO:-/mnt/d/Pinball/images/JJP/Wonka-v03.03.iso}
export JJP_MODS_SO=${JJP_MODS_SO:-/var/tmp/pad1512/jjpmodes.so} JJP_MODS_DIR=$HERE/modes
bash "$EMU/watch.sh" || exit 3
export JJP_DISPLAY=${JJP_NESTED:-:1}        # grab.sh: the hidden run's own screen (display.sh)
python3 "$EMU/jjpdrive.py" "$HERE/steps.txt"
rc=$?
LOG=/var/tmp/jjp_run/jjpe/temp/jjpmodes.log
[ -f "$LOG" ] && cp -f "$LOG" "$HERE/jjpmodes.log"
bash "$EMU/killgame.sh" >/dev/null 2>&1      # the rig cleaned up as it goes
exit $rc
