"""PAD-1079 (DoomWalrus666: "add videos ... to the character selection screen"): a co-op character's own video plays
in its pick card's portrait frame. The card has a see-through window there; the build makes the video a clip of the
bank's size with its picture where the window is on the glass and adds it to the video bank; coop.cfg names it
(``char_clip <n> <clip>``) and the runtime loops it behind the HUD (the backdrop) while the card is shown."""
import os
import pathlib
import shutil
import subprocess
import types

import numpy as np
import pytest

from pinball_decryptor.plugins.stern import coop_play as CP

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHARS = [{"name": "SHODAIGOJI", "ability": "longer_save"}, {"name": "KINGOJI", "ability": ""}]


def _ffmpeg():
    from pinball_decryptor.core.audio import find_ffmpeg
    return find_ffmpeg() or shutil.which("ffmpeg")


def _video(path, ffmpeg, src="testsrc2=size=320x240:rate=30", seconds=1):
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", str(seconds), "-pix_fmt", "yuv420p",
                    str(path)], check=True)
    return str(path)


def _project(tmp_path):
    project = str(tmp_path / "p")
    os.makedirs(project)
    CP.save_characters(project, {"pick": True, "list": CHARS})
    return project


def _fake_video(tmp_path, name="v.mp4"):
    path = tmp_path / name
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    return str(path)


def test_a_character_keeps_one_video(tmp_path):
    project = _project(tmp_path)
    CP.save_video(project, 0, _fake_video(tmp_path))
    assert CP.load_characters(project)["list"][0]["video"] == "coop/character_1_video.mp4"
    assert CP.video_path(project, CP.load_characters(project)["list"][0])
    CP.save_video(project, 0, _fake_video(tmp_path, "v.mov"))
    assert sorted(os.listdir(os.path.join(project, "coop"))) == ["character_1_video.mov"]   # one video a character
    with pytest.raises(CP.CoopError):
        CP.save_video(project, 0, str(tmp_path / "x.png"))
    with pytest.raises(CP.CoopError):
        CP.save_video(project, 5, _fake_video(tmp_path))
    CP.save_video(project, 0, None)
    assert CP.load_characters(project)["list"][0]["video"] == ""
    assert [e[1] for e in CP.clip_entries(project)] == []


def test_the_card_has_a_window_where_the_video_plays(tmp_path):
    project = _project(tmp_path)
    CP.save_video(project, 0, _fake_video(tmp_path))
    chars = CP.load_characters(project)
    plain = CP.pick_card(project, chars, 0, CP.words_for())
    cut = CP.pick_card(project, chars, 0, CP.words_for(), window=True)
    x, y, w, h = CP.PORTRAIT
    inside = cut[y + 10:y + h - 10, x + 10:x + w - 10]
    assert (inside == 0).all()                                            # see-through, premultiplied black
    assert (plain[y + 10:y + h - 10, x + 10:x + w - 10, 3] == 255).all()
    assert (cut[y - 1:y + 2, x + 40:x + w - 40, 3] > 200).all()            # the lit frame line stays
    assert np.array_equal(cut[:, x + w + 20:], plain[:, x + w + 20:])      # the words are as they were
    other = CP.pick_card(project, chars, 1, CP.words_for(), window=True)   # no video: no window
    assert np.array_equal(other, CP.pick_card(project, chars, 1, CP.words_for()))
    rnd = CP.pick_card(project, chars, 2, CP.words_for(), window=True)
    assert (rnd[y + 10:y + h - 10, x + 10:x + w - 10, 3] == 255).all()


def test_only_a_title_with_the_backdrop_gets_the_window(tmp_path, monkeypatch):
    project = _project(tmp_path)
    CP.save_video(project, 0, _fake_video(tmp_path))
    x, y, w, h = CP.PORTRAIT
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: object())
    for can, see in ((True, True), (False, False)):
        monkeypatch.setattr(CP, "can_video", lambda prof, can=can: can)
        art = CP.pick_screens(project)[0]["art_rgba"]
        assert (art[y + 50, x + 50, 3] == 0) == see


def test_godzilla_has_the_backdrop():
    from pinball_decryptor.plugins.stern import mode_project as MP
    gz = [MP.profile(k) for k in ("godzilla_le_1_16", "godzilla_pro_1_16", "godzilla_pro_1_15")]
    assert all(CP.can_video(p) for p in gz)
    assert not CP.can_video(None)


def test_the_window_on_the_glass():
    assert CP.window_box(1360, 768) == (CP.CARD_AT[0] + CP.PORTRAIT[0], CP.CARD_AT[1] + CP.PORTRAIT[1],
                                        CP.PORTRAIT[2], CP.PORTRAIT[3]) == (80, 170, 380, 306)
    assert CP.window_box(680, 384) == (40, 84, 190, 152)                  # half the glass: half the window, even


