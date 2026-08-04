#!/bin/bash
# in_asm logs each translation block once, when it is first translated - i.e.
# when it first executes. Bounded output, so qemu's buffered log actually gets
# flushed even though the guest dies via _exit.
cd /home/david
R=/home/david/spike2root
rm -f $R/dump/tb.log
export QEMU_LOG=in_asm
export QEMU_LOG_FILENAME=/dump/tb.log
./run_gz.sh > gz69.log 2>&1
echo "log size: $(du -h $R/dump/tb.log | cut -f1)"
echo
echo "=== was the loader body translated? blocks starting in 0x26aa..0x26ad ==="
grep -a '^IN:' -A1 $R/dump/tb.log | grep -aoE '^0x0026a[a-f][0-9a-f]{2}|^0x0026b[0-9a-f]{3}|^0x0026c[0-9a-f]{3}' | sort -u | head -40
echo
echo "=== raw: any occurrence of the key addresses ==="
for a in 0026aa58 0026aaf8 0026ab04 0026ab40 0026ab74 0026ac0c 0027316c 00273194; do
  printf '%s : %s\n' "$a" "$(grep -ac "0x$a" $R/dump/tb.log)"
done
