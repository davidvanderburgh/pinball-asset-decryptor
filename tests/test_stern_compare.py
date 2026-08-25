"""plugins.stern.compare — the two-card what-changed report (Compare tab).

Two synthetic cards are built with the shared ext4 fake, each carrying a
digest-bearing ``.sidx`` manifest, a container header, a game ELF with a
real (synthetic) adjustment table, sniffable videos and scene folders — so
every diff bucket is exercised end to end without a multi-GB fixture.
"""
import hashlib
import hmac
import os
import struct

import pytest

from pinball_decryptor.core.image_info import as_text
from pinball_decryptor.plugins.stern.compare import (_score_rows, _tri,
                                                     compare_cards,
                                                     extract_ref)
from pinball_decryptor.plugins.stern.sidx import SIDX_KEY, manifest_files
from tests.test_image_info import _FAKE_MP4, _container_header
from tests.test_stern_adjustments import make_elf


# ---------------------------------------------------------------------------
# A .sidx whose records carry REAL sizes + MD5s (unlike test_image_info's
# zero-payload _make_sidx — the compare diffs by these fields).
# ---------------------------------------------------------------------------

def _named(rows):
    """``{name: value}`` for a section's rows.

    NOT ``dict(rows)``: a listed FILE row is ``(name, value, ref)`` since the
    report started carrying what each row points at, and unpacking it two ways
    is how a renderer breaks on the one section that grew."""
    return {r[0]: r[1] for r in rows}


def _refs(rows):
    """Every ref a section's rows carry, in order."""
    return [r[2] for r in rows if len(r) > 2]


def _sidx_with_digests(files, tag=b"FI64"):
    """Valid ``.sidx`` bytes for ``files`` = ``{path: content}``."""
    paths = sorted(files)
    blob = bytearray(0x38)
    struct.pack_into("<I", blob, 0x34, 0x12345678)
    strs = b"".join(p.encode() + b"\x00" for p in paths)
    blob += b"STRS" + struct.pack("<I", len(strs)) + strs
    payload_len = 80 if tag == b"FI64" else 60
    for p in paths:
        data = files[p]
        payload = bytearray(payload_len)
        digest = hmac.new(SIDX_KEY, data, hashlib.sha1).digest()
        md5 = hashlib.md5(data).digest()
        if tag == b"FI64":
            struct.pack_into("<Q", payload, 8, len(data))
            struct.pack_into("<Q", payload, 24, len(data))
            payload[37:57] = digest
            payload[57:73] = md5
        else:
            struct.pack_into("<I", payload, 4, len(data))
            struct.pack_into("<I", payload, 12, len(data))
            payload[21:41] = digest
            payload[41:57] = md5
        blob += tag + struct.pack("<I", payload_len) + bytes(payload)
    return bytes(blob)


def test_manifest_files_reads_sizes_and_md5s():
    files = {"turtles_pro/image.bin": b"\x01" * 100,
             "turtles_pro/gfx/logo.png": b"png!"}
    for tag in (b"FI64", b"FINF"):
        out = manifest_files(_sidx_with_digests(files, tag=tag))
        assert set(out) == set(files)
        for path, content in files.items():
            assert out[path] == (len(content),
                                 hashlib.md5(content).hexdigest())
    # Junk in, empty out — never junk digests.
    assert manifest_files(b"not a sidx") == {}
    assert manifest_files(b"") == {}


# ---------------------------------------------------------------------------
# Two full synthetic cards
# ---------------------------------------------------------------------------

# The table locator needs a run of several AD_ pointers (a real table is
# hundreds), so both fixtures carry the same 6-setting base beyond their
# intended differences.
_ADJ_BASE = [
    ("AD_GRAND_CHAMPION_SCORE", 75000000, 1000000, 1000000000),
    ("AD_HIGH_SCORE_1_SCORE", 55000000, 1000000, 1000000000),
    ("AD_HIGH_SCORE_1_AWARDS", 1, 0, 4),
    ("AD_KASHMIR_CHAMPION", 10000000, 5000000, 1000000000),
    ("AD_KASHMIR_CHAMPION_AWARD", 0, 0, 2),
]
_ADJ_A = [
    ("AD_INVALID", 0, 0, 0),
    ("AD_FREE_PLAY", 0, 0, 1),
    ("AD_ALLOW_HIGH_SCORES", 1, 0, 1),
] + _ADJ_BASE
# B: free-play default flipped, one setting removed, one added.  Name
# lengths matter: make_elf packs the strings before the pointer array, and
# the locator only sees a 4-byte-aligned array — the name sums (with NULs)
# must stay ≡ 0 mod 4, as a real linker would keep them.
_ADJ_B = [
    ("AD_INVALID", 0, 0, 0),
    ("AD_FREE_PLAY", 1, 0, 1),
] + _ADJ_BASE + [
    ("AD_NEW_SETTING_2", 3, 0, 9),
]

