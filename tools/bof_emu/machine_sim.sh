#!/bin/bash
# machine_sim.sh <stock .fun> <multi-boot .fun> [workdir] - a Barrels of Fun machine's
# update and boot, run with the machine's OWN scripts (PAD-342).  Root, in WSL.
#
# Nothing of the machine's is rewritten: its updater (update/updatecode.sh), its
# update.sh and its ~/.bash_profile come out of the .fun files themselves and run
# unmodified, against a /home/pinball that is a bind mount in a private mount namespace
# (unshare -m), so they see the paths they were written for and nothing outside this
# run sees anything.  What the machine has and this does not is stood in for:
#
#   sudo, reboot, fbset, parsesettings, nocode, systemerror, logs, usleep
#         a bin dir first on PATH: logged, never run (sudo runs its command)
#   ~/stopgame, ~/updater/main      no-ops (the game is not running; main is the
#                                   updater's progress screen)
#   ~/startgame                     records which program is the game: the inode and
#                                   size of ~/craze/GDCraze.x86_64, and GAMEFILESIZE
#   /dev/fb0                        PAD_SELECT_FAKEFB, a file (the menu's last frame)
#   the FAST Neuron                 tools/bof_emu/bofhw.py with Labyrinth's profile:
#                                   the flippers are pressed through its control socket
#
# The run, each step checked:
#   A  the stock .fun installed by the machine's updater (the starting point)
#   B  the multi-boot .fun installed the same way: the install step rebuilds image 1
#      from its delta and checks it, the profile carries the hook, craze is a link
#   C  power-up: RIGHT, START -> image 1 is the game, its size recorded
#   D  power-up: LEFT, START -> back to image 0, image 1 untouched
#   E  power-up, no button: the countdown boots the remembered choice
#   F  the stock .fun installed again: the menu, its files and the hook are gone
set -u
STOCK=${1:?stock .fun}
MULTI=${2:?multi-boot .fun}
W=${3:-/var/tmp/pad_bofmachine}
HERE=$(cd "$(dirname "$0")" && pwd)
[ "$(id -u)" = 0 ] || { echo "machine_sim: run as root (the bind mounts)"; exit 2; }
if [ -z "${PAD_SIM_INNER:-}" ]; then
    export PAD_SIM_INNER=1
    exec unshare -m --propagation private bash "$0" "$@"
fi
STOCK=$(readlink -f "$STOCK")
MULTI=$(readlink -f "$MULTI")
H=/home/pinball
FAILS=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; FAILS=$((FAILS + 1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }

rm -rf "$W/home" "$W/usb" "$W/bin" "$W/rig"
mkdir -p "$W/home/pinball" "$W/usb" "$W/bin" "$W/rig" "$W/fbs"
mount --bind "$W/home" /home || { echo "machine_sim: cannot bind $W/home over /home"; exit 2; }

# ---- the machine's stand-ins ------------------------------------------------
cat > "$W/bin/sudo" <<'EOF'
#!/bin/bash
echo "sudo $*" >> /home/pinball/sudo.log
[ "${1:-}" = "-n" ] && shift
case "${1:-}" in
    reboot|systemerror|nocode|logs|fbset) exit 0 ;;
esac
exec "$@"
EOF
for t in reboot fbset parsesettings nocode systemerror logs usleep; do
    printf '#!/bin/bash\necho "%s $*" >> /home/pinball/sudo.log\nexit 0\n' "$t" > "$W/bin/$t"
