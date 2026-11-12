#!/bin/bash
# select_sh_test.sh [QEMU ROOT] - select.sh: the images.conf lookups (device,
# ':<sub>' form, and v2 lines of every width - three, six and the seven-field
# form that carries a card's own confirm sound: the lookup reads $1 and must
# not care how many fields follow) with the host awk and, when QEMU/ROOT are
# given (or found), with the card's own busybox awk under qemu-arm-static;
# a conf carrying a group= line, whose lookups must be unchanged;
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

# GROUP LINES ARE INVISIBLE TO select.sh (item 106).  This is the whole reason
# a group names ordinary image= lines instead of adding a line kind of its own:
# the hook's awk counts image= lines to find index N, and the choice file the
# menu writes still holds an image index.  A conf carrying a group must give
# byte-identical lookups to the same conf without one - including the indexes
# AFTER the group line, which is where a parser that counted group= too would
# come apart.
gtmp=$(mktemp)
printf 'image=/dev/mmcblk0p3|STOCK|the primary\nimage=/dev/mmcblk0p3:img1|A|first\ngroup=2-4|JUKEBOX|a different set every power-up|art0.png|anim1.gif|\nimage=/dev/mmcblk0p3:img2|SET 1|x\nimage=/dev/mmcblk0p3:img3|SET 2|y\nimage=/dev/mmcblk0p3:img4|SET 3|z\ndefault=2\n' > "$gtmp"
glookups() {   # glookups LABEL
    check "$1" 0 /dev/mmcblk0p3 "$gtmp"
    check "$1" 1 /dev/mmcblk0p3 "$gtmp"
    check "$1" 2 /dev/mmcblk0p3 "$gtmp"
    check "$1" 4 /dev/mmcblk0p3 "$gtmp"
    check "$1" 5 "" "$gtmp"
    checksub "$1" 0 "" "$gtmp"
    checksub "$1" 1 img1 "$gtmp"
    checksub "$1" 2 img2 "$gtmp"
    checksub "$1" 3 img3 "$gtmp"
    checksub "$1" 4 img4 "$gtmp"
}
glookups "host group"

if command -v "$QEMU" >/dev/null 2>&1 && [ -x "$ROOT/bin/busybox.nosuid" ]; then
    export AWK="$QEMU -L $ROOT $ROOT/bin/busybox.nosuid awk"
    check busybox 0 /dev/mmcblk0p3
    check busybox 1 /dev/mmcblk0p7
    check busybox 2 ""
    lookups busybox
    glookups "busybox group"
    # PAD-226: the scores= lookup, as the card's own awk reads it (spaces around the fields)
    printf 'image=/dev/mmcblk0p3|A|a
scores=0|heisei
scores = 2 | orchestra 
' > "$tmp.s"
    [ "$(sh select.sh --scores 0 "$tmp.s")" = heisei ] || { echo "select_sh_test: FAIL (busybox) --scores 0"; exit 1; }
    [ "$(sh select.sh --scores 2 "$tmp.s")" = orchestra ] || { echo "select_sh_test: FAIL (busybox) --scores 2"; exit 1; }
    [ -z "$(sh select.sh --scores 1 "$tmp.s")" ] || { echo "select_sh_test: FAIL (busybox) --scores 1"; exit 1; }
    rm -f "$tmp.s"
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
# PAD-307: the apply step - records its arguments, leaves a copy at --to when
# FAKE_APPLY_RC is 0, says one [select] line and exits FAKE_APPLY_RC (1 = nothing to do)
case " $* " in
    *" --apply-color "*)
        echo "$*" > "$APPLYARGS"
        to=""
        while [ $# -gt 0 ]; do [ "$1" = "--to" ] && to=$2; shift; done
        rc=${FAKE_APPLY_RC:-1}
        [ "$rc" = 0 ] && echo copy > "$to"
        echo "[select] color: fake apply, exit $rc"
        exit "$rc" ;;
    # PAD-1194: the high-score hand-over - records its arguments, a save leaves a table at --to
    *" --scores-save "*)
        echo "$*" >> "$SCOREARGS"
        to=""
        while [ $# -gt 0 ]; do [ "$1" = "--to" ] && to=$2; shift; done
        echo table > "$to"
        echo "[select] scores: fake save"
        exit "${FAKE_SAVE_RC:-0}" ;;
    *" --scores-load "*)
        echo "$*" >> "$SCOREARGS"
        echo "[select] scores: fake load"
        exit "${FAKE_LOAD_RC:-0}" ;;
