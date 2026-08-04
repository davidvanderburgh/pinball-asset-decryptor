#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "### strings: VA = file offset + 0x8000 ###"
printf '0x674c04 -> '; dd if=$G bs=1 skip=$((0x66cc04)) count=24 2>/dev/null | tr -d '\0' ; echo
printf '0x642fe0 -> '; dd if=$G bs=1 skip=$((0x63afe0)) count=40 2>/dev/null | tr -d '\0' ; echo
echo
echo "### 0x26aa58 - the function that should read the stream ###"
$OD -d --start-address=0x26aa58 --stop-address=0x26ac00 $G | sed -n '7,300p'
