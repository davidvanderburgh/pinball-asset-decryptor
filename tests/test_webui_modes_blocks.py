"""PAD-232: the web Modes tab's third way to make a mode, BLOCKS.

A blocks mode is made from New ▸ Mode from blocks…, listed with a Blocks pill, opened in the
block editor (its program, what is wrong with it, the C it makes and the card's shots, events
and callouts for the boxes), saved whole by the page, and taken to C with Edit as C. The tab runs
in-process (tests/webui_harness.py) against a scratch Godzilla Pro 1.15 project.
"""
import os

from pinball_decryptor.plugins.stern import block_modes as BM
from tests.test_webui_modes import _project, _svc, preview_on  # noqa: F401 - a fixture
from tests.webui_harness import web_app


def test_a_blocks_mode_is_made_listed_opened_saved_and_taken_to_c(tmp_path, preview_on):  # noqa: F811
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        svc = _svc(w)
        opened = []
        svc._opener = opened.append
        assert w.call("modes.new_blocks_mode", "Ramp Frenzy") == "ramp_frenzy"
        st = w.state("modes")
        rows = [r for r in st["rows"] if r["kind"] == "code"]
        assert rows == [{"slug": "ramp_frenzy", "kind": "code", "name": "Ramp Frenzy", "chip": "",
                         "chip_tip": "", "blocks": True}]
        assert st["sel"] == {"slug": "ramp_frenzy", "kind": "code"}
        assert st["n_blocks"] == 1 and st["n_code"] == 0 and st["n_form"] == 0
        b = st["code"]["blocks"]
        assert b["program"]["scripts"][0]["hat"]["shot"] == "Left ramp"      # the card's own shots
        assert b["problems"] == [] and st["code"]["status"] == "Ready to build."
        assert "Maser target" in b["choices"]["shots"]
        assert {"name": "skill_shot", "label": "the skill shot is made"} in b["choices"]["events"]
        assert {"role": "ten_seconds", "label": "Ten seconds left"} in b["choices"]["callouts"]
        light = b["choices"]["light"]                             # PAD-376: the Light show block's boxes
        assert [s["key"] for s in light["shows"]][:2] == ["burst", "beams"] and light["shows"][0]["steps"]
        assert ["bolts", "lightning"] in light["fx"] and ["top", "the top"] in light["places"]
        assert b["c"].startswith("/* ramp_frenzy.c - Ramp Frenzy, a mode made of blocks")
        assert opened == []                                       # nothing opens in an editor
        # the title the mode was made for is stamped, as for a code mode
        from pinball_decryptor.plugins.stern import code_modes as CM
        assert CM.load(str(proj), "ramp_frenzy").extra.get("title")

        # the page saves the whole program; a shot the card lacks is named, and the C follows
        prog = b["program"]
        prog["scripts"][0]["hat"]["shot"] = "Moon ramp"
        prog["name"] = "RAMPAGE"
        got = w.call("modes.blocks_save", "ramp_frenzy", prog)
        assert got["problems"] == ["Script 1's When names Moon ramp, a shot this card does not have."]
        st = w.state("modes")
        assert st["code"]["status"].startswith("To fix before it can be built: Script 1")
        assert st["rows"][0]["name"] == "RAMPAGE"
        with open(proj / "modes" / "ramp_frenzy" / "ramp_frenzy.c", encoding="utf-8") as f:
            assert '"Moon ramp"' in f.read()
        # only the OPEN mode's blocks are saved
        assert w.call("modes.blocks_save", "someone_else", prog) is None

        # Edit as C: a code mode from now on, its blocks kept aside
        w.answers.append("yes")
        assert w.call("modes.blocks_to_code") is True
        st = w.state("modes")
        assert st["code"]["blocks"] is None
        assert st["rows"][0]["blocks"] is False and st["n_code"] == 1 and st["n_blocks"] == 0
        assert opened and opened[-1].endswith("ramp_frenzy.c")
        assert os.path.isfile(BM.blocks_path(str(proj), "ramp_frenzy") + ".bak")


def test_duplicate_of_a_blocks_mode_stays_blocks(tmp_path, preview_on):  # noqa: F811
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new_blocks_mode", "Ramp Frenzy")
        assert w.call("modes.duplicate") == "ramp_frenzy_copy"
        st = w.state("modes")
        assert st["sel"] == {"slug": "ramp_frenzy_copy", "kind": "code"}
        assert st["code"]["blocks"]["program"]["name"] == "Ramp Frenzy COPY"
        assert 'pm_trigger("ramp_frenzy_copy.start")' in st["code"]["blocks"]["c"]
        w.answers.append("yes")
        assert w.call("modes.delete") is True
        assert not os.path.isdir(proj / "modes" / "ramp_frenzy_copy")


def test_no_project_says_so(tmp_path, preview_on):  # noqa: F811
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("modes.new_blocks_mode", "X") is None
        assert w.state("modes")["tryit_line"].startswith("Open or extract a card project first")


