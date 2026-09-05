#!/bin/bash
# select_sh_test.sh [QEMU ROOT] - select.sh: the images.conf lookups (device,
# ':<sub>' form, and v2 lines of every width - three, six and the seven-field
# form that carries a card's own confirm sound: the lookup reads $1 and must
# not care how many fields follow) with the host awk and, when QEMU/ROOT are
# given (or found), with the card's own busybox awk under qemu-arm-static;
# then the whole hook against a fake selector and fake mount/umount: index 0
# touches nothing, a plain device is remounted, a '<dev>:<sub>' device is
# mounted under the multi dir and bind-mounted, and every failure puts the
# primary back.
# QEMU is taken from the environment when not given (the Makefile exports it;
# an argv naming qemu is what a rig teardown's pkill matches).
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
QEMU=${1:-${QEMU:-qemu-arm-static}}
ROOT=${2:-/home/david/spike2root}
cd "$HERE"

check() {   # check LABEL IDX EXPECTED [CONF]
    local got
    got=$(sh select.sh --lookup "$2" "${4:-images.conf.example}")
    [ "$got" = "$3" ] || { echo "select_sh_test: FAIL ($1) index $2 -> '$got', expected '$3'"; exit 1; }
}
checksub() {   # checksub LABEL IDX EXPECTED CONF
    local got
    got=$(sh select.sh --lookup-sub "$2" "$4")
    [ "$got" = "$3" ] || { echo "select_sh_test: FAIL ($1) sub of index $2 -> '$got', expected '$3'"; exit 1; }
}

sh -n select.sh
bash -n select.sh
check host 0 /dev/mmcblk0p3
check host 1 /dev/mmcblk0p7
check host 2 ""
# a conf with spaces, a comment, a title containing '=', v2 media fields (six
# fields, and the seven-field form with a per-card confirm sound - on a plain
# device and on a ':<sub>' one) and the ':<sub>' device form
tmp=$(mktemp)
printf '# x\n  image = /dev/mmcblk0p3 | STOCK | a=b \nimage=/dev/mmcblk0p7|X|y|art1.png|anim1.gif|music1.wav\nimage=/dev/mmcblk0p7:img2|Z|z|a.png||\nimage=/dev/mmcblk0p7|W|w|art3.png|anim3.gif|music3.wav|confirm3.wav\nimage=/dev/mmcblk0p7:img4|V|v|art4.png|||confirm4.wav\nsound_move=move.wav\ndefault=1\n' > "$tmp"
lookups() {   # lookups LABEL
    check "$1" 0 /dev/mmcblk0p3 "$tmp"
    check "$1" 1 /dev/mmcblk0p7 "$tmp"
    check "$1" 2 /dev/mmcblk0p7 "$tmp"
    check "$1" 3 /dev/mmcblk0p7 "$tmp"
    check "$1" 4 /dev/mmcblk0p7 "$tmp"
    check "$1" 5 "" "$tmp"
    checksub "$1" 1 "" "$tmp"
    checksub "$1" 2 img2 "$tmp"
    checksub "$1" 3 "" "$tmp"
    checksub "$1" 4 img4 "$tmp"
}
lookups host

if command -v "$QEMU" >/dev/null 2>&1 && [ -x "$ROOT/bin/busybox.nosuid" ]; then
    export AWK="$QEMU -L $ROOT $ROOT/bin/busybox.nosuid awk"
    check busybox 0 /dev/mmcblk0p3
    check busybox 1 /dev/mmcblk0p7
    check busybox 2 ""
    lookups busybox
    unset AWK
    awks="host awk and the card's busybox awk under qemu"
else
    awks="host awk only"
fi
rm -f "$tmp"

