"""Build the Windows 11 short-menu handler and its package (PAD-1523).

    python tools/padmenu/build.py ZIG SIGNTOOL

Writes, beside the card icon handler in pinball_decryptor/shell/:

    padmenu64.dll      the IExplorerCommand handler (padmenu.c)
    padmenu.msix       the sparse package that declares it, signed
    padmenu.cer        the certificate it is signed with (public part)
    padmenu64.json     SHA-256 of the sources each was built from

Zig builds the DLL, as for tools/padicon (0.17.1 built the committed one).
The package is a zip of the manifest, its logo, [Content_Types].xml and
AppxBlockMap.xml (the SHA-256 of every 64 KiB block of every file), which
this writes itself, stored and with fixed times; then signtool signs it
(the Windows SDK BuildTools NuGet package, 10.0.28000.2957 signed the
committed one: unzip it, bin/<ver>/x64/signtool.exe).

WHY SIGNED, AND WITH WHAT.  Windows refuses an unsigned package that
declares an application for one user ("an unsigned package cannot include
Executable activations"), and only a package's own application can carry a
short-menu entry.  The certificate is the app's own, self-signed
("CN=Pinball Asset Decryptor", code signing, to 2056): its PRIVATE key lives
only in the maintainer's certificate store (CurrentUser\\My), never in
this repository; padmenu.cer is the public part, and the installer (which
runs elevated) adds it to the machine's Trusted People, the store Windows
reads a package's trust from.  That trusts packages signed with this key and
nothing else.  A lost key is a new certificate: build again with a new one,
commit the new .cer, and the next install trusts that.

All four files are committed, so a release needs no compiler and no key;
tests/test_pad1523_short_menu.py fails when the sources no longer match
the stamp (rebuild, commit them all).

The package's version is VERSION below: raise it whenever the manifest or
the DLL changes, so an installed older one is replaced (webui/shell_menu.py
compares the two).
"""
import base64
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT_DIR = os.path.join(ROOT, "pinball_decryptor", "shell")
DLL = os.path.join(OUT_DIR, "padmenu64.dll")
MSIX = os.path.join(OUT_DIR, "padmenu.msix")
STAMP = os.path.join(OUT_DIR, "padmenu64.json")
ICON = os.path.join(ROOT, "pinball_decryptor", "icon.ico")
SOURCES = ("padmenu.c", "padmenu.def", "AppxManifest.xml", "build.py")

#: the package's version; webui/shell_menu.VERSION reads it from the stamp
VERSION = "1.0.0.0"

BLOCK = 65536
EPOCH = (2026, 11, 23, 0, 0, 0)


def source_hash():
    h = hashlib.sha256()
    for name in SOURCES:
        with open(os.path.join(HERE, name), "rb") as f:
            # line endings differ per checkout; the hash must not
            h.update(f.read().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def build_dll(zig):
    cmd = [zig, "cc", "-target", "x86_64-windows-gnu", "-shared", "-O2",
           "-fno-stack-protector", "-fno-sanitize=all", "-Wall", "-Wextra",
           "-s", "-o", DLL, os.path.join(HERE, "padmenu.c"),
           os.path.join(HERE, "padmenu.def"),
           "-lc", "-lkernel32", "-ladvapi32", "-lole32", "-luuid"]
    subprocess.run(cmd, check=True, cwd=HERE)
    for junk in ("padmenu64.lib", "padmenu64.pdb", "padmenu.lib"):
        try:
            os.remove(os.path.join(OUT_DIR, junk))
        except OSError:
            pass


def logo_png():
    """The app's icon at 150 px, as the package's logo."""
    from PIL import Image
    im = Image.open(ICON)
    sizes = sorted(im.info.get("sizes") or [im.size])
    im.size = sizes[-1]
    im = im.convert("RGBA").resize((150, 150), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def manifest():
    with open(os.path.join(HERE, "AppxManifest.xml"), "rb") as f:
        text = f.read().replace(b"\r\n", b"\n")
    return text.replace(b"@VERSION@", VERSION.encode("ascii"))


def _block_map(files, lfh):
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
           '<BlockMap xmlns="http://schemas.microsoft.com/appx/2010/blockmap"'
           ' HashMethod="http://www.w3.org/2001/04/xmlenc#sha256">']
    for name, data in files:
        out.append('<File Name="%s" Size="%d" LfhSize="%d">'
                   % (name.replace("/", "\\"), len(data), lfh[name]))
        for i in range(0, max(len(data), 1), BLOCK):
            digest = hashlib.sha256(data[i:i + BLOCK]).digest()
            out.append('<Block Hash="%s"/>'
                       % base64.b64encode(digest).decode("ascii"))
        out.append('</File>')
    out.append('</BlockMap>')
    return "\r\n".join(out).encode("utf-8")


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
    'content-types">'
    '<Default Extension="png" ContentType="image/png"/>'
    '<Override PartName="/AppxManifest.xml" '
    'ContentType="application/vnd.ms-appx.manifest+xml"/>'
    '<Override PartName="/AppxBlockMap.xml" '
    'ContentType="application/vnd.ms-appx.blockmap+xml"/>'
    '</Types>').encode("utf-8")


