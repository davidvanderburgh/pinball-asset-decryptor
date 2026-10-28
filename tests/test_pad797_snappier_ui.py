"""PAD-797: a snappier UI loop.

Every @rpc runs on the one UI loop thread (webui/loop.py), so anything slow
there stalls every click.  These pin the pieces that were slow for no
reason: the event bus walked its whole buffer under the lock on every SSE
wake, an in-place progress line scanned the 5,000-line log deque for its
entry, the footer deep-copied a flat dict on every progress message, and
worker messages waited on a 100 ms poll.
"""

import queue
import threading
import time
import types

import pytest

from tests.webui_harness import web_app


# ------------------------------------------------------------ event bus
def _old_since(bus, seq):
    """The list comprehension ``EventBus.since`` used before PAD-797."""
    with bus._lock:
        if not bus._events:
            return [], False
        first = bus._events[0][0]
        gap = seq + 1 < first and seq < bus._last
        return [(s, t) for s, t in bus._events if s > seq], gap


@pytest.mark.parametrize("keep,published", [(50, 10), (8, 20), (8, 8)])
def test_since_answers_exactly_as_the_full_walk_did(keep, published):
    from pinball_decryptor.webui.state import EventBus
    bus = EventBus(keep=keep)
    for i in range(published):
        bus.publish("e", n=i)
    first = bus._events[0][0]
    # before the window, at its edges, inside it, at and after the end
    for seq in (0, first - 2, first - 1, first, first + 1,
                bus.last_seq // 2, bus.last_seq - 1, bus.last_seq,
                bus.last_seq + 5):
        assert bus.since(seq) == _old_since(bus, seq), (keep, published, seq)


def test_since_on_an_evicted_window_flags_the_gap():
    from pinball_decryptor.webui.state import EventBus
    bus = EventBus(keep=5)
    for i in range(12):
        bus.publish("e", n=i)
    # events 8..12 are kept; a page that saw 3 missed 4..7
    events, gap = bus.since(3)
    assert gap is True and [s for s, _ in events] == [8, 9, 10, 11, 12]
    # a page that saw 7 missed nothing
    events, gap = bus.since(7)
    assert gap is False and [s for s, _ in events] == [8, 9, 10, 11, 12]
    assert bus.since(12) == ([], False)
    assert bus.since(40) == ([], False)
    assert EventBus().since(0) == ([], False)


# ---------------------------------------------------------------- store
def test_a_flat_value_comes_back_as_a_copy_and_a_nested_one_deep():
    from pinball_decryptor.webui.state import EventBus, Store
    store = Store(EventBus())
    store.set("shell", footer={"pct": 1, "status": "x", "started": None},
              rows=[{"k": [1, 2]}], names=["a", "b"], n=3)
    footer = store.get("shell", "footer")
    footer["pct"] = 99
    assert store.get("shell", "footer")["pct"] == 1
    names = store.get("shell", "names")
    names.append("c")
    assert store.get("shell", "names") == ["a", "b"]
    rows = store.get("shell", "rows")
    rows[0]["k"].append(3)
    assert store.get("shell", "rows") == [{"k": [1, 2]}]
    assert store.get("shell", "n") == 3
    assert store.get("shell", "missing", "d") == "d"


