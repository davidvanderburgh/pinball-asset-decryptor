"""PAD-1370: a Spike 3 cabinet's light strips are the netbridge's own WS2812
outputs. The game sends the strip boards (nodes 2, 7, 14) only their bring-up
on the node bus; their lamp frames come to the bridge as host cmd 0x2f,
[channel] [n] [cmd body] [pad], after cmd 0x29 sets each channel's LED count.
Payloads below are captured off fallout_le 0.82.0's host UART."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "spike3_emu"))

import s3bridge  # noqa: E402
import s3leds  # noqa: E402

#: a long frame for the cabinet strips (channel 2): command a6, 30 RGB pixels
CAB_LONG = bytes.fromhex(
    "0264a6c00b001a1a1a565656e9e9e92020201f1f1fcbcbcbc0c0c0232323191919555555eeeeeec9c9c93e3e3e"
    "1919191a1a1a434343b5b5b5fefefecacaca6161612424241919191919192222228b8b8bb4b4b4d9d9d9f4f4f4"
    "fefefef5f5f5d7d7d7ababab00")


def _level(led, node, ch):
    if ch < s3leds.IDX:
        return led.m[s3leds.VAL + node * s3leds.IDX + ch]
    bank, i = divmod(ch, s3leds.IDX)
    return led.m[s3leds.HI + node * s3leds.HI_BANKS * s3leds.IDX + (bank - 1) * s3leds.IDX + i]


def test_channels_route_to_the_strip_boards():
    # channel 0 the speaker rings (node 7), 1 the topper (14), 2 the cabinet (2)
    for ch, node in ((0, 7), (1, 14), (2, 2)):
        got = s3bridge.ws2812_frame(bytes([ch]) + bytes.fromhex("02850000"))
        assert got == (node, bytes.fromhex("8500 00"))


def test_unrouted_and_short_payloads_are_dropped():
    assert s3bridge.ws2812_frame(bytes.fromhex("0302850000")) is None     # channel 3: no board
    assert s3bridge.ws2812_frame(b"\x02\x02") is None
    assert s3bridge.ws2812_frame(bytes.fromhex("02098500")) is None       # n past the payload
    assert s3bridge.ws2812_frame(bytes.fromhex("020085")) is None         # empty frame


def test_channel_map_override():
    nodes = s3bridge.ws2812_nodes("2=5, 3=12 junk")
    assert nodes == {0: 7, 1: 14, 2: 5, 3: 12}
    assert s3bridge.ws2812_frame(bytes.fromhex("0302850000"), nodes)[0] == 12
    assert s3bridge.ws2812_nodes("") == s3bridge.WS2812_NODES


def test_setup_lines_name_counts_and_parts():
    assert s3bridge.ws2812_setup(bytes.fromhex("007800")) == "WS2812 channel 0: 120 LEDs"
    assert s3bridge.ws2812_setup(bytes.fromhex("02b001")) == "WS2812 channel 2: 432 LEDs"
    assert s3bridge.ws2812_setup(bytes.fromhex("029000900048004800")) == \
        "WS2812 channel 2: parts 144+144+72+72 (432 LEDs)"
    assert s3bridge.ws2812_setup(b"\x00") is None


def test_frames_light_the_boards_lamps_including_past_96(tmp_path):
    led = s3leds.PadLed(str(tmp_path / "padled"))
    # bank 0 and bank 1 (channel 96) of every board, all at full
    for ch in (0, 1, 2):
        for body in ("02850000", "0391240000"):
            led.frame(*s3bridge.ws2812_frame(bytes([ch]) + bytes.fromhex(body)))
    for node in (7, 14, 2):
        assert _level(led, node, 0) == 255
        assert _level(led, node, 96) == 255
    assert led.wide_bad == 0
    # a long cabinet frame: every level it carries lands on node 2
    led.frame(*s3bridge.ws2812_frame(CAB_LONG))
    assert led.wide_bad == 0
    lit = [ch for ch in range(432) if _level(led, 2, ch)]
    assert len(lit) >= 90
    assert all(_level(led, 7, ch) == 0 for ch in range(1, 96))      # nothing strays onto the speakers
