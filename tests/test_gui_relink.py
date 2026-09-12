"""Project ▾ → "Relink moved files…" — the window that re-points a moved
project's replacement sources, driven end to end.

Real widgets: the whole value of this dialog is that a user clicks Search,
reads what was found, and clicks Relink, so the test walks the same three
steps and then reads the sidecar the app would build from.  Skipped rather
than failed where Tk cannot open a display.
"""

import json
import os
from types import SimpleNamespace

import pytest

tk = pytest.importorskip("tkinter")

from pinball_decryptor.core import staged_changes                # noqa: E402
from pinball_decryptor.gui import projects_ui                    # noqa: E402
from pinball_decryptor.gui.main_window import MainWindow         # noqa: E402


@pytest.fixture
def root():
    from tests.conftest import make_tk_root
    try:
        r = make_tk_root(tk)
    except tk.TclError:
        pytest.skip("no usable Tk display")
    r.geometry("400x200+10000+10000")      # off-screen, still laid out
    r.update()
    try:
        yield r
    finally:
        projects_ui._relink_win[0] = None
        try:
            r.destroy()
        except tk.TclError:
            pass


class _Var:
    def __init__(self, v=""):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


def _walk(w):
    for child in w.winfo_children():
        yield child
        for sub in _walk(child):
            yield sub


def _button(win, prefix):
    for w in _walk(win):
        try:
            if str(w.cget("text")).startswith(prefix):
                return w
        except tk.TclError:
            continue
    raise AssertionError("no button starting %r" % prefix)


def _entry(win):
    for w in _walk(win):
        if w.winfo_class() in ("TEntry", "Entry"):
            return w
    raise AssertionError("no entry in the window")


def _labels(win):
    out = []
    for w in _walk(win):
        if w.winfo_class() == "Label":
            try:
                out.append(str(w.cget("text")))
            except tk.TclError:
                pass
    return " || ".join(out)


@pytest.fixture
def moved(tmp_path, root, monkeypatch):
    """A project whose replacements all point at a PC that isn't this one,
    plus the same files sitting under a new folder."""
    proj = tmp_path / "GZ Heisei Custom"
    proj.mkdir()
    staged_changes.save(str(proj), {
        # One clip used by two slots, plus a video and an image.
        "audio": {"audio/idx0001.wav": r"G:\GZ media\audio\roar.wav",
                  "audio/idx0417.wav": r"G:\GZ media\audio\roar.wav"},
        "video": {"video/intro.mov": r"G:\GZ media\video\intro.mp4"},
        "image": {"images/logo.png": r"G:\GZ media\art\logo.png"},
        "audio_levels": {"audio/idx0001.wav": 4},
    })
    media = tmp_path / "moved media"
    for rel in ("audio/roar.wav", "video/intro.mp4"):
        p = media.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"media")

    # The search thread, run inline: work() ends with win.after(0, done), so
    # one root.update() still lands the result on the UI thread the same way.
    class _Inline:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()
    monkeypatch.setattr(projects_ui.threading, "Thread", _Inline)

    boxes = []
    monkeypatch.setattr(projects_ui.messagebox, "showinfo",
                        lambda *a, **k: boxes.append(a))
    monkeypatch.setattr(projects_ui.messagebox, "showwarning",
                        lambda *a, **k: boxes.append(a))

    logs, reloads = [], []
    app = SimpleNamespace(
        root=root,
        window=SimpleNamespace(
            _current_theme="light",
            append_log=lambda text, level="info": logs.append((text, level)),
            reload_assets_tabs=lambda: reloads.append(1)),
        _project_folder=lambda: str(proj),
    )
    return SimpleNamespace(app=app, proj=proj, media=media, logs=logs,
                           reloads=reloads, boxes=boxes, root=root)


