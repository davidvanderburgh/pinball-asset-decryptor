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

from pinball_decryptor.core.image_info import as_text
from pinball_decryptor.plugins.stern.compare import (_score_rows, _tri,
                                                     compare_cards)
from pinball_decryptor.plugins.stern.sidx import SIDX_KEY, manifest_files
from tests.test_image_info import _FAKE_MP4, _container_header
from tests.test_stern_adjustments import make_elf


# ---------------------------------------------------------------------------
# A .sidx whose records carry REAL sizes + MD5s (unlike test_image_info's
# zero-payload _make_sidx — the compare diffs by these fields).
# ---------------------------------------------------------------------------

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

    head = dict(by_title["Compared"])
    assert head["Version"] == "1.58.0 -> 1.59.0"
    assert head["Game folder"] == "turtles_pro"
    # 9 shared + clip.asset (A); 9 + new.png/config.sh/2 cc33 files (B).
    assert head["Validated files"] == "10 -> 13 (+3)"

    snd = dict(by_title["Sounds"])
    assert snd["Sounds"] == "549 -> 551 (+2)"
    assert snd["Sound fragments"] == "578 -> 580 (+2)"
    assert snd["Audio container"].startswith("image.bin changed")

    # Every bucket lands where it should — and only there.  Paths are shown
    # relative to the shared game folder.
    music = dict(by_title["Music banks"])
    assert music["Modified"] == "1:"
    assert "image-sc09.bin" in report

    videos = dict(by_title["Videos"])
    assert videos["Deleted"] == "1:" and "clip.asset" in report

    images = dict(by_title["Images"])
    assert images["Added"] == "1:" and images["Modified"] == "1:"
    assert "gfx/new.png" in report and "gfx/logo.png" in report
    assert "score.png" not in report          # unchanged stays unlisted

    scenes = dict(by_title["Scenes"])
    assert scenes["Added"] == "1:" and scenes["Modified"] == "1:"
    assert "assets/cc33" in report and "assets/aa11" in report
    assert "bb22" not in report               # untouched scene stays unlisted
    # The changed scene ASSET counts as its scene, not as a loose video.
    assert "aa11/scene.assets/0.asset" not in report

    other = dict(by_title["Other files"])
    assert other["Added"] == "1:" and other["Modified"] == "1:"
    assert "config.sh" in report and "notes.txt" not in report

    adj = dict(by_title["Adjustments"])
    assert adj["Total"] == "7 (unchanged)"          # sans AD_INVALID
    assert adj["Added"] == "1:" and adj["Deleted"] == "1:"
    assert adj["Modified defaults"] == "1:"
    assert "AD_NEW_SETTING" in report
    assert "AD_ALLOW_HIGH_SCORES" in report
    assert "AD_FREE_PLAY: 0 -> 1" in report

    # The adjustments-only fixture ELF has no high-score board table: the
    # section says so instead of diffing junk.
    hs = dict(by_title["High scores"])
    assert "not readable" in hs["High scores"]


def test_compare_same_card_reports_no_changes(tmp_path, monkeypatch):
    name = "turtles_pro-1_58_0.Release.8G.sdcard.raw"
    a, _b = _two_cards(tmp_path, monkeypatch,
                       name_a=name, name_b="other.raw", spec_b=SPEC_A)
    sections = compare_cards(a, a)
    by_title = dict(sections)
    assert dict(by_title["Sounds"])["Audio container"] \
        == "image.bin unchanged"
    for title in ("Music banks", "Videos", "Images", "Scenes",
                  "Other files"):
        assert dict(by_title[title]) == {"No changes": ""}


def test_compare_missing_manifest_degrades(tmp_path, monkeypatch):
    """A card without a readable .sidx still compares counts + firmware —
    only the file-level diff is (honestly) declared unavailable."""
    spec_b = {"turtles_pro": SPEC_B["turtles_pro"]}      # no /spk/index
    a, b = _two_cards(tmp_path, monkeypatch, spec_b=spec_b)
    sections = compare_cards(a, b)
    by_title = dict(sections)
    head = dict(by_title["Compared"])
    assert "image B" in head["File diff"]
    assert "Videos" not in by_title                      # no file buckets
    assert dict(by_title["Sounds"])["Sounds"] == "549 -> 551 (+2)"
    assert dict(by_title["Adjustments"])["Modified defaults"] == "1:"


def test_compare_different_games_warns(tmp_path, monkeypatch):
    files = {"image.bin": _container_header(100, 90), "x.png": b"P"}
    spec_b = _card_spec("led_zeppelin_pro", "led_zeppelin_pro-1_22_0.sidx",
                        files)
    a, b = _two_cards(tmp_path, monkeypatch, spec_b=spec_b,
                      name_b="led_zeppelin_pro-1_22_0.Release.8G.sdcard.raw")
    head = dict(dict(compare_cards(a, b))["Compared"])
    assert "different games" in head["Warning"]


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
