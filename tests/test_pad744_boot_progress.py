"""PAD-744: how far the game has booted, in the playfield window and the app.

David: "it would be good to show progress here [the playfield window] while
the emulator is booting up (like we do in the app window) since it can be at
80% for a bit while node boards come up". bootprog.py reads the steps inside
Boot and Node boards off the run's logs (the lines and their order timed on
four titles); the window's bar and status.sh's boot_pct both come from it.
"""

import os
import struct
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
if RIG not in sys.path:
    sys.path.insert(0, RIG)
import bootprog                                          # noqa: E402

try:
    import playfield as pf
except Exception:                                        # noqa: BLE001
    pf = None
needs_pf = pytest.mark.skipif(pf is None, reason="playfield not importable")

BOOTED = ('[gst] factory_make("qtdemux","demuxer") -> ok\n'
          '[gst] factory_make("queue","videoqueue") -> ok\n'
          '[gst] factory_make("vpudec","videodecoder") -> ok\n')
NODES = "[nbsched] playfield nodes: 4 1 8 9 7 12 14 (from switch table + node directory)\n"
PROBE = "[nb] ExchangeData: read failed node=2\n"
ATTRACT = ("[led] light show running: 30 lamp commands in 167 ms and the "
           "picture is moving (last node=8 cmd=97, 15127 ms)\n")


def _add(path, text):
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(text)


def test_the_steps_in_order(tmp_path):
    log, auto = tmp_path / "gzwatch.log", tmp_path / "padauto.log"
    b = bootprog.BootLog(str(tmp_path))
    assert b.poll() is None                               # no run log yet
    _add(log, "[run] node bus pty: /dev/pts/3\n")
    assert b.poll() == ("booting", 55, "Booting the game…")
    _add(log, BOOTED)
    assert b.poll() == ("techalerts", 80, "Bringing up node boards…")
    _add(log, NODES)
    assert b.poll() == ("techalerts", 84, "Node boards: 7 found")
    _add(log, PROBE * 1500)
    st, pct, words = b.poll()
    assert (st, pct) == ("techalerts", 88) and words == "Node boards: 7 found, checking the rest (1500)"
    _add(log, PROBE * 3000)
    assert b.poll()[1] == 92                              # stops short of the press
    _add(auto, "[auto] bus quiet after 14s (3574 probes); pressing Service Back once (2000ms)\n")
    assert b.poll() == ("techalerts", 95, "Passing Tech Alerts…")
    _add(log, ATTRACT)
    assert b.poll() == ("attract", 100, "Ready")


def test_a_line_split_across_reads_counts_once(tmp_path):
    log = tmp_path / "gzwatch.log"
    b = bootprog.BootLog(str(tmp_path))
    _add(log, BOOTED + NODES[:20])
    assert b.poll()[1] == 80
    _add(log, NODES[20:])
    assert b.poll()[2] == "Node boards: 7 found"


def test_a_new_launch_starts_the_count_over(tmp_path):
    """watch.sh truncates the log on every launch, Restart game's included."""
    log = tmp_path / "gzwatch.log"
    b = bootprog.BootLog(str(tmp_path))
    _add(log, BOOTED + NODES + PROBE * 50 + ATTRACT)
    assert b.poll()[0] == "attract"
    log.write_text("[run] node bus pty: /dev/pts/4\n")
    assert b.poll() == ("booting", 55, "Booting the game…")


def test_a_helper_that_gave_up_says_so(tmp_path):
    _add(tmp_path / "gzwatch.log", BOOTED + NODES)
    _add(tmp_path / "padauto.log", "[auto] 5 presses did not clear it; gave up\n")
    st, pct, words = bootprog.BootLog(str(tmp_path)).poll()
    assert st == "techalerts" and "Stuck at Tech Alerts" in words


