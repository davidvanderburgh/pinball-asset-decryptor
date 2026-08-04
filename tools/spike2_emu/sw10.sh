#!/bin/bash
# sw10.sh - the switch-latch investigation, step 1.
# Dump the three functions that touch the 8 scan bytes, plus every caller of
# the queue drain, so the pending-counter (entry[+22]) lifecycle can be read
# rather than guessed.
D=/home/david/game.dis
O=/mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu

dis() {  # dis <lo> <hi> <outfile>
  awk -v lo=$(printf '%d' $1) -v hi=$(printf '%d' $2) '
  /^ *[0-9a-f]+:/ {
    a = $0; sub(/:.*/, "", a); gsub(/ /, "", a)
    v = strtonum("0x" a)
    if (v >= lo && v <= hi) print
  }' "$D" > "$3"
  echo "$3: $(wc -l < "$3") lines"
}

dis 0x1e78f4 0x1e7bf0 $O/enq.dis        # 0x1e78f4 scan distributor
dis 0x1d54b8 0x1d5700 $O/cons2.dis      # 0x1d54b8 second consumer
dis 0x4606e4 0x460900 $O/notify.dis     # what the second consumer calls
dis 0x1d6d58 0x1d6f00 $O/perode.dis     # 0x1d6d58 / 0x1d6d94 per-node entry
dis 0x1e6800 0x1e68c0 $O/f6860.dis      # 0x1e6860, called from the drain

echo
echo "== callers of the queue drain 0x1e7540 =="
grep -aoE "^ *[0-9a-f]+:.*bl[[:space:]]+1e7540 <" "$D" | sed 's/:.*//' | tr -d ' ' | sort -u
echo "== callers of the scan distributor 0x1e78f4 =="
grep -aoE "^ *[0-9a-f]+:.*bl[[:space:]]+1e78f4 <" "$D" | sed 's/:.*//' | tr -d ' ' | sort -u
echo "== callers of the enqueue helper 0x1e7730 =="
grep -aoE "^ *[0-9a-f]+:.*bl[[:space:]]+1e7730 <" "$D" | sed 's/:.*//' | tr -d ' ' | sort -u
echo "== callers of the second consumer 0x1d54b8 =="
grep -aoE "^ *[0-9a-f]+:.*bl[[:space:]]+1d54b8 <" "$D" | sed 's/:.*//' | tr -d ' ' | sort -u
echo "== callers of 0x4606e4 =="
grep -aoE "^ *[0-9a-f]+:.*bl[[:space:]]+4606e4 <" "$D" | sed 's/:.*//' | tr -d ' ' | sort -u
echo "== callers of 0x1e6860 =="
grep -aoE "^ *[0-9a-f]+:.*bl[[:space:]]+1e6860 <" "$D" | sed 's/:.*//' | tr -d ' ' | sort -u