# ------------------------------------------------------------ log index
def test_an_in_place_line_is_found_after_many_appends(tmp_path):
    from pinball_decryptor.webui import window as window_mod
    keep = window_mod.LOG_KEEP
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window

        def _work():
            win.update_log_line("prog", "Converting 1 of 9")
            lid = win._keyed[(win._log_line_run, "prog")]
            for i in range(200):
                win.append_log("line %d" % i)
            win.update_log_line("prog", "Converting 5 of 9", "warn")
            entry = win._log_index["stern"][lid]
            assert entry["text"] == "Converting 5 of 9"
            assert entry["level"] == "warn"
            assert [e for e in win._log["stern"] if e["id"] == lid] == [entry]
            # the index names exactly the deque's lines
            assert (sorted(win._log_index["stern"])
                    == sorted(e["id"] for e in win._log["stern"]))
            # evict it: the deque drops the oldest, the index follows
            for i in range(keep):
                win.append_log("flood %d" % i)
            assert len(win._log["stern"]) == keep
            assert lid not in win._log_index["stern"]
            assert (sorted(win._log_index["stern"])
                    == sorted(e["id"] for e in win._log["stern"]))
            # an update of an evicted line does not raise or revive it
            win.update_log_line("prog", "Converting 9 of 9")
            assert lid not in win._log_index["stern"]
            win._clear_log("stern")
            assert "stern" not in win._log_index and "stern" not in win._log
        w.run(_work)


# --------------------------------------------------------- worker queue
def _fake_app(after, turn_s=0.05):
    from pinball_decryptor.app import App, UiQueue
    stub = types.SimpleNamespace(
        POLL_TURN_S=turn_s, _active_mode=None, _current_mfr=None,
        window=types.SimpleNamespace(append_log=lambda t, l: None),
        root=types.SimpleNamespace(after=lambda ms, fn: after.append((ms, fn))))
    stub._poll_queue = lambda: App._poll_queue(stub)
    stub.msg_queue = UiQueue(lambda: stub.root.after(0, stub._poll_queue))
    return stub


def test_a_put_from_a_worker_wakes_the_loop_without_a_timer():
    from pinball_decryptor.app import LogMsg
    after = []
    stub = _fake_app(after)
    seen = []
    stub.window.append_log = lambda t, l: seen.append(t)
    assert after == []                       # idle: nothing pending
    t = threading.Thread(target=lambda: stub.msg_queue.put(LogMsg("hi", "info")))
    t.start()
    t.join()
    assert [ms for ms, _ in after] == [0]    # one drain, straight away
    # a second put before the drain runs does not schedule another
    stub.msg_queue.put(LogMsg("there", "info"))
    assert [ms for ms, _ in after] == [0]
    ms, fn = after.pop()
    fn()
    assert seen == ["hi", "there"]
    assert after == []                       # idle again: no 100 ms poll
    # and the next put schedules again
    stub.msg_queue.put(LogMsg("again", "info"))
    assert [ms for ms, _ in after] == [0]


def test_a_put_during_a_drain_is_not_lost():
    from pinball_decryptor.app import LogMsg
    after = []
    stub = _fake_app(after)
    seen = []

    def append(text, level):
        seen.append(text)
        if text == "first":
            stub.msg_queue.put(LogMsg("during", "info"))
    stub.window.append_log = append
    stub.msg_queue.put(LogMsg("first", "info"))
    ms, fn = after.pop()
    fn()
    # the running drain took it; the put, landing after the flag was
    # cleared, scheduled one more turn, which finds nothing (and no more)
    assert seen == ["first", "during"]
    assert [ms for ms, _ in after] == [0]
    after.pop()[1]()
    assert seen == ["first", "during"] and after == []


def test_a_turn_out_of_time_comes_straight_back_once():
    from pinball_decryptor.app import LogMsg
    after = []
    stub = _fake_app(after, turn_s=0.001)
    stub.window.append_log = lambda t, l: time.sleep(0.003)   # one a turn
    for i in range(3):
        stub.msg_queue.put(LogMsg("l%d" % i, "info"))
    assert len(after) == 1
    ms, fn = after.pop()
    fn()
    assert [ms for ms, _ in after] == [0]    # the follow-up turn, once
    for _ in range(10):
        if not after:
            break
        assert [ms for ms, _ in after] == [0]
        after.pop()[1]()
    assert stub.msg_queue.empty() and after == []


def test_the_app_queue_is_the_waking_kind(tmp_path):
    from pinball_decryptor.app import UiQueue
    with web_app(tmp_path, mfr="stern") as w:
        assert isinstance(w.app.msg_queue, UiQueue)
        assert isinstance(w.app.msg_queue, queue.Queue)


