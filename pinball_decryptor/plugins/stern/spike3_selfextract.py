"""Spike 3 OTP key self-extractor (Method A) - build the card, ingest the key.

A software-only, user-runnable way for a machine owner to read their board's
256-bit LUKS unlock key **on hardware they own**, so PAD never has to carry the
key itself.  Two halves:

* :func:`build_extractor_card` wraps the pure-Python ``build_extractor_card.py``
  tool: it patches Stern's signed boot image so, at boot, ``/init`` writes the
  key (read exactly as Stern's own code does) to ``OTP_KEY.TXT`` on the FAT boot
  partition.  The rest of boot is unchanged, so the machine still boots the game.
* :func:`ingest_otp_key` takes the 64-hex key the user reads back, **verifies it
  against the card's real LUKS header**, and writes a ``padkeys.json`` the
  extract pipeline can use (:class:`.spike3_keys.Spike3KeySource`).

This only works on boards that do **not** enforce Raspberry Pi secure boot.  On
an enforced board the patched card simply refuses to boot (harmless), and there
is no software route - see ``stern-spike-3/docs/SPIKE3_SELF_EXTRACTOR_SCOPE.md``
(the rootfs has no getty/login/remote-shell surface; enforced boards are
DMA-only).  :data:`ENFORCED_BOARD_MESSAGE` is the honest result to show then.

**No key material lives in this module or the repo.**  The key only ever exists
in the user's own files at runtime.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


class Spike3SelfExtractError(Exception):
    pass


# The build tool ships under stern-spike-3/tools/ (outside the package).  Find it
# relative to the repo root, which is three levels up from this file
# (pinball_decryptor/plugins/stern/ -> repo root).
def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, os.pardir, os.pardir, os.pardir))


def _tool_path():
    p = os.path.join(_repo_root(), "stern-spike-3", "tools",
                     "build_extractor_card.py")
    if not os.path.exists(p):
        raise Spike3SelfExtractError(
            "build_extractor_card.py not found at %s" % p)
    return p


# --------------------------------------------------------------------------
# The honest result for an enforced board (no software route exists).
# --------------------------------------------------------------------------
ENFORCED_BOARD_MESSAGE = (
    "This board enforces Raspberry Pi secure boot, so the extractor card will "
    "not boot and no software can read the OTP key on it. This is expected on a "
    "hardened board and nothing was harmed - restore the backed-up boot.img / "
    "boot.sig. The key can only be read from such a board with a hardware RAM "
    "dump (DMA), which is out of scope here. The OTP key is fleet-wide, so a "
    "single cooperating un-enforced board anywhere yields the key for every "
    "machine; and if you already have the key, PAD can still verify it against "
    "this card and extract with it."
)


def deploy_instructions(out_dir, no_sig=False):
    """Human-readable deploy + read-back steps for a freshly built card."""
    boot = os.path.join(out_dir, "boot.img")
    if no_sig:
        sig_step = ("3. DELETE boot.sig from the card (keep config.txt). With "
                    "--no-sig there is no signature at all - the definitive "
                    "enforced-vs-not test.")
    else:
        sig_step = ("3. Copy the patched boot.img AND boot.sig onto that FAT "
                    "partition, overwriting the originals.")
    return "\n".join((
        "Deploy (keep your backups - every step is reversible):",
        "1. Power the machine off, remove the SD card, put it in a PC. Its first "
        "partition is FAT and mounts anywhere; ignore the rest (encrypted).",
        "2. BACK UP the card's original boot.img and boot.sig first.",
        sig_step,
        "4. Put the card back and power on.",
        "   - Boots to the game  -> key dumped (secure boot NOT enforced).",
        "   - Won't boot / blank  -> secure boot IS enforced; restore the backup "
        "(see the enforced-board note).",
        "5. Power off, bring the card to a PC, read OTP_KEY.TXT (64 hex chars) "
        "from the FAT partition.",
        "6. Hand OTP_KEY.TXT back to PAD to verify and use; then restore the "
        "original boot.img/boot.sig so the machine updates normally.",
        "",
        "Patched boot image: %s" % boot,
    ))


class ExtractorCardResult:
    def __init__(self, out_dir, boot_img, boot_sig, no_sig, log):
        self.out_dir = out_dir
        self.boot_img = boot_img
        self.boot_sig = boot_sig
        self.no_sig = no_sig
        self.log = log

    @property
    def instructions(self):
        return deploy_instructions(self.out_dir, self.no_sig)


def build_extractor_card(src, out_dir, *, no_sig=False, python=None):
    """Build the OTP-key extractor card from a Spike 3 ``*.raw`` or a BOOT.IMG.

    Runs the ``build_extractor_card.py`` tool (reusing all of its logic: raw
    partition-1 extraction, the cpio patch, and boot.sig SHA-256 regeneration)
    and returns an :class:`ExtractorCardResult`.  The source is only read.
    """
    if not os.path.exists(src):
        raise Spike3SelfExtractError("input not found: %s" % src)
    os.makedirs(out_dir, exist_ok=True)
    cmd = [python or sys.executable, _tool_path(), src, "-o", out_dir]
    if no_sig:
        cmd.append("--no-sig")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise Spike3SelfExtractError(
            "card build failed:\n%s" % (proc.stderr or proc.stdout or
                                        "(no output)"))
    boot_img = os.path.join(out_dir, "boot.img")
    if not os.path.exists(boot_img):
        raise Spike3SelfExtractError(
            "card build reported success but produced no boot.img")
    boot_sig = os.path.join(out_dir, "boot.sig")
    if no_sig:
        boot_sig = None
    elif not os.path.exists(boot_sig):
        boot_sig = None
    return ExtractorCardResult(out_dir, boot_img, boot_sig, no_sig, proc.stdout)


# --------------------------------------------------------------------------
# Ingest + verify the key the user read back
# --------------------------------------------------------------------------
def parse_otp_key_text(text):
    """Parse the key out of OTP_KEY.TXT or a probe's SPIKE3_KEY= line.

    Accepts: bare 64 hex chars (what ``xxd -p -c 32`` writes), a
    ``SPIKE3_KEY=<64hex>`` line (what ``spike3_otp_probe.sh`` prints), or raw
    32 bytes.  Returns the 32-byte key, or raises on anything malformed -
    never a truncated/guessed key.
    """
    if isinstance(text, (bytes, bytearray)):
        if len(text) == 32:
            return bytes(text)
        text = text.decode("latin1", "replace")
    hexstr = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "SPIKE3_KEY=" in line:
            line = line.split("SPIKE3_KEY=", 1)[1].strip()
        line = line.replace(" ", "")
        if len(line) == 64 and all(c in "0123456789abcdefABCDEF" for c in line):
            hexstr = line
            break
    if hexstr is None:
        raise Spike3SelfExtractError(
            "no 64-hex-character key found in the supplied text "
            "(expected OTP_KEY.TXT contents or a SPIKE3_KEY= line)")
    return bytes.fromhex(hexstr)


def _header_for_verify(image_path):
    from . import spike3
    parts = spike3.parse_partitions_path(image_path)
    if not parts:
        raise Spike3SelfExtractError("no MBR partitions found in %s" % image_path)
    part = (spike3.partition_for_role(parts, "games")
            or spike3.partition_for_role(parts, "rootfs"))
    if part is None:
        luks = spike3.luks_partitions(parts)
        if not luks:
            raise Spike3SelfExtractError(
                "no LUKS partition in %s - not a Spike 3 card?" % image_path)
        part = luks[0]
    with open(image_path, "rb") as f:
        header = spike3.read_luks_header(f, part["start_lba"])
    return header, part


def verify_otp_key(image_path, key32):
    """True if *key32* unlocks and verifies against *image_path*'s LUKS header."""
    from . import spike3
    otp = spike3._luks_otp()
    header, _part = _header_for_verify(image_path)
    ok, _mk = otp.verify_key(header, key32, area_bytes=header.raw)
    return bool(ok)


