"""Files dropped from the desktop on a Replace tab's row (PAD-838): the
window's drop handler hands their full paths to the context's drop box, and
the tab the page called takes them out by name."""

import os
import threading
import time

from pinball_decryptor.webui.drops import DropBox


def _p(drive, *parts):
    """A full path as this OS's window hands it in: a Mac or Linux runner has
    no C:, and its basename of a Windows path is the whole path."""
    if os.name == "nt":
        return os.path.join(drive + os.sep, *parts)
    return os.path.join(os.sep + drive.rstrip(":").lower(), *parts)


def test_take_finds_the_paths_by_name():
    box = DropBox()
    box.put([_p("C:", "pics", "a.png"), _p("C:", "pics", "b.png")])
    assert box.take(["b.png"], wait=0) == [_p("C:", "pics", "b.png")]
    # each path is handed out once
    assert box.take(["b.png"], wait=0) == []
    assert box.take(["a.png"], wait=0) == [_p("C:", "pics", "a.png")]


def test_take_waits_for_the_window_to_hand_them_in():
    """The page's call can reach the app before the window's handler."""
    box = DropBox()
    threading.Timer(0.2, box.put, [[_p("D:", "x", "late.png")]]).start()
    t0 = time.monotonic()
    assert box.take(["late.png"], wait=5) == [_p("D:", "x", "late.png")]
    assert time.monotonic() - t0 < 4


def test_take_gives_up_when_no_path_comes():
    """A browser never hands a path in: nothing, after the wait."""
    box = DropBox()
    assert box.take(["a.png"], wait=0.1) == []
    assert box.take([], wait=5) == []


def test_take_wants_every_name():
    box = DropBox()
    box.put([_p("C:", "p", "a.png")])
    assert box.take(["a.png", "b.png"], wait=0) == []
    # a part-claim takes nothing
    assert box.take(["a.png"], wait=0) == [_p("C:", "p", "a.png")]


def test_the_newest_drop_of_a_name_wins():
    box = DropBox()
    box.put([_p("C:", "old", "a.png")])
    box.put([_p("C:", "new", "a.png")])
    assert box.take(["a.png"], wait=0) == [_p("C:", "new", "a.png")]


def test_put_event_reads_pywebviews_drop_event():
    box = DropBox()
    box.put_event({"type": "drop", "dataTransfer": {"files": [
        {"name": "a.png", "pywebviewFullPath": _p("C:", "p", "a.png")},
        {"name": "nopath.png"}]}})
    box.put_event({"type": "drop"})            # no dataTransfer: ignored
    box.put_event(None)
    assert box.take(["a.png"], wait=0) == [_p("C:", "p", "a.png")]
    assert box.take(["nopath.png"], wait=0) == []


# ------------------------------------------------- the picker a drop answers
def _dialogs():
    from pinball_decryptor.webui.dialogs import Dialogs

    class _Loop:
        def pump_until(self, event):
            pass

        def notify(self):
            pass

    class _Store:
        def set(self, *a, **k):
            pass

        def get(self, *a, **k):
            return None

    d = Dialogs(_Loop(), _Store())
    d.said = []
    d.message = lambda icon, title, message, buttons, **k: d.said.append(
        message)
    d.ask = lambda spec: (_ for _ in ()).throw(AssertionError(
        "a picker was shown: %r" % spec))
    return d


IMAGES = [("Image files", "*.png *.jpg"), ("All files", "*.*")]


