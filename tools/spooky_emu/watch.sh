#!/bin/bash
# watch.sh <update file> - the one command the app runs (as root): unpack the
# update, bring up the board and the game, wait for attract mode, then print
# status.sh.
#
# Env (all optional):
#   PAD_VISIBLE 1 = draw on the desktop, 0 = hidden. Unsaid: seen, except a
#               run for a ticket or a session (it has a label) - hidden (PAD-309)
#   PAD_AUDIO   1 = sound on (a rig is silent unless asked)
#
# Prints `== step ==` headers for the app's footer ladder:
#   == Unpack ==, == Board ==, == Game ==, == Ready ==
# Exit: 0 ready, 2 bad args / not root, 3 no disk space, 4 not a game this
# emulator knows (or damaged), 5 no game in it, 6 the game did not reach
# attract mode, 7 setting up failed (the P-ROC games' Python downloads once).
#
# Rick and Morty's and Alice Cooper's game-code .pkg go to proc/watch.sh (the
# P-ROC rig, PAD-319); one slot runs one game, so each kind stops the other's.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/spkpath.sh"
UPD=${1:-}
[ "$(id -u)" = 0 ] || { echo "watch.sh: run as root" >&2; exit 2; }
[ -f "$UPD" ] || { echo "watch.sh: no such update file: $UPD" >&2; exit 2; }

# cancel.sh ends this run by its process tree; it finds it here.
mkdir -p "$SPK_ROOT"
echo $$ > "$SPK_ROOT/watch$SPK_SLOT.pid"
trap 'rm -f "$SPK_ROOT/watch$SPK_SLOT.pid"' EXIT

if spk_proc_file "$UPD"; then
    bash "$HERE/killgame.sh" >/dev/null 2>&1
    bash "$SPK_PROC/watch.sh" "$UPD"
    exit $?
fi
spk_proc_present && bash "$SPK_PROC/killgame.sh" >/dev/null 2>&1

echo "== Unpack =="
PREP=$SPK_ROOT/prepare$SPK_SLOT.out
bash "$HERE/prepare.sh" "$UPD" | tee "$PREP"
rc=${PIPESTATUS[0]}
[ "$rc" = 0 ] || exit "$rc"
BUILD=$(sed -n 's/^build=//p' "$PREP" | tail -1)
[ -n "$BUILD" ] || exit 5

echo "== Board =="
ARGS=()
# unsaid, a run for a ticket or a session is hidden (rigboard_visible, PAD-309)
[ "$(rigboard_visible)" = 1 ] && ARGS+=(--visible)
[ "${PAD_AUDIO:-0}" = 1 ] && ARGS+=(--audio)
echo "== Game =="
bash "$HERE/run_game.sh" "$BUILD" "${ARGS[@]}" || exit 6
echo "== Ready =="
bash "$HERE/status.sh"
exit 0
