#!/bin/bash
# padselect_sh_test.sh - the JJP hook (padselect.sh) against a fake selector,
# fake mount/umount/chown and plain directories standing in for the card's
# partitions, under dash (the shell rungame.sh is written for) when the host
# has it, and sh.
#
#   lookups     rootA / rootB / rootB:<sub> tokens out of a v2 conf
#   single      one image: no selector, no mask, nothing written
#   primary     index 0: nothing mounted; the updater IS masked; one log line
#   rootB       index 1: root B mounted by the card's own UUID, the game dir
#               bound, vf linked, chown'd, one log line naming it all
#   premounted  the rig's case: root B already there -> the bind only
#   sub         rootB:img2 -> the subdirectory's tree
#   selfail     selector exit 2: nothing mounted, the mask stays
#   nogame      a root B with no game: mount undone, image 0
#   bindfail    the bind fails: the mount is undone
#   badsub      a subdirectory that walks out of the tree is refused unmounted
#   nouuid      no fs_uuids.sh -> image 0
#   noblk       the UUID names no block device -> image 0
#   allow       jjp_update=allow leaves the updater alone
#   selog       the selector gets --log only with log= in the conf, or the override
#   rotate      the hook's log is rotated once past the cap
#   nobin       no selector binary -> image 0, one line
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
cd "$HERE"
SHELLS="sh"
command -v dash >/dev/null 2>&1 && SHELLS="dash sh"

