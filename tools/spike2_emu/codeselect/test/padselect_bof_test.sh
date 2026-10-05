#!/bin/bash
# padselect_bof_test.sh BOFSELECT PADDELTA [FONT] - the Barrels of Fun boot hook
# (padselect_bof.sh) and install step (pad_install_bof.sh) against a fake /home/pinball
# (PADSELECT_HOME), with the real menu program on a fake framebuffer and no FAST board -
# so every menu here times out and boots its default, which is what the conf says.
#
#   install  1. image 1 rebuilt from its delta, checked, the delta gone; craze/ a hard
#               link to image 0; the decrypted archive removed
#            2. a delta that does not rebuild the recorded md5: image 1 out of the menu,
#               its files gone, image 0 kept
#   hook     3. default=1: image 1 becomes the game (a link), GAMEFILESIZE its size
#            4. default=0 after that: back to image 0; image 1 untouched (the remove
#               before the link: nothing is written through a hard link)
#            5. a program that is not the recorded size: image 0
#            6. no menu program: image 0, and the hook still returns 0
#            7. one image in the conf: nothing happens, no menu
#   sound    8. a conf naming a sound: the player (a stand-in for aplay) is started on
#               the device, reads the menu's mix from the pipe, and is gone - the pipe
#               removed - before the hook returns (the game's sound server needs the card)
#            9. a conf with no sound: no player at all
#   random  10. a random card over both images is the default card: the countdown lands on
#               it, the menu rolls one and writes ITS image index, and that image is the game
set -u
BIN=$1; DELTA=$2; FONT=${3:-}
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/.." && pwd)
T=$(mktemp -d /tmp/padselect_bof_test.XXXXXX)
trap 'rm -rf "$T"' EXIT
FAILS=0
ok() { echo "ok $*"; }
bad() { echo "FAIL $*"; FAILS=$((FAILS + 1)); }

H=$T/home
D=$H/extracted/decrypt
P=$D/padselect
export PADSELECT_HOME=$H PADSELECT_NO_SUDO=1 PADSELECT_CHOICE=$T/choice
export PAD_SELECT_FAKEFB="1366x768x32:$T/fb.raw" PAD_SELECT_FAST_ROOT=$T/no-board

setup() {   # a machine just after BOF's updater installed a two-image multi-boot .fun
    rm -rf "$H"
    mkdir -p "$P" "$H/craze"
    head -c 300000 /dev/urandom > "$D/GDCraze.x86_64"
    { head -c 100000 "$D/GDCraze.x86_64"; printf 'the mod'; tail -c +100001 "$D/GDCraze.x86_64"; } > "$T/mod.bin"
    PYTHONPATH="$SRC/../../bof_emu" python3 -c "
import sys, mkbofmulti as mb
ops = mb.delta_ops('$D/GDCraze.x86_64', '$T/mod.bin')
mb.write_delta(ops, '$D/GDCraze.x86_64', '$T/mod.bin', '$D/pad_image1.delta')"
    cp "$D/GDCraze.x86_64" "$H/craze/GDCraze.x86_64"          # the updater's copy
    stat -c %s "$D/GDCraze.x86_64" > "$H/craze/GAMEFILESIZE"
    : > "$H/extracted/lab.tar.gz.gpg"
    cp "$BIN" "$P/bofselect"; cp "$DELTA" "$P/paddelta"
    cp "$SRC/padselect_bof.sh" "$P/padselect.sh"; cp "$SRC/pad_install_bof.sh" "$P/pad_install.sh"
    [ -n "$FONT" ] && [ -f "$FONT" ] && cp "$FONT" "$P/font.ttf"
    printf '0 GDCraze.x86_64 %s %s\n1 pad_image1.bin %s %s pad_image1.delta\n' \
        "$(stat -c %s "$D/GDCraze.x86_64")" "$(md5sum < "$D/GDCraze.x86_64" | cut -d' ' -f1)" \
        "$(stat -c %s "$T/mod.bin")" "$(md5sum < "$T/mod.bin" | cut -d' ' -f1)" > "$P/programs"
    conf 0
}
conf() {    # conf <default>
    printf 'image=GDCraze.x86_64|STOCK|\nimage=pad_image1.bin|MOD|\ndefault=%s\ntimeout=1\n' "$1" > "$P/images.conf"
    rm -f "$P/last"
}
inode() { stat -c %i "$1"; }

