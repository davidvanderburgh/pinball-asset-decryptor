"""PAD-367 - the Emulate tab refuses a Stern Spike 3 card up front.

Merlin1896 picked a walking_dead_remastered_le ...sdcard-secure card and the
tab copied 62 GB to the cache before failing to mount it (Spike 3 is a LUKS-
encrypted, CM4-fused layout PAD cannot read). These cover the GUI half of the
fix: a pick-time probe (webui/emulate_core.spike3_cmd / parse_spike3) tells the
tab, it says so in the log, and Start refuses before the rig is claimed or a
byte is copied. The rig half (parts.py --spike3, cardmount.sh, watch.sh) is in
tests/test_spike2_spike3_detect.py.
"""

import os
import sys

import pytest

from pinball_decryptor.webui import emulate_core, emulate_rig
from pinball_decryptor.webui.tabs import emulate as emulate_tab
from tests.test_webui_emulate import _Done, _lines, _patch, _svc, _wait
from tests.webui_harness import web_app

NS = "emulate"


@pytest.fixture(autouse=True)
def rig_on(monkeypatch):
    """conftest points PAD_EMU_DIR at an empty folder (no rig); these want the
    tab as it is on a machine that has one."""
    monkeypatch.setattr(emulate_rig, "rig_available", lambda: True)


# ---------------------------------------------------------------------------
# parse_spike3 - the one line cardmount/watch and the tab all read
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expect", [
    ("spike3: yes - partitions p2, p3 are LUKS-encrypted", (True, "partitions p2, p3 are LUKS-encrypted")),
    ("spike3: no", (False, "")),
    ("spike3: no - no such image: x", (False, "no such image: x")),
    ("your screen size is bogus\nspike3: yes - the boot partition is labelled SPIKE3",
     (True, "the boot partition is labelled SPIKE3")),
    ("nothing to see", (None, "")),
    ("", (None, "")),
])
def test_parse_spike3(text, expect):
    assert emulate_core.parse_spike3(text) == expect


def test_spike3_cmd_runs_parts_py_on_this_platform():
    cmd = emulate_rig.spike3_cmd("/some/card.raw")
    if cmd is None:                       # macOS: the container cannot be asked
        import sys
        assert sys.platform == "darwin"
    else:
        assert "parts.py" in " ".join(cmd) and "--spike3" in cmd


# ---------------------------------------------------------------------------
# the tab
# ---------------------------------------------------------------------------

def test_a_confirmed_spike3_card_is_refused_before_any_copy(tmp_path, monkeypatch):
    card = tmp_path / "walking_dead_remastered_le-0_93_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        # the pick-time probe has confirmed it (simulated here; the probe
        # itself is exercised below)
        w.run(lambda: svc._spike3_apply(str(card), True,
                                        "partitions p2, p3, p5, p6 are LUKS-encrypted"))
        w.call(NS + ".toggle")
        w.drain()
        assert "Spike 3 card" in svc.last_refusal
        assert "cannot be emulated" in svc.last_refusal
        # nothing was launched - watch.sh never ran, so nothing was copied
        assert not any("watch.sh" in " ".join(c) for c in rec.calls)
        assert svc._proc is None and not svc._starting


def test_the_pick_logs_the_spike3_notice(tmp_path, monkeypatch):
    monkeypatch.setattr(emulate_rig, "spike3_rig_present", lambda: False)
    card = tmp_path / "wdr-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        # picking the card sets _spike3_probed, which _spike3_apply checks
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        w.run(lambda: svc._spike3_apply(str(card), True,
                                        "the boot partition is labelled SPIKE3"))
        w.drain()
        log = _lines(w)
        assert any("is a Stern Spike 3 card" in ln for ln in log)
        assert any("SPIKE3" in ln for ln in log)


def test_a_non_spike3_card_is_not_refused_for_that_reason(tmp_path, monkeypatch):
    card = tmp_path / "godzilla_le-1_16_0.Release.8G.sdcard.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        w.run(lambda: svc._spike3_apply(str(card), False, ""))
        w.call(NS + ".toggle")
        _wait(w, lambda: any("watch.sh" in " ".join(c) for c in rec.calls))
        _wait(w, lambda: svc._proc is None and not svc._starting)
        assert "Spike 3" not in (svc.last_refusal or "")


