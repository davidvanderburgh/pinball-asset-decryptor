#!/bin/sh
# select.sh - the codeselect hook for /etc/init.d/game on a multi-image card.
#
# Called right after the script's own 'pkill boot_display ' line and before
# 'if [ -f $GAMES_PATH/game ]; then'. Runs the selector, reads the index it
# wrote, looks the device up in images.conf and, unless it is image 0 (the
# primary, which fstab already mounted at /games), swaps the mount. Stern's
# own launch lines follow untouched.
#
# Device forms in images.conf:
#   <dev>         a whole games partition: umount /games; mount -o ro,relatime,exec <dev> /games
#   <dev>:<sub>   a partition holding several games trees (img1/, img2/ ...):
#                 umount /games; mount -o ro <dev> /mnt/multi; mount --bind /mnt/multi/<sub> /games
#                 (/mnt/multi is created when the rootfs allows it; on the
#                 stock read-only rootfs /var/volatile/multi (tmpfs) is used)
#
# Every failure boots the primary (/dev/mmcblk0p3 is mounted back on /games):
# the card degrades to a stock card, never to a brick. This script never
# touches /mnt/boot. Writing the last-choice file is the selector's job.
#
# THE CARD LOG IS OFF unless images.conf carries a `log=<path>` line
# (mkmulticard.py --debug-log writes log=/dump/log/codeselect.log): a card
# the app builds writes nothing to /dump, boot after boot. The selector's
# stderr (the same lines) still reaches the serial console. With a log= line
# the selector starts the file afresh each boot (the previous boot's is kept
# as <path>.1) and writes at most 1 MiB, and this script's own lines go there
# too. CODESELECT_LOG=<path> forces a log, CODESELECT_LOG= (empty) none.
#
# AN IMAGE WITH ITS OWN HIGH SCORES (PAD-226): a `scores=<N>|<name>` line gives
# image N a machine store of its own. The game keeps its settings, audits and
# high-score table under /data/nv/<title>, and /data is one partition every
# image on the card shares, so two images of the same title share one table -
# wrong when one of them carries custom modes that change the scoring. After
# image N is mounted, /data/nv.own/<name>/<title> is bound over
# /data/nv/<title>; the first boot seeds it with a copy of the shared store
# (settings carry over; the owner resets its high scores once on the machine).
# Each image without a line keeps sharing. Every failure here leaves the image
# on the shared store and the boot goes on.
#
# HIGH SCORES APART FROM SETTINGS (PAD-1194): a `hiscores=<N>|<group>` line puts
# image N's high-score table in <group>, whichever store its settings are in, so
# images with settings of their own can still play into one table (pb_lawww:
# "Heisei - Original Sound (own settings, shared highscore)"). The game plays
# its table from one block of /data/nv/<title>/LKRAM (codeselect's scores.h),
# so only that block is handed over: before the image's store is bound,
# `codeselect --scores-save` copies the table of the store that booted this
# title LAST ($NV_HS/last.<title>) to $NV_HS/<group>/<title>; once it is bound,
# `--scores-load` writes the group's table into it as a new LKRAM generation.
# Never in the boot's way: a table that cannot be handed over (another game
# version, no LKRAM yet) leaves the image with the table it has.
#
# EACH IMAGE'S OWN CUSTOM MODES (PAD-226): a card's modes live on the rootfs at
# /usr/local/padmode, and a multi-boot card has only the primary's rootfs. The
# build copies every other image's set to $DIR/modes/img<N>/ (and makes an empty
# $DIR/modes/none); once image N is mounted its set - or the empty one - is bound
# over /usr/local/padmode, so the hooked game_monitor preloads the booted image's
# modes and nobody else's. Image 0 keeps the set its own card put there. A card
# with no $DIR/modes is left exactly as it always was.
#
# THE COLOR CORRECTION SET ON THIS MACHINE (PAD-307): the menu's Settings >
# Color correction keeps the operator's numbers per image in $COLOR (on /data).
# Once image N is mounted, and only when the conf says its game can be adjusted
# (a color_profile= line) and $COLOR holds numbers for it that differ from the
# build's, the selector writes a copy of the game program with those numbers in
# its drawing shaders into RAM ($COLOR_DIR, on the /var/volatile tmpfs) and the
# copy is bound over <title>/game. The games partition is never written. Every
# failure leaves the program as it was built: the colours it was built with,
# never a machine that will not boot.
#
#   select.sh                     the hook (what /etc/init.d/game calls)
#   select.sh --lookup N [conf]   print image N's device (without :<sub>)
#   select.sh --lookup-sub N [conf]   print image N's subdirectory ("" when none)
#   select.sh --scores N [conf]   print image N's own-scores name ("" when it shares)
#   select.sh --hiscores N [conf] print image N's high-score group ("" = with its settings)
#
# POSIX sh; needs only busybox sed/awk/grep/head/tr/mkdir/mount/umount + pidof.
# The CODESELECT_* variables exist for the tests (a fake selector, fake
# mount/umount, no block-device check); the hook runs with the defaults.

