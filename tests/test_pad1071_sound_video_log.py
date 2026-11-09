"""PAD-1071: the Emulate tab's Sound and video log - every sound and clip the game started during a run, in a
window of its own, each one opened from its row.

The sounds come from the mode runtime's sound-worker hook (``soundlog.on``; a stock card gets the pinned runtime
with ``soundlog.only``, which hooks nothing else), read off mode.log by the playfield window
(``tools/spike2_emu/soundwatch.py``) beside the clips it already records (PAD-827), and named by the app from the
project (``plugins/stern/emulator_log.py``). Proven in the emulator on Deadpool Pro 1.16 (the ticket's summary)."""
import json
import os
import re
import sys

import pytest

from pinball_decryptor.plugins.stern import emulator_log as EL
from tests.webui_harness import web_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
sys.path.insert(0, RIG)
import soundwatch as SW  # noqa: E402


def _text(*parts):
    with open(os.path.join(RIG, *parts), encoding="utf-8") as f:
        return f.read()


def _lines(path):
    return [json.loads(ln) for ln in open(path, encoding="utf-8").read().splitlines()] if os.path.exists(path) else []


def _append(path, text, mode="a"):
    with open(path, mode, encoding="utf-8") as f:
        f.write(text)


# ---- the playfield window's reading of mode.log ----------------------------------------------------------
@pytest.mark.parametrize("line, want", [
    ("   25168 [pad] sound 388 0", {"request": 388, "n": 0}),
    ("   43857 [pad] sound 386 1", {"request": 386, "n": 1}),
    ("       0 [pad] sound log: every request the sound worker takes (soundlog.on)", {"log": "on"}),
    ("       0 [pad] sound log: off - the port names no sound_worker",
     {"log": "off", "why": "the port names no sound_worker"}),
    ("      12 [pad] NOT THIS GAME'S PORT - the core functions do not match (3 site(s) wrong). x",
     {"log": "off", "why": "the port is not this game's"}),
    ("      14 [pad] insider: score reports stay on this machine", None),
    ("      20 [KAIJU] sound 12 0", None),                # a mode's own line, not the worker's
])
def test_the_runtimes_lines_are_read_as_sounds_and_the_logs_state(line, want):
    assert SW.line_event(line) == want


def test_the_sounds_are_recorded_as_the_log_grows_and_from_the_top_after_a_new_boot(tmp_path):
    log, seen = tmp_path / "mode.log", tmp_path / "sounds_seen_0.jsonl"
    _append(log, "       0 [pad] port /dump/game.port: deadpool_pro 1.16, 113 sites, 25 shots\n"
                 "       0 [pad] sound log: every request the sound worker takes (soundlog.on)\n"
                 "   25168 [pad] sound 388 0\n   2516", "w")
    w = SW.SoundWatch(str(log), str(seen))
    assert w.poll(1.0) == 1
    _append(log, "9 [pad] sound 392 0\n")                  # the half line, finished
    assert w.poll(1.1) == 0                               # not before POLL_S
    assert w.poll(2.0) == 1
    assert [e.get("request", e.get("log")) for e in _lines(seen)] == ["on", 388, 392]
    assert all(isinstance(e["t"], float) for e in _lines(seen))
    # a new boot's install took the old log out and the runtime wrote a new one
    _append(log, "       0 [pad] port /dump/game.port: deadpool_pro 1.16, 113 sites\n   10 [pad] sound 7 0\n", "w")
    assert w.poll(3.0) == 1
    assert _lines(seen)[-1]["request"] == 7


def test_the_playfield_window_records_the_sounds_beside_the_volume_file(monkeypatch, tmp_path):
    try:
        import playfield as pf
    except Exception:                                    # noqa: BLE001
        pytest.skip("playfield not importable")
    monkeypatch.setattr(pf.padpath, "dump", lambda: str(tmp_path / "dump"))
    monkeypatch.setattr(pf.padpath, "slot", lambda: 4)
    monkeypatch.setattr(pf, "AUDIO_CTL", None)
    assert pf.sound_watch() is None                      # started by hand: no tab to read the record
    monkeypatch.setattr(pf, "AUDIO_CTL", str(tmp_path / "audio_ctl.json"))
    w = pf.sound_watch()
    assert w.log_path == str(tmp_path / "dump" / "mode.log")
    assert w.seen_path == EL.sounds_file(str(tmp_path), 4)


