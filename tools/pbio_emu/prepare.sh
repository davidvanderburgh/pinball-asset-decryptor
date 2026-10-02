#!/bin/bash
# prepare.sh <file> [<file>...] - make a runnable build from Pinball
# Brothers files, cached; prints `build=<dir>` last.  As root.
#
#   *.iso   a Clonezilla restore ISO (clonezilla-live-alien40.iso): the
#           machine's whole disk.  Its root partition - Buildroot Linux with
#           the game under /game/<title> - is restored once to
#           $PBIO_CACHE/os-<name>/root.img and loop-mounted read-only.
#   *.upd   an update (plain tar.gz of game/<title>/...; a full one carries
#           the media, a delta only what changed).  Unpacked once to
#           $PBIO_CACHE/upd-<name>/tree and laid over what comes before it.
#
# The files stack in the order given.  With no ISO among them the machine's
# OS comes from $PBIO_OS (an ISO), else from an OS already prepared, else
# from a clonezilla-live-*.iso beside the first update - every title runs on
# the same Buildroot image (their programs need nothing it lacks), so
# Alien's restore ISO can carry ABBA.  The build must end up with the game's
# media: a delta update on its own (Queen's pbq0210G.upd without
# clonezilla-live-queen20d.iso under it) is refused.
#
# Exit: 0 ok, 2 bad args / not root, 3 no disk space, 4 not a title this rig
# knows (pbiotitles.py), 5 no game in it / damaged.
set -u -o pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/pbiopath.sh"
[ "$(id -u)" = 0 ] || { echo "prepare.sh: run as root" >&2; exit 2; }
[ $# -ge 1 ] || { echo "usage: prepare.sh <iso|upd> [<upd>...]" >&2; exit 2; }
mkdir -p "$PBIO_CACHE"

need_space() {      # <bytes>: refuse (exit 3) if /var/tmp has less free
    local free; free=$(df -B1 --output=avail "$PBIO_ROOT" | tail -1)
    if [ "$free" -lt "$1" ]; then
        echo "prepare.sh: not enough disk space: need $(( $1 >> 20 )) MB, have $(( free >> 20 )) MB" >&2
        exit 3
    fi
}
stem() { local b; b=$(basename "$1"); echo "${b%.*}" | tr -c 'A-Za-z0-9._\n-' _; }

# The root partition of a Clonezilla ISO -> os-<name>/root.img, mounted.
prep_os() {
    local iso=$1 key d m img parts p best bsize s
    key=os-$(stem "$iso"); d=$PBIO_CACHE/$key
    if [ ! -f "$d/root.img" ]; then
        m=$PBIO_ROOT/isomnt.$$; mkdir -p "$m" "$d"
        mount -o loop,ro "$iso" "$m" || { echo "prepare.sh: cannot mount $iso" >&2; exit 5; }
        img=$(ls -d "$m"/home/partimag/*/ 2>/dev/null | head -1)
        if [ -z "$img" ]; then
            umount "$m"; rmdir "$m"
            echo "prepare.sh: $iso is not a Clonezilla image (no home/partimag)" >&2; exit 5
        fi
        # the biggest partition is the root (Alien: sda1 boot 60 MB, sda2
        # root 3.3 GB, sda3 logs 488 MB)
        best=; bsize=0
        for p in $(cat "$img/parts"); do
            s=$(stat -c %s "$img/$p".*-img.* 2>/dev/null | awk '{t += $1} END {print t + 0}')
            [ "$s" -gt "$bsize" ] && { best=$p; bsize=$s; }
        done
        [ -n "$best" ] || { umount "$m"; echo "prepare.sh: no partition images in $img" >&2; exit 5; }
        # the partition's size, from the image's partition table
        s=$(sed -n "s|^/dev/$best .*size= *\([0-9]*\).*|\1|p" "$img"/*-pt.sf 2>/dev/null | head -1)
        need_space $(( ${s:-0} * 512 + (256 << 20) ))
        echo "Restoring $best from $(basename "$iso")..." >&2
        local f; f=$(ls "$img/$best".*-img.* | head -1)
        local unz="pigz -dc"
        case "$f" in *.zst.*) unz="zstd -dc" ;; *.xz.*) unz="xz -dc" ;; *.bz2.*) unz="bzip2 -dc" ;; esac
        if echo "$f" | grep -q '\.dd-ptcl-img\.'; then
            # dd-ptcl: a raw copy of the partition, compressed and split.
            # Written sparse: Queen's is 22 GB, most of it zeros.
            cat "$img/$best".dd-ptcl-img.* | $unz |
                dd of="$d/root.img.partial" bs=1M conv=sparse iflag=fullblock status=none
        else
            cat "$img/$best".*-ptcl-img.* | $unz |
                partclone.restore -C -s - -O "$d/root.img.partial" --restore_raw_file -q
        fi
        s=$?
        umount "$m"; rmdir "$m"
        [ "$s" = 0 ] || { rm -f "$d/root.img.partial"; echo "prepare.sh: restore failed" >&2; exit 5; }
        mv "$d/root.img.partial" "$d/root.img"
        basename "$iso" > "$d/source"
    fi
    mkdir -p "$d/mnt"
    mountpoint -q "$d/mnt" || mount -o loop,ro "$d/root.img" "$d/mnt" ||
        { echo "prepare.sh: $d/root.img will not mount" >&2; exit 5; }
    ls "$d"/mnt/game/*/pinprog >/dev/null 2>&1 ||
        { echo "prepare.sh: no game in $(basename "$iso")'s root partition" >&2; exit 5; }
    echo "$d/mnt"
}

# An update -> upd-<name>/tree
prep_upd() {
    local upd=$1 key d
    key=upd-$(stem "$upd"); d=$PBIO_CACHE/$key
    if [ ! -d "$d/tree/game" ]; then
        rm -rf "$d"; mkdir -p "$d/tree.partial"
        need_space $(( $(stat -c %s "$upd") * 11 / 10 ))
        echo "Unpacking $(basename "$upd")..." >&2
        # members are "./game/..." or "game/..." (both occur); the rest of
        # an update (init scripts, its installer) is the machine's, and the
        # rig uses only game/
        tar -xzf "$upd" -C "$d/tree.partial" 2>/dev/null
        find "$d/tree.partial" -mindepth 1 -maxdepth 1 ! -name game -exec rm -rf {} +
        [ -d "$d/tree.partial/game" ] ||
            { rm -rf "$d"; echo "prepare.sh: $(basename "$upd") is not a PB update (tar.gz with game/)" >&2; exit 5; }
        mv "$d/tree.partial" "$d/tree"
        basename "$upd" > "$d/source"
    fi
    echo "$d/tree"
}

OS=; LAYERS=(); NAMES=()
for f in "$@"; do
    [ -f "$f" ] || { echo "prepare.sh: no such file: $f" >&2; exit 2; }
    case "${f,,}" in
        *.iso) OS=$(prep_os "$f" | tail -1) || exit $?; NAMES+=("$(stem "$f")") ;;
        *.upd) L=$(prep_upd "$f" | tail -1) || exit $?; LAYERS=("$L" "${LAYERS[@]}"); NAMES+=("$(stem "$f")") ;;
        *) echo "prepare.sh: not a PB file (.iso or .upd): $f" >&2; exit 4 ;;
    esac
