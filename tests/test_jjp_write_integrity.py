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
import io
import os
import struct
import zlib

import pytest

from pinball_decryptor.plugins.jjp import crypto_v3 as v3
from pinball_decryptor.plugins.jjp.crypto import PRNG, xor_keystream
from pinball_decryptor.plugins.jjp import pipeline as P
from pinball_decryptor.plugins.jjp.executor import CommandError


SONIC_PATH = "/jjpe/gen1/Sonic/edata/graphics/UI/panel.png"
SONIC_WAV = "/jjpe/gen1/Sonic/edata/audio/callouts/eggman_01.wav"


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
# 2b.  Reading the ORIGINAL slot has to use the image's own cipher, or every
#      audio safety net silently switches off
# --------------------------------------------------------------------------

def _wav(nframes, nch=1, sw=2, rate=22050, fill=b"\x11\x22"):
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(nch)
        w.setsampwidth(sw)
        w.setframerate(rate)
        w.writeframes((fill * (nframes * nch * sw))[:nframes * nch * sw])
    return buf.getvalue()


def _audio_pipe(tmp_path, orig_encrypted, scheme, entry_path=SONIC_WAV,
                filler=216):
    from pinball_decryptor.plugins.jjp.filelist import FileEntry
    pipe = object.__new__(P.StandaloneModPipeline)
    logged = []
    pipe.log = lambda msg, lvl="info": logged.append((lvl, msg))
    pipe.logged = logged
    pipe.on_progress = lambda *a, **k: None
    pipe.game_name = "Sonic"
    pipe._write_scheme = scheme
    pipe._wsl_img = "/var/tmp/jjp_raw.img"
    pipe._debugfs_dump_file = lambda path, timeout=None: orig_encrypted
    pipe.skip_duration_match = False
    pipe.keep_full_length_paths = frozenset()
    entry = FileEntry(path=entry_path, filler_size=filler,
                      crc_encrypted=0, crc_decrypted=0)
    return pipe, entry


def test_original_wav_format_is_read_with_the_v3_cipher(tmp_path):
    """Regression: this used the legacy cipher on every image, so on a
    Sonic-era one it decrypted noise, the probe returned None, and
    _maybe_convert_audio quietly passed the replacement through with NO
    format check, NO conversion and NO trim to the slot length."""
    orig = _wav(4000, nch=1, sw=2, rate=22050)
    enc = _encrypt_v3(orig, SONIC_WAV, "Sonic", lead=216, trail=96)
    pipe, entry = _audio_pipe(tmp_path, enc, v3.SCHEME_V3)

    fmt = pipe._get_original_wav_format(entry)
    assert fmt is not None, "the original slot must be readable"
    assert (fmt["nchannels"], fmt["sampwidth"], fmt["framerate"]) == (1, 2, 22050)
    assert fmt["nframes"] == 4000
    assert fmt["_orig_size"] == len(orig)


def test_unreadable_original_slot_is_reported_not_silent(tmp_path):
    """If the slot still can't be read, say so — the old code returned None
    with no message and the run looked clean."""
    pipe, entry = _audio_pipe(tmp_path, os.urandom(4096), v3.SCHEME_LEGACY)
    assert pipe._get_original_wav_format(entry) is None
    assert any(lvl == "error" and "format-checked" in msg
               for lvl, msg in pipe.logged), pipe.logged


