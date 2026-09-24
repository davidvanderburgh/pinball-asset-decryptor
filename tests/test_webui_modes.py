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


def _project(w, path):
    """Point the project folder (Write's assets folder, else the Extract output) at *path*."""
    os.makedirs(str(path), exist_ok=True)
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
def test_new_mode_edit_autosave_and_validation(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        assert st["project_label"] == "Saved in %s" % os.path.join(str(proj), "modes")
        assert st["title_text"] == ("This project names no card, so its modes are made for "
                                    "Godzilla Pro 1.15.")
        assert st["status"].startswith("No modes yet. Press New for a blank mode")
        assert st["new_ok"] and st["ex_ok"]
        assert st["cap_text"] == "0 of 8 modes"

        slug = w.call("modes.new")
        assert slug == "new_mode"
        st = w.state("modes")
        assert st["rows"][0]["name"] == "NEW MODE" and st["rows"][0]["kind"] == "form"
        assert st["sel"] == {"slug": "new_mode", "kind": "form"}
        assert st["form"]["name"] == "NEW MODE"
        assert st["form"]["start_shot"] == "Maser target"
        assert st["shots_on"] == ["Left ramp", "Right ramp"]
        assert st["status"] == "Ready to build."
        assert st["editor_on"] and st["dup_ok"] and st["del_ok"]
        assert st["starts_words"] == "Can start: any number of times"
        assert st["preview"] and os.path.isfile(st["preview"]["path"])
        assert st["cap_text"] == "1 of 8 modes"

        # an edit autosaves half a second later, to the project's mode.json
        w.call("ui.set", "modes", "f:name", "ATOMIC TEST")
        assert w.state("modes")["save_state"] == "editing"
        path = proj / "modes" / "new_mode" / "mode.json"
        assert _wait(w, lambda: json.loads(path.read_text("utf-8"))["name"] == "ATOMIC TEST")
        # the list catches up on the loop after the save (a fast runner
        # reads the state between the two)
        assert _wait(w, lambda: w.state("modes")["rows"][0]["name"]
                     == "ATOMIC TEST")
        st = w.state("modes")
        assert st["save_state"] == "saved"

        # untick both shots: the status says what to fix
        w.call("ui.set", "modes", "shot:Left ramp", False)
        w.call("ui.set", "modes", "shot:Right ramp", False)
        assert _wait(w, lambda: w.state("modes")["status"].startswith("To fix"))
        assert "Pick at least one shot that scores while it runs." in w.state("modes")["status"]
        # the list names the editor page that holds it (the design's "Show •"), and that
        # page's tab carries a dot; the list catches up on the loop after the status (the
        # macOS CI leg read the row between the two)
        assert _wait(w, lambda: w.state("modes")["rows"][0]["chip"] == "Mode •"), \
            w.state("modes")["rows"][0]["chip"]
        st = w.state("modes")
        assert st["rows"][0]["chip"] == "Mode •"
        assert st["rows"][0]["chip_tip"] == st["status"]
        assert st["fix_pages"] == ["mode"] and st["ready"] is False
        w.call("modes.set_shots", ["Building", "Big loop"])
        assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
        st = w.state("modes")
        assert st["ready"] is True and st["fix_pages"] == [] and st["rows"][0]["chip"] == "ready"
        data = json.loads(path.read_text("utf-8"))
        assert data["scoring_shots"] == ["Building", "Big loop"]

        # the starts words follow the form at once (no save needed)
        w.call("ui.set", "modes", "f:starts_policy", "count")
        w.call("ui.set", "modes", "f:starts_count", "2")
        w.call("ui.set", "modes", "f:cooldown", "30")
        assert w.state("modes")["starts_words"] == (
            "Can start: up to 2 times a game, for each player; not again until 30 s after it ends")

        # advanced: per-shot points, early end, callouts, second clip, restore
        w.call("ui.set", "modes", "award:Building", "2,000,000")
        w.call("ui.set", "modes", "f:end_shot", "Big loop")
        w.call("ui.set", "modes", "f:callout_secs_0", "10")
        w.call("ui.set", "modes", "f:callout_id_0", "1291")
        w.call("ui.set", "modes", "f:clip_both", "same")
        w.call("ui.set", "modes", "f:award_ladder", "fixed")
        w.call("ui.set", "modes", "f:starts_kind", "event")
        w.call("ui.set", "modes", "f:start_event", "a ball starts")
        w.call("ui.set", "modes", "f:ends_kind", "event")
        w.call("ui.set", "modes", "f:end_event", "a multiball starts")
        w.call("ui.set", "modes", "f:light_shots_on", True)
        w.call("ui.set", "modes", "f:light_shots_pattern", "Chase")
        w.call("ui.set", "modes", "f:priority", "180")

        def saved():
            try:
                d = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                # Windows refuses a read while the autosave swaps the file in
                return False
            return d.get("award_ladder") == "fixed" and d.get("priority") == 180
        assert _wait(w, saved)
        d = json.loads(path.read_text("utf-8"))
        assert d["shot_award"] == [["Building", 2000000]]
        assert d["end_shot"] == "Big loop"
        assert d["callout_at"] == [[10, 1291]]
        assert d["clip_both"] == {"clip": "same"}
        assert d["starts"] == 2 and d["cooldown"] == 30
        assert d["starts_on"] == "event ball_start" or d["starts_on"].startswith("event ")
        assert d["ends_on"].startswith("event ")
        assert d["light_shots"] == "#ff6000" and d["light_shots_pattern"] == "chase"

        # reopening reads it all back into the form
        w.call("modes.new")
        w.call("modes.select", "new_mode", "form")
        f = w.state("modes")["form"]
        assert f["end_shot"] == "Big loop" and f["award_ladder"] == "fixed"
        assert f["callout_secs_0"] == "10" and f["callout_id_0"] == "1291"
        assert f["starts_policy"] == "count" and f["starts_count"] == "2"
        assert f["starts_kind"] == "event" and f["start_event"] == "a ball starts"
        assert w.state("modes")["awards"]["Building"] == "2000000"


def test_examples_duplicate_delete_and_the_cap(tmp_path, preview_on):
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
        for _i in range(7):
            w.call("modes.new")
        st = w.state("modes")
        assert len(_modes_on_disk(proj)) == 8
        assert st["new_ok"] is False
        assert st["cap_text"].startswith("8 of 8 modes: delete one to add another.")
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
        assert st["cap_text"] == "0 of 8 modes"          # a code mode takes no slot
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
        _project(w, proj)
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
        assert w.state("modes")["labels"]["film"] == "Nothing cut from a film yet."


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
        assert "Modes run on its port, jaws_le-1.02.port, with its 27 shots." in st["title_text"]
        assert st["profile"]["label"] == "Jaws LE 1.02"
        assert len(st["profile"]["shots"]) == 27 and st["profile"]["cols"] == 3
        names = [e["name"] for e in st["examples"]]
        assert names == ["TARGET RUSH"]                   # not Godzilla's four, no code examples
        w.call("modes.new")
        st = w.state("modes")
        assert st["status"] == "Ready to build."
        for part in ("screen", "lights", "stack", "events"):
            assert st["dis"][part], part
            assert st["reasons"][part].startswith("Not on this game: "), part
        assert st["reasons"]["sound_unheard"].startswith("Not heard yet: ")
        assert not st["dis"]["clip"]


def test_an_unproven_port_says_so(tmp_path, preview_on):
    proj = _card_project(tmp_path / "dp", "deadpool_le-1_14_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        assert st["title_note"].startswith("Unproven: ")
        assert st["new_ok"] and st["ex_ok"]


def test_tmnt_shots_and_greying(tmp_path, preview_on):
    proj = _card_project(tmp_path / "tmnt", "turtles_pro-1_59_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new")
        st = w.state("modes")
        assert st["profile"]["label"] == "TMNT Pro 1.59" and len(st["profile"]["shots"]) == 17
        assert st["dis"]["countdown"] and st["dis"]["own_sound"]
        assert st["reasons"]["sound"].startswith("Not on this game: ")
        assert st["dis"]["film_clip"] and st["dis"]["film_still"] and st["dis"]["film_sound"]
        assert st["reasons"]["film"].startswith("Not on this game: cutting a clip, a picture for "
                                                "the screen or a sound from a film, because")


def test_a_card_with_no_port_is_read_only(tmp_path, preview_on):
    proj = _card_project(tmp_path / "mando", "mando_le-1_10_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        assert st["no_port"].startswith("There is no port for ")
        assert st["title_note"] == st["no_port"]
        assert st["new_ok"] is False and st["ex_ok"] is False
        assert st["status"] == "Modes cannot be built for this card yet: it has no port (see above)."
        assert st["shots_text"] == "(no shots: this card's game has no port)"
        assert st["profile"]["shots"] == []


def test_a_mode_opened_on_another_titles_card_is_not_rewritten(tmp_path, preview_on):
    proj = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.example", "KAIJU RUSH")
        path = proj / "modes" / "kaiju_rush" / "mode.json"
        before = path.read_text("utf-8")
    _card_project(proj, "jaws_le-1_02_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        assert st["form"]["name"] == "KAIJU RUSH"
        assert "is not a shot on Jaws LE 1.02" in st["status"] or \
            "not on Jaws LE 1.02" in st["status"]
        assert st["status"].rstrip().endswith("Until then its file is unchanged, and a build "
                                              "refuses it.")
        # not buildable until an edit saves it: neither the list nor the editor says ready
        assert st["ready"] is False and st["rows"][0]["chip"] == "to fix"
        # a blur that re-sends a field unchanged is not an edit: nothing is written
        w.call("ui.set", "modes", "f:name", "KAIJU RUSH")
        assert w.state("modes")["save_state"] == "saved"
        time.sleep(0.8)
        w.drain()
        assert path.read_text("utf-8") == before
        # an edit is: the file now has the card's shots
        w.call("ui.set", "modes", "f:seconds", "31")
        assert _wait(w, lambda: '"jaws_le_1_02"' in path.read_text("utf-8"))
        assert w.state("modes")["status"].rstrip().endswith("Its file now has this card's shots.")
        st = w.state("modes")
        assert st["ready"] == st["status"].startswith("Ready to build.")
        if st["ready"]:
            assert st["rows"][0]["chip"] == "ready"


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
        assert st["msg"].startswith("godzilla_le 1.16: ")
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
