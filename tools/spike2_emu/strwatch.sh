#!/bin/bash
# strwatch.sh <log> <secs> <substring> - bridged run that reports the caller of
# every std::string built from a literal containing <substring>.
set -u
export PAD_STR_WATCH=${3:-VALIDATION}
export PAD_GL_DUMP=/home/david/shots
export PAD_GL_FRAME_EVERY=100
export PAD_GL_MAX_FRAMES=3
mkdir -p "$PAD_GL_DUMP"
bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/runbridge.sh "${1:-gzstr.log}" "${2:-20}" gpu > /dev/null 2>&1
echo "--- [strwatch] hits ---"
grep -a '\[strwatch\]' "/home/david/${1:-gzstr.log}" | head -40
echo "--- distinct callers ---"
grep -a '\[strwatch\]' "/home/david/${1:-gzstr.log}" | sed 's/ src=.*//' | sort | uniq -c
