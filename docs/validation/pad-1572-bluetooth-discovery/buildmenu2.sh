#!/bin/bash
# PAD-1572: rebuild menu.so with 32-bit time_t, then check every undefined symbol resolves from the card's libs.
set -eu
RIG=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1572/tools/spike2_emu
. "$RIG/padpath.sh"
tr -d '\r' < /mnt/c/tmp/PAD-1572/xgcc > /tmp/pad1572xgcc; chmod 755 /tmp/pad1572xgcc
cd /tmp/pad1572src
rm -rf /tmp/pad1572menu
CC=/tmp/pad1572xgcc SPIKEBT_SYSROOT=$ROOT SPIKEBT_HEADERS=/usr/arm-linux-gnueabihf/include \
  FREETYPE_INCLUDE=/tmp/pad1572ft/usr/include/freetype2 sh scripts/build-menu.sh /tmp/pad1572menu 2>&1 | tail -5
# every undefined function/object must be defined by one of the card's libs it links
arm-linux-gnueabihf-nm -D --undefined-only /tmp/pad1572menu/menu.so | awk '{print $NF}' | sed 's/@.*//' | sort -u > /tmp/pad1572und.txt
for l in libc.so.6 libdl.so.2 libpthread.so.0 librt.so.1; do arm-linux-gnueabihf-nm -D --defined-only "$ROOT/lib/$l"; done | awk '{print $NF}' | sed 's/@.*//' | sort -u > /tmp/pad1572def.txt
echo "undefined: $(wc -l < /tmp/pad1572und.txt); not in the card's libs:"
comm -23 /tmp/pad1572und.txt /tmp/pad1572def.txt
cp /tmp/pad1572menu/menu.so /mnt/c/tmp/PAD-1572/kit/menu.so
sha256sum /tmp/pad1572menu/menu.so
