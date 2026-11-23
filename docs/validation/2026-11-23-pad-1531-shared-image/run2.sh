#!/bin/bash
# PAD-1531 stand-in proof, part 2 (root, WSL Ubuntu, after run.sh): existing remote access keeps working.
set -u
export HOME=/home/david
W=/var/tmp/pad1531
REPO=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1531
cd "$W"
python3 /mnt/c/tmp/PAD-1531/standin/make_cards2.py "$REPO" "$W" 2>&1
read -r OFF SIZE < <(grep '^P2 offset/size' "$W/make.log" | awk '{print $3, $4}')
for X in D E F; do
  case $X in D) echo "=== D: desktop set it up, then the laptop, answering Keep";;
             E) echo "=== E: desktop set it up, then the laptop, answering Take it off";;
             F) echo "=== F: an existing setup (desktop) rebuilt from its project";; esac
  unshare -n -m bash /mnt/c/tmp/PAD-1531/standin/boot_one.sh "$X" "$OFF" "$SIZE" "desktop laptop"
done
