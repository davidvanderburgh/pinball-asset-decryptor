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
pip3 install --quiet pyinstaller pycryptodome UnityPy fsb5 pyogg Pillow 2>/dev/null || true

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
