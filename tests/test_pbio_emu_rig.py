"""tools/pbio_emu (PAD-272): the parts of the Pinball Brothers I/O-board rig
that can be checked without WSL - the emulated board's framing, answers and
state (pbioboard.py), its ball moves and Alien's tongue, the title profiles
(pbiotitles.py) and sw.py's switch names."""

import importlib.util
import json
import os
import pathlib
import sys

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "pbio_emu"


def _load(name, path):
    spec = importlib.util.spec_from_file_location("pbio_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(RIG))
board_mod = _load("board", RIG / "pbioboard.py")
titles = board_mod.pbiotitles
# sw.py reads the running rig's title at import: point it at no rig.
_root = os.environ.get("PBIO_ROOT")
os.environ["PBIO_ROOT"] = str(RIG / "no-such-rig")
try:
    sw = _load("sw", RIG / "sw.py")
finally:
    if _root is None:
        del os.environ["PBIO_ROOT"]
    else:
        os.environ["PBIO_ROOT"] = _root

ACK = bytes([0x52, 0x00])


def _board(tmp_path, monkeypatch, title="alien"):
    b = board_mod.Board(str(tmp_path), title=title, pty=False)
    b.sent = []
    monkeypatch.setattr(b, "send", lambda data: b.sent.append(bytes(data)))
    monkeypatch.setattr(b, "later", lambda secs, fn, *a: fn(*a))
    return b


@pytest.fixture
def board(tmp_path, monkeypatch):
    b = _board(tmp_path, monkeypatch)
    yield b
    b.log.close()


@pytest.fixture
def abba(tmp_path, monkeypatch):
    b = _board(tmp_path, monkeypatch, "abba")
    yield b
    b.log.close()


@pytest.fixture
def queen(tmp_path, monkeypatch):
    b = _board(tmp_path, monkeypatch, "queen")
    yield b
    b.log.close()


# --- framing ---------------------------------------------------------------

def test_frames_split_short_and_long_forms_and_keep_a_partial():
    buf = bytes([0xA2, 0x00, 0xA3, 0x53, 0x05, 0xA0, 0x34, 0x05, 0x01, 0x02,
                 0xA9, 0x4E])
    got, kept, skipped = board_mod.frames(buf)
    assert got == [b"\xa2\x00", b"\xa3\x53\x05", b"\xa0\x34\x05\x01\x02"]
    assert kept == b"\xa9\x4e"       # a coil request, 7 bytes still to come
    assert skipped == 0


def test_frames_skip_bytes_outside_a_frame():
    got, kept, skipped = board_mod.frames(b"\x00\x13\xa2\x01")
    assert got == [b"\xa2\x01"] and kept == b"" and skipped == 2


def test_every_command_is_acked_once(board):
    board.host_bytes("acm", bytes([0xA3, 0x14, 0x01, 0xA3, 0x61, 0x0B,
                                   0xA7, 0x34, 0x05, 0x00, 0x00, 0xFF, 0x00]))
    assert board.sent == [ACK, ACK, ACK]
    assert board.coils_enabled == 1 and 11 in board.gpio


# --- requests --------------------------------------------------------------

def test_versions_answer_alien_firmware_072_and_hardware_004(board):
    board.host_bytes("acm", bytes([0xA2, 0x00, 0xA2, 0x01]))
    assert board.sent == [bytes([0x55, 0x20, 0, 72, 0]),
                          bytes([0x54, 0x21, 0, 4])]


def test_abba_reports_firmware_103_it_refuses_below_100(abba):
    abba.host_bytes("acm", bytes([0xA2, 0x00]))
    fw = abba.sent[0]
    assert fw[2] << 8 | fw[3] >= 0x100


def test_switch_read_reply_is_0x53_first_and_made_is_1(board):
    board.host_bytes("acm", bytes([0xA3, 0x53, 42, 0xA3, 0x53, 36]))
    # TROUGH 1 has a ball at rest, the shooter lane is empty
    assert board.sent == [bytes([0x53, 0x33, 1]), bytes([0x53, 0x33, 0])]


def test_names_mode_reports_every_switch_made_once(tmp_path, monkeypatch):
    monkeypatch.setenv("PBIO_NAMES", "1")
    b = _board(tmp_path, monkeypatch)
    b.host_bytes("acm", bytes([0xA3, 0x53, 36]))
    assert b.sent[0] == bytes([0x53, 0x33, 1])
    b.host_bytes("acm", bytes([0xA3, 0x53, 95]))
    # after the last one it tells the game the truth, switch by switch
    assert bytes([0x54, 0x31, 36, 0]) in b.sent
    assert bytes([0x54, 0x31, 42, 1]) in b.sent
    b.log.close()


# --- switches, balls, coils ------------------------------------------------

def test_a_switch_change_is_reported_as_type_0x31(board):
    board.set_switch(82, 1, now=True)
    board.set_switch(82, 0, now=True)
    assert board.sent == [bytes([0x54, 0x31, 82, 1]), bytes([0x54, 0x31, 82, 0])]


def test_alien_at_rest_six_balls_and_the_tongue_home(board):
    on = sorted(n for n, v in board.state.items() if v)
    assert on == [0, 42, 43, 44, 45, 46, 47, 60]
    assert board.balls_state() == {"trough": 6, "shooter": 0, "in_play": 0}


def _coil(board, coil, mode):
    board.host_bytes("acm", bytes([0xA9, 0x4E, coil, 100, 20, 0, 0, 0, mode]))


def test_trough_coil_serves_a_ball_and_launch_coil_plays_it(board):
    _coil(board, 1, 5)                           # TROUGH: kicking now
    assert board.state[47] == 0 and board.state[36] == 1
    assert board.balls_state() == {"trough": 5, "shooter": 1, "in_play": 0}
    _coil(board, 0, 5)                           # the Launch button's coil
    assert board.state[36] == 0
    assert board.balls_state()["in_play"] == 1
    board.command("drain")
    assert board.balls_state() == {"trough": 6, "shooter": 0, "in_play": 0}


def test_configuring_a_coil_fires_nothing(board):
    _coil(board, 1, 0)
    assert board.balls == 6 and not board.coil_fired
    assert board.coil_config[1] == [100, 20, 0, 0]


def test_kickers_empty_their_switch(board):
    board.set_switch(70, 1, now=True)            # a ball in the AIRLOCK scoop
    _coil(board, 23, 5)
    assert board.state[70] == 0


def test_abba_serves_from_coil_0_and_launches_with_coil_1(abba):
    _coil(abba, 0, 5)
    assert abba.state[37] == 1 and abba.balls == 5
    _coil(abba, 1, 5)
    assert abba.state[37] == 0


def test_queen_serves_from_coil_1_launches_with_coil_0_and_kicks_its_vuks(queen):
    """PAD-326, from a played Queen 2.1G: coil 1 fired on every "TROUGH:
    kicking now", coil 0 is AUTO LAUNCH; LEFT VUK 19, RIGHT VUK 5."""
    assert queen.firmware == (1, 3, 0) and queen.balls == 6
    _coil(queen, 1, 5)
    assert queen.state[59] == 1 and queen.balls == 5      # SHOOTER
    _coil(queen, 0, 5)
    assert queen.state[59] == 0
    queen.set_switch(27, 1, now=True)
    _coil(queen, 19, 5)
    assert queen.state[27] == 0


def test_queen_plunges_with_both_flippers(queen):
    """No Launch button: both flipper buttons launch (and confirm the song
    select every ball starts on)."""
    queen.command("plunge")
    for sw in (77, 78):
        assert bytes([0x54, 0x31, sw, 1]) in queen.sent


def test_flipper_button_closes_its_eos(board):
    board.set_switch(77, 1, now=True)
    assert board.state[48] == 1
    board.set_switch(77, 0, now=True)
    assert board.state[48] == 0


def test_switch_rules_fire_their_coils(board):
    board.host_bytes("acm", bytes([0xA7, 0x57, 39, 12, 0xFF, 0, 0]))
    board.set_switch(39, 1, now=True)
    assert board.coil_fired.get(12) == 1


def test_leds_are_kept_by_number(board):
    board.host_bytes("acm", bytes([0xA7, 0x34, 0x05, 0x01, 0x10, 0x20, 0x30]))
    assert json.loads(board.command("leds")) == {"261": "102030"}


# --- Alien's tongue ----------------------------------------------------------

def test_tongue_runs_out_and_back_on_gpio_6_and_7(board, monkeypatch):
    t = [100.0]
    monkeypatch.setattr(board_mod.time, "monotonic", lambda: t[0])
    board.tongue["at"] = t[0]
    board.host_bytes("acm", bytes([0xA3, 0x61, 7, 0xA3, 0x61, 6]))  # forward
    t[0] += 0.2                                  # 50 pulses: off the home cam
    board.tongue_tick()
    assert board.state[0] == 0
    t[0] += 1.0                                  # full reach: the far cam
    board.tongue_tick()
    assert board.state[0] == 1 and board.tongue["pos"] == 240
    board.host_bytes("acm", bytes([0xA3, 0x62, 7]))                  # reverse
    t[0] += 0.3
    board.tongue_tick()
    assert board.state[0] == 0
    t[0] += 1.0
    board.tongue_tick()
    assert board.state[0] == 1 and board.tongue["pos"] == 0
    board.host_bytes("acm", bytes([0xA3, 0x62, 6]))                  # off
    t[0] += 1.0
    board.tongue_tick()
    assert board.tongue["pos"] == 0


# --- control socket requests ------------------------------------------------

def test_state_reports_what_the_board_keeps(board):
    board.host_bytes("acm", bytes([0xA2, 0x00, 0xA3, 0x14, 0x01]))
    s = json.loads(board.command("state"))
    assert s["title"] == "Alien" and s["frames"] == 2
    assert s["coils"]["enabled"] == 1 and s["ops"] == {"00": 1, "14": 1}
    assert s["balls"]["trough"] == 6 and s["switches"]["42"] == 1


def test_unknown_request_is_an_error(board):
    assert "err" in json.loads(board.command("jump"))


def test_plunge_presses_the_launch_button(board):
    board.command("plunge")
    assert bytes([0x54, 0x31, 76, 1]) in board.sent


# --- profiles and sw.py -------------------------------------------------------

@pytest.mark.parametrize("key", sorted(titles.TITLES))
def test_profiles_are_whole(key):
    t = titles.get(key)
    assert len(t["switches"]) == 96
    for n in (t["trough"] + [t["shooter"]] + list(t["buttons"].values())
              + t.get("plunge", [])):
        assert t["switches"][n] != "UNUSED", (key, n)
    assert t["screen"] and t["firmware"]


def test_detect_finds_the_title_folder(tmp_path):
    (tmp_path / "game" / "abba").mkdir(parents=True)
    (tmp_path / "game" / "abba" / "pinprog").write_bytes(b"")
    assert titles.detect(str(tmp_path)) == "abba"
    assert titles.detect(str(tmp_path / "nothing")) == ""


def test_switches_json_lists_only_used_switches():
    j = json.loads(titles.switches_json("alien"))
    names = {s["name"] for s in j["switches"]}
    assert "Start Button" in names and "Unused" not in names
    assert j["trough"] == [42, 43, 44, 45, 46, 47]


def test_sw_names_aliases_and_numbers():
    assert sw.lookup("start") == 75
    assert sw.lookup("left orbit") == 9
    assert sw.lookup("12") == 12
    assert sw.lookup("tongue opto") == 60


# ---------------------------------------------- the app's side (PAD-315)
files = _load("files", RIG / "pbiofiles.py")
pbioswitches = _load("switches", RIG / "pbioswitches.py")


def _folder(tmp_path, names, full=()):
    """PB's files by name; the ones in *full* big enough to be full updates
    (sparse, so nothing is written)."""
    for n in names:
        with open(tmp_path / n, "wb") as f:
            if n in full:
                f.truncate(files.FULL_MIN)
    return tmp_path


def _chain(folder, name):
    return [os.path.basename(p) for p in files.chain(str(folder / name))]


def test_files_tell_alien_abba_and_queen_apart():
    for name, key in (("pbap412.upd", "alien"), ("pbap41.upd", "alien"),
                      ("pbap145.upd", "abba"), ("PBAP141.UPD", "abba"),
                      ("pbq0210G.upd", "queen"),
                      ("clonezilla-live-alien40.iso", "alien"),
                      ("clonezilla-live-queen20d.iso", "queen"),
                      ("pbpp_predator_game_1_0.upd", ""), ("x.iso", "")):
        assert files.title(name) == key, name
    # each digit is one part: 4.1 < 4.1.1 < 4.1.2
    assert files.version("pbap41.upd") < files.version("pbap411.upd") < files.version("pbap412.upd")


def test_a_delta_brings_the_newest_full_update_below_it(tmp_path):
    d = _folder(tmp_path, ["clonezilla-live-alien40.iso", "pbap41.upd", "pbap411.upd",
                           "pbap412.upd", "pbap141.upd", "pbap145.upd"],
                full={"pbap41.upd", "pbap411.upd", "pbap141.upd"})
    assert _chain(d, "pbap412.upd") == ["pbap411.upd", "pbap412.upd"]
    assert _chain(d, "pbap411.upd") == ["pbap411.upd"]
    assert _chain(d, "pbap41.upd") == ["pbap41.upd"]
    # ABBA's updates never pick up Alien's (same "pbap")
    assert _chain(d, "pbap145.upd") == ["pbap141.upd", "pbap145.upd"]
    # an ISO is the whole machine: alone
    assert _chain(d, "clonezilla-live-alien40.iso") == ["clonezilla-live-alien40.iso"]


def test_a_delta_with_no_full_update_stands_on_its_restore_image(tmp_path):
    d = _folder(tmp_path, ["clonezilla-live-alien40.iso", "pbap412.upd",
                           "pbq0210G.upd"])
    assert _chain(d, "pbap412.upd") == ["clonezilla-live-alien40.iso", "pbap412.upd"]
    # no Queen image here: the delta alone (prepare.sh refuses it, saying why)
    assert _chain(d, "pbq0210G.upd") == ["pbq0210G.upd"]
    # with Queen's own image beside it, that is its base - not Alien's
    (d / "clonezilla-live-queen20d.iso").write_bytes(b"")
    assert _chain(d, "pbq0210G.upd") == ["clonezilla-live-queen20d.iso", "pbq0210G.upd"]


@pytest.mark.parametrize("key", ["alien", "abba", "queen"])
def test_the_playfield_table_is_predators_format(key):
    t = pbioswitches.table(key)
    prof = titles.get(key)
    assert t["title"] == prof["name"] and t["shooter"] == prof["shooter"]
    assert t["balls"] == len(prof["trough"])
    used = {n for n, s in prof["switches"].items() if s != "UNUSED"}
    assert {s["n"] for s in t["switches"]} == used
    rows = {r["keys"]: r for r in t["rows"]}
    b = prof["buttons"]
    assert rows["1"]["ns"] == [b["start"]] and rows["5"]["ns"] == [b["coin"]]
    assert rows["T"]["ns"] == [b["tilt"]]
    if "launch" in b:
        assert rows["Space"]["ns"] == [b["launch"]]
    else:                   # Queen: Space must not take the left flipper
        assert "Space" not in rows
    # the flipper buttons on the arrows; their EOS switches get no key
    assert rows["Left"]["ns"] and rows["Right"]["ns"]
    eos = {s["n"] for s in t["switches"] if "Eos" in s["label"]}
    assert eos and not any(set(r["ns"]) & eos for r in t["rows"] if r["keys"])
    # the coin door's buttons and the trough are not playfield letters
    lettered = {n for r in t["rows"] if len(r["keys"]) == 1 and r["keys"].isalpha()
                and r["keys"] != "T" for n in r["ns"]}
    assert not lettered & {b["enter"], b["escape"], b["up"], b["down"]}
    assert not lettered & set(prof["trough"])
    actions = {k["action"] for k in t["keymap"] if k["action"]}
    assert actions == {"plunge", "drain", "pause"}


# ------------------------------------------- sound, window, pace (PAD-322)
audio = _load("audio", RIG / "pbioaudio.py")


def test_the_chroots_alsa_writes_the_relays_format_into_the_fifo():
    """pinprog's SDL 1.2 speaks ALSA only: the default device converts to
    48 kHz 16-bit stereo and writes it raw into the FIFO pbioaudio.py reads,
    over ALSA's null device (no sound card in the chroot)."""
    conf = audio.asound_conf("/mnt/log/audio.fifo")
    assert "pcm.!default" in conf and "type plug" in conf
    assert 'pcm "padfifo" format S16_LE rate 48000 channels 2' in conf
    assert "type file" in conf and 'slave.pcm "null"' in conf
    assert 'file "/mnt/log/audio.fifo"' in conf and 'format "raw"' in conf


def test_volume_scales_the_samples_and_mute_is_silence():
    import array
    pcm = array.array("h", [1000, -1000, 32767, -32768]).tobytes()
    assert audio.scale(pcm, 1.0, False) == pcm
    half = array.array("h")
    half.frombytes(audio.scale(pcm, 0.5, False))
    assert list(half) == [500, -500, 16383, -16384]
    assert audio.scale(pcm, 1.0, True) == bytes(len(pcm))
    assert audio.scale(pcm, 0.0, False) == bytes(len(pcm))
    assert audio.levels(pcm)[0] == 32768


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs a FIFO (Linux)")
def test_the_relay_keeps_the_games_clock_without_pulseaudio_and_ends_with_it(tmp_path):
    """No PulseAudio: the FIFO is still drained at the real-time rate (the
    game never stalls, nor races ahead), and the relay ends with the game."""
    import subprocess
    import time
    game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (tmp_path / "game.pid").write_text(str(game.pid))
        ctl = tmp_path / "audio_ctl.json"
        ctl.write_text(json.dumps({"gain": 0.3, "muted": True}))
        fifo = tmp_path / "audio.fifo"
        relay = subprocess.Popen(
            [sys.executable, "-u", str(RIG / "pbioaudio.py"), "--fifo", str(fifo),
             "--rig", str(tmp_path), "--ctl", str(ctl), "--pulse", "unix:/nonexistent"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        end = time.time() + 10
        while not fifo.exists() and time.time() < end:
            time.sleep(0.05)
        t0 = time.time()
        with open(fifo, "wb") as w:            # 0.6 s of sound
            w.write(bytes(audio.BYTES_PER_S * 6 // 10))
        took = time.time() - t0
        assert 0.25 < took < 5, took
        game.kill()
        game.wait()
        out = relay.communicate(timeout=10)[0]
        assert relay.returncode == 0
        assert "level 30%, MUTED" in out and "the game is gone" in out
    finally:
        if game.poll() is None:
            game.kill()


def test_run_game_wires_the_sound_the_window_and_the_renderer():
    run = (RIG / "run_game.sh").read_text()
    # --audio: the chroot's asound.conf, the relay as this slot's, ALSA for SDL
    assert '--conf "$U/etc/asound.conf"' in run
    assert 'mkfifo -m 666 "$PBIO_RIG/audio.fifo"' in run
    assert "SDLAUDIO=alsa" in run and "SDL_AUDIODRIVER=$SDLAUDIO" in run
    assert 'CTLARG=(--ctl "$PAD_AUDIO_CTL")' in run
    # vidprog: the window shim, on the desktop by default, and SDL's
    # software renderer (the chroot's GL is softpipe: ~9 fps)
    assert "LD_PRELOAD=/usr/lib/pbioshim.so PBIO_WINDOWED=$WINDOWED" in run
    assert "WINDOWED=${PBIO_WINDOWED:-$VISIBLE}" in run
    assert "RENDER=${PBIO_RENDER:-software}" in run and "SDL_RENDER_DRIVER=$RENDER" in run
    # the relay is one of the slot's processes: killgame.sh stops it
    assert r"pbioaudio\.py" in (RIG / "pbiopath.sh").read_text()


def test_the_window_shim_moves_resizes_and_scales():
    src = (RIG / "pbioshim.c").read_text()
    assert "flags &= ~(SDL_FULLSCREEN_DESKTOP | SDL_FULLSCREEN | SDL_BORDERLESS);" in src
    assert "flags |= SDL_RESIZABLE;" in src
    assert "SDL_TEXTUREACCESS_TARGET" in src and "SDL_RenderCopy_p(renderer, wn->canvas" in src


def test_the_window_shim_loads_on_the_machines_glibc_230():
    """Built (build.sh) for the chroot's glibc 2.30: no newer symbol version,
    and dlsym from libdl.so.2."""
    import re
    so = (RIG / "pbioshim.so").read_bytes()
    assert so[:4] == b"\x7fELF"
    vers = {tuple(int(x) for x in v.split(b".")[1:])
            for v in re.findall(rb"GLIBC_(2\.\d+(?:\.\d+)?)", so)}
    assert vers and max(vers) <= (30,), sorted(vers)
    assert b"libdl.so.2" in so
