"""Files dropped from the desktop on a Replace tab's row (PAD-838): the
window's drop handler hands their full paths to the context's drop box, and
the tab the page called takes them out by name."""

import os
import threading
import time

from pinball_decryptor.webui.drops import DropBox


def test_take_finds_the_paths_by_name():
    box = DropBox()
    box.put([r"C:\pics\a.png", r"C:\pics\b.png"])
    assert box.take(["b.png"], wait=0) == [os.path.normpath(r"C:\pics\b.png")]
    # each path is handed out once
    assert box.take(["b.png"], wait=0) == []
    assert box.take(["a.png"], wait=0) == [os.path.normpath(r"C:\pics\a.png")]


def test_take_waits_for_the_window_to_hand_them_in():
    """The page's call can reach the app before the window's handler."""
    box = DropBox()
    threading.Timer(0.2, box.put, [[r"D:\x\late.png"]]).start()
    t0 = time.monotonic()
    assert box.take(["late.png"], wait=5) == [os.path.normpath(r"D:\x\late.png")]
    assert time.monotonic() - t0 < 4


def test_take_gives_up_when_no_path_comes():
    """A browser never hands a path in: nothing, after the wait."""
    box = DropBox()
    assert box.take(["a.png"], wait=0.1) == []
    assert box.take([], wait=5) == []


def test_take_wants_every_name():
    box = DropBox()
    box.put([r"C:\p\a.png"])
    assert box.take(["a.png", "b.png"], wait=0) == []
    # a part-claim takes nothing
    assert box.take(["a.png"], wait=0) == [os.path.normpath(r"C:\p\a.png")]


def test_the_newest_drop_of_a_name_wins():
    box = DropBox()
    box.put([r"C:\old\a.png"])
    box.put([r"C:\new\a.png"])
    assert box.take(["a.png"], wait=0) == [os.path.normpath(r"C:\new\a.png")]


def test_put_event_reads_pywebviews_drop_event():
    box = DropBox()
    box.put_event({"type": "drop", "dataTransfer": {"files": [
        {"name": "a.png", "pywebviewFullPath": r"C:\p\a.png"},
        {"name": "nopath.png"}]}})
    box.put_event({"type": "drop"})            # no dataTransfer: ignored
    box.put_event(None)
    assert box.take(["a.png"], wait=0) == [os.path.normpath(r"C:\p\a.png")]
    assert box.take(["nopath.png"], wait=0) == []