for SH in $SHELLS; do
echo "padselect_sh_test: under $SH"
$SH -n padselect.sh
W=$(mktemp -d)
G=$W/gen1; T=$W/temp; P=$W/perm; M=$W/multi; R=$W/run; U=$W/byuuid
mkdir -p "$G/GunsNRoses" "$G/scripts" "$G/padselect" "$T" "$P" "$R" "$U"
echo 'export GAMENAME=GunsNRoses' > "$G/setenv.sh"
: > "$G/GunsNRoses/game"
printf '#!/bin/dash\nFS_UUID_ROOTB=e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87\n' > "$G/scripts/fs_uuids.sh"
printf '#!/bin/dash\necho real updater\n' > "$G/scripts/updater.sh"
: > "$U/e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87"
cat > "$G/padselect/images.conf" <<'EOF'
# two images, the GNR pair
image=rootA|GUNS N' ROSES 3.03|Stock JJP code|art0.png||
image=rootB|CHAKA'S LOTLJ|Land of the Lost Jungle retheme|art1.png|anim1.gif|
image=rootB:img2|THIRD|a tree beside the second install
image=rootB:../etc|BAD|walks out
image=sdcard|ODD|an unknown token
default=0
timeout=15
EOF
# the fake selector: writes the index asked for, exits as asked, records argv
cat > "$W/fakesel" <<'EOF'
#!/bin/sh
echo "$*" > "$SELARGS"
echo "${PULSE_SINK:-}" > "$SELARGS.env"
out=""
while [ $# -gt 0 ]; do [ "$1" = "--out" ] && out=$2; shift; done
[ -n "$FAKE_IDX" ] && echo "$FAKE_IDX" > "$out"
exit "${FAKE_RC:-0}"
EOF
# fake pactl: the GNR's two sinks as `pactl list short sinks` prints them - the
# headphone kit's USB codec first (the server's default) and the onboard pci one
cat > "$W/fakepactl" <<'EOF'
#!/bin/sh
[ "$1 $2 $3" = "list short sinks" ] || exit 1
printf '0\talsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 48000Hz\tSUSPENDED\n'
printf '1\talsa_output.pci-0000_00_1f.3.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 48000Hz\tSUSPENDED\n'
printf '2\talsa_output.pci-0000_00_1f.3.hdmi-stereo\tmodule-alsa-card.c\ts16le 2ch 48000Hz\tSUSPENDED\n'
EOF
# fake mount: logs its arguments; fails when FAKE_FAIL names one of them.
# A device mount grows root B's trees (jjpe/gen1/GunsNRoses/game, img2/...)
# unless FAKE_EMPTY; a bind leaves a marker naming its source in the target.
cat > "$W/fakemount" <<'EOF'
#!/bin/sh
echo "mount $*" >> "$FAKELOG"
if [ -n "$FAKE_FAIL" ]; then for a in "$@"; do [ "$a" = "$FAKE_FAIL" ] && exit 1; done; fi
if [ "$1" = "--bind" ]; then [ -d "$3" ] && echo "$2" > "$3/.bound_from"; exit 0; fi
mp=$4
if [ -z "$FAKE_EMPTY" ]; then
    mkdir -p "$mp/jjpe/gen1/GunsNRoses" "$mp/img2/GunsNRoses"
    : > "$mp/jjpe/gen1/GunsNRoses/game"; : > "$mp/img2/GunsNRoses/game"
else
    mkdir -p "$mp/jjpe/gen1"
fi
exit 0
EOF
cat > "$W/fakeumount" <<'EOF'
#!/bin/sh
echo "umount $*" >> "$FAKELOG"
rm -f "$1/.bound_from"
[ -d "$1/jjpe" ] && rm -rf "$1/jjpe" "$1/img2"
exit 0
EOF
cat > "$W/fakechown" <<'EOF'
#!/bin/sh
echo "chown $*" >> "$FAKELOG"
exit 0
EOF
chmod 755 "$W/fakesel" "$W/fakepactl" "$W/fakemount" "$W/fakeumount" "$W/fakechown"
export FAKELOG="$W/calls" SELARGS="$W/selargs"
export JJPEDIR="$G" GAMENAME= GAMEDIR=
export PADSELECT_TEMP="$T" PADSELECT_PERM="$P" PADSELECT_MULTI="$M" PADSELECT_RUNDIR="$R" \
       PADSELECT_BYUUID="$U" PADSELECT_BIN="$W/fakesel" PADSELECT_MOUNT="$W/fakemount" \
       PADSELECT_UMOUNT="$W/fakeumount" PADSELECT_CHOWN="$W/fakechown"
unset PADSELECT_CONF PADSELECT_UUIDS PADSELECT_UPDATER PADSELECT_SELECT_LOG PADSELECT_NO_BLKCHECK
unset PULSE_SINK
# a pactl that fails (no server on the test host) is asked once, not for 10 s a case
export PADSELECT_PACTL="$W/failpactl" PADSELECT_PACTL_TRIES=1
printf '#!/bin/sh\nexit 1\n' > "$W/failpactl"; chmod 755 "$W/failpactl"

fail() { echo "padselect_sh_test: FAIL ($1)"; shift; for x in "$@"; do echo "  $x"; done; [ -f "$W/out" ] && cat "$W/out"; [ -f "$FAKELOG" ] && { echo "--- calls:"; cat "$FAKELOG"; }; exit 1; }
hook() {   # hook LABEL IDX RC FAIL EXPECTED-CALLS...   (the calls log must match exactly)
    local label=$1 idx=$2 rc=$3 fail=$4; shift 4
    : > "$FAKELOG"; : > "$SELARGS"
    rm -rf "$M" "$R" "$G/GunsNRoses/.bound_from" "$G/GunsNRoses/vf"; mkdir -p "$R"
    FAKE_IDX=$idx FAKE_RC=$rc FAKE_FAIL=$fail $SH padselect.sh > "$W/out" 2>&1 || fail "$label" "padselect.sh exited non-zero"
    local want="" line
    for line in "$@"; do want="$want$line
"; done
    if [ "$(cat "$FAKELOG")" != "$(printf '%s' "$want")" ]; then
        fail "$label" "calls differ; expected:" "$want"
    fi
}
MASK="mount --bind $R/updater.sh $G/scripts/updater.sh"
ROOTB="mount -o rw,noatime,discard $U/e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87 $M"

# --- lookups
for pair in "0 rootA" "1 rootB" "2 rootB:img2" "3 rootB:../etc" "4 sdcard" "5 "; do
    i=${pair%% *}; want=${pair#* }
    got=$($SH padselect.sh --lookup "$i" "$G/padselect/images.conf")
    [ "$got" = "$want" ] || fail lookup "index $i -> '$got', expected '$want'"
done

# --- single image: the hook is silent and touches nothing
mv "$G/padselect/images.conf" "$W/conf.multi"
printf 'image=rootA|ONLY|one\n' > "$G/padselect/images.conf"
hook single 0 0 ""
[ -s "$SELARGS" ] && fail single "the selector ran with one image"
[ -f "$T/padselect.log" ] && fail single "a log line with one image"
mv "$W/conf.multi" "$G/padselect/images.conf"

# --- index 0: the mask, nothing else
hook primary 0 0 "" "$MASK"
grep -q "image 0 chosen: the primary" "$W/out" || fail primary "message"
grep -q "updater masked (5 images, jjp_update=refuse)" "$T/padselect.log" || fail primary "no mask line in the hook log"
grep -q "image 0 chosen" "$T/padselect.log" || fail primary "no choice line in the hook log"
grep -q "update refused: multi-boot install" "$R/updater.sh" || fail primary "the mask script"
[ -x "$R/updater.sh" ] || fail primary "the mask is not executable"
# the mask writes what the game's update screen reads, and exits 1
if $SH "$R/updater.sh" 2>/dev/null; then fail primary "the mask exited 0"; fi
grep -q "update refused" "$T/rprogress" && grep -q "update refused" "$T/pcprogress" || fail primary "rprogress/pcprogress"
argv=$(cat "$SELARGS")
want="--conf $G/padselect/images.conf --input jjpio --learn --out $T/padselect.choice --last $P/padselect.last"
case "$argv" in *"$want"*) ;; *) fail primary "selector argv: $argv" "expected: $want" ;; esac
case " $argv " in *" --log "*) fail primary "the selector got --log with no log= in the conf" ;; esac

