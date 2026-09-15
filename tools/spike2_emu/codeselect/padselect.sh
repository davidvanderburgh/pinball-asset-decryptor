#!/bin/dash
# padselect.sh - the jjpselect hook for a JJP machine's rungame.sh on a
# multi-boot install (item 115; the selector is item 114, the builder that
# stages both is item 116).
#
# THE ONE LINE the builder adds to root A's /jjpe/gen1/scripts/rungame.sh,
# right after `$JJPEDIR/scripts/runonce.sh` and before `while true`:
#
#     [ -x $JJPEDIR/scripts/padselect.sh ] && $JJPEDIR/scripts/padselect.sh
#
# EXECUTED, not sourced: rungame.sh runs under jjp.service with Restart=always,
# and an `exit` inside a sourced file would take rungame.sh down and loop the
# service.  A child's exit is nothing.  Its mounts are in the same namespace,
# which is all rungame.sh needs.
#
# What it does, in order:
#   1. images.conf under /jjpe/gen1/padselect names the images (the same v2
#      grammar as the Stern card; conf.h).  Fewer than two: nothing, exit 0.
#   2. JJP's updater is MASKED (jjp_update=refuse, the default with two
#      images): updater.sh writes the OTHER root slot - which is image 1 -
#      and then swapgrub.sh -p b, so a JJP update would overwrite the second
#      image and boot it with no menu.  A tiny script is bind-mounted over
#      /jjpe/gen1/scripts/updater.sh for the life of the boot (a namespace
#      change: nothing new on the disk), and it tells the game's update screen
#      why.  jjp_update=allow in the conf leaves the updater alone.
#   3. jjpselect draws the menu on the X server xinit already started, reads
#      the cabinet buttons off /dev/jjpio100 and writes ONE integer to the
#      choice file.  Exit 0 = a choice; anything else = boot image 0 untouched.
#      Its sound goes to the onboard (pci) PulseAudio sink by name - the one
#      JJP's own scripts/audio/setup.pl moves the game's stream to - because
#      the server's DEFAULT sink on a machine with the headphone kit is the
#      kit's USB codec (2026-09-14: five silent sticks).
#   4. The chosen image's device token, from its image= line:
#        rootA          the primary's own tree: nothing to mount
#        rootB          root B (p5), the second JJP install: mounted rw by the
#                       UUID in the card's OWN scripts/fs_uuids.sh at
#                       /jjpe/multi/b; the game tree is /jjpe/multi/b/jjpe/gen1
#        rootB:<sub>    a directory <sub> at root B's top holding <GAMENAME>/
#                       (a tree the builder put beside the second install)
#      The mount is skipped when the tree is already there - the rig pre-mounts
#      root B into its jail, so ONE script serves both worlds.
#   5. mount --bind <tree>/<GAMENAME> /jjpe/gen1/<GAMENAME>, then what
#      runonce.sh did on the tree the game now sees (the vf link into
#      /jjpe/perm, chown, +x).  Any failure unwinds the bind and the mount, so
#      rungame.sh runs image 0 - a dead menu never keeps a pinball machine
#      from booting.
#   6. One line into /jjpe/temp/padselect.log (JJP's own log partition; the
#      previous file is kept as .1 once it passes 1 MiB).  The selector's own
#      verbose log only with a `log=<path>` line in the conf (the builder's
#      --debug-log), exactly as select.sh does on the Stern card.
#
#   padselect.sh                    the hook
#   padselect.sh --lookup N [conf]  print image N's device token (test / builder)
#
# dash, the shell rungame.sh itself is written for.  The PADSELECT_* variables
# exist for the tests (a fake selector, fake mount/umount/chown, plain
# directories for the partitions); the hook runs with the defaults.

JJPEDIR=${JJPEDIR:-/jjpe/gen1}
if [ -z "${GAMENAME:-}" ] && [ -r "$JJPEDIR/setenv.sh" ]; then . "$JJPEDIR/setenv.sh"; fi
GAMENAME=${GAMENAME:-}
GAMEDIR=${GAMEDIR:-$JJPEDIR/$GAMENAME}

