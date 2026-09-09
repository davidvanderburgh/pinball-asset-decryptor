#!/bin/bash
# rootfs.sh <card.raw> - build the guest rootfs that every run chroots into.
#
#   wsl -e bash <rig>/rootfs.sh /mnt/d/.../godzilla_pro-1_15_0....sdcard.raw
#
# THIS IS THE ONE STEP A FRESH CHECKOUT COULD NOT DO. `run_game.sh` chroots into
# $PAD_ROOT and nothing in the repository created it: the recipe lived in a
# gitignored planning document, so cloning this rig gave you every script and no
# filesystem to run them against.
#
# It needs NO ROOT. `debugfs` reads the ext4 image directly - no loop device, no
# mount, no sudo - and the boot partition is walked in Python by getboot.sh.
#
# WHAT GOES WRONG IF YOU DO THIS THE OBVIOUS WAY, both learned the hard way:
#
#   * **Extracting to a Windows path silently drops every symlink.** `/mnt/c`
#     is drvfs and cannot hold them, so `ld-linux.so.3` simply vanishes and
#     nothing in the guest links. The destination must be on the WSL ext4 disk,
#     which is why $PAD_ROOT defaults under $HOME and why this refuses a /mnt
#     path outright rather than producing a rootfs that fails later and
#     elsewhere.
#   * **`rdump /` of the OS partition is not the whole job.** The kernel the
#     game validates lives on the BOOT partition (FAT), which `rdump` of the OS
#     partition obviously never touches; without it the game raises GAME
#     VALIDATION ERROR #3. getboot.sh is therefore part of this script and not
#     an optional extra.
#
# THE TITLE ITSELF IS NOT EXTRACTED HERE, on purpose. `PAD_CARD=<image>
# watch.sh` runs a title straight off the card through a read-only FUSE mount
# (cardmount.sh) in about a second, where extracting one copies 3-6 GB. So this
# builds the OS and stops; pass --game <name> if you want a title on the WSL
# disk as well, which is worth it only for a title you run constantly.
set -u
. "$(dirname "$0")/padpath.sh"

IMG=""
WANT_GAME=""
FORCE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --game) WANT_GAME=${2:-}; shift 2 ;;
        --force) FORCE=1; shift ;;
        -h|--help) sed -n '2,36p' "$0"; exit 0 ;;
        *) IMG=$1; shift ;;
    esac
done
IMG=${IMG:-${PAD_CARD:-}}

[ -n "$IMG" ] || {
    echo "usage: rootfs.sh <card.raw> [--game <title>] [--force]" >&2
    echo "       PAD_ROOT=<dir> to build somewhere other than $ROOT" >&2
    exit 1
}
[ -f "$IMG" ] || { echo "[rootfs] no card image at $IMG" >&2; exit 1; }

# WHAT MAKES A DESTINATION BAD IS ITS FILESYSTEM, NOT ITS PATH.
#
# This refused any $ROOT under /mnt, which was a fair shorthand for "a Windows
# drive" while /mnt/c and its siblings were the only things mounted there.  It
# stopped being one the day the app gave the rigs a data disk of their own:
# that is an ext4 volume attached to the WSL VM by name, so it appears at
# /mnt/wsl/paddata in every distro - a real Linux filesystem, holding symlinks
# perfectly - and this refused it, which meant the emulator would not start at
# all on the arrangement the app now sets up by default.
#
# So ask the filesystem.  `findmnt -T` answers for a path that does not exist
# yet by walking up to the mount that will hold it, which is the normal case
# here since $ROOT is about to be created; the loop is for the machines where
# even the parent is missing, and `stat -f` is the fallback for a distro
# without findmnt.
#
# AND NOT BY TRYING TO MAKE A SYMLINK, which was the other obvious test and is
# wrong: on this Windows the drives are 9p rather than drvfs, and 9p DOES
# create a symlink when asked.  The reason to stay off it is that the extract
# does not survive the round trip, not that the syscall fails.
_pad_fstype() {
    _d=$1
    while [ ! -d "$_d" ] && [ "$_d" != / ]; do _d=$(dirname "$_d"); done
    _t=$(findmnt -no FSTYPE -T "$_d" 2>/dev/null | tail -1)
    [ -n "$_t" ] || _t=$(stat -f -c %T "$_d" 2>/dev/null)
    echo "$_t"
}

