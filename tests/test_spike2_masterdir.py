"""Spike 2 master-directory reader/writer (``spike2.masterdir``).

The directory is the encrypted record array in the tail of ``image.bin``: one
24-byte record per sound saying where its body is and how long it is.  Growing
a replacement past its stock slot means appending a record, so this module has
to rebuild the tail byte for byte -- a card whose directory does not decode is
a card that does not boot.

Fast tests below need no card and no firmware: the cipher layer takes the key
as an argument, and the transform, the geometry and the grow planner are all
pure.  The card-gated tests at the bottom check the halves that only the
firmware can answer -- that what we read is what the machine itself decodes,
that what we write is byte-identical to the card, and that a directory with an
appended record passes the firmware's own checksum gate.
"""
import os
import struct
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.environ.get("PAD_SPIKE2_IMG_DIR",
                         os.path.join(REPO, "images", "Stern", "spike2"))
CARDS = {
    # The validated build, and a generic/located one whose count is ODD.
    "turtles": "turtles_pro-1_58_0.Release.8G.sdcard.raw",
    "led_zeppelin_122": "led_zeppelin_le-1_22_0.Release.8G.sdcard.raw",
    # Godzilla Pro 1.15's record count is EVEN, so its file ends 24n+8 past the
    # directory offset where an odd card ends 24n+16, and appending a record
    # flips it the other way.  Both parities ship; both must round-trip.
    "godzilla_115": "godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw",
}


# --------------------------------------------------------------------------
# fast: geometry
# --------------------------------------------------------------------------
def test_tail_length_follows_the_aligned_size_not_the_record_bytes():
    """An odd count pads to 24n+8 and ends 24n+16 past the directory offset;
    an even one needs no pad and ends at 24n+8.

    Sizing the trailer from the record bytes instead produces a byte-identical
    ciphertext and a file 8 bytes too long on every even-count card, which is
    the one way to get this wrong and still see the content compare clean."""
    from pinball_decryptor.plugins.stern.spike2.masterdir import (
        align16, tail_len)
    assert tail_len(2053) == 24 * 2053 + 16          # odd: align16 adds 8
    assert tail_len(2534) == 24 * 2534 + 8           # even: nothing to add
    for n in (1, 2, 3, 100, 549, 2534, 5352, 10562):
        assert tail_len(n) == align16(24 * n) + 8
        assert align16(24 * n) % 16 == 0
        assert 0 <= align16(24 * n) - 24 * n <= 8


def test_header_geometry_reads_the_two_header_words():
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    hdr = bytearray(0x100)
    struct.pack_into("<I", hdr, MD.HDR_MD_OFF, 0x453c695b)
    struct.pack_into("<I", hdr, MD.HDR_COUNT, 2053)
    assert MD.header_geometry(bytes(hdr)) == (0x453c695b, 2053)


# --------------------------------------------------------------------------
# fast: the per-record post-transform
# --------------------------------------------------------------------------
# The first two records of TMNT Pro 1.58, captured either side of the
# firmware's own post-transform loop.  Record 0's length word passes through
# (the running XOR starts at zero) and record 1's is chained onto it, so this
# pins both the scatter and the chain.
_TMNT_PLAIN = bytes.fromhex(
    "4c1a8c1ef7ffffff62a42fc833019d2e15e5735549ed8882"
    "e48f8ce1e11a8caae56e0d940008b328cc950000d0e7bb2d")
_TMNT_RECORDS = bytes.fromhex(
    "a6b408000000000062a42fc833019d2e15e5735549ed8882"
    "c24b0b0000000000e56e0d940008b328d9707355d0e7bb2d")


def test_post_transform_matches_the_firmware_on_a_real_card():
    from pinball_decryptor.plugins.stern.spike2.masterdir import (
        post_forward, post_inverse)
    assert post_forward(_TMNT_PLAIN, 2) == _TMNT_RECORDS
    assert post_inverse(_TMNT_RECORDS, 2) == _TMNT_PLAIN