DIR=${PADSELECT_DIR:-$JJPEDIR/padselect}
CONF=${PADSELECT_CONF:-$DIR/images.conf}
BIN=${PADSELECT_BIN:-$DIR/jjpselect}
TEMP=${PADSELECT_TEMP:-/jjpe/temp}
PERM=${PADSELECT_PERM:-/jjpe/perm}
OUT=${PADSELECT_OUT:-$TEMP/padselect.choice}
LAST=${PADSELECT_LAST:-$PERM/padselect.last}
HOOKLOG=${PADSELECT_HOOKLOG:-$TEMP/padselect.log}
MULTI=${PADSELECT_MULTI:-/jjpe/multi/b}
UUIDS=${PADSELECT_UUIDS:-$JJPEDIR/scripts/fs_uuids.sh}
BYUUID=${PADSELECT_BYUUID:-/dev/disk/by-uuid}
UPDATER=${PADSELECT_UPDATER:-$JJPEDIR/scripts/updater.sh}
RUNDIR=${PADSELECT_RUNDIR:-/run/padselect}
MOUNT=${PADSELECT_MOUNT:-mount}
PACTL=${PADSELECT_PACTL:-pactl}
UMOUNT=${PADSELECT_UMOUNT:-umount}
CHOWN=${PADSELECT_CHOWN:-chown}
AWK=${AWK:-awk}
LOGCAP=${PADSELECT_LOGCAP:-1048576}

# ---- the hook's own one line per boot --------------------------------------
hooklog() {
    echo "padselect.sh: $*"
    [ -n "$HOOKLOG" ] || return 0
    d=${HOOKLOG%/*}
    [ "$d" != "$HOOKLOG" ] && mkdir -p "$d" 2>/dev/null
    if [ -f "$HOOKLOG" ]; then
        sz=$(stat -c %s "$HOOKLOG" 2>/dev/null || echo 0)
        [ "$sz" -gt "$LOGCAP" ] && mv -f "$HOOKLOG" "$HOOKLOG.1" 2>/dev/null
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*" >> "$HOOKLOG" 2>/dev/null
    [ -n "$SLOG" ] && echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) padselect.sh: $*" >> "$SLOG" 2>/dev/null
    return 0
}

# ---- the conf ----------------------------------------------------------------
conf_key() {   # conf_key KEY [conf] -> the value ("" when absent)
    $AWK -v k="$1" '
        index($0, "=") {
            key = $0; sub(/=.*/, "", key); gsub(/^[ \t]+|[ \t]+$/, "", key)
            if (key == k) { v = $0; sub(/^[^=]*=[ \t]*/, "", v); sub(/[ \t]+$/, "", v); print v; exit }
        }' "${2:-$CONF}" 2>/dev/null
}
count_images() {
    $AWK '/^[ \t]*image[ \t]*=/ { n++ } END { print n + 0 }' "${1:-$CONF}" 2>/dev/null
}
# image N's device token, split at ':' - prints "<dev>" or "<dev> <sub>"
lookup() {
    $AWK -F'|' -v want="$1" '
        /^[ \t]*image[ \t]*=/ {
            if (i == want) {
                sub(/^[ \t]*image[ \t]*=[ \t]*/, "", $1)
                gsub(/[ \t]+$/, "", $1)
                n = split($1, a, ":")
                if (n > 1) print a[1] " " a[2]
                else print a[1]
                exit
            }
            i++
        }' "${2:-$CONF}" 2>/dev/null
}

case "${1:-}" in
    --lookup)
        [ -n "${2:-}" ] || { echo "usage: padselect.sh --lookup N [conf]" >&2; exit 1; }
        set -- $(lookup "$2" "${3:-$CONF}")
        echo "${1:-}${2:+:$2}"
        exit 0
        ;;
esac

