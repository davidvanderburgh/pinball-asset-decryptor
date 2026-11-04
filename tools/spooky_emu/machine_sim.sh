#!/bin/bash
# machine_sim.sh <stock update> [<work dir>] - the Spooky multi-boot proven in the rig, end to
# end (PAD-980, MULTIBOOT.md): a marked build of the update (spkmarkmod.py) and the stock one
# made into ONE multi-boot update (mkspkmulti.py), installed into this slot's /game the way
# the title's own install leaves it, then two power-ups through the title's start command
# (run_game.sh, SPK_MACHINE=1: /game is one file system, as on the cabinet):
#
#   1  the launcher moves pad/ to /game/pad, makes b1, the menu comes up on the screen with
#      the board's buttons (shot menu.png); RIGHT + START on the board pick b1; the game
#      reaches attract running /game/pad/b1/uptest/main.x86_64, the paths showing b1's files
#      (shot attract.png)
#   2  the next power-up: nobody presses, the countdown boots the remembered b1, b1 is not
#      made again
#
# As root in the rig's distro, with PAD_SLOT set to a slot you took (riglock.sh).  Prints
# PASS / FAIL lines and "machine_sim: PASS" at the end.  The shots and logs are in <work dir>
# (default /var/tmp/pad_spooky/msim<slot>).
set -u
T=$(cd "$(dirname "$0")" && pwd)
. "$T/spkpath.sh"
UPD=$(realpath "${1:?usage: machine_sim.sh <stock update> [work dir]}")
W=${2:-$SPK_ROOT/msim$SPK_SLOT}
[ "$(id -u)" = 0 ] || { echo "machine_sim: run as root" >&2; exit 2; }
[ -n "${PAD_SLOT:-}" ] && [ "$PAD_SLOT" != 0 ] || { echo "machine_sim: set PAD_SLOT to a slot you took (riglock.sh take --any)" >&2; exit 2; }
FAILS=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; FAILS=$((FAILS + 1)); }
mkdir -p "$W"

# ---- the inputs --------------------------------------------------------------------
echo "== prepare the stock build (the rig's settings for the title)"
BUILD=$(bash "$T/prepare.sh" "$UPD" | sed -n 's/^build=//p')
[ -n "$BUILD" ] || { echo "machine_sim: prepare.sh failed" >&2; exit 1; }
TITLE=$(cat "$SPK_CACHE/$BUILD/.pad_title")
LAYOUT=$(python3 "$T/spktitles.py" get "$TITLE" layout)
echo "build $BUILD, title $TITLE, layout $LAYOUT"
echo "== the marked build and the multi-boot update"
rm -rf "$W/mod" "$W/multi" "$W/update"
MOD=$(python3 "$T/spkmarkmod.py" "$UPD" "$W/mod" "PAD-980 marked build") || { echo "machine_sim: spkmarkmod failed" >&2; exit 1; }
SEL=$(bash "$T/ensurespkselect.sh" x "$W/sel" | sed -n 's/^\[selector\] menu program: //p')
[ -n "$SEL" ] || { echo "machine_sim: no menu program" >&2; exit 1; }
mkdir -p "$W/multi"
python3 "$T/mkspkmulti.py" build --primary "$UPD" --extra "$MOD" --out "$W/multi" --selector-dir "$SEL" \
    --timeout 20 --titles "STOCK;MARKED" --subtitles "as shipped;PAD-980 marked build" \
    --cache-dir "$W/cache" || { echo "machine_sim: the build failed" >&2; exit 1; }
MULTI=$W/multi/$(basename "$UPD")
python3 "$T/mkspkmulti.py" verify --zip "$MULTI" && pass "the update verifies" || fail "verify"

# ---- the install, as the title's own leaves it --------------------------------------
echo "== install it into the slot's /game"
NV=$SPK_ROOT/nv$SPK_SLOT/$TITLE
rm -rf "$NV/game/code" "$NV/game/pad" "$NV/game/backup"
mkdir -p "$W/update" "$NV/game/code/uptest"
TAR=$(cd "$T" && python3 -c "import sys, mkspkmulti as m; print(m.SpkUpdate(sys.argv[1]).tar_path(sys.argv[2]))" "$MULTI" "$W/cache")
tar -xf "$TAR" -C "$W/update" || { echo "machine_sim: cannot unpack the update" >&2; exit 1; }
if [ "$LAYOUT" = flat ]; then
    cp -a "$W/update/." "$NV/game/code/uptest/"            # .profile: gcp -rf /game/update/* uptest/
else
    cp -a "$W/update/uptest/." "$NV/game/code/uptest/"
    case "$TITLE" in
        h78|um)   # the helper moves only what the update carries: the stock assets and config stay
            for d in assets config; do
                [ -d "$SPK_CACHE/$BUILD/$d" ] && cp -al "$SPK_CACHE/$BUILD/$d" "$NV/game/code/$d"
            done ;;
        *)        # the profile empties them and copies the update's (it has none)
            mkdir -p "$NV/game/code/assets" "$NV/game/code/config" ;;
    esac
