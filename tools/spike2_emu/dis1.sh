#!/bin/bash
# Find the true prologue of the startup step at 0x4f0720 and dump the function.
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "=== scan back for push (0x4f0400..0x4f0730) ==="
$OD -d --start-address=0x4f0400 --stop-address=0x4f0730 $G \
  | grep -E 'push|bx	lr|pop' | tail -30
