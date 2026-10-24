"""PAD-714: a mode in the place of one of the game's own modes counts as that mode on the OLDER builds too.

- The older C++ builds read the player up inline where the newest call a getter (mode_framework._inline_track): the
  finder reads their STOP (a slot that only jumps to it, Godzilla 1.13, followed) and writes `data mode_player_at`, the
  byte the runtime reads where it would call the getter.
- A derived port keeps the build's own game modes (PAD-363's lines, written from the target program into every draft):
  the merge dropped them as "no reference names it", so a derived older build had no game mode to take the place of.
- The older shipped ports carry the lines, read off their own programs.
"""
import glob
import os
import re
import types

import pytest

from pinball_decryptor.plugins.stern import mode_framework as MF
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import port_derive as D
from pinball_decryptor.plugins.stern import portgen

SDK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu", "modes", "sdk")
PORTS = os.path.join(SDK, "ports")

POPNE = 0x18BD81F0                              # popne {r4-r8, pc}
POP_LR = 0xE8BD41F0                             # pop {r4-r8, lr}
BX_R3 = 0xE12FFF13
OTHER = 0xE1A00000


def _bne(va, to):
    return 0x1A000000 | (((to - va - 8) >> 2) & 0xFFFFFF)


def _rush_118_stop():
    """Rush LE 1.18's STOP (0xf29dc, v[43]), as the disassembler gives it: the player byte read inline, a 0-based
    index, the reason stored as the stopped byte itself, the END, a tail call, and the wins after the branch over it."""
    rows = [
        (0xf29dc, "push", "{r4, r5, r6, r7, r8, lr}"), (0xf29e0, "movw", "r4, #0xaf20"), (0xf29e4, "movt", "r4, #0xb5b"),
        (0xf29e8, "mov", "r5, r0"), (0xf29ec, "ldrb", "r3, [r4]"), (0xf29f0, "sub", "r3, r3, #1"),
        (0xf29f4, "add", "r3, r0, r3"), (0xf29f8, "ldrb", "r6, [r3, #0x38]"), (0xf29fc, "cmp", "r6, #0"),
        (0xf2a00, "popne", "{r4, r5, r6, r7, r8, pc}"), (0xf2a04, "strb", "r1, [r3, #0x38]"),
        (0xf2a08, "mov", "r0, #0x1e"), (0xf2a0c, "mov", "r7, r1"), (0xf2a10, "bl", "#0x1ad86c"),
        (0xf2a14, "ldrb", "r2, [r4]"), (0xf2a18, "movw", "r3, #0x28e8"), (0xf2a1c, "ldr", "r1, [r5]"),
        (0xf2a20, "movt", "r3, #0xb62"), (0xf2a24, "add", "r2, r5, r2"), (0xf2a28, "mov", "r8, #1"),
        (0xf2a2c, "mov", "r0, r5"), (0xf2a30, "strb", "r8, [r3]"), (0xf2a34, "strb", "r6, [r2, #0x33]"),
        (0xf2a38, "ldr", "r3, [r1, #0xa8]"), (0xf2a3c, "blx", "r3"), (0xf2a40, "cmp", "r7, #0"),
        (0xf2a44, "bne", "#0xf2a64"), (0xf2a48, "bl", "#0x119cd4"), (0xf2a4c, "ldr", "r1, [r5, #4]"),
        (0xf2a50, "mov", "r2, r7"), (0xf2a54, "pop", "{r4, r5, r6, r7, r8, lr}"), (0xf2a58, "ldr", "r3, [r0]"),
        (0xf2a5c, "ldr", "r3, [r3, #0x94]"), (0xf2a60, "bx", "r3"), (0xf2a64, "ldr", "r2, [r5]"),
        (0xf2a68, "movw", "r1, #0x930"), (0xf2a6c, "ldrb", "r3, [r4]"), (0xf2a70, "movt", "r1, #0xb"),
        (0xf2a74, "ldr", "ip, [r2, #0x108]"), (0xf2a78, "add", "r3, r5, r3, lsl #2"), (0xf2a7c, "cmp", "ip, r1"),
        (0xf2a80, "ldr", "r2, [r3, #0x64]"), (0xf2a84, "add", "r2, r2, r8"), (0xf2a88, "str", "r2, [r3, #0x64]"),
    ]
    words = {0xf2a00: POPNE, 0xf2a44: _bne(0xf2a44, 0xf2a64), 0xf2a54: POP_LR, 0xf2a60: BX_R3}
    return [(va, m, o, words.get(va, OTHER)) for va, m, o in rows]


def test_an_older_builds_inline_player_read_is_its_stop():
    ins = _rush_118_stop()
    got = MF._stop_shape_inline(None, ins, ins[0][0])
    # the newest build's own (Rush LE 1.19: stopped +0x37, wins +0x64): the 0-based index puts its offsets one up
    assert got == {"player_at": 0xb5baf20, "player": None, "stopped": 0x37, "reason": None, "fn": 0xf29dc,
                   "wins": 0x64}