# ---- the rows, named from the project ----------------------------------------------------------------------
def _project(tmp_path):
    p = tmp_path / "proj"
    (p / "audio").mkdir(parents=True, exist_ok=True)
    (p / "sound_requests.tsv").write_text(
        "# The game's sound requests\nrequest\tidx\tsids\tname\talso\n"
        "151\t\t1441796\t\t\n"
        "388\t24\t1\t\t\n"
        "392\t8034,4920\t6175,5843\tSPEECH: GAME START\t\n", encoding="utf-8")
    for n in ("idx0024.wav", "idx8034 - kaiju roar.wav", "idx4920.wav"):
        (p / "audio" / n).write_bytes(b"RIFF")
    return str(p)


def _run(ctl, sounds=(), clips=()):
    os.makedirs(ctl, exist_ok=True)
    for path, evs in ((EL.sounds_file(ctl, 0), sounds), (EL.clips_file(ctl, 0), clips)):
        with open(path, "a", encoding="utf-8") as f:
            for ev in evs:
                f.write(json.dumps(ev) + "\n")


def test_sounds_and_clips_are_one_list_in_the_order_they_started_named_as_their_tab_rows(tmp_path):
    ctl = str(tmp_path / "ctl")
    _run(ctl, sounds=[{"log": "on", "t": 99.0}, {"request": 392, "n": 0, "t": 101.0},
                      {"request": 151, "n": 0, "t": 103.0}, {"request": 388, "n": 1, "t": 104.0}],
         clips=[{"path": "./a/0.asset", "rel": "video/CloneMultiballStart.mov", "name": "CloneMultiballStart",
                 "switch": "RIGHT RAMP MADE", "t": 102.0},
                {"path": "./a/0.asset", "rel": "video/CloneMultiballStart.mov", "name": "CloneMultiballStart",
                 "loop": True, "t": 105.0}])
    lg = EL.Log(ctl, 0, _project(tmp_path))
    assert lg.poll() is True
    got = [(r["kind"], r["name"], r["what"], r["rel"]) for r in lg.rows]
    assert got == [
        ("sound", "SPEECH: GAME START", "#392", "audio/idx8034 - kaiju roar.wav"),
        ("video", "CloneMultiballStart", "after RIGHT RAMP MADE", "video/CloneMultiballStart.mov"),
        ("sound", "Unnamed sound", "#151", ""),              # a song in a music bank: no Audio tab file
        ("sound", "idx0024", "#388", "audio/idx0024.wav"),
        ("video", "CloneMultiballStart", "loops", "video/CloneMultiballStart.mov"),
    ]
    assert lg.rows[0]["rels"] == ["audio/idx8034 - kaiju roar.wav", "audio/idx4920.wav"]
    assert any("music bank" in t for t in lg.rows[2]["tip"])
    assert any("numbered variant" in t for t in lg.rows[3]["tip"])
    assert lg.status == "on"
    assert lg.poll() is False                               # nothing new


def test_a_page_asks_only_for_the_rows_past_its_last_and_a_new_run_starts_the_list_again(tmp_path):
    ctl = str(tmp_path / "ctl")
    _run(ctl, sounds=[{"request": 388, "n": 0, "t": float(t)} for t in range(5)])
    lg = EL.Log(ctl, 0, _project(tmp_path))
    lg.poll()
    page = lg.page(-1)
    assert [r["i"] for r in page["rows"]] == [0, 1, 2, 3, 4] and page["first"] == 0
    assert page["counts"] == {"sound": 5, "video": 0}
    _run(ctl, sounds=[{"request": 392, "n": 0, "t": 9.0}])
    lg.poll()
    assert [r["i"] for r in lg.page(4)["rows"]] == [5]
    # Start: the tab takes the files out (the clips' with the names map), the next run's arrive
    EL.clear_sounds(ctl, 0)
    lg.poll()
    _run(ctl, sounds=[{"request": 151, "n": 0, "t": 20.0}])
    lg.poll()
    page = lg.page(5)
    assert page["first"] == 6 and [(r["i"], r["what"]) for r in page["rows"]] == [(6, "#151")]


