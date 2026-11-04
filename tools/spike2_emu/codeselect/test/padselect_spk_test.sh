#!/bin/bash
# padselect_spk_test.sh SPKSELECT [SPKSW] [FONT] - the Spooky Pinball multi-boot launcher
# (padselect_spk.sh, PAD-980) on a fake /game/code: uptest/ as the machine's update install
# leaves it (main.x86_64 = the launcher, pad/b0 the stock build whole, pad/d1 and pad/d2 the
# files of two more builds), a stock /game/code/assets the install did not touch, and each
# build's program a script that records where it ran from.  The menu draws on a fake
# framebuffer; the button reader is a stub printing spksw's lines.
#
#   1  first run: b1 made from b0 (hard links, its file laid over, b0's untouched, the file
#      it deletes gone), b2 (no files folder) left out; uptest's entries and
#      /game/code/assets are links through pad/live; the menu's default (b1) starts from its
#      own folder, in uptest, with the game's arguments; the stock assets kept aside;
#      the reader got the conf's board and switches
#   2  RIGHT + START from the reader pick card 2 (b0): pad/live -> b0, the paths follow
#      (an entry only b1 has is gone), the reader is gone
#   3  a second run boots the remembered pick and does not make b1 again
#   4  the card of a build that could not be made -> b0
#   5  no menu program -> no menu, the first card starts
#   6  no conf -> b0; no build 0 at all -> whatever pad/live points at
#   7  the real spksw (when given) on a dead port says "wait", and the countdown still boots
set -u
BIN=$1; SW=${2:-}; FONT=${3:-}
HERE=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d /tmp/padselect_spk_test.XXXXXX)
trap 'pkill -f "$T/sw" 2>/dev/null; rm -rf "$T"' EXIT
FAILS=0
U=$T/code/uptest
S=$U/pad                 # the update's pad/ as the install leaves it
P=$T/game/pad            # where the launcher keeps it (PADSELECT_HOME)
ok() { echo "ok $*"; }
bad() { echo "FAIL $*"; FAILS=$((FAILS + 1)); [ -f "$P/padselect.log" ] && cat "$P/padselect.log"; }

prog() {   # prog <file>: a "game" that records its own path, its cwd and arguments
    mkdir -p "$(dirname "$1")"
    printf '#!/bin/sh\necho "$0 $(pwd) $*" >> %s/started\n' "$T" > "$1"
    chmod +x "$1"
}
setup() {
    rm -rf "$T/code" "$T/game" "$T/started"
    mkdir -p "$S/b0/uptest/main_Data" "$S/b0/assets" "$S/d1/uptest/main_Data" "$S/d1/assets" "$T/code/assets"
    cp "$HERE/padselect_spk.sh" "$U/main.x86_64"
    chmod +x "$U/main.x86_64"
    prog "$S/b0/uptest/main.x86_64"
    echo "data of b0" > "$S/b0/uptest/main_Data/x"
    echo "v1" > "$S/b0/uptest/version.txt"
    echo "only in b0" > "$S/b0/uptest/gone.txt"
    echo "art of b0" > "$S/b0/assets/a.png"
    echo "data of my build" > "$S/d1/uptest/main_Data/x"
    echo "art of my build" > "$S/d1/assets/a.png"
    echo "uptest/gone.txt" > "$S/d1.removed"
    echo "the machine's own assets" > "$T/code/assets/a.png"
    touch "$U/.update_file"
    cp "$BIN" "$S/spkselect"
    [ -n "$FONT" ] && cp "$FONT" "$S/font.ttf"
    printf 'b1 d1\nb2 d2\n' > "$S/builds.txt"
    printf 'board=pinotaur\nL=81\nR=80\nS=87\nroot=assets %s/code/assets\n' "$T" > "$S/spk.conf"
    printf 'image=b1|SCOOBY-DOO|My build\nimage=b0|SCOOBY-DOO|Stock\nimage=b2|SCOOBY-DOO|Another\ndefault=0\ntimeout=1\n' \
        > "$S/images.conf"
    cat > "$T/sw" <<S
#!/bin/bash
echo "\$*" > $T/sw.args
echo ready
[ -f $T/presses ] && while read -r l; do sleep 0.3; echo "\$l"; done < $T/presses
exec sleep 600
S
    chmod +x "$T/sw"
    rm -f "$T/presses"
}
run() {
    rm -f "$T/started"
    PADSELECT_HOME="$P" PADSELECT_SW="${RUN_SW:-$T/sw}" PAD_SELECT_FAKEFB="1920x1080x32:$T/fb" \
        timeout 60 "$U/main.x86_64" -force-glcore >/dev/null 2>&1
    echo $?
}
started() { cat "$T/started" 2>/dev/null; }
ino() { stat -c %i "$1"; }

