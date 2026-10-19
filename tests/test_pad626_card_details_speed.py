"""PAD-626: Select card's "Card details" tile took a really long time.

A cold read of a card on a spinning disk was almost all video sniffing - one
12-byte read of every candidate file, each a seek (93 of 96 s on Stranger
Things, 8,500 files).  Now:

* the official-release table records which of a release's files are
  videos, so a file the card's manifest and size still call stock is not
  opened at all (an official card sniffs nothing, a build only what it
  changed);
* the report shows as soon as everything but the video count is read
  (``partial``), the count following;
* the finished report is kept beside the card's cached pictures, so the
  next look at the same card file shows it at once;
* the adjustment-table and high-score-board searches no longer walk every
  word of the game program in Python.
"""

import threading
import time

from pinball_decryptor.core import image_info
from pinball_decryptor.plugins.stern import stock_prints as sp
from pinball_decryptor.webui import card_preview as CP
from tests._ext4_fake import FakeExt4Reader
from tests.test_image_info import _FAKE_MP4, _FakeMfr
from tests.test_stern_stock_prints import (CARD, FOLDER, SIDX, _cards,
                                           _official_files, _table)
from tests.webui_harness import web_app

CLIP = "%s/assets/aa11/scene.assets/0.asset" % FOLDER


def _count_sniffs(monkeypatch):
    """The 12-byte video sniffs the probe makes, by file size."""
    seen = []
    real = FakeExt4Reader.peek

    def peek(self, node, n=16):
        if n == 12:
            seen.append(node["size"])
        return real(self, node, n)

    monkeypatch.setattr(FakeExt4Reader, "peek", peek)
    return seen


def _rows(sections, title):
    return dict((r[0], r[1]) for t, rows in sections if t == title
                for r in rows)


# ------------------------------------------------ the table knows the videos

def test_a_release_records_its_videos(tmp_path, monkeypatch):
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX))
    _key, rel = sp.make_release(cards["official"])
    assert rel["videos"] == [CLIP]
    assert sp.video_set(rel) == {CLIP}
    # a table made before PAD-626 has no record of them
    assert sp.video_set({"files": {}}) is None


def test_an_official_card_counts_its_videos_without_opening_them(
        tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern.info import card_info
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX))
    _table(tmp_path, monkeypatch, cards["official"])
    sniffs = _count_sniffs(monkeypatch)
    sections = card_info(cards["official"])
    assert _rows(sections, "Assets on Card")["Videos"] == "1"
    assert _rows(sections, "Firmware")["Official release"].startswith(
        "Official Turtles Pro 1.59")
    assert sniffs == []


def test_a_build_sniffs_only_the_files_it_changed(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern.info import card_info
    built = _official_files()
    built["assets/aa11/scene.assets/0.asset"] = _FAKE_MP4 + b"a longer clip"
    built["assets/cc33/scene.assets/0.asset"] = _FAKE_MP4 + b"a new one"
    built["assets/cc33/scene.assets/1.asset"] = b"\0" * 0x1000  # not a video
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX),
                   built=("custom.raw", built, SIDX))
    _table(tmp_path, monkeypatch, cards["official"])
    sniffs = _count_sniffs(monkeypatch)
    sections = card_info(cards["built"])
    assert _rows(sections, "Assets on Card")["Videos"] == "2"
    assert sorted(sniffs) == sorted([0x1000, len(_FAKE_MP4) + 13,
                                     len(_FAKE_MP4) + 9])


def test_a_stale_manifest_record_is_sniffed_not_trusted(tmp_path,
                                                        monkeypatch):
    """A card that replaced a file but kept Stern's record for it (DragonRR's
    Heisei card): the size on the card disagrees, so the file is opened."""
    from tests._ext4_fake import write_fake_card
    from tests.test_stern_compare import _card_spec, _install_readers_by_card
    from pinball_decryptor.plugins.stern.info import card_info
    official = str(write_fake_card(tmp_path / CARD))
    heisei = str(write_fake_card(tmp_path / "Heisei.raw"))
    spec = _card_spec(FOLDER, SIDX, _official_files())
    # a picture where the clip was, Stern's record for the clip kept
    spec[FOLDER]["assets"]["aa11"]["scene.assets"]["0.asset"] = b"\0" * 0x1100
    _install_readers_by_card(monkeypatch, {
        CARD: _card_spec(FOLDER, SIDX, _official_files()),
        "Heisei.raw": spec})
    _table(tmp_path, monkeypatch, official)
    sniffs = _count_sniffs(monkeypatch)
    assert _rows(card_info(heisei), "Assets on Card")["Videos"] == "0"
    assert sniffs == [0x1100]