done
if [ -z "$OS" ]; then
    if [ -n "${PBIO_OS:-}" ]; then
        OS=$(prep_os "$PBIO_OS" | tail -1) || exit $?
    else
        IMG=$(ls -t "$PBIO_CACHE"/os-*/root.img 2>/dev/null | head -1)
        if [ -n "$IMG" ]; then
            OS=$(dirname "$IMG")/mnt; mkdir -p "$OS"
            mountpoint -q "$OS" || mount -o loop,ro "$IMG" "$OS" || exit 5
        else
            ISO=$(ls "$(dirname "$1")"/clonezilla-live-*.iso 2>/dev/null | head -1)
            [ -n "$ISO" ] || { echo "prepare.sh: no machine OS: give a Clonezilla restore ISO (or PBIO_OS=<iso>)" >&2; exit 5; }
            OS=$(prep_os "$ISO" | tail -1) || exit $?
        fi
    fi
fi

# Which title: the top-most layer with a game/<dir>/pinprog
TITLE=
for L in "${LAYERS[@]}" "$OS"; do
    TITLE=$(python3 "$PBIO_TOOLS/pbiotitles.py" detect "$L")
    [ -n "$TITLE" ] && break
    if ls "$L"/game/*/pinprog >/dev/null 2>&1; then
        echo "prepare.sh: $(ls -d "$L"/game/*/ | xargs -n1 basename | head -1): a Pinball Brothers title this rig has no profile for yet" >&2
        exit 4
    fi
