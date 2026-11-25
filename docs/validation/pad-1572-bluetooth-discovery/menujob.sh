#!/bin/bash
# PAD-1572 job: menujob.sh <key> <card>
# The card's own preload order (mode runtime, then his menu.so: glibc initializes his first), his helper on the demo
# backend with Unauthenticated headphones ON (so the attract game selection carries his Bluetooth choice without an
# Insider scan). In attract: hold the left flipper (his game selection), then step through every choice with the right
# flipper, photographing each; then Left from the first choice (his wrap to Bluetooth), and Action on it.
# PAD1572_NO_BT=1: the same card and presses without his menu (our MODE CHALLENGE entry alone, the control).
RIG=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1572/tools/spike2_emu
. "$RIG/rigjob.sh"
job_begin "${1:?key}" "${2:?card}"
G=$ROOT
KIT=/mnt/c/tmp/PAD-1572/kit
rm -rf "$G/dump/spikebt" "$G/usr/local/spikebt"
mkdir -p "$G/usr/local/spikebt" "$G/dump/pad1572"
cp "$KIT/menu.so" "$KIT/spikebt" "$G/usr/local/spikebt/"; chmod 755 "$G/usr/local/spikebt/spikebt"
cat > "$G/dump/pad1572/pre.sh" <<'EOF'
#!/bin/sh
mkdir -p /dump/spikebt; chmod 700 /dump/spikebt; rm -f /dump/spikebt/demo.sock
/usr/local/spikebt/spikebt --backend=demo --socket=/dump/spikebt/demo.sock \
    --state=/dump/spikebt/demo-state.json >> /dump/spikebt/helper.log 2>&1 &
t=0; while [ ! -S /dump/spikebt/demo.sock ] && [ $t -lt 30 ]; do sleep 1; t=$((t+1)); done
EOF
chmod 755 "$G/dump/pad1572/pre.sh"
so=$(PAD_MODE_SO= bash "$RIG/modes/cardmodes.sh" "$CARD" | tail -1)
if [ -n "${PAD1572_RT:-}" ] && [ -n "$so" ]; then   # the card's modes compiled with the branch's runtime
    cp "$PAD1572_RT" "$G$so"; job_say "runtime: $PAD1572_RT over $so"
fi
if [ -n "${PAD1572_COMP:-}" ]; then   # a stock card: the branch's prebuilt runtime with Prolonged Competition only
    off=$(python3 "$RIG/parts.py" --games "$CARD"); t=$(python3 "$RIG/parts.py" --list-games "$CARD" | awk 'NR==1{print $4}')
    debugfs -R "dump /$t/game /tmp/pad1572_$KEY.elf" "$CARD?offset=$off" > /dev/null 2>&1
    python3 /mnt/c/tmp/PAD-1572/mkcomp.py "/tmp/pad1572_$KEY.elf" "$G/dump/comp.cfg" > "$JOB_OUT/comp.cfg.txt" 2>&1
    rm -f "/tmp/pad1572_$KEY.elf"
    cp "$RIG/modes/sdk/prebuilt/mode.so" "$G/lib/pad1572_mode.so"; so=/lib/pad1572_mode.so
    cp "$RIG/modes/sdk/ports/$PAD1572_COMP.port" "$G/dump/game.port"; job_say "port $PAD1572_COMP"
fi
if [ -n "${PAD1572_NO_BT:-}" ]; then
    export PAD_MODE_SO="$so" PAD_CARD_MODES=0
else
    export PAD_MODE_SO="${so:+$so:}/usr/local/spikebt/menu.so" PAD_CARD_MODES=0 SPIKEBT_BACKEND=demo
    export PAD_PREGAME=/dump/pad1572/pre.sh
fi
job_say "preload: $PAD_MODE_SO"
: > "$G/dump/mode.log"
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-600}" || job_fail "$JOB_WHY"
sw() { awk -v n="$1" '!/^#/ && toupper($0) ~ n {print $1; exit}' "$LIST"; }
SEL=$(sw "SERVICE SELECT"); PLUS=$(sw "SERVICE PLUS"); BACK=$(sw "SERVICE BACK")
LF=$(sw "LEFT FLIPPER BUTTON"); RF=$(sw "RIGHT FLIPPER BUTTON"); ACT=$(sw "ACTION BUTTON")
job_say "switches: select=$SEL plus=$PLUS back=$BACK lf=$LF rf=$RF action=$ACT"
press() { python3 "$RIG/swpoke.py" "$1" "${3:-200}" > /dev/null 2>&1 < /dev/null; job_sleep "${2:-1.5}"; }
if [ -z "${PAD1572_NO_BT:-}" ]; then
    # Service > Bluetooth (the last main-menu row) > Unauthenticated headphones (second row): Select turns it on
    job_sleep 6
    press "$SEL" 4; press "$SEL" 4; press "$(sw "SERVICE MINUS")"; press "$SEL" 4
    press "$PLUS" 2; press "$SEL" 3; job_shot "$JOB_OUT/svc_unauth.png"
    for i in 1 2 3 4 5 6; do press "$BACK" 2; done
    job_sleep 10
fi
job_shot "$JOB_OUT/m00_attract.png"
if [ -n "${PAD1572_NO_BT:-}${PAD1572_BOTH:-}" ]; then   # the stock way in: both flippers held
    python3 "$RIG/swpoke.py" "$RF" 2500 > /dev/null 2>&1 < /dev/null & press "$LF" 4 2500; wait
else
    press "$LF" 4 2500
fi
job_shot "$JOB_OUT/m01_select.png"
if [ -n "${PAD1572_BTACT:-}" ]; then   # onto his Bluetooth choice, Action: his menu
    press "$RF" 2.5 400; job_shot "$JOB_OUT/m01b_bt.png"; press "$ACT" 4; job_shot "$JOB_OUT/m01c_bt_action.png"
    cp "$G/dump/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_pass "bt action"
fi
for i in 02 03 04 05 06 07 08 09 10 11; do press "$RF" 2.5 400; job_shot "$JOB_OUT/m${i}_right.png"; done
for i in 1 2 3 4 5 6 7 8 9 10; do press "$LF" 1; done      # back toward the first choice
job_sleep 2; job_shot "$JOB_OUT/m20_first.png"
press "$LF" 2.5; job_shot "$JOB_OUT/m21_left_wrap.png"
press "$ACT" 4; job_shot "$JOB_OUT/m22_action.png"
cp "$G/dump/mode.log" "$JOB_OUT/mode.log" 2>/dev/null
grep -rah "spikebt:" "$JOB_OUT/watch.log" "${PAD_SLOTDIR:-$PAD_HOME}" --include='*.log' 2>/dev/null | sort | uniq -c > "$JOB_OUT/spikebt_lines.txt"
rm -rf "$G/usr/local/spikebt" "$G/dump/pad1572" "$G/dump/comp.cfg" "$G/lib/pad1572_mode.so"; [ -z "${PAD1572_COMP:-}" ] || rm -f "$G/dump/game.port"
job_pass "attract=${JOB_ATTRACT_S}s"
