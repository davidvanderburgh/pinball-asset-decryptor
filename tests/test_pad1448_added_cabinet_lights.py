"""PAD-1448: cabinet lights a card adds on a title that has none (Friday, Pinside: "add speaker light effects to stern
games that don't have them ... stranger things or Munsters").

The finder (lampmap.count_const / added_cabinet_anchor), the port block (added_cabinet_lines, every shipped port with no
cabinet lights), the fixtures' places (Godzilla's own speaker lights), addcab.cfg, the project's choice
(cab_shows.norm_added) and the Write carrying it; the runtime reading it before the game's start-up, and every list
of the runtime's files naming it. Emulator-proven on Stranger Things LE 1.13 (docs/plans/pad1448_added_cabinet_lights.md).
"""
import os
import re
import struct

import pytest

from pinball_decryptor.plugins.stern import cab_shows as CS
from pinball_decryptor.plugins.stern import lampmap as LM
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import portgen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
PORTS = os.path.join(SDK, "ports")
EMU = os.path.join(ROOT, "tools", "spike2_emu")


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def _movw(rd, v):
    return 0xE3000000 | ((v >> 12) & 0xF) << 16 | rd << 12 | (v & 0xFFF)


def _movt(rd, v):
    return 0xE3400000 | ((v >> 12) & 0xF) << 16 | rd << 12 | (v & 0xFFF)


class _Words:
    """The little of lampmap.Elf count_const reads: words and a mapped read-only range."""
    def __init__(self, words):
        self.words = tuple(words)

    def off(self, va):
        return 0 if 0x5d0000 <= va < 0x5e0000 else None


def test_count_const_finds_the_static_initialisers_copy():
    # Stranger Things LE 1.13 at 0x44748c: movw r2,#0xc620; movw r3,#0x1370; movt r2,#0x5d; movt r3,#0x89;
    # ldr r2,[r2]; str r2,[r3]; bx lr
    code = [0xE1A00000] * 4 + [_movw(2, 0xC620), _movw(3, 0x1370), _movt(2, 0x5D), _movt(3, 0x89),
                               0xE5922000, 0xE5832000, 0xE12FFF1E] + [0xE1A00000] * 4
    assert LM.count_const(_Words(code), 0x891370) == 0x5DC620
    # a load that is not copied into the count is not its constant
    code[9] = 0xE5932000
    assert LM.count_const(_Words(code), 0x891370) is None
    assert LM.count_const(_Words(code), 0) is None


def test_added_fixtures_sit_where_godzillas_speaker_lights_do():
    """23 speaker lights: the left ring of 12, the right of 11, each place and strip position the newer titles' own
    (Godzilla LE 1.16's port), light ids = first + channel in G, R, B order (a cablamp line names R, G, B)."""
    cab = LM.added_cabinet(340)
    assert [c["name"] for c in cab] == ["SPEAKER %d" % n for n in range(1, 24)]
    gz = [l for l in _read(PORTS, "godzilla_le-1.16.port").splitlines() if l.startswith("cablamp")]
    for c, line in zip(cab, gz):
        m = re.match(r"cablamp \S+\s+(\d+)\s+(SPEAKER \d+)\s+#.* at (\d+),(\d+), speaker ([LR])", line)
        assert (c["u"], c["name"], c["x"], c["y"], c["side"]) == (int(m.group(1)), m.group(2), int(m.group(3)),
                                                                  int(m.group(4)), m.group(5))
    assert cab[0]["lights"] == [341, 340, 342] and cab[0]["channel"] == 0
    assert cab[22]["lights"] == [340 + 66 + 1, 340 + 66, 340 + 66 + 2]


def test_blades_come_first_on_the_board():
    cab = LM.added_cabinet(100, speakers=2, blades=3)
    assert [c["name"] for c in cab] == ["EXPRESSIVE LIGHTING L 1", "EXPRESSIVE LIGHTING L 2", "EXPRESSIVE LIGHTING L 3",
                                        "EXPRESSIVE LIGHTING R 4", "EXPRESSIVE LIGHTING R 5", "EXPRESSIVE LIGHTING R 6",
                                        "SPEAKER 1", "SPEAKER 2"]
    assert [c["channel"] for c in cab] == list(range(0, 24, 3))
    assert {c["role"] for c in cab[:6]} == {"blade"} and [c["side"] for c in cab[:6]] == list("LLLRRR")
    assert len(cab) * 3 <= LM.ADDCAB_CHANNELS


