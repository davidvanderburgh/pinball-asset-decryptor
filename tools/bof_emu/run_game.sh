#!/bin/bash
# run_game.sh <binary> <profile.json> [--visible] [--audio] [--detach]
#
# Start a Barrels of Fun game on this PC: the emulated boards (bofhw.py), the
# port shim, and the game itself.  Run as root (it switches users itself).
#
#   --visible  draw on the WSLg desktop (GPU) instead of the slot's hidden
#              Xvfb display (the default: windows popping up are disruptive;
#              shot.sh shows a hidden run)
#   --audio    play sound through WSLg's PulseAudio (default: muted)
#   --detach   return once the game is up; killgame.sh stops it
#
# THE HOST MUST BE PROTECTED FROM THE GAME.  It shells out through
# OS.execute("sudo", ...) - `mount -o remount,ro /` around every settings save,
# plus sync, systemctl, iwctl, bluetoothctl, dhcpcd, reboot.  As root in a WSL
# distro the first of those remounts the whole distro read-only.  So the game
# runs as an ordinary user, and a logging no-op sudo (and friends) is first on
# its PATH.  Every attempt lands in $BOF_RIG/sudo.log.
#
# Rendering: the Godot 4 compatibility (OpenGL) renderer.  The titles are
# built for Forward+ (Vulkan) but draw identically under it, and OpenGL is what
# both WSLg (GPU, via d3d12) and a hidden Xvfb (llvmpipe) provide without a
# Vulkan driver in the distro.
set -u
. "$(dirname "$0")/bofpath.sh"
BIN=${1:-}; PROFILE=${2:-}; shift 2 2>/dev/null || true
VISIBLE=0; AUDIO=0; DETACH=0
for a in "$@"; do
    case "$a" in
        --visible) VISIBLE=1 ;;
        --audio) AUDIO=1 ;;
        --detach) DETACH=1 ;;
        *) echo "run_game.sh: unknown option $a" >&2; exit 2 ;;
    esac
done
[ -x "$BIN" ] || { echo "run_game.sh: not an executable game binary: $BIN" >&2; exit 2; }
[ -f "$PROFILE" ] || { echo "run_game.sh: no profile: $PROFILE" >&2; exit 2; }
[ -f "$BOF_SHIM" ] || { echo "run_game.sh: missing $BOF_SHIM" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to $BOF_USER itself)" >&2; exit 2; }
[ -n "$BOF_USER" ] || { echo "run_game.sh: no ordinary user account to run the game as" >&2; exit 2; }

bash "$BOF_TOOLS/killgame.sh" >/dev/null 2>&1
AUDIO=$(rigboard_audio "$VISIBLE" "$AUDIO")

TITLE=$(basename "$PROFILE" .json)
HOMEDIR=$BOF_HOMES/$TITLE
rm -rf "$BOF_RIG"
mkdir -p "$BOF_RIG/bin" "$BOF_RIG/hw" "$HOMEDIR"
# The shim is preloaded from this slot's folder, never from the rig's: an
# installed app's rig is /mnt/c/Program Files/..., and LD_PRELOAD is a
# space-separated list - ld.so tried "/mnt/c/Program", "Files/Pinball"...,
# ignored them all, and the game never found its boards (PAD-313).
cp "$BOF_SHIM" "$BOF_RIG/bofhwshim.so"
echo "$BIN" > "$BOF_RIG/binary"
echo "$TITLE" > "$BOF_RIG/title"
echo "$VISIBLE" > "$BOF_RIG/visible"

# The no-op sudo, and the commands the game runs directly.
cat > "$BOF_RIG/bin/sudo" <<'EOF'
#!/bin/sh
echo "$(date +%T) $(basename "$0") $*" >> "$BOFEMU_LOG_DIR/sudo.log"
exit 0
EOF
chmod 755 "$BOF_RIG/bin/sudo"
for t in systemctl iwctl bluetoothctl dhcpcd amixer ping ifconfig reboot shutdown poweroff; do
    ln -sf sudo "$BOF_RIG/bin/$t"
done
chown -R "$BOF_USER": "$BOF_RIG" "$HOMEDIR"

# The boards.  They run as the game's user so it may open their ptys.
#
# EVERYTHING STARTED HERE IS DETACHED WHOLE: `setsid -f` goes OUTSIDE runuser,
# and stdin is closed.  runuser passes the launching session's hang-up on to
# its child, so a game started as `runuser ... setsid game &` quit the moment
# the wsl.exe that ran this returned - i.e. right after watch.sh said Ready.
setsid -f runuser -u "$BOF_USER" -- python3 "$BOF_TOOLS/bofhw.py" \
    --dir "$BOF_RIG/hw" --profile "$PROFILE" --build "$(dirname "$BIN")" \
    < /dev/null > "$BOF_RIG/hw/daemon.out" 2>&1
