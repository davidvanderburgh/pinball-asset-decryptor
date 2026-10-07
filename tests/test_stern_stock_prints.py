"""plugins.stern.stock_prints -- the official Stern stock fingerprint table (PAD-426).

Synthetic cards are built with the shared ext4 fake and the Compare tests'
digest-bearing ``.sidx``: an "official" card, and builds of it that change a
scene picture, a video, the sound bank or add a file.  The table made from the
official card must call the official card official, and say what each build
changed -- the question PAD-421 could not answer (a shared custom Godzilla
card read as stock Godzilla LE 1.16).
"""
import hashlib
import json
import lzma
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import stock_prints as sp
from tests.test_image_info import _FAKE_MP4, _container_header
from tests.test_stern_compare import _card_spec, _install_readers_by_card

FOLDER = "turtles_pro"
SIDX = "turtles_pro-1_59_0.sidx"
CARD = "turtles_pro-1_59_0.Release.8G.sdcard.raw"


def _radium(*pictures):
    """``scene.radium`` bytes holding one 4x4 BC3 picture per entry, framed
    the way :func:`engine.parse_radium_images` finds them."""
    out = b"RADIUM-HEADER"
    for pix in pictures:
        assert len(pix) == 16
        out += struct.pack("<9I", 4, 4, 0x80000001, 4, 4, 5, 0, 0, 16) + pix
    return out + b"TAIL"


PIC_A = b"A" * 16
PIC_B = b"B" * 16
PIC_NEW = b"N" * 16


def _official_files():
    return {
        "image.bin": _container_header(10, 9),
        "game": b"\x7fELF-not-really",
        "image-sc09.bin": b"BANK",
        "gfx/logo.png": b"PNG-LOGO",
        "assets/aa11/scene.radium": _radium(PIC_A, PIC_B),
        "assets/aa11/scene.assets/0.asset": _FAKE_MP4 + b"clip",
        "assets/bb22/scene.radium": _radium(PIC_B),
    }


def _digest(pix):
    return hashlib.md5(pix).hexdigest()[:8]


def _cards(tmp_path, monkeypatch, **specs):
    """Write one fake card per ``name=files`` and serve each its own tree."""
    from tests._ext4_fake import write_fake_card
    paths, by_name = {}, {}
    for key, (name, files, sidx) in specs.items():
        paths[key] = str(write_fake_card(tmp_path / name))
        by_name[name] = _card_spec(FOLDER, sidx, files)
    _install_readers_by_card(monkeypatch, by_name)
    return paths


def _table(tmp_path, monkeypatch, official):
    key, rel = sp.make_release(official)
    path = str(tmp_path / "stock_prints.json.xz")
    sp.save_table({key: rel}, path)
    monkeypatch.setattr(sp, "TABLE_PATH", path)
    return key, rel


def test_release_entry_is_hashes_of_the_official_card(tmp_path, monkeypatch):
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX))
    key, rel = sp.make_release(cards["official"])
    assert key == SIDX
    assert rel["folder"] == FOLDER and rel["version"] == "1.59.0"
    assert sp.release_label(rel) == "Turtles Pro 1.59"
    files = _official_files()
    assert set(rel["files"]) == {"%s/%s" % (FOLDER, p) for p in files}
    logo = rel["files"]["%s/gfx/logo.png" % FOLDER]
    assert logo == [len(files["gfx/logo.png"]),
                    hashlib.md5(files["gfx/logo.png"]).hexdigest()[:16]]
    # The radium pictures, by the digest the extract names them with.
    assert sp.picture_set(rel) == {_digest(PIC_A), _digest(PIC_B)}
    # Hashes only: nothing of the card's bytes is in the entry.
    blob = json.dumps(rel)
    for content in files.values():
        assert content.decode("latin1") not in blob


