#!/bin/bash
# padselect_dp_test.sh DPSELECT [FONT] - The Big Lebowski multi-boot launcher (padselect_dp.sh,
# PAD-853) on a fake ~/game: stock 1.10 and 1.13 (each `start` a script that records what
# started it), the multi-boot version 9.0 (`start` = the launcher, the menu on a fake
# framebuffer) and two builds.  The button reader is a stub printing dpprocsw's lines.
#
#   1  first run: build 9.01 is made over its newest base present (1.13) - program and
#      assets hard links, the build's file laid over (the base's untouched), database a
#      real copy; build 9.02 (bases not on the machine) is left out; the menu's default
#      (9.01) starts with the game's arguments; the buttons are the stock machine.yaml's
#   2  RIGHT + START from the reader pick card 2 ("stock" = 1.13); the database of 9.01,
#      the build that ran last, is carried into 1.13; the reader is gone
#   3  a second run boots the remembered pick and does not make the build again
#   4  the card of a build that could not be made -> the stock version
#   5  no menu program -> the stock version
#   6  no conf -> the stock version; a launcher with no stock version at all exits 1
#   7  the first boot carries the database Version Select copied into <V>; later boots the last build's
set -u
BIN=$1; FONT=${2:-}
HERE=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d /tmp/padselect_dp_test.XXXXXX)
trap 'pkill -f "$T/procsw" 2>/dev/null; rm -rf "$T"' EXIT
FAILS=0
ok() { echo "ok $*"; }
bad() { echo "FAIL $*"; FAILS=$((FAILS + 1)); [ -f "$G/9.0/pad/padselect.log" ] && cat "$G/9.0/pad/padselect.log"; }
G=$T/game

stock_version() {   # stock_version <v>
    mkdir -p "$G/$1/config" "$G/$1/database" "$G/$1/assets"
    printf '#!/bin/sh\necho "$(basename "$(pwd)") $*" >> %s/started\n' "$T" > "$G/$1/start"
    chmod +x "$G/$1/start"
    echo "db of $1" > "$G/$1/database/database.db"
    echo "art of $1" > "$G/$1/assets/x.png"
    echo "lib" > "$G/$1/libpinproc.so.2.0"
    cat > "$G/$1/config/machine.yaml" <<'Y'
PRSwitches:
    flipperLwR:
        title: 'Right Flipper'
        number: SD65
    flipperLwL:
        number: SD67
    startButton:
        number: SD68
PRLEDs:
    startButton:
        number: A5-N66
Y
}
setup() {
    rm -rf "$G" "$T/started"
    stock_version 1.10
    stock_version 1.13
    mkdir -p "$G/assets" "$G/9.0/pad/b1/assets" "$G/9.0/pad/b2"
    cp "$HERE/padselect_dp.sh" "$G/9.0/start"
    cp "$BIN" "$G/9.0/pad/dpselect"
    [ -n "$FONT" ] && cp "$FONT" "$G/9.0/pad/font.ttf"
    echo "art of my build" > "$G/9.0/pad/b1/assets/x.png"
    printf '9.01 1.10,1.13 b1\n9.02 1.50 b2\n' > "$G/9.0/pad/builds.txt"
    printf 'image=9.01|THE BIG LEBOWSKI|My build\nimage=stock|THE BIG LEBOWSKI|Stock\nimage=9.02|THE BIG LEBOWSKI|Another\ndefault=0\ntimeout=1\n' \
        > "$G/9.0/pad/images.conf"
    # the reader: its arguments recorded, "ready", then $T/presses' lines, then it waits
    cat > "$T/procsw" <<P
#!/bin/bash
echo "\$*" > $T/procsw.args
echo ready
[ -f $T/presses ] && while read -r l; do sleep 0.3; echo "\$l"; done < $T/presses
exec sleep 600
P
    chmod +x "$T/procsw"
    rm -f "$T/presses"
}
run() {
    rm -f "$T/started"
    PADSELECT_PROCSW="$T/procsw" PAD_SELECT_FAKEFB="1366x768x32:$T/fb" \
        timeout 60 "$G/9.0/start" fullscreen os_version 2021-10-14-21 >/dev/null 2>&1
    echo $?
}
started() { cat "$T/started" 2>/dev/null; }
ino() { stat -c %i "$1"; }