def test_a_waking_queue_still_drains_by_hand():
    from pinball_decryptor.app import UiQueue
    q = UiQueue(lambda: None)
    q.put(1)
    q.put_nowait(2)
    assert q.get_nowait() == 1 and q.get() == 2 and q.empty()


# ------------------------------------------------------- startup imports
def test_a_lazy_module_imports_on_first_use():
    import sys
    from pinball_decryptor.core.lazy_import import lazy_module
    name = "pad797_lazy_probe_mod"
    sys.modules.pop(name, None)
    import types as _types
    mod = _types.ModuleType(name)
    mod.answer = 42
    lazy = lazy_module(name)
    assert "not loaded" in repr(lazy)
    sys.modules[name] = mod
    try:
        assert lazy.answer == 42
        assert "loaded" in repr(lazy) and "not loaded" not in repr(lazy)
        with pytest.raises(AttributeError):
            lazy.missing
    finally:
        sys.modules.pop(name, None)
    with pytest.raises(ImportError):
        lazy_module("pad797_no_such_module_anywhere").anything


def test_the_tabs_load_without_numpy_or_pillow():
    """numpy and PIL cost the UI loop 65 to 130 ms at startup through the
    Modes tab's module chain (block_modes, more_kaiju, battle_select, dds,
    scene_write, film_cut) and the Multi-boot tab; they load on first use."""
    import os
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import sys\n"
            "import pinball_decryptor.webui.tabs.modes\n"
            "from pinball_decryptor.webui.tabs import load_tab_classes\n"
            "load_tab_classes()\n"
            "print(sorted(m for m in sys.modules "
            "if m == 'numpy' or m == 'PIL' or m.startswith('PIL.')))\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=root,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip() == "[]", r.stdout


# ---------------------------------------------------------- content types
def test_the_server_names_its_content_types_without_the_registry():
    """mimetypes.init() reads the Windows registry (50 ms) on the first
    guess_type or add_type; the server's own table answers instead."""
    from pinball_decryptor.webui import server
    for ext, want in (("js", "text/javascript"), ("css", "text/css"),
                      ("html", "text/html"), ("woff2", "font/woff2"),
                      ("svg", "image/svg+xml"), ("png", "image/png"),
                      ("jpg", "image/jpeg"), ("jpeg", "image/jpeg"),
                      ("gif", "image/gif"), ("webp", "image/webp"),
                      ("ico", "image/x-icon"), ("json", "application/json"),
                      ("wav", "audio/wav"), ("ogg", "audio/ogg"),
                      ("flac", "audio/flac"), ("mp3", "audio/mpeg"),
                      ("mp4", "video/mp4"), ("webm", "video/webm"),
                      ("mov", "video/quicktime"), ("txt", "text/plain"),
                      ("md", "text/markdown"), ("map", "application/json")):
        assert server.content_type("C:/x/some.file." + ext) == want, ext
        assert server.content_type("some." + ext.upper()) == want, ext
    assert server.content_type("x.bin") == "application/octet-stream"
    assert server.content_type("noext") == "application/octet-stream"
    assert not hasattr(server, "mimetypes")
    import inspect
    assert "mimetypes." not in inspect.getsource(server)


def test_importing_the_host_leaves_mimetypes_uninitialised():
    import os
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import mimetypes\n"
            "import pinball_decryptor.webui.host\n"
            "import pinball_decryptor.app\n"
            "print(mimetypes.inited)\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=root,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip() == "False", r.stdout


# ------------------------------------------------------- python probes
def _fake_dist(tmp_path, name, version, body="__version__ = '0.0'\n"):
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text(body)
    info = tmp_path / ("%s-%s.dist-info" % (name, version))
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: %s\nVersion: %s\n"
                                   % (name.replace("_", "-"), version))
    return pkg


