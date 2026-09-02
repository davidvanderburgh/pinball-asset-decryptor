#!/bin/bash
# QEMU=qemu-arm-static headless.sh ROOT BIN T DEJAVU - render the menu without
# EGL under qemu-arm-static against the card rootfs libs, check the choice/last
# files, the PPM shape, the default/last-choice precedence, the -invert
# rotation, the art panels (stills, a pinned GIF frame, a missing picture),
# the 5- and 9-image carousels, and convert every frame to PNG in $T for eyes.
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
        --out "$T/choice" --last "$T/last" --log "$T/headless.log" --font "$FONT" --audio none "$@"
}
expect() {   # expect FILE VALUE
    local got; got=$(cat "$1")
    [ "$got" = "$2" ] || { echo "headless: FAIL $1 holds '$got', expected '$2'"; exit 1; }
}
pix() {   # pix PPM X Y RRGGBB
    python3 "$HERE/mkmedia.py" pix "$1" "$2" "$3" "$4"
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

# 7. media: two stills and a 4-frame GIF pinned to frame 2, sounds mixed into
#    a dump (no sink). Two cards: x = 60 / 698, pad 28 -> panels at (88,178)
#    and (726,178), 546x168 -> centres (361,262) and (999,262).
python3 "$HERE/mkmedia.py" make "$T/media"
cat > "$T/media.conf" <<'EOF'
image=p3|STERN STOCK|TMNT Pro 1.59.0 - original Stern code|art0.png||music0.wav
image=p7|TMNT 1987|1.59.0 - upscaled cartoon retheme|art1.png|anim1.gif|
sound_move=move.wav
sound_confirm=confirm.wav
volume=40
default=1
timeout=1
EOF
rm -f "$T/choice" "$T/last" "$T/media.log"
run "$T/menu_media.ppm" "$T/media.conf" --no-invert --media "$T/media" --anim-frame 2 \
    --audio-dump "$T/media_mix.raw" --log "$T/media.log"
expect "$T/choice" 1
pix "$T/menu_media.ppm" 361 262 C03040
pix "$T/menu_media.ppm" 999 262 0000FF
grep -q "media: 2 art, 1 anim (4 frames), 1 music, move=y confirm=y" "$T/media.log" || {
    echo "headless: FAIL media log line"; grep media "$T/media.log"; exit 1; }
grep -q "confirm: " "$T/media.log" || { echo "headless: FAIL no confirm wait logged"; exit 1; }
[ "$(stat -c %s "$T/media_mix.raw")" -gt $((44100 * 4)) ] || { echo "headless: FAIL the mix dump is too short"; exit 1; }
python3 - "$T/media_mix.raw" <<'EOF' || exit 1
import sys
d = open(sys.argv[1], "rb").read()
if not any(d):
    raise SystemExit("headless: FAIL the mix dump is all zeros (no music/confirm mixed)")
EOF

# 8. --invert with media: the panel centres land at the mirrored coordinates
rm -f "$T/choice" "$T/last"
run "$T/menu_media_invert.ppm" "$T/media.conf" --invert --media "$T/media" --anim-frame 2
pix "$T/menu_media_invert.ppm" $((1359 - 361)) $((767 - 262)) C03040
pix "$T/menu_media_invert.ppm" $((1359 - 999)) $((767 - 262)) 0000FF

# 9. a missing picture and a bad WAV are non-fatal: the menu still renders
#    and the choice is still written
cat > "$T/missing.conf" <<'EOF'
image=p3|STERN STOCK|TMNT Pro 1.59.0 - original Stern code|art0.png||
image=p7|TMNT 1987|1.59.0 - upscaled cartoon retheme|nope.png|anim1.gif|
image=p7:img2|A VERY LONG TITLE THAT WRAPS|a long subtitle that has to wrap onto several lines to be readable at all|art1.png||
sound_move=bad.wav
timeout=1
EOF
rm -f "$T/choice" "$T/last" "$T/missing.log"
run "$T/menu_missing.ppm" "$T/missing.conf" --no-invert --media "$T/media" --anim-frame 1 \
    --audio-dump "$T/missing_mix.raw" --log "$T/missing.log"
expect "$T/choice" 0
grep -q "art: cannot load nope.png" "$T/missing.log" || { echo "headless: FAIL missing PNG not logged"; exit 1; }
grep -q "bad.wav: unsupported" "$T/missing.log" || { echo "headless: FAIL bad WAV not refused"; exit 1; }
grep -q "media: 2 art, 1 anim (4 frames), 0 music, move=n confirm=n" "$T/missing.log" || {
    echo "headless: FAIL media line with a missing picture"; grep media "$T/missing.log"; exit 1; }
# three cards: x = 60 / 449 / 838, cw 389, pad 28 -> panel centres at x+28+333/2
pix "$T/menu_missing.ppm" $((449 + 28 + 166)) 262 00C000     # frame 1 of the GIF (no still to show)

# 10. carousels: 5 and 9 images, the highlight centred, wrap-around neighbours
{ for i in 1 2 3 4 5; do echo "image=/dev/mmcblk0p7:img$i|BUILD $i|custom build number $i with a subtitle"; done
  echo default=2; echo timeout=0; } > "$T/five.conf"
{ echo "image=/dev/mmcblk0p3|STERN STOCK|Godzilla Premium 1.15.0 - original Stern code|art0.png||"
  for i in 1 2 3 4 5 6 7 8; do
      if [ $((i % 2)) = 0 ]; then a=art1.png; else a="art0.png|anim1.gif"; fi
      echo "image=/dev/mmcblk0p7:img$i|HEISEI BUILD $i|1.15.0 - the doomwalrus666 retheme, variant $i|$a"
  done
  echo default=4; echo timeout=30; } > "$T/nine.conf"
rm -f "$T/choice" "$T/last"
run "$T/menu_five.ppm" "$T/five.conf" --no-invert
expect "$T/choice" 2
rm -f "$T/choice" "$T/last"
run "$T/menu_nine.ppm" "$T/nine.conf" --no-invert --media "$T/media" --anim-frame 1
expect "$T/choice" 4
# the highlighted card is the middle one of three (x = 449): its still is art1
pix "$T/menu_nine.ppm" $((449 + 28 + 166)) 262 2060C0
# its left neighbour (image 3: art0 + anim, not highlighted, pinned -> frame 1)
pix "$T/menu_nine.ppm" $((60 + 28 + 166)) 262 00C000
# a 17th image is refused
{ for i in $(seq 1 17); do echo "image=p7:img$i|B$i|x"; done; } > "$T/many.conf"
rm -f "$T/choice"
if run "$T/x.ppm" "$T/many.conf"; then echo "headless: FAIL 17 images accepted"; exit 1; fi

python3 "$HERE/ppm2png.py" "$T/menu.ppm" "$T/codeselect_menu.png"
python3 "$HERE/ppm2png.py" "$T/menu.ppm.loading.ppm" "$T/codeselect_loading.png"
python3 "$HERE/ppm2png.py" "$T/menu_default1.ppm" "$T/codeselect_menu_default1.png"
python3 "$HERE/ppm2png.py" "$T/menu_invert.ppm" "$T/codeselect_menu_invert.png" --rot180-of "$T/menu.ppm"
python3 "$HERE/ppm2png.py" "$T/menu_three.ppm" "$T/codeselect_menu_three.png"
python3 "$HERE/ppm2png.py" "$T/menu_four.ppm" "$T/codeselect_menu_four.png"
python3 "$HERE/ppm2png.py" "$T/menu_media.ppm" "$T/codeselect_menu_media.png"
python3 "$HERE/ppm2png.py" "$T/menu_media.ppm.loading.ppm" "$T/codeselect_loading_media.png"
python3 "$HERE/ppm2png.py" "$T/menu_media_invert.ppm" "$T/codeselect_menu_media_invert.png" --rot180-of "$T/menu_media.ppm"
python3 "$HERE/ppm2png.py" "$T/menu_missing.ppm" "$T/codeselect_menu_missing.png"
python3 "$HERE/ppm2png.py" "$T/menu_five.ppm" "$T/codeselect_menu_five.png"
python3 "$HERE/ppm2png.py" "$T/menu_nine.ppm" "$T/codeselect_menu_nine.png"
echo "headless: OK (frames in $T/*.png, font $FONT)"
