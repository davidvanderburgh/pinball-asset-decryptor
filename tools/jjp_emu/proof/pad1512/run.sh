#!/bin/bash
# PAD-1512 proof on Wonka 03.03 (Wonka's own key attached): the attract game type menu, a game
# type's start, start_all with its progress board, and a mode's code hearing the game's modes.
# As root in Ubuntu, hidden and muted:  bash run.sh  (rc 0 = every wait in steps.txt met)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
EMU=$(cd "$HERE/../.." && pwd)
export PAD_HIDDEN=1 PAD_AUDIO=0 PAD_LABEL=PAD-1512 JJP_ISO=${JJP_ISO:-/mnt/d/Pinball/images/JJP/Wonka-v03.03.iso}
export JJP_MODS_SO=${JJP_MODS_SO:-/var/tmp/pad1512/jjpmodes.so} JJP_MODS_DIR=$HERE/modes
# three of the game's own modes (two Mode objects and a multiball), a switch each; one switch ends any
export JJP_MODS_TEST_GAMEMODE=cl_mode,mtv_mode,gobstopper_mb
export JJP_MODS_TEST_SWITCH=switch_target_bank_1,switch_target_bank_2,switch_target_bank_3
export JJP_MODS_TEST_END_SWITCH=switch_target_l_loop
bash "$EMU/watch.sh" || exit 3
export JJP_DISPLAY=${JJP_NESTED:-:1}        # grab.sh: the hidden run's own screen (display.sh)
python3 "$EMU/jjpdrive.py" "$HERE/steps.txt"
rc=$?
LOG=/var/tmp/jjp_run/jjpe/temp/jjpmodes.log
[ -f "$LOG" ] && cp -f "$LOG" "$HERE/jjpmodes.log"
bash "$EMU/killgame.sh" >/dev/null 2>&1      # the rig cleaned up as it goes
exit $rc