def write_padkeys(out_path, key32):
    """Write/merge a padkeys.json carrying the OTP keyfile (64 hex).

    Merges into an existing file (keeping master_keys / spk_keyfile).  Never
    writes to the source image's directory on its own - the caller passes an
    explicit, writable *out_path* (read-only media such as an archive drive must
    not be touched)."""
    doc = {}
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if not isinstance(doc, dict):
                doc = {}
        except (OSError, ValueError):
            doc = {}
    doc["otp_keyfile"] = key32.hex()
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
    os.replace(tmp, out_path)
    return out_path


class OtpKeyResult:
    def __init__(self, verified, message, sidecar=None, key_hex=None):
        self.verified = verified
        self.message = message
        self.sidecar = sidecar
        self.key_hex = key_hex


def ingest_otp_key(key, image_path, *, out_path=None):
    """Verify a read-back OTP key against *image_path* and, if good, write it.

    *key* may be OTP_KEY.TXT text, a path to it, a SPIKE3_KEY= line, or 32 raw
    bytes.  On success a ``padkeys.json`` is written to *out_path* (default:
    ``padkeys.json`` in the current directory - NEVER next to the image, which
    may sit on read-only media).  Point the extract pipeline at it with
    ``$PAD_SPIKE3_KEYFILE``.
    """
    if isinstance(key, str) and os.path.exists(key):
        with open(key, "rb") as f:
            key = f.read()
    key32 = parse_otp_key_text(key)
    if verify_otp_key(image_path, key32):
        target = out_path or os.path.join(os.getcwd(), "padkeys.json")
        sidecar = write_padkeys(target, key32)
        return OtpKeyResult(
            True,
            "Key verified against this card and saved. Point PAD at it with "
            "$PAD_SPIKE3_KEYFILE=%s (or place it next to the image as "
            "padkeys.json) and extract." % sidecar,
            sidecar=sidecar, key_hex=key32.hex())
    return OtpKeyResult(
        False,
        "That key did NOT unlock this card. Re-read OTP_KEY.TXT (it is 64 hex "
        "characters), or if the card would not boot see the enforced-board note.")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="spike3_selfextract",
        description="Spike 3 OTP-key self-extractor: build the card, or ingest "
                    "and verify the key read back from it.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the extractor card")
    b.add_argument("input", help="a Spike 3 *.raw image or a BOOT.IMG")
    b.add_argument("-o", "--outdir", default="extractor_card_out")
    b.add_argument("--no-sig", action="store_true",
                   help="write no boot.sig (the definitive enforced-vs-not test)")

    g = sub.add_parser("ingest", help="verify a read-back key and save padkeys.json")
    g.add_argument("image", help="the Spike 3 *.raw the key was read from")
    g.add_argument("key", help="OTP_KEY.TXT (path or 64-hex) from the card")
    g.add_argument("-o", "--out", help="padkeys.json to write (default ./padkeys.json)")

    args = ap.parse_args(argv)
    if args.cmd == "build":
        res = build_extractor_card(args.input, args.outdir, no_sig=args.no_sig)
        print(res.log.rstrip())
        print(res.instructions)
        return 0
    if args.cmd == "ingest":
        res = ingest_otp_key(args.key, args.image, out_path=args.out)
        print(res.message)
        return 0 if res.verified else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
