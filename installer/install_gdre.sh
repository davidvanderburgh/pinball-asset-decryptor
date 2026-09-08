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

# PINNED, and deliberately not "latest".  This used to ask the GitHub API for
# whatever the newest release happened to be on the day a user ran the
# installer, which means two machines installing the same app version could get
# different tools, and a tool we have never run could arrive on a user's
# machine without anything in this app changing.  Upgrading is now an edit
# here - version, URL and hash together - and the hash is checked before
# anything is unpacked, so a truncated download or a proxy's error page cannot
# be installed as if it were the tool.
#
# Verified by hand on 2026-09-08: downloaded and sha256sum'd, and it matches
# the digest GitHub reports for the asset.
VER="v2.6.4"
DL_URL="https://github.com/GDRETools/gdsdecomp/releases/download/${VER}/GDRE_tools-${VER}-linux.zip"
SHA256="eda8cb09e64a060728fa371aa80ae148d3c5584a7de2f553699936daa84e7b4e"

echo "Downloading GDRE Tools ${VER}..."
curl -L --progress-bar "$DL_URL" -o /tmp/gdre_tools.zip
GOT=$(sha256sum /tmp/gdre_tools.zip | cut -d' ' -f1)
if [ "$GOT" != "$SHA256" ]; then
    rm -f /tmp/gdre_tools.zip
    echo "ERROR: GDRE Tools ${VER} downloaded, but it is not the file this" >&2
    echo "       app was tested with (got $GOT)." >&2
    echo "       A proxy or antivirus may have altered it; try again." >&2
    exit 1
fi
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
