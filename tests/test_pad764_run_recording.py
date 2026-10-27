"""PAD-764: every Spike 2 run is recorded so it can be replayed exactly.

David asked to replay exactly what he saw. A switch-log replay matched his
session to the millisecond until his first pick, then diverged: the game read
the machine's memory (the last place played, the audits) and the rig's was not
his. So each boot now saves the title's NVRAM as the game is about to read it,
next to the boot's switch log (runrec.py), and replayrun.sh boots a free rig on
that NVRAM and hands the game every switch at its game time (swreplay.py).

These pin the recorder and the replay timeline on fake rootfs trees, and the
hooks that call them (watch.sh, loadgame.sh, the shim's [pause] line). The
proof that a replay matches the run it recorded is the emulator's: see
docs/plans/pad764_run_recording.md.
"""
import json
import os
import re
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)

import runrec  # noqa: E402
import swreplay  # noqa: E402


def _text(name):
    with open(os.path.join(RIG, name), encoding="utf8", newline="") as f:
        return f.read()


def _write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _rig(tmp_path, game="godzilla_le"):
    root = tmp_path / "root"
    data = root / "data"
    _write(str(data / "nv" / game / "NVRAM" / "00000001.nv"), b"last place: TOKYO")
    _write(str(data / "nv" / game / "LKRAM" / "00000008.crc32"), b"crc")
    _write(str(data / ("nvram-%s.bin" % game)), b"\0" * 64)
    _write(str(data / "codeselect.last"), b"2\n")
    _write(str(data / "nv.own" / "heisei" / game / "NVRAM" / "1.nv"), b"edition store")
    _write(str(data / "nv" / "jaws_le" / "NVRAM" / "1.nv"), b"another title")   # not this run's
    logdir = tmp_path / "home"
    logdir.mkdir()
    return str(root), str(logdir)


SESSION = (
    "[watch] noise\n"
    "[pause] 100 ms frozen 0 ms in all (at boot)\n"
    "[sw] 60006 ms +5k\n"
    "[123.456] [sw] 60126 ms -5k +66b\n"            # PAD_LOG_TIME prefixes every line
    "[sw] id=5 node=0 bit=5 name=START\n"           # the shim's switch dump: not an edge
    "[swspin] 71996 ms id=85 node=9 rip START\n"
    "[swspin] 72162 ms id=85 node=9 rip END: 9 closures in 166 ms (54/s)\n"
    "[pause] 120000 ms frozen 30000 ms in all\n"
    "[sw] 121000 ms +59f -20m\n"
)


def test_a_boot_saves_the_titles_nvram_and_its_settings(tmp_path):
    root, logdir = _rig(tmp_path)
    env = {"PAD_CARD": "", "PAD_SLOT": "0", "PAD_OVERRIDE_DIR": str(tmp_path / "ovr"), "HOME": "/x",
           "PAD_SELECT": "1"}
    rec = runrec.start(logdir, root, "godzilla_le", os.path.join(logdir, "gzwatch.log"), env=env)
    nv = os.path.join(rec, "nvram")
    with open(os.path.join(nv, "nv", "godzilla_le", "NVRAM", "00000001.nv"), "rb") as f:
        assert f.read() == b"last place: TOKYO"
    for rel in ("nvram-godzilla_le.bin", "codeselect.last", "nv.own/heisei/godzilla_le/NVRAM/1.nv"):
        assert os.path.isfile(os.path.join(nv, rel)), rel
    assert not os.path.exists(os.path.join(nv, "nv", "jaws_le"))       # only the title that boots
    with open(os.path.join(rec, "run.json")) as f:
        info = json.load(f)
    assert info["game"] == "godzilla_le" and info["boot"] == "start"
    assert set(info["nvram"]) == {"nv/godzilla_le", "nvram-godzilla_le.bin", "codeselect.last",
                                  "nv.own/heisei/godzilla_le"}
    assert info["env"] == {k: v for k, v in env.items() if k.startswith("PAD_")}   # every PAD_ setting, no others
    assert info["edits"] == {"path": str(tmp_path / "ovr"), "manifest_sha1": None}
    with open(os.path.join(logdir, "runs", runrec.CURRENT)) as f:
        assert f.read().strip() == os.path.basename(rec)


