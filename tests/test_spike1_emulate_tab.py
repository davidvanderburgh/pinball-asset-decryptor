"""Spike 1 Emulate tab: the pure pieces (state wording, status mapping, command
builders, wiring) plus widget smoke tests on an invisible Tk root.

A sibling of tests/test_jjp_emulate_tab.py — same shape, no dongle.  The wording
is tested because the FIRST thing a user is told has to be the first thing that
is actually not ready: a run that needs the one-time build must say "Setup", not
"Stopped".
"""

import subprocess
from types import SimpleNamespace

import pytest

from pinball_decryptor.gui import _rig, spike1_emulate_tab
from pinball_decryptor.gui.spike1_emulate_tab import (DEFAULT_RIG_DIR,
                                                      Spike1EmulatePanel,
                                                      rig_cmd, rig_cmd_root,
                                                      rig_dir, state_text)


# ---------------------------------------------------------------- plumbing --

def _event_keep(name):
    return next(k for f, _t, k in spike1_emulate_tab._EVENT_LOGS if f == name)


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
    monkeypatch.setattr(spike1_emulate_tab.sys, "platform", "linux")
    with pytest.raises(RuntimeError):
        rig_cmd_root("start.sh")


def test_rig_cmd_root_targets_wsl_root(monkeypatch):
    monkeypatch.setattr(spike1_emulate_tab.sys, "platform", "win32")
    cmd = rig_cmd_root("start.sh")
    assert cmd[:4] == ["wsl.exe", "-u", "root", "-e"]


def test_status_is_ordinary_user_not_root(monkeypatch):
    """A read-only status poll must not need root — that would prompt or fail on
    a locked-down box, and the poll runs every couple of seconds."""
    monkeypatch.setattr(spike1_emulate_tab.sys, "platform", "win32")
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

@pytest.fixture(scope="module")
def root():
    """ONE Tk root for the whole module (matches tests/test_jjp_emulate_tab.py).
    A second tk.Tk() in one process throws on some hosts, so Tk tests may skip in
    a full local run; CI (Linux) creates one per module cleanly."""
    tk = pytest.importorskip("tkinter")
    from tests.conftest import make_tk_root
    try:
        # retried: one transient Tcl-script read miss must not skip the
        # whole module (pytest caches a module fixture's skip) - see
        # make_tk_root
        r = make_tk_root(tk)
    except Exception:                                       # noqa: BLE001
        pytest.skip("no usable Tk display")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except Exception:                                       # noqa: BLE001
        pass


@pytest.fixture
def panel(root, monkeypatch):
    """A built panel whose poller never shells out to WSL."""
    import tkinter as tk
    monkeypatch.setattr(Spike1EmulatePanel, "_schedule_poll",
                        lambda self, ms=None: None)
    frame = tk.Frame(root)
    p = Spike1EmulatePanel(frame, card_var=tk.StringVar())
    p.build(frame)
    yield p
    p._stopped = True
    try:
        frame.destroy()
    except Exception:                                       # noqa: BLE001
        pass


def test_go_button_is_leftmost(panel):
    assert panel._go_btn.pack_info()["side"] == "left"
    # Restart WSL sits next to Start, but only where WSL exists (Windows).
    if panel._reset_btn.winfo_manager():
        assert panel._reset_btn.pack_info()["side"] == "left"


def test_apply_running_flips_the_button(panel):
    panel._apply({"wsl": "1", "game_procs": "2", "game_uptime_s": "30",
                  "cpu": "140", "rss_mb": "512",
                  "dmd_frames": "300", "nodes_registered": "1",
                  "qemu_built": "1", "hwshim_built": "1", "game_ready": "1"})
    assert panel._last_up is True
    assert panel._go_btn["text"] == "Stop"
    assert panel._vals["dmd"]["text"] == "300"
    assert panel._vals["boards"]["text"] == "yes"
    assert "512 MB" in panel._vals["cpu"]["text"]


def test_apply_stopped_flips_back(panel):
    panel._apply({"wsl": "1", "game_procs": "2"})
    panel._apply({"wsl": "1", "game_procs": "0", "qemu_built": "1",
                  "game_ready": "1"})
    assert panel._last_up is False
    assert panel._go_btn["text"] == "Start emulator"


