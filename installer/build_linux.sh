#!/usr/bin/env bash
# Build AppImage for Pinball Asset Decryptor.
# Requirements: Python 3.10+ with tkinter, wget (for appimagetool), file.
# Tested on Ubuntu 22.04 / 24.04.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION=$(python3 -c "import sys; sys.path.insert(0,'$ROOT_DIR'); from pinball_decryptor import __version__; print(__version__)")
ARCH="$(uname -m)"

echo "=== Building Pinball Asset Decryptor v${VERSION} for Linux (${ARCH}) ==="

BUILD_DIR="$SCRIPT_DIR/build_linux"
APPDIR="$BUILD_DIR/AppDir"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$APPDIR"

# --- PyInstaller build --------------------------------------------------
echo "Installing build deps..."
# Install the FULL runtime dep set (requirements.txt: unicorn / capstone /
# numpy / zstandard / pycryptodome / Pillow) PLUS the build-only extras
# (pyinstaller, the UnityPy/fsb5/pyogg Godot-asset libs) and faster-whisper.
# Must stay in sync with requirements.txt -- a runtime dep missing here means
# PyInstaller's --collect-all / import analysis collects nothing and the
# AppImage silently ships without it (this is how Stern's unicorn/capstone/
# numpy went missing on the frozen builds).  Absolute path: this runs before
# the `cd "$ROOT_DIR"` below.
pip3 install --user -r "$ROOT_DIR/requirements.txt" pyinstaller UnityPy fsb5 pyogg faster-whisper imageio-ffmpeg

echo "Running PyInstaller..."
cd "$ROOT_DIR"
# See installer/build_macos.sh for the rationale.  The plugins are
# loaded dynamically via importlib.import_module(<string>) in
# core/registry.py, so each one needs an explicit --hidden-import.
# --collect-submodules silently no-ops in PyInstaller 6.x for
# packages added via --paths; the explicit per-plugin list is the
# bulletproof mechanism.
pyinstaller \
    --name "pinball-decryptor" \
    --windowed \
    --paths "$ROOT_DIR" \
    --add-data "$ROOT_DIR/pinball_decryptor/icon.png:pinball_decryptor" \
    --add-data "$ROOT_DIR/pinball_decryptor/plugins/spooky/Dockerfile:pinball_decryptor/plugins/spooky" \
    --add-data "$ROOT_DIR/pinball_decryptor/plugins/jjp/Dockerfile:pinball_decryptor/plugins/jjp" \
    --add-data "$ROOT_DIR/pinball_decryptor/plugins/jjp/partclone_to_raw.py:pinball_decryptor/plugins/jjp" \
    --hidden-import "Crypto" \
    --hidden-import "Crypto.Cipher" \
    --hidden-import "Crypto.Cipher.AES" \
    --hidden-import "Crypto.Util.Padding" \
    --collect-all "UnityPy" \
    --collect-all "fsb5" \
    --collect-all "pyogg" \
    --hidden-import "PIL" \
    --hidden-import "PIL.Image" \
    --hidden-import "pinball_decryptor.plugins.pb" \
    --hidden-import "pinball_decryptor.plugins.ap" \
    --hidden-import "pinball_decryptor.plugins.spooky" \
    --hidden-import "pinball_decryptor.plugins.bof" \
    --hidden-import "pinball_decryptor.plugins.jjp" \
    --hidden-import "pinball_decryptor.plugins.cgc" \
    --hidden-import "pinball_decryptor.plugins.williams" \
    --hidden-import "pinball_decryptor.plugins.pinmame_classic" \
    --hidden-import "pinball_decryptor.plugins.dp" \
    --hidden-import "pinball_decryptor.plugins.stern" \
    --hidden-import "pinball_decryptor.plugins.stern.engine" \
    --hidden-import "pinball_decryptor.plugins.stern.sidx" \
    --hidden-import "pinball_decryptor.plugins.stern.ext4" \
    --hidden-import "pinball_decryptor.core.rawdevice" \
    --hidden-import "pinball_decryptor.plugins.stern.radium" \
    --hidden-import "pinball_decryptor.plugins.stern.dds" \
    --hidden-import "pinball_decryptor.plugins.stern.spine" \
    --hidden-import "pinball_decryptor.plugins.stern.spike2" \
    --hidden-import "pinball_decryptor.plugins.stern.spike2.elf" \
    --hidden-import "pinball_decryptor.plugins.stern.spike2.rbtree" \
    --hidden-import "pinball_decryptor.plugins.stern.spike2.emulator" \
    --hidden-import "pinball_decryptor.plugins.stern.spike2.locate" \
    --hidden-import "pinball_decryptor.plugins.stern.spike2.codec" \
    --hidden-import "pinball_decryptor.plugins.stern.spike2.parallel" \
    --hidden-import "pinball_decryptor.plugins.stern.spike2.category" \
    --collect-all "unicorn" \
    --collect-all "capstone" \
    --collect-all "numpy" \
    --collect-all "faster_whisper" \
    --collect-all "ctranslate2" \
    --collect-all "onnxruntime" \
    --collect-all "av" \
    --collect-all "tokenizers" \
    --collect-all "huggingface_hub" \
    --collect-all "imageio_ffmpeg" \
    --collect-submodules "pinball_decryptor.plugins" \
    --collect-submodules "pinball_decryptor.core" \
    --noconfirm \
    --clean \
    --distpath "$BUILD_DIR/dist" \
    --workpath "$BUILD_DIR/work" \
    --specpath "$BUILD_DIR" \
    "$SCRIPT_DIR/pyinstaller_entry.py"

