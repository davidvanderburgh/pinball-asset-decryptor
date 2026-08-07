#!/bin/bash
# nb2.sh - the registry-touching sites OUTSIDE the poll/exchange core.
# The core (0x59d8xx..0x59ecxx) is already mapped; these five are not, and one
# of them should be what puts a real board object into a slot.
. "$(dirname "$0")/padpath.sh"
D=$RIG/disval.sh
for r in "0x5a02c0 0x5a03c0" "0x5a1140 0x5a1240" "0x5a2eb0 0x5a2fb0" "0x5a4580 0x5a4680" "0x5a4e80 0x5a4f80"; do
  set -- $r
  echo "############ $1 .. $2"
  bash $D $1 $2
  echo
done
