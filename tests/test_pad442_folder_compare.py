"""PAD-442 — compare two project folders on the Compare tab.

A tester, versioning a mod: "compare two card image files (or two extract
folders) and report the differences between the assets — which videos are
different, which audio is different … to ensure everything is in there as
intended (or not in there!)".  The card half was there (Stern Spike 2); this
is the folder half, for every manufacturer that extracts.

Covered here: what the report lists and what it leaves out
(:mod:`core.folder_compare`), that it reads the files as they are NOW rather
than the extract's baseline, the Stern sounds pairing by slot through the
same diff the card report uses, and the tab driving it.
"""

import json
import os
import struct
import time

import pytest

from pinball_decryptor.core import folder_compare, hashcache
from pinball_decryptor.core.checksums import CHECKSUMS_FILE, md5_file


def put(root, rel, data):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def wav(fill, frames=200):
    """A mono 16-bit WAV whose samples are all *fill*."""
    body = struct.pack("<h", fill) * frames
    return (b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16)
            + b"data" + struct.pack("<I", len(body)) + body)


def sections(secs):
    return {title: rows for title, rows in secs}


def items(rows, head):
    """The item rows listed under the count row *head*."""
    out, inside = [], False
    for row in rows:
        if row[0]:
            inside = row[0] == head
        elif inside:
            out.append(row)
    return out


def details(rows, head):
    return [r[1] for r in items(rows, head)]


@pytest.fixture
def pair(tmp_path):
    a, b = tmp_path / "mod 1.0", tmp_path / "mod 1.1"
    for root in (a, b):
        put(root, "video/attract.mp4", b"\0\0\0\x18ftypmp42" + b"A" * 900)
        put(root, "images/logo.png", b"\x89PNG" + b"L" * 300)
        put(root, "text/strings.tsv", b"a\tb\n")
        put(root, "audio/same.wav", wav(1))
    return a, b


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def test_every_kind_of_change_is_listed_by_kind(pair):
    a, b = pair
    put(a, "video/mode.mp4", b"\0\0\0\x18ftypmp42" + b"M" * 500)
    put(b, "video/mode.mp4", b"\0\0\0\x18ftypmp42" + b"M" * 800)
    put(b, "video/attract.mp4", b"\0\0\0\x18ftypmp42" + b"B" * 900)
    put(a, "images/old.png", b"\x89PNG" + b"O" * 200)
    put(b, "images/renamed.png", b"\x89PNG" + b"O" * 200)
    put(a, "images/gone.png", b"\x89PNG" + b"G" * 50)
    put(b, "images/new.png", b"\x89PNG" + b"N" * 60)
    put(b, "text/strings.tsv", b"a\tc\n")
    put(b, "fonts/menu.ttf", b"font")

    s = sections(folder_compare.compare_folders(str(a), str(b)))
    assert list(s) == ["Compared", "Sounds", "Videos", "Images", "Text",
                       "Other files"]
    vids = s["Videos"]
    assert details(vids, "Modified") == [
        "video/attract.mp4 — content changed (912 B)",
        "video/mode.mp4 — 512 B -> 812 B"]
    imgs = s["Images"]
    # a renamed file is one Moved row, not a deletion plus an addition
    assert details(imgs, "Moved") == ["images/old.png  ->  images/renamed.png"]
    assert [d.split(" — ")[0] for d in details(imgs, "Deleted")] == [
        "images/gone.png"]
    assert [d.split(" — ")[0] for d in details(imgs, "Added")] == [
        "images/new.png"]
    assert details(s["Text"], "Modified") == [
        "text/strings.tsv — content changed (4 B)"]
    assert [d.split(" — ")[0] for d in details(s["Other files"], "Added")] \
        == ["fonts/menu.ttf"]
    assert s["Sounds"] == [("No changes", "")]
    head = dict(r[:2] for r in s["Compared"])
    assert head["Unchanged"].startswith("2 files identical")
    assert head["Files"] == "7 -> 8 (+1)"


def test_a_kind_neither_folder_has_says_so(pair):
    a, b = pair
    for root in (a, b):
        os.remove(os.path.join(str(root), "video", "attract.mp4"))
    s = sections(folder_compare.compare_folders(str(a), str(b)))
    assert s["Videos"] == [("No changes", "no videos in either folder")]
    assert s["Images"] == [("No changes", "")]


