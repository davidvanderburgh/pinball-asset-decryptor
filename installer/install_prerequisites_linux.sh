#!/usr/bin/env bash
# Per-manufacturer prerequisite installer for Pinball Asset Decryptor on Linux.
#
# Each manufacturer plugin needs a different set of CLI tools.  Pick the
# manufacturers you actually plan to use; this installs only the union of
# tools those plugins need, through apt-get on Debian and Ubuntu or pacman on
# Arch and its spins (Omarchy, CachyOS, EndeavourOS, Manjaro).
#
# Safe to re-run: `apt-get install -y` and `pacman -S --needed` are both no-ops
# on packages already installed.
#
# Tested on Ubuntu 22.04 / 24.04 and Debian derivatives; the pacman names were
# checked against Arch's package database on 2026-09-06.  For other distros,
# install the equivalent packages manually using the manifest below.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Which package manager ----------------------------------------------
# apt on Debian and Ubuntu, pacman on Arch.  This used to stop here for every
# distro that was not apt, printing the apt names for the user to translate by
# hand - which is what a user on Omarchy (an Arch spin) did, reporting on
# 2026-09-06 that the app then ran without a fault.  So Arch is a real target,
# and the one thing between it and the app's own "Install Missing" button was
# a package-name table.
#
# DETECTED HERE, ABOVE THE MANIFEST, and read everywhere below as `${PM:-apt}`:
# the tests lift the picker and the install blocks out of this file by their
# section markers and run them on their own, so those blocks cannot depend on
# this one having run, and unset has to mean apt - what the script always was.
if command -v apt-get >/dev/null 2>&1; then
    PM=apt
elif command -v pacman >/dev/null 2>&1; then
    PM=pacman
else
    echo "This installer speaks apt (Debian / Ubuntu) and pacman (Arch and its spins)."
    echo "For another distro, install the equivalent of these by hand"
    echo "(the apt name, then the Arch name in brackets where it differs):"
    echo "  PB:     e2fsprogs"
    echo "  Spooky: gnupg ffmpeg partclone e2fsprogs zstd python3-zstandard (python-zstandard)"
    echo "  BOF:    gnupg tar curl unzip xvfb (xorg-server-xvfb) webp (libwebp) + GDRE Tools (download from GitHub)"
    echo "  JJP:    partclone e2fsprogs xorriso (libisoburn) pigz ffmpeg python3-zstandard (python-zstandard) gcc libc6-dev (glibc)"
    echo "  CGC:    e2fsprogs xxd (tinyxxd, or vim's) + pip (python-pip)"
    echo "  Stern:  qemu-user-static (+ qemu-user-static-binfmt) gcc-arm-linux-gnueabihf (arm-linux-gnueabihf-gcc, AUR) gcc libc6-dev (glibc) e2fsprogs fuse3 python3-tk (tk) ffmpeg busybox-static (busybox)"
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

# The same manifest in pacman's spelling, one entry per manufacturer above - a
# manufacturer with an apt list and no pacman list would install nothing on
# Arch and say so only in the summary.  Every name verified against Arch's
# package database (archlinux.org/packages) on 2026-09-06; all of them are in
# core or extra.  Where the two distros disagree:
#   python3-zstandard -> python-zstandard      xvfb    -> xorg-server-xvfb
#   webp              -> libwebp               xorriso -> libisoburn
#   libc6-dev         -> (nothing: Arch's glibc ships its headers, gcc pulls it)
#   xxd               -> tinyxxd, BUT vim and gvim also provide xxd and tinyxxd
#                        conflicts with them, so it is skipped when an xxd is
#                        already on the PATH (PM_CMD_OF below)
#   python3-tk        -> tk (Arch's python grows tkinter once tk is present)
#   qemu-user-static  -> qemu-user-static + qemu-user-static-binfmt.  Arch
#                        splits the binfmt registration into its own package,
#                        and the rig needs the registration, with the F flag:
#                        Arch generates it with `--persistent yes`, which IS
#                        that flag, and systemd's 25-systemd-binfmt.hook
#                        registers it in the same pacman transaction, so
#                        nothing here has to restart anything.
#   busybox-static    -> busybox (Arch's is built CONFIG_STATIC=y, and /bin is
#                        /usr/bin there, so the rig's /bin/busybox probe sees it)
#   gcc-arm-linux-gnueabihf -> NOT IN THE REPOS.  See MFR_AUR_PACKAGES.
declare -A MFR_PACMAN_PACKAGES=(
    [1]="e2fsprogs"
    [2]="gnupg ffmpeg partclone e2fsprogs zstd python-zstandard"
    [3]="gnupg tar curl unzip xorg-server-xvfb libwebp"
    [4]="partclone e2fsprogs libisoburn pigz ffmpeg python-zstandard gcc"
    # python-pip: Arch's python does not carry pip, and the pip step below is
    # how CGC's transcribe button gets faster-whisper.
    [5]="e2fsprogs tinyxxd python-pip"
    [6]="qemu-user-static qemu-user-static-binfmt gcc e2fsprogs fuse3 tk ffmpeg busybox"
)