def test_a_card_that_disagrees_with_its_own_manifest_is_refused(tmp_path,
                                                                 monkeypatch):
    from tests._ext4_fake import write_fake_card
    files = _official_files()
    spec = _card_spec(FOLDER, SIDX, files)
    # The bytes change, the manifest does not: written to after release.
    spec[FOLDER]["gfx"]["logo.png"] = b"PNG-EDITED"
    path = str(write_fake_card(tmp_path / CARD))
    _install_readers_by_card(monkeypatch, {CARD: spec})
    with pytest.raises(ValueError, match="not consistent"):
        sp.make_release(path)


def test_the_official_card_reads_official(tmp_path, monkeypatch):
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX))
    _table(tmp_path, monkeypatch, cards["official"])
    got = sp.check_card(cards["official"])
    assert got["status"] == "official"
    assert got["label"] == "Turtles Pro 1.59"
    assert got["text"].startswith("Official Turtles Pro 1.59")


def test_a_build_of_it_says_what_differs(tmp_path, monkeypatch):
    built = _official_files()
    built["assets/aa11/scene.radium"] = _radium(PIC_A, PIC_NEW)  # 1 picture
    built["assets/aa11/scene.assets/0.asset"] = _FAKE_MP4 + b"other clip"
    built["image.bin"] = _container_header(10, 9) + b"repacked"
    built["config.sh"] = b"#!/bin/sh\n"
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX),
                   # A custom card keeps the release's update index name.
                   built=("Turtles Custom V1.96.raw", built, SIDX))
    _table(tmp_path, monkeypatch, cards["official"])
    got = sp.check_card(cards["built"])
    assert got["status"] == "modified"
    diff = got["diff"]
    assert diff["scenes"] == 1
    assert diff["pictures"] == 1          # PIC_A is still stock
    assert diff["videos"] == 1
    assert diff["sounds"] is True
    assert diff["added"] == 1 and diff["deleted"] == 0
    assert got["text"] == ("Turtles Pro 1.59, modified: differs from the "
                           "official card in 1 scene, 1 picture, 1 video, "
                           "the sound bank, 1 other file.")


def test_a_release_with_no_record_is_unknown_not_official(tmp_path,
                                                          monkeypatch):
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX),
                   other=("turtles_pro-1_60_0.Release.8G.sdcard.raw",
                          _official_files(), "turtles_pro-1_60_0.sidx"))
    _table(tmp_path, monkeypatch, cards["official"])
    got = sp.check_card(cards["other"])
    assert got["status"] == "unknown"
    assert "turtles_pro-1_60_0.sidx" in got["text"]


def test_card_details_name_the_official_release(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern.info import card_info
    built = _official_files()
    built["gfx/logo.png"] = b"PNG-OTHER"
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX),
                   built=("custom.raw", built, SIDX))
    _table(tmp_path, monkeypatch, cards["official"])

    def row(path):
        fw = dict(card_info(path))["Firmware"]
        return dict((r[0], r[1]) for r in fw).get("Official release")

    assert row(cards["official"]).startswith("Official Turtles Pro 1.59")
    assert row(cards["built"]) == ("Turtles Pro 1.59, modified: differs from "
                                   "the official card in 1 picture.")


def test_diff_manifest_counts_by_kind():
    rel = {"files": {"g/assets/s1/scene.radium": [10, "a" * 16],
                     "g/assets/s1/scene.assets/0.asset": [5, "b" * 16],
                     "g/clip.asset": [9, "c" * 16],
                     "g/game": [4, "d" * 16],
                     "g/image-sc01.bin": [3, "e" * 16]},
           "pictures": ""}
    card = {"g/assets/s1/scene.radium": (10, "a" * 32),
            "g/assets/s1/scene.assets/0.asset": (5, "f" * 32),
            "g/clip.asset": (9, "0" * 32),
            "g/game": (4, "1" * 32),
            "g/image-sc01.bin": (3, "2" * 32)}
    d = sp.diff_manifest(rel, card, video_paths=["/g/clip.asset"])
    assert (d["scenes"], d["pictures"], d["videos"], d["program"],
            d["music"]) == (1, 1, 1, True, 1)
    same = {p: (v[0], v[1] + "0" * 16) for p, v in rel["files"].items()}
    assert sp.diff_manifest(rel, same)["changed"] == []
    # A file the build removed is said as removed, its scene as changed.
    gone = dict(same)
    del gone["g/assets/s1/scene.assets/0.asset"]
    d = sp.diff_manifest(rel, gone)
    assert (d["deleted"], d["scenes"], d["pictures"]) == (1, 1, 0)
    assert sp.change_words(d) == ["1 scene", "1 file removed"]


