"""PAD-1326: where a Spike 3 game keeps its players' Insider logins.

Spike 2's finder (``coop_play.insider_users``) reads 32-bit ARM code. A Spike 3 program is the same C++ built for
64-bit ARM: the user manager's lookup is ``cmp w3, #1; ldp xa, xb, [x0, #A]; csel x0, .., ne; b <table lookup>`` (the
two tables are 8-byte pointers now, read with one ldp), the table lookup's entry is still table + 20p + 4, and every
caller forms the manager - a function's static - with adrp + add. The runtime reads the tables pointer-sized and adds
the PIE's load address to the manager (``game_base``), for co-op's ``users`` line and the score feed's alike.
The library tests skip when the Spike 3 cards are not on this machine.
"""
import os
import re
import struct

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP, score_feed as SF

SDK = os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu", "modes", "sdk")


def _src():
    with open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8") as f:
        return f.read()


# ---- a synthetic 64-bit program -----------------------------------------------------------------------------------

TEXT_VA = 0x100000


def _b(at, to, link=False):
    return (0x94000000 if link else 0x14000000) | (((to - at) >> 2) & 0x3FFFFFF)


def _adrp(at, rd, target):
    imm = ((target & ~0xFFF) - (at & ~0xFFF)) >> 12
    return 0x90000000 | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5) | rd


def _add(rd, rn, imm):
    return 0x91000000 | (imm << 10) | (rn << 5) | rd


