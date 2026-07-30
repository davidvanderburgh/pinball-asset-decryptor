"""Guards on what the JJP ISO write path leaves behind in the image.

The install ISO's sda3 image is the machine's whole ROOT filesystem, not just
a bag of assets: JJP's own installer restores it to both root slots and boots
it.  So anything this path gets wrong about that filesystem shows up on the
machine as a game that will not stay up (``rungame.sh`` re-runs the game
forever and says nothing on a release image) or as a reboot loop
(``runonce.sh`` reboots when it finds a system file non-executable).  These
tests pin the three things that were wrong.
"""

import hashlib
import os
import struct
import zlib

import pytest

from pinball_decryptor.plugins.jjp import crypto_v3 as v3
from pinball_decryptor.plugins.jjp.crypto import PRNG, xor_keystream
from pinball_decryptor.plugins.jjp import pipeline as P
from pinball_decryptor.plugins.jjp.executor import CommandError


SONIC_PATH = "/jjpe/gen1/Sonic/edata/graphics/UI/panel.png"


# --------------------------------------------------------------------------
# A fake debugfs: a dict of path -> (bytes, mode, uid, gid), driven by the
# same command strings the pipeline sends to the real one.
# --------------------------------------------------------------------------

class FakeImage:
    def __init__(self, files):
        # files: {path: (content_bytes, perms, uid, gid)}
        self.files = dict(files)
        self.commands = []

    def run(self, command, writable=False, timeout=120):
        self.commands.append(command)
        parts = command.split(None, 1)
        verb = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        args = [a.strip('"') for a in rest.split('" "')] if rest else []
        if args:
            args[0] = args[0].lstrip('"')
            args[-1] = args[-1].rstrip('"')

        if verb == "stat":
            path = rest.strip('"')
            if path not in self.files:
                raise CommandError(command, 1, "File not found by ext2_lookup")
            data, perms, uid, gid = self.files[path]
            return ("Inode: 12   Type: regular    Mode:  %04o   Flags: 0x80000\n"
                    "Generation: 0    Version: 0x00000000:00000000\n"
                    "User: %5d   Group: %5d   Project:     0   Size: %d\n"
                    % (perms, uid, gid, len(data)))
        if verb == "rm":
            self.files.pop(rest.strip('"'), None)
            return ""
        if verb == "write":
            src, dest = args[0], args[1]
            with open(src, "rb") as fh:
                data = fh.read()
            # This is the behaviour that cost us: debugfs builds a brand new
            # inode from the staging file, so mode/uid/gid come from there.
            st = os.stat(src)
            self.files[dest] = (data, st.st_mode & 0o7777, 0, 0)
            return "Allocated inode: 12\n"
        if verb == "sif":
            path, field, value = rest.split('" ', 1)[0].strip('"'), None, None
            tail = rest.split('" ', 1)[1].split()
            field, value = tail[0], tail[1]
            data, perms, uid, gid = self.files[path]
            if field == "mode":
                perms = int(value, 8) & 0o7777
            elif field == "uid":
                uid = int(value)
            elif field == "gid":
                gid = int(value)
            self.files[path] = (data, perms, uid, gid)
            return ""
        raise AssertionError("unexpected debugfs command: %r" % command)


def _mod_pipe(tmp_path, image, **attrs):
    """A StandaloneModPipeline wired to a FakeImage instead of debugfs."""
    pipe = object.__new__(P.StandaloneModPipeline)
    pipe.log = lambda *a, **k: None
    pipe.on_progress = lambda *a, **k: None
    pipe.cancelled = False
    pipe._check_cancel = lambda: None
    pipe._debugfs_run = image.run
    pipe._debugfs_tmp = str(tmp_path)
    pipe._native_debugfs_path = "debugfs"
    pipe.game_name = "Sonic"
    pipe.changed_files = []
    for k, v in attrs.items():
        setattr(pipe, k, v)
    return pipe


# --------------------------------------------------------------------------
# 1.  Modes and ownership must survive a debugfs replace
# --------------------------------------------------------------------------

def test_inode_meta_is_read_off_debugfs_stat(tmp_path):
    image = FakeImage({"/etc/x": (b"x", 0o755, 1000, 44)})
    pipe = _mod_pipe(tmp_path, image)
    assert pipe._debugfs_inode_meta("/etc/x") == (0o755, 1000, 44)


