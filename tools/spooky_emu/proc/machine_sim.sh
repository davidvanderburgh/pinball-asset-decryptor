#!/bin/bash
# machine_sim.sh <stock rm-gamecode / ac-gamecode .pkg> [<work dir>] - the Spooky P-ROC
# multi-boot proven in the rig, end to end (PAD-980, ../MULTIBOOT.md "P-ROC titles"): a marked
# build of the package (../spkmarkmod.py) and the stock one made into ONE multi-boot package
# (../mkspkmulti.py), installed into a /game of its own the way the title's codeupdate leaves
# it, the package's hook run (sandboxed: a mount namespace, the machine's root commands as
# no-ops), then two power-ups through the launcher the hook installed:
#
#   1  the hook: .pad in place, the start script (Rick and Morty's rmstart.sh / Alice Cooper's
#      xinitrc) runs the launcher; the menu comes up on the rig's display; RIGHT + START
#      through dpprocsw on Rick and Morty's own libpinproc over tools/dp_emu's fake P3-ROC
#      pick b1; b1 is moved into the game's folder, its mark there; the game reaches attract
#   2  the next power-up: nobody presses, the countdown boots the remembered b1, no swap
#
# Spooky's own install step (Rick and Morty's run-on-update.sh: firmware, libraries, pacman)
# is the machine's and is NOT run here.  As root in PAD-Runtime with PAD_SLOT set to a slot
# you took (riglock.sh).  Prints PASS / FAIL lines and "machine_sim: PASS" at the end.
set -u
T=$(cd "$(dirname "$0")" && pwd)
SPK=$(cd "$T/.." && pwd)
REPO=$(cd "$SPK/../.." && pwd)
. "$T/sppath.sh"
UPD=$(realpath "${1:?usage: machine_sim.sh <stock .pkg> [work dir]}")
W=${2:-$SPP_ROOT/msim$SPP_SLOT}
[ "$(id -u)" = 0 ] || { echo "machine_sim: run as root" >&2; exit 2; }
[ -n "${PAD_SLOT:-}" ] && [ "$PAD_SLOT" != 0 ] || { echo "machine_sim: set PAD_SLOT to a slot you took" >&2; exit 2; }
FAILS=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; FAILS=$((FAILS + 1)); }
rm -rf "$W"; mkdir -p "$W"

echo "== prepare the stock build (the rig's settings for the title)"
BUILD=$(python3 "$T/prepare.py" "$UPD" | sed -n 's/^build=//p')
[ -n "$BUILD" ] || { echo "machine_sim: prepare.py failed" >&2; exit 1; }
TITLE=$(cat "$SPP_CACHE/$BUILD/title")
case "$TITLE" in
    rm) DIR=RickAndMorty; R=8;  S=15 ;;
    ac) DIR=code;         R=10; S=15 ;;
    *) echo "machine_sim: title $TITLE?" >&2; exit 1 ;;
esac
echo "build $BUILD, title $TITLE"

echo "== the marked build and the multi-boot package"
MOD=$(python3 "$SPK/spkmarkmod.py" "$UPD" "$W/mod" "PAD-980 marked build" | tail -1) && [ -f "$MOD" ] \
    || { echo "machine_sim: spkmarkmod failed" >&2; exit 1; }
SEL=$(bash "$SPK/ensurespkselect.sh" x "$W/sel" | sed -n 's/^\[selector\] menu program: //p')
[ -n "$SEL" ] || { echo "machine_sim: no menu program" >&2; exit 1; }
mkdir -p "$W/multi"
python3 "$SPK/mkspkmulti.py" build --primary "$UPD" --extra "$MOD" --out "$W/multi" --selector-dir "$SEL" \
    --timeout 20 --titles "STOCK;MARKED" --subtitles "as shipped;PAD-980 marked build" --cache-dir "$W/cache" \
    || { echo "machine_sim: the build failed" >&2; exit 1; }
MULTI=$W/multi/$(basename "$UPD")
python3 "$SPK/mkspkmulti.py" verify --update "$MULTI" && pass "the package verifies" || fail "verify"

echo "== install it as codeupdate does"
GAME=$W/game
G=$GAME/$DIR
mkdir -p "$G" "$GAME/images/launch/.local"
ZIP=$(cd "$SPK" && python3 -c "import sys, mkspkmulti as m; print(m.SpkUpdate(sys.argv[1]).tar_path(sys.argv[2]))" \
      "$MULTI" "$W/cache" | tail -1)
