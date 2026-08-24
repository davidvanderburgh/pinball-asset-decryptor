#!/bin/bash
# cardmount.sh <card.raw> [--umount] - mount a Spike 2 card's games partition,
# READ ONLY, WITHOUT ROOT, so a title can be run without extracting 6 GB first.
#
#   cardmount.sh .../jaws_le-1_02_0.Release.16G.sdcard.raw
#   -> $HOME/card/jaws_le-1_02_0   (and prints the title directory)
#
# WHY THIS IS POSSIBLE AT ALL. The obvious `mount -o loop,offset=` needs real
# root, and this rig has no sudo. Two things make it work anyway:
#
#   * fuse2fs, e2fsprogs' own read-only-capable ext4 driver in USERSPACE. It is
#     not installed and does not need to be: `apt-get download` works as an
#     ordinary user, and `dpkg-deb -x` into a private prefix gives a working
#     binary with no package manager and no privilege. See ensure_fuse2fs().
#   * fusermount3 is setuid, so an unprivileged user may create a FUSE mount -
#     and FUSE is one of the few filesystem types the kernel permits inside a
#     user namespace, which is where run_game.sh does its work.
#
# The partition is mounted `ro`. Nothing here can write to a card image, which
# is the right guarantee to have when the images are the only copies.
set -u

SELF=$(cd "$(dirname "$0")" && pwd)
# $PAD_HOME, so THE PLACE A CARD IS MOUNTED AND THE PLACE IT IS UNMOUNTED FROM
# are the same string however the two scripts were invoked. killgame.sh globs
# "$PAD_HOME/card/"*/ to unmount; if this mounted under a different $HOME the
# unmount would silently match nothing, which is exactly the bug padpath.sh's
# header describes. Sourced from padpath.sh, which resolves it once.
. "$SELF/padpath.sh"
PREFIX=$PAD_HOME/local
CARDS=$PAD_HOME/card
CACHE=$PAD_HOME/cardcache
FUSE2FS="$PREFIX/usr/bin/fuse2fs"
export LD_LIBRARY_PATH="$PREFIX/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"

die() { echo "[card] $*" >&2; exit 1; }

# HAND FILES BACK when this runs as root (a PAD_PIVOT session - item 13).
# Everything here lives under the DESKTOP USER's home ($HOME is set to theirs
# by the launcher), and a root-owned stamp/cache/log in their directory is the
# same trap watch.sh already fixes for its logs: the next ordinary run cannot
# overwrite it. No-op for a normal user run.
give_back() {
    [ "$(id -u)" = 0 ] || return 0
    local o
    o=$(stat -c %U "$HOME" 2>/dev/null)
    [ -n "$o" ] && [ "$o" != root ] && chown "$o" "$@" 2>/dev/null
    return 0
}

# LOCAL IMAGE CACHE - why card boots were slow, and why the SECOND one is not.
#
# The card images live on the Windows D: drive, so every cold read goes
# NTFS -> 9p -> fuse2fs: measured 139 MB/s for the raw image and roughly half
# that once fuse2fs is on top, against native ext4 for an extracted title. The
# page cache already makes REPEAT reads free while WSL stays up (measured
# 2.83 s -> 0.016 s on a 180 MB asset), so the cost that matters is the first
# boot of a title after a WSL start.
#
# The fix is a copy of the image on the WSL disk. It used to be made in the
# BACKGROUND while the game booted off the original - which meant the copy and
# the boot fought over the same 9p reads: 177 s to first picture with laggy
# input, against ~60-70 s for the copy alone plus ~9-15 s for a cached boot.
# So since item 74 the first mount WAITS for the copy (with progress lines) and
# then mounts the fresh cache - copy-then-boot, faster in total and never
# laggy. The detached copier is unchanged underneath; --precache starts it
# early (card pick time) and a stalled or failed copy falls back to booting
# the original exactly as before. dd conv=sparse punches holes for the zero
# blocks, so a 15 GB image lands as only its real data.
#
# PAD_CARD_CACHE=0 turns it off. The stamp file records path+size+mtime of the
# source, but only SIZE+MTIME are the identity (item 34): David keeps
# byte-identical cards at two and three paths, and while the path was part of
# the compare, every launch that alternated paths re-ran the full 7.3 GB copy
# - batman three times for bytes that never changed. A new dump of the same
# title still invalidates: a re-export gets a new size/mtime. The trade: two
# DIFFERENT cards sharing a label AND coincidentally identical size+mtime
# would wrongly share a cache. The path stays in the stamp for debugging, and
# staying with the full-stamp WRITE keeps every pre-fix stamp valid here.
# `rm -rf ~/cardcache` is the whole reclaim story.
cache_stamp() { stat -c "%n %s %Y" "$1" 2>/dev/null; }
# The identity: the stamp's last two fields, taken from the right so a path
# with spaces cannot shift them.
stamp_key() { local s="${1% *}"; echo "${s##* } ${1##* }"; }