def test_a_run_whose_sounds_cannot_be_logged_says_why(tmp_path):
    ctl = str(tmp_path / "ctl")
    _run(ctl, sounds=[{"log": "off", "why": "the port names no sound_worker", "t": 1.0}])
    lg = EL.Log(ctl, 0, str(tmp_path / "no project"))
    assert lg.poll() is True
    assert (lg.page()["status"], lg.page()["why"]) == ("off", "the port names no sound_worker")


def test_a_project_without_the_request_map_still_lists_the_sounds_by_number(tmp_path):
    ctl = str(tmp_path / "ctl")
    _run(ctl, sounds=[{"request": 12, "n": 0, "t": 1.0}])
    lg = EL.Log(ctl, 0, str(tmp_path))
    lg.poll()
    assert (lg.rows[0]["name"], lg.rows[0]["what"]) == ("Unnamed sound", "#12")
    assert any("Extract the card into it again" in t for t in lg.rows[0]["tip"])


# ---- the Emulate tab ------------------------------------------------------------------------------------------
def test_a_start_empties_the_last_runs_sounds_and_the_launch_asks_for_the_log(tmp_path, monkeypatch):
    from tests.test_webui_emulate import _svc
    monkeypatch.setenv("PAD_SLOT", "3")
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor.webui.tabs import emulate as emod
        svc = _svc(w)
        ctl = os.path.dirname(emod.audio_ctl_file())
        _run(ctl)
        _append(EL.sounds_file(ctl, 3), json.dumps({"request": 1, "n": 0, "t": 1.0}) + "\n")
        monkeypatch.setattr(svc, "_assets", lambda: _project(tmp_path))
        w.run(svc._clip_names_for_run)
        assert not os.path.exists(EL.sounds_file(ctl, 3))
        assert "PAD_SOUNDLOG=1" in svc._launch_env([])
        # what the playfield window then writes is what the page reads
        _append(EL.sounds_file(ctl, 3), json.dumps({"request": 392, "n": 0, "t": 5.0}) + "\n")
        got = w.call("emulate.log_rows", -1)
        assert [(r["name"], r["rel"]) for r in got["rows"]] == [("SPEECH: GAME START",
                                                                 "audio/idx8034 - kaiju roar.wav")]
        assert got["root"] == _project(tmp_path) and got["project"] == "proj"
        assert w.call("emulate.log_rows", got["rows"][-1]["i"])["rows"] == []
        # no native window in the tests: the page opens the address itself
        assert w.call("emulate.log_open")["url"].startswith("/static/js/tabs/emulate_log.html?t=")


def test_open_takes_a_row_to_its_tab_selected_and_playing(tmp_path, monkeypatch):
    from tests.test_webui_emulate import _svc
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        asked = []
        audio, video = w.window.service("audio"), w.window.service("video")
        monkeypatch.setattr(audio, "play_row", lambda rel: asked.append(("audio", rel)) or True)
        monkeypatch.setattr(video, "play", lambda rel: asked.append(("video", rel)) or True)
        assert w.call("emulate.log_show", "sound", "audio/idx0024.wav") is True
        assert w.ctx.store.get("shell", "tab") == "audio"
        assert w.call("emulate.log_show", "video", "video/CloneMultiballStart.mov") is True
        assert w.ctx.store.get("shell", "tab") == "video"
        assert asked == [("audio", "audio/idx0024.wav"), ("video", "video/CloneMultiballStart.mov")]
        assert w.call("emulate.log_show", "sound", "") is False