SLOG=${PADSELECT_SELECT_LOG-$(conf_key log)}
if [ -n "$SLOG" ]; then
    d=${SLOG%/*}
    [ "$d" != "$SLOG" ] && mkdir -p "$d" 2>/dev/null
fi

[ -r "$CONF" ] || exit 0                       # not a multi-boot install: silence
n=$(count_images)
[ "$n" -ge 2 ] || exit 0                       # one image: nothing to choose, nothing to mask

# ---- 2. JJP's updater -----------------------------------------------------------
policy=$(conf_key jjp_update)
[ -n "$policy" ] || policy=refuse
case "$policy" in
    allow) ;;
    *)
        if [ -f "$UPDATER" ]; then
            mkdir -p "$RUNDIR" 2>/dev/null
            cat > "$RUNDIR/updater.sh" <<EOF
#!/bin/dash
# padselect.sh: this is a multi-boot install.  JJP's updater writes the OTHER
# root slot - the second image - and then boots it, menu and all gone.
# Refused for the life of this boot (jjp_update=allow in images.conf lifts it).
echo 'update refused: multi-boot install (PAD)' > "$TEMP/rprogress" 2>/dev/null
echo 'update refused: multi-boot install (PAD)' > "$TEMP/pcprogress" 2>/dev/null
echo "padselect.sh: update refused: multi-boot install" >&2
exit 1
EOF
            chmod 755 "$RUNDIR/updater.sh" 2>/dev/null
            if $MOUNT --bind "$RUNDIR/updater.sh" "$UPDATER"; then
                hooklog "updater masked ($n images, jjp_update=$policy)"
            else
                hooklog "could not mask $UPDATER: a JJP update would overwrite image 1"
            fi
        fi
        ;;
esac

# ---- 3. the menu ----------------------------------------------------------------
[ -x "$BIN" ] || { hooklog "no $BIN: booting image 0"; exit 0; }
[ -n "$GAMENAME" ] || { hooklog "no GAMENAME ($JJPEDIR/setenv.sh): booting image 0"; exit 0; }
rm -f "$OUT"
# THE SINK (2026-09-14 evening, the GNR's silent menu).  PulseAudio's default sink on
# a machine with JJP's headphone kit is the kit's USB codec - pulse ranks usb above
# pci - and JJP's own scripts/audio/setup.pl, run once the GAME is up, moves the
# game's stream to the onboard pci sink and makes that the default.  The menu runs
# before setup.pl, so its stream went to the kit and the speakers stayed silent
# through five sticks, while every rig proof - one sink - heard it.  So: what
# setup.pl does, for the selector's stream.  PULSE_SINK is libpulse's default
# device, honoured by the selector's own pulse sink and by ALSA's pulse plugin
# alike; the match is setup.pl's ("pci" in the name, "analog" on the line).  No
# pci sink - the rig, with WSLg's one sink - means the default, as before.
# jjp.service is After= pulseaudio.service, not after it is READY, and setup.pl itself
# waits up to 10 s for the daemon: so ask again for that long while pactl FAILS (no
# server yet) - only when there is a pactl at all, and an answer is final whatever it
# names (the cards are detected before the socket opens; the rig's one sink must not
# cost 10 s a run).
if [ -z "${PULSE_SINK:-}" ]; then
    pci_sink=
    if command -v "$PACTL" >/dev/null 2>&1; then
        tries=${PADSELECT_PACTL_TRIES:-20}
        while [ "$tries" -gt 0 ]; do
            if sinks=$($PACTL list short sinks 2>/dev/null); then
                pci_sink=$(printf '%s\n' "$sinks" | $AWK -F'\t' '$2 ~ /pci/ && $0 ~ /analog/ { print $2; exit }')
                break
            fi
            tries=$((tries - 1))
            [ "$tries" -gt 0 ] && sleep 0.5
        done
    fi
    if [ -n "$pci_sink" ]; then
        PULSE_SINK=$pci_sink
        export PULSE_SINK
        hooklog "menu sound to $pci_sink (the pci sink, where JJP's setup.pl sends the game's)"
    else
        hooklog "no pci sink named by $PACTL: the menu's sound goes to the default sink"
    fi
fi
# --learn: the cabinet frame into the log whenever a bit changes - one line a press,
# nothing while idle - so a machine whose buttons sit elsewhere in the frame (the GNR's
# outside volume toggle and its Action button, 2026-09-14) is read, not guessed
"$BIN" --conf "$CONF" --input jjpio --learn --out "$OUT" --last "$LAST" ${SLOG:+--log "$SLOG"} \
    ${PADSELECT_AUDIO_DUMP:+--audio-dump "$PADSELECT_AUDIO_DUMP"}
rc=$?
[ "$rc" -eq 0 ] || { hooklog "selector exit $rc: booting image 0"; exit 0; }
idx=$(head -n 1 "$OUT" 2>/dev/null | tr -cd '0-9')
[ -n "$idx" ] || { hooklog "no choice in $OUT: booting image 0"; exit 0; }
if [ "$idx" -eq 0 ]; then
    hooklog "image 0 chosen: the primary, already in place"
    exit 0
fi

# ---- 4. the device token -------------------------------------------------------
set -- $(lookup "$idx")
dev=${1:-}
sub=${2:-}
[ -n "$dev" ] || { hooklog "image $idx has no device in $CONF: booting image 0"; exit 0; }
case "$sub" in
    */*|.*) hooklog "image $idx: bad subdirectory '$sub': booting image 0"; exit 0 ;;