done
chmod 755 "$W/bin"/*
mkdir -p $H/craze $H/updater $H/extracted $H/images
printf '#!/bin/bash\nexit 0\n' > $H/stopgame
printf '#!/bin/bash\nexit 0\n' > $H/updater/main
cat > $H/startgame <<'EOF'
#!/bin/bash
echo "boot $(stat -c '%i %s' /home/pinball/craze/GDCraze.x86_64) $(cat /home/pinball/craze/GAMEFILESIZE)" >> /home/pinball/boots.log
EOF
chmod 755 $H/stopgame $H/updater/main $H/startgame
export PATH="$W/bin:$PATH"

# the machine's own updater and profile: out of the stock .fun
gpg --batch --quiet --pinentry-mode loopback --passphrase funkey -d "$STOCK" 2>/dev/null \
    | tar -xz -C "$W" update 2>/dev/null
[ -f "$W/update/updatecode.sh" ] && [ -f "$W/update/.bash_profile" ] \
    || { echo "machine_sim: $STOCK has no update/updatecode.sh and .bash_profile"; exit 2; }
cp "$W/update/updatecode.sh" $H/updatecode.sh
cp "$W/update/.bash_profile" $H/.bash_profile
chmod +x $H/updatecode.sh

usb_install() {       # usb_install <fun> - the stick goes in, the updater runs
    rm -f "$W/usb/lab.fun"
    ln -s "$1" "$W/usb/lab.fun"
    echo "== update from $1"
    ( cd $H && bash $H/updatecode.sh "$W/usb" ) >/dev/null 2>&1
    echo "   updater state $(cat /tmp/UPDATESTATE 2>/dev/null)"
}

# ---- the FAST board -------------------------------------------------------------
python3 "$HERE/bofhw.py" --dir "$W/rig" --profile "$HERE/profiles/labyrinth.json" >/dev/null 2>&1 &
HW=$!
trap 'kill $HW 2>/dev/null' EXIT
for _ in $(seq 50); do [ -S "$W/rig/ctl.sock" ] && break; sleep 0.1; done
ctl() { python3 -c "
import socket,sys
s=socket.socket(socket.AF_UNIX); s.connect('$W/rig/ctl.sock'); s.sendall((sys.argv[1]+'\n').encode()); s.recv(100)" "$1"; }

boot() {             # boot <name> <switch...> - power-up, the menu, the buttons, the game
    local name=$1; shift
    local log=$H/extracted/decrypt/padselect/bofselect.log
    rm -f "$log"
    echo "== power-up: $name (buttons: ${*:-none})"
    ( cd $H && env HOME=$H PAD_SELECT_FAKEFB="1366x768x32:$W/fbs/$name.raw" PAD_SELECT_FAST_ROOT="$W/rig" \
        bash -c '. /home/pinball/.bash_profile' ) >/dev/null 2>&1 &
    local prof=$!
    if [ $# -gt 0 ]; then
        for _ in $(seq 100); do grep -q "switches read" "$log" 2>/dev/null && break; sleep 0.1; done
        sleep 0.5
        for sw in "$@"; do ctl "tap $sw 200"; sleep 0.6; done
    fi
    for _ in $(seq 300); do kill -0 $prof 2>/dev/null || break; sleep 0.2; done
    kill $prof 2>/dev/null
    tail -1 $H/boots.log | sed 's/^/   /'
}
game_is() {          # game_is <file in decrypt/> - that file is the game, its size recorded
    local f=$H/extracted/decrypt/$1 last
    last=$(tail -1 $H/boots.log)
    [ "$last" = "boot $(stat -c '%i %s' "$f") $(stat -c %s "$f")" ]
}

# A ---------------------------------------------------------------------------------
usb_install "$STOCK"
check "A stock install: the game is the stock program" \
    "[ \"\$(stat -c %s $H/craze/GDCraze.x86_64)\" = \"\$(stat -c %s $H/extracted/decrypt/GDCraze.x86_64)\" ]"
check "A stock install: the profile has no menu hook" "! grep -q 'PAD multi-boot' $H/.bash_profile"

# B ---------------------------------------------------------------------------------
usb_install "$MULTI"
P=$H/extracted/decrypt/padselect
sed 's/^/   install.log: /' "$P/install.log" 2>/dev/null | grep -v '^   install.log: Filesystem\|^   install.log: /dev\|overlay\|^   install.log: none' | head -20
check "B the profile carries the menu hook" "grep -q 'PAD multi-boot (PAD-342)' $H/.bash_profile"
check "B the profile's self-repair removes before it copies" "grep -q 'rm -f /home/pinball/craze/GDCraze.x86_64; cp -rf' $H/.bash_profile"
check "B the install step rebuilt image 1 and checked it" "grep -q 'image 1 (pad_image1.bin): .* ok' $P/install.log"
check "B the delta and the decrypted archive are gone" "[ ! -e $H/extracted/decrypt/pad_image1.delta ] && ! ls $H/extracted/*.tar.gz.gpg >/dev/null 2>&1"
check "B craze is a link to image 0, not a copy" "[ \"\$(stat -c %i $H/craze/GDCraze.x86_64)\" = \"\$(stat -c %i $H/extracted/decrypt/GDCraze.x86_64)\" ]"
check "B two images in the menu" "[ \"\$(grep -c '^image=' $P/images.conf)\" = 2 ]"
IMG1_MD5=$(awk '$1 == 1 { print $4 }' $P/programs)

# C ---------------------------------------------------------------------------------
boot C 22 14
check "C RIGHT, START: image 1 is the game" "game_is pad_image1.bin"
check "C the menu said so" "grep -q 'chose 1' $P/bofselect.log"
# D ---------------------------------------------------------------------------------
boot D 15 14
check "D LEFT, START: image 0 is the game again" "game_is GDCraze.x86_64"
check "D image 1 is untouched by the switch back" "[ \"\$(md5sum < $H/extracted/decrypt/pad_image1.bin | cut -d' ' -f1)\" = \"$IMG1_MD5\" ]"
# E ---------------------------------------------------------------------------------
boot C2 22 14 >/dev/null
boot E
check "E no button: the countdown boots the remembered image 1" "game_is pad_image1.bin"
check "E ...from the menu's own countdown" "grep -q 'countdown expired' $P/bofselect.log"
# F ---------------------------------------------------------------------------------
usb_install "$STOCK"
check "F a normal update: the menu's files are gone" "[ ! -e $H/extracted/decrypt/padselect ] && [ ! -e $H/extracted/decrypt/pad_image1.bin ]"
check "F a normal update: its own profile is back (no hook)" "! grep -q 'PAD multi-boot' $H/.bash_profile"
boot F
check "F power-up after it: the stock program, no menu" \
    "[ \"\$(tail -1 $H/boots.log | cut -d' ' -f3)\" = \"\$(stat -c %s $H/extracted/decrypt/GDCraze.x86_64)\" ] && [ ! -e $H/extracted/decrypt/padselect/bofselect.log ]"

echo "== sudo.log (what the machine's scripts asked for, as root)"
sort $H/sudo.log | uniq -c | sort -rn | head -12 | sed 's/^/   /'
if [ "$FAILS" = 0 ]; then echo "machine_sim: OK"; else echo "machine_sim: $FAILS FAILED"; fi
[ "$FAILS" = 0 ]
