"""PAD-813: the Getting started page - short videos and steps for the jobs a
new user comes for, open by itself on a first launch and from the top bar."""

import json
import os
import re
import subprocess

import pytest

from pinball_decryptor.webui import getting_started as GS
from tests.webui_harness import web_app

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------- at launch
def test_opens_for_a_new_user_only():
    assert GS.opens_at_launch({}, {}) is True
    assert GS.opens_at_launch({"disclaimer_accepted": True}, {}) is True
    # someone who has used the app does not get it again
    assert GS.opens_at_launch({"last_manufacturer": "stern"}, {}) is False
    assert GS.opens_at_launch({"projects": [{"folder": "x"}]}, {}) is False


def test_the_tick_wins():
    assert GS.opens_at_launch({"last_manufacturer": "stern",
                               "getting_started_at_launch": True}, {}) is True
    assert GS.opens_at_launch({"getting_started_at_launch": False}, {}) is False


def test_test_runs_and_plain_captures_never_get_it():
    assert GS.opens_at_launch({}, {"PAD_UI_NO_GETTING_STARTED": "1"}) is False
    assert GS.opens_at_launch({}, {"PYTEST_CURRENT_TEST": "x"}) is False


def _settings(tmp_path):
    with open(tmp_path / "cfg" / "settings.json", encoding="utf-8") as f:
        return json.load(f)


def test_first_launch_opens_it_once(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with web_app(tmp_path) as w:
        gs = w.state("shellx")["getting_started"]
        assert gs["open"] is True
        # seen once: unticked, so the next start goes to the picker
        assert gs["at_launch"] is False
        assert w.app._settings["getting_started_at_launch"] is False
        assert w.call("shellx.getting_started_close") is True
        assert w.state("shellx")["getting_started"]["open"] is False


def test_tick_is_saved(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.state("shellx")["getting_started"]["open"] is False
        w.call("shellx.getting_started_at_launch", True)
        assert w.state("shellx")["getting_started"]["at_launch"] is True
        assert w.app._settings["getting_started_at_launch"] is True
    assert _settings(tmp_path)["getting_started_at_launch"] is True


# ------------------------------------------------------------- the page
def test_top_bar_and_gear_open_it(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("shellx.getting_started_open")
        assert w.state("shellx")["getting_started"]["open"] is True
        w.call("shellx.getting_started_close")
        w.call("ui.settings_action", "getting_started")
        assert w.state("shellx")["getting_started"]["open"] is True


def test_go_opens_the_task_tab(tmp_path):
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        for task in GS.TASKS:
            w.call("shellx.getting_started_open")
            assert w.call("shellx.getting_started_go", task["id"]) == task["tab"], task["id"]
            assert w.state("shell")["tab"] == task["tab"]
            assert w.state("shellx")["getting_started"]["open"] is False


def test_go_without_a_manufacturer_goes_to_the_picker(tmp_path):
    with web_app(tmp_path) as w:
        w.call("shellx.getting_started_open")
        assert w.call("shellx.getting_started_go", "song") == ""
        assert w.state("shellx")["getting_started"]["open"] is False
        assert w.state("shell")["view"] == "picker"


def test_every_task_names_a_real_tab_and_has_steps(tmp_path):
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        rail = {t["ns"] for t in w.state("shell")["tabs"]}
        gs = w.state("shellx")["getting_started"]
    assert len({t["id"] for t in GS.TASKS}) == len(GS.TASKS)
    for t in GS.TASKS:
        assert t["tab"] in rail, t
        assert 3 <= len(t["steps"]) <= 5, t["id"]
    assert [t["id"] for t in gs["tasks"]] == [t["id"] for t in GS.TASKS]


def test_every_task_ships_its_video_and_poster():
    for t in GS.TASKS:
        for ext in ("mp4", "jpg"):
            path = GS.video_path(t["id"], ext)
            assert os.path.isfile(path), path
            assert os.path.getsize(path) > 2000, path


def test_videos_are_small_h264(tmp_path):
    """Every video plays in every webview (H.264 yuv420p) and stays small
    enough to ship in the installer."""
    probe = "ffprobe"
    try:
        subprocess.run([probe, "-version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no ffprobe")
    total = 0
    for t in GS.TASKS:
        path = GS.video_path(t["id"])
        total += os.path.getsize(path)
        out = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=codec_name,pix_fmt,width,height:format=duration",
                              "-of", "json", path], capture_output=True, text=True, check=True)
        info = json.loads(out.stdout)
        st = info["streams"][0]
        assert (st["codec_name"], st["pix_fmt"]) == ("h264", "yuv420p"), t["id"]
        assert (st["width"], st["height"]) == (1280, 720), t["id"]
        assert 10 <= float(info["format"]["duration"]) <= 120, t["id"]
    assert total < 40 * 1024 * 1024


def test_page_strings_are_plain_american(tmp_path):
    words = " ".join([GS.NOTE] + [t["title"] + " " + " ".join(t["steps"]) for t in GS.TASKS])
    assert "—" not in words
    assert not re.search(r"\b(colour|favourite|organise|centre)\b", words, re.I)
