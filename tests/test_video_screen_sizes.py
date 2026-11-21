"""Simon (2026-11-21), "Same as pictures": a replacement video goes on the card at the most the game shows its
slot - the player's box times its biggest zoom - never bigger than the user's file nor than the 1920x1088 Spike 2's
VPU decodes; a clip no bigger than its slot is converted to the slot's size as before
(plugins/stern/video_sizes.py, core/video_slots.stage_replacements' *sizes*)."""
import os
import subprocess

import pytest

from pinball_decryptor.core import video_slots
from pinball_decryptor.plugins.stern import scene_edit, video_sizes


def _man(zoom, clips=("clip_a",), box=(1360, 768)):
    return {"root": {"kids": [{"id": 1, "kf": [[1, 1]], "tr": [[1, [zoom, 0, 0, zoom, 0, 0]]],
                               "comps": [[1, 10]]}]},
            "objects": {"10": {"kind": "Video", "name": "video.in_game_videos", "w": box[0], "h": box[1],
                               "clips": list(clips)}}}


def test_the_most_the_game_shows_a_slot_is_its_box_times_its_zoom(tmp_path, monkeypatch):
    monkeypatch.setattr(scene_edit, "trees_of", lambda d: {"card": _man(1.32)})
    players = video_sizes.player_zooms(str(tmp_path))
    assert players["clip_a"] == (1360, 768, 1.32)
    assert video_sizes.shown_size((1360, 768), players["clip_a"]) == (1795, 1014)
    assert video_sizes.player_of(players, "video/clip_a.mov") == players["clip_a"]


def test_written_size():
    zoomed, maps, attract = (1360, 768, 1.32), (1360, 768, 1.4225), (1360, 768, 1.0)
    ws = video_sizes.written_size
    # a 4K clip: the most the screen shows it, in the slot's shape
    assert ws((1360, 768), (3840, 2160), zoomed) == (1794, 1012)
    # the city maps zoom past what the VPU decodes: held to 1920 wide
    assert ws((1360, 768), (3840, 2160), maps) == (1920, 1084)
    # never bigger than the user's own file
    assert ws((1360, 768), (1600, 900), zoomed) == (1592, 900)
    # a player that never zooms, a clip no bigger than its slot, or no player: the slot's size, as before
    assert ws((1360, 768), (3840, 2160), attract) == (1360, 768)
    assert ws((1360, 768), (640, 360), zoomed) == (1360, 768)
    assert ws((1360, 768), (3840, 2160), None) == (1360, 768)


def _slot(codec="h264", path="video/x.mp4"):
    from types import SimpleNamespace
    return SimpleNamespace(info=SimpleNamespace(width=1360, height=768, vcodec=codec), abs_path=path)


def test_only_clips_going_on_bigger_get_a_size(tmp_path, monkeypatch, manufacturers_by_key):
    from pinball_decryptor.core import video_sizes as core
    monkeypatch.setattr(scene_edit, "trees_of", lambda d: {"card": _man(1.32, clips=("big", "small"))})
    stern = manufacturers_by_key["stern"]
    stern.set_era("spike2")
    for n in ("big", "small"):
        (tmp_path / (n + ".mp4")).write_bytes(b"x")
    dims = {"big.mp4": (3840, 2160), "small.mp4": (640, 360)}

    def probe(p):
        return dims.get(os.path.basename(p)) if p else None
    slots = {"video/big.mov": _slot(), "video/small.mov": _slot()}
    picks = {"video/big.mov": str(tmp_path / "big.mp4"), "video/small.mov": str(tmp_path / "small.mp4")}
    assert core.sizes_for(stern, str(tmp_path), slots, picks, probe=probe, saved={}) == {
        "video/big.mov": (1794, 1012)}
    # Imported size off: the slot's size, as before
    assert core.sizes_for(stern, str(tmp_path), slots, picks, probe=probe,
                          saved={core.KEEP_KEY: {"video/big.mov": False}}) == {}


# ---------------------------------------------------------------------------------------------------------------
# Simon (2026-11-21): "we MUST cover all machines, spike 3, JJP ALL ... the image rules need to apply to the video
# rules even if we can't see a valid case right now"
# ---------------------------------------------------------------------------------------------------------------
def test_an_unmeasured_machine_keeps_your_size_up_to_its_limit():
    from pinball_decryptor.core import video_sizes as core
    ws = core.written_size
    # a PC-class machine (Spooky, BOF...): no scenes PAD reads, the full HD limit
    assert ws((1280, 720), (3840, 2160), None, (1920, 1080), True, False) == (1920, 1080)
    assert ws((1280, 720), (1600, 900), None, (1920, 1080), True, False) == (1600, 900)
    assert ws((1280, 720), (3840, 2160), None, (1920, 1080), False, False) == (1280, 720)    # Imported size off
    assert ws((1280, 720), (3840, 2160), None, None, True, False) == (1280, 720)             # no limit known


def test_each_machine_says_what_a_slot_can_take(manufacturers_by_key):
    stern = manufacturers_by_key["stern"]
    stern.set_era("spike2")
    assert stern.video_size_limit("", "video/x.mp4", _slot()) == ((1920, 1088), None, True)
    stern.set_era("spike3")
    assert stern.video_size_limit("", "video/x.mp4", _slot()) == ((1920, 1088), None, False)
    assert stern.video_size_limit("", "video/x.mp4", _slot("hevc")) == ((4096, 2160), None, False)
    assert stern.video_players("") is None                  # Spike 3's scenes are not measured
    stern.set_era("spike2")
    jjp = manufacturers_by_key["jjp"]
    assert jjp.video_size_limit("", "video/a.webm", _slot()) == ((1920, 1080), None, False)
    limit, why, _t = jjp.video_size_limit("", "video/a.ogv", _slot())
    assert limit is None and "exact size" in why
    for key in ("spooky", "bof", "pb", "ap"):
        assert manufacturers_by_key[key].video_size_limit("", "video/a.webm", _slot()) == (
            (1920, 1080), None, False)


