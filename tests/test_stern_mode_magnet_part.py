"""PAD-381: a mode holds the ball on the magnet - the model, the generated mode file, the interpreter's
key and the tab's seconds, at the desk. The runtime call underneath (pm_magnet_grab, its limits) is
tests/test_spike2_mode_magnet.py's. The emulator proof of a mode file's `magnet` line is recorded in
``mode_project.MAGNET_PROVEN``; until a build is there the tab greys Magnet and ``validate`` refuses one.

What is worth failing on:
  * A MODE NEVER NAMES A POWER OR A COIL. Its file carries a time and a shot; mode_file.c only ever
    calls pm_magnet_grab, so every limit the runtime holds applies to a mode file too.
  * THE SHOT IS THE PORT'S: the one the magnet sits at, never the user's pick.
  * THE APP'S LIMITS ARE THE RUNTIME'S: what the tab lets you type is what the runtime would send.
"""

import pathlib
import re
from dataclasses import replace

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"

PRO_116 = MP.profile_from_port(str(SDK / "ports" / "godzilla_pro-1.16.port"))
#: Godzilla Pro 1.16 as a proven build would see it, and as one that cannot
CAN = replace(PRO_116, key="godzilla_pro_1_16_magtest",
              cannot=tuple(c for c in PRO_116.cannot if c[0] != "magnet"))
CANNOT = replace(PRO_116, key="godzilla_pro_1_16_magnot",
                 cannot=(("magnet", "Not on Godzilla Pro 1.16 yet (a test)."),))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    monkeypatch.setitem(MP.PROFILES, CAN.key, CAN)
    monkeypatch.setitem(MP.PROFILES, CANNOT.key, CANNOT)


def _spec(title, **kw):
    spec = MP.blank_spec(MP.PROFILES[title])
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _lines(spec):
    return [line for line in MP.runtime_cfg(spec, "mag").splitlines() if not line.startswith("#")]


def _key(lines, key):
    return [line.split(None, 1)[1] for line in lines if line.split(None, 1)[0] == key]


def test_the_port_names_the_godzilla_target_as_the_magnets_shot():
    assert PRO_116.magnet_shot == "Godzilla target"
    le = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
    assert le.magnet_shot == "Godzilla target"
    # PAD-394: Pro 1.15's port names the magnet too, and a grab was seen there
    assert MP.GODZILLA_PRO_1_15.magnet_shot == "Godzilla target" and MP.GODZILLA_PRO_1_15.can("magnet")


def test_a_mode_has_no_magnet_until_one_is_set():
    spec = MP.ModeSpec(title=CAN.key)
    assert spec.magnet_ms == 0 and not _key(_lines(_spec(CAN.key)), "magnet")
    assert MP.blank_spec(CAN).magnet_ms == 0
    old = MP.ModeSpec.from_json({"format": 1, "name": "OLD", "seconds": 30})
    assert old.magnet_ms == 0


def test_the_line_carries_a_time_and_the_ports_shot_and_nothing_else():
    plain = _lines(_spec(CAN.key))
    on = _lines(_spec(CAN.key, magnet_ms=2500))
    assert _key(on, "magnet") == ["2500 0x00080000"]
    assert [line for line in on if not line.startswith("magnet")] == plain
    # a title that cannot: refused with the Mode page's reason, and nothing builds
    spec = _spec(CANNOT.key, magnet_ms=2500)
    assert MP.validate(spec) == MP.validate_magnet(spec, CANNOT) == [
        "Holding the ball on the magnet is not on Godzilla Pro 1.16 yet (Mode says why)."]
    assert MP.magnet_lines(spec, CANNOT) == []
    with pytest.raises(MP.ModeProjectError):
        MP.runtime_cfg(spec, "mag")
    assert MP.blank_spec(CANNOT).magnet_ms == 0


@pytest.mark.parametrize("value", [99, 5001, "two"])
def test_validate_names_a_bad_time(value):
    problems = MP.validate(_spec(CAN.key, magnet_ms=value))
    assert "The magnet holds the ball 0.1 to 5 seconds." in problems
    from pinball_decryptor.webui.tabs.modes import problem_pages
    assert problem_pages(problems) == ["mode"] * len(problems)


def test_the_field_round_trips(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=MP.ModeSpec(name="HELD", magnet_ms=1500))
    assert MP.load(str(project / "modes" / slug / "mode.json")).magnet_ms == 1500


def test_the_tab_reads_seconds_as_whole_ms():
    from pinball_decryptor.webui.tabs.modes import ModesTab
    assert ModesTab._magnet_ms("2") == 2000
    assert ModesTab._magnet_ms("1.5") == 1500
    assert ModesTab._magnet_ms(" 0.1 ") == 100
    assert ModesTab._magnet_ms("lots") == "lots"           # kept as typed: validate names it
    assert ModesTab.SPINBOXES["magnet_s"][:2] == [MP.MAGNET_MIN_MS / 1000, MP.MAGNET_MAX_MS / 1000]