def test_the_boot_ends_with_its_switch_log_beside_the_nvram(tmp_path):
    root, logdir = _rig(tmp_path)
    log = os.path.join(logdir, "gzwatch.log")
    rec = runrec.start(logdir, root, "godzilla_le", log, env={})
    _write(log, SESSION.encode())
    assert runrec.finish(logdir) == rec
    with open(os.path.join(rec, runrec.SWITCHES)) as f:
        lines = f.read().splitlines()
    assert lines == ["[pause] 100 ms frozen 0 ms in all", "[sw] 60006 ms +5k", "[sw] 60126 ms -5k +66b",
                     "[swspin] 71996 ms id=85 node=9 rip START", "[swspin] 72162 ms id=85 node=9 rip END",
                     "[pause] 120000 ms frozen 30000 ms in all", "[sw] 121000 ms +59f -20m"]
    with open(os.path.join(rec, "run.json")) as f:
        assert json.load(f)["switch_lines"] == 3
    assert not os.path.exists(os.path.join(logdir, "runs", runrec.CURRENT))
    assert runrec.finish(logdir) is None                     # once only


def test_a_checkpointable_run_reads_the_guests_own_log_first(tmp_path):
    root, logdir = _rig(tmp_path)
    rec = runrec.start(logdir, root, "godzilla_le", os.path.join(logdir, "gzwatch.log"), env={"PAD_PIVOT": "1"})
    _write(os.path.join(root, "dump", "game.out"), b"[sw] 1 ms +5k\n")
    _write(os.path.join(logdir, "gzwatch.log"), b"[sw] 1 ms +5k\n[sw] 2 ms -5k\n")
    runrec.finish(logdir)
    with open(os.path.join(rec, runrec.SWITCHES)) as f:
        assert f.read() == "[sw] 1 ms +5k\n"


def test_a_killed_run_is_finished_by_the_next_boot_from_the_log_it_left(tmp_path):
    root, logdir = _rig(tmp_path)
    log = os.path.join(logdir, "gzwatch.log")
    first = runrec.start(logdir, root, "godzilla_le", log, env={}, now=time.time() - 60)
    _write(log, b"[sw] 61000 ms +5k\n")                       # its watch.sh was killed: no finish
    second = runrec.start(logdir, root, "godzilla_le", log, env={})
    assert second != first
    with open(os.path.join(first, runrec.SWITCHES)) as f:
        assert f.read() == "[sw] 61000 ms +5k\n"


def test_a_log_older_than_the_boot_is_not_its_record(tmp_path):
    root, logdir = _rig(tmp_path)
    log = os.path.join(logdir, "gzwatch.log")
    _write(log, b"[sw] 61000 ms +5k\n")
    old = time.time() - 3600
    os.utime(log, (old, old))
    rec = runrec.start(logdir, root, "godzilla_le", log, env={})
    runrec.finish(logdir)
    with open(os.path.join(rec, runrec.SWITCHES)) as f:
        assert f.read() == ""


def test_only_the_newest_recordings_stay(tmp_path):
    root, logdir = _rig(tmp_path)
    now = time.time()
    recs = [runrec.start(logdir, root, "godzilla_le", "/nowhere", env={"PAD_RUN_KEEP": "3"}, now=now + i)
            for i in range(5)]
    runrec.finish(logdir)
    assert runrec.recordings(logdir) == recs[:1:-1]


def test_restore_puts_the_recorded_nvram_back_and_nothing_of_the_rigs(tmp_path):
    root, logdir = _rig(tmp_path)
    rec = runrec.start(logdir, root, "godzilla_le", "/nowhere", env={})
    runrec.finish(logdir)
    other = str(tmp_path / "other")
    _write(os.path.join(other, "data", "nv", "godzilla_le", "NVRAM", "00000001.nv"), b"last place: OSAKA")
    _write(os.path.join(other, "data", "nv", "godzilla_le", "NVRAM", "extra.nv"), b"the rig's own")
    _write(os.path.join(other, "data", "nv", "jaws_le", "x"), b"left alone")
    runrec.restore(rec, other)
    nvd = os.path.join(other, "data", "nv")
    with open(os.path.join(nvd, "godzilla_le", "NVRAM", "00000001.nv"), "rb") as f:
        assert f.read() == b"last place: TOKYO"
    assert not os.path.exists(os.path.join(nvd, "godzilla_le", "NVRAM", "extra.nv"))
    assert os.path.isfile(os.path.join(nvd, "jaws_le", "x"))
    assert os.path.isfile(os.path.join(other, "data", "nv.own", "heisei", "godzilla_le", "NVRAM", "1.nv"))


