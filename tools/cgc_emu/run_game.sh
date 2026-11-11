#!/bin/bash
# run_game.sh [<build>] - start a Chicago Gaming WPC remake on this PC, under
# qemu-arm, on the rig's emulated hardware (cgcshim.so).  <build> is a
# folder prepare.sh made (a name under $CGC_CACHE or a path; default: the
# newest there).  Run as root; the game runs as $CGC_USER.  Returns once the
# game reached attract mode (or died).
#
# Always hidden and muted: the game draws into a file ($CGC_RIG/fb, shot.sh
# makes a picture of it) and SDL's dummy audio driver takes its sound.  A
# window and speakers are the app's Emulate tab's business (a follow-up).
#
# The machine runs /home/debian/emumm/emumm from its own folder (it opens
# ../emumm/appdata/rom/... and ./cgc.so relative to it; Cactus Canyon's
# /home/debian/pin/pin opens ./ccdata/...).  Here that folder
# is $CGC_RIG/home/emumm, the build hard-linked, with the files the game
# writes linked to this slot's kept copies in $CGC_NV (the FRAM, CGC's
# adjustments samadj.bin, the clock offset); CGC_FRESH=1 starts over.  The
# game logs to /tmp/z4.log (pin: /tmp/z5.log), so it gets a private /tmp
# ($CGC_RIG/tmp).
#
# A fresh FRAM makes the Williams ROM restore factory settings and wait for
# the operator; run_game.sh presses ENTER, then ESCAPE until attract, as an
# operator would, until a run of this slot and title has reached attract
# once ($CGC_NV/.attract).
# Switches: sw.py.  Picture: shot.sh.  Stop: killgame.sh.
set -u
. "$(dirname "$0")/cgcpath.sh"
BUILD=
while [ $# -gt 0 ]; do
    case "$1" in
        --visible|--audio) echo "run_game.sh: $1: not yet - the rig runs hidden and muted" >&2 ;;
        -*) echo "run_game.sh: unknown option $1" >&2; exit 2 ;;
        *) BUILD=$1 ;;
    esac
    shift