# Is the cached copy present with the image's size+mtime? One definition,
# because cache_pick asks it on the way in and cache_wait on the way out.
cache_valid() {   # <img> <copy> <stamp>
    [ -f "$2" ] && [ -f "$3" ] \
        && [ "$(stamp_key "$(cat "$3")")" = "$(stamp_key "$(cache_stamp "$1")")" ]
}

# Is the pid in the pid file OUR copier, alive right now? Two review findings
# killed the old bare `kill -0` here. (1) The pid file survives a WSL restart
# on the ext4 disk, pids restart low, and a long-lived same-user daemon can
# REUSE the recorded pid - kill -0 then reads "running" forever, no copier is
# ever respawned, and every sync boot eats the full stall timeout. (2) The
# GUI's Start runs as ROOT (PAD_PIVOT) while --precache runs as the user;
# kill -0 across that boundary is EPERM, which read as "stale" and spawned a
# DUPLICATE dd over the live one. /proc answers both: the cmdline of any
# user's process is readable, and the copier's argv carries the cache path,
# so identity comes with liveness in one test - and matching THIS label's
# copy path (not just "cardcache") keeps a pid reused by another card's
# copier from reading as ours.
copier_alive() {   # <pidf> <copy>
    local pid
    pid=$(cat "$1" 2>/dev/null) && [ -n "$pid" ] \
        && grep -qsa -- "$2" "/proc/$pid/cmdline"
}