def test_the_app_s_own_files_are_not_the_mod_s(pair):
    """The baseline's rules and every dot-folder: the app's sidecars, its
    snapshot / cache folders, the build output, the logs, the auto-name
    sheets and a whole other extract parked inside are none of them the
    project's files."""
    a, b = pair
    for rel in (".staged_changes.json", ".orig/images/logo.png",
                ".uncorrected/images/logo.png", ".write_cache/x.bin",
                "build/card.raw", "logs/pad.log", "callouts.csv",
                "inner/" + CHECKSUMS_FILE, "inner/audio/x.wav"):
        put(b, rel, b"only in B")
    put(b, ".staged_changes.json", b"{}")
    s = sections(folder_compare.compare_folders(str(a), str(b)))
    for title in ("Sounds", "Videos", "Images", "Text", "Other files"):
        assert s[title] == [("No changes", "")] or \
            s[title][0][1].startswith("no "), (title, s[title])
    assert dict(r[:2] for r in s["Compared"])["Files"] == "4 (unchanged)"


def test_a_replaced_file_counts_even_though_the_baseline_does_not(pair):
    """THE POINT OF READING THE FILES.  A Replace tab writes its pick over
    the extracted file, so both projects' baselines still carry the stock
    card's digest for it -- same size, same baseline line, other bytes."""
    a, b = pair
    stock = os.path.join(str(a), "images", "logo.png")
    line = "images/logo.png\t%s\n" % md5_file(stock)
    for root in (a, b):
        with open(os.path.join(str(root), CHECKSUMS_FILE), "w") as f:
            f.write(line)
    put(b, "images/logo.png", b"\x89PNG" + b"X" * 300)       # same size
    s = sections(folder_compare.compare_folders(str(a), str(b)))
    assert details(s["Images"], "Modified") == [
        "images/logo.png — content changed (304 B)"]


def test_only_what_the_sizes_cannot_settle_is_read(pair, monkeypatch):
    a, b = pair
    put(b, "video/attract.mp4", b"bigger" * 400)          # size moved
    put(a, "images/only_a.png", b"\x89PNG" + b"1" * 11)    # no size twin
    put(b, "images/only_b.png", b"\x89PNG" + b"2" * 97)
    read = []
    real = hashcache.md5_for

    def spy(path, rel, cache):
        read.append(rel)
        return real(path, rel, cache)
    monkeypatch.setattr(hashcache, "md5_for", spy)
    folder_compare.compare_folders(str(a), str(b))
    assert sorted(read) == sorted(["images/logo.png", "text/strings.tsv",
                                   "audio/same.wav"] * 2)


def test_rows_open_the_file_in_the_folder_that_has_it(pair):
    a, b = pair
    put(a, "images/gone.png", b"g")
    put(b, "images/new.png", b"n")
    put(b, "images/logo.png", b"changed")
    s = sections(folder_compare.compare_folders(str(a), str(b)))
    refs = {r[2]["name"]: r[2] for r in s["Images"] if len(r) > 2}
    assert refs["gone.png"]["side"] == "A"
    assert refs["new.png"]["side"] == "B"
    assert refs["logo.png"]["side"] == "B"
    for ref in refs.values():
        assert os.path.isfile(ref["disk"])
    # count rows and section heads never open anything
    assert all(len(r) == 2 for r in s["Images"] if r[0])


def test_the_same_folder_twice_is_refused(pair):
    a, _b = pair
    s = folder_compare.compare_folders(str(a), str(a) + os.sep)
    assert s[0][0] == "Compared"
    assert any("same folder" in r[1] for r in s[0][1])


def test_an_extract_both_holder_says_to_pick_one_inside(tmp_path, pair):
    a, b = pair
    holder = tmp_path / "both"
    for name in ("stock", "mod"):
        put(holder, "%s/%s" % (name, CHECKSUMS_FILE), b"")
    s = folder_compare.compare_folders(str(holder), str(b))
    warn = [r[1] for r in s[0][1] if r[0] == "Warning"]
    assert warn and "mod, stock" in warn[0]


