#!/bin/bash
# openlog.sh <log> <secs> - bridged run with PAD_OPEN_LOG=1, so every file the
# game opens (and every open that fails) is logged. Written to find what the
# GAME VALIDATION ERROR #2/#3 on the Tech Alerts screen is actually checking.
. "$(dirname "$0")/padpath.sh"
set -u
export PAD_OPEN_LOG=${PAD_OPEN_LOG:-1}
export PAD_GL_DUMP=$HOME/shots
export PAD_GL_FRAME_EVERY=60
export PAD_GL_MAX_FRAMES=4
mkdir -p "$PAD_GL_DUMP"
exec bash "$RIG/runbridge.sh" "${1:-gzopen.log}" "${2:-20}" gpu