def _sidecar(proj):
    with open(os.path.join(str(proj), staged_changes.SIDE_CAR),
              encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# The window itself
# ---------------------------------------------------------------------------

def test_opening_lists_every_unreachable_file_and_where_it_was(moved):
    projects_ui.open_relink(moved.app)
    win = projects_ui._relink_win[0]
    assert win is not None
    text = _labels(win)
    # 3 files (the shared clip counts once), out of 3 recorded.
    assert "3 of this project's 3 replacement file(s) are not on this PC" \
        in text
    assert r"Last seen in:  G:\GZ media" in text
    # The folder they were last seen in is pre-filled, ready to be replaced.
    assert _entry(win).get() == r"G:\GZ media"


def test_search_then_relink_repoints_every_slot(moved):
    projects_ui.open_relink(moved.app)
    win = projects_ui._relink_win[0]
    entry = _entry(win)
    entry.delete(0, tk.END)
    entry.insert(0, str(moved.media))

    _button(win, "Search").invoke()
    moved.root.update()                    # land the after(0) result

    relink_btn = _button(win, "Relink")
    assert relink_btn.cget("text") == "Relink 2 file(s)"
    assert str(relink_btn.cget("state")) == "normal"
    assert "Found 2 of 3 file(s)" in _labels(win)
    assert "covering 3 slot(s)" in _labels(win)
    # Nothing written yet — the preview is a preview.
    assert _sidecar(moved.proj)["video"]["video/intro.mov"] \
        == r"G:\GZ media\video\intro.mp4"

    relink_btn.invoke()
    data = _sidecar(moved.proj)
    assert data["audio"] == {
        "audio/idx0001.wav": os.path.join(str(moved.media), "audio",
                                          "roar.wav"),
        "audio/idx0417.wav": os.path.join(str(moved.media), "audio",
                                          "roar.wav")}
    assert data["video"]["video/intro.mov"] == os.path.join(
        str(moved.media), "video", "intro.mp4")
    # The image nobody could find is untouched, and per-slot state survives.
    assert data["image"]["images/logo.png"] == r"G:\GZ media\art\logo.png"
    assert data["audio_levels"] == {"audio/idx0001.wav": 4}
    # The Replace tabs were told to re-scan, and the log says what happened.
    assert moved.reloads == [1]
    assert any("Relinked 2 replacement file(s) across 3 slot(s)" in t
               for t, _lvl in moved.logs)
    # …and the project's own history recorded it.
    hist = open(os.path.join(str(moved.proj), ".history.log"),
                encoding="utf-8").read()
    assert "Relinked 2 replacement file(s)" in hist


def test_after_relinking_the_window_relists_what_is_still_missing(moved):
    projects_ui.open_relink(moved.app)
    win = projects_ui._relink_win[0]
    entry = _entry(win)
    entry.delete(0, tk.END)
    entry.insert(0, str(moved.media))
    _button(win, "Search").invoke()
    moved.root.update()
    _button(win, "Relink").invoke()

    text = _labels(win)
    assert "1 of this project's 3 replacement file(s) are not on this PC" \
        in text
    assert str(_button(win, "Relink").cget("state")) == "disabled"


def test_a_project_with_no_recorded_replacements_says_so(moved, tmp_path):
    empty = tmp_path / "fresh"
    empty.mkdir()
    moved.app._project_folder = lambda: str(empty)
    projects_ui.open_relink(moved.app)
    assert projects_ui._relink_win[0] is None
    assert moved.boxes and "no recorded replacements" in moved.boxes[0][1]


def test_search_without_a_folder_asks_for_one_and_writes_nothing(moved):
    projects_ui.open_relink(moved.app)
    win = projects_ui._relink_win[0]
    entry = _entry(win)
    entry.delete(0, tk.END)
    entry.insert(0, r"G:\not a folder on this pc")
    _button(win, "Search").invoke()
    assert moved.boxes and "Pick the folder" in moved.boxes[0][1]
    assert _sidecar(moved.proj)["video"]["video/intro.mov"] \
        == r"G:\GZ media\video\intro.mp4"


# ---------------------------------------------------------------------------
# The menu entry that reaches it
# ---------------------------------------------------------------------------

def test_project_menu_carries_relink_and_fires_the_callback(root, tmp_path):
    called = []
    win = MainWindow.__new__(MainWindow)
    win.root = root
    win._current_theme = "light"
    win._is_running = lambda: False
    win.write_assets_var = _Var(str(tmp_path))
    win._current_mfr = object()
    win._recent_projects_provider = lambda: []
    for name in ("_on_new_project", "_on_load_project", "_on_save_project",
                 "_on_save_project_as", "_on_project_properties",
                 "_on_open_project_manager", "_on_open_recent_project"):
        setattr(win, name, lambda: None)
    win._on_relink_project = lambda: called.append(1)

    menu = MainWindow._build_project_menu(win)
    labels = {}                       # label -> its real index (separators
    for i in range(menu.index("end") + 1):        # do not shift it)
        if menu.type(i) != "separator":
            labels[str(menu.entrycget(i, "label"))] = i
    assert "Relink moved files…" in labels
    menu.invoke(labels["Relink moved files…"])
    assert called == [1]