def test_the_hashcache_is_kept_only_in_the_app_s_own_folders(pair):
    """A folder PAD extracted keeps the cache the Write scan keeps (so the
    next compare is instant); a folder of the user's own is not written to."""
    a, b = pair
    put(a, CHECKSUMS_FILE, b"")
    folder_compare.compare_folders(str(a), str(b))
    assert os.path.isfile(os.path.join(str(a), hashcache.CACHE_FILE))
    assert not os.path.exists(os.path.join(str(b), hashcache.CACHE_FILE))
    cache = hashcache.load(str(a))
    assert "images/logo.png" in cache


def test_the_sources_are_named_when_the_folders_recorded_them(pair):
    a, b = pair
    for root, ver in ((a, "1.15.0"), (b, "1.16.0")):
        with open(os.path.join(str(root), ".extract_source.json"), "w") as f:
            json.dump({"input_name": "godzilla_pro.raw",
                       "card_version": ver}, f)
    head = dict(r[:2] for r in
                folder_compare.compare_folders(str(a), str(b))[0][1])
    assert head["Extracted from A"] == "godzilla_pro.raw (1.15.0)"
    assert head["Extracted from B"] == "godzilla_pro.raw (1.16.0)"


# ---------------------------------------------------------------------------
# The build settings beside the files
# ---------------------------------------------------------------------------

def _settings(root, data):
    with open(os.path.join(str(root), ".staged_changes.json"), "w") as f:
        json.dump(data, f)


def test_the_settings_a_build_reads_are_compared(pair):
    a, b = pair
    profile = {"name": "Black and white", "saturation": 0.0}
    _settings(a, {
        "audio_levels": {"audio/x.wav": 3, "audio/y.wav": -2},
        "image_keep_size": ["images/a.png"],
        "asset_color_profile": profile,
        "audio": {"audio/x.wav": r"C:\mine\x.wav"},
        "image_change_filter": "All",
        "video_color_slots": {"video/a.mp4": True}})
    _settings(b, {
        "audio_levels": {"audio/x.wav": 3, "audio/z.wav": 4},
        "image_keep_size": ["images/b.png"],
        "video_trim": True,
        "asset_color_profile": dict(profile, saturation=0.5),
        "audio": {"audio/x.wav": r"D:\other\x.wav"},
        "image_change_filter": "Changed",
        "video_color_slots": {"video/a.mp4": True}})
    rows = sections(folder_compare.compare_folders(str(a), str(b)))[
        "Project settings"]
    assert details(rows, "Audio: Level") == [
        "audio/y.wav — -2 dB -> 0 dB", "audio/z.wav — 0 dB -> +4 dB"]
    assert details(rows, "Images: Keep size") == [
        "images/a.png — on -> off", "images/b.png — off -> on"]
    got = dict(r[:2] for r in rows if r[0])
    assert got["Video: Trim / pad box"] == "off -> on"
    assert got["Color profile for your files"] == "Black and white, changed"
    # the picks are the files themselves (compared above, and their source
    # paths differ machine to machine), and filters are only the view
    names = [r[0] for r in rows if r[0]]
    assert not [n for n in names if "filter" in n or n == "audio"]
    assert "Video: this clip's colors" not in names


def test_no_settings_section_without_a_settings_file(pair):
    a, b = pair
    assert "Project settings" not in sections(
        folder_compare.compare_folders(str(a), str(b)))
    _settings(a, {"image_change_filter": "All"})
    rows = sections(folder_compare.compare_folders(str(a), str(b)))[
        "Project settings"]
    assert rows[0][0] == "No changes"


# ---------------------------------------------------------------------------
# Stern: the decoded sounds pair by slot, past the codec's lead-in
# ---------------------------------------------------------------------------

def _stern():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    return SternManufacturer()


