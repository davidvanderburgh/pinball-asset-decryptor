"""PAD-1181: the playfield window's ball controls on a Spike 3 run, as on
Spike 2. The window reads the live switches (s3keys publishes them into the
padsw block's merged array); Plunge / Drain / Reset balls / the trough dots
run plunge.py, which on a Spike 3 slot hands the move to the bridge's ball
model (s3balls) through a request file; a drain rolls over the trough's open
positions from the far end; a trough eject that meets a ball in the shooter
lane is held until the lane clears (multiball)."""
import os
import struct
import subprocess
import sys
import threading
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
S3 = os.path.join(HERE, "..", "tools", "spike3_emu")
S2 = os.path.join(HERE, "..", "tools", "spike2_emu")
sys.path.insert(0, S3)

import s3balls  # noqa: E402
import s3bridge  # noqa: E402

# pokemon_le's own names and places (s3nodes.devices, node 8)
DEVS = [
    ("TROUGH 6", 8, 32, "switch"), ("TROUGH 5", 8, 33, "switch"), ("TROUGH 4", 8, 34, "switch"),
    ("TROUGH 3", 8, 35, "switch"), ("TROUGH 2", 8, 36, "switch"), ("TROUGH 1", 8, 37, "switch"),
    ("TROUGH JAM", 8, 38, "switch"), ("SHOOTER LANE", 8, 28, "switch"),
    ("LEFT SLINGSHOT", 8, 29, "switch"), ("TROUGH", 8, 1, "coil"), ("AUTO PLUNGER", 8, 4, "coil"),
]
TROUGH = [(8, 37), (8, 36), (8, 35), (8, 34), (8, 33), (8, 32)]   # position 1 first
LANE = (8, 28)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(s3balls, "ALIVE_S", 0)            # no keep-alive taps here


def _balls(d=None):
    sw = bytearray(512)
    return sw, s3balls.Balls(sw, s3balls.resolve(DEVS), d=str(d) if d else None)


def _run(b, secs, trace=None):
    """Tick for SECS; with TRACE (a list), record every trough/lane edge."""
    last = {nb: b.made(nb) for nb in TROUGH + [LANE]}
    end = time.time() + secs
    while time.time() < end:
        b.tick()
        if trace is not None:
            for nb in TROUGH + [LANE]:
                v = b.made(nb)
                if v != last[nb]:
                    last[nb] = v
                    trace.append((nb, v))
        time.sleep(0.002)


def _serve(b):
    """The game's own trough eject: a ball to the shooter lane."""
    b.coil(8, bytes([0x40, 1, 0xFF] + [0] * 8))               # boot configuration
    b.coil(8, bytes([0x40, 1, 0xE1, 6] + [0] * 7))            # a fire
    _run(b, 0.7)


def flags(b):
    return [b.made(nb) for nb in TROUGH]


def test_plunge_launches_only_the_ball_in_the_lane():
    _sw, b = _balls()
    assert b.ask("plunge").startswith("nothing in the shooter lane")
    assert b.home() == 6                                     # a Plunge never ejects
    _serve(b)
    assert b.home() == 5 and b.made(LANE)
    assert b.ask("plunge") == "shooter lane opened (ball launched)"
    assert not b.made(LANE) and b.out() == 1
    assert "a ball is in play" in b.ask("plunge")


def test_drain_refused_while_the_ball_waits_in_the_lane():
    _sw, b = _balls()
    assert b.ask("drain").startswith("the trough is already full")
    _serve(b)
    assert b.ask("drain").startswith("the ball is still in the shooter lane")
    assert b.home() == 5 and b.made(LANE)


def test_drain_rolls_over_the_open_positions_from_the_far_end():
    """Three balls out: the drained ball closes and opens TROUGH 6, then 5,
    and settles on 4 - Spike 2's PAD-186 roll, not a lone closure of 4."""
    _sw, b = _balls()
    for _ in range(3):
        b.ask("take")
    assert flags(b) == [True, True, True, False, False, False]
    trace = []
    assert b.ask("drain").startswith("trough 4 closed")
    _run(b, 0.5, trace)
    assert trace == [((8, 32), True), ((8, 32), False), ((8, 33), True), ((8, 33), False),
                     ((8, 34), True)]
    assert flags(b) == [True, True, True, True, False, False]


def test_drains_queue_behind_a_roll_and_each_rolls():
    _sw, b = _balls()
    for _ in range(3):
        b.ask("take")
    assert b.ask("drain").startswith("trough 4")
    assert b.ask("drain") is None                            # queued behind the roll
    assert b.ask("drain") is None
    _run(b, 1.2)
    assert b.home() == 6 and b.out() == 0