# 1
setup
bash "$P/pad_install.sh"
[ -f "$D/pad_image1.bin" ] && cmp -s "$D/pad_image1.bin" "$T/mod.bin" && [ ! -e "$D/pad_image1.delta" ] \
    && ok "1 install: image 1 rebuilt and checked, the delta gone" || { bad "1 install: image 1"; cat "$P/install.log"; }
[ "$(inode "$H/craze/GDCraze.x86_64")" = "$(inode "$D/GDCraze.x86_64")" ] \
    && ok "1 install: craze is a link to image 0" || bad "1 install: craze is still a copy"
[ ! -e "$H/extracted/lab.tar.gz.gpg" ] && ok "1 install: the decrypted archive is gone" || bad "1 install: archive left"

# 3
conf 1
bash "$P/padselect.sh"; rc=$?
[ "$rc" = 0 ] && [ "$(inode "$H/craze/GDCraze.x86_64")" = "$(inode "$D/pad_image1.bin")" ] \
    && [ "$(cat "$H/craze/GAMEFILESIZE")" = "$(stat -c %s "$D/pad_image1.bin")" ] \
    && ok "3 hook: default 1 -> image 1 is the game, its size recorded" || { bad "3 hook: image 1"; cat "$P/padselect.log"; }
# 4
conf 0
bash "$P/padselect.sh"
[ "$(inode "$H/craze/GDCraze.x86_64")" = "$(inode "$D/GDCraze.x86_64")" ] && cmp -s "$D/pad_image1.bin" "$T/mod.bin" \
    && ok "4 hook: back to image 0, image 1 untouched" || { bad "4 hook: back to image 0"; cat "$P/padselect.log"; }
# 5
conf 1
printf 'x' >> "$D/pad_image1.bin"
bash "$P/padselect.sh"
[ "$(inode "$H/craze/GDCraze.x86_64")" = "$(inode "$D/GDCraze.x86_64")" ] && grep -q "is not usable: image 0" "$P/padselect.log" \
    && ok "5 hook: a program of the wrong size -> image 0" || { bad "5 hook: wrong size"; cat "$P/padselect.log"; }
truncate -s -1 "$D/pad_image1.bin"
# 6
mv "$P/bofselect" "$T/bofselect.away"
bash "$P/padselect.sh"; rc=$?
[ "$rc" = 0 ] && [ "$(inode "$H/craze/GDCraze.x86_64")" = "$(inode "$D/GDCraze.x86_64")" ] && grep -q "no menu program" "$P/padselect.log" \
    && ok "6 hook: no menu program -> image 0, exit 0" || { bad "6 hook: no menu program"; cat "$P/padselect.log"; }
mv "$T/bofselect.away" "$P/bofselect"
# 7
printf 'image=GDCraze.x86_64|STOCK|\ndefault=0\ntimeout=1\n' > "$P/images.conf"
rm -f "$P/bofselect.log"
bash "$P/padselect.sh"
[ ! -e "$P/bofselect.log" ] && grep -q "1 image(s)" "$P/padselect.log" \
    && ok "7 hook: one image -> no menu" || { bad "7 hook: one image"; cat "$P/padselect.log"; }

