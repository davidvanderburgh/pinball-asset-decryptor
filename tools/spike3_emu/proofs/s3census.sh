# s3census.sh - measures on the rig which switch id each of a Spike 3 draft port's switch lines really has (PAD-1290:
# Star Wars 2025 LE numbers its switches unlike its device table's order). As root in WSL, hidden and muted:
#
#   TITLE=<game> DRAFT=<a draft port> SLOT=190 OUT=<a Windows dir as /mnt/c/...> bash s3census.sh
#
# Two runs (ids 0-63, then 64-127): the draft's own lines with its switch lines swapped for one bit per id, and
# shot_probe_mode.c logging every shot; play.sh (PROOF=census) starts a game and presses each switch line's switch once.
# Writes $OUT/<game>.switch_ids (`<id> <NAME>` per switch that reached the modes) for `s3port.py ... --switch-ids`.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SLOT=${SLOT:-190}; OUT=${OUT:-/var/tmp/pad-s3census}; mkdir -p "$OUT"
W=/var/tmp/pad-s3census/s$SLOT; mkdir -p "$W"
bash "$HERE/build_probe.sh" "$W/shotprobe64.so" "$HERE/shot_probe_mode.c" > "$W/build.out" 2>&1 || { tail -5 "$W/build.out"; exit 1; }
grep '^switch ' "$DRAFT" | awk '{$1 = $2 = $3 = ""; sub(/^ +/, ""); print toupper($0)}' > "$W/names.txt"
for h in 0 1; do
  { grep -v '^switch ' "$DRAFT"
    for i in $(seq $((64 * h)) $((64 * h + 63))); do printf 'switch %d 0x%x id%d\n' "$i" $((1 << (i - 64 * h))) "$i"; done
  } > "$W/census$h.port"
  CENSUS_HALF=$h CENSUS_NAMES="$W/names.txt" PROOF=census CFG=clock.cfg SO="$W/shotprobe64.so" PORT="$W/census$h.port" \
    TAG=census$h SECS=${SECS:-200} OUT="$OUT" bash "$HERE/s3proof.sh"
done
{ echo "# ${TITLE:-?} switch ids measured on the rig by s3census.sh ($(date +%F), slot $SLOT): <id> <NAME>"
  grep -h '^\[census\] [0-9]' "$OUT/play_census0.out" "$OUT/play_census1.out" | cut -d' ' -f2-
} > "$OUT/${TITLE:-census}.switch_ids"
echo "$(grep -vc '^#' "$OUT/${TITLE:-census}.switch_ids") of $(wc -l < "$W/names.txt") switches reached the modes:" \
     "$OUT/${TITLE:-census}.switch_ids"
