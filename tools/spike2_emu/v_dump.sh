#!/bin/bash
# usage: v_dump.sh START END OUTNAME
. "$(dirname "$0")/padpath.sh"
mkdir -p "$HOME/sw"
bash "$RIG/disval.sh" "$1" "$2" > "$HOME/sw/$3.dis" 2>&1
wc -l "$HOME/sw/$3.dis"
