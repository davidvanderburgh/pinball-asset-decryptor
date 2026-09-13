"""tools/jjp_emu/jjpvol.py - the JJP rig's Volume / Mute follower (item 118).

Pure: the level maths, the pactl parse and the plan of what to change.  The
loop itself runs pactl inside the rig's jail and is proven on the rig."""
import importlib.util
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "jjpvol", os.path.join(HERE, "..", "tools", "jjp_emu", "jjpvol.py"))
jjpvol = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(jjpvol)


SAMPLE = """Sink Input #1
\tDriver: protocol-native.c
\tOwner Module: 9
\tClient: 12
\tSink: 1
\tSample Specification: s16le 2ch 44100Hz
\tMute: no
\tVolume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB
\t        balance 0.00
\tProperties:
\t\tmedia.name = "Allegro Voice"
\t\tapplication.name = "game"
\t\tapplication.process.binary = "game"
Sink Input #7
\tMute: yes
\tVolume: mono: 42588 / 65% / -11.23 dB
\tProperties:
\t\tapplication.name = "ALSA plug-in [jjpselect]"
\t\tapplication.process.binary = "jjpselect"
Sink Input #9
\tMute: no
\tVolume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB
\tProperties:
\t\tapplication.process.binary = "firefox"
"""


def test_the_level_is_the_cube_root_of_the_gain():
    """PulseAudio's volume is cubic in amplitude, so a linear gain of 1/8 is
    half the raw volume - the loudness the Stern relay gives the same slider."""
    assert jjpvol.target_volume(1.0, False) == (65536, False)
    assert jjpvol.target_volume(0.125, False) == (32768, False)
    assert jjpvol.target_volume(2.0, False) == (65536, False)     # clamped


def test_zero_or_mute_is_a_mute():
    assert jjpvol.target_volume(0.0, False)[1] is True
    assert jjpvol.target_volume(0.5, True)[1] is True


def test_parse_reads_every_stream_with_its_binary():
    got = jjpvol.parse_sink_inputs(SAMPLE)
    assert [(s["index"], s["binary"], s["volume"], s["muted"]) for s in got] == [
        (1, "game", 65536, False), (7, "jjpselect", 42588, True), (9, "firefox", 65536, False)]


def test_the_plan_touches_only_the_game_and_the_menu():
    """WSLg's PulseAudio is shared by every Linux program on the machine."""
    cmds = jjpvol.plan(jjpvol.parse_sink_inputs(SAMPLE), 32768, False)
    touched = {c[1] for c in cmds}
    assert touched == {"1", "7"}
    assert ["set-sink-input-volume", "1", "32768"] in cmds
    assert ["set-sink-input-mute", "7", "0"] in cmds


def test_the_plan_is_empty_when_every_stream_is_already_there():
    inputs = [{"index": 3, "binary": "game", "volume": 32800, "muted": False}]
    assert jjpvol.plan(inputs, 32768, False) == []


def test_read_ctl_keeps_the_last_level_on_a_bad_file(tmp_path):
    p = tmp_path / "audio_ctl.json"
    assert jjpvol.read_ctl(str(p)) is None                        # absent
    p.write_text("{not json", encoding="utf-8")
    assert jjpvol.read_ctl(str(p)) is None                        # torn
    p.write_text(json.dumps({"gain": 0.4, "muted": True}), encoding="utf-8")
    assert jjpvol.read_ctl(str(p)) == (0.4, True)
    p.write_text(json.dumps({"gain": 7}), encoding="utf-8")
    assert jjpvol.read_ctl(str(p)) == (1.0, False)                # clamped


@pytest.mark.parametrize("line", ["Volume: front-left: 1000 / 2% / -100 dB",
                                  "\tVolume: mono: 1000 / 2% / -100 dB"])
def test_both_channel_layouts_parse(line):
    got = jjpvol.parse_sink_inputs("Sink Input #4\n%s\n" % line)
    assert got[0]["volume"] == 1000