# 8
setup
mkdir -p "$P/media"
python3 - "$P/media/move.wav" <<'PY'
import math, struct, sys, wave
w = wave.open(sys.argv[1], "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
w.writeframes(b"".join(struct.pack("<hh", v, v) for v in
                       (int(8000 * math.sin(i / 20.0)) for i in range(44100 // 5))))
w.close()
PY
printf '#!/bin/bash\necho "$*" > %s/player.args\nexec cat "${@: -1}" > %s/played\n' "$T" "$T" > "$T/fakeplay"
chmod +x "$T/fakeplay"
printf 'sound_move=move.wav\nmedia=%s\n' "$P/media" >> "$P/images.conf"
rm -f "$T/played" "$T/player.args"
PADSELECT_AUDIO_PLAYER="$T/fakeplay" PADSELECT_AUDIO_DEV=plughw:7,0 bash "$P/padselect.sh"; rc=$?
fifo_left=$(ls /tmp/padselect.audio.* 2>/dev/null | head -1)
if [ "$rc" = 0 ] && grep -q "sound: fakeplay on plughw:7,0" "$P/padselect.log" && grep -q "player stopped" "$P/padselect.log" \
    && grep -q -- "-t raw -f S16_LE -r 44100 -c 2 -B 80000 -F 20000 -D plughw:7,0" "$T/player.args" \
    && [ "$(stat -c %s "$T/played" 2>/dev/null || echo 0)" -gt 4096 ] \
    && ! pgrep -f "$T/fakeplay" >/dev/null && [ -z "$fifo_left" ] \
    && grep -q "audio: sink fifo, lead 40 ms" "$P/bofselect.log"; then
    # the lag between a flipper and its click: aplay's 80 ms buffer and a 40 ms lead,
    # where it was aplay's default half second and 200 ms (a second on the machine)
    ok "8 sound: the player got $(stat -c %s "$T/played") bytes of the menu's mix (80 ms buffer, 40 ms lead) and was gone before the game"
else
    bad "8 sound (played $(stat -c %s "$T/played" 2>/dev/null) bytes, fifo left '$fifo_left')"
    cat "$P/padselect.log"; cat "$P/audio.log" 2>/dev/null; grep -i audio "$P/bofselect.log"
fi
# 9
conf 0
rm -f "$T/player.args"
PADSELECT_AUDIO_PLAYER="$T/fakeplay" bash "$P/padselect.sh"
[ ! -e "$T/player.args" ] && grep -q "sound: none in the conf" "$P/padselect.log" \
    && ok "9 sound: a conf with no sound starts no player" || { bad "9 no sound"; cat "$P/padselect.log"; }
# 10
setup
bash "$P/pad_install.sh"
printf 'group=+0-1|RANDOM|\nimage=GDCraze.x86_64|STOCK|\nimage=pad_image1.bin|MOD|\ndefault=0\ndefault_card=0\ntimeout=1\n' \
    > "$P/images.conf"
rm -f "$P/last"
seen=""
for seed in 1 2 3 4 5 6; do
    PADSELECT_MENU_ARGS="--seed $seed" bash "$P/padselect.sh"
    c=$(sed -n "s/.*menu exit 0, choice '\([0-9]\)'.*/\1/p" "$P/padselect.log")
    f=$([ "$c" = 1 ] && echo pad_image1.bin || echo GDCraze.x86_64)
    if [ -z "$c" ] || [ "$(inode "$H/craze/GDCraze.x86_64")" != "$(inode "$D/$f")" ]; then
        seen="BAD"; cat "$P/padselect.log"; break
    fi
    seen="$seen$c"
done
case "$seen" in
    *BAD*) bad "10 random card: the rolled image is not the game" ;;
    *0*1*|*1*0*) ok "10 random card: the countdown rolled $seen - each roll's image became the game" ;;
    *) bad "10 random card: six rolls all landed on one image ($seen)" ;;
esac

# 2
setup
printf '\n' >> "$T/mod.bin"     # the recorded md5 is the old one; rewrite programs for the new
awk -v m="$(md5sum < "$T/mod.bin" | cut -d' ' -f1)" '$1 == 1 { $4 = m } { print }' "$P/programs" > "$P/p" && mv "$P/p" "$P/programs"
bash "$P/pad_install.sh"
[ ! -e "$D/pad_image1.bin" ] && [ "$(grep -c '^image=' "$P/images.conf")" = 1 ] && grep -q "taken out of the menu" "$P/install.log" \
    && [ -f "$D/GDCraze.x86_64" ] && ok "2 install: a delta that does not check out -> image 1 out of the menu" \
    || { bad "2 install: bad delta"; cat "$P/install.log"; }

if [ "$FAILS" = 0 ]; then echo "padselect_bof_test: OK"; else echo "padselect_bof_test: $FAILS FAILED"; exit 1; fi