_VIDEO_A = _FAKE_MP4 + b"A"
_SCENE_ASSET_A = _FAKE_MP4 + b"scene-A"
_SCENE_ASSET_B = _FAKE_MP4 + b"scene-B"


def _game_files(adj_specs, header, bank, logo, scene_aa_asset,
                extra=None):
    """The flat ``{relpath: content}`` a card's game folder carries."""
    files = {
        "image.bin": header,
        "game": make_elf(adj_specs),
        "image-sc09.bin": bank,
        "gfx/logo.png": logo,
        "gfx/score.png": b"SAME-PIXELS",
        "assets/aa11/scene.radium": b"RAD-AA",
        "assets/aa11/scene.assets/0.asset": scene_aa_asset,
        "assets/bb22/scene.radium": b"RAD-BB",
        "notes.txt": b"same-notes",
    }
    files.update(extra or {})
    return files


def _card_spec(game_folder, sidx_name, files):
    """Nested-dict card spec for the ext4 fake: /spk/index + the game tree."""
    tree = {}
    for rel, content in files.items():
        parts = rel.split("/")
        node = tree
        for d in parts[:-1]:
            node = node.setdefault(d, {})
        node[parts[-1]] = content
    manifest = {"%s/%s" % (game_folder, rel): c for rel, c in files.items()}
    return {"spk": {"index": {sidx_name: _sidx_with_digests(manifest)}},
            game_folder: tree}


_FILES_A = _game_files(_ADJ_A, _container_header(578, 549), b"BANK-A",
                       b"PNG-LOGO-A", _SCENE_ASSET_A,
                       extra={"clip.asset": _VIDEO_A})
_FILES_B = _game_files(_ADJ_B, _container_header(580, 551), b"BANK-B",
                       b"PNG-LOGO-B", _SCENE_ASSET_B,
                       extra={"gfx/new.png": b"NEW",
                              "config.sh": b"#!/bin/sh\n",
                              "assets/cc33/scene.radium": b"RAD-CC",
                              "assets/cc33/scene.assets/0.asset":
                                  _FAKE_MP4 + b"C"})

SPEC_A = _card_spec("turtles_pro", "turtles_pro-1_58_0.sidx", _FILES_A)
SPEC_B = _card_spec("turtles_pro", "turtles_pro-1_59_0.sidx", _FILES_B)


def _install_readers_by_card(monkeypatch, specs_by_name):
    """Like _ext4_fake.install_fake_reader, but each card FILE gets its own
    tree (the compare opens two cards in one call)."""
    from tests._ext4_fake import GOOD_OFF, FakeExt4Reader
    from pinball_decryptor.plugins.stern import explorer

    def fake_reader(fileobj, off, _size):
        if off == GOOD_OFF:
            return FakeExt4Reader(specs_by_name[os.path.basename(fileobj.name)])
        raise ValueError("not an ext filesystem")

    monkeypatch.setattr(explorer, "Ext4Reader", fake_reader)


def _two_cards(tmp_path, monkeypatch, spec_a=SPEC_A, spec_b=SPEC_B,
               name_a="turtles_pro-1_58_0.Release.8G.sdcard.raw",
               name_b="turtles_pro-1_59_0.Release.8G.sdcard.raw"):
    from tests._ext4_fake import write_fake_card
    a = write_fake_card(tmp_path / name_a)
    b = write_fake_card(tmp_path / name_b)
    _install_readers_by_card(monkeypatch, {name_a: spec_a, name_b: spec_b})
    return a, b