esac
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
# ---- PAD-226: an image with its own machine store (scores=<N>|<name>) ------------------------
# the games tree's game -> <title>/game names the title; the shared store is $NVD/<title>; the
# image's own is $NVO/<name>/<title>, seeded once from the shared one and bound over it
NVD="$W/nv"; NVO="$W/nvown"
export CODESELECT_NV="$NVD" CODESELECT_NV_OWN="$NVO"
rm -f "$G/game"; mkdir -p "$G/godzilla_pro"; ln -s godzilla_pro/game "$G/game"
mkdir -p "$NVD/godzilla_pro/NVM"; echo shared > "$NVD/godzilla_pro/NVM/00000001"
{ cat "$W/conf"; echo "scores=0|heisei"; echo "scores = 2 | orchestra "; } > "$W/conf_scores"
[ "$(sh select.sh --scores 0 "$W/conf_scores")" = heisei ] || { echo "select_sh_test: FAIL --scores 0"; exit 1; }
[ "$(sh select.sh --scores 2 "$W/conf_scores")" = orchestra ] || { echo "select_sh_test: FAIL --scores 2 (spaces)"; exit 1; }
[ -z "$(sh select.sh --scores 1 "$W/conf_scores")" ] || { echo "select_sh_test: FAIL --scores 1 is not shared"; exit 1; }
check "scores lines" 1 /dev/mmcblk0p7 "$W/conf_scores"
checksub "scores lines" 2 img2 "$W/conf_scores"
export CODESELECT_CONF="$W/conf_scores"
hook scores_first 0 0 "" "mount --bind $NVO/heisei/godzilla_pro $NVD/godzilla_pro"
grep -q "image 0: its own machine store $NVO/heisei/godzilla_pro, started from a copy of the shared one" "$W/out" \
    || { echo "select_sh_test: FAIL (scores_first) message"; cat "$W/out"; exit 1; }
