"""PAD-1100 (Brombomb): a compact multi-boot card was recorded as its OTHER game's build.

``mkmulticard.py --layout store`` keeps the second game as a whole tree inside the primary's
p3 (``img1/spk/index/*.sidx`` and all). The extract's stamps took whichever ``.sidx`` the
directory listed first or the walk met last, so a GZ 1.16 + Heisei card's project said
godzilla_pro 1.13, and Load modes refused: "Modes of your own can't be made for godzilla_pro
1.13.0 yet". Every reader now takes the primary's own versioned index, and a project already
recorded wrong is put right by the Modes tab's read of its card.
"""

import json
import os

from pinball_decryptor.plugins.stern import info, mode_project as MP, mode_tryit, stock_prints
from pinball_decryptor.plugins.stern.explorer import CardImage
from tests._ext4_fake import FakeExt4Reader, install_fake_reader, write_fake_card

#: A compact (store layout) dual-boot card's p3, in the directory order that misled the old
#: readers: the bare godzilla_pro.sidx listed before the versioned one, and img1 met last by
#: the depth-first walk.
STORE_TREE = {
    "img1": {"spk": {"index": {"godzilla_pro-1_13_0.sidx": b"SIDX113"}},
             "godzilla_pro": {"image.bin": b"\x01" * 64, "game": b"\x7fELF113"}},
    ".blobs": {"ab": {"abcdef": b"pooled"}},
    "spk": {"index": {"godzilla_pro-1_13_0.sidx": b"SIDX113", "godzilla_pro.sidx": b"SIDX",
                      "godzilla_pro-1_16_0.sidx": b"SIDX116"}},
    "godzilla_pro": {"image.bin": b"\x00" * 64, "game": b"\x7fELF116"},
}


def test_index_name_takes_the_live_index():
    # a card updated from 1.13 can keep the index it replaced: Stern's bare <title>.sidx link
    # names the live one, else the newest wins - never the first by name
    names = ["godzilla_pro-1_13_0.sidx", "godzilla_pro-1_16_0.sidx", "godzilla_pro.sidx"]
    assert info.index_name(names) == "godzilla_pro-1_16_0.sidx"
    assert info.index_name(names, {"godzilla_pro.sidx": "godzilla_pro-1_13_0.sidx"}) ==         "godzilla_pro-1_13_0.sidx"
    assert info.index_name(names, {"godzilla_pro.sidx": "gone-9_9_9.sidx"}) ==         "godzilla_pro-1_16_0.sidx"
    assert info.index_name(["x-1_9_0.sidx", "x-1_10_0.sidx"]) == "x-1_10_0.sidx"


def test_index_name_takes_the_versioned_index_whatever_the_order():
    assert info.index_name(["godzilla_pro.sidx", "godzilla_pro-1_16_0.sidx"]) == \
        "godzilla_pro-1_16_0.sidx"
    assert info.index_name(["godzilla_pro-1_16_0.sidx", "godzilla_pro.sidx"]) == \
        "godzilla_pro-1_16_0.sidx"
    assert info.index_name(["turtles.sidx"]) == "turtles.sidx"
    assert info.index_name([]) == ""


def test_other_image_paths():
    for p in ("/img1/spk/index/x.sidx", "img2/godzilla_pro/game", "/.blobs/ab/cd", "img1"):
        assert info.other_image_path(p), p
    for p in ("/spk/index/x.sidx", "/godzilla_pro/img1", "/image1/x", "/imgx/y"):
        assert not info.other_image_path(p), p


def test_walk_takes_the_primary_index_and_files_only():
    found = info._walk_partition(FakeExt4Reader(STORE_TREE), sniff=False)
    assert found["sidx_path"] == "/spk/index/godzilla_pro-1_16_0.sidx"
    assert found["image_bin_path"] == "/godzilla_pro/image.bin"
    assert list(found["game_elves"]) == ["/godzilla_pro/game"]
    nodes = stock_prints._file_nodes(FakeExt4Reader(STORE_TREE))
    assert not [p for p in nodes if p.startswith(("img1/", ".blobs/"))]
    assert "spk/index/godzilla_pro-1_16_0.sidx" in nodes


def test_card_readers_agree_on_the_primary_build(tmp_path, monkeypatch):
    install_fake_reader(monkeypatch, STORE_TREE)
    card = write_fake_card(tmp_path / "GZ Heisei dual boot.raw")
    # the extract's stamp, the Modes tab's probe and its read all say 1.16
    assert info.card_version_probe(card) == ("1.16.0", True)
    MP._PROBED.clear()
    assert MP.probe_card_title(card) == ("godzilla_pro", "1.16.0")
    game, version, _part = mode_tryit.card_title(card)
    assert (game, version) == ("godzilla_pro", "1.16.0")
    with CardImage(card) as img:                     # what the old readers took first
        assert [e.name for e in img.list_dir(1, "/spk/index")][0] == "godzilla_pro-1_13_0.sidx"
    with CardImage(card) as img:                     # ...and the Write path's manifest
        from pinball_decryptor.plugins.stern import sidx
        assert sidx.find_sidx(img.reader(1))[0] == "/spk/index/godzilla_pro-1_16_0.sidx"