def _logic_wav(nframes, rate=44100, nch=1, sw=2, fill=b"\x11\x22"):
    """A WAV shaped like JJP's actual audio.

    Every asset on the card is a Logic Pro export: a JUNK pad before fmt,
    then data, then LGWV/ResU/cue /LIST/bext trailing it — 2-5 KB of
    metadata, with the samples starting past offset 100 rather than at 44.
    """
    def chunk(cid, body):
        out = cid + struct.pack("<I", len(body)) + body
        return out + (b"\x00" if len(body) & 1 else b"")
    data = (fill * (nframes * nch * sw))[:nframes * nch * sw]
    body = (b"WAVE"
            + chunk(b"JUNK", b"\x00" * 64)
            + chunk(b"fmt ", struct.pack("<HHIIHH", 1, nch, rate,
                                         rate * nch * sw, nch * sw, sw * 8))
            + chunk(b"data", data)
            + chunk(b"LGWV", b"\xaa" * 972)
            + chunk(b"ResU", b"x\x9c" + b"\xbb" * 373)
            + chunk(b"cue ", b"\x01\x00\x00\x00" + b"\x00" * 24)
            + chunk(b"LIST", b"adtllabl" + b"Tempo: 120.0\x00" * 1)
            + chunk(b"bext", b"\xcc" * 602))
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_replacement_is_spliced_into_the_originals_container(tmp_path):
    """The fit has to keep the slot's byte length AND its chunks.

    Rebuilding the file canonically would hit the length only by stuffing
    the metadata budget with extra samples, and would throw away the cue
    points and labels the originals carry.
    """
    orig = _logic_wav(4000)
    enc = _encrypt_v3(orig, SONIC_WAV, "Sonic", lead=216, trail=96)
    pipe, entry = _audio_pipe(tmp_path, enc, v3.SCHEME_V3)
    fmt = pipe._get_original_wav_format(entry)
    assert fmt is not None and fmt["_orig_bytes"] == orig

    # a plain editor export: same format, same frames, no metadata chunks
    plain = _wav(4000, nch=1, sw=2, rate=44100)
    assert len(plain) != len(orig), "the fixture must differ in length"

    out = pipe._resize_wav_to_duration(plain, fmt, "audio/x.wav")
    assert len(out) == len(orig), "must land on the slot's exact size"
    for tag in (b"JUNK", b"LGWV", b"ResU", b"cue ", b"LIST", b"bext"):
        assert tag in out, f"{tag!r} chunk must survive the fit"
    # the samples really are the replacement's
    d_start, d_len = P.StandaloneModPipeline._wav_data_chunk(out)
    s_start, s_len = P.StandaloneModPipeline._wav_data_chunk(plain)
    assert out[d_start:d_start + s_len] == plain[s_start:s_start + s_len]
    # and everything around them is untouched
    assert out[:d_start] == orig[:d_start]
    assert out[d_start + d_len:] == orig[d_start + d_len:]


def test_splice_pads_a_short_replacement_and_trims_a_long_one(tmp_path):
    orig = _logic_wav(4000)
    enc = _encrypt_v3(orig, SONIC_WAV, "Sonic", lead=216, trail=96)
    pipe, entry = _audio_pipe(tmp_path, enc, v3.SCHEME_V3)
    fmt = pipe._get_original_wav_format(entry)
    for frames in (1000, 9000):
        out = pipe._resize_wav_to_duration(_wav(frames, rate=44100), fmt,
                                           "audio/x.wav")
        assert len(out) == len(orig)
        assert P.StandaloneModPipeline._wav_data_chunk(out)[1] == 4000 * 2


def test_data_chunk_walk_rejects_a_lying_header():
    """A replacement whose data chunk claims more bytes than it has is
    exactly the hand-padded file that would crash the game's parser."""
    good = _logic_wav(100)
    assert P.StandaloneModPipeline._wav_data_chunk(good) is not None
    lying = bytearray(good)
    d_start, d_len = P.StandaloneModPipeline._wav_data_chunk(good)
    struct.pack_into("<I", lying, d_start - 4, d_len + 10_000)
    assert P.StandaloneModPipeline._wav_data_chunk(bytes(lying)) is None
    assert P.StandaloneModPipeline._wav_data_chunk(b"not a wav at all") is None