DIR=${CODESELECT_DIR:-/usr/local/codeselect}
CONF=${CODESELECT_CONF:-$DIR/images.conf}
BIN=${CODESELECT_BIN:-$DIR/codeselect}
OUT=${CODESELECT_OUT:-/var/volatile/codeselect.choice}
PRIMARY=/dev/mmcblk0p3
GAMES=${CODESELECT_GAMES:-/games}
MULTI=${CODESELECT_MULTI:-/mnt/multi}
MULTI_FALLBACK=${CODESELECT_MULTI_FALLBACK:-/var/volatile/multi}
MOUNT=${CODESELECT_MOUNT:-mount}
UMOUNT=${CODESELECT_UMOUNT:-umount}
NV=${CODESELECT_NV:-/data/nv}
NV_OWN=${CODESELECT_NV_OWN:-/data/nv.own}
NV_HS=${CODESELECT_NV_HS:-/data/nv.hs}
MODES=${CODESELECT_MODES:-$DIR/modes}
PADMODE=${CODESELECT_PADMODE:-/usr/local/padmode}
COLOR=${CODESELECT_COLOR:-/data/codeselect.color}
COLOR_DIR=${CODESELECT_COLOR_DIR:-/var/volatile/padcolor}

log() {
    [ -n "$LOG" ] && echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) select.sh: $*" >> "$LOG" 2>/dev/null
    echo "select.sh: $*"
}

# AWK may name another awk (the tests run the card's busybox awk under qemu)
AWK=${AWK:-awk}

# the conf's `log=<path>` value ("" when there is none: the shipped default)
conf_log() {
    $AWK '/^[ \t]*log[ \t]*=/ { sub(/^[^=]*=[ \t]*/, ""); sub(/[ \t]+$/, ""); print; exit }' "$1" 2>/dev/null
}
LOG=${CODESELECT_LOG-$(conf_log "$CONF")}

# image N's device field split at ':' - prints "<dev>" or "<dev> <sub>":
# the N-th (0-based) 'image=<device>|...' line of the conf
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
        }' "$2"
}

is_blockdev() {
    [ -n "${CODESELECT_NO_BLKCHECK:-}" ] || [ -b "$1" ]
}

has_game() {
    [ -e "$1/game" ] || [ -L "$1/game" ]
}

# ITEM 107 - DELTAS. A store card (--layout store) may keep a tree's file as a
# byte-range DELTA of another tree's: the tree's own file is then a hardlink to
# the BASE (it plays the base's songs as it stands) and <tree>/.multiboot/deltas
# names what to rebuild. materialize.py - shipped beside this script, run with
# the card's own python2.7 - mounts the work partition rw, rebuilds each file
# under a stamp and binds it over its path under /games. It exits 0 on every
# failure, so a broken delta means the base's songs and never a machine that
# will not boot. Runs AFTER the tree is bound, so the bind targets exist.
# The CODESELECT_* variables exist for the tests (a stand-in python, a plain
# directory for the work partition); the hook runs with the defaults.
PY=${CODESELECT_PYTHON:-/usr/bin/python2.7}
WORKDEV=${CODESELECT_WORKDEV-/dev/mmcblk0p7}
WORKMNT=${CODESELECT_WORKMNT:-/mnt/work}
materialize() {   # materialize STORE-MOUNT SUB
    [ -f "$1/$2/.multiboot/deltas" ] || return 0
    [ -x "$PY" ] || { log "image $idx: stores deltas but there is no $PY: the game plays the base's files"; return 0; }
    [ -f "$DIR/materialize.py" ] || { log "image $idx: stores deltas but there is no $DIR/materialize.py: the game plays the base's files"; return 0; }
    wm=$WORKMNT
    if ! mkdir -p "$wm" 2>/dev/null; then
        wm=/var/volatile/work
        mkdir -p "$wm" 2>/dev/null
    fi
    log "image $idx: stores deltas: rebuilding them on $WORKDEV at $wm"
    "$PY" "$DIR/materialize.py" --store "$1" --tree "$2" --games "$GAMES" --work "$wm" \
        ${WORKDEV:+--mount-dev "$WORKDEV"} ${LOG:+--log "$LOG"} </dev/null
}