def test_a_new_picture_shared_by_two_scenes_counts_once():
    rel = {"files": {"g/a/scene.radium": [1, "a" * 16],
                     "g/b/scene.radium": [1, "b" * 16]},
           "pictures": _digest(PIC_A)}
    card = {"g/a/scene.radium": (1, "c" * 32), "g/b/scene.radium": (1, "d" * 32)}
    radiums = {"g/a/scene.radium": _radium(PIC_A, PIC_NEW),
               "g/b/scene.radium": _radium(PIC_NEW)}
    d = sp.diff_manifest(rel, card, radium_reader=radiums.__getitem__)
    assert (d["scenes"], d["pictures"]) == (2, 1)


def _project(tmp_path, pictures, rec=None, folder=FOLDER):
    proj = tmp_path / "proj"
    tex = proj / "images" / "scene_textures"
    tex.mkdir(parents=True)
    rows = ["# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt"]
    for i, d in enumerate(pictures):
        rows.append("scene_textures/radimg_Thing_4x4_%s.png\t/%s/assets/aa11/"
                    "scene.radium\t%d\t16\t4\t4\t5" % (d, folder, 36 * i))
    (tex / "radium_images.txt").write_text("\n".join(rows) + "\n",
                                           encoding="utf-8")
    if rec is not None:
        (proj / ".extract_source.json").write_text(json.dumps(rec),
                                                   encoding="utf-8")
    return str(proj)


def _picture_table():
    return {SIDX: {"folder": FOLDER, "name": "Turtles Pro",
                   "version": "1.59.0", "files": {},
                   "pictures": "".join(sorted([_digest(PIC_A),
                                               _digest(PIC_B)]))}}


def test_a_project_off_the_official_card_reads_official(tmp_path):
    proj = _project(tmp_path, [_digest(PIC_A), _digest(PIC_B)],
                    rec={"input_name": "x.raw", "card_version": "1.59.0"})
    got = sp.check_project(proj, table=_picture_table())
    assert got["status"] == "official"
    assert got["text"] == "Extracted from the official Turtles Pro 1.59 card."


def test_a_project_off_a_build_counts_the_pictures_it_differs_by(tmp_path):
    proj = _project(tmp_path, [_digest(PIC_A), _digest(PIC_NEW)],
                    rec={"input_name": "x.raw", "card_version": "1.59.0"})
    got = sp.check_project(proj, table=_picture_table())
    assert got["status"] == "modified"
    assert got["text"] == ("Extracted from a modified Turtles Pro 1.59 card: "
                           "1 picture is not the official one.")


def test_a_project_with_no_version_is_only_named_on_an_exact_match(tmp_path):
    exact = _project(tmp_path, [_digest(PIC_A)], rec={"input_name": "x"})
    assert sp.check_project(exact, table=_picture_table())["status"] \
        == "official"
    other = tmp_path / "o"
    other.mkdir()
    proj = _project(other, [_digest(PIC_NEW)], rec={"input_name": "x"})
    assert sp.check_project(proj, table=_picture_table())["status"] \
        == "unknown"


def test_the_verdict_the_extract_stamped_wins(tmp_path):
    stamp = {"status": "modified", "label": "Turtles Pro 1.59",
             "sidx": SIDX, "text": "Turtles Pro 1.59, modified: differs "
                                   "from the official card in the sound "
                                   "bank."}
    proj = _project(tmp_path, [_digest(PIC_A)],
                    rec={"input_name": "x", "card_version": "1.59.0",
                         "stock": stamp})
    got = sp.check_project(proj, table=_picture_table())
    assert got["status"] == "modified" and got["text"] == stamp["text"]