def test_a_function_that_is_not_the_stop_is_not_read_as_one():
    ins = _rush_118_stop()
    no_end = [(va, m, o, w) for va, m, o, w in ins if m != "blx"]        # no END: not the framework's STOP
    assert MF._stop_shape_inline(None, no_end, ins[0][0]) is None
    no_set = [(va, m, o, w) for va, m, o, w in ins if va != 0xf2a04]     # never marks the mode stopped
    assert MF._stop_shape_inline(None, no_set, ins[0][0]) is None


def test_the_byte_is_written_where_there_is_no_getter():
    found = MF.Found()
    found.update(mode_player_at=0xb5baf20, mode_slot_stop=43, mode_stopped_at=0x37, mode_wins_at=0x64)
    text = "\n".join(MF.port_lines(found))
    assert "data  mode_player_at         0x0b5baf20" in text and "site  mode_player " not in text
    assert portgen.generated("data", "mode_player_at 0xb5baf20")


def test_the_byte_makes_the_place_count():
    port = {"site": {}, "data": {"mode_player_at": 0xb5baf20}, "value": {"mode_slot_stop": 43, "mode_stopped_at": 0x37}}
    assert MP._place_counts(port)
    port["data"] = {}
    assert not MP._place_counts(port)


#: the older shipped ports whose own programs the finder read (PAD-714): the C++ builds' framework, the plain-C builds'
#: books
OLDER_CPP = ("avengers_infinity_le-1.09", "deadpool_le-1.14", "dungeons_and_dragons_le-1.00", "iron_maiden_le-1.16",
             "john_wick_le-1.01", "mando_le-1.44", "rush_le-1.18", "star_wars_le-1.30", "sword_of_rage_le-1.18",
             "turtles_pro-1.58")
OLDER_PLAIN = ("aerosmith_le-1.15", "batman-1.13", "guardians_le-1.14", "metallica_spike-1.03",
               "stranger_things_le-1.12")


def _port(name):
    with open(os.path.join(PORTS, name + ".port"), encoding="utf-8") as f:
        return f.read()


def test_every_older_shipped_port_counts_a_mode_in_a_game_modes_place():
    for name in OLDER_CPP:
        port = MP.read_port(os.path.join(PORTS, name + ".port"))
        assert MP._place_counts(port), name
        assert all(c for _i, _n, c in MP._places(port)), name
    for name in OLDER_PLAIN:
        port = MP.read_port(os.path.join(PORTS, name + ".port"))
        assert MP._places(port) and all(c for _i, _n, c in MP._places(port)), name


def test_the_older_builds_offsets_are_their_newest_builds():
    for old, new in (("rush_le-1.18", "rush_le-1.19"), ("star_wars_le-1.30", "star_wars_le-1.31"),
                     ("deadpool_le-1.14", "deadpool_le-1.16"), ("turtles_pro-1.58", "turtles_pro-1.59")):
        a, b = _port(old), _port(new)
        for name in ("mode_slot_stop", "mode_stopped_at", "mode_starts_at", "mode_wins_at"):
            pat = r"^value %s\s+(\S+)$" % name
            assert re.findall(pat, a, re.M) == re.findall(pat, b, re.M), (old, name)
        assert re.search(r"^data  mode_player_at\s+0x[0-9a-f]{8}$", a, re.M), old


# ---- the derive keeps the build's own game modes ----------------------------------------------------------------
class _Tgt:
    def word(self, va):
        return 0xE92D4010


def test_a_derived_port_keeps_the_builds_own_game_modes(monkeypatch):
    monkeypatch.setattr(D, "framework_core", lambda *a: dict(values=[], mapped=[], switch_lines=[], example="", notes=[]))
    refs = [types.SimpleNamespace(name="a-1.0", game="foo_fighters_le", version="1.04", label="Foo Fighters LE 1.04")]
    own = ["site block_start_8      0x000f83e0 0xe92d4070 0xe1a04000", "data block_obj_8        0x003f0100",
           "text block_name_8       Super Skill Shot", "value block_default 0"]
    lines = ["game x", "version 1", "site tick 0x00000100 0x1 0x2", "shot 0x1 Left ramp", "value mode_mask_busy 3"]
    draft = dict(ref="a-1.0", lines=lines + own, placed={("site", "tick"): 0x100},
                 how={("site", "tick"): "located (strict)"}, missing=[], seconds=0.1)
    body, _prov, _missing, _notes = D.merge({"a-1.0": draft}, refs, _Tgt(), "foo_fighters_le", "1.03.0", "crule")
    text = "\n".join(body)
    for line in own:
        assert line in body, line
    assert "NOT PLACED" not in text                     # (they were "no reference names it")
    assert text.count("block_name_8") == 1 and text.count("block_default") == 1


