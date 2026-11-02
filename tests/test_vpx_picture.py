"""The picture of a Visual Pinball table (PAD-942): tools/spike2_emu/vpx/vpxpicture.py.

What is worth failing on, none of it needing a real table:
  * THE PLAYFIELD WINS: the image GameData's IMAG names, found by its NAME
    among the Image<n> streams and read out of its DATA record, before the
    author's TableInfo/Screenshot (TMNT's is the instruction card).
  * THE SCREENSHOT IS THE FALLBACK: a BITS (raw) playfield, or none, and
    the screenshot shows; neither, and the table is an error the batch
    carries on past.
  * A TRANSPARENT PLAYFIELD CUT-OUT lies over black, as on the table.
  * THE JPEG IS SCALED to --size on its long side and the record names its
    size and source; `main` prints one `picture` line per table and the
    final JSON with the errors.
"""
import io
import json
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VPX = os.path.join(ROOT, "tools", "spike2_emu", "vpx")
if VPX not in sys.path:
    sys.path.insert(0, VPX)
pytestmark = pytest.mark.skipif(not os.path.isdir(VPX), reason="rig not present")


@pytest.fixture(scope="module")
def vpxpicture():
    pytest.importorskip("olefile")
    return pytest.importorskip("vpxpicture")


def _rec(tag, payload):
    return struct.pack("<I", 4 + len(payload)) + tag.encode() + payload


def _str(tag, text):
    b = text.encode("latin1")
    return _rec(tag, struct.pack("<I", len(b)) + b)


def _png(w, h, colour, mode="RGB"):
    from PIL import Image
    buf = io.BytesIO()
    Image.new(mode, (w, h), colour).save(buf, "PNG")
    return buf.getvalue()


def _image_stream(name, data=None, raw=False):
    """One GameStg/Image<n> as VPX writes it: the head, then the file under
    JPEG's DATA, or BITS for a raw bitmap."""
    head = _str("NAME", name) + _str("PATH", "C:\\x\\" + name) + _rec("WDTH", struct.pack("<I", 8)) \
        + _rec("HGHT", struct.pack("<I", 8))
    if raw:
        return head + _rec("BITS", b"") + b"\0" * 64
    return head + _rec("JPEG", b"") + _str("NAME", name) + _str("PATH", "C:\\x\\" + name) \
        + _rec("SIZE", struct.pack("<I", len(data))) + _rec("DATA", data) + _rec("ENDB", b"")


class _Ole:
    def __init__(self, streams):
        self.streams = streams

    def exists(self, name):
        return name in self.streams

    def openstream(self, name):
        return io.BytesIO(self.streams[name])

    def close(self):
        pass


def _table(monkeypatch, vpxpicture, playfield="pf", images=(), screenshot=None):
    streams = {"GameStg/GameData": (_str("IMAG", playfield) if playfield else b"") + _rec("ENDB", b"")}
    for i, (name, data, raw) in enumerate(images):
        streams["GameStg/Image%d" % i] = _image_stream(name, data, raw)
    if screenshot is not None:
        streams["TableInfo/Screenshot"] = screenshot
    monkeypatch.setattr(vpxpicture, "open_table", lambda path: _Ole(streams))


def test_the_playfield_image_wins_over_the_authors_screenshot(monkeypatch, vpxpicture):
    _table(monkeypatch, vpxpicture, images=[("ball", _png(4, 4, (0, 0, 255)), False),
                                            ("PF", _png(20, 40, (255, 0, 0)), False)],
           screenshot=_png(30, 10, (0, 255, 0)))
    img, source = vpxpicture.picture_of("x.vpx")
    assert source == "playfield" and img.size == (20, 40) and img.getpixel((1, 1)) == (255, 0, 0)


def test_a_raw_or_missing_playfield_falls_back_to_the_screenshot(monkeypatch, vpxpicture):
    _table(monkeypatch, vpxpicture, images=[("pf", None, True)], screenshot=_png(30, 10, (0, 255, 0)))
    img, source = vpxpicture.picture_of("x.vpx")
    assert source == "screenshot" and img.size == (30, 10)
    _table(monkeypatch, vpxpicture, playfield="nothere", screenshot=_png(6, 6, (0, 255, 0)))
    assert vpxpicture.picture_of("x.vpx")[1] == "screenshot"


def test_a_table_with_no_picture_the_kit_reads_is_an_error(monkeypatch, vpxpicture):
    _table(monkeypatch, vpxpicture, images=[("pf", None, True)])
    with pytest.raises(ValueError, match="not a picture the kit reads"):
        vpxpicture.picture_of("x.vpx")
    # Metallica: the playfield names an HDR file PIL does not open
    _table(monkeypatch, vpxpicture, images=[("pf", b"#?RADIANCE\n" + b"\0" * 40, False)])
    with pytest.raises(ValueError, match="not a picture the kit reads"):
        vpxpicture.picture_of("x.vpx")
    _table(monkeypatch, vpxpicture, playfield="")
    with pytest.raises(ValueError, match="no screenshot and names no playfield"):
        vpxpicture.picture_of("x.vpx")


def test_a_transparent_cut_out_lies_over_black(monkeypatch, vpxpicture):
    _table(monkeypatch, vpxpicture, images=[("pf", _png(8, 8, (255, 255, 255, 0), "RGBA"), False)])
    img, _ = vpxpicture.picture_of("x.vpx")
    assert img.mode == "RGB" and img.getpixel((3, 3)) == (0, 0, 0)


def test_the_picture_is_written_scaled_with_its_record(monkeypatch, vpxpicture, tmp_path):
    _table(monkeypatch, vpxpicture, images=[("pf", _png(200, 400, (255, 0, 0)), False)])
    got = vpxpicture.write_picture(str(tmp_path / "My Table (PAD).vpx"), str(tmp_path), size=100)
    assert got["file"] == str(tmp_path / "My Table (PAD).jpg") and os.path.isfile(got["file"])
    assert (got["w"], got["h"]) == (50, 100) and got["source"] == "playfield" and got["full"] == [200, 400]
    from PIL import Image
    with Image.open(got["file"]) as im:
        assert im.format == "JPEG" and im.size == (50, 100)


def test_main_prints_a_line_per_table_and_carries_on_past_an_error(monkeypatch, vpxpicture, tmp_path, capsys):
    good = str(tmp_path / "good.vpx")
    bad = str(tmp_path / "bad.vpx")
    streams = {}

    def opener(path):
        if path == bad:
            raise OSError("not an OLE file")
        return _Ole(streams)
    streams["GameStg/GameData"] = _str("IMAG", "pf") + _rec("ENDB", b"")
    streams["GameStg/Image0"] = _image_stream("pf", _png(10, 20, (0, 0, 255)))
    monkeypatch.setattr(vpxpicture, "open_table", opener)
    out = str(tmp_path / "pics")
    assert vpxpicture.main([out, good, bad, "--size", "10"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [ln.split()[0] for ln in lines] == ["picture", "picture", "{\"pictures\":"]
    first = json.loads(lines[0][8:])
    assert first["table"] == good and first["h"] == 10 and first["source"] == "playfield"
    assert json.loads(lines[1][8:]) == {"table": bad, "error": "not an OLE file"}
    final = json.loads(lines[2])
    assert set(final["pictures"]) == {good} and final["errors"] == {bad: "not an OLE file"}
    assert os.path.isfile(os.path.join(out, "good.jpg"))
