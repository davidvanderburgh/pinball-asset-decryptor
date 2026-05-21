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
    echo "  JJP:    partclone e2fsprogs xorriso pigz ffmpeg python3-zstandard"
    echo "  CGC:    e2fsprogs xxd"
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
)
declare -A MFR_DESCRIPTIONS=(
    [1]="ABBA, Alien, Queen, Predator (.upd files + Clonezilla ISOs)"
    [2]="Beetlejuice, Evil Dead, R&M, Halloween, Looney Tunes + many more"
    [3]="Labyrinth, Dune, Winchester (.fun files)"
    [4]="Wonka, GnR, Hobbit, Wizard of Oz, Avatar, etc. (.iso disk images)"
    [5]="Medieval Madness Remake, AFM Remake, MB Remake, Pulp Fiction (.img installer images)"
)
declare -A MFR_PACKAGES=(
    [1]="e2fsprogs"
    [2]="gnupg ffmpeg partclone e2fsprogs zstd python3-zstandard"
    [3]="gnupg tar curl unzip xvfb webp"
    [4]="partclone e2fsprogs xorriso pigz ffmpeg python3-zstandard"
    [5]="e2fsprogs xxd"
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
echo ""
echo "============================================================"
echo "  Pinball Asset Decryptor - Prerequisite Installer (Linux)"
echo "============================================================"
echo ""
echo "Pick the manufacturers you plan to use.  We'll install only"
echo "the tools those plugins actually need."
echo ""
for i in 1 2 3 4 5; do
    printf "  [%d] %s\n" "$i" "${MFR_NAMES[$i]}"
    printf "       %s\n" "${MFR_DESCRIPTIONS[$i]}"
done
echo "  [a] All of the above"
echo ""
read -rp "Enter numbers separated by commas (e.g. '2,4'), or 'a' for all: " pick

selected=()
if [ "${pick,,}" = "a" ]; then
    selected=(1 2 3 4 5)
else
    IFS=', ' read -ra tokens <<< "$pick"
    for t in "${tokens[@]}"; do
        case "$t" in
            1|2|3|4|5) selected+=("$t") ;;
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
$SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${all_packages[@]}"

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
for p in "${all_packages[@]}"; do
    if dpkg -s "$p" >/dev/null 2>&1; then
        printf "  %-30s OK\n" "$p"
    else
        printf "  %-30s MISSING\n" "$p"
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
echo ""
echo "Done.  Launch the app from the AppImage or 'python3 -m pinball_decryptor'."