ROOT_FS=$(_pad_fstype "$ROOT")
case "$ROOT_FS" in
    9p|v9fs|drvfs|virtiofs|cifs|smb3|smbfs|nfs|nfs4)
        echo "[rootfs] REFUSING: $ROOT is on a Windows or network filesystem" >&2
        echo "[rootfs] ($ROOT_FS), which does not carry an extracted rootfs" >&2
        echo "[rootfs] intact - ld-linux.so.3 would vanish and nothing in the" >&2
        echo "[rootfs] guest would link. Put PAD_ROOT on the WSL disk." >&2
        exit 1 ;;
    # ★ AND RAM, WHICH THE /mnt RULE USED TO CATCH BY ACCIDENT AND THE
    # FILESYSTEM RULE ABOVE LET THROUGH.
    #
    # /mnt/wsl IS A TMPFS. The data disk is an ext4 volume attached over the
    # top of it at /mnt/wsl/paddata, and the app hands the rig that path
    # whenever the disk FILE exists - not whenever it is attached. A WSL
    # restart drops the mount and leaves the file, so the next Start writes
    # into the tmpfs underneath: the extracted rootfs and then the card cache,
    # several GB, into memory. The old "refuse anything under /mnt" shorthand
    # stopped that with a clear message; replacing it with a filesystem test
    # that has no tmpfs in it turned a refusal into a silent multi-GB write
    # into RAM, on the arrangement the app sets up by default.
    #
    # It is also just wrong on its own terms, disk or no disk: a rootfs on
    # tmpfs is gone at the next restart, so every run would re-extract it.
    tmpfs|ramfs)
        echo "[rootfs] REFUSING: $ROOT is in MEMORY ($ROOT_FS), not on a disk." >&2
        case "$ROOT" in
            /mnt/wsl/*)
                echo "[rootfs] That path is the emulator's work disk, and it is" >&2
                echo "[rootfs] NOT ATTACHED right now - /mnt/wsl is a tmpfs, so" >&2
                echo "[rootfs] this run would put the rootfs and the card cache" >&2
                echo "[rootfs] in RAM and lose them at the next WSL restart." >&2
                echo "[rootfs] Attach it again from the app (the Emulate tab" >&2
                echo "[rootfs] re-attaches it), or restart WSL and try again." >&2 ;;
            *)
                echo "[rootfs] A rootfs there does not survive a restart, so the" >&2
                echo "[rootfs] guest would re-extract on every run. Point" >&2
                echo "[rootfs] PAD_ROOT at a real filesystem." >&2 ;;
        esac
        exit 1 ;;
esac

command -v debugfs >/dev/null 2>&1 || {
    echo "[rootfs] debugfs is not installed: apt-get install e2fsprogs" >&2
    exit 1
}

# "ALREADY POPULATED" MEANS THE GUEST CAN START A PROGRAM, not that a directory
# exists. `[ -d "$ROOT/lib" ]` was the test, and lib/ is made early in the
# extraction - so an extraction that stopped part way (a full disk, a closed
# terminal, a WSL restart) made this script congratulate itself forever after,
# and every run then died on `chroot: failed to run command '/bin/sh'`. The
# same question, asked the same way, is what ensurebuild.sh refuses to run
# against; padpath.sh owns it so there is one answer and not two.
INCOMPLETE=$(pad_guest_missing)
if [ -z "$INCOMPLETE" ] && [ "$FORCE" = 0 ]; then
    echo "[rootfs] $ROOT already looks populated - pass --force to rebuild"
    exit 0
fi
if [ -n "$INCOMPLETE" ] && [ -d "$ROOT/lib" ]; then
    echo "[rootfs] $ROOT is missing $INCOMPLETE - the last extraction did not"
    echo "[rootfs] finish. Extracting again."
fi

echo "[rootfs] card   : $IMG"
echo "[rootfs] rootfs : $ROOT"
python3 "$RIG/parts.py" "$IMG" | sed 's/^/[rootfs]   /'

OFF=$(python3 "$RIG/parts.py" --rootfs "$IMG") || {
    echo "[rootfs] could not identify the OS partition" >&2; exit 1; }

mkdir -p "$ROOT"

# EXTRACT INTO AN EMPTY DIRECTORY, ALWAYS, AND MERGE AFTERWARDS.
#
# `rdump` REFUSES a directory that is already there. It says so, per directory,
# and then SKIPS THAT WHOLE SUBTREE:
#
#     rdump: File exists while making directory /home/you/spike2root//bin
#
# and its exit status is 0 either way. So extracting on top of a rootfs that
# already exists - a repair, or --force - could copy NOTHING while every line
# on screen said it worked, because the directories that are already there are
# exactly the ones that matter. Measured: a rootfs with bin/, lib/ and usr/
# present came back from a full re-extraction still missing /bin/sh.
#
# It also bit the FIRST run: ensurebuild.sh makes $ROOT/dump before calling
# this, so the card's own /dump was skipped on every fresh build, with one
# alarming red line to show for it.
#
# The staged tree is just the OS partition (about 350 MB) and it is made INSIDE
# $ROOT - the one directory we already know is writable and the one the merge
# has to end up on anyway, which on macOS is a Docker volume and on WSL is the
# ext4 disk. `cp -a` then merges where rdump will not, so an extracted title
# under games/ (3-6 GB) and the derived tables under dump/ are left exactly
# where they are.
rm -rf "$ROOT"/.stage.*            # a previous run that was killed outright
STAGE=$(mktemp -d "$ROOT/.stage.XXXXXX") || {
    echo "[rootfs] could not make a staging directory in $ROOT" >&2
    exit 1; }
trap 'rm -rf "$STAGE"' EXIT INT TERM

echo "[rootfs] extracting the OS partition (offset $OFF) - several minutes"
# NEVER PIPE THIS INTO `head`. It was `| grep -v ... | head -5`, and `head`
# closes the pipe after five lines - which SIGPIPEs debugfs and kills the
# extraction PART WAY THROUGH. The result looked like a wrong partition ("no
# /lib") when the partition was right and the extraction had simply been shot.
# Capture it, then summarise.
#
# THE OWNERSHIP WARNINGS ARE EXPECTED AND ARE NOT ERRORS. rdump tries to restore
# each file's original owner, which needs CAP_CHOWN; running as an ordinary user
# it cannot, says so per file, and extracts the file anyway. That is exactly
# what is wanted here - the guest runs under qemu-user as this same user, so
# files owned by root would be less useful, not more. The whole point of this
# script is that it needs no root, so the noise is summarised rather than shown.
XLOG=$(mktemp "${TMPDIR:-/var/tmp}/rootfs.XXXXXX")
debugfs -R "rdump / $STAGE" "$IMG?offset=$OFF" > "$XLOG" 2>&1
# `|| true`, NOT `|| echo 0`. `grep -c` PRINTS "0" and EXITS 1 when it matches
# nothing, so the fallback appended a SECOND zero and this variable came out as
# two lines - which is what the app's log pane showed a first-time user
# (PAD-119, C FB 2026-09-08), mid-build, in the middle of an extraction that
# was going fine:
#     rootfs.sh: line 141: [: 0
#     0: integer expression expected
# That is a run under a root launch, where rdump keeps the card's ownership and
# so warns about nothing at all. The count is already defaulted at its reader.
CHOWN_WARN=$(grep -c 'changing ownership' "$XLOG" 2>/dev/null || true)
grep -v 'changing ownership' "$XLOG" | grep -v '^debugfs' | grep -v '^$' | head -8
[ "${CHOWN_WARN:-0}" -gt 0 ] && \
    echo "[rootfs] ($CHOWN_WARN ownership notices - expected without root, files still extracted)"
rm -f "$XLOG"

# rdump lands the tree under a directory named after the source root on some
# e2fsprogs versions and directly otherwise; normalise rather than assume.
if [ ! -d "$STAGE/lib" ] && [ -d "$STAGE/$(basename "$STAGE")" ]; then
    mv "$STAGE/$(basename "$STAGE")"/* "$STAGE/" 2>/dev/null || true
    rmdir "$STAGE/$(basename "$STAGE")" 2>/dev/null || true
fi

[ -d "$STAGE/lib" ] || {
    echo "[rootfs] extraction produced no /lib - wrong partition?" >&2; exit 1; }

# Into place. `-a` keeps the symlinks AS symlinks (the loader is one, and
# dereferencing it is the /mnt failure this script's header is about) and
# merges into what is already there instead of refusing it.
cp -af "$STAGE/." "$ROOT/" || {
    echo "[rootfs] could not merge the extracted tree into $ROOT" >&2; exit 1; }
rm -rf "$STAGE"

# WAS THAT EXTRACTION ACTUALLY COMPLETE? Checked BY NAME, and by the names that
# matter: the shell the chroot starts and the loader the kernel opens for it.
#
# `[ ! -e ] && [ ! -L ]` used to be the loader test, and a DANGLING symlink
# passes both halves of that - a link is a link whether or not anything is on
# the end of it. So the one file this check exists for could be missing and the
# check would pass. pad_guest_missing follows the links the way the chroot
# does, which is the only way to find out.
#
# FATAL, not a warning. Everything after this point - the kernel, the shim, the
# GL bridge, the game - is built on a filesystem that cannot start a program,
# and each of them fails as something else.
GUEST_MISSING=$(pad_guest_missing)
if [ -n "$GUEST_MISSING" ]; then
    echo "[rootfs] the extraction is INCOMPLETE: $GUEST_MISSING is not there." >&2
    echo "[rootfs] Nothing can be started inside a rootfs without it, and the" >&2
    echo "[rootfs] error you would get is about /bin/sh and not about this." >&2
    echo "[rootfs] Usually the disk filled up part way (check df -h) or the" >&2
    echo "[rootfs] extraction was interrupted. If you extracted to a /mnt path," >&2
    echo "[rootfs] symlinks were dropped instead; see the header." >&2
    exit 1
fi

# THE GUEST HALF OF THE GL BRIDGE HAS JUST BEEN OVERWRITTEN, and only its stamp
# would know. buildbridge.sh installs the bridge encoder AS $ROOT/usr/lib/
# libGLESv2.so.2, which is a file the card ships too - so re-extracting puts
# Stern's own library back while the stamp beside it still says ours is
# installed. ensurebuild.sh trusts that stamp (deliberately: the file existing
# proves nothing, because it exists on a brand new rootfs). Dropping it is what
# makes the next start rebuild rather than believe it.
rm -f "$ROOT/usr/lib/glbridge.srcs"

# The kernel the game hashes. Second half of the recipe, and the half that was
# missing for long enough to cost a GAME VALIDATION ERROR #3 investigation.
bash "$RIG/getboot.sh" "$IMG" "$ROOT" || {
    echo "[rootfs] getboot.sh failed - the game will raise VALIDATION ERROR #3" >&2
}

# The shared area every run publishes into: the GL ring, the switch block, the
# LED block, the audio FIFO, and the derived playfield tables.
mkdir -p "$ROOT/dump" "$ROOT/games" "$ROOT/data" "$ROOT/tmp" "$ROOT/run" \
         "$ROOT/dev" "$ROOT/proc" "$ROOT/sys"

if [ -n "$WANT_GAME" ]; then
    GOFF=$(python3 "$RIG/parts.py" --games "$IMG") || {
        echo "[rootfs] could not identify the games partition" >&2; exit 1; }
    # NO mkdir OF THE TITLE DIRECTORY. It used to be made here, one line before
    # the rdump that creates it - and rdump refuses a directory that already
    # exists and skips the whole subtree, so `--game` extracted the title into
    # a directory it had just made empty and said nothing. Same fault as the
    # rootfs extraction above; the staging trick is not used here only because
    # a title is 3-6 GB and would have to be copied twice.
    if [ -d "$ROOT/games/$WANT_GAME" ]; then
        echo "[rootfs] games/$WANT_GAME is already there. rdump will not write"
        echo "[rootfs] into a directory that exists, so it is left alone -"
        echo "[rootfs] remove it first if you want it extracted again."
        GOFF=""
    fi
fi
if [ -n "$WANT_GAME" ] && [ -n "${GOFF:-}" ]; then
    echo "[rootfs] extracting title $WANT_GAME (offset $GOFF) - 3-6 GB, minutes"
    # Same two traps as the rootfs extraction above: no `head` on the pipeline
    # (it SIGPIPEs debugfs mid-extraction), and the debugfs command is ONE
    # argument, so the inner quoting has to be single - `"rdump /x "$D""` ends
    # the outer string at the second quote and only worked by accident.
    TLOG=$(mktemp "${TMPDIR:-/var/tmp}/title.XXXXXX")
    debugfs -R "rdump /$WANT_GAME '$ROOT/games'" "$IMG?offset=$GOFF" > "$TLOG" 2>&1
    grep -v 'changing ownership' "$TLOG" | grep -v '^debugfs' | grep -v '^$' | head -8
    # The node firmware images and conagent are LOOSE files beside the binary,
    # under neither assets/ nor data/, and the original recipe missed all 18.
    # Without them every node board sits on "Runtime Info".
    bash "$RIG/gethex.sh" "$IMG" "$ROOT/games/$WANT_GAME" || true
    debugfs -R "rdump /spk '$ROOT/games'" "$IMG?offset=$GOFF" > "$TLOG" 2>&1
    grep -v 'changing ownership' "$TLOG" | grep -v '^debugfs' | grep -v '^$' | head -4
    rm -f "$TLOG"
fi

echo
echo "[rootfs] done. Next:"
# THE TWO BUILDS ARE NO LONGER A STEP, and that is a fix and not a tidy-up.
# They were printed here as advice and enforced nowhere, so a user who stopped
# after the extraction got `env: './padglhost': No such file or directory` at
# their first start, ten seconds after the app said "Starting...". watch.sh now
# builds whatever is missing and rebuilds whatever is stale (ensurebuild.sh),
# so the setup is this one command and then run it.
# The quotes are IN the advice, not around it: this rig is now installed to
# `C:\Program Files\...` as often as it is checked out, and a command printed
# bare there is a command that word-splits when it is pasted.
echo "[rootfs]   PAD_CARD=\"$IMG\" bash \"$RIG/watch.sh\""
echo "[rootfs]"
echo "[rootfs] It builds the hardware shim and the GL backend itself on the"
echo "[rootfs] first run. To build them now instead:"
echo "[rootfs]   bash \"$RIG/build.sh\"          # the ARM hardware shim"
echo "[rootfs]   bash \"$RIG/buildbridge.sh\"    # the GL backend"
