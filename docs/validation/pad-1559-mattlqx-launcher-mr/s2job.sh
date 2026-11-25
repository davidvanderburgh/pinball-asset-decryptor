#!/bin/bash
# PAD-1559 Spike 2 proof job (rigbatch): mattlqx's v0.3.0 armv7 files in the guest, his run-live.sh from main and
# the patched one run through cases.sh in the card's own userland before the game boots.
RIG=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1559/tools/spike2_emu
. "$RIG/rigjob.sh"
job_begin "${1:?key}" "${2:?card}"
export PAD_CARD_MODES=0
G=$ROOT
P=$G/dump/pad1559
rm -rf "$P" "$G/dump/spikebt" "$G/usr/local/spikebt"; mkdir -p "$P" "$G/usr/local/spikebt" "$G/usr/local/bin" "$G/usr/local/padmode"
tar xzf /home/david/pad1554/store/bluetooth/spike-pinball-bluetooth-armv7.tar.gz -C "$G/usr/local/spikebt"
S=/mnt/c/tmp/PAD-1559/rig
cp "$S/run-live.before.sh" "$S/run-live.after.sh" "$S/cases.sh" "$P/"
cp "$RIG/../../pinball_decryptor/resources/remote/pad-buttons.so" "$G/usr/local/bin/pad-buttons.so"
cp "$RIG/modes/sdk/prebuilt/mode.so" "$G/usr/local/padmode/mode.so"
chmod 755 "$P"/*.sh "$G/usr/local/bin/pad-buttons.so" "$G/usr/local/spikebt/"*.sh "$G/usr/local/spikebt/spikebt"
export PAD_PREGAME=/dump/pad1559/cases.sh
# cases.sh takes its arguments from this one-line wrapper (run_game.sh runs PAD_PREGAME with no arguments)
printf '#!/bin/sh\nexec /bin/sh /dump/pad1559/cases.sh /dump/pad1559 fallback unknown live s2exit1 s3exit3 s3exit2\n' > "$P/pre.sh"
export PAD_PREGAME=/dump/pad1559/pre.sh
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-600}" || { cp "$P"/*.txt "$JOB_OUT/" 2>/dev/null; job_fail "$JOB_WHY"; }
cp "$P"/*.txt "$JOB_OUT/" 2>/dev/null
job_shot "$JOB_OUT/attract.png"
rm -rf "$G/usr/local/spikebt" "$G/usr/local/bin/pad-buttons.so" "$G/usr/local/padmode" "$P"
[ -s "$JOB_OUT/results.txt" ] || job_fail "no case results"
job_pass "cases=$(grep -c . "$JOB_OUT/results.txt") attract=${JOB_ATTRACT_S}s"
