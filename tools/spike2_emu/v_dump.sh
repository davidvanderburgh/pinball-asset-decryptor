#!/bin/bash
# usage: v_dump.sh START END OUTNAME
bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/disval.sh "$1" "$2" > "/home/david/sw/$3.dis" 2>&1
wc -l "/home/david/sw/$3.dis"