if [ "$TITLE" = rm ]; then
    # codeupdate: rm -rf /game/RickAndMorty/*; pkgprocess: unzip -o into it
    python3 -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$ZIP" "$G"
    printf '#!/bin/bash\ncd /game/RickAndMorty && exec python RMGame.pyc\n' > "$GAME/images/launch/.local/rmstart.sh"
else
    # codeupdate: rm -rf /game/code/*; pkgprocess: unzip into extracted/, cp -rf extracted/* /game/code/
    python3 -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$ZIP" "$W/extracted"
    cp -rf "$W/extracted"/* "$G/"
    rm -rf "$W/extracted"
    mkdir -p "$W/xinit"
    cp "$G/xinitrc" "$W/xinit/xinitrc"                      # the stock one, as the machine has it
fi
# zip members keep their modes when extracted by unzip; Python's extractall does not
find "$G" -name "*.sh" -exec chmod +x {} +
chmod +x "$G/uptest/main.x86_64" "$G/PAD_MULTIBOOT/"{spkselect,dpprocsw} 2>/dev/null
[ -f "$G/PAD_MULTIBOOT_LIVE" ] && [ -d "$G/PAD_MULTIBOOT" ] && pass "installed: the stock build in $DIR, PAD_MULTIBOOT beside it" \
    || fail "the install left no PAD_MULTIBOOT"

echo "== the package's hook, sandboxed"
mkdir -p "$W/bin"
for c in unlock-root lock-root reboot chown pacman pinprocfw; do
    printf '#!/bin/sh\necho "%s $*" >> %s/hook_shell.log\n' "$c" "$W" > "$W/bin/$c"; chmod 755 "$W/bin/$c"
done
if [ "$TITLE" = rm ]; then
    rm -f "$G/PAD_MULTIBOOT/run-on-update.stock.sh"         # the machine's own install step
    unshare -m --propagation private bash -c "mount --bind '$GAME' /game && cd /game/$DIR && PATH='$W/bin':\$PATH bash run-on-update.sh" \
        > "$W/hook.out" 2>&1
    rm -f "$G/run-on-update.sh"                              # codeupdate deletes it
    grep -q "PAD multi-boot" "$GAME/images/launch/.local/rmstart.sh" && [ -f "$GAME/images/launch/.local/rmstart.sh.stock" ] \
        && pass "the hook installed rmstart.sh (the stock one kept)" || fail "rmstart.sh ($(cat "$W/hook.out"))"
    START=$GAME/images/launch/.local/rmstart.sh
else
    mkdir -p /etc/X11/xinit
    unshare -m --propagation private bash -c "mount --bind '$GAME' /game && mount --bind '$W/xinit' /etc/X11/xinit && cd /game/$DIR/uptest && PATH='$W/bin':\$PATH bash ./main.x86_64 ." \
        > "$W/hook.out" 2>&1
    grep -q "padselect.sh" "$W/xinit/xinitrc" && grep -q "reboot" "$W/hook_shell.log" \
        && cmp -s "$G/uptest/main.x86_64" "$SPP_CACHE/$BUILD/uptest/main.x86_64" \
        && pass "the stub put the real player back, installed the launcher's xinitrc and asked for a reboot" \
        || fail "the stub ($(cat "$W/hook.out"))"
    START=""
fi
[ -f "$G/.pad/padselect.sh" ] && [ ! -e "$G/PAD_MULTIBOOT" ] && pass ".pad in place" || fail "no .pad"

# the reader's board: Rick and Morty's own libpinproc over the Big Lebowski rig's fake P3-ROC
gcc -shared -fPIC -O2 -o "$W/aaiwshim.so" "$REPO/tools/dp_emu/aaiw/aaiwshim.c" -ldl -lpthread || exit 1
mkdir -p "$W/lib"
cp "$(ls -d "$SPP_CACHE"/rm_*/payload/libpinproc.so.2.0 | head -1)" "$W/lib/" 2>/dev/null \
    || cp "$G/payload/libpinproc.so.2.0" "$W/lib/" || { echo "machine_sim: no libpinproc (prepare the Rick and Morty .pkg once)" >&2; exit 1; }
FIFO=$W/proc.fifo; rm -f "$FIFO"; mkfifo "$FIFO"; chmod 666 "$FIFO"
chown -R "$SPP_USER": "$W/lib" "$W/aaiwshim.so"
exec 7<>"$FIFO"

