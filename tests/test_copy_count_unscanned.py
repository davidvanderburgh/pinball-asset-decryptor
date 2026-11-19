"""The Colors bar's Copy count before the Images / Video tab has been opened (Simon, 2026-11-19: "0 ASSETS" on the
Scenes and Video bars until the Images tab had scanned the project). The tab now starts its scan when asked, the
count reads "..." until it lands, the page asks again then, and APPLY copies to nothing meanwhile."""
import os
import types

from pinball_decryptor.webui.tabs import color, images, video

TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js", "tabs")


class _Svc:
    """An Images / Video tab that has not read the project yet."""

    def __init__(self):
        self.pending = True
        self._targets_themes = "this"

    def targets_pending(self):
        return self.pending

    def color_targets(self, scope="profiled"):
        return {} if self.pending else {"a.png": True, "b.png": True, "c.png": False}


def _bar(svc, file_mode=None):
    bar = types.SimpleNamespace(toasts=[], sets={})
    bar._ALL_WORDS = color.ColorTab._ALL_WORDS
    bar._ALL_SCOPES = color.ColorTab._ALL_SCOPES
    bar._all_service = lambda kind: svc
    bar._file_mode = lambda: file_mode
    bar._targets_pending = types.MethodType(color.ColorTab._targets_pending, bar)
    bar._still_reading = types.MethodType(color.ColorTab._still_reading, bar)
    bar.toast = lambda text, kind="info": bar.toasts.append(text)
    bar._theme_words = lambda kind, rel, themes: ""
    bar._shown = lambda: types.SimpleNamespace(label=lambda: "Warm")
    bar._asset = types.SimpleNamespace(label=lambda: "Warm")
    bar._project = ""
    return bar


def test_count_waits_for_the_scan_then_counts():
    svc = _Svc()
    bar = _bar(svc, file_mode=("images", "a.png"))
    r = color.ColorTab.copy_preview(bar, "file", None, "all")
    assert r["n"] is None and "Reading" in r["text"]          # "..." - never a 0 that is not a count
    svc.pending = False
    r = color.ColorTab.copy_preview(bar, "file", None, "all")
    assert r["n"] == 2                                        # b.png and c.png


def test_shared_count_waits_too():
    svc = _Svc()
    bar = _bar(svc)
    assert color.ColorTab.copy_preview(bar, "shared", "videos", "all")["n"] is None
    svc.pending = False
    assert color.ColorTab.copy_preview(bar, "shared", "videos", "all")["n"] == 3


def test_apply_copies_nothing_while_reading():
    bar = _bar(_Svc(), file_mode=("images", "a.png"))
    assert color.ColorTab.apply_to_all(bar, "all") is False
    assert bar.toasts and "Still reading" in bar.toasts[0]
    bar = _bar(_Svc())
    bar.toasts = []
    assert color.ColorTab._apply_to_every(bar, "images") is False
    assert "Still reading" in bar.toasts[0]


def test_targets_ready_asks_the_page_again():
    bar = types.SimpleNamespace(_targets_rev=4, sets={})
    bar.set = lambda **kw: bar.sets.update(kw)
    color.ColorTab.targets_ready(bar)
    assert bar.sets == {"targets_rev": 5}
    pane = open(os.path.join(TABS, "color_pane.js"), encoding="utf-8").read()
    assert "s.targets_rev]);" in pane                         # a count dependency
    assert "(r && r.n === null) ? null" in pane               # null kept as "..."


def _tab(cls, project, scan_dir, scanning=False):
    tab = types.SimpleNamespace(started=0)
    tab.mfr = types.SimpleNamespace(capabilities=types.SimpleNamespace(replace_image=True, replace_video=True))
    tab._per_file_colour = lambda: True
    tab._tab_present = lambda: True
    tab._assets_dir = tab._assets_path = lambda: project
    tab._scan_dir = scan_dir
    tab._scan_t0 = 1.0 if scanning else None

    def start():
        tab.started += 1
        tab._scan_t0 = 1.0
    tab._scan_image_slots_async = tab._scan_async = start
    return tab


def test_the_tabs_start_one_scan_when_asked(tmp_path):
    for cls in (images.ImagesTab, video.VideoTab):
        tab = _tab(cls, str(tmp_path), "")
        assert cls.targets_pending(tab) is True and tab.started == 1
        assert cls.targets_pending(tab) is True and tab.started == 1   # already scanning: not again
        tab = _tab(cls, str(tmp_path), str(tmp_path))
        assert cls.targets_pending(tab) is False and tab.started == 0  # read already
        tab = _tab(cls, "", "")
        assert cls.targets_pending(tab) is False                     # no project


def test_the_tabs_tell_the_bar_when_the_scan_lands():
    for mod, fn in ((images, "_populate_image_after_scan"), (video, "_populate_after_scan")):
        src = open(mod.__file__, encoding="utf-8").read()
        body = src.split("def %s" % fn, 1)[1].split("\n    def ", 1)[0]
        assert "self._targets_read()" in body, mod.__name__