# --- Assemble AppDir ----------------------------------------------------
# Layout follows the AppImage spec: a top-level AppRun, .desktop, icon,
# plus the binary under usr/bin/.
echo "Assembling AppDir..."
mkdir -p "$APPDIR/usr/bin"
cp -r "$BUILD_DIR/dist/pinball-decryptor/." "$APPDIR/usr/bin/"

# Top-level icon (required by appimagetool) + standard hicolor location
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "$ROOT_DIR/pinball_decryptor/icon.png" "$APPDIR/pinball-decryptor.png"
cp "$ROOT_DIR/pinball_decryptor/icon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/pinball-decryptor.png"

cat > "$APPDIR/pinball-decryptor.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Pinball Asset Decryptor
Comment=Extract, view, and modify pinball machine assets
Exec=pinball-decryptor
Icon=pinball-decryptor
Categories=Utility;
Terminal=false
EOF

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
exec "${HERE}/usr/bin/pinball-decryptor" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# --- Fetch appimagetool if needed --------------------------------------
APPIMAGETOOL="$BUILD_DIR/appimagetool"
if [ ! -x "$APPIMAGETOOL" ]; then
    echo "Fetching appimagetool..."
    case "$ARCH" in
        x86_64)  TOOL_ARCH="x86_64" ;;
        aarch64) TOOL_ARCH="aarch64" ;;
        *)       echo "Unsupported arch: $ARCH"; exit 1 ;;
    esac
    wget -q -O "$APPIMAGETOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${TOOL_ARCH}.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

# --- Package AppImage ---------------------------------------------------
mkdir -p "$SCRIPT_DIR/Output"
OUTPUT_NAME="Pinball_Asset_Decryptor_v${VERSION}_Linux_${ARCH}.AppImage"
OUTPUT_PATH="$SCRIPT_DIR/Output/$OUTPUT_NAME"

# ARCH must be set for appimagetool to pick the runtime; --appimage-extract-and-run
# avoids needing FUSE on CI runners that don't have it.
echo "Building AppImage..."
ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run \
    "$APPDIR" "$OUTPUT_PATH"

echo ""
echo "=== Build complete ==="
echo "Output: $OUTPUT_PATH"
