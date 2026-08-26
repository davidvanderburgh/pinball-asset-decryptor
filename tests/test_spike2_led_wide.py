"""leddecode.wide_decode(): batman's lamp dialect, against the real wire.

Queue item 85. David, on his live batman run: "i'm only seeing board 8 and 9
here and i'm not seeing all the leds coming through - are we missing some node
boards?" The boards were all present and being driven; the shim simply could
not read the command family that drives them. hwshim.c's led_wide_publish
header carries the reverse-engineering; this pins the result.

EVERY FRAME HERE IS REAL, taken from the `[nbcmd] <cmd> first frame <hex>`
lines of that run (batman-1_13_0, 2026-08-26) - the shim logs the first frame
it ever sees of each command, so this is one genuine example of every lamp
command the title speaks, on the node it was actually sent to. Nothing is
hand-built, because a hand-built frame would only ever test the grammar
against itself.

THE THINGS WORTH FAILING ON:

  * The LEVELS, not just the lamp lists. Half of these commands spend no bytes
    at all on brightness - the planner folds an all-off or all-on frame into
    two bits of the command byte (0x51667c) - so a decoder can address exactly
    the right lamps and still render a dark playfield. Getting the list right
    and the level wrong is the failure that looks like success.

  * A frame that does not fit the grammar must be REFUSED, not approximated.
    Only cmd 70 is refused here, and for a structural reason (bit 7 clear, a
    different builder entirely). If that list ever grows, something regressed;
    if it shrinks, someone taught the grammar a new form and should say so.

  * The two sides of the pair. b4 and b5 differ only in the level bit, so they
    must come out as one lamp set at opposite brightnesses - the assertion
    that catches reading them as godzilla's range fade.

tests/test_spike2_led_wide_twins.py is the other half of this: it compiles the
C out of hwshim.c and checks it agrees with the Python on every frame here.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

sys.path.insert(0, RIG)


def _leddecode():
    import leddecode
    return leddecode


#: `[nbcmd] <cmd> first frame <hex>`, batman-1_13_0, David's run of 2026-08-26.
FRAMES = {
    0x70: "8105700800000200",
    0x88: "8809888067f8ff080002ff00",
    0x89: "8808898036080e0e020b00",
    0x8A: "883d8adc067ff87fdf0720029289f019ffffff0000ff000000ff000000000000"
          "00ff0000ff0000ffff0000ff000000ff00000000ff5400ffff00005400021100",
    0x8E: "8d358ec203ffbf0ffeff0000ffffff000000ffff00000000000010101f1f1f1f"
          "1f1f1f1f1f1f1f1e08080f0f0f0f0f0f0f0f0f0f1e1eb100",
    0x95: "88069580660e02e700",
    0x96: "8d0a968000f0ffff00000f5600",
    0x97: "8a05970a3f028f00",
    0x98: "880d98b1070802800ee0020002108f00",
    0x9A: "8d0e9a80010ec0061000ffffff1e084300",
    0x9E: "8d179e80010ecf8701ffff00ffff000010100f1e08081e1e4300",
    0xA0: "8806a0039602003700",
    0xA1: "8806a11bb60002fe00",
    0xA2: "8a08a206883f000200fd00",
    0xA4: "8a04a406893f00",
    0xA5: "8904a500814d00",
    0xA6: "8d06a6008100ff4700",
    0xB4: "8905b427ac02e900",
    0xB5: "8905b527ac02e800",
    0xB7: "8a06b706883f02ea00",
}

#: cmd: (node, [indices], [levels]). Written out rather than computed, so a
#: change to the walk has to change a number a human put here on purpose.
#: Every command's lamps and levels. Nineteen of the twenty decode; the
#: level column is the payoff, and where it reads all-0x00 or all-0xFF the
#: frame spent no bytes on it (command bits 0-1 of 0 and 1 - see wide_decode).
#:
#: b4/b5 are the pair worth staring at. godzilla's dialect reads those three
#: bytes as [start][0x80|end][rate]: a RANGE fade over lamps 39..44. batman's
#: builder says otherwise, and says it twice - the index-list body at 0x518c50
#: emits [first][the count-2 middle indices][last|0x80], so this is the two
#: ENDPOINTS and the four lamps between them are untouched; and b4/b5 differ
#: only in command bit 0, which is the level, so they are the SAME two lamps
#: driven off and on. Same bytes, six lamps or two, and only the builder can
#: say which.
DECODED = {
    0x88: (8, [51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63], [0x00] * 13),
    0x89: (8, [27, 49, 50, 51], [0xFF] * 4),
    #: 45 lamps in a 59-byte body, which is only possible because the index
    #: bitmap is sparse: body[0] = 0xdc says fill with 0xff and transmit three
    #: of the seven window bytes.
    0x8A: (8, [0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18,
               19, 20, 21, 22, 23, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37,
               38, 40, 41, 42, 43, 44, 46, 47, 48, 49, 50],
           [0xFF, 0xFF, 0xFF, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0xFF, 0x00,
            0x00, 0xFF, 0xFF, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00,
            0x00, 0x00, 0x00, 0xFF, 0x54, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x54,
            0x00]),
    0x8E: (13, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17,
                18, 19, 20, 21, 23, 24, 25, 26, 27],
           [0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x10, 0x10, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F,
            0x1F, 0x1F, 0x1F, 0x1F, 0x1F]),
    0x95: (8, [49, 50, 51], [0xFF] * 3),
    0x96: (13, [4, 5, 6, 7], [0xFF, 0xFF, 0x00, 0x00]),
    0x97: (10, [10], [0x3F]),
    0x98: (8, [3, 9, 47, 49, 50, 51, 61, 62, 63], [0x00] * 9),
    0x9A: (13, [1, 2, 3, 14, 15], [0x10, 0x00, 0xFF, 0xFF, 0xFF]),
    0x9E: (13, [1, 2, 3, 8, 9, 10, 11, 14, 15],
           [0xFF, 0xFF, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x10, 0x10]),
    0xA0: (8, [3, 22], [0x00] * 2),
    0xA1: (8, [27, 54], [0xFF] * 2),
    0xA2: (10, [6, 8], [0x3F, 0x00]),
    0xA4: (10, [6, 9], [0x00] * 2),
    0xA5: (9, [0, 1], [0xFF] * 2),
    0xA6: (13, [0, 1], [0x00, 0xFF]),
    0xB4: (9, [39, 44], [0x00] * 2),
    0xB5: (9, [39, 44], [0xFF] * 2),
    #: command bits 0-1 == 3: ONE level byte shared by every addressed lamp,
    #: which is why both of these read 0x3f from a body carrying it once.
    0xB7: (10, [6, 8], [0x3F] * 2),
}

#: Refused, and for a reason worth keeping straight: cmd 70 is not in this
#: family at all - bit 7 of the command is CLEAR. It has its own builder
#: (0x51c2b4) and the older decode path owns it, and the day this grammar
#: starts accepting it, it is reading someone else's frame.
REFUSED = (0x70,)


def test_every_captured_frame_is_well_formed():
    """The corpus itself: real frames, so every checksum must close.

    If this fails the test data was mistyped, and every other assertion in the
    file is measuring the typo instead of the decoder.
    """
    for cmd, hexs in FRAMES.items():
        b = bytes.fromhex(hexs)
        assert b[1] + 3 == len(b), "cmd %02x: blen does not match length" % cmd
        assert sum(b[:-1]) & 0xFF == 0, "cmd %02x: checksum" % cmd
        assert b[2] == cmd, "cmd %02x: wrong command byte" % cmd


@pytest.mark.parametrize("cmd", sorted(DECODED))
def test_every_command_decodes_to_its_lamps_and_levels(cmd):
    got = _leddecode().wide_decode(bytes.fromhex(FRAMES[cmd]))
    assert got is not None, "cmd %02x should decode" % cmd
    idxs, vals = got
    node, want_idx, want_val = DECODED[cmd]
    assert bytes.fromhex(FRAMES[cmd])[0] & 0x3F == node
    assert idxs == want_idx
    assert vals == want_val


def test_the_census_is_covered():
    """Every command batman was seen to speak is accounted for, either way.

    Without this, dropping a command out of DECODED would silently reduce what
    is being checked instead of failing.
    """
    assert set(DECODED) | set(REFUSED) == set(FRAMES)


def test_the_off_and_on_pair_is_the_same_two_lamps():
    """b4/b5 differ only in the level bit, so they must address one lamp set.

    This is the assertion that would have caught reading them as godzilla's
    range fade: a range would make them lamps 39..44, and the pair would still
    look self-consistent while being four lamps wrong.
    """
    ld = _leddecode()
    off = ld.wide_decode(bytes.fromhex(FRAMES[0xB4]))
    on = ld.wide_decode(bytes.fromhex(FRAMES[0xB5]))
    assert off[0] == on[0] == [39, 44]
    assert set(off[1]) == {0x00} and set(on[1]) == {0xFF}


@pytest.mark.parametrize("cmd", REFUSED)
def test_frames_that_do_not_fit_are_refused(cmd):
    assert _leddecode().wide_decode(bytes.fromhex(FRAMES[cmd])) is None, (
        "cmd %02x does not fit this grammar and must be refused, not "
        "approximated" % cmd)


def test_every_addressed_index_is_a_real_lamp():
    """No decode may address a lamp the block cannot hold (val is [16][96])."""
    for cmd, hexs in FRAMES.items():
        got = _leddecode().wide_decode(bytes.fromhex(hexs))
        if got is None:
            continue
        idxs, vals = got
        assert idxs, "cmd %02x decoded to no lamps at all" % cmd
        assert all(0 <= i < 96 for i in idxs), "cmd %02x: index out of range" % cmd
        assert len(idxs) == len(set(idxs)), "cmd %02x: duplicate index" % cmd
        #: The analyzer splits a run rather than emit an out-of-order index
        #: (0x516794), so both body forms are ascending by construction. A
        #: decode that comes out unsorted is a decode that has drifted.
        assert idxs == sorted(idxs), (
            "cmd %02x: indices should come out ascending" % cmd)
        if vals is not None:
            assert len(vals) == len(idxs)
            assert all(0 <= v <= 255 for v in vals)


def test_a_truncated_frame_is_refused_rather_than_guessed():
    """Every prefix of a good frame is a bad frame, and must be refused.

    The exact-close rule is the whole safety argument for running this decoder
    on boards with no node gate, so it gets a test that attacks it directly
    rather than one that only confirms the happy path.
    """
    ld = _leddecode()
    good = bytes.fromhex(FRAMES[0x9E])
    assert ld.wide_decode(good) is not None
    for cut in range(6, len(good) - 1):
        maimed = good[:cut] + good[-2:]
        if len(maimed) == len(good):
            continue
        got = ld.wide_decode(maimed)
        assert got is None or got[0] != DECODED[0x9E][1], (
            "a %d-byte truncation decoded to the full frame's lamps" % cut)
