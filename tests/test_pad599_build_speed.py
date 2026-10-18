"""PAD-599: a big build (hundreds of clips, sounds and pictures) staged one
file after another, probed the same clip over and over, converted every
assigned sound again on every build, and encoded every scene picture one at
a time.  These pin the faster paths: the probe memo, the sound staging
cache, and clips / pictures / block encodes running several at once with
their results (and log lines) exactly what one-at-a-time gave."""

import os
import threading
import time

import pytest

from tests.test_audio_slots import _make_wav


# -- the probe memo ------------------------------------------------------------

def _counting_probe(monkeypatch):
    from pinball_decryptor.core import video
    calls = []

    def fake(path):
        calls.append(path)
        return video.VideoInfo(path, vcodec="h264", width=64, height=48,
                               fps=30.0, duration=1.0)

    monkeypatch.setattr(video, "_probe_video_info", fake)
    monkeypatch.setattr(video, "_PROBE_MEMO", {})
    return calls


def test_an_unchanged_clip_is_probed_once(tmp_path, monkeypatch):
    from pinball_decryptor.core import video
    calls = _counting_probe(monkeypatch)
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"\x00" * 64)
    first = video.detect_video_info(str(clip))
    second = video.detect_video_info(str(clip))
    assert len(calls) == 1
    assert (second.width, second.height) == (64, 48)
    # a caller adjusting its answer does not change the next one's
    second.duration = 99.0
    assert video.detect_video_info(str(clip)).duration == 1.0
    assert first is not second