def test_the_command_line_status_sh_runs(tmp_path, capsys):
    _add(tmp_path / "gzwatch.log", BOOTED + NODES)
    assert bootprog.main(["bootprog.py", str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "boot_pct=84", "boot_words=Node boards: 7 found"]


def test_status_sh_asks_it_while_the_game_boots():
    with open(os.path.join(RIG, "status.sh"), encoding="utf-8") as f:
        sh = f.read()
    assert 'python3 "$S/bootprog.py"' in sh and '[ "$ST" != attract ]' in sh
    with open(os.path.join(RIG, "padpath.sh"), encoding="utf-8") as f:
        assert "PAD_LOGDIR/p" in f.read()      # the Windows window can find it


def _block(tmp_path, paused):
    padsw = pf.padsw
    p = tmp_path / "padsw"
    data = bytearray(padsw.SIZE)
    struct.pack_into("<I", data, 0, pf.PADSW_MAGIC)
    struct.pack_into("<I", data, padsw.OFF_PAUSED, paused)
    p.write_bytes(bytes(data))
    return str(p)


@needs_pf
def test_the_window_shows_the_boot_and_hides_it_once_up(monkeypatch, tmp_path):
    monkeypatch.setattr(pf, "SW_PATH", _block(tmp_path, 0))
    log = tmp_path / "gzwatch.log"
    _add(log, BOOTED + NODES)
    run = pf.RunCtl(None, logdir=str(tmp_path))
    assert run.poll(10.0) is True
    assert run.dyn()["boot"] == {"pct": 84, "words": "Node boards: 7 found"}
    _add(log, ATTRACT)
    assert run.poll(10.5) is False                        # paced: once a second
    assert run.poll(11.1) is True and run.dyn()["boot"] is None
    # no live run: no bar, whatever the log says
    log.write_text(BOOTED)
    monkeypatch.setattr(pf, "SW_PATH", str(tmp_path / "gone"))
    run.poll(12.2)
    assert run.dyn()["boot"] is None


@needs_pf
def test_restart_waits_for_the_new_boot_not_a_timer(monkeypatch, tmp_path):
    """With the log to read, Restarting… lasts until the old boot's log is
    gone (the new launch truncated it), however long the gap."""
    monkeypatch.setattr(pf, "SW_PATH", _block(tmp_path, 0))
    dump = tmp_path / "dump"
    dump.mkdir()
    monkeypatch.setattr(pf.padpath, "dump", lambda: str(dump))
    monkeypatch.setenv("PAD_SLOT", "0")
    log = tmp_path / "gzwatch.log"
    _add(log, BOOTED + NODES + ATTRACT)
    run = pf.RunCtl(str(tmp_path / "audio.json"), logdir=str(tmp_path))
    run.poll(1.0)
    assert run.dyn()["boot"] is None                      # the game is up
    assert run.ask_restart() is True
    os.remove(pf.restart_req_path(run.ctl_path))          # the app took it
    t = run._restart_t
    assert run._restart_pending(t + pf.RESTART_GRACE_S + 5) is True
    log.write_text("[run] node bus pty: /dev/pts/4\n")   # the new launch
    run.poll(2.1)
    assert run.dyn()["restarting"] is False
    assert run.dyn()["boot"] == {"pct": 55, "words": "Booting the game…"}


def test_the_page_draws_the_bar():
    with open(os.path.join(RIG, "pfpage", "pf.js"), encoding="utf-8") as f:
        js = f.read()
    body = js[js.index("function runCluster(R)"):]
    body = body[:body.index("\n  }\n") + 4]
    assert "r.boot.pct" in body and "r.boot.words" in body


def test_the_app_footer_takes_the_finer_percent():
    from pinball_decryptor.webui import window
    got = []
    w = window.WebWindow.__new__(window.WebWindow)
    w._running = False
    w._phases = {"emulate": window.EMULATE_PHASES}
    w._phase_index = {"emulate": -1}
    w.current_tab_key = lambda: "Emulate"
    w._set_footer = lambda **kw: got.append(kw)
    w.set_status = lambda text: None
    w.set_emulate_progress("techalerts", 88, "Bringing up node boards…",
                           tab="Emulate")
    assert got[-1]["pct"] == 88 and got[-1]["index"] == 2
    w.set_emulate_progress("techalerts", None, "", tab="Emulate")
    assert got[-1]["pct"] == 80                           # as before without it
