#!/bin/bash
# PAD-1531 stand-in proof (run as root in WSL Ubuntu): make the three cards, then boot each one's own system files.
set -u
export HOME=/home/david
W=/var/tmp/pad1531
REPO=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1531
STOCK=/mnt/d/Pinball/images/Stern/spike2/deadpool_le-1_16_0.Release.8G.sdcard.raw
rm -rf "$W"; mkdir -p "$W"
cd "$W"
python3 /mnt/c/tmp/PAD-1531/standin/make_cards.py "$REPO" "$W" "$STOCK" 2>&1 | tee "$W/make.log" | grep -v '^P2 '
read -r OFF SIZE < <(grep '^P2 offset/size' "$W/make.log" | awk '{print $3, $4}')
for X in A B C; do
  case $X in A) echo "=== A: the builder's card (remote access on, builder's key)";;
             B) echo "=== B: A on the recipient's machine after one-button setup";;
             C) echo "=== C: the builder's build for sharing";; esac
  unshare -n -m bash /mnt/c/tmp/PAD-1531/standin/boot_one.sh "$X" "$OFF" "$SIZE"
done
