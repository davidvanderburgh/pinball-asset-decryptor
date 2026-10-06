#!/bin/bash
# run_game.sh <build> [--visible] [--audio]
#
# Start a Spooky P-ROC game on this PC: the title's own Python 2.7 code and
# its own procgame, on tools/proc_emu's emulated P3-ROC (pinproc =
# proc_emu's pure-Python stub, the board seeded from the title's machine
# yaml: trough full, every other switch at rest).  Alice Cooper's screen is
# its own Unity player, started first as the machine's xinitrc does.
# <build> is a folder prepare.py made (a name under $SPP_CACHE or a path).
# Run as root; the game runs as $SPP_USER.  Returns once the game is in
# attract (or died).
#
#   --visible    draw on the WSLg desktop instead of the slot's hidden Xvfb
#                display (the default: windows popping up are disruptive;
#                shot.sh shows a hidden run)
#   --audio      play sound through WSLg's PulseAudio (default: SDL's disk
#                writer into /dev/null).  A hidden run stays silent unless
#                PAD_AUDIO_ASKED=1 (tools/rigboard.sh).  PAD_AUDIO_CTL (the
#                app's audio_ctl.json, a Linux path) holds it at the app's
#                Volume / Mute, live (tools/spooky_emu/spkvol.py)
#
# The game runs in a network + mount namespace of the rig's own: the rig's
# copy of the build is bind-mounted where the machine keeps it
# (/game/RickAndMorty, /game/code - both games and the Unity player use
# those paths), and Alice Cooper's 127.0.0.1:9999 is private to the slot.
# The copy is hard-linked from the cache; the game writes only new files
# (settings, audits, high scores).  Switches: sw.sh.  Picture: shot.sh.
# Stop: killgame.sh.
set -u
. "$(dirname "$0")/sppath.sh"
BUILD=${1:-}; shift 2>/dev/null || true
VISIBLE=0; AUDIO=0
while [ $# -gt 0 ]; do
    case "$1" in
        --visible) VISIBLE=1 ;;
        --audio) AUDIO=1 ;;
        *) echo "run_game.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
