#!/bin/bash
# fb_bof_test.sh BOFSELECT [FONT] - where the Barrels of Fun menu lands on the glass (fb_linux.c,
# PAD-342), on a fake framebuffer with no board (--input none: each run counts down and exits).
#
#   1. one 1366x768 screen: the 1360x768 canvas 1:1 at 3,0, black 3-pixel borders
#   2. a Labyrinth's console - 1280x390 visible of a 1366x768 buffer (the backbox and the
#      playfield strip): the menu takes the whole buffer, 1:1 at 3,0, so the backbox is full
#      screen; card rows below the strip's 390 are drawn (before: the menu shrank into
#      1280x390 and the backbox showed it at half size, top left)
#   3. a buffer that is only TALLER (1366x768 of 1366x1536, panning room): the visible area
#      stays the glass, nothing is drawn below row 768
#   4. the driver is told after every frame (a write of the first pixel through the device),
#      so Intel's compressed scan-out on the backbox shows each one
set -u
BIN=$1; FONT=${2:-}
T=$(mktemp -d /tmp/fb_bof_test.XXXXXX)
trap 'rm -rf "$T"' EXIT
FAILS=0
ok() { echo "ok $*"; }
bad() { echo "FAIL $*"; FAILS=$((FAILS + 1)); }

printf 'image=GDCraze.x86_64|LABYRINTH|Stock code\nimage=pad_image1.bin|SARAH CODE|A mod\ndefault=0\ntimeout=1\n' > "$T/images.conf"

run() {     # run <name> <fake spec without the file>
    rm -f "$T/$1.fb" "$T/$1.log"
    PAD_SELECT_FAKEFB="$2:$T/$1.fb" "$BIN" --input none --conf "$T/images.conf" --out "$T/$1.choice" \
        --last "$T/$1.last" --log "$T/$1.log" --audio none --no-invert ${FONT:+--font "$FONT"} \
        >/dev/null 2>&1
}

# drawn W ROW X0 X1 FILE: 0 when some pixel of ROW between X0 and X1 is not black
drawn() {
    python3 - "$@" <<'PY'
import sys
w, row, x0, x1, path = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
with open(path, "rb") as f:
    f.seek((row * w + x0) * 4)
    px = f.read((x1 - x0) * 4)
sys.exit(0 if any(b for i, b in enumerate(px) if i % 4 != 3) else 1)
PY
}

# 1
run one "1366x768x32"
if grep -q "1:1 at 3,0 on the 1366x768 screen" "$T/one.log" && ! grep -q "whole buffer" "$T/one.log" \
    && drawn 1366 400 3 1363 "$T/one.fb" && ! drawn 1366 400 0 3 "$T/one.fb"; then
    ok "1 one 1366x768 screen: the canvas 1:1 at 3,0, black borders"
else
    bad "1 one screen"; cat "$T/one.log"
fi

# 2
run two "1280x390x32,1366x768"
if grep -q "shows 1280x390 of a 1366x768 buffer" "$T/two.log" \
    && grep -q "1:1 at 3,0 on the 1366x768 screen" "$T/two.log" \
    && drawn 1366 500 3 1363 "$T/two.fb" && drawn 1366 300 1280 1363 "$T/two.fb" \
    && ! drawn 1366 500 0 3 "$T/two.fb"; then
    ok "2 a Labyrinth's two screens (1280x390 of 1366x768): the whole buffer, 1:1 - the backbox is full screen"
else
    bad "2 two screens"; cat "$T/two.log"
fi

# 3
run tall "1366x768x32,1366x1536"
if [ "$(stat -c %s "$T/tall.fb")" = $((1366 * 1536 * 4)) ] && ! grep -q "whole buffer" "$T/tall.log" \
    && grep -q "1:1 at 3,0 on the 1366x768 screen" "$T/tall.log" \
    && drawn 1366 400 3 1363 "$T/tall.fb" && ! drawn 1366 1000 0 1366 "$T/tall.fb"; then
    ok "3 a taller buffer (panning room): the visible area stays the glass"
else
    bad "3 taller buffer"; cat "$T/tall.log"
fi

# 4: the driver hears of every frame (David's video: the backbox, on Intel's compressed
#    scan-out, showed the clips 5 times a second) - a write through the device for the
#    cleared glass, the menu and each countdown step (this conf animates nothing, so a frame
#    is drawn only when something changes), and the pixel written back is the one drawn
told=$(sed -n 's/.*the driver told \([0-9]*\) times by a write.*/\1/p' "$T/two.log")
if grep -q "after every frame the driver is told" "$T/two.log" && [ -n "$told" ] && [ "$told" -ge 3 ] \
    && ! drawn 1366 0 0 3 "$T/two.fb" && ! grep -q "refused" "$T/two.log"; then
    ok "4 the driver is told after every frame: $told writes, the first pixel unchanged"
else
    bad "4 the driver is told (told='$told')"; cat "$T/two.log"
fi

if [ "$FAILS" = 0 ]; then echo "fb_bof_test: OK"; else echo "fb_bof_test: $FAILS FAILED"; exit 1; fi