def test_take_puts_a_ball_on_the_playfield_from_the_far_end():
    _sw, b = _balls()
    assert b.ask("take").startswith("trough 6 opened")
    assert flags(b) == [True] * 5 + [False] and b.out() == 1
    for _ in range(5):
        b.ask("take")
    assert b.ask("take") == "the trough is empty - nothing to take out"


def test_reset_puts_every_ball_home_and_clears_the_lane():
    _sw, b = _balls()
    _serve(b)
    b.ask("take")
    b.ask("reset")
    assert b.home() == 6 and not b.made(LANE) and b.out() == 0


def test_serve_ejects_lands_and_launches():
    _sw, b = _balls()
    assert b.ask("serve") == "a ball served from the trough and launched"
    _run(b, 0.6)
    assert b.made(LANE) and b.home() == 5
    _run(b, 1.4)
    assert not b.made(LANE) and b.out() == 1


def test_multiball_eject_held_until_the_lane_clears():
    """A manual-plunger multiball: the game ejects while ball 1 waits in the
    lane - held, not dropped; each Plunge brings the next ball."""
    _sw, b = _balls()
    _serve(b)
    b.coil(8, bytes([0x40, 1, 0xE1, 6] + [0] * 7))           # the 2nd ball, lane full
    _run(b, 0.7)
    assert b.home() == 5 and b.eject_held
    b.ask("plunge")
    _run(b, 0.8)
    assert b.home() == 4 and b.made(LANE) and not b.eject_held and b.out() == 1


def test_auto_plunger_multiball_serves_every_ball():
    _sw, b = _balls()
    b.coil(8, bytes([0x40, 1, 0xFF] + [0] * 8))
    b.coil(8, bytes([0x40, 4, 0xFF] + [0] * 8))
    for n in range(3):
        b.coil(8, bytes([0x40, 1, 0xE1, 6] + [0] * 7))
        _run(b, 0.7)
        assert b.made(LANE)
        b.coil(8, bytes([0x40, 4, 0x96, 6] + [0] * 7))
        _run(b, 0.1)
    assert b.home() == 3 and b.out() == 3 and not b.made(LANE)


def test_window_requests_are_answered_and_the_note_published(tmp_path):
    dump = tmp_path / "dump"
    dump.mkdir()
    _sw, b = _balls(tmp_path)
    (dump / (s3balls.REQ_PREFIX + "1")).write_text("take\n")
    (dump / (s3balls.REQ_PREFIX + "2")).write_text("drain\n")
    _run(b, 0.4)
    assert (dump / (s3balls.ANS_PREFIX + "1")).read_text().startswith("trough 6 opened")
    assert (dump / (s3balls.ANS_PREFIX + "2")).read_text().startswith("trough 6 closed")
    assert not list(dump.glob(s3balls.REQ_PREFIX + "*"))
    note = (dump / "padball").read_text().splitlines()
    assert note[0] == "fed 0" and any("taken out of the trough" in ln for ln in note)
    assert any(ln.startswith("drain: a ball rolls into the trough") for ln in note)


def _bridge_thread(b, stop):
    while not stop.is_set():
        b.tick()
        time.sleep(0.01)


def test_plunge_py_hands_the_window_buttons_to_the_spike3_bridge(tmp_path):
    """The window's Plunge / Drain / Reset balls run plunge.py: on a Spike 3
    slot (its root holds balls.json) it asks the bridge and prints the answer."""
    (tmp_path / "dump").mkdir()
    _sw, b = _balls(tmp_path)                              # writes balls.json
    assert (tmp_path / "balls.json").exists()
    stop = threading.Event()
    t = threading.Thread(target=_bridge_thread, args=(b, stop), daemon=True)
    t.start()
    env = dict(os.environ, PAD_ROOT=str(tmp_path), PAD_SW_FILE=str(tmp_path / "padsw"),
               PAD_TABLES=str(tmp_path / "tables"))

    def plunge(verb):
        return subprocess.run([sys.executable, os.path.join(S2, "plunge.py"), verb], env=env,
                              capture_output=True, text=True, timeout=30, cwd=S2)
    try:
        r = plunge("plunge")
        assert r.returncode == 1 and r.stdout.startswith("nothing in the shooter lane to launch")
        r = plunge("take")
        assert r.returncode == 0 and "trough 6 opened" in r.stdout, r.stdout + r.stderr
        r = plunge("drain")
        assert r.returncode == 0 and "trough 6 closed" in r.stdout
        time.sleep(0.3)
        assert b.home() == 6
        r = plunge("reset")
        assert r.returncode == 0 and "6 balls in the trough" in r.stdout
    finally:
        stop.set()
        t.join(2)