def test_a_changed_clip_is_probed_again(tmp_path, monkeypatch):
    from pinball_decryptor.core import video
    calls = _counting_probe(monkeypatch)
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"\x00" * 64)
    video.detect_video_info(str(clip))
    clip.write_bytes(b"\x00" * 65)                 # a new size
    video.detect_video_info(str(clip))
    st = os.stat(clip)
    os.utime(clip, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    video.detect_video_info(str(clip))             # a new modification time
    assert len(calls) == 3


def test_the_duration_probe_is_kept_too(tmp_path, monkeypatch):
    from pinball_decryptor.core import audio
    calls = []
    monkeypatch.setattr(audio, "_ffmpeg_get_duration",
                        lambda p: calls.append(p) or 2.5)
    monkeypatch.setattr(audio, "_DURATION_MEMO", {})
    f = tmp_path / "a.mp4"
    f.write_bytes(b"\x00" * 10)
    assert audio.probe_duration(str(f)) == 2.5
    assert audio.probe_duration(str(f)) == 2.5
    assert len(calls) == 1


# -- sounds: the staging cache ------------------------------------------------

def _sound_project(tmp_path, n=3):
    from pinball_decryptor.core.audio_slots import scan_audio_slots
    from pinball_decryptor.core.checksums import generate_checksums
    assets = str(tmp_path / "proj")
    for i in range(n):
        _make_wav(os.path.join(assets, "audio", "idx%04d.wav" % i), seconds=0.3)
    generate_checksums(assets)
    reps = {}
    for i in range(n):
        rep = str(tmp_path / ("rep%d.wav" % i))
        _make_wav(rep, seconds=0.5, channels=2, freq=300 + 50 * i)
        reps["audio/idx%04d.wav" % i] = rep
    slots = {s.rel_path: s for s in scan_audio_slots(assets)}
    return assets, slots, reps


def _count_sound_stagings(monkeypatch):
    from pinball_decryptor.core import audio_slots
    real, seen = audio_slots.stage_replacement, []

    def counted(slot, rep, **kw):
        seen.append(slot.rel_path)
        return real(slot, rep, **kw)

    monkeypatch.setattr(audio_slots, "stage_replacement", counted)
    return seen


def test_a_second_build_converts_no_sound_again(tmp_path, monkeypatch):
    from pinball_decryptor.core.audio_slots import stage_replacements
    assets, slots, reps = _sound_project(tmp_path)
    seen = _count_sound_stagings(monkeypatch)
    staged, failures = stage_replacements(slots, reps, assets_dir=assets)
    assert staged == 3 and failures == [] and len(seen) == 3
    stamps = {rel: os.stat(slots[rel].abs_path).st_mtime_ns for rel in reps}
    logs = []
    staged, failures = stage_replacements(
        slots, reps, assets_dir=assets, log_cb=lambda t, l: logs.append(t))
    assert staged == 3 and failures == []
    assert len(seen) == 3                          # nothing converted again
    # the files are left alone, so the build's change scan hashes nothing
    assert {rel: os.stat(slots[rel].abs_path).st_mtime_ns
            for rel in reps} == stamps
    assert any("already converted" in t for t in logs)


def test_a_new_source_or_trim_converts_that_sound_again(tmp_path, monkeypatch):
    from pinball_decryptor.core.audio_slots import stage_replacements
    assets, slots, reps = _sound_project(tmp_path)
    stage_replacements(slots, reps, assets_dir=assets)
    seen = _count_sound_stagings(monkeypatch)
    rel = "audio/idx0001.wav"
    _make_wav(reps[rel], seconds=0.7, channels=2, freq=900)   # a new file
    stage_replacements(slots, reps, assets_dir=assets)
    assert seen == [rel]
    seen.clear()
    stage_replacements(slots, reps, trim_to_length=True, assets_dir=assets)
    assert sorted(seen) == sorted(reps)


def test_a_sound_touched_since_is_converted_again(tmp_path, monkeypatch):
    from pinball_decryptor.core.audio_slots import stage_replacements
    assets, slots, reps = _sound_project(tmp_path)
    stage_replacements(slots, reps, assets_dir=assets)
    seen = _count_sound_stagings(monkeypatch)
    rel = "audio/idx0002.wav"
    _make_wav(slots[rel].abs_path, seconds=0.3)    # something else wrote it
    stage_replacements(slots, reps, assets_dir=assets)
    assert seen == [rel]


def test_sounds_staged_at_once_log_in_order(tmp_path, monkeypatch):
    from pinball_decryptor.core.audio_slots import stage_replacements
    monkeypatch.setenv("PAD_STAGE_WORKERS", "4")
    assets, slots, reps = _sound_project(tmp_path, n=6)
    logs = []
    staged, failures = stage_replacements(
        slots, reps, assets_dir=assets, log_cb=lambda t, l: logs.append(t))
    assert staged == 6 and failures == []
    order = [t.split()[1] for t in logs if t.startswith("Staging ")]
    assert order == list(reps)
    for rel in reps:            # each sound's ✓ right after its Staging line
        i = logs.index(next(t for t in logs if t.startswith("Staging " + rel)))
        assert logs[i + 1].startswith("  ✓ " + rel)


# -- clips: several at once -----------------------------------------------------

def _clip_project(tmp_path, n):
    from pinball_decryptor.core.video import VideoInfo
    from pinball_decryptor.core.video_slots import VideoSlot
    assets = tmp_path / "proj"
    slots, reps = {}, {}
    for i in range(n):
        rel = "video/c%02d.mp4" % i
        p = assets / "video" / ("c%02d.mp4" % i)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"stock%d" % i)
        info = VideoInfo(str(p), vcodec="h264", width=64, height=48, fps=30.0,
                         duration=1.0)
        slots[rel] = VideoSlot(rel_path=rel, abs_path=str(p), ext=".mp4",
                               info=info, size=6, probed=True)
        rep = tmp_path / ("r%02d.mp4" % i)
        rep.write_bytes(b"rep%d" % i)
        reps[rel] = str(rep)
    return str(assets), slots, reps


