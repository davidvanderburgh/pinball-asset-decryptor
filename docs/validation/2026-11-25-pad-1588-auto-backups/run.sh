#!/bin/bash
# PAD-1588 stand-in proof (root, WSL Ubuntu): make the card, then boot it and run the app's backup code against it.
set -u
export HOME=/home/david
W=/var/tmp/pad1588
REPO=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1588
STOCK=/mnt/d/Pinball/images/Stern/spike2/godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw
find "$W" -mindepth 1 -maxdepth 1 ! -name py -exec rm -rf {} +
cd "$W"
PYTHONPATH=$W/py python3 /mnt/c/tmp/PAD-1588/standin/make_card.py "$REPO" "$W" "$STOCK" 2>&1 | tee "$W/make.log"
read -r OFF SIZE < <(grep '^P2 offset/size' "$W/make.log" | awk '{print $3, $4}')
unshare -n -m -p -f bash /mnt/c/tmp/PAD-1588/standin/boot.sh "$OFF" "$SIZE" "$REPO"
