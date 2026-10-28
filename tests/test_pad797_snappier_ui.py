"""PAD-797: a snappier UI loop.

Every @rpc runs on the one UI loop thread (webui/loop.py), so anything slow
there stalls every click.  These pin the pieces that were slow for no
reason: the event bus walked its whole buffer under the lock on every SSE
wake, an in-place progress line scanned the 5,000-line log deque for its
entry, the footer deep-copied a flat dict on every progress message, and
worker messages waited on a 100 ms poll.
"""

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
