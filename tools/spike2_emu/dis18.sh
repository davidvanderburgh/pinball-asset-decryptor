#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "### every return point in the event-93 handler 0x564cc..0x57880 ###"
$OD -d --start-address=0x564cc --stop-address=0x57880 $G \
  | grep -E 'mov	r0, #|pop	\{r4, pc\}|movs	r0|mvn	r0' | head -60
echo
echo "### 0x56700..0x567e0 raw (the tail of the linear fast path) ###"
$OD -d --start-address=0x566e0 --stop-address=0x567e0 $G | sed -n '7,80p'