def test_compare_full_report(tmp_path, monkeypatch):
    a, b = _two_cards(tmp_path, monkeypatch)
    sections = compare_cards(a, b)
    by_title = dict(sections)
    report = as_text(sections, title="Compare Report")

    head = _named(by_title["Compared"])
    assert head["Version"] == "1.58.0 -> 1.59.0"
    assert head["Game folder"] == "turtles_pro"
    # 9 shared + clip.asset (A); 9 + new.png/config.sh/2 cc33 files (B).
    assert head["Validated files"] == "10 -> 13 (+3)"

    snd = _named(by_title["Sounds"])
    assert snd["Sounds"] == "549 -> 551 (+2)"
    assert snd["Sound fragments"] == "578 -> 580 (+2)"
    assert snd["Audio container"].startswith("image.bin — ")

    # Every bucket lands where it should — and only there.  Paths are shown
    # relative to the shared game folder.
    music = _named(by_title["Music banks"])
    assert music["Modified"] == "1:"
    assert "image-sc09.bin" in report

    videos = _named(by_title["Videos"])
    assert videos["Deleted"] == "1:" and "clip.asset" in report

    images = _named(by_title["Images"])
    assert images["Added"] == "1:" and images["Modified"] == "1:"
    assert "gfx/new.png" in report and "gfx/logo.png" in report
    assert "score.png" not in report          # unchanged stays unlisted

    scenes = _named(by_title["Scenes"])
    assert scenes["Added"] == "1:" and scenes["Modified"] == "1:"
    assert "assets/cc33" in report and "assets/aa11" in report
    assert "bb22" not in report               # untouched scene stays unlisted
    # The changed scene ASSET counts as its scene, not as a loose video.
    assert "aa11/scene.assets/0.asset" not in report

    other = _named(by_title["Other files"])
    assert other["Added"] == "1:" and other["Modified"] == "1:"
    assert "config.sh" in report and "notes.txt" not in report

    adj = _named(by_title["Adjustments"])
    assert adj["Total"] == "7 (unchanged)"          # sans AD_INVALID
    assert adj["Added"] == "1:" and adj["Deleted"] == "1:"
    assert adj["Modified defaults"] == "1:"
    assert "AD_NEW_SETTING" in report
    assert "AD_ALLOW_HIGH_SCORES" in report
    assert "AD_FREE_PLAY: 0 -> 1" in report

    # The adjustments-only fixture ELF has no high-score board table: the
    # section says so instead of diffing junk.
    hs = _named(by_title["High scores"])
    assert "not readable" in hs["High scores"]


def test_compare_same_card_reports_no_changes(tmp_path, monkeypatch):
    name = "turtles_pro-1_58_0.Release.8G.sdcard.raw"
    a, _b = _two_cards(tmp_path, monkeypatch,
                       name_a=name, name_b="other.raw", spec_b=SPEC_A)
    sections = compare_cards(a, a)
    by_title = dict(sections)
    assert "(unchanged)" in _named(by_title["Sounds"])["Audio container"]
    for title in ("Music banks", "Videos", "Images", "Scenes",
                  "Other files"):
        assert _named(by_title[title]) == {"No changes": ""}


def test_compare_missing_manifest_degrades(tmp_path, monkeypatch):
    """A card without a readable .sidx still compares counts + firmware —
    only the file-level diff is (honestly) declared unavailable."""
    spec_b = {"turtles_pro": SPEC_B["turtles_pro"]}      # no /spk/index
    a, b = _two_cards(tmp_path, monkeypatch, spec_b=spec_b)
    sections = compare_cards(a, b)
    by_title = dict(sections)
    head = _named(by_title["Compared"])
    assert "image B" in head["File diff"]
    assert "Videos" not in by_title                      # no file buckets
    assert _named(by_title["Sounds"])["Sounds"] == "549 -> 551 (+2)"
    assert _named(by_title["Adjustments"])["Modified defaults"] == "1:"


def test_compare_different_games_warns(tmp_path, monkeypatch):
    files = {"image.bin": _container_header(100, 90), "x.png": b"P"}
    spec_b = _card_spec("led_zeppelin_pro", "led_zeppelin_pro-1_22_0.sidx",
                        files)
    a, b = _two_cards(tmp_path, monkeypatch, spec_b=spec_b,
                      name_b="led_zeppelin_pro-1_22_0.Release.8G.sdcard.raw")
    head = _named(dict(compare_cards(a, b))["Compared"])
    assert "different games" in head["Warning"]


