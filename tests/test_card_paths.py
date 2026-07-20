"""Mapping an extracted asset back to its file on the card.

Behind the Replace tabs' "Find in Partition Explorer" (monkeybug batch 16:
"it would be great if there was an option to find in partition ... to see
which radium file they live in").  The Stern extractor records the mapping in
per-kind TSV manifests; these guard the parsing and the three image stores.
"""
import os

from pinball_decryptor.core import card_paths


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def test_video_slot_resolves_to_its_asset_file(tmp_path):
    _write(str(tmp_path / "video" / "manifest.txt"),
           "# output\tcard path\tbytes\n"
           "Attract_Loop.mp4\t/spk/games/lz/scene.assets/3.asset/0.asset\t99\n")
    card, note = card_paths.video_card_path(str(tmp_path),
                                            "video/Attract_Loop.mp4")
    assert card == "/spk/games/lz/scene.assets/3.asset/0.asset"
    assert note == ""


def test_video_slot_without_manifest_entry_explains_itself(tmp_path):
    _write(str(tmp_path / "video" / "manifest.txt"),
           "# output\tcard path\tbytes\nOther.mp4\t/a/b.asset\t1\n")
    card, note = card_paths.video_card_path(str(tmp_path), "video/Missing.mp4")
    assert card is None
    assert "re-extract" in note.lower()


def test_loose_image_resolves_to_its_own_card_path(tmp_path):
    _write(str(tmp_path / "images" / "manifest.txt"),
           "# output\tcard path\tbytes\n"
           "spk/games/lz/logo.png\t/spk/games/lz/logo.png\t42\n")
    card, note = card_paths.image_card_path(
        str(tmp_path), "images/spk/games/lz/logo.png")
    assert card == "/spk/games/lz/logo.png"
    assert note == ""


def test_scene_texture_resolves_to_its_container_asset(tmp_path):
    _write(str(tmp_path / "images" / "scene_textures" / "manifest.txt"),
           "# output\tcard path\tbytes\twidth\theight\tformat\n"
           "scene_textures/Ramp.png\t/spk/games/lz/scene.assets/7.asset"
           "\t64\t32\t32\t5\n")
    card, note = card_paths.image_card_path(
        str(tmp_path), "images/scene_textures/Ramp.png")
    assert card == "/spk/games/lz/scene.assets/7.asset"
    assert "inside" in note


def test_radium_embedded_image_names_its_radium_file(tmp_path):
    """The headline ask: which radium file does this image live in?"""
    _write(str(tmp_path / "images" / "scene_textures" / "radium_images.txt"),
           "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
           "scene_textures/radimg_Song_512x512_ab12cd34.png"
           "\t/spk/games/lz/ui.radium\t4096\t512\t512\t512\t5\n")
    card, note = card_paths.image_card_path(
        str(tmp_path),
        "images/scene_textures/radimg_Song_512x512_ab12cd34.png")
    assert card == "/spk/games/lz/ui.radium"
    assert "ui.radium" in note


def test_radium_image_first_occurrence_wins(tmp_path):
    """A radium PNG is content-deduplicated across containers, so the same
    output appears on several rows; the first is its "home"."""
    _write(str(tmp_path / "images" / "scene_textures" / "radium_images.txt"),
           "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
           "scene_textures/dup.png\t/spk/games/lz/first.radium\t1\t2\t3\t4\t5\n"
           "scene_textures/dup.png\t/spk/games/lz/second.radium\t9\t2\t3\t4\t5\n")
    card, _ = card_paths.image_card_path(
        str(tmp_path), "images/scene_textures/dup.png")
    assert card == "/spk/games/lz/first.radium"


def test_image_with_no_manifests_at_all(tmp_path):
    card, note = card_paths.image_card_path(str(tmp_path), "images/x.png")
    assert card is None
    assert "re-extract" in note.lower()


def test_audio_container_inferred_from_the_decode_name():
    # Sounds are decoded out of the bank binaries, not stored as files.
    assert card_paths.audio_container("audio/00m00s213 - idx0460 - you.wav") \
        == "image.bin"
    assert card_paths.audio_container("audio/music_cat07_0003 - music.wav") \
        == "image-sc07.bin"
    assert card_paths.audio_container("audio/handwritten name.wav") is None


def test_audio_card_hint_explains_the_container_relationship():
    container, note = card_paths.audio_card_hint("audio/x - idx0461.wav")
    assert container == "image.bin"
    assert "image.bin" in note
    container, note = card_paths.audio_card_hint("audio/mystery.wav")
    assert container is None
    assert note


def test_manifest_parsing_tolerates_junk_rows(tmp_path):
    _write(str(tmp_path / "video" / "manifest.txt"),
           "# output\tcard path\tbytes\n"
           "\n"
           "truncated_row_no_tabs\n"
           "Good.mp4\t/a/good.asset\t7\n")
    card, _ = card_paths.video_card_path(str(tmp_path), "video/Good.mp4")
    assert card == "/a/good.asset"
