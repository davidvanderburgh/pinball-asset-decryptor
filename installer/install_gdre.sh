#!/bin/bash
# Install GDRE Tools (Godot RE Tools) — the single source of truth.
#
# Both prerequisite installers run this exact script:
#   * install_prerequisites.ps1       runs it inside WSL (as root)
#   * install_prerequisites_linux.sh  runs it natively
#
# Keeping the logic in one real .sh file — pinned to LF endings via
# .gitattributes — is deliberate.  The previous approach embedded this
# bash inside a PowerShell here-string and piped it to WSL, which glued
# a UTF-8 BOM onto line 1 and left CRLFs that broke the `cat <<EOF`
# heredoc.  A standalone .sh cannot suffer either problem.
#
# Installs the binary to /opt/gdre_tools/ and a PATH wrapper at
# /usr/local/bin/gdre_tools.  Requires curl + unzip already installed.
set -e

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

if [ -x /opt/gdre_tools/gdre_tools.x86_64 ]; then
    echo "GDRE Tools already installed at /opt/gdre_tools — skipping."
    exit 0
fi

ASSET_SUFFIX="-linux.zip"
META=$(curl -sf https://api.github.com/repos/GDRETools/gdsdecomp/releases/latest)
DL_URL=$(echo "$META" | grep -oE "\"browser_download_url\": \"[^\"]*${ASSET_SUFFIX}\"" | head -1 | cut -d'"' -f4)
VER=$(echo "$META" | grep -oE '"tag_name": "[^"]*"' | head -1 | cut -d'"' -f4)
if [ -z "$DL_URL" ]; then
    echo "ERROR: no ${ASSET_SUFFIX} release asset on GDRETools/gdsdecomp." >&2
    exit 1
fi

echo "Downloading GDRE Tools ${VER}..."
curl -L --progress-bar "$DL_URL" -o /tmp/gdre_tools.zip
rm -rf /tmp/gdre_extract
mkdir -p /tmp/gdre_extract
unzip -o /tmp/gdre_tools.zip -d /tmp/gdre_extract/ >/dev/null

$SUDO rm -rf /opt/gdre_tools
$SUDO mkdir -p /opt/gdre_tools
$SUDO cp -f /tmp/gdre_extract/gdre_tools.x86_64 /opt/gdre_tools/
$SUDO cp -f /tmp/gdre_extract/gdre_tools.pck    /opt/gdre_tools/
$SUDO cp -f /tmp/gdre_extract/libGodotMonoDecompNativeAOT.so /opt/gdre_tools/ 2>/dev/null || true
$SUDO chmod +x /opt/gdre_tools/gdre_tools.x86_64

# Wrapper on PATH.  Quoted <<'EOF' so $LD_LIBRARY_PATH / $@ stay literal.
$SUDO tee /usr/local/bin/gdre_tools >/dev/null <<'EOF'
#!/bin/bash
export LD_LIBRARY_PATH=/opt/gdre_tools:$LD_LIBRARY_PATH
exec "/opt/gdre_tools/gdre_tools.x86_64" "$@"
EOF
$SUDO chmod +x /usr/local/bin/gdre_tools

rm -rf /tmp/gdre_tools.zip /tmp/gdre_extract
echo "GDRE Tools ${VER} installed (wrapper: /usr/local/bin/gdre_tools)."