def test_compare_uses_the_card_not_a_disagreeing_filename(tmp_path,
                                                          monkeypatch):
    """Card A is a relabelled 1.58.0 whose FILE claims 1.58.1.  The diff must
    read 1.58.0 -> 1.59.0 off the cards themselves, and say why the name in
    the picker looks different."""
    a, b = _two_cards(tmp_path, monkeypatch,
                      name_a="turtles_pro-1_58_1.1987.8G.sdcard.raw")
    head = _named(dict(compare_cards(a, b))["Compared"])
    assert head["Version"] == "1.58.0 -> 1.59.0"
    assert head["Filename version (A)"].startswith("named 1.58.1 but the "
                                                   "card says 1.58.0")
    assert "Filename version (B)" not in head       # B's name agrees


def test_compare_unopenable_card_reports_error(tmp_path):
    bad = tmp_path / "junk.raw"
    bad.write_bytes(b"junk")
    sections = compare_cards(str(bad), str(bad))
    assert sections[0][0] == "Error"
    assert sections[0][1][0][0] == "Image A"


def test_tri_and_score_rows():
    assert _tri({"a": 1, "b": 2, "c": 3}, {"b": 2, "c": 9, "d": 4}) \
        == (["d"], ["a"], ["c"])
    # High-score diff by slot label: default initials/player/score changes
    # each get named; added/deleted places listed by display name.
    a = {"GRAND CHAMPION": {"display": "GRAND CHAMPION", "initials": "JDB",
                            "player": "BORGIE", "score": 20000000},
         "HIGH SCORE #1": {"display": "HIGH SCORE #1", "initials": "AAA",
                           "player": "", "score": 10000000}}
    b = {"GRAND CHAMPION": {"display": "GRAND CHAMPION", "initials": "ZZZ",
                            "player": "BORGIE", "score": 25000000},
         "KAIJU CHAMPION": {"display": "KAIJU CHAMPION", "initials": "GOJ",
                            "player": "", "score": None}}
    rows = _score_rows(a, b)
    text = "\n".join("%s %s" % r for r in rows)
    assert "Places 2 (unchanged)" in text
    assert "KAIJU CHAMPION" in text and "HIGH SCORE #1" in text
    assert "initials JDB -> ZZZ" in text
    assert "default score 20,000,000 -> 25,000,000" in text
    assert _score_rows(None, b)[0][1].startswith("board not readable")


# ---------------------------------------------------------------------------
# Row refs + opening one listed file straight off the card (PAD-81)
# ---------------------------------------------------------------------------

def test_listed_file_rows_carry_the_card_they_are_on(tmp_path, monkeypatch):
    """Added/Modified point at B; Deleted points at A.

    THE SIDE IS THE WHOLE POINT.  A deleted file exists on exactly one of the
    two cards, and a ref that sent the Compare tab to image B for it would
    open nothing, every time — which is indistinguishable from a broken
    reader.  Count rows and the "… and N more" row get no ref at all: neither
    is a file.
    """
    a, b = _two_cards(tmp_path, monkeypatch)
    by_title = dict(compare_cards(a, b))

    images = by_title["Images"]
    by_path = {r["path"]: r for r in _refs(images)}
    assert by_path["turtles_pro/gfx/new.png"]["side"] == "B"      # added
    assert by_path["turtles_pro/gfx/logo.png"]["side"] == "B"     # modified
    # Every ref names a real manifest path and its own basename.
    for ref in _refs(images):
        assert ref["name"] == ref["path"].rsplit("/", 1)[-1]

    videos = by_title["Videos"]
    assert [(r["side"], r["path"]) for r in _refs(videos)] \
        == [("A", "turtles_pro/clip.asset")]                      # deleted

    # Count rows ("Added", "1:") carry nothing to open.
    assert all(len(r) == 2 for r in images if r[0])
    # Neither do the sections that are not files at all.
    for title in ("Compared", "Sounds", "Scenes", "Adjustments",
                  "High scores"):
        assert _refs(by_title[title]) == []


def test_extract_ref_writes_the_file_off_the_card(tmp_path, monkeypatch):
    """The bytes the ref names, out of the image, with no Extract."""
    a, b = _two_cards(tmp_path, monkeypatch)
    by_title = dict(compare_cards(a, b))
    ref = next(r for r in _refs(by_title["Images"])
               if r["path"].endswith("gfx/logo.png"))
    out = tmp_path / "opened"
    out.mkdir()
    written = extract_ref(b, ref, str(out))
    assert os.path.basename(written) == "logo.png"
    with open(written, "rb") as f:
        assert f.read() == b"PNG-LOGO-B"
    # The same ref against card A gets A's copy — this is how a Modified row
    # would be compared by eye, and it is the pair of bytes the digests
    # disagreed about.
    written_a = extract_ref(a, ref, str(tmp_path / "opened_a"))
    with open(written_a, "rb") as f:
        assert f.read() == b"PNG-LOGO-A"


