"""PAD-163 — pairing a folder of reworked files with a tab's slots by name.

A modder converted every clip they extracted from Godzilla to black and white
and dropped them back into the project.  Their converter wrote .mp4 for all of
them, and 145 of the card's 658 clips are extracted as .mov, so those copies
sat beside their slots instead of in them.  core.folder_match pairs by name
whatever the file type, and tells the Replace tabs which strays are that.
"""

import os

from pinball_decryptor.core import folder_match

VIDEO_EXTS = (".mp4", ".mov")
IMAGE_EXTS = (".png", ".jpg")


def _touch(root, rel, data=b"x"):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def test_a_converters_mp4s_pair_with_the_cards_mov_and_mp4_slots(tmp_path):
    folder = str(tmp_path / "BW clips")
    for name in ("Tank_Jackpot1.mp4", "Rampage_P.mp4", "tilt.mp4"):
        _touch(folder, name)
    slots = ["video/Tank_Jackpot1.mov", "video/Rampage_P.mov",
             "video/tilt.mp4", "video/megalon_drill.mp4"]

    found = folder_match.match_folder(folder, slots, VIDEO_EXTS)

    assert found["pairs"] == {
        "video/Tank_Jackpot1.mov": os.path.join(folder, "Tank_Jackpot1.mp4"),
        "video/Rampage_P.mov": os.path.join(folder, "Rampage_P.mp4"),
        "video/tilt.mp4": os.path.join(folder, "tilt.mp4"),
    }
    assert found["retyped"] == ["video/Rampage_P.mov",
                                "video/Tank_Jackpot1.mov"]
    assert found["unmatched"] == found["ambiguous"] == []
    assert found["files"] == 3


def test_letter_case_does_not_matter(tmp_path):
    folder = str(tmp_path / "bw")
    _touch(folder, "TANK_JACKPOT1.MP4")
    found = folder_match.match_folder(folder, ["video/Tank_Jackpot1.mov"],
                                      VIDEO_EXTS)
    assert list(found["pairs"]) == ["video/Tank_Jackpot1.mov"]


def test_files_of_another_kind_are_not_counted(tmp_path):
    folder = str(tmp_path / "bw")
    _touch(folder, "Tank_Jackpot1.mp4")
    _touch(folder, "notes.txt")
    _touch(folder, "Thumbs.db")
    _touch(folder, ".hidden/Rampage_P.mp4")
    found = folder_match.match_folder(
        folder, ["video/Tank_Jackpot1.mov", "video/Rampage_P.mov"],
        VIDEO_EXTS)
    assert found["files"] == 1
    assert list(found["pairs"]) == ["video/Tank_Jackpot1.mov"]


def test_a_name_no_slot_has_is_listed(tmp_path):
    folder = str(tmp_path / "bw")
    _touch(folder, "my_new_intro.mp4")
    found = folder_match.match_folder(folder, ["video/tilt.mp4"], VIDEO_EXTS)
    assert found["pairs"] == {}
    assert found["unmatched"] == ["my_new_intro.mp4"]


def test_a_bare_glyph_name_fits_every_atlas_so_it_is_left_out(tmp_path):
    """U+0041_A.png is in every font's folder; a loose one says nothing
    about which font it is."""
    folder = str(tmp_path / "glyphs")
    _touch(folder, "U+0041_A.png")
    slots = ["images/scene_textures/glyphs/radimg_512x512_a4a16c84/U+0041_A.png",
             "images/scene_textures/glyphs/radimg_512x512_2af9d168/U+0041_A.png"]
    found = folder_match.match_folder(folder, slots, IMAGE_EXTS)
    assert found["pairs"] == {}
    assert found["ambiguous"] == ["U+0041_A.png"]


def test_the_files_own_folders_pick_between_same_named_slots(tmp_path):
    """A copy of the project's images folder pairs glyph for glyph."""
    folder = str(tmp_path / "copy")
    a = "images/scene_textures/glyphs/radimg_512x512_a4a16c84/U+0041_A.png"
    b = "images/scene_textures/glyphs/radimg_512x512_2af9d168/U+0041_A.png"
    pa = _touch(folder, "scene_textures/glyphs/radimg_512x512_a4a16c84/"
                        "U+0041_A.png")
    pb = _touch(folder, "BW/images/scene_textures/glyphs/"
                        "radimg_512x512_2af9d168/U+0041_A.png")
    found = folder_match.match_folder(folder, [a, b], IMAGE_EXTS)
    assert found["pairs"] == {a: pa, b: pb}
    assert found["ambiguous"] == []


