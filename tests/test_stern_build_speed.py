"""A build's own speed-ups: one progress bar, the per-card play tables, the clips made side by
side and kept, the code modes' object kept and compiled early (desk only; the clip tests need
ffmpeg and skip without it)."""
import os
import threading

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import mode_assets as MA
from pinball_decryptor.plugins.stern import mode_write as MW


# ---- one bar for the whole build ------------------------------------------------------------
def test_a_stage_reports_in_its_own_stretch_of_the_bar():
    got = []
    cb = E._span(lambda d, t, w: got.append((d, t, w)), 12, 30, "Deriving the grown sound bank")
    cb(0, 0, "Reading the game's sound directory...")
    cb(1, 2535, "x")
    cb(2535, 2535, "x")
    assert got[0] == (12, 100, "Deriving the grown sound bank...")
    assert got[1][0] == 12 and got[1][2] == "Deriving the grown sound bank: sound 1 of 2535..."
    assert got[2][:2] == (30, 100)
    plain = []
    E._span(lambda d, t, w: plain.append((d, w)), 97, 100)(3, 12, "Writing game")
    assert plain == [(97, "Writing game")]
    assert E._span(None, 0, 1) is None


def test_a_stage_on_the_builds_scale_is_moved_into_its_stretch():
    got = []
    cb = E._rescale(lambda d, t, w: got.append((d, t, w)), 10, 75, 31, 45)
    cb(10, 100, "a")
    cb(75, 100, "b")
    cb(42, 100, "c")
    assert got == [(31, 100, "a"), (45, 100, "b"), (37, 100, "c")]


def test_the_bar_never_moves_back_but_the_words_do():
    got = []
    cb = E._forward_only(lambda d, t, w: got.append((d, t, w)))
    cb(30, 100, "derive")
    cb(12, 100, "re-point")
    cb(0, 0, "no figure")
    cb(45, 100, "encode")
    assert got == [(30, 100, "derive"), (30, 100, "re-point"), (0, 0, "no figure"),
                   (45, 100, "encode")]
    assert E._forward_only(cb) is cb and E._forward_only(None) is None


