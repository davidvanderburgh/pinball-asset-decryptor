"""PAD-453 (DragonRR): Undo and Redo on the Video tab.

Each change the page makes to the picks is one step that Undo takes back and Redo does again:
the pick, a clear, a clip's own settings, the boxes over the list.  A step moves only what its
change moved, the sidecar follows every Undo, and the project folder follows the way Clear makes
it follow (an applied slot left with no pick gets its original back, a mode's own clip comes and
goes with its pick)."""

import json
import os

from pinball_decryptor.core import staged_originals
from pinball_decryptor.plugins.stern import clip_modes as CM
from tests.test_pad444_clip_modes import FOLLOW, MAIN, OTHER, SHARED, SOLO, _ready, _stub_reading
from tests.test_webui_video import _mine, _project, _row, _scan, _wait
from tests.webui_harness import web_app

INTRO, ATTRACT, BOSS = "video/intro.mp4", "video/attract.mp4", "video/sub/boss.mp4"


def _side(proj):
    return json.loads((proj / ".staged_changes.json").read_text(encoding="utf-8"))


def _log(w):
    return [l["text"] for l in w.run(w.window.log_history)]


def test_undo_takes_a_pick_back_and_redo_puts_it_again(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="spooky") as w:
        _scan(w, proj)
        assert w.state("video")["undo"] == {"undo": "", "redo": ""}
        assert w.call("video.undo") is False                  # nothing to undo yet
        w.answers.append(str(mine))
        assert w.call("video.choose", INTRO) is True
        assert w.state("video")["undo"] == {"undo": "the pick for intro.mp4", "redo": ""}
        assert w.call("video.undo") is True
        st = w.state("video")
        assert _row(st, INTRO)["rep"] == "Choose…"
        assert _side(proj)["video"] == {}
        assert st["can_clear"] is False
        assert st["undo"] == {"undo": "", "redo": "the pick for intro.mp4"}
        assert st["select"]["rels"] == [INTRO]                # the row it took back is shown
        assert "Replace Video: undid the pick for intro.mp4." in _log(w)
        assert w.window.pending_video_assignments(str(proj)) is None
        assert w.call("video.undo", True) is True
        st = w.state("video")
        assert _row(st, INTRO)["rep"] == "mine.mp4"
        assert _side(proj)["video"] == {INTRO: str(mine)}
        assert st["undo"] == {"undo": "the pick for intro.mp4", "redo": ""}
        assert "Replace Video: redid the pick for intro.mp4." in _log(w)
        assert w.call("video.undo", True) is False            # nothing left to redo


def test_a_cancelled_picker_is_no_step_and_a_new_change_ends_redo(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="ap") as w:
        _scan(w, proj)
        assert w.call("video.choose", INTRO) is False          # the picker closed: no step
        assert w.state("video")["undo"]["undo"] == ""
        for rel in (INTRO, ATTRACT):
            w.answers.append(str(mine))
            w.call("video.choose", rel)
        assert w.call("video.undo") is True                    # only the last pick goes
        st = w.state("video")
        assert _row(st, ATTRACT)["rep"] == "Choose…" and _row(st, INTRO)["rep"] == "mine.mp4"
        assert st["undo"] == {"undo": "the pick for intro.mp4", "redo": "the pick for attract.mp4"}
        w.call("video.set_trim", True)                         # a new change: no redo after it
        assert w.state("video")["undo"] == {"undo": "Trim / pad", "redo": ""}
        assert w.call("video.undo") is True
        assert w.window.video_trim_var.get() is False and _side(proj)["video_trim"] is False


def test_undo_brings_back_a_cleared_pick_with_its_own_settings(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="jjp") as w:
        _scan(w, proj)
        w.answers.append(str(mine))
        w.call("video.choose", INTRO)
        w.call("video.set_asis", INTRO, True)
        assert w.state("video")["undo"]["undo"] == "the conversion of intro.mp4"
        w.call("video.set_length", INTRO, "full")
        assert w.call("video.clear", [INTRO]) == 1
        assert w.state("video")["undo"]["undo"] == "clearing intro.mp4"
        assert w.call("video.undo") is True
        side = _side(proj)
        assert side["video"] == {INTRO: str(mine)}
        assert side["video_asis_slots"] == {INTRO: True}
        assert side["video_length_slots"] == {INTRO: "full"}
        # back through the length and the conversion, one step each, to the bare pick
        w.call("video.undo")
        assert _side(proj)["video_length_slots"] == {}
        w.call("video.undo")
        assert _side(proj)["video_asis_slots"] == {}
        assert w.call("video.row_menu", [INTRO])["asis"] == "box"
        assert _side(proj)["video"] == {INTRO: str(mine)}