def test_post_transform_leaves_the_identity_bytes_alone():
    """Bytes 8..15 and 20..23 carry the sound's identity and must survive the
    transform untouched -- an appended record keeps them so the game's
    play-time lookup still finds the sound."""
    from pinball_decryptor.plugins.stern.spike2.masterdir import post_forward
    md = post_forward(_TMNT_PLAIN, 2)
    for k in range(2):
        o = k * 24
        assert md[o + 8:o + 16] == _TMNT_PLAIN[o + 8:o + 16]
        assert md[o + 20:o + 24] == _TMNT_PLAIN[o + 20:o + 24]


def test_post_transform_round_trips_over_random_records():
    import random
    from pinball_decryptor.plugins.stern.spike2.masterdir import (
        post_forward, post_inverse)
    rnd = random.Random(20260909)
    for n in (1, 2, 7, 64):
        pt = bytes(rnd.getrandbits(8) for _ in range(24 * n))
        assert post_inverse(post_forward(pt, n), n) == pt


def test_post_transform_ignores_bytes_past_the_last_record():
    """The alignment pad rides through the cipher but the firmware's loop stops
    at the record count, so the pad must come back untouched."""
    from pinball_decryptor.plugins.stern.spike2.masterdir import post_forward
    pad = b"\xa5" * 8
    md = post_forward(_TMNT_PLAIN + pad, 2)
    assert md[48:] == pad


# --------------------------------------------------------------------------
# fast: the checksum
# --------------------------------------------------------------------------
def test_crc_is_a_running_crc32_with_no_final_inversion():
    """The build constant is the CRC's STARTING value, not a value XORed into
    the result -- a refactor to the inverted form still 'looks like a CRC' and
    fails only on the machine."""
    from pinball_decryptor.plugins.stern.spike2.masterdir import crc
    assert crc(0x11a58ff1, b"spike2") == 0x9d7ea1a6
    assert crc(0, b"") == 0
    assert crc(0x11a58ff1, b"") == 0x11a58ff1
    assert crc(crc(0x11a58ff1, b"spi"), b"ke2") == crc(0x11a58ff1, b"spike2")


# --------------------------------------------------------------------------
# fast: the seed permutation
# --------------------------------------------------------------------------
def _permutation_map(order):
    """A BitMap for the bit permutation ``order`` (bit i -> bit order[i])."""
    from pinball_decryptor.plugins.stern.spike2.masterdir import BitMap
    return BitMap(0, [1 << order[i] for i in range(32)])


def test_seed_map_inverts_a_bit_permutation():
    import random
    rnd = random.Random(7)
    order = list(range(32))
    rnd.shuffle(order)
    bm = _permutation_map(order)
    for _ in range(50):
        x = rnd.getrandbits(32)
        assert bm.invert(bm.apply(x)) == x
    assert bm.apply(0) == 0


def test_seed_map_is_linear_over_the_basis():
    import random
    rnd = random.Random(11)
    order = list(range(32))
    rnd.shuffle(order)
    bm = _permutation_map(order)
    for _ in range(20):
        a, b = rnd.getrandbits(32), rnd.getrandbits(32)
        assert bm.apply(a ^ b) == bm.apply(a) ^ bm.apply(b) ^ bm.apply(0)


def test_seed_map_refuses_a_singular_map():
    """A build whose seed word does not determine the checksum reversibly must
    be refused, not silently written with a wrong seed."""
    from pinball_decryptor.plugins.stern.spike2.masterdir import (
        BitMap, MasterDirError)
    bm = BitMap(0, [1] * 32)                 # rank 1
    with pytest.raises(MasterDirError):
        bm.invert(1)


# --------------------------------------------------------------------------
# fast: the cipher layer, with the key supplied
# --------------------------------------------------------------------------
# A card relates a record's raw length word to the decoded sample count by one
# XOR constant per build (TMNT 1.58's is used here); the fake directory obeys
# that so a grow plan built from it is the shape a real one has.
_FAKE_LENGTH_XOR = 0x5572ae9b


def _fake_length(i):
    return 20000 + i * 1000