def test_inode_meta_is_none_for_a_file_that_is_not_there(tmp_path):
    pipe = _mod_pipe(tmp_path, FakeImage({}))
    assert pipe._debugfs_inode_meta("/etc/nope") is None


def test_restoring_meta_is_a_noop_without_meta(tmp_path):
    image = FakeImage({"/etc/x": (b"x", 0o644, 0, 0)})
    pipe = _mod_pipe(tmp_path, image)
    pipe._debugfs_restore_inode_meta("/etc/x", None)
    assert image.commands == []


def test_system_file_write_keeps_the_exec_bit(tmp_path):
    """A replaced executable used to come back 0644 root:root.

    On a JJP card that is not cosmetic: runonce.sh reboots the machine when
    it finds jjpe-mount-generator non-executable, and the installer ships the
    same workaround, so a lost exec bit is a documented way to break boot.
    """
    gen = "/etc/systemd/system-generators/jjpe-mount-generator"
    image = FakeImage({gen: (b"#!/bin/sh\nold\n", 0o755, 0, 0)})
    replacement = tmp_path / "sysfile"
    replacement.write_bytes(b"#!/bin/sh\nnew\n")

    pipe = _mod_pipe(tmp_path, image)
    pipe._write_system_files_debugfs(
        [("system" + gen, str(replacement))])

    data, perms, uid, gid = image.files[gen]
    assert data == b"#!/bin/sh\nnew\n"
    assert perms == 0o755, "the replaced generator must stay executable"
    assert (uid, gid) == (0, 0)


def test_system_file_write_keeps_a_non_root_owner(tmp_path):
    image = FakeImage({"/etc/thing": (b"old", 0o640, 1000, 1000)})
    replacement = tmp_path / "thing"
    replacement.write_bytes(b"new")

    pipe = _mod_pipe(tmp_path, image)
    pipe._write_system_files_debugfs([("system/etc/thing", str(replacement))])

    assert image.files["/etc/thing"] == (b"new", 0o640, 1000, 1000)


# --------------------------------------------------------------------------
# 2.  The post-write spot-check has to use the cipher the write used
# --------------------------------------------------------------------------

