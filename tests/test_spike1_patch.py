"""The line-frequency ELF patch (tools/spike1_emu/s1patch.py).

The patch replaces ``sys_line_status_get_operating_frequency_pdi`` with a stub
that reports 60 Hz / not-spoofed / valid, so the game's mains self-test passes and
it boots to attract instead of "CHECK POWER DISTRIBUTION BOARD".  These tests pin
the stub's ARM encoding (a typo would corrupt the game) and the guard behaviour;
the end-to-end effect is verified live on the rig (GOT + Ghostbusters).
"""

import importlib.util
import os
import struct
import sys

import pytest

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "spike1_emu")
if _DIR not in sys.path:                       # so s1patch can `import s1elf`
    sys.path.insert(0, _DIR)


def _load(name):
    p = os.path.join(_DIR, name + ".py")
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s1patch = _load("s1patch")


def test_2arg_stub_is_the_expected_arm_instructions():
    # (unsigned& freq, bool& spoofed) — GoT / Ghostbusters / KISS
    words = struct.unpack("<6I", s1patch.STUB_2ARG)
    assert words == (
        0xE3A0203C,   # mov  r2, #60
        0xE5802000,   # str  r2, [r0]    -> *freq = 60
        0xE3A02000,   # mov  r2, #0
        0xE5C12000,   # strb r2, [r1]    -> *spoofed = 0
        0xE3A00001,   # mov  r0, #1      -> return valid
        0xE12FFF1E,   # bx   lr
    )
    assert len(s1patch.STUB_2ARG) == 24


def test_1arg_stub_omits_the_r1_write():
    # (unsigned& freq) — WWE: the caller sets only r0, so writing *spoofed via
    # r1 (as the 2-arg stub does) dereferences NULL and crashed the boot.
    words = struct.unpack("<4I", s1patch.STUB_1ARG)
    assert words == (
        0xE3A0203C,   # mov  r2, #60
        0xE5802000,   # str  r2, [r0]    -> *freq = 60
        0xE3A00001,   # mov  r0, #1      -> return valid
        0xE12FFF1E,   # bx   lr
    )
    assert len(s1patch.STUB_1ARG) == 16
    # the 1-arg stub must NOT contain the `strb r2,[r1]` NULL-write
    assert struct.pack("<I", 0xE5C12000) not in s1patch.STUB_1ARG


def test_guard_mask_matches_ldr_r3_pc_prologue():
    # stock prologue `ldr r3,[pc,#N]` is 0xE59F3xxx; the guard must accept it
    assert (0xE59F3044 & 0xFFFFF000) == s1patch._LDR_R3_PC
    # and reject something that is not that load
    assert (0xE3A0203C & 0xFFFFF000) != s1patch._LDR_R3_PC   # our own stub


def test_patch_rejects_a_non_elf(tmp_path):
    p = tmp_path / "notelf.bin"
    p.write_bytes(b"not an elf at all" * 8)
    with pytest.raises(Exception):
        s1patch.patch_line_frequency(str(p))


# --- registered-return patch (WWE's boot-to-attract gate) ---------------------

def _reg_site(ret_word, str_off=0x10):
    return struct.pack("<5I", 0xE3A03002, ret_word,
                       0xE58A3000 | str_off, 0xE28DD020, 0xE8BD87F0)


def test_reg_ret_matcher_finds_the_wwe_site_shape():
    """`mov r3,#2 ; mov r0,r8 ; str r3,[r10,#imm] ; add sp ; pop {…,pc}` — the
    status-2 early return whose stale-r8 return kept WWE re-grading its nodes
    forever (cmd 0xfe x96/node) instead of scanning the matrix."""
    win = b"\x00" * 8 + _reg_site(s1patch._REG_RET_OLD) + b"\x00" * 8
    assert s1patch._reg_ret_sites(win, s1patch._REG_RET_OLD) == [8]
    # any [r10,#imm] offset is accepted (WWE stores at #16, others differ)
    win24 = _reg_site(s1patch._REG_RET_OLD, str_off=0x18)
    assert s1patch._reg_ret_sites(win24, s1patch._REG_RET_OLD) == [0]


def test_reg_ret_matcher_rejects_near_misses():
    # a status other than 2, or a return that is not mov r0,r8
    for words in (
        struct.pack("<5I", 0xE3A03004, s1patch._REG_RET_OLD, 0xE58A3010,
                    0xE28DD020, 0xE8BD87F0),          # status 4, not 2
        struct.pack("<5I", 0xE3A03002, s1patch._REG_RET_OLD, 0xE58A3010,
                    0xE28DD020, 0xE8BD07F0),          # pop WITHOUT pc
    ):
        assert s1patch._reg_ret_sites(words, s1patch._REG_RET_OLD) == []


def test_reg_ret_new_word_returns_success():
    assert s1patch._REG_RET_NEW == 0xE3A00001        # mov r0, #1
    assert s1patch._REG_RET_OLD == 0xE1A00008        # mov r0, r8 (the bug)