def _fake_directory(count, md_off=0x1000, seed=0x12345678):
    import random
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    rnd = random.Random(1234 + count)
    recs = bytearray(rnd.getrandbits(8) for _ in range(24 * count))
    for i in range(count):                    # plausible ascending body offsets
        struct.pack_into("<I", recs, i * 24, 0x2000 + i * 0x800)
        struct.pack_into("<I", recs, i * 24 + 16,
                         _FAKE_LENGTH_XOR ^ _fake_length(i))
    pad = MD.align16(24 * count) - 24 * count
    return MD.Directory(bytes(recs), count, md_off, seed,
                        pad_plain=b"\x5a" * pad, trailer=b"\xde\xad\xbe\xef")


@pytest.mark.parametrize("count", [4, 5])       # even and odd
def test_pack_tail_and_unpack_tail_are_inverses(count):
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    key, iv = b"K" * 24, b"V" * 16
    d = _fake_directory(count)
    blob = MD.pack_tail(d, key, iv, 0xcafebabe)
    assert len(blob) == MD.tail_len(count)
    back = MD.unpack_tail(blob, count, key, iv, md_off=d.md_off)
    assert back.records == d.records
    assert back.count == d.count
    assert back.seed == 0xcafebabe
    assert back.pad_plain == d.pad_plain
    assert back.trailer == d.trailer


def test_packed_tail_puts_the_seed_where_the_firmware_reads_it():
    """The firmware reads the seed at ``directory offset + align16(24n)``, so
    an odd count buries the first 8 trailer bytes inside the ciphertext and an
    even one does not."""
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    key, iv = b"K" * 24, b"V" * 16
    for count in (4, 5):
        blob = MD.pack_tail(_fake_directory(count), key, iv, 0x11223344)
        at = MD.align16(24 * count)
        assert struct.unpack_from("<I", blob, at)[0] == 0x11223344


def test_unpack_tail_rejects_a_short_tail():
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    with pytest.raises(MD.MasterDirError):
        MD.unpack_tail(b"\x00" * 32, 5, b"K" * 24, b"V" * 16)


def _image_with_header(tmp_path, md_off, count, size):
    p = tmp_path / "image.bin"
    buf = bytearray(size)
    struct.pack_into("<I", buf, 0x40, md_off)
    struct.pack_into("<I", buf, 0x60, count)
    p.write_bytes(bytes(buf))
    return str(p)


def test_read_tail_bytes_checks_the_header_before_any_firmware_runs(tmp_path):
    """A bad header is a bad card, and saying so costs nothing -- booting an
    emulator to find out costs a minute."""
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    good = _image_with_header(tmp_path, 0x1000, 5, 0x1000 + MD.tail_len(5))
    md_off, count, blob = MD.read_tail_bytes(good)
    assert (md_off, count) == (0x1000, 5)
    assert len(blob) == MD.tail_len(5)

    with pytest.raises(MD.MasterDirError):        # file too short for the count
        MD.read_tail_bytes(_image_with_header(tmp_path, 0x1000, 5, 0x1080))
    with pytest.raises(MD.MasterDirError):        # count inside the header
        MD.read_tail_bytes(_image_with_header(tmp_path, 0x20, 5, 0x10000))
    with pytest.raises(MD.MasterDirError):        # no records at all
        MD.read_tail_bytes(_image_with_header(tmp_path, 0x1000, 0, 0x10000))


def test_read_tail_bytes_accepts_a_grown_image_whose_bodies_follow(tmp_path):
    """After a grow the directory is no longer the last thing in the file, so
    the geometry check has to allow bytes past it."""
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    path = _image_with_header(tmp_path, 0x1000, 5,
                              0x1000 + MD.tail_len(5) + 0x8000)
    md_off, count, blob = MD.read_tail_bytes(path)
    assert (md_off, count, len(blob)) == (0x1000, 5, MD.tail_len(5))


# --------------------------------------------------------------------------
# fast: Directory
# --------------------------------------------------------------------------
def test_directory_reports_its_own_geometry():
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    d = _fake_directory(5, md_off=0x4000)
    assert d.size_aligned == MD.align16(24 * 5)
    assert d.tail_len == MD.tail_len(5)
    assert d.file_size() == 0x4000 + MD.tail_len(5)
    assert d.body_off(2) == 0x2000 + 2 * 0x800
    assert d.record(0) == d.records[:24]
    with pytest.raises(IndexError):
        d.record(5)


