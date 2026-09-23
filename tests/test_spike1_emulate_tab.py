"""Spike 1 Emulate tab: the pure pieces (state wording, status mapping, command
builders, wiring), from ``webui/emulate_spike1_core.py``.  The web tab itself is
driven in tests/test_webui_emulate_spike1.py.

A sibling of tests/test_jjp_emulate_tab.py — same shape, no dongle.  The wording
is tested because the FIRST thing a user is told has to be the first thing that
is actually not ready: a run that needs the one-time build must say "Setup", not
"Stopped".
"""

import subprocess
from types import SimpleNamespace

import pytest

from pinball_decryptor.webui import rig as _rig
from pinball_decryptor.webui import emulate_spike1_core as spike1_emulate_tab
from pinball_decryptor.webui.emulate_spike1_core import (DEFAULT_RIG_DIR,
                                                         rig_cmd,
                                                         rig_cmd_root,
                                                         rig_dir, state_text)


# ---------------------------------------------------------------- plumbing --

def _event_keep(name):
    return next(k for f, _t, k in spike1_emulate_tab._EVENT_LOGS if f == name)


@pytest.fixture(autouse=True)
def _no_runtime_unless_asked(monkeypatch):
    """THE TESTS MUST NOT DEPEND ON WHETHER THIS MACHINE HAS THE RUNTIME.

    `runtime.distro_for` asks WSL which distro to route a rig into, and on a
    developer's box - where the runtime IS installed - that answer costs two
    wsl.exe launches and starts a distro, inside the Start path these tests
    time.  Three of them failed that way, on the dev box only, while every CI
    runner passed: the worst shape a test can have.  So the default here is
    "no runtime", and the tests that are ABOUT routing patch it themselves.
    """
    monkeypatch.setattr(spike1_emulate_tab.runtime, "distro_for", lambda rig: None)
    monkeypatch.setattr(spike1_emulate_tab.runtime, "known_state", lambda: None)
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

    monkeypatch.setattr(spike1_emulate_tab.runtime, "install", _refuse_install)
    monkeypatch.setattr(spike1_emulate_tab.runtime, "status",
                        lambda *a, **kw: ("unsupported", "not in tests"))
    from pinball_decryptor.core import payloads as _core_payloads
    monkeypatch.setattr(_core_payloads, "ensure", _refuse_payloads)


def test_event_log_filters_keep_events_and_drop_chatter():
    """The rig-event tail forwards event-shaped lines and drops the periodic
    chatter — a flooded log pane is a known UI-thread freeze class."""
    emu = _event_keep("emu.log")
    assert emu.search("======== GAME RUN 1 / 1000 ========")
    assert emu.search("======== RUN 1 exited (code 0) ========")
    assert emu.search("PAD/spike1: DUMP (tid 5) live guest CPU state:")
    assert emu.search("PAD/spike1: FATAL guest signal 11")
    assert not emu.search("S1I2C RDWR RD addr=0x50 len=8")

    aud = _event_keep("audio.log")
    assert aud.search("[play] fifo /home/d/s1emu/audio.fifo")
    assert aud.search("[padrelay] player connected from ('127.0.0.1', 1)")
    assert aud.search("[padplay] queue  334 ms  underruns    3  fed 1")
    assert not aud.search("[padplay] queue  334 ms  underruns    0  fed 1")

    # the keeper's log IS the event stream: every line goes through
    assert _event_keep("s1ball.log") is None


def test_rig_dir_is_overridable(monkeypatch):
    monkeypatch.setenv("PAD_SPIKE1_EMU_DIR", "/somewhere/else")
    assert rig_dir() == "/somewhere/else"


def test_rig_dir_defaults_into_the_repo():
    assert DEFAULT_RIG_DIR.replace("\\", "/").endswith("tools/spike1_emu")


def test_rig_cmd_root_refuses_off_windows(monkeypatch):
    """Root is honest only on WSL; a Linux desktop's sudo wants a password a GUI
    app has nowhere to ask for."""
    monkeypatch.setattr(_rig.sys, "platform", "linux")
    with pytest.raises(RuntimeError):
        rig_cmd_root("start.sh")


def test_rig_cmd_root_targets_wsl_root(monkeypatch):
    # WHICH LINUX IS PINNED HERE ON PURPOSE.  Since the app can install a
    # runtime distro of its own, the command builders ask the real machine
    # which one to name - so this assertion used to pass or fail depending on
    # whether the person running it had the runtime installed.  The routing
    # itself is tested against an injected runner in tests/test_runtime.py;
    # what is tested here is the root part, so the distro is held still.
    monkeypatch.setattr(_rig.sys, "platform", "win32")
    monkeypatch.setattr(spike1_emulate_tab, "rig_distro", lambda: None)
    cmd = rig_cmd_root("start.sh")
    assert cmd[:4] == ["wsl.exe", "-u", "root", "-e"]