@pytest.mark.skipif(sys.platform == "darwin",
                    reason="macOS never asks (spike3_cmd is None: the container cannot open "
                           "the card's host path); the rig's own refusal speaks there")
def test_the_probe_asks_parts_py_and_records_the_verdict(tmp_path, monkeypatch):
    card = tmp_path / "wdr-secure.raw"
    card.write_bytes(b"\0" * 512)
    # the probe's guard skips it under PAD_UI_NO_RIG (what web_app sets) and
    # when rig_dir() holds no parts.py (conftest points it at an empty dir);
    # here we let it run and answer the --spike3 call from the recorder.
    monkeypatch.setattr(emulate_tab, "no_rig", lambda: False)
    (tmp_path / "parts.py").write_text("")
    monkeypatch.setattr(emulate_rig, "rig_dir", lambda: str(tmp_path))
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch, answers={
            "--spike3": _Done(out=b"spike3: yes - partitions p2 are LUKS-encrypted\n"),
        })
        # picking the card fires the probe through the card-var trace
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        _wait(w, lambda: svc._spike3 is True)
        assert any("--spike3" in " ".join(c) for c in rec.calls)
        assert "LUKS" in svc._spike3_why


# ---------------------------------------------------------------------------
# PAD-1090: on a PC with the Spike 3 rig, the card runs instead
# ---------------------------------------------------------------------------

#: a padkeys.json naming an OTP key (zeros: no real key belongs in a test)
OTP_DOC = '{"otp_keyfile": "%s"}' % ("00" * 32)


def _s3_rig(monkeypatch, check=b"s3check: ok\n"):
    from pinball_decryptor.core import rigdata
    monkeypatch.setattr(rigdata, "cards_exists", lambda: False)   # no WSL in tests
    monkeypatch.setattr(emulate_rig, "spike3_rig_present", lambda: True)
    monkeypatch.setattr(emulate_rig, "spike3_check_cmd",
                        lambda: ["bash", "s3launch.sh", "--check"])
    monkeypatch.setattr(emulate_rig, "spike3_launch_cmd",
                        lambda card, slot, minutes, audio=False, keyfile=None:
                        ["bash", "s3launch.sh", card, str(slot), str(minutes)]
                        + (["--audio"] if audio else [])
                        + (["--keyfile", keyfile] if keyfile else []))
    monkeypatch.setattr(emulate_rig, "spike3_stop_cmd",
                        lambda slot: ["bash", "s3launch.sh", "--stop", str(slot)])
    return {"--check": _Done(check)}


def _pick(w, svc, card):
    w.run(lambda: w.window.emulate_card_var.set(str(card)))
    w.run(lambda: svc._spike3_apply(str(card), True, "partitions p2, p3 are LUKS-encrypted"))


def test_a_spike3_card_runs_on_the_spike3_rig(tmp_path, monkeypatch):
    from tests.test_webui_emulate import _Recorder
    card = tmp_path / "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        answers = _s3_rig(monkeypatch)
        rec = _Recorder(answers=answers, lines=(
            "s3launch: starting slot 1 for 240 min",
            "[s3run] exec /games/game  (14400s cap)"))
        monkeypatch.setattr(svc, "_run", rec.run)
        monkeypatch.setattr(svc, "_popen", rec.popen)
        _pick(w, svc, card)
        w.call(NS + ".toggle")
        _wait(w, lambda: any("s3launch.sh" in c and str(card) in c
                             for c in (" ".join(x) for x in rec.calls)))
        assert not (svc.last_refusal or "")
        assert not any("watch.sh" in " ".join(c) for c in rec.calls)
        log = _lines(w)
        assert any("[s3run] exec /games/game" in ln for ln in log)
        # Stop asks the launcher, not killgame.sh
        w.run(lambda: setattr(svc, "_s3_slot", 1))
        w.run(svc.stop)
        _wait(w, lambda: any("--stop" in c for c in rec.calls))
        _wait(w, lambda: not svc._stopping)
        assert not any("killgame.sh" in " ".join(c) for c in rec.calls)


