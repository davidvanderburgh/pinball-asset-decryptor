#!/bin/bash
# padselect_proc_test.sh SPKSELECT [FONT] - the Spooky P-ROC multi-boot launcher
# (padselect_proc.sh, PAD-980) on a fake game folder, as the machine's update leaves it: the
# stock build in the folder (b0), .pad/ beside it with the menu, the launcher, d1 (a build's
# own files) and PAD_MULTIBOOT_LIVE saying "b0 <stamp>".  Each build's start.sh records which
# build ran and where.  The menu draws on a fake framebuffer; the button reader is a stub
# printing dpprocsw's lines.
#
#   1  first start: a new multi-boot - b1 made from the folder (hard links, its file over,
#      its deletion, its settings file a real copy); the countdown starts b0 in the folder;
#      the reader got the conf's switches and the lib folder
#   2  RIGHT + START: b1 moved into the folder, b0 into .pad/b0, b0's settings carried to b1,
#      the marker says b1, the reader is gone
#   3  LEFT + START back to b0: what was played on b1 is carried to b0
#   4  a normal update installed (the folder emptied, the marker gone, .pad left): no menu,
#      the folder's own game starts
#   5  a power cut while b0 was moving out: put back, b0 starts
#   6  a power cut while b1 was moving in: finished, b1 starts
#   7  no menu program -> the folder's build starts
set -u
BIN=$1; FONT=${2:-}
HERE=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d /tmp/padselect_proc_test.XXXXXX)
trap 'pkill -f "$T/procsw" 2>/dev/null; rm -rf "$T"' EXIT
FAILS=0
G=$T/game/RickAndMorty
P=$G/.pad
ok() { echo "ok $*"; }
bad() { echo "FAIL $*"; FAILS=$((FAILS + 1)); [ -f "$P/padselect.log" ] && cat "$P/padselect.log"; }

setup() {
    rm -rf "$T/game" "$T/started"
    mkdir -p "$G/config" "$G/assets" "$P/d1/assets"
    printf '#!/bin/sh\necho "$(cat which.txt) $(pwd) $(cat config/game_user_data.yaml)" >> %s/started\n' "$T" > "$G/start.sh"
    echo "stock" > "$G/which.txt"
    echo "art of stock" > "$G/assets/a.png"
    echo "only stock" > "$G/gone.txt"
    echo "scores of stock" > "$G/config/game_user_data.yaml"
    echo "mine" > "$P/d1/which.txt"
    echo "art of mine" > "$P/d1/assets/a.png"
    echo "gone.txt" > "$P/d1.removed"
    echo "b0 20261104" > "$G/PAD_MULTIBOOT_LIVE"
    cp "$HERE/padselect_proc.sh" "$P/padselect.sh"
    cp "$BIN" "$P/spkselect"
    [ -n "$FONT" ] && cp "$FONT" "$P/font.ttf"
    printf 'b1 d1\n' > "$P/builds.txt"
    printf 'start=sh start.sh\nlib=/usr/local/lib\nL=SD14\nR=SD8\nS=SD15\nkeep=config/game_user_data.yaml\n' > "$P/proc.conf"
    printf 'image=b0|RICK AND MORTY|Stock\nimage=b1|RICK AND MORTY|Mine\ndefault=0\ntimeout=1\n' > "$P/images.conf"
    cat > "$T/procsw" <<S
#!/bin/bash
echo "\$*" > $T/procsw.args
echo ready
[ -f $T/presses ] && while read -r l; do sleep 0.3; echo "\$l"; done < $T/presses
exec sleep 600
S
    chmod +x "$T/procsw"
    rm -f "$T/presses"
}
run() {
    rm -f "$T/started"
    PADSELECT_PROCSW="$T/procsw" PAD_SELECT_FAKEFB="1366x768x32:$T/fb" \
        timeout 60 bash "$P/padselect.sh" >/dev/null 2>&1
    echo $?
}
started() { cat "$T/started" 2>/dev/null; }
ino() { stat -c %i "$1"; }

# 1
setup
rc=$(run)
if [ "$rc" = 0 ] && [ "$(started)" = "stock $G scores of stock" ] \
    && [ "$(cat "$P/b1/which.txt")" = mine ] && [ "$(cat "$P/b1/assets/a.png")" = "art of mine" ] \
    && [ "$(cat "$G/assets/a.png")" = "art of stock" ] && [ ! -e "$P/b1/gone.txt" ] \
    && [ "$(ino "$P/b1/start.sh")" = "$(ino "$G/start.sh")" ] \
    && [ "$(ino "$P/b1/config/game_user_data.yaml")" != "$(ino "$G/config/game_user_data.yaml")" ] \
    && [ ! -e "$P/b1/.pad" ] && [ ! -e "$P/b1/PAD_MULTIBOOT_LIVE" ] \
    && [ "$(cat "$T/procsw.args")" = "L=SD14 R=SD8 S=SD15" ] && grep -q "through /usr/local/lib" "$P/padselect.log"; then
    ok "1 a new multi-boot: b1 made (links, its files, its deletion, a real settings copy), the countdown starts b0 in the folder"