esac
mounted=0
case "$dev" in
    rootA)
        hooklog "image $idx names rootA: the primary's own tree, nothing to mount"
        exit 0
        ;;
    rootB)
        if [ -n "$sub" ]; then tree=$MULTI/$sub; else tree=$MULTI/jjpe/gen1; fi
        if [ ! -e "$tree/$GAMENAME/game" ]; then
            # not pre-mounted: root B by the UUID the card itself declares
            [ -r "$UUIDS" ] || { hooklog "no $UUIDS: cannot find root B: booting image 0"; exit 0; }
            . "$UUIDS"
            [ -n "${FS_UUID_ROOTB:-}" ] || { hooklog "$UUIDS names no FS_UUID_ROOTB: booting image 0"; exit 0; }
            blk=$BYUUID/$FS_UUID_ROOTB
            if [ -z "${PADSELECT_NO_BLKCHECK:-}" ] && [ ! -e "$blk" ]; then
                hooklog "no $blk (root B): booting image 0"; exit 0
            fi
            mkdir -p "$MULTI" 2>/dev/null
            if ! $MOUNT -o rw,noatime,discard "$blk" "$MULTI"; then
                hooklog "mount of root B ($blk) at $MULTI failed: booting image 0"; exit 0
            fi
            mounted=1
        fi
        ;;
    *)
        hooklog "image $idx: unknown device token '$dev': booting image 0"
        exit 0
        ;;
esac

undo() {   # undo WHY
    hooklog "$1: booting image 0"
    $UMOUNT "$JJPEDIR/$GAMENAME" 2>/dev/null
    [ "$mounted" = 1 ] && $UMOUNT "$MULTI" 2>/dev/null
    exit 0
}

# ---- 5. the bind ----------------------------------------------------------------
[ -e "$tree/$GAMENAME/game" ] || undo "image $idx: no $tree/$GAMENAME/game"
$MOUNT --bind "$tree/$GAMENAME" "$JJPEDIR/$GAMENAME" || undo "image $idx: bind of $tree/$GAMENAME failed"
[ -e "$GAMEDIR/game" ] || undo "image $idx: $GAMEDIR/game is not there after the bind"
# what runonce.sh did for the primary's tree, for the one the game now sees
mkdir -p "$PERM/vf" 2>/dev/null
ln -s -f -T "$PERM/vf" "$GAMEDIR/vf" 2>/dev/null
$CHOWN -R root:root "$GAMEDIR"/* 2>/dev/null
chmod --silent +x "$GAMEDIR/game" 2>/dev/null
if [ "$mounted" = 1 ]; then how="root B mounted at $MULTI"; else how="root B was already at $MULTI"; fi
hooklog "image $idx: $dev${sub:+:$sub} - $tree/$GAMENAME bound over $JJPEDIR/$GAMENAME ($how)"
exit 0