for _ in $(seq 1 50); do [ -S "$BOF_RIG/hw/ctl.sock" ] && break; sleep 0.1; done
[ -S "$BOF_RIG/hw/ctl.sock" ] || { echo "run_game.sh: board emulator did not start:" >&2; cat "$BOF_RIG/hw/daemon.out" >&2; exit 3; }

if [ $VISIBLE = 1 ]; then
    DISP=${DISPLAY:-:0}
else
    DISP=$BOF_DISPLAY
    setsid -f Xvfb "$DISP" -screen 0 2560x1440x24 -nolisten tcp \
        < /dev/null > "$BOF_RIG/xvfb.log" 2>&1
    for _ in $(seq 1 50); do [ -e "/tmp/.X11-unix/X${DISP#:}" ] && break; sleep 0.1; done
    pgrep -xf "Xvfb $DISP .*" | head -1 > "$BOF_RIG/xvfb.pid"
fi
echo "$DISP" > "$BOF_RIG/display"

if [ $AUDIO = 1 ] && [ -S /mnt/wslg/PulseServer ]; then
    AUDIO_ENV="PULSE_SERVER=unix:/mnt/wslg/PulseServer"
    AUDIO_ARG=PulseAudio
else
    AUDIO_ENV=""
    AUDIO_ARG=Dummy
fi

# A window you can move and size.  Every title's project says borderless and
# not resizable (a cabinet's monitor has nothing else on it), which on a desk
# is a 1280x1110 slab with no title bar to drag.  Godot reads override.cfg
# from the executable's folder after the embedded project settings; the game
# code never sets its own window, so this is the whole change.  canvas_items
# stretch scales the picture with the window instead of cropping it (at the
# project size it draws exactly as before).  It opens near the top left, not
# centred: centred, a 1110-high window on a shorter screen puts its title bar
# above the top edge, out of reach.  Only on the desktop: a hidden run stays
# exactly the build as shipped.
OVR="$(dirname "$BIN")/override.cfg"
if [ $VISIBLE = 1 ]; then
    printf '%s\n' '[display]' 'window/size/borderless=false' \
        'window/size/resizable=true' 'window/stretch/mode="canvas_items"' \
        'window/stretch/aspect="keep"' 'window/size/initial_position_type=0' \
        'window/size/initial_position=Vector2i(40, 40)' > "$OVR"
else
    rm -f "$OVR"
fi

cd "$BOF_RIG" || exit 3
# shellcheck disable=SC2086
setsid -f runuser -u "$BOF_USER" -- env -i \
    PATH="$BOF_RIG/bin:/usr/local/bin:/usr/bin:/bin" \
    HOME="$HOMEDIR" USER="$BOF_USER" LANG=C.UTF-8 \
    DISPLAY="$DISP" XDG_RUNTIME_DIR="$BOF_RIG" $AUDIO_ENV \
    BOFEMU_LOG_DIR="$BOF_RIG" GODOT_SILENCE_ROOT_WARNING=1 \
    LD_PRELOAD="$BOF_RIG/bofhwshim.so" BOFHW_DEV="$BOF_RIG/hw/dev" BOFHW_SYS="$BOF_RIG/hw/sys" \
    "$BIN" --display-driver x11 --rendering-method gl_compatibility \
        --audio-driver $AUDIO_ARG < /dev/null > "$BOF_RIG/game.log" 2>&1
for _ in $(seq 1 50); do
    GP=$(pgrep -u "$BOF_USER" -xf "$BIN .*" | head -1)
    [ -n "$GP" ] && break
    sleep 0.1
done
[ -n "${GP:-}" ] || { echo "run_game.sh: the game did not start:" >&2; tail -20 "$BOF_RIG/game.log" >&2; exit 4; }
echo "$GP" > "$BOF_RIG/game.pid"
rigboard_post bof "$BOF_SLOT" "$GP" "$TITLE" "${PAD_TITLE:-}" "$VISIBLE" "$AUDIO"
# The playfield window's keys in the game's own window too (PAD-313): on the
# desktop (PAD_GAMEKEYS=1 forces it on a hidden run, for tests).  The game's
# environment carries BOFEMU_LOG_DIR=<this rig>, its mark.  It ends with the
# game.
if [ "${PAD_GAMEKEYS:-$VISIBLE}" = 1 ]; then
    setsid -f python3 -u "$BOF_TOOLS/../ap_emu/gamekeys.py" --display "$DISP" \
        --mark "BOFEMU_LOG_DIR=$BOF_RIG" --sock "$BOF_RIG/hw/ctl.sock" \
        --pidfile "$BOF_RIG/game.pid" --bof-profile "$TITLE" \
        < /dev/null > "$BOF_RIG/gamekeys.log" 2>&1
fi
echo "pid=$GP"
echo "display=$DISP"
[ $DETACH = 1 ] && exit 0
while kill -0 "$GP" 2>/dev/null; do sleep 1; done
bash "$BOF_TOOLS/killgame.sh" >/dev/null 2>&1
