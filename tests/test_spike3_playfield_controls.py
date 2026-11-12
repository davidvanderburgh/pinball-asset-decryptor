"""PAD-1183: every control and readout of the virtual playfield window on a
Spike 3 run - the parts the Spike 2 guest shim does there, done by the Spike 3
rig's own helpers, each checked here without a card or a game."""
import os
import re
import signal
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S3 = os.path.join(ROOT, "tools", "spike3_emu")
S2 = os.path.join(ROOT, "tools", "spike2_emu")
for p in (S3, S2):
    if p not in sys.path:
        sys.path.insert(0, p)

import coilact  # noqa: E402
import coilmap  # noqa: E402
import padsw  # noqa: E402
import s3bridge  # noqa: E402
import s3keys  # noqa: E402

needs_ftruncate = pytest.mark.skipif(sys.platform == "win32" and not hasattr(os, "ftruncate"),
                                     reason="needs ftruncate")

TABLE = {"COIN DOOR POWER INTERLOCK": [0, 23], "SERVICE SELECT": [0, 8],
         "START BUTTON": [1, 11], "TROUGH 1": [8, 37], "SPINNER OPTO": [9, 12],
         "LEFT FLIPPER BUTTON": [8, 25]}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A slot directory, its switch list and a padsw block; returns
    (keys, ids, slot dir)."""
    rows = s3bridge.write_switch_list(TABLE, str(tmp_path / "t" / "switch_list.txt"))
    ids = {name: sid for sid, node, bit, name in rows}
    slot = tmp_path / "slot7"
    slot.mkdir()
    (slot / "nodesw").write_bytes(bytes(512))
    (slot / "spi.in").write_bytes(b"\xff" * 8)
    blk = bytearray(4096)
    struct.pack_into("<I", blk, 0, s3keys.MAGIC)
    (tmp_path / "padsw").write_bytes(bytes(blk))
    monkeypatch.setattr(s3keys, "BASE", str(tmp_path / "slot%s"))
    k = s3keys.Keys("7", str(tmp_path / "padsw"), str(tmp_path / "t" / "switch_list.txt"))
    assert k.attach() and k.writable
    yield k, ids, slot
    k.mm.close()


def door_closed(slot):
    """SPI bit 15 (CPU index 23), active low."""
    return not (slot / "spi.in").read_bytes()[1] & 0x80


def test_offsets_are_padsw_h():
    """s3keys carries its own copy of the block's layout; padsw.py is the one
    definition on the Python side."""
    assert (s3keys.OFF_HELD, s3keys.OFF_SCR_HELD, s3keys.OFF_MRG_GEN, s3keys.OFF_MRG,
            s3keys.OFF_GUEST_T0, s3keys.OFF_SPIN, s3keys.OFF_CAB, s3keys.OFF_SCR_CAB,
            s3keys.OFF_STOP_WANT, s3keys.OFF_STOP_GEN, s3keys.OFF_STOP_N,
            s3keys.OFF_STOP_ACK) == (
        padsw.OFF_HELD, padsw.OFF_SCR_HELD, padsw.OFF_MRG_GEN, padsw.OFF_MRG,
        padsw.OFF_GUEST_T0, padsw.OFF_SPIN, padsw.OFF_CAB, padsw.OFF_SCR_CAB,
        padsw.OFF_STOP_WANT, padsw.OFF_STOP_GEN, padsw.OFF_STOP_N, padsw.OFF_STOP_ACK)


def test_the_door_click_opens_a_door_the_keyboard_latched_shut(rig):
    """padglhost latches the door shut in the KEYBOARD's half at window open;
    the playfield's door click is the SCRIPTS' half (take, then 0). With the
    old union merge the door never opened; last edge wins, as on Spike 2."""
    k, ids, slot = rig
    door = ids["COIN DOOR POWER INTERLOCK"]
    k.mm[s3keys.OFF_HELD + door] = 1               # window-open latch
    k.step()
    assert door_closed(slot)
    k.mm[s3keys.OFF_SCR_HELD + door] = 1           # padsw.take(): silent
    k.step()
    assert door_closed(slot)
    k.mm[s3keys.OFF_SCR_HELD + door] = 0           # the click: open it
    k.step()
    assert not door_closed(slot)
    k.mm[s3keys.OFF_SCR_HELD + door] = 1           # and shut again
    k.step()
    assert door_closed(slot)


def test_what_the_game_is_handed_is_published_for_the_window(rig):
    """mrg[] is the switches as the bridge answers the game - the ball
    model's moves too - and guest_t0 says a game is there to take a write."""
    k, ids, slot = rig
    m = k.mm
    assert padsw.guest_ms(m) is not None
    k.step()
    gen = struct.unpack_from("<I", m, padsw.OFF_MRG_GEN)[0]
    assert gen >= 1 and not m[padsw.OFF_MRG + ids["TROUGH 1"]]
    b = bytearray((slot / "nodesw").read_bytes())
    b[8 * 8 + 37 // 8] |= 1 << (37 % 8)            # the ball model homes a ball
    (slot / "nodesw").write_bytes(bytes(b))
    k.step()
    assert m[padsw.OFF_MRG + ids["TROUGH 1"]] == 1
    assert struct.unpack_from("<I", m, padsw.OFF_MRG_GEN)[0] == gen + 1
    k.mm[s3keys.OFF_CAB + 4] = 1                    # SELECT, on the SPI chain
    k.step()
    assert m[padsw.OFF_MRG + ids["SERVICE SELECT"]] == 1
    k.step()                                        # nothing moved: no new gen
    assert struct.unpack_from("<I", m, padsw.OFF_MRG_GEN)[0] == gen + 2
    # and a script's write is adopted, so padsw.set_confirmed can see it land
    padsw.set_held(m, ids["START BUTTON"], 1)
    k.step()
    assert padsw.adopted(m, ids["START BUTTON"], 1)


def test_a_right_held_spinner_rips(rig):
    """spin[id] set = an edge every RIP_MS, so the game counts spins; let go,
    the spinner rests where the sources leave it."""
    k, ids, slot = rig
    sid = ids["SPINNER OPTO"]

    def made():
        return bool((slot / "nodesw").read_bytes()[8 * 9 + 1] & 0x10)
    k.step(now=0.0)
    assert not made()
    k.mm[s3keys.OFF_SPIN + sid] = 1
    seen = []
    for i in range(8):
        k.step(now=i * s3keys.RIP_MS / 1000.0 + 0.001)
        seen.append(made())
    assert seen == [True, False] * 4
    k.mm[s3keys.OFF_SPIN + sid] = 0
    k.step(now=1.0)
    assert not made()


def test_pause_is_served_for_the_renderer(rig, monkeypatch):
    """padglhost (PAD_PAUSE_KEEPER=1) asks with stop_want + a new stop_gen;
    the keeper stops the slot's game, answers stop_n then stop_ack, and
    resumes what it froze."""
    k, ids, slot = rig
    sent = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    monkeypatch.setattr(s3keys, "game_pids", lambda s: [4242])
    monkeypatch.setattr(signal, "SIGSTOP", getattr(signal, "SIGSTOP", 19), raising=False)
    monkeypatch.setattr(signal, "SIGCONT", getattr(signal, "SIGCONT", 18), raising=False)
    m = k.mm
    assert k.pause_serve() is None                  # nothing asked
    struct.pack_into("<II", m, padsw.OFF_STOP_WANT, 1, 1)
    assert k.pause_serve() == ("stop", 1)
    assert struct.unpack_from("<II", m, padsw.OFF_STOP_N) == (1, 1)
    assert k.pause_serve() is None                  # served once
    struct.pack_into("<II", m, padsw.OFF_STOP_WANT, 0, 2)
    assert k.pause_serve() == ("cont", 1)
    assert struct.unpack_from("<I", m, padsw.OFF_STOP_ACK)[0] == 2
    assert sent == [(4242, signal.SIGSTOP), (4242, signal.SIGCONT)]
    struct.pack_into("<II", m, padsw.OFF_STOP_WANT, 1, 3)
    k.pause_serve()
    k.thaw()                                        # the keeper exits: resumed
    assert sent[-1] == (4242, signal.SIGCONT)


def test_the_renderer_asks_the_keeper_on_a_window_run():
    src = open(os.path.join(S3, "s3run.sh"), encoding="utf-8").read()
    assert re.search(r"RENV=\(PAD_GL_WINDOW=1[^)]*PAD_PAUSE_KEEPER=1\)", src)


@needs_ftruncate
def test_coil_drives_reach_the_shaker_panel(tmp_path):
    """The 14-byte cmd 40 and cmd 4d fill padled v5's drive table as Spike 2's
    shim does, so coilmap.drive (the window's Shaker panel) reads them."""
    import s3leds
    led = s3leds.PadLed(str(tmp_path / "padled"))
    # node 3 coil 0 (a shaker): pulse 200/255 for 50 ticks, hold 120 for 250
    led.frame(3, bytes([0x40, 0, 200, 50, 0, 120, 250, 0, 0, 0, 0]))
    d = (tmp_path / "padled").read_bytes()
    got = coilmap.drive(d, 3, 0)
    assert got["until"] and got["pulse_pwr"] == 200 and got["hold_pwr"] == 120
    assert (got["pulse_ms"], got["hold_ms"]) == (500, 2500)
    assert d[coilmap.COIL_OFF + 3 * 16] == 1                     # and it flashes
    assert struct.unpack_from("<I", d, coilmap.DRIVE_FIRES_OFF)[0] == 1
    led.frame(3, bytes([0x4D, 0, 0]))                            # OFF
    assert coilmap.drive((tmp_path / "padled").read_bytes(), 3, 0)["until"] == 0
    led.frame(8, bytes([0x40, 2, 0]))                            # by its rule
    d = (tmp_path / "padled").read_bytes()
    assert struct.unpack_from("<I", d, s3leds.DRIVE_RULE_FIRES)[0] == 1
    assert struct.unpack_from("<I", d, s3leds.DRIVE_OFFS)[0] == 1
    led.close()


def test_a_coil_finds_its_switch_spelled_short():
    """pokemon_le: coil BOTTOM POP BUMPER, switch BOT POP BUMPER."""
    rows = [{"id": 99, "name": "BOT POP BUMPER"}, {"id": 98, "name": "TOP POP BUMPER"}]
    assert coilact.hold_switch("BOTTOM POP BUMPER", rows) == 99
    assert coilact.describe("BOTTOM POP BUMPER", rows) == "holds BOT POP BUMPER (99), which fires it"
    assert coilact.hold_switch("BOT POP BUMPER", [{"id": 5, "name": "BOTTOM POP BUMPER"}]) == 5
    assert coilact.hold_switch("TOP POP BUMPER", rows) == 98


def test_clip_lines_are_spike2s_for_the_clips_list(tmp_path):
    """s3vidhost names each clip start the way padvidhost does, so the
    window's CLIPS list (clipwatch) reads a Spike 3 run unchanged."""
    import clipwatch
    import s3vidhost
    log = s3vidhost.ClipLog(str(tmp_path / "padvid.log"))
    path = "/games/pokemon_le/assets/lcd/auto_loaded/60ed/scene.assets/2.asset/247.asset"
    log.serving(1, 1920, 1080, path, 121, 30.0)
    log.serving(0, 1920, 1080, "", 0, 0.0)          # unknown: no line
    lines = (tmp_path / "padvid.log").read_text().splitlines()
    assert len(lines) == 2
    m = clipwatch.LINE.search(lines[1])
    assert m and m.group(2) == "1" and m.group(3) == "121" and m.group(4) == path
    assert clipwatch.FPS.search(m.group(5)).group(1) == "30.00"
    assert clipwatch.short(path) == "2.asset/247.asset"


def _box(kind, body):
    return struct.pack(">I4s", 8 + len(body), kind) + body


def _qt(frames, scale, duration, handler=b"vide"):
    """A QuickTime file's skeleton: ftyp, then moov/trak/mdia with an mdhd,
    a hdlr and minf/stbl/stsz - the boxes s3vidhost.qt_length reads."""
    mdhd = _box(b"mdhd", bytes(4) + bytes(8) + struct.pack(">II", scale, duration) + bytes(4))
    hdlr = _box(b"hdlr", bytes(4) + bytes(4) + handler + bytes(12))
    stsz = _box(b"stsz", bytes(4) + struct.pack(">II", 0, frames))
    minf = _box(b"minf", _box(b"stbl", stsz))
    return (_box(b"ftyp", b"qt  " + bytes(4)) + _box(b"free", bytes(16))
            + _box(b"moov", _box(b"mvhd", bytes(100))
                   + _box(b"trak", _box(b"mdia", mdhd + hdlr + minf))))


def test_a_clips_length_is_read_off_its_own_file(tmp_path):
    """The game's demuxer cannot be asked which probe was which clip, so the
    host reads the clip's frame count and rate off the card's file - what
    clipwatch needs to tell a loop (the attract clip, 121 frames at 30)."""
    import s3vidhost
    rel = "games/pokemon_le/assets/lcd/x/scene.assets/2.asset/7.asset"
    p = tmp_path / rel
    p.parent.mkdir(parents=True)
    p.write_bytes(_qt(121, 3000, 12100))
    assert s3vidhost.qt_length(str(p)) == (121, 30.0)
    (tmp_path / "snd.asset").write_bytes(_qt(10, 1000, 1000, handler=b"soun"))
    assert s3vidhost.qt_length(str(tmp_path / "snd.asset")) == (0, 0.0)
    assert s3vidhost.qt_length(str(tmp_path / "missing.asset")) == (0, 0.0)
    log = s3vidhost.ClipLog(str(tmp_path / "padvid.log"), str(tmp_path))
    log.serving(1, 1920, 1080, "/" + rel, 0, 0.0)
    line = (tmp_path / "padvid.log").read_text().splitlines()[1]
    assert " 121 frames /%s (30.00 fps)" % rel in line


def test_the_feed_carries_each_clip_after_the_channels():
    """s3vid.h and s3vidhost.py agree: three clip words in the channel's
    spare room (still 32 words before the extradata), then one path per
    channel after the channel array."""
    import s3vidhost
    h = open(os.path.join(S3, "s3vid.h"), encoding="utf-8").read()
    assert "unsigned clip_frames, clip_rate_num, clip_rate_den;" in h
    assert "unsigned pad[14];" in h and "#define S3VID_PATH     256" in h
    assert "char clip[S3VID_CHANNELS][S3VID_PATH];" in h
    assert (s3vidhost.CLIP_FRAMES, s3vidhost.CLIP_RATE_DEN, s3vidhost.PATH) == (15, 17, 256)
    body = re.search(r"struct s3vid_chan \{(.*?)unsigned char extra", h, re.S).group(1)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    n = 0
    for decl in re.findall(r"unsigned\s+([^;]+);", body):
        for name in decl.split(","):
            size = re.search(r"\[(\d+)\]", name)
            n += int(size.group(1)) if size else 1
    assert n == 32                   # s3vidhost.CHAN_SZ's 32 * 4


def test_the_window_learns_the_runs_log_directory():
    """s3run.sh's launch line says where padvid.log is; the Emulate tab hands
    it to the window as PAD_LOGDIR (padpath.logdir)."""
    src = open(os.path.join(S3, "s3run.sh"), encoding="utf-8").read()
    assert re.search(r'"logdir=\$\(wslpath -w "\$SD"', src)
    tab = open(os.path.join(ROOT, "pinball_decryptor", "webui", "tabs", "emulate.py"),
               encoding="utf-8").read()
    assert '("logdir", "PAD_LOGDIR")' in tab
    from pinball_decryptor.webui import emulate_core
    f = emulate_core.playfield_launch(
        "PAD_PLAYFIELD_WINDOWS_LAUNCH game=pokemon_le savestates=1 root=X slot=33 "
        "root_wsl=/var/tmp/pad-s3/slot33 logdir=\\\\wsl.localhost\\Ubuntu\\var\\tmp\\pad-s3\\slot33")
    assert f["logdir"].endswith("slot33")
