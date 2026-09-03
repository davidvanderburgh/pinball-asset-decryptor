#!/bin/bash
# QEMU=qemu-arm-static headless.sh ROOT BIN T DEJAVU - render the menu without
# EGL under qemu-arm-static against the card rootfs libs, check the choice/last
# files, the PPM shape, the default/last-choice precedence, the -invert
# rotation, the art panels (stills, a pinned GIF frame, a missing picture),
# the 5- and 9-image carousels, the --snapshot frame (the preview: one frame,
# nothing else started or written), the --frames K run (a whole animation out
# of ONE load), and convert every frame to PNG in $T for eyes.
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
grep -q "media: 2 art, 1 anim (4 frames), 1 music, 0 card confirm, move=y confirm=y" "$T/media.log" || {
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
grep -q "media: 2 art, 1 anim (4 frames), 0 music, 0 card confirm, move=n confirm=n" "$T/missing.log" || {
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

# 11. --snapshot: ONE frame, what the machine shows the moment the menu
#     appears, nothing started or written but the PPM. --highlight 1
#     --anim-frame 2 on the media conf: card 1's GIF at frame 2 (blue) and
#     card 0's still at the panel centres; the countdown line (amber, 38 px on
#     baseline 718) holds the conf's timeout as if just started; the stdout
#     line names the frame count; no choice/last/LOADING file; no input or
#     audio opened (no nb/spi/audio line in the log, and the WAVs are not even
#     loaded: 0 music, move=n). The snap helper passes neither --input nor
#     --audio: their defaults (hw, auto) must not matter.
snap() {   # snap PPM CONF [extra args...] -> stdout in $T/snap.out
    local ppm=$1 conf=$2; shift 2
    "$QEMU" -L "$ROOT" "$BIN" --snapshot "$ppm" --conf "$conf" --out "$T/choice" --last "$T/last" \
        --log "$T/snap.log" --font "$FONT" "$@" > "$T/snap.out"
}
band() {   # band PPM X0 Y0 X1 Y1 RRGGBB - at least one pixel of that colour in the rectangle
    python3 "$HERE/mkmedia.py" band "$@"
}
rm -f "$T/choice" "$T/last" "$T/snap.log"
snap "$T/snap_1_2.ppm" "$T/media.conf" --media "$T/media" --highlight 1 --anim-frame 2 || {
    echo "headless: FAIL snapshot exit $?"; cat "$T/snap.out"; exit 1; }
[ "$(head -c 16 "$T/snap_1_2.ppm" | tr '\n' ' ')" = "P6 1360 768 255 " ] || { echo "headless: FAIL snapshot PPM header"; exit 1; }
[ "$(stat -c %s "$T/snap_1_2.ppm")" -eq $((16 + 1360 * 768 * 3)) ] || { echo "headless: FAIL snapshot PPM size"; exit 1; }
[ ! -f "$T/choice" ] && [ ! -f "$T/last" ] || { echo "headless: FAIL the snapshot wrote a choice/last file"; exit 1; }
[ ! -f "$T/snap_1_2.ppm.loading.ppm" ] || { echo "headless: FAIL the snapshot wrote a LOADING frame"; exit 1; }
pix "$T/snap_1_2.ppm" 361 262 C03040                 # card 0: its still
pix "$T/snap_1_2.ppm" 999 262 0000FF                 # card 1 (highlighted): GIF frame 2
band "$T/snap_1_2.ppm" 300 684 1060 722 FFC42D       # 'booting TMNT 1987 in 1 s'
grep -qF "snapshot: $T/snap_1_2.ppm 1360x768, highlight 1 (TMNT 1987) from --highlight, frame 2 of 4, timeout 1 s, invert 0, font $FONT, media $T/media" "$T/snap.out" || {
    echo "headless: FAIL snapshot stdout line"; cat "$T/snap.out"; exit 1; }
grep -qF ", pictures 1:899,255,200,112" "$T/snap.out" || {
    echo "headless: FAIL snapshot pictures field (highlighted)"; cat "$T/snap.out"; exit 1; }
grep -q "media: 2 art, 1 anim (4 frames), 0 music, 0 card confirm, move=n confirm=n" "$T/snap.log" || {
    echo "headless: FAIL the snapshot touched the sounds"; grep media "$T/snap.log"; exit 1; }
if grep -qE "(nb|spi|audio): " "$T/snap.log"; then echo "headless: FAIL the snapshot opened input or audio"; exit 1; fi
# card 1 NOT highlighted plays its animation too (David, 2026-09-03: every
# card plays, all the time), so --anim-frame 2 pins IT at frame 2 as well;
# card 0 has no animation -> its still, and 'frame 0 of 0' for the
# highlighted card's own count.  The 'pictures' field names every visible
# animated card's rectangle, highlighted or not.
snap "$T/snap_0_2.ppm" "$T/media.conf" --media "$T/media" --highlight 0 --anim-frame 2
pix "$T/snap_0_2.ppm" 361 262 C03040
pix "$T/snap_0_2.ppm" 999 262 0000FF
grep -qF "highlight 0 (STERN STOCK) from --highlight, frame 0 of 0," "$T/snap.out" || {
    echo "headless: FAIL snapshot frame count without an animation"; cat "$T/snap.out"; exit 1; }
grep -qF ", pictures 1:899,255,200,112" "$T/snap.out" || {
    echo "headless: FAIL snapshot pictures field"; cat "$T/snap.out"; exit 1; }
# a frame past the end wraps (6 of 4 -> 2)
snap "$T/snap_wrap.ppm" "$T/media.conf" --media "$T/media" --highlight 1 --anim-frame 6
pix "$T/snap_wrap.ppm" 999 262 0000FF
grep -qF "frame 2 of 4," "$T/snap.out" || { echo "headless: FAIL snapshot frame wrap"; cat "$T/snap.out"; exit 1; }
# no --highlight: the conf default (1) - never the last-choice file, which is
# neither read nor written
echo 0 > "$T/last"
snap "$T/snap_def.ppm" "$T/media.conf" --media "$T/media"
grep -qF "highlight 1 (TMNT 1987) from conf default, frame 0 of 4," "$T/snap.out" || {
    echo "headless: FAIL snapshot default highlight"; cat "$T/snap.out"; exit 1; }
pix "$T/snap_def.ppm" 999 262 FF0000                 # frame 0
expect "$T/last" 0
rm -f "$T/last"
# timeout 0: 'press START to boot ...' in the same amber on the same baseline
snap "$T/snap_wait.ppm" "$T/three.conf"
band "$T/snap_wait.ppm" 300 684 1060 722 FFC42D
grep -qF "highlight 1 (GODZILLA HEISEI) from conf default, frame 0 of 0, timeout 0 s," "$T/snap.out" || {
    echo "headless: FAIL snapshot timeout-0 line"; cat "$T/snap.out"; exit 1; }
# a missing media directory: every picture fails, the cards render without
# them, exit 0
rm -f "$T/snap.log"
snap "$T/snap_nomedia.ppm" "$T/missing.conf" --media "$T/nonexistent" --highlight 2
grep -q "art: cannot load art0.png" "$T/snap.log" || { echo "headless: FAIL missing media dir not logged"; exit 1; }
grep -q "anim: cannot open anim1.gif" "$T/snap.log" || { echo "headless: FAIL missing GIF not logged"; exit 1; }
grep -q "media: 0 art, 0 anim (0 frames), 0 music, 0 card confirm, move=n confirm=n" "$T/snap.log" || {
    echo "headless: FAIL media line without a media dir"; grep media "$T/snap.log"; exit 1; }
band "$T/snap_nomedia.ppm" 300 684 1060 722 FFC42D
# THEMES (theme.h): theme= picks a built-in, color_<role>= puts one colour on
# top of it, theme=custom is the default plus the overrides, an unknown name
# falls back to the default and says so, a bad colour value is ignored - and
# none of it can keep a machine from booting
cat > "$T/theme.conf" <<'EOF'
image=/dev/mmcblk0p3|STERN STOCK|original code
image=/dev/mmcblk0p7|TMNT 1987|retheme
default=1
timeout=0
theme=daylight
EOF
rm -f "$T/snap.log"
snap "$T/snap_theme.ppm" "$T/theme.conf"
pix "$T/snap_theme.ppm" 5 5 F2F0EA                   # daylight's background...
band "$T/snap_theme.ppm" 300 684 1060 722 C2410C     # ...and its countdown line
grep -q "theme: daylight (0 of 14 colours set by the conf)" "$T/snap.log" || {
    echo "headless: FAIL theme log"; cat "$T/snap.log"; exit 1; }
cat > "$T/custom.conf" <<'EOF'
image=/dev/mmcblk0p3|STERN STOCK|original code
image=/dev/mmcblk0p7|TMNT 1987|retheme
default=1
timeout=0
theme=custom
color_background=#102030
color_countdown=00FF00
color_frame_hl=notacolour
color_nosuchrole=ffffff
EOF
rm -f "$T/snap.log"
snap "$T/snap_custom.ppm" "$T/custom.conf"
pix "$T/snap_custom.ppm" 5 5 102030
band "$T/snap_custom.ppm" 300 684 1060 722 00FF00
grep -q "theme: custom (2 of 14 colours set by the conf, 2 colour values ignored)" "$T/snap.log" || {
    echo "headless: FAIL custom theme log"; cat "$T/snap.log"; exit 1; }
sed 's/^theme=custom$/theme=nosuchtheme/' "$T/custom.conf" > "$T/unknown.conf"
rm -f "$T/snap.log"
snap "$T/snap_unknown.ppm" "$T/unknown.conf"
pix "$T/snap_unknown.ppm" 5 5 102030                 # the overrides still apply on the fallback
grep -q "theme: 'nosuchtheme' is not a theme, using midnight" "$T/snap.log" || {
    echo "headless: FAIL unknown theme log"; cat "$T/snap.log"; exit 1; }
grep -q "theme: midnight (2 of 14 colours set by the conf, 2 colour values ignored)" "$T/snap.log" || {
    echo "headless: FAIL unknown theme falls back"; cat "$T/snap.log"; exit 1; }
# no theme key at all: the default, and the pixels this program always drew
rm -f "$T/snap.log"
snap "$T/snap_notheme.ppm" "$T/three.conf"
pix "$T/snap_notheme.ppm" 5 5 0B0E13
band "$T/snap_notheme.ppm" 300 684 1060 722 FFC42D
grep -q "theme: midnight (0 of 14 colours set by the conf)" "$T/snap.log" || {
    echo "headless: FAIL default theme log"; cat "$T/snap.log"; exit 1; }
# refused, exit 2, no PPM: --highlight past the end, an empty conf,
# --snapshot together with --headless
rm -f "$T/snap_bad.ppm"
if snap "$T/snap_bad.ppm" "$T/media.conf" --media "$T/media" --highlight 2; then echo "headless: FAIL --highlight 2 of 2 accepted"; exit 1; fi
grep -qF "error: --highlight 2 out of range (2 images)" "$T/snap.out" || {
    echo "headless: FAIL no error line for --highlight 2"; cat "$T/snap.out"; exit 1; }
if snap "$T/snap_bad.ppm" "$T/empty.conf"; then echo "headless: FAIL snapshot of an empty conf accepted"; exit 1; fi
grep -qF "error: " "$T/snap.out" || { echo "headless: FAIL no error line for the empty conf"; exit 1; }
if snap "$T/snap_bad.ppm" "$T/media.conf" --headless "$T/x.ppm" 2>/dev/null; then echo "headless: FAIL --snapshot with --headless accepted"; exit 1; fi
[ ! -f "$T/snap_bad.ppm" ] || { echo "headless: FAIL a refused snapshot wrote a PPM"; exit 1; }

# 12. --frames K: a WHOLE RUN of frames out of ONE load, which is the whole
#     point - the preview used to pay a process start and a re-decode of every
#     PNG, GIF and font for each frame it showed. K > 1 turns the --snapshot
#     value into a printf pattern holding the frame number, so the caller keeps
#     its own file names.
# K = 1 is the old path to the byte: the same picture and the same stdout line
# as no --frames at all (the file name is the only difference, so it is masked)
rm -f "$T/f1.ppm" "$T/f1n.ppm"
snap "$T/f1.ppm" "$T/media.conf" --media "$T/media" --highlight 1 --anim-frame 2
sed 's#/f1\.ppm#/FRAME#' "$T/snap.out" > "$T/f1.out"
snap "$T/f1n.ppm" "$T/media.conf" --media "$T/media" --highlight 1 --anim-frame 2 --frames 1
sed 's#/f1n\.ppm#/FRAME#' "$T/snap.out" > "$T/f1n.out"
cmp -s "$T/f1.ppm" "$T/f1n.ppm" || { echo "headless: FAIL --frames 1 is not the single-frame picture"; exit 1; }
cmp -s "$T/f1.out" "$T/f1n.out" || { echo "headless: FAIL --frames 1 changed the stdout line"; diff "$T/f1.out" "$T/f1n.out"; exit 1; }
# a '%' in the name is a NAME with K = 1, never a pattern
rm -f "$T/100%_f1.ppm"
snap "$T/100%_f1.ppm" "$T/media.conf" --media "$T/media" --highlight 1
[ -f "$T/100%_f1.ppm" ] || { echo "headless: FAIL K=1 expanded a '%' in the file name"; exit 1; }

# four frames, one run: the GIF's four colours in turn at the highlighted
# panel centre, card 0's still unmoved in every one, four DIFFERENT files
rm -f "$T"/run_*.ppm
snap "$T/run_%d.ppm" "$T/media.conf" --media "$T/media" --highlight 1 --frames 4
i=0
for want in FF0000 00C000 0000FF FFFF00; do
    [ -f "$T/run_$i.ppm" ] || { echo "headless: FAIL --frames 4 wrote no run_$i.ppm"; exit 1; }
    pix "$T/run_$i.ppm" 999 262 "$want"      # the animation moves
    pix "$T/run_$i.ppm" 361 262 C03040       # and only the animation moves
    grep -qF "snapshot: $T/run_$i.ppm 1360x768, highlight 1 (TMNT 1987) from --highlight, frame $i of 4," "$T/snap.out" || {
        echo "headless: FAIL no snapshot line for frame $i"; cat "$T/snap.out"; exit 1; }
    i=$((i + 1))
done
[ "$(ls "$T"/run_*.ppm | wc -l)" = 4 ] || { echo "headless: FAIL --frames 4 wrote $(ls "$T"/run_*.ppm | wc -l) files"; exit 1; }
for a in 0 1 2 3; do
    for b in 0 1 2 3; do
        if [ "$a" -lt "$b" ] && cmp -s "$T/run_$a.ppm" "$T/run_$b.ppm"; then
            echo "headless: FAIL --frames 4: frames $a and $b are the same picture"; exit 1
        fi
    done
done

# the run wraps at the end of the animation, and each file is named for the
# FRAME it holds, not for its place in the run: 3, 0, 1
rm -f "$T"/wrap_*.ppm
snap "$T/wrap_%d.ppm" "$T/media.conf" --media "$T/media" --highlight 1 --anim-frame 3 --frames 3
pix "$T/wrap_3.ppm" 999 262 FFFF00
pix "$T/wrap_0.ppm" 999 262 FF0000
pix "$T/wrap_1.ppm" 999 262 00C000
[ ! -f "$T/wrap_2.ppm" ] || { echo "headless: FAIL --anim-frame 3 --frames 3 wrote frame 2"; exit 1; }
for f in 3 0 1; do
    grep -qF "snapshot: $T/wrap_$f.ppm 1360x768, highlight 1 (TMNT 1987) from --highlight, frame $f of 4," "$T/snap.out" || {
        echo "headless: FAIL no wrapped snapshot line for frame $f"; cat "$T/snap.out"; exit 1; }
done

# more frames than the animation has would only rewrite files this same run
# has already written: trimmed, and said in the log
rm -f "$T"/cap_*.ppm "$T/cap.log"
snap "$T/cap_%d.ppm" "$T/media.conf" --media "$T/media" --highlight 1 --frames 8 --log "$T/cap.log"
[ "$(ls "$T"/cap_*.ppm | wc -l)" = 4 ] || { echo "headless: FAIL --frames 8 on a 4-frame GIF wrote $(ls "$T"/cap_*.ppm | wc -l) files"; exit 1; }
grep -q "snapshot: 8 frames asked for, image 1 has 4: 4 written" "$T/cap.log" || {
    echo "headless: FAIL no cap line in the log"; grep snapshot "$T/cap.log"; exit 1; }

# a card with NO animation has nothing to step: ONE file, and the log says so
# (its 'frame 0 of 0' already tells a caller to stop asking)
rm -f "$T"/still_*.ppm "$T/still.log"
snap "$T/still_%d.ppm" "$T/media.conf" --media "$T/media" --highlight 0 --frames 4 --log "$T/still.log"
[ "$(ls "$T"/still_*.ppm | wc -l)" = 1 ] || { echo "headless: FAIL a still card wrote $(ls "$T"/still_*.ppm | wc -l) files"; exit 1; }
[ -f "$T/still_0.ppm" ] || { echo "headless: FAIL the one still frame is not still_0.ppm"; exit 1; }
grep -q "snapshot: image 0 has no animation: 1 frame, not 4" "$T/still.log" || {
    echo "headless: FAIL no 'no animation' line in the log"; grep snapshot "$T/still.log"; exit 1; }
grep -qF "frame 0 of 0," "$T/snap.out" || { echo "headless: FAIL still frame count"; cat "$T/snap.out"; exit 1; }

# refused BEFORE a byte is written: K out of range, and every pattern that is
# not exactly one bare %d. The message goes to stderr, like the other argument
# refusals, and nothing is left on disk.
rm -f "$T"/bad_* "$T/bad.ppm"
refuse() {   # refuse WHAT SNAPSHOT-VALUE [extra args...]
    local what=$1 val=$2; shift 2
    if "$QEMU" -L "$ROOT" "$BIN" --snapshot "$val" --conf "$T/media.conf" --media "$T/media" \
        --font "$FONT" "$@" > "$T/snap.out" 2> "$T/snap.err"; then
        echo "headless: FAIL $what accepted"; cat "$T/snap.out"; exit 1
    fi
    grep -q "^codeselect: " "$T/snap.err" || {
        echo "headless: FAIL $what refused without a message"; cat "$T/snap.err"; exit 1; }
}
refuse "--frames 0"                "$T/bad_%d.ppm"    --frames 0
refuse "--frames 151"              "$T/bad_%d.ppm"    --frames 151
refuse "a pattern with no %d"      "$T/bad.ppm"       --frames 4
refuse "a pattern with two %d"     "$T/bad_%d_%d.ppm" --frames 4
refuse "a %s in the pattern"       "$T/bad_%s.ppm"    --frames 4
refuse "a width in the pattern"    "$T/bad_%03d.ppm"  --frames 4
refuse "a pattern ending in %"     "$T/bad_%"         --frames 4
[ -z "$(ls "$T"/bad_* "$T/bad.ppm" 2>/dev/null)" ] || { echo "headless: FAIL a refused --frames run wrote a file"; exit 1; }
# and K > 1 belongs to --snapshot alone
if run "$T/x.ppm" "$T/two.conf" --frames 4 2>/dev/null; then echo "headless: FAIL --frames 4 without --snapshot accepted"; exit 1; fi
# a literal percent survives a pattern
rm -f "$T"/pc_*
snap "$T/pc_100%%_%d.ppm" "$T/media.conf" --media "$T/media" --highlight 1 --frames 2
[ -f "$T/pc_100%_0.ppm" ] && [ -f "$T/pc_100%_1.ppm" ] || { echo "headless: FAIL '%%' in a pattern"; ls "$T"/pc_*; exit 1; }

python3 "$HERE/ppm2png.py" "$T/run_0.ppm" "$T/codeselect_frames_0.png"
python3 "$HERE/ppm2png.py" "$T/run_3.ppm" "$T/codeselect_frames_3.png"
python3 "$HERE/ppm2png.py" "$T/snap_1_2.ppm" "$T/codeselect_snapshot.png"
python3 "$HERE/ppm2png.py" "$T/snap_nomedia.ppm" "$T/codeselect_snapshot_nomedia.png"
python3 "$HERE/ppm2png.py" "$T/menu.ppm" "$T/codeselect_menu.png"
# 13. volume=machine: the MASTER VOLUME SETTING off the card's /data/nv mirror
#     (nvm.h) - the newest generation wins, a missing store falls back to the
#     title's factory level, and --volume still overrides both
python3 "$HERE/mkmedia.py" nvm "$T/nv/NVM" 33
cat > "$T/machine.conf" <<EOF
image=p3|A|a
image=p7|B|b
volume=machine
machine_volume=$T/nv/NVM|73fa9f7f0223dfa965f070fa2d0d49ed0efaec62|18
default=0
timeout=1
EOF
run "$T/menu_machine.ppm" "$T/machine.conf" --log "$T/machine.log"
grep -q "audio: volume follows the machine: 33/63 ($T/nv/NVM/00000002)" "$T/machine.log" \
    || { echo "headless: FAIL volume=machine did not read 33/63 from the newest generation"; grep audio "$T/machine.log"; exit 1; }
rm -rf "$T/nv"
run "$T/menu_machine.ppm" "$T/machine.conf" --log "$T/machine.log"
grep -q "no setting read (no store in $T/nv/NVM); the title's factory 18/63" "$T/machine.log" \
    || { echo "headless: FAIL volume=machine without a store did not fall back to the factory level"; grep audio "$T/machine.log"; exit 1; }
run "$T/menu_machine.ppm" "$T/machine.conf" --log "$T/machine.log" --volume 70
grep -q "audio: --volume 70 overrides volume=machine" "$T/machine.log" \
    || { echo "headless: FAIL --volume did not override volume=machine"; grep audio "$T/machine.log"; exit 1; }
expect "$T/choice" 0

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
