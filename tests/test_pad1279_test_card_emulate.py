"""PAD-1279: a PAD test card through the Emulate path, and its screen on the glass.

DragonRR extracted a test card and pressed Emulate: the rig looked for a game ELF on it
("mounted, but no directory in it holds a game ELF") and gave up, because a test card has
no game - only the boot selector's TEST CARD menu. And once the rig ran that menu it drew
nothing at all: the selector's test card branch went into the settings loop before the
screen texture existed, so every frame was uploaded into no texture - on the machine too.
Proven in the emulator (hidden rig, menu walked by the cabinet buttons); these tests pin
the pieces in place.
"""
import importlib.util
import pathlib
import re

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu"


@pytest.fixture(scope="module")
def parts():
    spec = importlib.util.spec_from_file_location("parts_pad1279", RIG / "parts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TESTCARD_CONF = (
    "image=/dev/mmcblk0p3|TEST CARD|color profile test card||\n"
    "color_profile=0|1.00 1.00 1.00|1.00 1.00 1.00|0.00 0.00 0.00|1.00|As built\n"
    "testcard=on\n"
    "test_dir=/games/testcard\n"
    "test_image=test0.png|Gradient\n"
)


def test_a_testcard_line_is_read_the_way_the_selector_reads_it(parts):
    assert parts.images_conf_testcard(TESTCARD_CONF)
    assert parts.images_conf_testcard("  testcard = on \n")
    assert not parts.images_conf_testcard("# testcard=on\n")
    assert not parts.images_conf_testcard("testcard=off\n")
    assert not parts.images_conf_testcard("image=/dev/mmcblk0p3|A|\nimage=/dev/mmcblk0p7|B|\n")
    assert not parts.images_conf_testcard(None)


def test_a_test_card_is_a_menu_although_it_names_one_image(parts, monkeypatch):
    monkeypatch.setattr(parts, "identify", lambda path: {"rootfs": 4096})
    monkeypatch.setattr(parts, "_ls", lambda path, off, d=None: ["codeselect", "images.conf"])
    monkeypatch.setattr(parts, "_cat", lambda path, off, f: TESTCARD_CONF)
    state, why, n = parts.multiboot("card.raw")
    assert state == "yes" and "test card" in why and n == 1
    # ...and the same card without the line is still the one-tree "no" it always was
    monkeypatch.setattr(parts, "_cat", lambda path, off, f: TESTCARD_CONF.replace("testcard=on\n", ""))
    assert parts.multiboot("card.raw")[0] == "no"


def test_the_selector_makes_its_screen_texture_before_the_test_card_loop():
    src = (RIG / "codeselect" / "codeselect.c").read_text(encoding="utf-8")
    branch = src[src.index("if (c.testcard) {"):]
    branch = branch[:branch.index("goto testcard_done;")]
    tex = branch.find("egl_stern_texture(")
    loop = branch.find("settings_run(&se)")
    assert tex != -1, "the test card branch never creates the screen texture: a black glass"
    assert tex < loop


def test_the_rig_runs_a_test_card_as_its_menu():
    watch = (RIG / "watch.sh").read_text(encoding="utf-8")
    assert re.search(r'parts\.py" --testcard "\$PAD_CARD"', watch)
    assert "export PAD_TESTCARD PAD_SELECT" in watch
    mount = (RIG / "cardmount.sh").read_text(encoding="utf-8")
    assert '[ -d "$m/testcard" ]' in mount and "testcard_none" in mount
    run = (RIG / "run_game.sh").read_text(encoding="utf-8")
    tc = run[run.index("sel_testcard() {"):]
    tc = tc[:tc.index("\n}\n")]
    assert ('if [ -z "$SEL_GIVEUP" ] && [ "${PAD_TESTCARD:-}" = 1 ]; then\n'
            '            sel_testcard') in run
    # the card's own conf, verbatim but for its rootfs paths, and its media
    assert "--rootfs-file /usr/local/codeselect/images.conf" in tc
    assert "(media|font)" in tc and "--rootfs-dir /usr/local/codeselect/media" in tc
    # ...and a test card never falls back to booting a game that is not there
    assert 'a test card boots no game' in run
