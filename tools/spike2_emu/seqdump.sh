#!/bin/bash
# seqdump.sh <log> <secs> <from> <to> - run bridged with PADGL_DEBUG=3 and dump
# every GL op of frames [from,to). The window used to be hard-coded at 60..62,
# which only ever showed the steady state; the splash is in the first few
# frames, so comparing the two windows is the whole point.
#
# PAD_GL_DUMP here is read by the HOST, which is a native WSL process, so it
# takes a WSL path - "/dump" is the chroot's path and silently writes nothing.
set -u
export PADGL_DEBUG=3
export PADGL_SEQ_FROM=${3:-0}
export PADGL_SEQ_TO=${4:-4}
export PAD_GL_DUMP=${PAD_GL_DUMP:-/home/david/shots}
export PAD_GL_FRAME_EVERY=${PAD_GL_FRAME_EVERY:-10}
export PAD_GL_MAX_FRAMES=${PAD_GL_MAX_FRAMES:-14}
mkdir -p "$PAD_GL_DUMP"; rm -f "$PAD_GL_DUMP"/frame_*.png
exec bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/runbridge.sh "${1:-gzseq.log}" "${2:-20}" gpu
