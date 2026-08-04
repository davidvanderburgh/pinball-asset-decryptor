#!/bin/bash
# Q22: this qemu build's in_asm prints only the block START address plus raw
# OBJD-T bytes - no disassembly - so only block starts can be grepped. Thread
# entry points ARE block starts, so ask which threads ever executed.
R=/home/david/spike2root
T=$R/dump/tb.log
echo "=== game-thread entry points seen in [thread] lines vs actually executed ==="
for a in 005a9b60:thread1 \
         00447440:SceneCache-loader \
         004efef0:thread3 \
         00444e14:scene-enumerator \
         004e7e64:thread6-gate-writer \
         00504ee0:thread7 \
         005a59b0:thread9 \
         0021cf1c:thread10-gate \
         001d7e9c:thread12 \
         00459604:AUDIO-STREAM-WORKER \
         0033bd20:thread37-sound-TU ; do
  addr=${a%%:*}; name=${a##*:}
  printf '  %-24s 0x%s -> %s\n' "$name" "$addr" "$(grep -ac "0x$addr" $T)"
done
echo
echo "=== total distinct blocks translated in game .text ==="
grep -aoE '^0x00[0-5][0-9a-f]{5}' $T | sort -u | wc -l