def test_the_clip_is_the_video_in_the_window_on_black(tmp_path):
    ff = _ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg here")
    src = _video(tmp_path / "src.mp4", ff, "color=c=red:size=320x240:rate=30")
    out = CP.window_clip(src, str(tmp_path / "clip.mp4"), 1360, 768, ff)
    png = str(tmp_path / "f.png")
    subprocess.run([ff, "-v", "error", "-y", "-i", out, "-frames:v", "1", png], check=True)
    from PIL import Image
    f = np.asarray(Image.open(png).convert("RGB")).astype(int)
    assert f.shape == (768, 1360, 3)
    x, y, w, h = CP.window_box(1360, 768)
    assert f[y + h // 2, x + w // 2, 0] > 200 and f[y + h // 2, x + w // 2, 1] < 60      # red in the window
    for px, py in ((x - 6, y + h // 2), (x + w + 6, y + h // 2), (x + w // 2, y - 6), (x + w // 2, y + h + 6),
                   (1200, 600), (20, 20)):
        assert f[py, px].max() < 30, (px, py)                                            # black around it


def test_the_build_adds_each_clip_and_names_it(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern import video_bank as VB
    project = _project(tmp_path)
    CP.save_video(project, 1, _fake_video(tmp_path))
    prof = types.SimpleNamespace(label="Godzilla Premium/LE 1.16", game_dir="godzilla_le",
                                 lcd=lambda which: "assets/lcd/auto_loaded/bank")
    result = types.SimpleNamespace(project=project, profile=prof, replaced=[], new=[], lines=[])
    monkeypatch.setattr(CP, "wants_screens", lambda project, prof: True)
    monkeypatch.setattr(CP, "can_video", lambda prof: True)
    monkeypatch.setattr(VB, "clip_frame", lambda data: (1360, 768))
    monkeypatch.setattr(VB, "parse", lambda data: types.SimpleNamespace(labels=[("Normal", 1), ("ScoreFrame", 2)]))
    made = []
    monkeypatch.setattr(CP, "window_clip", lambda src, out, w, h, ff: made.append((src, w, h)) or
                        open(out, "wb").write(b"x" * 10))
    monkeypatch.setattr(VB, "add_clip", lambda data, name, size: (data + name.encode(), {"path": "2.asset/9.asset"}))
    got = MW.coop_clips_into(result, b"BANK", str(tmp_path / "scratch"), ffmpeg="ffmpeg")
    assert got == [(2, "PadCoopClip2")] and made[0][1:] == (1360, 768)
    bank_card = "godzilla_le/assets/lcd/auto_loaded/bank/scene.radium"
    assert result.replaced[0][0] == bank_card
    assert open(result.replaced[0][1], "rb").read() == b"BANKPadCoopClip2"
    assert result.new[0][0] == "godzilla_le/assets/lcd/auto_loaded/bank/scene.assets/2.asset/9.asset"
    assert "KINGOJI" in result.lines[-1]
    # a bank the build already rewrote is grown, not the stock one
    result2 = types.SimpleNamespace(project=project, profile=prof, replaced=[(bank_card, result.replaced[0][1])],
                                    new=[], lines=[])
    MW.coop_clips_into(result2, b"BANK", str(tmp_path / "scratch2"), ffmpeg="ffmpeg")
    assert open(result.replaced[0][1], "rb").read() == b"BANKPadCoopClip2PadCoopClip2"
    monkeypatch.setattr(CP, "can_video", lambda prof: False)            # no backdrop: left out, and said
    result3 = types.SimpleNamespace(project=project, profile=prof, replaced=[], new=[], lines=[])
    assert MW.coop_clips_into(result3, b"BANK", str(tmp_path / "s3"), ffmpeg="ffmpeg") == []
    assert "left out" in result3.lines[-1] and not result3.replaced
    monkeypatch.setattr(CP, "can_video", lambda prof: True)            # a bank with no Normal crop: left out too
    monkeypatch.setattr(VB, "parse", lambda data: types.SimpleNamespace(labels=[("ScoreFrame", 2)]))
    result4 = types.SimpleNamespace(project=project, profile=prof, replaced=[], new=[], lines=[])
    assert MW.coop_clips_into(result4, b"BANK", str(tmp_path / "s4"), ffmpeg="ffmpeg") == []
    assert "no Normal crop" in result4.lines[-1]


def test_godzillas_bank_plays_the_normal_crop_one_to_one():
    """The crops are the VideoSurface's keyframes; Normal's track is the identity on Godzilla LE 1.16's bank (and
    ScoreFrame, the backdrop's own, is not), read off a bank the rig built."""
    import struct
    path = pathlib.Path(r"C:/tmp/PAD-1079/ovr/godzilla_le/assets/lcd/auto_loaded/"
                        r"60ed7e5036b8ce09d35a3e101ea6fc1380b37d97/scene.radium")
    if not path.is_file():
        pytest.skip("no Godzilla bank here")
    from pinball_decryptor.plugins.stern import video_bank as VB
    data = path.read_bytes()
    bank = VB.parse(data)
    frames = dict(bank.labels)
    p = data.find(bank.surface_node.encode()) + len(bank.surface_node) + 4
    n = struct.unpack_from("<Q", data, p)[0]
    p += 8 + 5 * n + 8
    tracks = {}
    for _ in range(struct.unpack_from("<Q", data, p)[0]):
        tracks[struct.unpack_from("<I", data, p + 8)[0]] = struct.unpack_from("<16f", data, p + 12)
        p += 68
    assert tracks[frames["Normal"]] == (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    assert tracks[frames["ScoreFrame"]][12:14] != (0, 0)


def test_the_settings_file_carries_the_videos(tmp_path, monkeypatch):
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: types.SimpleNamespace(label="Godzilla"))
    src = _project(tmp_path)
    CP.save(src, True)
    CP.save_video(src, 1, _fake_video(tmp_path))
    out = str(tmp_path / "coop.zip")
    assert CP.export_settings(src, out)["pictures"] == 1
    dest = str(tmp_path / "d")
    os.makedirs(dest)
    assert CP.import_settings(dest, out)["pictures"] == 1
    got = CP.load_characters(dest)["list"]
    assert got[1]["video"] == "coop/character_2_video.mp4" and got[0]["video"] == ""
    with open(os.path.join(dest, "coop", "character_2_video.mp4"), "rb") as f:
        assert f.read() == b"\x00\x00\x00\x18ftypmp42"
    assert CP.export_settings(src, str(tmp_path / "c.json"))["left_out"] == 1


def test_the_preview_shows_the_videos_first_frame_in_the_window(tmp_path):
    ff = _ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg here")
    project = _project(tmp_path)
    CP.save_video(project, 0, _video(tmp_path / "g.mp4", ff, "color=c=green:size=320x240:rate=30"))
    import io
    from PIL import Image
    png = CP.preview(project, dict(CP.load_characters(project), pick=True), CP.words_for(), 0, videos=True)
    g = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
    x, y, w, h = CP.window_box(*CP.GLASS)
    assert g[y + h // 2, x + w // 2, 1] > 100 and g[y + h // 2, x + w // 2, 0] < 60
    png = CP.preview(project, dict(CP.load_characters(project), pick=True), CP.words_for(), 0, videos=False)
    g = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
    assert not (g[y + h // 2, x + w // 2, 1] > 100 and g[y + h // 2, x + w // 2, 0] < 60)


def test_the_dialog_takes_a_video(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import modes as M
    project = _project(tmp_path)
    svc = M.ModesTab.__new__(M.ModesTab)
    state, said = {}, []
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "get", lambda k, d=None: state.get(k, d), raising=False)
    monkeypatch.setattr(svc, "project", lambda: project, raising=False)
    monkeypatch.setattr(svc, "_say", lambda w, *a, **k: said.append(w), raising=False)
    monkeypatch.setattr(CP, "project_powers", lambda project: ("", []))
    monkeypatch.setattr(CP, "project_abilities", lambda project: ("", []))
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: types.SimpleNamespace(label="Jaws Pro"))
    monkeypatch.setattr(CP, "can_video", lambda prof: False)
    monkeypatch.setattr(CP, "preset_for", lambda prof: "")
    monkeypatch.setattr(svc, "_coop_preview", lambda project, chars: None, raising=False)
    video = _fake_video(tmp_path)
    monkeypatch.setattr(svc, "window", types.SimpleNamespace(ask_open=lambda *a: video), raising=False)
    assert svc.coop_char_video(1)
    assert state["coop_ch"]["rows"][1]["video"] and not state["coop_ch"]["rows"][0]["video"]
    assert "Jaws Pro cannot play a video" in state["coop_ch"]["videos"]
    assert svc.coop_char_video(1, clear=True) and not state["coop_ch"]["rows"][1]["video"]
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes_dialogs.js").read_text("utf-8")
    assert 'call("modes.coop_char_video", i, false)' in js


def test_the_runtime_reads_the_clip_lines_and_plays_them_behind_the_card():
    src = (ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c").read_text("utf-8")
    assert 'str_starts(s, "char_clip ")' in src and 'str_starts(s, "clip_crop ")' in src
    show = src[src.index("static void coop_clip_show(int want)"):]
    show = show[:show.index("\n}\n")]
    assert "pm_backdrop(coop_clip[c])" in show and "pm_backdrop(0)" in show
    tick = src[src.index("static void coop_screens_tick(void)"):]
    assert "coop_clip_show(" in tick[:tick.index("\n}\n")]