[ "$(cat "$NVO/heisei/godzilla_pro/NVM/00000001")" = shared ] || { echo "select_sh_test: FAIL (scores_first) the seed is not the shared store"; exit 1; }
[ ! -e "$NVO/heisei/godzilla_pro.part" ] || { echo "select_sh_test: FAIL (scores_first) a .part was left"; exit 1; }
# the next boot binds the store it already has and never copies over it
echo "shared, later" > "$NVD/godzilla_pro/NVM/00000001"; echo own > "$NVO/heisei/godzilla_pro/NVM/00000002"
hook scores_again 0 0 "" "mount --bind $NVO/heisei/godzilla_pro $NVD/godzilla_pro"
[ "$(cat "$NVO/heisei/godzilla_pro/NVM/00000001")" = shared ] || { echo "select_sh_test: FAIL (scores_again) the store was copied over"; exit 1; }
grep -q "started from a copy" "$W/out" && { echo "select_sh_test: FAIL (scores_again) seeded twice"; cat "$W/out"; exit 1; }
# the selector fails and the primary boots: image 0's own store still applies
hook scores_selfail 1 2 "" "mount --bind $NVO/heisei/godzilla_pro $NVD/godzilla_pro"
# no shared store yet (a new machine): the image's own starts empty
rm -rf "$NVO" "$NVD"
hook scores_empty 0 0 "" "mount --bind $NVO/heisei/godzilla_pro $NVD/godzilla_pro"
grep -q "started empty" "$W/out" || { echo "select_sh_test: FAIL (scores_empty) message"; cat "$W/out"; exit 1; }
[ -d "$NVD/godzilla_pro" ] || { echo "select_sh_test: FAIL (scores_empty) no mountpoint made"; exit 1; }
# a name that walks out of the store dir is refused: the image shares, no bind
{ cat "$W/conf"; echo "scores=0|../etc"; } > "$W/conf_badname"
export CODESELECT_CONF="$W/conf_badname"
hook scores_badname 0 0 ""
grep -q "bad scores name '../etc': it shares the machine store" "$W/out" || { echo "select_sh_test: FAIL (scores_badname) message"; cat "$W/out"; exit 1; }
# a games tree whose game is not <title>/game: the image shares, no bind
export CODESELECT_CONF="$W/conf_scores"
rm -f "$G/game"; : > "$G/game"
hook scores_notitle 0 0 ""
grep -q "cannot tell its title" "$W/out" || { echo "select_sh_test: FAIL (scores_notitle) message"; cat "$W/out"; exit 1; }
rm -f "$G/game"; ln -s godzilla_pro/game "$G/game"
# ---- PAD-1194: high scores apart from settings (hiscores=<N>|<group>) ---------------------------
# the table of the store that booted LAST is saved to its group before the store is bound; the
# group's table is loaded into the bound store after; last.<title> says which store that was
HS="$W/nvhs"; SCOREARGS="$W/scoreargs"
export CODESELECT_NV_HS="$HS" SCOREARGS
{ cat "$W/conf"; echo "scores=0|heisei"; echo "hiscores = 0 | shared "; } > "$W/conf_hs_own"
{ cat "$W/conf"; echo "hiscores=0|shared"; } > "$W/conf_hs_base"
[ "$(sh select.sh --hiscores 0 "$W/conf_hs_own")" = shared ] || { echo "select_sh_test: FAIL --hiscores 0"; exit 1; }
[ -z "$(sh select.sh --hiscores 1 "$W/conf_hs_own")" ] || { echo "select_sh_test: FAIL --hiscores 1 has none"; exit 1; }
[ -z "$(sh select.sh --hiscores 0 "$W/conf_scores")" ] || { echo "select_sh_test: FAIL --hiscores read a scores= line"; exit 1; }
# 1. its own settings, the shared table, nothing booted before: no save, a load into its store
rm -rf "$HS"; : > "$SCOREARGS"
export CODESELECT_CONF="$W/conf_hs_own"
hook hs_first 0 0 "" "mount --bind $NVO/heisei/godzilla_pro $NVD/godzilla_pro"
[ "$(cat "$SCOREARGS")" = "--scores-load --from $HS/shared/godzilla_pro --store $NVD/godzilla_pro" ] \
    || { echo "select_sh_test: FAIL (hs_first) calls"; cat "$SCOREARGS"; cat "$W/out"; exit 1; }
[ "$(cat "$HS/last.godzilla_pro")" = "shared|$NVO/heisei/godzilla_pro" ] \
    || { echo "select_sh_test: FAIL (hs_first) last"; cat "$HS/last.godzilla_pro"; exit 1; }