def test_a_launch_that_brought_its_own_modes_keeps_them(tmp_path):
    root, logdir = _rig(tmp_path)
    _write(os.path.join(root, "lib", "pad_mode.so"), b"ELF")
    for n in ("game.port", "mode1.cfg", "kaiju.assets", "mode.log"):
        _write(os.path.join(root, "dump", n), b"x")
    rec = runrec.start(logdir, root, "godzilla_le", "/nowhere", env={"PAD_MODE_SO": "/lib/pad_mode.so"})
    assert sorted(os.listdir(os.path.join(rec, "modes"))) == ["game.port", "kaiju.assets", "mode1.cfg",
                                                              "pad_mode.so"]
    keep, _warn = runrec.replay_env(rec, env={})
    assert keep["PAD_MODE_SO"] == "/lib/pad_mode.so"
    # a card's own modes are the card's: nothing kept
    rec2 = runrec.start(logdir, root, "godzilla_le", "/nowhere", env={})
    assert not os.path.exists(os.path.join(rec2, "modes"))


def test_a_replay_boots_with_the_runs_settings_on_its_own_rig(tmp_path):
    root, logdir = _rig(tmp_path)
    card = str(tmp_path / "card.raw")
    _write(card, b"card")
    ovr = str(tmp_path / "ovr")
    _write(os.path.join(ovr, "overrides.json"), b'{"v": 1}')
    env = {"PAD_CARD": card, "PAD_OVERRIDE_DIR": ovr, "PAD_SLOT": "0", "PAD_ROOT": root, "PAD_LOGDIR": logdir,
           "PAD_LABEL": "David", "PAD_BALL_FEED": "1", "PAD_SELECT": "0", "WSL_DISTRO_NAME": "Ubuntu"}
    rec = runrec.start(logdir, root, "godzilla_le", "/nowhere", env=env)
    keep, warn = runrec.replay_env(rec, env={"WSL_DISTRO_NAME": "Ubuntu"})
    assert keep == {"PAD_CARD": card, "PAD_OVERRIDE_DIR": ovr, "PAD_SELECT": "0"}
    assert warn == []
    _write(os.path.join(ovr, "overrides.json"), b'{"v": 2}')
    os.utime(card, (1, 1))                              # a boot's mount moves the mtime: not a change
    assert runrec.replay_env(rec, env={"WSL_DISTRO_NAME": "Ubuntu"})[1] == ["the edits folder %s holds another set now (the project's edits changed since)" % ovr]
    _write(card, b"another card")
    _keep, warn = runrec.replay_env(rec, env={"WSL_DISTRO_NAME": "PAD-Runtime"})
    assert any("recorded in Ubuntu" in w for w in warn)
    assert any("card" in w and "changed" in w for w in warn)
    assert any("edits" in w for w in warn)


def test_the_replay_times_every_change_on_the_games_own_clock(tmp_path):
    p = str(tmp_path / "switches.log")
    _write(p, SESSION.encode())
    evs = swreplay.read_events(p)
    assert evs == [
        (60006, "sw", 5, True),
        (60126, "sw", 5, False), (60126, "sw", 66, True),       # one line keeps its order
        (71996, "spin", 85, True), (72162, "spin", 85, False),
        (121000 - 30000, "sw", 59, True),                       # after a 30 s Pause: 30 s less game time
    ]                                                          # -20m: the shim's own motor, never replayed
    assert [e[2] for e in swreplay.read_events(p, skip="b")] == [5, 5, 85, 85, 59]
    assert swreplay.source_file(str(tmp_path)) == p


def test_a_restart_boot_counts_pauses_from_its_own_start(tmp_path):
    """A Restart game keeps the block, so the boot finds the last boot's total."""
    p = str(tmp_path / "switches.log")
    _write(p, b"[pause] 50 ms frozen 12000 ms in all (at boot)\n[sw] 500 ms +5k\n"
              b"[pause] 5000 ms frozen 14000 ms in all\n[sw] 6000 ms -5k\n")
    assert swreplay.read_events(p) == [(500, "sw", 5, True), (6000 - 2000, "sw", 5, False)]


