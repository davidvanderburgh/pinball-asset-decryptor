#!/bin/bash
# cardmount.sh <card.raw> [--part N] [--umount] - mount a Spike 2 card's games
# partition, READ ONLY, WITHOUT ROOT, so a title can be run without extracting
# 6 GB first.
#
#   cardmount.sh .../jaws_le-1_02_0.Release.16G.sdcard.raw
#   -> $HOME/card/jaws_le-1_02_0   (and prints the title directory)
#
#   cardmount.sh multi.raw --part 7
#   -> $HOME/card/multi.p7         (item 90: partition N of a multi-image card;
#                                   the default is the FIRST games partition, p3,
#                                   and --part N mounts any other one beside it,
#                                   sharing the same local cache copy)
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
# are the same string however the two scripts were invoked. killgame.sh unmounts
# what /proc/self/mounts lists under $PAD_CARDS; if this mounted under a different $HOME the
# unmount would silently match nothing, which is exactly the bug padpath.sh's
# header describes. Sourced from padpath.sh, which resolves it once.
. "$SELF/padpath.sh"
PREFIX=$PAD_HOME/local
CARDS=$PAD_CARDS          # per rig slot (padpath.sh): a slot unmounts only its own
# THE SHARED CARD STORE (PAD-651): when /mnt/wsl/cards is mounted (cardstore.ps1: one ext4 disk file on the NVMe,
# attached to the WSL VM by name, so EVERY distro sees it), the cache lives there - one cache for the sessions'
# Ubuntu, the app's runtime and the app's data disk, sized for the newest build of every title. Without it (a
# machine without the store, a reboot before the logon task ran) the cache is $PAD_HOME/cardcache as it always was.
# PAD_CARD_CACHE_DIR names another.
if [ -n "${PAD_CARD_CACHE_DIR:-}" ]; then
    CACHE=$PAD_CARD_CACHE_DIR
elif [ -d /mnt/wsl/cards/cardcache ] && mountpoint -q /mnt/wsl/cards 2>/dev/null; then
    CACHE=/mnt/wsl/cards/cardcache
else
    CACHE=$PAD_HOME/cardcache
fi
# THE LIBRARY STAYS (PAD-727). The store was filled with the newest build of every title on 2026-10-20 and the
# eviction below was plain least-recently-booted, so four days of older versions and custom builds booted on purpose
# pushed 37 newest builds out of it - and the next 53-build sweep copied them off D: again (PAD-723). An entry whose
# image sits directly in the library folder and still has the stamp it was copied with is now never evicted, not by
# the copier making room and not by the app's 30-day clean-up (--cache-list says which). A newer build replacing
# it, or the image moving to `older versions`, makes it an ordinary entry again. PAD_CARD_LIBRARY names another
# folder; a machine without that folder pins nothing and the cache works as it always did.
LIBRARY=${PAD_CARD_LIBRARY:-/mnt/d/Pinball/images/Stern/spike2}
# The space the copier leaves free. On a distro's own disk that space is the distro's (cardstage.sh asks 30 GB);
# the store holds nothing but the cache, so it keeps only a margin - with the library pinned in it, that margin is
# the difference between an older version cached and one booted where it lies.
if [ "$CACHE" = /mnt/wsl/cards/cardcache ]; then
    CACHE_KEEP_GB=${PAD_STORE_KEEP_FREE_GB:-2}
else
    CACHE_KEEP_GB=${PAD_CACHE_KEEP_FREE_GB:-8}
fi
FUSE2FS="$PREFIX/usr/bin/fuse2fs"
# Both library directories, because the packages unpacked into $PREFIX put
# their libraries in /lib up to 24.04 and in /usr/lib from 26.04 (PAD-437).
export LD_LIBRARY_PATH="$PREFIX/lib/x86_64-linux-gnu:$PREFIX/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"

die() { echo "[card] $*" >&2; exit 1; }

# HAND FILES BACK when this runs as root (a PAD_PIVOT session - item 13).
# Everything here lives under the DESKTOP USER's home, and a root-owned
# stamp/cache/mountpoint in their directory is the same trap watch.sh already
# fixes for its logs: the next ordinary run cannot overwrite it. No-op for a
# normal user run.
#
# THIS WAS A LOCAL COPY THAT ASKED `stat -c %U "$HOME"`, and under `sudo` $HOME
# is /root - which root owns, so the copy returned having chowned nothing on
# exactly the runs that needed it (PAD-182). padpath.sh's pad_give_back is the
# one definition and asks $PAD_HOME, which is the home this rig belongs to
# however the script was reached. Kept as a name because five call sites read
# better with the short one.
give_back() { pad_give_back "$@"; }

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
# blocks, so a 15 GB image lands as only its real data - and since PAD-484
# cardcopy.py reads only that data too (each ext partition's used blocks,
# by its own bitmaps): ~25 s an 8 GB card off D: instead of 1-2 minutes.
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