def test_note_reports_running_and_registered(panel):
    """While running with boards registered, the note says the game boots to
    attract and the switch window is clickable."""
    panel._apply({"wsl": "1", "game_procs": "2", "nodes_registered": "1"})
    text = panel._note["text"].lower()
    assert "registered" in text and ("attract" in text or "switch" in text)


def test_apply_drives_the_footer_ladder(panel):
    """The tab feeds the shared footer ladder (Extract / Boot / Node boards /
    Ready) through footer_cb, like the Spike 2 tab."""
    seen = []
    panel._footer_cb = lambda kind, pct=None, text="": seen.append(kind)
    panel._busy = False
    panel._apply({"wsl": "1", "game_procs": "2", "nodes_registered": "1"})
    assert "run" in seen
    seen.clear()
    panel._apply({"wsl": "1", "game_procs": "2", "nodes_registered": "0"})
    assert "boot" in seen
    seen.clear()
    panel._apply({"wsl": "1", "game_procs": "0", "qemu_built": "1",
                  "game_ready": "1"})
    assert "idle" in seen


def test_start_without_a_card_or_a_game_asks(panel, monkeypatch):
    """Pressing Start with nothing selected and no extracted game must ask, not
    launch."""
    called = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: called.append(a) or SimpleNamespace(
                            returncode=0, stdout=b""))
    shown = []
    monkeypatch.setattr(spike1_emulate_tab.messagebox, "showinfo",
                        lambda *a, **k: shown.append(a))
    panel._info = {"game_ready": "0"}
    panel._start_async()
    assert shown and not called


def test_start_allows_no_card_once_a_game_is_extracted(panel, monkeypatch):
    """A game already extracted means Start needs no card — it reuses it."""
    ran = []
    monkeypatch.setattr(spike1_emulate_tab.threading, "Thread",
                        lambda target=None, **k: SimpleNamespace(
                            start=(lambda: ran.append(1)), daemon=True))
    shown = []
    monkeypatch.setattr(spike1_emulate_tab.messagebox, "showinfo",
                        lambda *a, **k: shown.append(a))
    panel._info = {"game_ready": "1"}
    panel._start_async()
    assert ran and not shown


def test_fix_state_shuts_down_wsl_when_confirmed(panel, monkeypatch):
    monkeypatch.setattr(spike1_emulate_tab.sys, "platform", "win32")
    monkeypatch.setattr(spike1_emulate_tab.messagebox, "askyesno",
                        lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: calls.append(a[0]) or SimpleNamespace(
                            returncode=0, stdout=b""))
    monkeypatch.setattr(spike1_emulate_tab.threading, "Thread",
                        lambda target=None, **k: SimpleNamespace(
                            start=(target or (lambda: None)), daemon=True))
    panel._fix_state()
    assert calls == [["wsl.exe", "--shutdown"]]


def test_shutdown_sync_is_a_noop_when_nothing_ran(panel, monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    panel._last_up = False
    panel._info = {"responder": "0"}
    panel.shutdown_sync()
    assert not called


# --------------------------------------------------------------- log streaming --

class _FakeStdout:
    def __init__(self, lines):
        self._it = iter(lines)

    def __iter__(self):
        return self._it

    def close(self):
        pass


class _FakeProc:
    def __init__(self, lines, rc):
        self.stdout = _FakeStdout(lines)
        self.returncode = rc

    def kill(self):
        pass

    def wait(self):
        return self.returncode


def test_run_streaming_logs_each_line(panel, monkeypatch):
    logged = []
    monkeypatch.setattr(panel, "_log", lambda m: logged.append(m))
    lines = ["Setup: building the patched ARM emulator…\n",
             "Node-bus responder up.\n", "READY\n"]
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: _FakeProc(lines, rc=0))
    rc = panel._run_streaming(["start.sh"], timeout=1800)
    assert rc == 0
    assert any("Node-bus responder up" in m for m in logged)
    assert any("READY" in m for m in logged)


def test_run_streaming_survives_a_popen_failure(panel, monkeypatch):
    monkeypatch.setattr(panel, "_log", lambda m: None)

    def boom(*a, **k):
        raise OSError("wsl.exe not found")

    monkeypatch.setattr(subprocess, "Popen", boom)
    assert panel._run_streaming(["start.sh"], timeout=1800) is None