# --- index 1: root B by UUID, the bind, runonce's leftovers
hook rootB 1 0 "" "$MASK" "$ROOTB" "mount --bind $M/jjpe/gen1/GunsNRoses $G/GunsNRoses" "chown -R root:root $G/GunsNRoses/game $G/GunsNRoses/vf"
[ "$(cat "$G/GunsNRoses/.bound_from")" = "$M/jjpe/gen1/GunsNRoses" ] || fail rootB "bind source"
[ "$(readlink "$G/GunsNRoses/vf")" = "$P/vf" ] || fail rootB "vf link -> $(readlink "$G/GunsNRoses/vf")"
[ -d "$P/vf" ] || fail rootB "perm/vf not created"
grep -q "image 1: rootB - $M/jjpe/gen1/GunsNRoses bound over $G/GunsNRoses (root B mounted at $M)" "$W/out" || fail rootB "message"

# --- pre-mounted (the rig): no UUID mount, just the bind
mkdir -p "$M/jjpe/gen1/GunsNRoses"; : > "$M/jjpe/gen1/GunsNRoses/game"
: > "$FAKELOG"; : > "$SELARGS"; rm -rf "$R" "$G/GunsNRoses/.bound_from"; mkdir -p "$R"
FAKE_IDX=1 FAKE_RC=0 FAKE_FAIL= $SH padselect.sh > "$W/out" 2>&1 || fail premounted "exit"
[ "$(cat "$FAKELOG")" = "$(printf '%s\n%s\n%s' "$MASK" "mount --bind $M/jjpe/gen1/GunsNRoses $G/GunsNRoses" "chown -R root:root $G/GunsNRoses/game $G/GunsNRoses/vf")" ] || fail premounted "calls"
grep -q "(root B was already at $M)" "$W/out" || fail premounted "message"

# --- rootB:img2
hook sub 2 0 "" "$MASK" "$ROOTB" "mount --bind $M/img2/GunsNRoses $G/GunsNRoses" "chown -R root:root $G/GunsNRoses/game $G/GunsNRoses/vf"
grep -q "image 2: rootB:img2 - $M/img2/GunsNRoses bound" "$W/out" || fail sub "message"

# --- the selector fails: the mask stays, nothing is mounted
hook selfail 1 2 "" "$MASK"
grep -q "selector exit 2: booting image 0" "$W/out" || fail selfail "message"