# What pacman cannot supply.  The AUR is not a repository, it is recipes, and
# building from it takes a helper (yay, paru) or makepkg by hand, neither of
# which this script should be running as root.  These are NAMED at the end,
# not installed.  The Spike 2 rig builds its hardware shim and the guest half
# of its GL bridge with arm-linux-gnueabihf-gcc (buildshim.sh / buildbridge.sh
# call it by that name), and on Arch that is an AUR toolchain: the source
# package builds binutils, kernel headers, glibc and then gcc, an hour or more;
# the *-bin packages beside it are the same compiler prebuilt.
declare -A MFR_AUR_PACKAGES=(
    [6]="arm-linux-gnueabihf-gcc"
)

# A pacman package that exists only to put ONE command on the PATH, and whose
# command another installed package may already provide.  Installing it then
# would not be a no-op, it would be a refused conflict (tinyxxd vs vim), so it
# is skipped when the command is already there, and the summary counts it OK
# by the command rather than by the package.
declare -A PM_CMD_OF=(
    [tinyxxd]="xxd"
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
    if [ "${PM:-apt}" = pacman ]; then
        list=${MFR_PACMAN_PACKAGES[$s]:-}
    else
        list=${MFR_PACKAGES[$s]}
    fi
    for p in $list; do
        pkg_set[$p]=1
    done
done
all_packages=("${!pkg_set[@]}")

# ...and the ones only the AUR has, which are named rather than installed.
declare -A aur_set=()
if [ "${PM:-apt}" = pacman ]; then
    for s in "${selected[@]}"; do
        for p in ${MFR_AUR_PACKAGES[$s]:-}; do
            aur_set[$p]=1
        done
    done
fi
all_aur_packages=("${!aur_set[@]}")

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
echo "Will install (${PM:-apt}): ${all_packages[*]}"
if [ -n "${all_aur_packages[*]:-}" ]; then
    echo "From the AUR, by hand (pacman cannot): ${all_aur_packages[*]}"
fi
if [ "${PM:-apt}" = pacman ]; then
    echo ""
    echo "On Arch that is 'pacman -Syu --needed ...': the whole system is brought"
    echo "up to date first, because pacman does not install into a stale one"
    echo "(a partial upgrade is the one thing Arch says never to do)."
fi
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
# Installed, by whichever package manager this is.  Defined HERE rather than
# beside the detection at the top because the tests run this block and the
# summary below on their own, lifted out by their section markers (see
# tests/test_installer.py); what they need has to travel with them.
pkg_installed() {
    case "${PM:-apt}" in
        pacman)
            pacman -Qq "$1" >/dev/null 2>&1 && return 0
            # ...or the one command it exists for is already on the PATH
            # (vim's xxd stands in for tinyxxd, which conflicts with it).
            local cmd=${PM_CMD_OF[$1]:-}
            [ -n "$cmd" ] && command -v "$cmd" >/dev/null 2>&1 ;;
        *)  dpkg -s "$1" >/dev/null 2>&1 ;;
    esac
}

echo ""
if [ "${PM:-apt}" = pacman ]; then
    # Leave out what another package's command already satisfies (PM_CMD_OF):
    # pacman would not skip it, it would refuse the conflict and the batch.
    wanted=()
    for p in "${all_packages[@]}"; do
        if [ -n "${PM_CMD_OF[$p]:-}" ] && pkg_installed "$p"; then
            echo "  $p: already have ${PM_CMD_OF[$p]} - skipping"
        else
            wanted+=("$p")
        fi
    done
    echo "Installing packages (pacman -Syu --needed)..."
    # ONE UNKNOWN NAME MUST NOT TAKE THE OTHERS DOWN WITH IT: pacman's "target
    # not found" fails the whole transaction exactly as apt's "no installation
    # candidate" does (the apt path below says why that matters), so the same
    # batch first, then one at a time.  The retries are `-Su`, not `-S`: the
    # batch's `-y` already refreshed the database - pacman syncs before it
    # resolves targets, so a refused batch still leaves a fresh one - and a
    # plain `-S` against a fresh database with no `-u` is the partial upgrade
    # Arch does not support.
    if [ -n "${wanted[*]:-}" ] && \
            ! $SUDO pacman -Syu --needed --noconfirm "${wanted[@]}"; then
        echo ""
        echo "That did not go through as one command.  Retrying them one at a"
        echo "time so a package pacman cannot get does not block the rest..."
        for p in "${wanted[@]}"; do
            $SUDO pacman -Su --needed --noconfirm "$p" \
                || echo "  pacman could not install $p"
        done
    fi
else
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

fi