def test_dry_replay_prints_the_timeline(tmp_path, capsys):
    p = str(tmp_path / "switches.log")
    _write(p, SESSION.encode())
    assert swreplay.main([p, "--dry", "--from", "70000"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("replay: 3 switch changes")
    assert out[1:] == ["71996 spin +85", "72162 spin -85", "91000 sw +59"]


def test_watch_records_every_boot_before_its_log_goes():
    src = _text("watch.sh")
    body = src[src.index("launch_game() {"):src.index("\nlaunch_game\n")]
    rec = body.index('runrec.py" start')
    assert rec < body.index('rm -f "$ROOT/dump/game.out"')       # the last boot's log is read first
    assert rec < body.index('> "$LOG" 2>&1 &')                    # and before the new boot truncates $LOG
    assert '"${BOOT_KIND:-start}"' in body
    assert "BOOT_KIND=restart launch_game" in src                # Restart game: its own recording
    td = src[src.index("teardown() {"):src.index("trap 'teardown; exit 130' INT TERM")]
    assert td.index('runrec.py" finish') > td.index("pad_pkill -9 -x game")   # the guest is gone first
    assert '${PAD_RECORD:-1}' in body and '${PAD_RECORD:-1}' in td


def test_stop_writes_the_switch_log_watch_never_got_to():
    """The app's Stop is killgame.sh, which kills watch.sh before its teardown:
    the first rig recording here ended with no switch log until it did this."""
    src = _text("killgame.sh")
    fin = src.index('runrec.py" finish "$PAD_LOGDIR"')
    assert fin > src.index("pad_pkill -9 -x game")
    assert fin > src.index('[ -n "$_rs" ] && kill -9 $_rs')      # after watch.sh itself is gone


def test_replayrun_waits_for_the_new_boots_clock():
    """The block outlives a run: the last guest's clock origin is cleared before
    the replay's boot, or the whole record goes in against a game still booting."""
    src = _text("replayrun.sh")
    assert src.index("padsw.OFF_GUEST_T0, 0") < src.index('setsid bash "$RIG/watch.sh"')
    rep = _text("swreplay.py")
    assert "OFF_GUEST_T0)[0] != boot" in rep                     # a reboot under the replay stops it


def test_a_save_state_load_ends_the_recording_before_the_log_is_cut():
    src = _text("loadgame.sh")
    assert src.index('runrec.py" finish') < src.index('bash "$RIG/restorestate.sh"')


def test_the_shim_logs_the_frozen_time_and_lasts_a_session():
    src = _text("hwshim.c")
    m = re.search(r"static void sw_shm_edges\(void\)\n\{(.*?)\n\}", src, re.S)
    body = m.group(1)
    assert '"[pause] %lu ms frozen %u ms in all%s\\n"' in body
    assert body.index("[pause]") < body.index("if (!on || budget <= 0) return;")   # whatever the log budget
    assert int(re.search(r"static int budget = (\d+);", body).group(1)) >= 100000
    assert int(re.search(r"static int sw_spin_budget = (\d+);", src).group(1)) >= 10000
    assert swreplay.PAUSE.search("[pause] 95000 ms frozen 30000 ms in all")
    assert runrec.RECORD_LINE.search("[pause] 95000 ms frozen 30000 ms in all (at boot)")


def test_replayrun_never_takes_rig_0_and_turns_the_live_helpers_off():
    src = _text("replayrun.sh")
    assert 'if [ -z "$SLOT" ] || [ "$SLOT" = 0 ]' in src
    assert '[ "$WANT" = 0 ] && {' in src
    exports = re.search(r"\nexport PAD_HIDDEN=1 [^\n]*", src).group(0)
    for k in ("PAD_AUDIO=0", "PAD_BALL_FEED=0", "PAD_AUTO_ATTRACT=0", "PAD_RECORD=0"):
        assert k in exports
    assert src.index("eval \"$ENVS\"") < src.index(exports.strip())   # the recording cannot turn them back on
