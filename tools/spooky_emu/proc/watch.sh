#!/bin/bash
# watch.sh <game-code .pkg> - the P-ROC half of tools/spooky_emu/watch.sh,
# which hands Rick and Morty's and Alice Cooper's files here (as root): set
# up what the games run on (once), unpack the .pkg, bring up the board and
# the game, wait for attract mode, then print the Emulate tab's status.
#
# Env: PAD_VISIBLE / PAD_AUDIO / PAD_AUDIO_CTL as tools/spooky_emu/watch.sh.
#
# The same `== step ==` headers and exit codes as tools/spooky_emu/watch.sh:
# 0 ready, 2 bad args / not root, 3 no disk space, 4 not a game this rig knows
# (or damaged), 6 the game did not reach attract mode, 7 setting up failed
# (it downloads its Python the first time).
set -u
. "$(dirname "$0")/sppath.sh"
PKG=${1:-}
[ "$(id -u)" = 0 ] || { echo "watch.sh: run as root" >&2; exit 2; }
[ -f "$PKG" ] || { echo "watch.sh: no such update file: $PKG" >&2; exit 2; }

echo "== Unpack =="
# AP's Python 2.7 env and the two modules beside it: a few minutes, once.
if [ ! -f "$SPP_PY/.ready" ] || [ ! -f "$SPP_ROOT/site/.ready" ]; then
    echo "Setting up the games' Python (once; it downloads)…"
    bash "$SPP_TOOLS/setup.sh" || exit 7
fi
PREP=$SPP_ROOT/prepare$SPP_SLOT.out
mkdir -p "$SPP_ROOT"
python3 "$SPP_TOOLS/prepare.py" "$PKG" | tee "$PREP"
rc=${PIPESTATUS[0]}
case "$rc" in 0) ;; 3) exit 3 ;; *) exit 4 ;; esac
BUILD=$(sed -n 's/^build=//p' "$PREP" | tail -1)
[ -n "$BUILD" ] || exit 4

echo "== Board =="
ARGS=()
[ "$(rigboard_visible)" = 1 ] && ARGS+=(--visible)
[ "${PAD_AUDIO:-0}" = 1 ] && ARGS+=(--audio)
echo "== Game =="
bash "$SPP_TOOLS/run_game.sh" "$BUILD" "${ARGS[@]}" || exit 6
echo "== Ready =="
bash "$SPP_TOOLS/../status.sh"
exit 0
