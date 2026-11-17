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


# ---- co-op play on Spike 3 -----------------------------------------------------------------------------------------

#: the flipper buttons' switch ids (left, right) in each program's own device table
FLIPPERS = {"fallout_le": [24, 25], "pokemon_le": [23, 24], "star_wars_2025_le": [45, 46],
            "star_wars_2025_pro": [45, 46], "star_wars_elg": [50, 49], "transformers_mtmte_le": [56, 55],
            "walking_dead_remastered_le": [23, 24]}


@pytest.mark.parametrize("key", sorted(CARDS))
def test_every_spike3_program_names_its_flipper_buttons(key):
    from pinball_decryptor.plugins.stern import sound_modes as SM
    assert SM.flipper_buttons(_library_program(key)) == FLIPPERS[key]


def test_a_spike3_coop_cfg_is_the_core_lines():
    b = _library_program("star_wars_elg")
    assert CP.cfg_text(b, awards={"x": True}, setting=0x70afd8, only=True).splitlines() == [
        "coop on", "button 49", "setting 0x0070afd8", "only", "users 0x00710c20 0x190 0x198"]


def test_the_coop_play_row_grows_into_the_elg_program():
    from pinball_decryptor.plugins.stern import menu_settings as MS, spike3_menu
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    b = _library_program("star_wars_elg")
    row = spike3_menu._coop_row()
    assert row[1] == CP.MENU_VALUES_A64 == 2 and row[3]["help_text"] == CP.MENU_HELP_A64
    out, settings, refused = spike3_menu.grow(b, [row])
    assert not refused and [s.key for s in settings] == [MS.COOP_PLAY]
    s = settings[0]
    assert s.live == 0x70afd8 and s.where.endswith("Attract Mode") and s.help == CP.MENU_HELP_A64
    assert MS.check(out, s) == []
    t = AdjustmentTable(out, wide_ok=True)
    assert t.wide and len(out) > len(b)


def test_the_coop_row_and_an_edition_go_on_together():
    from pinball_decryptor.plugins.stern import menu_settings as MS, spike3_menu
    b = _library_program("star_wars_elg")
    out, settings, refused = spike3_menu.grow(b, [(MS.EDITION, 2, ["A", "B"]), spike3_menu._coop_row()])
    assert not refused and {s.key for s in settings} == {MS.EDITION, MS.COOP_PLAY}
    assert len({s.live for s in settings}) == 2


def test_the_runtime_arms_coop_on_64bit():
    src = _src()
    arm = src[src.index("static void coop_arm(void)\n{"):]
    arm = arm[:arm.index("\n}\n")]
    assert "#if PM_A64" in arm and "if (!edge_hook(e)) {" in arm                    # the button's edges, hooked
    assert "coop.setting = setting_addr(coop.setting);" in src             # the row's word, moved (PAD-1382)
    assert "return a + (pm_addr)game_base;" in src
    assert "pm_addr setting;" in src
    assert "return only && v ? setting_addr(v) : 0;" in src                    # the Insider gate's too
    assert "static pm_addr insider_while;" in src and "pm_addr at = coop_setting_wanted();" in src
    assert src.count("ret = coop_add_game(r0, r1, r2, r3) & 0xffu;") == 2               # a bool in w0
    for fn in ("static void coop_scores_same(unsigned n)\n{",
               "static unsigned long long coop_award_now(const struct coop_award *a, unsigned p)\n{"):
        body = src[src.index(fn):]
        body = body[:body.index("\n}\n")]
        assert 'pm_addr s32 = data("scores32"), s64 = data("scores");' in body


def test_the_spike3_write_carries_coop():
    from pinball_decryptor.plugins.stern import spike3_modes as S3M
    assert "co-op play" not in S3M.FAMILY_LEFT_OUT
    import inspect
    sig = inspect.signature(S3M.plan)
    assert sig.parameters["coop_setting"].default == 0 and sig.parameters["coop_ok"].default is True
    w = open(os.path.join(os.path.dirname(__file__), "..", "pinball_decryptor", "plugins", "stern", "spike3_write.py"),
             encoding="utf-8").read()
    # the menu first: coop.cfg names the CO-OP PLAY row's live value
    assert w.index("menu = spike3_menu.plan(") < w.index("mplan, mremove = _plan_modes(")
    assert "coop_setting = menu.live(MS.COOP_PLAY) if menu is not None else 0" in w


