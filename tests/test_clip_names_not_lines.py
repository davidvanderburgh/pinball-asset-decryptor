"""Simon (2026-11-21), comparing Godzilla's Match screen in the emulator with the Scenes preview:
"It is different, even the case is different. Why?"  The Match scene's title box holds MATCH; the
game program also holds the string ``match`` - the name of the Match clip, which the game hands
its video player - and the preview took that for the game's line for the box and drew "match".
A clip's name (a Video object's ``clips`` in scene_tree.json) is never a line on screen."""

import json
import os

GAME = "/godzilla_le/game"


def _rows(*lines):
    return [{"path": GAME, "original": s, "replacement": ""} for s in lines]


def _project(tmp_path, clips):
    d = tmp_path / "images" / "scene_textures"
    d.mkdir(parents=True)
    tree = {"/g/assets/lcd/a/scene.radium": {"objects": {
        "601": {"kind": "Video", "name": "Video_Instance", "w": 1360, "h": 768, "clips": clips},
        "7": {"kind": "Text", "text": "MATCH"}}}}
    (d / "scene_tree.json").write_text(json.dumps(tree), encoding="utf-8")
    return str(tmp_path)


def test_clip_names_are_read_from_every_video_player(tmp_path):
    from pinball_decryptor.webui.game_filled import clip_names
    assets = _project(tmp_path, ["match", "ATTRACT_LOOP1"])
    assert clip_names(assets) == {"match", "ATTRACT_LOOP1"}
    assert clip_names(str(tmp_path / "nowhere")) == frozenset()
    assert clip_names("") == frozenset()


def test_a_clip_name_is_not_the_games_line_for_a_box():
    from pinball_decryptor.webui.game_filled import game_row_for, try_lines
    rows = _rows("match", "MATCH AWARD")
    # without the clip names the clip reads as the box's own line (the bug)
    assert game_row_for(rows, "MATCH")["original"] == "match"
    assert game_row_for(rows, "MATCH", {"match"}) is None
    got = try_lines(rows, "MATCH", "Title_Instance", {"match"})
    assert "match" not in got and "MATCH AWARD" in got


def test_only_the_exact_clip_name_is_left_out():
    """A game line in other case is not the clip (the clip is named as written)."""
    from pinball_decryptor.webui.game_filled import game_row_for
    rows = _rows("match", "MATCH")
    assert game_row_for(rows, "MATCH", {"match"})["original"] == "MATCH"


def test_try_lines_for_reads_the_projects_clips(tmp_path, monkeypatch):
    from pinball_decryptor.core import text_manifest
    from pinball_decryptor.webui import game_filled
    assets = _project(tmp_path, ["match"])
    monkeypatch.setattr(text_manifest, "load", lambda _a: _rows("match", "MATCH AWARD"))
    monkeypatch.setattr(text_manifest, "manifest_path",
                        lambda a: os.path.join(a, "images", "scene_textures", "scene_tree.json"))
    got = game_filled.try_lines_for(assets, "MATCH", "Title_Instance")
    assert got and "match" not in got