def test_addcab_cfg_is_what_the_runtime_reads():
    text = LM.added_cabinet_cfg(LM.added_cabinet(340))
    lines = text.splitlines()
    assert lines[1] == "channels 69"
    fx = [l for l in lines if l.startswith("fixture ")]
    assert len(fx) == 23 and fx[0] == "fixture 0 41 95 28 SPEAKER 1"
    rt = _read(SDK, "pad_mode_runtime.c")
    assert '"channels "' in rt and '"fixture "' in rt and "ADDCAB_MAX     (3 * (96 + 24))" in rt
    assert LM.ADDCAB_CHANNELS == 3 * (96 + 24)


def _port_text(name):
    return _read(PORTS, name)


def test_every_shipped_port_without_cabinet_lights_says_whether_it_can_take_them():
    """Each port with no cablamp line carries the block: the anchors, or why not (Star Wars ELG: no RGB light). The
    older builds whose programs are not on this desk (the archive cards) carry none yet."""
    seen = 0
    for f in sorted(os.listdir(PORTS)):
        if not f.endswith(".port"):
            continue
        t = _port_text(f)
        if "\ncablamp " in t:
            assert "addcab_" not in t, f
            continue
        if "# ---- added cabinet lights (PAD-1448)" not in t:
            continue
        seen += 1
        if "# not on this build:" in t:
            continue
        p = MP.read_port(os.path.join(PORTS, f))
        assert CS.addable(p), f
        v = p["value"]
        assert v["addcab_group"] == 1 and 0 < v["addcab_clone"] < v["addcab_lights"] < v["addcab_slot"] + 1000, f
        assert v["addcab_slot"] >= v["addcab_lights"] - 1, f
    assert seen >= 22


def test_stranger_things_le_anchors_are_the_emulator_proven_ones():
    p = MP.read_port(os.path.join(PORTS, "stranger_things_le-1.13.port"))
    assert p["data"]["addcab_light_tab"] == 0x7C7994 and p["data"]["addcab_dev_tab"] == 0x7C74DC
    assert p["data"]["addcab_light_n"] == 0x5DC620 and p["data"]["addcab_dev_n"] == 0x5DC75C
    assert (p["value"]["addcab_lights"], p["value"]["addcab_devices"], p["value"]["addcab_clone"],
            p["value"]["addcab_slot"]) == (340, 459, 122, 396)


def test_the_anchors_are_each_builds_own_never_a_recipes():
    assert portgen.generated("data", "addcab_light_tab 0x007c7994")
    assert portgen.generated("value", "addcab_slot 396")
    t = _port_text("stranger_things_le-1.13.port")
    without = "\n".join(l for l in t.splitlines() if "addcab_" not in l)
    assert portgen.entries_sha1(t) == portgen.entries_sha1(without)


def test_the_projects_choice_and_the_refusals():
    p = MP.read_port(os.path.join(PORTS, "munsters_le-1.28.port"))
    assert CS.addable(p)
    assert CS.port_refusal(p, "Munsters LE") == CS.NO_CAB_ADDABLE % "Munsters LE"
    on = CS.norm_added({"on": True})
    assert on == {"on": True, "speakers": 23, "blades": 0}
    assert CS.port_refusal(p, "Munsters LE", on) == ""
    assert len(CS.added_layout(p, on)) == 23
    assert CS.added_layout(p, CS.norm_added({"on": False})) == []
    assert CS.norm_added({"on": 1, "speakers": 99, "blades": -3}) == {"on": True, "speakers": 24, "blades": 0}
    assert CS.norm_added({"on": 1, "speakers": 0, "blades": 0})["speakers"] == 23     # never nothing at all
    kept = CS.norm({"shows": [], "added": {"on": True, "speakers": 12, "blades": 48}})
    assert kept["added"] == {"on": True, "speakers": 12, "blades": 48}
    assert "added" not in CS.norm({"shows": []})
    # a title with cabinet lights of its own is never offered them; one whose port cannot is refused as before
    lz = MP.read_port(os.path.join(PORTS, "led_zeppelin_le-1.22.port"))
    assert not CS.addable(lz) and CS.port_refusal(lz, "LZ") == ""
    elg = MP.read_port(os.path.join(PORTS, "star_wars_elg-1.10.port"))
    assert not CS.addable(elg) and CS.port_refusal(elg, "ELG", on) == CS.NO_CAB % "ELG"