# ---- the hook itself, with fakes -------------------------------------------
W=$(mktemp -d)
mkdir -p "$W/games" "$W/log"
cat > "$W/conf" <<'EOF'
image=/dev/mmcblk0p3|STOCK|s
image=/dev/mmcblk0p7|EXTRA|e
image=/dev/mmcblk0p7:img2|MULTI 2|m
image=/dev/mmcblk0p7:img9|MULTI 9|missing tree
image=/dev/mmcblk0p7:../etc|BAD SUB|x
EOF
# the fake selector writes the index the test asks for and exits as asked; it
# records its own command line so the log switch can be checked
cat > "$W/fakesel" <<'EOF'
#!/bin/sh
echo "$*" > "$SELARGS"
out=""
while [ $# -gt 0 ]; do [ "$1" = "--out" ] && out=$2; shift; done
[ -n "$FAKE_IDX" ] && echo "$FAKE_IDX" > "$out"
exit "${FAKE_RC:-0}"
EOF
# fake mount: logs its arguments; fails when FAKE_FAIL names one of them; a
# device mount grows a games tree (game, img1/game, img2/game); a bind copies
# the source tree's game marker
cat > "$W/fakemount" <<'EOF'
#!/bin/sh
echo "mount $*" >> "$FAKELOG"
if [ -n "$FAKE_FAIL" ]; then for a in "$@"; do [ "$a" = "$FAKE_FAIL" ] && exit 1; done; fi
if [ "$1" = "--bind" ]; then [ -e "$2/game" ] && : > "$3/game"; exit 0; fi
mp=$6
mkdir -p "$mp/img1" "$mp/img2"
: > "$mp/game"; : > "$mp/img1/game"; : > "$mp/img2/game"
exit 0
EOF
cat > "$W/fakeumount" <<'EOF'
#!/bin/sh
echo "umount $*" >> "$FAKELOG"
[ "$FAKE_FAIL" = "umount" ] && exit 1
rm -f "$1/game"
exit 0
EOF
chmod 755 "$W/fakesel" "$W/fakemount" "$W/fakeumount"
export FAKELOG="$W/calls" SELARGS="$W/selargs"
export CODESELECT_DIR="$W" CODESELECT_CONF="$W/conf" CODESELECT_BIN="$W/fakesel" \
       CODESELECT_OUT="$W/choice" CODESELECT_GAMES="$W/games" \
       CODESELECT_MULTI="$W/multi" CODESELECT_MULTI_FALLBACK="$W/multi2" \
       CODESELECT_MOUNT="$W/fakemount" CODESELECT_UMOUNT="$W/fakeumount" CODESELECT_NO_BLKCHECK=1

hook() {   # hook LABEL IDX RC FAIL EXPECTED-CALLS...
    local label=$1 idx=$2 rc=$3 fail=$4; shift 4
    : > "$FAKELOG"
    : > "$W/games/game"
    rm -rf "$W/multi" "$W/multi2"
    FAKE_IDX=$idx FAKE_RC=$rc FAKE_FAIL=$fail sh select.sh > "$W/out" 2>&1 || {
        echo "select_sh_test: FAIL ($label) select.sh exited non-zero"; cat "$W/out"; exit 1; }
    local want="" line
    for line in "$@"; do want="$want$line
"; done
    if [ "$(cat "$FAKELOG")" != "$(printf '%s' "$want")" ]; then
        echo "select_sh_test: FAIL ($label) mount calls were:"; cat "$FAKELOG"
        echo "--- expected:"; printf '%s' "$want"; cat "$W/out"; exit 1
    fi
}
G="$W/games"; M="$W/multi"
# index 0: nothing is touched
hook primary 0 0 ""
grep -q "image 0 is the primary" "$W/out" || { echo "select_sh_test: FAIL (primary) message"; cat "$W/out"; exit 1; }
# THE CARD LOG IS OFF BY DEFAULT: no --log for the selector, nothing under the log dir
case " $(cat "$SELARGS") " in *" --log "*) echo "select_sh_test: FAIL the selector got --log with no log= in the conf"; cat "$SELARGS"; exit 1 ;; esac
[ -z "$(ls -A "$W/log")" ] || { echo "select_sh_test: FAIL the hook wrote under the log dir with the log off"; ls -l "$W/log"; exit 1; }
# a log= line in the conf (mkmulticard --debug-log) turns it on: the selector gets
# --log <path> and the hook's own lines land in that file
{ cat "$W/conf"; echo "log=$W/log/codeselect.log"; } > "$W/conf_log"
export CODESELECT_CONF="$W/conf_log"
hook logged 0 0 ""
case " $(cat "$SELARGS") " in *" --log $W/log/codeselect.log "*) ;; *) echo "select_sh_test: FAIL log= in the conf did not reach the selector"; cat "$SELARGS"; exit 1 ;; esac
grep -q "select.sh: image 0 is the primary" "$W/log/codeselect.log" || { echo "select_sh_test: FAIL the hook's line is not in the card log"; ls -l "$W/log"; exit 1; }
# CODESELECT_LOG= (empty) forces it off even then; CODESELECT_LOG=<path> forces it on without the line
export CODESELECT_LOG=
hook forced_off 0 0 ""
case " $(cat "$SELARGS") " in *" --log "*) echo "select_sh_test: FAIL CODESELECT_LOG= did not turn the log off"; cat "$SELARGS"; exit 1 ;; esac
export CODESELECT_CONF="$W/conf" CODESELECT_LOG="$W/log/forced.log"
hook forced_on 0 0 ""
case " $(cat "$SELARGS") " in *" --log $W/log/forced.log "*) ;; *) echo "select_sh_test: FAIL CODESELECT_LOG=<path> did not turn the log on"; cat "$SELARGS"; exit 1 ;; esac
grep -q "select.sh: image 0 is the primary" "$W/log/forced.log" || { echo "select_sh_test: FAIL the forced log holds no hook line"; exit 1; }
unset CODESELECT_LOG
rm -f "$W/log/codeselect.log" "$W/log/forced.log"
# a plain device: umount + mount
hook plain 1 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $G"
grep -q "image 1: mounted /dev/mmcblk0p7 at $G" "$W/out" || { echo "select_sh_test: FAIL (plain) message"; cat "$W/out"; exit 1; }
# the multi form: umount, mount the partition under the multi dir, bind the subtree
hook multi 2 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $M" "mount --bind $M/img2 $G"
grep -q "image 2: mounted /dev/mmcblk0p7 at $M, img2 bound over $G" "$W/out" || { echo "select_sh_test: FAIL (multi) message"; cat "$W/out"; exit 1; }
[ -e "$G/game" ] || { echo "select_sh_test: FAIL (multi) no game after the bind"; exit 1; }
# a subtree that is not there: everything is undone and the primary comes back
hook missing 3 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $M" \
    "umount $G" "umount $M" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p3 $G"
