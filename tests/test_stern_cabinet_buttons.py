"""PAD-1403: the cabinet buttons as shots on every Spike 2 build - the Action, flipper and Start buttons' presses,
releases and holds and the flipper + Action combos (cabinet_buttons.py, buttons.cfg, pad_mode_runtime.c "PAD-1403").
Desk parts; the emulator proof is recorded in ``mode_project.BUTTON_SHOTS_PROVEN``."""

import pathlib

import pytest

from pinball_decryptor.plugins.stern import cabinet_buttons as CB
from pinball_decryptor.plugins.stern import mode_project as MP
from tests.test_spike2_mode_roster import _host_run, _lift

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"
PORTS = sorted((SDK / "ports").glob("*.port"))
RUNTIME = SDK / "pad_mode_runtime.c"


def _port_bits(port):
    used = 1
    for _n, m in port["shot"]:
        used |= m
    for _sw, m, _n in port.get("switch", ()):
        used |= m
    return used


# ---- the profiles ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", PORTS, ids=lambda p: p.stem)
def test_every_port_offers_button_shots_on_bits_of_their_own(path):
    port = MP.read_port(str(path))
    p = MP.profile_from_port(str(path))
    shots = dict(p.shots)
    assert p.button_shots, "no button shots on %s" % path.stem
    used, seen = _port_bits(port), 0
    for name in p.button_shots:
        m = shots[name]
        assert m and not m & (m - 1), name                      # one bit
        assert not m & used, "%s shares a bit with the port's own shot" % name
        assert not m & seen, "%s shares a bit with another button shot" % name
        seen |= m
    # the order is the table's: a port short of bits drops the end of it, never the presses
    order = [n for n in CB.NAMES if n in p.button_shots]
    assert list(p.button_shots) == order
    assert not set(p.button_shots) & set(MP.playfield_shots(p))


def test_king_kong_gets_the_first_nine_and_x_men_all_eighteen():
    kk = MP.profile_from_port(str(SDK / "ports" / "king_kong_le-0.97.port"))
    assert list(kk.button_shots) == list(CB.NAMES[:9])
    xm = MP.profile_from_port(str(SDK / "ports" / "uncanny_xmen_le-0.98.port"))
    assert list(xm.button_shots) == list(CB.NAMES)
    assert "Left flipper + Action button" in xm.button_shots


@pytest.mark.parametrize("name", ["beatles-1.29", "jurassic_park_the_pin-1.05", "star_wars_elg-1.10"])
def test_titles_without_an_action_button_offer_none_of_its_shots(name):
    p = MP.profile_from_port(str(SDK / "ports" / (name + ".port")))
    assert not any("action" in CB.buttons_of(n) for n in p.button_shots)
    assert {"Left flipper button", "Right flipper button", "Start button", "Both flipper buttons"} <= set(p.button_shots)


def test_godzilla_keeps_its_switch_line_presses_and_gets_the_rest():
    p = MP.profile_from_port(str(SDK / "ports" / "godzilla_pro-1.15.port"))
    assert {"Action button", "Left flipper button", "Right flipper button"} <= set(p.switch_shots)
    assert not {"Action button", "Left flipper button", "Right flipper button"} & set(p.button_shots)
    assert "Start button" in p.button_shots and "Left flipper + Action button" in p.button_shots
    assert dict(MP.GODZILLA_PRO_1_15.shots) == dict(p.shots)
    assert MP.GODZILLA_PRO_1_15.button_shots == p.button_shots


def test_a_spike3_port_gets_none():
    shots, names = CB.with_button_shots([("Ramp", 2)], "uncanny_xmen_le", arch="a64")
    assert names == () and shots == (("Ramp", 2),)


def test_bits_run_out_cleanly():
    full = [("s%d" % b, 1 << b) for b in range(1, 62)]          # bits 62 and 63 free
    shots, names = CB.with_button_shots(full, "x")
    assert names == CB.NAMES[:2]
    assert dict(shots)["Action button"] == 1 << 63 and dict(shots)["Left flipper button"] == 1 << 62


# ---- buttons.cfg ------------------------------------------------------------------------------------------------
def test_cfg_lines_use_the_programs_ids_and_name_what_it_lacks():
    shots = [("Action button", 1 << 63), ("Left flipper + Action button", 1 << 59),
             ("Right flipper button held 3 s", 1 << 48), ("Start button released", 1 << 46), ("Ramp", 2)]
    lines, missing = CB.cfg_lines(shots, {"left": 68, "right": 67, "start": 36})
    assert lines == ["button 0x0001000000000000 hold 67 3000 Right flipper button held 3 s",
                     "button 0x0000400000000000 release 36 Start button released"]
    assert missing == ["Action button", "Left flipper + Action button"]
    lines, missing = CB.cfg_lines(shots, {"left": 68, "right": 67, "start": 36, "action": 34})
    assert "button 0x0800000000000000 combo 68 34 Left flipper + Action button" in lines and not missing