# ---- a plain-C build's own modes, from the same title's port --------------------------------------------------------
#: game programs (<game>-<major>_<minor>_<patch>*.elf): PAD_GAME_ELFS, several joined with os.pathsep
ELFS = [d for d in (os.environ.get("PAD_GAME_ELFS") or r"C:\tmp\PAD-698\elf;C:\tmp\PAD-714\elf").split(os.pathsep) if d]


def _elf(stem):
    for d in ELFS:
        found = glob.glob(os.path.join(d, stem + "*.elf"))
        if found:
            with open(found[0], "rb") as f:
                return f.read()
    pytest.skip("no %s game program on this machine (set PAD_GAME_ELFS)" % stem)


def test_a_start_is_matched_by_its_head_not_its_immediates_or_registers():
    # Batman 66: Joker (episodes 5-6) on 1.13 saves r4-r11 and counts audit 0x31, on 1.14 r4-r10 and 0x36
    assert MF._shape(0xE92D4FF8, 0xE3A00031) == MF._shape(0xE92D47F0, 0xE3A00036)
    assert MF._shape(0xE3001234, 0xE92D4010) == MF._shape(0xE30A1678, 0xE92D4010)      # movw r1 first, then the push
    assert MF._shape(0xE92D4070, 0xE1A05000) != MF._shape(0xE92D4070, 0xE1A04000)      # another register moved
    assert MF._shape(0xE92D4070, 0xE24DD014) != MF._shape(0xE92D4070, 0xE1A05000)


def test_an_older_plain_c_build_gets_its_starts_from_the_same_titles_port():
    got = MF.plain_starts(_elf("uncanny_xmen_le-0_97_0"), _port("uncanny_xmen_le-0.98"))
    assert got[0] == (0xE3A7C, "Fastball Special") and got[3] == (0x5C86C, "A Fiery Assault")
    assert 11 not in got and 13 not in got          # a tail-reached start, a wizard: no audit witness of their own
    assert len(got) == 12
    got = MF.plain_starts(_elf("elvira3-1_11_0"), _port("elvira3-1.13"))
    assert got == {0: (0xDC31C, "Houses (whichever House is selected)")}


def test_the_finder_agrees_with_the_shipped_starts_and_never_places_one_wrong():
    for key in ("uncanny_xmen_le-0.98", "batman-1.13", "metallica_spike-1.03", "james_bond_le-1.06",
                "stranger_things_le-1.12"):
        title = {"batman-1.13": "batman-1.14", "metallica_spike-1.03": "metallica_spike-1.04",
                 "stranger_things_le-1.12": "stranger_things_le-1.13"}.get(key, key)
        got = MF.plain_starts(_elf(key.replace(".", "_") + "_"), _port(title))
        have = {int(m.group(1)): int(m.group(2), 16)
                for m in re.finditer(r"^site\s+block_start_(\d+)\s+0x([0-9a-f]+)", _port(key), re.M)}
        assert got and all(have.get(i) == va for i, (va, _n) in got.items()), key
    # James Bond's Jetpack Multiball (28) is the lock-open check (PAD-578), not the function that counts its audit
    assert 28 not in MF.plain_starts(_elf("james_bond_le-1_06_"), _port("james_bond_le-1.06"))


def test_a_plain_c_books_audit_is_the_id_its_start_counts():
    # X-Men 0.98 counts AUD_FASTBALL_SPECIAL_STARTS as 165 (its name is the 209th); Bond's Ahoy wizard 276, not
    # AUD_SPECTRE_TARGET_1's 180
    books, _add = MF.plain_books(_elf("uncanny_xmen_le-0_98_"), _port("uncanny_xmen_le-0.98"))
    assert books[0]["started"] == 165
    books, _add = MF.plain_books(_elf("james_bond_le-1_06_"), _port("james_bond_le-1.06"))
    assert books[6]["started"] == 276
    assert "value place_audit_started_0        165" in _port("uncanny_xmen_le-0.98")


def test_a_derived_plain_c_draft_takes_the_titles_starts(monkeypatch):
    calls = []

    def lines(b, text):
        calls.append(text)
        return ["site block_start_0 0x00001000 0xe92d4010 0xe1a04000", "text block_name_0 Houses"] if "ok" in text else []
    monkeypatch.setattr(MF, "plain_start_lines", lines)
    tgt = types.SimpleNamespace(b=b"")
    out = portgen.own_plain_starts(tgt, "elvira3", "game elvira3\n# ok\n")
    assert out[1:] == ["site block_start_0 0x00001000 0xe92d4010 0xe1a04000", "text block_name_0 Houses"]
    assert calls == ["game elvira3\n# ok\n"]
    # no same-title reference: the title's shipped ports, its own name first, newest first
    calls.clear()
    portgen.own_plain_starts(types.SimpleNamespace(b=b""), "uncanny_xmen_le", None)
    assert [re.search(r"^version\s+(\S+)", t, re.M).group(1) for t in calls][:1] == ["0.98"]
    assert all(re.search(r"^game\s+uncanny_xmen", t, re.M) for t in calls)