grep -q "scores: fake load (group shared)" "$W/out" || { echo "select_sh_test: FAIL (hs_first) message"; cat "$W/out"; exit 1; }
# 2. the shared settings, the same table: the last store's table is saved first, then loaded here
: > "$SCOREARGS"
export CODESELECT_CONF="$W/conf_hs_base"
hook hs_next 0 0 ""
[ "$(cat "$SCOREARGS")" = "--scores-save --store $NVO/heisei/godzilla_pro --to $HS/shared/godzilla_pro
--scores-load --from $HS/shared/godzilla_pro --store $NVD/godzilla_pro" ] \
    || { echo "select_sh_test: FAIL (hs_next) calls"; cat "$SCOREARGS"; cat "$W/out"; exit 1; }
[ "$(cat "$HS/last.godzilla_pro")" = "shared|$NVD/godzilla_pro" ] || { echo "select_sh_test: FAIL (hs_next) last"; exit 1; }
[ ! -e "$HS/last.godzilla_pro.part" ] || { echo "select_sh_test: FAIL (hs_next) a .part was left"; exit 1; }
# 3. a load the selector refuses (another game version): said, and the boot goes on
: > "$SCOREARGS"
FAKE_LOAD_RC=2 hook hs_refused 0 0 ""
grep -q "the shared high scores could not be loaded (exit 2)" "$W/out" || { echo "select_sh_test: FAIL (hs_refused) message"; cat "$W/out"; exit 1; }
# 4. a card that splits nothing for the image: the last table is still saved, then forgotten
: > "$SCOREARGS"
export CODESELECT_CONF="$W/conf"
hook hs_none 0 0 ""
[ "$(cat "$SCOREARGS")" = "--scores-save --store $NVD/godzilla_pro --to $HS/shared/godzilla_pro" ] \
    || { echo "select_sh_test: FAIL (hs_none) calls"; cat "$SCOREARGS"; exit 1; }
[ ! -e "$HS/last.godzilla_pro" ] || { echo "select_sh_test: FAIL (hs_none) last was kept"; exit 1; }
# 5. a last file that names a store outside the title's: nothing saved from it
echo "shared|/etc" > "$HS/last.godzilla_pro"; : > "$SCOREARGS"
export CODESELECT_CONF="$W/conf_hs_base"
hook hs_badlast 0 0 ""
grep -q "names no store of godzilla_pro ('/etc'): nothing saved" "$W/out" || { echo "select_sh_test: FAIL (hs_badlast) message"; cat "$W/out"; exit 1; }
grep -q -- "--scores-save" "$SCOREARGS" && { echo "select_sh_test: FAIL (hs_badlast) saved from /etc"; exit 1; }
# 6. a bad group name: no load, the table it has
{ cat "$W/conf"; echo "hiscores=0|../x"; } > "$W/conf_hs_bad"; : > "$SCOREARGS"
export CODESELECT_CONF="$W/conf_hs_bad"
hook hs_badgroup 0 0 ""
grep -q "bad hiscores group '../x'" "$W/out" || { echo "select_sh_test: FAIL (hs_badgroup) message"; cat "$W/out"; exit 1; }
grep -q -- "--scores-load" "$SCOREARGS" && { echo "select_sh_test: FAIL (hs_badgroup) loaded"; exit 1; }
unset CODESELECT_NV_HS
rm -rf "$HS"
rm -f "$G/game"; : > "$G/game"
export CODESELECT_CONF="$W/conf"
unset CODESELECT_NV CODESELECT_NV_OWN
rm -rf "$G/godzilla_pro" "$NVD" "$NVO"
# ---- PAD-226: each image's own custom modes ($DIR/modes/img<N>, else $DIR/modes/none) -------
PM="$W/padmode"
mkdir -p "$W/modes/img2" "$W/modes/none" "$PM"
: > "$W/modes/img2/mode.so"
export CODESELECT_PADMODE="$PM"
# image 2 carries its own set: it is bound over the rootfs's
hook modes_own 2 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $M" "mount --bind $M/img2 $G" \
    "mount --bind $W/modes/img2 $PM"
grep -q "image 2: $W/modes/img2 bound over $PM (its own custom modes)" "$W/out" || { echo "select_sh_test: FAIL (modes_own) message"; cat "$W/out"; exit 1; }
# image 1 carries none: the empty set, so the primary's modes never run under it
hook modes_none 1 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $G" "mount --bind $W/modes/none $PM"
grep -q "(no custom modes)" "$W/out" || { echo "select_sh_test: FAIL (modes_none) message"; cat "$W/out"; exit 1; }
# image 0 keeps the set its own card put on the rootfs
hook modes_primary 0 0 ""
# no mountpoint on the rootfs: nothing is bound, and the log says so
rmdir "$PM"
hook modes_nomount 1 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $G"
grep -q "no $PM: the rootfs's modes stay as they are" "$W/out" || { echo "select_sh_test: FAIL (modes_nomount) message"; cat "$W/out"; exit 1; }
# a card built before per-image modes (no $DIR/modes): exactly the mounts it always made
rm -rf "$W/modes"; mkdir -p "$PM"
hook modes_oldcard 1 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $G"
unset CODESELECT_PADMODE
rm -rf "$PM"
# ---- PAD-307: the color correction set on this machine ------------------------------------------
# a values file and a color_profile= line: the selector writes a copy of <title>/game into the
# colour dir and the copy is bound over the program; everything else leaves the program alone
CV="$W/padcolor"; CF="$W/codeselect.color"
export CODESELECT_COLOR="$CF" CODESELECT_COLOR_DIR="$CV" APPLYARGS="$W/applyargs"
rm -f "$G/game"; mkdir -p "$G/godzilla_pro"; : > "$G/godzilla_pro/game"; ln -s godzilla_pro/game "$G/game"
{ cat "$W/conf"; echo "color_profile=0|1.10 1.20 1.35|1 1 1|0 0 0|0.90|Recommended"; } > "$W/conf_color"
export CODESELECT_CONF="$W/conf_color"
rm -f "$CF" "$APPLYARGS"
hook color_nofile 0 0 ""
[ ! -e "$APPLYARGS" ] || { echo "select_sh_test: FAIL (color_nofile) the selector was asked with no values file"; exit 1; }
echo "/dev/mmcblk0p3|1.30 1.20 1.35|1 1 1|0 0 0|0.90" > "$CF"
FAKE_APPLY_RC=0 hook color_apply 0 0 "" "mount --bind $CV/godzilla_pro.game $G/godzilla_pro/game"
[ "$(cat "$APPLYARGS")" = "--apply-color --conf $W/conf_color --image 0 --program $G/godzilla_pro/game --to $CV/godzilla_pro.game --color-file $CF" ] \
    || { echo "select_sh_test: FAIL (color_apply) the selector was asked:"; cat "$APPLYARGS"; exit 1; }
grep -q "image 0: color: fake apply, exit 0" "$W/out" || { echo "select_sh_test: FAIL (color_apply) the selector's line is not in the log"; cat "$W/out"; exit 1; }
grep -q "image 0: $CV/godzilla_pro.game bound over $G/godzilla_pro/game" "$W/out" || { echo "select_sh_test: FAIL (color_apply) message"; cat "$W/out"; exit 1; }
# the same after a choice of another image: the step follows the image that boots
FAKE_APPLY_RC=0 hook color_image2 2 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $M" "mount --bind $M/img2 $G"
grep -q "cannot tell its title" "$W/out" || { echo "select_sh_test: FAIL (color_image2) the fake tree has no title and must say so"; cat "$W/out"; exit 1; }
rm -f "$G/game"; ln -s godzilla_pro/game "$G/game"
# nothing to do (exit 1): no bind, nothing left behind
FAKE_APPLY_RC=1 hook color_nothing 0 0 ""
[ ! -e "$CV/godzilla_pro.game" ] || { echo "select_sh_test: FAIL (color_nothing) a copy was left"; exit 1; }
grep -q "could not be applied" "$W/out" && { echo "select_sh_test: FAIL (color_nothing) nothing to do is not a failure"; cat "$W/out"; exit 1; }
# refused (exit 2): no bind, as built, and the log says so
FAKE_APPLY_RC=2 hook color_refused 0 0 ""
grep -q "could not be applied (exit 2): its colors are as built" "$W/out" || { echo "select_sh_test: FAIL (color_refused) message"; cat "$W/out"; exit 1; }
# the bind fails: the copy is taken away again
FAKE_APPLY_RC=0 hook color_bindfail 0 0 "$CV/godzilla_pro.game" "mount --bind $CV/godzilla_pro.game $G/godzilla_pro/game"
grep -q "binding $CV/godzilla_pro.game over $G/godzilla_pro/game failed: its colors are as built" "$W/out" \
    || { echo "select_sh_test: FAIL (color_bindfail) message"; cat "$W/out"; exit 1; }
[ ! -e "$CV/godzilla_pro.game" ] || { echo "select_sh_test: FAIL (color_bindfail) the copy was left"; exit 1; }
# a conf with no color_profile= line: the selector is never asked, values file or not
rm -f "$APPLYARGS"
export CODESELECT_CONF="$W/conf"
FAKE_APPLY_RC=0 hook color_noline 0 0 ""
[ ! -e "$APPLYARGS" ] || { echo "select_sh_test: FAIL (color_noline) the selector was asked"; exit 1; }
unset CODESELECT_COLOR CODESELECT_COLOR_DIR
rm -rf "$G/godzilla_pro" "$CV" "$CF"; rm -f "$G/game"
# ---- deltas (item 107): a tree carrying .multiboot/deltas runs materialize.py --------------
# the fake mount grows the index under img2 when FAKE_DELTAS is set; the fake python records
# its command line; no --mount-dev when CODESELECT_WORKDEV is empty (a plain work directory)
cat > "$W/fakepy" <<'EOF'
#!/bin/sh
echo "$*" > "$PYARGS"
echo "materialize: fake ran"
exit 0
EOF
chmod 755 "$W/fakepy"
cp materialize.py "$W/materialize.py"
export PYARGS="$W/pyargs"
sed -i 's|^: > "$mp/game".*|&; if [ -n "$FAKE_DELTAS" ]; then mkdir -p "$mp/img2/.multiboot"; : > "$mp/img2/.multiboot/deltas"; fi|' "$W/fakemount"
: > "$PYARGS"
FAKE_DELTAS=1 CODESELECT_PYTHON="$W/fakepy" CODESELECT_WORKDEV= CODESELECT_WORKMNT="$W/work" \
hook deltas 2 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $M" "mount --bind $M/img2 $G"
grep -q "image 2: stores deltas: rebuilding them" "$W/out" || { echo "select_sh_test: FAIL (deltas) message"; cat "$W/out"; exit 1; }
grep -q "materialize: fake ran" "$W/out" || { echo "select_sh_test: FAIL (deltas) materialize.py was not run"; cat "$W/out"; exit 1; }
case " $(cat "$PYARGS") " in
    *" $W/materialize.py --store $M --tree img2 --games $G --work $W/work "*) ;;
    *) echo "select_sh_test: FAIL (deltas) materialize.py arguments:"; cat "$PYARGS"; exit 1 ;;
