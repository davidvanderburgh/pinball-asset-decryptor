"""PAD-402 (DragonRR): a file loaded over the user's own edits, in Scenes and in Modes.

Two people working on one project load each other's files. Whatever the file would change of
what the user edited is listed, one row each, and they answer: Cancel, Replace all, Skip
conflicts (load only the rest), or Replace ticked only. Before anything of theirs is replaced,
their own are saved to a backup file in the project's Backups folder (a tick they can clear).
Modes also offer Keep both, the old load beside theirs under a new name.
"""

import json
import os
import zipfile

from pinball_decryptor.core import text_manifest
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import scene_edit, scene_share

_STATIC = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                       "webui", "static")

MINE = [{"op": "move", "node": 9, "dx": 1, "dy": 1}]
THEIRS = [{"op": "move", "node": 5, "dx": 3, "dy": 4}]


def _two_projects(tmp_path):
    from tests.test_gui_scene_editor import CARD, _seed
    mine, friend = tmp_path / "mine", tmp_path / "friend"
    _seed(mine)
    _seed(friend)
    scene_edit.save(str(friend), {CARD: THEIRS})
    text_manifest.save(str(friend), [{"path": CARD, "original": "KAIJU", "replacement": "BEAST"}])
    scene_edit.save(str(mine), {CARD: MINE})
    text_manifest.save(str(mine), [{"path": CARD, "original": "KAIJU", "replacement": "GOJI"}])
    return mine, friend


def _spec(project, slug):
    return dict(MP.list_modes(project)[0])[slug]


def _backups(project):
    d = os.path.join(str(project), MP.BACKUP_DIR)
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def test_scenes_ask_about_each_conflict_and_back_up_first(tmp_path):
    from tests.test_gui_scene_editor import CARD, _open, _wait
    from tests.webui_harness import web_app
    mine, friend = _two_projects(tmp_path)
    zip_path = str(tmp_path / "from sam.zip")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, friend)
        w.answers.append(zip_path)
        assert w.call("text_scenes.edits_save", "all", True) == zip_path
        _open(w, mine)

        # every conflict is a row: the scene and the text line, mine beside the file's
        w.answers.extend([zip_path, "cancel"])
        assert w.call("text_scenes.edits_load") is None
        spec = w.asked[-1]
        assert spec["kind"] == "conflicts" and spec["backup_label"]
        rows = {i["id"]: (i["what"], i["mine"], i["theirs"]) for i in spec["items"]}
        assert rows["scene:" + CARD][1:] == ("1 edit: moved +1,+1", "1 edit: moved +3,+4")
        assert rows["text:0"] == ('Text "KAIJU"', '"GOJI"', '"BEAST"')
        assert "2 things you edited yourself" in spec["message"]
        assert scene_edit.ops_for(str(mine), CARD) == MINE and _backups(mine) == []

        # Skip conflicts: nothing of mine changes, and nothing is backed up
        w.answers.extend([zip_path, {"choice": "skip", "backup": True}])
        w.call("text_scenes.edits_load")
        assert scene_edit.ops_for(str(mine), CARD) == MINE
        assert text_manifest.changed(str(mine)) == {CARD: [("KAIJU", "GOJI")]}
        assert _backups(mine) == []
        assert "2 things you edited were kept" in w.state("text_scenes")["caption_full"]

        # one by one: the line replaced, the scene kept, mine saved to a file first
        w.answers.extend([zip_path, {"choice": "pick", "take": ["text:0"], "backup": True}])
        w.call("text_scenes.edits_load")
        assert _wait(w, lambda: text_manifest.changed(str(mine)) == {CARD: [("KAIJU", "BEAST")]})
        assert scene_edit.ops_for(str(mine), CARD) == MINE
        (backup,) = _backups(mine)
        assert backup.startswith("Before loading from sam ") and backup.endswith(".zip")
        cap = w.state("text_scenes")["caption_full"]
        assert "1 thing you edited was kept" in cap and backup in cap, cap
        # the backup is a scene save: it holds what was mine before the load
        saved = os.path.join(str(mine), MP.BACKUP_DIR, backup)
        assert scene_edit.read_share(saved) == {CARD: MINE}
        assert [(t["original"], t["new"]) for t in scene_share.read_extras(saved)["text"]] == [
            ("KAIJU", "GOJI")]

        # Replace all with the backup cleared: the file's scene, no second backup
        w.answers.extend([zip_path, {"choice": "replace", "backup": False}])
        w.call("text_scenes.edits_load")
        assert scene_edit.ops_for(str(mine), CARD) == THEIRS
        assert len(_backups(mine)) == 1

        # the same edits again: nothing to ask
        n = len(w.asked)
        w.answers.append(zip_path)
        w.call("text_scenes.edits_load")
        assert [s.get("kind") for s in w.asked[n:]] == ["file"]


