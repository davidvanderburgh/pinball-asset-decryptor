"""PAD-1555: Stern's November 2026 Spike 2 builds.

- ret_use.py: the callers of a build's award screens and light shows that use what they get back, read off the program
  (PAD-1400's list; its scan was lost, and a derived port copied `own_ret_scanned 1` with no list at all).
- the shipped ports of the new builds: proven headers, their own caller lists, switch_spawn only where the same model's
  earlier port had it.
"""
import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PORTS = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "ports"

from pinball_decryptor.plugins.stern import portgen as G  # noqa: E402
from pinball_decryptor.plugins.stern import ret_use as R  # noqa: E402

pytest.importorskip("capstone")

BASE = 0x10000
PUSH, POP, NOP = 0xE92D4010, 0xE8BD8010, 0xE1A00000


def _program(words, base=BASE):
    body = struct.pack("<%dI" % len(words), *words)
    hdr = bytearray(0x34 + 32)
    hdr[:4] = b"\x7fELF"
    hdr[4] = 1
    struct.pack_into("<I", hdr, 0x1C, 0x34)
    struct.pack_into("<HH", hdr, 0x2A, 32, 1)
    struct.pack_into("<8I", hdr, 0x34, 1, len(hdr), base, base, len(body), len(body), 5, 0x1000)
    return bytes(hdr) + body


def _bl(at, target):
    return 0xEB000000 | (((target - (at + 8)) >> 2) & 0xFFFFFF)


def _b(at, target):
    return 0xEA000000 | (((target - (at + 8)) >> 2) & 0xFFFFFF)


def _build():
    """show_start at BASE; one caller per rule, each with its bl's address."""
    w = [PUSH, POP]
    calls = {}

    def caller(name, after):
        at = BASE + 4 * len(w)
        calls[name] = at
        w.append(_bl(at, BASE))
        w.extend(after)
        w.append(POP)                                   # the caller's own return (r0 overwritten first where it is)

    caller("base", [0xE58010A8])                        # str r1, [r0, #0xa8]           - used as a base
    caller("checked", [0xE3500000, 0x158020A0])         # cmp r0, #0; strne r2, [r0, #0xa0] - null-checked: safe
    w.append(NOP)
    calls["returned"] = BASE + 4 * len(w)
    w.extend([_bl(BASE + 4 * len(w), BASE), POP])       # bl; pop {r4, pc}              - returned
    caller("overwritten", [0xE594009C, 0xE5903000, 0xE3A00000])   # ldr r0,[r4,#0x9c]; ldr r3,[r0]; mov r0,#0 - not it
    at = BASE + 4 * len(w)
    calls["jumped"] = at
    w.extend([_bl(at, BASE), _b(at + 4, at + 12), NOP, 0xE5803000, POP])   # bl; b +; (skipped); str r3,[r0]
    return G.Elf(_program(w)), calls


def test_the_callers_that_use_the_result_are_listed_and_no_others():
    elf, calls = _build()
    got = R.scan(elf, {"show_start": BASE})
    assert set(got) == {calls["base"], calls["returned"], calls["jumped"]}
    assert calls["checked"] not in got and calls["overwritten"] not in got


def test_the_lines_say_scanned_with_the_list():
    lines = R.lines([0x1234, 0x5678])
    assert "value own_ret_scanned      1" in lines
    assert [l for l in lines if l.startswith("value own_pass_")] == [
        "value own_pass_0           0x00001234", "value own_pass_1           0x00005678"]
    assert R.is_own("own_ret_scanned") and R.is_own("own_pass_12") and not R.is_own("own_game_x")


def test_a_derived_port_never_copies_a_reference_s_scan():
    """The copied `own_ret_scanned 1` with no own_pass lines made a whole-game mode refuse every caller."""
    from pinball_decryptor.plugins.stern import port_derive as D
    assert D._read_here("own_ret_scanned") and D._read_here("own_pass_3")
    assert G.REVISION >= 13


NEW = ("king_kong_le-1.00", "king_kong_le-1.01", "king_kong_pro-1.01", "avengers_infinity_le-1.12",
       "avengers_infinity_pro-1.12", "foo_fighters_le-1.05", "foo_fighters_pro-1.05", "dungeons_and_dragons_le-1.11",
       "dungeons_and_dragons_pro-1.11", "metallica_spike-1.05")


@pytest.mark.parametrize("key", NEW)
def test_a_new_build_ships_a_proven_port_with_its_own_caller_list(key):
    from pinball_decryptor.plugins.stern import mode_project as MP
    text = (PORTS / (key + ".port")).read_text(encoding="utf-8")
    head = text.split("\ngame ")[0]
    assert MP.UNPROVEN_MARK not in head and "Emulator-proven" in head and "checkjob.sh" in head
    assert len(re.findall(r"^value own_ret_scanned\s+1$", text, re.M)) == 1
    passes = re.findall(r"^value own_pass_\d+\s+(0x[0-9a-f]+)$", text, re.M)
    assert len(passes) >= 10
    # switch_spawn only where the same model's earlier port had one (PAD-1400 placed it where a build needed it)
    assert ("\nsite switch_spawn " in text) == (key == "metallica_spike-1.05")


def test_the_coil_record_size_is_the_build_s_own():
    """PAD-1555: the November 2026 builds grew the framework's coil record from 0x68 to 0x70 bytes (the fields the
    runtime reads stay where they were); a held coil looked for its record at the old stride and found none - "no one
    coil of the game's is node 9 coil 0" on Avengers LE 1.12. The runtime takes the size from the port."""
    src = (ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c").read_text(encoding="utf-8")
    assert '#define COIL_REC_SIZE  ((pm_addr)pm_port_value("coil_rec_size", 0x68))' in src
    big = {"king_kong_le-1.00", "king_kong_le-1.01", "king_kong_pro-1.01", "avengers_infinity_le-1.12",
           "avengers_infinity_pro-1.12", "foo_fighters_le-1.05", "foo_fighters_pro-1.05", "metallica_spike-1.05"}
    for key in NEW:
        text = (PORTS / (key + ".port")).read_text(encoding="utf-8")
        assert bool(re.search(r"^value coil_rec_size\s+0x70", text, re.M)) == (key in big), key


def test_the_scoop_event_argument_is_the_title_s_own():
    """PAD-1555: which argument a title's scoop handler takes its event in is the title's (D&D's and Venom's the
    second). Two titles naming `scoop_event_arg 1` made it look like the framework's, so King Kong's, Avengers',
    Foo Fighters' and Metallica's November ports took it - and King Kong's scoop held no ball in the emulator."""
    from pinball_decryptor.plugins.stern import port_derive as D
    assert G.REVISION >= 15
    for n in ("scoop_event", "scoop_event_arg"):
        assert n in G.TITLE_VALUES and not D.framework_value(n)
    for port in PORTS.glob("*.port"):
        has = bool(re.search(r"^value scoop_event_arg\s", port.read_text(encoding="utf-8"), re.M))
        assert not has or port.stem.startswith(("dungeons_and_dragons", "venom")), port.stem
