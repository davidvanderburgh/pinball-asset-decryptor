"""The TEST CARD entry on a game card (Simon, 2026-11-23).

Simon: "Make me a 1.16 vanilla plus the test card, make it default to the test card on first boot. but
show the menu."  mkmulticard --test-entry adds `image=testcard|TEST CARD|...` as the menu's last image line:
it opens the test card screens and boots nothing (codeselect conf.h; driven under qemu by
tools/spike2_emu/codeselect/test/testcard_entry_test.py).  Its files go in /games/padtest on the primary's
games partition.  This file pins the card's side: the line, the parse that keeps it apart from the games,
default= naming it, and the flags.
"""
import argparse
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(__file__), os.pardir, "tools", "spike2_emu")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def mk():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard
    return mkmulticard


DEVS = ["/dev/mmcblk0p3"]


def test_the_entry_is_the_last_image_line_and_default_may_name_it(mk):
    text = mk.render_images_conf(DEVS, ["Godzilla 1.16"], default=1,
                                 test_entry=("TEST CARD", "test pictures"), test_dir="/games/padtest")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    imgs = [ln for ln in lines if ln.startswith("image=")]
    assert imgs == ["image=/dev/mmcblk0p3|Godzilla 1.16|", "image=testcard|TEST CARD|test pictures"]
    assert "default=1" in lines and "test_dir=/games/padtest" in lines
    # without the entry, default=1 is no image of a one-image card
    with pytest.raises(mk.Refused, match="default=1"):
        mk.render_images_conf(DEVS, ["Godzilla 1.16"], default=1)


def test_the_parse_keeps_the_entry_apart_from_the_games(mk):
    text = mk.render_images_conf(DEVS + ["/dev/mmcblk0p7"], ["A", "B"], default=2,
                                 test_entry=("TEST CARD", ""), test_dir="/games/padtest")
    conf = mk.parse_images_conf(text)
    assert [d for (d, _t, _s) in conf["images"]] == DEVS + ["/dev/mmcblk0p7"]
    assert len(conf["media"]) == 2
    assert conf["test_entry"] == ("TEST CARD", "")
    assert conf["default"] == 2
    # the like-for-like render the update path uses gives the same text back
    assert mk.render_images_conf_text(conf) == text
    plain = mk.parse_images_conf(mk.render_images_conf(DEVS, ["A"]))
    assert plain["test_entry"] is None


def test_a_title_with_a_bar_is_refused(mk):
    with pytest.raises(mk.Refused, match="TEST CARD entry"):
        mk.render_images_conf(DEVS, ["A"], test_entry=("TEST|CARD", ""))


class _Plan:
    trees = [("p3", None)]

    def devices(self):
        return list(DEVS)


def _args(**kw):
    base = dict(conf=None, titles="Godzilla 1.16", subtitles=None, default=None, timeout=None,
                selector_dir=None, test_entry=False, no_test_entry=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_the_flags_add_keep_and_take_off_the_entry(mk):
    on = mk.conf_for_plan(_Plan(), _args(test_entry=True, default=1))
    assert "image=testcard|TEST CARD|%s" % mk.TEST_ENTRY_SUBTITLE in on
    assert "test_dir=/games/padtest" in on
    ex = mk.parse_images_conf(on)
    kept = mk.conf_for_plan(_Plan(), _args(), existing=ex)
    assert "image=testcard|" in kept and "default=1" in kept
    off = mk.conf_for_plan(_Plan(), _args(no_test_entry=True, default=0), existing=ex)
    assert "image=testcard|" not in off and "test_dir=" not in off



# ---- the Multi-boot tab (Simon, 2026-11-26: "Start the TEST CARD entry") ----------------------------------------
def test_the_multi_boot_form_asks_the_tools_for_it():
    import types
    from pinball_decryptor.webui import multiboot_core as mbc
    on = types.SimpleNamespace(boot_menu="menu", flip_guard=60, test_entry=True,
                               test_specs=("--test", "/tmp/a.png|A", "--test", "/tmp/b.mp4|B"))
    off = types.SimpleNamespace(boot_menu="menu", flip_guard=60, test_entry=False, test_specs=())
    assert mbc.flip_args(on)[-1] == "--test-entry" and mbc.flip_args(off)[-1] == "--no-test-entry"
    src = __import__("inspect").getsource(mbc.prepare_args)
    assert 'args += list(getattr(form, "test_specs", ()) or ())' in src
    wants = __import__("inspect").getsource(mbc.form_wants_media)
    assert 'getattr(form, "test_entry", False) and getattr(form, "test_specs", ())' in wants
    assert mbc.MultibootForm.__dataclass_fields__["test_entry"].default is False


def test_the_panel_stages_the_test_card_list_before_the_write():
    import inspect
    from pinball_decryptor.webui import multiboot_core as mbc
    go = inspect.getsource(mbc.MultibootPanel._do_build_flash)
    assert 'return self._stage_test_entry(lambda: self._do_build_flash(do_write, do_flash))' in go
    assert go.index("_stage_test_entry") < go.index('self._write_plan()["action"]')
    st = inspect.getsource(mbc.MultibootPanel._stage_test_entry)
    assert "tc.shared().items" in st and "tc.stage(items, folder, None, log=log, clips=True)" in st
    assert "tc.test_specs(staged, wsl)" in st and "self._kick_drain()" in st
    assert 'getattr(self, "_stage_busy", False)' in inspect.getsource(mbc.MultibootPanel._drain)


def test_a_loaded_card_shows_its_entry():
    src = open(os.path.join(ROOT, "tools", "spike2_emu", "mkmulticard.py"), encoding="utf-8").read()
    assert '("test_entry", bool(conf.get("test_entry"))),' in src
    from pinball_decryptor.webui import multiboot_core as mbc
    assert "test_entry=bool(info.get(\"test_entry\"))," in __import__("inspect").getsource(mbc)


def test_menu_settings_offer_it_on_spike_2():
    js = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "multiboot.js"),
              encoding="utf-8").read()
    assert '${w.test_entry ? html`<${Box} legend="Test card">' in js
    assert 'k="test_entry" checked=${s.test_entry}' in js
    panel = open(os.path.join(ROOT, "pinball_decryptor", "webui", "multiboot_panel.py"), encoding="utf-8").read()
    assert '"test_entry": be.key == "stern",' in panel
    tab = open(os.path.join(ROOT, "pinball_decryptor", "webui", "tabs", "multiboot.py"), encoding="utf-8").read()
    assert '("test_entry", "_test_entry_var")' in tab


