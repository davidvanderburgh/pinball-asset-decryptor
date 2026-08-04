#!/bin/bash
echo "=== qemu-arm options and their env vars ==="
qemu-arm-static -h 2>&1 | grep -iE 'QEMU_|dfilter|-d ' | head -30
echo
echo "=== does the trace file exist? ==="
ls -la /home/david/spike2root/dump/ | head