def test_rig_cmd_root_names_the_runtime_distro(monkeypatch):
    """And when there IS one, it is named before the root switch - a machine
    with our runtime must not run the root half in someone else's Linux."""
    monkeypatch.setattr(_rig.sys, "platform", "win32")
    monkeypatch.setattr(spike1_emulate_tab, "rig_distro", lambda: "PAD-Runtime")
    cmd = rig_cmd_root("start.sh")
    assert cmd[:6] == ["wsl.exe", "-d", "PAD-Runtime", "-u", "root", "-e"]


def test_status_is_ordinary_user_not_root(monkeypatch):
    """A read-only status poll must not need root — that would prompt or fail on
    a locked-down box, and the poll runs every couple of seconds."""
    monkeypatch.setattr(_rig.sys, "platform", "win32")
    cmd = rig_cmd("status.sh")
    assert "root" not in cmd


# ------------------------------------------------------------------ wording --

def test_state_running_reports_boards_registered():
    label, hint = state_text({"wsl": "1", "game_procs": "2",
                              "game_uptime_s": "75", "dmd_frames": "500",
                              "nodes_registered": "1"})
    # "Game running", matching the Spike 2 tab (the two texts used to flap
    # in the shared footer - David: "choose one").
    assert label == "Game running"
    assert "boards" in hint.lower() and "registered" in hint.lower()


def test_state_booting_before_boards_register():
    label, _ = state_text({"wsl": "1", "game_procs": "2",
                           "nodes_registered": "0"})
    assert label == "Booting…"


def test_state_setup_needed_beats_stopped():
    """With the emulator not yet built, the FIRST run has to build it — calling
    that "Stopped" hides the several-minute wait the user is about to hit."""
    label, hint = state_text({"wsl": "1", "game_procs": "0", "qemu_built": "0"})
    assert label == "Setup needed"
    assert "build" in hint.lower()


def test_state_no_game_asks_for_a_card():
    label, hint = state_text({"wsl": "1", "game_procs": "0", "qemu_built": "1",
                              "game_ready": "0"})
    assert label == "No game extracted"
    assert "card" in hint.lower()


def test_state_not_running_when_ready():
    label, _ = state_text({"wsl": "1", "game_procs": "0", "qemu_built": "1",
                           "game_ready": "1"})
    assert label == "Not running"


def test_state_no_wsl():
    assert "WSL" in state_text({"wsl": "0"})[0]


def test_state_empty_is_checking():
    assert state_text({})[0] == "Checking…"


# ------------------------------------------------------------------ widgets --

# --------------------------------------------------------------- log streaming --


# ------------------------------------------------------------- DMD preview --

def test_load_dmd_decoder_from_rig_dir():
    """The DMD window decodes frames with the rig's s1dmd — a script tree, not
    an installed package, so it loads by path."""
    m = spike1_emulate_tab._load_dmd_decoder()
    assert hasattr(m, "decode_frame")
    assert m.FRAME_BYTES == 2048


# ------------------------------------------------------------------- cache --

def test_parse_cache_reads_entries_and_free():
    text = ("entry\tgot_le-1_37\t204800\t1700000000\tGOT_LE\t1\n"
            "entry\tghostbusters_le-1_17\t153600\t1699990000\tghostbusters_le\t0\n"
            "disk\t98566144\n")
    rows, free = spike1_emulate_tab.parse_cache(text)
    assert free == "98566144"
    assert [r["label"] for r in rows] == ["got_le-1_37",
                                          "ghostbusters_le-1_17"]  # newest first
    assert rows[0]["active"] is True and rows[1]["active"] is False
    assert rows[0]["game"] == "GOT_LE"


def test_parse_cache_empty_is_no_rows():
    rows, free = spike1_emulate_tab.parse_cache("disk\t500\n")
    assert rows == [] and free == "500"


def test_human_kb_scales():
    assert spike1_emulate_tab.human_kb(512) == "512 KB"
    assert spike1_emulate_tab.human_kb(153600) == "150.0 MB"
    assert spike1_emulate_tab.human_kb("bad") == "?"


# -------------------------------------------------------------- integration --

def test_stern_spike1_declares_the_capability():
    """The tab is gated on emulate_spike1; without it the panel is built and
    never shown, which looks exactly like a broken tab."""
    from pinball_decryptor.plugins.stern.manufacturer import _SPIKE1_CAPS
    assert _SPIKE1_CAPS.emulate_spike1 is True
    # …and NOT the Spike 2 flag, or a Spike 1 card would get the Spike 2 panel.
    assert _SPIKE1_CAPS.emulate is False


