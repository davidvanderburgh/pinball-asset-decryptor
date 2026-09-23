"""Emulate tab: the parts that can be got wrong without anyone noticing.

Mostly the pure pieces — status parsing, the wording shown for each state, the
Windows->WSL path map.  The wording is tested because "Waiting at Tech Alerts"
being read as a fault cost this project a whole pass of believing the emulator
was hung when it was doing exactly what the real machine does; a test is the
cheapest way to stop that regressing into "Stuck".

The subject is ``webui/emulate_core.py`` (the rig's Tk-free helpers) and
``webui/emulate_rig.py`` (the tab's word lists).  The web tab itself is
driven in tests/test_webui_emulate.py; a few tests here borrow one of its
methods on a bare instance, where the method reads nothing but a variable.
"""

import json
import os
import pathlib
import sys
import time
from types import SimpleNamespace

import pytest

from tests.conftest import HAS_BASH

from pinball_decryptor.webui import runtime_prompt as _runtime_ui
from pinball_decryptor.webui import emulate_core, emulate_rig
from pinball_decryptor.webui.tabs import emulate as emulate_web

from pinball_decryptor.webui.emulate_core import (DEFAULT_RIG_DIR, parse_status,
                                                  rig_cmd_root, setup_extras,
                                                  setup_notice, setup_ok,
                                                  setup_settled, setup_state,
                                                  setup_summary, state_text,
                                                  _NEEDS_WSL_RESTART, _wsl_path)

# ``setup_state`` is imported BY VALUE here on purpose.  The autouse fixture
# below replaces ``emulate_core.setup_state`` so that building a panel never
# shells out to WSL, and the two tests that are about the probe itself have to
# reach the real one - through this binding, which monkeypatch does not touch.
# Without it they exercised the stub and one of them passed for that reason.


@pytest.fixture(autouse=True)
def _no_real_setup_probe(monkeypatch):
    """Building a panel probes THIS machine for what the emulator needs, and a
    unit test must not shell out to WSL to find out.  None is "could not ask",
    which is deliberately the same as "nothing to say" - so the default panel
    in every test below carries no prerequisite notice.  Tests that are about
    the notice patch this again with facts of their own."""
    monkeypatch.setattr(emulate_core, "setup_state", lambda: None)


@pytest.fixture(autouse=True)
def _no_runtime_unless_asked(monkeypatch):
    """THE TESTS MUST NOT DEPEND ON WHETHER THIS MACHINE HAS THE RUNTIME.

    `runtime.wsl_distro` asks WSL which distro to route into, and on a
    developer's box - where the runtime IS installed - that answer costs two
    wsl.exe launches and starts a distro, inside the Start path these tests
    time.  Three of them failed that way, on the dev box only, while every CI
    runner passed: the worst shape a test can have.  So the default here is
    "no runtime", and the tests that are ABOUT routing patch it themselves.
    """
    monkeypatch.setattr(emulate_core.runtime, "wsl_distro",
                        lambda runner=None: None)
    monkeypatch.setattr(emulate_core.runtime, "known_state", lambda: None)
    # AND NOTHING HERE MAY REACH THE NETWORK OR A REAL DISTRO.  `_fix_setup`
    # calls `_install_runtime`, which on a machine whose runtime is a version
    # behind falls straight through to `runtime.install()` - a 371 MB download
    # into the real per-user cache, and a `wsl --import` into the real WSL.  A
    # test that does that on a CI runner is a broken test, and on a developer's
    # machine it is a broken machine, so both are refused here and any test
    # that is ABOUT installing patches them itself.
    def _refuse_install(*a, **kw):
        raise AssertionError(
            "a test reached the real runtime installer - patch it")

    def _refuse_payloads(*a, **kw):
        raise AssertionError(
            "a test reached the real payload downloader - patch it")

    monkeypatch.setattr(emulate_core.runtime, "install", _refuse_install)
    monkeypatch.setattr(emulate_core.runtime, "status",
                        lambda *a, **kw: ("unsupported", "not in tests"))
    from pinball_decryptor.core import payloads as _core_payloads
    monkeypatch.setattr(_core_payloads, "ensure", _refuse_payloads)


def test_parse_status_reads_key_value_lines():
    info = parse_status("procs=5\nrunning=1\ncpu=14.9\nrss=995\nstate=running\n")
    assert info["procs"] == "5"
    assert info["running"] == "1"
    assert info["cpu"] == "14.9"
    assert info["state"] == "running"


def test_parse_status_survives_noise_and_emptiness():
    # status.sh is invoked through wsl.exe, which is entitled to prepend its own
    # warnings ("your 131072x1 screen size is bogus") to stdout.
    assert parse_status("") == {}
    assert parse_status(None) == {}
    info = parse_status("your screen size is bogus\nstate=off\n")
    assert info == {"state": "off"}


def test_values_containing_equals_are_not_truncated():
    assert parse_status("log=/home/x/a=b.log")["log"] == "/home/x/a=b.log"


def test_tech_alerts_is_described_as_a_place_not_a_fault():
    # ("Waiting at Tech Alerts" until 2026-08-24 — but since item 63 a boot
    # steps past the screen on its own, so "waiting" was itself misleading;
    # David called it. The point stands: at a glance it must not read as a
    # defect.)
    label, hint = state_text({"state": "techalerts"})
    assert label == "At Tech Alerts"
    for wrong in ("stuck", "hung", "fault", "error", "failed", "parked"):
        assert wrong not in label.lower(), wrong
    # The hint has to say what to do about it, and say it is normal.
    assert "press a switch" in hint.lower()
    assert "not a fault" in hint.lower()


def test_tech_alerts_hint_changes_while_auto_advance_is_working():
    # Telling the user to press something while autoattract.sh is pressing it
    # gets two operators fighting over the same screen — and the label names
    # the WORK (the node-bus bring-up, matching the footer's "Node boards"
    # chip), not the readout screen it ends on.
    label, hint = state_text({"state": "techalerts", "auto": "1"})
    assert "node boards" in label.lower()
    assert "press a switch" not in hint.lower()
    assert "attract" in hint.lower()


def test_auto_advance_wording_only_applies_at_tech_alerts():
    # auto= lingers for a poll or two after the game has moved on; the hint for
    # a running game must not turn into "skipping to attract mode".
    _, hint = state_text({"state": "running", "auto": "1"})
    assert hint == "Attract loop, operator menu, or a game in play."
    # auto=0 is the rig saying the helper has finished or was never started.
    _, hint = state_text({"state": "techalerts", "auto": "0"})
    assert "press a switch" in hint.lower()


def test_every_state_the_rig_can_emit_has_wording():
    # `attract` is the word status.sh emits now; `running` is what it emitted
    # before, kept so an older rig still reads as something.
    for state in ("off", "booting", "techalerts", "attract", "running"):
        label, _ = state_text({"state": state})
        assert label and label != state


def test_a_running_game_is_not_called_attract_or_tech_alerts():
    # Two generations of the same lie. 2026-08-05: the app said "Waiting at
    # Tech Alerts" while the game sat in attract (status.sh and
    # autoattract.sh disagreed). 2026-08-24, David: "when i start a game,
    # it's no longer in attract mode" — the rig deliberately cannot tell
    # attract from a game in play (gamestate.sh), so the label must claim
    # neither.  "Game running" is what it can stand behind.
    label, hint = state_text({"state": "attract"})
    assert "running" in label.lower()
    assert "attract" not in label.lower()
    assert "tech alert" not in label.lower()
    # ...the honest breakdown lives in the hint instead.
    assert "attract" in hint.lower() and "in play" in hint.lower()


def test_auto_advance_giving_up_is_not_shown_as_ordinary_waiting():
    # auto=0 means the helper is not running; it does NOT mean it succeeded.
    # "finished the job" and "ran out of presses" both used to read as the
    # same unchanging "Waiting at Tech Alerts", and they need opposite things
    # from the human.
    label, hint = state_text({"state": "techalerts", "auto": "0",
                              "auto_result": "gaveup"})
    assert "stuck" in label.lower()
    assert "service menu" in hint.lower()
    assert "esc" in hint.lower()
    # ...a helper that simply finished reads as being AT the screen — not
    # "Waiting", which was a lie in the common case once item 63 made boots
    # step past it on their own (David, 2026-08-24).
    label, hint = state_text({"state": "techalerts", "auto": "0",
                              "auto_result": "ok"})
    assert label == "At Tech Alerts"
    assert "press a switch" in hint.lower()
    # ...and while the helper is actually on the job, the label names the
    # node-bus work, matching the footer chip.
    label, _ = state_text({"state": "techalerts", "auto": "1"})
    assert "node boards" in label.lower()


def test_unknown_state_falls_back_to_the_raw_word():
    # Better to show what the rig said than to silently claim it is off.
    assert state_text({"state": "wat"})[0] == "wat"
    assert state_text({})[0] == "Not running"


def test_windows_paths_map_into_wsl():
    assert _wsl_path(r"c:\repo\tools\spike2_emu") == "/mnt/c/repo/tools/spike2_emu"
    assert _wsl_path(r"D:\a\b") == "/mnt/d/a/b"
    # Already a POSIX path (someone set PAD_EMU_DIR from inside WSL).
    assert _wsl_path("/mnt/c/repo/tools/spike2_emu") == "/mnt/c/repo/tools/spike2_emu"


def test_default_rig_dir_is_the_copy_in_the_repo():
    # The rig used to live in c:\tmp, where a reboot could take it. It is in the
    # repo now, and this default is what makes the Emulate tab find it - so a
    # relocation that forgets this file breaks Start with no other symptom.
    rig = pathlib.Path(DEFAULT_RIG_DIR)
    assert rig.name == "spike2_emu" and rig.parent.name == "tools"
    assert (rig / "watch.sh").is_file()
    assert (rig / "status.sh").is_file()


def test_stop_and_killgame_agree_on_the_restart_token():
    # Stop's "restart WSL?" offer fires on a token killgame.sh prints when
    # leftovers survive everything it can do from inside the VM.  2026-08-09:
    # dead guests held as zombies kept the process count nonzero, so the
    # button stayed on Stop (which killed nothing) and "Restart WSL…" stayed
    # greyed out (nonzero procs reads as a live run) - a wedge only `wsl
    # --shutdown` from Windows could clear, and only the log pane knew.  The
    # token lives in two languages; this is what keeps it ONE string.
    killgame = (pathlib.Path(DEFAULT_RIG_DIR) / "killgame.sh").read_text(
        encoding="utf-8")
    emitted = [ln for ln in killgame.splitlines()
               if _NEEDS_WSL_RESTART in ln
               and not ln.lstrip().startswith("#")]
    assert emitted, ("killgame.sh no longer prints %r, so Stop can never "
                     "offer the WSL restart again" % _NEEDS_WSL_RESTART)
    assert any("echo" in ln for ln in emitted)


# --------------------------------------------------------------------------
# "Card image to run" survives a restart
#
# The field was empty on every launch and the path had to be re-browsed.  The
# save half was never the problem: _on_close and _materialize_anchor have
# always written `emulate_card` into the project anchor, and
# _apply_project_folder has always read it back — but that only runs on an
# EXPLICIT Project -> Open.  An ordinary startup goes through
# _apply_manufacturer, which restored the manufacturer's paths and re-marked
# the folder as the loaded project without ever fetching the card.
#
# So these drive _apply_manufacturer itself rather than a helper in isolation.
# A helper test would have passed against the broken app, because the bug was
# that nothing called it.  Stub pattern borrowed from test_gui_batch27.
# --------------------------------------------------------------------------

def _anchor(folder, emulate_card=None):
    """Write a project anchor into *folder* through the REAL writers — save()
    for the anchor and update_anchor() for the card, which is the pair
    _materialize_anchor and _on_close actually use.  Hand-rolling the JSON
    here silently produced a file load() rejects (no "kind"), and the tests
    then passed the failure off as the app's."""
    from pinball_decryptor.core import project_file
    project_file.save(
        project_file.anchor_path(str(folder)),
        manufacturer_key="stern",
        paths={"extract_input": "C:/stock/game.raw",
               "extract_output": str(folder)},
        extract_options={},
        app_version="test")
    if emulate_card is not None:
        project_file.update_anchor(str(folder), emulate_card=emulate_card)


def _restore(folder, settings=None):
    """Run _apply_manufacturer over *folder* and return what the card field
    ends up showing."""
    from pinball_decryptor.app import App

    class _Var:
        def __init__(self):
            self.value = "SENTINEL — never set"

        def set(self, v):
            self.value = v

    var = _Var()
    stub = SimpleNamespace(
        _load_manufacturer_paths=lambda key: None,
        _kick_off_prereq_check=lambda mfr: None,
        _project_folder=lambda: str(folder),
        _set_loaded_project=lambda p: None,
        _settings=settings if settings is not None else {},
        window=SimpleNamespace(apply_manufacturer=lambda mfr: None,
                               emulate_card_var=var,
                               # no Emulate service: the machine row is
                               # left alone (its own test is below)
                               service=lambda name: None),
    )
    # Bound by hand rather than stubbed out: BOTH halves have to be the real
    # code or this stops testing the thing that was broken, which was the call
    # site and not the restore.
    stub._restore_emulate_card = (
        lambda folder: App._restore_emulate_card(stub, folder))
    # The Multi-boot tab's form rides the same rail out of _apply_manufacturer
    # and has its own tests in test_multiboot_tab.py; the real one is bound
    # here rather than stubbed, and finds no panel on this window.
    stub.restore_multiboot_state = (
        lambda folder: App.restore_multiboot_state(stub, folder))
    App._apply_manufacturer(stub, SimpleNamespace(key="stern"))
    return var.value


def test_startup_restores_the_card_from_the_project(tmp_path):
    proj = tmp_path / "godzilla"
    proj.mkdir()
    _anchor(proj, emulate_card="D:/cards/godzilla.raw")
    assert _restore(proj) == "D:/cards/godzilla.raw"