def test_a_python_probe_answers_without_importing_the_module(tmp_path, monkeypatch):
    """faster_whisper took 150 ms warm (a second or more cold) to import
    just to see whether it exists; find_spec and the dist metadata answer."""
    import sys
    from pinball_decryptor.core import prereqs
    name = "pad797_probe_pkg"
    _fake_dist(tmp_path, name, "3.1.4",
               body="raise RuntimeError('imported after all')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(name, None)
    assert prereqs._probe_python_import(name) == (True, name + " 3.1.4")
    assert name not in sys.modules
    ok, msg = prereqs._probe_python_import("pad797_missing_pkg")
    assert ok is False and "pad797_missing_pkg" in msg
    # a dotted name, a module without a distribution, a module imported
    assert prereqs._probe_python_import("json.decoder") == (True, "json.decoder available")
    assert prereqs._probe_python_import("pytest") == (True, "pytest " + pytest.__version__)
    # the Prerequisite path still reads it
    p = prereqs.Prerequisite(name="x", where="host", probe="python:" + name,
                             reason="r", install_hint="pip install x")
    r = prereqs.check_prerequisite(p)
    assert r.ok and r.message == name + " 3.1.4"
    assert name not in sys.modules


def test_a_native_extension_probe_still_really_imports(tmp_path, monkeypatch):
    """unicorn and capstone load a library at import: installed is not yet
    loads, so those two keep the real import (prereqs.IMPORT_PROBES)."""
    import sys
    from pinball_decryptor.core import prereqs
    assert {"unicorn", "capstone"} <= set(prereqs.IMPORT_PROBES)
    name = "pad797_broken_ext"
    _fake_dist(tmp_path, name, "9.9",
               body="raise ImportError('DLL load failed')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(name, None)
    assert prereqs._probe_python_import(name)[0] is True
    ok, msg = prereqs._probe_python_import(name, really_import=True)
    assert ok is False and "DLL load failed" in msg
    monkeypatch.setattr(prereqs, "IMPORT_PROBES", frozenset({name}))
    assert prereqs._probe_python_import(name)[0] is False
    good = "pad797_good_ext"
    _fake_dist(tmp_path, good, "1.0", body="__version__ = '1.0.1'\n")
    sys.modules.pop(good, None)
    assert prereqs._probe_python_import(good, really_import=True) == (True, good + " 1.0.1")
    sys.modules.pop(good, None)


# ------------------------------------------------------- probe cache
def _clip(tmp_path, rel, body=b"not really mp4 but enough"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return p


def _info(path, **kw):
    from pinball_decryptor.core.video import VideoInfo
    base = dict(vcodec="h264", width=1920, height=1080, fps=30.0,
                duration=4.5, has_audio=True, audio_rate=48000,
                audio_channels=2, profile="High", level=41, keyint=60,
                pix_fmt="yuv420p", container="mp4")
    base.update(kw)
    return VideoInfo(str(path), **base)


def test_video_info_round_trips_through_a_dict(tmp_path):
    from pinball_decryptor.core.video import VideoInfo
    info = _info(tmp_path / "a.mp4", has_alpha=True, nframes=135)
    d = info.to_dict()
    assert "path" not in d and d["keyint"] == 60 and d["has_alpha"] is True
    back = VideoInfo.from_dict(dict(d, stranger="ignored"), "elsewhere.mp4")
    assert back.path == "elsewhere.mp4" and back.to_dict() == d
    assert VideoInfo.from_dict({}, "x").to_dict() == VideoInfo("x").to_dict()


def test_the_probe_cache_answers_a_hit_and_probes_a_miss(tmp_path, monkeypatch):
    from pinball_decryptor.core import video
    monkeypatch.setattr(video, "prober_tag", lambda: "ffprobe-test")
    clip = _clip(tmp_path, "video/a.mp4")
    probes = []

    def fake_probe(path):
        probes.append(path)
        return _info(path)
    monkeypatch.setattr(video, "detect_video_info", fake_probe)
    cache = video.load_probe_cache(str(tmp_path))
    assert cache == {}                                   # no sidecar yet
    info = video.cached_video_info(str(tmp_path), "video/a.mp4", cache)
    assert info.width == 1920 and probes == [str(clip)]
    assert video.save_probe_cache(str(tmp_path), cache) is True
    assert (tmp_path / video.PROBE_CACHE_FILE).exists()
    # a hit: no probe, the same answer, for the real path
    cache2 = video.load_probe_cache(str(tmp_path))
    assert cache2 == cache
    again = video.cached_video_info(str(tmp_path), "video/a.mp4", cache2)
    assert again.to_dict() == info.to_dict() and again.path == str(clip)
    assert probes == [str(clip)]
    # a None answer is not kept
    monkeypatch.setattr(video, "detect_video_info", lambda p: None)
    _clip(tmp_path, "video/b.mp4")
    assert video.cached_video_info(str(tmp_path), "video/b.mp4", cache2) is None
    assert "video/b.mp4" not in cache2


@pytest.mark.parametrize("how", ["size", "mtime", "prober", "gone"])
def test_the_probe_cache_forgets_a_moved_clip(tmp_path, monkeypatch, how):
    import os
    from pinball_decryptor.core import video
    monkeypatch.setattr(video, "prober_tag", lambda: "ffprobe-test")
    clip = _clip(tmp_path, "video/a.mp4")
    cache = {}
    video.probe_cache_store(cache, "video/a.mp4", str(clip), _info(clip))
    assert video.probe_cache_lookup(cache, "video/a.mp4", str(clip)) is not None
    if how == "size":
        clip.write_bytes(b"longer than before, so a different size")
    elif how == "mtime":
        st = os.stat(clip)
        os.utime(clip, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    elif how == "prober":
        monkeypatch.setattr(video, "prober_tag", lambda: "banner")
    else:
        clip.unlink()
    assert video.probe_cache_lookup(cache, "video/a.mp4", str(clip)) is None
    assert video.probe_cache_lookup(cache, "video/other.mp4", str(clip)) is None


def test_a_corrupt_probe_cache_is_ignored(tmp_path):
    import json
    from pinball_decryptor.core import video
    side = tmp_path / video.PROBE_CACHE_FILE
    side.write_text("{not json")
    assert video.load_probe_cache(str(tmp_path)) == {}
    side.write_text(json.dumps([1, 2]))
    assert video.load_probe_cache(str(tmp_path)) == {}
    side.write_text(json.dumps({"ok.mp4": [1, 2, "t", {"width": 3}],
                                "short.mp4": [1, 2, "t"],
                                "wrong.mp4": [1, 2, "t", "nope"],
                                "junk": 5}))
    assert video.load_probe_cache(str(tmp_path)) == {
        "ok.mp4": [1, 2, "t", {"width": 3}]}
    assert video.load_probe_cache(str(tmp_path / "missing")) == {}


def test_the_probe_cache_is_not_written_in_a_capture_run(tmp_path, monkeypatch):
    from pinball_decryptor.core import video
    monkeypatch.setenv("PAD_UI_CAPTURE", "1")
    assert video.save_probe_cache(str(tmp_path), {"a": [1, 2, "t", {}]}) is False
    assert not (tmp_path / video.PROBE_CACHE_FILE).exists()
    monkeypatch.delenv("PAD_UI_CAPTURE")
    assert video.save_probe_cache(str(tmp_path), {"a": [1, 2, "t", {}]}) is True
    assert (tmp_path / video.PROBE_CACHE_FILE).exists()


def test_the_probe_cache_sidecar_never_enters_a_baseline_or_a_write_scan(tmp_path):
    from pinball_decryptor.core import checksums, video
    from pinball_decryptor.webui.write_scan import walk_changes
    assert video.PROBE_CACHE_FILE in checksums.TRACKING_SIDECARS
    assert video.PROBE_CACHE_FILE in checksums.FINGERPRINT_SKIP_FILES
    _clip(tmp_path, "video/a.mp4")
    (tmp_path / video.PROBE_CACHE_FILE).write_text("{}")
    checksums.generate_checksums(str(tmp_path))
    listed = (tmp_path / checksums.CHECKSUMS_FILE).read_text()
    assert "video/a.mp4" in listed and video.PROBE_CACHE_FILE not in listed
    saved = {"video/a.mp4": "0" * 32, video.PROBE_CACHE_FILE: "0" * 32}
    changed = walk_changes(str(tmp_path), saved, hide_imported_cache=False,
                           current=lambda: True)
    assert [rel for rel, _ in changed] == ["video/a.mp4"]


def _probe_tab(tmp_path, slots, scan_id=7):
    """A stand-in for the Video tab around _probe_metadata_async."""
    import time as _time
    import types as _types
    from pinball_decryptor.webui.tabs.video import TAB
    timers, applied = [], []
    stub = _types.SimpleNamespace(
        _slots=slots, _scan_dir=str(tmp_path), _scan_id=scan_id,
        ctx=_types.SimpleNamespace(loop=_types.SimpleNamespace(
            after=lambda ms, fn: timers.append(fn))),
        _apply_meta=lambda sid, rel, info: applied.append((rel, info)))
    TAB._probe_metadata_async(stub, scan_id)
    deadline = _time.monotonic() + 10
    while timers and _time.monotonic() < deadline:
        fn = timers.pop(0)
        fn()
        if timers:
            _time.sleep(0.01)
    return applied


def test_the_video_tab_probes_only_the_misses_and_saves_once(tmp_path, monkeypatch):
    import json
    from pinball_decryptor.core import video
    from pinball_decryptor.core.video_slots import VideoSlot
    monkeypatch.setattr(video, "prober_tag", lambda: "ffprobe-test")
    a, b = _clip(tmp_path, "video/a.mp4"), _clip(tmp_path, "video/b.mp4")
    cache = {}
    video.probe_cache_store(cache, "video/a.mp4", str(a), _info(a, width=640))
    video.save_probe_cache(str(tmp_path), cache)
    probes, saves = [], []

    def fake_probe(path):
        probes.append(path)
        return _info(path, width=1280)
    monkeypatch.setattr(video, "detect_video_info", fake_probe)
    real_save = video.save_probe_cache
    monkeypatch.setattr(video, "save_probe_cache",
                        lambda folder, c: saves.append(folder) or real_save(folder, c))

    def slots():
        return [VideoSlot("video/a.mp4", str(a), ".mp4", None, a.stat().st_size),
                VideoSlot("video/b.mp4", str(b), ".mp4", None, b.stat().st_size)]
    applied = dict(_probe_tab(tmp_path, slots()))
    assert probes == [str(b)]                          # a was a hit
    assert applied["video/a.mp4"].width == 640
    assert applied["video/b.mp4"].width == 1280
    assert saves == [str(tmp_path)]
    on_disk = json.loads((tmp_path / video.PROBE_CACHE_FILE).read_text())
    assert set(on_disk) == {"video/a.mp4", "video/b.mp4"}
    # the next pass: all hits, no probe, no save
    applied = dict(_probe_tab(tmp_path, slots()))
    assert probes == [str(b)] and saves == [str(tmp_path)]
    assert applied["video/b.mp4"].width == 1280
    # a capture run: probes, but leaves the folder alone
    monkeypatch.setattr(video, "save_probe_cache", real_save)
    monkeypatch.setenv("PAD_UI_CAPTURE", "1")
    c = _clip(tmp_path, "video/c.mp4")
    _probe_tab(tmp_path, slots() + [
        VideoSlot("video/c.mp4", str(c), ".mp4", None, c.stat().st_size)])
    assert probes == [str(b), str(c)]
    assert "video/c.mp4" not in json.loads(
        (tmp_path / video.PROBE_CACHE_FILE).read_text())
