#!/bin/bash
cd /home/david
export PAD_SCENE_VERBOSE=9d57875196c613785a1eee010c55223a0f1aa821
./run_gz.sh > gz73.log 2>&1
echo "=== the 17 fields cereal reads out of the failing scene ==="
grep '\[hdr\]' gz73.log
echo
echo "=== first 96 bytes of that file for comparison ==="
xxd -l 96 /home/david/spike2root/games/godzilla_pro/assets/lcd/auto_loaded/9d57875196c613785a1eee010c55223a0f1aa821/scene.radium
