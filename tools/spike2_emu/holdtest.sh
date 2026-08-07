#!/bin/bash
# holdtest.sh <log> [VAR=VAL ...] - HOW LONG BEFORE THE GAME WILL LEAVE TECH ALERTS.
#
#   wsl -e bash $RIG/holdtest.sh $HOME/gzx.log PAD_NB_RECOVER_US=5000
#
# Boots the game with auto-advance OFF, then holds Service Back every 2 s until
# it takes, and prints the wall-clock offset at which it did. That number is the
# whole point of the boot-time work, and it is the only honest way to compare a
# change: the alert lines clearing, the node board flags, and the timeout count
# are all things that can improve while the wait does not.
#
# t0 is the first byte in the run log, i.e. the game starting - the same t0
# boottime.sh uses, so the two are directly comparable.
. "$(dirname "$0")/padpath.sh"
set -u
LOG=${1:-$HOME/gzhold.log}
shift || true

bash "$RIG/killgame.sh" >/dev/null 2>&1
sleep 1
rm -f "$LOG"

# Extra VAR=VAL arguments are exported to the run, so an A/B is one line.
for kv in "$@"; do export "${kv?}"; done
export PAD_AUTO_ATTRACT=0 LOG="$LOG"
echo "[holdtest] $LOG  $*"

setsid bash "$RIG/watch.sh" 4 > "$HOME/watchhold.log" 2>&1 &

for i in $(seq 1 400); do [ -s "$LOG" ] && break; sleep 0.25; done
[ -s "$LOG" ] || { echo "[holdtest] the game never started"; exit 1; }
T0=$(date +%s.%N)
el() { echo "$T0 $(date +%s.%N)" | awk '{printf "%.1f", $2 - $1}'; }
c() { local n; n=$(grep -ac 'gst\] factory_make' "$LOG" 2>/dev/null); echo "${n:-0}"; }

i=0
while [ $i -lt 60 ]; do
    i=$((i + 1))
    now=$(el)
    if [ "$(c)" -gt 10 ]; then
        echo "[holdtest] RESULT t=${now}s after $((i - 1)) holds   $*"
        to=$(grep -ac 'ExchangeData: read failed' "$LOG"); echo "[holdtest] timeouts: $to"
        bash "$RIG/killgame.sh" >/dev/null 2>&1
        exit 0
    fi
    pgrep -x game >/dev/null || { echo "[holdtest] the game exited"; exit 1; }
    python3 "$RIG/swpoke.py" 28 1600 >/dev/null 2>&1
    sleep 2
done
echo "[holdtest] gave up after 60 holds"
bash "$RIG/killgame.sh" >/dev/null 2>&1
exit 1