def _project(tmp_path, card, stock_sidx, card_version=None):
    proj = tmp_path / "proj"
    proj.mkdir()
    rec = {"input_path": card, "input_name": os.path.basename(card), "size": 1,
           "stock": {"status": "modified", "label": "Godzilla Pro 1.13", "sidx": stock_sidx,
                     "text": "Extracted from a modified Godzilla Pro 1.13 card."}}
    if card_version:
        rec["card_version"] = card_version
    (proj / ".extract_source.json").write_text(json.dumps(rec), encoding="utf-8")
    return str(proj)


def test_a_project_recorded_as_the_other_image_is_put_right(tmp_path):
    card = str(tmp_path / "GZ Heisei dual boot.raw")
    open(card, "wb").close()
    proj = _project(tmp_path, card, "godzilla_pro-1_13_0.sidx")
    before = MP.project_card(proj)
    assert before.label() == "godzilla_pro 1.13.0"
    # the reporter's refusal: no 1.13 port, so Load modes / Copy to stop
    assert MP.project_profile(proj)[1] is None
    assert MP.heal_card_record(proj, before, "godzilla_pro", "1.16.0") is True
    after = MP.project_card(proj)
    assert after.label() == "godzilla_pro 1.16.0" and after.source == MP.INDEX_SOURCE
    assert MP.project_profile(proj)[1] is not None             # the shipped 1.16 port
    rec = json.loads((tmp_path / "proj" / ".extract_source.json").read_text(encoding="utf-8"))
    assert rec["card_version"] == "1.16.0"
    assert rec["stock"] == {"sidx": "godzilla_pro-1_16_0.sidx", "status": "unknown",
                            "label": "", "text": ""}
    # once right, nothing more to do (no refresh loop)
    assert MP.heal_card_record(proj, after, "godzilla_pro", "1.16.0") is False


def test_heal_leaves_other_cards_alone(tmp_path):
    card = str(tmp_path / "a.raw")
    open(card, "wb").close()
    proj = _project(tmp_path, card, "godzilla_pro-1_16_0.sidx")
    right = MP.project_card(proj)
    assert MP.heal_card_record(proj, right, "godzilla_pro", "1.16.0") is False
    # a read of some other image (a Try it on card) never rewrites the project's record
    other = MP.ProjectCard(str(tmp_path / "other.raw"), "godzilla_pro", "1.13.0", "x")
    assert MP.heal_card_record(proj, other, "godzilla_pro", "1.16.0") is False
    assert MP.project_card(proj).label() == "godzilla_pro 1.16.0"


class _Read:
    def __init__(self, game, version, origin):
        self.game, self.version, self.port_origin = game, version, origin


def test_the_modes_tab_heals_to_the_build_its_port_proved(tmp_path):
    """The tab's read found the shipped godzilla_pro 1.16 port ON the card's program while the
    record (and even the card's index) said 1.13: the record follows the program."""
    from pinball_decryptor.webui.tabs.modes import ModesTab
    card = str(tmp_path / "GZ Heisei dual boot.raw")
    open(card, "wb").close()
    proj = _project(tmp_path, card, "godzilla_pro-1_13_0.sidx", card_version="1.13.0")
    before = MP.project_card(proj)
    prof = MP.profile_for_card("godzilla_pro", "1.16.0")

    class Tab:
        said = []
        _say = said.append
        _card_key = staticmethod(ModesTab._card_key)
        _title_files_sig = lambda self, p: ("sig", p)
    tab = Tab()
    got, label = ModesTab._heal_card_record(tab, proj, before, _Read("godzilla_pro", "1.13.0",
                                                                      "shipped"), prof,
                                            "Godzilla Pro 1.13")
    assert got.label() == "godzilla_pro 1.16.0" and label == "Godzilla Pro 1.16"
    assert MP.project_profile(proj)[1].label == "Godzilla Pro 1.16"
    assert "the record now says so" in tab.said[0]
    # a port derived for whatever the index claims proves nothing: no heal from it
    proj2 = tmp_path / "p2"
    proj2.mkdir()
    (proj2 / ".extract_source.json").write_text(json.dumps(
        {"input_path": card, "card_version": "1.13.0",
         "stock": {"sidx": "godzilla_pro-1_13_0.sidx", "status": "modified"}}), encoding="utf-8")
    c2 = MP.project_card(str(proj2))
    got2, _l = ModesTab._heal_card_record(tab, str(proj2), c2, _Read("godzilla_pro", "1.13.0",
                                                                      "derived"), prof, "x")
    assert got2 is c2 and MP.project_card(str(proj2)).label() == "godzilla_pro 1.13.0"