# image N's `scores=<N>|<name>` name ("" when the image shares the store)
scores_name() {
    $AWK -F'|' -v want="$1" '
        /^[ \t]*scores[ \t]*=/ {
            sub(/^[ \t]*scores[ \t]*=[ \t]*/, "", $1)
            gsub(/[ \t]+$/, "", $1); gsub(/^[ \t]+|[ \t]+$/, "", $2)
            if ($1 == want "") { print $2; exit }
        }' "$2"
}

# image N's `hiscores=<N>|<group>` group ("" when its scores go with its settings)
hiscores_name() {
    $AWK -F'|' -v want="$1" '
        /^[ \t]*hiscores[ \t]*=/ {
            sub(/^[ \t]*hiscores[ \t]*=[ \t]*/, "", $1)
            gsub(/[ \t]+$/, "", $1); gsub(/^[ \t]+|[ \t]+$/, "", $2)
            if ($1 == want "") { print $2; exit }
        }' "$2"
}

# a store/group name select.sh accepts (the rule scores= names follow)
good_name() {
    case "$1" in ""|.*|*/*|*[!A-Za-z0-9._-]*) return 1 ;; esac
    return 0
}

# the title directory the mounted games tree runs: game -> <title>/game
game_title() {
    t=$(readlink "$GAMES/game" 2>/dev/null)
    t=${t%/game}
    t=${t##*/}
    case "$t" in ""|.*|*/*|game) return 1 ;; esac
    echo "$t"
}

# PAD-226: bind image $idx's own machine store over the shared one (see the header)
own_scores() {
    name=$(scores_name "$idx" "$CONF")
    [ -n "$name" ] || return 0
    case "$name" in
        .*|*/*|*[!A-Za-z0-9._-]*) log "image $idx: bad scores name '$name': it shares the machine store"; return 0 ;;
    esac
    title=$(game_title) || { log "image $idx: cannot tell its title from $GAMES/game: it shares the machine store"; return 0; }
    store=$NV_OWN/$name/$title
    if [ ! -d "$store" ]; then
        rm -rf "$store.part"
        if ! mkdir -p "$NV_OWN/$name"; then
            log "image $idx: cannot create $NV_OWN/$name: it shares the machine store"; return 0
        fi
        if [ -d "$NV/$title" ]; then
            cp -a "$NV/$title" "$store.part" && mv "$store.part" "$store" || {
                rm -rf "$store.part"
                log "image $idx: copying $NV/$title failed: it shares the machine store"; return 0; }
            log "image $idx: its own machine store $store, started from a copy of the shared one"
        else
            mkdir -p "$store" || { log "image $idx: cannot create $store: it shares the machine store"; return 0; }
            log "image $idx: its own machine store $store, started empty (no shared store yet)"
        fi
    fi
    mkdir -p "$NV/$title" 2>/dev/null
    if $MOUNT --bind "$store" "$NV/$title"; then
        STORE_REAL=$store
        log "image $idx: $store bound over $NV/$title (its own settings, audits and high scores)"
    else
        log "image $idx: binding $store failed: it shares the machine store"
    fi
}