# Is this cache entry the library's? Its .src names the image it was copied from; the entry is pinned when that
# image is a file directly in $LIBRARY (by either spelling: the repo's images/ is a junction to the same folder) and
# still has the entry's stamp.
cache_pinned() {   # <label>
    local s img lib
    s=$(cat "$CACHE/$1.src" 2>/dev/null) || return 1
    img=${s% * *}
    lib=$(readlink -f "$LIBRARY" 2>/dev/null) && [ -n "$lib" ] && [ -d "$lib" ] || return 1
    [ "$(readlink -f "$(dirname "$img")" 2>/dev/null)" = "$lib" ] || return 1
    cache_valid "$img" "$CACHE/$1.raw" "$CACHE/$1.src"
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

# Is any mount of this label live - the games mount at $CARDS/<label> OR one
# of the per-partition ones at $CARDS/<label>.pN (item 90: a PAD_SELECT run
# mounts every games partition of a multi-image card beside the first)? ONE
# test, because both the cache manager's eviction guard and --cache-drop ask
# it, and a check that saw only the plain directory would evict the cache
# copy out from under a live .p7 mount.
label_mounted() {   # <label>
    local m
    for m in "$CARDS/$1" "$CARDS/$1".p*; do
        mountpoint -q "$m" 2>/dev/null && return 0
    done
    return 1
}

# Is the cached copy in use ANYWHERE (PAD-739)? label_mounted sees only THIS rig slot's mounts ($CARDS is per slot),
# so a card booted in rig 2 read as free to a delete from the Emulate tab (slot 0). Every reader of a copy - the
# fuse2fs that mounts it, a live copier - has the copy's path as one whole argument, so /proc answers for every slot.
# Read in-shell (read -d ''), never by a grep whose own argv would carry the path and match itself. One pass lists
# every argument naming a file in the cache; --cache-list takes it once (CACHE_READERS) rather than once a card.
cache_readers() {
    local f a
    for f in /proc/[0-9]*/cmdline; do
        while IFS= read -r -d '' a; do
            case $a in "$CACHE"/*) printf '%s\n' "$a" ;; esac
        done < "$f" 2>/dev/null
    done
}
cache_in_use() {   # <label>
    local c="$CACHE/$1.raw" r
    label_mounted "$1" && return 0
    r=${CACHE_READERS-$(cache_readers)}
    case $'\n'"$r"$'\n' in *$'\n'"$c"$'\n'*|*$'\n'"$c.partial"$'\n'*) return 0 ;; esac
    return 1
}

# Where the entry's image stands (PAD-739), for the Cache window and the clean-ups:
#   ok           the image is there with the entry's stamp - the copy is what a boot of it uses
#   changed      the image is there but rebuilt or replaced since (or the entry has no stamp): never used again
#   gone         its folder is there but the file is not (deleted or renamed): never used again unless it comes back
#   unreachable  its folder is not there either (a drive not attached, a share offline): may be used again
cache_source_state() {   # <label>
    local s img
    s=$(cat "$CACHE/$1.src" 2>/dev/null) || { echo changed; return; }
    img=${s% * *}
    if [ -f "$img" ]; then
        cache_valid "$img" "$CACHE/$1.raw" "$CACHE/$1.src" && echo ok || echo changed
    elif [ -d "$(dirname "$img")" ]; then
        echo gone
    else
        echo unreachable
    fi
}

# THE CACHE'S OWN SIZE LIMIT (PAD-739). cache_make_room evicted only when `df` said the disk was nearly full - and on
# a distro's own disk `df` reports the VIRTUAL size of its ext4.vhdx (1 TB by default), not the Windows drive behind
# it. So on a machine without the store nothing was ever evicted: a user's ~/cardcache reached 150 GB over a month of
# custom Godzilla builds, the distro disk 226 GB on C:. A limit on what the cache itself holds is the bound df cannot
# give. `cardmount.sh --cache-limit N` saves it beside the cache (.limit_gb, 0 = none); without one it is 64 GB on a
# distro disk (PAD_CACHE_MAX_GB) and none on the store, which is its own sized disk holding nothing else.
cache_limit_gb() {
    local v
    v=$(tr -dc 0-9 2>/dev/null < "$CACHE/.limit_gb")
    if [ -n "$v" ]; then echo $((10#$v)); return; fi
    if [ "$CACHE" = /mnt/wsl/cards/cardcache ]; then echo 0; else echo "${PAD_CACHE_MAX_GB:-64}"; fi
}
cache_used_kb() {
    local u
    u=$(du -ck "$CACHE"/*.raw "$CACHE"/*.raw.partial 2>/dev/null | tail -1 | cut -f1)
    echo "${u:-0}"
}

# ITEM 77: never start a copy the disk cannot hold - the cache was measured
# at 125 GB real (half the WSL disk) with 29 GB free and NOTHING pruning it.
# Frees space by evicting the least-recently-BOOTED entries first (the .boot
# sidecar; a missing one falls back to the copy's own mtime, which makes
# never-booted strays and pre-item-77 entries the first to go). Never evicts
# the label being copied, a mounted label, one whose copier is live, or the
# library's (cache_pinned, PAD-727); an entry whose image is gone or changed
# can never be booted from again and goes before any other.
# `need` is what the copy can really take: the image's ALLOCATED bytes when
# its filesystem reports them (drvfs does, for NTFS), else its apparent size.
# The copy is sparse (cardcopy.py, or `dd conv=sparse`), so it never lands bigger than what the
# original allocates. Apparent size alone was wrong by 22 GB for a card built
# for a 32 GB SD card (card_size.py: 30.4 GB apparent, 8.5 GB allocated) -
# more than the whole work disk, so merely PICKING it evicted every other
# cached card and then ran off the original anyway. Returns 1 when even
# eviction cannot make room; the boot then runs off the original and nothing
# half-lands. CACHE_KEEP_GB is the floor the rest of the disk keeps
# (PAD_CACHE_KEEP_FREE_GB, default 8, on a distro's disk; 2 on the store).
# PAD-739: it also keeps the cache under its own size limit (cache_limit_gb), because on a distro's disk df is the
# virtual disk's and never ran short; and a copy that never finished goes first of all.
# PAD-816: AND THE WINDOWS DRIVE BEHIND IT. The same virtual-size df let a 14.7 GB copy start on a machine whose C:
# had a few GB left: the vhdx could not grow, ext4 hit a failed write at 3.6 GB and remounted the WHOLE distro
# read-only, and nothing in WSL worked again until a restart. The app names that drive (PAD_HOST_DRIVE, the drvfs
# mount of the drive ext4.vhdx is on); its free space, plus what this call has evicted (freed blocks inside the vhdx
# are reused before it grows - and if they were handed back to Windows instead, df of the drive shows them), is the
# room a copy really has. PAD_HOST_KEEP_FREE_GB (4) stays free for Windows. Not on the store, whose disk is its own.
host_free_kb() {
    [ -n "${PAD_HOST_DRIVE:-}" ] && [ "$CACHE" != /mnt/wsl/cards/cardcache ] || return 1
    df -k --output=avail "$PAD_HOST_DRIVE" 2>/dev/null | tail -1 | tr -d " " | grep -E '^[0-9]+$'
}
cache_make_room() {   # <img> <own-copy-path>
    local need keep free f vlabel vboot victim oldest size alloc pinned limit used over why
    local host0 hnow hroom hkeep evicted=0 hshort=0
    size=$(stat -c %s "$1" 2>/dev/null || echo 0)
    alloc=$(( $(stat -c '%b * %B' "$1" 2>/dev/null || echo 0) ))
    if [ "$alloc" -gt 0 ] && [ "$alloc" -lt "$size" ]; then
        need=$(( alloc / 1024 ))
    else
        need=$(( size / 1024 ))
    fi
    keep=$(( CACHE_KEEP_GB * 1048576 ))
    limit=$(( $(cache_limit_gb) * 1048576 ))
    host0=$(host_free_kb) || host0=""
    hkeep=$(( ${PAD_HOST_KEEP_FREE_GB:-4} * 1048576 ))
    while :; do
        free=$(df -k --output=avail "$CACHE" 2>/dev/null | tail -1 | tr -d " ")
        [ -n "$free" ] || return 0             # df unreadable: do not guess
        hshort=0
        if [ -n "$host0" ]; then
            hnow=$(host_free_kb) || hnow=$host0
            hroom=$(( host0 + evicted ))
            [ "$hnow" -gt "$hroom" ] && hroom=$hnow
            # The Windows drive's own floor, carried into the ext4 terms the checks below use.
            hroom=$(( hroom - hkeep + keep ))
            if [ "$hroom" -lt "$free" ]; then free=$hroom; hshort=1; fi
        fi
        over=0
        if [ "$limit" -gt 0 ]; then
            used=$(cache_used_kb)
            [ $(( used + need )) -gt "$limit" ] && over=1
        fi
        [ $(( free - need )) -ge "$keep" ] && [ "$over" = 0 ] && return 0
        victim=""; oldest=0; pinned=0
        # A copy that never finished (WSL shut down or the copier killed mid-copy) is a .partial with no .raw and no
        # live copier: --cache-list never showed it and nothing took it, up to 15 GB each (PAD-739). First out.
        for f in "$CACHE"/*.raw.partial; do
            [ -e "$f" ] || break
            vlabel=$(basename "$f" .raw.partial)
            [ "$CACHE/$vlabel.raw" = "$2" ] && continue
            [ -e "$CACHE/$vlabel.raw" ] && continue
            cache_in_use "$vlabel" && continue
            copier_alive "$CACHE/$vlabel.pid" "$CACHE/$vlabel.raw" && continue
            victim="$vlabel"; oldest=0; why="a copy that never finished"
            break
        done
        [ -n "$victim" ] || for f in "$CACHE"/*.raw; do
            [ -e "$f" ] || break
            [ "$f" = "$2" ] && continue
            vlabel=$(basename "$f" .raw)
            cache_in_use "$vlabel" && continue
            copier_alive "$CACHE/$vlabel.pid" "$f" && continue
            if cache_pinned "$vlabel"; then pinned=$((pinned + 1)); continue; fi
            case $(cache_source_state "$vlabel") in
                changed|gone) vboot=0 ;;       # its image is gone or changed: dead weight, first out
                # ok, or unreachable (a drive not attached: it may boot again once it is) - by its last boot
                *) vboot=$(stat -c %Y "$CACHE/$vlabel.boot" 2>/dev/null \
                           || stat -c %Y "$f" 2>/dev/null) || continue ;;
            esac
            if [ -z "$victim" ] || [ "$vboot" -lt "$oldest" ]; then
                victim="$vlabel"; oldest="$vboot"
            fi
        done
        if [ -z "$victim" ]; then
            if [ $(( free - need )) -ge "$keep" ]; then
                # only the limit is unmet, by cards in use or the library's: the disk has the room, so cache anyway
                if [ "$over" = 1 ]; then
                    echo "[card] the cache is over its $(( limit / 1048576 )) GB limit and nothing else can go - in use, or the library's ($pinned)${1:+ - caching anyway}" >&2
                fi
                return 0
            fi
            if [ "$hshort" = 1 ]; then
                echo "[card] the Windows drive behind WSL ($PAD_HOST_DRIVE) is too full to cache this card ($(awk "BEGIN { printf \"%.1f\", $hnow / 1048576 }") GB free, want $(( (need + hkeep) / 1048576 )) GB) - running off the original. Free space there and the next boot caches it." >&2
                return 1
            fi
            echo "[card] disk too full to cache ($(( free / 1048576 )) GB free, want $(( (need + keep) / 1048576 )) GB) and nothing evictable ($pinned library cards kept) - running off the original" >&2
            return 1
        fi
        if [ -n "${why:-}" ]; then
            :
        elif [ "$oldest" = 0 ]; then
            why="its image is gone or changed"
        else
            why="least recently booted"
        fi
        if [ "$over" = 1 ] && [ $(( free - need )) -ge "$keep" ]; then
            echo "[card] evicting cached $victim ($why) to keep the cache under its $(( limit / 1048576 )) GB limit" >&2
        else
            echo "[card] evicting cached $victim ($why) to make room" >&2
        fi
        why=""
        evicted=$(( evicted + $(du -ck "$CACHE/$victim.raw" "$CACHE/$victim.raw.partial" 2>/dev/null | tail -1 | cut -f1) ))
        rm -f "$CACHE/$victim.raw" "$CACHE/$victim.raw.partial" \
              "$CACHE/$victim.src" "$CACHE/$victim.log" \
              "$CACHE/$victim.boot" "$CACHE/$victim.pid"
    done
}

# ITEM 74: wait for the detached copier, narrating progress so the minutes are
# visible - one newline-terminated line every 2 s, because the GUI's drain
# thread and the run log both read LINES (dd's own \r progress never surfaces
# through either). The copier is never killed here: on a stall or a failure
# the boot falls back to the 9p hybrid and the copy keeps going for next time.
# THE COPY IS ON THE BOARD (PAD-649). David: "indicate on rig pills when card copies are ongoing and the
# percentage of them". While a card is copied into the cache the board (pad_board_dir, beside the rigs' locks)
# carries copy-<label>.json - {"label","card","who","slot","distro","state","done_mb","total_mb","pct","updated"}
# - rewritten every 2 s by cache_wait below and removed at its end; cardstage.sh asks for a "queued" one
# (--board-copy queued) while it waits for the machine's one copy lock. The triage dashboard and the Emulate tab
# tie it to the rig whose lock says it waits for that card (rigbatch names the label there) and show "copying
# Dungeons And Dragons LE 1.10 19%" on the pill. A record nobody has touched for 90 s is stale and ignored.
copy_board_file() { echo "$(pad_board_dir)/copy-$1.json"; }
copy_board_write() {   # <label> <img> <state> <done-bytes> <total-bytes>
    local f d pct=0
    f=$(copy_board_file "$1"); d=$(dirname "$f")
    mkdir -p "$d" 2>/dev/null || return 0
    [ "$5" -gt 0 ] 2>/dev/null && pct=$(( $4 * 100 / $5 ))
    printf '{"label":"%s","card":"%s","who":"%s","slot":%s,"distro":"%s","state":"%s","done_mb":%s,"total_mb":%s,"pct":%s,"updated":%s}\n' \
        "$1" "$(basename "$2")" "$(pad_label 2>/dev/null | tr -d '"\\' | cut -c1-40)" "${PAD_SLOT:-0}" \
        "${WSL_DISTRO_NAME:-$(uname -n)}" "$3" $(( $4 / 1048576 )) $(( $5 / 1048576 )) "$pct" "$(date +%s)" \
        > "$f.tmp" 2>/dev/null && mv -f "$f.tmp" "$f" 2>/dev/null
    return 0
}
copy_board_clear() { rm -f "$(copy_board_file "$1")" "$(copy_board_file "$1").tmp" 2>/dev/null; return 0; }

# Returns 0 iff the cache is valid when the copier is done.
cache_wait() {   # <img> <copy> <stamp> <pidf>
    local img="$1" copy="$2" stamp="$3" pidf="$4"
    local total tmb done mb pct last=-1 still=0 label
    label=$(basename "$copy" .raw)
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
        copy_board_write "$label" "$img" copying "$done" "$total"
        if [ "$done" = "$last" ]; then
            still=$(( still + 1 ))
            if [ "$still" -ge 120 ]; then   # 240 s without a byte moving
                echo "[card] copy stalled - booting from the original instead (copy continues)" >&2
                copy_board_clear "$label"
                return 1
            fi
        else
            still=0
        fi
        last=$done
        sleep 2
    done
    copy_board_clear "$label"
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
        # Last-boot clock for the cache manager (item 77): atime is useless
        # here (relatime, plus whole-tree scans touch everything), so a BOOT
        # stamps a sidecar. Sync only - a --precache hit is not a boot and
        # must not freshen the entry against LRU eviction.
        [ "$mode" = sync ] && touch "$CACHE/$label.boot" 2>/dev/null
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
        if ! cache_make_room "$img" "$copy"; then
            echo "$img"; return
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
            img="$1"; copy="$2"; stamp="$3"; pidf="$4"; self="$5"
            rm -f "$copy.partial"
            # PAD-484: only what the card USES is read (cardcopy.py: the ext
            # partitions by their own bitmaps, the rest whole) - about half
            # of a Spike 2 image, and every byte of it comes off D: through
            # 9p. Anything it cannot do, it says so and the plain copy runs.
            if [ "${PAD_CARD_COPY_USED:-1}" != 0 ] && \
               python3 "$self/cardcopy.py" "$img" "$copy.partial"; then
                :
            else
                rm -f "$copy.partial"
                dd if="$img" of="$copy.partial" bs=4M conv=sparse status=none
            fi
            # The size gate on the way out is load-bearing: two copiers can
            # only exist through a broken lock, but if they ever do they
            # share the .partial NAME, and an mv would publish the OTHER
            # copier in-flight file under a stamp cache_valid accepts.
            # Never publish a file that is not the whole image.
            if [ -f "$copy.partial" ] \
               && [ "$(stat -c %s "$copy.partial" 2>/dev/null)" = \
                    "$(stat -c %s "$img" 2>/dev/null)" ]; then
                mv "$copy.partial" "$copy"
                stat -c "%n %s %Y" "$img" > "$stamp"
                # A root (PAD_PIVOT) run hands the finished copy back to the
                # desktop user, same as give_back() - inlined because this
                # runs detached, long after the parent script has exited.
                # $PAD_HOME and not $HOME, for the reason pad_give_back gives:
                # under sudo $HOME is /root and this chowned nothing (PAD-182).
                # padpath.sh exports PAD_HOME, so this inner sh inherits it.
                # (No apostrophes in here - this whole body is one
                # single-quoted string, and one would end it.)
                if [ "$(id -u)" = 0 ]; then
                    o=$(stat -c %U "$PAD_HOME" 2>/dev/null)
                    [ -n "$o" ] && [ "$o" != root ] && \
                        chown "$o" "$copy" "$stamp" 2>/dev/null
                fi
                echo "[card] local cache of $(basename "$img") complete"
            else
                rm -f "$copy.partial"
                echo "[card] local cache copy FAILED (disk full?); runs still work off D:"
            fi
            rm -f "$pidf"
        ' _ "$img" "$copy" "$stamp" "$pidf" "$SELF" \
            </dev/null >> "$CACHE/$label.log" 2>&1 &
        echo $! > "$pidf"
        give_back "$pidf" "$CACHE/$label.log"
    fi
    if [ "$mode" = sync ]; then
        if cache_wait "$img" "$copy" "$stamp" "$pidf"; then
            echo "[card] local cache ready - booting from it" >&2
            touch "$CACHE/$label.boot" 2>/dev/null
            echo "$copy"; return
        fi
        echo "[card] cache not usable - booting from the original" >&2
    fi
    echo "$img"
}

# fuse2fs and libfuse2, unpacked into a private prefix. Downloaded once; after
# that this is offline. Ubuntu splits them into two packages, and up to 24.04
# fuse2fs links libfuse.so.2 (not the libfuse3 the distro ships), hence both.
# 26.04's fuse2fs links libfuse3, so there the library download is skipped
# (PAD-437, ensure_fuse2fs).
#
# ONE OF THE TWO IS SPELLED DIFFERENTLY ON EVERY RELEASE BUT THIS ONE, and
# this used to name 24.04's spelling alone. The t64 transition renamed
# `libfuse2` to `libfuse2t64` in noble, so on 22.04 - a supported LTS, and the
# release a user is on until the day they upgrade - that name resolves to
# nothing. Both names went to apt in ONE `apt-get download`, which is
# all-or-nothing, so the name this release does not have downloaded NEITHER
# package; and apt's own "Unable to locate package" went to /dev/null, leaving
# the person with "no network?" about a machine whose network is fine.
#
# So: one package at a time, each spelling tried until one resolves, and
# whatever apt said is what is printed when none of them do. `fuse2fs` itself
# is spelled the same on both releases (checked against Ubuntu's own file
# index, not assumed), so it is a one-name list and stays a list anyway - the
# next rename is not going to announce itself either.
PAD_FUSE2FS_PKGS=${PAD_FUSE2FS_PKGS:-"fuse2fs"}
PAD_LIBFUSE2_PKGS=${PAD_LIBFUSE2_PKGS:-"libfuse2t64 libfuse2"}

#: Does <binary> still have the libraries it was linked against? The private
#: prefix below outlives a distro upgrade and the .so files it was filled from
#: may not, which is the same trap pad_criu_runs describes: an executable file
#: that cannot start. `ldd` honours the LD_LIBRARY_PATH exported above, so it
#: asks the question the way the run will ask it, and a machine with no `ldd`
#: at all answers "fine" rather than losing its card mount to a missing
#: diagnostic.
_resolves() {
    [ -x "$1" ] || return 1
    ! ldd "$1" 2>/dev/null | grep -q "not found"
}

#: Download the first of <names> this release publishes, into $PWD. Prints
#: what apt said about EVERY name when none of them resolve - which is the
#: sentence a person can act on, and the one this used to throw away.
_apt_download_first() {
    local name out all=
    for name in "$@"; do
        out=$(apt-get download "$name" 2>&1) && return 0
        all="$all$name: $out
"
    done
    printf '%s' "$all" | sed 's/^/[card]   /' >&2
    return 1
}

#: Unpack every .deb in <dir> into $PREFIX, deleting each once it is in, so
#: the next download into the same directory is all the next call unpacks.
_unpack_debs() {   # <dir>
    local d
    for d in "$1"/*.deb; do
        [ -e "$d" ] || continue
        dpkg-deb -x "$d" "$PREFIX" || return 1
        rm -f "$d"
    done
}

#: The download, into the empty directory <dir>: fuse2fs first, then the
#: library ONLY IF the binary it brought cannot find one. Up to 24.04 fuse2fs
#: links libfuse.so.2, which a stock install does not have. 26.04's links the
#: system's libfuse3, which the fuse3 prerequisite already installs, so
#: fetching libfuse2 there was a second slow download of a file nothing opens.
_fetch_fuse2fs() {   # <dir>
    ( cd "$1" && _apt_download_first $PAD_FUSE2FS_PKGS ) || {
        echo "[card] could not download fuse2fs (tried: $PAD_FUSE2FS_PKGS)" >&2
        return 1; }
    _unpack_debs "$1" || return 1
    [ -x "$FUSE2FS" ] || {
        echo "[card] that package unpacked, and it does not hold $FUSE2FS" >&2
        return 1; }
    _resolves "$FUSE2FS" && return 0
    ( cd "$1" && _apt_download_first $PAD_LIBFUSE2_PKGS ) || {
        echo "[card] could not download libfuse.so.2 (tried:" \
             "$PAD_LIBFUSE2_PKGS)" >&2
        return 1; }
    _unpack_debs "$1"
}

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
    # ...and the private copy, IF IT STILL RUNS. `-x` alone kept a prefix
    # filled on the release this machine used to be on: the file is there, the
    # library it wants is not, and the mount died in the dynamic linker rather
    # than here where it can be re-fetched.
    #
    # AND ldd IS THE WHOLE TEST, because the "(once)" below was never true on
    # Ubuntu 26.04 (PAD-437). This also demanded
    # $PREFIX/lib/x86_64-linux-gnu/libfuse.so.2 by name, which is where 22.04's
    # and 24.04's packages put it. 26.04's packages put their libraries under
    # /usr/lib, and its fuse2fs does not link libfuse.so.2 at all, so that file
    # never existed: every Start went back to apt for both packages, and on a
    # slow mirror the run sat on the boot selector's line for 44 s, and past
    # 100 s once, before the card mounted. "Does the binary find every library
    # it links" is the question that path stood in for, and ldd answers it for
    # every layout.
    _resolves "$FUSE2FS" && return 0
    # On stderr, so the line is in the log WHILE the download runs: watch.sh
    # reads stdout through $(...) and republishes it only once the mount is
    # done, which put this line after the wait it explains. And it says how
    # long that wait can be: one package took 51 s from archive.ubuntu.com
    # on 2026-10-07, both together 135 s.
    echo "[card] fetching fuse2fs into $PREFIX (once; a download from Ubuntu, which can take a minute or two)" >&2
    # ...AND THIS ACCOUNT MAY WRITE THERE. Asked BEFORE the download, because
    # what a root-owned prefix produces otherwise is twenty lines of tar
    # ("Cannot open: File exists", "Cannot utime: Operation not permitted"),
    # then `dpkg-deb: error: tar subprocess failed`, then "could not get
    # fuse2fs" - and not one of them says the directory belongs to root
    # (PAD-182). An elevated run that made this prefix now hands it back
    # below, so this is only ever reached on a machine one already poisoned.
    pad_can_write "$PREFIX" card || return 1
    mkdir -p "$PREFIX" || return 1
    # A FRESH DIRECTORY FOR EVERY FETCH. This was one shared /tmp/cardpkg and
    # every .deb in it was unpacked: a root (PAD_PIVOT) fetch left it
    # root-owned for the next ordinary run's download to fail in, and a .deb an
    # earlier fetch left there (another version, another release) was unpacked
    # again, in name order, over the one just downloaded.
    local pkgs ok=0
    pkgs=$(mktemp -d "${TMPDIR:-/tmp}/cardpkg.XXXXXX") || return 1
    _fetch_fuse2fs "$pkgs" && ok=1
    rm -rf "$pkgs"
    # RECURSIVE, because this is a whole unpacked tree and not a stamp: a root
    # fetch used to leave every file in it owned by root, and the next ordinary
    # run could then neither re-fetch nor repair it (PAD-182). Handed back on a
    # failed fetch too, since a half-unpacked tree is the same trap.
    pad_give_back -R "$PREFIX"
    [ "$ok" = 1 ] || return 1
    # Still a library short? Then name it. Passing this on to the mount is how
    # it used to go: "fuse2fs refused <card>", and no word about what for.
    _resolves "$FUSE2FS" && return 0
    echo "[card] fuse2fs is here but cannot start; it needs:" >&2
    ldd "$FUSE2FS" 2>&1 | grep "not found" | sed 's/^[[:space:]]*/[card]   /' >&2
    return 1
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
#
# ITEM 90's MULTI LAYOUT (mkmulticard.py --layout multi): p7 is one ext4 whose
# root holds img1/, img2/ ... - each a COMPLETE games tree, so the title dir
# sits one level down. For such a partition this prints the FIRST imgN that
# holds a title (`img1`), never `img1/<title>`: the last line of this script
# is "$MNT/<that>", and watch.sh takes its dirname to find the mount to tear
# down - a two-component answer would leave the FUSE mount behind. run_game.sh
# resolves the subdirectory it actually wants from parts.py --list-games.
title_dir() {
    local m="$1" d s
    for d in "$m"/*; do
        # the title's own `game` is a FILE; a store card's img1/ (item 95)
        # sits beside the title with a `game` SYMLINK, and sorts before it
        [ -f "$d/game" ] && [ ! -L "$d/game" ] && [ ! -L "$d" ] && { basename "$d"; return 0; }
    done
    for d in "$m"/img[0-9]*; do
        [ -d "$d" ] && [ ! -L "$d" ] || continue
        for s in "$d"/*; do
            [ -f "$s/game" ] && [ ! -L "$s" ] && { basename "$d"; return 0; }
        done
    done
    return 1
}

# ITEM 77: cache-manager queries. No image argument and no mount - these are
# what the Emulate tab's Card cache dialog shells. Tab-separated so a label
# or source path may carry spaces (the source is LAST for the same reason).
if [ "${1:-}" = "--cache-dir" ]; then     # where the cache is (the shared store when mounted; PAD-651)
    echo "$CACHE"; exit 0
fi
if [ "${1:-}" = "--cache-list" ]; then
    # entry <TAB> label <TAB> real_kb <TAB> apparent_kb <TAB> boot_epoch <TAB> source
    # pinned <TAB> label   - after its entry when it is the library's (PAD-727): a line of its own, so a reader
    #                        that knows only `entry` lines reads the same rows
    # state <TAB> label <TAB> source-state <TAB> use <TAB> copied_epoch     (PAD-739, after its entry)
    #                        source-state: cache_source_state; use: mounted|copying|- ; copied_epoch: the copy's
    #                        own mtime, the last-used stand-in for a card never booted
    # leftover <TAB> label <TAB> real_kb <TAB> mtime <TAB> use   (PAD-739) a copy that never finished, or sidecars
    #                        whose card is gone: no .raw. use: copying|-
    # limit <TAB> limit_gb <TAB> used_kb <TAB> dir <TAB> store|distro   (PAD-739)
    CACHE_READERS=$(cache_readers)
    for f in "$CACHE"/*.raw; do
        [ -e "$f" ] || break
        l=$(basename "$f" .raw)
        rk=$(du -k "$f" 2>/dev/null | cut -f1)
        ak=$(( $(stat -c %s "$f" 2>/dev/null || echo 0) / 1024 ))
        b=$(stat -c %Y "$CACHE/$l.boot" 2>/dev/null || echo 0)
        s=$(cat "$CACHE/$l.src" 2>/dev/null); s=${s% * *}
        printf 'entry\t%s\t%s\t%s\t%s\t%s\n' "$l" "${rk:-0}" "$ak" "$b" "$s"
        cache_pinned "$l" && printf 'pinned\t%s\n' "$l"
        if copier_alive "$CACHE/$l.pid" "$f"; then u=copying
        elif cache_in_use "$l"; then u=mounted
        else u=-; fi
        printf 'state\t%s\t%s\t%s\t%s\n' "$l" "$(cache_source_state "$l")" "$u" "$(stat -c %Y "$f" 2>/dev/null || echo 0)"
    done
    for f in "$CACHE"/*.raw.partial "$CACHE"/*.src "$CACHE"/*.log "$CACHE"/*.boot "$CACHE"/*.pid; do
        [ -e "$f" ] || continue
        case $f in *.raw.partial) l=$(basename "$f" .raw.partial) ;; *) l=$(basename "${f%.*}") ;; esac
        [ -e "$CACHE/$l.raw" ] && continue
        case " ${seen:-} " in *" $l "*) continue ;; esac
        seen="${seen:-} $l"
        rk=$(du -ck "$CACHE/$l.raw.partial" "$CACHE/$l.src" "$CACHE/$l.log" "$CACHE/$l.boot" "$CACHE/$l.pid" \
             2>/dev/null | tail -1 | cut -f1)
        m=$(stat -c %Y "$CACHE/$l.raw.partial" "$CACHE/$l.log" "$CACHE/$l.src" "$CACHE/$l.boot" 2>/dev/null \
            | sort -rn | head -1)
        if copier_alive "$CACHE/$l.pid" "$CACHE/$l.raw" || cache_in_use "$l"; then u=copying; else u=-; fi
        printf 'leftover\t%s\t%s\t%s\t%s\n' "$l" "${rk:-0}" "${m:-0}" "$u"
    done
    if [ "$CACHE" = /mnt/wsl/cards/cardcache ]; then k=store; else k=distro; fi
    printf 'limit\t%s\t%s\t%s\t%s\n' "$(cache_limit_gb)" "$(cache_used_kb)" "$CACHE" "$k"
    df -k --output=avail,size "$CACHE" 2>/dev/null | tail -1 \
        | awk '{printf "disk\t%s\t%s\n", $1, $2}'
    exit 0
fi
if [ "${1:-}" = "--cache-drop" ]; then
    l="${2:-}"; [ -n "$l" ] || die "usage: cardmount.sh --cache-drop <label>"
    case $l in */*|.|..) die "not a cache label: $l" ;; esac
    c="$CACHE/$l.raw"
    # cache_in_use and not label_mounted alone: a card mounted by another rig slot is in use too (PAD-739)
    cache_in_use "$l" && die "$l is in use by a running emulator - not dropping"
    copier_alive "$CACHE/$l.pid" "$c" && die "$l is being copied - not dropping"
    rm -f "$c" "$c.partial" "$CACHE/$l.src" "$CACHE/$l.log" \
          "$CACHE/$l.boot" "$CACHE/$l.pid" 2>/dev/null
    # Say so when a file stayed (a root-owned one in a sticky folder, a read-only disk): the window reports it
    # rather than counting the space as freed (PAD-739).
    for f in "$c" "$c.partial" "$CACHE/$l.src" "$CACHE/$l.log" "$CACHE/$l.boot" "$CACHE/$l.pid"; do
        [ -e "$f" ] && die "could not delete $(basename "$f") (permission denied?)"
    done
    echo "[card] dropped cached $l"
    exit 0
fi
if [ "${1:-}" = "--cache-limit" ]; then
    # --cache-limit            prints the limit in GB (0 = none)
    # --cache-limit N|default  saves it (default: back to 64 GB on a distro disk, none on the store) and evicts
    #                          to it now, by the copier's own rule: never a card in use, being copied or the library's
    v="${2:-}"
    if [ -z "$v" ]; then cache_limit_gb; exit 0; fi
    mkdir -p "$CACHE" || die "no cache folder $CACHE"
    case $v in
        default) rm -f "$CACHE/.limit_gb" ;;
        *[!0-9]*) die "usage: cardmount.sh --cache-limit [GB|default]" ;;
        *) echo "$((10#$v))" > "$CACHE/.limit_gb" || die "could not save the limit in $CACHE" ;;
    esac
    give_back "$CACHE/.limit_gb" 2>/dev/null
    echo "[card] cache limit $(cache_limit_gb) GB (0 = none)"
    cache_make_room "" "" || true
    exit 0
