#!/bin/bash
. "$(dirname "$0")/padpath.sh"
R=$ROOT
echo "=== available -d items ==="
qemu-arm-static -d help 2>&1 | head -25
echo
echo "=== smoke test: exec logging on busybox, no filter ==="
QEMU_LOG=exec QEMU_LOG_FILENAME=/tmp/t1.log qemu-arm-static -L $R $R/bin/busybox true 2>/dev/null
echo "t1.log: $(wc -l < /tmp/t1.log 2>/dev/null) lines"
head -3 /tmp/t1.log 2>/dev/null
echo
echo "=== smoke test: with a dfilter using .. syntax ==="
QEMU_LOG=exec QEMU_DFILTER=0x10000..0x20000 QEMU_LOG_FILENAME=/tmp/t2.log \
  qemu-arm-static -L $R $R/bin/busybox true 2>/dev/null
echo "t2.log: $(wc -l < /tmp/t2.log 2>/dev/null) lines"
head -3 /tmp/t2.log 2>/dev/null
