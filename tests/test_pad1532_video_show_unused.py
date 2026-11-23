"""PAD-1532: "Show unused" on the Video tab, as on the Audio tab - unticked, the clips the game
never plays (Played in: Not played) leave the list."""
import json
import os

from tests.test_pad444_clip_modes import FOLLOW, MAIN, OTHER, SHARED, SOLO, _ready, _stub_reading
from tests.test_webui_video import _project, _rels, _scan, _wait
from tests.webui_harness import web_app

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(HERE, "..", "pinball_decryptor", "webui", "static", "js", "tabs", "video.js")


def test_unticked_it_leaves_out_only_the_clips_the_game_never_plays(tmp_path, monkeypatch):
    proj = _project(tmp_path, names=(SHARED, SOLO, OTHER, MAIN))
    _stub_reading(monkeypatch, tmp_path, proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        st = _ready(w)
        assert not st.get("hide_unused")                     # ticked (every clip) by default
        assert sorted(_rels(st)) == sorted([SHARED, FOLLOW, SOLO, OTHER, MAIN])
        assert w.call("video.set_hide_unused", True) is True
        st = _wait(w, lambda st: OTHER not in _rels(st))
        assert sorted(_rels(st)) == sorted([SHARED, FOLLOW, SOLO, MAIN])   # "other" code stays
        assert st["hide_unused"] is True and st["counts"]["shown"] == 4
        # the mode list's "Not played by the game" asks for them, so it shows them all the same
        assert w.call("video.set_mode_filter", "__unplayed__") is True
        assert _rels(w.state("video")) == [OTHER]
        assert w.call("video.set_mode_filter", "") is True
        assert OTHER not in _rels(w.state("video"))
        # it goes with the project's staged changes, and comes back on the next scan
        staged = json.loads((proj / ".staged_changes.json").read_text(encoding="utf-8"))
        assert staged.get("video_hide_unused") is True
        _scan(w, proj)
        st = _ready(w)
        assert st["hide_unused"] is True and OTHER not in _rels(st)
        # revealing a hidden clip (from another tab) shows every clip again
        w.run(w.window.reveal_video_slot, OTHER)
        st = _wait(w, lambda st: OTHER in _rels(st))
        assert not st["hide_unused"]
        assert w.call("video.set_hide_unused", False) is True
        staged = json.loads((proj / ".staged_changes.json").read_text(encoding="utf-8"))
        assert "video_hide_unused" not in staged


def test_the_page_draws_the_tick_beside_show_once_the_card_is_read():
    with open(JS, encoding="utf-8") as f:
        src = f.read()
    tick = src.index('label="Show unused"')
    assert src.index('call("video.set_change_filter", v)') < tick < src.index("vid-modefilter")
    assert 'md.ready ? html`<${Check} checked=${!s.hide_unused} label="Show unused"' in src
    assert 'call("video.set_hide_unused", !v)' in src
