"""PAD-1090: the virtual playfield on a Spike 3 run.

s3pf.py writes the window's tables from the card's own device records,
s3leds.py fills padled.h's block from the node bus, coilmap reads the exact
group -> node map a Spike 3 run knows - each checked here without a card."""
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S3 = os.path.join(ROOT, "tools", "spike3_emu")
S2 = os.path.join(ROOT, "tools", "spike2_emu")
for p in (S3, S2):
    if p not in sys.path:
        sys.path.insert(0, p)

import coilmap  # noqa: E402
import devicexy  # noqa: E402
import s3pf  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform == "win32" and not hasattr(os, "ftruncate"),
                                reason="needs ftruncate")


def _rec(name, kind, image, x, y, group=7, index=1, conn="", w=30, h=30):
    return dict(name=name, kind=kind, image=image, x=x, y=y, w=w, h=h,
                group=group, index=index, node=8, location=0, conn=conn, part="")


def test_the_layout_is_the_picture_with_the_most_device_kinds():
    """A topper carries lamps alone; strip lamps named "playfield" at x = 0
    (Walking Dead, Fallout) are unplaced and do not count."""
    recs = ([_rec("T%d" % i, "led", "TestMenu/topper_tm", 10 + i, 10) for i in range(50)]
            + [_rec("S%d" % i, "led", "playfield", 0, i + 1) for i in range(60)]
            + [_rec("TROUGH 1", "switch", "TestMenu/picnic_pf", 358, 844),
               _rec("POP", "coil", "TestMenu/picnic_pf", 100, 200),
               _rec("SPOT", "led", "TestMenu/picnic_pf", 120, 220)])
    assert s3pf.layout_image(recs) == "TestMenu/picnic_pf"


def test_device_xy_reads_back_through_the_spike2_reader(tmp_path):
    recs = [_rec("TROUGH 1", "switch", "playfield", 358, 844, group=7, index=37, conn="8a"),
            _rec("MEOWTH BALLOON SPOT", "led", "playfield", 139, 338, group=8, index=82),
            _rec("AUTO PLUNGER", "coil", "playfield", 400, 900, group=7, index=3),
            _rec("NO PICTURE", "switch", "", 0, 0)]
    p = tmp_path / "device_xy.txt"
    p.write_text(s3pf.device_xy("pokemon_le", recs, "playfield", (451, 998)))
    rows = devicexy.read_table(str(p))
    by = {r["name"]: r for r in rows}
    assert by["TROUGH 1"]["x"] == 358 and by["TROUGH 1"]["y"] == 844
    assert by["TROUGH 1"]["group"] == 7 and by["TROUGH 1"]["index"] == 37
    assert by["TROUGH 1"]["conn"] == "8a"
    assert by["MEOWTH BALLOON SPOT"]["kind"] == "led"
    assert by["NO PICTURE"]["image"] == ""
    assert devicexy.layout_image(rows) == "playfield"


def test_the_exact_group_map_wins_over_inference(tmp_path):
    (tmp_path / "device_xy.txt").write_text("# empty\n")
    (tmp_path / "group_node_exact.txt").write_text("# group node\n1 2\n7 8\n8 9\n")
    assert coilmap.group_node_for(str(tmp_path / "device_xy.txt")) == {1: 2, 7: 8, 8: 9}


def test_find_picture_takes_the_models_own_drawing(tmp_path):
    imgs = tmp_path / "games" / "pokemon_le" / "assets" / "nuk" / "images" / "Test"
    imgs.mkdir(parents=True)
    for n in ("pokemon_playfield_pro.png", "pokemon_playfield_le.png"):
        (imgs / n).write_bytes(b"png")
    got = s3pf.find_picture(str(tmp_path), "pokemon_le", "playfield")
    assert os.path.basename(got) == "pokemon_playfield_le.png"
    tm = tmp_path / "games" / "pokemon_le" / "assets" / "nuk" / "images" / "TestMenu"
    tm.mkdir()
    (tm / "picnic_pf.png").write_bytes(b"png")
    assert os.path.normpath(s3pf.find_picture(str(tmp_path), "pokemon_le", "TestMenu/picnic_pf")) == str(tm / "picnic_pf.png")
    assert s3pf.find_picture(str(tmp_path), "pokemon_le", "TestMenu/nothing") is None


@pytest.mark.skipif(sys.platform == "win32", reason="mmap of a growing file: the rig runs it in WSL")
def test_s3leds_publishes_lamps_and_coils_at_padled_offsets(tmp_path):
    """Spike 2's recorded lamp frames are [addr][n][cmd body ck][pad]; their
    b[2:-1] is a Spike 3 unmasked frame, so the same lamps must come out."""
    import s3leds
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from test_spike2_led_wide import DECODED, FRAMES
    path = tmp_path / "padled"
    led = s3leds.PadLed(str(path))
    b = bytes.fromhex(FRAMES[0x97])
    node, idxs, vals = DECODED[0x97]
    led.frame(b[0] & 0x3F, b[2:-1])
    led.frame(8, bytes([0x40, 3, 0xA0, 0x00, 0x00]))     # coil 3 on node 8 fires
    d = path.read_bytes()
    assert struct.unpack_from("<II", d, 0) == (coilmap.PADLED_MAGIC, 4)
    for i, v in zip(idxs, vals):
        assert d[s3leds.VAL + node * 96 + i] == v
        assert d[s3leds.SEEN + node * 96 + i] == 1
    assert d[coilmap.COIL_OFF + 8 * 16 + 3] == 1
    assert d[coilmap.LVL_OFF + 8 * 16 + 3] == 0xA0
    assert struct.unpack_from("<I", d, s3leds.WIDE_DECODED)[0] == 1
    led.close()
    assert not path.exists()            # gone = the run ended (playfield.py)