else
    bad "1 first start (rc $rc, started '$(started)')"
fi

# 2
echo "scores played on stock" > "$G/config/game_user_data.yaml"
printf 'sw R 1\nsw R 0\nsw S 1\n' > "$T/presses"
rc=$(run)
if [ "$rc" = 0 ] && [ "$(started)" = "mine $G scores played on stock" ] \
    && [ "$(cat "$G/assets/a.png")" = "art of mine" ] && [ ! -e "$G/gone.txt" ] \
    && [ "$(cat "$P/b0/which.txt")" = stock ] && [ -e "$P/b0/gone.txt" ] && [ ! -e "$P/b1" ] \
    && [ "$(cat "$G/PAD_MULTIBOOT_LIVE")" = "b1 20261104" ] && [ ! -e "$P/swap" ] \
    && ! pgrep -f "$T/procsw" >/dev/null; then
    ok "2 RIGHT + START: b1 in the folder, b0 in .pad/b0, the settings carried, the reader gone"
else
    bad "2 swap to b1 (rc $rc, started '$(started)')"
fi

# 3
echo "scores played on mine" > "$G/config/game_user_data.yaml"
printf 'sw L 1\nsw L 0\nsw S 1\n' > "$T/presses"
rc=$(run)
if [ "$(started)" = "stock $G scores played on mine" ] && [ "$(cat "$P/b1/which.txt")" = mine ] \
    && [ "$(cat "$G/PAD_MULTIBOOT_LIVE")" = "b0 20261104" ] && [ -e "$G/gone.txt" ]; then
    ok "3 LEFT + START back to b0: what was played on b1 came along"
else
    bad "3 back to b0 (started '$(started)')"
fi

# 4
for e in "$G"/*; do rm -rf "$e"; done
mkdir -p "$G/config"
printf '#!/bin/sh\necho "new stock $(pwd)" >> %s/started\n' "$T" > "$G/start.sh"
rc=$(run)
if [ "$(started)" = "new stock $G" ] && grep -q "a normal update is installed" "$P/padselect.log" \
    && ! grep -q "menu:" "$P/padselect.log"; then
    ok "4 a normal update over it: no menu, the folder's own game starts"
else
    bad "4 normal update (started '$(started)')"
fi

# 5
setup; rm -f "$T/presses"; run >/dev/null
mkdir -p "$P/b0.out"; mv "$G/assets" "$G/which.txt" "$P/b0.out/"; echo "out b0 b1" > "$P/swap"
rc=$(run)
if [ "$(started)" = "stock $G scores of stock" ] && [ "$(cat "$G/assets/a.png")" = "art of stock" ] \
    && [ ! -e "$P/b0.out" ] && [ ! -e "$P/swap" ] && grep -q "interrupted (out" "$P/padselect.log"; then
    ok "5 cut while b0 moved out: put back, b0 starts"
else
    bad "5 out recovery (started '$(started)')"
fi

# 6
setup; printf 'sw R 1\nsw R 0\nsw S 1\n' > "$T/presses"; run >/dev/null
printf 'sw L 1\nsw L 0\nsw S 1\n' > "$T/presses"; run >/dev/null      # b0 live, b1 in .pad
# as if cut half way through bringing b1 in: b0 already out, some of b1 in the folder
mkdir -p "$P/b0"
for e in "$G"/*; do mv "$e" "$P/b0/"; done
mv "$P/b1/which.txt" "$G/"; echo "in b0 b1" > "$P/swap"; echo "b0 20261104" > "$G/PAD_MULTIBOOT_LIVE"
rm -f "$P/last" "$T/presses"
sed -i 's/^default=0/default=1/' "$P/images.conf"
rc=$(run)
if [ "$(started)" = "mine $G scores of stock" ] && [ "$(cat "$G/assets/a.png")" = "art of mine" ] \
    && [ "$(cat "$G/PAD_MULTIBOOT_LIVE")" = "b1 20261104" ] && [ ! -e "$P/swap" ]; then
    ok "6 cut while b1 moved in: finished, b1 starts"
else
    bad "6 in recovery (started '$(started)')"
fi

# 7
setup; rm -f "$P/spkselect"
run >/dev/null
if [ "$(started)" = "stock $G scores of stock" ] && grep -q "no menu program" "$P/padselect.log"; then
    ok "7 no menu program: the folder's build starts"
else
    bad "7 no menu (started '$(started)')"
fi

echo "padselect_proc_test: $([ $FAILS = 0 ] && echo OK || echo "$FAILS FAILED")"
exit $((FAILS > 0))