def test_a_table_without_videos_sniffs_as_before(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern.info import card_info
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX))
    key, rel = sp.make_release(cards["official"])
    del rel["videos"]
    path = str(tmp_path / "old.json.xz")
    sp.save_table({key: rel}, path)
    monkeypatch.setattr(sp, "TABLE_PATH", path)
    sniffs = _count_sniffs(monkeypatch)
    assert _rows(card_info(cards["official"]),
                 "Assets on Card")["Videos"] == "1"
    assert len(sniffs) == 1


def test_the_shipped_table_knows_every_releases_videos():
    table = sp.load_table()
    for key, rel in table.items():
        vids = sp.video_set(rel)
        assert vids is not None, key
        assert vids <= set(rel["files"]), key
    # Godzilla LE 1.16: the count the card's own sniff gives
    assert len(sp.video_set(table["godzilla_le-1_16_0.sidx"])) == 658


# ------------------------------------------------------ the report in stages

def test_the_report_comes_early_without_the_video_count(tmp_path,
                                                        monkeypatch):
    from pinball_decryptor.plugins.stern.info import VIDEOS_COUNTING, card_info
    cards = _cards(tmp_path, monkeypatch,
                   official=(CARD, _official_files(), SIDX))
    _table(tmp_path, monkeypatch, cards["official"])
    early = []
    full = card_info(cards["official"], partial=early.append)
    assert len(early) == 1
    first = early[0]
    assert _rows(first, "Assets on Card")["Videos"] == VIDEOS_COUNTING
    # the official-release row needs the videos: it comes with them
    assert "Official release" not in _rows(first, "Firmware")
    assert _rows(first, "Firmware")["Version"].startswith("1.59.0")
    assert _rows(full, "Assets on Card")["Videos"] == "1"
    assert "Official release" in _rows(full, "Firmware")
    # the same sections, in the same order, once the count is in
    assert [t for t, _r in first] == [t for t, _r in full]


def test_collect_passes_partial_only_to_a_plugin_that_takes_it(tmp_path):
    img = tmp_path / "game.img"
    img.write_bytes(b"\x00" * 10)
    got = []

    class _Staged(_FakeMfr):
        def image_info(self, path, assets_dir=None, partial=None):
            partial([("Firmware", [("Version", "?")])])
            return [("Firmware", [("Version", "1.0")])]

    full = image_info.collect(_Staged(), str(img), partial=got.append)
    assert [t for t, _r in got[0]] == ["File", "Detection", "Firmware"]
    assert _rows(got[0], "Firmware")["Version"] == "?"
    assert _rows(full, "Firmware")["Version"] == "1.0"
    # a plugin without the keyword is called as before
    got.clear()
    image_info.collect(_FakeMfr(extra=[("X", [("a", "b")])]), str(img),
                       partial=got.append)
    assert got == []

    def boom(_s):
        raise RuntimeError("the page went away")

    # a partial that fails never costs the full report
    assert _rows(image_info.collect(_Staged(), str(img), partial=boom),
                 "Firmware")["Version"] == "1.0"


# ------------------------------------------------------ the Select card tab

def _card(tmp_path, name="card.raw"):
    p = tmp_path / name
    p.write_bytes(b"\0" * 4096)
    return str(p)


