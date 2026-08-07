#!/bin/bash
. "$(dirname "$0")/padpath.sh"
echo "=== qemu-arm options and their env vars ==="
qemu-arm-static -h 2>&1 | grep -iE 'QEMU_|dfilter|-d ' | head -30
echo
echo "=== does the trace file exist? ==="
ls -la "$ROOT/dump/" | head
