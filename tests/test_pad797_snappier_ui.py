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
