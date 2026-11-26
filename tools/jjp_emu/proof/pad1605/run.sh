#!/bin/bash
# PAD-1605 proof on Wonka 03.03 (Wonka's own key attached): the Emulate tab's Try it start - the
# settings straight to watch.sh as rig_cmd_root passes them, the runtime built for the ISO and the
# title's mode folder - hidden and muted.  As root in the default Linux:
#   bash run.sh <jjpmodes.so> <mode folder>      (rc 0 = every wait in steps.txt met)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
EMU=$(cd "$HERE/../.." && pwd)
env PAD_HIDDEN=1 PAD_AUDIO=0 PAD_LABEL=PAD-1605 JJP_MODS_SO="$1" JJP_MODS_DIR="$2" \
    bash "$EMU/watch.sh" "${JJP_ISO:-/mnt/d/Pinball/images/JJP/Wonka-v03.03.iso}" || exit 3
export JJP_DISPLAY=${JJP_NESTED:-:1}
python3 "$EMU/jjpdrive.py" "$HERE/steps.txt"
rc=$?
LOG=/var/tmp/jjp_run/jjpe/temp/jjpmodes.log
[ -f "$LOG" ] && cp -f "$LOG" "$HERE/jjpmodes.log"
bash "$EMU/killgame.sh" >/dev/null 2>&1
exit $rc