case "$BUILD" in /*) ;; "") ;; *) BUILD=$SPP_CACHE/$BUILD ;; esac
[ -n "$BUILD" ] && [ -f "$BUILD/title" ] || { echo "run_game.sh: not a prepared build: ${BUILD:-<none>} (prepare.py)" >&2; exit 2; }
[ -f "$SPP_ROOT/site/.ready" ] || { echo "run_game.sh: no $SPP_ROOT/site (setup.sh)" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to $SPP_USER itself)" >&2; exit 2; }
[ -n "$SPP_USER" ] || { echo "run_game.sh: no ordinary user account to run the game as" >&2; exit 2; }

# Per title: where the machine keeps it, what starts it, the machine yaml
# (the one the game itself loads), the screen, and the board's ball model
# (the trough's eject coil, the shooter lane switch, the launch coil; see
# spprun.py).
TITLE=$(cat "$BUILD/title")
case "$TITLE" in
    rm) DIR=RickAndMorty; LAUNCH=RMGame.pyc; YAML=config/RM_PROTOTYPE1.yaml
        SCREEN=1280x720; NAME="Rick and Morty"; UNITY=
        BALLS="eject=troughEject shooter=shooterLane launch=autoPlunger" ;;
    ac) DIR=code; LAUNCH=ACGame.py; YAML=config/alice.yaml
        SCREEN=1366x768; NAME="Alice Cooper's Nightmare Castle"; UNITY=uptest/main.x86_64
        BALLS="eject=trough shooter=shooter launch=autoFire" ;;
    *) echo "run_game.sh: unknown title '$TITLE' in $BUILD/title" >&2; exit 2 ;;
esac

bash "$SPP_TOOLS/killgame.sh" >/dev/null 2>&1

rm -rf "$SPP_RIG"
mkdir -p "$SPP_RIG/game"
cp -al "$(realpath "$BUILD")" "$SPP_RIG/game/$DIR"
rm -f "$SPP_RIG/game/$DIR/title"
echo "$BUILD" > "$SPP_RIG/build"
echo "$VISIBLE" > "$SPP_RIG/visible"
echo "$TITLE" > "$SPP_RIG/title"
echo "$NAME" > "$SPP_RIG/name"
touch "$(realpath "$BUILD")/used"            # the Cache window's "Last played"
# The game creates files anywhere in its tree (config/game_user_*.yaml,
# /game/log.txt), so it owns every directory; the files stay root's - they
# are the cache's own inodes (hard links), and the game must not rewrite
# them.  A file it does rewrite is copied first (below).
chown "$SPP_USER": "$SPP_RIG"
find "$SPP_RIG/game" -type d -exec chown "$SPP_USER": {} +
# Alice Cooper's Unity player uses /game/code/... only when this file exists
# (else its developer's C:/ALICECOOPER/...).
# Its launcher reads two files of the machine's OS and, finding them missing,
# copies its own over them and reboots (spprun.py's SPP_OSFILES): they are
# answered with copies of the package's own, taken before the launcher
# deletes its codeupdate.
OSFILES=
if [ "$TITLE" = ac ]; then
    : > "$SPP_RIG/game/DO_NOT_DELETE"
    mkdir -p "$SPP_RIG/os"
    cp "$BUILD/codeupdate" "$SPP_RIG/os/codeupdate"
    cp "$BUILD/xinitrc" "$SPP_RIG/os/xinitrc"
    OSFILES="/sbin/codeupdate=$SPP_RIG/os/codeupdate;/etc/X11/xinit/xinitrc=$SPP_RIG/os/xinitrc"
fi
: > "$SPP_RIG/rig.log"
chown "$SPP_USER": "$SPP_RIG/rig.log"     # spprun.py writes it too

# The board, seeded from the machine yaml: the trough full of balls (an NC
# trough opto with a ball is open), everything else at rest.  prochw.py
# needs PyYAML, which PAD-Runtime's python lacks and AP's py3 env has.
PATH=$SPP_PY3/bin:$PATH PAD_SLOT=$SPP_SLOT bash "$SPP_PROC/hw.sh" --yaml "$SPP_RIG/game/$DIR/$YAML" \
    >> "$SPP_RIG/rig.log" \
    || { echo "run_game.sh: the board did not come up" >&2; exit 3; }
FPGA=$(. "$SPP_PROC/procpath.sh"; echo "$PROC_FPGA")
CTL=$(. "$SPP_PROC/procpath.sh"; echo "$PROC_CTL")
chmod 666 "$FPGA"
# The virtual playfield's table (the AP window's format, as the Warden
# games'), from the same yaml, numbered as the board numbers it.
SHOOTER=$(echo "$BALLS" | tr ' ' '\n' | sed -n 's/^shooter=//p')
"$SPP_PY3/bin/python3" "$SPP_TOOLS/sppswitches.py" "$SPP_RIG/game/$DIR/$YAML" "$NAME" "$SHOOTER" \
    > "$SPP_RIG/switches.json.tmp" 2>> "$SPP_RIG/rig.log" \
    && mv "$SPP_RIG/switches.json.tmp" "$SPP_RIG/switches.json" \
    || echo "run_game.sh: no switches.json - the virtual playfield will not open" >&2

# A hidden run's Xvfb starts inside the namespace (netns.sh): WSLg mounts
# /tmp/.X11-unix read-only, so Xvfb can only listen on its abstract socket,
# and an abstract socket belongs to one network namespace.
if [ $VISIBLE = 1 ]; then DISP=${DISPLAY:-:0}; XVFB=0; else DISP=$SPP_DISPLAY; XVFB=1; fi
echo "$DISP" > "$SPP_RIG/display"
echo "$SCREEN" > "$SPP_RIG/screen"
echo "$SCREEN" > "$SPP_RIG/window"

AUDIO=$(rigboard_audio "$VISIBLE" "$AUDIO")
if [ "$AUDIO" = 1 ] && [ -S /mnt/wslg/PulseServer ]; then
    # No shared memory with WSLg's PulseAudio, as on the AP rig: the py27
    # env's libpulse (no memfd) wants WSLg's /dev/shm, which this distro
    # cannot see, and then fails the whole connection ("shm_open() failed"
    # -> "Could not connect to PulseAudio") - the game started with its
    # sound off on every visible run (PAD-405).
    echo 'enable-shm = no' > "$SPP_RIG/pulse-client.conf"
    AUDIO_ENV="SDL_AUDIODRIVER=pulse PULSE_SERVER=unix:/mnt/wslg/PulseServer PULSE_CLIENTCONFIG=$SPP_RIG/pulse-client.conf"
else
    AUDIO_ENV="SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=/dev/null SDL_DISKAUDIODELAY=0"
fi
mkdir -p /game     # the mount point only; nothing is ever written to it

# Detached whole (setsid -f, stdin closed): a child of the wsl.exe that
# started this dies with it (tools/bof_emu learned it).
# shellcheck disable=SC2086
setsid -f unshare --net --mount --propagation private \
    env SPP_TOOLS="$SPP_TOOLS" SPP_RIG="$SPP_RIG" SPP_PY="$SPP_PY" SPP_USER="$SPP_USER" \
        SPP_SITE="$SPP_ROOT/site" SPP_STUB="$SPP_PROC/pystub" SPP_DIR="$DIR" SPP_LAUNCH="$LAUNCH" \
        SPP_UNITY="$UNITY" SPP_OSFILES="$OSFILES" SPP_SCREEN="$SCREEN" SPP_XVFB=$XVFB DISPLAY="$DISP" \
        SPP_BALLS="$BALLS" PROC_EMU_FPGA="$FPGA" PROC_EMU_CTL="$CTL" SPP_VISIBLE=$VISIBLE $AUDIO_ENV \
    bash "$SPP_TOOLS/netns.sh" < /dev/null >> "$SPP_RIG/rig.log" 2>&1

# Up = the game's run loop is going and attract has shown its first page:
# spprun.py writes `attract` beside the log when the title's attract mode
# starts.  A cold cache reads ~3 GB of assets first.
for i in $(seq 1 1800); do
    [ -f "$SPP_RIG/attract" ] && break
    [ "$i" -gt 50 ] && ! spp_alive game && break
    sleep 0.1
done
# The app's Volume / Mute, live, as on the Warden rig: spkvol.py finds the
# game's (and Alice Cooper's player's) streams by SPK_MARK (netns.sh).
if [ "$AUDIO" = 1 ] && [ -n "${PAD_AUDIO_CTL:-}" ] && [ -S /mnt/wslg/PulseServer ] && spp_alive game; then
    setsid -f python3 "$SPP_TOOLS/../spkvol.py" --ctl "$PAD_AUDIO_CTL" --rig "$SPP_RIG" \
        < /dev/null >> "$SPP_RIG/spkvol.log" 2>&1
fi
if spp_alive game && [ -f "$SPP_RIG/attract" ]; then
    rigboard_post spooky-proc "$SPP_SLOT" "$(spp_pid game)" "$(basename "$BUILD")" "$NAME" "$VISIBLE" "$AUDIO"
    # The playfield window's keys in the game's own window too, as on the
    # Warden rig (PAD-313): gamekeys.py speaks the Warden board's ctl.sock,
    # which sppctl.py --serve answers from this board (its own socket has no
    # pause or reset).  The game's own key map is off (spprun.py), so a key
    # means one thing in both windows.  Both end with the game (PAD-405).
    if [ "${PAD_GAMEKEYS:-$VISIBLE}" = 1 ]; then
        PAD_SLOT=$SPP_SLOT SPP_ROOT=$SPP_ROOT setsid -f python3 "$SPP_TOOLS/sppctl.py" --serve "$SPP_RIG/ctl.sock" \
            < /dev/null >> "$SPP_RIG/gamekeys.log" 2>&1
        for _ in $(seq 1 30); do [ -S "$SPP_RIG/ctl.sock" ] && break; sleep 0.1; done
        setsid -f python3 -u "$SPP_TOOLS/../../ap_emu/gamekeys.py" --display "$DISP" \
            --mark "SPK_MARK=$SPP_RIG" --sock "$SPP_RIG/ctl.sock" \
            --pidfile "$SPP_RIG/game.pid" --table "$SPP_RIG/switches.json" \
            < /dev/null >> "$SPP_RIG/gamekeys.log" 2>&1
    fi
    echo "Ready: $(basename "$BUILD"), slot $SPP_SLOT, display $DISP"
else
    echo "run_game.sh: the game did not come up:" >&2
    tail -20 "$SPP_RIG/game.out" >&2
    exit 1
fi