def test_spike2_era_does_not_get_the_spike1_flag():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    assert SternManufacturer._SPIKE2_CAPS.emulate is True
    assert SternManufacturer._SPIKE2_CAPS.emulate_spike1 is False


def test_help_has_an_entry_for_the_spike1_tab():
    from pinball_decryptor.webui.help_content import HELP_CONTENT
    body = " ".join(t + " " + b for t, b in HELP_CONTENT["Emulate Spike1"])
    assert "dot-matrix" in body.lower() or "dmd" in body.lower()
    assert "card" in body.lower()


def test_rig_scripts_exist():
    """The rig the tab drives must ship with it — the tab is a thin launcher and
    is useless without start/stop/status."""
    import os
    for s in ("start.sh", "stop.sh", "status.sh"):
        assert os.path.isfile(os.path.join(DEFAULT_RIG_DIR, s)), s


# ------------------------------------------------ card path persistence --
# The selected Spike 1 card image survives an app restart (David 2026-08-31:
# "the selected image needs to be remembered").  Same rail as the Spike 2
# card / JJP ISO, own key ``spike1_emulate_card``: anchor first, global
# fallback when the anchor predates the key, global only with no project.

def _restore_s1(folder, settings=None, anchor_card=None):
    from pinball_decryptor.app import App
    from pinball_decryptor.core import project_file

    if folder:
        project_file.save(
            project_file.anchor_path(str(folder)),
            manufacturer_key="stern",
            paths={"extract_input": "C:/stock/game.raw",
                   "extract_output": str(folder)},
            extract_options={},
            app_version="test")
        if anchor_card is not None:
            project_file.update_anchor(str(folder),
                                       spike1_emulate_card=anchor_card)

    class _Var:
        value = "SENTINEL - never set"

        def set(self, v):
            self.value = v

    var = _Var()
    stub = SimpleNamespace(
        _settings=settings if settings is not None else {},
        # the real window always has the Spike 2 var too (tabs build eagerly);
        # without it the method returns before reaching the Spike 1 block
        window=SimpleNamespace(emulate_card_var=_Var(),
                               spike1_emulate_card_var=var,
                               # no Emulate service: the machine row is
                               # left alone
                               service=lambda name: None),
    )
    App._restore_emulate_card(stub, str(folder) if folder else "")
    return var.value


def test_spike1_card_restores_from_the_anchor(tmp_path):
    proj = tmp_path / "gble"
    proj.mkdir()
    assert _restore_s1(proj, anchor_card="D:/cards/gble.iso") \
        == "D:/cards/gble.iso"


def test_spike1_card_anchor_without_key_falls_back_to_global(tmp_path):
    """Anchors written before the key existed restore from the global —
    the same rule that made EXISTING JJP projects restore their ISO."""
    proj = tmp_path / "old-project"
    proj.mkdir()
    assert _restore_s1(proj, {"spike1_emulate_card": "D:/cards/kiss.iso"}) \
        == "D:/cards/kiss.iso"


def test_spike1_card_restores_from_global_with_no_project(tmp_path):
    assert _restore_s1(None, {"spike1_emulate_card": "D:/cards/got.iso"}) \
        == "D:/cards/got.iso"
    assert _restore_s1(None, {}) == ""


# -------------------------------------------------------------- save states --
# item 87: the slot manager is live — it lists s1slots.sh's pipe protocol,
# and Save now refuses politely when no game is running.


def test_slot_size_and_date_formatting():
    assert spike1_emulate_tab.fmt_size("44362327") == "42.3 MB"
    assert spike1_emulate_tab.fmt_size("512") == "512 B"
    assert spike1_emulate_tab.fmt_size("junk") == "?"
    assert spike1_emulate_tab.fmt_when("not-a-number") == "?"


def test_dead_keeper_is_named_not_masked():
    """A game up with no ball keeper sits on LOCATING PINBALLS forever — the
    state cell must name the keeper, not say "Game running" (2026-08-31,
    David's first app-started pivot run)."""
    label, hint = state_text({"wsl": "1", "game_procs": "1", "keeper": "0",
                              "nodes_registered": "1"})
    assert label == "No ball keeper"
    assert "LOCATING PINBALLS" in hint
    # with the keeper alive the ladder is unchanged
    label, _ = state_text({"wsl": "1", "game_procs": "1", "keeper": "1",
                           "nodes_registered": "1"})
    assert label == "Game running"
    # a status.sh from before the keeper key existed stays unchanged too
    label, _ = state_text({"wsl": "1", "game_procs": "1",
                           "nodes_registered": "1"})
    assert label == "Game running"