def test_directory_rejects_a_record_array_of_the_wrong_size():
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    with pytest.raises(MD.MasterDirError):
        MD.Directory(b"\x00" * 23, 1, 0, 0)


def test_directory_identity_excludes_the_geometry():
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    d = _fake_directory(3)
    moved = MD.set_geometry(d.record(1), body_off=0x99999, length_word=0x1234)
    other = MD.Directory(d.records[:24] + moved + d.records[48:], 3,
                         d.md_off, d.seed)
    assert other.identity(1) == d.identity(1)
    assert other.body_off(1) == 0x99999
    assert other.length_word(1) == 0x1234


def test_padding_follows_the_count_parity_not_the_source_directory():
    """Appending a record flips the parity, so the plaintext pad appears or
    disappears; carrying the source's pad over blindly would write 8 bytes too
    many (or too few) into the checksummed buffer."""
    odd = _fake_directory(5)
    assert len(odd.padded_plain) == 8
    even = odd.with_records(odd.records + b"\x00" * 24, 6)
    assert even.padded_plain == b""
    back = even.with_records(even.records[:24 * 5], 5)
    assert len(back.padded_plain) == 8


# --------------------------------------------------------------------------
# fast: the grow planner
# --------------------------------------------------------------------------
def _edit(idx, old, new, body):
    from pinball_decryptor.plugins.stern.spike2.masterdir import GrowEdit
    return GrowEdit(idx, old, new, body)


def test_plan_grow_appends_records_and_leaves_the_stock_ones_alone():
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    d = _fake_directory(5)
    grown, places = MD.plan_grow_records(
        d, [_edit(1, _fake_length(1), _fake_length(1) + 44100, 10000),
            _edit(3, _fake_length(3), _fake_length(3) + 22050, 12000)])

    assert grown.count == 7
    assert grown.records[:24 * 5] == d.records      # nothing existing moves
    assert [p.idx for p in places] == [1, 3]
    assert [p.new_idx for p in places] == [5, 6]

    # each appended record is its source, with only the geometry replaced
    assert grown.identity(5) == d.identity(1)
    assert grown.identity(6) == d.identity(3)
    # and its length word decodes to the length that was asked for
    assert grown.length_word(5) ^ _FAKE_LENGTH_XOR == _fake_length(1) + 44100
    assert grown.length_word(6) ^ _FAKE_LENGTH_XOR == _fake_length(3) + 22050
    assert grown.body_off(5) == places[0].body_off
    assert grown.body_off(6) == places[1].body_off


def test_plan_grow_places_bodies_past_the_new_tail_and_apart():
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    d = _fake_directory(5, md_off=0x40000)
    grown, places = MD.plan_grow_records(
        d, [_edit(0, _fake_length(0), _fake_length(0) + 4410, 4096),
            _edit(2, _fake_length(2), _fake_length(2) + 8820, 8192)])
    end_of_tail = d.md_off + MD.tail_len(grown.count)
    assert places[0].body_off >= end_of_tail + MD.BODY_PAD
    assert places[1].body_off >= places[0].body_off + 4096 + MD.BODY_PAD
    # every body starts far enough in that a delta<0 codec reads defined bytes
    for p in places:
        assert p.body_off - MD.BODY_PAD >= end_of_tail
        # and past where the file ended before the grow, so no stock body,
        # record or offset has to move
        assert p.body_off > d.file_size()


def test_plan_grow_refuses_edits_it_cannot_honour():
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    d = _fake_directory(5)
    with pytest.raises(MD.MasterDirError):
        MD.plan_grow_records(d, [])
    long1 = _fake_length(1) + 100
    with pytest.raises(MD.MasterDirError):
        MD.plan_grow_records(d, [_edit(9, 100, 200, 16)])       # out of range
    with pytest.raises(MD.MasterDirError):
        MD.plan_grow_records(d, [_edit(1, _fake_length(1), long1, 16),
                                 _edit(1, _fake_length(1), long1, 16)])  # twice
    with pytest.raises(MD.MasterDirError):
        MD.plan_grow_records(d, [_edit(1, _fake_length(1),
                                       _fake_length(1), 16)])   # not longer
    with pytest.raises(MD.MasterDirError):
        MD.plan_grow_records(d, [_edit(1, _fake_length(1), long1, 0)])


