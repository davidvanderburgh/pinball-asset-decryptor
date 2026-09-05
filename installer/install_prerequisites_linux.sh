#!/usr/bin/env bash
# Per-manufacturer prerequisite installer for Pinball Asset Decryptor on Linux.
#
# Each manufacturer plugin needs a different set of CLI tools.  Pick the
# manufacturers you actually plan to use; this installs only the union of
# tools those plugins need (via apt-get).
#
# Safe to re-run: apt-get install -y on already-installed packages is a no-op.
#
# Tested on Ubuntu 22.04 / 24.04 and Debian derivatives.  For other distros,
# install the equivalent packages manually using the manifest below.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v apt-get >/dev/null 2>&1; then
    echo "This installer expects an apt-based distro (Debian / Ubuntu)."
    echo "For others, install the equivalent of these packages by hand:"
    echo "  PB:     e2fsprogs"
    echo "  Spooky: gnupg ffmpeg partclone e2fsprogs zstd python3-zstandard"
    echo "  BOF:    gnupg tar curl unzip xvfb webp + GDRE Tools (download from GitHub)"
    echo "  JJP:    partclone e2fsprogs xorriso pigz ffmpeg python3-zstandard gcc libc6-dev"
    echo "  CGC:    e2fsprogs xxd"
    echo "  Stern:  qemu-user-static gcc-arm-linux-gnueabihf gcc libc6-dev e2fsprogs fuse3 python3-tk ffmpeg busybox-static"
    exit 1
fi

# --- Manufacturer manifest ----------------------------------------------
# Mirror of installer/install_prerequisites.ps1 but flattened to a single
# apt package list per mfr (Linux doesn't have the host-vs-WSL split).
declare -A MFR_NAMES=(
    [1]="Pinball Brothers"
    [2]="Spooky Pinball"
    [3]="Barrels of Fun"
    [4]="Jersey Jack Pinball"
    [5]="Chicago Gaming Company"
    [6]="Stern Pinball"
)
declare -A MFR_DESCRIPTIONS=(
    [1]="ABBA, Alien, Queen, Predator (.upd files + Clonezilla ISOs)"
    [2]="Beetlejuice, Evil Dead, R&M, Halloween, Looney Tunes + many more"
    [3]="Labyrinth, Dune, Winchester (.fun files)"
    [4]="Wonka, GnR, Hobbit, Wizard of Oz, Avatar, etc. (.iso disk images)"
    [5]="Medieval Madness Remake, AFM Remake, MB Remake, Pulp Fiction (.img installer images)"
    [6]="Spike 2: Godzilla, Jurassic Park, Deadpool, Star Wars + more (SD-card images) - and the Emulate tab"
)
declare -A MFR_PACKAGES=(
    [1]="e2fsprogs"
    [2]="gnupg ffmpeg partclone e2fsprogs zstd python3-zstandard"
    [3]="gnupg tar curl unzip xvfb webp"
    # gcc pulls libc6-dev only as a *recommended* package, so name the
    # headers too — without them the dongle-extract hooks won't compile.
    [4]="partclone e2fsprogs xorriso pigz ffmpeg python3-zstandard gcc libc6-dev"
    [5]="e2fsprogs xxd"
    # Stern needs nothing on Linux for extract/write - native Linux mounts
    # ext4 itself. Everything here is for the EMULATE tab, which runs the
    # machine's own 32-bit ARM binary under qemu-user against a guest
    # filesystem built from a card image:
    #   qemu-user-static          runs the ARM binary
    #   gcc-arm-linux-gnueabihf   builds the LD_PRELOAD hardware shim
    #   gcc + libc6-dev           builds padglhost, the NATIVE renderer that
    #                             draws the picture. A different compiler from
    #                             the line above, and having that one says
    #                             nothing about having this one - a user hit
    #                             exactly that gap, shim built, renderer not.
    #                             libc6-dev is named for the same reason it is
    #                             named under JJP: gcc only recommends it.
    #   e2fsprogs                 rootfs.sh, which needs no root to extract
    #   fuse3                     fusermount3, so a card mounts read-only
    #                             without root (fuse2fs itself is fetched by
    #                             cardmount.sh into a private prefix)
    #   python3-tk                the virtual playfield window. Separate from
    #                             python3 on Debian and Ubuntu, and its
    #                             absence reads as a puzzling ImportError.
    #   ffmpeg                    decodes the game's video AND its audio. The
    #                             game does neither itself - its gstreamer has
    #                             no software H.264 element - so without this
    #                             the emulator starts, opens its window, and
    #                             plays black and silent, which is the one
    #                             failure here that does not look like one.
    #   busybox-static            SAVE STATES. The checkpointable boot pivots
    #                             away from the host tree and then has to
    #                             umount it, which needs a NATIVE STATIC
    #                             binary inside the guest root; the rootfs's
    #                             own busybox is ARM. Nobody has one by
    #                             default and it was on no list, so v0.126.0
    #                             refused to start at all without it - the rig
    #                             now runs the ordinary boot instead, and this
    #                             is what buys the feature back.
    [6]="qemu-user-static gcc-arm-linux-gnueabihf gcc libc6-dev e2fsprogs fuse3 python3-tk ffmpeg busybox-static"
)

