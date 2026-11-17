# play.sh SLOT - plays one proof on a running Spike 3 slot (s3proof.sh starts it beside the run; PAD-1286).
# PROOF picks what is played after a game is started and its first ball plunged (explore: EXPLORE_SEQ, PAD-1292):
#   ballsave  wait out the game's own save, trigger the mode, drain inside its save, shoot the served ball, drain again
#   game      keep the ball in play HOLD s (a probe mode does the rest: place_probe_mode.c)
#   mb        trigger the mode, plunge the balls it serves, shoot, drain them one by one
#   coil      trigger the mode, shoot through its holds
#   mode      trigger the mode, score its shots, keep the ball up until its clock ends it (PAD-1288..1290)
#   census    press every switch in CENSUS_NAMES once, print the id each reached the modes with (s3census.sh)
#   clock     the same as `mode`'s wait-out-the-clock play (PAD-1290, PAD-1291: 54 shots for 54 presses with allshots.cfg),
#             reachable by its own name: `coil|mode)` above is the case bash runs for PROOF=mode
#   stackmb   start the game's own multiball, trigger a `stack no` mode inside it, drain until it starts
#   edge      (PAD-1322) the flipper buttons in attract, then in play the trigger, the scoring shots, a slingshot, a
#             pop bumper and the flipper buttons: with `value switch_edge_log N` in the port, every edge is logged
#   spare     (PAD-1329) with spare_sweep_mode.c in the runtime (SO=): close the input its `sweep:` line names on the
#             board (s3press.py set) twice, 3 s each; its shot pulses the spare output it names (the bridge's nbtrace)
# The title's switch names (Star Wars ELG 1.10's by default) - each list is `|`-separated:
TRIGGER_SW=${TRIGGER_SW:-TOP LANE CENTER}                   # the mode files' trigger (0x40 x3 on ELG)
SHOT_SWS=${SHOT_SWS:-CENTER TARGET|HIDDEN TARGET|LEFT LUKE ORBIT}  # three of its scoring shots (0x20000138)
EARLY_SWS=${EARLY_SWS:-LEFT LUKE ORBIT|HIDDEN TARGET}       # starts the game's own ball save right after the plunge
GAME_MB_SW=${GAME_MB_SW:-DEATH STAR TARGET}                 # x3 starts the game's own multiball
GAME_MB_SWS=${GAME_MB_SWS:-}                                # or these, once each in turn (a title's lock sequence)
GAME_MB_TIMES=${GAME_MB_TIMES:-3}                            # GAME_MB_SW (a | list: in turn) played this many times (PAD-1291)
FLIP_SWS=${FLIP_SWS:-L FLIPPER BUTTON|R FLIPPER BUTTON}      # the flipper buttons (PROOF=edge)
NOHANDLER_SWS=${NOHANDLER_SWS:-LEFT SLINGSHOT|RIGHT POP BUMPER}   # switches the drain runs no handler for (PROOF=edge)
START_HOLD_MS=${START_HOLD_MS:-6000}                        # ELG's first-boot GAME SETUP screen takes a held Start
ATTRACT_WAIT=${ATTRACT_WAIT:-${SETTLE_S:-20}}               # after the runtime is up, before the first Start (WDR: ~60)
COINS=${COINS:-0}                                           # credits first (Walking Dead Remastered's fresh settings: 4; Pokemon LE is not on free play)
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
echo "[play] ready after ${i}s"; sleep "${ATTRACT_WAIT:-20}"   # Walking Dead Remastered takes a Start only ~60 s on
if [ "${PROOF:-game}" = edge ]; then
  echo "[play] attract: the flipper buttons at $(date +%T)"; IFS='|' read -r -a fl <<< "$FLIP_SWS"
  for s in "${fl[@]}"; do $P sw "$SLOT" "$s" 400; sleep 2; done
