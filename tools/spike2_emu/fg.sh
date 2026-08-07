#!/bin/bash
# fg.sh - list the FG_* flag-name strings around the validation flag, and count
# them. FG_GAME_VALIDATION_ERROR_PERM_MESSAGE is the name of the condition the
# Tech Alerts screen reports, so the surrounding names are the rest of the set.
. "$(dirname "$0")/padpath.sh"
cd $ROOT/games/godzilla_pro
echo "=== total FG_ strings ==="
strings -td game | grep -c ' FG_'
echo "=== 40 around the validation one ==="
strings -td game | grep ' FG_' | grep -n . | sed -n '1,400p' | grep -A6 -B6 'VALIDATION'