def test_stern_sounds_pair_by_slot_whatever_the_names(tmp_path):
    """Two extracts made with different naming settings still line up, and
    a sound replaced in the project (its baseline still the stock digest)
    is listed as changed."""
    a, b = tmp_path / "a", tmp_path / "b"
    for i in range(4):
        put(a, "audio/idx%04d.wav" % i, wav(i + 1))
        put(b, "audio/00m00s005 - idx%04d - Callout.wav" % i, wav(i + 1))
    put(b, "audio/00m00s005 - idx0002 - Callout.wav", wav(77))
    with open(os.path.join(str(b), CHECKSUMS_FILE), "w") as f:
        f.write("audio/00m00s005 - idx0002 - Callout.wav\t%s\n"
                % md5_file(os.path.join(str(a), "audio", "idx0002.wav")))
    put(b, "modes/start/end.wav", wav(9))

    s = sections(_stern().compare_folders(str(a), str(b)))
    snd = s["Sounds"]
    got = dict(r[:2] for r in snd if r[0])
    assert got["Decoded sounds"] == "4 (unchanged)"
    assert got["Unchanged"].startswith("3 of 4 sounds")
    assert details(snd, "Changed") == [
        "00m00s005 - idx0002 - Callout.wav (image A: idx0002.wav)"]
    assert "Moved" not in got and "Added" not in got
    # the changed sound opens out of folder B
    ref = items(snd, "Changed")[0][2]
    assert ref["side"] == "B" and os.path.isfile(ref["disk"])
    # a sound that isn't one of the card's decoded slots is still listed
    assert [d.split(" — ")[0] for d in details(s["Other sounds"], "Added")] \
        == ["modes/start/end.wav"]
    assert "(sounds: see that section)" in dict(
        r[:2] for r in s["Compared"])["Unchanged"]


def test_stern_identical_sound_folders_say_so(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for root in (a, b):
        put(root, "audio/idx0000.wav", wav(5))
    snd = sections(_stern().compare_folders(str(a), str(b)))["Sounds"]
    assert snd[-1] == ("No changes",
                       "every sound decodes identically in both folders")
    assert "Other sounds" not in sections(
        _stern().compare_folders(str(a), str(b)))


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------

def _wait(w, pred, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def test_the_tab_compares_two_folders(tmp_path, pair):
    from tests.webui_harness import web_app
    a, b = pair
    put(b, "video/attract.mp4", b"other")
    with web_app(tmp_path / "app", mfr="stern") as w:
        w.call("ui.set", "compare", "a", str(a))
        w.call("ui.set", "compare", "b", str(b))
        assert w.call("compare.run") is True
        assert _wait(w, lambda: w.state("compare")["has_report"])
        st = w.state("compare")
        assert st["kind"] == "folders"
        titles = [r["change"] for r in st["rows"] if r["kind"] == "section"]
        assert titles[:3] == ["Compared", "Sounds", "Videos"]
        # a folder's row opens the file itself: no card to look for
        svc = w.window.service("compare")
        rid = next(iter(svc._refs))
        side, image, ref = w.run(svc._open_target, rid)
        assert image is None and os.path.isfile(ref["disk"])


def test_one_image_and_one_folder_is_refused(tmp_path, pair):
    from tests.webui_harness import web_app
    a, _b = pair
    card = tmp_path / "card.raw"
    card.write_bytes(b"card")
    with web_app(tmp_path / "app", mfr="stern") as w:
        w.call("ui.set", "compare", "a", str(a))
        w.call("ui.set", "compare", "b", str(card))
        assert w.call("compare.run") is False
        assert w.asked[-1]["title"] == "One image, one folder"
        # Extract Both is for two cards
        assert w.call("compare.extract_both") is False
        assert "A is already a folder" in w.asked[-1]["message"]


def test_a_manufacturer_without_card_compare_gets_the_folder_half(
        tmp_path, pair):
    from tests.webui_harness import web_app
    a, b = pair
    one, two = tmp_path / "1.iso", tmp_path / "2.iso"
    one.write_bytes(b"1")
    two.write_bytes(b"2")
    with web_app(tmp_path / "app", mfr="jjp") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["compare"]["visible"] is True
        assert w.state("compare")["images_ok"] is False
        w.call("ui.set", "compare", "a", str(one))
        w.call("ui.set", "compare", "b", str(two))
        assert w.call("compare.run") is False
        assert w.asked[-1]["title"] == "Pick two folders"
        w.call("ui.set", "compare", "a", str(a))
        w.call("ui.set", "compare", "b", str(b))
        assert w.call("compare.run") is True
        assert _wait(w, lambda: w.state("compare")["has_report"])