L=$G/.pad/padselect.log
power_up() {    # power_up <n> <press: yes|no>
    local n=$1 press=$2 i
    echo "== power-up $n"
    [ -f "$L" ] && mv -f "$L" "$W/padselect$((n - 1)).log"
    SPP_MACHINE_GAME=$GAME SPP_MACHINE_LAUNCH=$G/.pad/padselect.sh SPP_MSIM_FIFO=$FIFO \
        SPP_MSIM_SHIM=$W/aaiwshim.so SPP_MSIM_LIB=$W/lib \
        bash "$T/run_game.sh" "$BUILD" > "$W/run$n.out" 2>&1 &
    local rg=$!
    for i in $(seq 1 600); do grep -qs " menu: " "$L" && break; kill -0 $rg 2>/dev/null || break; sleep 0.2; done
    if grep -qs " menu: " "$L"; then
        pass "$n: the menu is up ($(grep -o 'menu: .*' "$L"))"
        sleep 3
        ffmpeg -loglevel error -y -f x11grab -video_size "$(cat "$SPP_RIG/screen")" \
            -i "$(cat "$SPP_RIG/display")+0,0" -frames:v 1 "$W/menu$n.png" 2>/dev/null \
            || nsenter -t "$(cat "$SPP_RIG/ns.pid")" -n ffmpeg -loglevel error -y -f x11grab \
                -video_size "$(cat "$SPP_RIG/screen")" -i "$(cat "$SPP_RIG/display")+0,0" -frames:v 1 "$W/menu$n.png"
        if [ "$press" = yes ]; then
            echo "pulse $R 300" >&7; sleep 1.0
            echo "pulse $S 300" >&7
        fi
    else
        fail "$n: no menu ($(tail -3 "$L" 2>/dev/null | tr '\n' '|') $(tail -3 "$SPP_RIG/launcher.out" 2>/dev/null | tr '\n' '|'))"
    fi
    wait $rg
    echo "run_game: $(tail -1 "$W/run$n.out")"
}

power_up 1 yes
grep -q "first start\|a new multi-boot" "$L" && grep -q "build b1: made" "$L" && pass "1: a new multi-boot, b1 made" \
    || fail "1: b1 ($(grep -o 'build b1.*' "$L"))"
grep -q "buttons: L=SD14 R=SD$R S=SD15" "$L" && grep -qs "pulse $R 300" "$SPP_RIG/shim.log" \
    && grep -qs "FPGA Chip ID" "$G/.pad/dpprocsw.log" \
    && pass "1: $(grep -o 'buttons: .*' "$L")" || fail "1: buttons"
grep -q "choice '1'" "$L" && grep -q "live = b1" "$L" && pass "1: RIGHT + START picked b1, moved into $DIR" \
    || fail "1: the pick ($(grep -o "choice '.*'" "$L"))"
[ "$(cat "$G/PAD_MULTIBOOT_MARK" 2>/dev/null)" = "PAD-980 marked build" ] && [ "$(cut -d' ' -f1 "$G/PAD_MULTIBOOT_LIVE")" = b1 ] \
    && pass "1: the folder holds b1 (its mark, the marker)" || fail "1: the folder does not hold b1"
[ -d "$G/.pad/b0" ] && [ ! -e "$G/.pad/b0/PAD_MULTIBOOT_MARK" ] && pass "1: b0 kept whole in .pad/b0" || fail "1: .pad/b0"
[ -f "$SPP_RIG/attract" ] && pass "1: $TITLE in attract" || fail "1: no attract ($(tail -2 "$W/run1.out" | tr '\n' '|'))"
ffmpeg -loglevel error -y -f x11grab -video_size "$(cat "$SPP_RIG/screen")" -i "$(cat "$SPP_RIG/display")+0,0" \
    -frames:v 1 "$W/attract1.png" 2>/dev/null || bash "$T/shot.sh" "$W/attract1.png" >/dev/null 2>&1
bash "$T/killgame.sh" >/dev/null 2>&1

power_up 2 no
grep -q "switching" "$L" && fail "2: switched again" || pass "2: no swap - b1 stays in the folder"
grep -q "menu exit 0, choice '1'" "$L" && pass "2: the countdown booted the remembered b1" || fail "2: $(grep -o "choice '.*'" "$L")"
[ -f "$SPP_RIG/attract" ] && pass "2: $TITLE in attract" || fail "2: no attract"
bash "$T/killgame.sh" >/dev/null 2>&1
cp "$L" "$W/padselect2.log" 2>/dev/null

echo "machine_sim: $([ $FAILS = 0 ] && echo PASS || echo "$FAILS FAILED") ($TITLE, shots in $W)"
exit $((FAILS > 0))