def test_a_fixed_canvas_slot_never_changes_size(tmp_path, manufacturers_by_key):
    limit, why, _t = manufacturers_by_key["dp"].video_size_limit(
        "", "videos/clip.cdmd", _slot(path=str(tmp_path / "clip.cdmd")))
    assert limit is None and "fixed canvas" in why


def test_the_note_warns_where_a_bigger_clip_is_untested():
    from pinball_decryptor.core import video_sizes as core
    untested = core.Facts(limit=(1920, 1080), tested=False, measured=False)
    text = core.words((1280, 720), (3840, 2160), untested, True)
    assert "PAD can't measure how big this machine plays this slot" in text
    assert "PAD will write it at 1920×1080" in text and "WARNING: " + core.UNTESTED in text
    assert "WARNING" not in core.words((1280, 720), (3840, 2160), untested, False)        # off: the slot's size
    fixed = core.Facts(why="this clip's format has a fixed canvas")
    assert "since this clip's format has a fixed canvas" in core.words((272, 102), (1920, 720), fixed, True)
    tested = core.Facts(limit=(1920, 1088), tested=True, player=(1360, 768, 1.32), measured=True)
    text = core.words((1360, 768), (3840, 2160), tested, True)
    assert "plays this slot at up to 1795×1014" in text and "PAD will write it at 1794×1012" in text
    assert "WARNING" not in text


def _clip(ffmpeg, path, size):
    r = subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=%s:rate=10:duration=1" % size,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", path], capture_output=True)
    if r.returncode != 0:
        pytest.skip("ffmpeg could not render a clip")


def test_staging_puts_a_bigger_clip_on_at_its_size(tmp_path):
    from pinball_decryptor.core.video import detect_video_info, find_ffmpeg
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    os.makedirs(str(tmp_path / "video"))
    _clip(ffmpeg, str(tmp_path / "video" / "clip_a.mp4"), "64x36")
    rep = str(tmp_path / "rep.mp4")
    _clip(ffmpeg, rep, "256x144")
    slots = {s.rel_path: s for s in video_slots.scan_video_slots(str(tmp_path), exts=(".mp4",))}
    rel = "video/clip_a.mp4"
    staged, failures = video_slots.stage_replacements({rel: slots[rel]}, {rel: rep}, assets_dir=str(tmp_path),
                                                      sizes={rel: (128, 72)})
    assert staged == 1 and failures == []
    info = detect_video_info(str(tmp_path / "video" / "clip_a.mp4"))
    assert (info.width, info.height) == (128, 72)
    # without a size it is converted to the slot's own (the stock clip's, from its snapshot)
    staged, failures = video_slots.stage_replacements({rel: slots[rel]}, {rel: rep}, assets_dir=str(tmp_path))
    assert staged == 1
    info = detect_video_info(str(tmp_path / "video" / "clip_a.mp4"))
    assert (info.width, info.height) == (64, 36)


def test_the_write_lists_a_reduced_clip(tmp_path, monkeypatch):
    from pinball_decryptor.webui import write_scan
    monkeypatch.setattr(scene_edit, "trees_of", lambda d: {"card": _man(1.32)})

    class Info:
        width, height = 1360, 768

    class Slot:
        info = Info()

    class Mfr:
        def video_players(self, d):
            return video_sizes.player_zooms(d)

        def video_size_limit(self, d, rel, slot):
            return (1920, 1088), None, True
    rep = tmp_path / "mine.mp4"
    rep.write_bytes(b"x")
    monkeypatch.setattr(write_scan, "_video_dims", lambda p: (3840, 2160) if p and p.endswith("mine.mp4") else None)
    got = write_scan.video_size_notes(str(tmp_path), Mfr(), {"video/clip_a.mov": Slot()},
                                      {"video/clip_a.mov": str(rep)})
    assert got == {"video/clip_a.mov": "3840×2160 → 1794×1012 (reduced: the most the machine's video player shows it)"}


def test_a_bigger_clip_keeps_the_byte_budget_where_the_card_pins_it(tmp_path, monkeypatch):
    """PR #42 review: a card that holds each clip to its byte length (JJP's Sonic-era images) keeps the stock
    clip's bytes as the budget of a clip that goes on bigger; elsewhere a bigger clip has none."""
    stock = tmp_path / "stock.mp4"
    stock.write_bytes(b"\0" * 5000)
    slot = video_slots.VideoSlot(rel_path="video/clip_a.mp4", abs_path=str(stock), ext=".mp4", info=None, size=5000)
    monkeypatch.setattr(video_slots, "_clip_bitrate", lambda p: 1000000)
    monkeypatch.setattr(video_slots, "_slot_keyint", lambda p: None)
    monkeypatch.setattr(video_slots, "detect_video_info", lambda p: None)

    class Cache:
        def recipe(self, *a, **k):
            return k

    def budget(pin, size):
        return video_slots._conversion(Cache(), slot, "rep.mp4", str(stock), False, None, True, pin, False,
                                       None, size)[2]
    assert budget(True, (1920, 1080)) == 5000
    assert budget(True, None) == 5000
    assert budget(False, (1920, 1080)) is None