def test_extract_ref_survives_a_stale_partition_index(tmp_path, monkeypatch):
    """A recorded index that no longer resolves must not become "not there".

    The report can outlive the card it describes, and the index is a hint.
    Every browsable partition is tried before the file is called missing.
    """
    a, b = _two_cards(tmp_path, monkeypatch)
    ref = next(r for r in _refs(dict(compare_cards(a, b))["Images"])
               if r["path"].endswith("gfx/logo.png"))
    ref = dict(ref, part=3)                       # never browsable
    written = extract_ref(b, ref, str(tmp_path / "stale"))
    with open(written, "rb") as f:
        assert f.read() == b"PNG-LOGO-B"


def test_extract_ref_refuses_a_file_the_card_does_not_have(tmp_path,
                                                           monkeypatch):
    """And writes nothing — an empty file the desktop then opens into an
    error dialog is the worst of both outcomes."""
    a, b = _two_cards(tmp_path, monkeypatch)
    out = tmp_path / "nope"
    out.mkdir()
    with pytest.raises(FileNotFoundError):
        extract_ref(b, {"path": "turtles_pro/gfx/not_here.png",
                        "part": None}, str(out))
    assert os.listdir(out) == []
    with pytest.raises(FileNotFoundError):
        extract_ref(b, {}, str(out))


def test_an_extensionless_video_gets_a_name_the_desktop_can_open(tmp_path,
                                                                 monkeypatch):
    """Spike 2 stores videos as ``0.asset``.

    A straight copy of one lands on a name Windows has no handler for, so
    "open the changed video" would fail on the FILE NAME rather than on
    anything real — while the report itself already identifies these by the
    same ``ftyp`` sniff.  Bytes nobody recognises keep the card's own name:
    a wrong extension hides a file instead of opening it.
    """
    files = dict(_FILES_A)
    files["clip.asset"] = _VIDEO_A                    # ftyp head
    files["mystery.asset"] = b"\x00" * 64             # nothing recognisable
    spec = _card_spec("turtles_pro", "turtles_pro-1_58_0.sidx", files)
    a, _b = _two_cards(tmp_path, monkeypatch, spec_a=spec, spec_b=spec,
                       name_b="other.raw")
    out = str(tmp_path / "opened")
    written = extract_ref(a, {"path": "turtles_pro/clip.asset", "part": None},
                          out)
    assert os.path.basename(written) == "clip.mp4"
    with open(written, "rb") as f:
        assert f.read() == _VIDEO_A
    kept = extract_ref(a, {"path": "turtles_pro/mystery.asset",
                           "part": None}, out)
    assert os.path.basename(kept) == "mystery.asset"
    # A name that already says what it is is left completely alone.
    png = extract_ref(a, {"path": "turtles_pro/gfx/logo.png", "part": None},
                      out)
    assert os.path.basename(png) == "logo.png"


# ---------------------------------------------------------------------------
# Sounds — the section a tester's Extract Both used to leave unchanged
# ---------------------------------------------------------------------------