def test_buttons_into_writes_the_cfg_and_refuses_a_used_button_the_card_lacks(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW
    p = MP.profile_from_port(str(SDK / "ports" / "uncanny_xmen_le-0.98.port"))

    class R:
        lines = []
        buttons_file = ""

    class Spec:
        def __init__(self, shot):
            self.start_shots = [shot]

    monkeypatch.setattr(CB, "switch_ids", lambda elf: {"left": 68, "right": 67, "start": 36, "action": 34})
    r = MW.buttons_into(R(), b"", str(tmp_path), p, [("m", Spec("Action button held 1 s"))])
    text = (tmp_path / CB.CFG_NAME).read_text()
    assert r.buttons_file and text.count("\nbutton ") == 18
    assert "button 0x0200000000000000 hold 34 1000 Action button held 1 s" in text
    monkeypatch.setattr(CB, "switch_ids", lambda elf: {"left": 68, "right": 67, "start": 36})
    with pytest.raises(MW.ModeWriteError, match="no the action button"):
        MW.buttons_into(R(), b"", str(tmp_path), p, [("m", Spec("Left flipper + Action button"))])
    r = MW.buttons_into(R(), b"", str(tmp_path), p, [("m", Spec("Left flipper button"))])   # unused: just left out
    assert "Action" not in (tmp_path / CB.CFG_NAME).read_text().split("\n", 1)[1]


def test_the_installers_carry_buttons_cfg():
    tryit = (REPO / "tools" / "spike2_emu" / "modes" / "tryit.sh").read_text(encoding="utf-8")
    assert 'put "$S/buttons.cfg" "$DUMP/buttons.cfg"' in tryit
    assert tryit.count('"$DUMP"/buttons.cfg') == 2
    assert '"$DUMP/buttons.cfg"' in (REPO / "tools" / "spike2_emu" / "modes" / "cardmodes.sh").read_text(encoding="utf-8")
    import importlib.util
    spec = importlib.util.spec_from_file_location("mi", REPO / "tools" / "spike2_emu" / "mode_install.py")
    mi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mi)
    assert ("buttons.cfg", 0o100644) in mi.EXTRA_FILES and "buttons.cfg" not in mi.STANDALONE_FILES


# ---- the runtime ------------------------------------------------------------------------------------------------
def _due_harness(tmp_path, script):
    src = RUNTIME.read_text(encoding="utf-8")
    due = _lift(src, "static int btn_due(")
    return _host_run(tmp_path, "#include <stdio.h>\nenum { BTN_PRESS = 1, BTN_RELEASE, BTN_HOLD, BTN_COMBO };\n"
                     + due + "\nint main(void) {\n unsigned long d = 0; int f = 0;\n" + script + "\n return 0; }\n")


def test_a_hold_fires_once_after_its_time_even_on_an_even_millisecond(tmp_path):
    """The press time was kept as `now | 1`: on an even millisecond one past now, the difference wrapped and the hold
    fired at the press (X-Men Pro, the emulator: "held 1 s" and "held 3 s" with the press)."""
    out = _due_harness(tmp_path, "\n".join([
        ' printf("%d", btn_due(BTN_HOLD, 1, 0, 1, 0, 0, 52272, 1000, &d, &f));',    # the press, even ms
        ' printf("%d", btn_due(BTN_HOLD, 0, 0, 1, 0, 0, 52280, 1000, &d, &f));',
        ' printf("%d", btn_due(BTN_HOLD, 0, 0, 1, 0, 0, 53271, 1000, &d, &f));',
        ' printf("%d", btn_due(BTN_HOLD, 0, 0, 1, 0, 0, 53272, 1000, &d, &f));',    # 1 s
        ' printf("%d", btn_due(BTN_HOLD, 0, 0, 1, 0, 0, 59000, 1000, &d, &f));',    # once
        ' printf("%d", btn_due(BTN_HOLD, 0, 1, 0, 0, 0, 59100, 1000, &d, &f));',    # released
        ' printf("%d", btn_due(BTN_HOLD, 1, 0, 1, 0, 0, 60000, 1000, &d, &f));',    # pressed again: its own clock
        ' printf("%d", btn_due(BTN_HOLD, 0, 0, 1, 0, 0, 61000, 1000, &d, &f));']))
    assert out == "00010001"


def test_press_release_and_combo_either_order(tmp_path):
    out = _due_harness(tmp_path, "\n".join([
        ' printf("%d", btn_due(BTN_PRESS, 1, 0, 1, 0, 0, 1, 0, &d, &f));',
        ' printf("%d", btn_due(BTN_PRESS, 0, 1, 0, 0, 0, 1, 0, &d, &f));',
        ' printf("%d", btn_due(BTN_RELEASE, 0, 1, 0, 0, 0, 1, 0, &d, &f));',
        ' printf("%d", btn_due(BTN_COMBO, 1, 0, 1, 0, 1, 1, 0, &d, &f));',     # flipper held, Action pressed
        ' printf("%d", btn_due(BTN_COMBO, 0, 0, 1, 1, 1, 1, 0, &d, &f));',     # Action held, flipper pressed
        ' printf("%d", btn_due(BTN_COMBO, 1, 0, 1, 0, 0, 1, 0, &d, &f));']))   # alone
    assert out == "101110"


def test_the_runtime_counts_only_presses_in_a_game_and_their_releases():
    src = RUNTIME.read_text(encoding="utf-8")
    edge = _lift(src, "static void btn_edge(unsigned id, unsigned level, unsigned polarity)\n{")
    assert "pm_in_game()" in edge and "btn_down[id]" in edge
    assert src.count("if (n_btn) btn_edge(id, level, pol);") == 2          # both drain hooks (Spike 2, Spike 3)
    assert "    switches_deliver();\n    btn_tick();" in src and "    switches_arm();" in src and "    buttons_arm();" in src
    assert '"/usr/local/padmode/buttons.cfg", "/dump/buttons.cfg"' in src