fi
[ "$COINS" -gt 0 ] && { $P coin "$SLOT" "$COINS"; sleep 3; }
for k in $(seq 1 8); do
  # a retry drops its coins again: coins dropped while the game is still booting are not counted (PAD-1289, Pokemon)
  [ "$COINS" -gt 0 ] && [ "$k" -gt 1 ] && $P coin "$SLOT" "$COINS" > /dev/null 2>&1
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
coil|mode)
  sleep 4
  for k in 1 2 3; do $P sw "$SLOT" "$TRIGGER_SW"; sleep 2; done
  echo "[play] triggers in at $(date +%s)"
  for r in $(seq 1 8); do sleep 4; sws "$SHOT_SWS" 1; done
  sleep 10 ;;
clock)
  sleep 4
  for k in 1 2 3; do $P sw "$SLOT" "$TRIGGER_SW"; sleep 2; done
  echo "[play] triggers in at $(date +%s)"; sleep 2
  for r in 1 2; do sws "$SHOT_SWS" 2; done
  echo "[play] shots in at $(date +%s); waiting out the clock"
  for k in $(seq 1 90); do grep -qE "END|ended" $L && break; sleep 1; done
  grep -E "START|END|ended|score" $L | tail -8
  sleep 10 ;;
census)
  sleep 6
  while IFS= read -r n; do
    [ -n "$n" ] || continue
    b=$(grep -c "\[probe\] shot" $L); $P sw "$SLOT" "$n" < /dev/null > /dev/null 2>&1; sleep 1.6
    m=$(grep "\[probe\] shot" $L | tail -n +$((b+1)) | head -1 | awk '{print $NF}')
    [ -n "$m" ] && echo "[census] $(python3 -c 'import sys; print(int(sys.argv[1].replace("_", ""), 16).bit_length() - 1 + 64 * int(sys.argv[2]))' "$m" "${CENSUS_HALF:-0}") $n"       || echo "[census] - $n"
  done < "$CENSUS_NAMES" ;;
stackmb)
  sleep 4
  if [ -n "${GAME_MB_SWS:-}" ]; then sws "$GAME_MB_SWS" 2; else for k in $(seq 1 "${GAME_MB_TIMES:-3}"); do sws "$GAME_MB_SW" 2; done; fi
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
explore)   # PAD-1292: what starts a title's own multiball - EXPLORE_SEQ="SWITCH*hits|..." , the trough after each
  sleep 4; IFS='|' read -r -a steps <<< "$EXPLORE_SEQ"
  for e in "${steps[@]}"; do
    s=${e%\**}; n=${e##*\*}; [ "$n" = "$e" ] && n=1
    for k in $(seq 1 "$n"); do $P sw "$SLOT" "$s"; sleep 2; done
    sleep 3; echo "[play] after $s x$n: $(plunge)"
  done
  sleep 10 ;;
edge)
  sleep 4
  for k in 1 2 3; do $P sw "$SLOT" "$TRIGGER_SW"; sleep 2; done
  echo "[play] triggers in at $(date +%T)"; sleep 3
  for r in 1 2; do
    echo "[play] round $r: shots"; sws "$SHOT_SWS" 2
    echo "[play] round $r: no-handler switches"; sws "$NOHANDLER_SWS" 2
    echo "[play] round $r: flipper buttons"; IFS='|' read -r -a fl <<< "$FLIP_SWS"
    for s in "${fl[@]}"; do $P sw "$SLOT" "$s" 600; sleep 2; done
  done
  sleep 10 ;;
spare)
  for i in $(seq 1 60); do grep -q "sweep: input" $L && break; sleep 1; done
  ln=$(grep -a -m1 "sweep: input" $L); echo "[play] $ln"
  io=$(echo "$ln" | sed -n 's/.*sweep: input \([0-9]*\):\([0-9]*\) .*/\1 \2/p')
  [ -n "$io" ] || { echo "[play] no spare input chosen"; exit 0; }
  for r in 1 2; do
    echo "[play] round $r: spare input $io closed at $(date +%T)"; $P set "$SLOT" $io 1; sleep 3
    echo "[play] round $r: spare input $io open at $(date +%T)"; $P set "$SLOT" $io 0; sleep 6
  done
  sleep 5 ;;
esac
echo "[play] done"
