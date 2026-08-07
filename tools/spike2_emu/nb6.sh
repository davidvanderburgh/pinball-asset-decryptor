#!/bin/bash
# nb6.sh <log> - request/reply shapes per command, straight off the wire.
# byte 1 = payload_len+1, last byte = reply length the game will then read.
L=${1:-$HOME/gz300.log}
grep -aoE '^\[nb\] TX len=[0-9]+ 8[0-9a-f]([0-9a-f]{2})+$' "$L" \
 | awk '{h=$4; n=(length(h)-2)/2; cmd=substr(h,5,2); rl=substr(h,length(h)-1,2);
         pay=substr(h,5,(n-2)*2-2);
         printf "cmd %s  txbytes %d  payload %-10s replylen 0x%s\n", cmd, n, pay, rl}' \
 | sort | uniq -c | sort -k3,3 | head -40