def test_clear_replacements_and_replace_from_folder_are_one_step_each(tmp_path):
    proj = _project(tmp_path)
    mine = tmp_path / "bw"
    (mine / "deep").mkdir(parents=True)
    (mine / "Attract.MOV").write_bytes(b"x")
    (mine / "deep" / "boss.mp4").write_bytes(b"x")
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        w.answers += [str(mine), "yes"]
        assert w.call("video.replace_from_folder") is True
        w.answers.append("yes")
        assert w.call("video.clear_all") == 2
        assert w.state("video")["undo"]["undo"] == "Clear replacements"
        assert w.call("video.undo") is True
        st = w.state("video")
        assert _row(st, ATTRACT)["rep"] == "Attract.MOV" and _row(st, BOSS)["rep"] == "boss.mp4"
        assert sorted(st["select"]["rels"]) == [ATTRACT, BOSS]
        assert st["undo"]["undo"] == "Replace from folder"
        assert w.call("video.undo") is True
        assert _side(proj)["video"] == {}
        assert w.call("video.undo", True) and w.call("video.undo", True)
        assert _side(proj)["video"] == {}                     # cleared again


def test_undo_moves_only_what_its_step_moved(tmp_path):
    """A change made in between that is no step of this tab's (the Colors bar's Apply to all
    sets the clips' own switches, with an Undo of its own) is left as it is."""
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="jjp") as w:
        _scan(w, proj)
        for rel in (INTRO, ATTRACT):
            w.answers.append(str(mine))
            w.call("video.choose", rel)
        tab = w.window.service("video")
        w.run(lambda: tab._length.__setitem__(INTRO, "stock"))
        assert w.call("video.undo") is True                   # attract's pick
        assert w.run(lambda: dict(tab._length)) == {INTRO: "stock"}
        assert _row(w.state("video"), INTRO)["rep"] == "mine.mp4"


def test_undo_of_a_built_pick_puts_the_original_back_as_clear_does(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        w.answers.append(str(mine))
        w.call("video.choose", INTRO)
        # a build applied it: the slot has its .orig snapshot and the replacement's bytes
        target = proj / "video" / "intro.mp4"
        staged_originals.snapshot(str(proj), INTRO, None)
        target.write_bytes(b"replacement bytes")
        assert w.call("video.undo") is True
        assert target.read_bytes() == b"\0" * 64
        assert any(t.startswith("Replace Video: undid the pick for intro.mp4 (its slot has the "
                                "card's original file back") for t in _log(w))
        # Redo picks it again; the next build applies it again
        assert w.call("video.undo", True) is True
        assert _side(proj)["video"] == {INTRO: str(mine)}
        assert target.read_bytes() == b"\0" * 64


def test_the_steps_belong_to_the_project_folder(tmp_path):
    proj = _project(tmp_path)
    other = _project(tmp_path / "o")
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="pb") as w:
        _scan(w, proj)
        w.answers.append(str(mine))
        w.call("video.choose", INTRO)
        w.call("video.scan")                                  # the same folder again: kept
        _wait(w, lambda st: not st.get("scanning"))
        assert w.state("video")["undo"]["undo"] == "the pick for intro.mp4"
        _scan(w, other)
        _wait(w, lambda st: st["project"] and not st.get("scanning")
              and _row(st, INTRO)["rep"] == "Choose…")
        assert w.state("video")["undo"] == {"undo": "", "redo": ""}
        assert w.call("video.undo") is False
        assert _side(proj)["video"] == {INTRO: str(mine)}


def test_undo_and_redo_make_and_drop_a_modes_own_clip(tmp_path, monkeypatch):
    proj = _project(tmp_path, names=(SHARED, SOLO, OTHER, MAIN))
    _stub_reading(monkeypatch, tmp_path, proj)
    mine = tmp_path / "battra.mp4"
    mine.write_bytes(b"\1" * 40)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        _ready(w)
        w.answers.append(str(mine))
        assert w.call("video.choose", FOLLOW) is True
        _ready(w, lambda st: _row(st, FOLLOW)["rep"] == "battra.mp4")
        assert (proj / FOLLOW).exists()
        # Undo: the mode plays the shared clip again, its copy and record gone (as Clear does)
        assert w.call("video.undo") is True
        st = _ready(w, lambda st: _row(st, FOLLOW)["follow"])
        assert not (proj / FOLLOW).exists() and CM.records(str(proj)) == []
        assert _row(st, SHARED)["pair"] is True
        # Redo: its own clip again
        assert w.call("video.undo", True) is True
        st = _ready(w, lambda st: _row(st, FOLLOW)["rep"] == "battra.mp4")
        assert (proj / FOLLOW).read_bytes() == (proj / SHARED).read_bytes()
        assert [r["rel"] for r in CM.records(str(proj))] == [FOLLOW]
        assert _row(st, FOLLOW)["copy"] is True
        pend = w.run(lambda: w.window.service("video").pending_video_assignments(str(proj)))
        assert pend[1] == {FOLLOW: os.path.normpath(str(mine))}


def test_the_page_has_undo_redo_and_their_keys():
    js = open(os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui",
                           "static", "js", "tabs", "video.js"), encoding="utf-8").read()
    for bit in ('call("video.undo")', 'call("video.undo", true)', 'call("video.undo", redo)',
                '["Ctrl+Z", undo.undo ? "Undo " + undo.undo : T.undoNone]',
                'k === "y" || (k === "z" && e.shiftKey)', 'el.closest(".cpd")',
                'class="cpd-shell" ref=${shellRef}'):
        assert bit in js, bit