def test_plan_grow_catches_a_length_the_record_does_not_decode_to():
    """Two edits imply this build's length constant twice; if they disagree the
    caller passed a wrong 'current length', which would otherwise write a
    record whose sound plays for the wrong duration."""
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    d = _fake_directory(5)
    MD.plan_grow_records(d, [_edit(1, _fake_length(1), _fake_length(1) + 10, 64),
                             _edit(2, _fake_length(2), _fake_length(2) + 10, 64)])
    with pytest.raises(MD.MasterDirError):
        MD.plan_grow_records(
            d, [_edit(1, _fake_length(1), _fake_length(1) + 10, 64),
                _edit(2, _fake_length(2) ^ 1, _fake_length(2) + 10, 64)])


def test_grown_directory_still_packs_to_the_expected_size():
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    key, iv = b"K" * 24, b"V" * 16
    for count in (4, 5):                      # both parities, both directions
        d = _fake_directory(count)
        grown, _ = MD.plan_grow_records(
            d, [_edit(0, _fake_length(0), _fake_length(0) + 200, 64)])
        blob = MD.pack_tail(grown, key, iv, 1)
        assert len(blob) == MD.tail_len(count + 1)
        back = MD.unpack_tail(blob, count + 1, key, iv)
        assert back.records == grown.records


# --------------------------------------------------------------------------
# card-gated: the halves only the firmware can answer
# --------------------------------------------------------------------------
def _card_path(title):
    return os.path.join(IMG_DIR, CARDS[title])


def _extract_inputs_cached(title):
    """Extract (and cache in the temp dir) the card's game_real + image.bin.

    Shares the cache directory with tests/test_stern_audio_tail.py, so a run of
    either populates the other."""
    from pinball_decryptor.plugins.stern import engine as E
    work = os.path.join(tempfile.gettempdir(), "pad_stern_tail_" + title)
    gr = os.path.join(work, "game_real")
    img = os.path.join(work, "image.bin")
    if os.path.exists(gr) and os.path.exists(img) and os.path.getsize(img) > 0:
        return gr, img
    os.makedirs(work, exist_ok=True)
    parts = E._linux_partitions(_card_path(title))
    with open(_card_path(title), "rb") as disk_f:
        E._extract_inputs(disk_f, parts, work, lambda *a, **k: None)
    return gr, img


@pytest.fixture(autouse=True)
def _no_faulthandler():
    """Disable pytest's faulthandler around the emulator tests.

    unicorn services guest memory through the host's fault machinery, and on
    Windows pytest's faulthandler plugin traps that first: it prints a
    "Windows fatal exception: access violation" and kills the process inside
    ``Spike2Emu.__init__``.  Same reasoning as test_stern_audio_tail.py."""
    import faulthandler
    was = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        yield
    finally:
        if was:
            faulthandler.enable()


def _booted(gr, img):
    from pinball_decryptor.plugins.stern.spike2.emulator import Spike2Emu
    emu = Spike2Emu(gr, img)
    if not emu.audio_supported:
        emu.close()
        pytest.skip("audio decode is not supported for this build")
    emu.boot()
    return emu


