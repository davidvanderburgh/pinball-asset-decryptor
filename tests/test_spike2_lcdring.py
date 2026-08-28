"""lcdring.py: the VILLAIN VISION command ring reads back what the shim rang.

Queue item 83. The shim (hwshim.c, lcd_publish) writes a 4096-byte page whose
offsets are hard-coded in C, in padlcd.h's comment, in playfield.py and now in
lcdring.py. Four copies of one layout is exactly the arrangement that drifts,
and a drift here is silent: the reader prints plausible numbers off the wrong
bytes.

So these tests build the page the way the SHIM does - from frames shaped the
way the GAME's builders emit them - and assert the reader recovers the fields.
The frames below are not invented: each is the payload of one builder named in
padlcd.h's table, with the length the wire carries.

THE FAULT THIS EXISTS TO CATCH FIRST is the one that has now happened twice:
a payload field silently acquiring a meaning. `aux` must come back as a number
and must never be printed as a range, and an unknown verb must print its digit
rather than borrow a known word.
"""
import os
import struct
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

MAGIC = 0x44434C50
HDR, RAW = 60, 22
STRIDE = {3: 28, 4: 36}     # v3: one slot per frame. v4: coalesced (rep/last)


def _page(frames, version=4, state=None):
    """The shim's page: a 14-word header, ring_head at 56, ring at 60.

    A frame is ``(sel, payload)`` or, for a v4 coalesced slot,
    ``(sel, payload, rep, span_ms)``.
    """
    d = bytearray(4096)
    st = state or (2994, 0, 30, 4, 7, 8, 9, 0x80, 0x10, 12345)
    struct.pack_into("<14I", d, 0, MAGIC, version, 9, 6, *st)
    struct.pack_into("<I", d, 56, len(frames))
    for i, f in enumerate(frames):
        sel, b = f[0], f[1]
        rep, span = (f[2], f[3]) if len(f) > 2 else (1, 0)
        # Unknown versions borrow the v3 stride: the reader must refuse
        # them before the ring layout can matter.
        off = HDR + i * STRIDE.get(version, 28)
        ln = min(len(b), RAW)
        t = 1000 + i * 250
        if version >= 4:
            struct.pack_into("<IIHBB", d, off, t, t + span, rep, sel, ln)
            d[off + 12:off + 12 + ln] = b[:ln]
        else:
            struct.pack_into("<IBB", d, off, t, sel, ln)
            d[off + 6:off + 6 + ln] = b[:ln]
    return bytes(d)


#: Payloads AFTER the selector byte, i.e. the wire's ilen minus 3 bytes.
VERB_LOOP = (0x98, bytes([1]))
VERB_BARE = (0x98, bytes([4]))
ASSET_54 = (0x98, bytes([0]) + struct.pack("<I", 54))
ASSET_AUX = (0x98, bytes([0]) + struct.pack("<I", 54)
             + struct.pack("<I", 928) + struct.pack("<H", 106))
BIG = (0x98, bytes([0]) + struct.pack("<I", 2994) + struct.pack("<I", 0)
       + struct.pack("<H", 43) + struct.pack("<I", 7)
       + struct.pack("<I", 8) + struct.pack("<H", 9))
POLL = (0x90, bytes([0, 0, 0, 0]))
BRIGHT = (0x80, bytes([0x80, 0x10, 0, 0]))


def _run(tmp_path, page, expect_rc=0):
    p = tmp_path / "padlcd.last"
    p.write_bytes(page)
    r = subprocess.run([sys.executable, os.path.join(RIG, "lcdring.py"),
                        str(p)], capture_output=True, timeout=60)
    out = (r.stdout + r.stderr).decode("utf8", "replace")
    assert r.returncode == expect_rc, out
    return out


def _run_default(tmp_path, expect_rc=0):
    """No path argument: the reader resolves dump/ itself, steered here by
    PAD_ROOT - the same variable watch.sh exports to move the rootfs."""
    env = dict(os.environ, PAD_ROOT=str(tmp_path))
    r = subprocess.run([sys.executable, os.path.join(RIG, "lcdring.py")],
                       capture_output=True, timeout=60, env=env)
    out = (r.stdout + r.stderr).decode("utf8", "replace")
    assert r.returncode == expect_rc, out
    return out


def test_every_frame_shape_decodes(tmp_path):
    out = _run(tmp_path, _page([VERB_LOOP, ASSET_54, ASSET_AUX, POLL,
                                BRIGHT, BIG, VERB_BARE]))
    assert "verb 1 (play loop)" in out
    assert "asset 54" in out
    assert "aux 928" in out
    assert "12 fps" in out, "the 106 period code was not decoded as 12 fps"
    assert "status poll" in out
    assert "brightness 128 fade 16" in out
    assert "x 7/8/9" in out, "the 24-byte form's extra fields were dropped"


def test_the_rate_code_is_never_read_as_an_asset(tmp_path):
    """106 is a frame PERIOD (12 fps) and v1 drew it as an asset id. No
    output line may present it as one."""
    out = _run(tmp_path, _page([ASSET_AUX]))
    body = [l for l in out.splitlines() if l.strip().startswith("1000")]
    assert body, out
    assert "asset 106" not in out, out
    assert "12 fps" in body[0], body[0]


