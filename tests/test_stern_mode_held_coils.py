"""PAD-381: the other mechanisms a mode may hold like the magnet - the Mechagodzilla magnet and the bridge
diverter on a Godzilla Premium/LE. Held by the same runtime code as the Godzilla magnet (one bounded command
at the coil object's own powers, from a process of ours that controls it; tests/test_spike2_mode_magnet.py
holds that code), named by the port, written by the app as ``coil_hold <name> <ms> [mask]``. Emulator-proven on
the stock Premium/LE 1.16 card (MODE_SDK.md "Held coils"; ``mode_project.HELD_COILS_PROVEN``).

What is worth failing on:
  * ONE CODE PATH FOR EVERY HELD COIL: pm_magnet_grab is pm_coil_hold("magnet"), and every coil gets the same
    limits; the powers are the object's own.
  * THE GAME WINS, for any coil: a process of the game's controlling it, or an on-time it asked for, refuses a
    hold and ends one.
  * THE PORT'S GETTER BUILDS THE PORT'S DEVICE: checked in the game program itself when it is here.
"""
import os
import pathlib
import re
import struct

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
LE_PORT = SDK / "ports" / "godzilla_le-1.16.port"
LE_ELF = [os.environ.get("PAD_GODZILLA_LE_116_GAME", ""), r"C:\tmp\gzle116_stock.elf", "/mnt/c/tmp/gzle116_stock.elf"]


def _lift(src, signature):
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


# ---- the runtime ---------------------------------------------------------------------------
def test_every_held_coil_is_the_magnets_code():
    src = RUNTIME.read_text(encoding="utf-8")
    for api, body in (("int pm_magnet_grab(", 'pm_coil_hold("magnet", ms)'),
                      ("void pm_magnet_release(", 'pm_coil_release("magnet")'),
                      ("int pm_magnet_holding(", 'pm_coil_holding("magnet")')):
        assert body in _lift(src, api)
    arm = _lift(src, "static void coils_arm(void)")
    assert 'pm_port_text("held_coils")' in arm and 't = "magnet";' in arm      # a port without the line: the magnet
    assert "c->id = base + (unsigned)n_coils;" in arm                        # a process id each
    assert "static void (*const coil_procs[COILS_MAX])(void)" in src


def test_the_game_wins_for_every_coil():
    src = RUNTIME.read_text(encoding="utf-8")
    busy = _lift(src, "static int coil_game_busy(")
    assert "c->obj + c->ctl" in busy and "ctl != c->id" in busy              # a process of the game's controls it
    assert "c->ctl = 44;" in _lift(src, "static void coils_arm(void)")       # +44 on Godzilla's ControlCoil
    assert "c->obj + 36" in busy                                              # the game asked for an on-time
    assert "_procs" in busy                                                   # the game's own processes the port names
    assert "coil_game_busy(c)" in _lift(src, "int pm_coil_hold(")
    assert 'coil_let_go(c, "the game wants it")' in _lift(src, "static void magnet_tick(")
    lets = _lift(src, "static void magnet_let_go(")
    assert "for (i = 0; i < n_coils; i++) coil_let_go(&coils[i], why);" in lets   # a mode's end lets all go


def test_an_operator_disabled_coil_is_refused_on_every_route():
    """PAD-420: a coil held by its board address asks its own object whether the operator disabled it (the object's
    "disabled" virtual, `<name>_off_slot`), before any adjustment the port names - as Godzilla's route asks v[40]."""
    src = RUNTIME.read_text(encoding="utf-8")
    dis = _lift(src, "static int coil_disabled(")
    assert "coil_virtual(c->obj, 40)" in dis
    assert dis.index('"%s_off_slot"') < dis.index('"%s_off_adj"') < dis.index('"%s_on_adj"')
    assert "c->obj && (id = pm_port_value(key, 0)) > 0) return (coil_virtual(c->obj, (unsigned)id)" in dis
    assert "coil_disabled(c)" in _lift(src, "int pm_coil_hold(")


