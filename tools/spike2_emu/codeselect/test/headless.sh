#!/bin/bash
# QEMU=qemu-arm-static headless.sh ROOT BIN T DEJAVU - render the menu without
# EGL under qemu-arm-static against the card rootfs libs, check the choice/last
# files, the PPM shape, the default/last-choice precedence and the -invert
# rotation, and convert every frame to PNG in $T for eyes.
# The emulator comes from the ENVIRONMENT, not argv: the rig's teardown does
# pkill -f 'arm-binfmt|qemu-arm', and this script's own command line must
# not match it (see the Makefile).
set -e
QEMU=${QEMU:-qemu-arm-static}
ROOT=$1; BIN=$2; T=$3; DEJAVU=$4
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$T"
if [ -f "$DEJAVU" ]; then FONT=$DEJAVU; else FONT=$ROOT/usr/local/spike/VeraMono.ttf; fi

cat > "$T/two.conf" <<'EOF'
# two images, the TMNT pair
image=p3|STERN STOCK|TMNT Pro 1.59.0 - original Stern code
image=p7|TMNT 1987|1.59.0 - upscaled cartoon retheme
default=0
timeout=10
EOF
cat > "$T/three.conf" <<'EOF'
image=/dev/mmcblk0p3|STERN STOCK|Godzilla Premium 1.15.0 - original Stern code
image=/dev/mmcblk0p7|GODZILLA HEISEI|1.15.0 - the doomwalrus666 retheme, 488 videos, battle callouts
image=/dev/mmcblk0p8|HEISEI ORCHESTRA|1.15.0 - Heisei retheme with the orchestral score
default=1
timeout=0
EOF
cat > "$T/four.conf" <<'EOF'
image=/dev/mmcblk0p3|STERN STOCK|original code
image=/dev/mmcblk0p7|BUILD ONE|first custom build with a rather long subtitle that has to wrap onto several lines
image=/dev/mmcblk0p8|BUILD TWO|second custom build
image=/dev/mmcblk0p9|A VERY LONG TITLE INDEED|fourth
default=3
timeout=30
EOF

run() {   # run PPM CONF [extra args...]
    local ppm=$1 conf=$2; shift 2
    "$QEMU" -L "$ROOT" "$BIN" --headless "$ppm" --conf "$conf" --input none --timeout 1 \
        --out "$T/choice" --last "$T/last" --log "$T/headless.log" --font "$FONT" "$@"
}
expect() {   # expect FILE VALUE
    local got; got=$(cat "$1")
    [ "$got" = "$2" ] || { echo "headless: FAIL $1 holds '$got', expected '$2'"; exit 1; }
}

# 1. plain: default 0, no last file -> choice 0, last 0
rm -f "$T/choice" "$T/last"
run "$T/menu.ppm" "$T/two.conf" --no-invert
expect "$T/choice" 0
expect "$T/last" 0
# header "P6\n1360 768\n255\n" = 16 bytes, then 1360*768*3 bytes of RGB
[ "$(head -c 16 "$T/menu.ppm" | tr '\n' ' ')" = "P6 1360 768 255 " ] || { echo "headless: FAIL PPM header"; exit 1; }
size=$(stat -c %s "$T/menu.ppm")
[ "$size" -eq $((16 + 1360 * 768 * 3)) ] || { echo "headless: FAIL PPM size $size"; exit 1; }
[ -f "$T/menu.ppm.loading.ppm" ] || { echo "headless: FAIL no loading frame"; exit 1; }

# 2. --default 1 with no last file -> choice 1
rm -f "$T/choice" "$T/last"
run "$T/menu_default1.ppm" "$T/two.conf" --default 1 --no-invert
expect "$T/choice" 1
expect "$T/last" 1

# 3. the last-choice file (now 1) beats --default 0
rm -f "$T/choice"
run "$T/menu_last.ppm" "$T/two.conf" --default 0 --no-invert
expect "$T/choice" 1

# 4. --invert: the same frame as (1) rotated 180 degrees
rm -f "$T/choice" "$T/last"
run "$T/menu_invert.ppm" "$T/two.conf" --invert
expect "$T/choice" 0

# 5. three and four images (layout only)
rm -f "$T/choice" "$T/last"
run "$T/menu_three.ppm" "$T/three.conf" --no-invert
expect "$T/choice" 1
rm -f "$T/choice" "$T/last"
run "$T/menu_four.ppm" "$T/four.conf" --no-invert
expect "$T/choice" 3

# 6. a bad conf -> exit 2, no choice
rm -f "$T/choice"
echo "# nothing" > "$T/empty.conf"
if run "$T/x.ppm" "$T/empty.conf"; then echo "headless: FAIL empty conf accepted"; exit 1; fi
[ ! -f "$T/choice" ] || { echo "headless: FAIL choice written for an empty conf"; exit 1; }

python3 "$HERE/ppm2png.py" "$T/menu.ppm" "$T/codeselect_menu.png"
python3 "$HERE/ppm2png.py" "$T/menu.ppm.loading.ppm" "$T/codeselect_loading.png"
python3 "$HERE/ppm2png.py" "$T/menu_default1.ppm" "$T/codeselect_menu_default1.png"
python3 "$HERE/ppm2png.py" "$T/menu_invert.ppm" "$T/codeselect_menu_invert.png" --rot180-of "$T/menu.ppm"
python3 "$HERE/ppm2png.py" "$T/menu_three.ppm" "$T/codeselect_menu_three.png"
python3 "$HERE/ppm2png.py" "$T/menu_four.ppm" "$T/codeselect_menu_four.png"
echo "headless: OK (frames in $T/*.png, font $FONT)"
