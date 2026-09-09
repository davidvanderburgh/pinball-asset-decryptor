"""Recovering the images off a multi-boot card someone else built (no Tk).

A card downloaded from another user records, in its build.json and
media.json, the .raw files and the videos / WAVs it was made from - on THEIR
disk.  Loading it here has to draw its own menu anyway (the rendered media
is on the card), and 'Recover images…' has to turn it into a card this
machine can update, rebuild and add to.  These are the pure pieces of that:
what a load makes of a foreign report, what the tool prints and how the rows
are pointed at it.  The Tk half is in test_multiboot_tab.py.
"""
import os

from pinball_decryptor.gui import multiboot_tab
from pinball_decryptor.gui.multiboot_tab import (
    ImageRow, extract_args, extract_commands, is_file_choice, on_card_fields,
    parse_extract, recover_rows, recover_sound, recoverable_indexes,
    recovered_media_dirname, rows_from_inspect, sound_file_errors,
    split_sound_source)


def _foreign_report(tmp_path, with_files=True):
    """What ``inspect --json`` prints for David's downloaded Godzilla card:
    two images whose .raw sources are on G:, media made from videos and WAVs
    on G:, everything rendered onto the card."""
    src0 = "/mnt/g/Pinball Custom Image/Custom Heisei Image/Premium/Orchestral.raw"
    src1 = "/mnt/g/Pinball Custom Image/Original Codes/godzilla_le-1_16_0.raw"
    clip = "/mnt/g/Pinball Custom Image/Custom Heisei Videos/Powerup/Powering Up.mp4"
    roar = "/mnt/g/Pinball Custom Image/Custom Heisei Sounds/Godzilla Roar.wav"
    return {
        "card": str(tmp_path / "card.multi.raw"), "layout": "parts",
        "images": [
            {"index": 0, "device": "/dev/mmcblk0p3", "title": "Heisei",
             "subtitle": "Orchestral", "art": "art0.png", "anim": "anim0.gif",
             "music": "music0.wav", "confirm": "confirm0.wav",
             "art_source": clip + "@0", "anim_source": clip,
             "music_source": roar, "confirm_source": roar,
             "source": src0, "source_exists": False,
             "title_dir": "godzilla_le", "bypass": "bypassed",
             "version": "1.16.0"},
            {"index": 1, "device": "/dev/mmcblk0p7", "title": "Standard",
             "subtitle": "Classic", "art": "art1.png", "anim": None,
             "music": None, "confirm": None,
             "art_source": "auto", "anim_source": "none",
             "music_source": "none", "confirm_source": None,
             "source": src1, "source_exists": False,
             "title_dir": "godzilla_le", "bypass": "bypassed",
             "version": "1.16.0"}],
        "timeout": 20, "default": 0, "volume": "machine",
        "sound_move": "move.wav", "sound_move_source": roar,
        "sound_confirm": "confirm.wav", "sound_confirm_source": "synth",
        "media": [{"name": n, "bytes": 1} for n in
                  ("art0.png", "anim0.gif", "music0.wav", "confirm0.wav",
                   "art1.png", "move.wav", "confirm.wav")],
        "has_media_json": True, "has_build_json": True, "warnings": []}


def test_a_media_source_on_another_machine_comes_back_as_recorded_and_is_said(tmp_path):
    """The preview refused to draw David's downloaded card over
    'art file not found: G:/…Powering Up.mp4' - a video on the OTHER
    person's disk.  The row keeps the spec as recorded (a load followed by
    an apply writes what was read; a drive that is unplugged is the same
    picture), the warnings say so per field, and the PICTURE is drawn
    anyway: the visual gate drops these sentences while nothing has to be
    rendered again (media_file_errors)."""
    rows, warnings = rows_from_inspect(_foreign_report(tmp_path))
    r0, r1 = rows
    assert is_file_choice(r0.art) and r0.art.endswith("Powering Up.mp4") and not r0.art_on_card
    assert r0.art_time == "0"
    assert is_file_choice(r0.anim) and not r0.anim_on_card
    assert is_file_choice(r0.music) and is_file_choice(r0.confirm)
    assert on_card_fields(r0) == []
    # 'auto' / 'none' are not files anywhere; they stay what they were
    assert (r1.art, r1.art_on_card) == ("auto", False)
    assert (r1.anim, r1.anim_on_card) == ("none", False)
    assert r1.music == "none" and r1.confirm == ""
    made_from = [w for w in warnings if "was made from" in w]
    assert len(made_from) == 4 and all("not on this machine" in w for w in made_from)
    assert all("art0.png" in w or "anim0.gif" in w or "music0.wav" in w or "confirm0.wav" in w
               for w in made_from)
    # ...and the sources themselves are still said to be missing
    assert sum("is not on this machine - the menu" in w for w in warnings) == 2
    # what the picture's gate lets through: every media-file sentence, the
    # sounds' among them; the rest of validate_form's stands
    form = multiboot_tab.MultibootForm(images=rows, out=str(tmp_path / "card.multi.raw"),
                                       sound_move=r0.music, sound_confirm="synth")
    errs = multiboot_tab.validate_form(form, sources=False)
    assert errs and all(("not found" in e) for e in errs)
    assert multiboot_tab.media_file_errors(errs) == errs
    assert multiboot_tab.sound_file_errors(errs) == [e for e in errs if e.startswith("The move")]
    assert multiboot_tab.media_file_errors(["Volume is 0-100.", "Image 0: the title must not contain | ; $ or `."]) == []