def test_start_mode_now_reaches_a_blocks_mode_built_into_the_run(tmp_path, preview_on):  # noqa: F811
    from tests.test_webui_modes import _FakeEmulate, _wait, _with_emu
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, proj)
        w.call("modes.new_blocks_mode", "Ramp Frenzy")
        emu = _FakeEmulate()
        _with_emu(w, emu)
        w.call("modes.start_now")
        assert w.state("modes")["tryit_line"] == "the emulator is not running: press Try it first."
        emu._last_up = True
        w.call("modes.start_now")
        assert w.state("modes")["tryit_line"].startswith("the run that is up was not started by Try it")
        live = {"project": str(proj), "slots": {}, "signatures": {}, "stage": str(tmp_path),
                "run": emu._launch_serial, "codes": [], "codes_unreached": []}
        svc._tryit_live = dict(live)
        w.call("modes.start_now")
        assert w.state("modes")["tryit_line"] == ("ramp_frenzy is not in the game that is running: "
                                                  "press Try it to build it in.")
        svc._tryit_live = dict(live, codes=["ramp_frenzy"])
        ran = []

        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        svc._run_fn = lambda cmd, **kw: (ran.append(cmd), R())[1]
        assert w.run(svc.on_start_now) == ["rig", "modes/tryit.sh", "start-code", "ramp_frenzy"]
        assert _wait(w, lambda: w.state("modes")["tryit_line"] ==
                     "asked the game to start ramp_frenzy. A game must be in play.")


def test_own_clips_and_sounds_are_picked_into_the_folder_and_carried(tmp_path, preview_on):  # noqa: F811
    """PAD-374: "+ Clip…" / "+ Sound…" / "Music…" copy the file into the mode's folder and name it;
    the saved program puts it in assets.json, and the problems look for it in the folder."""
    from pinball_decryptor.plugins.stern import code_modes as CM
    proj = tmp_path / "proj"
    src = tmp_path / "films"
    src.mkdir()
    for f in ("King Sever.mp4", "roar.wav", "bed.wav", "notes.txt"):
        (src / f).write_bytes(b"x")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new_blocks_mode", "Heads")
        ch = w.state("modes")["code"]["blocks"]["choices"]
        assert ch["why_clip"] == "" and ch["why_sound"] == "" and ch["why_music"] == ""
        folder = proj / "modes" / "heads"
        w.answers.append(str(src / "King Sever.mp4"))
        got = w.call("modes.blocks_pick", "clip", [])
        assert got == {"name": "king_sever", "file": "king_sever.mp4", "path": str(folder / "king_sever.mp4")}
        w.answers.append(str(src / "roar.wav"))
        assert w.call("modes.blocks_pick", "sound", [])["file"] == "roar.wav"
        w.answers.append(str(src / "roar.wav"))                 # again: a name of its own, a copy of its own
        again = w.call("modes.blocks_pick", "sound", ["roar"])
        assert again["name"] == "roar_2" and again["file"] == "roar_2.wav"
        w.answers.append(str(src / "bed.wav"))
        assert w.call("modes.blocks_pick", "music", [])["file"] == "music.wav"
        w.answers.append(str(src / "notes.txt"))
        assert w.call("modes.blocks_pick", "sound", []) is None  # not a WAV
        w.answers.append("")
        assert w.call("modes.blocks_pick", "clip", []) is None   # nothing picked
        assert w.call("modes.blocks_pick", "picture", []) is None
        assert sorted(os.listdir(folder)) == ["assets.json", "blocks.json", "heads.c", "king_sever.mp4",
                                              "music.wav", "roar.wav", "roar_2.wav"]

        prog = w.state("modes")["code"]["blocks"]["program"]
        prog["clips"] = [{"name": "king_sever", "file": "king_sever.mp4"}, {"name": "gone", "file": "gone.mp4"}]
        prog["sounds"] = [{"name": "roar", "file": "roar.wav", "priority": 3}]
        prog["music"] = "music.wav"
        prog["scripts"][1]["do"].append({"op": "clip", "clip": "king_sever", "where": "full"})
        prog["scripts"][1]["do"].append({"op": "sound", "sound": "roar", "fallback": None})
        got = w.call("modes.blocks_save", "heads", prog)
        assert got["problems"] == ["The clip gone's file gone.mp4 is not in the mode's folder: pick it again."]
        spec = CM.load(str(proj), "heads")
        assert spec.clips == {"king_sever": "king_sever.mp4", "gone": "gone.mp4"}
        assert spec.calls == {"roar": {"wav": "roar.wav", "priority": 3}} and spec.music == "music.wav"
        c = w.state("modes")["code"]
        assert 'clip_full("king_sever");' in c["blocks"]["c"] and 'sound("roar");' in c["blocks"]["c"]
        assert c["folder"] == str(folder)


def test_own_sounds_cannot_be_picked_where_the_card_cannot_carry_them(tmp_path, preview_on, monkeypatch):  # noqa: F811
    from pinball_decryptor.plugins.stern import mode_sounds as MS
    monkeypatch.setattr(MS, "carriers", lambda *a, **k: None)
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new_blocks_mode", "Heads")
        ch = w.state("modes")["code"]["blocks"]["choices"]
        assert ch["why_sound"].startswith("the app has not found spare sounds on") and ch["why_music"]
        assert w.call("modes.blocks_pick", "sound", []) is None and not w.answers