# ------------------------------------------------------------ app speaker --
# item 87 follow-up (no-sound report): the APP owns the Windows player; the
# rig's WSL side runs only fifo + relay (PAD_AUDIO_SINK=relay), because a
# Windows exec from WSL rides an interop socket that dies with start.sh's
# wsl.exe - the probe hung forever and a fresh app + fresh Start was silent.


# ------------------------------------------------- whose guest is it? (98) --
# comm=game is the guest's one stable identity, and it is NOT unique on the
# machine: the Spike 2 rig names its guest `game` too.  A bare `pgrep -x game`
# in this rig therefore answered "SOME rig is running a game", which opened the
# Spike 1 DMD/switch windows over a Spike 2 run and, on app quit, let this
# rig's stop.sh KILL that run.  tools/spike1_emu/s1own.sh is the one place that
# decides which guests are ours; these keep every caller pointed at it.
#
# The live proof is a run (two comm=game processes, one on this rig's mounts
# and one not); what is checkable in half a second is that no caller has grown
# its own copy of the rule again.

def _rig_text(name):
    import os
    with open(os.path.join(DEFAULT_RIG_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def _rig_code(name):
    """The script WITHOUT its comments - these scripts explain the mistakes
    they no longer make, and a naive substring check reads the explanation as
    the mistake."""
    return "\n".join(ln for ln in _rig_text(name).splitlines()
                     if not ln.lstrip().startswith("#"))


def test_the_rig_ships_the_ownership_helper():
    import os
    assert os.path.isfile(os.path.join(DEFAULT_RIG_DIR, "s1own.sh"))


def test_ownership_is_decided_by_this_rigs_mounts():
    """/proc/<pid>/mountinfo, because it is the only fact that is readable by
    the ordinary user status.sh runs as AND survives a criu restore (which
    comes back with no ancestor of ours and a command line identical to the
    Spike 2 rig's)."""
    own = _rig_text("s1own.sh")
    assert "mountinfo" in own
    assert "S1_WORK" in own


def test_status_asks_the_helper_instead_of_counting_every_game():
    status = _rig_code("status.sh")
    assert "s1own.sh" in status
    assert "pgrep -c -x game" not in status
    assert "pgrep -x game" not in status
    # the responder key sends the app's quit hook into stop.sh, and the Spike 2
    # rig has a nodebus.py of its own
    assert 'pgrep -f "nodebus.py"' not in status


def test_stop_kills_our_guest_and_our_responder_only():
    stop = _rig_code("stop.sh")
    assert "pkill -KILL -x game" not in stop
    assert "pkill -KILL -f nodebus.py" not in stop
    assert stop.count("killours game") == 2      # again after the restart loop
    assert "killours nodebus" in stop


def test_restore_replaces_only_our_guests():
    restore = _rig_code("s1restorestate.sh")
    assert "s1own.sh" in restore
    assert '$2=="game"' not in restore


def test_responder_pattern_is_anchored():
    """alive.sh's rule: every -f pattern is anchored or comm-exact.  Measured
    unanchored, this matched a shell that merely had the command in its own
    command line."""
    own = _rig_code("s1own.sh")
    assert 'pgrep -f "^' in own


@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"),
                    reason="the helper reads a Linux /proc")
def test_helper_runs_and_answers_nothing_when_no_guest_is_ours(tmp_path):
    import os
    out = subprocess.run(["bash", os.path.join(DEFAULT_RIG_DIR, "s1own.sh"),
                          "game"], stdout=subprocess.PIPE,
                         env=dict(os.environ, S1_WORK=str(tmp_path)))
    assert out.returncode == 0
    assert out.stdout.decode().strip() == ""


# ------------------------------------------------- the speaker's PCM rate --
# The DMD generation is 44100x2; the 2012 home models run their DAC at 24000
# (sys_dac_init asks for rate index 3).  Opening the speaker at the wrong rate
# starves it - the player wants 176400 B/s while the game makes 96000 - so
# nothing is heard at all (PAD-101).


# ------------------------------------------------- the one-time build fails --


# ---------------------------------------- the emulator we ship, not build --


def test_the_panel_only_asks_for_payloads_the_app_actually_pins():
    """A key the registry does not carry would raise KeyError the first time a
    user pressed Start on a fresh machine."""
    from pinball_decryptor.core import payloads as core_payloads
    for key in spike1_emulate_tab.PAYLOAD_KEYS:
        assert key in core_payloads.PAYLOADS


# ------------------------------- what the adversarial review found here ----