# Pip packages -- installed into the same Python that runs the app
# (via `python3 -m pip install --user`).  Pulled from PyPI so they
# stay current independent of the apt cycle.  Currently only CGC
# needs this (faster-whisper for the auto-transcribe button).
declare -A MFR_PIP_PACKAGES=(
    [5]="faster-whisper"
)

# Plugins whose apt packages alone aren't enough — extra
# download-install-from-github post-step gets dispatched after the
# apt section.  Currently only BOF needs this (GDRE Tools).
declare -A MFR_CUSTOM=(
    [3]="install_gdre_tools"
)

# --- Picker -------------------------------------------------------------
# THE MENU AND THE VALID ANSWERS COME FROM THE MANIFEST, not from a list of
# numbers written out a second time down here.  They were two lists and they
# came apart: Stern went in as [6] with v0.110.0, this block stayed at five,
# and from then on "All of the above" installed everything EXCEPT the Spike 2
# emulator's packages while typing 6 was dropped without a word ("2,6"
# installed Spooky's and reported success).  What that costs is
# qemu-user-static, and on Linux there is no second way to get it: the Emulate
# tab's "Set up emulator..." installs packages through `wsl -u root`, so on a
# Linux desktop it can only print the command.  So a user who picked "a" off a
# menu that lists Stern got a machine that cannot emulate and nothing anywhere
# saying why (PAD-104).  A seventh manufacturer cannot repeat it.
mfr_ids=$(printf '%s\n' "${!MFR_NAMES[@]}" | sort -n | tr '\n' ' ')
mfr_ids=${mfr_ids% }

echo ""
echo "============================================================"
echo "  Pinball Asset Decryptor - Prerequisite Installer (Linux)"
echo "============================================================"
echo ""
echo "Pick the manufacturers you plan to use.  We'll install only"
echo "the tools those plugins actually need."
echo ""
for i in $mfr_ids; do
    printf "  [%d] %s\n" "$i" "${MFR_NAMES[$i]}"
    printf "       %s\n" "${MFR_DESCRIPTIONS[$i]}"
done
echo "  [a] All of the above"
echo ""
read -rp "Enter numbers separated by commas (e.g. '2,4'), or 'a' for all: " pick

selected=()
if [ "${pick,,}" = "a" ]; then
    selected=($mfr_ids)
else
    IFS=', ' read -ra tokens <<< "$pick"
    for t in "${tokens[@]}"; do
        [ -n "$t" ] || continue
        # Membership by string match on the id list rather than by indexing
        # MFR_NAMES with it, because the token is whatever the user typed and
        # an array subscript is arithmetic: `MFR_NAMES[$t]` on "1+1" answers
        # for Spooky.
        case " $mfr_ids " in
            *" $t "*) selected+=("$t") ;;
            # AND SAY SO.  A number this script did not recognise used to
            # vanish silently, which is how a pick could be half honoured and
            # still look like it worked.
            *) echo "  Ignoring \"$t\" - not one of the numbers above." ;;
        esac
    done
fi

if [ "${#selected[@]}" -eq 0 ]; then
    echo "No manufacturers selected - nothing to install."
    exit 0
fi

# --- Dedup the package set ---------------------------------------------
declare -A pkg_set=()
for s in "${selected[@]}"; do
    for p in ${MFR_PACKAGES[$s]}; do
        pkg_set[$p]=1
    done
done
all_packages=("${!pkg_set[@]}")

declare -A pip_set=()
for s in "${selected[@]}"; do
    for p in ${MFR_PIP_PACKAGES[$s]:-}; do
        pip_set[$p]=1
    done
done
all_pip_packages=("${!pip_set[@]}")

echo ""
echo "Selected manufacturers:"
for s in "${selected[@]}"; do
    echo "  - ${MFR_NAMES[$s]}"
done
echo ""
echo "Will install (apt): ${all_packages[*]}"
if [ "${#all_pip_packages[@]}" -gt 0 ]; then
    echo "Will install (pip): ${all_pip_packages[*]}"
fi
echo ""
read -rp "Proceed? (y/n) " proceed
if [ "$proceed" != "y" ]; then
    echo "Cancelled."
    exit 0
fi

# --- Install ------------------------------------------------------------
echo ""
echo "Refreshing apt indexes..."
$SUDO apt-get update -qq

