#!/bin/bash
# presstest.sh <switch-id> <ms> [log] - does ONE press of this switch, for this
# long, leave Tech Alerts?
#
#   wsl -e bash $RIG/presstest.sh 28 600
#
# Boots with auto-advance off, waits for the node bus timeout storm to go quiet
# (the point at which the game starts accepting an operator at all), presses
# ONCE, and says whether it took.
#
# ONE PRESS PER BOOT, NECESSARILY. Once the game leaves Tech Alerts the question
# cannot be asked again in the same run, so every candidate costs a fresh boot
# (~45 s). That is why this is a script and not something typed each time.
. "$(dirname "$0")/padpath.sh"
set -u
SW=${1:?switch id}
MS=${2:?hold milliseconds}
LOG=${3:-$HOME/gzpress.log}

bash "$RIG/killgame.sh" >/dev/null 2>&1
sleep 5                     # let the previous renderer release its ring, or
                            # the next one dies on startup
rm -f "$LOG"
export PAD_AUTO_ATTRACT=0 LOG="$LOG"
nohup setsid bash "$RIG/watch.sh" 4 \
    > "$HOME/watchpress.log" 2>&1 < /dev/null &
disown

for i in $(seq 1 400); do [ -s "$LOG" ] && break; sleep 0.25; done
[ -s "$LOG" ] || { echo "id=$SW ms=$MS  GAME NEVER STARTED"; exit 1; }

c() { local n; n=$(grep -ac 'gst\] factory_make' "$LOG" 2>/dev/null); echo "${n:-0}"; }
p() { local n; n=$(grep -ac 'ExchangeData: read failed' "$LOG" 2>/dev/null); echo "${n:-0}"; }

# same readiness test autoattract.sh uses: the storm must start, then go quiet
still=0; seen=0; last=$(p); w=0
while [ "$w" -lt 120 ]; do
    sleep 1; w=$((w + 1))
    now=$(p)
    if [ "$now" != "$last" ]; then seen=1; still=0; last=$now; continue; fi
    [ "$seen" = 0 ] && continue
    still=$((still + 1)); [ "$still" -ge 2 ] && break
done

before=$(c)
python3 "$RIG/swpoke.py" "$SW" "$MS" >/dev/null 2>&1
sleep 6
after=$(c)
if [ "$after" -gt 10 ]; then
    echo "id=$SW ms=$MS  WORKED   (factory_make $before -> $after, ready at ${w}s)"
else
    echo "id=$SW ms=$MS  no effect (factory_make $before -> $after, ready at ${w}s)"
fi
bash "$RIG/killgame.sh" >/dev/null 2>&1