def test_project_details_carry_the_manufacturers_stock_answer(tmp_path):
    from pinball_decryptor.webui.extract_helpers import project_details
    proj = _project(tmp_path, [_digest(PIC_A)], rec={"input_name": "x"})
    with open(os.path.join(proj, ".checksums.md5"), "w") as f:
        f.write("")

    class Mfr:
        key = "stern"

        def project_stock(self, folder):
            return {"status": "official", "label": "L", "text": "T"}

        def detect(self, path):
            return None

    assert project_details(proj, [Mfr()], Mfr())["stock"]["text"] == "T"
    # A manufacturer with no official record says nothing.
    assert project_details(proj, [], object())["stock"] is None


def test_table_round_trip_is_byte_stable(tmp_path):
    rel = _picture_table()
    a, b = str(tmp_path / "a.json.xz"), str(tmp_path / "b.json.xz")
    sp.save_table(rel, a)
    sp.save_table(rel, b)
    with open(a, "rb") as fa, open(b, "rb") as fb:
        assert fa.read() == fb.read()
    assert sp.load_table(a) == rel
    assert sp.load_table(str(tmp_path / "missing.json.xz")) == {}


def test_the_shipped_table_covers_the_latest_builds():
    table = sp.load_table()
    assert table, "pinball_decryptor/plugins/stern/data/stock_prints.json.xz"
    for key in ("godzilla_le-1_16_0.sidx", "godzilla_pro-1_16_0.sidx",
                "metallica_spike-1_04_0.sidx", "turtles_pro-1_59_0.sidx"):
        assert key in table, key
    hexd = set("0123456789abcdef")
    for key, rel in table.items():
        assert rel["files"] and rel["version"] and rel["folder"], key
        assert len(rel["pictures"]) % sp.PICTURE_DIGITS == 0
        assert set(rel["pictures"]) <= hexd
        for path, (size, md5) in rel["files"].items():
            assert len(md5) == sp.FILE_DIGITS and set(md5) <= hexd, path
    with lzma.open(sp.TABLE_PATH, "rb") as f:
        assert json.loads(f.read())["format"] == sp.TABLE_FORMAT


def _stale_card(tmp_path, monkeypatch, new_clip):
    """An official card plus a build that replaced the scene clip but kept
    Stern's manifest record for it (DragonRR's Heisei card did this to 541
    videos)."""
    from tests._ext4_fake import write_fake_card
    official = str(write_fake_card(tmp_path / CARD))
    built = str(write_fake_card(tmp_path / "Heisei.raw"))
    spec = _card_spec(FOLDER, SIDX, _official_files())
    spec[FOLDER]["assets"]["aa11"]["scene.assets"]["0.asset"] = new_clip
    _install_readers_by_card(monkeypatch, {
        CARD: _card_spec(FOLDER, SIDX, _official_files()),
        "Heisei.raw": spec})
    _table(tmp_path, monkeypatch, official)
    return built


def test_a_replaced_file_its_manifest_still_calls_stock_is_caught(
        tmp_path, monkeypatch):
    built = _stale_card(tmp_path, monkeypatch,
                        _FAKE_MP4 + b"a much longer replacement clip")
    got = sp.check_card(built)                 # sizes only: still caught
    assert got["status"] == "modified"
    assert got["diff"]["videos"] == 1 and got["stale"] == 1
    assert "not built by PAD" in got["text"]


def test_a_same_size_replacement_needs_the_deep_check(tmp_path, monkeypatch):
    clip = _official_files()["assets/aa11/scene.assets/0.asset"]
    built = _stale_card(tmp_path, monkeypatch, clip[:-4] + b"XXXX")
    assert sp.check_card(built)["status"] == "official"   # can't tell
    got = sp.check_card(built, deep=True)
    assert got["status"] == "modified" and got["deep"]
    assert got["diff"]["videos"] == 1 and got["stale"] == 1
