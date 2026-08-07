#!/bin/bash
# strwatch.sh <log> <secs> <substring> - bridged run that reports the caller of
# every std::string built from a literal containing <substring>.
. "$(dirname "$0")/padpath.sh"
set -u
export PAD_STR_WATCH=${3:-VALIDATION}
export PAD_GL_DUMP=$HOME/shots
export PAD_GL_FRAME_EVERY=100
export PAD_GL_MAX_FRAMES=3
mkdir -p "$PAD_GL_DUMP"
bash $RIG/runbridge.sh "${1:-gzstr.log}" "${2:-20}" gpu > /dev/null 2>&1
echo "--- [strwatch] hits ---"
grep -a '\[strwatch\]' "$HOME/${1:-gzstr.log}" | head -40
echo "--- distinct callers ---"
grep -a '\[strwatch\]' "$HOME/${1:-gzstr.log}" | sed 's/ src=.*//' | sort | uniq -c