def test_v3_resize_targets_the_slots_exact_byte_size(tmp_path):
    """On scheme 3 the byte count is what matters, not the frame count: the
    original may carry RIFF chunks the canonical header we write does not."""
    # A WAV whose header carries a LIST chunk inside the RIFF, so the file is
    # 12 bytes longer than the canonical layout we write for the same frames.
    data = (b"\x11\x22" * 4000)
    fmt_chunk = (b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 22050,
                                       22050 * 2, 2, 16))
    list_chunk = b"LIST" + struct.pack("<I", 4) + b"abcd"
    body = b"WAVE" + fmt_chunk + list_chunk + b"data" + struct.pack(
        "<I", len(data)) + data
    orig_padded = b"RIFF" + struct.pack("<I", len(body)) + body
    assert len(orig_padded) == len(_wav(4000)) + 12
    enc = _encrypt_v3(orig_padded, SONIC_WAV, "Sonic", lead=216, trail=96)
    pipe, entry = _audio_pipe(tmp_path, enc, v3.SCHEME_V3)
    fmt = pipe._get_original_wav_format(entry)
    assert fmt is not None and fmt["_orig_size"] == len(orig_padded)

    # A replacement with the same frame count but the plain header: it must
    # still be rewritten so the file lands on the slot's exact size.
    out = pipe._resize_wav_to_duration(_wav(4000), fmt, "audio/x.wav")
    assert len(out) == len(orig_padded), (
        "the fitted WAV has to be exactly the slot's size")


def test_legacy_resize_still_matches_frames_not_bytes(tmp_path):
    """Legacy titles keep the proven behaviour — frame matching, no byte
    budget (their content runs to EOF, so length is free)."""
    orig = _wav(4000)
    pipe, entry = _audio_pipe(tmp_path, b"", v3.SCHEME_LEGACY)
    from pinball_decryptor.plugins.jjp.audio import detect_wav_format
    fmt = detect_wav_format(orig)
    fmt["_orig_size"] = len(orig) + 12      # would force a rewrite on v3
    out = pipe._resize_wav_to_duration(_wav(4000), fmt, "audio/x.wav")
    assert len(out) == len(orig), "legacy must not chase the byte budget"


# --------------------------------------------------------------------------
# 2c.  Both write paths must know which cipher the image uses
# --------------------------------------------------------------------------

def test_both_encrypt_phases_stash_the_detected_scheme():
    """The ISO path stashed it and the Direct-SSD path did not, so every
    audio check silently reverted to the older cipher when writing straight
    to a card."""
    import inspect
    src = inspect.getsource(P)
    for fn in ("_phase_encrypt_standalone", "_phase_encrypt_ssd"):
        body = src.split("def %s" % fn, 1)[1].split("\n    def ", 1)[0]
        assert "_detect_write_scheme(" in body, fn
        assert "self._write_scheme = scheme" in body, (
            "%s detects the scheme but never stashes it" % fn)


# --------------------------------------------------------------------------
# 2c-bis.  ...and the sample it detects from has to actually be readable
#
# PAD-28.  The ISO Encrypt phase dumped its sample with `debugfs dump` into
# `tempfile.gettempdir()` — the HOST's temp dir — while debugfs itself was
# running inside Docker/WSL.  The dump landed somewhere the host has no file,
# every read raised FileNotFoundError, and _detect_write_scheme just ran out
# of entries and returned the older cipher.  On a Sonic image (scheme 3) that
# encrypted two replacement clips with the scheme-2 routine and forged the
# CRCs that routine expects, so the size check, both CRC forges, the post-
# write spot-check and the ISO build all passed — and the machine played a
# black screen.  It also spent 16m25s doing it, one failed debugfs call per
# fl.dat entry, all 16,232 of them.
# --------------------------------------------------------------------------

def _fl_entry(path=SONIC_PATH, filler=216):
    from pinball_decryptor.plugins.jjp.filelist import FileEntry
    return FileEntry(path=path, filler_size=filler,
                     crc_encrypted=0, crc_decrypted=0)


def test_the_scheme_is_read_off_the_image():
    enc = _encrypt_v3(_png(), SONIC_PATH, "Sonic", lead=216, trail=96)
    scheme = P._detect_write_scheme([_fl_entry()], lambda e: enc, "Sonic")
    assert scheme == v3.SCHEME_V3


def test_an_unreadable_image_stops_the_build_instead_of_guessing():
    """The heart of it: no sample must never mean "assume the old cipher".

    Guessing wrong is undetectable from inside the app — the write forges the
    checksums of whichever routine it used, so everything downstream agrees
    with it — and only the machine ever finds out.
    """
    def unreadable(entry):
        raise FileNotFoundError(entry.path)

    with pytest.raises(P.PipelineError) as excinfo:
        P._detect_write_scheme([_fl_entry() for _ in range(200)],
                               unreadable, "Sonic")
    msg = str(excinfo.value)
    assert "cannot be confirmed" in msg
    assert "black" in msg                 # says what it would have looked like
    assert "FileNotFoundError" in msg or SONIC_PATH in msg   # the real cause


