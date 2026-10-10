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