# 1
setup
rc=$(run)
if [ "$rc" = 0 ] && [ "$(started)" = "$P/b1/uptest/main.x86_64 $U -force-glcore" ] \
    && [ "$(ino "$P/b1/uptest/version.txt")" = "$(ino "$P/b0/uptest/version.txt")" ] \
    && [ "$(cat "$P/b1/uptest/main_Data/x")" = "data of my build" ] \
    && [ "$(cat "$P/b0/uptest/main_Data/x")" = "data of b0" ] \
    && [ ! -e "$P/b1/uptest/gone.txt" ] && [ -e "$P/b0/uptest/gone.txt" ] \
    && [ ! -e "$P/b2" ] && grep -q "build b2: no $P/d2" "$P/padselect.log" \
    && [ "$(readlink "$P/live")" = b1 ] && [ "$(readlink "$U/version.txt")" = "$P/live/uptest/version.txt" ] \
    && [ ! -e "$S" ] && grep -q "moved there from the update" "$P/padselect.log" \
    && [ "$(cat "$U/main_Data/x")" = "data of my build" ] && [ -f "$U/.update_file" ] && [ ! -L "$U/.update_file" ] \
    && [ "$(cat "$T/code/assets/a.png")" = "art of my build" ] \
    && [ "$(cat "$P/stock_assets/a.png")" = "the machine's own assets" ] \
    && [ "$(cat "$T/sw.args")" = "L=81 R=80 S=87" ]; then
    ok "1 b1 made from b0 (links, its file over, b0 untouched, its deletion), b2 left out, paths through pad/live, b1 started from its folder in uptest, stock assets kept aside"
else
    bad "1 first run (rc $rc, started '$(started)')"
fi

# 2
printf 'sw R 1\nsw R 0\nsw S 1\n' > "$T/presses"
rc=$(run)
if [ "$rc" = 0 ] && [ "$(started)" = "$P/b0/uptest/main.x86_64 $U -force-glcore" ] \
    && [ "$(readlink "$P/live")" = b0 ] && [ "$(cat "$U/main_Data/x")" = "data of b0" ] \
    && [ "$(cat "$U/gone.txt")" = "only in b0" ] && [ "$(cat "$T/code/assets/a.png")" = "art of b0" ] \
    && ! pgrep -f "$T/sw" >/dev/null; then
    ok "2 RIGHT + START -> b0, pad/live and every path follow, the reader gone"
else
    bad "2 buttons (rc $rc, started '$(started)')"
fi
# and back to b1: the entry b1 lacks is gone from uptest again
rm -f "$T/presses" "$P/last"
run >/dev/null
if [ "$(readlink "$P/live")" = b1 ] && [ ! -e "$U/gone.txt" ] && [ ! -L "$U/gone.txt" ]; then
    ok "2b back on b1: b0's own entry is gone from uptest"
else
    bad "2b back on b1 (live $(readlink "$P/live"), gone.txt $(ls -l "$U/gone.txt" 2>&1))"
fi

# 3
printf 'sw R 1\nsw R 0\nsw S 1\n' > "$T/presses"; run >/dev/null; rm -f "$T/presses"
run >/dev/null
if [ "$(started)" = "$P/b0/uptest/main.x86_64 $U -force-glcore" ] && ! grep -q "making it" "$P/padselect.log"; then
    ok "3 a second run: the countdown boots the remembered pick (b0), b1 is not made again"
else
    bad "3 second run (started '$(started)')"
fi

# 4
sed -i 's/^default=0/default=2/' "$P/images.conf"; rm -f "$P/last"
run >/dev/null
if [ "$(started)" = "$P/b0/uptest/main.x86_64 $U -force-glcore" ] && grep -q "image 2 (b2) is not made" "$P/padselect.log"; then
    ok "4 the card of a build that could not be made -> b0"
else
    bad "4 missing build (started '$(started)')"
fi

# 5
setup; rm -f "$S/spkselect"
run >/dev/null
if [ "$(started)" = "$P/b1/uptest/main.x86_64 $U -force-glcore" ] && grep -q "no menu program" "$P/padselect.log"; then
    ok "5 no menu program -> no menu, the first card (b1) starts"
else
    bad "5 no menu program (started '$(started)')"
fi

# 6
setup; run >/dev/null; rm -f "$P/images.conf"
run >/dev/null
a=$(started)
mv "$P/b0" "$P/b0.gone"
run >/dev/null
b=$(started)
if [ "$a" = "$P/b0/uptest/main.x86_64 $U -force-glcore" ] && [ "$b" = "$P/b0/uptest/main.x86_64 $U -force-glcore" -o -z "$b" ] \
    && grep -q "no build 0" "$P/padselect.log"; then
    ok "6 no conf -> b0; no build 0 -> pad/live's build (or nothing), never a hang"
else
    bad "6 no conf ('$a', then '$b')"
fi

# 7
if [ -n "$SW" ]; then
    setup
    cp "$SW" "$S/spksw"
    printf 'dev=%s/no-board\n' "$T" >> "$S/spk.conf"
    RUN_SW="" ; unset RUN_SW
    rm -f "$T/started"
    PADSELECT_HOME="$P" PAD_SELECT_FAKEFB="1920x1080x32:$T/fb" timeout 60 "$U/main.x86_64" -force-glcore >/dev/null 2>&1
    if [ "$(started)" = "$P/b1/uptest/main.x86_64 $U -force-glcore" ] && grep -q "pid" "$P/padselect.log" \
        && ! pgrep -f "$P/spksw" >/dev/null; then
        ok "7 the real spksw on a missing board: the countdown boots b1, the reader is gone"
    else
        bad "7 real spksw (started '$(started)')"
    fi
fi

echo "padselect_spk_test: $([ $FAILS = 0 ] && echo OK || echo "$FAILS FAILED")"
exit $((FAILS > 0))