# --- root B with no game tree: unmounted again
FAKE_EMPTY=1 hook nogame 1 0 "" "$MASK" "$ROOTB" "umount $G/GunsNRoses" "umount $M"
grep -q "no $M/jjpe/gen1/GunsNRoses/game: booting image 0" "$W/out" || fail nogame "message"

# --- the bind fails: root B unmounted
hook bindfail 1 0 --bind "$MASK" "$ROOTB" "mount --bind $M/jjpe/gen1/GunsNRoses $G/GunsNRoses" "umount $G/GunsNRoses" "umount $M"
grep -q "bind of $M/jjpe/gen1/GunsNRoses failed: booting image 0" "$W/out" || fail bindfail "message"

# --- the root B mount fails: image 0
hook mountfail 1 0 "$U/e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87" "$MASK" "$ROOTB"
grep -q "mount of root B .* failed: booting image 0" "$W/out" || fail mountfail "message"

# --- a subdirectory that walks out, and an unknown token: refused before any mount
hook badsub 3 0 "" "$MASK"
grep -q "bad subdirectory '../etc'" "$W/out" || fail badsub "message"
hook odd 4 0 "" "$MASK"
grep -q "unknown device token 'sdcard'" "$W/out" || fail odd "message"
hook past 9 0 "" "$MASK"
grep -q "image 9 has no device" "$W/out" || fail past "message"

# --- no fs_uuids.sh, then a UUID that names no block device
mv "$G/scripts/fs_uuids.sh" "$W/uuids.bak"
hook nouuid 1 0 "" "$MASK"
grep -q "no $G/scripts/fs_uuids.sh: cannot find root B" "$W/out" || fail nouuid "message"
mv "$W/uuids.bak" "$G/scripts/fs_uuids.sh"
mv "$U/e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87" "$W/blk.bak"
hook noblk 1 0 "" "$MASK"
grep -q "no $U/e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87 (root B): booting image 0" "$W/out" || fail noblk "message"
mv "$W/blk.bak" "$U/e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87"

# --- jjp_update=allow: no mask
{ cat "$G/padselect/images.conf"; echo "jjp_update=allow"; } > "$W/conf.allow"
PADSELECT_CONF="$W/conf.allow" hook allow 0 0 ""
grep -q "updater masked" "$W/out" && fail allow "masked despite jjp_update=allow"
[ -e "$R/updater.sh" ] && fail allow "a mask script was written"

# --- the selector log: only with log= in the conf, or the override
{ cat "$G/padselect/images.conf"; echo "log=$W/log/jjpselect.log"; } > "$W/conf.log"
PADSELECT_CONF="$W/conf.log" hook selog 0 0 "" "$MASK"
case " $(cat "$SELARGS") " in *" --log $W/log/jjpselect.log "*) ;; *) fail selog "log= did not reach the selector: $(cat "$SELARGS")" ;; esac
grep -q "padselect.sh: image 0 chosen" "$W/log/jjpselect.log" || fail selog "the hook's line is not in the selector log"
PADSELECT_SELECT_LOG= hook selog_off 0 0 "" "$MASK"
case " $(cat "$SELARGS") " in *" --log "*) fail selog_off "PADSELECT_SELECT_LOG= did not turn it off" ;; esac
PADSELECT_SELECT_LOG="$W/log/forced.log" hook selog_on 0 0 "" "$MASK"
case " $(cat "$SELARGS") " in *" --log $W/log/forced.log "*) ;; *) fail selog_on "the override did not turn it on" ;; esac

# --- the hook's log rotates once past the cap
: > "$T/padselect.log"
PADSELECT_LOGCAP=100 hook rotate1 0 0 "" "$MASK"
head -c 200 /dev/zero | tr '\0' 'x' >> "$T/padselect.log"
PADSELECT_LOGCAP=100 hook rotate2 0 0 "" "$MASK"
[ -f "$T/padselect.log.1" ] || fail rotate "no .1 after the cap"
[ "$(stat -c %s "$T/padselect.log")" -lt 200 ] || fail rotate "the log was not started afresh"

