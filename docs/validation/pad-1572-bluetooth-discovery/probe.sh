#!/bin/bash
# PAD-1572: build Matt's discovery probe (host x86) and run it over a list of game ELFs.
set -u
R=/mnt/c/tmp/PAD-1572/spikebt
B=/tmp/pad1572probe; mkdir -p $B
cc -O2 -std=gnu11 -I $R/native $R/tests/discovery_probe.c $R/native/game_profile.c $R/native/discovery.c -o $B/probe 2>&1 | tail -5
for f in "$@"; do
  rm -rf $B/cache; mkdir -m 700 $B/cache
  key=$(sha256sum "$f" | cut -c1-64)
  printf '%s  %s\n  ' "$(basename "$f")" "${key:0:12}"
  $B/probe "$f" $B/cache "$key" | head -1
  printf '  warm: '; $B/probe "$f" $B/cache "$key" | head -1
done
