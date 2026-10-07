"""core.original_match: finding the file a picked sound or picture was made
from, by what it sounds or looks like (PAD-443).

The sounds are made up here (tones and noise bursts, a different tune per
seed) and run through what a Write does to a replacement -- gained, resampled,
noise from the codec, trimmed or padded -- in numpy, so the tests need ffmpeg
only to read them back (the matcher decodes through it).  The pictures go
through what a Write does to one -- stretched to the slot, a colour profile,
the BC3 texture format -- with Pillow and the Stern plugin's own encoder.
"""

import json
import os
import shutil
import wave

import numpy as np
import pytest

from pinball_decryptor.core import original_match as om

Image = pytest.importorskip("PIL.Image")


def _ffmpeg():
    from pinball_decryptor.core.audio import find_ffmpeg
    return find_ffmpeg()


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg") and not _ffmpeg(),
                                  reason="needs ffmpeg")


# --------------------------------------------------------------------------
# made-up sounds
# --------------------------------------------------------------------------

def _tune(seed, seconds=1.2, rate=48000):
    """A sound of its own per *seed*: a few tones and a noise burst, each
    with its own pitch, length and swell."""
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    out = np.zeros(n)
    t0 = 0
    while t0 < n:
        dur = int(rate * rng.uniform(0.06, 0.3))
        t = np.arange(min(dur, n - t0)) / rate
        env = np.sin(np.pi * np.linspace(0, 1, len(t))) ** rng.uniform(0.5, 3)
        if rng.random() < 0.25:
            sig = rng.normal(0, 0.3, len(t))
        else:
            f = rng.uniform(150, 3500)
            sig = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)
        out[t0:t0 + len(t)] += env * sig * rng.uniform(0.2, 0.9)
        t0 += int(len(t) * rng.uniform(0.6, 1.1)) + int(rate * rng.uniform(0, 0.08))
    return out / max(1e-9, np.abs(out).max()) * 0.8