def test_detection_gives_up_long_before_it_walks_the_whole_file_list():
    """16,232 failed debugfs round-trips is 16 minutes of silence."""
    tried = []

    def unreadable(entry):
        tried.append(entry.path)
        raise FileNotFoundError(entry.path)

    with pytest.raises(P.PipelineError):
        P._detect_write_scheme([_fl_entry() for _ in range(16232)],
                               unreadable, "Sonic")
    assert len(tried) <= P._SCHEME_SAMPLE_ATTEMPTS


def test_a_few_stale_file_list_entries_do_not_stop_the_build():
    """A sidecar from another release names files this image doesn't carry.
    Those are misses, not a broken reader — keep going."""
    enc = _encrypt_v3(_png(), SONIC_PATH, "Sonic", lead=216, trail=96)
    reads = []

    def flaky(entry):
        reads.append(entry.path)
        if len(reads) <= 4:
            raise FileNotFoundError(entry.path)
        return enc

    assert P._detect_write_scheme([_fl_entry() for _ in range(9)],
                                  flaky, "Sonic") == v3.SCHEME_V3


def test_a_pre_sonic_image_still_reads_as_the_legacy_scheme():
    """The fix must not push older titles down the scheme-3 path."""
    from pinball_decryptor.plugins.jjp.crypto import encrypt_file
    path = "/jjpe/gen1/Wonka/edata/graphics/UI/panel.png"
    content = _png()
    enc = encrypt_file(content, 216, path, 0, 0)
    scheme = P._detect_write_scheme([_fl_entry(path)], lambda e: enc, "Wonka")
    assert scheme == v3.SCHEME_LEGACY


# --------------------------------------------------------------------------
# 2c-ter.  debugfs dump writes on debugfs's side of the fence
# --------------------------------------------------------------------------

def test_dump_is_read_back_from_the_host_in_native_mode(tmp_path):
    """Native debugfs runs on the host, so the dump is a host file — going
    through the executor to read it would look in WSL/Docker for a path that
    only exists here."""
    image = FakeImage({})
    pipe = _mod_pipe(tmp_path, image)

    def fake_run(command, writable=False, timeout=120):
        # what real debugfs does: write the asset at the dump target
        dest = command.rsplit('" "', 1)[1].rstrip('"')
        with open(dest, "wb") as fh:
            fh.write(b"asset-bytes")
        return ""

    pipe._debugfs_run = fake_run
    pipe.executor = None          # must not be touched in native mode
    assert pipe._debugfs_dump_file("/jjpe/x.webm") == b"asset-bytes"
    assert not os.path.exists(os.path.join(str(tmp_path), "dumped_file")), \
        "the dump file must be cleaned up"


def test_dump_is_read_back_through_the_executor_in_container_mode(tmp_path):
    """Docker/WSL: debugfs wrote inside the container, so the read-back is
    base64 over the executor — the path is meaningless on the host."""
    import base64 as _b64

    class _Exec:
        def __init__(self):
            self.commands = []

        def run(self, command, timeout=None):
            self.commands.append(command)
            if command.startswith("base64 "):
                return _b64.b64encode(b"asset-bytes").decode() + "\n"
            return ""

    pipe = _mod_pipe(tmp_path, FakeImage({}))
    pipe._native_debugfs_path = None
    pipe._debugfs_tmp = "/var/tmp/jjp_debugfs_dead1234"
    pipe._debugfs_run = lambda *a, **k: ""
    pipe.executor = _Exec()

    assert pipe._debugfs_dump_file("/jjpe/x.webm") == b"asset-bytes"
    assert any(c.startswith("base64 '/var/tmp/jjp_debugfs_dead1234/")
               for c in pipe.executor.commands), pipe.executor.commands


