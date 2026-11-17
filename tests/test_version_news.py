"""PAD-1388: what a new game version adds, changes and drops against the
version a project was extracted from (core.version_news)."""
import json
import os
import struct
import wave

from pinball_decryptor.core import staged_changes, version_news
from pinball_decryptor.core.checksums import generate_checksums


def _wav(path, seed, n=400):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<h", (i * seed) % 3000)
                               for i in range(n)))


def _put(root, rel, data):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def _extract(root, version, videos, images, sounds, texts):
    """A miniature extract: *videos* ``{name: (card path, bytes)}``,
    *images* ``{rel: bytes}``, *sounds* ``{name: seed}``, *texts* [words];
    then its stock baseline, the way an Extract ends."""
    os.makedirs(root, exist_ok=True)
    rows = ["# output\tcard path\tbytes"]
    for name, (card, data) in videos.items():
        _put(root, "video/" + name, data)
        rows.append("%s\t%s\t%d" % (name, card, len(data)))
    _put(root, "video/manifest.txt", ("\n".join(rows) + "\n").encode())
    for rel, data in images.items():
        _put(root, rel, data)
    for name, seed in sounds.items():
        _wav(os.path.join(root, "audio", name), seed)
    _put(root, "text/strings.tsv", "".join(
        "game\t%s\t\n" % t for t in texts).encode())
    with open(os.path.join(root, ".extract_source.json"), "w") as f:
        json.dump({"card_version": version}, f)
    generate_checksums(str(root))
    return str(root)


def _pair(tmp_path):
    old = _extract(
        tmp_path / "old", "0.93.0",
        videos={"INTRO.mp4": ("/g/a/1.asset", b"intro-v1"),
                "KONG.mp4": ("/g/a/2.asset", b"kong-v1"),
                "MOVED.mp4": ("/g/a/3.asset", b"moved-bytes"),
                "CUT.mp4": ("/g/a/4.asset", b"cut-clip")},
        images={"images/king/logo.png": b"logo-1",
                "images/king/old_only.png": b"gone"},
        sounds={"idx0000.wav": 3, "idx0001.wav": 5},
        texts=["JACKPOT", "SUPER JACKPOT"])
    new = _extract(
        tmp_path / "new", "1.00.0",
        videos={"INTRO.mp4": ("/g/a/1.asset", b"intro-v1"),
                "KONG.mp4": ("/g/a/2.asset", b"kong-v2-reencoded"),
                "RENAMED.mp4": ("/g/b/9.asset", b"moved-bytes"),
                "SKULL_ISLAND.mp4": ("/g/b/10.asset", b"brand-new")},
        images={"images/king/logo.png": b"logo-2",
                "images/king/new_one.png": b"fresh"},
        sounds={"idx0000.wav": 3, "idx0001.wav": 5, "idx0002.wav": 11},
        texts=["JACKPOT", "SUPER JACKPOT", "SKULL ISLAND MULTIBALL"])
    return old, new


def test_new_version_lists_what_it_adds_changes_and_drops(tmp_path):
    old, new = _pair(tmp_path)
    news = version_news.compare(old, new)
    v = news["kinds"]["video"]
    assert v["added"] == ["video/SKULL_ISLAND.mp4"]
    # same bytes under another name and card path is not new
    assert "video/RENAMED.mp4" not in v["added"]
    assert v["changed"] == [("video/KONG.mp4", "video/KONG.mp4")]
    assert v["removed"] == ["video/CUT.mp4"]
    assert v["same"] == 2
    i = news["kinds"]["image"]
    assert i["added"] == ["images/king/new_one.png"]
    assert i["changed"] == [("images/king/logo.png", "images/king/logo.png")]
    assert i["removed"] == ["images/king/old_only.png"]
    s = news["kinds"]["sound"]
    assert s["added"] == ["audio/idx0002.wav"] and s["same"] == 2
    t = news["kinds"]["text"]
    assert t["added"] == ["SKULL ISLAND MULTIBALL"] and t["same"] == 2
    assert (news["old_version"], news["new_version"]) == ("0.93.0", "1.00.0")
    assert version_news.headline(news) == (
        "1.00.0 adds 1 video, 1 sound, 1 picture and 1 text line.")


def test_a_replaced_slot_is_judged_by_its_stock_baseline(tmp_path):
    """A Replace pick written over the old extract is the MOD, not the stock
    clip: the compare reads the baseline, and names the replaced slots the
    new version changed or dropped."""
    old, new = _pair(tmp_path)
    _put(old, "video/INTRO.mp4", b"my own intro")       # replaced, unchanged
    _put(old, "video/KONG.mp4", b"my own kong")         # replaced, changed
    _put(old, "video/CUT.mp4", b"my own cut")           # replaced, dropped
    staged_changes.save(old, {"video": {
        "video/INTRO.mp4": "C:/mods/intro.mp4",
        "video/KONG.mp4": "C:/mods/kong.mp4",
        "video/CUT.mp4": "C:/mods/cut.mp4"}})
    news = version_news.compare(old, new)
    assert news["kinds"]["video"]["same"] == 2
    assert news["yours"] == {"changed": ["video/KONG.mp4"],
                             "removed": ["video/CUT.mp4"]}
    lines = [t for _lvl, t in version_news.summary_lines(news)]
    assert any("KONG.mp4" in t and "still goes on" in t for t in lines)
    assert any("CUT.mp4" in t and "nowhere to go" in t for t in lines)


def test_nothing_new_says_so_and_the_page_copy_is_capped(tmp_path):
    old, _new = _pair(tmp_path)
    same = tmp_path / "same"
    import shutil
    shutil.copytree(old, same)
    news = version_news.compare(old, str(same))
    assert version_news.headline(news) == (
        "0.93.0 adds no new videos, sounds, pictures or text.")
    page = version_news.for_page(news, cap=1)
    assert [k["kind"] for k in page["kinds"]] == ["video", "sound", "image",
                                                  "text"]
    assert all(k["n_added"] == 0 for k in page["kinds"])


def test_report_file_lists_everything(tmp_path):
    old, new = _pair(tmp_path)
    news = version_news.compare(old, new)
    path = version_news.write_report(news, str(tmp_path / "r.txt"))
    text = open(path, encoding="utf-8").read()
    assert "What's new in 1.00.0 (compared with 0.93.0)" in text
    for name in ("SKULL_ISLAND.mp4", "new_one.png", "idx0002.wav",
                 "SKULL ISLAND MULTIBALL", "CUT.mp4"):
        assert name in text


def test_a_clip_reencoded_into_another_container_is_changed_not_new(tmp_path):
    """KK LE 1.00.0 re-encoded about 200 of 0.93.0's .mp4 clips as .mov at
    new card paths: the same name in another container is a change."""
    old = _extract(tmp_path / "o", "0.93.0",
                   videos={"KONG.mp4": ("/g/a/2.asset", b"kong-mp4")},
                   images={}, sounds={"idx0000.wav": 3}, texts=[])
    new = _extract(tmp_path / "n", "1.00.0",
                   videos={"KONG.mov": ("/g/z/7.asset", b"kong-mov")},
                   images={}, sounds={"idx0000.wav": 3}, texts=[])
    v = version_news.compare(old, new)["kinds"]["video"]
    assert v["changed"] == [("video/KONG.mp4", "video/KONG.mov")]
    assert v["added"] == [] and v["removed"] == []
