"""The web Modes tab (webui/tabs/modes.py): the Tk ModesPanel's behaviour on the web.

Every test runs the real app in-process (tests/webui_harness.py) against a scratch
project folder; nothing touches a real project, a card image or the emulator. The preview
switch is turned on by standing in ``core.preview.enabled`` (a real code is signed).
"""

import json
import os
import time

import pytest

from tests.webui_harness import web_app

@pytest.fixture
def preview_on(monkeypatch):
    from pinball_decryptor.core import preview
    monkeypatch.setattr(preview, "enabled", lambda feature: feature == "modes")
    return True


def _svc(w):
    return w.window.service("modes")


def _wait(w, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        try:
            if cond():
                return True
        except (OSError, ValueError):
            # a poll that reads a file mid-save: Windows refuses the read
            # while os.replace swaps it in, or the JSON is not there yet
            pass
        time.sleep(0.05)
    return cond()


#: The card a scratch project names when a test gives none: there is no default game any
#: more (a project that names no card greys the form), so the Godzilla tests say which
#: card their project is for. The image is not there, so the tab reads nothing and uses
#: the shipped port.
GODZILLA_CARD = "godzilla_pro-1_15_0.raw"


def _project(w, path, card=GODZILLA_CARD):
    """Point the project folder (Write's assets folder, else the Extract output) at *path*.
    A folder that names no card yet is made a *card* project first (``card=None``: a bare
    folder)."""
    os.makedirs(str(path), exist_ok=True)
    if card and not os.path.isfile(os.path.join(str(path), ".extract_source.json")):
        _card_project(path, card)
    svc = _svc(w)

    def go():
        var = svc._project_var()
        assert svc._project_hooked is var          # the tab follows this variable
        try:
            var.set(str(path))
        except Exception:                           # noqa: BLE001 - another tab's trace
            pass
        svc._refresh_all()
    w.run(go)
    w.drain()


def _modes_on_disk(project):
    root = os.path.join(str(project), "modes")
    if not os.path.isdir(root):
        return []
    return sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "mode.json")))


# ------------------------------------------------------------------ gating
MFRS = ["stern", "jjp", "spooky", "pb", "williams", "cgc", "dp", "ap", "bof",
        "data_east", "sega"]


def _mfr_keys():
    from pinball_decryptor.core.registry import all_manufacturers, load_plugins
    load_plugins()
    return {m.key for m in all_manufacturers()}


@pytest.mark.parametrize("mfr", MFRS)
def test_visible_only_for_spike2_with_the_preview_switch(tmp_path, preview_on, mfr):
    if mfr not in _mfr_keys():
        pytest.skip("no %s plugin" % mfr)
    with web_app(tmp_path, mfr=mfr) as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["modes"]["visible"] == (mfr == "stern")
        st = w.state("modes")
        if mfr == "stern":
            # no project yet: the Tk tab's no-project state
            assert st["project_label"].startswith("Open or extract a card project first")
            assert st["new_ok"] is False and st["ex_ok"] is False
            assert st["rows"] == []
            assert st["status"] == ""
            assert st["stock"]["msg"].startswith("Open or extract a card project first")
            assert st["about"].startswith("Make a game mode of your own")