# ------------------------------------------------------------- DMD preview --

def test_load_dmd_decoder_from_rig_dir():
    """The DMD window decodes frames with the rig's s1dmd — a script tree, not
    an installed package, so it loads by path."""
    m = spike1_emulate_tab._load_dmd_decoder()
    assert hasattr(m, "decode_frame")
    assert m.FRAME_BYTES == 2048


def test_open_viewers_is_inert_without_run_dir(panel):
    """A running game with no work/distro yet must not try to open windows."""
    panel._info = {"game_procs": "2"}     # no work/distro
    panel._open_viewers()                 # must not raise
    # the manager may be created, but with nothing to point it at
    assert panel._viewers is None or panel._viewers._io is None


def test_window_reset_when_idle_just_says_so(panel, monkeypatch):
    logged = []
    monkeypatch.setattr(panel, "_log", lambda m: logged.append(m))
    panel._last_up = False
    panel._window_reset()
    assert logged and "start" in logged[-1].lower()


# ------------------------------------------------------------------- cache --

def test_parse_cache_reads_entries_and_free():
    text = ("entry\tgot_le-1_37\t204800\t1700000000\tGOT_LE\t1\n"
            "entry\tghostbusters_le-1_17\t153600\t1699990000\tghostbusters_le\t0\n"
            "disk\t98566144\n")
    rows, free = Spike1EmulatePanel._parse_cache(text)
    assert free == "98566144"
    assert [r["label"] for r in rows] == ["got_le-1_37",
                                          "ghostbusters_le-1_17"]  # newest first
    assert rows[0]["active"] is True and rows[1]["active"] is False
    assert rows[0]["game"] == "GOT_LE"


def test_parse_cache_empty_is_no_rows():
    rows, free = Spike1EmulatePanel._parse_cache("disk\t500\n")
    assert rows == [] and free == "500"


def test_human_kb_scales():
    assert Spike1EmulatePanel._human_kb(512) == "512 KB"
    assert Spike1EmulatePanel._human_kb(153600) == "150.0 MB"
    assert Spike1EmulatePanel._human_kb("bad") == "?"


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


def test_main_window_wires_the_spike1_tab():
    import inspect
    from pinball_decryptor.gui import main_window
    src = inspect.getsource(main_window)
    assert '(self._tab_spike1_emulate, "Emulate", "Emulate Spike1")' in src
    assert "self._build_spike1_emulate_tab()" in src
    assert '_configure_tab("Emulate Spike1"' in src
    assert "_spike1_emulate_panel" in src


def test_help_has_an_entry_for_the_spike1_tab():
    from pinball_decryptor.gui.help_dialog import HELP_CONTENT
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
                               spike1_emulate_card_var=var),
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

def _inline_threads(monkeypatch):
    """Make the panel's worker threads run inline, so a test sees the result
    without sleeping."""
    class _T:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(spike1_emulate_tab.threading, "Thread", _T)


def test_slots_refresh_parses_the_pipe_protocol(panel, root, monkeypatch):
    monkeypatch.setattr(spike1_emulate_tab.sys, "platform", "win32")
    monkeypatch.setattr(spike1_emulate_tab, "rig_available", lambda: True)
    _inline_threads(monkeypatch)
    out = (b"root|/home/d/s1emu/saves\n"
           b"slot|ghostbusters_le-1_17/quicksave|44362327|"
           b"ghostbusters_le-1_17|mid-ball test |1788199042\n"
           b"slot|GOT_LE-1_37/s2|13000000|GOT_LE-1_37||1788100000\n"
           b"total|57362327\n"
           b"free|100980350976\n")
    monkeypatch.setattr(
        spike1_emulate_tab.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(stdout=out))
    panel._slots_refresh()
    root.update()          # flush the after(0) apply
    assert [r["ref"] for r in panel._slots_rows] == [
        "ghostbusters_le-1_17/quicksave", "GOT_LE-1_37/s2"]
    assert panel._slots_rows[0]["label"] == "mid-ball test"
    rows = panel._slots_tree.get_children()
    assert list(rows) == ["ghostbusters_le-1_17/quicksave", "GOT_LE-1_37/s2"]
    assert "2 slots" in panel._slots_sum.cget("text")