esac
case " $(cat "$PYARGS") " in *" --mount-dev "*) echo "select_sh_test: FAIL (deltas) --mount-dev with an empty CODESELECT_WORKDEV"; cat "$PYARGS"; exit 1 ;; esac
[ -d "$W/work" ] || { echo "select_sh_test: FAIL (deltas) the work mountpoint was not created"; exit 1; }
# the default work device reaches the script as --mount-dev
: > "$PYARGS"
FAKE_DELTAS=1 CODESELECT_PYTHON="$W/fakepy" CODESELECT_WORKMNT="$W/work" \
hook deltasdev 2 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $M" "mount --bind $M/img2 $G"
case " $(cat "$PYARGS") " in *" --mount-dev /dev/mmcblk0p7 "*) ;; *) echo "select_sh_test: FAIL (deltasdev) no --mount-dev /dev/mmcblk0p7:"; cat "$PYARGS"; exit 1 ;; esac
# no python on the card: the bind stands, the base's files play, and the log says why
FAKE_DELTAS=1 CODESELECT_PYTHON="$W/nosuchpython" \
hook deltasnopy 2 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $M" "mount --bind $M/img2 $G"
grep -q "there is no $W/nosuchpython: the game plays the base's files" "$W/out" || { echo "select_sh_test: FAIL (deltasnopy) message"; cat "$W/out"; exit 1; }
# a tree without the index runs nothing (the same mounts, no python line)
: > "$PYARGS"
CODESELECT_PYTHON="$W/fakepy" \
hook nodeltas 2 0 "" "umount $G" "mount -t ext4 -o ro,relatime,exec /dev/mmcblk0p7 $M" "mount --bind $M/img2 $G"
[ -z "$(cat "$PYARGS")" ] || { echo "select_sh_test: FAIL (nodeltas) materialize.py ran with no index"; exit 1; }
# and the real script, under this host's python, against a real tiny store: the
# fake mount's tree gets a base blob, a delta of it and an index, and the work
# file comes out as the variant with a stamp beside it
PYREAL=$(command -v python3 || command -v python)
if [ -n "$PYREAL" ]; then
    rm -rf "$W/work" "$W/multi"
    cat > "$W/mkstore.py" <<'EOF'