def _extract_folder(root, wavs):
    """An extract folder holding ``{name: bytes}`` under ``audio/``, with the
    ``.checksums.md5`` baseline every real Extract leaves behind."""
    import hashlib

    from pinball_decryptor.core.checksums import CHECKSUMS_FILE
    os.makedirs(os.path.join(root, "audio"), exist_ok=True)
    lines = []
    for name, data in wavs.items():
        with open(os.path.join(root, "audio", name), "wb") as f:
            f.write(data)
        lines.append("audio/%s\t%s" % (name, hashlib.md5(data).hexdigest()))
    with open(os.path.join(root, CHECKSUMS_FILE), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return str(root)


def test_sounds_never_judges_the_audio_by_the_container_digest(tmp_path,
                                                               monkeypatch):
    """image.bin is repacked and re-keyed on EVERY Stern build, so its stored
    digest differs between any two releases whether or not a sound changed.
    The section used to read that as "sounds were re-encoded or replaced" —
    a guaranteed false alarm — and send the user off to extract both cards."""
    a, b = _two_cards(tmp_path, monkeypatch)
    snd = _named(dict(compare_cards(a, b))["Sounds"])
    report = as_text(compare_cards(a, b), title="Compare Report")

    assert "re-encoded or replaced" not in report
    assert snd["Container bytes"].startswith("differ — as they do between ANY")
    # ...and the section says what WOULD answer the question, in a way the
    # tab can actually deliver on.
    assert "Extract Both" in snd["Per-sound diff"]
    assert "either card" in snd["Per-sound diff"]


def test_one_extract_found_names_the_missing_side(tmp_path, monkeypatch):
    a, b = _two_cards(tmp_path, monkeypatch)
    only_a = _extract_folder(tmp_path / "xa", {"idx0001.wav": b"one"})
    snd = _named(dict(compare_cards(a, b, only_a, None))["Sounds"])
    assert "image B" in snd["Per-sound diff"]


def test_two_extracts_turn_the_section_into_a_per_sound_diff(tmp_path,
                                                             monkeypatch):
    """The whole point: after Extract Both, Compare lists the sounds."""
    a, b = _two_cards(tmp_path, monkeypatch)
    xa = _extract_folder(tmp_path / "xa", {
        "idx0001.wav": b"same", "idx0002.wav": b"stock", "idx0003.wav": b"gone",
        "idx0004.wav": b"shifted"})
    xb = _extract_folder(tmp_path / "xb", {
        "idx0001.wav": b"same", "idx0002.wav": b"MODDED",
        "idx0005.wav": b"shifted", "idx0006.wav": b"brand new"})
    rows = dict(compare_cards(a, b, xa, xb))["Sounds"]
    snd = _named(rows)
    report = as_text([("Sounds", rows)], title="Compare Report")

    assert snd["Extract A"] == xa and snd["Extract B"] == xb
    assert snd["Decoded sounds"] == "4 (unchanged)"
    assert snd["Unchanged"] == ("1 of 4 sounds are identical and still in "
                                "the same slot")
    assert snd["Changed"] == "1:" and snd["Moved"] == "1:"
    assert snd["Added"] == "1:" and snd["Removed"] == "1:"
    assert "idx0004.wav  ->  idx0005.wav" in report      # same audio, new slot
    assert "idx0006.wav" in report and "idx0003.wav" in report

    # Every listed sound carries a ref pointing at the file on disk, so the
    # tab's double-click plays it instead of decoding it a second time.
    refs = _refs(rows)
    assert len(refs) == 4
    assert {r["side"] for r in refs} == {"A", "B"}
    for ref in refs:
        assert os.path.isfile(ref["disk"])
        assert extract_ref("unused.raw", ref, str(tmp_path)) == ref["disk"]


def test_two_identical_extracts_say_so(tmp_path, monkeypatch):
    a, b = _two_cards(tmp_path, monkeypatch)
    wavs = {"idx0001.wav": b"one", "idx0002.wav": b"two"}
    xa = _extract_folder(tmp_path / "xa", wavs)
    xb = _extract_folder(tmp_path / "xb", wavs)
    snd = _named(dict(compare_cards(a, b, xa, xb))["Sounds"])
    assert snd["No changes"] == "every sound decodes identically on both cards"


def test_an_audio_less_extract_says_which_one_and_why(tmp_path, monkeypatch):
    """A video/images-only Extract has no audio folder.  Saying "no changes"
    there would be a lie the user cannot see through."""
    a, b = _two_cards(tmp_path, monkeypatch)
    xa = _extract_folder(tmp_path / "xa", {"idx0001.wav": b"one"})
    xb = str(tmp_path / "xb")
    os.makedirs(xb)
    snd = _named(dict(compare_cards(a, b, xa, xb))["Sounds"])
    assert "image B" in snd["Per-sound diff"]
    assert "Audio switched off" in snd["Per-sound diff"]


def test_a_sound_that_left_the_extract_folder_says_so(tmp_path):
    """Refs outlive the folder they name — a deleted extract must report,
    not hand back a path to nothing."""
    with pytest.raises(FileNotFoundError):
        extract_ref("unused.raw",
                    {"disk": str(tmp_path / "audio" / "idx0001.wav"),
                     "name": "idx0001.wav", "side": "B"}, str(tmp_path))


# ---------------------------------------------------------------------------
# The report lists everything; the tab decides how much to show (PAD-86)
# ---------------------------------------------------------------------------

def test_a_long_change_list_is_not_truncated_by_the_report(tmp_path,
                                                           monkeypatch):
    """"Would it be possible to display more than the first 12 entries for
    each asset category?"  It is the RENDERER's call now, so the report has
    to carry every entry — and one blank-named row per entry, which is what
    marks them as items of the count row above (image_info.group_rows).
    """
    from pinball_decryptor.core.image_info import group_rows

    a, b = _two_cards(tmp_path, monkeypatch)
    xa = _extract_folder(tmp_path / "xa",
                         {"idx%04d.wav" % i: b"old %d" % i
                          for i in range(40)})
    xb = _extract_folder(tmp_path / "xb",
                         {"idx%04d.wav" % i: b"new %d" % i
                          for i in range(40)})
    rows = dict(compare_cards(a, b, xa, xb))["Sounds"]

    groups = dict((head[0], items) for head, items in group_rows(rows))
    assert groups["Changed"] and len(groups["Changed"]) == 40
    assert all(r[0] == "" for r in groups["Changed"])
    # …and Copy Report is a copy of all forty, not of a truncation.
    text = as_text([("Sounds", rows)], title="Compare Report")
    for i in range(40):
        assert "idx%04d.wav" % i in text
    assert "more" not in text


def test_the_codec_lead_in_is_named_when_it_had_to_be_set_aside(tmp_path,
                                                                monkeypatch):
    """Silently ignoring bytes is how a diff stops being trustworthy.  When
    the repack case fires, the section says which bytes and why."""
    import struct

    def wav(first):
        body = struct.pack("<h", first) + b"".join(
            struct.pack("<h", s) for s in range(1, 300))
        return (b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVE"
                + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 44100,
                                        88200, 2, 16)
                + b"data" + struct.pack("<I", len(body)) + body)

    a, b = _two_cards(tmp_path, monkeypatch)
    xa = _extract_folder(tmp_path / "xa", {"idx0001.wav": wav(111)})
    xb = _extract_folder(tmp_path / "xb", {"idx0001.wav": wav(-9)})
    snd = _named(dict(compare_cards(a, b, xa, xb))["Sounds"])

    assert snd["Unchanged"] == ("1 of 1 sounds are identical and still in "
                                "the same slot")
    assert snd["Codec lead-in"].startswith("1 sound(s) matched only once "
                                           "their first frame was set aside")
    # And it stays off the report entirely when nothing needed it.
    xc = _extract_folder(tmp_path / "xc", {"idx0001.wav": wav(111)})
    assert "Codec lead-in" not in \
        _named(dict(compare_cards(a, b, xa, xc))["Sounds"])


