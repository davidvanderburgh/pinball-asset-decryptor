"""PAD-1192: a picture whose image data is damaged (it passes PIL's verify(), which checks chunk checksums only) hung a
Write for hours at "Making the co-op characters' picked clips (10 of 11)": ffmpeg's ``-loop 1`` retries a still it
cannot decode forever (its ``-t`` counts frames out, and none come), and Cancel cannot reach into the run. Every looped
still is now decoded whole by PIL and handed to ffmpeg as a plain PNG, the pickers refuse such a file, and the co-op
ffmpeg runs carry a time limit."""
import os
import struct
import time
import zlib

import pytest

from pinball_decryptor.plugins.stern import attract_items as AI
from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import mode_assets as MA


def _ffmpeg():
    from pinball_decryptor.core.audio import find_ffmpeg
    ff = find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg here")
    return ff


def _png(path, size=(160, 120)):
    import numpy as np
    from PIL import Image
    Image.fromarray(np.random.default_rng(7).integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)).save(path)
    return str(path)


def _damaged(path):
    """A PNG with garbage in its compressed image data and every chunk checksum right: verify() passes it."""
    good = open(_png(str(path) + ".src.png"), "rb").read()
    b = bytearray(good)
    i = 8
    while i < len(b):
        n = struct.unpack(">I", b[i:i + 4])[0]
        if b[i + 4:i + 8] == b"IDAT":
            body = bytearray(b[i + 8:i + 8 + n])
            for k in range(60, min(len(body), 400)):
                body[k] ^= 0x5A
            b[i + 8:i + 8 + n] = body
            b[i + 8 + n:i + 12 + n] = struct.pack(">I", zlib.crc32(b"IDAT" + bytes(body)))
            break
        i += 12 + n
    open(path, "wb").write(bytes(b))
    return str(path)


def _apng(path):
    from PIL import Image
    frames = [Image.new("RGB", (80, 60), c) for c in ((200, 0, 0), (0, 200, 0), (0, 0, 200))]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    return str(path)


def test_the_damaged_picture_passes_verify_but_not_a_whole_read(tmp_path):
    from PIL import Image
    bad = _damaged(tmp_path / "gmk.png")
    with Image.open(bad) as im:
        im.verify()                                     # what the pickers asked before: it says yes
    with pytest.raises(Exception):
        MA.check_picture(bad)
    with pytest.raises(ValueError, match="gmk.png is not a picture that reads whole"):
        MA.clean_still(bad, str(tmp_path / "out.png"))


def test_the_pickers_refuse_it(tmp_path):
    project = str(tmp_path / "project")
    os.makedirs(project)
    CP.save(project, True)
    CP.save_characters(project, {"pick": True, "list": [{"name": "sokogekigoji"}]})
    bad = _damaged(tmp_path / "gmk.png")
    with pytest.raises(CP.CoopError, match="not a picture the app can read"):
        CP.save_picked_clip(project, 0, bad)
    with pytest.raises(CP.CoopError, match="not a picture the app can read"):
        CP.save_picture(project, 0, bad)
    assert not os.path.exists(os.path.join(project, CP.PICTURE_DIR, "character_1_picked.png"))


def test_a_damaged_picture_already_in_a_project_stops_the_build_at_once(tmp_path, monkeypatch):
    ff = _ffmpeg()
    monkeypatch.setattr(CP, "FFMPEG_TIMEOUT", 30)       # a regression fails here, not forever
    bad = _damaged(tmp_path / "character_10_picked.png")
    loop = CP.picked_clip(_png(tmp_path / "pic.png"), str(tmp_path / "loop.mp4"), 320, 180, ff)
    t = time.time()
    with pytest.raises(CP.CoopError, match="character_10_picked.png is not a picture that reads whole"):
        CP.picked_clip(bad, str(tmp_path / "PadCoopPicked10.mp4"), 1360, 768, ff)
    with pytest.raises(CP.CoopError, match="character_10_picked.png"):
        CP.bonus_clip(loop, str(tmp_path / "bonus.mp4"), (200, 40, 80, 64), ff, picture=bad, seconds=1,
                      size=(320, 180))
    with pytest.raises(AI.AttractError, match="character_10_picked.png"):
        AI.still_clip(bad, 1, str(tmp_path / "attract.mp4"), 320, 180, ffmpeg=ff)
    assert time.time() - t < 10
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".still.png")]


def test_good_and_animated_pictures_still_make_clips(tmp_path):
    ff = _ffmpeg()
    from pinball_decryptor.core.video import detect_video_info
    for src in (_png(tmp_path / "plain.png"), _apng(tmp_path / "animated.png")):
        out = str(tmp_path / (os.path.basename(src) + ".mp4"))
        CP.picked_clip(src, out, 320, 180, ff, seconds=2)
        info = detect_video_info(out)
        assert abs(float(info.duration) - 2.0) < 0.2, src
        assert not os.path.exists(out + ".still.png")
        loop = out
        bonus = str(tmp_path / (os.path.basename(src) + ".bonus.mp4"))
        CP.bonus_clip(loop, bonus, (200, 40, 80, 64), ff, picture=src, seconds=1, size=(320, 180))
        att = str(tmp_path / (os.path.basename(src) + ".attract.mp4"))
        AI.still_clip(src, 1, att, 320, 180, ffmpeg=ff)
        assert os.path.getsize(bonus) and os.path.getsize(att)


def test_a_stuck_ffmpeg_run_is_stopped_and_named(tmp_path, monkeypatch):
    """The backstop: what PAD-1192's build ran (a looped still ffmpeg cannot decode) never ends on its own."""
    ff = _ffmpeg()
    monkeypatch.setattr(CP, "FFMPEG_TIMEOUT", 3)
    bad = _damaged(tmp_path / "gmk.png")
    head, tail = MA._encode_args(ff, str(tmp_path / "stuck.mp4"))
    cmd = head + ["-loop", "1", "-framerate", "30", "-i", bad, "-t", "3"] + tail
    t = time.time()
    with pytest.raises(CP.CoopError, match="still making the picked clip of gmk.png after 0 minutes and was stopped"):
        CP._ffmpeg_run(cmd, "the picked clip of gmk.png")
    assert time.time() - t < 15
    os.remove(bad)                                      # the killed run let go of the file (WinError 32 before)
