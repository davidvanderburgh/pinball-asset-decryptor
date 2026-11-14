"""PAD-1209: the Audio tab's Type, Show, Hide unused, Play sequentially and
Play replacements come back next session, like "Show comments" (PAD-1176).

They are kept app-wide in settings.json the moment they are picked.  Show and
Hide unused used to be kept per folder only; a folder saved that way still
opens as it was filtered until the app-wide choice is first made.

Driven through the web UI's Replace Audio service (webui/tabs/audio.py).
"""
import json

from tests.test_gui_audio_rename import _load
from tests.test_pad894_rename_from_callouts import _project, boxes  # noqa: F401
from tests.test_pad1069_audio_comments import ROWS
from tests.webui_harness import web_app

KEYS = ("audio_type", "audio_show", "audio_hide_unused",
        "audio_play_through", "audio_play_subst")


def _settings(tmp_path):
    files = list(tmp_path.rglob("settings.json"))
    assert files
    return json.loads(files[0].read_text(encoding="utf-8"))


def _toolbar(w):
    st = w.state("audio")
    return {k: st[k] for k in ("type", "show", "hide_unused", "play_through",
                               "play_subst")}


def test_untouched_nothing_is_saved_and_defaults_show(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert _toolbar(w) == {"type": "All types", "show": "All",
                               "hide_unused": False, "play_through": False,
                               "play_subst": False}
    assert not set(KEYS) & set(_settings(tmp_path))


def test_choices_are_saved_and_a_new_session_restores_them(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.state("audio")["type_useful"] is True
        assert w.call("audio.set_type", "Callouts") is True
        assert w.call("audio.set_show", "Unchanged") is True
        assert w.call("audio.set_hide_unused", True) is True
        # "Play replacements" ticks "Play sequentially" too
        assert w.call("audio.set_play_subst", True) is True
        assert w.state("audio")["play_through"] is True
        saved = {k: _settings(tmp_path).get(k) for k in KEYS}
    assert saved == {"audio_type": "Callouts", "audio_show": "Unchanged",
                     "audio_hide_unused": True, "audio_play_through": True,
                     "audio_play_subst": True}
    with web_app(tmp_path, mfr="stern", settings=saved) as w:
        # the Play boxes are back before any project is scanned
        assert w.state("audio")["play_through"] is True
        assert w.state("audio")["play_subst"] is True
        _load(w, assets)
        assert _toolbar(w) == {"type": "Callouts", "show": "Unchanged",
                               "hide_unused": True, "play_through": True,
                               "play_subst": True}
        # unticking from the page is remembered too
        w.run(lambda: w.window.service("audio")
              .audio_play_through_var.set(False))
        assert _settings(tmp_path)["audio_play_through"] is False


def test_app_wide_show_beats_the_folders_old_one(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        # the folder's sidecar keeps Show = Unchanged
        assert w.call("audio.set_show", "Unchanged") is True
    # no app-wide choice yet: the folder's own still opens
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.state("audio")["show"] == "Unchanged"
    with web_app(tmp_path, mfr="stern",
                 settings={"audio_show": "All", "audio_hide_unused": False,
                           "audio_type": "Nonsense"}) as w:
        _load(w, assets)
        assert w.state("audio")["show"] == "All"
        assert w.state("audio")["type"] == "All types"