def test_save_now_refuses_without_a_running_game(panel, monkeypatch):
    told = {}
    monkeypatch.setattr(spike1_emulate_tab.messagebox, "showinfo",
                        lambda *a, **kw: told.setdefault("msg", a))
    ran = {}
    monkeypatch.setattr(spike1_emulate_tab.subprocess, "run",
                        lambda *a, **kw: ran.setdefault("cmd", a))
    panel._info = {"game_procs": "0"}
    panel._slot_save()
    assert told and not ran     # a message, never a root shell-out


def test_slot_size_and_date_formatting():
    assert Spike1EmulatePanel._fmt_size("44362327") == "42.3 MB"
    assert Spike1EmulatePanel._fmt_size("512") == "512 B"
    assert Spike1EmulatePanel._fmt_size("junk") == "?"
    assert Spike1EmulatePanel._fmt_when("not-a-number") == "?"


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

def test_player_cmd_is_padplay_via_pads_own_python(panel, monkeypatch):
    monkeypatch.setattr(spike1_emulate_tab, "windows_python",
                        lambda console=False: r"C:\Py\python.exe")
    monkeypatch.setattr(spike1_emulate_tab.os.path, "isfile", lambda p: True)
    cmd = panel._player_cmd()
    assert cmd[0] == r"C:\Py\python.exe"
    assert cmd[1].replace("\\", "/").endswith("tools/spike2_emu/padplay.py")
    assert cmd[2:] == ["127.0.0.1", "45998", "44100", "2"]


def test_player_relaunch_backs_off(panel, monkeypatch):
    """A dead player is relaunched, but at most once per 5 s - connection
    refused while the rig boots must not spin."""
    monkeypatch.setattr(spike1_emulate_tab.sys, "platform", "win32")
    spawned = []

    class _Proc:
        def poll(self):
            return 1                       # exited

        def kill(self):
            pass

    monkeypatch.setattr(panel, "_player_cmd", lambda: ["py", "padplay"])
    monkeypatch.setattr(spike1_emulate_tab.subprocess, "Popen",
                        lambda *a, **kw: spawned.append(a) or _Proc())
    t = {"v": 100.0}
    monkeypatch.setattr(spike1_emulate_tab.time, "monotonic", lambda: t["v"])
    panel._ensure_player()
    panel._ensure_player()                 # same instant: backoff holds
    assert len(spawned) == 1
    t["v"] += 6.0
    panel._ensure_player()                 # dead + past backoff: relaunched
    assert len(spawned) == 2


def test_stop_player_kills_and_forgets(panel):
    killed = {}

    class _Proc:
        def poll(self):
            return None

        def kill(self):
            killed["v"] = True

    panel._player = _Proc()
    panel._stop_player()
    assert killed.get("v") is True
    assert panel._player is None


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

def test_audio_format_comes_from_the_run_dir(panel, tmp_path, monkeypatch):
    (tmp_path / "s1audio").write_text("24000 2\n", encoding="utf-8")
    panel._info = {"work": "/home/david/s1emu", "distro": "Ubuntu"}
    monkeypatch.setattr(spike1_emulate_tab, "wsl_unc",
                        lambda distro, p: str(tmp_path / p.rsplit("/", 1)[-1]))
    assert panel._audio_format() == ("24000", "2")


def test_audio_format_falls_back_when_the_rig_has_not_said(panel, tmp_path,
                                                           monkeypatch):
    panel._info = {"work": "/home/david/s1emu", "distro": "Ubuntu"}
    monkeypatch.setattr(spike1_emulate_tab, "wsl_unc",
                        lambda distro, p: str(tmp_path / "missing"))
    assert panel._audio_format() == panel.DEFAULT_AUDIO == ("44100", "2")


def test_audio_format_ignores_a_malformed_marker(panel, tmp_path, monkeypatch):
    (tmp_path / "s1audio").write_text("garbage\n", encoding="utf-8")
    panel._info = {"work": "/home/david/s1emu", "distro": "Ubuntu"}
    monkeypatch.setattr(spike1_emulate_tab, "wsl_unc",
                        lambda distro, p: str(tmp_path / p.rsplit("/", 1)[-1]))
    assert panel._audio_format() == ("44100", "2")