def test_plunge_py_stays_on_spike2_without_balls_json(tmp_path, monkeypatch):
    sys.path.insert(0, S2)
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    import importlib
    import padpath
    importlib.reload(padpath)
    monkeypatch.setenv("PAD_TABLES", str(tmp_path / "tables"))
    import s3ballask
    assert s3ballask.spike3_dir() is None
    (tmp_path / "balls.json").write_text("{}")
    assert s3ballask.spike3_dir() == str(tmp_path)              # no dump/: the slot itself
    (tmp_path / "dump").mkdir()
    assert s3ballask.spike3_dir() == str(tmp_path / "dump")


def test_window_reads_the_live_spike3_switches(tmp_path, monkeypatch):
    """s3keys publishes nodesw / spi.in into the block's merged array, so the
    window's trough dots and BALLS line follow the ball model."""
    import s3keys
    table = {"TROUGH 1": [8, 37], "TROUGH 6": [8, 32], "SHOOTER LANE": [8, 28],
             "SERVICE SELECT": [0, 8], "START BUTTON": [1, 11]}
    rows = s3bridge.write_switch_list(table, str(tmp_path / "t" / "switch_list.txt"))
    ids = {name: sid for sid, node, bit, name in rows}
    slot = tmp_path / "slot7"
    slot.mkdir()
    sw = bytearray(512)
    sw[8 * 8 + 4] |= 0x20                                    # TROUGH 1 (8, 37) made
    sw[8 * 8 + 3] |= 0x10                                    # SHOOTER LANE (8, 28) made
    (slot / "nodesw").write_bytes(bytes(sw))
    (slot / "spi.in").write_bytes(b"\xfe" + b"\xff" * 7)     # SPI bit 0 held: SERVICE SELECT
    padsw = tmp_path / "padsw"
    blk = bytearray(4096)
    struct.pack_into("<I", blk, 0, s3keys.MAGIC)
    padsw.write_bytes(bytes(blk))
    monkeypatch.setattr(s3keys, "BASE", str(tmp_path / "slot%s"))
    k = s3keys.Keys("7", str(padsw), str(tmp_path / "t" / "switch_list.txt"))
    assert k.attach() and k.writable
    assert k.publish()
    k.mm.flush()
    k.mm.close()
    k.mm = None
    d = padsw.read_bytes()
    assert struct.unpack_from("<I", d, s3keys.OFF_MRG_GEN)[0] >= 1
    mrg = d[s3keys.OFF_MRG:s3keys.OFF_MRG + 256]
    assert mrg[ids["TROUGH 1"]] == 1 and mrg[ids["SHOOTER LANE"]] == 1
    assert mrg[ids["TROUGH 6"]] == 0 and mrg[ids["START BUTTON"]] == 0
    assert mrg[ids["SERVICE SELECT"]] == 1
    # the window's reader takes the merged array once its generation moved
    sys.path.insert(0, S2)
    assert s3keys.OFF_MRG_GEN == 536 and s3keys.OFF_MRG == 540
    import padsw as P
    assert (P.OFF_MRG_GEN, P.OFF_MRG) == (s3keys.OFF_MRG_GEN, s3keys.OFF_MRG)
    # nothing changed: no new generation
    assert k.attach()
    assert not k.publish()


def test_auto_plunger_marker_launches_through_the_spike3_bridge(tmp_path):
    """The artwork's AUTO PLUNGER coil marker (coilact.py) opens the lane by
    the bridge's Plunge on a Spike 3 slot, not by writing the switch itself."""
    (tmp_path / "dump").mkdir()
    _sw, b = _balls(tmp_path)
    _serve(b)
    assert b.made(LANE)
    stop = threading.Event()
    t = threading.Thread(target=_bridge_thread, args=(b, stop), daemon=True)
    t.start()
    env = dict(os.environ, PAD_ROOT=str(tmp_path), PAD_SW_FILE=str(tmp_path / "padsw"),
               PAD_TABLES=str(tmp_path / "tables"))
    try:
        r = subprocess.run([sys.executable, os.path.join(S2, "coilact.py"), "AUTO PLUNGER"], env=env,
                           capture_output=True, text=True, timeout=30, cwd=S2)
        assert r.returncode == 0 and "shooter lane opened" in r.stdout, r.stdout + r.stderr
        assert not b.made(LANE) and b.out() == 1
    finally:
        stop.set()
        t.join(2)
