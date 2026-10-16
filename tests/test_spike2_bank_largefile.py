"""PAD-593: the game program's sound-bank loader taught the large-file calls.

The words are Godzilla Premium/LE 1.16's own loader (0x3b5b30..0x3b5c34, read off a
custom image's program), laid out on a stand-in program so the finder, the patch and its
refusals run without a card."""
import struct

import pytest

from pinball_decryptor.plugins.stern.spike2 import bank_largefile as BL

TVA = 0x3B5B30
P_OPEN, P_FXSTAT, P_XSTAT64 = 0x159D0, 0x14CBC, 0x15250


def _bl(frm, to):
    return 0xEB000000 | (((to - (frm + 8)) >> 2) & 0xFFFFFF)


def _loader():
    """The loader's words from 0x3b5b30, with its calls aimed at the stand-in PLT."""
    w = [
        0xE2850078,  # 3b5b30 add r0, r5, #120
        0xE3A01000,  # 3b5b34 mov r1, #0
        None,        # 3b5b38 bl open
        0xE2507000,  # 3b5b3c subs r7, r0, #0
        0xBA00002B,  # 3b5b40 blt
        0xE3A00003,  # 3b5b44 mov r0, #3
        0xE1A01007,  # 3b5b48 mov r1, r7
        0xE28D2018,  # 3b5b4c add r2, sp, #24
        None,        # 3b5b50 bl __fxstat
        0xE3500000,  # 3b5b54 cmp r0, #0
        0xBA00002A,  # 3b5b58 blt
        0xE3A00000,  # 3b5b5c mov r0, #0
        0xE1A04000,  # 3b5b60 mov r4, r0
        0xEBFFFF1B,  # 3b5b64 bl ...
        0xE59D0044,  # 3b5b68 ldr r0, [sp, #68]
        0xE1A01FC0,  # 3b5b6c asr r1, r0, #31
        0xEBFFFED0,  # 3b5b70 bl ...
        0xE3A02001,  # 3b5b74 mov r2, #1
        0xE59D1044,  # 3b5b78 ldr r1, [sp, #68]
        0xE1A00004,  # 3b5b7c mov r0, r4
        0xE58D7000,  # 3b5b80 str r7, [sp]
        0xE1A03002,  # 3b5b84 mov r3, r2
        0xE58D4004,  # 3b5b88 str r4, [sp, #4]
        0xEBF1806D,  # 3b5b8c bl mmap
        0xE3700001,  # 3b5b90 cmn r0, #1
        0x0A000032,  # 3b5b94 beq
        0xE3560000,  # 3b5b98 cmp r6, #0
        0xE5850070,  # 3b5b9c str r0, [r5, #112]
        0xE5854074,  # 3b5ba0 str r4, [r5, #116]
        0x1A00001C,  # 3b5ba4 bne
        0xE3043C40,  # 3b5ba8 movw r3, #0x4c40
        0xE59D2044,  # 3b5bac ldr r2, [sp, #68]
        0xE347307D,  # 3b5bb0 movt r3, #0x7d
        0xE3A04001,  # 3b5bb4 mov r4, #1
        0xE1C300D0,  # 3b5bb8 ldrd r0, [r3]
        0xE0900002,  # 3b5bbc adds r0, r0, r2
        0xE0A11FC2,  # 3b5bc0 adc r1, r1, r2, asr #31
    ]
    w[2] = _bl(TVA + 8, P_OPEN)
    w[8] = _bl(TVA + 32, P_FXSTAT)
    return w


class _Prog:
    """What bank_largefile reads of a program: its text words, where they sit, its PLT."""

    def __init__(self, words, plt=None):
        self.words = list(words)
        self.tva = TVA
        self.plt_by_name = dict(plt or {"open": P_OPEN, "__fxstat": P_FXSTAT,
                                         "__xstat64": P_XSTAT64})

    def off(self, va):
        return va - TVA


@pytest.fixture
def prog(monkeypatch):
    holder = {}

    def make(words, plt=None):
        p = _Prog(words, plt)
        holder["p"] = p
        return b"".join(struct.pack("<I", x) for x in p.words)

    def elf(b):
        p = holder["p"]
        return _Prog([struct.unpack_from("<I", b, 4 * i)[0] for i in range(len(b) // 4)],
                     p.plt_by_name)

    monkeypatch.setattr(BL, "_elf", elf)
    return make


def _apply(b, ov):
    b = bytearray(b)
    for o, v in ov.items():
        b[o:o + len(v)] = v
    return bytes(b)


def _word(b, va):
    return struct.unpack_from("<I", b, va - TVA)[0]


def test_the_loader_opens_large_files_and_reads_the_size_unsigned(prog):
    b = prog(_loader())
    ov = BL.overlay(b)
    out = _apply(b, ov)
    assert _word(out, 0x3B5B34) == 0xE3A01802          # mov r1, #0x20000 (O_LARGEFILE)
    assert _word(out, 0x3B5B48) == 0xE2851078          # add r1, r5, #120: the bank's path
    assert _word(out, 0x3B5B50) == _bl(0x3B5B50, P_XSTAT64)
    for va, rd in ((0x3B5B68, 0), (0x3B5B78, 1), (0x3B5BAC, 2)):
        assert _word(out, va) == 0xE59D0048 | (rd << 12)   # ldr rd, [sp, #72] (stat64 st_size)
    assert _word(out, 0x3B5B6C) == 0xE3A01000          # mov r1, #0 (zero extension)
    assert _word(out, 0x3B5BC0) == 0xE2A11000          # adc r1, r1, #0
    assert len(ov) == 8                                 # 3 at the stat, 3 loads, 2 extensions
    # once on, the program carries it and patching again changes nothing
    assert BL.overlay(out) == {} and BL.carries(out) and not BL.carries(b)
    assert BL.bank_limit(b) == BL.LARGE_BANK_BYTES


def test_another_shape_keeps_the_2_gib_ceiling(prog):
    from pinball_decryptor.plugins.stern.spike2.emulator import MAX_IMAGE_BYTES
    w = _loader()
    w[5] = 0xE3A00001                                   # not __fxstat's _STAT_VER call
    b = prog(w)
    with pytest.raises(BL.LargefileError):
        BL.overlay(b)
    assert BL.bank_limit(b) == MAX_IMAGE_BYTES and not BL.patchable(b)
    # and a program without __xstat64 to call
    b = prog(_loader(), {"open": P_OPEN, "__fxstat": P_FXSTAT})
    assert BL.bank_limit(b) == MAX_IMAGE_BYTES


def test_the_ceiling_fits_the_desk_emulators_window():
    """Every build derives its bank at emulator.DESC_BASE, so the patched ceiling has to fit
    between there and 4 GiB."""
    from pinball_decryptor.plugins.stern.spike2.emulator import DESC_BASE, MAX_IMAGE_BYTES
    assert MAX_IMAGE_BYTES < BL.LARGE_BANK_BYTES <= (1 << 32) - DESC_BASE