def test_the_entry_is_a_change_and_always_remakes_the_media():
    """The first real update in place (2026-11-26) said "no menu change" and put the entry on with no files."""
    import dataclasses
    from pinball_decryptor.webui import multiboot_core as mbc
    before = mbc.MultibootForm(images=[], out="x.raw")
    after = dataclasses.replace(before, test_entry=True)
    assert "TEST CARD entry" in mbc.diff_forms(before, after)[0]
    assert mbc.media_specs_changed(before, after) is True
    assert mbc.media_specs_changed(after, after) is True, "the Test card tab's list may have changed since"
    assert mbc.media_specs_changed(before, before) is False


# ---- PR #49 review (PAD-1615): the entry's files through update, and taken off with the entry -------------------
def test_the_entry_is_on_when_asked_kept_when_not_and_off_when_taken_off(mk):
    A = argparse.Namespace
    assert mk.test_entry_wanted(A(test_entry=True, no_test_entry=False), {}) is True
    assert mk.test_entry_wanted(A(test_entry=False, no_test_entry=False), {"test_entry": ("TEST CARD", "")}) is True
    assert mk.test_entry_wanted(A(test_entry=False, no_test_entry=False), {"test_entry": None}) is False
    assert mk.test_entry_wanted(A(test_entry=False, no_test_entry=True), {"test_entry": ("TEST CARD", "")}) is False
    assert mk.test_entry_wanted(A(), None) is False


def test_a_games_tree_walk_leaves_the_entrys_folder_out_at_the_root_only(mk):
    class P:
        layout = "parts"
        store_subdirs = ()
    assert mk.TEST_ENTRY_SUBDIR in mk.tree_skip(P(), "")
    assert mk.TEST_ENTRY_SUBDIR not in mk.tree_skip(P(), "img1")
    P.layout = "store"
    assert mk.TEST_ENTRY_SUBDIR in mk.tree_skip(P(), "")


def _fake_p3(mk, monkeypatch, have, free=1 << 30):
    script = []
    monkeypatch.setattr(mk, "need_tools", lambda *a: None)
    monkeypatch.setattr(mk, "_test_entry_dir", lambda card: ("ref", free, None if have is None else dict(have)))
    monkeypatch.setattr(mk, "debugfs_write_script", lambda ref, cmds: script.extend(cmds))
    monkeypatch.setattr(mk, "e2fsck", lambda ref: (0, ""))
    return script


def test_the_entrys_files_replace_what_the_folder_held(mk, monkeypatch, tmp_path):
    src = tmp_path / "t2.png"
    src.write_bytes(b"x" * 10)
    script = _fake_p3(mk, monkeypatch, {"t1.png": 5, "s1.wav": 5})
    mk.put_test_entry_files("card.img", {"t2.png": str(src)})
    assert script[:2] == ['rm "/padtest/s1.wav"', 'rm "/padtest/t1.png"']
    assert not any(c.startswith("mkdir") for c in script)
    assert any(c.startswith("write ") and c.endswith('"/padtest/t2.png"') for c in script)


def test_the_entry_taken_off_empties_its_folder_and_makes_none(mk, monkeypatch):
    script = _fake_p3(mk, monkeypatch, {"t1.png": 5})
    mk.put_test_entry_files("card.img", {})
    assert script == ['rm "/padtest/t1.png"']
    script = _fake_p3(mk, monkeypatch, None)
    mk.put_test_entry_files("card.img", {})
    assert script == []                                 # no folder, nothing to take off: p3 untouched


def test_the_room_counts_what_the_folder_gives_back(mk, monkeypatch, tmp_path):
    src = tmp_path / "big.padv"
    src.write_bytes(b"x" * 1000)
    head = mk.TEST_ENTRY_HEADROOM
    _fake_p3(mk, monkeypatch, {"old.padv": 1000}, free=head)
    mk.check_test_entry_room("card.img", {"big.padv": str(src)})          # the old file's room comes back
    _fake_p3(mk, monkeypatch, {}, free=head)
    with pytest.raises(mk.Refused, match="games partition has"):
        mk.check_test_entry_room("card.img", {"big.padv": str(src)})


def test_update_sets_the_entrys_files_apart_and_checks_their_room_first(mk):
    import inspect
    src = inspect.getsource(mk._update_locked)
    assert src.count("tests_apart=entry_on") == 2      # the plan and the inject both
    assert src.index("check_test_entry_room(") < src.index("# ---- execute")
    assert "put_test_entry_files(card, {})" in src     # taken off: its files go with it
