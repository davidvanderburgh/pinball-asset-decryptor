"""PAD-1213: Spike 3 emulator - the window's switch list before it opens, the
host video decoder's first frame, and the sound's catch-up ceiling."""
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMU = os.path.join(ROOT, "tools", "spike3_emu")
sys.path.insert(0, EMU)

import s3bridge  # noqa: E402
import s3vidhost  # noqa: E402


def read(name):
    with open(os.path.join(EMU, name), encoding="utf-8") as f:
        return f.read()


# ---- the video decoder ------------------------------------------------------

def test_decoder_is_slice_threaded_never_frame_threaded():
    """Frame threading holds the first frame back by a packet a thread (15
    packets, 589 ms on a 10-core PC) - longer than Stern's player waits."""
    cmd = s3vidhost.decoder_cmd(s3vidhost.HEVC, 1920, 1080, threads=4)
    assert cmd[cmd.index("-thread_type") + 1] == "slice"
    assert cmd[cmd.index("-threads") + 1] == "4"
    assert cmd.index("-thread_type") < cmd.index("-i")       # an INPUT option
    assert cmd[cmd.index("-f") + 1] == "hevc"
    assert "1920x1080" in cmd
    assert s3vidhost.decoder_cmd(s3vidhost.H264, 480, 320, threads=1)[
        s3vidhost.decoder_cmd(s3vidhost.H264, 480, 320, threads=1).index("-f") + 1] == "h264"


def test_decoder_threads_knob(monkeypatch):
    monkeypatch.setenv("PAD_S3_VID_THREADS", "2")
    assert s3vidhost.decoder_threads() == 2
    monkeypatch.setenv("PAD_S3_VID_THREADS", "x")
    assert 1 <= s3vidhost.decoder_threads() <= 4


class FakeDecoder:
    def __init__(self, key):
        self.key, self.c, self.extra, self.killed, self.dead = key, None, None, False, False

    def bind(self, c, extra):
        self.c, self.extra = c, extra
        return self

    def alive(self):
        return not self.killed and not self.dead

    def kill(self):
        self.killed = True


def spares(monkeypatch, on="1"):
    monkeypatch.setenv("PAD_S3_VID_WARM", on)
    made = []

    def make(key):
        d = FakeDecoder(key)
        made.append(d)
        return d
    sp = s3vidhost.Spares(None, None, make=make)
    # refill runs in a thread in the host; inline here, so the test is exact
    monkeypatch.setattr(s3vidhost.threading, "Thread",
                        lambda target, args=(), daemon=None: type(
                            "T", (), {"start": lambda self: target(*args)})())
    return sp, made


def test_an_open_takes_the_warm_spare_and_leaves_a_new_one(monkeypatch):
    sp, made = spares(monkeypatch)
    key = (s3vidhost.HEVC, 1920, 1080)
    first = sp.take(0, *key, b"x")             # nothing warm yet: started now
    assert first is made[0] and first.c == 0 and first.extra == b"x"
    assert sp.spare[key] is made[1]            # ...and one is warming behind it
    second = sp.take(1, *key, b"y")
    assert second is made[1] and second.c == 1 and second.extra == b"y"
    assert len(made) == 3 and sp.spare[key] is made[2]


def test_a_dead_spare_is_not_handed_out(monkeypatch):
    sp, made = spares(monkeypatch)
    key = (s3vidhost.HEVC, 1360, 768)
    sp.take(0, *key, b"")
    made[1].dead = True                        # its ffmpeg exited meanwhile
    d = sp.take(0, *key, b"")
    assert d is made[2] and made[1].killed


def test_spares_are_kept_for_the_last_few_sizes_only(monkeypatch):
    sp, made = spares(monkeypatch)
    keys = [(s3vidhost.HEVC, 100 + i, 100) for i in range(sp.KEEP + 2)]
    for k in keys:
        sp.take(0, *k, b"")
    assert list(sp.spare) == keys[-sp.KEEP:]
    evicted = [d for d in made if d.key in keys[:2] and d not in (made[0], made[2])]
    assert evicted and all(d.killed for d in evicted)
    sp.close()
    assert not sp.spare and all(d.killed for d in made if d.c is None)