def test_no_encrypt_phase_dumps_into_the_hosts_temp_dir():
    """The exact shape of the bug: a debugfs dump target built from
    tempfile.gettempdir(), which is the host's and not debugfs's."""
    import inspect
    src = inspect.getsource(P)
    for fn in ("_phase_encrypt_standalone", "_phase_encrypt_ssd"):
        body = src.split("def %s" % fn, 1)[1].split("\n    def ", 1)[0]
        assert "gettempdir" not in body, (
            "%s builds a debugfs path from the host's temp dir" % fn)


# --------------------------------------------------------------------------
# 2d.  A replacement whose header lies must be refused, not written
# --------------------------------------------------------------------------

def test_a_wav_claiming_more_audio_than_it_holds_is_refused():
    """The hand-padded file: trimmed to hit the pinned byte count, with the
    data chunk still claiming its old length.  Length checks and the forged
    CRC both pass, so the game was the first thing to notice."""
    good = _logic_wav(2000)
    assert P._validate_replacement(good, "/x/a.wav") is None
    lying = bytearray(good)
    d_start, d_len = P.StandaloneModPipeline._wav_data_chunk(good)
    struct.pack_into("<I", lying, d_start - 4, d_len + 5000)
    why = P._validate_replacement(bytes(lying), "/x/a.wav")
    assert why and "claims" in why


def test_a_wav_with_a_lying_riff_header_is_refused():
    good = _logic_wav(2000)
    lying = bytearray(good)
    struct.pack_into("<I", lying, 4, len(good) * 2)
    why = P._validate_replacement(bytes(lying), "/x/a.wav")
    assert why and "RIFF" in why


def test_harmless_trailing_slop_is_not_refused():
    """Plenty of real files carry junk after the declared end; refusing
    those would break working mods."""
    assert P._validate_replacement(_logic_wav(500) + b"\x00" * 32,
                                   "/x/a.wav") is None