def _write(path, x, rate=48000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return str(path)


def _card_copy(x, gain_db=-5.0, rate=48000, to_rate=44100, pad=0.0, cut=None,
               seed=0):
    """*x* the way a Write and an extract leave it: gained to the slot,
    resampled, the codec's noise, cut or padded to the slot's length."""
    if cut is not None:
        x = x[:int(cut * rate)]
    y = x * 10 ** (gain_db / 20)
    t = np.arange(int(len(y) * to_rate / rate)) * rate / to_rate
    y = np.interp(t, np.arange(len(y)), y)
    y = y + np.random.default_rng(seed).normal(0, 0.003, len(y))
    if pad:
        y = np.concatenate([y, np.zeros(int(pad * to_rate))])
    return y, to_rate


def _copy_file(path, x, **kw):
    y, r = _card_copy(x, **kw)
    return _write(path, y, r)


def _find(kind, refs, folder, **kw):
    return om.find_originals(kind, refs, [str(folder)], **kw)["matches"]


# --------------------------------------------------------------------------
# sounds: scoring
# --------------------------------------------------------------------------

def test_a_sound_scores_the_same_louder_and_another_does_not():
    a = om.sound_features(_tune(1)[::3])
    louder = om.sound_features(_tune(1)[::3] * 0.25)
    other = om.sound_features(_tune(2)[::3])
    r, cov, level = om.sound_score(a, louder)
    assert r > 0.99 and cov == 1.0 and level < 0.05
    r2, _cov, level2 = om.sound_score(a, other)
    assert r2 < om.MATCH[om.SOUND] or level2 > om.MAX_LEVEL


def test_silence_has_no_fingerprint():
    assert om.sound_features(np.zeros(16000)) is None


# --------------------------------------------------------------------------
# sounds: finding
# --------------------------------------------------------------------------

@needs_ffmpeg
def test_each_card_copy_finds_its_own_file_among_others(tmp_path):
    mine = tmp_path / "My sounds"
    refs = {}
    for seed in range(5):
        x = _tune(seed)
        _write(mine / ("take %d final.wav" % seed), x)
        refs["audio/idx%04d.wav" % seed] = _copy_file(
            tmp_path / "copies" / ("idx%04d.wav" % seed), x, seed=seed)
    for seed in range(20, 26):                     # files of nothing picked
        _write(mine / "unused" / ("outtake %d.wav" % seed), _tune(seed))
    found = _find(om.SOUND, refs, mine)
    for seed in range(5):
        m = found["audio/idx%04d.wav" % seed]
        assert m.best is not None, m
        assert os.path.basename(m.best.path) == "take %d final.wav" % seed
        assert m.sure and not m.longer and m.best.rate == 48000


@needs_ffmpeg
def test_a_copy_whose_file_is_not_there_is_not_found(tmp_path):
    mine = tmp_path / "mine"
    for seed in range(30, 36):
        _write(mine / ("s%d.wav" % seed), _tune(seed))
    ref = _copy_file(tmp_path / "idx0001.wav", _tune(7))
    m = _find(om.SOUND, {"a": ref}, mine)["a"]
    assert m.best is None and m.score < om.MATCH[om.SOUND]


@needs_ffmpeg
def test_a_file_a_trim_cut_is_found_and_said_to_be_longer(tmp_path):
    x = np.concatenate([_tune(3), _tune(4)])           # 2.4 s
    _write(tmp_path / "mine" / "long take.wav", x)
    ref = _copy_file(tmp_path / "idx0003.wav", x, cut=1.2)
    m = _find(om.SOUND, {"a": ref}, tmp_path / "mine")["a"]
    assert m.best is not None and m.longer


@needs_ffmpeg
def test_a_file_a_build_padded_with_silence_is_found(tmp_path):
    x = _tune(5)
    _write(tmp_path / "mine" / "short.wav", x)
    ref = _copy_file(tmp_path / "idx0005.wav", x, pad=1.5)
    m = _find(om.SOUND, {"a": ref}, tmp_path / "mine")["a"]
    assert m.best is not None and not m.longer and m.sure


@needs_ffmpeg
def test_the_copys_own_length_beats_a_longer_take_that_starts_the_same(
        tmp_path):
    # one sound is often the start of a longer one (TANK FIRE 1 and 2)
    x = _tune(6)
    _write(tmp_path / "mine" / "b exact.wav", x)
    _write(tmp_path / "mine" / "a longer.wav",
           np.concatenate([x, _tune(8)]))
    ref = _copy_file(tmp_path / "idx0006.wav", x)
    m = _find(om.SOUND, {"a": ref}, tmp_path / "mine")["a"]
    assert os.path.basename(m.best.path) == "b exact.wav"
    assert [os.path.basename(v.path) for v in m.variants] == ["a longer.wav"]
    assert m.sure and not m.longer


@needs_ffmpeg
def test_the_same_sound_twice_uses_the_better_copy(tmp_path):
    x = _tune(9)
    _write(tmp_path / "mine" / "z master.wav", x, 48000)
    _write(tmp_path / "mine" / "a export.wav",
           np.interp(np.arange(len(x) // 2) * 2.0, np.arange(len(x)), x),
           24000)
    ref = _copy_file(tmp_path / "idx0009.wav", x)
    m = _find(om.SOUND, {"a": ref}, tmp_path / "mine")["a"]
    assert os.path.basename(m.best.path) == "z master.wav"
    assert [os.path.basename(c.path) for c in m.same] == ["a export.wav"]


@needs_ffmpeg
def test_an_extracts_own_files_are_never_offered(tmp_path):
    x = _tune(10)
    root = tmp_path / "pinball"
    extract = root / "GZ V1.93 extract"
    card = _copy_file(extract / "audio" / "idx0010.wav", x)
    # the extract's baseline names its card files; a source folder kept
    # inside it (a real project keeps .assets/) is the user's own
    (extract / ".checksums.md5").write_text(
        "audio/idx0010.wav\t%s\n" % ("0" * 32), encoding="utf-8")
    _write(extract / ".assets" / "my master.wav", x)
    ref = _copy_file(tmp_path / "picked" / "idx0010.wav", x, seed=3)
    res = om.find_originals(om.SOUND, {"a": ref}, [str(root)])
    m = res["matches"]["a"]
    assert res["card_files"] == 1
    assert os.path.basename(m.best.path) == "my master.wav"
    assert os.path.normcase(m.best.path) != os.path.normcase(card)


@needs_ffmpeg
def test_the_pick_itself_is_not_its_answer_but_a_copy_of_it_is(tmp_path):
    x = _tune(11)
    mine = tmp_path / "mine"
    pick = _copy_file(mine / "picked.wav", x)
    shutil.copy2(pick, mine / "elsewhere.wav")
    m = _find(om.SOUND, {"a": pick}, mine)["a"]
    assert os.path.basename(m.best.path) == "elsewhere.wav"
    assert m.identical


@needs_ffmpeg
def test_fingerprints_are_cached_on_disk(tmp_path, monkeypatch):
    mine = tmp_path / "mine"
    _write(mine / "take.wav", _tune(12))
    ref = _copy_file(tmp_path / "idx0012.wav", _tune(12))
    cache = str(tmp_path / "cache")
    first = _find(om.SOUND, {"a": ref}, mine, cache_dir=cache)["a"]
    assert first.best is not None and os.listdir(cache)
    calls = []
    real = om.decode_sound
    monkeypatch.setattr(om, "decode_sound",
                        lambda p, *a, **k: calls.append(p) or real(p, *a, **k))
    again = _find(om.SOUND, {"a": ref}, mine, cache_dir=cache)["a"]
    assert again.best.path == first.best.path
    assert calls == [ref]               # only the copy, never the folder


def test_a_search_can_be_stopped(tmp_path):
    with pytest.raises(om.Cancelled):
        om.find_originals(om.PICTURE, {}, [str(tmp_path)],
                          cancel=lambda: True)


# --------------------------------------------------------------------------
# pictures
# --------------------------------------------------------------------------

def _art(seed, w=96, h=64, alpha=True):
    """A picture of its own per *seed*: soft blobs of colour."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w] / max(w, h)
    rgb = np.zeros((h, w, 3))
    for _ in range(6):
        cy, cx, r = rng.uniform(0, 1, 3) * (h / max(w, h), w / max(w, h), 0.4)
        blob = np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (r * r + 0.01))
        rgb += blob[..., None] * rng.uniform(0, 255, 3)
    rgb = np.clip(rgb, 0, 255)
    a = np.full((h, w), 255.0)
    if alpha:
        a = np.clip(255 * (1.2 - 2 * np.hypot(yy - 0.3, xx - 0.5)), 0, 255)
    return Image.fromarray(np.dstack([rgb, a]).astype(np.uint8), "RGBA")


def _bw(im):
    from PIL import ImageOps
    g = ImageOps.grayscale(im.convert("RGB"))
    return Image.merge("RGBA", (g, g, g, im.split()[3]))


def _picture_copy(path, master, size):
    """What a Write leaves on the card: stretched to the slot, a colour
    profile, BC3."""
    from pinball_decryptor.plugins.stern import dds
    a = np.asarray(master.resize(size, Image.LANCZOS), np.float32)
    rgb = 255.0 * (np.clip(a[..., :3] * 1.04, 0, 255) / 255.0) ** 0.9
    a = np.clip(np.round(np.dstack([rgb, a[..., 3]])), 0, 255).astype(np.uint8)
    back = dds.decode_bc3(dds.encode_bc3(a), size[0], size[1])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray(back, "RGBA").save(path)
    return str(path)


def test_each_picture_copy_finds_its_own_master(tmp_path):
    mine = tmp_path / "My art"
    mine.mkdir()
    refs = {}
    for seed in range(6):
        im = _art(seed)
        im.resize((192, 128), Image.LANCZOS).save(mine / ("art %d.png" % seed))
        refs["images/p%d.png" % seed] = _picture_copy(
            tmp_path / "copies" / ("p%d.png" % seed),
            Image.open(mine / ("art %d.png" % seed)), (96, 64))
    for seed in range(40, 50):
        _art(seed).save(mine / ("other %d.png" % seed))
    found = _find(om.PICTURE, refs, mine)
    for seed in range(6):
        m = found["images/p%d.png" % seed]
        assert os.path.basename(m.best.path) == "art %d.png" % seed, m
        assert m.sure and (m.best.width, m.best.height) == (192, 128)


def test_a_black_and_white_twin_is_not_its_colour_picture(tmp_path):
    mine = tmp_path / "mine"
    mine.mkdir()
    im = _art(1)
    im.save(mine / "colour.png")
    _bw(im).save(mine / "bw.png")
    to_colour = _picture_copy(tmp_path / "c.png", im, im.size)
    to_bw = _picture_copy(tmp_path / "b.png", _bw(im), im.size)
    found = _find(om.PICTURE, {"c": to_colour, "b": to_bw}, mine)
    assert os.path.basename(found["c"].best.path) == "colour.png"
    assert os.path.basename(found["b"].best.path) == "bw.png"


def test_the_bigger_copy_of_one_picture_wins(tmp_path):
    mine = tmp_path / "mine"
    mine.mkdir()
    im = _art(2)
    im.save(mine / "a small.png")
    big = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
    big.save(mine / "b big.png")
    ref = _picture_copy(tmp_path / "r.png", big, im.size)
    m = _find(om.PICTURE, {"r": ref}, mine)["r"]
    assert os.path.basename(m.best.path) == "b big.png"
    assert [os.path.basename(c.path) for c in m.same] == ["a small.png"]


def test_neighbouring_frames_of_an_animation_are_told_apart(tmp_path):
    # a thumbnail can't see a small moving spark; the copy's own size can
    mine = tmp_path / "frames"
    mine.mkdir()
    base = np.asarray(_art(3, 160, 120, alpha=False)).copy()
    frames = []
    for k in range(5):
        f = base.copy()
        f[60:72, 20 + 12 * k:32 + 12 * k, :3] = 255
        frames.append(Image.fromarray(f, "RGBA"))
        frames[-1].save(mine / ("frame_%02d.png" % k))
    refs = {"f%d" % k: _picture_copy(tmp_path / ("c%d.png" % k), frames[k],
                                     (160, 120)) for k in (1, 3)}
    found = _find(om.PICTURE, refs, mine)
    assert os.path.basename(found["f1"].best.path) == "frame_01.png"
    assert os.path.basename(found["f3"].best.path) == "frame_03.png"


def test_a_flat_picture_finds_a_flat_one_of_its_level(tmp_path):
    mine = tmp_path / "mine"
    mine.mkdir()
    for seed in range(8):
        _art(seed).save(mine / ("art %d.png" % seed))
    Image.new("RGBA", (20, 6), (255, 255, 255, 255)).save(mine / "dash.png")
    Image.new("RGBA", (20, 6), (90, 90, 90, 255)).save(mine / "grey dash.png")
    ref = tmp_path / "U+002D.png"
    Image.new("RGBA", (10, 3), (254, 254, 254, 255)).save(ref)
    m = _find(om.PICTURE, {"r": str(ref)}, mine)["r"]
    assert os.path.basename(m.best.path) == "dash.png"


def test_a_slots_name_settles_a_dead_heat(tmp_path):
    # one glyph in two atlases is the same picture; the one named like the
    # slot is the one
    mine = tmp_path / "glyphs"
    letter = _art(4, 24, 32)
    for atlas in ("radimg_a_11111111", "radimg_b_22222222"):
        (mine / atlas).mkdir(parents=True)
    letter.save(mine / "radimg_a_11111111" / "U+0047_G.png")
    letter.save(mine / "radimg_b_22222222" / "U+0051_Q.png")
    ref = _picture_copy(tmp_path / "copy.png", letter, (24, 32))
    key = "images/scene_textures/glyphs/radimg_x_33333333/U+0047_G.png"
    m = _find(om.PICTURE, {key: ref}, mine)[key]
    assert os.path.basename(m.best.path) == "U+0047_G.png"


def test_listing_skips_app_folders_and_extract_card_files(tmp_path):
    root = tmp_path / "root"
    ext = root / "old extract"
    for rel in ("images/a.png", "images/b.png", ".assets/mine.png",
                "build/out.png", "card_files/x.png", ".orig/images/a.png"):
        p = ext / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4)).save(p)
    (ext / ".checksums.md5").write_text(
        "images/a.png\t%s\nimages/b.png\t%s\n" % ("0" * 32, "1" * 32),
        encoding="utf-8")
    Image.new("RGB", (4, 4)).save(root / "loose.png")
    (root / "notes.txt").write_text("x", encoding="utf-8")
    paths, skipped = om.list_files([str(root)], om.PICTURE_EXTS)
    names = sorted(os.path.relpath(p, root).replace(os.sep, "/") for p in paths)
    assert names == ["loose.png", "old extract/.assets/mine.png"]
    assert skipped == 2
    # searched from inside the extract, its card files are still its own
    paths, skipped = om.list_files([str(ext / "images")], om.PICTURE_EXTS)
    assert paths == [] and skipped == 2
    cards = om.CardFiles()
    assert cards.is_card_file(str(ext / "images" / "a.png"))
    assert not cards.is_card_file(str(ext / ".assets" / "mine.png"))
    assert not cards.is_card_file(str(root / "loose.png"))


def test_unreadable_copies_are_reported(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a picture")
    res = om.find_originals(om.PICTURE, {"x": str(bad)}, [str(tmp_path)])
    assert res["unreadable"] == ["x"] and res["matches"] == {}
    json.dumps(res["unreadable"])
