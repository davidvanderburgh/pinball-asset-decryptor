"""The Colors bar's one Copy (color._copy_plan): its count before the Images / Video tab has been opened (Simon,
2026-11-19: "0 ASSETS" until the Images tab had scanned the project - the tab now starts its scan when asked, the count
reads "..." until it lands, and APPLY copies nothing meanwhile), and WHICH as Simon laid it out: All / Without a
profile / With a profile, and several files selected overriding WHICH."""
import os
import types

from pinball_decryptor.webui.tabs import color, images, video

TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js", "tabs")

#: a.png switched on, b.png off, c.png on, d.png off - none locked
STATES = {"a.png": True, "b.png": False, "c.png": True, "d.png": False}


class _Svc:
    """An Images / Video tab: *pending* until it has read the project."""

    def __init__(self, pending=False):
        self.pending = pending
        self._targets_themes = "this"

    def targets_pending(self):
        return self.pending

    def color_targets(self, scope="profiled"):
        if self.pending:
            return {}
        return dict(STATES) if scope == "all" else {r: on for r, on in STATES.items() if on}


def _bar(svc, tmp_path, file=None, more=()):
    bar = types.SimpleNamespace(toasts=[])
    for name in ("_copy_plan", "_theme_list", "_themes_said", "_theme_now", "_copy_words", "_targets_pending",
                 "_still_reading", "_file_rels"):
        setattr(bar, name, types.MethodType(getattr(color.ColorTab, name), bar))
    for name in ("_ALL_WORDS", "_ALL_SCOPES", "_WHICH", "_WHICH_WORDS"):
        setattr(bar, name, getattr(color.ColorTab, name))
    bar._raw = color.ColorTab._raw
    bar._project = str(tmp_path)
    bar._asset = None
    bar._file = {"kind": "images", "rel": file, "more": list(more)} if file else None
    bar._file_mode = lambda: ("images", file) if file else None
    bar._all_service = lambda kind: svc
    bar._shown = lambda: types.SimpleNamespace(label=lambda: "Warm")
    bar.window = types.SimpleNamespace(service=lambda ns: None)
    bar.toast = lambda text, kind="info": bar.toasts.append(text)
    return bar


def _targets(bar, source, which, kind="images"):
    return color.ColorTab._copy_plan(bar, source, kind, which, "this")


def test_count_waits_for_the_scan_then_counts(tmp_path):
    svc = _Svc(pending=True)
    bar = _bar(svc, tmp_path, file="a.png")
    r = color.ColorTab.copy_preview(bar, "file", None, "all")
    assert r["n"] is None and "Reading" in r["text"]          # "..." - never a 0 that is not a count
    svc.pending = False
    assert color.ColorTab.copy_preview(bar, "file", None, "all")["n"] == 3      # b, c, d (not a itself)


def test_shared_count_waits_too(tmp_path):
    svc = _Svc(pending=True)
    bar = _bar(svc, tmp_path)
    assert color.ColorTab.copy_preview(bar, "shared", "videos", "all")["n"] is None
    svc.pending = False
    assert color.ColorTab.copy_preview(bar, "shared", "videos", "all")["n"] == 4


def test_apply_copies_nothing_while_reading(tmp_path):
    bar = _bar(_Svc(pending=True), tmp_path, file="a.png")
    assert color.ColorTab.copy_profile(bar, "file", None, "all") is False
    assert bar.toasts and "Still reading" in bar.toasts[0]


def test_which_all_without_and_with_a_profile(tmp_path):
    """Simon: "Put the recommended setting on ALL unlocked files / only on files that don't have a profile AND are
    unlocked / only on files that DO have a profile already AND are unlocked"."""
    bar = _bar(_Svc(), tmp_path)
    plan = _targets(bar, "shared", "all")
    assert set(plan["targets"]) == set(STATES) and plan["attach"] == ["b.png", "d.png"]
    plan = _targets(bar, "shared", "off")
    assert set(plan["targets"]) == {"b.png", "d.png"} and plan["attach"] == ["b.png", "d.png"]
    plan = _targets(bar, "shared", "profiled")
    assert set(plan["targets"]) == {"a.png", "c.png"} and plan["attach"] == []     # nothing new switched on
    # the shared profile is no profile of its own: each falls back to it
    assert set(plan["value"].values()) == {None}


def test_a_files_profile_goes_to_the_others(tmp_path):
    bar = _bar(_Svc(), tmp_path, file="a.png")
    assert set(_targets(bar, "file", "off")["targets"]) == {"b.png", "d.png"}
    assert set(_targets(bar, "file", "profiled")["targets"]) == {"c.png"}    # not a itself


def test_several_selected_override_which(tmp_path):
    """Simon: the files selected "must override WHICH"."""
    bar = _bar(_Svc(), tmp_path, file="a.png", more=["b.png", "zz-locked.png"])
    plan = _targets(bar, "shared", "selected")
    assert set(plan["targets"]) == {"a.png", "b.png"}                       # a locked one is never reached
    plan = _targets(bar, "file", "selected")
    assert set(plan["targets"]) == {"b.png"} and plan["attach"] == ["b.png"]
    assert "Nothing is selected" in _targets(_bar(_Svc(), tmp_path), "shared", "selected")["error"]


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
