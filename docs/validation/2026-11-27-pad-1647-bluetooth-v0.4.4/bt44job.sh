#!/bin/bash
# PAD-1647 job: bt44job.sh <key> <card>
# spike-pinball-bluetooth v0.4.4 (the armv7 archive exactly as the app's plugin store holds it) in the guest's
# /usr/local/spikebt, its helper on the demo backend, its menu.so preloaded into the card's own game. Reaches
# attract, writes down what his menu said of the game, then walks the presses in PAD1647_SEQ, photographing the
# screen after each one.
#   tokens: SEL PLUS MINUS BACK LF RF ACT START (a press), LFH (left flipper held 2.5 s), ACTH (Action held 1.5 s),
#           wN (wait N game seconds)
RIG=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1647/tools/spike2_emu
. "$RIG/rigjob.sh"
job_begin "${1:?key}" "${2:?card}"
G=$ROOT
STORE=/mnt/c/tmp/PAD-1647/store/bluetooth
rm -rf "$G/dump/spikebt" "$G/usr/local/spikebt" "$G/tmp/spikebt-game.log" "$G/dump/pad1647"
mkdir -p "$G/usr/local/spikebt" "$G/dump/pad1647"
tar xzf "$STORE/spike-pinball-bluetooth-armv7.tar.gz" -C "$G/usr/local/spikebt"
( cd "$G/usr/local/spikebt" && sha256sum -c SHA256SUMS ) > "$JOB_OUT/sums.txt" 2>&1 || job_fail "the release's own SHA256SUMS does not check out in the guest"
sha256sum "$STORE"/*.tar.gz > "$JOB_OUT/archives.txt"
cat > "$G/dump/pad1647/pre.sh" <<'EOF'
#!/bin/sh
mkdir -p /dump/spikebt; chmod 700 /dump/spikebt; rm -f /dump/spikebt/demo.sock
/usr/local/spikebt/spikebt --backend=demo --socket=/dump/spikebt/demo.sock \
    --state=/dump/spikebt/demo-state.json >> /dump/spikebt/helper.log 2>&1 &
t=0; while [ ! -S /dump/spikebt/demo.sock ] && [ $t -lt 30 ]; do sleep 1; t=$((t+1)); done
EOF
chmod 755 "$G/dump/pad1647/pre.sh"
if [ -n "${PAD1647_CARDMODES:-}" ]; then   # the card's OWN modes and runtime, in the card's order (runtime left of his menu)
    so=$(PAD_MODE_SO= bash "$RIG/modes/cardmodes.sh" "$CARD" | tail -1)
    [ -n "$so" ] || job_fail "the card has no mode runtime"
    export PAD_MODE_SO="$so:/usr/local/spikebt/menu.so" PAD_CARD_MODES=0
    job_say "preload: $PAD_MODE_SO"
elif [ -n "${PAD1647_MODE:-}" ]; then   # PAD's own mode runtime on the card as well, in the card's order (left of his)
    cp "$RIG/modes/sdk/prebuilt/mode.so" "$G/lib/pad1647_mode.so"
    export PAD_MODE_SO=/lib/pad1647_mode.so:/usr/local/spikebt/menu.so PAD_CARD_MODES=0
else
    export PAD_TRACE_SO=/usr/local/spikebt/menu.so
fi
export PAD_PREGAME=/dump/pad1647/pre.sh SPIKEBT_BACKEND=demo
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-600}" || { cp "$G/tmp/spikebt-game.log" "$G/dump/spikebt/helper.log" "$JOB_OUT/" 2>/dev/null; job_fail "$JOB_WHY"; }
job_sleep 6
job_shot "$JOB_OUT/00_attract.png"
for m in /proc/[0-9]*/maps; do
    if grep -q 'spikebt/menu.so' "$m" 2>/dev/null; then
        echo "pid ${m%/maps}: $(grep -o '/[^ ]*\.so' "$m" | sort -u | grep -v '^/lib/\|^/usr/lib/' | tr '\n' ' ')"
    fi
done > "$JOB_OUT/game_maps.txt" 2>&1
cp "$G/tmp/spikebt-game.log" "$JOB_OUT/" 2>/dev/null
sw() { awk -v n="$1" '!/^#/ && toupper($0) ~ n {print $1; exit}' "$LIST"; }
SEL=$(sw "SERVICE SELECT"); PLUS=$(sw "SERVICE PLUS"); MINUS=$(sw "SERVICE MINUS"); BACK=$(sw "SERVICE BACK")
LF=$(sw "LEFT FLIPPER BUTTON"); RF=$(sw "RIGHT FLIPPER BUTTON"); ACT=$(sw "ACTION BUTTON"); START=$(sw "START BUTTON")
job_say "switches: select=$SEL plus=$PLUS minus=$MINUS back=$BACK lf=$LF rf=$RF action=$ACT start=$START"
press() { python3 "$RIG/swpoke.py" "$1" "${3:-300}" > /dev/null 2>&1 < /dev/null; job_sleep "${2:-2}"; }
n=0
SEQ=${PAD1647_SEQ:-SEL_SEL_MINUS_SEL}
for tok in ${SEQ//_/ }; do
    n=$((n+1))
    case "$tok" in
        SEL) press "$SEL" 3 ;; PLUS) press "$PLUS" ;; MINUS) press "$MINUS" ;; BACK) press "$BACK" ;;
        LF) press "$LF" 2 300 ;; RF) press "$RF" 2 300 ;; ACT) press "$ACT" 3 ;; START) press "$START" 4 ;;
        LFH) press "$LF" 4 2500 ;; ACTH) press "$ACT" 3 1500 ;;
        w*) job_sleep "${tok#w}" ;;
        *) job_say "unknown token $tok" ;;
    esac
    job_shot "$JOB_OUT/$(printf %02d "$n")_$tok.png"
done
cp "$G/tmp/spikebt-game.log" "$G/dump/spikebt/helper.log" "$JOB_OUT/" 2>/dev/null
grep -rah "spikebt:" "$JOB_OUT/watch.log" "$G/dump" "$G/tmp" "${PAD_SLOTDIR:-$PAD_HOME}" --include='*.log' 2>/dev/null | sort | uniq -c > "$JOB_OUT/spikebt_lines.txt"
rm -rf "$G/usr/local/spikebt" "$G/dump/pad1647" "$G/lib/pad1647_mode.so"
grep -q 'spikebt/menu.so' "$JOB_OUT/game_maps.txt" || job_fail "his menu.so was not loaded into the game"
job_pass "attract=${JOB_ATTRACT_S}s shots=$n"