def test_a_spike3_rig_that_is_not_set_up_says_what_is_missing(tmp_path, monkeypatch):
    from tests.test_webui_emulate import _Recorder
    card = tmp_path / "fallout_le-0_81_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        answers = _s3_rig(monkeypatch, check=b"s3check: missing - CUSE (/dev/cuse)\n")
        rec = _Recorder(answers=answers)
        monkeypatch.setattr(svc, "_run", rec.run)
        monkeypatch.setattr(svc, "_popen", rec.popen)
        _pick(w, svc, card)
        w.call(NS + ".toggle")
        _wait(w, lambda: "not set up" in (svc.last_refusal or ""))
        assert "CUSE" in svc.last_refusal
        assert not any(len(c) > 2 and c[2] == str(card) for c in rec.calls)
        _wait(w, lambda: not svc._starting and svc._proc is None)


def test_spike3_sound_follows_the_panel_mute(tmp_path, monkeypatch):
    from tests.test_webui_emulate import _Recorder
    card = tmp_path / "star_wars_2025_le-0_96_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _Recorder(answers=_s3_rig(monkeypatch))
        monkeypatch.setattr(svc, "_run", rec.run)
        monkeypatch.setattr(svc, "_popen", rec.popen)
        w.run(lambda: svc._mute_var.set(False))
        _pick(w, svc, card)
        w.call(NS + ".toggle")
        _wait(w, lambda: any(str(card) in c for c in rec.calls))
        launch = [c for c in rec.calls if str(card) in c][0]
        assert launch[-1] == "--audio"


@pytest.mark.parametrize("text,expect", [
    ("s3check: ok", (True, "")),
    ("warn\ns3check: missing - root;CUSE (/dev/cuse)", (False, "root;CUSE (/dev/cuse)")),
    ("", (None, "")),
])
def test_parse_s3check(text, expect):
    assert emulate_core.parse_s3check(text) == expect


