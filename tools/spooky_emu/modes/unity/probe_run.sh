#!/bin/bash
# probe_run.sh <slot> <out dir with padunity.so + PadModes.dll> - boot
# Scooby-Doo on the Spooky rig, hidden and muted, with PAD's managed runtime
# preloaded (PAD-1387 proof).  Run in PAD-Runtime as root after
# `riglock.sh take`.  The log is $SPK_RIG/logs/padunity.log.
set -u
SLOT=${1:?slot}; OUT=${2:?out dir}
T=$(cd "$(dirname "$0")/../.." && pwd)
install -d -m 755 /var/tmp/pad_spooky/padunity
install -m 644 "$OUT/PadModes.dll" /var/tmp/pad_spooky/padunity/PadModes.dll
# run_game.sh preloads SPK_MENU_SO (the multi-boot menu's slot) in front of
# spkshim.so; any .so works there.
export PAD_SLOT=$SLOT PAD_LABEL=PAD-1387 PAD_HIDDEN=1 PAD_VISIBLE=0 PAD_AUDIO=0
export SPK_MENU_SO=$OUT/padunity.so SPK_MENU_PROTO=warden SPK_MENU_SWITCH=250
bash "$T/watch.sh" /mnt/d/Pinball/images/Spooky/v2025.12.01.09.scooby
echo "watch rc=$?"
