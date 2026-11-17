# s3proof.sh - one emulator proof run of a Spike 3 port (PAD-1286; the recipe: docs/plans/spike3_modes.md,
# "The proof pass on a Spike 3 port"). As root in WSL, hidden and muted, on rig slot $SLOT:
#
#   [TITLE=<game>] PROOF=ballsave|game|mb|coil|mode|clock|census|stackmb|edge|spare  CARD=<name in D:\Pinball\images\Stern\spike3>  SLOT=88 \
#   CFG=save.cfg [CFG2=done.cfg] [SO=<a mode64.so>] [PORT=<a port>] TAG=<name> OUT=<a Windows dir as /mnt/c/...> \
#     bash s3proof.sh
#
# The mode files come from modes/ beside this script (CFG -> mode.cfg, CFG2 -> mode1.cfg); SO defaults to the
# repo's prebuilt mode64.so, PORT to ports/spike3/<game>-<version>.port by PORTNAME. play.sh plays the game (the
# title's switch names: titles/$TITLE.env, sourced first if TITLE names one - its card, port, mode-file folder, switch
# names and the trigger / shot bits the mode files are rewritten to, PAD-1288..1290). Logs land in $OUT: mode_<tag>.log (the runtime's),
# bridge_<tag>.log (the bus and the ball model's [ball] lines), play_<tag>.out, run_<tag>.out.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
SLOT=${SLOT:-88}; TAG=${TAG:-run}; OUT=${OUT:-/var/tmp/pad-s3proof}
if [ -n "${TITLE:-}" ]; then
    [ -f "$HERE/titles/$TITLE.env" ] || { echo "s3proof: no titles/$TITLE.env" >&2; exit 2; }
    set -a; . "$HERE/titles/$TITLE.env"; set +a        # exported: play.sh reads the switch names
fi
MODES=${MODES:-$HERE/modes}
CARD=/mnt/d/Pinball/images/Stern/spike3/${CARD:-star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw}
PORTNAME=${PORTNAME:-star_wars_elg-1.10.port}
# the title's switch names for play.sh (titles/<game>.env; Star Wars ELG's are play.sh's defaults)
if [ -n "${TITLE:-}" ]; then set -a; . "$HERE/titles/$TITLE.env"; set +a; fi
W=/var/tmp/pad-s3proof/s$SLOT; mkdir -p "$W/files" "$OUT"; rm -f "$W"/files/*
cp "${SO:-$REPO/tools/spike2_emu/modes/sdk/prebuilt/mode64.so}" "$W/mode64.so"
cp "${PORT:-$REPO/tools/spike2_emu/modes/sdk/ports/spike3/$PORTNAME}" "$W/files/game.port"
cp "$MODES/${CFG:-save.cfg}" "$W/files/mode.cfg"
[ -n "${CFG2:-}" ] && cp "$MODES/$CFG2" "$W/files/mode1.cfg"
# the mode files name Star Wars ELG's shot bits; another title's (its port's switch lines) from its titles/<game>.env
for f in "$W"/files/mode*.cfg; do
  [ -n "${TRIGGER_BITS:-}" ] && sed -i "s/^trigger \+0x[0-9a-fA-F]\+/trigger        $TRIGGER_BITS/" "$f"
  [ -n "${SHOT_BITS:-}" ] && sed -i "s/^shots .*/shots          $SHOT_BITS/" "$f"
done
D=/var/tmp/pad-s3/slot$SLOT/connectivity.up/dump
rm -f "$D/mode.log"
( PROOF=${PROOF:-game} bash "$HERE/play.sh" "$SLOT" > "$W/play_$TAG.out" 2>&1 ) &
env PAD_LABEL=${PAD_LABEL:-PAD-s3proof} PAD_HIDDEN=1 PAD_S3_BALLS_TRACE=1 PAD_S3_NBTRACE=${PAD_S3_NBTRACE:-0} PAD_S3_MODE_SO="$W/mode64.so" \
    PAD_S3_MODE_FILES="$W/files" bash "$REPO/tools/spike3_emu/s3run.sh" "$CARD" --slot "$SLOT" --fresh --bus --bridge \
    --secs "${SECS:-230}" > "$W/run_$TAG.out" 2>&1
echo "run exit $? ($(grep -a -m1 'cap' "$W/run_$TAG.out" || echo 'see run_'$TAG'.out'))"
wait
cp "$D/mode.log" "$OUT/mode_$TAG.log" 2>/dev/null
cp "$W/play_$TAG.out" "$W/run_$TAG.out" "$OUT/"
cp "/var/tmp/pad-s3/slot$SLOT/bridge.log" "$OUT/bridge_$TAG.log"
[ -f "/var/tmp/pad-s3/slot$SLOT/nbtrace.log" ] && cp "/var/tmp/pad-s3/slot$SLOT/nbtrace.log" "$OUT/nbtrace_$TAG.log"   # PAD_S3_NBTRACE=1 (PAD-1329)
tail -4 "$W/play_$TAG.out"