def _png(size=64, seed=b"\x11\x22\x33\x44"):
    def chunk(typ, body):
        return (struct.pack(">I", len(body)) + typ + body
                + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + (seed * (size * 3 // 4 + 1))[:size * 3]
                   for _ in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _encrypt_v3(content, path, game_name, lead, trail):
    body = bytearray(os.urandom(lead) + content + os.urandom(trail))
    v3._unshuffle(body, lead)
    p = PRNG()
    v3.set_seeds_for_crypto(p, path, v3.crypto_key(path, game_name))
    return xor_keystream(bytes(body), p)


def _verify_pipe(tmp_path, disk_encrypted, content, lead, scheme):
    """A pipeline ready to run _verify_raw_image over one scheme-3 asset."""
    fl = tmp_path / "fl_decrypted.dat"
    fl.write_text("%s,%d,0,0\n" % (SONIC_PATH, lead), encoding="latin-1")

    rel = SONIC_PATH.split("/edata/", 1)[1]
    replacement = tmp_path / "panel.png"
    replacement.write_bytes(content)

    pipe = object.__new__(P.StandaloneModPipeline)
    pipe.log = lambda *a, **k: None
    pipe.on_progress = lambda *a, **k: None
    pipe.game_name = "Sonic"
    pipe.fl_dat_path = str(fl)
    pipe.changed_files = [(rel, str(replacement))]
    pipe._write_scheme = scheme
    pipe._debugfs_dump_file = lambda path, timeout=None: disk_encrypted
    pipe._expected_spot = {
        'md5': hashlib.md5(disk_encrypted).hexdigest(),
        'size': len(disk_encrypted),
        'content_md5': hashlib.md5(content).hexdigest(),
        'content_len': len(content),
    }
    return pipe


def test_scheme3_spot_check_passes_on_a_good_write(tmp_path):
    """Regression: this check always used the legacy cipher, so on a Sonic
    image it decrypted noise and failed a write that was perfectly fine —
    "Modified files did not persist to the raw image. The ISO was NOT built."
    """
    content = _png()
    enc = _encrypt_v3(content, SONIC_PATH, "Sonic", lead=216, trail=96)
    pipe = _verify_pipe(tmp_path, enc, content, 216, v3.SCHEME_V3)

    pipe._verify_raw_image("/var/tmp/whatever.img")  # no raise


def test_legacy_cipher_on_a_scheme3_asset_is_what_used_to_break(tmp_path):
    """Pins why the branch above has to exist.

    Reading a scheme-3 asset with the legacy cipher yields noise, so the
    spot-check reported "Modified files did not persist to the raw image /
    debugfs write may have failed" on a write that had actually worked — and
    refused to build the ISO.  Scheme 3 shipped in v0.96.0; this check was
    never taught about it.
    """
    content = _png()
    enc = _encrypt_v3(content, SONIC_PATH, "Sonic", lead=216, trail=96)
    pipe = _verify_pipe(tmp_path, enc, content, 216, v3.SCHEME_LEGACY)

    with pytest.raises(P.PipelineError, match="did not persist"):
        pipe._verify_raw_image("/var/tmp/whatever.img")


def test_scheme3_spot_check_still_fails_on_a_bad_write(tmp_path):
    """The fix must not turn the check into a rubber stamp: content that is
    not what we asked for still has to stop the ISO."""
    content = _png()
    other = _png(seed=b"\xaa\xbb\xcc\xdd")
    enc = _encrypt_v3(other, SONIC_PATH, "Sonic", lead=216, trail=96)
    pipe = _verify_pipe(tmp_path, enc, content, 216, v3.SCHEME_V3)
    # Encrypted bytes match what was written; the *content* is the wrong PNG.
    pipe._expected_spot['content_md5'] = hashlib.md5(content).hexdigest()

    with pytest.raises(P.PipelineError):
        pipe._verify_raw_image("/var/tmp/whatever.img")


def test_spot_check_catches_encrypted_bytes_that_did_not_land(tmp_path):
    content = _png()
    enc = _encrypt_v3(content, SONIC_PATH, "Sonic", lead=216, trail=96)
    pipe = _verify_pipe(tmp_path, enc, content, 216, v3.SCHEME_V3)
    pipe._expected_spot['md5'] = hashlib.md5(b"something else").hexdigest()

    with pytest.raises(P.PipelineError):
        pipe._verify_raw_image("/var/tmp/whatever.img")


# --------------------------------------------------------------------------
# 3.  e2fsck's verdict must not be thrown away
# --------------------------------------------------------------------------

class _FsckExecutor:
    def __init__(self, returncode, output):
        self.returncode = returncode
        self.output = output

    def stream(self, cmd, timeout=None):
        if self.returncode:
            raise CommandError(cmd, self.returncode, self.output)
        for line in self.output.splitlines():
            yield line

    def run(self, cmd, timeout=None):
        return ""


def _convert_pipe(returncode, output):
    pipe = object.__new__(P.StandaloneModPipeline)
    pipe.log = lambda *a, **k: None
    pipe.on_progress = lambda *a, **k: None
    pipe.executor = _FsckExecutor(returncode, output)
    pipe._wsl_img = "/var/tmp/jjp_raw.img"
    pipe.changed_files = []          # skips the spot-check

    def _tools():
        raise RuntimeError("reached the tool check")
    pipe._ensure_iso_tools = _tools
    return pipe


def test_uncorrected_fsck_errors_block_the_iso():
    """exit 4 means errors are LEFT UNCORRECTED.  Building an ISO from that
    hands the machine a root filesystem its own e2fsck then "repairs" by
    deleting things — the ISO must not be built."""
    pipe = _convert_pipe(4, "Inode 12 is in use but has dtime set\n"
                            "/var/tmp/jjp_raw.img: UNEXPECTED INCONSISTENCY")

    with pytest.raises(P.PipelineError) as exc:
        pipe._phase_convert_standalone()
    assert "UNEXPECTED INCONSISTENCY" in str(exc.value)


def test_repaired_fsck_does_not_block_the_iso():
    """exit 1 is the normal outcome after debugfs -w: it repaired things."""
    pipe = _convert_pipe(1, "/var/tmp/jjp_raw.img: ***** FILE SYSTEM WAS "
                            "MODIFIED *****")

    with pytest.raises(RuntimeError, match="reached the tool check"):
        pipe._phase_convert_standalone()


def test_clean_fsck_does_not_block_the_iso():
    pipe = _convert_pipe(0, "/var/tmp/jjp_raw.img: clean, 16440/2097152 files")

    with pytest.raises(RuntimeError, match="reached the tool check"):
        pipe._phase_convert_standalone()