# --- switch-map extractor (s1elf.extract_switch_map) --------------------------
# Correctness of the (node, index) -> name decode is verified live against the
# real Game of Thrones LE ELF (64 switches; START BUTTON=(9,5), SHOOTER
# LANE=(1,20), TROUGH #1=(1,18)…).  Here we pin the module contract: it reads an
# ELF32-LE, and degrades rather than crashes on the wrong kind of file.

def test_switch_map_rejects_a_non_elf(tmp_path):
    s1elf = _load("s1elf")
    p = tmp_path / "notelf.bin"
    p.write_bytes(b"junk bytes, definitely not an ELF" * 4)
    with pytest.raises(Exception):
        s1elf.extract_switch_map(str(p))


def test_read_cstr_rejects_binary():
    s1elf = _load("s1elf")
    # a stub with the reader's read_vaddr, exercising read_cstr in isolation
    elf = s1elf._Elf.__new__(s1elf._Elf)
    # section file-offset must be non-zero (read_vaddr treats off==0 as unmapped)
    elf.data = b"\x00" * 8 + b"HELLO\x00" + bytes([0xff, 0x00, 0x01])
    elf.sections = [dict(off=8, addr=0x1000, size=len(elf.data) - 8, type=1)]
    assert elf.read_cstr(0x1000) == "HELLO"
    assert elf.read_cstr(0x1006) is None      # 0xff -> not printable


# --- signature-aware stub selection (the WWE-crash regression) ---------------

def _mini_elf_with_freq_symbol(mangled):
    """A minimal ELF32-LE whose only symbol is the frequency function (with the
    given mangled name) at a .text offset holding a stock `ldr r3,[pc]`
    prologue — enough for patch_line_frequency to resolve + patch it."""
    _EHDR = struct.Struct("<16sHHIIIIIHHHHHH")
    _SHDR = struct.Struct("<IIIIIIIIII")
    _SYM = struct.Struct("<IIIBBH")
    TEXT_VA = 0x8000
    text = struct.pack("<I", 0xE59F3040) + b"\x00" * 60   # ldr r3,[pc,#N]; pad
    strtab = b"\x00" + mangled.encode() + b"\x00"
    symtab = _SYM.pack(0, 0, 0, 0, 0, 0)
    symtab += _SYM.pack(1, TEXT_VA, 0, 0, 0, 1)           # the function symbol
    shoff, text_off, strtab_off, symtab_off = 0x200, 0x1000, 0x2000, 0x2100
    total = symtab_off + len(symtab) + 0x40
    buf = bytearray(total)
    _EHDR.pack_into(buf, 0, b"\x7fELF\x01\x01\x01" + b"\x00" * 9,
                    2, 40, 1, 0, 0, shoff, 0, _EHDR.size, 0, 0,
                    _SHDR.size, 4, 0)
    buf[text_off:text_off + len(text)] = text
    buf[strtab_off:strtab_off + len(strtab)] = strtab
    buf[symtab_off:symtab_off + len(symtab)] = symtab

    def shdr(typ, addr, off, size, link=0, entsize=0):
        return _SHDR.pack(0, typ, 0, addr, off, size, link, 0, 1, entsize)
    sh = shdr(0, 0, 0, 0)
    sh += shdr(1, TEXT_VA, text_off, len(text))               # .text PROGBITS
    sh += shdr(3, 0, strtab_off, len(strtab))                 # .strtab
    sh += shdr(2, 0, symtab_off, len(symtab), link=2, entsize=_SYM.size)
    buf[shoff:shoff + len(sh)] = sh
    return bytes(buf)


def test_line_frequency_picks_2arg_stub_for_RjRb(tmp_path):
    p = tmp_path / "twoarg.elf"
    p.write_bytes(_mini_elf_with_freq_symbol(
        "_Z43sys_line_status_get_operating_frequency_pdiRjRb"))
    assert s1patch.patch_line_frequency(str(p)) == "patched"
    assert p.read_bytes()[0x1000:0x1000 + 24] == s1patch.STUB_2ARG


def test_line_frequency_picks_1arg_stub_for_Rj_only_wwe(tmp_path):
    p = tmp_path / "onearg.elf"
    p.write_bytes(_mini_elf_with_freq_symbol(
        "_Z43sys_line_status_get_operating_frequency_pdiRj"))
    assert s1patch.patch_line_frequency(str(p)) == "patched"
    data = p.read_bytes()
    assert data[0x1000:0x1000 + 16] == s1patch.STUB_1ARG
    # crucially, the NULL-prone `strb r2,[r1]` word is NOT present
    assert struct.pack("<I", 0xE5C12000) not in data[0x1000:0x1000 + 16]


def test_line_frequency_repatches_a_wrong_stub(tmp_path):
    # an ELF a previous build stubbed with the WRONG (2-arg) stub on a 1-arg
    # function must be CORRECTED on re-run, not refused.
    p = tmp_path / "wrong.elf"
    buf = bytearray(_mini_elf_with_freq_symbol(
        "_Z43sys_line_status_get_operating_frequency_pdiRj"))
    buf[0x1000:0x1000 + 24] = s1patch.STUB_2ARG            # the wrong stub
    p.write_bytes(bytes(buf))
    assert s1patch.patch_line_frequency(str(p)) == "patched"
    assert p.read_bytes()[0x1000:0x1000 + 16] == s1patch.STUB_1ARG