def test_a_second_project_shows_its_own_card_not_the_first(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    _anchor(a, emulate_card="D:/cards/a.raw")
    _anchor(b, emulate_card="D:/cards/b.raw")
    assert _restore(a) == "D:/cards/a.raw"
    assert _restore(b) == "D:/cards/b.raw"


def test_a_project_with_no_card_shows_empty_not_the_global(tmp_path):
    """A project's own value wins even when it is EMPTY.  Falling back here
    would leak the previously-used card into a project that never had one,
    which is the exact leak _apply_project_folder already guards against."""
    proj = tmp_path / "fresh"
    proj.mkdir()
    _anchor(proj)
    assert _restore(proj, {"emulate_card": "D:/cards/other.raw"}) == ""


def test_no_project_falls_back_to_the_global_last_used(tmp_path):
    plain = tmp_path / "just-a-folder"
    plain.mkdir()
    assert _restore(plain, {"emulate_card": "D:/cards/last.raw"}) \
        == "D:/cards/last.raw"
    assert _restore(plain, {}) == ""
    assert _restore("", {"emulate_card": "D:/cards/last.raw"}) \
        == "D:/cards/last.raw"


def test_an_unreadable_anchor_leaves_the_field_empty_not_broken(tmp_path):
    """Anchors live in the project folder, which is often a NAS.  A truncated
    or half-written one must not take the startup down with it."""
    proj = tmp_path / "corrupt"
    proj.mkdir()
    from pinball_decryptor.core import project_file
    pathlib.Path(project_file.anchor_path(str(proj))).write_text(
        "{not json", encoding="utf-8")
    assert _restore(proj) == ""


def test_the_global_is_written_on_every_settings_save(tmp_path, monkeypatch):
    """Without this the no-project fallback above has nothing to read: the
    anchor save in _on_close is skipped outright when the folder is not a
    project, so a card picked against a plain folder had nowhere to live."""
    from pinball_decryptor import app as app_mod
    from pinball_decryptor.app import App
    # _save_settings really writes, so point it somewhere disposable — the
    # default is the user's live settings.json.
    monkeypatch.setattr(app_mod, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"))
    settings = {}
    stub = SimpleNamespace(
        _capture_run=lambda: False,
        _current_mfr=None,
        _settings=settings,
        root=SimpleNamespace(winfo_geometry=lambda: "1x1"),
        # The save also records the window state; a 1x1 footprint is below
        # the "don't persist a window you can't see" floor, so nothing but
        # the maximized flag comes out of it here.
        _window_is_maximized=lambda: False,
        _last_normal_geometry=None,
        window=SimpleNamespace(
            _current_theme="dark",
            _last_browse_dirs=None,
            emulate_card_var=SimpleNamespace(
                get=lambda: "  D:/cards/last.raw  ")),
    )
    # The Multi-boot tab's form is saved here too; the real reader is bound
    # rather than stubbed, and finds no panel on this window.
    stub.multiboot_state = lambda: App.multiboot_state(stub)
    App._save_settings(stub)
    assert settings["emulate_card"] == "D:/cards/last.raw"


class _Var:
    """A Tk variable's get/set, without Tk."""

    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def test_the_machine_row_is_saved_globally(tmp_path, monkeypatch):
    """PAD-149: the country DIP switches and the mains are the user's
    machine, so they go into settings.json on every save."""
    from pinball_decryptor import app as app_mod
    from pinball_decryptor.app import App
    monkeypatch.setattr(app_mod, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"))
    settings = {}
    stub = SimpleNamespace(
        _capture_run=lambda: False,
        _current_mfr=None,
        _settings=settings,
        root=SimpleNamespace(winfo_geometry=lambda: "1x1"),
        _window_is_maximized=lambda: False,
        _last_normal_geometry=None,
        window=SimpleNamespace(
            _current_theme="dark",
            _last_browse_dirs=None,
            emulate_card_var=_Var(""),
            emulate_country_var=_Var("France"),
            emulate_power_var=_Var("50 Hz mains, European machine")),
    )
    stub.multiboot_state = lambda: App.multiboot_state(stub)
    App._save_settings(stub)
    assert settings["emulate_country"] == "France"
    assert settings["emulate_power"] == "50 Hz mains, European machine"


def test_the_machine_row_comes_back_whatever_the_project(tmp_path):
    """Restored from the GLOBAL value even with a project open - a European
    cabinet does not become a US one because another project was opened -
    and a value this build does not offer is ignored rather than shown."""
    from pinball_decryptor.app import App
    from pinball_decryptor.webui.tabs.emulate import EmulateTab
    country, power = _Var("As set in the game"), _Var("60 Hz mains")
    svc = object.__new__(EmulateTab)        # machine_choices reads no state
    stub = SimpleNamespace(
        _settings={"emulate_country": "Germany",
                   "emulate_power": "50 Hz mains, US machine"},
        window=SimpleNamespace(emulate_country_var=country,
                               emulate_power_var=power,
                               service=lambda name: svc))
    App._restore_emulate_machine(stub)
    assert (country.get(), power.get()) == ("Germany",
                                            "50 Hz mains, US machine")
    stub._settings = {"emulate_country": "Atlantis", "emulate_power": "400 Hz"}
    App._restore_emulate_machine(stub)
    assert (country.get(), power.get()) == ("Germany",
                                            "50 Hz mains, US machine")


# --------------------------------------------------------------------------
# The machine row (PAD-149): what the country and power picks hand the rig
# --------------------------------------------------------------------------

def _machine_tab(country=None, power=None):
    """The web Emulate tab's ``_machine_env`` over two plain variables (it
    reads nothing else), without a page or a loop."""
    from pinball_decryptor.webui.tabs.emulate import EmulateTab
    tab = object.__new__(EmulateTab)
    tab.emulate_country_var = _Var(
        emulate_rig.COUNTRY_GAME if country is None else country)
    tab.emulate_power_var = _Var(
        emulate_rig.POWER_CHOICES[0][0] if power is None else power)
    return tab


_RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu"


def test_an_untouched_machine_row_adds_nothing_to_start():
    """PAD-149: a US machine on 60 Hz is the rig's own default, so the row
    says nothing unless it is overruling it - Start hands watch.sh exactly
    what it handed it before the row existed."""
    assert emulate_rig.COUNTRY_GAME == "As set in the game"
    assert emulate_rig.POWER_CHOICES[0] == ("60 Hz mains", ())
    assert _machine_tab()._machine_env() == []


def test_a_country_is_the_dip_value_the_game_reads():
    """The position in the game's own country table IS the number the CPU
    board's DIP switches report - 6 read back as FRANCE's index off a live
    stranger_things 1.12.0 - so the list must never be sorted."""
    countries = emulate_rig.COUNTRIES
    assert len(countries) == len(set(countries)) == 30
    assert (countries[0], countries[6], countries[14], countries[29]) == \
        ("U.S.A.", "France", "U.K.", "Indonesia")
    env = _machine_tab("Indonesia")._machine_env()
    assert "PAD_CAB_DIP=29" in env and "PAD_COUNTRY=29" in env
    # A value this build does not offer reads as the untouched default.
    assert _machine_tab("Atlantis")._machine_env() == []


def test_a_picked_country_sets_what_the_boot_screen_shows():
    """David picked Denmark and D&D's boot screen still said U.S.A.: the
    switches only flag the stored country, and the boot screen reads the
    stored one.  So a pick sets both - and U.S.A. sends its 0 too, because
    the stored country outlives the run and a silent U.S.A. could never put
    a machine back from Denmark."""
    assert _machine_tab("Denmark")._machine_env() == [
        "PAD_CAB_DIP=9", "PAD_COUNTRY=9"]
    assert _machine_tab("U.S.A.")._machine_env() == [
        "PAD_CAB_DIP=0", "PAD_COUNTRY=0"]
    assert _machine_tab("As set in the game")._machine_env() == []


def test_power_picks_the_mains_and_the_board():
    """The mains (run_game.sh) and the board the machine was built for (the
    shim) move together: a European machine is a 50 Hz board on 50 Hz, and a
    US machine on 50 Hz is the refusal Sam described."""
    assert _machine_tab(power="50 Hz mains, European machine")._machine_env() \
        == ["PAD_MAINS_HZ=50", "PAD_FACTORY_HZ=50"]
    assert _machine_tab("Germany", "50 Hz mains, US machine")._machine_env() \
        == ["PAD_CAB_DIP=7", "PAD_COUNTRY=7",
            "PAD_MAINS_HZ=50", "PAD_FACTORY_HZ=60"]


def test_the_rig_carries_the_machine_row_to_the_game():
    """The three variables reach the game: the mains in run_game.sh, the
    board and the DIP switches in the shim, all three across the macOS
    container."""
    import re
    run_game = (_RIG / "run_game.sh").read_text(encoding="utf-8")
    assert '"${PAD_MAINS_HZ:-}"' in run_game
    assert "echo $((MAINS_HZ * 100)) >" in run_game
    assert "echo 6000 >" not in run_game
    shim = (_RIG / "hwshim.c").read_text(encoding="utf-8")
    # EVERY cabinet word handed over carries the switches - the first cut of
    # this knob lived only in the synthesized word, which only a title with
    # no findable switch table ever reaches.
    scans = shim.count("have = sw_scan_bytes(0, bits);")
    applied = re.findall(r"have = sw_scan_bytes\(0, bits\);[^\n]*\n"
                         r"\s*cab_dip_apply\(bits\);", shim)
    assert scans >= 2 and len(applied) == scans
    assert re.search(r"bits\[k\] = idle\[k\];.*?cab_dip_apply\(bits\);\s*"
                     r"have = 1;", shim, re.S)
    # The board and the stored country are set on a loaded chip and on a
    # blank one, after the identity seed and before any probe's poke.
    assert len(re.findall(r"nv_ident_seed\(\);\s*nv_factory_hz_apply\(\);\s*"
                          r"nv_country_apply\(\);\s*nv_poke_apply\(\);",
                          shim)) == 2
    box = (_RIG / "docker" / "padbox.sh").read_text(encoding="utf-8")
    forwarded = box.split("for v in PAD_GAME", 1)[1].split("; do", 1)[0]
    for name in ("PAD_CAB_DIP", "PAD_COUNTRY", "PAD_MAINS_HZ",
                 "PAD_FACTORY_HZ"):
        assert name in forwarded, name


def test_the_mains_lock_is_not_shown_as_tech_alerts():
    """PAD-173: the refusal runs no light show, so the rig reads it as Tech
    Alerts - and "press a switch to carry on" is the advice that walks the
    game past the lock the user picked Power to see."""
    label, hint = state_text({"state": "techalerts", "auto": "0",
                              "auto_result": "mainslock"})
    assert label != "At Tech Alerts"
    assert "50 Hz" in label and "US" in label
    assert "will not operate in this country" in hint.lower()
    assert "60 Hz mains" in hint
    # Only at the Tech Alerts reading: a game past it is running, whatever
    # the helper said at the start.
    label, _ = state_text({"state": "attract", "auto": "0",
                           "auto_result": "mainslock"})
    assert label == "Game running"


def _without_comments(text):
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("#"))


def test_auto_advance_stands_down_on_a_us_machine_on_50_hz():
    """PAD-173, measured on stranger_things_le 1.12.0: the refusal was on the
    glass, autoattract.sh pressed Service Back into it, and the game went on
    to Guided Setup.  The helper must stand down before its first press, say
    so in the line status.sh reads, and watch.sh must say it in the pane."""
    import re
    auto = _without_comments(
        (_RIG / "autoattract.sh").read_text(encoding="utf-8"))
    lock = auto.index("if pad_mains_lock; then")
    assert lock < auto.index('echo "[auto] waiting for the game')
    assert lock < auto.index('press "$HOLD"')
    block = auto[lock:auto.index("\nfi", lock)]
    assert "exit 0" in block
    said = re.search(r'echo "(\[auto\] mains lock[^"]*)"', block).group(1)
    status = _without_comments(
        (_RIG / "status.sh").read_text(encoding="utf-8"))
    grep = re.search(r"elif grep -aq '([^']*)' \"\$AUTOLOG\"; then\n"
                     r"\s*echo \"auto_result=mainslock\"", status)
    assert grep, "status.sh no longer reports the stand-down"
    assert re.search(grep.group(1), said), (grep.group(1), said)
    # ...and before the "ok" test, which a stand-down line must not reach.
    assert status.index("auto_result=mainslock") < status.index(
        "auto_result=ok")
    for ok in ("past Tech Alerts", "already past", "nothing to do"):
        assert ok not in block, ok
    # The one definition, in padpath.sh, which both scripts source.
    pad = (_RIG / "padpath.sh").read_text(encoding="utf-8")
    assert "pad_mains_lock() {" in pad
    watch = _without_comments((_RIG / "watch.sh").read_text(encoding="utf-8"))
    launch = watch[watch.index('if [ "${PAD_AUTO_ATTRACT:-1}" != 0 ]; then'):]
    launch = launch[:launch.index("PAD_SW_EXERCISE")]
    assert "if pad_mains_lock; then" in launch
    # A run with no helper must not inherit the last run's verdict.
    assert '\nelse\n    : > "$PAD_HOME/padauto.log"' in launch


@pytest.mark.skipif(not HAS_BASH, reason="no working bash")
def test_pad_mains_lock_is_a_us_board_on_50_hz():
    """The truth table, off the function itself: 50 Hz mains with anything
    but a 50 Hz board (an unset board is the saved one, US by default).  Fed
    on stdin with the variables set inside the script, because `bash` here
    may be the WSL launcher, which does not carry the caller's environment."""
    import subprocess
    pad = (_RIG / "padpath.sh").read_text(encoding="utf-8")
    fn = pad[pad.index("pad_mains_lock() {"):]
    fn = fn[:fn.index("\n}") + 2]

    def locked(mains, board):
        sets = "".join("%s=%s\n" % (k, v) for k, v in
                       (("PAD_MAINS_HZ", mains), ("PAD_FACTORY_HZ", board))
                       if v is not None)
        script = ("unset PAD_MAINS_HZ PAD_FACTORY_HZ\n%s\n%s"
                  "pad_mains_lock && echo yes || echo no\n" % (fn, sets))
        # Bytes, not text: text mode on Windows would hand bash CRLFs.
        out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                             stdout=subprocess.PIPE, timeout=60).stdout
        return out.decode("utf-8", "replace").strip() == "yes"

    assert locked("50", "60")
    assert locked("50", None)
    assert not locked("50", "50")
    assert not locked("60", "60")
    assert not locked(None, None)
    assert not locked(None, "60")


# --- item 56: master PC-side volume + Mute -----------------------------------
#
# "master pc volume knob for emulator (not for in game, but for the emulator
# to my pc speakers). should have mute and volume setting controls." — the
# file is BOTH the remembered preference and padplay.py's live control
# channel (see AUDIO_CTL_FILE's docstring), so these tests cover the GUI half
# of that contract: what gets written, what gets loaded back, and that a
# corrupt/missing file degrades to today's unity/unmuted behaviour rather
# than failing the panel outright.
#
# EVERY test below points AUDIO_CTL_FILE at its own tmp_path first. The
# session-wide _isolate_audio_ctl fixture in conftest.py is only the backstop
# against a stray write reaching the developer's real settings dir; it shares
# ONE path for the whole run, so a test that cares whether the file is
# absent, corrupt, or holds a specific value needs its own, or it would be
# reading whatever the previous test in the session left behind.

def _isolated_ctl(monkeypatch, tmp_path):
    path = str(tmp_path / "audio_ctl.json")
    monkeypatch.setattr(emulate_core, "AUDIO_CTL_FILE", path)
    return path


def test_audio_ctl_round_trips(monkeypatch, tmp_path):
    _isolated_ctl(monkeypatch, tmp_path)
    emulate_core._write_audio_ctl(0.35, False)
    assert emulate_core._load_audio_ctl() == (0.35, False)
    emulate_core._write_audio_ctl(0.0, True)
    assert emulate_core._load_audio_ctl() == (0.0, True)


def test_audio_ctl_defaults_to_unity_unmuted_when_absent(monkeypatch, tmp_path):
    path = _isolated_ctl(monkeypatch, tmp_path)
    assert not os.path.exists(path)
    assert emulate_core._load_audio_ctl() == (1.0, False)


def test_audio_ctl_survives_a_corrupt_file(monkeypatch, tmp_path):
    """Half-written or foreign JSON must not take the panel down with it —
    same tolerance as every other small state file in this rig."""
    path = _isolated_ctl(monkeypatch, tmp_path)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert emulate_core._load_audio_ctl() == (1.0, False)


def test_audio_ctl_clamps_an_out_of_range_gain(monkeypatch, tmp_path):
    path = _isolated_ctl(monkeypatch, tmp_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"gain": 4.0, "muted": False}, f)
    assert emulate_core._load_audio_ctl() == (1.0, False)


# --- how each platform reaches the rig ---------------------------------------
#
# The rig is a Linux program and the three platforms differ only in how Linux is
# reached.  Getting this wrong is invisible on the machine you develop on and
# total on the other two, which is exactly what a test is for.

def _cmd_on(monkeypatch, platform, tmp_path, *args, **kw):
    monkeypatch.setattr(emulate_core.sys, "platform", platform)
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    return emulate_core.rig_cmd(*args, **kw)


def test_linux_runs_the_rig_directly(monkeypatch, tmp_path):
    cmd = _cmd_on(monkeypatch, "linux", tmp_path, "watch.sh", 30)
    assert cmd[0] == "bash"
    assert cmd[1].endswith("watch.sh")
    assert cmd[2] == "30"
    assert "wsl.exe" not in cmd


def test_windows_reaches_the_rig_through_wsl(monkeypatch, tmp_path):
    cmd = _cmd_on(monkeypatch, "win32", tmp_path, "watch.sh", 30)
    assert cmd[:2] == ["wsl.exe", "-e"]
    assert "bash" in cmd
    # The path handed to WSL must be a POSIX one, never the Windows spelling.
    assert not any("\\" in c for c in cmd), cmd


def test_macos_goes_through_the_container(monkeypatch, tmp_path):
    """qemu-user translates LINUX syscalls and the chroot needs Linux
    namespaces, so macOS runs the rig in a container rather than natively.
    padbox.sh owns every detail of that."""
    cmd = _cmd_on(monkeypatch, "darwin", tmp_path, "watch.sh", 30)
    assert any(c.endswith("padbox.sh") for c in cmd), cmd
    assert "wsl.exe" not in cmd
    assert cmd[-2:] == ["watch.sh", "30"]


def test_env_survives_the_hop_on_every_platform(monkeypatch, tmp_path):
    """`env NAME=value` rather than a shell assignment: wsl.exe re-parses its
    arguments, and `$var` expands to nothing on that second pass."""
    for platform in ("linux", "win32", "darwin"):
        cmd = _cmd_on(monkeypatch, platform, tmp_path, "watch.sh", 30,
                      env=["LOG=/tmp/x.log"])
        assert "LOG=/tmp/x.log" in cmd, (platform, cmd)
        assert any(c.endswith("env") or c == "env" for c in cmd), (platform, cmd)


# --- the checkpointable launch (item 13) -------------------------------------
#
# On Windows, Start boots the guest as root under PAD_PIVOT=1 - the only shape
# criu can checkpoint, so the only shape the playfield's Save/Load state
# buttons work in.  watch.sh drops the helpers back to the desktop user, whose
# home rides along explicitly because root's own HOME is the wrong rootfs.

def _home(monkeypatch, value):
    """Pin wsl_home()'s answer - the probe itself needs a live WSL.

    The second slot is the DISTRO the answer belongs to, not a boolean: the
    app can install its own Linux mid-session, and a cache that outlived the
    switch would hand one distro's home to a rig running in another.  "" is
    the machine's default, which is where these tests run."""
    monkeypatch.setattr(emulate_core, "_WSL_HOME", [value, ""])


def test_windows_start_is_the_checkpointable_launch(monkeypatch, tmp_path):
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    _home(monkeypatch, "/home/somebody")
    cmd = emulate_core.watch_cmd(120, ["PAD_CARD=/mnt/c/x.raw"])
    assert cmd[:3] == ["wsl.exe", "-u", "root"]
    assert "PAD_PIVOT=1" in cmd
    assert "HOME=/home/somebody" in cmd
    # The caller's env still survives the hop, same rule as rig_cmd's.
    assert "PAD_CARD=/mnt/c/x.raw" in cmd
    assert cmd[-1] == "120"
    assert not any("\\" in c for c in cmd), cmd


def test_a_failed_home_probe_degrades_to_the_ordinary_launch(monkeypatch,
                                                             tmp_path):
    """No save states rather than a root run pointed at /root/spike2root."""
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    _home(monkeypatch, None)
    cmd = emulate_core.watch_cmd(120, [])
    assert cmd[:2] == ["wsl.exe", "-e"]
    assert "-u" not in cmd and "PAD_PIVOT=1" not in cmd


