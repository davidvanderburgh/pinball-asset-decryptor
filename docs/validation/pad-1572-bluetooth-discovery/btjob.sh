#!/bin/bash
# PAD-1572 job: btjob.sh <key> <card>
# Matt's helper (demo backend) beside the game, his menu.so at 6d1381a (runtime discovery) preloaded, the card's
# own game program or one laid over it (PAD_OVERRIDE_DIR). Reaches attract, records discovery from his log, then
# Service > main menu > last row (Bluetooth) > Select, and photographs each screen.
RIG=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1572/tools/spike2_emu
. "$RIG/rigjob.sh"
job_begin "${1:?key}" "${2:?card}"
G=$ROOT
KIT=/mnt/c/tmp/PAD-1572/kit
rm -rf "$G/dump/spikebt" "$G/usr/local/spikebt" "$G/tmp/spikebt-game.log"
mkdir -p "$G/usr/local/spikebt"
cp "$KIT/menu.so" "$KIT/spikebt" "$G/usr/local/spikebt/"; chmod 755 "$G/usr/local/spikebt/spikebt"
sha256sum "$G/usr/local/spikebt/menu.so" > "$JOB_OUT/menu_sha.txt"
mkdir -p "$G/dump/pad1572"
cat > "$G/dump/pad1572/pre.sh" <<'EOF'
#!/bin/sh
mkdir -p /dump/spikebt; chmod 700 /dump/spikebt; rm -f /dump/spikebt/demo.sock
/usr/local/spikebt/spikebt --backend=demo --socket=/dump/spikebt/demo.sock \
    --state=/dump/spikebt/demo-state.json >> /dump/spikebt/helper.log 2>&1 &
t=0; while [ ! -S /dump/spikebt/demo.sock ] && [ $t -lt 30 ]; do sleep 1; t=$((t+1)); done
EOF
chmod 755 "$G/dump/pad1572/pre.sh"
if [ -n "${PAD1572_PREBUILT:-}" ]; then   # PAD's prebuilt mode runtime alone (no modes), preloaded as a card's would be
    cp "$RIG/modes/sdk/prebuilt/mode.so" "$G/lib/pad1572_mode.so"; export PAD_MODE_SO=/lib/pad1572_mode.so
fi
export PAD_PREGAME=/dump/pad1572/pre.sh
export PAD_TRACE_SO=/usr/local/spikebt/menu.so SPIKEBT_BACKEND=demo
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-600}" || { cp "$G/tmp/spikebt-game.log" "$G/dump/spikebt/helper.log" "$JOB_OUT/" 2>/dev/null; job_fail "$JOB_WHY"; }
job_sleep 6
job_shot "$JOB_OUT/attract.png"
for m in /proc/[0-9]*/maps; do
    if grep -q 'spikebt/menu.so' "$m" 2>/dev/null; then
        echo "pid ${m%/maps}: $(grep -o '/[^ ]*\.so' "$m" | sort -u | grep -v '^/lib/\|^/usr/lib/' | tr '\n' ' ')"
        sha256sum "/proc/${m%/maps}/exe" 2>/dev/null
    fi
done > "$JOB_OUT/game_maps.txt" 2>&1
ls -la "$G/dump/spikebt" "$G/dump/spikebt/discovery" > "$JOB_OUT/dumpdir.txt" 2>&1
cp "$G/tmp/spikebt-game.log" "$JOB_OUT/" 2>/dev/null
sw() { awk -v n="$1" '!/^#/ && toupper($0) ~ n {print $1; exit}' "$LIST"; }
SEL=$(sw "SERVICE SELECT"); PLUS=$(sw "SERVICE PLUS"); MINUS=$(sw "SERVICE MINUS"); BACK=$(sw "SERVICE BACK")
job_say "service switches: select=$SEL plus=$PLUS minus=$MINUS back=$BACK"
press() { python3 "$RIG/swpoke.py" "$1" 300 > /dev/null 2>&1 < /dev/null; job_sleep "${2:-1.5}"; }
press "$SEL" 4; press "$SEL" 4; job_shot "$JOB_OUT/svc_0_root.png"
press "$MINUS"; job_shot "$JOB_OUT/svc_1_last_row.png"
press "$SEL" 4; job_shot "$JOB_OUT/bt_menu.png"
cp "$G/tmp/spikebt-game.log" "$G/dump/spikebt/helper.log" "$JOB_OUT/" 2>/dev/null
grep -rah "spikebt:" "$JOB_OUT/watch.log" "$G/dump" "$G/tmp" "${PAD_SLOTDIR:-$PAD_HOME}" --include='*.log' 2>/dev/null | sort | uniq -c > "$JOB_OUT/discovery_lines.txt"
rm -rf "$G/usr/local/spikebt" "$G/dump/pad1572"
job_pass "attract=${JOB_ATTRACT_S}s"
