#!/bin/bash
T=/home/david/spike2root/dump/tb.log
echo "=== which blocks of the caller 0x444014 executed? ==="
grep -aoE '^0x00444[0-1][0-9a-f]{2}' $T | sort -u
echo
echo "=== key decision points ==="
for a in 0026aa8c:loader-early-return-empty \
         0026aaf8:radium-branch \
         0026ac0c:json-branch \
         0027316c:cereal-loadBinary \
         002731ac:loadBinary-throw \
         00444150:caller-returns-null \
         00444160:caller-not-radium \
         0026abf0:deserialize-call \
         00291570:deserialize-body ; do
  addr=${a%%:*}; name=${a##*:}
  printf '  %-28s %s -> %s\n' "$name" "0x$addr" "$(grep -ac "0x$addr" $T)"
done
