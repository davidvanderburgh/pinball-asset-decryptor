#!/bin/bash
# ctl.sh <request...> | --stream - spkctl.py for callers that can only run
# bash scripts (the app's rig_cmd, the switch window's pipe).  While the
# slot runs a P-ROC game, proc/sppctl.py answers the same requests.
. "$(dirname "$0")/spkpath.sh"
spk_proc_alive && exec python3 "$SPK_PROC/sppctl.py" --slot "$SPK_SLOT" "$@"
exec python3 "$SPK_TOOLS/spkctl.py" --slot "$SPK_SLOT" "$@"
