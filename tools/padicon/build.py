"""Build the card-image icon handler (pinball_decryptor/shell/padicon64.dll).

    python tools/padicon/build.py [path to zig.exe]

One C file that calls kernel32 only.  Zig is the compiler because it is one
unzipped folder with the Windows headers in it (https://ziglang.org/download,
0.17.1 built the committed DLL); ``zig`` on PATH or the ZIG environment
variable works too.  The built DLL is committed, like the app's other
prebuilt pieces, so a release needs no compiler; padicon64.json beside it
records the SHA-256 of the sources it was built from, and
tests/test_pad1522_compact_from_explorer.py fails when they no longer match
(rebuild, commit both).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT_DIR = os.path.join(ROOT, "pinball_decryptor", "shell")
OUT = os.path.join(OUT_DIR, "padicon64.dll")
STAMP = os.path.join(OUT_DIR, "padicon64.json")
SOURCES = ("padicon.c", "padicon.def")


def source_hash():
    h = hashlib.sha256()
    for name in SOURCES:
        with open(os.path.join(HERE, name), "rb") as f:
            # line endings differ per checkout; the hash must not
            h.update(f.read().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def main(argv):
    zig = (argv[1] if len(argv) > 1 else os.environ.get("ZIG")
           or shutil.which("zig"))
    if not zig:
        sys.exit("zig not found: pass its path, or set ZIG")
    os.makedirs(OUT_DIR, exist_ok=True)
    cmd = [zig, "cc", "-target", "x86_64-windows-gnu", "-shared", "-O2",
           "-fno-stack-protector", "-fno-sanitize=all", "-Wall", "-Wextra",
           "-s",
           "-o", OUT,
           os.path.join(HERE, "padicon.c"), os.path.join(HERE, "padicon.def"),
           "-lc", "-lkernel32"]
    subprocess.run(cmd, check=True, cwd=HERE)
    for junk in ("padicon.lib", "padicon64.lib", "padicon64.pdb"):
        try:
            os.remove(os.path.join(OUT_DIR, junk))
        except OSError:
            pass
    with open(OUT, "rb") as f:
        dll = hashlib.sha256(f.read()).hexdigest()
    with open(STAMP, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"sources": source_hash(), "dll": dll}, f, indent=1)
        f.write("\n")
    print("wrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))


if __name__ == "__main__":
    main(sys.argv)
