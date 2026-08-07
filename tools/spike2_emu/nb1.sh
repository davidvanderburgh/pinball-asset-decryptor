#!/bin/bash
# nb1.sh - who touches the node board registry at 0x70a474 (+0x28 = the 64 slots)?
# Both reference forms, because findref.sh alone misses pc-relative literal pools
# (that is exactly how the mixer's voice array hid).
. "$(dirname "$0")/padpath.sh"
echo "=== movw/movt sites building 0x70a474 / 0x70a49c ==="
bash "$RIG/findref.sh" 0x70a474 0x70a49c 0x69cc08

echo
echo "=== literal-pool words equal to 0x70a474 / 0x70a49c / 0x69cc08 ==="
python3 "$RIG/litref.py" 0x70a474 0x70a49c 0x69cc08