# Any OTHER label's copier live right now? One copier at a time, MACHINE-WIDE:
# the card images live on one spinning disk (repo images/ is a JUNCTION to
# D:\Pinball\images - same files, two spellings), and two concurrent dd
# readers seek-thrash it to ~6 MB/s COMBINED for the pair - live-measured
# 2026-08-23, when a pick-time precache ran beside another copy and D: pegged
# at 100% for minutes with both copies crawling. Prints the other label.
other_copier() {   # <own-copy-path>
    local f c
    for f in "$CACHE"/*.pid; do
        [ -e "$f" ] || continue
        c="${f%.pid}.raw"
        [ "$c" = "$1" ] && continue
        if copier_alive "$f" "$c"; then basename "${f%.pid}"; return 0; fi
    done
    return 1
}

# ITEM 74: wait for the detached copier, narrating progress so the minutes are
# visible - one newline-terminated line every 2 s, because the GUI's drain
# thread and the run log both read LINES (dd's own \r progress never surfaces
# through either). The copier is never killed here: on a stall or a failure
# the boot falls back to the 9p hybrid and the copy keeps going for next time.
# Returns 0 iff the cache is valid when the copier is done.
cache_wait() {   # <img> <copy> <stamp> <pidf>
    local img="$1" copy="$2" stamp="$3" pidf="$4"
    local total tmb done mb pct last=-1 still=0
    total=$(stat -c %s "$img" 2>/dev/null) || return 1
    [ "$total" -gt 0 ] || return 1
    tmb=$(( total / 1048576 ))
    while copier_alive "$pidf" "$copy"; do
        # .partial is written sequentially, so its apparent size tracks the
        # position - EXCEPT inside a run of zeros, where conv=sparse seeks
        # and st_size freezes until real data lands (desk-verified during
        # review). At the measured 139-180 MB/s a false stall needs >30 GB
        # of contiguous zeros, which no card here has; a REAL wedge (dead
        # NAS mid-copy) just waits the full 4 min before falling back.
        done=$(stat -c %s "$copy.partial" 2>/dev/null || echo 0)
        mb=$(( done / 1048576 )); pct=$(( done * 100 / total ))
        echo "[card] copying $(basename "$img"): $mb / $tmb MB ($pct%)" >&2
        if [ "$done" = "$last" ]; then
            still=$(( still + 1 ))
            if [ "$still" -ge 120 ]; then   # 240 s without a byte moving
                echo "[card] copy stalled - booting from the original instead (copy continues)" >&2
                return 1
            fi
        else
            still=0
        fi
        last=$done
        sleep 2
    done
    cache_valid "$img" "$copy" "$stamp"
}

# Prints the path to mount: the cached copy if it is valid, else the original -
# and in the latter case starts the background copy if one is wanted and not
# already running. Mode (arg 3): `sync` (the default) WAITS for that copy with
# progress and mounts the fresh cache when it lands - item 74's pre-copy, which
# replaced booting off 9p WHILE the copy competed for the same reads (177 s to
# first picture, laggy input; measured ~9 s cached and ~60-70 s for the copy
# alone, so copy-then-boot wins on both time and feel). `async` keeps the old
# start-and-return behaviour - used by the already-mounted rejoin (the copy
# only helps the NEXT mount, so blocking a rejoin on it would be pure delay)
# and by --precache. PAD_CARD_PRECOPY=0 forces async everywhere - the escape
# hatch back to the hybrid boot.
cache_pick() {
    local img="$1" label="$2" mode="${3:-sync}"
    local copy="$CACHE/$label.raw" stamp="$CACHE/$label.src"
    if [ "${PAD_CARD_CACHE:-1}" = 0 ]; then echo "$img"; return; fi
    [ "${PAD_CARD_PRECOPY:-1}" = 0 ] && mode=async
    if cache_valid "$img" "$copy" "$stamp"; then
        echo "[card] using local cache $copy" >&2
        echo "$copy"; return
    fi
    mkdir -p "$CACHE"
    give_back "$CACHE"
    # One copier at a time per label. The pid file is the lock; a stale one
    # (machine rebooted mid-copy) is detected by the pid being gone.
    local pidf="$CACHE/$label.pid"
    if copier_alive "$pidf" "$copy"; then
        echo "[card] local cache copy already in progress" >&2
    else
        local other
        if other=$(other_copier "$copy"); then
            if [ "$mode" = async ]; then
                # A warm-up must never join a seek storm - it can wait for
                # any next occasion. A BOOT (sync) is the user asking now,
                # so it proceeds under a warning instead.
                echo "[card] not pre-caching: $other is already copying (one copier at a time)" >&2
                echo "$img"; return
            fi
            echo "[card] WARNING: $other is copying too - both copies will crawl on one disk" >&2
        fi
        echo "[card] caching $(basename "$img") to the WSL disk in the background" >&2
        echo "[card]   (first run only; next boot of this card is native speed)" >&2
        # setsid, for the same reason fuse2fs gets it below: this shell is
        # frequently a `wsl -e bash -c` child, and when that session ends its
        # process group goes with it - the first copier died at 0 bytes this
        # exact way, silently, with its pid file still claiming progress.
        #
        # The copier's stdout/stderr MUST also be redirected away from the
        # caller's: run_game.sh and watch.sh read this script through $(...),
        # which waits for EOF on the pipe - a background child still holding
        # it open would stall the whole run until the copy finished, which is
        # the exact opposite of the point. Progress goes to a log beside the
        # cache.
        setsid bash -c '
            img="$1"; copy="$2"; stamp="$3"; pidf="$4"
            rm -f "$copy.partial"
            # The size gate on the way out is load-bearing: two copiers can
            # only exist through a broken lock, but if they ever do they
            # share the .partial NAME, and an mv would publish the OTHER
            # copier in-flight file under a stamp cache_valid accepts.
            # Never publish a file that is not the whole image.
            if dd if="$img" of="$copy.partial" bs=4M conv=sparse status=none \
               && [ "$(stat -c %s "$copy.partial" 2>/dev/null)" = \
                    "$(stat -c %s "$img" 2>/dev/null)" ]; then
                mv "$copy.partial" "$copy"
                stat -c "%n %s %Y" "$img" > "$stamp"
                # A root (PAD_PIVOT) run hands the finished copy back to the
                # desktop user, same as give_back() - inlined because this
                # runs detached, long after the parent script has exited.
                if [ "$(id -u)" = 0 ]; then
                    o=$(stat -c %U "$HOME" 2>/dev/null)
                    [ -n "$o" ] && [ "$o" != root ] && \
                        chown "$o" "$copy" "$stamp" 2>/dev/null
                fi
                echo "[card] local cache of $(basename "$img") complete"
            else
                rm -f "$copy.partial"
                echo "[card] local cache copy FAILED (disk full?); runs still work off D:"
            fi
            rm -f "$pidf"
        ' _ "$img" "$copy" "$stamp" "$pidf" \
            </dev/null >> "$CACHE/$label.log" 2>&1 &
        echo $! > "$pidf"
        give_back "$pidf" "$CACHE/$label.log"
    fi
    if [ "$mode" = sync ]; then
        if cache_wait "$img" "$copy" "$stamp" "$pidf"; then
            echo "[card] local cache ready - booting from it" >&2
            echo "$copy"; return
        fi
        echo "[card] cache not usable - booting from the original" >&2
    fi
    echo "$img"
}

# fuse2fs and libfuse2, unpacked into a private prefix. Downloaded once; after
# that this is offline. Ubuntu splits them into two packages and fuse2fs links
# libfuse.so.2 (not the libfuse3 the distro ships), hence both.
ensure_fuse2fs() {
    # A PROPERLY INSTALLED fuse2fs WINS, and asking first is the whole fix.
    # The private-prefix download below exists for one situation - a machine
    # where this rig has no root and fuse2fs is not installed - and it was
    # being taken unconditionally, so a machine that HAD fuse2fs still went to
    # the network for its own copy. In the container it then failed outright:
    # the image drops apt's package lists, so `apt-get download` had nothing to
    # resolve against and the run died at "could not get fuse2fs" on a box with
    # fuse2fs already in it.
    if command -v fuse2fs >/dev/null 2>&1; then
        FUSE2FS=$(command -v fuse2fs)
        return 0
    fi
    [ -x "$FUSE2FS" ] && [ -e "$PREFIX/lib/x86_64-linux-gnu/libfuse.so.2" ] && return 0
    echo "[card] fetching fuse2fs into $PREFIX (once)"
    mkdir -p "$PREFIX" /tmp/cardpkg || return 1
    ( cd /tmp/cardpkg && apt-get download fuse2fs libfuse2t64 >/dev/null 2>&1 ) || {
        echo "[card] apt-get download failed - no network?" >&2; return 1; }
    for d in /tmp/cardpkg/*.deb; do dpkg-deb -x "$d" "$PREFIX" || return 1; done
    [ -x "$FUSE2FS" ] || return 1
    return 0
}

# The games partition. It is p3 on every Spike 2 card seen - 8 GB and 16 GB,
# 2019 titles and 2024 ones - but the start sector is read rather than assumed,
# because a wrong offset does not fail, it mounts something else.
# WHERE THE GAMES PARTITION IS. Asked of parts.py, which every other script
# that reaches into a card already asks - rootfs.sh, getboot.sh, gethex.sh.
#
# THIS USED TO BE A SECOND IMPLEMENTATION, and it was the weaker one: it shelled
# out to `/sbin/fdisk -l` and matched the human-readable output with awk on
# three conditions at once - the device name ending in "3", the image path
# appearing on the line, and the last field being the word "Linux". It assumed
# the games partition is the THIRD, where parts.py identifies it by what is
# inside it. In the container it simply printed nothing, and the run died with
# "no third Linux partition" against a card whose partitions parts.py had
# listed correctly seconds earlier.
#
# Two scripts defining one fact is the thing this rig's own rules forbid.
games_offset() {
    python3 "$SELF/parts.py" --games "$1" 2>/dev/null
}

# The title directory inside the partition: the one holding a `game` ELF. The
# card also has spk/ and the three symlinks the machine itself uses.
title_dir() {
    local m="$1" d
    for d in "$m"/*; do
        [ -f "$d/game" ] && [ ! -L "$d" ] && { basename "$d"; return 0; }
    done
    return 1
}

IMG=${1:-}
[ -n "$IMG" ] || die "usage: cardmount.sh <card.raw> [--umount|--precache]"
[ -f "$IMG" ] || die "no image at $IMG"
LABEL=$(basename "$IMG"); LABEL=${LABEL%%.Release*}; LABEL=${LABEL%%.raw}
MNT="$CARDS/$LABEL"

if [ "${2:-}" = "--umount" ]; then
    fusermount -u "$MNT" 2>/dev/null || fusermount3 -u "$MNT" 2>/dev/null
    rmdir "$MNT" 2>/dev/null
    echo "[card] unmounted $MNT"
    exit 0
fi

# ITEM 74: start (or join) the background copy and return - no mount, no wait.
# The Emulate tab fires this the moment a card is PICKED, so by the time Start
# is pressed the copy is done or well along, and the boot's sync wait in
# cache_pick collects whatever remains. Idempotent: a valid cache just prints
# "using local cache", a copy already running prints that it is.
if [ "${2:-}" = "--precache" ]; then
    # Never start a 7 GB dd beside a live run - the copy would fight the
    # run's 9p reads, which is the exact contention item 74 removed. Checked
    # HERE rather than only in the GUI, because the GUI's run-is-up flag is
    # blind at startup (the first status poll has not answered when a
    # restored card path fires this) and blind to terminal-started runs.
    if pgrep -x game >/dev/null 2>&1 || pgrep -x padglhost >/dev/null 2>&1; then
        echo "[card] a run is up - not pre-caching" >&2
        exit 0
    fi
    cache_pick "$IMG" "$LABEL" async >/dev/null
    exit 0
fi

# A STALE MOUNT POINT IS NOT AN EMPTY ONE. If fuse2fs has died, the directory
# is still a mountpoint with nothing behind it and every read returns an error
# instead of a file - which is indistinguishable from a working mount until
# something tries to read. Clear it before deciding anything else.
# THE SAME TEST ALSO CATCHES A MOUNT THIS USER MAY NOT READ: FUSE denies every
# user but the mounter by default - root included - so a root (PAD_PIVOT) run
# finding the desktop user's old plain-`ro` mount reads it as "stale" and
# remounts it below, with allow_other this time, which is exactly the right
# outcome. The message covers both.
# The [ -d ] || grep pair covers two distinct corpses. A mount whose fuse2fs
# died politely still stats as a directory ([ -d ] true, contents unreadable).
# A mount whose fuse2fs was SIGKILLED (killgame at app quit) is a DEAD
# ENDPOINT: stat itself fails with ENOTCONN, so [ -d ] is FALSE and the first
# test can never fire - item 74's confirming run died on exactly that, with
# mkdir -p failing on the corpse. The kernel still lists the mount, so
# /proc/self/mounts is the detector that survives; spaces in the path appear
# there \040-escaped (the savestate rig learned this the hard way).
MNT_ESC=$(printf %s "$MNT" | sed 's/ /\\040/g')
if ! ls "$MNT" >/dev/null 2>&1 \
   && { { [ -d "$MNT" ] && mountpoint -q "$MNT" 2>/dev/null; } \
        || grep -qs " $MNT_ESC " /proc/self/mounts; }; then
    echo "[card] mount at $MNT is unreadable (fuse2fs gone, or another user's) - remounting"
    fusermount -u "$MNT" 2>/dev/null || fusermount3 -u "$MNT" 2>/dev/null
    umount -l "$MNT" 2>/dev/null
fi

# Already mounted and healthy? Then say so and stop - remounting a live card
# under a running game is not something to do by accident. The cache copy is
# still worth STARTING though: the mount in use stays on whatever it was
# mounted from, and the next mount picks the local copy up. Without this, a
# card mounted before the cache feature ever ran would stay slow forever.
if [ -d "$MNT" ] && mountpoint -q "$MNT" 2>/dev/null; then
    T=$(title_dir "$MNT") || die "$MNT is mounted but holds no game"
    # async: the mount in use stays on whatever it was mounted from, so the
    # copy only helps the NEXT mount - a rejoin must not block on it (item 74).
    cache_pick "$IMG" "$LABEL" async >/dev/null
    # The kernel too, item 62 - see the fresh-mount path below for the whole
    # story. getboot's stamp makes this free when it already matches, and a
    # rejoined mount is exactly the case where someone else likely staged it.
    bash "$RIG/getboot.sh" "$IMG" "$ROOT" 1>&2 || \
        echo "[card] getboot failed - the game will raise VALIDATION ERROR #3" >&2
    echo "[card] already mounted: $MNT"
    echo "$MNT/$T"
    exit 0
fi

ensure_fuse2fs || die "could not get fuse2fs"
# Mount the local cache when there is a valid one; start building it when not.
SRC=$(cache_pick "$IMG" "$LABEL")
OFF=$(games_offset "$SRC")
[ -n "$OFF" ] || die "no third Linux partition in $(basename "$SRC")"
mkdir -p "$MNT" || die "cannot create $MNT"

echo "[card] mounting $(basename "$SRC") p3 at offset $OFF (read only)"
# A ROOT MOUNT MUST CARRY allow_other, and only root may add it freely: FUSE
# denies everyone but the mounting user by default, and a PAD_PIVOT session
# (item 13) is root mounting a card that DAVID's helpers then read - the
# video host opens clips straight off this mount, and without allow_other
# every one of those opens is EACCES and the screen is black with no error
# anywhere. An ordinary user run keeps the plain options: user_allow_other
# is not on in /etc/fuse.conf and does not need to be.
MOPTS="ro,offset=$OFF"
[ "$(id -u)" = 0 ] && MOPTS="$MOPTS,allow_other"
give_back "$CARDS" "$MNT"
# setsid, AND THAT IS THE WHOLE POINT OF IT. fuse2fs keeps running for as long
# as the mount exists, so it must NOT be in the caller's process group:
# watch.sh tears a run down by killing process groups, and that killed the
# mount out from under the game it had just started. The symptom is the worst
# kind - the game boots, loads a few assets, then sits at "Startup In
# Progress" forever, because its files stopped existing halfway through. There
# is no error anywhere; every read simply fails.
setsid "$FUSE2FS" -o "$MOPTS" "$SRC" "$MNT" >/dev/null 2>&1 \
    || die "fuse2fs refused $(basename "$SRC")"
# setsid returns as soon as the daemon has forked, so wait for the mount to
# actually appear rather than racing the first read of it.
for _ in $(seq 1 40); do mountpoint -q "$MNT" 2>/dev/null && break; sleep 0.05; done
mountpoint -q "$MNT" 2>/dev/null || die "fuse2fs did not mount $(basename "$SRC")"

T=$(title_dir "$MNT") || {
    fusermount -u "$MNT" 2>/dev/null
    die "mounted, but no directory in it holds a game ELF"
}

# THE KERNEL THE GAME VALIDATES COMES FROM THIS CARD TOO (item 62). getboot.sh
# used to run from exactly one place - rootfs.sh, at rootfs BUILD time - so
# /mnt/boot/zImage was the build card's (godzilla's) forever, and every other
# title raised GAME VALIDATION ERROR #3: the ZK track hashes the whole file
# and its provider treats a bad hash and a missing file as the same state, so
# a wrong kernel reads exactly like no kernel. Staging here, on the mount that
# every card run goes through (watch.sh and run_game.sh both), gives the game
# the bytes its own card ships - nothing is faked, it hashes them itself.
# From $IMG and not $SRC, although $SRC is the faster disk: the copier's dd
# does not preserve the original's mtime, so the cache copy's size+mtime is a
# DIFFERENT identity from the original's, and staging from one while the
# rejoin path checks the other would restage on every alternate mount. The
# original's size+mtime is the identity David's own copies share (item 34:
# the same card at three paths, same mtime), the read is a few MB once per
# card, and the stamp makes every later call free. Failure is a warning and
# not a die: a run with the wrong kernel banner is degraded, a run refused
# over it would be worse.
bash "$RIG/getboot.sh" "$IMG" "$ROOT" 1>&2 || \
    echo "[card] getboot failed - the game will raise VALIDATION ERROR #3" >&2

echo "[card] title: $T"
echo "$MNT/$T"
