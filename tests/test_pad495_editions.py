"""PAD-495 (a tester's request): EDITION, the setting that picks which edition of the game boots.

A multi-boot card's images are editions of one game; each edition's Write puts EDITION in the
operator menu (Attract Mode, beside the game's own BOOT SCREEN and 70TH BOOT SCREEN) and the
card's boot program reads it off the NVM mirror at power-up. These tests pin the setting on the
real Godzilla 1.16 programs where the cards are on this machine (skipped elsewhere, as on CI),
next to PAD-494's MUSIC MODE: both go into one program with ONE category table, and a program
reads back which editions it was built for."""

import hashlib
import os

import pytest

from pinball_decryptor.plugins.stern import editions as Ed
from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable, menu_label

CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")
PRO116 = os.path.join(CARDS, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
MODES = ["Standard", "Orchestral", "Heisei"]
EDITIONS = ["Standard", "70th Anniversary"]


# ---- the project's names ---------------------------------------------------------------------
def test_names_are_cleaned_and_a_single_name_is_no_editions():
    assert Ed.clean({"names": ["  Standard ", "", "70th   Anniversary", "", ""]}) == \
        ["Standard", "Edition 2", "70th Anniversary"]
    assert Ed.clean({"names": ["A"] * 12}) == ["A"] * Ed.MAX_EDITIONS
    assert Ed.clean(None) == [] and Ed.clean({"names": "Standard"}) == []
    assert Ed.count(["Standard"]) == 0 and Ed.count(EDITIONS) == 2
    assert Ed.to_json(["", ""]) is None
    assert Ed.to_json(EDITIONS) == {"names": EDITIONS}


def test_the_store_key_is_the_sha1_of_the_caption_the_machine_shows():
    assert Ed.CAPTION == "EDITION"
    assert Ed.NVM_KEY == hashlib.sha1(b"EDITION").hexdigest()


def test_a_project_s_editions_come_from_its_sidecar(tmp_path):
    from pinball_decryptor.core import staged_changes
    assert Ed.load(str(tmp_path)) == []
    staged_changes.save(str(tmp_path), {Ed.STAGED_KEY: {"names": EDITIONS}})
    assert Ed.load(str(tmp_path)) == EDITIONS


# ---- the real game programs (David's machine) ------------------------------------------------
def _program(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        return img.preview(part, "/%s/game" % game, cap=256 << 20)


def _built(raw, tmp, wanted):
    """*raw* with the settings in it the way a Write puts them (engine._MenuJobs)."""
    from pinball_decryptor.plugins.stern import engine as E
    jobs = []
    for key, values, names in wanted:
        cls = E._EditionMenu if key == MS.EDITION else E._MusicModeMenu
        jobs.append(cls(values, names, lambda *a, **k: None))
    menu = E._MenuJobs(*jobs)
    reloc, why = E._text_reloc_plan(raw)
    assert reloc, why
    fw, blob = menu.plan(raw, reloc["base_va"] + reloc["used"])
    grown = E._grow_program_text(raw, fw, blob, reloc, None, str(tmp), None, lambda *a, **k: None)
    menu.done()
    assert menu.ok
    with open(grown["path"], "rb") as f:
        return f.read(), [j.setting for j in jobs]


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_godzilla_116_gives_edition_its_deprecated_insert_led_max_brightness(card):
    raw = _program(card)
    assert MS.offered(raw, MS.EDITION) == ""
    t = AdjustmentTable(raw)
    setting, _writes, cat = MS.plan(t, MS.EDITION, 2, EDITIONS)
    assert setting.id == 33 and setting.category == 16
    assert menu_label(t, 33).startswith("DEPRECATED")
    # Attract Mode is where the game's own BOOT SCREEN and 70TH BOOT SCREEN are
    assert any(c == 16 for c, _k, _i in cat.records)
    assert setting.help == "1 = Standard, 2 = 70th Anniversary"
    assert Ed.in_program(raw) is None


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_music_mode_and_edition_share_one_table(card, tmp_path):
    raw = _program(card)
    new, (music, edition) = _built(raw, tmp_path, [(MS.MUSIC_MODE, 3, MODES),
                                                   (MS.EDITION, 2, EDITIONS)])
    assert MS.check(new, music) == [] and MS.check(new, edition) == []
    t = AdjustmentTable(new)
    assert menu_label(t, 31) == "MUSIC MODE" and menu_label(t, 33) == "EDITION"
    assert len(MS.category_table(t).records) == 109
    assert Ed.in_program(new) == {"values": 2, "help": "1 = Standard, 2 = 70th Anniversary", "id": 33}
    old = AdjustmentTable(raw)
    for i in range(old.count):
        if i not in (31, 33):
            assert t.entry(i) == old.entry(i)


@pytest.mark.parametrize("card", [LE116], ids=["le116"])
def test_edition_goes_onto_a_card_that_already_has_music_mode(card, tmp_path):
    raw = _program(card)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first, _ = _built(raw, tmp_path / "a", [(MS.MUSIC_MODE, 3, MODES)])
    assert Ed.in_program(first) is None
    second, (edition,) = _built(first, tmp_path / "b", [(MS.EDITION, 3, EDITIONS + ["Heisei"])])
    t = AdjustmentTable(second)
    assert menu_label(t, 31) == "MUSIC MODE"
    assert len(MS.category_table(t).records) == 109
    assert Ed.in_program(second)["values"] == 3


def test_one_setting_refused_never_stops_the_other():
    raw = _program(LE116)
    t = AdjustmentTable(raw)
    settings, writes, cat, refused = MS.plan_many(
        t, [(MS.MUSIC_MODE, 9, MODES), (MS.EDITION, 2, EDITIONS)])
    assert [s.key for s in settings] == [MS.EDITION]
    assert "2 to 8 values" in refused[MS.MUSIC_MODE]
    assert MS.table_records(cat, *settings) == 108


# ---- the Multi-boot side: tools/spike2_emu/mkmulticard.py ------------------------------------
RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu")
STORE = "/data/nv/godzilla_le/NVM"


@pytest.fixture()
def mk():
    import sys
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard
    return mkmulticard


def _ed(n=2):
    return {"store": STORE, "key": Ed.NVM_KEY, "values": n}


def test_an_editions_card_writes_one_line_and_reads_it_back(mk):
    text = mk.render_images_conf(["p3", "p7:img1"], ["STANDARD", "70TH"], edition=_ed())
    assert "edition=%s|%s|2" % (STORE, Ed.NVM_KEY) in text.splitlines()
    assert mk.parse_images_conf(text)["edition"] == _ed()
    # any other card is byte for byte what it was
    assert "edition" not in mk.render_images_conf(["p3", "p7:img1"], ["A", "B"])
    assert mk.parse_images_conf(mk.render_images_conf(["p3", "p7"]))["edition"] is None


def test_a_line_the_menu_would_not_read_is_dropped_on_reading(mk):
    text = mk.render_images_conf(["p3", "p7"]) + "edition=%s|nothex|2\n" % STORE
    assert mk.parse_images_conf(text)["edition"] is None


def test_every_image_is_one_edition_and_shares_the_settings_store(mk):
    with pytest.raises(mk.Refused, match="offers 3 editions and the card has 2 images"):
        mk.render_images_conf(["p3", "p7"], edition=_ed(3))
    with pytest.raises(mk.Refused, match="no random card"):
        mk.render_images_conf(["p3", "p7", "p8"], edition=_ed(3),
                              groups=[{"members": [1, 2], "title": "R", "subtitle": ""}])
    with pytest.raises(mk.Refused, match="shares the game's settings store"):
        mk.render_images_conf(["p3", "p7"], edition=_ed(), scores={1: "own"})
    with pytest.raises(mk.Refused, match="40 hex"):
        mk.render_images_conf(["p3", "p7"], edition={"store": STORE, "key": "x", "values": 2})


def test_an_older_menu_is_refused_an_editions_card(mk, tmp_path):
    conf = mk.render_images_conf(["p3", "p7"], edition=_ed())
    old = tmp_path / "old"
    old.write_bytes(b"\x7fELF...codeselect 3.1 - Spike 2 boot-time code selector\x00")
    with pytest.raises(mk.Refused, match="codeselect 3.2 or later"):
        mk.check_selector_reads_conf(str(old), conf)
    new = tmp_path / "new"
    new.write_bytes(b"\x7fELF...codeselect 3.2 - Spike 2 boot-time code selector\x00")
    mk.check_selector_reads_conf(str(new), conf)
    mk.check_selector_reads_conf(str(old), mk.render_images_conf(["p3", "p7"]))


def _fake_trees(mk, monkeypatch, programs, title="godzilla_le"):
    """mkmulticard's tree readers over in-memory game programs, one per image."""
    import contextlib

    class Plan:
        def devices(self):
            return ["p3"] + ["p7:img%d" % k for k in range(1, len(programs))]

    monkeypatch.setattr(mk, "plan_tree_source", lambda plan, k: ("ed%d.raw" % k, 3, k))
    monkeypatch.setattr(mk, "tree_root_inode", lambda r, sub: sub)
    monkeypatch.setattr(mk, "tree_game", lambda r, root: (title, "/%s/game" % title, 9, root))
    monkeypatch.setattr(mk, "open_source",
                        lambda path, part: (contextlib.nullcontext(), _Reader(programs)))
    return Plan()


class _Reader:
    def __init__(self, programs):
        self.programs = programs

    def read_file_bytes(self, node):
        return self.programs[node]


def test_the_card_reads_every_image_s_edition(mk, monkeypatch, tmp_path):
    raw = _program(LE116)
    for d in "ab":
        (tmp_path / d).mkdir()
    two, _ = _built(raw, tmp_path / "a", [(MS.EDITION, 2, EDITIONS)])
    plan = _fake_trees(mk, monkeypatch, [two, two])
    assert mk.edition_for_plan(plan) == {"store": STORE, "key": Ed.NVM_KEY, "values": 2}
    # a stock image has no EDITION
    plan = _fake_trees(mk, monkeypatch, [two, raw])
    with pytest.raises(mk.Refused, match="image 1 .* has no EDITION in its menu"):
        mk.edition_for_plan(plan)
    # an image built for another count, or with other names
    three, _ = _built(raw, tmp_path / "b", [(MS.EDITION, 3, EDITIONS + ["Heisei"])])
    with pytest.raises(mk.Refused, match="offers 3 editions and the card has 2 images"):
        mk.edition_for_plan(_fake_trees(mk, monkeypatch, [two, three]))
    (tmp_path / "c").mkdir()
    other, _ = _built(raw, tmp_path / "c", [(MS.EDITION, 2, ["Colour", "Black and white"])])
    with pytest.raises(mk.Refused, match="names the editions"):
        mk.edition_for_plan(_fake_trees(mk, monkeypatch, [two, other]))