def test_the_write_puts_addcab_cfg_beside_the_shows(tmp_path):
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.plugins.stern import mode_write as MW
    prof = next((x for x in MP.profiles().values() if x.port == "munsters_le-1.28.port"), None)
    assert prof is not None
    project = str(tmp_path / "proj")
    os.makedirs(project)
    data = staged_changes.load(project)
    data[CS.STAGED_KEY] = {"shows": [], "added": {"on": True, "speakers": 23, "blades": 0}}
    staged_changes.save(project, data)
    res = MW.ModePlan(project=project, profile=prof, port="", build=None)
    MW.addcab_into(res, str(tmp_path / "scratch"), CS.load_added(project))
    assert res.addcab_file and os.path.basename(res.addcab_file) == CS.ADD_CFG
    text = open(res.addcab_file, encoding="utf-8").read()
    assert "channels 69" in text and text.count("\nfixture ") == 23
    off = MW.ModePlan(project=project, profile=prof, port="", build=None)
    MW.addcab_into(off, str(tmp_path / "scratch2"), CS.norm_added({}))
    assert not off.addcab_file


def test_the_runtime_adds_them_after_the_gate_and_before_the_games_start_up():
    rt = _read(SDK, "pad_mode_runtime.c")
    start = rt.index("static void pad_mode_start(void)")
    body = rt[start:start + 4000]
    assert body.index("if (!port_gate()) return;") < body.index("addcab_arm();") < body.index("cabs_arm();")
    arm = rt[rt.index("static void addcab_arm(void)\n{"):]
    arm = arm[:arm.index("\n}\n")]
    # nothing is written before the build is checked against its port's counts
    assert arm.index("nl != want_l || nd != want_d") < arm.index("addcab_page_rw(lc, 1)")
    assert '"/usr/local/padmode/addcab.cfg", "/dump/addcab.cfg"' in rt


def test_every_list_of_the_runtimes_files_names_addcab_cfg():
    from tools.spike2_emu import mode_install as MI   # noqa: F401 - the card's install list
    assert ("addcab.cfg", 0o100644) in MI.EXTRA_FILES and "addcab.cfg" not in MI.STANDALONE_FILES
    tryit = _read(EMU, "modes", "tryit.sh")
    assert tryit.count('"$DUMP"/addcab.cfg') == 2 and 'put "$S/addcab.cfg" "$DUMP/addcab.cfg"' in tryit
    cm = _read(EMU, "modes", "cardmodes.sh")
    assert cm.count("addcab.cfg") == 2
    rg = _read(EMU, "run_game.sh")
    assert '[ -f "$R/dump/addcab.cfg" ]' in rg and "grep -vx 2" in rg


@pytest.mark.skipif(not os.path.isdir(r"C:/tmp/PAD-1400/elf"), reason="the extracted programs are on David's desk")
def test_the_finder_on_the_real_programs():
    for key, want in (("stranger_things_le-1.13", (0x5DC620, 0x5DC75C, 340, 459, 122, 396)),
                      ("munsters_le-1.28", (0x4B2F54, 0x4B3040, 143, 269, 6, 215))):
        a = LM.added_cabinet_anchor(LM.Elf(os.path.join(r"C:/tmp/PAD-1400/elf", key)))
        assert (a["light_const"], a["dev_const"], a["lights"], a["devices"], a["clone"], a["slot"]) == want, key
