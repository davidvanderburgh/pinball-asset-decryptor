"""Stern **Spike 3**: the games volume as one plaintext partition, read AND
written (PAD-1186).

A Spike 3 card keeps its game on p6, a LUKS2 ``aes-xts-plain64`` volume over
ext4 that carries Spike 2's own asset tree (``assets/lcd/auto_loaded/<sha>/
scene.radium`` + ``scene.assets/*.asset`` clips, PNGs, ``image.bin``,
``spk/index/*.sidx``).  :class:`GamesVolume` presents that volume's plaintext
as a seekable byte stream: offset 0 is the filesystem's first byte, reads
decrypt the covering XTS sectors, writes read-modify-write them and encrypt
them back under the volume's own master key.  XTS works sector by sector with
the sector number as its tweak, so a write changes the ciphertext of exactly
the sectors it touches and nothing else on the card.

Handed to the Spike 2 engine as a one-partition disk (``[(0, size)]``) it
runs the Spike 2 extractors and the shared write core unchanged; the engine
knows it is a Spike 3 volume from :attr:`GamesVolume.pad_spike3` (no Spike 2
game program beside ``image.bin``: the game is an aarch64 Godot program, and
its sounds are plain PCM that :mod:`.spike3_sound` reads and writes itself).

The key comes from :class:`.spike3_keys.Spike3KeySource`, as for Extract; no
key is ever in the repo.
"""

from __future__ import annotations

import os

from . import spike3 as _s3
from .spike3_keys import Spike3KeySource, Spike3KeyError

_SS = 512


class GamesVolume(_s3.DecryptingSegmentReader):
    """Read/write plaintext view of a Spike 3 LUKS2 data segment.

    ``writable`` needs *fileobj* opened ``r+b``.  Written sectors stay in the
    cache (already re-encrypted on the file), so a read after a write sees
    the new bytes."""

    #: the engine's marker: a Spike 3 games volume (engine._SPIKE3_CARD)
    pad_spike3 = True

    def __init__(self, fileobj, part, header, master_key, writable=False):
        super().__init__(fileobj, part["start_lba"], header, master_key)
        self.part = part
        self.header = header
        self.master_key = master_key
        self.writable = writable
        self._enc = _s3._luks_otp().aes_xts_encrypt
        self.sectors_written = 0
        #: the partition's byte offset on the card and the segment's offset
        #: inside it (the grow step opens the same volume through dm-crypt)
        self.part_offset = part["start_lba"] * _SS
        self.segment_offset = self._seg_off

    def write(self, data):
        if not self.writable:
            raise OSError("this Spike 3 volume is open read-only")
        data = bytes(data)
        n = len(data)
        if n == 0:
            return 0
        start = self._pos
        end = start + n
        if end > self.size:
            raise OSError("write past the end of the games volume "
                          "(0x%x > 0x%x)" % (end, self.size))
        sec = self._sector
        first, last = start // sec, (end - 1) // sec
        # whole run of sectors at once: one read of the edges, one write
        buf = bytearray()
        lo_pad = start - first * sec
        hi_pad = (last + 1) * sec - end
        if lo_pad or hi_pad:
            head = self._sector_plain(first) if lo_pad else b""
            tail = self._sector_plain(last) if hi_pad else b""
            buf += head[:lo_pad]
            buf += data
            if hi_pad:
                buf += tail[sec - hi_pad:]
        else:
            buf += data
        plain = bytes(buf)
        ct = self._enc(self.master_key, plain, first * self._iv_step, sec, self._iv_step)
        self._f.seek(self._phys_base + first * sec)
        self._f.write(ct)
        for i in range(last - first + 1):
            s = first + i
            if s in self._cache:
                self._cache[s] = plain[i * sec:(i + 1) * sec]
        self.sectors_written += last - first + 1
        self._pos = end
        return n

    def flush(self):
        try:
            self._f.flush()
        except (AttributeError, OSError):
            pass

    def close(self):
        super().close()
        try:
            self._f.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def image_id(path):
    """``pokemon_le-0_82_0`` for ``pokemon_le-0_82_0.Release.64G.sdcard-secure.raw``
    (the stem the keyfile's per-card keys are named by)."""
    return os.path.basename(path).split(".", 1)[0]


def open_games(path, writable=False, key_source=None):
    """Unlock the games volume of the Spike 3 card at *path* and return a
    :class:`GamesVolume` over it.  Raises :class:`Spike3KeyError` when no key
    the user gave opens it, ``ValueError`` when *path* is not a Spike 3 card."""
    f = open(path, "r+b" if writable else "rb")
    try:
        parts = _s3.parse_partitions(f)
        if not _s3.is_spike3_card_parts(parts):
            raise ValueError("%s is not a Stern Spike 3 secure SD-card image"
                             % path)
        games = _s3.partition_for_role(parts, "games")
        if games is None:
            raise ValueError("no encrypted games partition on %s" % path)
        ks = key_source or Spike3KeySource.discover(image_path=path,
                                                    image_id=image_id(path))
        if ks is None or not ks.has_any():
            raise Spike3KeyError(
                "No Spike 3 key for this card: unlock it in the Extract tab "
                "first (your own board's key).")
        ks._image_id = getattr(ks, "_image_id", None) or image_id(path)
        otp = _s3._luks_otp()
        header = _s3.read_luks_header(f, games["start_lba"])
        header._pad_part_sectors = games["sectors"]
        mk = ks.master_key(header, role="games", part=games)
        if not otp.verify_master_key(header, mk):
            raise Spike3KeyError("the key did not unlock this card's games "
                                 "partition")
        return GamesVolume(f, games, header, mk, writable=writable)
    except BaseException:
        f.close()
        raise


def volume_parts(vol):
    """The one-partition disk the engine is handed for *vol*."""
    return [(0, vol.size)]
