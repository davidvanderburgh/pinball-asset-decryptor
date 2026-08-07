#!/bin/bash
# nbtimeout.sh <log> - attribute every ExchangeData timeout to the node bus
# frame that caused it.
#
#   wsl -e bash $RIG/nbtimeout.sh $HOME/gznb.log
#
# ONLY MEANINGFUL ON A RUN WITH PAD_NB_LOG RAISED. The [nb] budget is 400 lines
# by default, so on an ordinary run every [nb] line is from the first second and
# the "frame that caused it" is stale for the whole rest of the log - which
# reads as "every timeout is the 00 poll" and is completely wrong. This script
# refuses rather than print that.
. "$(dirname "$0")/padpath.sh"
set -u
L=${1:-$HOME/gznb.log}

nb=$(grep -ac '^\[nb\] ' "$L" 2>/dev/null)
to=$(grep -ac 'ExchangeData: read failed' "$L" 2>/dev/null)
echo "[nb] lines: ${nb:-0}   timeouts: ${to:-0}"
if [ "${nb:-0}" -lt 5000 ]; then
    echo "too few [nb] lines - re-run with PAD_NB_LOG=400000 or the attribution lies"
    exit 1
fi

awk '
/^\[nb\] TX len=/ {
    # "[nb] TX len=5 8202fe7e0d" -> node byte 82, command byte fe
    frame = $4
    node = substr(frame, 1, 2)
    cmd  = substr(frame, 5, 2)
    next
}
/ExchangeData: read failed/ {
    if (node != "") { n[node]++; c[node " " cmd]++ }
}
END {
    print "--- by node address (first frame byte, 0x80|id) ---"
    for (k in n) printf "%8d  %s\n", n[k], k
    print "--- by node + command ---"
    for (k in c) printf "%8d  %s\n", c[k], k
}' "$L" | sort -rn -k1
