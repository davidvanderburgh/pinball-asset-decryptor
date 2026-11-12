"""PAD-1185: a Spike 3 extract names its clips from the scenes, and decodes the
music banks beside image.bin.

The card keeps every clip as a number under a hash folder
(``auto_loaded/<sha1>/scene.assets/2.asset/180.asset``); before this the
extract copied that path, so a project's ``video/`` was a tree of numbers.
The clip's name is in its scene's ``scene.radium``, which Spike 2's extract
already reads; the Spike 3 extract now does the same, a folder per game
(``video/fallout_le/``, ``video/fallout_le/spike3/spike_menu/``) with a
``video/manifest.txt``.  The ``image-scNN.bin`` music banks were skipped
entirely; they are the same plain PCM container as image.bin and decode as
Spike 2's ``music_catNN_NNNN.wav``.
"""

import os
import struct
import wave

from pinball_decryptor.plugins.stern import spike3_extract as SE
from pinball_decryptor.plugins.stern import spike3_sound as S3


def _record(name, ref, ident=0x01):
    nb, rb = name.encode(), ref.encode()
    return (struct.pack("<Q", len(nb)) + nb
            + struct.pack("<I", 0x80000000 | ident)
            + struct.pack("<Q", len(rb)) + rb)


def _radium(*clips):
    return b"\x00" * 16 + b"".join(_record(n, r, i + 1)
                                   for i, (n, r) in enumerate(clips))


MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
MOV = b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 32
MOOV = b"\x00\x00\x00\x10moov" + b"\x00" * 32

_GAME = "/fallout_le/assets/lcd/auto_loaded/60ed7e5036b8ce09"
_MENU = "/fallout_le/spike3/spike_menu/assets/lcd/auto_loaded/bc0792d8dc81e8aa"
_NONAME = "/fallout_le/assets/lcd/auto_loaded/ed692432953d8707"

CARD = {
    _GAME + "/scene.radium": _radium(("GrognakComic6", "2.asset/180.asset"),
                                     ("shoot_again", "2.asset/796.asset"),
                                     ("shoot_again", "2.asset/797.asset")),
    _GAME + "/scene.assets/2.asset/180.asset": MP4,
    _GAME + "/scene.assets/2.asset/796.asset": MP4,
    _GAME + "/scene.assets/2.asset/797.asset": MP4,
    _MENU + "/scene.radium": _radium(("JUKEBOX_LOOP3", "2.asset/10.asset")),
    _MENU + "/scene.assets/2.asset/10.asset": MOV,
    _NONAME + "/scene.assets/3.asset/59.asset": MOOV,   # no scene.radium
}


class _Pipe:
    def __init__(self, out):
        self.output_dir = str(out)
        self.logs = []

    def _check_cancel(self):
        pass

    def _progress(self, *a):
        pass

    def _log(self, msg, level="info"):
        self.logs.append((level, msg))


def _extract(out):
    pipe = _Pipe(out)
    vids = [(p, b) for p, b in CARD.items()
            if p.endswith(".asset") and SE.is_video_head(b)]
    radiums = {p[:-len("/scene.radium")]: p for p in CARD
               if p.endswith("/scene.radium")}

    def write(it, path):
        with open(path, "wb") as f:
            f.write(it[1])
    got = SE.extract_videos(pipe, vids, lambda it: it[0], lambda it: len(it[1]),
                            lambda it: SE.video_brand(it[1][:12]), write,
                            radiums, lambda p: CARD[p])
    return pipe, got


def _files(top):
    out = set()
    for d, _ds, fs in os.walk(top):
        for f in fs:
            out.add(os.path.relpath(os.path.join(d, f), top).replace(os.sep, "/"))
    return out


def test_clips_are_named_from_their_scene_in_the_games_own_folder(tmp_path):
    pipe, (done, named) = _extract(tmp_path)
    assert (done, named) == (5, 4)
    assert _files(tmp_path / "video") == {
        "fallout_le/GrognakComic6.mp4",
        "fallout_le/shoot_again.mp4",
        "fallout_le/shoot_again_2.mp4",
        # a clip no scene names keeps its scene hash and place, never a number
        "fallout_le/video_ed692432_3_59.mov",
        # the service menu's clips stay apart, as its sounds do
        "fallout_le/spike3/spike_menu/JUKEBOX_LOOP3.mov",
        "manifest.txt",
    }
    assert any("4 of 5 video(s) named" in m for _l, m in pipe.logs)


def test_manifest_gives_each_clips_card_path(tmp_path):
    _extract(tmp_path)
    rows = [l.rstrip("\n").split("\t") for l in
            open(tmp_path / "video" / "manifest.txt", encoding="utf-8")
            if not l.startswith("#")]
    by_name = {r[0]: (r[1], int(r[2])) for r in rows}
    assert by_name["fallout_le/GrognakComic6.mp4"] == (
        _GAME + "/scene.assets/2.asset/180.asset", len(MP4))
    assert len(by_name) == 5


