#!/bin/bash
# Build an event-id -> handler-address map from every call site of the
# subscribe() helper at 0x4bb380.  Handler goes in r2 as a movw/movt pair,
# event id in r1, priority in r3.
D=$HOME/game.dis

awk '
/^ *[0-9a-f]+:/ {
  line = $0
  # remember the most recent immediate loads
  if (match(line, /mov\tr1, #[0-9]+/))  { s=substr(line,RSTART,RLENGTH); sub(/.*#/,"",s); r1=s+0; r1ok=1 }
  if (match(line, /movw\tr1, #[0-9]+/)) { s=substr(line,RSTART,RLENGTH); sub(/.*#/,"",s); r1=s+0; r1ok=1 }
  if (match(line, /movw\tr2, #[0-9]+/)) { s=substr(line,RSTART,RLENGTH); sub(/.*#/,"",s); r2lo=s+0 }
  if (match(line, /movt\tr2, #[0-9]+/)) { s=substr(line,RSTART,RLENGTH); sub(/.*#/,"",s); r2hi=s+0 }
  if (match(line, /mov\tr3, #[0-9]+/))  { s=substr(line,RSTART,RLENGTH); sub(/.*#/,"",s); r3=s+0 }
  if (line ~ /bl\t4bb380/) {
    addr = line; sub(/:.*/,"",addr); gsub(/ /,"",addr)
    if (r1ok) printf "event %3d  handler 0x%x  prio %d   @ %s\n", r1, r2hi*65536+r2lo, r3, addr
    else      printf "event  ??  handler 0x%x  prio %d   @ %s\n",     r2hi*65536+r2lo, r3, addr
  }
}
' $D > $HOME/evmap.txt

echo "total registrations: $(wc -l < $HOME/evmap.txt)"
echo
echo "=== event 93 (0x5d) ==="
grep -E '^event  93' $HOME/evmap.txt
echo "=== event 94 (0x5e) ==="
grep -E '^event  94' $HOME/evmap.txt
echo
echo "=== distinct event ids seen ==="
awk '{print $2}' $HOME/evmap.txt | sort -n | uniq -c | tr '\n' ' ' | head -c 3000
echo