def test_an_armed_drop_answers_the_next_picker(tmp_path, monkeypatch):
    from pinball_decryptor.webui import compat
    d = _dialogs()
    monkeypatch.setattr(compat.messagebox, "showinfo",
                        lambda title, message, **k: d.said.append(message))
    pic = tmp_path / "a.png"
    pic.write_bytes(b"x")
    other = tmp_path / "b.png"
    other.write_bytes(b"x")
    d.arm_drop([str(pic)])
    assert d.file("open", filetypes=IMAGES) == os.path.normpath(str(pic))
    # used once: the next picker shows (here: would raise)
    d.arm_drop([str(pic), str(other)])
    assert d.file("open", filetypes=IMAGES, multiple=True) == (
        os.path.normpath(str(pic)), os.path.normpath(str(other)))
    # several on a one-file picker
    d.arm_drop([str(pic), str(other)])
    assert d.file("open", filetypes=IMAGES) == ""
    assert d.said[-1] == "This takes one file: drop just one here."
    # a folder picker wants one folder, a file picker a file
    d.arm_drop([str(tmp_path)])
    assert d.file("folder") == os.path.normpath(str(tmp_path))
    d.arm_drop([str(pic)])
    assert d.file("folder") == ""
    assert d.said[-1] == "This asks for a folder: drop one folder here."
    d.arm_drop([str(tmp_path)])
    assert d.file("open", filetypes=IMAGES) == ""
    assert "not a folder" in d.said[-1]


def test_a_drop_takes_what_the_picker_would(tmp_path, monkeypatch):
    """The picker's own file types decide: with "All files" offered, any
    file (a card image named oddly); without, only those types."""
    from pinball_decryptor.webui import compat
    d = _dialogs()
    monkeypatch.setattr(compat.messagebox, "showinfo",
                        lambda title, message, **k: d.said.append(message))
    odd = tmp_path / "v2026.09.15.11.beetlejuice"
    odd.write_bytes(b"x")
    d.arm_drop([str(odd)])
    assert d.file("open", filetypes=IMAGES) == os.path.normpath(str(odd))
    d.arm_drop([str(odd)])
    assert d.file("open", filetypes=[("Profiles", "*.txt *.json")]) == ""
    assert d.said[-1] == ("v2026.09.15.11.beetlejuice is not a file this "
                          "takes (*.txt *.json), so it was not used.")
    card = tmp_path / "GODZILLA.SDCARD.RAW"
    card.write_bytes(b"x")
    d.arm_drop([str(card)])
    assert d.file("open", filetypes=[("Card", "*.raw")]) == \
        os.path.normpath(str(card))


def test_a_save_picker_and_a_stale_drop_show_the_picker(tmp_path,
                                                         monkeypatch):
    from pinball_decryptor.webui import dialogs as D
    d = _dialogs()
    shown = []
    d.ask = lambda spec: shown.append(spec["mode"]) or ""
    pic = tmp_path / "a.png"
    pic.write_bytes(b"x")
    d.arm_drop([str(pic)])
    assert d.file("save") == ""
    assert shown == ["save"]
    # the drop went with it
    assert d.file("open") == "" and shown == ["save", "open"]
    t = [1000.0]
    monkeypatch.setattr(D.time, "monotonic", lambda: t[0])
    d.arm_drop([str(pic)])
    t[0] += D.DROP_WAIT_S + 1
    assert d.file("open") == "" and shown[-1] == "open"


def test_ui_drop_arm_says_when_the_window_gave_no_path(tmp_path):
    from tests.webui_harness import web_app
    with web_app(tmp_path) as w:
        assert w.call("ui.drop_arm", ["nowhere.png"]) is False
        assert "could not tell where" in w.asked[-1]["message"]


def test_a_card_dropped_on_select_cards_browse(tmp_path):
    """PAD-838: a card image dropped on the Select card / Extract path or
    its Browse… is the card, as Browse… picking it would make it."""
    from tests.webui_harness import web_app
    card = tmp_path / "cards" / "game.pkg"
    card.parent.mkdir()
    card.write_bytes(b"x")
    with web_app(tmp_path, mfr="spooky") as w:
        n = len(w.asked)
        w.ctx.drops.put([str(card)])
        assert w.call("ui.drop_arm", ["game.pkg"]) is True
        assert w.call("extract.browse_input") is True
        assert len(w.asked) == n
        assert w.window.extract_input_var.get() == os.path.normpath(str(card))
