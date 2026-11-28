#!/bin/bash
# PAD-1647: the author's own discovery probe (tests/discovery_probe.c at v0.4.4, built for this PC) over game programs:
# does v0.4.4's menu find what it needs in each one?  The stock Godzilla Pro 1.16 is the control.
set -u
R=/mnt/c/tmp/PAD-1647/src
B=/tmp/pad1647probe; rm -rf $B; mkdir -p $B
cc -O2 -std=gnu11 -I $R/native $R/tests/discovery_probe.c $R/native/game_profile.c $R/native/discovery.c -o $B/probe 2>&1 | tail -5
[ -x $B/probe ] || { echo "the probe did not build"; exit 1; }
for f in "$@"; do
  rm -rf $B/cache; mkdir -m 700 $B/cache
  key=$(sha256sum "$f" | cut -c1-64)
  printf '%s  sha256 %s  %s bytes\n  cold: ' "$f" "${key:0:12}" "$(stat -c %s "$f")"
  $B/probe "$f" $B/cache "$key" > $B/out.txt 2>&1; echo "exit $? $(head -1 $B/out.txt)  ($(($(wc -l < $B/out.txt) - 1)) addresses)"
  printf '  warm: '; $B/probe "$f" $B/cache "$key" 2>&1 | head -1
done
