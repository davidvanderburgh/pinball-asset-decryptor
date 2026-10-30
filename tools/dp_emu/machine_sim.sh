#!/bin/bash
# machine_sim.sh - The Big Lebowski multi-boot, end to end on this PC (PAD-853,
# tools/dp_emu/MULTIBOOT.md): the steps a machine takes, played in the order an owner
# takes them, on a build prepare.py made from a machine's disk image.
#
#   machine_sim.sh <prepared build> <stock update zip> <multi-boot zip> <out dir>
#
#   1. ~/game as the machine has it: the image's base assets and its installed version;
#   2. the USB update installs the stock update zip (its delta laid over the installed
#      version as menuitem_usbupdate_download.py does) and Version Select picks it
#      (the database copied into it, `version` written) - the owner's stock machine;
#   3. the USB update installs the multi-boot zip (a full one: unzipped, renamed), and
#      Version Select picks it - the one step the owner takes;
#   4. run.sh - the machine's own, from the image - starts `version`, i.e. the launcher:
#      it makes the builds, shows the menu on the X server (shot 1), dpprocsw reads the
#      flippers through the stock version's own libpinproc from a fake P3-ROC
#      (aaiwshim.so), RIGHT + START are pressed (shot 2), and the chosen build starts and
#      reaches attract (shot 3);
#   5. a second power-up: nothing pressed, the countdown boots the remembered build.
#
# The one substitution: run.sh starts a version with the machine's arguments (fullscreen,
# a real P-ROC); here they are the rig's own, `fakepinproc dev` (run_game.sh), so the game
# runs on its simulated board.  The menu's board is the fake P3-ROC either way.
#
# Run as root in Ubuntu or PAD-Runtime, with PAD_SLOT=N PAD_LABEL=PAD-n (a rig of your own:
# its hidden display).  Prints VERDICT: PASS|FAIL <why>.  The game tree is /tmp/dpsim<slot>:
# the game's loader fails on a long path to its program (MULTIBOOT.md).
set -u
. "$(dirname "$0")/dppath.sh"
BUILD=${1:?usage: machine_sim.sh <prepared build> <stock zip> <multi-boot zip> <out dir>}
STOCK_ZIP=${2:?}; MB_ZIP=${3:?}; OUT=${4:?}
case "$BUILD" in /*) ;; *) BUILD=$DP_CACHE/$BUILD ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
S=/tmp/dpsim${DP_SLOT}
G=$S/game
mkdir -p "$OUT"
LOG=$OUT/machine_sim.log
: > "$LOG"
say() { echo "$*" | tee -a "$LOG"; }
verdict() { say "VERDICT: $*"; cleanup; [ "${1%% *}" = PASS ]; exit $?; }
cleanup() {
    pkill -f "^\./start fakepinproc" 2>/dev/null
    pkill -f "dpprocsw L=" 2>/dev/null
    pkill -f "dpselect --input pipe" 2>/dev/null
    [ -n "${XPID:-}" ] && kill "$XPID" 2>/dev/null
}
trap cleanup EXIT

[ "$(id -u)" = 0 ] || { echo "machine_sim.sh: run as root" >&2; exit 2; }
[ -d "$BUILD/assets" ] || { echo "machine_sim.sh: $BUILD is not a prepared build" >&2; exit 2; }

# ---- the shim: the fake P3-ROC for the menu's buttons -----------------------
SHIM=$S.aaiwshim.so
gcc -shared -fPIC -O2 -o "$SHIM" "$HERE/aaiw/aaiwshim.c" -ldl -lpthread || verdict "FAIL cannot build aaiwshim"

# ---- 1. ~/game as the machine has it ----------------------------------------
rm -rf "$S"; mkdir -p "$G/temp"
INST=$(cat "$BUILD/version")
cp -al "$(realpath "$BUILD/assets")" "$G/assets"
cp -al "$BUILD/$INST" "$G/$INST"
rm -rf "$G/$INST/database"; cp -a "$BUILD/$INST/database" "$G/$INST/database"   # the game writes it
find "$G" -name '*.wav' -size 0 | while read -r f; do       # run_game.sh's silence for an empty wav
    rm -f "$f"; ffmpeg -loglevel error -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a pcm_s16le "$f"
done
: > "$G/serial"
echo "$INST" > "$G/version"
say "1. ~/game: base assets + installed $INST"

# ---- the machine's USB update and Version Select, as the game's own code does them ----
usb_update() {      # usb_update <zip>: menuitem_usbupdate*.py
    python3 - "$G" "$1" <<'PY'
import os, re, shutil, subprocess, sys, zipfile
g, z = sys.argv[1], sys.argv[2]
name = os.path.basename(z)
m = re.search(r"TBL-v([\d.]+)", os.path.splitext(name)[0])
if not m:
    sys.exit("usb update: %s is not offered (the name is not TBL-v<version>.zip)" % name)
ver = m.group(1).rstrip(".")
if ver in next(os.walk(g))[1]:
    sys.exit("usb update: %s is not offered (version %s is already a folder)" % (name, ver))
cur = open(os.path.join(g, "version")).read().strip()
delta = []
with zipfile.ZipFile(z) as zf:
    try:
        delta = [v for v in zf.read(ver + "/delta").decode().replace(" ", "").split(",") if v]
    except KeyError:
        pass
if delta and cur not in delta:
    sys.exit("usb update: DELTA UPDATE %s CAN'T BE INSTALLED FROM THIS VERSION (%s)" % (ver, cur))
tmp = os.path.join(g, "temp")
shutil.rmtree(tmp, ignore_errors=True); os.mkdir(tmp)
shutil.copyfile(z, os.path.join(g, ver + ".zip"))
subprocess.check_call(["unzip", "-o", "-q", os.path.join(g, ver + ".zip"), "-d", tmp])
os.remove(os.path.join(g, ver + ".zip"))
new = os.path.join(tmp, ver)
if delta:
    # copytree(current assets -> new assets, ignoring what the update carries)
    cur_assets = os.path.join(g, cur, "assets")
    for root, dirs, files in os.walk(cur_assets):
        rel = os.path.relpath(root, cur_assets)
        for f in files:
            d = os.path.join(new, "assets", rel, f)
            if not os.path.exists(d):
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(os.path.join(root, f), d)
    # (only assets/: the program, its libraries and config are the update's own)
os.rename(new, os.path.join(g, ver))
print("usb update: %s installed as %s (%s)" % (name, ver, "delta over " + cur if delta else "full"))
PY
}
version_select() {  # version_select <v>: menuitem_versionselect_select.py
    local cur; cur=$(cat "$G/version")
    if [ -f "$G/$cur/database/database.db" ] && [ -d "$G/$1/database" ]; then
        cp -f "$G/$cur/database/database.db" "$G/$1/database/database.db"
    fi
    echo "$1" > "$G/version"
    say "version select: $1 (database copied from $cur)"
}

# ---- 2. the owner's stock machine ---------------------------------------------
usb_update "$STOCK_ZIP" | tee -a "$LOG" || verdict "FAIL the stock update did not install"
STOCK=$(python3 -c "import re,sys,os;print(re.search(r'TBL-v([\d.]+)',os.path.basename(sys.argv[1])).group(1).rstrip('.'))" "$STOCK_ZIP")
version_select "$STOCK"

# ---- 3. the multi-boot ---------------------------------------------------------
usb_update "$MB_ZIP" | tee -a "$LOG" || verdict "FAIL the multi-boot zip did not install"
V=$(python3 -c "import re,sys,os;print(re.search(r'TBL-v([\d.]+)',os.path.basename(sys.argv[1])).group(1).rstrip('.'))" "$MB_ZIP")
version_select "$V"
chown -R "$DP_USER": "$S"

# ---- 4. power-up: run.sh ----------------------------------------------------------
DISP=$DP_DISPLAY
setsid -f Xvfb "$DISP" -screen 0 1366x768x24 -nolisten tcp -noreset </dev/null >"$OUT/xvfb.log" 2>&1
dp_wait_display "$DISP" || verdict "FAIL the display did not come up"
XPID=$(pgrep -xf "Xvfb $DISP .*" | head -1)
# the machine's own run.sh, with the rig's arguments for the machine's (the header)
cat > "$G/run.sh" <<'RUN'
# ~/game/run.sh as a TBL machine has it (TBL_justin_113_v10.img, 2021-12-02), the rig's arguments
cd "$(dirname "$0")"
run_function() {
	version=$(cat "version")
	if [ -d $version ]; then
		cd $version
		chmod +x start
		./start fakepinproc dev >> ../run.log 2>&1
		cd ..
		echo "Finished running the game (version $version). Please check run.log for the output in case of a crash."
		if [ -f "restart" ]; then
			rm -f "restart"
			run_function
		fi
	else
		echo "Version $version could not be found. Please edit the \"version\" file so it points to an existing folder."
	fi
}
run_function
RUN
chmod +x "$G/run.sh"
FIFO=$S/proc.fifo
rm -f "$FIFO"; mkfifo "$FIFO"; chmod 666 "$FIFO"

power_up() {        # power_up <tag>
    rm -f "$S/shim.log"
    setsid -f runuser -u "$DP_USER" -- env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$S" USER="$DP_USER" \
        LANG=C.UTF-8 DISPLAY="$DISP" SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=/dev/null SDL_DISKAUDIODELAY=0 \
        AAIW_PROC_CHIP=p3 DPEMU_FIFO="$FIFO" DPEMU_LOG="$S/shim.log" PADSELECT_PROCSW_PRELOAD="$SHIM" \
        bash "$G/run.sh" </dev/null >"$OUT/run_$1.out" 2>&1
}
shot() { ffmpeg -loglevel error -y -f x11grab -video_size 1366x768 -i "$DISP+0,0" -frames:v 1 "$OUT/$1.png"; }
game_cwd() {        # the folder the running game was started in
    local p
    for p in $(pgrep -f '^\./start fakepinproc'); do readlink "/proc/$p/cwd"; done | sort -u | head -1
}
wait_menu() {
    local i
    for i in $(seq 1 200); do
        grep -q "menu: " "$G/$V/pad/padselect.log" 2>/dev/null && grep -q "pipe: ready" "$G/$V/pad/dpselect.log" 2>/dev/null && return 0
        sleep 0.3
    done
    return 1
}
wait_game() {       # wait_game <folder>
    local i
    for i in $(seq 1 300); do
        # started there, and still running 25 s later (the game's own crash ends it)
        if [ "$(game_cwd)" = "$G/$1" ]; then
            sleep 25
            [ "$(game_cwd)" = "$G/$1" ] && return 0
            return 1
        fi
        sleep 0.5
    done
    return 1
}

say "4. power-up: run.sh -> $V/start"
power_up 1
wait_menu || { cat "$G/$V/pad/padselect.log" >> "$LOG" 2>/dev/null; verdict "FAIL the menu did not come up"; }
sleep 1.5
shot 1_menu
exec 7<>"$FIFO"
SW_R=$(awk '/flipperLwR:/{f=1} f&&/number:/{print $2; exit}' "$G/$STOCK/config/machine.yaml" | tr -dc 0-9)
SW_S=$(awk '/^PRSwitches/{p=1} p&&/startButton:/{f=1} f&&/number:/{print $2; exit}' "$G/$STOCK/config/machine.yaml" | tr -dc 0-9)
echo "pulse ${SW_R:-65} 300" >&7; sleep 1.0
shot 2_menu_right
echo "pulse ${SW_S:-68} 300" >&7
B1="${V}1"
wait_game "$B1" || { cat "$G/$V/pad/padselect.log" >> "$LOG"; tail -20 "$G/run.log" >> "$LOG" 2>/dev/null; verdict "FAIL $B1 did not start"; }
shot 3_game
# attract is drawn: the screen is not one colour
python3 -c "
import sys
from PIL import Image
n = len(Image.open(sys.argv[1]).convert('RGB').getcolors(1 << 20) or [])
sys.exit(0 if n > 50 else 1)" "$OUT/3_game.png" || verdict "FAIL $B1 runs but draws nothing (3_game.png is one colour)"
grep -q "key: right" "$G/$V/pad/dpselect.log" && grep -q "key: start" "$G/$V/pad/dpselect.log" \
    || verdict "FAIL the menu did not see RIGHT and START"
[ -f "$G/$B1/.pad_build" ] || verdict "FAIL $B1 was not made by the launcher"
[ "$(stat -c %i "$G/$B1/start")" = "$(stat -c %i "$G/$STOCK/start")" ] || say "note: $B1's program is not a link to $STOCK's (its own)"
[ -f "$G/$B1/assets/pad_mark.txt" ] && say "4. the build's own file is in $B1 (assets/pad_mark.txt)"
say "4. RIGHT + START: $B1 ($(sed -n 's/.*making it from \([^ ]*\) .*/\1/p' "$G/$V/pad/padselect.log") + the build's files, made by the launcher) is running in attract"
cp "$G/$V/pad/padselect.log" "$OUT/padselect_1.log"; cp "$G/$V/pad/dpselect.log" "$OUT/dpselect_1.log"

# ---- 5. the next power-up: nothing pressed ------------------------------------------
pkill -f "^\./start fakepinproc"; sleep 2
pkill -f "bash $G/run.sh" 2>/dev/null
power_up 2
wait_menu || verdict "FAIL the menu did not come back at the second power-up"
wait_game "$B1" || { cat "$G/$V/pad/padselect.log" >> "$LOG"; verdict "FAIL the countdown did not boot the remembered $B1"; }
grep -q "making it" "$G/$V/pad/padselect.log" && verdict "FAIL $B1 was made again"
say "5. second power-up: the countdown booted the remembered $B1, not made again"
cp "$G/$V/pad/padselect.log" "$OUT/padselect_2.log"
verdict "PASS stock $STOCK + $B1 from $(basename "$MB_ZIP"): menu on X, buttons through $STOCK's libpinproc, the build made, booted, remembered"
