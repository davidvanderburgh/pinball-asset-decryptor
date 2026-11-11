"""PAD-1176: a "Show comments" checkbox on the Audio tab.

The Comment column (PAD-1069) used to appear only once a sound had a
comment, with no way to show or hide it.  "Show comments" now shows or
hides it, and the choice is kept app-wide in settings.json, so it is the
same in the next session.  Until it is first ticked or unticked the column
behaves as before: shown once a sound has a comment.

Driven through the web UI's Replace Audio service (webui/tabs/audio.py).
"""
import json

from tests.test_gui_audio_rename import _load, _rows
from tests.test_pad894_rename_from_callouts import _project, boxes  # noqa: F401
from tests.test_pad1069_audio_comments import JACK, KAI, ROWS
from tests.webui_harness import web_app


def _settings(tmp_path):
    files = list(tmp_path.rglob("settings.json"))
    assert files
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_untouched_it_shows_once_a_sound_has_a_comment(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.state("audio")["comments"] is False
        assert w.call("audio.set_comment", JACK, "Kong") is True
        assert w.state("audio")["comments"] is True
    assert "audio_show_comments" not in _settings(tmp_path)


def test_ticked_shows_the_column_with_no_comments_yet(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.set_show_comments", True) is True
        assert w.state("audio")["comments"] is True
        # sortable while every cell is still blank
        assert w.call("audio.sort", "cm") is True
        assert w.state("audio")["sort"]["key"] == "cm"
    assert _settings(tmp_path)["audio_show_comments"] is True


def test_unticked_hides_it_and_a_new_session_remembers(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.set_comment", JACK, "Kong, after a battle") is True
        assert w.call("audio.set_comment", KAI, "Pilot") is True
        assert w.call("audio.sort", "cm") is True
        assert w.call("audio.set_show_comments", False) is True
        st = w.state("audio")
        assert st["comments"] is False
        # the hidden column no longer sorts the list: back to by name
        assert st["sort"] == {"key": "#0", "desc": False}
        # the search still finds words only a comment holds
        w.run(lambda: w.window.service("audio").audio_search_var.set("battle"))
        assert _rows(w) == [JACK]
    assert _settings(tmp_path)["audio_show_comments"] is False
    with web_app(tmp_path, mfr="stern",
                 settings={"audio_show_comments": False}) as w:
        _load(w, assets)
        assert w.state("audio")["comments"] is False
        assert w.call("audio.set_show_comments", True) is True
        assert w.state("audio")["comments"] is True
        assert {r["k"]: r.get("cm") for r in w.state("audio")["rows"]}[KAI] == "Pilot"