def test_re_extract_removes_the_old_card_path_copies(tmp_path):
    """An extract made before this wrote video/<card path>.mov: those exact
    files go (and the folders they leave empty), anything else stays."""
    vdir = tmp_path / "video"
    old = vdir / (_GAME.lstrip("/") + "/scene.assets/2.asset/180.mov")
    old.parent.mkdir(parents=True)
    old.write_bytes(MP4)
    mine = vdir / "my_notes.txt"
    mine.write_text("keep me")
    pipe, _ = _extract(tmp_path)
    assert not old.exists()
    assert not (vdir / "fallout_le" / "assets").exists()
    assert mine.read_text() == "keep me"
    assert any("Removed 1 video(s)" in m for _l, m in pipe.logs)


def test_spk_paths_without_the_game_folder_still_get_names(tmp_path):
    """An .spk's paths are relative to its section ("assets/lcd/..."): the
    clips land straight in video/."""
    vids = [("assets/lcd/auto_loaded/aa/scene.assets/2.asset/1.asset", b"mp42")]
    radiums = {"assets/lcd/auto_loaded/aa": "r"}
    plan = SE.name_videos(vids, radiums,
                          lambda _r: _radium(("Title_Loop", "2.asset/1.asset")))
    assert plan == [("Title_Loop.mp4", True)]


def test_video_group():
    assert SE.video_group(_GAME + "/scene.assets/2.asset/1.asset") == "fallout_le"
    assert (SE.video_group(_MENU + "/scene.assets/2.asset/1.asset")
            == "fallout_le/spike3/spike_menu")
    assert SE.video_group("assets/lcd/x/scene.assets/1.asset") == ""


# -- music banks ---------------------------------------------------------------

def _container(frames_list, stereo=True):
    """A tiny valid Spike 3 sound container (see spike3_sound's layout)."""
    ch = 2 if stereo else 1
    bodies = [b"\x01\x00" * (n * ch) for n in frames_list]
    first = 0x80
    offs, o = [], first
    for b in bodies:
        offs.append(o)
        o += len(b)
    md_off = o
    count = len(bodies)
    dir_len = (24 * count + 15) // 16 * 16
    hdr = bytearray(0x80)
    struct.pack_into("<Q", hdr, 0x40, md_off)
    struct.pack_into("<I", hdr, 0x60, count)
    d = bytearray(dir_len)
    for i, (off, n) in enumerate(zip(offs, frames_list)):
        struct.pack_into("<QIIII", d, 24 * i, off,
                         0x00020000 if stereo else 0, 0, n, 0)
    return bytes(hdr) + b"".join(bodies) + bytes(d) + b"\x00" * 8


def test_bank_decodes_as_spike2_music_names(tmp_path):
    p = tmp_path / "image-sc07.bin"
    p.write_bytes(_container([441, 882]))
    out = tmp_path / "audio"
    out.mkdir()
    (out / "idx0001.wav").write_bytes(b"keep: image.bin's own")
    (out / "music_cat07_0009.wav").write_bytes(b"stale")
    got = S3.decode_container(str(p), str(out), stem="music_cat07")
    assert got["sounds"] == 2
    names = sorted(os.listdir(out))
    assert names == ["idx0001.wav", "music_cat07_0000.wav", "music_cat07_0001.wav"]
    with wave.open(str(out / "music_cat07_0001.wav")) as w:
        assert (w.getnchannels(), w.getnframes(), w.getframerate()) == (2, 882, 44100)


def test_banks_are_picked_up_and_decoded_beside_image_bin(tmp_path):
    files = {"fallout_le/image.bin": _container([100]),
             "fallout_le/image-sc12.bin": _container([200]),
             "fallout_le/image-sc03.bin": _container([300, 10], stereo=False)}
    assert all(SE.is_sound_container(os.path.basename(k)) for k in files)
    assert not SE.is_sound_container("image-sc.bin")
    assert not SE.is_sound_container("image.bin.bak")
    pipe = _Pipe(tmp_path)

    def write(rel, out):
        with open(out, "wb") as f:
            f.write(files[rel])
    sounds, _secs = SE.decode_sound_containers(pipe, list(files), lambda r: r, write)
    assert sounds == 4
    audio = tmp_path / "sound" / "fallout_le" / "audio"
    assert sorted(os.listdir(audio)) == [
        "idx0000.wav", "music_cat03_0000.wav", "music_cat03_0001.wav",
        "music_cat12_0000.wav"]
    # the containers are not kept
    assert not any(f.endswith(".bin") for f in os.listdir(audio.parent))