fi

IMG=${1:-}
[ -n "$IMG" ] || die "usage: cardmount.sh <card.raw> [--part N] [--umount|--precache|--cache-now] | --cache-list | --cache-drop <label> | --cache-limit [GB|default]"
[ -f "$IMG" ] || die "no image at $IMG"

# ★ A STERN SPIKE 3 CARD CANNOT BE MOUNTED - REFUSE IT BEFORE THE COPY (PAD-367).
# Spike 3 (CM4 generation: Walking Dead Remastered, Star Wars 2025, Pokemon)
# encrypts every data partition as LUKS2/AES-XTS with a key fused into the
# machine's SoC, not written to the card - so fuse2fs refuses its "games"
# partition as not-ext4, and there is nothing on the card to decrypt it with.
# Checked here, before cache_pick, so a 60 GB copy is not made only to fail the
# mount: this one guard covers the pick-time --precache, the sweep's
# --cache-now and the Start-time mount alike. parts.py reads only the MBR and a
# few partition magics; if it or python3 is missing the check is skipped and
# the mount fails as before.
if command -v python3 >/dev/null 2>&1 \
   && S3=$(python3 "$SELF/parts.py" --spike3 "$IMG" 2>/dev/null) \
   && [ "${S3#spike3: yes}" != "$S3" ]; then
    die "$(basename "$IMG") is a Stern Spike 3 card (${S3#spike3: yes - }). Its partitions are encrypted (LUKS2) with a key kept in the machine, not on the card, so PAD cannot mount or emulate it."