def test_scenes_reset_mine_then_load_the_file(tmp_path):
    """Round 2: every scene of mine back as shipped, the ones the file does not touch too,
    then the whole file loaded; mine backed up first."""
    from tests.test_gui_scene_editor import CARD, _open, _wait
    from tests.webui_harness import web_app
    mine, friend = _two_projects(tmp_path)
    other = "/g/other/scene.radium"
    scene_edit.save(str(mine), {CARD: MINE, other: MINE})
    zip_path = str(tmp_path / "from sam.zip")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, friend)
        w.answers.append(zip_path)
        assert w.call("text_scenes.edits_save", "all", True) == zip_path
        _open(w, mine)
        w.answers.extend([zip_path, {"choice": "reset", "backup": True}])
        w.call("text_scenes.edits_load")
        assert "reset" in [b["id"] for b in w.asked[-1]["buttons"]]
        assert scene_edit.load(str(mine)) == {CARD: THEIRS}
        assert _wait(w, lambda: text_manifest.changed(str(mine)) == {CARD: [("KAIJU", "BEAST")]})
        (backup,) = _backups(mine)
        saved = os.path.join(str(mine), MP.BACKUP_DIR, backup)
        assert scene_edit.read_share(saved) == {CARD: MINE}
        cap = w.state("text_scenes")["caption_full"]
        assert cap.startswith("Put 2 scenes back as the game shipped them first."), cap
        assert "kept" not in cap and backup in cap, cap


def test_modes_ask_about_each_conflict_and_back_up_first(tmp_path, monkeypatch):
    from pinball_decryptor.core import preview
    from tests.test_webui_modes import _card_project, _modes_on_disk, _project
    from tests.webui_harness import web_app
    monkeypatch.setattr(preview, "enabled", lambda feature: feature == "modes")
    friend = _card_project(tmp_path / "friend", "godzilla_le-1_16_0.raw")
    mine = _card_project(tmp_path / "mine", "godzilla_le-1_16_0.raw")
    zip_path = str(tmp_path / "sam modes.zip")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, friend, card=None)
        assert w.call("modes.example", "KAIJU RUSH") == "kaiju_rush"
        w.answers.append(zip_path)
        assert w.call("modes.save_file", "all") == zip_path
        _project(w, mine, card=None)
        w.answers.append(zip_path)
        w.call("modes.load_file")
        assert _modes_on_disk(mine) == ["kaiju_rush"]

        # the same mode again: already here, no question, no kaiju_rush_2
        n = len(w.asked)
        w.answers.append(zip_path)
        assert w.call("modes.load_file") is None
        assert [s.get("kind") for s in w.asked[n:]] == ["file", "message"]
        assert "1 mode in the file is already here" in w.asked[-1]["message"]
        assert _modes_on_disk(mine) == ["kaiju_rush"]

        # mine changed: a conflict
        spec = _spec(mine, "kaiju_rush")
        spec.seconds = 45
        MP.save(mine, "kaiju_rush", spec)
        w.answers.extend([zip_path, "cancel"])
        assert w.call("modes.load_file") is None
        ask = w.asked[-1]
        assert ask["kind"] == "conflicts"
        assert [b["id"] for b in ask["buttons"]] == ["cancel", "copies", "skip", "replace", "pick"]
        (row,) = ask["items"]
        assert row["id"] == "kaiju_rush" and row["mine"].startswith("KAIJU RUSH, changed ")
        assert row["theirs"].startswith("KAIJU RUSH, saved ")

        w.answers.extend([zip_path, {"choice": "skip", "backup": True}])
        assert w.call("modes.load_file") is None
        assert "1 of yours was kept" in w.asked[-1]["message"]
        assert _spec(mine, "kaiju_rush").seconds == 45 and _backups(mine) == []

        w.answers.extend([zip_path, {"choice": "copies", "backup": True}])
        w.call("modes.load_file")
        assert _modes_on_disk(mine) == ["kaiju_rush", "kaiju_rush_2"]
        assert _backups(mine) == []
        MP.delete_mode(mine, "kaiju_rush_2")

        w.answers.extend([zip_path, {"choice": "replace", "backup": True}])
        w.call("modes.load_file")
        assert _modes_on_disk(mine) == ["kaiju_rush"]
        assert _spec(mine, "kaiju_rush").seconds != 45
        (backup,) = _backups(mine)
        assert backup in w.asked[-1]["message"]
        with zipfile.ZipFile(os.path.join(str(mine), MP.BACKUP_DIR, backup)) as z:
            assert json.loads(z.read("modes/kaiju_rush/mode.json"))["seconds"] == 45


def test_modes_import_replaces_and_skips_by_folder_name(tmp_path):
    a = _card_project_plain(tmp_path / "a")
    b = _card_project_plain(tmp_path / "b")
    for project, secs in ((a, 20), (b, 50)):
        for name in ("ONE", "TWO"):
            spec = MP.ModeSpec(name=name, title="godzilla_le_1_16")
            spec.seconds = secs
            MP.new_mode(project, spec=spec)
    out = str(tmp_path / "a.zip")
    MP.export_modes(a, out)
    conflicts, same = MP.share_conflicts(out, b)
    assert [c["slug"] for c in conflicts] == ["one", "two"] and same == []
    report = MP.import_modes(out, b, replace={"one"}, skip={"two"})
    assert [(m.slug, m.new_slug) for m in report.modes] == [("one", "one")]
    assert _spec(b, "one").seconds == 20 and _spec(b, "two").seconds == 50
    assert MP.import_modes(out, b, skip={"one", "two"}) is None
    assert MP.share_conflicts(str(tmp_path / "nope.zip"), b) == ([], [])


def _card_project_plain(path):
    from tests.test_webui_modes import _card_project
    return str(_card_project(path, "godzilla_le-1_16_0.raw"))


def test_the_page_draws_the_conflicts_dialog():
    js = open(os.path.join(_STATIC, "js", "core", "dialogs.js"), encoding="utf-8").read()
    assert 'top.kind === "conflicts"' in js and "function ConflictsModal" in js
    assert 'label: "Replace ticked only"' in js and "spec.backup_label" in js