def test_spike3_launch_cmd_runs_the_launcher_as_root(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("the WSL argv is Windows-only")
    monkeypatch.setattr(emulate_core, "_wsl_head", lambda root=False: ["wsl.exe"] + (["-u", "root"] if root else []) + ["-e"])
    cmd = emulate_core.spike3_launch_cmd(r"D:\cards\x.raw", 3, 240, audio=True)
    assert cmd[:4] == ["wsl.exe", "-u", "root", "-e"]
    assert cmd[5].endswith("/spike3_emu/s3launch.sh")
    assert cmd[6:] == ["/mnt/d/cards/x.raw", "3", "240", "--audio"]
    assert emulate_core.spike3_stop_cmd(3)[-2:] == ["--stop", "3"]


def test_spike3_launch_cmd_hands_over_the_users_keyfile(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("the WSL argv is Windows-only")
    monkeypatch.setattr(emulate_core, "_wsl_head", lambda root=False: ["wsl.exe"] + (["-u", "root"] if root else []) + ["-e"])
    cmd = emulate_core.spike3_launch_cmd(r"D:\cards\x.raw", 3, 240,
                                         keyfile=r"C:\proj\padkeys.json")
    assert cmd[-2:] == ["--keyfile", "/mnt/c/proj/padkeys.json"]


def test_spike3_keyfile_is_found_where_the_extract_unlock_left_it(tmp_path, monkeypatch):
    """The Extract tab's unlock sets $PAD_SPIKE3_KEYFILE (this process only)
    and saves padkeys.json to the project folder or ~/.pad - the Emulate tab
    finds it in the same places, card-side sidecars first after the env."""
    home = tmp_path / "home"
    (home / ".pad").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("PAD_SPIKE3_KEYFILE", raising=False)
    cards = tmp_path / "cards"
    cards.mkdir()
    card = cards / "pokemon_le.raw"
    card.write_bytes(b"")
    proj = tmp_path / "proj"
    proj.mkdir()
    find = emulate_core.spike3_keyfile
    assert find(str(card), project=str(proj)) is None
    cfg = home / ".pad" / "spike3_padkeys.json"
    cfg.write_text(OTP_DOC)
    assert find(str(card), project=str(proj)) == str(cfg)
    (proj / "padkeys.json").write_text(OTP_DOC)
    assert find(str(card), project=str(proj)) == str(proj / "padkeys.json")
    (cards / "padkeys.json").write_text(OTP_DOC)
    assert find(str(card), project=str(proj)) == str(cards / "padkeys.json")
    side = cards / "pokemon_le.raw.padkeys.json"
    side.write_text(OTP_DOC)
    assert find(str(card), project=str(proj)) == str(side)
    env = tmp_path / "unlocked.json"
    env.write_text(OTP_DOC)
    monkeypatch.setenv("PAD_SPIKE3_KEYFILE", str(env))
    assert find(str(card), project=str(proj)) == str(env)


def test_the_tab_hands_the_unlocked_key_to_the_launcher(tmp_path, monkeypatch):
    from tests.test_webui_emulate import _Recorder
    card = tmp_path / "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    key = tmp_path / "padkeys.json"
    key.write_text(OTP_DOC)
    monkeypatch.setenv("PAD_SPIKE3_KEYFILE", str(key))
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        answers = _s3_rig(monkeypatch)
        rec = _Recorder(answers=answers, lines=("s3launch: starting slot 1 for 240 min",))
        monkeypatch.setattr(svc, "_run", rec.run)
        monkeypatch.setattr(svc, "_popen", rec.popen)
        _pick(w, svc, card)
        w.call(NS + ".toggle")
        _wait(w, lambda: any("--keyfile" in c for c in rec.calls))
        launch = [c for c in rec.calls if "--keyfile" in c][0]
        assert launch[launch.index("--keyfile") + 1] == str(key)


def test_a_spike3_run_opens_the_virtual_playfield(tmp_path, monkeypatch):
    """s3run.sh prints the launch line once s3pf.py has written the title's
    tables; the tab opens Spike 2's playfield window on it, as for a Spike 2
    run whose WSL cannot start one itself."""
    from tests.test_webui_emulate import _Recorder
    card = tmp_path / "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    line = ("PAD_PLAYFIELD_WINDOWS_LAUNCH game=pokemon_le savestates=0 "
            r"root=\\wsl.localhost\Ubuntu\var\tmp\pad-s3\slot1 "
            r"tables=\\wsl.localhost\Ubuntu\var\tmp\pad-s3\slot1\tables "
            "slot=1 root_wsl=/var/tmp/pad-s3/slot1")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        answers = _s3_rig(monkeypatch)
        rec = _Recorder(answers=answers, lines=("s3launch: starting slot 1 for 240 min", line))
        monkeypatch.setattr(svc, "_run", rec.run)
        monkeypatch.setattr(svc, "_popen", rec.popen)
        opened = []
        monkeypatch.setattr(svc, "_open_playfield", opened.append)
        _pick(w, svc, card)
        w.call(NS + ".toggle")
        _wait(w, lambda: opened)
        assert opened[0]["game"] == "pokemon_le"
        assert opened[0]["root_wsl"] == "/var/tmp/pad-s3/slot1"


def test_a_spike3_card_gets_the_emulate_tab_and_not_visual_pinball():
    """David opened a Spike 3 card in the ticket's app and saw no Emulate tab:
    the era's capabilities were extract-only, and the window's gate is where
    a tab appears - so it is asked here, not the tab."""
    import types
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    from pinball_decryptor.webui.window import WebWindow
    mfr = SternManufacturer()
    mfr.set_era("spike3")
    fake = types.SimpleNamespace(modes_preview_on=lambda m: False,
                                 vpx_preview_on=lambda: True)
    gates = WebWindow._gate(fake, mfr)
    assert gates["Emulate"] is True
    assert gates["Extract"] is True
    assert not gates["Visual Pinball"]
    mfr.set_era("spike2")
    assert WebWindow._gate(fake, mfr)["Visual Pinball"]


def test_with_the_rig_the_pick_says_start_runs_it(tmp_path, monkeypatch):
    """David's log: the pick still said "cannot be emulated" on a PC whose
    Spike 3 rig runs the card."""
    monkeypatch.setattr(emulate_rig, "spike3_rig_present", lambda: True)
    card = tmp_path / "wdr-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        w.run(lambda: svc._spike3_apply(str(card), True, "SPIKE3"))
        w.drain()
        log = _lines(w)
        assert any("Start runs it on the Spike 3 emulator" in ln for ln in log)
        assert not any("cannot be emulated" in ln for ln in log)


def test_missing_packages_are_installed_and_the_run_goes_on(tmp_path, monkeypatch):
    """PAD-Runtime lacked five apt packages: Start installs them
    (s3launch.sh --setup), checks again, and runs the card."""
    from tests.test_webui_emulate import _Done, _Recorder
    card = tmp_path / "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _s3_rig(monkeypatch)
        monkeypatch.setattr(emulate_rig, "spike3_setup_cmd",
                            lambda: ["bash", "s3launch.sh", "--setup"])
        checks = [b"s3check: missing - packages: python3-pil\n"
                  b"s3setup: apt-get install python3-pil\n", b"s3check: ok\n"]
        rec = _Recorder(lines=("s3launch: installing python3-pil",))
        real_run = rec.run

        def run(cmd, **kw):
            if "--check" in cmd:
                rec.calls.append(list(map(str, cmd)))
                return _Done(checks.pop(0))
            return real_run(cmd, **kw)
        monkeypatch.setattr(svc, "_run", run)
        monkeypatch.setattr(svc, "_popen", rec.popen)
        _pick(w, svc, card)
        w.call(NS + ".toggle")
        _wait(w, lambda: any(str(card) in " ".join(c) for c in rec.calls))
        names = [" ".join(c) for c in rec.calls]
        setup = [i for i, c in enumerate(names) if "--setup" in c]
        launch = [i for i, c in enumerate(names) if str(card) in c]
        assert setup and launch and setup[0] < launch[0]
        assert not (svc.last_refusal or "")
        assert any("setting up Spike 3 emulation" in ln for ln in _lines(w))



def test_restart_game_on_a_spike3_run_is_stop_then_start(tmp_path, monkeypatch):
    """restartgame.sh asks the Spike 2 rig of the same number; a Spike 3 run
    restarts by Stop and Start instead."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        stopped = []
        monkeypatch.setattr(svc, "stop", lambda: stopped.append(1))
        monkeypatch.setattr(svc, "_launched", lambda: True)
        monkeypatch.setattr(svc, "_run", lambda *a, **k: pytest.fail("restartgame.sh asked"))
        w.run(lambda: setattr(svc, "_s3_slot", 1))
        assert w.run(svc.restart) is True
        assert stopped and svc._restart_wait == 40


@pytest.mark.parametrize("line,expect", [
    ("[s3run] progress boot 52 Booting the game", ("boot", 52, "Booting the game")),
    ("[s3run] progress nodes 66 Locating node boards (4 of 10)",
     ("nodes", 66, "Locating node boards (4 of 10)")),
    ("[s3run] progress run 100 Running - the game is in attract",
     ("run", 100, "Running - the game is in attract")),
    ("s3launch: decrypting the card into the Spike 3 store (once per card; a few minutes)",
     ("copy", 5, "Preparing the Spike 3 card (first time only)…")),
    ("s3launch:   [s3store] p2 rootfs         4794 files    636.0 MB  new    226.3 MB  (60 s)",
     ("copy", 30, "Preparing the Spike 3 card: rootfs done")),
    ("s3launch:   [s3store]   games: 500 files, 2170 MB",
     ("copy", 88, "Preparing the Spike 3 card: 2170 MB of the game")),
    ("s3launch: building the Spike 3 rig (once; a few minutes)",
     ("copy", 50, "Building the Spike 3 emulator (first time only)…")),
    ("[s3run] exec /games/game  (14400s cap)", None),
])
def test_spike3_lines_become_footer_steps(line, expect):
    from pinball_decryptor.webui.tabs.emulate import EmulateTab as EmulateService
    assert EmulateService._s3_footer_for(line) == expect


def test_a_spike3_run_paints_its_own_footer_not_the_spike2_poll(tmp_path, monkeypatch):
    """The Spike 2 status poll sees no Spike 2 game and painted the footer
    idle all through a Spike 3 boot; the run's own step wins."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        painted = []
        monkeypatch.setattr(svc, "_footer", lambda *a: painted.append(a))
        w.run(lambda: setattr(svc, "_s3_slot", 1))
        w.run(lambda: setattr(svc, "_s3_foot", ("nodes", 70, "Locating node boards (6 of 10)")))
        w.run(lambda: svc._paint_footer({"running": "0"}))
        assert painted == [("nodes", 70, "Locating node boards (6 of 10)")]
