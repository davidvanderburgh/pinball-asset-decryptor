"""Stern Spike 3 OTP-key helper - the logic behind the 'Spike 3' tab.

Spike 3 (Raspberry Pi CM4) keeps the game's assets on LUKS2 volumes whose
256-bit key is fused into the board's customer OTP and lives NOWHERE in the SD
image.  The scheme is fully worked out and the decrypt runs on a PC; the one
missing input is a single read of that key off a real board.

The two standalone tools under ``stern-spike-3/tools`` already do the hard
parts, and they are the ONLY place that knows how any of it works:

* ``build_extractor_card.py`` patches Stern's signed ``boot.img`` so that, at
  boot, ``/init`` writes the 64-hex key to ``OTP_KEY.TXT`` on the FAT boot
  partition (read exactly the way Stern's own code reads it).  The rest of boot
  is unchanged, so the machine still boots the game.  Works only if the board
  does NOT enforce Raspberry Pi secure boot; if it does, the patched card just
  refuses to boot (harmless - restore the backup), and that failure is itself
  the answer to whether secure boot is on.
* ``luks_otp.py`` verifies a candidate key against a real LUKS2 header in about
  a second (and can decrypt), so one recovered key can be tried against every
  game image to settle global-vs-per-device.

This module is a CONTROL SURFACE for those two tools and nothing more.  It
builds their command lines (pure functions, so the tests read the argv without
running anything), parses ``OTP_KEY.TXT`` out of whatever the owner brings
back, and carves LUKS2 headers out of a raw image so a key can be verified.  It
reimplements none of the crypto and none of the boot-image patching - a second
copy of either is how two tools come to disagree.  The Tk tab in
:mod:`..gui.spike3_tab` drives this and streams the tools' output.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass


# --- locating the standalone tools -----------------------------------------

def repo_root():
    """The directory that holds ``stern-spike-3/`` at runtime.

    In a dev checkout that is three levels up from this file
    (``pinball_decryptor/core/spike3.py`` -> ``core`` -> ``pinball_decryptor``
    -> root).  In a frozen build (PyInstaller macOS / Linux) the tools are
    added under ``sys._MEIPASS`` beside ``pinball_decryptor/``, so that wins -
    the frozen app ships no separate Python and ``__file__`` may point into an
    archive, so the checkout math cannot be relied on there.  The Windows
    installer is not frozen (embedded Python + source tree), so it takes the
    checkout branch and finds ``{app}/stern-spike-3/tools``."""
    from pathlib import Path
    mp = getattr(sys, "_MEIPASS", None)
    if mp:
        return Path(mp)
    return Path(__file__).resolve().parents[2]


def tools_dir():
    """``<root>/stern-spike-3/tools`` as a string."""
    return str(repo_root() / "stern-spike-3" / "tools")


def build_extractor_tool():
    return os.path.join(tools_dir(), "build_extractor_card.py")


def luks_otp_tool():
    return os.path.join(tools_dir(), "luks_otp.py")


def python_exe():
    """The interpreter to run the tools with.

    ``sys.executable`` when it is a real Python (the normal case - the app is
    launched by python), else the first ``python3``/``python`` on PATH so the
    tab still works if the app is ever run frozen.  The tools are pure Python
    with only ``zstandard`` (already a project dependency)."""
    exe = sys.executable or ""
    base = os.path.basename(exe).lower()
    if exe and "python" in base:
        return exe
    import shutil
    for cand in ("python3", "python"):
        found = shutil.which(cand)
        if found:
            return found
    return exe or "python3"


# --- command lines (pure) --------------------------------------------------

def prepare_argv(source, outdir, boot_sig=None, no_sig=False, python=None):
    """argv to build the extractor ``boot.img`` + ``boot.sig`` from *source*
    (a raw SD image, or a bare ``boot.img``) into *outdir*.

    ``boot_sig`` is only meaningful when *source* is a bare ``boot.img`` - for
    a whole raw image the tool pulls both files out of partition 1 itself.
    ``no_sig`` writes no boot.sig (the enforced-board test - see run_prepare)."""
    argv = [python or python_exe(), build_extractor_tool(), source,
            "-o", outdir]
    if boot_sig:
        argv += ["--boot-sig", boot_sig]
    if no_sig:
        argv += ["--no-sig"]
    return argv


def verify_argv(header, key_hex, slot="0", digest="0", python=None):
    """argv to verify *key_hex* against a carved LUKS2 *header*."""
    return [python or python_exe(), luks_otp_tool(), "verify", header,
            "--key-hex", key_hex, "--slot", slot, "--digest", digest]


def decrypt_probe_argv(image, header, part_base_lba, key_hex, out,
                       sector=0, count=8, python=None):
    """argv to decrypt a few sectors - a spot check that the key really opens
    the volume, not just the header digest."""
    return [python or python_exe(), luks_otp_tool(), "decrypt", image,
            "--header", header, "--part-base-lba", str(int(part_base_lba)),
            "--key-hex", key_hex, "--sector", str(int(sector)),
            "--count", str(int(count)), "--out", out]


# --- running the tools IN-PROCESS ------------------------------------------
#
# The tools are pure Python (build_extractor_card needs only ``zstandard``,
# already bundled; luks_otp is stdlib), so the app runs them in ITS OWN
# interpreter rather than shelling out.  A subprocess would need a Python on
# PATH, and the frozen macOS / Linux builds ship none (``sys.executable`` is the
# app binary) - which is exactly how the first Spike 3 build failed in the field
# (``pythonw ... build_extractor_card.py: No such file``).  In-process also means
# the same dependencies the app already has, and real exceptions we can report.
# The tool FILES still have to be packaged with the app (installer/*.iss,
# build_linux.sh, build_macos.sh add ``stern-spike-3/tools``); this only removes
# the second interpreter, not the need to ship the code.

_MODULE_CACHE = {}


def _load_module(path):
    """Import a standalone tool file by absolute *path* (the ``stern-spike-3``
    dir has a hyphen, so it is not an ordinary package import).  Cached.
    Returns the module, or None if the file is missing or fails to import."""
    if path in _MODULE_CACHE:
        return _MODULE_CACHE[path]
    import importlib.util
    if not os.path.exists(path):
        return None
    name = "_spike3_" + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:               # noqa: BLE001 - e.g. zstandard missing
        return None
    _MODULE_CACHE[path] = mod
    return mod


def tools_available():
    """True when both tool files are present where the app can reach them -
    the check the tab makes before offering to run anything, so a missing
    install surfaces a plain sentence instead of an interpreter error."""
    return (os.path.exists(build_extractor_tool())
            and os.path.exists(luks_otp_tool()))


def _run_module_main(mod, argv):
    """Call *mod*.main(*argv*) in-process, capturing everything it prints and
    turning its exit into an ``(rc, text)`` pair.  argparse errors and explicit
    ``sys.exit`` both come back as a non-zero rc rather than killing the app."""
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            ret = mod.main(argv)
        rc = int(ret) if ret is not None else 0
    except SystemExit as exc:
        code = exc.code
        if code is None:
            rc = 0
        elif isinstance(code, int):
            rc = code
        else:
            # ``sys.exit("message")`` - the tool's own error string, which
            # Python would print to stderr; keep it so the user sees why.
            buf.write(str(code))
            rc = 1
    except Exception as exc:        # noqa: BLE001 - report, never crash the app
        buf.write("\nerror: %s: %s" % (type(exc).__name__, exc))
        rc = 1
    return rc, buf.getvalue()


def run_prepare(source, outdir, boot_sig=None, no_sig=False):
    """Build the extractor ``boot.img`` (+ ``boot.sig``) from *source* into
    *outdir*, in-process.  Returns ``(rc, output_text)``; rc 0 on success.

    ``no_sig`` builds the enforced-board TEST variant: it writes no ``boot.sig``
    at all, so the deploy is "copy this boot.img, keep config.txt, and DELETE
    boot.sig from the card".  A board that does not enforce secure boot boots the
    ramdisk with no signature check and dumps the key; an enforcing board rejects
    a missing signature, which is the definitive confirmation that it enforces."""
    mod = _load_module(build_extractor_tool())
    if mod is None:
        return 1, ("Cannot load build_extractor_card.py. The Spike 3 tools did "
                   "not ship with this build - reinstall the latest version.")
    argv = [source, "-o", outdir]
    if boot_sig:
        argv += ["--boot-sig", boot_sig]
    if no_sig:
        argv += ["--no-sig"]
    return _run_module_main(mod, argv)


def run_verify(header, key_hex, slot="0", digest="0"):
    """Verify *key_hex* against a carved LUKS2 *header*, in-process.  Returns
    ``(rc, output_text)``; rc 0 == the key opens it, 2 == it does not."""
    mod = _load_module(luks_otp_tool())
    if mod is None:
        return 1, ("Cannot load luks_otp.py. The Spike 3 tools did not ship "
                   "with this build - reinstall the latest version.")
    return _run_module_main(
        mod, ["verify", header, "--key-hex", key_hex,
              "--slot", slot, "--digest", digest])


# --- the key, out of whatever the owner brings back ------------------------

_KEY_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")


def is_valid_key_hex(s):
    """True for exactly 64 hex characters (a 32-byte keyfile)."""
    if not isinstance(s, str):
        return False
    s = s.strip()
    return len(s) == 64 and all(c in "0123456789abcdefABCDEF" for c in s)


def parse_key_text(text):
    """Pull the 64-hex key out of ``OTP_KEY.TXT`` content.

    The dump is ``xxd -p -c 32`` output - normally one 64-char line, maybe with
    a trailing newline.  We accept that, and also a key embedded in a longer
    report, but we never return a fragment: it must be exactly 64 hex chars
    bounded by non-hex (or the string ends), lower-cased."""
    if text is None:
        return None
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    flat = text.strip()
    if is_valid_key_hex(flat):
        return flat.lower()
    # collapse internal whitespace first: xxd can wrap, and a pasted key may
    # carry stray spaces/newlines the owner did not mean.
    collapsed = re.sub(r"\s+", "", flat)
    if is_valid_key_hex(collapsed):
        return collapsed.lower()
    m = _KEY_RE.search(flat)
    return m.group(0).lower() if m else None


@dataclass
class KeyRead:
    key_hex: "str | None" = None
    source: str = ""           # "text", "otp_file", "raw_image", "raw_fallback"
    note: str = ""


def _find_otp_txt(folder):
    """OTP_KEY.TXT in *folder*, case-insensitive; None if absent."""
    try:
        for name in os.listdir(folder):
            if name.lower() == "otp_key.txt":
                return os.path.join(folder, name)
    except OSError:
        pass
    return None


def _fat_reader():
    """The build_extractor_card module (for its ``FatReader``/MBR helpers), or
    None if it cannot be loaded."""
    return _load_module(build_extractor_tool())


def read_key_from_image(path):
    """Best-effort: read OTP_KEY.TXT out of the FAT partition of a raw SD
    image, with the tool's own raw-last-sector fallback.  Returns a
    :class:`KeyRead`."""
    import struct
    bec = _fat_reader()
    try:
        with open(path, "rb") as f:
            head = f.read(512)
            if head[510:512] != b"\x55\xaa":
                return KeyRead(note="Not a raw SD image (no MBR signature). "
                                    "Point me at OTP_KEY.TXT instead.")
            e = head[446:446 + 16]
            lba = struct.unpack_from("<I", e, 8)[0]
            nsec = struct.unpack_from("<I", e, 12)[0]
            f.seek(lba * 512)
            part = f.read(min(nsec * 512, 256 * 1024 * 1024))
    except OSError as exc:
        return KeyRead(note="Could not read %s: %s" % (path, exc))
    if bec is not None:
        try:
            fat = bec.FatReader(part)
            data = fat.find("OTP_KEY.TXT")
            if data:
                key = parse_key_text(data)
                if key:
                    return KeyRead(key, "raw_image",
                                   "Read OTP_KEY.TXT from the card's boot "
                                   "partition.")
        except Exception:           # noqa: BLE001
            pass
    # Fallback: /init writes the key raw to the last 512-byte sector of the
    # FAT partition if the vfat write ever fails.
    tail = part[-512:] if len(part) >= 512 else part
    key = parse_key_text(tail)
    if key:
        return KeyRead(key, "raw_fallback",
                       "OTP_KEY.TXT was not present, but the key was found in "
                       "the boot partition's last-sector fallback.")
    return KeyRead(note="No key found in the image. If the machine booted to "
                        "the game, send OTP_KEY.TXT from the boot partition.")


def read_key(path):
    """Resolve a key from whatever the owner brings back: a directory (look for
    OTP_KEY.TXT), a small text file (parse it), or a raw SD image (carve it).
    Returns a :class:`KeyRead`."""
    if not path or not os.path.exists(path):
        return KeyRead(note="Path does not exist.")
    if os.path.isdir(path):
        txt = _find_otp_txt(path)
        if not txt:
            return KeyRead(note="No OTP_KEY.TXT in that folder.")
        path = txt
    # A small file is treated as text (OTP_KEY.TXT or a pasted report); a large
    # one is a raw image.
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return KeyRead(note="Could not stat %s: %s" % (path, exc))
    if size <= 1 << 20:
        try:
            with open(path, "rb") as f:
                blob = f.read()
        except OSError as exc:
            return KeyRead(note="Could not read %s: %s" % (path, exc))
        key = parse_key_text(blob)
        if key:
            return KeyRead(key, "otp_file", "Read the key from %s."
                           % os.path.basename(path))
        return KeyRead(note="No 64-hex key found in %s."
                            % os.path.basename(path))
    return read_key_from_image(path)


# --- LUKS2 headers for verification ----------------------------------------

@dataclass(frozen=True)
class Partition:
    name: str
    lba: int
    desc: str


# Base LBAs from the Star Wars image; the structure is identical on every
# current Spike 3 game (see docs/KEY_EXTRACTION.md).  ``games`` (p6) is the big
# read-only asset volume - the one worth decrypting.
KNOWN_PARTITIONS = (
    Partition("games", 51740675, "audio + video assets (~35 GB, read-only)"),
    Partition("rootfs", 131073, "the OS filesystem"),
    Partition("data", 1359873, "settings"),
    Partition("connectivity", 1409026, "networking state"),
)

HEADER_SECTORS = 8192           # 4 MiB - covers the LUKS2 header + slot 0


def carve_header(image_path, lba, out_path, sectors=HEADER_SECTORS):
    """Copy *sectors* starting at *lba* out of *image_path* into *out_path* (a
    LUKS2 header).  Pure file I/O - no dd, no cryptsetup.  Returns the number
    of bytes written, or raises OSError."""
    n = int(sectors) * 512
    with open(image_path, "rb") as src:
        src.seek(int(lba) * 512)
        data = src.read(n)
    with open(out_path, "wb") as dst:
        dst.write(data)
    return len(data)


def looks_like_luks2(image_path, lba):
    """True if the sector at *lba* begins with the LUKS2 magic (``LUKS`` +
    version 2).  A cheap gate before carving a whole header."""
    try:
        with open(image_path, "rb") as f:
            f.seek(int(lba) * 512)
            sig = f.read(8)
    except OSError:
        return False
    return sig[:6] == b"LUKS\xba\xbe" and sig[6:8] == b"\x00\x02"


# --- reading the tools' output back ----------------------------------------

def interpret_verify_output(text, rc=None):
    """Turn ``luks_otp.py verify`` output into a small dict:
    ``{"valid": bool, "master_key": str|None}``.  Falls back to the exit code
    (0 == valid, 2 == invalid) when the text is unexpected."""
    valid = None
    master = None
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("RESULT: VALID"):
            valid = True
            if "master_key =" in s:
                master = s.split("master_key =", 1)[1].strip() or None
        elif s.startswith("RESULT: INVALID"):
            valid = False
    if valid is None and rc is not None:
        valid = (rc == 0)
    return {"valid": bool(valid), "master_key": master}


def secure_boot_hint(booted):
    """Plain-English reading of a Method-A boot outcome for the tab's status.

    *booted* True  -> the patched card ran, so secure boot is NOT enforced and
                      OTP_KEY.TXT should be on the card.
    *booted* False -> it refused to boot, so secure boot IS enforced; Method A
                      is closed and only a shell/serial read (or Stern's own
                      signed code) can reach the key."""
    if booted:
        return ("The machine booted the patched card, so this board does NOT "
                "enforce secure boot. The key is in OTP_KEY.TXT on the boot "
                "partition.")
    return ("The machine refused to boot the patched card, so this board "
            "DOES enforce secure boot. No harm done - restore the backup. "
            "The extractor-card route is closed for this board.")