def _account_probe(monkeypatch, whoami, passwd=""):
    """Answer the two wsl.exe probes wsl_account() makes, and nothing else."""
    monkeypatch.setattr(emulate_core, "_WSL_ACCOUNT", [("", ""), False])
    monkeypatch.setattr(emulate_core, "_WSL_HOME", [None, False])
    # False = never probed, so the probes below actually run.

    def fake_run(argv, **kw):
        if "whoami" in argv:
            return SimpleNamespace(returncode=0, stdout=whoami.encode())
        if "getent" in argv:
            return SimpleNamespace(returncode=0, stdout=passwd.encode())
        raise AssertionError("unexpected probe: %r" % (argv,))

    monkeypatch.setattr(emulate_core.subprocess, "run", fake_run)


def test_the_account_probe_names_a_root_default_distro(monkeypatch):
    """A distro that never got a user of its own logs everyone in as root,
    and that is a machine to build for, not a broken probe: wsl_account says
    so with root's own home, while wsl_home - which exists to answer "is
    there a DESKTOP user to hand the root launch" - still says None.

    wsl.exe is entitled to prepend its own warnings to stdout, so both
    answers are read off the LAST line.
    """
    _account_probe(monkeypatch,
                   "wsl: your 131072x1 screen size is bogus\nroot\n",
                   "root:x:0:0:root:/root:/bin/bash\n")
    assert emulate_core.wsl_account() == ("root", "/root")
    assert emulate_core.wsl_home() is None
    _account_probe(monkeypatch, "david\n",
                   "david:x:1000:1000::/home/david:/bin/bash\n")
    assert emulate_core.wsl_account() == ("david", "/home/david")
    assert emulate_core.wsl_home() == "/home/david"


def test_the_account_probe_is_empty_when_wsl_says_nothing(monkeypatch):
    """'' is "could not ask", which is NOT the same fact as 'root' - the
    Multi-boot tab's build tells the two apart (PAD-114).  An account whose
    passwd row cannot be read keeps its name and loses only the home."""
    _account_probe(monkeypatch, "")
    assert emulate_core.wsl_account() == ("", "")
    assert emulate_core.wsl_home() is None
    _account_probe(monkeypatch, "david\n", "")
    assert emulate_core.wsl_account() == ("david", "")
    assert emulate_core.wsl_home() is None


def test_savestates_off_is_the_ordinary_launch(monkeypatch, tmp_path):
    """The tab's opt-out - and the DEFAULT: with the toggle off, even a
    machine whose home probe would succeed boots the plain user launch, not
    root and not PAD_PIVOT, so a run costs nothing it did not cost before
    item 13.  watch.sh then starts the playfield without its Save/Load
    state controls (no --savestates), so nothing on screen can only refuse."""
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    _home(monkeypatch, "/home/somebody")
    cmd = emulate_core.watch_cmd(120, ["PAD_CARD=/mnt/c/x.raw"],
                                savestates=False)
    assert cmd[:2] == ["wsl.exe", "-e"]
    assert "-u" not in cmd and "PAD_PIVOT=1" not in cmd
    # The caller's env still survives the hop, same rule as rig_cmd's.
    assert "PAD_CARD=/mnt/c/x.raw" in cmd


def test_other_platforms_keep_their_launch(monkeypatch, tmp_path):
    """The pivot boot is a WSL arrangement; macOS's container and a Linux
    desktop keep the launch they had."""
    for platform in ("linux", "darwin"):
        monkeypatch.setattr(emulate_core.sys, "platform", platform)
        monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
        _home(monkeypatch, "/home/somebody")
        cmd = emulate_core.watch_cmd(30, [])
        assert "wsl.exe" not in cmd, (platform, cmd)
        assert "PAD_PIVOT=1" not in cmd, (platform, cmd)


def test_launch_from_slot_loads_as_root_with_the_desktop_home(monkeypatch,
                                                              tmp_path):
    """The tab's Launch button restores a slot: root (criu), the desktop
    HOME (padpath's rootfs), and PAD_RESTORE_KILL so the booted guest is
    replaced by the restored one."""
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    _home(monkeypatch, "/home/somebody")
    cmd = emulate_core.load_cmd("slot3")
    assert cmd[:3] == ["wsl.exe", "-u", "root"]
    assert "HOME=/home/somebody" in cmd
    assert "PAD_RESTORE_KILL=1" in cmd
    assert any(c.endswith("loadgame.sh") for c in cmd)
    assert cmd[-1] == "slot3"


def test_stop_kills_as_root_on_windows(monkeypatch, tmp_path):
    """A PAD_PIVOT guest is a root process: the ordinary user's pkill reports
    success and kills nothing.  Root's kill reaches both kinds of run."""
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    _home(monkeypatch, "/home/somebody")
    cmd = emulate_core.kill_cmd()
    assert cmd[:3] == ["wsl.exe", "-u", "root"]
    assert any(c.endswith("killgame.sh") for c in cmd)
    _home(monkeypatch, None)
    cmd = emulate_core.kill_cmd()
    assert cmd[:2] == ["wsl.exe", "-e"], cmd


def test_the_container_entry_point_ships_with_the_rig():
    """rig_cmd names it on macOS, so its absence would be a macOS-only failure
    that nobody developing on Windows or Linux would ever see."""
    import os
    box = pathlib.Path(DEFAULT_RIG_DIR) / "docker" / "padbox.sh"
    dockerfile = pathlib.Path(DEFAULT_RIG_DIR) / "docker" / "Dockerfile"
    entry = pathlib.Path(DEFAULT_RIG_DIR) / "docker" / "entrypoint.sh"
    if not pathlib.Path(DEFAULT_RIG_DIR).is_dir():
        pytest.skip("rig not present")
    for p in (box, dockerfile, entry):
        assert p.is_file(), "missing %s" % p


# --------------------------------------------------------------------------
# Docker, which is macOS's WSL
# --------------------------------------------------------------------------

def _fake_run(rc=0, raises=None):
    def run(*a, **kw):
        if raises is not None:
            raise raises
        return SimpleNamespace(returncode=rc)
    return run


def test_docker_state_tells_absent_from_stopped(monkeypatch):
    """Two different faults with two different remedies: nothing installed is a
    download, installed-but-down is one click.  Collapsing them into "no
    Docker" sends someone to the website who already has it."""
    # The client is FOUND here, so this test is about the three answers the
    # probe itself gives.  Finding it is its own question and its own test
    # below - a machine with no docker at all answers "absent" before running
    # anything, which is the point of that one.
    monkeypatch.setattr(emulate_core, "docker_cli",
                        lambda: "/usr/local/bin/docker")
    # AND THE ENGINE IS FOUND, because on darwin a failing `docker info` is
    # only "stopped" when there is something behind the client to have
    # stopped - the engineless split below is what this same call answers
    # otherwise, and it has its own test.  Unpinned, this read "engineless"
    # on the macOS CI runner, which ships neither an engine nor colima.
    monkeypatch.setattr(emulate_core, "docker_engine",
                        lambda: ("Docker Desktop", "app",
                                 "/Applications/Docker.app"))
    monkeypatch.setattr(emulate_core.subprocess, "run", _fake_run(rc=0))
    assert emulate_core.docker_state() == "ok"
    monkeypatch.setattr(emulate_core.subprocess, "run", _fake_run(rc=1))
    assert emulate_core.docker_state() == "stopped"
    monkeypatch.setattr(emulate_core.subprocess, "run",
                        _fake_run(raises=FileNotFoundError()))
    assert emulate_core.docker_state() == "absent"


def test_docker_is_looked_for_where_a_mac_actually_keeps_it(tmp_path,
                                                           monkeypatch):
    """★ PAD-74.  A Mac app launched from Finder inherits launchd's PATH -
    /usr/bin:/bin:/usr/sbin:/sbin - so a bare ["docker", "info"] is a PATH
    lookup that fails on a Mac where docker is installed and working.  A
    reporter had installed it with MacPorts, and the tab told him Docker
    Desktop was required while /opt/local/bin/docker sat on his disk."""
    tool = tmp_path / "docker"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(emulate_core.shutil, "which", lambda *a, **kw: None)
    assert emulate_core.which_tool("docker", (str(tmp_path),)) == str(tool)
    assert emulate_core.which_tool("nosuchtool", (str(tmp_path),)) is None
    # PATH still wins when it has an answer: someone who launched the app from
    # a terminal has already said which docker they mean.
    monkeypatch.setattr(emulate_core.shutil, "which", lambda *a, **kw: "/p/d")
    assert emulate_core.which_tool("docker", (str(tmp_path),)) == "/p/d"
    # The list itself is the fix, so the places it must name are the test.
    for d in ("/usr/local/bin",                     # Docker Desktop's symlink
              "/opt/homebrew/bin",                  # Homebrew, Apple Silicon
              "/opt/local/bin",                     # MacPorts - the reporter
              "~/.docker/bin"):                     # Desktop, no symlink
        assert d in emulate_core.DOCKER_DIRS, d


def test_pad_docker_overrides_and_a_wrong_one_is_not_ignored(tmp_path,
                                                             monkeypatch):
    """The escape hatch for the Mac that keeps it somewhere else - and a
    support instruction that is silently ignored when mistyped is worse than
    one that fails, so a bad override is "absent", not a fallback."""
    tool = tmp_path / "docker"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("PAD_DOCKER", str(tool))
    assert emulate_core.docker_cli() == str(tool)
    monkeypatch.setenv("PAD_DOCKER", str(tmp_path / "nope"))
    assert emulate_core.docker_cli() is None


def test_a_client_with_no_engine_is_not_a_missing_docker(monkeypatch):
    """★ PAD-74's second half.  On macOS `docker` is only a client: the
    containers need a Linux machine behind it, and a package manager's docker
    ships none (MacPorts says so of its own port).  That Mac is neither
    "Docker is stopped" - there is nothing to start - nor "not installed",
    which is what it used to be told."""
    monkeypatch.setattr(emulate_core.sys, "platform", "darwin")
    monkeypatch.setattr(emulate_core, "docker_cli",
                        lambda: "/opt/local/bin/docker")
    monkeypatch.setattr(emulate_core.subprocess, "run", _fake_run(rc=1))
    monkeypatch.setattr(emulate_core, "docker_engine", lambda: None)
    assert emulate_core.docker_state() == "engineless"
    # An engine that IS installed makes the same failure "start it".
    monkeypatch.setattr(emulate_core, "docker_engine",
                        lambda: ("Colima", "cli", "/opt/local/bin/colima"))
    assert emulate_core.docker_state() == "stopped"


def test_engineless_is_macos_only(monkeypatch):
    """Everywhere else the daemon is local, so "installed but not running" is
    the whole of the question and a fourth answer would be a wrong one."""
    monkeypatch.setattr(emulate_core.sys, "platform", "linux")
    monkeypatch.setattr(emulate_core, "docker_cli", lambda: "/usr/bin/docker")
    monkeypatch.setattr(emulate_core.subprocess, "run", _fake_run(rc=1))
    monkeypatch.setattr(emulate_core, "docker_engine", lambda: None)
    assert emulate_core.docker_state() == "stopped"