# 1
setup
rc=$(run)
if [ "$rc" = 0 ] && [ "$(started)" = "9.01 fullscreen os_version 2021-10-14-21" ] \
    && [ "$(ino "$G/9.01/start")" = "$(ino "$G/1.13/start")" ] \
    && [ "$(cat "$G/9.01/assets/x.png")" = "art of my build" ] \
    && [ "$(cat "$G/1.13/assets/x.png")" = "art of 1.13" ] \
    && [ "$(ino "$G/9.01/database/database.db")" != "$(ino "$G/1.13/database/database.db")" ] \
    && [ "$(cat "$G/9.01/database/database.db")" = "db of 1.13" ] \
    && [ ! -e "$G/9.02" ] && grep -q "build 9.02: none of its bases (1.50)" "$G/9.0/pad/padselect.log" \
    && [ "$(cat "$T/procsw.args")" = "L=SD67 R=SD65 S=SD68" ]; then
    ok "1 9.01 made over 1.13 (links, its file laid over, the base's untouched, a real database), 9.02 left out, 9.01 started with the game's arguments, buttons from machine.yaml"
else
    bad "1 first run (rc $rc, started '$(started)')"
fi

# 2
echo "db played on 9.01" > "$G/9.01/database/database.db"
printf 'sw R 1\nsw R 0\nsw S 1\n' > "$T/presses"
rc=$(run)
if [ "$rc" = 0 ] && [ "$(started)" = "1.13 fullscreen os_version 2021-10-14-21" ] \
    && [ "$(cat "$G/1.13/database/database.db")" = "db played on 9.01" ] \
    && grep -q "database: carried from 9.01 to 1.13" "$G/9.0/pad/padselect.log" \
    && ! pgrep -f "$T/procsw" >/dev/null; then
    ok "2 RIGHT + START -> stock 1.13, the database carried from 9.01, the reader gone"
else
    bad "2 buttons (rc $rc, started '$(started)')"
fi

# 3
rm -f "$T/presses"
run >/dev/null
if [ "$(started)" = "1.13 fullscreen os_version 2021-10-14-21" ] && ! grep -q "making it" "$G/9.0/pad/padselect.log" \
    && ! grep -q "database: carried" "$G/9.0/pad/padselect.log"; then
    ok "3 a second run: the countdown boots the remembered pick (1.13), 9.01 is not made again, no database carried"
else
    bad "3 second run (started '$(started)')"
fi

# 4
sed -i 's/^default=0/default=2/' "$G/9.0/pad/images.conf"; rm -f "$G/9.0/pad/last"
run >/dev/null
if [ "$(started)" = "1.13 fullscreen os_version 2021-10-14-21" ] && grep -q "image 2 (9.02) is not on this machine" "$G/9.0/pad/padselect.log"; then
    ok "4 the card of a build that could not be made -> stock 1.13"
else
    bad "4 missing build (started '$(started)')"
fi

# 5
setup; rm -f "$G/9.0/pad/dpselect"
run >/dev/null
if [ "$(started)" = "9.01 fullscreen os_version 2021-10-14-21" ] || [ "$(started)" = "1.13 fullscreen os_version 2021-10-14-21" ]; then
    # no menu = the conf's first card stands (choice 0): 9.01 here
    if grep -q "no menu program" "$G/9.0/pad/padselect.log"; then
        ok "5 no menu program -> no menu, the first card ($(started | cut -d' ' -f1)) starts"
    else bad "5 no menu program"; fi
else
    bad "5 no menu program (started '$(started)')"
fi

# 6
setup; rm -f "$G/9.0/pad/images.conf"
run >/dev/null
a=$(started)
rm -rf "$G/1.10" "$G/1.13"
rc=$(run)
if [ "$a" = "1.13 fullscreen os_version 2021-10-14-21" ] && [ "$rc" = 1 ] && [ -z "$(started)" ]; then
    ok "6 no conf -> stock 1.13; nothing to start at all -> exit 1"
else
    bad "6 no conf (started '$a', then rc $rc)"
fi

# 7
setup
mkdir -p "$G/9.0/database"; echo "db the owner was running" > "$G/9.0/database/database.db"
run >/dev/null
first=$(cat "$G/9.01/database/database.db")
echo "db played on 9.01" > "$G/9.01/database/database.db"; touch -d '+5 sec' "$G/9.01/database/database.db"
sed -i 's/^default=0/default=1/' "$G/9.0/pad/images.conf"; rm -f "$G/9.0/pad/last"
run >/dev/null
if [ "$first" = "db the owner was running" ] && grep -q "database: carried from 9.01 to 1.13" "$G/9.0/pad/padselect.log" \
    && [ "$(cat "$G/1.13/database/database.db")" = "db played on 9.01" ]; then
    ok "7 the first boot carries the database Version Select put in 9.0; later ones carry the last build's"
else
    bad "7 first carry ('$first', 1.13 has '$(cat "$G/1.13/database/database.db")')"
fi

echo "padselect_dp_test: $([ $FAILS = 0 ] && echo OK || echo "$FAILS FAILED")"
exit $((FAILS > 0))