# ---- the play tables, kept per card ------------------------------------------------------------
def test_the_play_tables_are_read_once_per_card(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_params_cache_dir", lambda: str(tmp_path))
    gr, img, card = tmp_path / "game_real", tmp_path / "image.bin", tmp_path / "card.raw"
    gr.write_bytes(b"\x7fELF" + b"\x01" * 64)
    img.write_bytes(b"\x02" * 0x1000)
    card.write_bytes(b"\x03" * 0x1000)
    calls = []

    def reader(g, i, log=None):
        calls.append(1)
        return [E._DescSite(5, 0x10, b"k" * 8, b"p" * 8, 0x20, b"d" * 4, 99)]
    monkeypatch.setattr(E, "_descriptor_sites", reader)
    monkeypatch.setattr(E, "_DESCRIPTOR_SITES", reader)            # the genuine reader here
    with open(card, "rb") as f:
        key = E._card_sites_key(f, str(gr), str(img))
    assert key
    first = E._card_descriptor_sites(str(gr), str(img), None, card_key=key)
    again = E._card_descriptor_sites(str(gr), str(img), None, card_key=key)
    assert first == again and len(calls) == 1
    assert isinstance(again[0], E._DescSite) and again[0].duration == 99
    # another card image (its mtime moved) is read again
    os.utime(card, (1, 1))
    with open(card, "rb") as f:
        assert E._card_sites_key(f, str(gr), str(img)) != key
    # a stand-in reader (a test's) is always asked and never kept
    monkeypatch.setattr(E, "_DESCRIPTOR_SITES", object())
    E._card_descriptor_sites(str(gr), str(img), None, card_key=key)
    assert len(calls) == 2
    assert E._is_stale_cache_file(os.path.basename(E._sites_cache_path(key))) is False


def test_a_card_that_is_not_a_file_has_no_play_table_key():
    class Device:
        name = 3                               # a raw device's handle names no file
    assert E._card_sites_key(Device(), "g", "i") is None


# ---- the clips: side by side, and kept ---------------------------------------------------------
def _ffmpeg():
    from pinball_decryptor.core import audio
    p = audio.find_ffmpeg()
    if not p:
        pytest.skip("no ffmpeg")
    return p


def test_clips_made_side_by_side_are_the_clips_the_loop_made(tmp_path, monkeypatch):
    ff = _ffmpeg()
    monkeypatch.setattr(MA, "clip_cache_dir", lambda: str(tmp_path / "cache"))
    jobs = [MA.ClipJob("title", 320, 180, title="KAIJU RUSH", seconds=1.0,
                       panel_color="#146e28", title_color="#ffe600"),
            MA.ClipJob("title", 320, 180, title="MOTHRA", seconds=0.5,
                       panel_color="#000000", title_color="#ffffff")]
    made, scratch = MA.make_clips(jobs, ff)
    assert scratch is None and set(made) == set(jobs)
    for job in jobs:
        direct = str(tmp_path / ("direct_%s.mp4" % job.title.replace(" ", "_")))
        MA.render_title_clip(direct, job.title, job.w, job.h, job.seconds, job.panel_color,
                             job.title_color, ff)
        with open(direct, "rb") as a, open(made[job], "rb") as b:
            assert a.read() == b.read(), "a clip made in the pool differs from one made alone"


def test_a_clip_made_before_is_copied_not_encoded(tmp_path, monkeypatch):
    monkeypatch.setattr(MA, "clip_cache_dir", lambda: str(tmp_path / "cache"))
    monkeypatch.delenv(MA.CLIP_CACHE_ENV, raising=False)
    encoded, seen = [], []
    lock = threading.Lock()

    def encode(job, out, ffmpeg):
        with lock:
            encoded.append(job.title)
        with open(out, "wb") as f:
            f.write(job.title.encode())
    monkeypatch.setattr(MA, "_encode_clip", encode)
    jobs = [MA.ClipJob("title", 8, 8, title=t, seconds=1.0) for t in ("A", "B", "C", "D", "E")]
    made, _s = MA.make_clips(jobs, "ffmpeg", progress=lambda d, t, w: seen.append((d, t)))
    assert sorted(encoded) == ["A", "B", "C", "D", "E"] and len(made) == 5
    assert sorted(seen) == [(i, 5) for i in range(1, 6)]
    encoded.clear()
    made2, _s = MA.make_clips(jobs + [MA.ClipJob("title", 8, 8, title="F", seconds=1.0)], "ffmpeg")
    assert encoded == ["F"], "the kept clips were encoded again"
    assert open(made2[jobs[0]], "rb").read() == b"A"
    # the same title at another length is another clip
    assert MA.clip_key(jobs[0], "ffmpeg") != MA.clip_key(
        MA.ClipJob("title", 8, 8, title="A", seconds=2.0), "ffmpeg")
    # caching off: made in a scratch folder the caller removes
    monkeypatch.setenv(MA.CLIP_CACHE_ENV, "0")
    made3, scratch = MA.make_clips(jobs[:1], "ffmpeg")
    assert scratch and made3[jobs[0]].startswith(scratch)


def test_the_first_failing_clip_is_the_error(tmp_path, monkeypatch):
    monkeypatch.setattr(MA, "clip_cache_dir", lambda: str(tmp_path / "cache"))

    def encode(job, out, ffmpeg):
        if job.title in ("B", "C"):
            raise MA.ModeAssetError("ffmpeg could not encode %s" % job.title)
        with open(out, "wb") as f:
            f.write(b"ok")
    monkeypatch.setattr(MA, "_encode_clip", encode)
    jobs = [MA.ClipJob("title", 8, 8, title=t) for t in ("A", "B", "C")]
    with pytest.raises(MA.ModeAssetError, match="encode B"):
        MA.make_clips(jobs, "ffmpeg")
    assert not [n for n in os.listdir(str(tmp_path / "cache")) if ".tmp" in n]


def test_a_video_clip_is_kept_by_its_bytes(tmp_path, monkeypatch):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"one")
    job = MA.ClipJob("file", 8, 8, src=str(src))
    k1 = MA.clip_key(job, "ffmpeg")
    src.write_bytes(b"two")
    os.utime(src, (5, 5))
    assert MA.clip_key(job, "ffmpeg") != k1
    missing = MA.ClipJob("file", 8, 8, src=str(tmp_path / "gone.mp4"))
    assert MA.clip_key(missing, "ffmpeg")        # the encode, not the key, says it is missing