def test_a_spike3_coop_plan_says_what_it_is(tmp_path):
    from pinball_decryptor.plugins.stern import mode_project as MP, mode_write as MW
    prof = MP.profiles()["star_wars_elg_1_10_spike3"]
    assert prof.arch == "a64" and not CP.title_refusal(prof)          # its port names the player sites
    b = _library_program("star_wars_elg")
    r = MW.ModePlan(project=str(tmp_path), profile=prof, port="", build=None)
    MW.coop_into(r, b, str(tmp_path), setting=0x70afd8, only=True)
    text = open(r.coop_file).read()
    assert "setting 0x0070afd8" in text and "screens" not in text and "intro" not in text
    assert r.lines[0] == "co-op play: " + CP.HOW_A64
    assert "CO-OP PLAY: 0 Off, 1 On" in r.lines[1] and r.lines[-1] == "co-op play: " + CP.A64_LEFT_OUT


# ---- the player sites on every Spike 3 port ------------------------------------------------------------------------

PORTS = {"fallout_le": ("fallout_le-0.82", True), "pokemon_le": ("pokemon_le-0.82", False),
         "star_wars_2025_le": ("star_wars_2025_le-0.96", False), "star_wars_2025_pro": ("star_wars_2025_pro-0.84", False),
         "star_wars_elg": ("star_wars_elg-1.10", True), "walking_dead_remastered_le": ("walking_dead_remastered_le-0.92", True),
         "transformers_mtmte_le": ("transformers_mtmte_le-0.96", True)}