echo "Installing packages..."
# ONE UNAVAILABLE NAME MUST NOT TAKE THE OTHERS DOWN WITH IT.  `apt-get install
# a b c` is all or nothing: if apt has no version of ONE of them the whole
# command fails and none of the rest are installed - and with `set -e` above,
# the script dies there, so the summary that would have named the culprit never
# prints either.  A tester met exactly that on the WSL side of this (PAD-41):
# ended a run four packages short having been told about one.  So the batch is
# tried first because it is one download plan and much faster, and only if it
# fails is each package retried on its own, which is what turns "nothing
# installed, here is an apt error" into "everything installed except this one",
# and the summary below then names it.
#
# `$SUDO env VAR=...`, NOT `$SUDO VAR=... `: bash decides which leading words
# are variable assignments while PARSING, before `$SUDO` is expanded, so on a
# machine already running as root - where SUDO is empty and vanishes -
# `DEBIAN_FRONTEND=noninteractive` becomes the command word and every install
# dies with "DEBIAN_FRONTEND=noninteractive: command not found".  `env` also
# takes the setting past a sudoers policy that would otherwise refuse it.
if ! $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        "${all_packages[@]}"; then
    echo ""
    echo "That did not go through as one command.  Retrying them one at a"
    echo "time so a package apt cannot get does not block the rest..."
    for p in "${all_packages[@]}"; do
        $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$p" \
            || echo "  apt could not install $p"
    done
fi

# --- Custom post-install steps (downloads that aren't in apt) -----------
install_gdre_tools() {
    # GDRE Tools (Godot RE Tools) — required for BOF's PCK repack.
    # The install logic is the shared install_gdre.sh, run verbatim by
    # the Windows (WSL) installer too — one source of truth.
    echo ""
    bash "$SCRIPT_DIR/install_gdre.sh"
}

for s in "${selected[@]}"; do
    custom=${MFR_CUSTOM[$s]:-}
    if [ -n "$custom" ]; then
        $custom
    fi
done

# --- Pip packages -- install into the user site for the running python3.
# We pin to `python3` (not `python`) because Debian/Ubuntu reserve the
# unversioned name on some systems.  --user lands the packages where
# the app's interpreter will see them without requiring sudo.
if [ "${#all_pip_packages[@]}" -gt 0 ]; then
    echo ""
    echo "Installing pip packages (python3 -m pip install --user)..."
    python3 -m pip install --user --upgrade "${all_pip_packages[@]}"
fi

# --- Summary ------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Prerequisites Summary"
echo "============================================================"
still_missing=()
for p in "${all_packages[@]}"; do
    if dpkg -s "$p" >/dev/null 2>&1; then
        printf "  %-30s OK\n" "$p"
    else
        printf "  %-30s MISSING\n" "$p"
        still_missing+=("$p")
    fi
done
for p in "${all_pip_packages[@]}"; do
    # Map the pip package name to its import name where they differ.
    case "$p" in
        faster-whisper) module="faster_whisper" ;;
        *)              module="${p//-/_}" ;;
    esac
    if python3 -c "import $module" >/dev/null 2>&1; then
        printf "  %-30s OK (pip)\n" "$p"
    else
        printf "  %-30s MISSING (pip)\n" "$p"
    fi
done
# A PACKAGE BEING MISSING AND APT BEING ABLE TO GET IT ARE TWO FACTS, and the
# second one is repairable.  Ubuntu keeps qemu-user-static in its `universe`
# component; a distro with universe switched off answers "has no installation
# candidate" for it while gcc-arm-linux-gnueabihf beside it in `main` installs
# fine, so the run above ends one package short with no explanation of which
# kind of short it is.
#
# CLAIMED ONLY WITH EVIDENCE, from apt's own downloaded indexes rather than
# from the sources config: a distro that has never run `apt-get update` has no
# index at all, `indextargets` prints nothing, and reading that as "universe is
# off" would accuse a healthy machine (PAD-42).  The `apt-get update` above is
# what makes the answer real.  Ubuntu only - on Debian that package is in
# `main` and an unavailable one means something else entirely.
if [ "${#still_missing[@]}" -gt 0 ]; then
    comps=$(apt-get indextargets --format '$(COMPONENT)' 2>/dev/null | sort -u)
    if [ -n "$comps" ] && grep -qs '^ID=ubuntu' /etc/os-release &&
       ! printf '%s\n' "$comps" | grep -qx universe; then
        echo ""
        echo "This Ubuntu has its 'universe' component switched off, and that"
        echo "is where qemu-user-static lives.  Turn it on and re-run this:"
        echo ""
        echo "    sudo add-apt-repository -y universe"
    fi
fi

echo ""
echo "Done.  Launch the app from the AppImage or 'python3 -m pinball_decryptor'."
