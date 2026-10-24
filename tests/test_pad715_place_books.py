"""PAD-715: the three plain-C game modes PAD-710 found no books for, and the place of a mode whose port site is a check.

James Bond's Bird One Multiball is ROCKET_MULTIBALL in the program's names (the flags its start sets), reached through
the callers of its port site - the lock-open check (PAD-578), which the lamps ask too and the lock handler asks at every
lock: a mode in its place is taken at the multiball's own start (`site place_start_<id>`), never at the check. Jurassic
Park The Pin counts its Restore Power as AUD_RESTORE_POWER_START.
"""

import glob
import os
import re

import pytest

from pinball_decryptor.plugins.stern import mode_framework as MF
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import port_derive
from pinball_decryptor.plugins.stern import portgen

SDK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu", "modes", "sdk")
PORTS = os.path.join(SDK, "ports")


def _port(name):
    with open(os.path.join(PORTS, name + ".port"), encoding="utf-8") as f:
        return f.read()


def _src(name):
    with open(os.path.join(SDK, name), encoding="utf-8") as f:
        return f.read()


# ---- the ports -----------------------------------------------------------------------------------
@pytest.mark.parametrize("key,start28,start29", [("james_bond_le-1.06", 0xe650c, 0x165f50),
                                                 ("james_bond_pro-1.06", 0xe6058, 0x164f2c)])
def test_bond_names_bird_one_books_and_both_lock_multiballs_starts(key, start28, start29):
    text = _port(key)
    for line in ("value place_audit_started_29       263", "value place_flag_played_29         73",
                 "site  place_start_28               0x%08x 0xe92d43f0 0xe24dd00c" % start28,
                 "site  place_start_29               0x%08x 0xe92d40f0 0xe24dd00c" % start29):
        assert line in text, line
    places = {i: (n, c) for i, n, c in MP._places(MP.read_port(os.path.join(PORTS, key + ".port")))}
    assert places[29] == ("Bird One Multiball", True) and places[28] == ("Jetpack Multiball", True)


def test_jurassic_park_the_pin_names_restore_power():
    assert "value place_audit_started_5        184" in _port("jurassic_park_the_pin-1.05")
    places = {i: n for i, n, _c in MP._places(MP.read_port(os.path.join(PORTS, "jurassic_park_the_pin-1.05.port")))}
    assert places[5] == "Restore Power"


def test_every_plain_c_game_mode_has_books():
    """170 of 170: every game mode of the newest plain-C ports is offered (PAD-710 found 167)."""
    for path in sorted(glob.glob(os.path.join(PORTS, "*.port"))):
        text = open(path, encoding="utf-8").read()
        if "block_obj_" in text or not re.search(r"^value place_(audit|flag)_", text, re.M):
            continue
        ids = {int(i) for i in re.findall(r"^site\s+block_start_(\d+)\s", text, re.M)}
        booked = {int(i) for i in re.findall(r"^value place_\w+?_(\d+)\s", text, re.M)}
        assert ids <= booked, (os.path.basename(path), sorted(ids - booked))


def test_the_place_start_line_is_generated():
    assert portgen.generated("site", "place_start_29 0x00165f50 0xe92d40f0 0xe24dd00c")


# ---- the finder ----------------------------------------------------------------------------------
def test_only_the_missing_lines_are_added(monkeypatch):
    """A port with some modes' books gets the others' (it was all or nothing: Bird One never came)."""
    monkeypatch.setattr(MF, "plain_books", lambda elf, text: ({6: {"started": 180}, 29: {"started": 290}}, 0x245ea0))
    monkeypatch.setattr(MF.S, "Program", lambda elf: type("P", (), {"word": lambda self, va: 0})())
    have = "game x\nsite  audit_add              0x00245ea0 0x0 0x0\nvalue place_audit_started_6        180\n"
    lines = [x for x in MF.plain_lines_for(b"", have) if not x.startswith("#")]
    assert lines == ["value place_audit_started_29       290"]
    assert MF.plain_lines_for(b"", have + "value place_audit_started_29 290\n") == []


def test_a_derived_port_reads_the_books_off_its_own_build():
    for name in ("place_audit_started_29", "place_flag_played_6", "place_audit_completed_3", "place_flag_completed_1"):
        assert port_derive._read_here(name), name
    assert not port_derive._read_here("challenge_place_1") and port_derive._read_here("switch_count")


ELF = os.environ.get("PAD_GAME_ELFS", r"C:\tmp\PAD-698\elf")


def _elf(stem):
    found = glob.glob(os.path.join(ELF, stem + "*.elf"))
    if not found:
        pytest.skip("no %s game program on this machine (set PAD_GAME_ELFS)" % stem)
    with open(found[0], "rb") as f:
        return f.read()


def test_bird_one_is_read_off_the_program():
    books, add = MF.plain_books(_elf("james_bond_le-1_06_0"), _port("james_bond_le-1.06"))
    assert add == 0x245ea0
    assert books[29] == {"started": 263, "played": 73, "start": 0x165f50}      # ROCKET_MULTIBALL, its own start
    assert books[28] == {"started": 377, "played": 106, "start": 0xe650c}     # Jetpack: its own start too
    assert "start" not in books[6]                                            # a real start: no other
    assert len(books) == 30


def test_restore_power_is_read_off_the_program():
    books, _add = MF.plain_books(_elf("jurassic_park_the_pin-1_05_0"), _port("jurassic_park_the_pin-1.05"))
    assert books[5] == {"started": 184} and len(books) == 6


# ---- the runtime ---------------------------------------------------------------------------------
def test_the_check_takes_nothing_and_the_start_takes_the_place():
    rt = _src("pad_mode_runtime.c")
    hook = rt[rt.index("static int on_block_start(unsigned *r, unsigned hook_n)"):]
    hook = hook[:hook.index("\n}\n")]
    assert "!place_check[id] && place_take(r, id)" in hook
    for want in ('pm_snprintf(name, sizeof name, "place_start_%u", id);',
                 "hook_veto_n(a, on_place_start, id, 0)) place_from[id] = a;",
                 "return id < BLOCK_IDS && place_from[id] && place_take(r, id);",
                 "if (place_check[id] && !place_from[id]) return 0;",
                 "if (!(f = place_check[id] ? place_from[id] : fn(key))) return 0;"):
        assert want in rt, want