done
[ -z "$BUILD" ] && BUILD=$(ls -1td "$CGC_CACHE"/*/ 2>/dev/null | head -1)
case "$BUILD" in /*) ;; "") ;; *) BUILD=$CGC_CACHE/$BUILD ;; esac
BUILD=${BUILD%/}
[ -n "$BUILD" ] && [ -f "$BUILD/.complete" ] ||
    { echo "run_game.sh: not a prepared build: ${BUILD:-<none>} (prepare.sh)" >&2; exit 2; }
[ -f "$CGC_SHIM" ] || { echo "run_game.sh: no $CGC_SHIM (build.sh)" >&2; exit 2; }
[ -n "$CGC_QEMU" ] || { echo "run_game.sh: no qemu-arm-static" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run_game.sh: run as root (it drops to $CGC_USER itself)" >&2; exit 2; }
[ -n "$CGC_USER" ] || { echo "run_game.sh: no ordinary user account to run the game as" >&2; exit 2; }

TITLE=$(cat "$BUILD/.pad_title")
PROG=$(cat "$BUILD/.pad_program")
case "$PROG" in emumm|pin) ;; *) echo "run_game.sh: $TITLE runs $PROG, which this rig does not drive" >&2; exit 4 ;; esac

bash "$CGC_TOOLS/killgame.sh" >/dev/null 2>&1

rm -rf "$CGC_RIG"
G=$CGC_RIG/home/$PROG
mkdir -p "$CGC_RIG/home" "$CGC_RIG/tmp"
cp -al "$(realpath "$BUILD/$PROG")" "$G"
NV=$CGC_ROOT/nv$CGC_SLOT/$TITLE
[ "${CGC_FRESH:-0}" = 1 ] && rm -rf "$NV"
mkdir -p "$NV"
FRESH=0; [ -f "$NV/.attract" ] || FRESH=1
for f in samadj.bin host_clock_offset.bin; do
    [ -f "$NV/$f" ] || { [ -f "$G/$f" ] && cp "$G/$f" "$NV/$f"; }
    rm -f "$G/$f"
    [ -f "$NV/$f" ] && ln -s "$NV/$f" "$G/$f"
done
# The ROM's switch / coil names and the ball model, from this checkout's
# tables (prepare.sh's copies in the build are what the card was checked with)
ROM=$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import cgctitles; print(cgctitles.find_rom(sys.argv[2]) or "")'     "$CGC_TOOLS" "$G")
python3 "$CGC_TOOLS/cgcroms.py" "$ROM" --json > "$CGC_RIG/names.json" &&
    python3 "$CGC_TOOLS/cgctitles.py" balls "$TITLE" "$CGC_RIG/names.json" > "$CGC_RIG/balls" ||
    cp "$BUILD/.pad_balls" "$CGC_RIG/balls"
mkfifo "$CGC_RIG/ctl"
: > "$CGC_RIG/events"
echo "$BUILD" > "$CGC_RIG/build"
echo "$TITLE" > "$CGC_RIG/title"
touch "$(realpath "$BUILD")/.used"
chown -R "$CGC_USER": "$CGC_RIG" "$NV"
chmod 1777 "$CGC_RIG/tmp"

ENVS="PATH=/usr/bin:/bin HOME=$CGC_RIG/home USER=$CGC_USER LANG=C \
CGC_MARK=$CGC_RIG CGC_FB=$CGC_RIG/fb CGC_CTL=$CGC_RIG/ctl CGC_STATE=$CGC_RIG/state \
CGC_EVENTS=$CGC_RIG/events CGC_LOG=$CGC_RIG/shim.log CGC_NV=$NV/fram.bin \
SDL_AUDIODRIVER=dummy"
# ns.sh: a private /tmp for the game's z4.log, then the game.  Detached
# whole (setsid -f, stdin closed): a child of runuser dies with the wsl.exe
# that started this (tools/bof_emu learned it).
cat > "$CGC_RIG/ns.sh" <<EOF
echo \$\$ > $CGC_RIG/ns.pid
mount --bind $CGC_RIG/tmp /tmp || exit 1
cd $G || exit 1
exec runuser -u $CGC_USER -- env -i $ENVS CGC_BALLS="$(cat "$CGC_RIG/balls")" \
    $CGC_QEMU -L $BUILD/sysroot -E LD_PRELOAD=$CGC_SHIM ./$PROG
EOF
setsid -f unshare -m --propagation private bash "$CGC_RIG/ns.sh" \
    < /dev/null > "$CGC_RIG/game.out" 2>&1
for _ in $(seq 1 50); do
    p=$(cgc_slot_pids | head -1)
    [ -n "$p" ] && { echo "$p" > "$CGC_RIG/game.pid"; break; }
    sleep 0.1
done
cgc_game_alive || { echo "run_game.sh: the game did not start:" >&2; cat "$CGC_RIG/game.out" "$CGC_RIG/shim.log" >&2 2>/dev/null; exit 1; }

# Up = attract mode: the game drives its lamps (they are all off while it
# boots, restores factory settings or sits in the service menu).
lamps_on() { grep -q '^lamps ' "$CGC_RIG/state" 2>/dev/null && ! grep -q '^lamps 0000000000000000$' "$CGC_RIG/state"; }
# pin (Cactus Canyon) drives a few lamps from the moment its output tables
# load, long before attract: there, up = the board at rest and the lamps
# moving (a lamp show), not merely some lit
if [ "$PROG" = pin ]; then
    first_lamps=
    lamps_on() {
        local l
        grep -q '^idle 1$' "$CGC_RIG/state" 2>/dev/null || return 1
        l=$(sed -n 's/^lamps //p' "$CGC_RIG/state" 2>/dev/null)
        [ -n "$l" ] && [ "$l" != 0000000000000000 ] || return 1
        [ -z "$first_lamps" ] && { first_lamps=$l; return 1; }
        [ "$l" != "$first_lamps" ]
    }
fi
tap() { echo "$1 1" > "$CGC_RIG/ctl"; sleep 0.2; echo "$1 0" > "$CGC_RIG/ctl"; }
up=0
for i in $(seq 1 600); do
    lamps_on && { up=1; break; }
    cgc_game_alive || break
    # a fresh FRAM: FACTORY SETTINGS RESTORED waits for the operator
    if [ $FRESH = 1 ] && [ "$i" = 400 ]; then
        echo "fresh settings: ENTER, then ESCAPE until attract" >> "$CGC_RIG/shim.log"
        tap "sys 0 7"; sleep 3
        for _ in $(seq 1 12); do tap "sys 0 4"; sleep 5; lamps_on && break; done
    fi
    sleep 0.1
done
if [ $up = 1 ]; then
    touch "$NV/.attract"
    echo "Ready: $(basename "$BUILD"), slot $CGC_SLOT"
    rigboard_post cgc "$CGC_SLOT" "$(cgc_game_pid)" "$(basename "$BUILD")" \
        "${PAD_TITLE:-$(python3 "$CGC_TOOLS/cgctitles.py" get "$TITLE" title)}" 0 0
else
    echo "run_game.sh: the game did not reach attract:" >&2
    tail -20 "$CGC_RIG/shim.log" "$CGC_RIG/tmp/z4.log" "$CGC_RIG/tmp/z5.log" "$CGC_RIG/game.out" >&2 2>/dev/null
    exit 1
fi
