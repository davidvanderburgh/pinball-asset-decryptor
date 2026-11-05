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
#   8  two games (Halloween + Ultraman, PAD-997): each keeps its own files of /game (own=);
#      a game's first start gets its seed= file from its build; a power cut mid-swap is finished
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
    PADSELECT_HOME="$P" PADSELECT_GAME="$T/game" PADSELECT_SW="${RUN_SW:-$T/sw}" PAD_SELECT_FAKEFB="1920x1080x32:$T/fb" \
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
    && [ "$(cat "$T/code/assets/a.png")" = "art of my build" ] && [ ! -L "$T/code/assets" ] \
    && [ ! -e "$P/b1/assets" ] && grep -q "^assets b1$" "$P/roots" && [ -f "$U/.backup_file" ] \
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
    && [ "$(cat "$P/b1/assets/a.png")" = "art of my build" ] && [ ! -e "$P/b0/assets" ] \
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

# 2c a power cut between the rename and its record: b1's assets in place, pad/roots says nobody's
echo "assets -" > "$P/roots"
rm -f "$P/last"
run >/dev/null
if [ "$(readlink "$P/live")" = b1 ] && [ "$(cat "$T/code/assets/a.png")" = "art of my build" ] \
    && [ "$(cat "$P/b0/assets/a.png")" = "art of b0" ] && [ "$(cat "$P/stock_assets/a.png")" = "the machine's own assets" ]; then
    ok "2c an unrecorded rename is put home to the build that lacked it, not taken for the machine's own"
else
    bad "2c recovery (live $(readlink "$P/live"), assets '$(cat "$T/code/assets/a.png")', b0 '$(cat "$P/b0/assets/a.png" 2>&1)')"
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

# 8
setup
G=$T/game
mkdir -p "$G" "$S/b0/config" "$S/d1/config"
echo "um defaults" > "$S/b0/config/default_highscores.config"
echo "h78 defaults" > "$S/d1/config/default_highscores.config"
echo "um scores" > "$G/highscores.config"
echo "um features" > "$G/_game_features.json"
echo "shared" > "$G/notes.txt"
printf 'title=b0 ultraman\ntitle=b1 halloween_78\ntitle=b2 halloween_78\nown=*.config *.json\nseed=highscores.config config/default_highscores.config\n' >> "$S/spk.conf"
# a file named like a glob in the launcher's own folder must not be taken for /game's
touch "$U/x.json"
run >/dev/null
if [ "$(started)" = "$P/b1/uptest/main.x86_64 $U -force-glcore" ] && [ "$(cat "$G/highscores.config")" = "h78 defaults" ] \
    && [ ! -e "$G/_game_features.json" ] && [ "$(cat "$P/home_ultraman/highscores.config")" = "um scores" ] \
    && [ "$(cat "$P/home_ultraman/_game_features.json")" = "um features" ] && [ "$(cat "$P/home_owner")" = halloween_78 ] \
    && [ "$(cat "$G/notes.txt")" = shared ] && [ -e "$U/x.json" ]; then
    ok "8 b1 (Halloween): Ultraman's own files kept in pad/home_ultraman, Halloween's scores seeded from its build"
else
    bad "8 first Halloween start ($(ls "$G" | tr '\n' ' '), owner $(cat "$P/home_owner" 2>&1))"
fi
echo "h78 scores" > "$G/highscores.config"; echo "h78 features" > "$G/_game_features.json"
printf 'sw R 1\nsw R 0\nsw S 1\n' > "$T/presses"
run >/dev/null; rm -f "$T/presses"
if [ "$(started)" = "$P/b0/uptest/main.x86_64 $U -force-glcore" ] && [ "$(cat "$G/highscores.config")" = "um scores" ] \
    && [ "$(cat "$G/_game_features.json")" = "um features" ] && [ ! -e "$P/home_ultraman" ] \
    && [ "$(cat "$P/home_halloween_78/highscores.config")" = "h78 scores" ] && [ "$(cat "$P/home_owner")" = ultraman ]; then
    ok "8b b0 (Ultraman): its own scores and settings back, Halloween's kept"
else
    bad "8b back to Ultraman ($(ls "$G" | tr '\n' ' '), owner $(cat "$P/home_owner" 2>&1))"
fi
# a power cut after pad/home_owner moved on but before every file came back
rm -f "$P/last"; run >/dev/null
mkdir -p "$P/home_halloween_78"; mv "$G/_game_features.json" "$P/home_halloween_78/"
rm -f "$P/last"; run >/dev/null
if [ "$(started)" = "$P/b1/uptest/main.x86_64 $U -force-glcore" ] && [ "$(cat "$G/highscores.config")" = "h78 scores" ] \
    && [ "$(cat "$G/_game_features.json")" = "h78 features" ] && [ ! -e "$P/home_halloween_78" ] \
    && [ "$(cat "$P/home_ultraman/highscores.config")" = "um scores" ]; then
    ok "8c Halloween again: its own files back, a swap cut short is finished"
else
    bad "8c Halloween again ($(ls "$G" | tr '\n' ' '), owner $(cat "$P/home_owner" 2>&1))"
fi

echo "padselect_spk_test: $([ $FAILS = 0 ] && echo OK || echo "$FAILS FAILED")"
exit $((FAILS > 0))