# --- THE SINK (2026-09-14 evening): the selector's stream goes to the pci analog sink,
# named the way JJP's setup.pl names it for the game; a PULSE_SINK already set is kept;
# no pci sink (the rig) = the default, and the hook says so
PADSELECT_PACTL="$W/fakepactl" hook sink 0 0 "" "$MASK"
[ "$(cat "$SELARGS.env")" = "alsa_output.pci-0000_00_1f.3.analog-stereo" ] || fail sink "PULSE_SINK for the selector: '$(cat "$SELARGS.env")'"
grep -q "menu sound to alsa_output.pci-0000_00_1f.3.analog-stereo" "$W/out" || fail sink "no hook line naming the sink"
PULSE_SINK=given PADSELECT_PACTL="$W/fakepactl" hook sinkgiven 0 0 "" "$MASK"
[ "$(cat "$SELARGS.env")" = "given" ] || fail sinkgiven "a PULSE_SINK already set was replaced: '$(cat "$SELARGS.env")'"
PADSELECT_PACTL="$W/nosuchpactl" hook sinknone 0 0 "" "$MASK"
[ -z "$(cat "$SELARGS.env")" ] || fail sinknone "a sink was named with no pactl: '$(cat "$SELARGS.env")'"
printf '#!/bin/sh\nprintf "0\\tRDPSink\\tmodule-rdp.c\\ts16le 2ch 44100Hz\\tRUNNING\\n"\n' > "$W/fakepactl1"; chmod 755 "$W/fakepactl1"
PADSELECT_PACTL="$W/fakepactl1" PADSELECT_PACTL_TRIES=20 hook sinkrig 0 0 "" "$MASK"
[ -z "$(cat "$SELARGS.env")" ] || fail sinkrig "a sink was named with no pci line: '$(cat "$SELARGS.env")'"
grep -q "no pci sink named by" "$W/out" || fail sinkrig "the hook did not say the default is used"
[ -z "$(cat "$SELARGS.env")" ] || fail sinknone "a sink was named with no pactl: '$(cat "$SELARGS.env")'"
grep -q "no pci sink named by" "$W/out" || fail sinknone "the hook did not say the default is used"

# --- a maintenance reboot (2026-09-14): rungame.sh's patched 68/69 cases call the hook
# with --maintenance-reboot before rebooting; the next boot repeats the last choice
# without the menu - once, only while the mark is fresh, only with a last choice
: > "$SELARGS"
$SH padselect.sh --maintenance-reboot > "$W/out" 2>&1 || fail maint "the mark run exited non-zero"
[ -s "$P/padselect.maint" ] || fail maint "no mark written"
grep -q "maintenance reboot: image" "$W/out" || fail maint "no mark line"
echo 1 > "$P/padselect.last"
hook maint 0 0 "" "$MASK" "$ROOTB" "mount --bind $M/jjpe/gen1/GunsNRoses $G/GunsNRoses" "chown -R root:root $G/GunsNRoses/game $G/GunsNRoses/vf"
[ -s "$SELARGS" ] && fail maint "the selector ran on a maintenance boot"
[ -f "$P/padselect.maint" ] && fail maint "the mark was not consumed"
grep -q "maintenance reboot .*: image 1 again, no menu" "$W/out" || fail maint "message"
hook maint2 0 0 "" "$MASK"
[ -s "$SELARGS" ] || fail maint2 "the selector did not run once the mark was consumed"
echo 1000 > "$P/padselect.maint"
hook maintstale 0 0 "" "$MASK"
[ -s "$SELARGS" ] || fail maintstale "the selector did not run with a stale mark"
grep -q "maintenance mark ignored" "$W/out" || fail maintstale "message"
[ -f "$P/padselect.maint" ] && fail maintstale "a stale mark was kept"
date +%s > "$P/padselect.maint"; rm -f "$P/padselect.last"
hook maintnolast 0 0 "" "$MASK"
[ -s "$SELARGS" ] || fail maintnolast "the selector did not run with no last choice"
rm -f "$P/padselect.last" "$P/padselect.maint"

# --- no selector binary: image 0, one line
PADSELECT_BIN="$W/nosuch" hook nobin 0 0 "" "$MASK"
grep -q "no $W/nosuch: booting image 0" "$W/out" || fail nobin "message"

rm -rf "$W"
done
echo "padselect_sh_test: OK ($SHELLS)"
