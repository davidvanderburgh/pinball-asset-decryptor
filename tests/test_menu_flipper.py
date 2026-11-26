"""The right flipper back to the boot menu (Simon, 2026-11-22).

Simon: "1. Multiboot menu alone 2. Multiboot menu plus facility to reinvoke the flippers 3. No menu appears,
available only through flippers", then "This should not run during gameplay at all. Just when no game is running"
and "Right flipper held on - 5 seconds for activation."  The Multi-boot tab's Menu settings carry it as Boot menu
(images.conf boot_menu=menu|flipper|hidden) and After a game (flip_guard=, 20 or 60 s: a tilt, the bonus and the
initials switch the flippers off too).  padmenu.so reads the game's node bus for the flipper and the flipper rules
(tools/spike2_emu/codeselect/test/padmenu_flip_test.sh, under qemu); this file pins the card's side: the builder's
keys, the tab's command lines, its state and its preview.
"""
import argparse
import os
import sys

import pytest

from pinball_decryptor.webui import multiboot_core
from pinball_decryptor.webui.multiboot_core import (ImageRow, MultibootForm, build_args, inject_args,
                                                    menu_from_state, write_preview_conf)

RIG = os.path.join(os.path.dirname(__file__), os.pardir, "tools", "spike2_emu")
SEL = os.path.join(RIG, "codeselect")


@pytest.fixture
def mk():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard
    return mkmulticard


def _form(tmp_path, n=2, **kw):
    rows = []
    for i in range(n):
        p = tmp_path / ("img%d.raw" % i)
        p.write_bytes(b"\0" * 512)
        rows.append(ImageRow(path=str(p), title="IMG %d" % i))
    form = MultibootForm(images=rows, out=str(tmp_path / "multi" / "card.multi.raw"))
    for k, v in kw.items():
        setattr(form, k, v)
    return form


def test_the_card_carries_boot_menu_and_flip_guard_only_when_asked(mk):
    devs = ["/dev/mmcblk0p3", "/dev/mmcblk0p7"]
    plain = mk.render_images_conf(devs, ["A", "B"])
    assert not [ln for ln in plain.splitlines() if ln.startswith(("boot_menu", "flip_guard"))]
    conf = mk.parse_images_conf(plain)
    assert conf["boot_menu"] is None and conf["flip_guard"] is None
    text = mk.render_images_conf(devs, ["A", "B"], back_hold=3, boot_menu="hidden", flip_guard=20)
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert lines.index("boot_menu=hidden") == lines.index("back_hold=3") + 1
    assert "flip_guard=20" in lines
    back = mk.parse_images_conf(text)
    assert back["boot_menu"] == "hidden" and back["flip_guard"] == 20
    # the like-for-like render the update path uses keeps both
    again = mk.render_images_conf_text(back).splitlines()
    assert "boot_menu=hidden" in again and "flip_guard=20" in again
    with pytest.raises(mk.Refused, match="boot_menu"):
        mk.render_images_conf(devs, ["A", "B"], boot_menu="sometimes")
    with pytest.raises(mk.Refused, match="flip_guard"):
        mk.render_images_conf(devs, ["A", "B"], flip_guard=601)
    # a word the selector does not know reads as 'menu', as the selector reads it
    assert mk.parse_images_conf(plain + "boot_menu=sometimes\n")["boot_menu"] == "menu"


def test_the_flags_and_an_inject_keep_the_cards_own(mk):
    ap = argparse.ArgumentParser()
    mk._add_conf_flags(ap)
    assert ap.parse_args([]).boot_menu is None and ap.parse_args([]).flip_guard is None
    a = ap.parse_args(["--boot-menu", "flipper", "--flip-guard", "60"])
    assert (a.boot_menu, a.flip_guard) == ("flipper", 60)
    with pytest.raises(SystemExit):
        ap.parse_args(["--boot-menu", "often"])


def test_the_tab_spells_both_out_on_every_spike2_command_line(tmp_path):
    form = _form(tmp_path)
    assert (form.boot_menu, form.flip_guard) == ("menu", 60)
    for argv in (build_args(form), inject_args(form, form.out), multiboot_core.update_args(form, form.out)):
        # always spelled out: the tool keeps a card's own value for a flag left off, so a card switched back
        # to 'menu' must say so
        assert argv[argv.index("--boot-menu") + 1] == "menu"
        assert argv[argv.index("--flip-guard") + 1] == "60"
    form.boot_menu, form.flip_guard = "flipper", 20
    argv = build_args(form)
    assert argv[argv.index("--boot-menu") + 1] == "flipper" and argv[argv.index("--flip-guard") + 1] == "20"


