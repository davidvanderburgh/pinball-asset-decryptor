#!/bin/bash
# PAD-1515 proof on Wonka 03.03 (Wonka's own key attached): the layout editor's places drawn by the
# runtime - the attract menu's box, heading, lines and hint; a mode's panel, title, total, timer and
# picture; a wizard's progress panes each in a box of its own.  Shots in /var/tmp/pad1515.
# As root in Ubuntu, hidden and muted:  bash run.sh  (rc 0 = every wait in steps.txt met)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
EMU=$(cd "$HERE/../.." && pwd)
mkdir -p /var/tmp/pad1515
export PAD_HIDDEN=1 PAD_AUDIO=0 PAD_LABEL=PAD-1515 JJP_ISO=${JJP_ISO:-/mnt/d/Pinball/images/JJP/Wonka-v03.03.iso}
export JJP_MODS_SO=${JJP_MODS_SO:-/var/tmp/pad1515/jjpmodes.so} JJP_MODS_DIR=${JJP_MODS_DIR:-$HERE/modes}
# the runtime, built against the image's glibc whenever jjpmodes.c is newer than it
if [ ! -f "$JJP_MODS_SO" ] || [ "$EMU/jjpmodes.c" -nt "$JJP_MODS_SO" ]; then
    bash "$EMU/mount.sh" "$JJP_ISO" && bash "$EMU/jail.sh" && bash "$EMU/buildmods.sh" || exit 2
fi
# two of the game's own modes, a switch each; one switch ends either (the wizard's progress board)
export JJP_MODS_TEST_GAMEMODE=cl_mode,mtv_mode
export JJP_MODS_TEST_SWITCH=switch_target_bank_1,switch_target_bank_2
export JJP_MODS_TEST_END_SWITCH=switch_target_l_loop
bash "$EMU/watch.sh" || exit 3
export JJP_DISPLAY=${JJP_NESTED:-:1}        # grab.sh: the hidden run's own screen (display.sh)
python3 "$EMU/jjpdrive.py" "${STEPS:-$HERE/steps.txt}"
rc=$?
LOG=/var/tmp/jjp_run/jjpe/temp/jjpmodes.log
[ -f "$LOG" ] && cp -f "$LOG" /var/tmp/pad1515/jjpmodes.log
bash "$EMU/killgame.sh" >/dev/null 2>&1      # the rig cleaned up as it goes
exit $rc
