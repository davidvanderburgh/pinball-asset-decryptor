"""With no preview code, no tab of the app says a word about the dark preview feature.

Every Stern Spike 2 tab is shown in turn (its ``on_show`` runs, as when a person clicks it)
against a scratch project that HOLDS that feature's files, and every string the tab puts in
the store - what its page draws - is searched for the feature's words. The tab itself must
not be on the rail. The app's log (every line any tab wrote, shown on every tab) is searched
too. A control run with the switch ON must find the words on the feature's own tab, so a
sweep that stopped seeing the pages' text cannot pass by finding nothing.
"""

import json
import re

import pytest

from tests.webui_harness import web_app

#: the preview feature's words, as the browser sweep searched them
WORDS = re.compile(r"\b(modes?|mode maker|mode editor|try it|code modes?|film cutter|"
                   r"stock modes?)\b", re.I)

#: the game's OWN modes as any pinball player says it, on tabs that have nothing to do with
#: the preview feature (on main before it): these phrases are allowed
ALLOWED = ("topper-only modes", "how a mode looks")

#: store keys whose VALUES are data, not words a page shows (paths, ids, option values)
_DATA_KEYS = {"mode", "modes", "kind", "key", "ns", "id", "icon", "path", "value"}

#: a folder or file name, whole or inside a sentence (``C:\x\modes\a``, ``modes/kaiju_rush``):
#: the person's own, or where a file is, not the app's words. Only that token is skipped;
#: the rest of the sentence is searched.
_PATH_TOKEN = re.compile(r"""[^\s"'()]*[\\/][^\s"'()]*""")


def _strings(value, key=""):
    """Every string in a store value, with the key it sits under."""
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, str(k))
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v, key)


def _hits(ns, state):
    out = []
    for key, text in _strings(state):
        if key in _DATA_KEYS:
            continue
        text = _PATH_TOKEN.sub(" ", text)
        for m in WORDS.finditer(text):
            if any(a in text[max(0, m.start() - 20):m.end() + 20] for a in ALLOWED):
                continue
            out.append((ns, key, m.group(0), text[max(0, m.start() - 60):m.end() + 60]))
    return out


def test_a_path_is_skipped_but_the_sentence_around_it_is_not():
    assert not _hits("t", {"x": "C:\\Users\\x\\proj\\modes\\kaiju_rush\\mode.json"})
    assert not _hits("t", {"x": "Saved in /home/x/proj/modes/a."})
    assert _hits("t", {"x": "Two modes were saved in C:\\Users\\x\\proj."})
    assert _hits("t", {"x": "made modes/a from the template, then Try it builds it"})


def _scratch_project(tmp_path):
    """A card project with the feature's files in it: what a project made with the switch
    on and then opened without it looks like."""
    proj = tmp_path / "proj"
    folder = proj / "modes" / "kaiju_rush"
    folder.mkdir(parents=True)
    (proj / ".extract_source.json").write_text(json.dumps({
        "input_path": str(tmp_path / "godzilla_pro-1_15_0.raw"),
        "input_name": "godzilla_pro-1_15_0.raw"}), encoding="utf-8")
    from pinball_decryptor.plugins.stern import mode_project as MP
    MP.save(str(proj), "kaiju_rush", dict(MP.example_specs())["KAIJU RUSH"])
    return proj


def _sweep(tmp_path, with_project, switch_on):
    """Show every Stern Spike 2 tab in turn; every hit of the feature's words in what the
    tabs, the shell and the app's log hold."""
    with web_app(tmp_path, mfr="stern") as w:
        if w.state("shell").get("mfr", {}).get("era") not in (None, "spike2"):
            w.call("ui.set_era", "spike2")
            w.drain()
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert bool(tabs["modes"]["visible"]) is switch_on
        if with_project:
            proj = _scratch_project(tmp_path)
            modes = w.window.service("modes")
            var = modes._project_var() if modes is not None else None
            if var is None:
                pytest.skip("no project folder variable in this window")
            w.run(lambda: var.set(str(proj)))
            w.drain()
        found = []
        shown = [ns for ns, t in tabs.items() if t["visible"]]
        assert shown, "no tab is shown for Stern Spike 2"
        for ns in shown:
            w.call("ui.select_tab", ns)
            w.drain()
            found += _hits(ns, w.state(ns))
        found += _hits("shell", {k: v for k, v in w.state("shell").items() if k != "tabs"})
        found += _hits("shell.tabs", [t.get("label", "") for t in w.state("shell")["tabs"]
                                      if t["visible"]])
        lines = [e for q in list(w.window._log.values()) for e in q]
        lines += list(w.window._pending_log)
        found += _hits("log", [e.get("text", "") for e in lines])
        return found


@pytest.mark.parametrize("with_project", [False, True])
def test_no_tab_says_the_preview_features_words_without_a_code(tmp_path, with_project):
    found = _sweep(tmp_path, with_project, switch_on=False)
    assert not found, "\n".join("%s.%s: %r in %r" % h for h in found)


@pytest.mark.usefixtures("preview_modes_on")
def test_the_sweep_finds_the_words_with_the_switch_on(tmp_path):
    """The control: with the switch on, the same sweep finds the feature's words on its own
    tab, so the sweep above really reads what the pages draw."""
    found = _sweep(tmp_path, True, switch_on=True)
    assert any(h[0] == "modes" for h in found), found


def test_the_card_readers_log_lines_name_no_feature():
    """The lines the card reader writes to the shared log (shown on every tab) say what was
    read and how long it took, never what it was read for."""
    import inspect
    from pinball_decryptor.webui import modes_reading
    src = inspect.getsource(modes_reading.TitleReadMixin)
    said = re.findall(r'_say_read\(\s*"([^"]*)"', src)
    assert said, "the reader writes no log line?"
    for text in said + [modes_reading.TitleReadMixin.READ_LOG_TAG]:
        assert not WORDS.search(text), text
    from pinball_decryptor.plugins.stern import title_reader
    for words in title_reader.STEP_WORDS.values():
        assert not WORDS.search(words), words
