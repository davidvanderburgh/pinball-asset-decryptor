#!/bin/bash
# Q21: 16 queues sit on the pool's release list (+0xa4) and the free deque is
# empty. Moving them back is exactly what the worker thread 0x459184 does at
# 0x459264..0x459324. Prove whether the worker ever got past its opening spin,
# using in_asm block translation (each block logged once, when first executed).
cd /home/david
R=/home/david/spike2root
rm -f $R/dump/tb.log
export QEMU_LOG=in_asm
export QEMU_LOG_FILENAME=/dump/tb.log
./run_game.sh > gz85.log 2>&1
echo "tb.log size: $(du -h $R/dump/tb.log | cut -f1)"
echo
echo "=== did the worker execute these blocks? (1 = yes) ==="
for a in 00459184:worker-entry \
         004591b4:the-spin \
         004591bc:past-the-spin \
         00459210:walk-inuse-list \
         00459264:walk-release-list \
         00459300:push-back-onto-free-deque \
         00458e98:queue-allocator \
         0033a478:store-queue-into-voice ; do
  addr=${a%%:*}; name=${a##*:}
  printf '  %-30s 0x%s -> %s\n' "$name" "$addr" "$(grep -ac "0x$addr" $R/dump/tb.log)"
done
echo
echo "=== who writes the gate byte 0x7acb54 ? ==="
bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/findref.sh 0x7acb54
