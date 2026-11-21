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


def test_only_clips_going_on_bigger_get_a_size(tmp_path, monkeypatch):
    monkeypatch.setattr(scene_edit, "trees_of", lambda d: {"card": _man(1.32, clips=("big", "small"))})

    class Info:
        width, height = 1360, 768

    class Slot:
        info = Info()
    for n in ("big", "small"):
        (tmp_path / (n + ".mp4")).write_bytes(b"x")
    dims = {"big.mp4": (3840, 2160), "small.mp4": (640, 360)}
    got = video_sizes.sizes_for(str(tmp_path), {"video/big.mov": Slot(), "video/small.mov": Slot()},
                                {"video/big.mov": str(tmp_path / "big.mp4"),
                                 "video/small.mov": str(tmp_path / "small.mp4")},
                                probe=lambda p: dims.get(os.path.basename(p)) if p else None)
    assert got == {"video/big.mov": (1794, 1012)}


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
    rep = tmp_path / "mine.mp4"
    rep.write_bytes(b"x")
    monkeypatch.setattr(write_scan, "_video_dims", lambda p: (3840, 2160) if p and p.endswith("mine.mp4") else None)
    got = write_scan.video_size_notes(str(tmp_path), Mfr(), {"video/clip_a.mov": Slot()},
                                      {"video/clip_a.mov": str(rep)})
    assert got == {"video/clip_a.mov": "3840×2160 → 1794×1012 (reduced: the most the screen shows it)"}