def test_the_setup_plan_follows_the_package_manager_already_working(
        monkeypatch):
    """Colima, from whichever package manager put the client there.  Telling a
    MacPorts user to install Homebrew first is a second package manager for a
    problem the first one solves - and MacPorts' own docker port points at
    colima for exactly this."""
    monkeypatch.setattr(emulate_core, "homebrew", lambda: None)
    monkeypatch.setattr(emulate_core, "which_tool",
                        lambda name, dirs=None: ("/opt/local/bin/port"
                                                 if name == "port" else None))
    plan = emulate_core.engine_setup_plan("/opt/local/bin/docker")
    assert plan["manager"] == "MacPorts"
    # THE PLAN IS THE WORK, not a sentence about the work: this argv is what
    # the button runs, and -N so nothing it cannot see asks a question.
    assert plan["install"] == ["/opt/local/bin/port", "-N", "install", "colima"]
    assert plan["admin"] is True            # port installs system-wide
    assert plan["steps"] and all(isinstance(s, str) for s in plan["steps"])
    # No client at all: colima is the Linux machine, not the docker command,
    # so that Mac needs both.
    assert emulate_core.engine_setup_plan(None)["packages"] == ["docker",
                                                               "colima"]
    # Homebrew's docker gets Homebrew's colima - and NEVER as root, which
    # Homebrew refuses outright.
    monkeypatch.setattr(emulate_core, "homebrew",
                        lambda: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(emulate_core, "which_tool",
                        lambda name, dirs=None: None)
    plan = emulate_core.engine_setup_plan("/opt/homebrew/bin/docker")
    assert plan["manager"] == "Homebrew"
    assert plan["install"] == ["/opt/homebrew/bin/brew", "install", "colima"]
    assert plan["admin"] is False
    # Neither package manager: there is nothing this app can drive, so there
    # is no plan and the tab must not grow a button that cannot work.
    monkeypatch.setattr(emulate_core, "homebrew", lambda: None)
    assert emulate_core.engine_setup_plan("/opt/local/bin/docker") is None


def test_no_step_of_the_mac_setup_asks_anyone_to_type_a_command(monkeypatch):
    """★ David, 2026-08-19: "we should never be asking the user to type things
    in the terminal".  The plan's sentences are what the consent dialog and the
    tab's notice are both built from, so this is the one place to hold the
    line - and the notice is built from the plan for exactly that reason."""
    monkeypatch.setattr(emulate_core, "homebrew", lambda: None)
    monkeypatch.setattr(emulate_core, "which_tool",
                        lambda name, dirs=None: ("/opt/local/bin/port"
                                                 if name == "port" else None))
    banned = ("terminal", "sudo ", "type this", "brew install", "port install")
    for cli in ("/opt/local/bin/docker", None):
        plan = emulate_core.engine_setup_plan(cli)
        assert plan, cli
        words = " ".join(plan["steps"]).lower()
        words += " " + emulate_rig.plan_sentence(plan).lower()
        for phrase in banned:
            assert phrase not in words, (phrase, words)
        # It says what WILL HAPPEN, in the app's own voice.
        assert "install" in words and "colima" in words


def test_a_slow_docker_is_starting_not_missing(monkeypatch):
    """`docker info` against a daemon that is waking up can time out, and
    reporting that as "not installed" would send the user to reinstall
    something they already have."""
    import subprocess as sp
    # The client has to be found for the probe to run at all - without this
    # the answer is "absent" before subprocess is reached, which is what the
    # macOS CI runner (no docker installed) actually returned.
    monkeypatch.setattr(emulate_core, "docker_cli",
                        lambda: "/usr/local/bin/docker")
    monkeypatch.setattr(emulate_core.subprocess, "run",
                        _fake_run(raises=sp.TimeoutExpired("docker", 12)))
    assert emulate_core.docker_state() == "stopped"


# ----------------------------------------------------------------------
# The setup check: what this machine still needs before it can emulate.
#
# The fault these are about reached a user on 2026-08-07 as
#
#     chroot: failed to run command '/bin/sh': Exec format error
#
# arriving in the log pane after Start had said "Starting…", on a machine
# that had never had qemu-user-static.  It is the one of the rig's four
# guest-exec faults that the rig cannot repair by itself, so the app has to
# - and the wording is what a user acts on, which is why it is tested.
# ----------------------------------------------------------------------

_READY = {"qemu": "1", "armgcc": "1", "nativecc": "1", "debugfs": "1",
          "fuse": "1", "ffmpeg": "1", "binfmt": "1", "iswsl": "1",
          "wslconf": "1"}


def _facts(**over):
    f = dict(_READY)
    f.update(over)
    return f


def test_a_ready_machine_is_told_nothing():
    assert setup_ok(_facts())
    assert setup_notice(_facts(), can_fix=True) == ""


def test_a_machine_we_could_not_ask_is_not_accused():
    """setup_state returns None for a PC with no WSL and for a probe that
    timed out.  Neither is evidence of a fault, and a prerequisite notice in
    front of someone whose machine is fine is worse than none at all."""
    assert setup_ok(None)
    assert setup_notice(None, can_fix=True) == ""
    assert setup_summary(None) == ([], "1")


def test_summary_lists_only_what_is_actually_missing():
    missing, binfmt = setup_summary(_facts(qemu="0", fuse="0", binfmt="0"))
    assert [pkg for pkg, _ in missing] == ["qemu-user-static", "fuse3"]
    assert binfmt == "0"


def test_the_arm_handler_leads_because_it_is_what_stops_the_run():
    """Ralf's machine: no qemu-user-static and no registration.  The headline
    has to be the thing that would kill the run, not a package list."""
    text = setup_notice(_facts(qemu="0", armgcc="0", binfmt="0"),
                        can_fix=True)
    assert "cannot run the emulator yet" in text
    handler = text.index("32-bit ARM")
    packages = text.index("qemu-user-static")
    assert handler < packages, "the package list must not bury the cause"
    # And it must say what it will do about it, since it can.
    assert "Set up emulator" in text


def test_every_missing_package_says_what_it_is_for():
    text = setup_notice(_facts(qemu="0", armgcc="0", debugfs="0", fuse="0"),
                        can_fix=True)
    for pkg in ("qemu-user-static", "gcc-arm-linux-gnueabihf", "e2fsprogs",
                "fuse3"):
        assert pkg in text
    assert "32-bit ARM game binary" in text
    assert "without extracting" in text


# ----------------------------------------------------------------------
# THE RIG COMPILES TWO THINGS AND THE TAB ONLY ASKED ABOUT ONE OF THEM.
# The hardware shim is ARM and cross compiled; padglhost, the renderer that
# draws the picture, is native.  A user on 2026-08-08 had the cross compiler,
# watched the shim build in his log, and thirty seconds into the run met
#
#     [build] the GL renderer is not built, and there is no gcc here
#     [build] to build it. It is a NATIVE binary - install gcc ...
#
# The tab had said nothing before Start, because nothing here knew the native
# compiler was a prerequisite at all.
# ----------------------------------------------------------------------

def test_the_native_compiler_is_a_prerequisite_in_its_own_right():
    """Having the ARM cross compiler says nothing about having gcc, which is
    exactly the machine that reported this."""
    facts = _facts(nativecc="0")
    assert not setup_ok(facts)
    missing, _binfmt = setup_summary(facts)
    assert [pkg for pkg, _ in missing] == ["gcc libc6-dev"]
    text = setup_notice(facts, can_fix=True)
    assert "gcc libc6-dev" in text
    # ...and said in terms of what it costs the user, not of a compiler.
    assert "picture" in text


def test_the_headers_are_named_beside_the_compiler():
    """gcc only RECOMMENDS libc6-dev, so `apt install gcc` on a slim WSL is a
    compiler with no headers - and padglhost.c opens with #include <stdio.h>.
    The JJP hooks learned this already; naming only gcc here would have sent
    the same user round again."""
    text = setup_notice(_facts(nativecc="0", binfmt="1"), can_fix=False)
    assert "sudo apt install gcc libc6-dev" in text


def test_a_rig_that_never_heard_of_the_native_compiler_accuses_nobody():
    """An older rig emits no `nativecc` line at all, and an absent fact is not
    a missing package - the same direction everything else here takes."""
    older = dict(_READY)
    del older["nativecc"]
    assert setup_ok(older)
    assert setup_notice(older, can_fix=True) == ""


# ----------------------------------------------------------------------
# AND THE DECODER, WHICH IS THE SAME OMISSION WITH A WORSE SYMPTOM.
# Every other prerequisite here builds or mounts something, so missing one
# ENDS the run and names itself in the log.  Missing ffmpeg ends nothing: the
# guest boots, the shim loads, the renderer opens a 1360x768 window and holds
# 59 fps - and the window is black and silent, because the game decodes
# neither its video nor its audio itself.  A user on 2026-08-08 (PAD-49) ran
# exactly that, with a log repeating
#
#     ch0 decode failed: [Errno 2] No such file or directory: 'ffmpeg'
#
# a hundred times a second, while the tab said nothing before Start and the
# prerequisite strip said "All prerequisites OK" - that strip's ffmpeg is the
# WINDOWS one, which the app bundles, and this one is Linux's.
# ----------------------------------------------------------------------

def test_the_decoder_is_a_prerequisite_in_its_own_right():
    """A machine that passes every other line here is precisely the machine
    that reported this."""
    facts = _facts(ffmpeg="0")
    assert not setup_ok(facts)
    missing, binfmt = setup_summary(facts)
    assert [pkg for pkg, _ in missing] == ["ffmpeg"]
    # Nothing else about that machine was wrong, so nothing else may be said.
    assert binfmt == "1"


def test_the_decoder_is_explained_by_what_its_absence_costs():
    """"ffmpeg" means nothing to the person this is written for; a black
    screen is the thing he actually has, and the notice has to join the two -
    the same standard the native compiler's line is held to ("picture")."""
    text = setup_notice(_facts(ffmpeg="0"), can_fix=True)
    assert "ffmpeg" in text
    assert "video" in text and "sound" in text
    assert "Set up emulator" in text


def test_the_decoder_can_be_the_only_thing_wrong():
    """It has to survive being the WHOLE fault.  Every earlier prerequisite
    fails alongside a dead run, so a notice listing one package and no
    stopped-run headline is a shape this had never had to produce."""
    text = setup_notice(_facts(ffmpeg="0"), can_fix=False)
    assert "sudo apt install ffmpeg" in text
    # ...and it must not invent a second fault to explain itself with.
    assert "32-bit ARM" not in text


def test_the_button_promises_only_what_it_is_going_to_do():
    """The summary sentence used to say "installs those in WSL and registers
    the handler" whatever was wrong, which was safe only because every
    prerequisite before this one turned up on machines that also had no
    handler registered.  The decoder is the first that arrives ALONE, and the
    machine that reported it had its handler already - so that sentence
    promised it an act that was not going to happen."""
    only_pkg = setup_notice(_facts(ffmpeg="0"), can_fix=True)
    assert "installs those in WSL" in only_pkg
    assert "registers the handler" not in only_pkg
    # ...and the converse still says it, since then it IS going to.
    both = setup_notice(_facts(ffmpeg="0", binfmt="0"), can_fix=True)
    assert "installs those in WSL and registers the handler" in both
    # A handler that is merely switched off is a different act, which the
    # consent list has distinguished since it was written.
    off = setup_notice(_facts(binfmt="disabled"), can_fix=True)
    assert "switches the 32-bit ARM handler back on" in off
    assert "installs those in WSL" not in off


def test_a_rig_that_never_heard_of_the_decoder_accuses_nobody():
    """An older rig emits no `ffmpeg` line, and silence is not a missing
    package - the direction every fact here takes."""
    older = dict(_READY)
    del older["ffmpeg"]
    assert setup_ok(older)
    assert setup_notice(older, can_fix=True) == ""


# ----------------------------------------------------------------------
# AND THE ONE THAT IS NOT ABOUT STARTING AT ALL (PAD-53).
#
# v0.126.0 made every Start a checkpointable (PAD_PIVOT) boot so the save-state
# controls could simply be on.  That boot needs a native static busybox, which
# no machine has by default and which was on no prerequisite list anywhere -
# and run_game.sh's answer to a pivot it cannot do was to stop.  A user on
# 2026-08-11 ran star_wars_le and iron_maiden_pro, both of which had worked
# before, and got no window at all:
#
#     [run] PAD_PIVOT needs a STATIC busybox at /bin/busybox
#     [watch] the game never started.
#
# watch.sh now withdraws the request and boots the ordinary way, so the cost is
# the FEATURE.  Which is why this package is not in _SETUP_TOOLS: a machine
# missing it runs the emulator perfectly, and "this PC cannot run the emulator"
# in front of it would be the same false accusation every other rule here
# guards against.
# ----------------------------------------------------------------------

def test_the_save_state_package_does_not_stop_the_emulator():
    facts = _facts(busybox="0")
    assert setup_ok(facts), "a missing extra must not read as a dead emulator"
    assert not setup_settled(facts), "...but there IS something to say"
    assert [pkg for pkg, _ in setup_extras(facts)] == ["busybox-static"]
    # It is not in the list that decides whether a run can start.
    assert setup_summary(facts)[0] == []


def test_the_notice_leads_with_the_emulator_working():
    """The headline is the difference between a true notice and a false one:
    this machine runs every title, and telling its owner it cannot is how a
    correct warning turns into a wrong one."""
    text = setup_notice(_facts(busybox="0"), can_fix=True)
    assert "cannot run the emulator" not in text
    assert "The emulator runs on this PC" in text
    assert "Save states need" in text
    assert "busybox-static" in text
    # ...and it must not invent a second fault to explain itself with.
    assert "32-bit ARM" not in text


def test_the_button_offers_to_install_the_save_state_package():
    """The button lives UNDER this notice.  Hiding the notice on a machine
    that only misses an extra would have left nothing to press, and the
    package invisible."""
    text = setup_notice(_facts(busybox="0"), can_fix=True)
    assert "installs those in WSL" in text
    steps = emulate_core.setup_fix_steps(_facts(busybox="0"))
    assert any("busybox-static" in s for s in steps), (
        "the consent list must name what the button is about to install")


def test_linux_asks_for_it_at_the_command_line_like_everything_else():
    text = setup_notice(_facts(busybox="0", iswsl="1"), can_fix=False)
    assert "sudo apt install busybox-static" in text


def test_a_linux_desktop_is_not_told_about_a_windows_only_shape():
    """watch_cmd asks for the checkpointable boot on Windows and nowhere else,
    so a Linux Start never wants a static busybox - and a package a machine's
    runs would never use is not a prerequisite of that machine."""
    facts = _facts(busybox="0", iswsl="0", wslconf="1")
    assert setup_extras(facts) == []
    assert setup_settled(facts)
    assert setup_notice(facts, can_fix=False) == ""


def test_a_rig_that_never_heard_of_the_save_state_package_accuses_nobody():
    """An older setupcheck.sh emits no `busybox` line at all - the same
    direction every other fact here takes."""
    assert setup_extras(_facts()) == []
    assert setup_settled(_facts())
    assert setup_notice(_facts(), can_fix=True) == ""


# ----------------------------------------------------------------------
# ...AND THE SECOND FEATURE ON THAT LIST (★ PAD-126).
#
# The boot menu a multi-boot card starts up into is an ARM program, built by
# codeselect/Makefile - so `make` is as much a part of that build as the cross
# compiler is.  It is not a compiler, nobody thinks of it as a prerequisite,
# and it was named on no list: not here, not in setupcheck.sh, not in either
# installer.  A user pressed Build on 2026-09-10 and got, out of a script he
# had never run by hand:
#
#     [build] .../buildselect.sh: line 78: make: command not found
#     [build] build FAILED, and a PAD_SELECT run has no menu without it.
#
# His emulator was perfect, which is why this is an EXTRA - and why the one
# hard-coded "Save states" headline the extras used to get had to go.
# ----------------------------------------------------------------------

def test_the_menu_program_tool_costs_a_card_and_not_the_emulator():
    facts = _facts(make="0")
    assert setup_ok(facts), "a missing extra must not read as a dead emulator"
    assert not setup_settled(facts), "...but there IS something to say"
    assert [pkg for pkg, _ in setup_extras(facts)] == ["make"]
    assert setup_summary(facts)[0] == []
    text = setup_notice(facts, can_fix=True)
    assert "cannot run the emulator" not in text
    assert "The emulator runs on this PC. Multi-boot cards do not yet." in text
    assert "Multi-boot cards need:" in text and "make" in text
    # ...and NOT under the other feature's name, which is the whole point of
    # grouping them: this machine's save states are fine.
    assert "Save states" not in text


def test_the_button_offers_to_install_the_menu_program_tool():
    steps = emulate_core.setup_fix_steps(_facts(make="0"))
    assert any(s.startswith("Install in WSL:") and "make" in s
               for s in steps), steps


def test_a_linux_desktop_is_asked_for_it_too():
    """Unlike the save-state pair.  The freezable boot shape is a Windows
    one, so a Linux desktop is never asked for busybox-static - but a card is
    built the same way on every desktop, and a Linux PC without make cannot
    build one either."""
    facts = _facts(make="0", busybox="0", iswsl="0", wslconf="1")
    assert [pkg for pkg, _ in setup_extras(facts)] == ["make"]
    assert not setup_settled(facts)
    assert "sudo apt install make" in setup_notice(facts, can_fix=False)


def test_the_two_features_are_named_apart_when_both_are_missing():
    facts = _facts(make="0", busybox="0")
    assert [pkg for pkg, _ in setup_extras(facts)] == ["busybox-static",
                                                       "make"]
    text = setup_notice(facts, can_fix=True)
    assert ("The emulator runs on this PC. Save states and multi-boot cards "
            "do not yet.") in text
    assert "Save states need:" in text and "Multi-boot cards need:" in text
    groups = emulate_core.setup_extra_groups(facts)
    assert [feat for feat, _rows in groups] == ["Save states",
                                                "Multi-boot cards"]
    assert [pkg for _f, rows in groups for pkg, _why in rows] == [
        "busybox-static", "make"]


def test_a_rig_that_never_heard_of_make_accuses_nobody():
    """An older setupcheck.sh emits no `make` line - the direction every fact
    here takes."""
    assert setup_extras(_facts()) == []
    assert setup_settled(_facts())


def test_the_notice_survives_a_machine_whose_only_repair_is_wsl_conf():
    """A crash, found on David's own PC while photographing PAD-126.

    Everything installed, the ARM handler registered, a distro that does not
    boot systemd, and an environment warning to put the notice on screen: the
    only thing “Set up emulator…” would do is write /etc/wsl.conf, that step
    was in the consent list and in no summary, and the sentence built from
    the summary indexed an empty list.  What the tab showed instead of its
    notice was “Internal error: list index out of range”.
    """
    facts = _facts(wslconf="0", user="root")
    assert emulate_core.setup_fix_steps(facts), "there IS a step to consent to"
    text = setup_notice(facts, can_fix=True)
    assert "systemd on in /etc/wsl.conf" in text
    assert "stay BLACK" in text, "the warning it is on screen for"


def test_an_uninstallable_extra_does_not_ask_for_a_new_linux():
    """"Replace your distro" is the answer to an emulator that cannot run.
    Answering a switched-off feature with it would be wildly out of
    proportion - and the machine saying so runs every title today."""
    facts = _facts(busybox="0", nocand="busybox-static", universe="1",
                   indexed="1")
    text = setup_notice(facts, can_fix=True)
    assert "wsl --install" not in text
    assert "save states stay off" in text
    assert "titles start and run exactly as they do now" in text


def test_the_run_says_it_once_when_the_decoder_is_missing_anyway():
    """THE BACKSTOP, for a run started outside this tab.

    Nothing in watch.sh FAILS to start without ffmpeg - padvidhost.py creates
    its mmap either way, so "video: host decoder up" gets printed by a decoder
    that cannot decode a thing.  The check has to come before the helpers, and
    it has to hand the guest the existing no-bridge path: left pointed at a
    bridge that can never fill, the game re-arms the same clip forever and
    blocks on every one of them, which is the hundred-lines-a-second log."""
    watch = _rig_text("watch.sh")
    body = "\n".join(ln for ln in watch.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "command -v ffmpeg" in body, (
        "watch.sh starts the decode helpers without ever asking for ffmpeg")
    # Against where they are STARTED, not merely named: both are named far
    # above this, in the teardown's pkill list.
    at = body.index("command -v ffmpeg")
    for launch in ('setsid_as_user bash "$S/playaudio.sh"',
                   'setsid_as_user python3 "$S/padvidhost.py"'):
        assert launch in body, "watch.sh no longer starts it this way"
        assert at < body.index(launch), (
            "the check must come before the helper it is about")
    assert "export PAD_VID=0" in body


def test_a_registered_but_disabled_handler_is_not_called_missing():
    """Different fault, different repair: it is registered, so nothing needs
    installing and telling the user to install something would be wrong."""
    text = setup_notice(_facts(binfmt="disabled"), can_fix=True)
    assert "switched" in text.lower()
    assert "Missing" not in text
    assert not setup_ok(_facts(binfmt="disabled"))


def test_without_a_fixer_the_user_gets_the_rig_s_own_command():
    """On a Linux desktop the app cannot get root without a password prompt it
    has nowhere to show, so it prints - and it prints the command THIS machine
    wants, which the rig derived (Ubuntu 24.04 and Debian differ)."""
    advice = "sudo sh -c 'cat /usr/lib/binfmt.d/qemu-arm.conf > /proc/sys/fs/binfmt_misc/register'"
    text = setup_notice(_facts(binfmt="0", advice=advice), can_fix=False)
    assert advice in text
    assert "Set up emulator" not in text


def test_missing_packages_are_named_as_one_apt_line_not_four():
    text = setup_notice(_facts(qemu="0", armgcc="0", binfmt="1"),
                        can_fix=False)
    assert "sudo apt install qemu-user-static gcc-arm-linux-gnueabihf" in text


def test_probe_failure_is_none_rather_than_a_wrong_answer(monkeypatch):
    """A probe that cannot run must not read as "everything is missing"."""
    def boom(*a, **kw):
        raise FileNotFoundError("wsl.exe")
    monkeypatch.setattr(emulate_core.subprocess, "run", boom)
    monkeypatch.setattr(emulate_core, "rig_available", lambda: True)
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    assert setup_state() is None


def test_probe_reads_the_rig_s_key_value_output(monkeypatch):
    out = (b"qemu=0\nbinfmt=0\n"
           b"advice=sudo apt install qemu-user-static\n")
    monkeypatch.setattr(emulate_core, "rig_available", lambda: True)
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    monkeypatch.setattr(emulate_core.subprocess, "run",
                        lambda *a, **kw: SimpleNamespace(returncode=0,
                                                         stdout=out))
    facts = setup_state()
    assert facts["qemu"] == "0"
    # The advice is a whole command with '=' nowhere but the first split.
    assert facts["advice"] == "sudo apt install qemu-user-static"


def test_root_commands_are_wsl_only_and_actually_ask_for_root(monkeypatch):
    """The no-root rule the rig follows is a LINUX fact.  `wsl -u root` is uid
    0 with no password, which is why the Windows path may repair and the Linux
    one may only advise - so this must never quietly produce a non-root
    command on a platform where root is not free."""
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    cmd = rig_cmd_root("setupfix.sh")
    assert cmd[:4] == ["wsl.exe", "-u", "root", "-e"]
    assert cmd[-1].endswith("/setupfix.sh")
    for plat in ("linux", "darwin"):
        monkeypatch.setattr(emulate_core.sys, "platform", plat)
        with pytest.raises(RuntimeError):
            rig_cmd_root("setupfix.sh")


# ---- the rig side, checked as text: these are the two ways the pair can
# ---- silently stop agreeing with each other.

def _rig_text(name):
    return (pathlib.Path(DEFAULT_RIG_DIR) / name).read_text(encoding="utf-8")


def test_the_repair_installs_exactly_the_packages_the_tab_names():
    """The tab explains five packages and the rig installs them.  Two lists in
    two languages is precisely how they drift.

    The rig's copy lives in setupcheck.sh, which probes the tool and knows the
    package that carries it; setupfix.sh installs whatever that reports as
    missing rather than keeping a third list.

    Commas are how the rig's whitespace-split list spells a fact that needs
    more than one package (gcc,libc6-dev); the tab spells the same thing with
    a space, and this is the seam where those two have to mean the same."""
    check = _rig_text("setupcheck.sh").replace(",", " ")
    fix = _rig_text("setupfix.sh")
    # The optional ones are installed by the same button off the same `need`
    # list, so they are held to the same seam - EXCEPT the ones apt cannot
    # supply at all, which is what the fourth field says.  criu is on no
    # Ubuntu, so its seam is with getcriu.sh instead, and its package field in
    # setupcheck.sh is `-` precisely so it never reaches `need`.
    rows = ([t + ("apt", "") for t in emulate_core._SETUP_TOOLS]
            + list(emulate_core._SETUP_OPTIONAL))
    for key, pkg, _why, how, _feat in rows:
        assert 'sudo' not in pkg
        assert "%s:" % key in check
        if how == "apt":
            assert pkg in check, "%s (%s) is explained but never installed" % (
                pkg, key)
        else:
            assert "%s:@" % key in check and ":-:" in check, (
                "%s must not be handed to apt-get, which has no such package"
                % pkg)
            assert "getcriu.sh" in fix, (
                "%s is explained but nothing gets it" % pkg)
    assert '_get "$facts" need' in fix


def test_the_repair_keeps_no_list_of_its_own_to_prove_itself_with():
    """setupfix.sh's LAST act is to re-probe and declare the machine fixed, and
    it used to do that by naming the four fact keys one per line - a third copy
    of the list, on the success path, where nobody would think to look.  Adding
    a fifth prerequisite would have left it announcing "result=ok" on a machine
    that still could not build the renderer.

    `need` is emitted by the same loop that emits the keys, so the proof is
    about whatever setupcheck probes today."""
    fix = _rig_text("setupfix.sh")
    proof = fix.split("# ---- 4.")[-1]
    assert '-z "$(_get "$facts" need)"' in proof
    for key, _pkg, _why in emulate_core._SETUP_TOOLS:
        assert '_get "$facts" %s' % key not in proof, (
            "setupfix.sh is naming %s itself again" % key)


def test_the_repair_does_not_hide_apt_failure_behind_a_pipe():
    """`apt-get ... | sed` reports SED's exit status, so a failed install
    reads as a clean one and the tab would announce success."""
    fix = _rig_text("setupfix.sh")
    for line in fix.splitlines():
        if "apt-get install" in line or "apt-get update" in line:
            assert "| sed" not in line, line


# ----------------------------------------------------------------------
# "Missing" and "installable" are two different facts, and the tab used to
# know only the first.  A tester on 2026-08-07 was told qemu-user-static was
# missing, pressed the button that installs it, and got
#
#     E: Package 'qemu-user-static' has no installation candidate
#
# twice - because Ubuntu publishes it in `universe` and his WSL had that
# component switched off.  gcc-arm-linux-gnueabihf, named in the same apt
# command and sitting in `main`, was installable and was NOT installed either:
# `apt-get install a b` is all or nothing.
# ----------------------------------------------------------------------

def test_a_package_apt_cannot_install_is_not_just_called_missing():
    text = setup_notice(_facts(qemu="0", armgcc="0", binfmt="0",
                               nocand="qemu-user-static", universe="0"),
                        can_fix=True)
    assert "universe" in text
    assert "switched off" in text
    # and the button must promise the extra step it is now going to take
    assert "turns universe back on" in text


def test_an_unavailable_package_with_no_known_cause_still_says_so():
    """Not every "no installation candidate" is universe - an out-of-support
    distro does it too.  Naming a cause we have not established would be a
    guess, but saying nothing sends the user back to the same button."""
    text = setup_notice(_facts(qemu="0", binfmt="1",
                               nocand="qemu-user-static", universe="1"),
                        can_fix=True)
    assert "do not offer it" in text
    assert "universe" not in text


def test_the_printed_commands_lead_with_the_one_that_makes_the_rest_work():
    """On Linux the app can only advise, and `sudo apt install
    qemu-user-static` is advice that FAILS on this machine until universe is
    on.  Order is the whole content here."""
    text = setup_notice(_facts(qemu="0", armgcc="0", binfmt="0",
                               nocand="qemu-user-static", universe="0"),
                        can_fix=False)
    assert text.index("add-apt-repository universe") < text.index("apt install")


def test_on_arch_the_printed_commands_are_pacmans():
    """setupcheck.sh now says which package manager it found (`pm`).  On a
    pacman machine the advice is spelled for it - apt's names are "target not
    found" there - and the cross compiler, which is in no repository pacman
    has, is named from the AUR on a line of its own rather than dropped or
    handed to pacman with the rest.  A user on Omarchy (2026-09-06) did this
    translation by hand; nothing in the tab had a word for that machine."""
    text = setup_notice(_facts(qemu="0", armgcc="0", nativecc="0",
                               binfmt="0", pm="pacman"), can_fix=False)
    for apt in ("apt install", "apt-get", "add-apt-repository"):
        assert apt not in text, (apt, text)
    pac = [ln for ln in text.splitlines() if "pacman -S --needed" in ln]
    assert pac, text
    for name in ("qemu-user-static", "qemu-user-static-binfmt", "gcc"):
        assert name in pac[0], (name, pac[0])
    for debian in ("libc6-dev", "gcc-arm-linux-gnueabihf"):
        assert debian not in text, (debian, text)
    aur = [ln for ln in text.splitlines() if "arm-linux-gnueabihf-gcc" in ln]
    assert aur and "AUR" in aur[0], text
    # An apt machine, and a rig too old to say, read exactly as before.
    for facts in (_facts(qemu="0", armgcc="0", binfmt="0", pm="apt"),
                  _facts(qemu="0", armgcc="0", binfmt="0")):
        old = setup_notice(facts, can_fix=False)
        assert "sudo apt install qemu-user-static gcc-arm-linux-gnueabihf" in old, old
        assert "pacman" not in old, old


def test_a_rig_that_never_heard_of_nocand_accuses_nobody():
    """The fact is new.  An older setupcheck.sh, or a probe that timed out,
    must read as "nothing known against them" and not as "none of them can be
    installed"."""
    assert emulate_core.setup_unavailable(_facts(qemu="0")) == []
    assert emulate_core.setup_unavailable(None) == []
    assert "cannot install" not in setup_notice(_facts(qemu="0", binfmt="0"),
                                                can_fix=True)


def test_the_repair_installs_one_package_at_a_time():
    """`apt-get install a b` is all or nothing: one package this machine's
    sources do not carry means NONE of the others get installed, which is how
    a user missing four things ends up with four things still missing."""
    fix = _rig_text("setupfix.sh")
    for line in fix.splitlines():
        if line.lstrip().startswith("#"):
            continue                    # the comment explaining exactly this
        if "apt-get install" in line:
            assert '"$pkg"' in line, line
            assert "$pkgs" not in line, line


def test_the_repair_only_edits_the_distro_s_own_sources():
    """Appending `universe` to a PPA line turns a working repository into a
    404 on every apt-get update.  The in-place edit is allowed exactly two
    files, and within them only ubuntu.com archive lines."""
    fix = _rig_text("setupfix.sh")
    for line in fix.splitlines():
        if line.strip().startswith("for f in"):
            assert line.count("/etc/apt/") == 2, line
            assert "sources.list.d/*" not in line, line
    assert r"ubuntu\.com" in fix


# ----------------------------------------------------------------------
# PAD-42.  The SAME tester, one release on, and both halves of "apt has no
# installation candidate" were still wrong.
#
#   * His machine: a current Ubuntu, universe ON, whose archive had installed
#     twenty-one packages seconds earlier - and the app told him his distro
#     was out of support or its sources trimmed, and that installing a current
#     Ubuntu was the way back.  Two causes nothing had checked, and the advice
#     was the thing he had already done.  The button stayed on offer, under a
#     sentence saying the package could not be installed, and he pressed it
#     twice.
#
#   * Every OTHER machine: `nocand` and `universe` are both read out of apt's
#     DOWNLOADED metadata, and a WSL Ubuntu that has never run `apt-get
#     update` has none.  `apt-cache policy` prints nothing for a package that
#     is not installed, `apt-get indextargets` prints nothing at all - so a
#     brand-new distro, where all four packages install perfectly, was told
#     its sources offered none of them and that universe was switched off.
#     Reproduced in WSL with APT_CONFIG pointing at an empty lists dir.
# ----------------------------------------------------------------------

#: Jim-Beam's machine as the fixed probe describes it: a release that does not
#: publish qemu-user-static, which the rig is willing to go and fetch.
_NOCAND = dict(qemu="0", armgcc="1", debugfs="1", fuse="1", binfmt="0",
               nocand="qemu-user-static", xrel="qemu-user-static",
               universe="1", indexed="1",
               components="main restricted universe multiverse",
               distro="ubuntu 26.10 resolute")

#: The same shape, for a package the rig will NOT cross-install: an ordinary
#: dynamically linked one whose dependencies belong to its own release.
_NOCAND_HARD = dict(_NOCAND, qemu="1", armgcc="0", binfmt="1",
                    nocand="gcc-arm-linux-gnueabihf", xrel="")


def test_the_release_that_lacks_the_package_is_named_not_guessed_at():
    """"Out of support" and "sources have been trimmed" were both guesses,
    and both wrong about the machine that met them.  What setupcheck.sh can
    actually report is the release and the components apt has on."""
    text = setup_notice(_facts(**_NOCAND), can_fix=True)
    assert "ubuntu 26.10 resolute" in text
    assert "universe” switched on" in text
    assert "does not publish it" in text
    for guess in ("out of support", "trimmed", "latest version"):
        assert guess not in text


def test_the_app_fetches_the_package_rather_than_telling_him_to_move_distro():
    """THE POINT OF PAD-42.  qemu-user-static depends on nothing, so a .deb
    from an Ubuntu that publishes it installs cleanly on one that does not -
    and the app doing that beats the app printing two wsl commands."""
    facts = _facts(**_NOCAND)
    assert emulate_core.setup_fetchable(facts) == ["qemu-user-static"]
    assert emulate_core.setup_fixable(facts), "the button can still do this"
    text = setup_notice(facts, can_fix=True)
    assert "Ubuntu %s's archive" % emulate_core.FALLBACK_RELEASE in text
    assert "depends on nothing" in text
    # ...and it must NOT fall back to telling him to move distro.
    assert "wsl --set-default" not in text


def test_the_fetch_is_named_in_the_dialog_that_consents_to_it():
    """Fetching from another release is not `apt install`, and the dialog is
    the only place the user agrees to any of it."""
    steps = emulate_core.setup_fix_steps(_facts(**_NOCAND))
    fetch = [s for s in steps if "Ubuntu %s's archive"
             % emulate_core.FALLBACK_RELEASE in s]
    assert len(fetch) == 1, steps
    assert "depends on nothing" in fetch[0]
    assert "sources are not changed" in fetch[0]
    # and it is not ALSO promised as an ordinary install
    assert not [s for s in steps
                if s.startswith("Install in WSL") and "qemu-user-static" in s]


def test_a_package_that_cannot_be_fetched_still_takes_the_button_away():
    """The fetch is allowed for one package because it depends on nothing.
    Everything else is still a dead end, and must still read like one."""
    facts = _facts(**_NOCAND_HARD)
    assert emulate_core.setup_fetchable(facts) == []
    assert not emulate_core.setup_fixable(facts)
    text = setup_notice(facts, can_fix=True)
    assert "installs those in WSL" not in text
    assert "wsl --install -d %s" % emulate_core.KNOWN_GOOD_DISTRO in text
    assert "wsl --set-default %s" % emulate_core.KNOWN_GOOD_DISTRO in text


def test_a_rig_that_never_heard_of_xrel_promises_nothing():
    """`xrel` is new.  An older setupcheck.sh must not have its silence read
    as "yes, fetch it" - that would promise a repair that never happens."""
    assert emulate_core.setup_fetchable(_facts(qemu="0")) == []
    assert emulate_core.setup_fetchable(None) == []
    old = _facts(**dict(_NOCAND, xrel=None))
    del old["xrel"]
    assert not emulate_core.setup_fixable(old)


def test_the_button_stays_when_any_of_it_can_still_be_installed():
    """One unavailable package out of two is not a dead end - installing the
    other is still progress, and one at a time is what the rig now does."""
    facts = _facts(qemu="0", armgcc="0", binfmt="0",
                   nocand="qemu-user-static", universe="1", indexed="1")
    assert emulate_core.setup_fixable(facts)
    assert "installs those in WSL" in setup_notice(facts, can_fix=True)


def test_universe_is_still_the_repair_it_was_made_in_pad_41():
    """The new dead-end path must not swallow the case that HAS a fix."""
    facts = _facts(qemu="0", binfmt="0", nocand="qemu-user-static",
                   universe="0", indexed="1")
    assert emulate_core.setup_fixable(facts)
    assert "turns universe back on" in setup_notice(facts, can_fix=True)


def test_printed_advice_leaves_out_a_package_apt_has_no_version_of():
    """`apt install a b` is all or nothing, so naming an uninstallable
    package in the printed command installs neither.  That is the PAD-41 bug,
    still living in the advice the app prints on Linux."""
    text = setup_notice(_facts(qemu="0", armgcc="0", binfmt="1",
                               nocand="qemu-user-static", universe="1",
                               indexed="1"), can_fix=False)
    assert "sudo apt install gcc-arm-linux-gnueabihf" in text
    assert "apt install qemu-user-static" not in text


def test_an_empty_apt_index_is_not_evidence_against_the_sources():
    """The probe must not answer either question out of metadata it does not
    have; setupfix.sh's `apt-get update` is what makes them answerable."""
    check = _rig_text("setupcheck.sh")
    assert 'echo "indexed=$indexed"' in check
    # The loop that fills `nocand` must be behind the index gate.
    lines = [ln for ln in check.splitlines() if not ln.lstrip().startswith("#")]
    start = next(i for i, ln in enumerate(lines) if 'if [ -n "$need" ]' in ln)
    cond = " ".join(lines[start:start + 3])
    assert '[ "$indexed" = 1 ]' in cond, \
        "nocand is still computed off an index that may not be there: " + cond
    # ...and universe is judged from what apt reports it has, not re-probed.
    assert "printf '%s\\n' $components | grep -qx universe" in check


def test_the_probe_reports_the_release_it_is_talking_about():
    check = _rig_text("setupcheck.sh")
    for key in ("indexed=", "components=", "distro="):
        assert "echo \"%s" % key in check or "echo %s" % key in check, key


def test_the_repair_stops_naming_causes_it_never_checked():
    fix = _rig_text("setupfix.sh")
    body = "\n".join(ln for ln in fix.splitlines()
                     if not ln.lstrip().startswith("#"))
    for guess in ("out of support", "have been trimmed",
                  "installing a current Ubuntu"):
        assert guess not in body, guess
    # and it says the release instead
    assert '_get "$f" distro' in fix
    assert '_get "$f" components' in fix


def test_an_update_that_failed_is_not_evidence_the_release_lacks_it():
    """"This release does not publish the package" can only be said about an
    index that was actually refreshed.  An unreachable archive looks exactly
    the same from `apt-cache policy`."""
    fix = _rig_text("setupfix.sh")
    assert "updated=1" in fix and "updated=0" in fix
    assert 'if _run apt-get update -qq; then' in fix


def test_the_two_halves_agree_on_the_fallback_release():
    """One release, three spellings: the distro name a user types at wsl.exe,
    the suite apt knows it by, and the version the tab says out loud."""
    fix = _rig_text("setupfix.sh")
    assert "PAD_KNOWN_GOOD_DISTRO=%s" % emulate_core.KNOWN_GOOD_DISTRO in fix
    assert emulate_core.FALLBACK_RELEASE == "24.04"
    assert "PAD_FALLBACK_SUITE=noble" in fix


def test_the_installer_puts_a_machine_on_the_release_the_app_names():
    """PAD-114, and the third half of the same fact.  The prerequisite
    installer asked wsl.exe for `-d Ubuntu`, which is the TRACKING name: it
    installs whichever LTS is current that month.  So the installer could put
    a new machine on one release while every hint the app gives names another
    - including the suite the rig's cross-release package fetch downloads
    from, which is pinned to exactly one.

    The plain name survives as the FALLBACK, and it has two jobs: a Store with
    no entry for this exact release, and a machine where this exact name is
    already registered (the dead distro this installer reports just above),
    where the pinned install can only answer "already exists".

    Since PAD-164 the name is chosen rather than hardcoded, because a name the
    machine's own wsl.exe has never heard of installs nothing at all - so what
    is asserted here is that the pin still WINS whenever the machine offers
    it, which is the property this test was written for."""
    ps1 = (pathlib.Path(DEFAULT_RIG_DIR).parent.parent / "installer"
           / "install_prerequisites.ps1").read_text(encoding="utf-8")
    assert '$PadKnownGoodDistro = "%s"' % emulate_core.KNOWN_GOOD_DISTRO in ps1
    assert ("if (@($Online) -contains $PadKnownGoodDistro) "
            "{ return $PadKnownGoodDistro }") in ps1, (
        "the pinned release must still be what gets installed on any machine "
        "whose wsl.exe offers it (PAD-114)")
    assert '@("--install", "-d", $distro)' in ps1
    assert '@("--install", "-d", "Ubuntu")' in ps1, "the fallback is still there"
    # ...and it is reached only after a non-zero exit, so an install that
    # merely wants its first-run setup finished never becomes a second distro.
    # Checked at EVERY call site: PAD-164 added a second one, in the branch
    # that runs on a machine with no WSL at all.
    runs = [i for i in range(len(ps1))
            if ps1.startswith("& wsl $plan.FallbackArgs", i)]
    assert runs, "the fallback is actually run"
    for i in runs:
        # The nearest `if (` above the call is the block it lives in.
        cond = ps1[:i][ps1[:i].rindex("if ("):]
        assert "$installExit -ne 0" in cond, cond
    # No hint anywhere still sends a person to the tracking name by hand.
    assert "wsl --install -d Ubuntu\"" not in ps1
    assert "wsl --set-default Ubuntu\"" not in ps1


def test_only_a_package_that_depends_on_nothing_is_cross_installed():
    """THE SAFETY PROPERTY.  A .deb from another release drags its dependency
    chain in with it, which is how "the emulator will not start" becomes "apt
    is broken".  qemu-user-static is exempt because its Depends is empty - and
    that is re-read off the DOWNLOADED FILE, so the flag in setupcheck.sh can
    only narrow what is attempted, never widen what is allowed."""
    check = _rig_text("setupcheck.sh")
    flagged = [ln.split(":")[2] for ln in check.splitlines()
               if ln.count(":") == 3 and ln.rstrip().endswith(":1")]
    assert flagged == ["qemu-user-static"], flagged
    fix = _rig_text("setupfix.sh")
    assert "dpkg-deb -f \"$deb\" Depends" in fix
    assert "dpkg-deb -f \"$deb\" Pre-Depends" in fix
    gate = fix.split("dpkg-deb -f \"$deb\" Depends", 1)[1]
    assert gate.index('[ -n "$deps$predeps" ]') < gate.index("dpkg -i"), \
        "the dependency gate must come before the install, not after"


# ----------------------------------------------------------------------
# ★ PAD-139: Ubuntu 26.04 has no qemu-user-static.
#
# Debian's qemu merged the static build into qemu-user (9.1), dropped the
# `-static` compatibility links (9.2) and deleted the qemu-user-static package
# (10.0.3), leaving a VIRTUAL name that qemu-user-binfmt provides.  26.04 LTS
# carries that qemu.  So the rig looked for a file that release never has, apt
# refused the name, and the tab told the user his release "does not publish"
# the package and promised to fetch 24.04's - a package 26.04's own
# qemu-user-binfmt declares Breaks against.
# ----------------------------------------------------------------------

#: The fixed setupcheck.sh's answer inside a real Ubuntu 26.04.1 userland with
#: no qemu installed (ubuntu-base, `apt-get update` against the resolute
#: archive), on a machine whose handler is registered - the reporter's shape.
_RESOLUTE = dict(qemu="0", pkg_qemu="qemu-user-binfmt", binfmt="1",
                 indexed="1", nocand="", xrel="", universe="1",
                 components="main multiverse restricted universe",
                 distro="ubuntu 26.04 resolute")


def test_the_tab_names_the_package_this_release_installs():
    facts = _facts(**_RESOLUTE)
    missing, _ = setup_summary(facts)
    assert [pkg for pkg, _ in missing] == ["qemu-user-binfmt"]
    text = setup_notice(facts, can_fix=True)
    assert "qemu-user-binfmt — runs the machine's own 32-bit ARM" in text
    assert "installs those in WSL" in text
    # Not one word of what the reporter was told.
    for said in ("qemu-user-static", "does not publish",
                 "Ubuntu %s's archive" % emulate_core.FALLBACK_RELEASE):
        assert said not in text, (said, text)
    # THE CONSENT IS THE NAME apt WILL BE GIVEN, and nothing fetched.
    assert emulate_core.setup_fix_steps(facts) == [
        "Install in WSL:  qemu-user-binfmt"]
    # ...and the command a Linux desktop is told to type is one apt accepts.
    assert "sudo apt install qemu-user-binfmt" in setup_notice(facts,
                                                               can_fix=False)


def test_a_rig_that_never_heard_of_pkg_keeps_the_tables_spelling():
    """Absent keys accuse nobody - and rename nothing."""
    missing, _ = setup_summary(_facts(qemu="0"))
    assert [pkg for pkg, _ in missing] == ["qemu-user-static"]
    assert emulate_core._apt_name(None, "qemu", "qemu-user-static") == \
        "qemu-user-static"


def test_the_rig_asks_for_the_interpreter_and_apt_for_its_name():
    """The product scripts must not look for `qemu-arm-static` by name, and
    what they install has to be asked of apt after the index exists."""
    for name in ("setupcheck.sh", "run_game.sh"):
        body = "\n".join(ln for ln in _rig_text(name).splitlines()
                         if not ln.lstrip().startswith("#"))
        assert "command -v qemu-arm-static" not in body, name
        assert "pad_qemu_arm" in body, name
    check = _rig_text("setupcheck.sh")
    assert "qemu:@pad_qemu_arm:qemu-user-static:1" in check
    assert "pad_apt_name" in check and '"pkg_$_key=' in check
    fix = _rig_text("setupfix.sh")
    assert "pad_apt_name" in fix.split("if _run apt-get update -qq; then", 1)[1], \
        "setupfix.sh spells the packages before there is an index to ask"
    assert "$(pad_apt_name qemu-user-static)" in _rig_text("ensurebuild.sh")


@pytest.mark.skipif(not HAS_BASH, reason="no working bash")
def test_pad_qemu_arm_and_pad_apt_name_on_both_releases():
    r"""The two rig functions against fakes shaped like the real thing.

    `apt-cache` answers are copied from Ubuntu 24.04 (David's WSL) and from a
    26.04.1 ubuntu-base after `apt-get update`; `ldd` answers are what glibc's
    prints for a static-pie qemu and for 24.04's dynamic qemu-arm.  Any dir on
    the host PATH that holds a real qemu is dropped first, so the answers do
    not depend on the machine running the test.  Fed on stdin, whole, for the
    reason test_emulate_setup_check.py gives: `bash` is git-bash on one
    Windows host and the WSL launcher on the next.
    """
    harness = r"""
tmp=$(mktemp -d) || exit 1
mkdir -p "$tmp/bin" "$tmp/static" "$tmp/dynamic" "$tmp/old" "$tmp/aptbin"
clean=
IFS=:
for d in $PATH; do
    [ -e "$d/qemu-arm-static" ] || [ -e "$d/qemu-arm" ] || clean="$clean:$d"
done
unset IFS
for t in head grep sed; do
    p=$(command -v "$t") || continue
    case ":$clean:" in *":${p%/*}:"*) ;; *) ln -s "$p" "$tmp/bin/$t" ;; esac
done
base=$tmp/bin$clean
for f in static/qemu-arm dynamic/qemu-arm old/qemu-arm-static; do
    printf '\177ELF fake' > "$tmp/$f"; chmod +x "$tmp/$f"
done
printf '#!/bin/sh\ncase "$1" in\n*/dynamic/*) printf "\\tlinux-vdso.so.1 (0x1)\\n\\tlibglib-2.0.so.0 => /lib/libglib-2.0.so.0 (0x2)\\n" ;;\n*) printf "\\tstatically linked\\n" ;;\nesac\n' > "$tmp/bin/ldd"
chmod +x "$tmp/bin/ldd"
echo "--- qemu"
echo "static=[$(PATH=$tmp/static:$base; pad_qemu_arm)]"
echo "dynamic=[$(PATH=$tmp/dynamic:$base; pad_qemu_arm)]"
echo "old=[$(PATH=$tmp/old:$tmp/dynamic:$base; pad_qemu_arm)]"
echo "none=[$(PATH=$base; pad_qemu_arm)]"

printf '#!/bin/sh\ncase $1 in policy) f="$FAKE/policy.$3" ;; show) f="$FAKE/show.$2" ;; esac\n[ -f "$f" ] && cat "$f"\nexit 0\n' > "$tmp/aptbin/apt-cache"
chmod +x "$tmp/aptbin/apt-cache"
mkdir -p "$tmp/resolute" "$tmp/noble" "$tmp/cold" "$tmp/lookalike"
printf 'qemu-user-static:\n  Installed: (none)\n  Candidate: (none)\n  Version table:\n' > "$tmp/resolute/policy.qemu-user-static"
printf 'qemu-user-binfmt:\n  Installed: (none)\n  Candidate: 1:10.2.1+ds-1ubuntu3.2\n' > "$tmp/resolute/policy.qemu-user-binfmt"
printf 'Package: qemu-user-binfmt\nReplaces: qemu-user-binfmt-hwe, qemu-user-static (<< 1:9.1.0)\nProvides: qemu-user-static\nBreaks: qemu-user-static\n' > "$tmp/resolute/show.qemu-user-binfmt"
printf 'qemu-user-static:\n  Installed: (none)\n  Candidate: 1:8.2.2+ds-0ubuntu1.18\n' > "$tmp/noble/policy.qemu-user-static"
printf 'qemu-user-binfmt:\n  Installed: (none)\n  Candidate: 1:8.2.2+ds-0ubuntu1.18\n' > "$tmp/noble/policy.qemu-user-binfmt"
printf 'Package: qemu-user-binfmt\nDepends: qemu-user (= 1:8.2.2+ds-0ubuntu1.18)\nConflicts: qemu-user-static\n' > "$tmp/noble/show.qemu-user-binfmt"
cp "$tmp/resolute/policy."* "$tmp/lookalike/"
printf 'Package: qemu-user-binfmt\nProvides: qemu-user-static-binfmt\n' > "$tmp/lookalike/show.qemu-user-binfmt"
echo "--- apt"
for shape in resolute noble cold lookalike; do
    echo "$shape=[$(export FAKE=$tmp/$shape; PATH=$tmp/aptbin:$PATH; pad_apt_name qemu-user-static)]"
done
echo "other=[$(export FAKE=$tmp/resolute; PATH=$tmp/aptbin:$PATH; pad_apt_name ffmpeg)]"
rm -rf "$tmp"
"""
    import subprocess
    src = _rig_text("padpath.sh")
    out = subprocess.run(["bash", "-s"], input=(src + harness).encode("utf-8"),
                         capture_output=True, timeout=120)
    said = out.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace") + said
    assert "--- apt" in said, said
    got = dict(ln.split("=", 1) for ln in said.splitlines() if "=[" in ln)
    # 26.04: plain qemu-arm, static, is the interpreter.
    assert got["static"].endswith("/static/qemu-arm]"), got
    # 24.04's qemu-user: a DYNAMIC qemu-arm cannot be copied into a guest.
    assert got["dynamic"] == "[]", got
    # Wherever the -static name exists it wins.
    assert got["old"].endswith("/old/qemu-arm-static]"), got
    assert got["none"] == "[]", got
    # apt's answer, not a release number.
    assert got["resolute"] == "[qemu-user-binfmt]", got
    assert got["noble"] == "[qemu-user-static]", got
    assert got["cold"] == "[qemu-user-static]", "no index is not evidence"
    assert got["lookalike"] == "[qemu-user-static]", got
    assert got["other"] == "[ffmpeg]", got


def test_the_fetch_leaves_the_machine_s_package_sources_alone():
    """The sources-editing version of this idea fails open: a cleanup that is
    skipped leaves a foreign repository on the machine, and every apt-get
    upgrade from then on is pulling from the wrong release.  apt is run
    against a throwaway root instead, so there is no cleanup to skip."""
    fix = _rig_text("setupfix.sh")
    body = fix.split("_fetch_foreign() {", 1)[1].split("\n}", 1)[0]
    for override in ("Dir::Etc::sourcelist=", "Dir::Etc::sourceparts=/dev/null",
                     "Dir::State::lists=", "Dir::Cache="):
        assert override in body, override
    assert "/etc/apt" not in body, "the fetch must not touch the real sources"
    assert 'rm -rf "$t"' in body


def test_the_fetch_uses_the_mirror_apt_is_already_configured_with():
    """Someone on a country mirror or on ports.ubuntu.com has that for a
    reason, and the pool is the same on all of them."""
    body = _rig_text("setupfix.sh").split("_fetch_foreign() {", 1)[1]
    assert "REPO_URI" in body.split("\n}", 1)[0]
    assert "ports.ubuntu.com" in body, "no fallback for non-x86 hosts"


def test_the_probe_reuses_the_rig_s_own_binfmt_detection():
    """setupcheck.sh must not grow its own copy of "is there an ARM handler" -
    ensurebuild.sh owns that, and the run itself uses ensurebuild's."""
    check = _rig_text("setupcheck.sh")
    assert "ensurebuild.sh" in check


def test_the_tab_and_the_run_agree_on_what_a_usable_compiler_is():
    """Same rule, and for the same reason: the prediction the tab makes before
    Start and the decision the run makes half a minute later have to be one
    function, or the tab clears a machine the build then refuses.

    `command -v gcc` in either place is the specific way that goes wrong - it
    passes a WSL that has the compiler and none of its headers."""
    check = _rig_text("setupcheck.sh")
    ensure = _rig_text("ensurebuild.sh")
    assert "_pad_cc_works" in ensure, "the run's own test has to be a function"
    assert "@_pad_cc_works" in check, "setupcheck must call it, not re-ask"
    bridge = ensure.split("pad_ensure_bridge() {", 1)[1].split("\n}", 1)[0]
    assert "command -v gcc" not in bridge, (
        "the renderer's guard is back to a PATH lookup")
    assert bridge.count("_pad_cc_works") == 2, (
        "both the missing and the stale branch decide it the same way")
    assert "_pad_binfmt_arm" in check
    assert "_pad_binfmt_advice" in check
    assert "binfmt_misc/qemu-arm" not in check, "that is a second detector"


# ---------------------------------------------------------------------------
# Per-game save-state scoping (item 33 territory, David 2026-08-10: "you
# can't load a venom save state for john wick"). The title is derived from
# the picked card's filename the same way the rig names its card cache:
# everything up to the first dash-digit of the basename.
# ---------------------------------------------------------------------------

def _tab_with_card(path):
    from pinball_decryptor.webui.tabs.emulate import EmulateTab
    tab = object.__new__(EmulateTab)
    tab.emulate_card_var = SimpleNamespace(get=lambda: path)
    return tab


def test_card_game_derives_the_title_from_the_filename():
    t = _tab_with_card(r"D:\imgs\star_wars_le-1_30_0.Release.8G.sdcard.raw")
    assert t._card_game() == "star_wars_le"


def test_card_game_survives_suffixed_and_upscaled_names():
    t = _tab_with_card(
        r"C:\x\turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw")
    assert t._card_game() == "turtles_pro"


def test_card_game_is_case_insensitive_and_strips_quotes():
    t = _tab_with_card(r'  "d:\y\GODZILLA_PRO-1_15_0_spike2.raw"  ')
    assert t._card_game() == "godzilla_pro"


def test_card_game_answers_none_rather_than_guessing():
    assert _tab_with_card("")._card_game() is None
    assert _tab_with_card(r"C:\x\NoVersionShape.raw")._card_game() is None


# ---------------------------------------------------------------------------
# "Reset windows" (item 37, David 2026-08-10: "button on emulate tab to reset
# window positions of emulator to default (in case they are off-screen somehow
# or messed up from multi-monitor setups)").
#
# The rig-side half lives in winreset.sh and is tested by running it; what is
# testable here is the half the app owns - the Windows-side playfield state,
# where the playfield really is a Windows process and no script inside WSL can
# reach its home - plus the gate, because a reset under a live run is written
# straight back by padglhost and would report a success that never happened.
# ---------------------------------------------------------------------------

def _pf_state(monkeypatch, tmp_path, text):
    p = tmp_path / ".pad_playfield.json"
    if text is None:
        if p.exists():
            p.unlink()
    else:
        p.write_text(text)
    monkeypatch.setattr(emulate_rig, "PF_STATE", str(p))
    return p


def test_forget_playfield_pos_takes_only_that_key(monkeypatch, tmp_path):
    """Other playfield state survives: taking the whole file would be a
    second, silent reset nobody asked for."""
    import json as _json
    p = _pf_state(monkeypatch, tmp_path,
                  '{"playfield_pos": [-1800, 300], "keep_me": 7}')
    msg = emulate_rig.forget_playfield_pos()
    assert msg and "-1800" in msg
    assert _json.loads(p.read_text()) == {"keep_me": 7}


def test_forget_playfield_pos_is_quiet_when_there_is_nothing_to_forget(
        monkeypatch, tmp_path):
    """Absent key, absent file and junk all answer None rather than raising -
    the button runs on machines that have never opened a playfield."""
    _pf_state(monkeypatch, tmp_path, '{"keep_me": 7}')
    assert emulate_rig.forget_playfield_pos() is None
    _pf_state(monkeypatch, tmp_path, None)
    assert emulate_rig.forget_playfield_pos() is None
    _pf_state(monkeypatch, tmp_path, "not json at all")
    assert emulate_rig.forget_playfield_pos() is None


def test_forget_playfield_pos_leaves_a_non_dict_alone(monkeypatch, tmp_path):
    """Valid JSON that is not an object is still not ours to rewrite."""
    p = _pf_state(monkeypatch, tmp_path, '[1, 2, 3]')
    assert emulate_rig.forget_playfield_pos() is None
    assert p.read_text() == '[1, 2, 3]'


# ----------------------------------------------------------------------
# THE MACHINE WHOSE WSL CANNOT START A WINDOWS PROGRAM.
#
# The virtual playfield is a Windows process, because this WSL has no Tk of
# any kind, and watch.sh launches it through interop.  A user's distro has
# `[interop] enabled=false` in /etc/wsl.conf, so his window could never open
# itself and the rig's only answer was a command to type before every run.
#
# Interop is LINUX -> WINDOWS.  Windows -> Linux (`wsl.exe`) is unaffected by
# that switch, so everything the window DOES once it is up still works - only
# the launch cannot cross.  PAD is already on the far side, so the run asks
# and PAD opens it.
# ----------------------------------------------------------------------

_LAUNCH = (r"PAD_PLAYFIELD_WINDOWS_LAUNCH game=godzilla_pro savestates=1 "
           r"root=\\wsl.localhost\Ubuntu\home\david\spike2root "
           r"tables=\\wsl.localhost\Ubuntu\home\david\spike2root\dump\tables")


def test_the_launch_token_carries_the_title_and_both_paths():
    got = emulate_core.playfield_launch(_LAUNCH)
    assert got["game"] == "godzilla_pro"
    assert got["savestates"] == "1"
    # The paths are the pair WSLENV's /p would have translated during the
    # interop exec that is not happening - already in Windows form, and
    # entitled to contain a space, which is why the split is on the KEYS.
    assert got["root"] == r"\\wsl.localhost\Ubuntu\home\david\spike2root"
    assert got["tables"].endswith(r"\dump\tables")


def test_the_token_is_found_inside_the_log_line_it_arrives_on():
    """It is read off watch.sh's stdout, which the tab has already prefixed
    for its log pane."""
    assert emulate_core.playfield_launch("[emulate] " + _LAUNCH)["game"] \
        == "godzilla_pro"


def test_a_path_with_a_space_survives_the_parse():
    got = emulate_core.playfield_launch(
        r"PAD_PLAYFIELD_WINDOWS_LAUNCH game=jaws_pro savestates=0 "
        r"root=\\wsl.localhost\Ubuntu\home\d v\spike2root tables=")
    assert got["root"].endswith(r"\home\d v\spike2root")
    assert got["savestates"] == "0"


def test_an_ordinary_log_line_is_not_a_launch_request():
    """Every line of the run's output goes through this."""
    for line in ("[watch] virtual playfield window opening",
                 "[watch] the game never started.", "", "state=attract"):
        assert emulate_core.playfield_launch(line) is None
    # ...and neither is the token with nothing to launch.
    assert emulate_core.playfield_launch(
        "PAD_PLAYFIELD_WINDOWS_LAUNCH savestates=1") is None


# ----------------------------------------------------------------------
# Item 74: a first boot copies the card BEFORE the guest starts, and
# cardmount.sh narrates it one line every 2 s.  The drain thread turns those
# lines into the state label, because status.sh's honest "Not running" during
# the copy is exactly the looks-like-a-hang this item exists to remove.
# ----------------------------------------------------------------------

def test_a_copy_progress_line_becomes_a_state_label():
    got = emulate_core.card_copy_progress(
        "[card] copying godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw: "
        "3121 / 7497 MB (41%)")
    assert got == "Copying card: 3121 / 7497 MB (41%)"


def test_a_card_name_with_spaces_survives_the_parse():
    """'Heisei Custom Image Premium V1.raw' is a real card on the desk."""
    got = emulate_core.card_copy_progress(
        "[card] copying Heisei Custom Image Premium V1.raw: 0 / 7497 MB (0%)")
    assert got == "Copying card: 0 / 7497 MB (0%)"


def test_ordinary_card_lines_are_not_copy_progress():
    """The verdict lines that FOLLOW the progress must parse as None — the
    drain uses that edge to stop showing a copy that has finished."""
    for line in ("[card] using local cache /home/david/cardcache/x.raw",
                 "[card] local cache ready - booting from it",
                 "[card] cache not usable - booting from the original",
                 "[card] caching x.raw to the WSL disk in the background",
                 "[card] copy stalled - booting from the original instead "
                 "(copy continues)",
                 "", "state=attract"):
        assert emulate_core.card_copy_progress(line) is None


# ----------------------------------------------------------------------
# Item 77: the Card cache manager.  The list format is cardmount.sh's
# --cache-list — tab separated, source LAST, because labels and source
# paths are entitled to spaces ("Heisei Custom Image Premium V1" is real).
# ----------------------------------------------------------------------

_CACHE_LIST = (
    "entry\talpha\t3072\t7168\t1787000000\t/mnt/d/cards/alpha.raw\n"
    "entry\tbeta card\t5242880\t7761920\t0\t/mnt/c/spaced dir/beta card.raw\n"
    "entry\tgamma\t2048\t2048\t1786000000\t\n"
    "disk\t29355388\t263114392\n")


def test_cache_list_parses_and_sorts_biggest_first():
    entries, disk = emulate_core.parse_cache_list(_CACHE_LIST)
    assert [e["label"] for e in entries] == ["beta card", "alpha", "gamma"]
    assert entries[0]["real_kb"] == 5242880
    assert entries[0]["src"] == "/mnt/c/spaced dir/beta card.raw"
    # boot 0 means no sidecar yet — rendered as "never", never as 1970.
    assert entries[0]["boot"] == 0
    assert disk == (29355388, 263114392)


def test_cache_list_survives_garbage_and_emptiness():
    assert emulate_core.parse_cache_list("") == ([], None)
    entries, disk = emulate_core.parse_cache_list(
        "noise\nentry\tbad\tNaN\t1\t2\tx\ndisk\ta\tb\n" + _CACHE_LIST)
    assert len(entries) == 3 and disk is not None


def test_cache_sizes_and_boot_render_for_humans():
    assert emulate_core.human_size(5242880) == "5.0 GB"
    assert emulate_core.human_size(2048) == "2 MB"
    assert emulate_core.cache_boot_text(0) == "never"
    assert emulate_core.cache_boot_text(1787000000).startswith("20")


# ----------------------------------------------------------------------
# Item 78: the footer bar under the notebook carries the EMULATION's
# loading state while the Emulate tab is showing — the panel dispatches
# semantic kinds and the window renders them.  These test the dispatch.
# ----------------------------------------------------------------------


def test_the_interpreter_is_never_the_frozen_app_itself(monkeypatch):
    """sys.executable is the answer on the Windows build (the app runs on the
    Python bundled beside it) and a TRAP in a frozen one, where it is PAD.exe
    - handing that a script path starts a second copy of PAD."""
    monkeypatch.setattr(emulate_core.sys, "frozen", True, raising=False)
    monkeypatch.setattr(emulate_core.sys, "executable",
                        r"C:\Program Files\PAD\PAD.exe")
    monkeypatch.setattr(emulate_core.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(emulate_core.shutil, "which", lambda n: None)
    got = emulate_core.windows_python()
    assert got and got.lower().endswith("pythonw.exe"), got
    assert "PAD.exe" not in got


def test_the_interpreter_prefers_the_windowed_twin_of_the_running_one(
        monkeypatch):
    """python.exe would put a black console beside the playfield."""
    monkeypatch.setattr(emulate_core.sys, "frozen", False, raising=False)
    monkeypatch.setattr(emulate_core.sys, "executable", r"C:\Py\python.exe")
    monkeypatch.setattr(emulate_core.os.path, "isfile", lambda p: True)
    assert emulate_core.windows_python() == r"C:\Py\pythonw.exe"


def test_no_interpreter_at_all_is_said_rather_than_guessed(monkeypatch):
    """A wrong guess here launches something that is not Python."""
    monkeypatch.setattr(emulate_core.sys, "frozen", False, raising=False)
    monkeypatch.setattr(emulate_core.sys, "executable", "")
    monkeypatch.setattr(emulate_core.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(emulate_core.shutil, "which", lambda n: None)
    assert emulate_core.windows_python() is None


def test_the_path_search_does_not_go_through_a_platform_aware_helper(
        monkeypatch, tmp_path):
    """shutil.which BRANCHES ON sys.platform, and its win32 branch reaches for
    a `_winapi` that is None everywhere else - so the moment that call landed
    in the Windows launch path, every test that walks that path by faking the
    platform died inside the standard library on the Linux and macOS runners,
    and the shape went unchecked on two machines out of three.  The lookup
    walks PATH itself; the names are spelled with their extension, so there is
    nothing else which() was doing for us."""
    def boom(_name):
        raise AttributeError("'NoneType' object has no attribute "
                             "'NeedCurrentDirectoryForExePath'")

    monkeypatch.setattr(emulate_core.shutil, "which", boom)
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    monkeypatch.setattr(emulate_core.sys, "frozen", False, raising=False)
    monkeypatch.setattr(emulate_core.sys, "executable", "")
    monkeypatch.setenv("PATH", str(tmp_path))
    # Nothing on PATH is an ANSWER, not a crash.
    assert emulate_core.windows_python() is None
    # ...and with the interpreter there, PATH is what finds it.
    exe = tmp_path / "python.exe"
    exe.write_text("")
    assert emulate_core.windows_python(console=True) == str(exe)
    # Which is what makes the whole Windows launch shape reachable from any
    # host again - the thing the fake platform is there to test.
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    assert emulate_core.rig_cmd("watch.sh", 30)[:2] == ["wsl.exe", "-e"]


def test_a_playfield_that_stops_leaves_something_to_read():
    """The ORDINARY launch, which is watch.sh's own and not this tab's.

    Reported 2026-08-11: "starting Bond Pro was missing the keys window and
    playfield", with a full run log in which not one line was about the
    playfield.  It could not be: the launch was `... >/dev/null 2>&1 &`, so a
    window that died on its first line and a window the user closed produced
    exactly the same evidence, which is none.  Since item 39 retired the
    Controls window into that window's key panel, it takes the key list with
    it - which is why the report names two windows and not one.
    """
    body = "\n".join(ln for ln in _rig_text("watch.sh").splitlines()
                     if not ln.lstrip().startswith("#"))
    # Both launches - the Linux desktop's local Tk process and WSL's Windows
    # one through interop - write where a human can read it afterwards, the
    # same rule autoattract.sh and ballfeed.py have always followed.
    for launch in ('"$RIG/playfield.py" "$GAME" $PF_STATES',
                   '"$PF_WIN" "$GAME" $PF_STATES'):
        lines = [ln for ln in body.splitlines() if launch in ln]
        assert len(lines) == 1, "watch.sh no longer launches it this way"
        assert '>>"$PFLOG" 2>&1' in lines[0], (
            "the playfield's own output goes nowhere again")
        assert ">/dev/null 2>&1 &" not in lines[0]
    # ...and the run ASKS, once, whether it stayed up. Only for a window the
    # RUN launched: the one PAD opens has no process on that side to find,
    # and the app reports its own failures.
    assert body.count("PF_LAUNCHED=1") == 2, "one per launch, and only there"
    assert '[ "${PF_LAUNCHED:-0}" = 1 ] && ! pf_up' in body
    assert body.index('[ "${PF_LAUNCHED:-0}" = 1 ]') > body.index("PF_LAUNCHED=1"), (
        "the check has to come after the launch it is about")
    # An empty log is a different fault from a traceback - the interpreter
    # never ran the script at all - and is worth its own sentence.
    check = body[body.index('[ "${PF_LAUNCHED:-0}" = 1 ]'):]
    assert '-s "$PFLOG"' in check and "never ran it" in check


# ----------------------------------------------------------------------
# ...AND THE OTHER HALF OF A SAVE STATE, WHICH APT CANNOT SUPPLY.
#
# PAD-53 made a missing busybox-static cost the feature instead of the run.
# A machine that then installed busybox-static STILL had no save states:
# criu was a hard-coded /var/tmp/criubuild/... in eight rig scripts, and no
# Ubuntu publishes criu at all (`apt-cache policy criu` -> empty version
# table).  It is built from source instead, and the tab has to say so without
# ever handing that name to apt.
# ----------------------------------------------------------------------

_CRIU_FACTS = {"iswsl": "1", "qemu": "1", "armgcc": "1", "nativecc": "1",
               "debugfs": "1", "fuse": "1", "ffmpeg": "1", "busybox": "1",
               "criu": "0", "binfmt": "1", "universe": "1", "nocand": ""}


def test_a_machine_missing_only_criu_still_runs_the_emulator():
    """The notice must not tell a working PC that it cannot emulate."""
    assert setup_ok(_CRIU_FACTS)
    assert not setup_settled(_CRIU_FACTS)
    notice = setup_notice(_CRIU_FACTS, can_fix=True)
    assert notice.startswith("The emulator runs on this PC.")
    assert "criu" in notice


def test_criu_is_never_offered_as_a_package_to_install():
    """No Ubuntu publishes it: `apt install criu` cannot work anywhere, and
    naming it beside a real package fails that one too."""
    steps = emulate_core.setup_fix_steps(_CRIU_FACTS)
    assert steps and all("Install in WSL:  criu" not in s for s in steps)
    assert any("Build criu from source" in s for s in steps), steps
    # The consent has to say what a build costs - it is minutes and a
    # download, not an apt install.
    build = [s for s in steps if "Build criu" in s][0]
    assert "GitHub" in build and "minutes" in build


def test_the_button_stays_for_a_machine_whose_only_gap_is_criu():
    """It can build it, so there is something to press."""
    assert emulate_core.setup_fixable(_CRIU_FACTS)
    assert "Set up emulator" in setup_notice(_CRIU_FACTS, can_fix=True)


def test_both_save_state_pieces_are_named_when_both_are_missing():
    facts = dict(_CRIU_FACTS, busybox="0")
    extras = [p for p, _ in setup_extras(facts)]
    assert extras == ["busybox-static", "criu"]
    steps = emulate_core.setup_fix_steps(facts)
    assert any(s.startswith("Install in WSL:") and "busybox-static" in s
               for s in steps)
    assert any("Build criu" in s for s in steps)


def test_printed_advice_never_names_a_package_that_does_not_exist():
    """`sudo apt install criu` is advice that cannot work on any Ubuntu."""
    facts = dict(_CRIU_FACTS, ffmpeg="0", busybox="0")
    notice = setup_notice(facts, can_fix=False)
    assert "apt install criu" not in notice
    assert "apt install ffmpeg busybox-static" in notice
    assert "getcriu.sh" in notice


def test_a_rig_that_never_heard_of_criu_accuses_nobody():
    """An older rig emits no `criu` line, and silence is not a missing
    program - the same rule every other fact here follows."""
    facts = dict(_CRIU_FACTS)
    del facts["criu"]
    assert setup_extras(facts) == []
    assert emulate_core.setup_built(facts) == []
    assert setup_settled(facts)


# ----------------------------------------------------------------------
# What the app's own WSL restart leaves behind
#
# Reported 2026-08-12 (Pinside, #151-#153).  A tester's run stopped on an
# unset DISPLAY; the cure offered was "Restart WSL…" on this tab; and his
# NEXT run stopped on
#
#     chroot: failed to run command '/bin/sh': Exec format error
#
# because the kernel's 32-bit ARM registration lives in the RUNNING kernel
# and his distro does not boot systemd, so the restart took it with it.  The
# tab said nothing about that at all: the setup probe ran once, at build
# time, against the machine as it was BEFORE the restart - so the notice and
# the "Set up emulator…" button that puts the handler back both stayed
# hidden, and what the user got instead was a wall of guest log text telling
# him to edit /etc/wsl.conf by hand.
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# ...and the same fault said from the other side.
#
# When the handler really is gone, the run's own message is what the user
# reads, and it used to be two root commands and an /etc/wsl.conf edit with
# no mention that the app in front of him does both.  The tester on
# 2026-08-12 set about doing it by hand.
# ----------------------------------------------------------------------

def _guest_binfmt_message():
    """The lines pad_ensure_guest_exec prints when no ARM handler exists,
    comments dropped - what the user reads, not what the file explains."""
    text = (pathlib.Path(DEFAULT_RIG_DIR) / "ensurebuild.sh").read_text(
        encoding="utf-8")
    body = text[text.index("no handler registered for 32-bit ARM"):]
    body = body[:body.index("return 1")]
    return "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))


def test_the_guest_message_names_the_button_that_does_all_of_it():
    """One string, two languages: the rig prints the name of a button this
    tab shows, so the two must not drift.  It is checked without its
    ellipsis - the shell writes three dots and the tab one character."""
    said = _guest_binfmt_message()
    assert "Set up emulator" in said
    # The tab's button carries that name (a web label, not a widget now).
    src = pathlib.Path(emulate_web.__file__).read_text(encoding="utf-8")
    assert 'setup_label="Set up emulator…"' in src


def test_the_button_is_offered_before_the_commands_and_only_on_wsl():
    """A Linux desktop has no such button and no free root, so it keeps the
    commands on their own - and where the button does exist it comes first,
    because it is what the reader should do."""
    said = _guest_binfmt_message()
    assert said.index("Set up emulator") < said.index("$(_pad_binfmt_advice)")
    assert 'IS_WSL' in said[:said.index("Set up emulator")], \
        "a Linux desktop is being pointed at a button it does not have"
    # The by-hand route is still printed, for a terminal run and for anyone
    # who wants to see what is being done.
    assert "wsl.conf" in said and "systemd=true" in said


# --- PAD's own Python, handed to the rig (PAD-95) ----------------------------
#
# The rig can only find a Python the USER installed, so a PC with none was told
# there was no Windows Python for the sound to go through and sent to
# python.org - with a `py` command its terminal did not recognise.  The app is
# standing on the Windows side already and every packaged install ships an
# embeddable CPython with pip beside it, so the app says where that is.


def test_the_sound_bridge_asks_for_the_console_twin(monkeypatch):
    """The playfield wants pythonw.exe (no console beside the window); the
    sound bridge wants python.exe - it is a stdio program with the guest's PCM
    piped into it, and python.exe is also the spelling the rig's own search
    produces, so the path handed over and the path reported back match."""
    monkeypatch.setattr(emulate_core.sys, "frozen", False, raising=False)
    monkeypatch.setattr(emulate_core.sys, "executable", r"C:\Py\pythonw.exe")
    monkeypatch.setattr(emulate_core.os.path, "isfile", lambda p: True)
    assert emulate_core.windows_python() == r"C:\Py\pythonw.exe"
    assert emulate_core.windows_python(console=True) == r"C:\Py\python.exe"


def test_the_rig_is_handed_pads_own_python_on_windows(monkeypatch, tmp_path):
    r"""★ PAD-95.  Two scripts need this interpreter and neither can find it:
    setupcheck.sh reports whether this PC has a Windows sound player at all,
    and playaudio.sh plays through one.  It rides every rig call as
    PAD_WINPYTHON, which padpath.sh has always read first - translated to
    /mnt/c on the way, spaces and all, because `C:\Program Files` is where it
    lives on a default install."""
    ours = r"C:\Program Files\PAD\python\python.exe"
    said = "PAD_WINPYTHON=/mnt/c/Program Files/PAD/python/python.exe"
    monkeypatch.setattr(emulate_core, "windows_python",
                        lambda console=False: ours)
    cmd = _cmd_on(monkeypatch, "win32", tmp_path, "setupcheck.sh")
    assert said in cmd, cmd
    assert "env" in cmd, cmd
    # A Windows path never crosses: WSL is handed the POSIX spelling.
    assert not any("\\" in c for c in cmd), cmd
    # The caller's own entries follow it and win any argument.
    cmd = _cmd_on(monkeypatch, "win32", tmp_path, "watch.sh", 30,
                  env=["PAD_CARD=/mnt/c/x.raw"])
    assert cmd.index(said) < cmd.index("PAD_CARD=/mnt/c/x.raw"), cmd
    # ...AND THE CHECKPOINTABLE LAUNCH SAYS IT TOO, because that one is built
    # here rather than by rig_cmd - a run started without it is a run whose
    # sound quietly takes the WSLg path.
    _home(monkeypatch, "/home/somebody")
    cmd = emulate_core.watch_cmd(120, ["PAD_CARD=/mnt/c/x.raw"])
    assert cmd[:3] == ["wsl.exe", "-u", "root"], cmd
    assert said in cmd, cmd
    assert cmd[-1] == "120", cmd


def test_nothing_of_the_sort_off_windows(monkeypatch, tmp_path):
    """There is no interop boundary to hand a Windows .exe across, and the
    container forwards its own variables - so this must not appear at all."""
    monkeypatch.setattr(emulate_core, "windows_python",
                        lambda console=False: r"C:\Py\python.exe")
    for platform in ("linux", "darwin"):
        cmd = _cmd_on(monkeypatch, platform, tmp_path, "watch.sh", 30)
        assert not any(c.startswith("PAD_WINPYTHON") for c in cmd), (
            platform, cmd)


def test_no_interpreter_to_name_leaves_the_rig_as_it_was(monkeypatch,
                                                         tmp_path):
    """Running from a checkout with nothing to point at is not a fault: an
    absent variable is the rig's own search, unchanged."""
    monkeypatch.setattr(emulate_core, "windows_python",
                        lambda console=False: None)
    cmd = _cmd_on(monkeypatch, "win32", tmp_path, "setupcheck.sh")
    assert not any(c.startswith("PAD_WINPYTHON") for c in cmd), cmd
    assert "env" not in cmd, cmd


# --------------------------------------------------------------------------
# Item 90, 2026-09-02: the card ticks the Boot selector box, not the user.
#
# David: "i shouldn't have to check off 'boot selector' in the emulate tab. if
# it has multi-boot, i expect to see the multi-boot screen."  So the tickbox
# stopped being the switch and became the OVERRIDE: the card is asked (one
# `parts.py --multiboot`, off the main thread), the box shows the answer, and
# PAD_SELECT is only sent when the tab has something to say that the rig would
# not work out for itself.
# --------------------------------------------------------------------------

def test_multiboot_cmd_asks_the_rigs_own_tool(monkeypatch, tmp_path):
    """The one definition lives in parts.py; the tab shells it rather than
    re-implementing the test, so the tickbox and the run cannot disagree."""
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    cmd = emulate_core.multiboot_cmd("D:\\cards\\multi.raw")
    assert cmd[:3] == ["wsl.exe", "-e", "python3"], cmd
    assert cmd[3].endswith("/parts.py"), cmd
    assert cmd[-2] == "--multiboot"
    # A Windows path never crosses: WSL is handed the POSIX spelling.
    assert not any("\\" in c for c in cmd), cmd
    monkeypatch.setattr(emulate_core.sys, "platform", "linux")
    cmd = emulate_core.multiboot_cmd("/cards/multi.raw")
    assert cmd[0] == "python3" and cmd[1].endswith("parts.py")
    assert cmd[-2:] == ["--multiboot", "/cards/multi.raw"]
    # macOS: the rig is in a container whose filesystem is not this one, so
    # the card's host path is not a path the probe could open.
    monkeypatch.setattr(emulate_core.sys, "platform", "darwin")
    assert emulate_core.multiboot_cmd("/cards/multi.raw") is None


def test_parse_multiboot_reads_the_line_and_nothing_else():
    """wsl.exe is entitled to prepend its own warnings to stdout (see
    parse_status); one of those turning a yes into an unknown would switch a
    menu off silently."""
    p = emulate_core.parse_multiboot
    assert p("your 131072x1 screen size is bogus\n"
             "multiboot: yes - selector installed, 2 images in images.conf\n") \
        == ("yes", "selector installed, 2 images in images.conf")
    assert p("multiboot: no - no /usr/local/codeselect/codeselect in the "
             "rootfs\n")[0] == "no"
    assert p("multiboot: unknown - x.raw: no MBR signature - not a card "
             "image?")[0] == "unknown"
    # Anything else at all is 'unknown', never 'no'.
    for junk in ("", None, "bash: parts.py: No such file", "multiboot: maybe"):
        assert p(junk)[0] == "unknown", junk


# ------------------------------------------- the Linux this rig talks to ----

def test_every_wsl_call_in_this_module_goes_to_the_same_distro(monkeypatch):
    """The app can install a Linux of its own, and this rig's calls answer
    questions ABOUT EACH OTHER - which user it runs as, where that user's home
    is, whether its binaries are built there.  One head asking a different
    machine than the rest gives answers that are each true and together
    nonsense, so they all go through _wsl_head."""
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    monkeypatch.setattr(emulate_core.runtime, "wsl_distro",
                        lambda runner=None: "PAD-Runtime")
    assert emulate_core._wsl_head() == ["wsl.exe", "-d", "PAD-Runtime", "-e"]
    assert emulate_core._wsl_head(root=True) == [
        "wsl.exe", "-d", "PAD-Runtime", "-u", "root", "-e"]
    assert emulate_core.rig_cmd("watch.sh")[:4] == [
        "wsl.exe", "-d", "PAD-Runtime", "-e"]
    assert emulate_core.rig_cmd_root("run_game.sh")[:6] == [
        "wsl.exe", "-d", "PAD-Runtime", "-u", "root", "-e"]

    # ...and with no runtime installed, nothing changes from how it has always
    # worked: the machine's default distro, no -d at all.
    monkeypatch.setattr(emulate_core.runtime, "wsl_distro",
                        lambda runner=None: None)
    assert emulate_core._wsl_head() == ["wsl.exe", "-e"]
    assert emulate_core.rig_cmd("watch.sh")[:2] == ["wsl.exe", "-e"]


def test_no_call_site_spells_out_its_own_wsl_head():
    """A new `["wsl.exe", "-e", ...]` typed into this module would silently
    talk to the default distro while the rest of the rig ran in ours."""
    src = pathlib.Path(emulate_core.__file__).read_text(encoding="utf-8")
    stray = [ln.strip() for ln in src.splitlines()
             if '"wsl.exe", "-' in ln and "_wsl_head" not in ln
             and not ln.strip().startswith("#")]
    # `wsl.exe --shutdown` is deliberately global - it restarts WSL itself,
    # which is not a per-distro act - and the docstring quoting the old shape.
    assert not [s for s in stray if "--shutdown" not in s and "copies of" not in s], stray


def test_the_wsl_account_belongs_to_the_distro_it_was_probed_in(monkeypatch):
    """★ The app can install its own Linux MID-SESSION.  Probe the Spike 2 tab
    once (caching the default distro's user and home), press Fix setup on the
    Spike 1 tab, and every later Spike 2 run is `wsl -d PAD-Runtime` carrying
    the OTHER distro's account - a rig looking for its work in a home that
    belongs to nobody there.  The cache is keyed by distro now."""
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    where = {"distro": None}
    monkeypatch.setattr(emulate_core.runtime, "wsl_distro",
                        lambda runner=None: where["distro"])
    probes = []

    def fake_run(argv, **kw):
        probes.append(argv)
        if "whoami" in argv:
            return SimpleNamespace(stdout=b"david\n", returncode=0)
        return SimpleNamespace(stdout=b"david:x:1000:1000::/home/david:/bin/sh\n",
                               returncode=0)

    monkeypatch.setattr(emulate_core, "_WSL_ACCOUNT", [("", ""), False])
    monkeypatch.setattr(emulate_core.subprocess, "run", fake_run)
    assert emulate_core.wsl_account() == ("david", "/home/david")
    n = len(probes)
    emulate_core.wsl_account()
    assert len(probes) == n, "the same distro must be answered from cache"

    where["distro"] = "PAD-Runtime"          # Fix setup ran
    emulate_core.wsl_account()
    assert len(probes) > n, "a different distro must be asked again"
    assert probes[-1][:3] == ["wsl.exe", "-d", "PAD-Runtime"], probes[-1]


# --------------------------------------------------------------------------
# A runtime this build will not use, and the tab that has to say so
# --------------------------------------------------------------------------
#
# ★ THE RELEASE THIS WAS WRITTEN FOR.  core/runtime.py carries a version stamp
# and refuses a runtime whose stamp is not the number this build expects:
# `wsl_distro()` answers None and every path into Linux falls back to the
# machine's default distro.  Nothing is deleted and nothing crashes, which is
# why it went unnoticed - but the emulator leaves the Linux that carries its
# toolchain, the prerequisite rows go red, and the card cache and SAVE-STATE
# SLOTS sit in a distro nothing is looking at any more.  From the outside that
# is indistinguishable from losing them.
#
# And until `_runtime_ui` existed, `runtime.install` had exactly three call
# sites and all three were in the Spike 1 tab.  So the FIRST bump of that stamp
# would have reached a Spike 2 user as an emulator that broke itself, with the
# cure on a tab they had no reason to open.


def _rt(monkeypatch, state, detail="because"):
    monkeypatch.setattr(_runtime_ui.runtime, "status",
                        lambda *a, **k: (state, detail))


def test_the_work_disk_is_not_made_behind_a_plain_start(tmp_path):
    """And NOT on Start, which is where the Spike 1 tab makes it.

    `_rig_env` on this tab already hands the rig the disk whenever the file
    exists, so making one on Start would move a user who has been running in
    the runtime without it: the card cache would stay behind, unreferenced,
    and the next Start would re-copy several GB.  Nothing lost, and it would
    look exactly like losing it.  A migration is not a side effect of Start.
    """
    src = pathlib.Path(emulate_web.__file__).read_text(encoding="utf-8",
                                                       errors="replace")
    callers = [ln.strip() for ln in src.splitlines()
               if "self._ensure_data_disk()" in ln]
    assert len(callers) == 1, (
        "the work disk is made from %d places; it belongs to the runtime "
        "install alone" % len(callers))
    # ...and that one caller is inside the runtime install, not somewhere a
    # Start can reach.  Sliced by method rather than by line order, which a
    # tidy-up would reorder without changing anything that matters.
    j = src.index("def runtime_fix(self)")
    fix = src[j:src.index("\n    def ", j + 1)]
    assert "self._ensure_data_disk()" in fix, \
        "the work disk is no longer made where the distro has just been replaced"


def test_the_poll_asks_which_linux_off_the_ui_loop(tmp_path, monkeypatch):
    """The answer costs two wsl.exe launches when cold, and asking on the UI
    loop is one of the four ways this window has been frozen.  On the main
    thread runtime.status() deliberately answers "not known yet" instead, so
    asking there would never see a stale runtime at all."""
    src = pathlib.Path(emulate_web.__file__).read_text(encoding="utf-8",
                                                       errors="replace")
    i = src.index("def _poll(self)")
    # To the END of the method, not a byte window: _poll is long, and a window
    # short enough to miss the hand-off makes this test pass by not looking.
    body = src[i:src.index("\n    def ", i + 1)]
    ask = body.index("runtime.status()")
    hand_off = body.index("def apply_and_release")
    assert ask < hand_off, \
        "the runtime is asked after the hand-off to the main loop"
    assert "self._runtime_apply(rt)" in body, \
        "the poll no longer tells the tab which Linux it is in"


# ----------------------------------------------------------- the ladder --

def test_consent_is_required_before_a_runtime_is_replaced(monkeypatch):
    """The whole point of the module.  Replacing unregisters the distro, and
    a save state is something a person made and cannot get back."""
    asked, installed = [], []
    _rt(monkeypatch, "stale")

    def install(log=None, progress=None, replace=False, **kw):
        if not replace:
            raise _runtime_ui.runtime.RuntimeNeedsReplacing("already there")
        installed.append("replaced")

    monkeypatch.setattr(_runtime_ui.runtime, "install", install)
    state = _runtime_ui.ensure(say=lambda m: None,
                               ask=lambda: asked.append(1) or True)
    assert asked and installed == ["replaced"] and state == "ready"


def test_a_refusal_leaves_the_installed_runtime_exactly_as_it_was(monkeypatch):
    installed = []
    _rt(monkeypatch, "stale")

    def install(log=None, progress=None, replace=False, **kw):
        if not replace:
            raise _runtime_ui.runtime.RuntimeNeedsReplacing("already there")
        installed.append("replaced")

    monkeypatch.setattr(_runtime_ui.runtime, "install", install)
    said = []
    state = _runtime_ui.ensure(say=said.append, ask=lambda: False)
    assert not installed, "a no must not destroy anything"
    assert state == "stale"
    assert any("left the installed runtime alone" in s for s in said), said


def test_a_blocked_download_offers_the_file_route(monkeypatch):
    """370 MB from a host some proxies refuse is the download most likely to
    be stopped, and it was the one with no way round."""
    offered = []
    _rt(monkeypatch, "absent")

    def boom(*a, **kw):
        raise RuntimeError("could not download: blocked")

    monkeypatch.setattr(_runtime_ui.runtime, "install", boom)
    state = _runtime_ui.ensure(say=lambda m: None,
                               on_blocked=offered.append)
    assert offered, "no way round a blocked download"
    assert state == "absent"


def test_a_machine_that_cannot_have_one_is_told_nothing(monkeypatch):
    """Not Windows, or no image pinned in this build: not a fault, so not a
    sentence.  None is the caller's signal to say nothing at all."""
    for state in ("unsupported", "unpublished"):
        _rt(monkeypatch, state)
        said = []
        assert _runtime_ui.ensure(say=said.append) is None
        assert said == [], said


def test_more_than_one_tab_can_move_a_user_off_a_stale_runtime():
    """THE REGRESSION THIS MODULE EXISTS FOR.  Before it, runtime.install had
    three call sites and every one was in the Spike 1 tab - so the first bump
    of the version stamp would have left a Spike 2 user with a broken emulator
    and the cure on a tab they had no reason to open."""
    webui = pathlib.Path(emulate_core.__file__).parent
    users = sorted(p.name for p in webui.rglob("*.py")
                   if "_runtime_ui.ensure(" in p.read_text(encoding="utf-8",
                                                           errors="replace"))
    assert len(users) >= 2, (
        "only %s can act on a stale runtime; a user who never opens that tab "
        "has no way off one" % (users or "nothing"))


# --------------------------------------------------------------------------
# Item 127: launch_with - the Modes tab's Try it through this tab's own Start
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# feature/emulate-prepare: the launch API the Modes tab's Try it drives -
# every refusal says why, a preparation narrates and can be cancelled, and
# the window is told when a run goes down
# --------------------------------------------------------------------------


def test_the_card_functions_are_the_plugins(tmp_path):
    """PAD-161's choice of card moved to plugins/stern/cards.py so Try it can share it
    without a Tk import; the tab reads them back from there, one definition."""
    from pinball_decryptor.plugins.stern import cards
    assert emulate_core.override_base_card is cards.override_base_card
    assert emulate_core._title_label is cards._title_label
