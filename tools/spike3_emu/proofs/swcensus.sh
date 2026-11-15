# swcensus.sh - which id a Spike 3 game hands its switch_hit site for each playfield switch (PAD-1291). As root in WSL,
# hidden and muted, on rig slot $SLOT:
#
#   TITLE=<game> SLOT=191 PORT=<a draft port> OUT=<a Windows dir as /mnt/c/...> bash swcensus.sh
#
# A switch's id is NOT always its rank in the program's device table (s3port.py's guess): Star Wars 2025 Pro 0.84 numbers
# its Right target after every other playfield switch, and each one after it one lower. This boots the card with the
# draft port (its switch_hit sites hooked, `value switch_hit_log` on), starts a game, then presses each switch the draft
# names, one at a time, and waits for the runtime's `switch hit: switch N` line before the next: $OUT/census.txt gets
# `<id> <NAME>` per switch, `# no switch hit: <NAME>` for one the game sent none for (s3census.sh's format: kept as
# titles/<game>-<version>.switch_ids). `s3port.py ... --switch-ids census.txt`
# writes the port's switch lines from it. Logs: $OUT/census_mode.log, census_run.out.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
if [ -n "${TITLE:-}" ]; then set -a; . "$HERE/titles/$TITLE.env"; set +a; fi
SLOT=${SLOT:-88}; OUT=${OUT:-/var/tmp/pad-s3proof}
CARD=/mnt/d/Pinball/images/Stern/spike3/${CARD:-star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw}
PORT=${PORT:-$REPO/tools/spike2_emu/modes/sdk/ports/spike3/${PORTNAME:-star_wars_elg-1.10.port}}
W=/var/tmp/pad-s3proof/s$SLOT; mkdir -p "$W/files" "$OUT"; rm -f "$W"/files/*
cp "${SO:-$REPO/tools/spike2_emu/modes/sdk/prebuilt/mode64.so}" "$W/mode64.so"
grep -v '^value switch_hit_log' "$PORT" > "$W/files/game.port"; echo "value switch_hit_log    400" >> "$W/files/game.port"
cp "$HERE/modes/clock.cfg" "$W/files/mode.cfg"      # the runtime arms its hooks for a mode; this one's trigger is ELG's
P="python3 $REPO/tools/spike3_emu/s3press.py"
L=/var/tmp/pad-s3/slot$SLOT/connectivity.up/dump/mode.log; rm -f "$L"
mapfile -t NAMES < <(awk '$1 == "switch" { $1 = $2 = $3 = ""; sub(/^ +/, ""); print toupper($0) }' "$PORT")
: > "$OUT/census.txt"
(
  sleep 5; for i in $(seq 1 240); do grep -q "armed" "$L" 2>/dev/null && break; sleep 1; done; sleep "${ATTRACT_WAIT:-20}"
  for k in 1 2 3 4 5 6; do
    [ "${COINS:-0}" -gt 0 ] && { $P coin "$SLOT" "$COINS" >/dev/null; sleep 2; }
    [ "${START_HOLD_MS:-0}" -gt 0 ] && { $P sw "$SLOT" "START BUTTON" "$START_HOLD_MS"; sleep 7; }
    $P sw "$SLOT" "START BUTTON"; sleep 8
    grep -q "in_game 0 -> 1" "$L" && break
  done
  echo "# a game after $k start press(es)" >> "$OUT/census.txt"
  $P plunge "$SLOT" >/dev/null; sleep 6
  for s in "${NAMES[@]}"; do
    before=$(grep -c "switch hit:" "$L")
    $P sw "$SLOT" "$s" >/dev/null
    id=
    for t in $(seq 1 30); do
      sleep 0.1
      n=$(grep -c "switch hit:" "$L")
      [ "$n" -gt "$before" ] && { id=$(grep "switch hit:" "$L" | sed -n "$((before + 1))p" | awk '{print $NF}'); break; }
    done
    if [ -n "$id" ]; then echo "$id $s"; else echo "# no switch hit: $s"; fi >> "$OUT/census.txt"
    sleep 1.5
    # a late hit (a slow switch) must not be read as the next one's
    while [ "$(grep -c "switch hit:" "$L")" -gt "$((before + 1))" ] || { [ -z "$id" ] && [ "$(grep -c "switch hit:" "$L")" -gt "$before" ]; }; do
      echo "# a late hit after $s: $(grep "switch hit:" "$L" | tail -1 | awk '{print $NF}')" >> "$OUT/census.txt"; break
    done
  done
  echo "# done" >> "$OUT/census.txt"
) &
env PAD_LABEL=${PAD_LABEL:-PAD-s3census} PAD_HIDDEN=1 PAD_S3_MODE_SO="$W/mode64.so" PAD_S3_MODE_FILES="$W/files" \
    bash "$REPO/tools/spike3_emu/s3run.sh" "$CARD" --slot "$SLOT" --fresh --bus --bridge --secs "${SECS:-360}" \
    > "$OUT/census_run.out" 2>&1
wait
cp "$L" "$OUT/census_mode.log" 2>/dev/null
grep -c '^[0-9]' "$OUT/census.txt" | sed 's/$/ switch(es) sent an id/'