def _fake_clip_staging(monkeypatch, fail=()):
    """stage_replacement as a slow conversion that records how many ran at
    once; the clips in *fail* fail."""
    from pinball_decryptor.core import video_slots
    state = {"now": 0, "most": 0, "done": []}
    lock = threading.Lock()

    def fake(slot, rep, **kw):
        with lock:
            state["now"] += 1
            state["most"] = max(state["most"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
            state["done"].append(slot.rel_path)
        if slot.rel_path in fail:
            return False, "ffmpeg failed"
        with open(slot.abs_path, "wb") as f:
            f.write(b"converted " + open(rep, "rb").read())
        return True, "re-encoded"

    monkeypatch.setattr(video_slots, "stage_replacement", fake)
    monkeypatch.setattr(video_slots, "_pristine_slot", lambda s, o: s)
    monkeypatch.setattr(video_slots, "_clip_bitrate", lambda p: None)
    monkeypatch.setattr(video_slots, "_slot_keyint", lambda p: 0)
    return state


def test_clips_convert_several_at_once(tmp_path, monkeypatch):
    from pinball_decryptor.core import video_slots
    monkeypatch.setenv("PAD_STAGE_WORKERS", "4")
    assets, slots, reps = _clip_project(tmp_path, 8)
    state = _fake_clip_staging(monkeypatch, fail={"video/c03.mp4"})
    logs, progress = [], []
    staged, failures = video_slots.stage_replacements(
        slots, reps, assets_dir=assets,
        log_cb=lambda t, l: logs.append(t),
        progress_cb=lambda i, n, d: progress.append((i, n)))
    assert state["most"] > 1
    assert staged == 7
    assert failures == [("video/c03.mp4", "ffmpeg failed")]
    # each clip's lines together: its Staging line, then its result
    for rel in reps:
        i = logs.index(next(t for t in logs if t.startswith("Staging " + rel)))
        assert logs[i + 1].startswith(("  ✓ " + rel, "  ✗ " + rel))
    assert progress[-1] == (8, 8)
    assert [i for i, _n in progress] == sorted(i for i, _n in progress)
    # and the next build keeps all but the one that failed
    state["done"].clear()
    staged, failures = video_slots.stage_replacements(slots, reps,
                                                      assets_dir=assets)
    assert state["done"] == ["video/c03.mp4"]


def test_one_worker_is_the_old_one_at_a_time(tmp_path, monkeypatch):
    from pinball_decryptor.core import video_slots
    monkeypatch.setenv("PAD_STAGE_WORKERS", "1")
    assets, slots, reps = _clip_project(tmp_path, 4)
    state = _fake_clip_staging(monkeypatch)
    video_slots.stage_replacements(slots, reps, assets_dir=assets)
    assert state["most"] == 1
    assert state["done"] == list(reps)


def test_a_cancel_stops_starting_clips(tmp_path, monkeypatch):
    from pinball_decryptor.core import video_slots
    monkeypatch.setenv("PAD_STAGE_WORKERS", "2")
    assets, slots, reps = _clip_project(tmp_path, 10)
    state = _fake_clip_staging(monkeypatch)
    logs = []
    staged, failures = video_slots.stage_replacements(
        slots, reps, assets_dir=assets, log_cb=lambda t, l: logs.append(t),
        cancel_cb=lambda: len(state["done"]) >= 2)
    assert len(state["done"]) < 10
    assert staged == len(state["done"])
    assert any(t.startswith("Canceled") for t in logs)


def test_the_worker_count(monkeypatch):
    from pinball_decryptor.core import video_slots, audio_slots, image_slots
    from pinball_decryptor.plugins.stern import engine
    monkeypatch.delenv("PAD_STAGE_WORKERS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert video_slots.staging_workers(300) == 6
    assert video_slots.staging_workers(2) == 2
    assert audio_slots.audio_workers(300) == 8
    assert image_slots.picture_workers(300) == 8
    assert engine._encode_workers() == 8
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    assert video_slots.staging_workers(300) == 1
    monkeypatch.setenv("PAD_STAGE_WORKERS", "3")
    assert video_slots.staging_workers(300) == 3
    assert image_slots.picture_workers(300) == 3


# -- scene textures: encoded at once, placed in order -------------------------

def test_textures_encoded_at_once_come_back_in_order(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    from pinball_decryptor.plugins.stern import dds, engine
    monkeypatch.setenv("PAD_STAGE_WORKERS", "4")
    edits, nodes = [], {}
    for i in range(6):
        png = tmp_path / ("t%d.png" % i)
        Image.new("RGBA", (8, 8), (40 * i, 10, 10, 255)).save(png)
        edits.append(("t%d.png" % i, "/card/t%d" % i, str(png), 8, 8,
                      engine._DXT5_FORMAT))
        nodes["/card/t%d" % i] = {"size": 64, "i_block": bytes([i]) * 60,
                                  "id": i}
    monkeypatch.setattr(engine, "_resolve_card_nodes",
                        lambda reader, paths, cancel: dict(nodes))

    class Reader:
        def read_file_bytes(self, node):
            return b"\x00" * node["size"]

    real = dds.encode_bc3

    def slow(arr):          # the first ones finish last
        time.sleep(0.02 * (6 - int(arr[0, 0, 0]) // 40))
        return real(arr)

    monkeypatch.setattr(dds, "encode_bc3", slow)
    monkeypatch.setattr(dds, "encode_bc1", slow)
    logs = []
    patches, skipped = engine._prepare_texture_patches(
        Reader(), edits, lambda t, l="info": logs.append(t), lambda: False)
    assert skipped == 0
    assert [n["id"] for n, _p in patches] == list(range(6))
    for i, (_n, payload) in enumerate(patches):
        arr = np.asarray(Image.open(edits[i][2]).convert("RGBA"),
                         dtype=np.uint8)
        assert payload == real(arr)
    ready = [t for t in logs if "ready to patch" in t]
    assert [t.split()[1].rstrip(":") for t in ready] == ["t%d.png" % i for i in range(6)]


# -- a long sound's blocks on workers -------------------------------------------

class _Mem:
    def __init__(self, n):
        self.b = bytes(n)

    def __getitem__(self, sl):
        return self.b[sl]


def _stub_mono(np):
    """A GenRecover whose keystream is a function of the position alone, as
    the firmware's is: enough to show where each block's words land."""
    from pinball_decryptor.plugins.stern.spike2 import codec
    gr = object.__new__(codec.GenRecover)
    gr.emu = type("E", (), {"mm": _Mem(1 << 22)})()
    gr.qmul = 3
    gr._calibrate = lambda p: (0, 0, -1)

    def recover(p, cursor, n=200):
        i = np.arange(n, dtype=np.int64) + cursor
        return (i * 2654435761) & 0xffff, i % 16

    gr.recover_block = recover
    gr._encode_leadout = lambda *a: None
    return gr


def _mono_blocks(gr, np, calls):
    def blocks(p, jobs, three=None):
        calls.append(len(jobs))
        out = {}
        for k, cursor, seg, _r in jobs:
            K, rb = gr.recover_block(p, cursor, n=len(seg))
            enc, _ = gr.encode_block(np.asarray(seg, np.int64)[:len(K)], K, rb)
            out[k] = (len(K), enc)
        return out
    return blocks


def test_a_mono_sound_from_workers_is_the_same_bytes():
    np = pytest.importorskip("numpy")
    pytest.importorskip("unicorn")
    gr = _stub_mono(np)
    p = {"length": 200 * 300 + 77, "body_off": 4096, "scale": 3, "chan": 1}
    rng = np.random.default_rng(5)
    tgt = rng.integers(-9000, 9000, p["length"] - 150)
    alone = gr.encode_sound(p, tgt)
    calls = []
    shared = gr.encode_sound(p, tgt, blocks=_mono_blocks(gr, np, calls))
    assert calls == [-(-len(tgt) // 200) - 1]     # every block but the first
    assert shared == alone
    # a pool that gives up leaves the parent to encode them, the same bytes
    assert gr.encode_sound(p, tgt, blocks=lambda *a, **k: None) == alone


def test_a_stereo_sound_from_workers_is_the_same_bytes_and_shares_the_probe_rule():
    np = pytest.importorskip("numpy")
    pytest.importorskip("unicorn")
    from pinball_decryptor.plugins.stern.spike2 import codec
    sr = object.__new__(codec.StereoRecover)
    sr.emu = type("E", (), {"mm": _Mem(1 << 23)})()
    sr.qmul = 5
    sr._three_probe = {}
    sr._calibrate = lambda p: 0
    sr._encode_leadout = lambda *a: None

    def recover(p, cursor, nf=200):
        i = np.arange(nf, dtype=np.int64) + cursor
        sr._three_probe.setdefault((p["scale"], p["chan"]), False)
        z = np.zeros(nf, np.int64)
        return {"KL": (i * 40503) & 0xffff, "rbL": i % 16,
                "KR": (i * 9973) & 0xffff, "aR": (i // 3) % 16, "bR": z,
                "m": nf}

    sr.recover_block = recover
    p = {"length": 200 * 280 + 13, "body_off": 8192, "scale": 22, "chan": 2}
    rng = np.random.default_rng(9)
    L = rng.integers(-5000, 5000, p["length"] - 100)
    R = rng.integers(-5000, 5000, p["length"] - 100)
    alone = sr.encode_sound(p, L, R)
    seen = []

    def blocks(pp, jobs, three=None):
        seen.append(three)
        out = {}
        for k, cursor, a, b in jobs:
            rec = recover(pp, cursor, nf=len(a))
            frame, _ = sr.encode_block(np.asarray(a, np.int64),
                                       np.asarray(b, np.int64), rec)
            out[k] = (rec["m"], frame)
        return out

    sr._three_probe = {}
    assert sr.encode_sound(p, L, R, blocks=blocks) == alone
    assert seen == [False]      # the first block's answer, handed on


def test_a_block_pool_whose_workers_cannot_start_gives_the_work_back(tmp_path):
    from pinball_decryptor.plugins.stern.spike2 import parallel
    logs = []
    pool = parallel.BlockPool("image", str(tmp_path / "no_game_real"),
                              str(tmp_path / "no_image.bin"), [], 2,
                              log=lambda t, l="info": logs.append((t, l)))
    try:
        jobs = [(k, 200 + 200 * k, [0] * 200, None)
                for k in range(1, parallel.BLOCKS_MIN + 5)]
        assert pool.blocks({"chan": 1, "scale": 0}, jobs) is None
        assert pool.broken
        assert any(l == "warning" and "one process" in t for t, l in logs)
        pool.warm({"idx": 1})                       # a no-op once broken
        assert pool.blocks({"chan": 1, "scale": 0}, jobs) is None
    finally:
        pool.close()


def test_short_sounds_stay_in_the_parent(tmp_path):
    from pinball_decryptor.plugins.stern.spike2 import parallel
    pool = object.__new__(parallel.BlockPool)
    pool.broken, pool._ready, pool.conns, pool.procs = None, True, [], []
    assert pool.blocks({"chan": 1}, [(1, 400, [0], None)]) is None


def test_the_block_worker_count(monkeypatch):
    from pinball_decryptor.plugins.stern.spike2 import parallel
    monkeypatch.delenv("PAD_STERN_BLOCK_WORKERS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert parallel.block_workers() == 8
    monkeypatch.setattr(os, "cpu_count", lambda: 3)
    assert parallel.block_workers() == 0           # one worker would not pay
    monkeypatch.setattr(os, "cpu_count", lambda: 6)
    assert parallel.block_workers() == 4
    monkeypatch.setenv("PAD_STERN_BLOCK_WORKERS", "0")
    assert parallel.block_workers() == 0
    assert parallel.start_block_pool("image", "x", "y", []) is None


# -- the chain-encode cache -------------------------------------------------------

class _MM:
    def __init__(self, data):
        self.data = bytearray(data)

    def __getitem__(self, sl):
        return bytes(self.data[sl])


def _chain_cache(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine as E
    gr = tmp_path / "game_real"
    if not gr.exists():
        gr.write_bytes(b"\x7fELF firmware")
    monkeypatch.delenv("PAD_STERN_AUDIO_CACHE", raising=False)
    return E, E._chain_body_cache(str(tmp_path / "proj"), str(gr), b"stock-id",
                                  lambda *a, **k: None)


def _chain_row(**kw):
    row = {"idx": 7, "body_off": 64, "length": 40, "scale": 3, "chan": 1,
           "key0": 11}
    row.update(kw)
    return row


def test_a_chain_record_is_encoded_once_for_the_same_inputs(tmp_path,
                                                            monkeypatch):
    E, cache = _chain_cache(tmp_path, monkeypatch)
    wav = tmp_path / "song.wav"
    wav.write_bytes(b"RIFF-song-1")
    emu = type("Emu", (), {"mm": _MM(bytes(range(256)) * 4)})()
    made = []

    def encode():
        made.append(1)
        return 62, b"\x01\x02" * 41

    row = _chain_row()
    first = E._chain_encoded(cache, "image", emu, row, str(wav), encode)
    again = E._chain_encoded(cache, "image", emu, row, str(wav), encode)
    assert first == again == (62, b"\x01\x02" * 41) and len(made) == 1
    # a fresh build (a new cache object) replays it from the folder
    E2, cache2 = _chain_cache(tmp_path, monkeypatch)
    assert E2._chain_encoded(cache2, "image", emu, row, str(wav),
                             encode) == first
    assert len(made) == 1 and cache2.hits == 1


@pytest.mark.parametrize("change", ["row", "wav", "window", "where", "gain",
                                    "loop", "ref", "card"])
def test_anything_the_encode_depends_on_encodes_it_again(tmp_path, monkeypatch,
                                                         change):
    E, cache = _chain_cache(tmp_path, monkeypatch)
    wav = tmp_path / "song.wav"
    wav.write_bytes(b"RIFF-song-1")
    emu = type("Emu", (), {"mm": _MM(bytes(1024))})()
    made = []

    def encode():
        made.append(1)
        return 64, b"\x05" * 80

    kw = dict(gain_db=None, loop=True, ref={"idx": 3, "scale": 1})
    E._chain_encoded(cache, "image", emu, _chain_row(), str(wav), encode, **kw)
    row, where = _chain_row(), "image"
    if change == "row":
        row = _chain_row(key0=12)
    elif change == "wav":
        wav.write_bytes(b"RIFF-song-2")
    elif change == "window":
        emu.mm.data[70] = 9
    elif change == "where":
        where = "image-sc01.bin"
    elif change == "gain":
        kw["gain_db"] = -3.0
    elif change == "loop":
        kw["loop"] = False
    elif change == "ref":
        kw["ref"] = {"idx": 4, "scale": 1}
    elif change == "card":
        (tmp_path / "game_real").write_bytes(b"\x7fELF other firmware")
        E, cache = _chain_cache(tmp_path, monkeypatch)
    E._chain_encoded(cache, where, emu, row, str(wav), encode, **kw)
    assert len(made) == 2


def test_the_chain_cache_keeps_only_what_the_last_build_used(tmp_path,
                                                             monkeypatch):
    E, cache = _chain_cache(tmp_path, monkeypatch)
    emu = type("Emu", (), {"mm": _MM(bytes(1024))})()
    for n in range(3):
        wav = tmp_path / ("s%d.wav" % n)
        wav.write_bytes(b"song%d" % n)
        E._chain_encoded(cache, "image", emu, _chain_row(idx=n), str(wav),
                         lambda: (64, b"\x00" * 80))
    assert len(os.listdir(cache.dir)) == 3
    E, cache = _chain_cache(tmp_path, monkeypatch)
    E._chain_encoded(cache, "image", emu, _chain_row(idx=1),
                     str(tmp_path / "s1.wav"), lambda: (64, b"\x00" * 80))
    cache.prune()
    assert len(os.listdir(cache.dir)) == 1 and cache.hits == 1


def test_the_audio_cache_switch_turns_the_chain_cache_off(tmp_path,
                                                          monkeypatch):
    from pinball_decryptor.plugins.stern import engine as E
    monkeypatch.setenv("PAD_STERN_AUDIO_CACHE", "0")
    assert E._chain_body_cache(str(tmp_path), str(tmp_path / "g"), b"x",
                               lambda *a, **k: None) is None
    assert E._chain_encoded(None, "image", None, {}, "w", lambda: (1, b"z")) \
        == (1, b"z")


def test_the_block_worker_count_is_no_part_of_an_audio_cache_key(tmp_path,
                                                                 monkeypatch):
    from pinball_decryptor.plugins.stern import engine as E
    gr = tmp_path / "game_real"
    gr.write_bytes(b"fw")
    monkeypatch.delenv("PAD_STERN_BLOCK_WORKERS", raising=False)
    a = E._audio_cache_base_key(str(gr), b"id")
    monkeypatch.setenv("PAD_STERN_BLOCK_WORKERS", "3")
    assert E._audio_cache_base_key(str(gr), b"id") == a
