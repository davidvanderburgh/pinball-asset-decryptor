#!/bin/bash
. "$(dirname "$0")/padpath.sh"
echo "=== debuggers available ==="
for g in gdb-multiarch gdb arm-linux-gnueabihf-gdb gdb-arm-none-eabi; do
  p=$(command -v $g 2>/dev/null)
  [ -n "$p" ] && echo "$g -> $p"
done
echo
echo "=== qemu-arm-static version ==="
qemu-arm-static --version 2>/dev/null | head -2
echo
echo "=== word at 0x26aed8 (the wrapper vtable) and 0x26aedc, from the file ==="
# VA -> file offset: .text is mapped at its link address, file offset = VA - 0x8000
xxd -s $((0x26aed8 - 0x8000)) -l 16 $ROOT/games/godzilla_pro/game