fi

LABEL=$(basename "$IMG"); LABEL=${LABEL%%.Release*}; LABEL=${LABEL%%.raw}
MNT="$CARDS/$LABEL"
# ITEM 90: `--part N` mounts partition N (kernel numbering: p3 is the first
# games partition, p7 the first appended one on a multi-image card) at its
# OWN directory, $CARDS/<label>.pN, so the first games partition's mount at
# $CARDS/<label> - which every existing card run uses - is never disturbed
# and the two can be live side by side. The cache copy is shared: it is keyed
# by the label, so the second mount of one image finds the copy the first
# one waited for. Without --part nothing below changes.
PART=""
MODE=${2:-}
if [ "$MODE" = "--part" ]; then
    PART=${3:-}
    case "$PART" in
        ''|*[!0-9]*) die "usage: cardmount.sh <card.raw> --part N [--umount|--precache]" ;;
    esac
    MNT="$CARDS/$LABEL.p$PART"
    MODE=${4:-}
fi

if [ "$MODE" = "--umount" ]; then
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
# PAD-484: cache it NOW and wait - no mount. rigbatch's stager (cardstage.sh
# `cache`) runs this a few builds ahead of the rigs, so every job's own mount
# finds a valid copy on the WSL disk and boots at native speed: Godzilla Pro
# 1.16 reached attract in 23 s from the cache against 79-130 s from the same
# card on C: (9p under fuse2fs: the validator's and the scene loader's reads
# are latency-bound there). Unlike --precache it does not stand down beside a
# live run - the runs it stages for read their own copies, not 9p. Prints the
# path a boot would use: the copy, or the original when it could not be made.
if [ "$MODE" = "--cache-now" ]; then
    PAD_CARD_CACHE=1 cache_pick "$IMG" "$LABEL" sync
    exit 0