def test_a_stock_card_gets_the_stage_that_hooks_the_sound_worker_and_nothing_else(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_runtime as MR
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from pinball_decryptor.webui import emulate_log as ELW
    said = []

    class Tab:
        def _log(self, line):
            said.append(line)

        def _elog_dir_slot(self):
            return str(tmp_path), 2

    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(MT, "card_title", lambda card: ("deadpool_pro", "1.16.0", 2))
    port = MR.port_file("deadpool_pro", "1.16")
    assert port, "Deadpool Pro 1.16 ships a port"
    # a launch that brings its own runtime (the override set's modes, Try it) needs none
    assert ELW.EmulateLogMixin._elog_stage_env(Tab(), ["PAD_MODE_SO=/lib/pad_mode.so"], "card.raw") == []
    env = ELW.EmulateLogMixin._elog_stage_env(Tab(), ["PAD_AUDIO=1"], "card.raw")
    assert len(env) == 1 and env[0].startswith("PAD_SOUNDLOG_STAGE=")
    stage = tmp_path / "pad_soundlog_stage_2"
    assert sorted(os.listdir(stage)) == ["game.port", "pad_mode.so", "soundlog.only"]
    assert (stage / "pad_mode.so").read_bytes() == open(MR.prebuilt_object(), "rb").read()
    assert (stage / "game.port").read_bytes() == open(port, "rb").read()
    # a build with no port: no stage, and the log says the sounds are not listed
    monkeypatch.setattr(MT, "card_title", lambda card: ("some_title", "9.99", 2))
    assert ELW.EmulateLogMixin._elog_stage_env(Tab(), [], "card.raw") == []
    assert "lists no sounds this run" in said[-1] and "no port for some_title" in said[-1]


def test_the_windows_card_offers_the_log_and_the_page_reads_the_rows():
    js = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "emulate.js"),
              encoding="utf-8").read()
    assert 'call("emulate.log_open")' in js and "Sound and video log" in js
    page = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "emulate_log.js"),
                encoding="utf-8").read()
    assert '"emulate.log_rows"' in page and '"emulate.log_show"' in page and "/media?p=" in page


# ---- the rig ----------------------------------------------------------------------------------------------------
def test_the_runtime_arms_the_sound_log_right_after_the_port_gate_and_stops_there_for_a_stock_card():
    src = _text("modes", "sdk", "pad_mode_runtime.c")
    start = src[src.index("static void pad_mode_start(void)"):]
    assert re.search(r"if \(!port_gate\(\)\) return;\s*\n\s*if \(soundlog_arm\(\)\) return;", start)
    arm = src[src.index("static int soundlog_arm(void)"):src.index("static void pad_mode_start(void)")]
    assert 'pm_trigger("soundlog.only")' in arm and 'pm_trigger("soundlog.on")' in arm
    # its own allowance: mode.log's 40000 lines would end a long session's list
    assert "if (worker_log) sound_say(r[0], r[2]);" in src


def test_every_boot_asks_soundlog_sh_after_the_cards_modes_and_the_launch_carries_its_variables():
    run = _text("run_game.sh")
    first = run.index('_cardmode_so=$(bash "$S/modes/cardmodes.sh"')
    assert run.index('bash "$S/modes/soundlog.sh"', first) > first
    image = run.index('PAD_CARD_IMAGE="$SEL_CARDIDX" bash "$S/modes/cardmodes.sh"')
    assert run.index('bash "$S/modes/soundlog.sh"', image) < run.index("export PAD_MODE_SO", image)
    watch = _text("watch.sh")
    launch = watch[watch.index('setsid env PAD_THREAD_ENTRY=1'):watch.index('bash "$RIG/run_game.sh"')]
    assert 'PAD_SOUNDLOG="${PAD_SOUNDLOG:-}"' in launch and 'PAD_SOUNDLOG_STAGE="${PAD_SOUNDLOG_STAGE:-}"' in launch
    tryit = _text("modes", "tryit.sh")
    install = tryit[tryit.index("    install)"):]
    assert '"$DUMP"/soundlog.only' in install.split('put "$S/pad_mode.so"')[0]     # cleared first
    assert 'put "$S/soundlog.only" "$DUMP/soundlog.only"' in install


def test_soundlog_sh_rules():
    sh = _text("modes", "soundlog.sh")
    off = sh[sh.index('if [ "${PAD_SOUNDLOG:-}" != 1 ]'):sh.index("so=\"\"")]
    assert 'rm -f "$DUMP/soundlog.on" "$DUMP/soundlog.only"' in off and "exit 0" in off
    own = sh[sh.index('if [ -n "${PAD_MODE_SO:-}" ]'):sh.index("elif")]
    assert 'rm -f "$DUMP/soundlog.only"' in own                        # never cuts a brought runtime short
    assert 'bash "$HERE/tryit.sh" install "$PAD_SOUNDLOG_STAGE"' in sh
    assert sh.rstrip().endswith("exit 0")                              # it never stops a run