# --- ...and what to do about one the package manager would not install --
# A red MISSING in the summary used to be the end of it, on both installers,
# and that is not even a diagnosis: apt refusing a package because Ubuntu keeps
# it in a component this distro has switched off is a different fault from a
# download that failed, it is knowable, and only one of the two is repairable.
#
# ALL OF THAT ALREADY EXISTS, in tools/spike2_emu/setupfix.sh - the script the
# Emulate tab's "Set up emulator..." button runs.  It refreshes the index,
# turns `universe` on when that is why, installs one at a time, fetches the one
# package that depends on nothing from a release that publishes it, and says
# which of those it was when none of them worked.  Handing it the packages is
# how this script gets all of that without keeping a second, weaker copy of it
# (PAD-104); `--packages` is step one only, so nothing here registers a kernel
# handler or builds anything.
#
# NAMED, NOT IMPLIED: only the packages that actually failed, so a Spooky user
# is helped without an ARM emulator arriving on his machine as a side effect.
still=
for p in "${all_packages[@]}"; do
    pkg_installed "$p" || still="$still $p"
done
if [ -n "$still" ]; then
    rig="$SCRIPT_DIR/../tools/spike2_emu"
    [ -f "$rig/setupfix.sh" ] || rig="$SCRIPT_DIR/tools/spike2_emu"
    echo ""
    echo "${PM:-apt} could not install:$still"
    if [ "${PM:-apt}" = pacman ]; then
        # setupfix.sh's repairs are apt's: the index refresh, the `universe`
        # component, the one .deb fetched from another Ubuntu release.  None
        # of them means anything to pacman, whose own message is the best
        # help there is - and unlike apt's it names the target it lacks.
        echo "Run this to see pacman's own reason:"
        echo "    sudo pacman -S --needed$still"
    elif [ -f "$rig/setupfix.sh" ]; then
        echo ""
        echo "There is more the app can do about that than apt can:"
        echo "  * refresh the package index and try again, one at a time"
        echo "  * if this Ubuntu has its 'universe' component switched off"
        echo "    (where qemu-user-static and ffmpeg live), turn it on"
        echo "  * for a package this release does not publish at all, fetch"
        echo "    that one file from Ubuntu 24.04 - only ever a package that"
        echo "    depends on nothing, which is checked before it is installed"
        echo "  * and if none of that works, say which of those it was"
        echo ""
        read -rp "Try that now? [Y/n] " try
        case "${try,,}" in
            ''|y|yes) $SUDO bash "$rig/setupfix.sh" --packages $still || true ;;
            *)        echo "Skipped." ;;
        esac
    else
        echo "Run this to see apt's own reason:"
        echo "    sudo apt-get install$still"
    fi
fi

# --- ...and what pacman cannot install at all ---------------------------
# Named, with the way to get each one, and what it costs to go without.
if [ -n "${all_aur_packages[*]:-}" ]; then
    echo ""
    echo "From the AUR, which pacman does not install from: ${all_aur_packages[*]}"
    echo "  With an AUR helper:  yay -S ${all_aur_packages[*]}    (or paru -S ...)"
    for p in "${all_aur_packages[@]}"; do
        case "$p" in
            arm-linux-gnueabihf-gcc)
                echo "  $p is the Spike 2 emulator's cross compiler: the"
                echo "  Emulate tab builds its hardware shim with it, and nothing else in"
                echo "  the app needs it.  The source package builds the whole toolchain"
                echo "  and takes a while; arm-linux-gnueabihf-gcc-bin is the same"
                echo "  compiler prebuilt." ;;
        esac
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
    # PEP 668.  Arch, and Debian 12 / Ubuntu 23.04 and later, mark the system
    # Python "externally managed", and pip then refuses even --user with a wall
    # of text and exit 1 - which, with `set -e` above, ended this script here
    # with the summary unprinted.  --user installs into ~/.local, the one tree
    # that marking does not cover; the flag that gets past the refusal is
    # named for the thing --user does not do.  So: plain first (older pips do
    # not know the flag), then with it, and a pip that still refuses is named
    # rather than fatal.
    if ! python3 -m pip install --user --upgrade "${all_pip_packages[@]}"; then
        echo ""
        echo "pip refused - an externally managed Python, most likely.  Retrying"
        echo "into your user site (~/.local), which that marking does not cover..."
        python3 -m pip install --user --upgrade --break-system-packages \
                "${all_pip_packages[@]}" \
            || echo "  pip could not install: ${all_pip_packages[*]}"
    fi
fi

# --- Summary ------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Prerequisites Summary"
echo "============================================================"
for p in "${all_packages[@]}"; do
    if pkg_installed "$p"; then
        printf "  %-30s OK\n" "$p"
    else
        printf "  %-30s MISSING\n" "$p"
    fi
done
# `[*]:+` rather than a bare `[@]`: the array may be unset, not merely empty,
# and `set -u` treats those differently.
for p in ${all_aur_packages[*]:+"${all_aur_packages[@]}"}; do
    if pacman -Qq "$p" >/dev/null 2>&1; then
        printf "  %-30s OK (AUR)\n" "$p"
    else
        printf "  %-30s MISSING (AUR - see above)\n" "$p"
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
# Anything still MISSING here has already been past the repair step above,
# which is where the explanation lives - the reason is not repeated as a guess
# down here, where nothing has been checked.

echo ""
echo "Done.  Launch the app from the AppImage or 'python3 -m pinball_decryptor'."