def _decode_in_guest(emu, count_hint=None):
    """Run the firmware's own directory decode and return
    ``(records, passed_checksum)`` as the machine itself sees them.

    Stops at the first band build, so this costs one decode (seconds) rather
    than the whole per-record chain (minutes)."""
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    from unicorn.arm_const import UC_ARM_REG_R0
    sites = MD._crypto_sites(emu)
    cap = {}

    def at_md(e):
        if "dst" not in cap:
            cap["dst"] = e.mu.reg_read(UC_ARM_REG_R0)
            cap["n"] = EM._md_record_count(e, cap["dst"])

    def at_gate(e):
        cap["got"] = e.mu.reg_read(UC_ARM_REG_R0)
        cap["want"] = e.mu.reg_read(EM._R[sites["CRC_EXPECT_REG"]])

    def at_band(e):
        cap["band"] = True
        e.mu.emu_stop()

    emu.add_hook(emu.MASTERDIR_MALLOC, at_md)
    emu.add_hook(sites["CRC_GATE"], at_gate)
    emu.add_hook(emu.BANDLOOP, at_band)
    try:
        emu.call(emu.MASTERDIR_DECODE, (0,), limit=600_000_000)
    finally:
        for a in (emu.MASTERDIR_MALLOC, sites["CRC_GATE"], emu.BANDLOOP):
            emu.del_hook(a)
    n = count_hint or cap.get("n")
    if not cap.get("band") or not n:
        return None, False
    emu._ensure_range(cap["dst"], n * 24)
    return (bytes(emu.mu.mem_read(cap["dst"], n * 24)),
            cap.get("got") is not None and cap["got"] == cap.get("want"))


@pytest.mark.slow
@pytest.mark.parametrize("title", sorted(CARDS))
def test_directory_read_and_write_round_trip_on_a_card(title):
    """What we read is what the machine decodes, and what we write is the card."""
    if not os.path.exists(_card_path(title)):
        pytest.skip("card image %s not present" % CARDS[title])
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD

    gr, img = _extract_inputs_cached(title)
    emu = _booted(gr, img)
    try:
        d = MD.read_directory(img, emu)
        assert d.md_off + d.tail_len == os.path.getsize(img)

        guest, gate_ok = _decode_in_guest(emu, d.count)
        assert gate_ok, "the firmware's own checksum gate rejected its own card"
        assert guest is not None
        assert d.records == guest[:24 * d.count], (
            "%s: the directory we decode is not the array the firmware built"
            % title)

        with open(img, "rb") as f:
            f.seek(d.md_off)
            on_card = f.read()
        writes = MD.write_directory(d, emu)
        assert writes[d.md_off] == on_card, (
            "%s: rebuilt tail differs from the card (%d vs %d bytes)"
            % (title, len(writes[d.md_off]), len(on_card)))
        assert writes[MD.HDR_COUNT] == struct.pack("<I", d.count)
    finally:
        emu.close()


@pytest.mark.slow
@pytest.mark.parametrize("title", sorted(CARDS))
def test_appended_record_passes_the_firmwares_own_checksum(title):
    """Append a record, flipping the count's parity, and let the machine judge.

    The staged directory goes into the emulator's copy-on-write view of the
    card, so the file is never touched; reaching the band build means the
    firmware decrypted it, post-transformed it and accepted its checksum."""
    if not os.path.exists(_card_path(title)):
        pytest.skip("card image %s not present" % CARDS[title])
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    from pinball_decryptor.plugins.stern.spike2.emulator import (
        DESC_BASE, Spike2Emu)

    gr, img = _extract_inputs_cached(title)
    emu = _booted(gr, img)
    try:
        d = MD.read_directory(img, emu)
        j = d.count // 2
        old_len = 40000                 # only has to be self-consistent here
        grown, places = MD.plan_grow_records(
            d, [MD.GrowEdit(j, old_len, old_len + 44100, 2 * 44100)])
        writes = MD.write_directory(grown, emu)
    finally:
        emu.close()

    assert grown.count == d.count + 1
    assert len(writes[grown.md_off]) == MD.tail_len(grown.count)
    assert places[0].body_off > os.path.getsize(img), (
        "the appended body must start past the old end of the file")

    staged = Spike2Emu(gr, img)
    try:
        for off, data in writes.items():
            staged._ensure_range(DESC_BASE + off, len(data))
            staged.mu.mem_write(DESC_BASE + off, data)
        staged.boot()
        guest, gate_ok = _decode_in_guest(staged, grown.count)
        assert gate_ok, (
            "%s: the firmware rejected the checksum of the rebuilt directory"
            % title)
        assert guest[:24 * d.count] == d.records, "a stock record moved"
        assert guest[24 * d.count:24 * grown.count] == grown.records[24 * d.count:]
    finally:
        staged.close()