def _ldp(rt, rt2, rn, off):
    return 0xA9400000 | ((off // 8) << 15) | (rt2 << 10) | (rn << 5) | rt


def _program(manager=0x710c20, a=0x190, heads=1, callers=((21, 0), (22, 0)), cond=1):
    """A 64-bit ELF of one executable PT_LOAD: the table lookup (ELG 1.10's shape), *heads* manager lookups reading
    the tables at +a / +a+8, and callers forming *manager* through x<reg> (offset: a manager of their own)."""
    nop = 0xD503201F
    look = TEXT_VA
    w = [0xA9BE7BF3,                                   # stp x19, x30
         0x12001C34,                                   # and w20, w1, #0xff
         0x51000683,                                   # sub w3, w20, #1
         0x12001C63,                                   # and w3, w3, #0xff
         0x71000C7F,                                   # cmp w3, #3
         0x54000288,                                   # b.hi
         0xD2800081,                                   # mov x1, #4
         0x52800280,                                   # mov w0, #20
         0x9BB40400,                                   # umaddl x0, w0, w20, x1
         0x94000000,                                   # bl uuid_is_null (anywhere)
         0xD65F03C0] + [nop] * 9
    head_at = []
    for _ in range(heads):
        at = TEXT_VA + 4 * len(w)
        head_at.append(at)
        w += [0x7100047F, _ldp(3, 0, 0, a), 0x9A800060 | (cond << 12)]          # cmp w3,#1; ldp; csel x0,x3,x0,cc
        w.append(_b(TEXT_VA + 4 * len(w), look))
    for reg, extra in callers:
        mgr = manager + extra
        w.append(_adrp(TEXT_VA + 4 * len(w), reg, mgr))
        w += [nop, nop, _add(0, reg, mgr & 0xFFF), nop]
        w.append(_b(TEXT_VA + 4 * len(w), head_at[0], link=True))
    text = struct.pack("<%dI" % len(w), *w)
    ph = struct.pack("<IIQQQQQQ", 1, 5, 0x1000, TEXT_VA, TEXT_VA, len(text), len(text), 0x1000)
    hdr = (b"\x7fELF\x02\x01\x01" + b"\0" * 9 + struct.pack("<HHIQQQIHHHHHH", 3, 183, 1, TEXT_VA, 0x40, 0, 0, 64, 56,
                                                            1, 64, 0, 0))
    b = hdr + ph
    return b + b"\0" * (0x1000 - len(b)) + text


def test_a_64bit_program_names_its_manager_and_tables():
    assert CP.insider_users(_program()) == (0x710c20, 0x190, 0x198)


def test_csel_eq_swaps_which_table_is_not_player_ones():
    """``csel x0, x3, x0, eq`` picks the first for player 1, so the other table is A."""
    assert CP.insider_users(_program(cond=0)) == (0x710c20, 0x198, 0x190)


def test_the_tables_field_is_read_off_the_ldp():
    assert CP.insider_users(_program(a=0x160)) == (0x710c20, 0x160, 0x168)


def test_through_another_register_too():
    assert CP.insider_users(_program(callers=((19, 0),))) == (0x710c20, 0x190, 0x198)


def test_two_managers_or_two_lookups_name_none():
    assert CP.insider_users(_program(callers=((21, 0), (22, 0x40)))) is None
    assert CP.insider_users(_program(heads=2)) is None


def test_a_64bit_program_without_the_lookup_names_none():
    b = bytearray(_program())
    b[0x1000:0x1000 + 0x50] = b"\0" * 0x50                                     # the table lookup gone
    assert CP.insider_users(bytes(b)) is None


def test_the_feed_names_them_in_scorefeed_cfg():
    assert SF.users_line(_program()) == "users 0x00710c20 0x190 0x198"
    assert "users 0x00710c20 0x190 0x198" in SF.cfg_text("http://10.0.0.7/", "x", _program(), only=True).splitlines()


# ---- the library's Spike 3 programs --------------------------------------------------------------------------------

LIBRARY = r"D:\Pinball\images\Stern\spike3"
CARDS = {
    "fallout_le": ("fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw", 0x66ca6e0),
    "pokemon_le": ("pokemon_le-0_82_0.Release.64G.sdcard-secure.raw", 0x32973d0),
    "star_wars_2025_le": ("star_wars_2025_le-0_96_0.Release.64G.sdcard-secure.raw", 0x98b9f8),
    "star_wars_2025_pro": ("star_wars_2025_pro-0_84_0.Release.64G.sdcard-secure.raw", 0x7e5940),
    "star_wars_elg": ("star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw", 0x710c20),
    "transformers_mtmte_le": ("transformers_mtmte_le-0_96_0_spike3.Release.64G.sdcard-secure.raw", 0xad8050),
    "walking_dead_remastered_le": ("walking_dead_remastered_le-0_92_0.Release.64G.sdcard-secure.raw", 0x8859f8),
}

_PROGRAMS = {}


def _library_program(key):
    path = os.path.join(LIBRARY, CARDS[key][0])
    if not os.path.isfile(path):
        pytest.skip("no Spike 3 library card for %s" % key)
    if key not in _PROGRAMS:
        from pinball_decryptor.plugins.stern import title_reader as TR
        _game, _version, elf = TR.game_program(path)
        _PROGRAMS[key] = elf if isinstance(elf, (bytes, bytearray)) else open(elf, "rb").read()
    return _PROGRAMS[key]


def _rw_bss(b, va):
    """True when *va* is in a writable PT_LOAD's memory (the manager is a static: .data / .bss)."""
    phoff, = struct.unpack_from("<Q", b, 0x20)
    phsz, phn = struct.unpack_from("<HH", b, 0x36)
    for i in range(phn):
        t, fl, _off, v, _pa, _fs, ms, _al = struct.unpack_from("<IIQQQQQQ", b, phoff + i * phsz)
        if t == 1 and fl & 2 and v <= va < v + ms:
            return True
    return False


@pytest.mark.parametrize("key", sorted(CARDS))
def test_every_spike3_library_program_names_its_logins(key):
    b = _library_program(key)
    u = CP.insider_users(b)
    assert u == (CARDS[key][1], 0x190, 0x198)
    assert _rw_bss(b, u[0])


# ---- the runtime ---------------------------------------------------------------------------------------------------

def test_the_runtime_reads_the_tables_pointer_sized():
    src = _src()
    assert "return *(volatile const pm_addr *)(unsigned long)(mgr + off);" in src
    assert "(volatile const unsigned *)(unsigned long)(cu_mgr" not in src
    assert "(volatile const unsigned *)(unsigned long)(feed.mgr" not in src
    assert src.count("coop_user_table(cu_mgr, cu_off[") == 5
    assert "pm_addr t = coop_user_table(feed.mgr, feed.off[k]);" in src
    assert re.search(r"static int coop_user_table_ok\(pm_addr t\)\n\{\n#if PM_A64\n\s+return t >= 0x10000ul", src)


def test_the_runtime_moves_the_manager_by_the_load_address():
    src = _src()
    assert "if (cu_mgr) cu_mgr += (pm_addr)game_base;" in src
    assert "if (feed.mgr) feed.mgr += (pm_addr)game_base;" in src
    assert "static pm_addr cu_mgr;" in src
    assert re.search(r"pm_addr mgr;\s+/\* the logins' tables", src)
    assert src.count("maps_has(cu_mgr + cu_off[") == 2 and src.count("maps_has(feed.mgr + feed.off[") == 2
    assert "maps_has(cu_mgr + cu_off[0], 4," not in src and "maps_has(feed.mgr + feed.off[0], 4," not in src