def test_hidden_without_the_preview_switch(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs["modes"]["visible"]


@pytest.mark.parametrize("era", ["spike1", "whitestar"])
def test_hidden_on_other_stern_eras(tmp_path, preview_on, era):
    with web_app(tmp_path, mfr="stern", era=era) as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs["modes"]["visible"]


# ---------------------------------------------------------- the list, the form
def test_examples_duplicate_delete_and_the_cap(tmp_path, preview_on, monkeypatch):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        names = [e["name"] for e in w.state("modes")["examples"] if not e["code"]]
        assert names[:4] == ["KAIJU RUSH", "ATOMIC BREATH", "MOTHRA'S SONG", "MECHAGODZILLA"]
        codes = [e for e in w.state("modes")["examples"] if e["code"]]
        assert codes and codes[0]["label"].endswith(" (code mode)")
        assert w.call("modes.example", "KAIJU RUSH") == "kaiju_rush"
        assert w.state("modes")["form"]["name"] == "KAIJU RUSH"
        assert w.call("modes.duplicate")
        assert len(_modes_on_disk(proj)) == 2
        # Delete asks first; "no" keeps it
        w.answers.append("no")
        assert w.call("modes.delete") is False
        assert w.asked[-1]["title"] == "Delete mode"
        assert w.asked[-1]["message"].startswith("Delete KAIJU RUSH COPY, with its picture")
        w.answers.append("yes")
        assert w.call("modes.delete") is True
        assert len(_modes_on_disk(proj)) == 1
        # fill to the cap: New and the form examples grey, the line says what to do
        from pinball_decryptor.plugins.stern import mode_project as MP
        monkeypatch.setattr(MP, "MAX_MODES", 3)   # the real cap is 64; test the guard small
        for _i in range(2):
            w.call("modes.new")
        st = w.state("modes")
        assert len(_modes_on_disk(proj)) == 3
        assert st["new_ok"] is False
        assert st["cap_text"].startswith("3 of 3 modes: delete one to add another.")
        assert all(e["disabled"] for e in st["examples"] if not e["code"])
        assert not any(e["disabled"] for e in st["examples"] if e["code"])
        # the plugin's refusal is a message box titled as the Tk one
        n = len(w.asked)
        w.call("modes.new")
        assert len(w.asked) == n + 1 and w.asked[-1]["title"] == "New mode"


def test_choose_a_picture_copies_it_in(tmp_path, preview_on):
    from PIL import Image
    proj = tmp_path / "proj"
    png = tmp_path / "pic.png"
    Image.new("RGBA", (64, 32), (255, 0, 0, 255)).save(png)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new")
        w.answers.append(str(png))
        assert w.call("modes.choose", "art") == "art.png"
        assert w.asked[-1]["title"] == "Choose the screen's picture"
        st = w.state("modes")
        assert st["form"]["art_mode"] == "file"
        assert st["labels"]["art"] == "Picture: art.png"
        assert (proj / "modes" / "new_mode" / "art.png").is_file()
        # cancelling a sound choice puts the radio back
        w.answers.append("")
        assert w.call("modes.choose", "end") is None
        assert w.state("modes")["form"]["end_mode"] == "game"


# ------------------------------------------------------------------ code modes
def test_code_modes_are_in_the_list(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        svc = _svc(w)
        opened = []
        svc._opener = opened.append
        path = w.call("modes.new_code_mode", "Laser Show")
        assert path and os.path.isfile(path) and opened == [path]
        st = w.state("modes")
        code_rows = [r for r in st["rows"] if r["kind"] == "code"]
        assert code_rows and code_rows[0]["slug"] == "laser_show"
        assert st["sel"] == {"slug": "laser_show", "kind": "code"}
        assert st["code"]["source"].endswith("laser_show.c")
        assert st["code"]["trigger"] == "/dump/laser_show.start"
        assert st["tryit_line"].startswith("made modes/laser_show/laser_show.c from the Mode SDK")
        assert st["cap_text"] == "" and st["n_form"] == 0 and st["n_code"] == 1   # no slot
        assert st["code_words"].startswith("Code modes: ")
        assert st["dup_ok"] and st["del_ok"] and not st["editor_on"]
        # duplicate and delete a code mode
        assert w.call("modes.duplicate") == "laser_show_copy"
        w.answers.append("yes")
        assert w.call("modes.delete") is True
        assert not os.path.isdir(proj / "modes" / "laser_show_copy")


# ------------------------------------------------------------------ the stock table
def test_stock_table_needs_a_known_build(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj, card="mando_le-1_40_0.raw")
        st = w.state("modes")["stock"]
        assert st["on"] is False
        assert st["msg"].startswith("The app doesn't know the timers and awards of")


# ------------------------------------------------------------------ Try it
class _FakeEmulate:
    """The Emulate service's launch API, as the Tk EmulatePanel had it."""

    placeholder = None

    def __init__(self, accept=True, state=None):
        self.accept = accept
        self.state = dict(state or {})
        self.handed = []
        self.refused = []
        self.progress = []
        self.last_refusal = ""
        self._last_up = False
        self._launch_serial = 0

    def launch_with(self, prepare):
        self.handed.append(prepare)
        if not self.accept:
            self.last_refusal = "the emulator is not set up on this PC; use Check setup on the Emulate tab"
            return False
        self._launch_serial += 1
        return True

    def launch_state(self):
        return dict({"up": False, "busy": False, "overrides": False, "card": "", "rig": True},
                    **self.state)

    def set_preparing(self, text, pct=None):
        self.progress.append((text, pct))

    def prepare_refuse(self, reason):
        self.refused.append(reason)

    def prepare_cancelled(self):
        return False

    def launch_as_root(self):
        return False

    @staticmethod
    def rig_cmd(script, *args):
        return ["rig", script] + [str(a) for a in args]

    rig_cmd_root = rig_cmd


def _with_emu(w, emu):
    w.window._by_ns["emulate"] = emu


def test_tryit_refusals_before_the_hand_off(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        svc._platform = "win32"
        w.call("modes.tryit")
        assert w.state("modes")["tryit_line"].startswith("Open or extract a card project first")
        _project(w, proj)
        _with_emu(w, None)
        w.window._by_ns.pop("emulate", None)
        w.call("modes.tryit")
        assert w.state("modes")["tryit_line"] == "there is no Emulate tab to run it in."
        emu = _FakeEmulate(state={"busy": True})
        _with_emu(w, emu)
        w.call("modes.tryit")
        assert w.state("modes")["tryit_line"] == "there are no modes in this project yet."
        w.call("modes.new")
        w.call("modes.tryit")
        assert w.state("modes")["tryit_line"] == "the emulator is starting or stopping; wait for it."
        emu.state = {"up": True}
        w.call("modes.tryit")
        assert w.state("modes")["tryit_line"].startswith("the emulator is already running")
        emu.state = {"overrides": True}
        w.call("modes.tryit")
        assert w.state("modes")["tryit_line"].startswith("\"apply my edits\" is ticked")
        emu.state = {}
        emu.accept = False
        assert w.call("modes.tryit") is False
        st = w.state("modes")
        assert st["tryit"]["state"] == "failed"
        assert st["tryit_line"].startswith("the emulator is not set up on this PC")
        svc._platform = "darwin"
        w.call("modes.tryit")
        assert w.state("modes")["tryit_line"].startswith("Try it runs on Windows and Linux for now")


def test_tryit_hands_off_and_refuses_a_missing_card(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        svc._platform = "win32"
        _project(w, proj)
        w.call("modes.new")
        emu = _FakeEmulate()
        _with_emu(w, emu)
        assert w.call("modes.tryit") is True
        st = w.state("modes")
        assert st["tryit"]["state"] == "preflight" and st["tryit"]["working"]
        assert st["tryit_line"] == "building the modes and starting the card in the Emulate tab…"
        assert emu.handed == [svc.tryit_prepare]
        # the Emulate tab's worker runs the preparation with its card: none picked
        env = svc.tryit_prepare(str(tmp_path / "nope.raw"))
        assert env is None
        assert _wait(w, lambda: w.state("modes")["tryit"]["state"] == "failed")
        line = w.state("modes")["tryit_line"]
        assert line == "pick a card image in the Emulate tab first (a Godzilla Pro 1.15 card)."
        assert svc.tryit_prepare.last_reason == line
        assert emu.refused == [line]


def test_tryit_cancel_and_run_ended(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        svc._platform = "win32"
        _project(w, proj)
        w.call("modes.new")
        emu = _FakeEmulate()
        _with_emu(w, emu)
        w.call("modes.tryit")
        # the same button is Cancel while it works
        assert w.call("modes.tryit") is False
        assert w.state("modes")["tryit_line"] == "cancelling…"
        assert svc._tryit_cancelled()
        # a launch that never came up: failed, with where to look
        w.run(lambda: svc.run_ended(1))
        assert w.state("modes")["tryit"]["state"] == "failed"
        assert w.state("modes")["tryit_line"] == svc.TRYIT_NOT_UP
        # a live run that ended
        w.run(lambda: svc._tryit_set("live"))
        w.run(lambda: svc.run_ended(None))
        assert w.state("modes")["tryit"]["state"] == "ended"
        assert w.state("modes")["tryit_line"] == ("The run ended. Press Try it to run the modes "
                                                  "again.")


def test_start_and_end_mode_need_a_try_it_run(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, proj)
        w.call("modes.start_now")
        assert w.state("modes")["tryit_line"] == "open a mode first."
        w.call("modes.new")
        emu = _FakeEmulate()
        _with_emu(w, emu)
        w.call("modes.start_now")
        assert w.state("modes")["tryit_line"] == "the emulator is not running: press Try it first."
        w.call("modes.end_now")
        assert w.state("modes")["tryit_line"] == "the emulator is not running."
        emu._last_up = True
        w.call("modes.start_now")
        assert w.state("modes")["tryit_line"].startswith("the run that is up was not started by Try it")
        # a Try it record for THIS launch: Start mode now names the installed slot
        svc._tryit_live = {"project": str(proj), "slots": {"new_mode": 0}, "signatures": {},
                           "stage": str(tmp_path), "run": emu._launch_serial,
                           "codes": [], "codes_unreached": []}
        ran = []

        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        svc._run_fn = lambda cmd, **kw: (ran.append(cmd), R())[1]
        cmd = w.run(svc.on_start_now)
        assert cmd == ["rig", "modes/tryit.sh", "start", "0"]
        assert _wait(w, lambda: w.state("modes")["tryit_line"] ==
                     "asked the game to start NEW MODE. A game must be in play.")
        cmd = w.run(svc.on_end_now)
        assert cmd == ["rig", "modes/tryit.sh", "stop"]
        assert _wait(w, lambda: w.state("modes")["tryit_line"] ==
                     "asked the game to end the running mode.")


# ------------------------------------------------------------------ the film cutter
def test_film_dialog_opens_on_the_open_mode(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        assert w.call("modes.film_open", "clip") is False       # no mode open
        w.call("modes.new")
        assert w.call("modes.film_open", "sound") is True
        film = w.state("modes")["film"]
        assert film["take_sound"] and not film["take_clip"]
        assert film["status"] == "The mode keeps only the cut, never the film."
        w.call("ui.set", "modes", "film:start", "1:23")
        assert w.state("modes")["film"]["start"] == "1:23"
        w.call("modes.film_close")
        assert w.state("modes")["film"] is None
        assert w.state("modes")["labels"]["film"] == "Nothing cut from a video yet."


# ------------------------------------------------------------------ per title (item 148)
def _card_project(path, image_name):
    os.makedirs(str(path), exist_ok=True)
    with open(os.path.join(str(path), ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(str(path), image_name), "input_name": image_name}, f)
    return path


def test_jaws_greys_what_its_port_cannot_do(tmp_path, preview_on):
    proj = _card_project(tmp_path / "jaws", "jaws_le-1_02_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        assert st["title_text"].startswith("Card: jaws_le-1_02_0.raw, Jaws LE 1.02 (from ")
        assert "Modes of your own use its 27 shots." in st["title_text"]
        assert "port" not in st["title_text"] and st["title_port"] == "jaws_le-1.02.port"
        assert st["profile"]["label"] == "Jaws LE 1.02"
        assert len(st["profile"]["shots"]) == 27 and st["profile"]["cols"] == 3
        names = [e["name"] for e in st["examples"]]
        assert names == ["TARGET RUSH"]                   # not Godzilla's four, no code examples
        w.call("modes.new")
        st = w.state("modes")
        assert st["status"] == "Ready to build."
        for part in ("screen", "stack"):
            assert st["dis"][part], part
            assert st["reasons"][part].startswith("Not on this game: "), part
        assert not st["dis"]["lights"]              # item 164: its inserts, every one in the mode's colour
        assert not st["dis"]["events"]              # item 162: Jaws's events were seen firing
        assert "sound_unheard" not in st["reasons"]            # item 163: Jaws's callouts are heard
        assert not st["dis"]["clip"]


def test_an_unproven_port_says_so(tmp_path, preview_on, monkeypatch):
    import dataclasses
    from pinball_decryptor.plugins.stern import mode_project as MP
    real = MP._folder_profiles

    def folder_profiles(d):      # every shipped port is proven now: make Deadpool LE's a draft
        return {k: dataclasses.replace(p, proven=False, proven_note="it was drafted and has never run.")
                if p.game_dir == "deadpool_le" else p for k, p in real(d).items()}
    monkeypatch.setattr(MP, "_folder_profiles", folder_profiles)
    proj = _card_project(tmp_path / "dp", "deadpool_le-1_14_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        assert st["title_note"].startswith("Unproven: ")
        assert st["new_ok"] and st["ex_ok"]
        assert st["check_offer"] and st["check_wanted"] and st["check_done"] is None


def test_a_passing_check_proves_a_drafted_port(tmp_path, preview_on, monkeypatch):
    import dataclasses
    from pinball_decryptor.plugins.stern import game_check as GC
    from pinball_decryptor.plugins.stern import mode_project as MP
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path / "cache"))
    real = MP._folder_profiles

    def folder_profiles(d):
        return {k: dataclasses.replace(p, proven=False, proven_note="it was drafted and has never run.")
                if p.game_dir == "deadpool_le" else p for k, p in real(d).items()}
    monkeypatch.setattr(MP, "_folder_profiles", folder_profiles)
    res = GC.CheckResult(armed="armed: 1 mode(s)", started=True, pressed=3, ball_end=True,
                         shots_seen={"Left orbit": "LEFT ORBIT"}, shots_unseen=["Inner loop"],
                         when="2026-09-24 12:00")
    assert GC.record(os.path.join(MP.PORTS_DIR, "deadpool_le-1.14.port"), res)
    proj = _card_project(tmp_path / "dp", "deadpool_le-1_14_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        assert st["title_note"] == "" and not st["check_wanted"] and st["check_offer"]
        assert st["check_done"]["ok"] and st["check_done"]["when"] == "2026-09-24 12:00"
        assert st["check_done"]["text"].startswith("Checked in the emulator: modes run on Deadpool LE")


def test_beatles_switch_shots_are_proven_and_its_countdown_heard(tmp_path, preview_on):
    proj = _card_project(tmp_path / "beatles", "beatles-1_29_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        assert st["profile"]["label"] == "The Beatles 1.29" and len(st["profile"]["shots"]) == 35
        assert "shots from switches" not in st["title_note"]      # beatles-1.29 is in SWITCH_SHOTS_PROVEN
        w.call("modes.new")
        st = w.state("modes")
        assert not st["dis"]["countdown"]
        assert "sound_unheard" not in st["reasons"]            # item 163: 385 heard saying one..five


def test_tmnt_shots_and_greying(tmp_path, preview_on):
    proj = _card_project(tmp_path / "tmnt", "turtles_pro-1_59_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new")
        st = w.state("modes")
        assert st["profile"]["label"] == "TMNT Pro 1.59" and len(st["profile"]["shots"]) == 17
        # item 163: its countdown is heard (441); no time-up call carries an end sound of its own
        assert not st["dis"]["countdown"] and st["dis"]["own_sound"]
        assert st["reasons"]["sound"].startswith("Not on this game: ")
        # item 164: a clip plays on TMNT Pro 1.59 now, so only the picture and the sound are greyed
        assert not st["dis"]["film_clip"] and st["dis"]["film_still"] and st["dis"]["film_sound"]
        assert st["reasons"]["film"].startswith("Not on this game: cutting a picture for the screen "
                                                "or a sound from a film, because")


def test_a_card_with_no_port_is_read_only(tmp_path, preview_on):
    proj = _card_project(tmp_path / "mando", "mando_le-1_10_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        assert st["no_port"].startswith("Modes of your own can't be made for ")
        assert st["title_note"].startswith(st["no_port"])
        assert "MODE_SDK.md" in st["no_port_details"] and "MODE_SDK" not in st["title_note"]
        assert st["new_ok"] is False and st["ex_ok"] is False
        assert st["ex_tip"] == st["no_port"]              # the greyed Examples says why
        assert st["status"] == "Modes of your own can't be built for this card yet (see above)."
        assert st["shots_text"] == "(no shots: modes of your own can't be made for this card yet)"
        assert st["profile"]["shots"] == []


def test_tryit_uses_the_emulate_services_try_it_seam(tmp_path, preview_on):
    """Tk's main_window._modes_try: accepted -> the Emulate tab comes forward."""
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        svc._platform = "win32"
        _project(w, proj)
        w.call("modes.new")
        emu = _FakeEmulate()
        seen = []

        def try_it(prepare):
            seen.append(prepare)
            return False, "the emulator is already running: stop it first, then try again."
        emu.try_it = try_it
        _with_emu(w, emu)
        assert w.call("modes.tryit") is False
        assert seen == [svc.tryit_prepare]
        st = w.state("modes")
        assert st["tryit"]["state"] == "failed"
        assert st["tryit_line"] == "the emulator is already running: stop it first, then try again."


def test_the_real_emulate_service_has_the_launch_api(tmp_path, preview_on):
    """The web Emulate service answers every name this tab asks it for."""
    with web_app(tmp_path, mfr="stern") as w:
        emu = w.window.service("emulate")
        if getattr(emu, "placeholder", None):
            pytest.skip("the Emulate tab is not ported yet")
        for name in ("launch_with", "launch_state", "set_preparing", "prepare_refuse",
                     "prepare_cancelled", "launch_as_root"):
            assert callable(getattr(emu, name, None)), name
        for name in ("last_refusal", "_last_up", "_launch_serial", "emulate_card_var"):
            assert hasattr(emu, name), name
        from pinball_decryptor.webui import emulate_rig
        assert callable(emulate_rig.rig_cmd) and callable(emulate_rig.rig_cmd_root)
        # "Try it on" is the Emulate tab's own card box
        svc = _svc(w)
        assert svc._export("emulate_card_var") is emu.emulate_card_var


# ------------------------------------------------------------------ the film cutter, for real
def _test_film(tmp_path):
    import subprocess
    from pinball_decryptor.core.audio import find_ffmpeg
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("no ffmpeg")
    film = tmp_path / "film.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(film)],
                   check=True, capture_output=True)
    return film


def test_film_cut_becomes_the_modes_clip_and_saves(tmp_path, preview_on):
    film = _test_film(tmp_path)
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new")
        assert w.call("modes.film_open", "clip")
        fields = dict(w.state("modes")["film"], film=str(film), start="0:01", length="2",
                      take_clip=True, take_sound=True, take_still=True)
        assert w.call("modes.film_probe", fields)
        assert _wait(w, lambda: "Reading" not in (w.state("modes")["film"] or {}).get("info", "Reading"),
                     timeout=30)
        assert w.call("modes.film_cut", fields)
        assert _wait(w, lambda: w.state("modes")["film"] is None, timeout=60)
        folder = proj / "modes" / "new_mode"
        assert (folder / "clip.mp4").is_file() and (folder / "end.wav").is_file() \
            and (folder / "art.png").is_file()
        st = w.state("modes")
        assert st["form"]["clip"] == "file" and st["form"]["end_mode"] == "file" \
            and st["form"]["art_mode"] == "file"
        assert st["labels"]["film"].startswith("Clip: 2 s from 0:01.")
        data = json.loads((folder / "mode.json").read_text("utf-8"))
        assert data["clip_file"] == "clip.mp4" and data["clip_source"] == os.path.abspath(str(film))


# ------------------------------------------------------------------ a code example
def test_a_code_example_without_its_films(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        code = [e["name"] for e in w.state("modes")["examples"] if e["code"]]
        name = code[0]
        w.answers.append("")                  # "Where are the films?" - cancelled
        assert w.call("modes.code_example", name)
        assert w.asked[-1]["kind"] == "file" and w.asked[-1]["title"].startswith("Where are the films? ")
        assert _wait(w, lambda: w.state("modes")["tryit_line"].startswith("added the example "),
                     timeout=60)
        assert _wait(w, lambda: any(r["kind"] == "code" for r in w.state("modes")["rows"]))
        assert w.state("modes")["sel"]["kind"] == "code"


# ------------------------------------------------------------------ the game's own modes, staged
def test_stock_value_staged_for_the_next_write(tmp_path, preview_on):
    proj = _card_project(tmp_path / "gz", "godzilla_le-1_16_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")["stock"]
        if not st["on"]:
            pytest.skip("no stock table for godzilla_le 1.16 in this tree")
        assert st["msg"].startswith("Godzilla Premium/LE 1.16: ")
        assert "Nothing changed - every number is the game's own." in st["msg"]
        row = next(r for r in st["rows"] if not r["readonly"] and r["stock"] not in ("?", "0"))
        w.call("modes.stock_select", row["key"])
        st = w.state("modes")["stock"]
        assert st["row_on"] and st["value"] == row["value"]
        stock = int(row["stock"].replace(",", ""))
        note = w.call("modes.stock_set", str(stock + 1))
        st = w.state("modes")["stock"]
        if "staged for the next Write." in note:
            assert "1 change(s) staged for the next Write." in st["msg"]
            assert next(r for r in st["rows"] if r["key"] == row["key"])["changed"]
            assert w.call("modes.stock_all") == 1
            assert w.state("modes")["stock"]["note"] == ("Every number is back to the game's own "
                                                         "(1 change(s) undone).")
        else:
            assert st["note"] == note                 # refused with a sentence
        # a read-only row says why and cannot be set
        ro = [r for r in st["rows"] if r["readonly"]]
        if ro:
            w.call("modes.stock_select", ro[0]["key"])
            st = w.state("modes")["stock"]
            assert st["note"].startswith("Read-only: ") and not st["row_on"]


# ------------------------------------------------------------------ the review's fixes
def test_a_moved_callout_alone_is_ready(tmp_path, preview_on):
    """A mode opened on another build's card that only moved a callout builds as it is: the
    list and the editor say ready, and the sentence still says what moved."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    proj = _card_project(tmp_path / "jaws", "jaws_le-1_02_0.raw")
    spec = MP.blank_spec(MP.GODZILLA_PRO_1_15)
    spec.name, spec.start_shot, spec.scoring_shots = "SPIN", "Spinner", ["Spinner"]
    spec.callout_at = [[10, 1291]]
    spec.screen, spec.lights, spec.clip = False, False, "none"
    MP.save(str(proj), "spin", spec)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        assert st["status"].startswith("Ready to build. Callout 1291 is ")
        assert st["status"].endswith("a build uses this card's numbers.")
        assert st["ready"] is True
        assert [(r["name"], r["chip"]) for r in st["rows"]] == [("SPIN", "ready")]


def test_a_mode_not_open_names_the_page_to_fix(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        first = w.call("modes.new")
        w.call("modes.new")
        second = w.state("modes")["sel"]["slug"]
        assert second != first
        w.call("ui.set", "modes", "f:priority", "999")
        path = proj / "modes" / second / "mode.json"
        assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("priority") == 999)
        st = w.state("modes")
        assert st["fix_pages"] == ["show"] and st["rows"][1]["chip"] == "Show •"
        w.call("modes.select", first, "form")
        row = w.state("modes")["rows"][1]
        assert row["slug"] == second and row["chip"] == "Show •"
        assert row["chip_tip"].startswith("To fix before it can be built: The display priority is")


def test_page_of_every_problem_sentence():
    from pinball_decryptor.webui.tabs.modes import fix_chip, problem_pages
    assert problem_pages(["The mode needs a name.", "The award ladder is rising or fixed."]) == \
        ["mode", "scoring"]
    assert problem_pages(["Choose the video file for the second clip."]) == ["show"]
    assert problem_pages(["The end sound file end.wav is not in the mode's folder."]) == ["sounds"]
    assert problem_pages(["Callout id 'x' is not a callout number (Jaws LE 1.02 has 1 to 9)."]) == \
        ["sounds"]
    assert problem_pages(["The lit shots are solid, blink, pulse or chase."]) == ["lights"]
    assert problem_pages(["Godzilla Pro 1.15 has no shot called 'X' to end the mode."]) == ["scoring"]
    assert problem_pages(["Godzilla Pro 1.15 has no shot called 'X'."]) == ["mode"]
    assert fix_chip(["The mode needs a name.", "The clip plays at the start or at the end."]) == \
        "Mode +1 •"
    assert fix_chip(["an unknown title"]) == "to fix"


def test_spinboxes_carry_the_tk_bounds(tmp_path, preview_on):
    from pinball_decryptor.plugins.stern import mode_project as MP
    with web_app(tmp_path, mfr="stern") as w:
        spin = w.state("modes")["spin"]
        assert spin["seconds"] == [1, 300] and spin["start_count"] == [1, 20]
        assert spin["starts_count"] == [1, MP.STARTS_MAX]
        assert spin["cooldown"] == [0, MP.COOLDOWN_MAX]
        assert spin["restore_after"] == [1, MP.RESTORE_AFTER_MAX]
        assert spin["priority"] == [0, 255] and spin["callout_secs"] == [0, 300]
        assert spin["clip_seconds"][:2] == [1, 30] and spin["clip_both_seconds"][:2] == [1, 30]
        assert spin["sound_shot_every"] == [1, 20]


def test_the_end_sound_can_be_chosen_again(tmp_path, preview_on):
    """Tk re-opened the picker on every click of "My sound…": the page's Change… does, and
    the second file replaces the first."""
    import wave
    proj = tmp_path / "proj"
    wavs = []
    for i, n in enumerate((800, 1600)):
        p = tmp_path / ("s%d.wav" % i)
        with wave.open(str(p), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(48000)
            f.writeframes(b"\0\0" * n)
        wavs.append(p)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new")
        w.answers.append(str(wavs[0]))
        assert w.call("modes.choose", "end") == "end.wav"
        assert w.state("modes")["form"]["end_mode"] == "file"
        n = len(w.asked)
        w.answers.append(str(wavs[1]))
        assert w.call("modes.choose", "end") == "end.wav"
        assert len(w.asked) == n + 1 and w.asked[-1]["title"] == "Choose the sound"
        dest = proj / "modes" / "new_mode" / "end.wav"
        assert dest.read_bytes() == wavs[1].read_bytes()
        # cancelling a second choice keeps the sound it has
        w.answers.append("")
        assert w.call("modes.choose", "end") is None
        assert w.state("modes")["form"]["end_mode"] == "file"


def test_the_sdk_document_is_always_reachable(tmp_path, preview_on):
    """Tk's "Open MODE_SDK.md" was on the Try it row with or without a project."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        opened = []
        svc._opener = opened.append
        st = w.state("modes")
        assert st["project"] == "" and st["sdk_doc"].endswith("MODE_SDK.md")
        assert w.call("modes.open_sdk_doc") is True
        assert opened == [svc.sdk_doc()]
        # New code mode… with no project: Tk's sentence, nothing asked
        n = len(w.asked)
        assert w.call("modes.new_code_mode", "") is None
        assert len(w.asked) == n
        assert w.state("modes")["tryit_line"] == MP.NO_PROJECT_HELP


# ------------------------------------------------------------------ Try it, for real
class _R:
    returncode = 0
    stdout = "[tryit] ready"
    stderr = ""


def test_rig_commands_are_inert_and_never_run_without_the_rig(tmp_path, preview_on,
                                                              monkeypatch):
    """PAD_UI_NO_RIG (the harness, the captures): the tab's rig commands are the Emulate
    service's own inert argv (no wsl.exe asked for a distro) and none of them is spawned."""
    import subprocess
    from pinball_decryptor.webui import emulate_rig
    from pinball_decryptor.webui import modes_tryit
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        emu = w.window.service("emulate")
        if getattr(emu, "placeholder", None):
            pytest.skip("the Emulate tab is not ported yet")
        assert modes_tryit.no_rig()
        # the real service has no rig_cmd: the seam is the webui package's emulate_rig
        assert svc._rig_module() is emulate_rig

        def asked(*a, **k):
            raise AssertionError("rig_cmd was asked under PAD_UI_NO_RIG")
        monkeypatch.setattr(emulate_rig, "rig_cmd", asked)
        monkeypatch.setattr(emulate_rig, "rig_cmd_root", asked)
        assert svc.check_cmd() == emu._cmd("modes/tryit.sh", "check")
        assert svc.check_cmd(as_root=True) == emu._cmd_root("modes/tryit.sh", "check")
        assert svc.trigger_cmd(2) == emu._cmd("modes/tryit.sh", "start", "2")

        def spawned(*a, **k):
            raise AssertionError("a rig command was spawned under PAD_UI_NO_RIG")
        monkeypatch.setattr(subprocess, "Popen", spawned)
        monkeypatch.setattr(subprocess, "run", spawned)
        assert svc._run(svc.check_cmd()) == (False, modes_tryit.NO_RIG_TEXT)


@pytest.mark.parametrize("path", ["seam", "no_rig"])
def test_tryit_through_the_real_emulate_service(tmp_path, preview_on, monkeypatch, path):
    """The whole Try it with the REAL Emulate service: preflight, the Emulate tab forward,
    the rig check and install before watch.sh, progress on the Emulate tab, the run's env,
    starting -> live, Start mode now, the live push after an autosave, and run_ended back.
    Only the spawns are stood in (and the set build, which needs a card image).

    ``seam``: this tab's commands through ``webui/emulate_rig`` (the import the web port got
    wrong once), its builders stood in. ``no_rig``: the harness's PAD_UI_NO_RIG, where they
    are the Emulate service's inert argv."""
    import threading
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.webui import emulate_rig
    from pinball_decryptor.webui import modes_tryit

    events = []
    monkeypatch.setattr(emulate_rig, "rig_available", lambda: True)
    if path == "seam":
        monkeypatch.setattr(modes_tryit, "no_rig", lambda: False)
        monkeypatch.setattr(emulate_rig, "rig_cmd",
                            lambda script, *a, env=(): ["FAKE", script] + [str(x) for x in a])
        monkeypatch.setattr(emulate_rig, "rig_cmd_root",
                            lambda script, *a: ["FAKEROOT", script] + [str(x) for x in a])
    else:
        def asked(*a, **k):
            raise AssertionError("rig_cmd was asked under PAD_UI_NO_RIG")
        monkeypatch.setattr(emulate_rig, "rig_cmd", asked)
        monkeypatch.setattr(emulate_rig, "rig_cmd_root", asked)
    monkeypatch.setattr(MW, "preview_on", lambda: True)

    proj = tmp_path / "proj"
    card = tmp_path / "godzilla_pro-1_15_0.raw"
    card.write_bytes(b"\0" * 512)
    stage = tmp_path / "stage"
    stage.mkdir()
    built = {}

    def fake_build_set(project, card_path, base=None, ffmpeg=None, log=None, progress=None,
                       cancel=None, sound_ok=None):
        found, _broken = MP.list_modes(project)
        for i in range(1, 4):
            progress(i, 3, "building step %d" % i)
            built.setdefault("preparing", []).append((emu._preparing, emu._preparing_pct))
        built["card"] = card_path
        slots = [(i, slug, spec.name) for i, (slug, spec) in enumerate(found)]
        for i, _slug, _n in slots:
            (stage / ("mode%s.cfg" % ("" if i == 0 else i))).write_text("x", encoding="utf-8")
        return MT.TrySet(set_dir=str(tmp_path / "set"), stage_dir=str(stage),
                         game_dir="godzilla_pro", version="1.15", slots=slots,
                         specs=dict(found), files=["godzilla_pro/x.png"])
    monkeypatch.setattr(MT, "build_set", fake_build_set)

    released = threading.Event()

    class _Proc:
        returncode = None

        def __init__(self):
            def lines():
                yield b"[watch] started\n"
                released.wait(60)
            self.stdout = lines()

        def poll(self):
            return None if not released.is_set() else 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            released.set()

    def wait_for(w, cond, timeout=10.0):
        return _wait(w, cond, timeout)

    with web_app(tmp_path, mfr="stern") as w:
        modes = _svc(w)
        emu = w.window.service("emulate")
        if getattr(emu, "placeholder", None):
            pytest.skip("the Emulate tab is not ported yet")
        try:
            modes._platform = "win32"
            modes._run_fn = lambda cmd, **kw: (events.append(("run", list(cmd))), _R())[1]
            monkeypatch.setattr(emu, "_popen",
                                lambda cmd, **kw: (events.append(("popen", list(cmd))), _Proc())[1])
            monkeypatch.setattr(emu, "_run", lambda cmd, **kw: _R())
            _project(w, proj)
            w.run(lambda: emu.emulate_card_var.set(str(card)))
            w.call("ui.select_tab", "modes")
            w.call("modes.new")

            # preflight, then the hand-off: the Emulate tab comes forward
            assert w.call("modes.tryit") is True
            assert w.state("shell")["tab"] == "emulate"
            assert wait_for(w, lambda: any(k == "popen" for k, _c in events), 15), \
                w.state("modes")["tryit_line"]
            # the rig check first, then the install, THEN watch.sh
            assert [k for k, _c in events] == ["run", "run", "popen"], events
            runs = [c for k, c in events if k == "run"]
            assert "check" in runs[0] and "install" in runs[1], runs
            if path == "seam":
                assert runs[0] == ["FAKE", "modes/tryit.sh", "check"]
                assert runs[1][:3] == ["FAKE", "modes/tryit.sh", "install"]
            else:
                assert runs[0] == emu._cmd("modes/tryit.sh", "check")
            watch = " ".join(events[-1][1])
            assert "watch.sh" in watch
            assert "PAD_OVERRIDE_DIR=" in watch and "PAD_MODE_SO=" in watch
            assert built["card"] == str(card)
            # the progress reached the Emulate tab's State line as it built
            assert built["preparing"][-1] == ("building step 3", 100)
            assert wait_for(w, lambda: w.state("modes")["tryit"]["state"] == "starting", 5)
            assert w.state("modes")["tryit_line"].startswith("1 mode(s) ready (NEW MODE).")

            # the run comes up: live
            w.run(emu._apply, {"running": "1", "state": "attract", "procs": "5"})
            assert wait_for(w, lambda: w.state("modes")["tryit"]["state"] == "live", 5)
            assert wait_for(w, lambda: w.state("modes")["emu"]["up"] is True, 5)

            # Start mode now names the mode's slot
            cmd = w.run(modes.on_start_now)
            want = (["FAKE", "modes/tryit.sh", "start", "0"] if path == "seam"
                    else emu._cmd("modes/tryit.sh", "start", "0"))
            assert cmd == want
            assert wait_for(w, lambda: w.state("modes")["tryit_line"] ==
                            "asked the game to start NEW MODE. A game must be in play.", 5)

            # an edit while it runs reaches the game after its autosave
            before = len(events)
            w.call("ui.set", "modes", "f:seconds", "44")
            assert wait_for(w, lambda: any(k == "run" and "push" in c for k, c in events[before:]), 5)
            assert wait_for(w, lambda: w.state("modes")["tryit_line"] ==
                            "NEW MODE updated in the running game.", 5)

            # the run goes down: the Emulate service tells this tab, which says so
            w.run(emu._apply, {"running": "0", "state": "off", "procs": "0"})
            released.set()
            assert wait_for(w, lambda: w.state("modes")["tryit"]["state"] == "ended", 5)
            assert w.state("modes")["tryit_line"] == ("The run ended. Press Try it to run the "
                                                      "modes again.")
            assert w.run(modes.on_start_now) is None
        finally:
            released.set()


# ------------------------------------------------------------------ any Spike 2 card
# The PORTS and STOCK helpers behind title_reader are built beside this tab, so these tests
# stand in title_reader.read_card (the contract: progress(step, fraction, text), cancel(),
# a TitleRead back) and give it a port file and a stock table of their own.
BEATLES_CARD = "beatles-1_29_0.Release.8G.sdcard.raw"

BEATLES_PORT = """# The Beatles 1.29: a stand-in port for the tab's tests (no program behind it)
game           beatles
version        1.29

site tick             0x000c0210 0xe92d4038 0xe3a00037
site shot_dispatch    0x0003e314 0xe92d4ff0 0xe3045b18
site ball_end         0x0004b5e8 0xe92d40f8 0xe30e6c04
site score_add        0x0015ee3c 0xe3041d0e 0xe3401087

data cur_player             0x0054322c
data scores                 0x005b3578

shot 0x1               Left orbit
shot 0x2               Right orbit
shot 0x4               Penny Lane ramp
shot 0x8               Abbey Road ramp
shot 0x10              Center target
"""

BEATLES_TABLE = """
build beatles 1.29 sha1 00000000000000000000000000000000000000aa
mode 1 cmode_all_my_loving obj 0x0 vtable 0x0 title_msg ?
mode 2 cmode_drive_my_car obj 0x0 vtable 0x0 title_msg ?
number 2 timer.timer 30 adj AD_MODE_DRIVE_MY_CAR_TIMER 171 e3a000ab adjustment  # range 20..60, min..max default in ELF
number 2 timer.shots 2 adj AD_MODE_DRIVE_MY_CAR_SHOTS 172 e3a000ac adjustment  # range 2..8, min..max default in ELF
number 2 timer.bonus ? code 0x35354 - code  # worked out in code
mode 6 cmode_main_multiball obj 0x0 vtable 0x0 title_msg ?
number 6 timer.ball_save 30 adj AD_MAIN_MULTIBALL_BALL_SAVE_SECONDS 180 e3a000b4 adjustment  # range 0..60, min..max default in ELF
"""


def _derived_port(text, name="beatles-1.29"):
    """A port derived on this machine as port_derive.ensure_port leaves it: in the title
    cache's ports folder with a current sidecar, so every lookup lists it."""
    import json
    from pinball_decryptor.plugins.stern import port_derive as PD
    from pinball_decryptor.plugins.stern import portgen as G
    path = os.path.join(PD.user_ports_dir(), name + ".port")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    with open(path[:-len(".port")] + ".json", "w", encoding="utf-8") as f:
        json.dump(dict(key=dict(elf_sha1="aa" * 20, revision=G.REVISION, refs={}), ok=True), f)
    return path


class _FakeReader:
    """title_reader.read_card as the contract has it. ``gate`` holds the port step until
    set (so a test can look at the tab mid-read); ``fail`` raises that error instead."""

    def __init__(self, tmp_path, port=True, missing=(), fail=None, proven=False):
        import threading
        from pinball_decryptor.plugins.stern import stock_modes as SM
        self.gate = threading.Event()
        self.calls = []
        self.fail = fail
        self.missing = tuple(missing)
        self.proven = proven
        self.port = ""
        self.want_port = bool(port)
        self.build = SM.parse(BEATLES_TABLE)[0]

    def __call__(self, card, progress=None, cancel=None):
        from pinball_decryptor.plugins.stern import title_reader as TR
        self.calls.append(card)
        progress("program", 0.0, TR.STEP_WORDS["program"])
        progress("program", 1.0, TR.STEP_WORDS["program"])
        progress("port", 0.0, TR.STEP_WORDS["port"])
        progress("port", 0.5, "Placing the ball end")
        while not self.gate.wait(0.02):
            if cancel is not None and cancel():
                raise TR.Cancelled()
        if self.fail:
            raise TR.TitleReadError(self.fail)
        if self.want_port and not self.port:
            # where ensure_port puts a port it derives, with the sidecar that keeps it current
            self.port = _derived_port(BEATLES_PORT)
        progress("port", 1.0, "")
        progress("stock", 0.0, TR.STEP_WORDS["stock"])
        progress("stock", 1.0, "")
        return TR.TitleRead(
            game="beatles", version="1.29.0", elf_sha1="aa" * 20, family="c",
            port_path=self.port, port_origin="derived" if self.port else "",
            port_proven=self.proven, port_missing=() if self.port else self.missing,
            stock_build=self.build, stock_origin="generated",
            notes=("Read by the stand-in reader.",), seconds=1.5)


@pytest.fixture
def beatles(monkeypatch, tmp_path):
    """A Beatles-like card project whose image is on disk (so the tab reads it), the stand-in
    reader, and no SHIPPED port for Beatles (one may come later): only the port the read
    finds, as every lookup (the tab, Write, Try it) resolves it."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import title_reader as TR
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path / "titles"))
    real = MP._folder_profiles

    def folder_profiles(d):
        out = real(d)
        if os.path.abspath(d) == os.path.abspath(MP.PORTS_DIR):
            # the SHIPPED Beatles port is hidden; one derived on this machine stays
            out = {k: p for k, p in out.items() if p.game_dir != "beatles"}
        return out
    monkeypatch.setattr(MP, "_folder_profiles", folder_profiles)
    proj = tmp_path / "beatles"
    _card_project(proj, BEATLES_CARD)
    with open(os.path.join(str(proj), BEATLES_CARD), "wb") as f:
        f.write(b"\0" * 4096)

    def make(**kw):
        fake = _FakeReader(tmp_path, **kw)
        monkeypatch.setattr(TR, "read_card", fake)
        return fake
    return proj, make


def _reading(w):
    return w.state("modes")["reading"]


def test_reading_can_be_cancelled_and_read_again(tmp_path, preview_on, beatles):
    proj, make = beatles
    fake = make()
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj, card=None)
        assert _wait(w, lambda: _reading(w).get("state") == "reading")
        assert w.call("modes.read_cancel") is True
        assert _reading(w)["text"] == "Stopping at the next step…"
        assert _wait(w, lambda: _reading(w)["state"] == "cancelled")
        st = w.state("modes")
        assert "was stopped" in st["no_port"] and "Read again" in st["no_port"]
        assert st["new_ok"] is False
        # a refresh does not start it again by itself
        w.run(_svc(w)._refresh_all)
        w.drain()
        assert len(fake.calls) == 1 and _reading(w)["state"] == "cancelled"
        fake.gate.set()
        assert w.call("modes.read_again") is True
        assert _wait(w, lambda: _reading(w)["state"] == "done")
        assert len(fake.calls) == 2
        assert w.state("modes")["new_ok"] is True


def test_a_card_that_cannot_be_read_says_why(tmp_path, preview_on, beatles):
    proj, make = beatles
    fake = make(fail="The game program could not be read from the card: bad superblock")
    fake.gate.set()
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj, card=None)
        assert _wait(w, lambda: _reading(w).get("state") == "failed")
        r = _reading(w)
        assert r["error"].endswith("bad superblock")
        assert [x["state"] for x in r["steps"]] == ["done", "failed", "todo"]
        st = w.state("modes")
        assert st["no_port"].startswith("The card could not be read, so modes cannot be made "
                                        "for it: ")
        assert st["new_ok"] is False


def test_no_port_says_why_and_the_server_refuses(tmp_path, preview_on, beatles):
    """A build the app could not make a port for: the words say what is missing, and New,
    an example, a code mode and Try it are refused on the server as well as greyed."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    proj, make = beatles
    fake = make(port=False, missing=("shot_dispatch", "score_add"))
    fake.gate.set()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        svc._platform = "win32"
        _project(w, proj, card=None)
        assert _wait(w, lambda: _reading(w).get("state") == "done")
        st = w.state("modes")
        assert st["no_port"].startswith("Modes of your own can't be made for The Beatles 1.29 "
                                        "yet: the app could not find where the game hands out "
                                        "its shots and how the game adds points in its program")
        # the banner says what still works, and the SDK pointer is a tooltip
        assert st["title_note"] == st["no_port"] + " " + MP.NO_PORT_STILL
        assert st["no_port_details"] == MP.NO_PORT_DETAILS
        assert st["new_ok"] is False and st["ex_ok"] is False and st["examples"] == []
        assert st["shots_text"] == "(no shots: modes of your own can't be made for this card yet)"
        # the game's own modes do not need a port: they are listed and can be changed
        assert [r["name"] for r in st["game_rows"]][:2] == ["Drive My Car", "Main Multiball"]
        n = len(w.asked)
        assert w.call("modes.new") is None
        assert w.asked[n]["title"] == "New mode" and "hands out its shots" in w.asked[n]["message"]
        assert w.call("modes.example", "TARGET RUSH") is None
        assert w.call("modes.new_code_mode", "Laser") is None
        assert w.state("modes")["tryit_line"].startswith("Modes of your own can't be made for "
                                                         "The Beatles")
        assert _modes_on_disk(proj) == [] and not os.path.isdir(proj / "modes" / "laser")
        # a mode already in the folder: Try it says why at once, before the Emulate tab or
        # the rig is asked anything
        MP.new_mode(str(proj), "OLD", MP.blank_spec(MP.GODZILLA_PRO_1_15))
        emu = _FakeEmulate()
        _with_emu(w, emu)
        assert w.call("modes.tryit") is False
        assert emu.handed == []
        st = w.state("modes")
        assert st["tryit"]["state"] == "failed"
        assert st["tryit_line"].startswith("Modes of your own can't be made for The Beatles "
                                           "1.29 yet")


def test_tryit_checks_the_port_before_the_rig(tmp_path, preview_on):
    """The Emulate tab's worker: a project whose card has no port is refused before the rig
    check runs (it used to spend up to two minutes on the rig first)."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    proj = _card_project(tmp_path / "mando", "mando_le-1_40_0.raw")
    MP.new_mode(str(proj), "OLD", MP.blank_spec(MP.GODZILLA_PRO_1_15))
    card = tmp_path / "mando_le-1_40_0.raw"
    card.write_bytes(b"\0" * 64)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, proj, card=None)
        ran = []
        svc._run_fn = lambda cmd, **k: ran.append(cmd)
        _with_emu(w, _FakeEmulate())
        svc._tryit_project = str(proj)
        assert svc.tryit_prepare(str(card)) is None
        assert ran == []
        assert svc.tryit_prepare.last_reason.startswith("Modes of your own can't be made for "
                                                        "The Mandalorian")


def test_the_games_own_mode_has_a_page(tmp_path, preview_on, beatles):
    from pinball_decryptor.core import staged_changes
    proj, make = beatles
    make().gate.set()
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj, card=None)
        assert _wait(w, lambda: _reading(w).get("state") == "done")
        assert w.call("modes.select", "2", "game") is True
        st = w.state("modes")
        assert st["sel"] == {"slug": "2", "kind": "game"}
        g = st["game_mode"]
        assert g["name"] == "Drive My Car" and g["build"] == "The Beatles 1.29"
        assert not st["open"] and st["code"] is None
        timer = next(r for r in g["rows"] if r["key"] == "2.timer.timer")
        assert timer["stock"] == "30" and timer["current"] == "30" and not timer["readonly"]
        assert timer["hint"].startswith("An operator setting (AD_MODE_DRIVE_MY_CAR_TIMER), "
                                        "20 to 60")
        # the visible line in plain words; the setting's name and the address in the tooltip
        assert timer["where"] == "Operator setting, 20 to 60 (also on the Defaults tab)"
        code = next(r for r in g["rows"] if r["key"] == "2.timer.bonus")
        assert code["readonly"] and code["why"] == ("The game works this out as it plays, so it "
                                                    "cannot be changed here.")
        assert "0x35354" in code["hint"] and "0x" not in code["where"]
        # Set: staged for the next Write, as the Defaults tab stages a setting
        text = w.call("modes.game_set", "2.timer.timer", "45")
        assert "30 -> 45 staged for the next Write" in text
        assert staged_changes.load(str(proj))["settings"]["AD_MODE_DRIVE_MY_CAR_TIMER"] == 45
        st = w.state("modes")
        timer = next(r for r in st["game_mode"]["rows"] if r["key"] == "2.timer.timer")
        assert timer["changed"] and timer["current"] == "45"
        assert st["game_mode"]["note"] == text
        assert next(r for r in st["game_rows"] if r["slug"] == "2")["chip"] == "1 changed"
        # out of the game's range: refused with its words, nothing more staged
        assert w.call("modes.game_set", "2.timer.timer", "600")
        assert staged_changes.load(str(proj))["settings"]["AD_MODE_DRIVE_MY_CAR_TIMER"] == 45
        # Stock: back to the game's own
        assert "back to the game's own 30" in w.call("modes.game_stock", "2.timer.timer")
        assert "AD_MODE_DRIVE_MY_CAR_TIMER" not in (
            staged_changes.load(str(proj)).get("settings") or {})
        # a read-only row cannot be set
        assert w.call("modes.game_stock", "2.timer.bonus") == ""
        # the dialog still lists every number
        w.call("modes.stock_refresh")
        assert len(w.state("modes")["stock"]["rows"]) == 4
        # a mode of the person's own leaves the page
        slug = w.call("modes.new")
        st = w.state("modes")
        assert st["game_mode"] is None and st["sel"] == {"slug": slug, "kind": "form"}
        w.call("modes.select", "6", "game")
        assert w.state("modes")["game_mode"]["name"] == "Main Multiball"
        w.call("modes.select", slug, "form")
        assert w.state("modes")["game_mode"] is None and w.state("modes")["open"]


def test_godzilla_uses_its_shipped_port_while_the_card_is_read(tmp_path, preview_on,
                                                               monkeypatch):
    """The Godzilla path is unchanged: its port is shipped, so the form is live at once,
    and the read that runs beside it only adds the game's own modes."""
    import threading
    from pinball_decryptor.plugins.stern import mode_runtime as MR
    from pinball_decryptor.plugins.stern import title_reader as TR
    gate = threading.Event()

    def read_card(card, progress=None, cancel=None):
        progress("program", 1.0, "")
        gate.wait(120)          # held until the test has looked (a slow runner starts late)
        return TR.TitleRead(game="godzilla_pro", version="1.15.0",
                            port_path=MR.port_file("godzilla_pro", "1.15"),
                            port_origin="shipped", port_proven=True)
    monkeypatch.setattr(TR, "read_card", read_card)
    proj = _card_project(tmp_path / "gz", "godzilla_pro-1_15_0.raw")
    (proj / "godzilla_pro-1_15_0.raw").write_bytes(b"\0" * 64)
    with web_app(tmp_path, mfr="stern") as w:
      try:
        _project(w, proj, card=None)
        st = w.state("modes")
        assert _reading(w)["state"] == "reading"
        assert st["profile"]["key"] == "godzilla_pro_1_15" and st["new_ok"] and not st["no_port"]
        names = [e["name"] for e in st["examples"] if not e["code"]]
        assert names[:4] == ["KAIJU RUSH", "ATOMIC BREATH", "MOTHRA'S SONG", "MECHAGODZILLA"]
        assert any(e["code"] for e in st["examples"])
        assert w.call("modes.new") == "new_mode"
        gate.set()
        assert _wait(w, lambda: _reading(w)["state"] == "done")
        st = w.state("modes")
        assert st["profile"]["key"] == "godzilla_pro_1_15" and st["title_origin"] == "shipped"
        assert st["title_note"] == "" and st["open"] and st["editor_on"]
      finally:
        gate.set()


def test_a_project_with_no_card_knows_no_game(tmp_path, preview_on):
    from pinball_decryptor.plugins.stern import mode_project as MP
    proj = tmp_path / "bare"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj, card=None)
        st = w.state("modes")
        # said once, in the note: the head keeps only the counts
        assert st["title_text"] == "" and st["title_note"] == MP.NO_CARD_HELP and st["no_card"]
        assert st["new_ok"] is False and st["examples"] == [] and st["profile"]["shots"] == []
        assert st["shots_text"] == "(no shots: this project names no card)"
        assert w.call("modes.new") is None and _modes_on_disk(proj) == []
        # the "Try it on" card names a game: the modes are for it
        emu = w.window.service("emulate")
        w.run(lambda: emu.emulate_card_var.set(str(tmp_path / "godzilla_le-1_16_0.raw")))
        w.drain()                          # the card box's trace re-reads the title
        st = w.state("modes")
        assert st["profile"]["label"] == "Godzilla Premium/LE 1.16" and st["new_ok"]
        assert st["title_via"] == "try_on"
        assert "\"Try it on\" card" in st["title_text"]
        # a code mode made here records that game, so Try it and Write build it for it
        # (the project names no card for them to read it from)
        from pinball_decryptor.plugins.stern import code_modes as CM
        from pinball_decryptor.plugins.stern import mode_write as MW
        svc = _svc(w)
        svc._opener = lambda path: None
        assert w.call("modes.new_code_mode", "Blitz")
        code = CM.list_code(str(proj))
        assert [(s, c.extra.get("title")) for s, c in code] == [("blitz", "godzilla_le_1_16")]
        assert CM.profile_for(str(proj), code).key == "godzilla_le_1_16"
        assert not any(CM.NO_TITLE in ln for ln in MW.pending_lines(str(proj)))


def test_a_port_worked_out_earlier_shows_unproven_before_the_read(tmp_path, preview_on,
                                                                   beatles):
    """A port derived on this machine in an earlier session is used at once, while the card
    is read again, and it says it is unproven whatever its header says."""
    from pinball_decryptor.plugins.stern import port_derive
    proj, make = beatles
    fake = make()
    _derived_port(BEATLES_PORT.replace("# The Beatles 1.29:", "# DRAFTED by port_tool.py:"))
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj, card=None)
        assert _wait(w, lambda: _reading(w).get("state") == "reading")
        st = w.state("modes")
        assert st["profile"]["label"] == "The Beatles 1.29" and st["new_ok"]
        assert st["title_origin"] == "derived"
        assert st["title_note"].startswith("Check this game (or press Try it) once first: the app worked out by "
                                           "itself how to run modes on The Beatles 1.29")
        assert st["write_waits"] is True
        fake.gate.set()
        assert _wait(w, lambda: _reading(w)["state"] == "done")


def test_the_title_note_carries_the_ports_switch_line_words():
    from types import SimpleNamespace
    from pinball_decryptor.webui.tabs.modes import ModesTab as ModesService
    p = SimpleNamespace(switch_shots_note="Its shots from switches are desk-only.")
    assert ModesService._with_switch_note("", p) == \
        "Unproven: Its shots from switches are desk-only."
    assert ModesService._with_switch_note("Unproven: x.", p) == \
        "Unproven: x. Its shots from switches are desk-only."
    assert ModesService._with_switch_note("n", SimpleNamespace()) == "n"


# ---- review fixes: what a title cannot do is greyed with the reason, in plain words -----------
def test_own_sounds_grey_where_no_carriers_were_measured(tmp_path, preview_on):
    """Review M1: on a title with no measured carriers (TMNT Pro 1.58, not the latest build) the
    start sound, shot sound and music are greyed with a plain reason, refused on the server, and
    the Try it words drop the "about a minute" sentence; on Godzilla Premium/LE 1.16 (measured)
    they stay live. Item 163: Jaws carries them now, and The Beatles greys only the music (no
    stock tune to carry it)."""
    proj = _card_project(tmp_path / "tmnt", "turtles_pro-1_58_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new")
        st = w.state("modes")
        assert st["dis"]["own_extra"] and st["own_extra_ok"] is False
        why = st["reasons"]["own_extra"]
        assert why.startswith("Not on this game yet: ") and "TMNT Pro 1.58" in why
        assert "port" not in why
        asked = len(w.asked)
        assert w.call("modes.choose", "sound_start") is None       # the server refuses too
        assert len(w.asked) == asked                                # no file dialog was opened
    proj = _card_project(tmp_path / "jaws", "jaws_le-1_02_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new")
        st = w.state("modes")
        assert not st["dis"]["own_extra"] and st["own_extra_ok"] is True
        # item 164: Jaws's inserts are proven and 26 of them are tied to its shots
        assert not st["dis"]["lit_shots"]
    proj = _card_project(tmp_path / "beatles", "beatles-1_29_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new")
        st = w.state("modes")
        assert not st["dis"]["own_extra"] and st["dis"]["own_music"]
        assert "stock tune" in st["reasons"]["own_music"] and "Beatles" in st["reasons"]["own_music"]
        asked = len(w.asked)
        assert w.call("modes.choose", "music") is None             # the server refuses the music
        assert len(w.asked) == asked
    gz = _card_project(tmp_path / "gz", "godzilla_le-1_16_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, gz)
        w.call("modes.new")
        st = w.state("modes")
        assert not st["dis"]["own_extra"] and st["own_extra_ok"] is True
        assert "own_extra" not in st["reasons"] and not st["dis"]["lit_shots"]
        assert not st["dis"]["show_order"]


def test_the_show_page_is_one_sentence_where_nothing_on_it_works(tmp_path, preview_on):
    """Review: on a title that can show neither a screen nor a clip (TMNT Pro 1.58; 1.59 plays a
    clip since item 164), the Show page collapses to one sentence and "stays up" / "priority"
    grey with it."""
    proj = _card_project(tmp_path / "tmnt", "turtles_pro-1_58_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new")
        st = w.state("modes")
        assert st["dis"]["screen"] and st["dis"]["clip"] and st["dis"]["show_order"]
        assert st["reasons"]["show_all"].startswith("Not on this game yet: a mode cannot show a "
                                                    "screen or a clip of its own on TMNT Pro 1.58")
        assert "TMNT Pro 1.58 cannot show either" in st["reasons"]["show_order"]


def test_a_live_try_it_records_a_derived_ports_first_run(tmp_path, preview_on):
    """Review M6: once live, Try it asks the rig whether the runtime hooked the game (tryit.sh
    armed); its "armed:" line records the derived port's live run, so Write carries the modes
    from then on. "NOT THIS GAME'S PORT" records nothing and says so."""
    import subprocess
    from pinball_decryptor.plugins.stern import port_derive as PD
    path = _derived_port(BEATLES_PORT)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _with_emu(w, _FakeEmulate())
        assert svc.armed_cmd()[-2:] == ["modes/tryit.sh", "armed"]
        out = ["[tryit] NOT THIS GAME'S PORT - the core functions do not match (1 site(s) wrong)."]
        svc._run_fn = lambda cmd, **k: subprocess.CompletedProcess(cmd, 3, out[0], "")
        svc._tryit_live = {"record_port": path, "project": ""}
        svc._armed_tries = 0
        svc._tryit_check_armed().join(5)
        w.drain()
        assert not PD.ran_live(path) and svc._tryit_live["record_port"] == ""
        assert "the game did not take the modes" in w.state("modes")["tryit_line"]
        out[0] = "[tryit] 12 [mode] armed: 1 mode(s); can callout lights"
        svc._run_fn = lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, out[0], "")
        svc._tryit_live = {"record_port": path, "project": ""}
        svc._tryit_check_armed().join(5)
        w.drain()
        assert PD.ran_live(path) and svc._tryit_live["record_port"] == ""
        assert svc._tryit_check_armed() is None                    # nothing left to ask
    # the rig script has the verb, reading only this run's mode.log
    rig = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tools", "spike2_emu", "modes", "tryit.sh")
    body = open(rig, encoding="utf-8").read()
    assert "    armed)" in body and '"$DUMP/mode.log"' in body


def test_the_game_mode_page_reads_like_the_defaults_tab(tmp_path, preview_on, beatles,
                                                        monkeypatch):
    """Review: a setting's label is its operator-menu caption (the Defaults tab's words, from
    the read), the visible line says where it lives in plain words, and the list puts the
    person's own modes first."""
    proj, make = beatles
    fake = make()
    fake.gate.set()
    from pinball_decryptor.plugins.stern import title_reader as TR
    real_call = fake.__call__

    def with_captions(card, progress=None, cancel=None):
        tr = real_call(card, progress=progress, cancel=cancel)
        tr.captions = {"AD_MODE_DRIVE_MY_CAR_TIMER": "DRIVE MY CAR TIME"}
        return tr
    monkeypatch.setattr(TR, "read_card", with_captions)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj, card=None)
        assert _wait(w, lambda: _reading(w).get("state") == "done")
        w.call("modes.select", "2", "game")
        g = w.state("modes")["game_mode"]
        timer = next(r for r in g["rows"] if r["key"] == "2.timer.timer")
        assert timer["number"] == "Time"                 # "Drive My Car Time" under Drive My Car
        assert "DRIVE MY CAR TIME" in timer["hint"] and "AD_MODE_DRIVE_MY_CAR_TIMER" in timer["hint"]
        assert g["build"] == "The Beatles 1.29"