import hashlib, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[1])))
import materialize as mz
root, sub = sys.argv[2], "img2"
base = bytes(bytearray(range(256))) * 200
var = bytearray(base); var[1000:1010] = b"0123456789"; var = bytes(var)
os.makedirs(os.path.join(root, ".blobs")); os.makedirs(os.path.join(root, sub, ".multiboot")); os.makedirs(os.path.join(root, sub, "t"))
key = hashlib.sha256(base).hexdigest() + ".0644.0.0"
open(os.path.join(root, ".blobs", key), "wb").write(base)
open(os.path.join(root, sub, "t", "image.bin"), "wb").write(base)
open(os.path.join(root, sub, "game"), "wb").write(b"")
sha = hashlib.sha256(var).hexdigest(); name = sha + ".0644.0.0.delta"
def ch(b):
    for i in range(0, len(b), 4096): yield b[i:i + 4096]
ranges = mz.find_delta(ch(base), ch(var), len(base))
with open(os.path.join(root, ".blobs", name), "wb") as f: mz.write_delta(f, key, sha, len(base), ranges, ch(var))
mz.write_index(os.path.join(root, sub, ".multiboot", "deltas"), [("t/image.bin", key, name, len(base))])
open(os.path.join(root, "want"), "wb").write(var)
EOF
    "$PYREAL" "$W/mkstore.py" "$W/materialize.py" "$W/multi"
    # the fake mount would wipe the tree: run the function's own command line instead
    CODESELECT_DIR="$W" "$PYREAL" "$W/materialize.py" --store "$W/multi" --tree img2 --games "$G" --work "$W/work" --no-bind --verify > "$W/out" 2>&1 \
        || { echo "select_sh_test: FAIL (real) materialize.py exited non-zero"; cat "$W/out"; exit 1; }
    cmp -s "$W/work/t/image.bin" "$W/multi/want" || { echo "select_sh_test: FAIL (real) the work file is not the variant"; cat "$W/out"; exit 1; }
    grep -q "^base " "$W/work/t/image.bin.stamp" || { echo "select_sh_test: FAIL (real) no stamp"; ls -l "$W/work/t"; exit 1; }
    grep -q "1 of 1 delta file(s) in place" "$W/out" || { echo "select_sh_test: FAIL (real) message"; cat "$W/out"; exit 1; }
    real="materialize.py for real under $PYREAL"
else
    real="no python on this host: materialize.py's own run skipped"
fi
rm -rf "$W"
echo "select_sh_test: OK ($awks; the hook against fake mounts: 26 cases; $real)"
