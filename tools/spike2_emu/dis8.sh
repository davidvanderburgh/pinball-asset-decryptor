#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

# Dump the event-93 handler and strip the repetitive C++ static-init guard
# checks (movw/movt r0,#0x79xxxx ; ldr r3,[r0] ; tst r3,#1 ; beq far) so the
# real body is visible.
$OD -d --start-address=0x564cc --stop-address=0x56e20 $G | sed -n '7,4000p' \
  | grep -vE 'movw	r0, #|movt	r0, #121|ldr	r3, \[r0\]$|tst	r3, #1|beq	5(6|7)[0-9a-f]{3} '