def test_a_statically_built_coil_object_is_named_not_built_again():
    """PAD-420: where a static initializer builds the coil's object (Deadpool, Led Zeppelin, Sword of Rage, Star Wars
    ELG), the port names the object (`data <name>_obj`); the runtime never calls that initializer as a getter."""
    src = RUNTIME.read_text(encoding="utf-8")
    ok = _lift(src, "static int coil_device_ok(")
    assert ok.index('"%s_get"') < ok.index('"%s_obj"')
    assert "else if (c->route) {" in ok and "obj = data(key);" in ok
    assert "if (obj && !maps_has(obj, 4, MAP_R)) obj = 0;" in ok


def test_the_interpreter_holds_on_its_shot_or_as_it_starts():
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    assert "if (coil_line(M, line)) return;" in src
    at = _lift(src, "static void coils_at(")
    assert "pm_coil_hold(cfg.coil_name[i], cfg.coil_ms[i])" in at
    assert "coils_at(M, 0);" in _lift(src, "static void mode_start(")
    assert "coils_at(M, mask);" in _lift(src, "static void magnet_shot(")


# ---- the port and the game program -------------------------------------------------------------
def test_the_premium_port_names_its_coils():
    port = MP.read_port(str(LE_PORT))
    assert port["text"]["held_coils"].split() == ["magnet", "mg_magnet", "bridge"]
    assert (port["value"]["mg_magnet_dev"], port["value"]["bridge_dev"]) == (14, 12)
    assert port["text"]["mg_magnet_label"] == "Mechagodzilla magnet"
    pro = MP.read_port(str(SDK / "ports" / "godzilla_pro-1.16.port"))
    assert pro["text"]["held_coils"].split() == ["magnet"]


def _elf():
    for c in LE_ELF:
        if c and os.path.isfile(c):
            return open(c, "rb").read()
    return None


def _word(b, va):
    e = struct.unpack_from("<I", b, 0x1c)[0]
    for i in range(struct.unpack_from("<H", b, 0x2c)[0]):
        t, off, v, _pa, fs = struct.unpack_from("<5I", b, e + 32 * i)
        if t == 1 and v <= va < v + fs:
            return struct.unpack_from("<I", b, va - v + off)[0]
    return None


@pytest.mark.parametrize("name", ["mg_magnet", "bridge"])
def test_the_getter_builds_the_ports_device(name):
    b = _elf()
    if b is None:
        pytest.skip("no Godzilla LE 1.16 game program here")
    port = MP.read_port(str(LE_PORT))
    addr, w0, w1 = port["site"]["%s_get" % name]
    assert (_word(b, addr), _word(b, addr + 4)) == (w0, w1)
    dev = port["value"]["%s_dev" % name]
    # the getter constructs its object with `mov r1, #<device>` before the ControlCoil constructor call
    words = [_word(b, addr + 4 * k) for k in range(64)]
    assert (0xE3A01000 | dev) in words, "the getter does not pass device %d" % dev


# PAD-394: other titles whose ControlCoil is Godzilla's (the same take/give and vtable slots). Each getter must
# build its object with the port's device, and the framework sites must start with the port's words.
OTHER_PORTS = {
    "king_kong_le-0.97": (("spider_magnet", 10), ("log_diverter", 13), ("ramp_diverter", 15)),
    "jaws_le-1.02": (("left_post", 14), ("right_post", 13)),
}
ELVES = [os.environ.get("PAD_ELVES", ""), r"C:\tmp\PAD-363\elves", "/mnt/c/tmp/PAD-363/elves"]


@pytest.mark.parametrize("key", sorted(OTHER_PORTS))
def test_the_other_titles_ports_name_their_coils(key):
    port = MP.read_port(str(SDK / "ports" / (key + ".port")))
    assert port["text"]["held_coils"].split() == [n for n, _d in OTHER_PORTS[key]]
    for name, dev in OTHER_PORTS[key]:
        assert port["value"]["%s_dev" % name] == dev and "%s_get" % name in port["site"]
        assert port["text"]["%s_label" % name]
    for s in ("coil_fire", "proc_exists", "proc_create", "proc_sleep", "coil_take", "coil_give"):
        assert s in port["site"], s
    assert "magnet_get" not in port["site"]                  # no Godzilla magnet: the Magnet part stays greyed