grep -q "primary remounted" "$W/out" || { echo "select_sh_test: FAIL (missing) message"; cat "$W/out"; exit 1; }
# a subdirectory that walks out of the tree is refused before any mount
hook badsub 4 0 ""
grep -q "bad subdirectory" "$W/out" || { echo "select_sh_test: FAIL (badsub) message"; cat "$W/out"; exit 1; }
# the device mount fails: the primary comes back
hook mountfail 1 0 /dev/mmcblk0p7 "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $G" \
    "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p3 $G"
# the multi partition mount fails: the primary comes back, nothing else is touched
hook multifail 2 0 /dev/mmcblk0p7 "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $M" \
    "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p3 $G"
# umount busy: nothing else happens (the primary is still mounted)
hook busy 1 0 umount "umount $G"
grep -q "still mounted" "$W/out" || { echo "select_sh_test: FAIL (busy) message"; cat "$W/out"; exit 1; }
# the selector fails: no mount call at all
hook selfail 1 2 ""
grep -q "selector exit 2" "$W/out" || { echo "select_sh_test: FAIL (selfail) message"; cat "$W/out"; exit 1; }
# an index past the conf
hook nodev 7 0 ""
grep -q "has no device" "$W/out" || { echo "select_sh_test: FAIL (nodev) message"; cat "$W/out"; exit 1; }
# the multi dir cannot be created (its parent is a file, as a read-only
# rootfs would refuse it): the fallback dir is used
: > "$W/blocked"
CODESELECT_MULTI="$W/blocked/multi" \
hook fallback 2 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $W/multi2" "mount --bind $W/multi2/img2 $G"
grep -q "using $W/multi2" "$W/out" || { echo "select_sh_test: FAIL (fallback) message"; cat "$W/out"; exit 1; }
rm -rf "$W"
echo "select_sh_test: OK ($awks; the hook against fake mounts: 11 cases)"