def pack(files, out):
    """Write the package: *files* ``[(name, bytes)]``, then the block map
    and the content types."""
    buf = io.BytesIO()
    lfh = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, data in files:
            info = zipfile.ZipInfo(name, EPOCH)
            info.create_system = 0
            start = buf.tell()
            z.writestr(info, data)
            # the local header's real length: 30 + name + extra field
            raw = buf.getvalue()[start:start + 30]
            nlen, xlen = struct.unpack("<HH", raw[26:30])
            lfh[name] = 30 + nlen + xlen
        for name, data in (("AppxBlockMap.xml", _block_map(files, lfh)),
                           ("[Content_Types].xml", CONTENT_TYPES)):
            info = zipfile.ZipInfo(name, EPOCH)
            info.create_system = 0
            z.writestr(info, data)
    with open(out, "wb") as f:
        f.write(buf.getvalue())


#: the signing certificate's subject: the manifest's Publisher must be it
SUBJECT = "CN=Pinball Asset Decryptor"
CER = os.path.join(OUT_DIR, "padmenu.cer")


def sign(signtool):
    subprocess.run([signtool, "sign", "/fd", "SHA256", "/s", "My",
                    "/n", SUBJECT[3:], MSIX], check=True)
    ps = ("$c = Get-ChildItem Cert:\\CurrentUser\\My | Where-Object "
          "Subject -eq '%s' | Where-Object HasPrivateKey | "
          "Sort-Object NotAfter | Select-Object -Last 1; "
          "Export-Certificate -Cert $c -FilePath '%s' -Type CERT | Out-Null"
          % (SUBJECT, CER))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def thumbprint(cer):
    """The certificate's SHA-1 thumbprint, as Windows names it in a store"""
    with open(cer, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest().upper()


def main(argv):
    zig = (argv[1] if len(argv) > 1 else os.environ.get("ZIG")
           or shutil.which("zig"))
    signtool = (argv[2] if len(argv) > 2 else os.environ.get("SIGNTOOL")
                or shutil.which("signtool"))
    if not zig:
        sys.exit("zig not found: pass its path, or set ZIG")
    if not signtool:
        sys.exit("signtool not found: pass its path, or set SIGNTOOL")
    os.makedirs(OUT_DIR, exist_ok=True)
    build_dll(zig)
    pack([("AppxManifest.xml", manifest()), ("logo.png", logo_png())], MSIX)
    sign(signtool)
    digest = {}
    for path in (DLL, MSIX, CER):
        with open(path, "rb") as f:
            digest[os.path.basename(path)] = hashlib.sha256(
                f.read()).hexdigest()
    with open(STAMP, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"sources": source_hash(), "version": VERSION,
                   "dll": digest["padmenu64.dll"],
                   "msix": digest["padmenu.msix"],
                   "cer": digest["padmenu.cer"],
                   "thumbprint": thumbprint(CER)}, f, indent=1)
        f.write("\n")
    for path in (DLL, MSIX):
        print("wrote %s (%d bytes)" % (path, os.path.getsize(path)))


if __name__ == "__main__":
    main(sys.argv)