# PAD-1194, BEFORE the store is bound: the table of the store that booted this
# title last goes to that boot's group (see the header)
hs_save_last() {
    HS_TITLE=$(game_title) || { HS_TITLE=""; return 0; }
    last=$NV_HS/last.$HS_TITLE
    [ -f "$last" ] || return 0
    IFS='|' read -r lg lp < "$last"
    good_name "$lg" || { log "image $idx: $last names no group ('$lg'): nothing saved"; return 0; }
    case "$lp" in
        "$NV/$HS_TITLE"|"$NV_OWN"/*/"$HS_TITLE") ;;
        *) log "image $idx: $last names no store of $HS_TITLE ('$lp'): nothing saved"; return 0 ;;
    esac
    [ -d "$lp" ] || return 0
    mkdir -p "$NV_HS/$lg" 2>/dev/null
    msg=$("$BIN" --scores-save --store "$lp" --to "$NV_HS/$lg/$HS_TITLE" </dev/null 2>/dev/null)
    rc=$?
    [ -n "$msg" ] && log "image $idx: $(echo "$msg" | sed 's/^\[select\] //' | head -n 1) (group $lg)"
    [ "$rc" -le 1 ] || log "image $idx: the last game's high scores could not be saved (exit $rc)"
}

# PAD-1194, AFTER the store is bound: its group's table into it, and this boot
# remembered as the one to save from next time
hs_load() {
    [ -n "$HS_TITLE" ] || return 0
    group=$(hiscores_name "$idx" "$CONF")
    if [ -z "$group" ]; then
        # nothing split for this image: no hand-over to make next time
        rm -f "$NV_HS/last.$HS_TITLE"
        return 0
    fi
    good_name "$group" || { log "image $idx: bad hiscores group '$group': it keeps the table it has"; return 0; }
    mkdir -p "$NV_HS" 2>/dev/null || { log "image $idx: cannot create $NV_HS: it keeps the table it has"; return 0; }
    msg=$("$BIN" --scores-load --from "$NV_HS/$group/$HS_TITLE" --store "$NV/$HS_TITLE" </dev/null 2>/dev/null)
    rc=$?
    [ -n "$msg" ] && log "image $idx: $(echo "$msg" | sed 's/^\[select\] //' | head -n 1) (group $group)"
    [ "$rc" -le 1 ] || log "image $idx: the shared high scores could not be loaded (exit $rc): it keeps the table it has"
    if echo "$group|$STORE_REAL" > "$NV_HS/last.$HS_TITLE.part" \
            && mv "$NV_HS/last.$HS_TITLE.part" "$NV_HS/last.$HS_TITLE"; then
        :
    else
        log "image $idx: cannot write $NV_HS/last.$HS_TITLE: its scores are not handed on"
    fi
}

# PAD-226: bind image $idx's own custom modes (or none) over the rootfs's (see the header)
own_modes() {
    [ -d "$MODES" ] || return 0
    [ "$idx" -eq 0 ] && return 0
    src=$MODES/img$idx
    what="its own custom modes"
    if [ ! -d "$src" ]; then
        src=$MODES/none
        what="no custom modes"
    fi
    if [ ! -d "$src" ] || [ ! -d "$PADMODE" ]; then
        log "image $idx: no $src or no $PADMODE: the rootfs's modes stay as they are"
        return 0
    fi
    if $MOUNT --bind "$src" "$PADMODE"; then
        log "image $idx: $src bound over $PADMODE ($what)"
    else
        log "image $idx: binding $src over $PADMODE failed: the rootfs's modes stay as they are"
    fi
}

# PAD-307: image $idx's game program with the operator's colour numbers, bound
# over its own (see the header).  The selector does the copy (--apply-color):
# exit 0 = a copy is at $out, 1 = nothing to do, anything else = refused.  Its
# own log is NOT passed: a second --log run would start the menu's file afresh,
# so its one line comes back on stdout and goes into this script's log.
own_color() {
    [ -f "$COLOR" ] || return 0
    grep -q '^[ 	]*color_profile[ 	]*=' "$CONF" 2>/dev/null || return 0
    title=$(game_title) || { log "image $idx: cannot tell its title from $GAMES/game: its colors are as built"; return 0; }
    prog=$GAMES/$title/game
    [ -f "$prog" ] || { log "image $idx: no $prog: its colors are as built"; return 0; }
    mkdir -p "$COLOR_DIR" 2>/dev/null || { log "image $idx: cannot create $COLOR_DIR: its colors are as built"; return 0; }
    out=$COLOR_DIR/$title.game
    rm -f "$out"
    msg=$("$BIN" --apply-color --conf "$CONF" --image "$idx" --program "$prog" --to "$out" \
            --color-file "$COLOR" </dev/null 2>/dev/null)
    rc=$?
    [ -n "$msg" ] && log "image $idx: $(echo "$msg" | sed 's/^\[select\] //' | head -n 1)"
    if [ "$rc" -ne 0 ]; then
        rm -f "$out"
        [ "$rc" -ne 1 ] && log "image $idx: the color correction could not be applied (exit $rc): its colors are as built"
        return 0
    fi
    if [ -f "$out" ] && $MOUNT --bind "$out" "$prog"; then
        log "image $idx: $out bound over $prog (the color correction set on this machine)"
    else
        rm -f "$out"
        log "image $idx: binding $out over $prog failed: its colors are as built"
    fi
}

# everything that belongs to the image that is about to boot, once it is mounted
image_ready() {
    STORE_REAL=""
    hs_save_last
    own_scores
    [ -n "$STORE_REAL" ] || STORE_REAL=$NV/$HS_TITLE
    hs_load
    own_modes
    own_color
}

case "$1" in
    --scores)
        [ -n "$2" ] || { echo "usage: select.sh --scores N [conf]" >&2; exit 1; }
        scores_name "$2" "${3:-$CONF}"
        exit 0
        ;;
    --hiscores)
        [ -n "$2" ] || { echo "usage: select.sh --hiscores N [conf]" >&2; exit 1; }
        hiscores_name "$2" "${3:-$CONF}"
        exit 0
        ;;
    --lookup)
        [ -n "$2" ] || { echo "usage: select.sh --lookup N [conf]" >&2; exit 1; }
        set -- $(lookup "$2" "${3:-$CONF}")
        echo "$1"
        exit 0
        ;;
    --lookup-sub)
        [ -n "$2" ] || { echo "usage: select.sh --lookup-sub N [conf]" >&2; exit 1; }
        set -- $(lookup "$2" "${3:-$CONF}")
        echo "$2"
        exit 0
        ;;
esac

if [ -n "$LOG" ]; then
    d=${LOG%/*}
    [ "$d" != "$LOG" ] && mkdir -p "$d" 2>/dev/null
fi

[ -x "$BIN" ] || { log "no $BIN: booting primary"; exit 0; }
[ -r "$CONF" ] || { log "no $CONF: booting primary"; exit 0; }

# boot_display was just pkill'ed; give it a moment to release the display
i=0
while [ "$i" -lt 30 ] && pidof boot_display >/dev/null 2>&1; do
    usleep 100000
    i=$((i + 1))
done

# the primary boots after all: image 0's own store, when it has one
primary() {
    idx=0
    image_ready
    exit 0
}

rm -f "$OUT"
"$BIN" --conf "$CONF" --out "$OUT" ${LOG:+--log "$LOG"}
rc=$?
[ "$rc" -eq 0 ] || { log "selector exit $rc: booting primary"; primary; }

idx=$(head -n 1 "$OUT" 2>/dev/null | tr -cd '0-9')
[ -n "$idx" ] || { log "no choice in $OUT: booting primary"; primary; }

if [ "$idx" -eq 0 ]; then
    log "image 0 is the primary, already mounted at $GAMES"
    image_ready
    exit 0
fi

set -- $(lookup "$idx" "$CONF")
dev=$1
sub=$2
[ -n "$dev" ] || { log "image $idx has no device in $CONF: booting primary"; primary; }
is_blockdev "$dev" || { log "$dev is not a block device: booting primary"; primary; }
case "$sub" in
    */*|.*) log "image $idx: bad subdirectory '$sub': booting primary"; primary ;;