def test_the_frame_shift_is_named_when_it_had_to_be_set_aside(tmp_path,
                                                              monkeypatch):
    """Its own row, not folded into the lead-in one: a different thing was
    set aside (a whole frame of SHIFT, not one frame's value) for a
    different reason, and 1,356 Venom sounds hung on it."""
    import struct

    def wav(samples):
        body = b"".join(struct.pack("<h", s) for s in samples)
        return (b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVE"
                + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 44100,
                                        88200, 2, 16)
                + b"data" + struct.pack("<I", len(body)) + body)

    tone = list(range(1, 300))
    a, b = _two_cards(tmp_path, monkeypatch)
    xa = _extract_folder(tmp_path / "xa", {"idx0001.wav": wav([-9]
                                                              + tone[:-1])})
    xb = _extract_folder(tmp_path / "xb", {"idx0001.wav": wav(tone)})
    snd = _named(dict(compare_cards(a, b, xa, xb))["Sounds"])

    assert snd["Unchanged"] == ("1 of 1 sounds are identical and still in "
                                "the same slot")
    assert snd["Codec frame shift"].startswith(
        "1 sound(s) matched once one card was read a frame later")
    assert "Codec lead-in" not in snd
    # And it stays off the report entirely when nothing needed it.
    xc = _extract_folder(tmp_path / "xc", {"idx0001.wav": wav([-9]
                                                              + tone[:-1])})
    assert "Codec frame shift" not in \
        _named(dict(compare_cards(a, b, xa, xc))["Sounds"])