def test_the_apps_limits_are_the_runtimes():
    rt = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    assert int(re.search(r"#define MAGNET_MAX_MS\s+(\d+)u", rt).group(1)) == MP.MAGNET_MAX_MS
    assert int(re.search(r"#define MAGNET_MIN_MS\s+(\d+)u", rt).group(1)) == MP.MAGNET_MIN_MS


def test_every_shipped_build_gets_a_verdict_with_the_game_named():
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        build = "%s-%s" % (p.game_dir, p.version)
        if build in MP.MAGNET_PROVEN:
            assert p.can("magnet") and p.magnet_shot, key
        else:
            assert not p.can("magnet") and p.label in p.why_not("magnet"), key


def test_the_interpreter_only_ever_asks_the_runtime():
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    assert "if (magnet_line(M, line)) return;" in src
    # a mode file reaches the magnet through pm_magnet_grab alone: never a coil call, never a power
    assert "coil_fire" not in src and "magnet_send" not in src
    body = src[src.index("static void magnet_shot("):]
    body = body[:body.index("\n}\n")]
    assert "pm_magnet_grab(cfg.magnet_ms)" in body and "(mask & cfg.magnet_bits)" in body
    # the running mode's hits, and the hit that starts it (both starting paths)
    on_shot = src[src.index("static void on_shot(uint64_t mask)"):]
    on_shot = on_shot[:on_shot.index("\n}\n")]
    assert on_shot.count("magnet_shot(M, mask)") == 3
    assert on_shot.count("if (running(M)) magnet_shot(M, mask);") == 2
    # the shot defaults to the port's
    assert 'pm_port_value("magnet_shot", 0)' in src[src.index("static int magnet_line("):]
    # and a mode's end goes through pm_end, where the runtime lets go
    end = src[src.index("static void mode_end(const char *why)"):]
    assert "pm_end();" in end[:end.index("\n}\n")]


def test_the_ports_name_the_shot_the_magnet_sits_at():
    for name in ("godzilla_pro-1.16", "godzilla_le-1.16", "godzilla_pro-1.15"):
        port = MP.read_port(str(SDK / "ports" / (name + ".port")))
        assert port["value"]["magnet_shot"] == dict(port["shot"])["Godzilla target"], name


def test_the_docs_name_the_key_and_the_field():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("magnet", "magnet_ms", "pm_magnet_grab"):
        assert re.search(r"`%s(?:[ (][^`]*)?`" % re.escape(name), doc), name
    assert "**From a mode file, and the Modes tab.** `magnet <ms> [mask]`" in (
        SDK / "MODE_SDK.md").read_text(encoding="utf-8")


#: PAD-420: the builds whose magnet is one of their PROVEN held coils, and the shot nearest it on the playfield picture
#: (not King Kong or Avengers: the game answers their one shot by the magnet with that magnet itself - King Kong pulses
#: it 4 x 20 ms on a pit target hit, Avengers grabs the ball in its tower - so a mode's grab there adds nothing)
MAGNET_COILS = {
    "jurassic_park_le-1.16": ("trex_magnet", "Left ramp enter opto"),
    "james_bond_le-1.06": ("jet_pack_magnet", "Tank hood target"),
}


@pytest.mark.parametrize("key", sorted(MAGNET_COILS))
def test_a_magnet_that_is_a_held_coil_is_the_magnet_part_s_coil(key):
    """PAD-420: `text magnet_coil <name>` makes one of the port's held coils the magnet a mode's `magnet` line grabs
    with - one coil, one set of limits, whichever part asks - and only a held coil the port can drive counts."""
    coil, shot = MAGNET_COILS[key]
    port = MP.read_port(str(SDK / "ports" / (key + ".port")))
    assert port["text"]["magnet_coil"] == coil and (key, coil) in MP.HELD_COILS_PROVEN
    assert MP._magnet_ports(port) and MP._magnet_shot_name(port) == shot
    bad = dict(port, text=dict(port["text"], magnet_coil="no_such_coil"))
    assert not MP._magnet_ports(bad)


def test_the_runtime_grabs_with_the_port_s_magnet_coil():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    body = src[src.index("static const char *magnet_coil_name(void)"):]
    body = body[:body.index("\n}\n") + 3]
    assert 'pm_port_text("magnet_coil")' in body and 'return t && *t ? t : "magnet";' in body
    assert "int pm_magnet_grab(unsigned ms) { return pm_coil_hold(magnet_coil_name(), ms); }" in src
