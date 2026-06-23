#!/usr/bin/env bash
# Build macOS DMG for Pinball Asset Decryptor.
# Requirements: Python 3.10+, PyInstaller, create-dmg (brew install create-dmg).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION=$(python3 -c "import sys; sys.path.insert(0,'$ROOT_DIR'); from pinball_decryptor import __version__; print(__version__)")

echo "=== Building Pinball Asset Decryptor v${VERSION} for macOS ==="

# --- Generate .icns from the PNG ----------------------------------------
ICONSET="$SCRIPT_DIR/build/icon.iconset"
mkdir -p "$ICONSET"
sips -z 16 16     "$ROOT_DIR/pinball_decryptor/icon.png" --out "$ICONSET/icon_16x16.png"      2>/dev/null
sips -z 32 32     "$ROOT_DIR/pinball_decryptor/icon.png" --out "$ICONSET/icon_16x16@2x.png"   2>/dev/null
sips -z 32 32     "$ROOT_DIR/pinball_decryptor/icon.png" --out "$ICONSET/icon_32x32.png"      2>/dev/null
sips -z 64 64     "$ROOT_DIR/pinball_decryptor/icon.png" --out "$ICONSET/icon_32x32@2x.png"   2>/dev/null
sips -z 128 128   "$ROOT_DIR/pinball_decryptor/icon.png" --out "$ICONSET/icon_128x128.png"    2>/dev/null
sips -z 256 256   "$ROOT_DIR/pinball_decryptor/icon.png" --out "$ICONSET/icon_128x128@2x.png" 2>/dev/null
sips -z 256 256   "$ROOT_DIR/pinball_decryptor/icon.png" --out "$ICONSET/icon_256x256.png"    2>/dev/null
iconutil -c icns "$ICONSET" -o "$SCRIPT_DIR/build/icon.icns"

# --- PyInstaller build --------------------------------------------------
echo "Running PyInstaller..."
cd "$ROOT_DIR"
# Install the FULL runtime dep set (requirements.txt: unicorn / capstone /
# numpy / zstandard / pycryptodome / Pillow) PLUS the build-only extras
# (pyinstaller, the UnityPy/fsb5/pyogg Godot-asset libs) and faster-whisper.
# This MUST stay in sync with requirements.txt -- if a runtime dep isn't
# installed here, PyInstaller's --collect-all / import analysis below collects
# nothing and the frozen .app silently ships without it.  Stern audio was
# dead-on-arrival on macOS for exactly this reason: the build installed
# UnityPy/fsb5/pyogg but never unicorn/capstone/numpy, so all 4 Stern prereqs
# showed missing in a bundle that pip can't fix.  No `|| true` -- a failed dep
# install must abort the build, not silently ship a broken bundle.
pip3 install -r "$ROOT_DIR/requirements.txt" pyinstaller UnityPy fsb5 pyogg faster-whisper imageio-ffmpeg

# --add-data lines bundle the per-plugin Dockerfiles so the macOS
# DockerExecutor in spooky / jjp can find them at runtime.
#
# Plugins are loaded dynamically at startup via
# ``importlib.import_module(<string>)`` in core/registry.py —
# PyInstaller's static analyser cannot trace string-based imports
# so we MUST list each plugin package explicitly with --hidden-
# import.  Without that the bundle ships with an EMPTY plugins/
# tree (only the --add-data Dockerfiles) and every plugin fails
# with "No module named 'pinball_decryptor.plugins.<name>'" at
# startup — picker shows "no manufacturer plugins registered" and
# the app is unusable.  v0.7.1 and v0.7.2 both shipped that way.
# (--collect-submodules silently no-ops here, hence the explicit
# per-plugin list — PyInstaller's tracer DOES follow each
# __init__.py → manufacturer.py → pipeline.py chain once we tell
# it to start from the package root.)
pyinstaller \
    --name "Pinball Asset Decryptor" \
    --windowed \
    --icon "$SCRIPT_DIR/build/icon.icns" \
    --paths "$ROOT_DIR" \
    --add-data "$ROOT_DIR/pinball_decryptor/icon.png:pinball_decryptor" \
    --add-data "$ROOT_DIR/pinball_decryptor/plugins/spooky/Dockerfile:pinball_decryptor/plugins/spooky" \
    --add-data "$ROOT_DIR/pinball_decryptor/plugins/jjp/Dockerfile:pinball_decryptor/plugins/jjp" \
    --add-data "$ROOT_DIR/pinball_decryptor/plugins/jjp/partclone_to_raw.py:pinball_decryptor/plugins/jjp" \
    --add-data "$ROOT_DIR/pinball_decryptor/plugins/jjp/crypto.py:pinball_decryptor/plugins/jjp" \
    --add-data "$ROOT_DIR/pinball_decryptor/plugins/jjp/filelist.py:pinball_decryptor/plugins/jjp" \
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
    --hidden-import "pinball_decryptor.plugins.dp" \
    --hidden-import "pinball_decryptor.plugins.stern" \
    --hidden-import "pinball_decryptor.plugins.stern.engine" \
    --hidden-import "pinball_decryptor.plugins.stern.ext4" \
    --hidden-import "pinball_decryptor.plugins.stern.rawdevice" \
    --hidden-import "pinball_decryptor.plugins.stern.radium" \
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
    --distpath "$SCRIPT_DIR/build/dist" \
    --workpath "$SCRIPT_DIR/build/work" \
    --specpath "$SCRIPT_DIR/build" \
    "$SCRIPT_DIR/pyinstaller_entry.py"

APP_PATH="$SCRIPT_DIR/build/dist/Pinball Asset Decryptor.app"

# --- Ad-hoc code signing so macOS doesn't flag the app as "damaged" ------
echo "Ad-hoc code signing..."
codesign --force --deep --sign - "$APP_PATH"

# --- Package as DMG -----------------------------------------------------
echo "Creating DMG..."
mkdir -p "$SCRIPT_DIR/Output"
DMG_NAME="Pinball_Asset_Decryptor_v${VERSION}_macOS.dmg"
DMG_PATH="$SCRIPT_DIR/Output/$DMG_NAME"

if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "Pinball Asset Decryptor" \
        --volicon "$SCRIPT_DIR/build/icon.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "Pinball Asset Decryptor.app" 150 190 \
        --app-drop-link 450 190 \
        "$DMG_PATH" \
        "$APP_PATH"
else
    echo "create-dmg not found, falling back to hdiutil..."
    hdiutil create -srcfolder "$APP_PATH" \
        -volname "Pinball Asset Decryptor" \
        -format UDZO \
        "$DMG_PATH"
fi

echo ""
echo "=== Build complete ==="
echo "Output: $DMG_PATH"
