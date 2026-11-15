# play.sh SLOT - plays one proof on a running Spike 3 slot (s3proof.sh starts it beside the run; PAD-1286).
# PROOF picks what is played after a game is started and its first ball plunged:
#   ballsave  wait out the game's own save, trigger the mode, drain inside its save, shoot the served ball, drain again
#   game      keep the ball in play HOLD s (a probe mode does the rest: place_probe_mode.c)
#   mb        trigger the mode, plunge the balls it serves, shoot, drain them one by one
#   coil      trigger the mode, shoot through its holds
#   stackmb   start the game's own multiball, trigger a `stack no` mode inside it, drain until it starts
#   mode      trigger the mode, score its shots, then keep the ball up until its clock ends it (PAD-1288)
# The title's switch names (Star Wars ELG 1.10's by default) - each list is `|`-separated:
TRIGGER_SW=${TRIGGER_SW:-TOP LANE CENTER}                   # the mode files' trigger (0x40 x3 on ELG)
SHOT_SWS=${SHOT_SWS:-CENTER TARGET|HIDDEN TARGET|LEFT LUKE ORBIT}  # three of its scoring shots (0x20000138)
EARLY_SWS=${EARLY_SWS:-LEFT LUKE ORBIT|HIDDEN TARGET}       # starts the game's own ball save right after the plunge
GAME_MB_SW=${GAME_MB_SW:-DEATH STAR TARGET}                 # x3 starts the game's own multiball
START_HOLD_MS=${START_HOLD_MS:-6000}                        # ELG's first-boot GAME SETUP screen takes a held Start
SETTLE_S=${SETTLE_S:-20}                                    # after the runtime is up, before the first Start
COINS=${COINS:-0}                                           # coins before each Start (a title not on free play)
AFTER_START_SWS=${AFTER_START_SWS:-}                        # pressed after each Start (a character select)
SLOT=${1:-88}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
P="python3 $REPO/tools/spike3_emu/s3press.py"
L=/var/tmp/pad-s3/slot$SLOT/connectivity.up/dump/mode.log
B=/var/tmp/pad-s3/slot$SLOT/bridge.log
sws() { local list s; IFS='|' read -r -a list <<< "$1"; for s in "${list[@]}"; do $P sw "$SLOT" "$s"; sleep "${2:-2}"; done; }
plunge() { $P plunge "$SLOT" 2>&1 | tail -1; }
drain() { $P drain "$SLOT" 2>&1 | tail -1; }

sleep 5; for i in $(seq 1 240); do grep -q "ready on\|\[mode\]\|armed" $L 2>/dev/null && break; sleep 1; done
echo "[play] ready after ${i}s"; sleep "$SETTLE_S"
for k in $(seq 1 8); do
  [ "$COINS" -gt 0 ] && { $P coin "$SLOT" "$COINS" >/dev/null; sleep 2; }
  [ "$START_HOLD_MS" -gt 0 ] && { $P sw "$SLOT" "START BUTTON" "$START_HOLD_MS"; sleep 7; }
  $P sw "$SLOT" "START BUTTON"; sleep 8
  [ -n "$AFTER_START_SWS" ] && sws "$AFTER_START_SWS" 3
  grep -q "in_game 0 -> 1\|\[probe\] in game" $L && break
done
echo "[play] game after $k start press(es)"; sleep 3
for k in $(seq 1 6); do out=$(plunge); echo "[play] plunge $k: $out"; echo "$out" | grep -q "nothing in the shooter" || break; sleep 4; done
grep -a "turned round" $B | tail -1 | sed 's/^/[play] /'

case ${PROOF:-game} in
ballsave)
  sleep 2; sws "$EARLY_SWS" 1
  echo "[play] waiting out the game's own ball save"; sleep 40
  for k in 1 2 3; do $P sw "$SLOT" "$TRIGGER_SW"; sleep 2; done
  echo "[play] triggers in"; sleep 3
  grep -E "START|BALL SAVE|ball save" $L | tail -3
  echo "[play] drain inside the save at $(date +%T): $(drain)"; sleep 8
  grep -a "\[ball\]" $B | grep -v keep-alive | tail -4
  echo "[play] plunge after: $(plunge)"; sleep 2
  sws "$SHOT_SWS"; sleep 6
  echo "[play] drain after the save at $(date +%T): $(drain)"; sleep 12
  grep -E "END|end of ball|ball ended" $L | tail -4 ;;
game)
  sleep "${HOLD:-70}" ;;
mb)
  sleep 4
  for k in 1 2 3; do $P sw "$SLOT" "$TRIGGER_SW"; sleep 2; done
  echo "[play] triggers in at $(date +%s)"
  for k in $(seq 1 8); do sleep 3; echo "[play] mb plunge $k: $(plunge)"; done
  sws "$SHOT_SWS"
  grep -E "multiball|balls" $L | tail -5
  for round in 1 2 3 4 5 6; do
    echo "[play] drain $round: $(drain)"; sleep 8
    grep -E "TEST.*END|ended|ours is over" $L | tail -1
  done
  sleep 10 ;;
coil)
  sleep 4
  for k in 1 2 3; do $P sw "$SLOT" "$TRIGGER_SW"; sleep 2; done
  echo "[play] triggers in at $(date +%s)"
  for r in $(seq 1 8); do sleep 4; sws "$SHOT_SWS" 1; done
  sleep 10 ;;
mode)
  sleep 4
  for k in 1 2 3; do $P sw "$SLOT" "$TRIGGER_SW"; sleep 2; done
  echo "[play] triggers in at $(date +%s)"; sleep 2
  for r in 1 2; do sws "$SHOT_SWS" 2; done
  echo "[play] shots in at $(date +%s); waiting out the clock"
  for k in $(seq 1 60); do grep -qE "TEST END|ended" $L && break; sleep 1; done
  grep -E "START|END|ended|score" $L | tail -8
  sleep 10 ;;
stackmb)
  sleep 4
  for k in 1 2 3; do $P sw "$SLOT" "$GAME_MB_SW"; sleep 2; done
  echo "[play] the game's own multiball asked for at $(date +%s)"
  for k in $(seq 1 6); do sleep 3; echo "[play] mb plunge $k: $(plunge)"; done
  for k in 1 2 3; do $P sw "$SLOT" "$TRIGGER_SW"; sleep 2; done
  echo "[play] the mode's trigger inside the game's multiball at $(date +%s)"; sleep 4
  for round in 1 2 3 4 5 6; do
    echo "[play] drain $round: $(drain)"; sleep 8
    $P sw "$SLOT" "$TRIGGER_SW"; sleep 3
    grep -q "STACK MB START" $L && { echo "[play] started after drain $round"; break; }
  done
  sleep 25 ;;
esac
echo "[play] done"