def _port(name):
    with open(os.path.join(SDK, "ports", "spike3", name + ".port"), encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("key", sorted(PORTS))
def test_the_finder_names_each_ports_player_sites(key):
    from pinball_decryptor.plugins.stern import portcoop as PC
    text = _port(PORTS[key][0])
    cur = int(re.search(r"^data cur_player\s+(0x[0-9a-f]+)", text, re.M).group(1), 16)
    lines = PC.lines_a64(_library_program(key), cur)
    assert len(lines) == 4 and lines[2].split()[-1] == "0x%08x" % cur
    carried = [l.split("#")[0].split() for l in text.splitlines() if not l.startswith("#")]
    commented = [l[2:].split() for l in text.splitlines() if l.startswith("# site coop_") or l.startswith("# data coop_")]
    for line in lines:
        assert line.split() in (carried if PORTS[key][1] else commented), line
        assert line.split() not in (commented if PORTS[key][1] else carried), line
    if not PORTS[key][1]:                               # no switch edge: the button cannot be read
        assert not re.search(r"^site switch_edge", text, re.M)


def test_elgs_paired_lines_are_the_finders():
    from pinball_decryptor.plugins.stern import portcoop as PC
    assert PC.lines_a64(_library_program("star_wars_elg"), 0x6b1a1a) == [
        "site coop_player_change 0x00417b50 0xd0001402 0xf9468442",
        "site coop_add_player  0x00417710 0xa9be53f3 0x52800a20",
        "data coop_player            0x006b1a1a", "data coop_players           0x00792200"]


def test_a_program_without_the_shapes_names_no_sites():
    from pinball_decryptor.plugins.stern import portcoop as PC
    assert PC.lines_a64(_program(), 0x6b1a1a) == []


def test_coop_goes_on_the_spike3_titles_whose_port_reads_the_button():
    from pinball_decryptor.plugins.stern import mode_project as MP
    profs = {k: p for k, p in MP.profiles().items() if getattr(p, "arch", "") == "a64"}
    on = sorted(k for k, p in profs.items() if not CP.title_refusal(p))
    assert on == ["fallout_le_0_82_spike3", "star_wars_elg_1_10_spike3", "transformers_mtmte_le_0_96_spike3",
                  "walking_dead_remastered_le_0_92_spike3"]
    for k, p in profs.items():
        if k not in on:
            assert CP.title_refusal(p) == CP.NO_PORT % p.label


# ---- the message table and its BALL line --------------------------------------------------------------------------

#: each program's message table and the index of its "BALL %d" line (ELG's is its Spike 2 build's 1255)
MESSAGES = {"fallout_le": (0x65fbdb8, 1256), "pokemon_le": (0x31c8828, 1252), "star_wars_2025_le": (0x8e2948, 1252),
            "star_wars_2025_pro": (0x7770d8, 1248), "star_wars_elg": (0x6c96e8, 1255),
            "walking_dead_remastered_le": (0x7e6328, 1254), "transformers_mtmte_le": (0xa1c3a8, 1256)}


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_the_message_table_and_its_ball_line(key):
    from pinball_decryptor.plugins.stern import portcoop as PC
    t, n = MESSAGES[key]
    lines = PC.message_lines_a64(_library_program(key))
    assert lines == ["data message_table          0x%08x" % t, "value coop_ball_msg          %d" % n]
    text = _port(PORTS[key][0])
    carried = [l.split("#")[0].split() for l in text.splitlines() if not l.startswith("#")]
    commented = [l[2:].split() for l in text.splitlines() if l.startswith("# data message_table")
                 or l.startswith("# value coop_ball_msg")]
    for line in lines:
        assert line.split() in (carried if PORTS[key][1] else commented)


def test_the_runtime_steps_the_message_table_by_pointer_size():
    src = _src()
    assert "4u * borrow[i].idx" not in src and "4u * idx" not in src and "4u * (unsigned)v" not in src
    # borrow and restore go through PAD-1327's message_slot (which also makes a 64-bit table page writable), find steps it
    assert src.count('data("message_table") + sizeof(void *) *') == 2 and "*message_slot(borrow[i].idx) = borrow[i].old;" in src


# ---- handicaps on Spike 3 -------------------------------------------------------------------------------------------

def test_a_spike3_handicap_cfg():
    from pinball_decryptor.plugins.stern import handicap as HC, mode_project as MP
    prof = MP.profiles()["star_wars_elg_1_10_spike3"]
    assert not HC.title_refusal(prof)
    port = MP.read_port(MP.port_path(prof))
    text = HC.cfg_text(_library_program("star_wars_elg"), "star_wars_elg", setting=0x70afe8, only=True, port=port)
    lines = text.splitlines()
    assert lines[1:7] == ["handicap on", "left 50", "right 49", "start 60", "setting 0x0070afe8", "only"]
    assert not any(l.startswith("record ") for l in lines)                 # the records read 32-bit code
    assert "level +3 adj:94+6:0:15," in text                                 # AD_BALL_SAVE_TIME, 0-15 s


def test_handicaps_go_on_the_titles_that_take_coop():
    from pinball_decryptor.plugins.stern import handicap as HC, mode_project as MP, spike3_modes as S3M
    on = sorted(k for k, p in MP.profiles().items() if getattr(p, "arch", "") == "a64" and not HC.title_refusal(p))
    assert on == ["fallout_le_0_82_spike3", "star_wars_elg_1_10_spike3", "transformers_mtmte_le_0_96_spike3",
                  "walking_dead_remastered_le_0_92_spike3"]
    assert "handicaps" not in S3M.FAMILY_LEFT_OUT


def test_coop_play_and_handicap_rows_grow_together():
    from pinball_decryptor.plugins.stern import menu_settings as MS, spike3_menu
    out, settings, refused = spike3_menu.grow(_library_program("star_wars_elg"),
                                              [spike3_menu._coop_row(), spike3_menu._hand_row()])
    assert not refused
    assert {s.key: s.live for s in settings} == {MS.COOP_PLAY: 0x70afd8, MS.HANDICAP: 0x70afe8}
    for s in settings:
        assert MS.check(out, s) == []


def test_the_runtime_handicap_on_64bit():
    src = _src()
    arm = src[src.index("static void hand_arm(void)\n{"):]
    arm = arm[:arm.index("\n}\n")]
    assert "#if PM_A64" in arm and "!edge_hook(e)" in arm
    assert "hand.setting = setting_addr(hand.setting);" in src
    assert "id &= 0xffffu;" in src[src.index("static unsigned adj_chain(unsigned id)"):][:400]


# ---- co-op and handicaps are not put on one Spike 3 card ----------------------------------------------------------

def test_a_spike3_card_with_coop_leaves_the_handicaps_out(monkeypatch):
    from pinball_decryptor.plugins.stern import handicap as HC, mode_project as MP, mode_write as MW
    from pinball_decryptor.plugins.stern import spike3_modes as S3M
    prof = MP.profiles()["star_wars_elg_1_10_spike3"]
    monkeypatch.setattr(HC, "load", lambda p: True)
    monkeypatch.setattr(HC, "project_title", lambda p, probe=False: prof)
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    monkeypatch.setattr(S3M, "coop_wanted", lambda p, real_card=True: None)
    assert S3M.hand_wanted("proj", real_card=False) is prof              # handicaps alone go on
    monkeypatch.setattr(S3M, "coop_wanted", lambda p, real_card=True: prof)
    assert S3M.hand_wanted("proj", real_card=False) is None              # beside co-op they do not
    assert "co-op" in S3M.HAND_WITH_COOP and not S3M.HAND_WITH_COOP.endswith(".")


def test_the_runtime_refuses_handicaps_beside_coop_on_64bit():
    src = _src()
    arm = src[src.index("static void hand_arm(void)\n{"):]
    head = arm[:arm.index("#endif")]
    assert head.lstrip().startswith("static void hand_arm(void)\n{\n#if PM_A64")
    assert "if (coop_wanted()) {" in head and "return;" in head


# ---- beside the music modes (PAD-1324): their program is the one the machine runs ----------------------------------

def test_the_music_modes_program_carries_coop_play_and_handicap(monkeypatch):
    from pinball_decryptor.plugins.stern import menu_settings as MS, spike3_menu
    monkeypatch.setattr(spike3_menu, "coop_row_asked", lambda p: True)
    monkeypatch.setattr(spike3_menu, "hand_row_asked", lambda p: True)
    monkeypatch.setattr("pinball_decryptor.plugins.stern.editions.load", lambda p: [])
    rows = spike3_menu.rows_wanted("proj")
    assert [r[0] for r in rows] == [MS.COOP_PLAY, MS.HANDICAP]


def test_beside_music_mode_coop_play_keeps_its_setting():
    """CO-OP PLAY lands on the same setting with MUSIC MODE beside it (ELG: 0x70afd8); spike3_modes reads it off the
    music modes' grow all the same, the program the machine runs."""
    from pinball_decryptor.plugins.stern import menu_settings as MS, spike3_menu
    b = _library_program("star_wars_elg")
    _o, alone, _r = spike3_menu.grow(b, [spike3_menu._coop_row()])
    _o, both, _r = spike3_menu.grow(b, [(MS.MUSIC_MODE, 2, ["A", "B"]), spike3_menu._coop_row()])
    a = {s.key: s.live for s in alone}
    m = {s.key: s.live for s in both}
    assert MS.MUSIC_MODE in m and m[MS.COOP_PLAY] == a[MS.COOP_PLAY] == 0x70afd8 != m[MS.MUSIC_MODE]
    src = open(os.path.join(os.path.dirname(__file__), "..", "pinball_decryptor", "plugins", "stern",
                            "spike3_modes.py"), encoding="utf-8").read()
    assert "coop_setting = live.get(MS.COOP_PLAY, 0)" in src and "hand_setting = live.get(MS.HANDICAP, 0)" in src


def test_every_early_return_of_the_spike3_plan_knows_coop_and_handicaps():
    """The merge with the music modes added a check after them that returned None for a card of co-op alone (found
    planning the real ELG card): every 'nothing to carry' check counts co-op and the handicaps."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "pinball_decryptor", "plugins", "stern",
                            "spike3_modes.py"), encoding="utf-8").read()
    body = src[src.index("def plan(project, reader, scratch"):]
    body = body[:body.index("\ndef ", 10)]
    checks = re.findall(r"if \(?not modes and not code and not feed and not slots[^:]*:", body, re.S)
    assert len(checks) == 4
    for c in checks:
        assert "coop_prof is None" in c and "hand_prof is None" in c, c