def test_the_tab_refuses_what_the_card_cannot_take(tmp_path):
    form = _form(tmp_path, boot_menu="sometimes")
    assert any("Boot menu" in e for e in multiboot_core.validate_form(form, sources=False))
    form = _form(tmp_path, boot_menu="flipper", flip_guard=45)
    assert any("After a game" in e for e in multiboot_core.validate_form(form, sources=False))
    form = _form(tmp_path, boot_menu="hidden", flip_guard=20)
    assert not [e for e in multiboot_core.validate_form(form, sources=False) if "Boot menu" in e or "After a game" in e]


def test_the_saved_state_and_the_preview(tmp_path):
    assert menu_from_state({})["boot_menu"] == "menu" and menu_from_state({})["flip_guard"] == 60
    got = menu_from_state({"boot_menu": "hidden", "flip_guard": 20})
    assert (got["boot_menu"], got["flip_guard"]) == ("hidden", 20)
    bad = menu_from_state({"boot_menu": "x", "flip_guard": 7})
    assert (bad["boot_menu"], bad["flip_guard"]) == ("menu", 60)
    # the menu names the ways back that are on (BACK, the right flipper, both), so the preview carries both keys
    plain = write_preview_conf(_form(tmp_path)).splitlines()
    assert "back_hold=3" in plain and "boot_menu=menu" in plain
    assert "boot_menu=flipper" in write_preview_conf(_form(tmp_path, boot_menu="flipper")).splitlines()
    assert "back_hold=0" in write_preview_conf(_form(tmp_path, back_hold=0)).splitlines()


def test_the_flipper_keys_are_a_stern_cards_alone(tmp_path, monkeypatch):
    """PR #48 review: other makers' cards are as they were - no boot_menu=, so no new line on their menus."""
    import pinball_decryptor.webui.multiboot_core as core
    assert core.flip_args(_form(tmp_path, boot_menu="flipper"))[:2] == ["--boot-menu", "flipper"]
    monkeypatch.setattr(core, "backend_for", lambda f: type("B", (), {"key": "spk"})())
    assert core.flip_args(_form(tmp_path)) == []


def test_the_menu_names_each_way_back():
    """PR #48 review (David: "choose either or and label them on the multiboot menu as such"): the selector reads
    back_hold= too and says BACK, the right flipper or both; the dialog offers the four ways as one choice."""
    conf_c = open(os.path.join(SEL, "conf.c"), encoding="utf-8").read()
    assert '"back_hold"' in conf_c and "boot_menu_set = 1" in conf_c
    cs = open(os.path.join(SEL, "codeselect.c"), encoding="utf-8").read()
    for words in ('hold the coin door BACK button %d s during a "', 'or the right flipper %d s when no game is running',
                  'BACK button %d s during a game",', 'hold the right flipper %d s when no game is running",'):
        assert words in cs
    js = open(os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js", "tabs",
                           "multiboot.js"), encoding="utf-8").read()
    for value in ('"back"', '"flipper"', '"both"', '"off"'):
        assert "value: %s" % value in js
    assert "Back to this menu:" in js


def test_the_menu_and_the_watcher_read_the_same_keys():
    conf_c = open(os.path.join(SEL, "conf.c"), encoding="utf-8").read()
    for key in ('"boot_menu"', '"flip_hold"', '"flip_guard"', '"flipper"', '"hidden"'):
        assert key in conf_c
    pm = open(os.path.join(SEL, "padmenu.c"), encoding="utf-8").read()
    for key in ('"boot_menu"', '"flip_hold"', '"flip_guard"', '"flipper"', '"hidden"'):
        assert key in pm
    cs = open(os.path.join(SEL, "codeselect.c"), encoding="utf-8").read()
    assert "BOOT_MENU_HIDDEN" in cs and "input_held(in, EV_RIGHT)" in cs
    assert "padmenu_flip_test.sh" in open(os.path.join(SEL, "Makefile"), encoding="utf-8").read()


def test_a_loaded_cards_flipper_change_is_a_change():
    """Found 2026-11-26: a loaded card whose Boot menu or After a game changed said "No change pending" - the names
    were not in MENU_FIELD_ORDER, which diff_forms filters by."""
    import dataclasses
    from pinball_decryptor.webui import multiboot_core as mbc
    assert "boot menu" in mbc.MENU_FIELD_ORDER and "after a game" in mbc.MENU_FIELD_ORDER
    before = mbc.MultibootForm(images=[], out="x.raw")
    menu, _ = mbc.diff_forms(before, dataclasses.replace(before, boot_menu="flipper"))
    assert "boot menu" in menu
    menu, _ = mbc.diff_forms(before, dataclasses.replace(before, flip_guard=20))
    assert "after a game" in menu