# ---- the code modes' object: kept, and compiled early --------------------------------------------
class _Executor:
    def __init__(self, runs):
        self.runs = runs

    def to_exec_path(self, p):
        return p

    def run(self, cmd, timeout=None):
        self.runs.append(cmd)
        out = cmd.split(" -o ", 1)[1].split(" ", 1)[0].strip("'")
        with open(out, "wb") as f:
            f.write(b"\x7fELF object for " + str(len(self.runs)).encode())
        return "built"


def _code_mode(tmp_path, text="/* a mode */\n"):
    folder = tmp_path / "modes" / "blitz"
    folder.mkdir(parents=True, exist_ok=True)
    src = folder / "blitz.c"
    src.write_text(text)
    return str(src)


def test_the_same_sources_take_the_kept_object(tmp_path, monkeypatch):
    from pinball_decryptor.core import executor
    runs = []
    monkeypatch.setattr(executor, "create_executor", lambda: _Executor(runs))
    monkeypatch.setattr(MW, "code_cache_dir", lambda: str(tmp_path / "objs"))
    monkeypatch.delenv(MW.CODE_CACHE_ENV, raising=False)
    src = _code_mode(tmp_path)
    said = []
    a = MW.compile_code_object([src], str(tmp_path / "a" / "mode.so"),
                               log=lambda m, *k: said.append(m))
    b = MW.compile_code_object([src], str(tmp_path / "b" / "mode.so"),
                               log=lambda m, *k: said.append(m))
    assert len(runs) == 1 and open(a, "rb").read() == open(b, "rb").read()
    assert "earlier build" in said[-1]
    # a header beside the mode is part of what it is
    (tmp_path / "modes" / "blitz" / "extra.h").write_text("#define X 1\n")
    MW.compile_code_object([src], str(tmp_path / "c" / "mode.so"))
    assert len(runs) == 2
    # a caller's own executor always compiles
    mine = []
    MW.compile_code_object([src], str(tmp_path / "d" / "mode.so"), executor=_Executor(mine))
    assert len(mine) == 1
    monkeypatch.setenv(MW.CODE_CACHE_ENV, "0")
    MW.compile_code_object([src], str(tmp_path / "e" / "mode.so"))
    assert len(runs) == 3


def test_the_key_counts_every_file_a_compile_could_include(tmp_path):
    """gcc finds a quoted include beside the source or in any folder under it, whatever its
    extension, so each of those is in the key; the mode's pictures, clips, sounds and
    assets.json are not, so an asset edit keeps the kept object."""
    src = _code_mode(tmp_path)
    folder = tmp_path / "modes" / "blitz"
    key = MW.code_object_key([src])
    assert MW.code_object_key([src]) == key
    for rel, text in (("util.inc", "int u;\n"), ("lib/x.h", "#define Y 2\n"),
                      ("helpers.c", "int h;\n")):
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        new = MW.code_object_key([src])
        assert new != key, rel
        path.write_text(text + "/* edited */\n")
        assert MW.code_object_key([src]) != new, rel + " edited"
        key = MW.code_object_key([src])
    for name in ("clip.mp4", "music.wav", "screen.png", "assets.json"):
        (folder / name).write_bytes(b"not code")
    assert MW.code_object_key([src]) == key


def test_a_compile_started_early_is_the_one_the_build_takes(tmp_path, monkeypatch):
    from pinball_decryptor.core import executor
    runs = []
    gate = threading.Event()

    class Slow(_Executor):
        def run(self, cmd, timeout=None):
            gate.wait(10)
            return _Executor.run(self, cmd, timeout)
    monkeypatch.setattr(executor, "create_executor", lambda: Slow(runs))
    monkeypatch.setattr(MW, "code_cache_dir", lambda: str(tmp_path / "objs"))
    monkeypatch.delenv(MW.CODE_CACHE_ENV, raising=False)
    src = _code_mode(tmp_path, "/* early */\n")
    t = MW.prefetch_code_object([src])
    assert t is not None
    assert MW.prefetch_code_object([src]) is None            # one compile per key at a time
    done = []
    waiter = threading.Thread(target=lambda: done.append(
        MW.compile_code_object([src], str(tmp_path / "out" / "mode.so"))))
    waiter.start()
    gate.set()
    t.join(10)
    waiter.join(10)
    assert done and len(runs) == 1, "the build compiled again instead of waiting"
    assert MW.prefetch_code_object([src]) is None            # kept: nothing to start