esac

if ! $UMOUNT "$GAMES"; then
    log "umount $GAMES failed: booting primary (still mounted)"
    primary
fi

if [ -z "$sub" ]; then
    if $MOUNT -t ext4 -o ro,relatime,exec "$dev" "$GAMES" && has_game "$GAMES"; then
        log "image $idx: mounted $dev at $GAMES"
        image_ready
        exit 0
    fi
    log "mount $dev failed or it has no $GAMES/game: remounting the primary $PRIMARY"
    $UMOUNT "$GAMES" 2>/dev/null
else
    mp=$MULTI
    if ! mkdir -p "$mp" 2>/dev/null; then
        mp=$MULTI_FALLBACK
        mkdir -p "$mp" 2>/dev/null
        log "$MULTI is not creatable (read-only rootfs), using $mp"
    fi
    if [ -d "$mp" ] && $MOUNT -t ext4 -o ro,relatime,exec "$dev" "$mp"; then
        if [ -d "$mp/$sub" ] && $MOUNT --bind "$mp/$sub" "$GAMES" && has_game "$GAMES"; then
            log "image $idx: mounted $dev at $mp, $sub bound over $GAMES"
            materialize "$mp" "$sub"
            image_ready
            exit 0
        fi
        log "no $mp/$sub/game or the bind failed: remounting the primary $PRIMARY"
        $UMOUNT "$GAMES" 2>/dev/null
        $UMOUNT "$mp" 2>/dev/null
    else
        log "mount $dev at $mp failed: remounting the primary $PRIMARY"
    fi
fi

if $MOUNT -t ext4 -o ro,relatime,exec "$PRIMARY" "$GAMES"; then
    log "primary remounted"
    primary
else
    log "PRIMARY REMOUNT FAILED: $GAMES is empty"
fi
exit 0