done
[ -n "$TITLE" ] || { echo "prepare.sh: no game in these files" >&2; exit 5; }
DIR=$(python3 "$PBIO_TOOLS/pbiotitles.py" get "$TITLE" dir)
# the media must be somewhere in the stack (a delta update carries none)
MEDIA=0
for L in "${LAYERS[@]}" "$OS"; do
    [ -d "$L/game/$DIR/media" ] && [ -d "$L/game/$DIR/audio" ] && MEDIA=1
done
[ "$MEDIA" = 1 ] || { echo "prepare.sh: no $DIR media in these files - a delta update needs the full update or the restore ISO under it" >&2; exit 5; }

B=$PBIO_CACHE/build-$(IFS=+; echo "${NAMES[*]}")
mkdir -p "$B"

# Fonts.  A machine's fonts come with its factory image, and an update
# does not carry them again (ABBA's full 1.41 has no media/fonts), but
# vidprog dies on the first one it cannot open.  Every font it names that
# no layer has is filled in from another title in the same OS image (the
# same file name - PB reuses them: bonus.ttf, Danger.ttf...), else from a
# stand-in bold sans, listed in <build>/fonts.
FILL=$B/fontfill/game/$DIR/media/fonts
rm -rf "$B/fontfill" "$B/fonts"
VID=
for L in "${LAYERS[@]}" "$OS"; do
    [ -f "$L/game/$DIR/vidprog" ] && { VID=$L/game/$DIR/vidprog; break; }
done
for f in $(strings -n 6 "$VID" 2>/dev/null | sed -n 's|^fonts/\([A-Za-z0-9_.-]*\.ttf\)$|\1|p' | sort -u); do
    have=0
    for L in "${LAYERS[@]}" "$OS"; do [ -f "$L/game/$DIR/media/fonts/$f" ] && have=1; done
    [ "$have" = 1 ] && continue
    src=$(ls "$OS"/game/*/media/fonts/"$f" 2>/dev/null | head -1)
    how="from $(echo "$src" | sed 's|.*/game/\([^/]*\)/.*|\1|')"
    if [ -z "$src" ]; then
        src=$(ls /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf "$OS"/game/*/media/fonts/UbuntuMono-B.ttf 2>/dev/null | head -1)
        how="STAND-IN $(basename "$src")"
    fi
    [ -n "$src" ] || continue
    mkdir -p "$FILL"
    cp "$src" "$FILL/$f"
    echo "$f $how" >> "$B/fonts"
    echo "font $f: $how"
done
if [ -d "$FILL" ]; then LAYERS+=("$B/fontfill"); fi

printf '%s\n' "${LAYERS[@]}" "$OS" > "$B/layers"
echo "$TITLE" > "$B/title"
echo "title=$TITLE"
echo "build=$B"