def test_aux_is_never_captioned_as_a_range(tmp_path):
    """v2's invented reading. The two u32s are an asset and a companion, and
    'range' / '54-928' returning means a field grew a meaning again."""
    out = _run(tmp_path, _page([ASSET_AUX]))
    assert "range" not in out.lower(), out
    assert "54-928" not in out, out


def test_unknown_verb_keeps_its_number(tmp_path):
    out = _run(tmp_path, _page([VERB_BARE]))
    assert "verb 4" in out, out
    assert "play loop" not in out and "play once" not in out, out


def test_a_wrapped_ring_reads_oldest_first(tmp_path):
    """ring_head counts slots EVER, so past 64 the slots wrap and the oldest
    live entry is head-64. Getting this backwards silently reverses the
    transcript, which is worse than not having one."""
    frames = [(0x98, bytes([0]) + struct.pack("<I", i)) for i in range(1, 65)]
    page = bytearray(_page(frames))
    struct.pack_into("<I", page, 56, 64 + 3)    # 3 slots overwritten
    out = _run(tmp_path, bytes(page))
    rows = [l for l in out.splitlines() if " 98  " in l]
    assert len(rows) == 64, out
    # slot order after wrap: head-64 = 3 -> slots 3..63 then 0..2
    assert "asset 4" in rows[0], rows[0]
    assert "asset 3" in rows[-1], rows[-1]


def test_a_coalesced_slot_prints_its_count_and_span(tmp_path):
    """The 60 Hz poll flood, as one honest line. The first live reading
    showed 0x90 arriving every 17 ms with a constant payload - a raw ring
    held ~1 s and every play command was flushed within a second. A v4
    slot carries the count and the span, and both must reach the output:
    '421 polls over 7 s' IS the cadence measurement."""
    out = _run(tmp_path, _page([(0x90, bytes([0, 0xEA, 0x41, 0]), 421, 7157),
                                ASSET_54]))
    assert "x421 over 7157 ms" in out, out
    assert "asset 54" in out, out
    # A rep-1 slot must NOT grow the suffix - most slots are single.
    row = [l for l in out.splitlines() if "asset 54" in l][0]
    assert " over " not in row, row


def test_a_saturated_count_admits_it(tmp_path):
    """rep is u16 and the shim saturates rather than wraps. 65535 exactly
    means 'at least' - printing it as an exact count would be one more
    number posing as a measurement."""
    out = _run(tmp_path, _page([(0x90, bytes([0, 0, 0, 0]), 0xFFFF, 60000)]))
    assert "x65535+ over 60000 ms" in out, out


def test_a_v3_preserved_block_still_reads(tmp_path):
    """padlcd.last files written before the coalesce exist on disk. The
    reader keeps the old stride for them rather than shifting every field
    and printing confident nonsense."""
    out = _run(tmp_path, _page([ASSET_AUX, VERB_BARE], version=3))
    assert "asset 54" in out and "aux 928" in out and "verb 4" in out, out


def test_a_version_mismatch_is_announced_not_hidden(tmp_path):
    """Reading a page whose ring layout this reader does not know must be a
    refusal, not a guess - a wrong stride shifts every field."""
    out = _run(tmp_path, _page([ASSET_54], version=2), expect_rc=1)
    assert "no known ring layout" in out, out


def test_a_page_without_the_magic_is_refused(tmp_path):
    page = bytearray(_page([ASSET_54]))
    struct.pack_into("<I", page, 0, 0)
    out = _run(tmp_path, bytes(page), expect_rc=1)
    assert "no PLCD block" in out, out


def test_an_empty_ring_says_so(tmp_path):
    out = _run(tmp_path, _page([]))
    assert "ring empty" in out, out


def test_a_live_block_wins_over_the_preserved_one(tmp_path):
    """Mid-game the previous run's padlcd.last still exists. The first cut
    preferred it, so reading the ring during a run showed the WRONG run's
    transcript - plausible output off stale evidence, this protocol's
    signature failure. Live must win."""
    dump = tmp_path / "dump"
    dump.mkdir()
    (dump / "padlcd").write_bytes(_page([ASSET_54]))
    (dump / "padlcd.last").write_bytes(_page([BRIGHT]))
    out = _run_default(tmp_path)
    header = out.splitlines()[0]
    assert "padlcd.last" not in header, \
        "the stale preserved copy shadowed the live block: %r" % header
    assert "asset 54" in out, out
    assert "brightness" not in out, \
        "the stale preserved copy's ring leaked through: %r" % out


def test_nothing_to_read_explains_both_absences(tmp_path):
    """The tool's actual debut: '[Errno 2] ... padlcd', naming only the
    fallback, from a user who had just been told a transcript would exist.
    Each absence has a plain meaning and the message must say them."""
    (tmp_path / "dump").mkdir()
    out = _run_default(tmp_path, expect_rc=1)
    assert "no run is live" in out, out
    assert "padlcd.last" in out and "ENDED" in out, out
    assert "Errno" not in out, out