def test_a_stand_in_compile_is_never_run_early(tmp_path, monkeypatch):
    monkeypatch.setattr(MW, "compile_code_object", lambda *a, **k: None)
    assert MW.prefetch_code_object([_code_mode(tmp_path)]) is None


# ---- a card's firmware + image.bin, kept for the next override set ----------------------------
class _Reader:
    def __init__(self):
        self.calls = []

    def extract_file(self, node, path, progress=None):
        self.calls.append(node["name"])
        with open(path, "wb") as f:
            f.write(node["data"])
        if progress:
            progress(len(node["data"]), len(node["data"]))


def test_an_override_set_takes_the_cards_pair_from_its_kept_copy(tmp_path, monkeypatch):
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 4096)
    reader = _Reader()
    fw = {"name": "game", "size": 5, "i_block": b"\x01" * 60, "data": b"ELF!!"}
    img = {"name": "image.bin", "size": 9, "i_block": b"\x02" * 60, "data": b"soundbank"}
    monkeypatch.setattr(E, "_locate", lambda disk_f, parts: (reader, fw, img))
    monkeypatch.setattr(E, "card_cache_dir", lambda: str(tmp_path / "kept"))
    monkeypatch.delenv(E.CARD_CACHE_ENV, raising=False)
    said = []
    say = lambda m, *a, **k: said.append(m)                     # noqa: E731

    def extract(work):
        os.makedirs(work)
        with open(card, "rb") as f:
            return E._extract_inputs_kept(f, [], str(work), say)

    # a Write (no override set) reads the card and keeps nothing
    extract(tmp_path / "w0")
    assert reader.calls == ["game", "image.bin"] and not os.path.exists(tmp_path / "kept")
    E._KEEP_EXTRACTS.on = True
    try:
        gr, im, _r, _f, _i = extract(tmp_path / "w1")
        assert reader.calls[2:] == ["game", "image.bin"]
        kept_lines = [m for m in said if m.startswith("Kept a copy")]
        assert len(kept_lines) == 1 and E.CARD_CACHE_ENV + "=0" in kept_lines[0]
        # the build's own copy is staged over (a grown bank): the kept pair is untouched
        with open(im, "r+b") as f:
            f.write(b"GROWN")
        gr2, im2, _r, _f, _i = extract(tmp_path / "w2")
        assert len(reader.calls) == 4, "the card was read again"
        assert open(im2, "rb").read() == b"soundbank" and open(gr2, "rb").read() == b"ELF!!"
        # another card file (its mtime moved) is read again
        os.utime(card, (5, 5))
        extract(tmp_path / "w3")
        assert len(reader.calls) == 6
        monkeypatch.setenv(E.CARD_CACHE_ENV, "0")
        extract(tmp_path / "w4")
        assert len(reader.calls) == 8
    finally:
        E._KEEP_EXTRACTS.on = False


def test_only_a_caller_that_asks_keeps_the_card(tmp_path, monkeypatch):
    """The Emulate tab's override set (and any caller that does not ask) keeps no card copy;
    the preview-set builder asks with keep_card_extracts."""
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 4096)
    seen = []

    def compute(*a, **k):
        seen.append(getattr(E._KEEP_EXTRACTS, "on", False))
        return None, None, None, None, None                     # as a cancelled compute
    monkeypatch.setattr(E, "_linux_partitions", lambda p: [])
    monkeypatch.setattr(E, "_compute_patches", compute)
    monkeypatch.setattr(E, "_rmtree_grow_plan", lambda plan: None)

    def build(n):
        return E.write_overrides(str(card), str(tmp_path), str(tmp_path / ("set%d" % n)))
    assert build(0) == (None, None, None, None)
    with E.keep_card_extracts():
        build(1)
    build(2)
    assert seen == [False, True, False]
    assert not E._KEEP_EXTRACTS.on and not getattr(E._KEEP_EXTRACTS, "wanted", False)


def test_the_preview_set_builder_asks_to_keep_the_card(tmp_path, monkeypatch):
    import inspect
    src = inspect.getsource(MW.build_tryit_set)
    assert "with E.keep_card_extracts():" in src and "E.write_overrides(" in src
    assert src.index("with E.keep_card_extracts():") < src.index("E.write_overrides(")