def test_a_media_source_that_is_here_is_kept_as_the_spec_without_a_word(tmp_path):
    """A card of David's own: the video exists, so nothing is said about it."""
    clip = tmp_path / "Powering Up.mp4"
    clip.write_bytes(bytes(4))
    rep = _foreign_report(tmp_path)
    rep["images"][0]["art_source"] = multiboot_tab.wsl(str(clip)) + "@3"
    rep["images"][0]["anim_source"] = multiboot_tab.wsl(str(clip)) + "@2"
    rows, warnings = rows_from_inspect(rep)
    r0 = rows[0]
    assert r0.art_on_card is False and r0.art_time == "3"
    assert r0.anim_on_card is False and r0.anim_start == "2"
    assert not any("its art was made from" in w or "its animation was made from" in w
                   for w in warnings)
    assert sum("was made from" in w for w in warnings) == 2      # the two WAVs still are


def test_a_menu_sound_made_on_another_machine_keeps_its_path_and_recovers_to_the_cards_wav(tmp_path):
    """The recorded source comes back as recorded (a drive not plugged in
    is the same picture, and must round-trip); the recovery is what points
    the field at the card's own WAV."""
    value, note = split_sound_source("move.wav", "move sound",
                                     "/mnt/g/Sounds/Godzilla Roar.wav")
    assert is_file_choice(value) and value.endswith("Godzilla Roar.wav") and note == ""
    assert split_sound_source("confirm.wav", "confirm sound", "synth") == ("synth", "")
    media = tmp_path / "card.menu-media"
    media.mkdir()
    (media / "move.wav").write_bytes(bytes(2))
    assert recover_sound(value, str(media), "move.wav") == str(media / "move.wav")
    assert recover_sound(value, str(media), "confirm.wav") is None      # not copied out
    assert recover_sound("auto", str(media), "move.wav") is None        # a word is not a file
    here = tmp_path / "mine.wav"
    here.write_bytes(bytes(2))
    assert recover_sound(str(here), str(media), "move.wav") is None     # on this machine: kept
    assert recover_sound(value, "", "move.wav") is None
    # ...and the visual gate lets exactly these two sentences through
    errs = ["Image 0: art file not found: G:/x.mp4",
            "The move sound file was not found: G:/roar.wav",
            "The confirm sound file was not found: G:/roar.wav", "Volume is 0-100."]
    assert sound_file_errors(errs) == errs[1:3]


def test_parse_extract_reads_the_tools_lines():
    text = ("some chatter\n"
            "[extract] image 0: /mnt/d/rec/Orchestral.raw\n"
            "[card] progress 5/10 50.0% copying\n"
            "[extract] image 1: /mnt/d/rec/godzilla_le-1_16_0.raw\n"
            "[extract] media: /mnt/d/rec/card.multi.menu-media\n"
            "[extract] done: 2 image(s)\n")
    mapping, media = parse_extract(text)
    assert mapping == {0: multiboot_tab.host_path("/mnt/d/rec/Orchestral.raw"),
                       1: multiboot_tab.host_path("/mnt/d/rec/godzilla_le-1_16_0.raw")}
    assert media == multiboot_tab.host_path("/mnt/d/rec/card.multi.menu-media")
    assert parse_extract("") == ({}, "")


