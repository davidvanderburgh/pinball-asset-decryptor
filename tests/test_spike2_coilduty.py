"""PAD-670: coilduty.py tallies how long a drive really ran from a run's [coildrive] lines - the measurement the shaker's
30 s a minute stands on (the stock game's busiest minute, MODE_SDK.md "The shaker").

What is worth failing on: a later fire takes over what was left (not added to it), an OFF cuts a run short, another
drive's lines are not counted, and the busiest 60 s is found wherever it starts."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("coilduty", ROOT / "tools" / "spike2_emu" / "coilduty.py")
CD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CD)


def fire(t, ms, node=1, coil=0, pwr=31):
    return ("[coildrive] %d ms node %d coil %d: pulse %d/255 for %d ms, hold 0/255 for 0 ms (%d+0 ticks at 100/s)"
            % (t, node, coil, pwr, ms, ms // 10))


def off(t, node=1, coil=0):
    return "[coildrive] %d ms node %d coil %d: OFF (cmd 4d), 0 ms of its last command left" % (t, node, coil)


def test_a_take_over_replaces_what_was_left_and_an_off_cuts_it():
    lines = [fire(1000, 500), fire(1200, 1000),      # taken over at 1.2 s: runs to 2.2 s, not 2.7
             fire(5000, 5000), off(6000),             # stopped after 1 s
             fire(7000, 200, node=8)]                 # another drive
    assert CD.runs(lines) == [[1000, 2200], [5000, 6000]]


def test_the_busiest_minute_wherever_it_starts():
    lines = [fire(0, 1000), fire(70000, 2000), fire(100000, 3000), fire(125000, 4000)]
    rs = CD.runs(lines)
    assert CD.busiest(rs) == (9000, 70000)            # 70 s .. 130 s holds the last three
    assert CD.on_in(rs, 0, 60000) == 1000


def test_the_report(tmp_path, capsys):
    log = tmp_path / "gzwatch.log"
    log.write_text("\n".join([fire(1000, 2000), "[event] something else", fire(4000, 5000)]) + "\n")
    assert CD.main([str(log)]) == 0
    out = capsys.readouterr().out
    assert "7.0 s running in all" in out and "longest unbroken run: 5.00 s" in out
    assert CD.main([str(log), "9", "3"]) == 1
