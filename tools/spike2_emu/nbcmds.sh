#!/bin/bash
# nbcmds.sh <log> - the node bus command census, parsed from the wire rather
# than by cutting fixed columns.
#
# Addressed frame:  [0x80|id] [payload_len+1] [payload...] [checksum] [reply_len]
# so the command is byte 2 and the payload length is byte 1 minus 1.
L=${1:-/home/david/gz300.log}
echo "=== health ==="
for k in '\[segv\]' '\[throw\]' 'Radium Warning' 'ExchangeData' 'Node bus protocol' 'Nodebus:'; do
  printf '%-24s %s\n' "$k" "$(grep -ac "$k" "$L")"
done
echo
echo "=== addressed commands, by node ==="
grep -aoE '^\[nb\] TX len=[0-9]+ 8[0-9a-f]([0-9a-f]{2})+$' "$L" \
 | awk '{h=$4; id=substr(h,2,1); cmd=substr(h,5,2); print id" "cmd}' \
 | sort | uniq -c | sort -k2,2 -k3,3 | awk '{printf "node %s cmd %s  x%s\n", $2, $3, $1}'
echo
echo "=== unaddressed commands ==="
grep -aoE '^\[nb\] TX len=[0-9]+ [0-7][0-9a-f]([0-9a-f]{2})*$' "$L" \
 | awk '{print $4}' | sort | uniq -c | sort -rn | head -12