def test_recover_rows_points_the_rows_at_the_files_and_the_media_copies(tmp_path):
    """After a recovery every field that named a file on the other machine
    - and every '(on the card)' one - is the card's own copy in the
    recovered media dir; a field whose copy was not written keeps what it
    had, and a word stays a word."""
    media = tmp_path / "card.menu-media"
    media.mkdir()
    for name in ("art0.png", "anim0.gif", "confirm0.wav"):
        (media / name).write_bytes(bytes(2))
    rep = _foreign_report(tmp_path)
    rep["images"][1]["art"] = "art1.png"
    rep["images"][1]["art_source"] = None       # an old card: no source recorded
    rows, _w = rows_from_inspect(rep)
    assert rows[1].art_on_card is True
    mapping = {0: str(tmp_path / "Orchestral.raw"), 1: str(tmp_path / "gz.raw")}
    notes = recover_rows(rows, mapping, str(media), rep)
    r0, r1 = rows
    assert (r0.path, r1.path) == (mapping[0], mapping[1])
    assert r0.art == str(media / "art0.png") and r0.art_on_card is False
    assert r0.art_video == "" and r0.art_time == ""
    assert r0.anim == str(media / "anim0.gif") and r0.anim_on_card is False
    assert r0.confirm == str(media / "confirm0.wav") and r0.confirm_on_card is False
    # music0.wav was not copied out: that field keeps the recorded source
    assert r0.music.endswith("Godzilla Roar.wav") and r0.music_on_card is False
    # art1.png (on the card, no source) was not copied out either: still the card's own
    assert (r1.art, r1.art_on_card) == ("art1.png", True)
    assert on_card_fields(r1) == [("art", "art1.png")]
    assert r1.anim == "none" and r1.music == "none"
    assert [n for n in notes if n.startswith("image 0: ")][0] == "image 0: " + mapping[0]
    assert sum(" is " in n for n in notes) == 3
    # applied to a baseline copy too, the two stay equal - a recovery is not a change
    base, _w = rows_from_inspect(rep)
    recover_rows(base, mapping, str(media), rep)
    assert [multiboot_tab.art_spec(r) for r in base] == [multiboot_tab.art_spec(r) for r in rows]
    assert multiboot_tab.diff_forms(
        multiboot_tab.MultibootForm(images=base),
        multiboot_tab.MultibootForm(images=rows)) == ([], [])
    # ...and now art1.png's copy turns up: the on-card field takes it
    (media / "art1.png").write_bytes(bytes(2))
    recover_rows(rows, {}, str(media), rep)
    assert r1.art == str(media / "art1.png") and r1.art_on_card is False


def test_recoverable_indexes_needs_a_missing_raw_and_a_tree_on_the_card(tmp_path):
    rep = _foreign_report(tmp_path)
    rows, _w = rows_from_inspect(rep)
    assert recoverable_indexes(rows, rep) == [0, 1]
    here = tmp_path / "here.raw"
    here.write_bytes(bytes(4))
    rows[0].path = str(here)
    assert recoverable_indexes(rows, rep) == [1]
    # the reader's menu-only image carries no games trees: nothing to recover from
    rep["images"][1]["title_dir"] = None
    assert recoverable_indexes(rows, rep) == []
    # a card with no build.json records no path at all - still recoverable
    rep["images"][1]["title_dir"] = "godzilla_le"
    rows[1].path = ""
    assert recoverable_indexes(rows, rep) == [1]
    assert recoverable_indexes([], None) == []


def test_extract_args_name_the_card_the_folder_the_images_and_the_media(monkeypatch):
    monkeypatch.setattr(multiboot_tab.sys, "platform", "win32")
    args = extract_args("D:/multi/card.multi.raw", "D:/multi/recovered",
                        "D:/multi/recovered/card.multi.menu-media", [0, 1])
    assert args[:2] == [multiboot_tab.MKMULTICARD, "extract"]
    assert args[2:6] == ["--card", "/mnt/d/multi/card.multi.raw",
                         "--out-dir", "/mnt/d/multi/recovered"]
    assert args[6:10] == ["--image", "0", "--image", "1"]
    assert args[10:] == ["--media-out", "/mnt/d/multi/recovered/card.multi.menu-media"]
    cmds = extract_commands("D:/multi/card.multi.raw", "D:/multi/recovered", cwd="/mnt/c/repo")
    assert [label for label, _ in cmds] == ["extract"]
    assert "--image" not in cmds[0][1][-1]


def test_the_recovered_media_dir_is_named_for_the_card_and_is_never_plain_media():
    assert recovered_media_dirname("D:/x/Godzilla V1.6.multi.raw") == "Godzilla V1.6.multi.menu-media"
    assert recovered_media_dirname("card.img") == "card.menu-media"
    assert recovered_media_dirname("") == "card.menu-media"
    assert os.path.basename(recovered_media_dirname("media.raw")) != "media"