def test_truncated_png_and_jpeg_are_refused():
    png = _png()
    assert P._validate_replacement(png, "/x/a.png") is None
    assert P._validate_replacement(png[:len(png) // 2], "/x/a.png")
    jpg = b"\xff\xd8" + b"\x00" * 200 + b"\xff\xd9"
    assert P._validate_replacement(jpg, "/x/a.jpg") is None
    assert P._validate_replacement(jpg[:-2], "/x/a.jpg")


def test_unknown_types_are_left_alone():
    assert P._validate_replacement(b"anything at all", "/x/a.bin") is None


# --------------------------------------------------------------------------
# 2d-bis.  Refusing a clip that misses the pinned size has to read as an
#          answer, not as an internal error
# --------------------------------------------------------------------------

SONIC_WEBM = "/jjpe/gen1/Sonic/edata/graphics/Attract Mode/Game_Logo_Sonic.webm"


def _pinned_slot(path, orig_len=4000, lead=216, trail=96):
    """(entry, read_original) for a scheme-3 slot holding *orig_len* bytes."""
    orig = bytes(bytearray((0x77 for _ in range(orig_len))))
    enc = _encrypt_v3(orig, path, "Sonic", lead=lead, trail=trail)
    return _fl_entry(path, filler=lead), (lambda entry: enc)


def test_a_video_that_misses_the_pinned_size_says_what_to_do():
    """"1020664 vs 2117960" on its own reads as a bug in the app.  The size
    pin is real and refusing is correct — the alternative is the black screen
    the whole check exists to stop — so the message has to carry that."""
    entry, read_original = _pinned_slot(SONIC_WEBM)
    with pytest.raises(v3.SizeMismatch) as excinfo:
        P._encrypt_one(v3.SCHEME_V3, entry, b"a much shorter clip",
                       "Sonic", read_original)
    msg = str(excinfo.value)
    assert "4096" in msg, "the byte target the clip has to hit"
    assert "exact byte count" in msg
    assert "left on the card untouched" in msg


def test_a_non_video_still_gets_the_plain_size_message():
    """The clip-specific wording must not leak onto every other asset."""
    entry, read_original = _pinned_slot(
        "/jjpe/gen1/Sonic/edata/audio/music/theme.ogg")
    with pytest.raises(v3.SizeMismatch) as excinfo:
        P._encrypt_one(v3.SCHEME_V3, entry, b"short", "Sonic", read_original)
    assert "exact byte count" not in str(excinfo.value)


def test_a_video_that_does_hit_the_pinned_size_is_written():
    """The refusal is about the size, not about being a video."""
    entry, read_original = _pinned_slot(SONIC_WEBM, orig_len=4000)
    fitted = bytes(bytearray((0x22 for _ in range(4096))))   # content + trail
    out, note = P._encrypt_one(v3.SCHEME_V3, entry, fitted, "Sonic",
                               read_original)
    assert len(out) == len(read_original(entry))
    assert "scheme 3" in note


# --------------------------------------------------------------------------
# 2e.  PNG replacements get fitted to the pinned slot size
# --------------------------------------------------------------------------

def test_png_is_padded_to_the_slot_size_without_changing_pixels():
    from PIL import Image
    import io as _io
    png = _png()
    target = len(png) + 500
    out = P.fit_png_to_size(png, target)
    assert out is not None and len(out) == target
    before = Image.open(_io.BytesIO(png)).convert("RGBA").tobytes()
    after = Image.open(_io.BytesIO(out)).convert("RGBA").tobytes()
    assert before == after, "padding must not touch a single pixel"


def test_png_metadata_is_dropped_to_make_room():
    png = _png()
    bulky = (png[:-12]
             + struct.pack(">I", 400) + b"tEXt" + b"c\x00" + b"x" * 398
             + struct.pack(">I", zlib.crc32(b"tEXtc\x00" + b"x" * 398)
                           & 0xFFFFFFFF)
             + png[-12:])
    # target smaller than the bulky file but reachable once the text goes
    out = P.fit_png_to_size(bulky, len(png) + 20)
    assert out is not None and len(out) == len(png) + 20


def test_png_fit_gives_up_rather_than_guessing():
    png = _png()
    assert P.fit_png_to_size(png, len(png) - 100) is None   # cannot shrink
    assert P.fit_png_to_size(png, len(png) + 5) is None     # no legal chunk
    assert P.fit_png_to_size(b"not a png", 100) is None
    assert P.fit_png_to_size(png, len(png)) == png          # already exact


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


def test_cancelled_fsck_is_reported_as_cancelled():
    """Exit 32 is 'the user stopped it', not 'the filesystem is broken'."""
    pipe = _convert_pipe(32, "/var/tmp/jjp_raw.img: cancelled!")

    with pytest.raises(P.PipelineError) as exc:
        pipe._phase_convert_standalone()
    assert "cancelled" in str(exc.value).lower()
    assert "could not repair" not in str(exc.value)


# --------------------------------------------------------------------------
# 4.  Restoring permissions must not cost a round-trip it does not need
# --------------------------------------------------------------------------

def test_metadata_restore_skips_fields_that_already_match(tmp_path):
    image = FakeImage({"/etc/x": (b"x", 0o644, 0, 0)})
    pipe = _mod_pipe(tmp_path, image)
    pipe._debugfs_restore_inode_meta("/etc/x", (0o644, 0, 0), (0o644, 0, 0))
    assert image.commands == [], "nothing differed, so nothing to write"


def test_metadata_restore_writes_only_the_field_that_differs(tmp_path):
    image = FakeImage({"/etc/x": (b"x", 0o644, 0, 0)})
    pipe = _mod_pipe(tmp_path, image)
    pipe._debugfs_restore_inode_meta("/etc/x", (0o755, 0, 0), (0o644, 0, 0))
    assert [c.split()[0] for c in image.commands] == ["sif"]
    assert "mode" in image.commands[0]
    assert image.files["/etc/x"][1] == 0o755


def test_metadata_restore_still_works_without_a_current_reading(tmp_path):
    image = FakeImage({"/etc/x": (b"x", 0o600, 0, 0)})
    pipe = _mod_pipe(tmp_path, image)
    pipe._debugfs_restore_inode_meta("/etc/x", (0o755, 1000, 44))
    assert image.files["/etc/x"] == (b"x", 0o755, 1000, 44)