def test_another_cards_fingerprinted_glyphs_pair_with_nothing(tmp_path):
    """The reporter's glyphs: same names, but the atlas folder carries a
    different card's fingerprint — not a pairing by name can make."""
    folder = str(tmp_path / "silent")
    _touch(folder, "glyphs/radimg_512x512_bba78124/U+0069_i.png")
    slots = ["images/scene_textures/glyphs/radimg_512x512_a4a16c84/U+0069_i.png",
             "images/scene_textures/glyphs/radimg_512x512_2af9d168/U+0069_i.png"]
    found = folder_match.match_folder(folder, slots, IMAGE_EXTS)
    assert found["pairs"] == {}
    left = found["unmatched"] + found["ambiguous"]
    assert left == ["glyphs/radimg_512x512_bba78124/U+0069_i.png"]
    assert folder_match.FINGERPRINT_RE.search(left[0])


def test_the_fingerprint_pattern_spots_pictures_and_glyphs_only():
    fp = folder_match.FINGERPRINT_RE
    assert fp.search("scene_textures/radimg_unnamed_instance_15_154x70_"
                     "e8cae493.png")
    assert fp.search("glyphs/radimg_512x512_bba78124/U+0069_i.png")
    assert not fp.search("Tank_Jackpot1.mp4")
    assert not fp.search("godzilla_le/assets/lcd/Login/Avatar.png")


def test_two_files_for_one_slot_keep_the_one_of_the_slots_own_type(tmp_path):
    folder = str(tmp_path / "bw")
    mp4 = _touch(folder, "Tank_Jackpot1.mp4")
    mov = _touch(folder, "Tank_Jackpot1.mov")
    found = folder_match.match_folder(folder, ["video/Tank_Jackpot1.mov"],
                                      VIDEO_EXTS)
    assert found["pairs"] == {"video/Tank_Jackpot1.mov": mov}
    assert found["retyped"] == []
    assert found["duplicates"] == ["Tank_Jackpot1.mp4"]
    assert os.path.isfile(mp4)


def test_slots_differing_only_in_type_are_told_apart_by_the_files_type(
        tmp_path):
    folder = str(tmp_path / "art")
    jpg = _touch(folder, "logo.jpg")
    found = folder_match.match_folder(
        folder, ["images/loose/logo.png", "images/loose/logo.jpg"],
        IMAGE_EXTS)
    assert found["pairs"] == {"images/loose/logo.jpg": jpg}


def test_a_stray_under_another_file_type_names_its_slot():
    baseline = {"video/Tank_Jackpot1.mov": "a", "video/tilt.mp4": "b",
                "video/manifest.txt": "c"}
    rels = ["video/Tank_Jackpot1.mp4", "video/tilt.mp4",
            "video/JUKEBOX_LOOP6f.mov"]
    foreign, twins = folder_match.foreign_twins(rels, baseline,
                                                casefold=False)
    assert foreign == {"video/Tank_Jackpot1.mp4", "video/JUKEBOX_LOOP6f.mov"}
    assert twins == {"video/Tank_Jackpot1.mp4": "video/Tank_Jackpot1.mov"}


def test_a_name_in_other_letter_case_is_the_cards_file_on_windows():
    """Windows opens tank_jackpot1.mov by the card's name, so the build
    writes it — it is not a stray there."""
    baseline = {"video/Tank_Jackpot1.mov": "a"}
    rels = ["video/tank_jackpot1.mov"]
    assert folder_match.foreign_twins(rels, baseline, casefold=True) \
        == (set(), {})
    foreign, twins = folder_match.foreign_twins(rels, baseline,
                                                casefold=False)
    assert foreign == {"video/tank_jackpot1.mov"}
    assert twins == {"video/tank_jackpot1.mov": "video/Tank_Jackpot1.mov"}


def test_no_twin_when_two_card_files_share_the_name():
    baseline = {"images/loose/logo.png": "a", "images/loose/logo.jpg": "b"}
    foreign, twins = folder_match.foreign_twins(
        ["images/loose/logo.bmp"], baseline, casefold=False)
    assert foreign == {"images/loose/logo.bmp"}
    assert twins == {}
