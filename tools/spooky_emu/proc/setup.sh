#!/bin/bash
# setup.sh - what the Spooky P-ROC games need beyond tools/ap_emu's Python
# 2.7 env.  Idempotent: a finished one (its .ready stamp) is left alone.
#
# The .pkg carries the game and its own procgame but no interpreter: the
# machines' OS (Arch for Rick and Morty, Debian for Alice Cooper) provided
# Python 2.7 with pySDL2, SDL2_mixer/ttf/image, PyYAML, numpy, PIL, pyserial,
# OpenCV - all in AP's env already (`tools/ap_emu/setup.sh`, run here first
# when missing) - plus two AP's titles never import:
#
#   pygame       SkeletonGame's sound (pygame.mixer) and its font lookup
#                (pygame.font.match_font).  2.0.3, the last line with a
#                Python 2.7 wheel, is SDL2-based: pygame 1.9.6's wheel brings
#                SDL 1.2 and a second libpng into the process and dies on a
#                double free the first time an HD font is drawn.
#   ffpyplayer   Rick and Morty's procgame imports it at the top of
#                dmd/layers.py (its mp4 movies); 4.0.1 is the last py27 wheel.
#
# Both go into $SPP_ROOT/site (pip --target), never into AP's env, and the
# game's PYTHONPATH carries it.
set -eu
. "$(dirname "$0")/sppath.sh"
SITE=$SPP_ROOT/site
# AP's env first, even when the site is ready: the two live apart, and a
# pruned AP env leaves a site with nothing to run it on.
[ -f "$SPP_PY/.ready" ] || bash "$SPP_TOOLS/../../ap_emu/setup.sh"
[ -f "$SITE/.ready" ] && { echo "setup.sh: $SITE ready"; exit 0; }
rm -rf "$SITE"
mkdir -p "$SITE"
"$SPP_PY/bin/pip" install -q --no-cache-dir --only-binary=:all: --target "$SITE" \
    "pygame==2.0.3" "ffpyplayer==4.0.1"
PYTHONPATH=$SITE PYSDL2_DLL_PATH=$SPP_PY/lib "$SPP_PY/bin/python" -c \
    "import pygame, pygame.mixer, pygame.font, ffpyplayer.player, sdl2, yaml, serial, cv2"
touch "$SITE/.ready"
echo "setup.sh: $SITE ready"