@pytest.mark.parametrize("key", sorted(OTHER_PORTS))
def test_the_other_titles_getters_build_the_ports_devices(key):
    path = next((os.path.join(d, key + ".elf") for d in ELVES if d and os.path.isfile(os.path.join(d, key + ".elf"))),
                None)
    if path is None:
        pytest.skip("no %s game program here" % key)
    b = open(path, "rb").read()
    port = MP.read_port(str(SDK / "ports" / (key + ".port")))
    for name, (addr, w0, w1) in port["site"].items():
        assert (_word(b, addr), _word(b, addr + 4)) == (w0, w1), name
    for name, dev in OTHER_PORTS[key]:
        addr = port["site"]["%s_get" % name][0]
        words = [_word(b, addr + 4 * k) for k in range(64)]
        assert (0xE3A01000 | dev) in words, "%s's getter does not pass device %d" % (name, dev)
    # take control: the controlling process at +44 (ldrh r3, [r0, #0x2c]); give back: it is cleared
    take, give = port["site"]["coil_take"][0], port["site"]["coil_give"][0]
    assert 0xE1D032BC in [_word(b, take + 4 * k) for k in range(12)]
    assert _word(b, give + 16) == 0xE1C052BC


# ---- the app ---------------------------------------------------------------------------------
LE = MP.profile_from_port(str(LE_PORT))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    monkeypatch.setitem(MP.PROFILES, LE.key, LE)


def _spec(**kw):
    spec = MP.blank_spec(LE, name="HELD")
    spec.start_shot, spec.scoring_shots = "Godzilla target", ["Left ramp"]
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def test_the_profile_offers_the_proven_coils():
    assert LE.held_coils == (("mg_magnet", "Mechagodzilla magnet"), ("bridge", "bridge"))
    assert LE.can("coils")
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        build = "%s-%s" % (p.game_dir, p.version)
        proven = any(b == build for b, _c in MP.HELD_COILS_PROVEN)
        assert p.can("coils") == proven, key
        assert all((build, n) in MP.HELD_COILS_PROVEN for n, _l in p.held_coils), key
        if not proven:
            assert p.label in p.why_not("coils"), key


def test_the_lines_are_the_proven_ones():
    spec = _spec(coil_holds=[["mg_magnet", 2000, ""], ["bridge", 2000, "Left ramp"]])
    assert MP.validate(spec) == []
    lines = [l for l in MP.runtime_cfg(spec, "h").splitlines() if l.startswith("coil_hold")]
    assert lines == ["coil_hold      mg_magnet 2000", "coil_hold      bridge 2000 0x00100000"]


@pytest.mark.parametrize("row, problem", [
    (["shield", 2000, ""], "has no mechanism called 'shield'"),
    (["bridge", 5001, ""], "The bridge holds 0.1 to 5 seconds."),
    (["mg_magnet", 50, ""], "The Mechagodzilla magnet holds 0.1 to 5 seconds."),
    (["bridge", 2000, "Nowhere"], "has no shot called 'Nowhere' to hold the bridge on."),
])
def test_validate_names_each_problem(row, problem):
    problems = MP.validate(_spec(coil_holds=[row]))
    assert any(problem in x for x in problems), problems
    from pinball_decryptor.webui.tabs.modes import problem_pages
    assert problem_pages(problems) == ["mode"] * len(problems)


def test_the_field_round_trips(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    rows = [["bridge", 1500, "Left ramp"]]
    slug, _ = MP.new_mode(str(project), spec=MP.ModeSpec(name="HELD", coil_holds=rows))
    assert MP.load(str(project / "modes" / slug / "mode.json")).coil_holds == rows


def test_the_docs_name_the_key_and_the_calls():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("coil_hold", "coil_holds", "pm_coil_hold"):
        assert re.search(r"`%s(?:[ (][^`]*)?`" % re.escape(name), doc), name
    assert "## Held coils (PAD-381)" in (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
