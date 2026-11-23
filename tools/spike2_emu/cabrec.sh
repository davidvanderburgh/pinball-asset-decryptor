#!/bin/bash
# cabrec.sh <out.bin> <seconds> <period ms> <map> - record the running game's cabinet lights (PAD-1516): cabrec.py
# on this rig's LED block (padpath.sh: PAD_SLOT's rig), beside the guest. The Expression lights tab's Record.
S=$(cd "$(dirname "$0")" && pwd)
. "$S/padpath.sh"
exec python3 "$S/cabrec.py" "$ROOT/dump/padled" "$@"
