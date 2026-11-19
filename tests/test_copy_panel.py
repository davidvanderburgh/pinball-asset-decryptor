"""The Colors bar's one Copy section (Simon, 2026-11-19: "it is vital we don't lose even a tiny piece of functionality"):
every way the old panel and the Which files card had of giving files a profile is still reachable from it."""
import os

TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js", "tabs")


def _src(name):
    with open(os.path.join(TABS, name), encoding="utf-8") as f:
        return f.read()


def test_every_old_way_is_still_there():
    pane = _src("color_pane.js")
    # a file's profile to the other files: profiled / all, this theme / every theme (PAD-439, PAD-462, themes)
    assert 'call("color.apply_to_all", which, null, themes)' in pane
    # the shared profile to every image / video / line of text (the Which files card, PAD-463 / PAD-471)
    assert 'call("color.apply_to_all", "all", to)' in pane
    assert 'EVERY_KINDS().map((e) => e.k)' in pane
    # dropping a file's own profile: here, in this theme, in every theme
    # (Simon: one button for the theme on show - "Same as the other files" in theme 1, "Same as theme 1" above it -
    # naming the profile it lands on; and Reset in every theme)
    assert "Same as the other files (“${sharedName}”)" in pane
    assert "Same as theme 1 (“${(f && f.base_name) || sharedName}”)" in pane
    assert "Reset in every theme (“${sharedName}”)<//>" in pane
    assert "Reset this file's profile" in pane
    assert 'call("color.file_shared", "all")' in pane
    # the card's notes: an old Every replaced box to turn off, and what the profile is on now
    assert "<${WhichFilesNotes} s=${s} />" in pane
    color = _src("color.js")
    assert 'call("color.set_all", k, false)' in color
    assert "<${WhichFilesNotes} s=${s} />" in color          # the Color profile tab keeps its card whole


def test_the_panel_says_what_copy_will_do_first():
    pane = _src("color_pane.js")
    assert 'call("color.copy_preview", source, to, scope, themes)' in pane
    # one grid (Simon: "as columnized as possible, box sizes the same"): the tags and every row's choices
    for word in ("SELECTED", "THEME", "COPY FROM", "TO KIND", "WHICH", "THEMES"):
        assert 'tag("%s"' % word in pane, word
    assert '"With profile attached"' in pane and "span: 4" in pane


def test_the_preview_asks_the_same_targets_as_the_copy():
    from pinball_decryptor.webui.tabs import color
    src = open(color.__file__, encoding="utf-8").read()
    body = src.split("def copy_preview", 1)[1].split("\n    def ", 1)[0]
    assert 'getattr(self._all_service(kind), "color_targets", None)' in body
    assert "svc._targets_themes = themes" in body