fi
chmod +x "$NV/game/code/uptest/main.x86_64"
touch "$NV/game/code/uptest/.update_file"
rm -rf "$W/update"
head -3 "$NV/game/code/uptest/main.x86_64" | grep -q "multi-boot launcher" && pass "uptest/main.x86_64 is the launcher" \
    || fail "uptest/main.x86_64 is not the launcher"

ctl() { python3 -c "
import socket, sys
s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); s.sendall((sys.argv[2] + '\n').encode()); s.recv(200)" \
    "$SPK_RIG/ctl.sock" "$1"; }
sw_of() { sed -n "s/^$1=//p" "$NV/game/pad/spk.conf" | tail -1; }
power_up() {    # power_up <n> <press: yes|no>
    local n=$1 press=$2 log=$NV/game/pad/padselect.log i
    echo "== power-up $n"
    rm -f "$W/run$n.out"
    # the last power-up's log would answer for this one before the launcher rotates it
    [ -f "$log" ] && mv -f "$log" "$W/padselect$((n - 1)).log"
    SPK_MACHINE=1 bash "$T/run_game.sh" "$BUILD" > "$W/run$n.out" 2>&1 &
    local rg=$!
    for i in $(seq 1 600); do
        grep -qs "^.* menu: " "$log" && break
        kill -0 $rg 2>/dev/null || break
        sleep 0.2
    done
    if grep -qs " menu: " "$log"; then
        pass "$n: the menu is up ($(grep -o 'menu: .*' "$log"))"
        sleep 3
        bash "$T/shot.sh" "$W/menu$n.png" >/dev/null 2>&1 || ffmpeg -loglevel error -y -f x11grab -video_size 1920x1080 \
            -i "$(cat "$SPK_RIG/display")+0,0" -frames:v 1 "$W/menu$n.png"
        if [ "$press" = yes ]; then
            ctl "tap $(sw_of R) 300"; sleep 1.0
            ctl "tap $(sw_of S) 600"
        fi
    else
        fail "$n: no menu (padselect.log: $(tail -3 "$log" 2>/dev/null | tr '\n' '|'))"
    fi
    wait $rg
    echo "run_game: $(tail -1 "$W/run$n.out")"
}

# ---- 1 ------------------------------------------------------------------------------
power_up 1 yes
L=$NV/game/pad/padselect.log
[ -d "$NV/game/pad/b1" ] && [ ! -e "$NV/game/code/uptest/pad" ] && grep -q "moved there from the update" "$L" \
    && pass "1: pad/ moved to /game/pad, b1 made" || fail "1: pad/b1 ($(ls "$NV/game" | tr '\n' ' '))"
grep -q "buttons: .* reader pid" "$L" \
    && pass "1: $(grep -o 'buttons: .*' "$L")" || fail "1: no button reader"
grep -q "choice '1'" "$L" && pass "1: RIGHT + START on the board picked card 1" || fail "1: the pick ($(grep -o "choice '.*'" "$L"))"
p=$(spk_game_pid)
exe=$(readlink "/proc/$p/exe" 2>/dev/null)
case "$exe" in */pad/b1/uptest/main.x86_64) pass "1: the game runs $exe";; *) fail "1: the game runs '$exe' (pid $p)";; esac
spk_attract && pass "1: $TITLE in attract" || fail "1: no attract"
# the links name /game/..., which only the game's mount namespace has: read them as it would
lk=$(readlink "$NV/game/code/uptest/PAD_MULTIBOOT_MARK")
[ "$lk" = /game/pad/live/uptest/PAD_MULTIBOOT_MARK ] && [ "$(readlink "$NV/game/pad/live")" = b1 ] \
    && [ "$(cat "$NV/game/pad/b1/uptest/PAD_MULTIBOOT_MARK" 2>/dev/null)" = "PAD-980 marked build" ] \
    && pass "1: uptest shows b1's own file (-> $lk, live = b1)" || fail "1: uptest does not show b1's mark ('$lk')"
sleep 5
bash "$T/shot.sh" "$W/attract1.png" >/dev/null 2>&1 && pass "1: shot $W/attract1.png"
bash "$T/stop.sh" >/dev/null 2>&1; bash "$T/killgame.sh" >/dev/null 2>&1

# ---- 2 ------------------------------------------------------------------------------
power_up 2 no
L=$NV/game/pad/padselect.log
grep -q "making it" "$L" && fail "2: b1 made again" || pass "2: b1 not made again"
grep -q "starting b1" "$L" && pass "2: the countdown booted the remembered b1" || fail "2: $(grep -o 'starting .*' "$L")"
spk_attract && pass "2: $TITLE in attract" || fail "2: no attract"
bash "$T/stop.sh" >/dev/null 2>&1; bash "$T/killgame.sh" >/dev/null 2>&1
cp "$NV/game/pad/padselect.log" "$W/padselect2.log" 2>/dev/null

echo "machine_sim: $([ $FAILS = 0 ] && echo PASS || echo "$FAILS FAILED") ($TITLE, shots in $W)"
exit $((FAILS > 0))
