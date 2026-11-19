"""The Colors bar's one Copy section (Simon, 2026-11-19: "it is vital we don't lose even a tiny piece of functionality"):
every way the old panel and the Which files card had of giving files a profile is still reachable from it."""
import os

TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js", "tabs")


def _src(name):
    with open(os.path.join(TABS, name), encoding="utf-8") as f:
        return f.read()


def test_every_old_way_is_still_there():
    pane = _src("color_pane.js")
    # Simon (2026-11-19): one copy, color.copy_profile(source, kind, which, themes). Every old copy is one of its
    # choices: a file's profile to the profiled / all other files (PAD-439, PAD-462) = "file" + "profiled" / "all";
    # the shared profile to every image / video / line of text (the Which files card, PAD-463 / PAD-471) = "shared" +
    # "all"; this theme / every theme = "this" / every theme ticked
    assert 'call("color.copy_profile", source, to, scope, themes)' in pane
    # (Simon, 2026-11-19: "ALL (P) WITH (P) WITHOUT (P)", the spectrum palette marking a profile)
    for which in ('opt("all", html`ALL <${SpectrumPal} />`', 'opt("profiled", html`WITH <${SpectrumPal} />`',
                  'opt("off", html`WITHOUT <${SpectrumPal} />`'):
        assert which in pane, which
    assert 'EVERY_KINDS().map((e) => e.k)' in pane
    assert 'label="All themes"' in pane
    # the old calls stay for anything else that uses them
    from pinball_decryptor.webui.tabs import color
    assert hasattr(color.ColorTab, "apply_to_all") and hasattr(color.ColorTab, "_apply_to_every")
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
    for word in ("SELECTED", "THEME", "TO WHAT?", "WHICH?", "THEMES"):
        assert 'tag("%s"' % word in pane, word
    assert 'tag(html`COPY <${SpectrumPal} /> FROM`)' in pane
    assert '<span class="cpd-title">Color profiles <${SpectrumPal} /></span>' in pane
    # WHICH?: three choices on twelve columns, 3 / 4 / 5 (Simon: "WITHOUT" was cut off - "make the ALL box smaller
    # and the WITHOUT box larger")
    for span, which in ((3, "all"), (4, "profiled"), (5, "off")):
        assert "span: %d, onClick: () => setWhich(\"%s\")" % (span, which) in pane, which


def test_the_preview_asks_the_same_targets_as_the_copy():
    from pinball_decryptor.webui.tabs import color
    src = open(color.__file__, encoding="utf-8").read()
    body = src.split("def copy_preview", 1)[1].split("\n    def ", 1)[0]
    assert "self._copy_plan(source, kind, scope, themes)" in body
    apply = src.split("def copy_profile", 1)[1].split("\n    def ", 1)[0]
    assert "self._copy_plan(source, kind, which, themes)" in apply