def _wait(w, pred, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        info = w.state("card").get("info") or {}
        if pred(info):
            return info
        time.sleep(0.02)
    raise AssertionError("never: %r" % (w.state("card").get("info"),))


def _staged_collect(monkeypatch, tmp_path, gate, calls):
    def collect(mfr, path, assets_dir=None, partial=None):
        calls.append(path)
        if partial is not None:
            partial([("Assets on Card", [("Videos", "counting…")])])
        gate.wait(10)
        return [("Assets on Card", [("Videos", "658")])]

    monkeypatch.setattr(image_info, "collect", collect)
    monkeypatch.setattr(CP, "cache_root", lambda: str(tmp_path / "cache"))


def test_the_tile_shows_the_early_report_then_the_full_one(tmp_path,
                                                          monkeypatch):
    card = _card(tmp_path)
    gate, calls = threading.Event(), []
    _staged_collect(monkeypatch, tmp_path, gate, calls)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        info = _wait(w, lambda i: i.get("state") == "partial")
        assert info["sections"][0]["rows"] == [["Videos", "counting…"]]
        assert info["status"] == "Counting the videos…"
        # nothing to copy until the report is whole
        assert w.call("card.info_copy") == ""
        gate.set()
        info = _wait(w, lambda i: i.get("state") == "ready")
        assert info["sections"][0]["rows"] == [["Videos", "658"]]
        assert info["status"] == ""
        assert "658" in w.call("card.info_copy")


def test_the_next_look_at_the_same_card_is_instant(tmp_path, monkeypatch):
    card = _card(tmp_path)
    gate, calls = threading.Event(), []
    gate.set()
    _staged_collect(monkeypatch, tmp_path, gate, calls)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        _wait(w, lambda i: i.get("state") == "ready")
    assert len(calls) == 1
    # the app opened again on the same card: shown at once, nothing read
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        info = w.state("card")["info"]
        assert info["state"] == "ready"
        assert info["sections"][0]["rows"] == [["Videos", "658"]]
    assert len(calls) == 1
    # Refresh reads the card again
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        w.call("card.refresh")
        _wait(w, lambda i: i.get("state") == "ready")
    assert len(calls) == 2


def test_a_changed_card_file_or_app_is_read_again(tmp_path, monkeypatch):
    import os
    from pinball_decryptor.webui.tabs import card as card_tab
    card = _card(tmp_path)
    gate, calls = threading.Event(), []
    gate.set()
    _staged_collect(monkeypatch, tmp_path, gate, calls)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        _wait(w, lambda i: i.get("state") == "ready")
    # written to: another file as far as the kept report is concerned
    st = os.stat(card)
    os.utime(card, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        _wait(w, lambda i: i.get("state") == "ready")
    assert len(calls) == 2
    # another build of the app may read more: its own report
    real = card_tab._info_stamp
    monkeypatch.setattr(card_tab, "_info_stamp",
                        lambda m, a: dict(real(m, a), app="9.9.9"))
    with web_app(tmp_path, mfr="stern") as w:
        w.call("card.look", card)
        _wait(w, lambda i: i.get("state") == "ready")
    assert len(calls) == 3


def test_a_report_that_failed_is_not_kept(tmp_path, monkeypatch):
    card = _card(tmp_path)
    calls = []

    def collect(mfr, path, assets_dir=None, partial=None):
        calls.append(path)
        return [("Firmware", [("Card read", "Could not open: busy")])]

    monkeypatch.setattr(image_info, "collect", collect)
    monkeypatch.setattr(CP, "cache_root", lambda: str(tmp_path / "cache"))
    for _ in range(2):
        with web_app(tmp_path, mfr="stern") as w:
            w.call("card.look", card)
            _wait(w, lambda i: i.get("state") == "ready")
    assert len(calls) == 2


def test_the_next_look_does_not_read_the_games_again(tmp_path, monkeypatch):
    """With the picture cached, the games on the card were the one read left
    in the preview: the glass said "Reading the card…" over a report that
    was already shown."""
    card = _card(tmp_path)
    gate, calls, games = threading.Event(), [], []
    gate.set()
    _staged_collect(monkeypatch, tmp_path, gate, calls)
    monkeypatch.setattr(CP, "games_on",
                        lambda p: games.append(p) or ["Godzilla LE"])
    monkeypatch.setattr(CP, "splash_png", lambda p, out: {
        "src": str(tmp_path / "splash.png"), "w": 1360, "h": 768,
        "kind": "splash"})
    for _ in range(2):
        with web_app(tmp_path, mfr="stern") as w:
            w.call("card.look", card)
            _wait(w, lambda i: i.get("state") == "ready")
            end = time.time() + 20
            while (w.state("card").get("preview") or {}).get(
                    "state") != "ready" and time.time() < end:
                w.drain()
                time.sleep(0.02)
            assert w.state("card")["preview"]["state"] == "ready"
    assert games == [card]