def test_warm_spares_can_be_turned_off(monkeypatch):
    sp, made = spares(monkeypatch, on="0")
    sp.take(0, s3vidhost.HEVC, 64, 64, b"")
    assert len(made) == 1 and not sp.spare


# ---- the switch list, before the window opens -------------------------------

def test_switch_tables_are_written_with_ids_by_node_and_bit(tmp_path):
    devs = [("TROUGH 1", 8, 37, "switch"), ("COIN DOOR POWER INTERLOCK", 0, 23, "switch"),
            ("JUMPER LVDS RESOLUTION 1", 0, 20, "switch"), ("FLASHER", 9, 1, "lamp")]
    d = tmp_path / "slot"                      # made by the writer
    table = s3bridge.write_switch_tables(devs, str(d))
    assert table == {"TROUGH 1": [8, 37], "COIN DOOR POWER INTERLOCK": [0, 23],
                     "JUMPER LVDS RESOLUTION 1": [0, 20]}
    assert json.loads((d / "switches.json").read_text()) == table
    ids = s3bridge.read_switch_list(str(d / "tables" / "game" / "switch_list.txt"))
    assert ids == {1: (0, 20, "JUMPER LVDS RESOLUTION 1"),
                   2: (0, 23, "COIN DOOR POWER INTERLOCK"), 3: (8, 37, "TROUGH 1")}


def test_s3run_writes_this_titles_list_before_the_renderer_starts():
    """The window latches the coin door and trough by the list's ids as it
    opens; another title's list left in the slot closed Transformers' LVDS
    resolution jumper while it booted (Guided Setup at 1360x768)."""
    s = read("s3run.sh")
    clear = s.index('rm -rf "$SD/tables" "$SD/switches.json"')
    write = s.index('s3bridge.py" --switches "$SD" "$TREE/games/game"')
    renderer = s.index('setsid "$B/padglhost"')
    assert clear < write < renderer


def test_bridge_has_a_switches_only_entry():
    s = read("s3bridge.py")
    assert re.search(r'sys\.argv\[1\] == "--switches"', s)
    assert "return switches_main(" in s


# ---- the sound --------------------------------------------------------------

def test_spike3_sound_catches_up_from_200_ms_not_750():
    s = read("s3run.sh")
    assert "PAD_AUDIO_MAX_LATE_MS=${PAD_AUDIO_MAX_LATE_MS:-200}" in s
    # and the knob reaches the Windows player (WSLENV), as the others do
    with open(os.path.join(ROOT, "tools", "spike2_emu", "playaudio.sh"), encoding="utf-8") as f:
        assert 'WSLENV:+$WSLENV:}PAD_AUDIO_MAX_LATE_MS' in f.read()


@pytest.mark.parametrize("least_ms, cut_ms", [(150, 0), (190, 0), (210, 120), (660, 570)])
def test_the_200_ms_ceiling_cuts_back_to_the_cushion(least_ms, cut_ms, monkeypatch):
    import importlib.util
    import types
    sd = types.ModuleType("sounddevice")       # the Windows player's speaker, not here
    sd.query_hostapis = lambda *a: []
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    spec = importlib.util.spec_from_file_location(
        "padplay_pad1213", os.path.join(ROOT, "tools", "spike2_emu", "padplay.py"))
    padplay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(padplay)
    bps = 44100 * 4
    pre, late = 90, 200
    ceiling = bps * max(late, pre + 100) // 1000
    cut = padplay.catch_up(bps * least_ms // 1000, bps * pre // 1000, ceiling, 4)
    assert abs(cut * 1000 // bps - cut_ms) <= 1