fi
# --board-copy queued|clear: the board's copy record for this card (PAD-649; the comment at copy_board_write).
# "queued" says a copy is wanted and waits its turn for the machine's one copy lock (cardstage.sh); "clear"
# removes the record. A card already in the cache gets no record either way.
if [ "$MODE" = "--board-copy" ]; then
    case "${3:-}" in
        queued)
            if ! cache_valid "$IMG" "$CACHE/$LABEL.raw" "$CACHE/$LABEL.src"; then
                copy_board_write "$LABEL" "$IMG" queued 0 "$(stat -c %s "$IMG" 2>/dev/null || echo 0)"
            fi ;;
        clear) copy_board_clear "$LABEL" ;;
        *) die "usage: cardmount.sh <card.raw> --board-copy queued|clear" ;;
    esac
    exit 0
fi
if [ "$MODE" = "--precache" ]; then
    # Never start a 7 GB dd beside a live run - the copy would fight the
    # run's 9p reads, which is the exact contention item 74 removed. Checked
    # HERE rather than only in the GUI, because the GUI's run-is-up flag is
    # blind at startup (the first status poll has not answered when a
    # restored card path fires this) and blind to terminal-started runs.
    if [ -n "$(pad_pids -x game)" ] || [ -n "$(pad_pids -x padglhost)" ]; then
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
if [ -n "$PART" ]; then
    # By NUMBER, not by contents (item 90): the caller has already asked
    # parts.py --list-games which partitions hold a game, and this is the one
    # it chose. parts.py walks the EBR chain, so p7 and up resolve too.
    OFF=$(python3 "$SELF/parts.py" --part "$PART" "$SRC" 2>/dev/null)
    [ -n "$OFF" ] || die "no partition $PART in $(basename "$SRC")"
else
    OFF=$(games_offset "$SRC")
    [ -n "$OFF" ] || die "no third Linux partition in $(basename "$SRC")"
fi
# AND SAY WHY IT CANNOT BE CREATED. `mkdir: Permission denied` followed by
# "[card] cannot create /home/ales/card/<title>" is where PAD-182's reporter's
# run ENDED, twice, on a machine whose only fault was a root-owned ~/card left
# by one elevated start - and between them those two lines name the path, the
# syscall and nothing that could be acted on. pad_can_write names the owner and
# the chown; the die below still ends the run, because an unmountable card is
# the end of it.
# A disk gone read-only under the cache copy (PAD-816) lands here first: name it, not the mount point.
if pad_disk_readonly; then pad_disk_readonly_say card; die "cannot create $MNT"; fi
pad_can_write "$MNT" card || die "cannot create $MNT"
mkdir -p "$MNT" || die "cannot create $MNT"

echo "[card] mounting $(basename "$SRC") p${PART:-3} at offset $OFF (read only)"
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
