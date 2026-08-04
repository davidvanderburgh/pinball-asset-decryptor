#!/bin/bash
# nb4.sh - who consumes the identity?
#   0x5a2f44(id) returns the u16 built from identity payload bytes [8..9] and
#   only re-asks while it is ZERO, so that field is the board's hardware id and
#   must be non-zero or the game asks forever.
D=/home/david/game.dis
echo "=== callers of 0x5a2f44 (get board hw id) ==="
grep -c 'bl	5a2f44' $D
grep -n 'bl	5a2f44' $D | head -30
echo
echo "=== callers of 0x5a2e10 (identify + register) ==="
grep -n 'bl	5a2e10' $D | head -20
echo
echo "=== callers of 0x5a2f9c ==="
grep -n 'bl	5a2f9c' $D | head -20
