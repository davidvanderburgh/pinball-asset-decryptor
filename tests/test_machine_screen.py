"""PAD-1467: what a machine's own screen shows, read over remote access (core/machine_screen.py), and the Network
tab's Machine screen card: one picture, a live view, Save."""
import io
import struct
import time
from pathlib import Path

import pytest

from pinball_decryptor.core import machine_screen as MS
from tests.webui_harness import web_app

GODZILLA = '1360,1536\n16\n2720\n0,768\nU:1360x768p-60\n'


def _page(w, h, stride, colour565):
    line = struct.pack('<H', colour565) * w + b'\0' * (stride - 2 * w)
    return line * h


def test_geometry_is_the_screen_being_shown():
    geo = MS.parse_geometry(GODZILLA)
    assert geo == dict(width=1360, height=768, bpp=16, stride=2720, pan_y=768)
    assert MS.frame_bytes(geo) == 2720 * 768
    # no mode line: two pages are still told apart by where the shown one starts
    assert MS.parse_geometry('1360,1536\n16\n2720\n0,768\n\n')['height'] == 768
    # one page, nothing panned
    assert MS.parse_geometry('800,480\n32\n3200\n0,0\nU:800x480p-60\n') == dict(width=800, height=480, bpp=32,
                                                                              stride=3200, pan_y=0)
    with pytest.raises(MS.ScreenError, match='no /dev/fb0'):
        MS.parse_geometry('none\n')
    with pytest.raises(MS.ScreenError, match='does not read'):
        MS.parse_geometry('1360,1536\n8\n1360\n0,0\n\n')


def test_a_page_becomes_a_picture_in_its_own_colours():
    from PIL import Image
    geo = dict(width=8, height=4, bpp=16, stride=20, pan_y=0)                 # a stride wider than the line
    red = Image.open(io.BytesIO(MS.encode(_page(8, 4, 20, 0xF800), geo)))
    assert red.size == (8, 4) and red.format == 'PNG' and red.getpixel((3, 2)) == (255, 0, 0)
    assert Image.open(io.BytesIO(MS.encode(_page(8, 4, 20, 0x07E0), geo))).getpixel((0, 0)) == (0, 255, 0)
    assert Image.open(io.BytesIO(MS.encode(_page(8, 4, 20, 0x001F), geo))).getpixel((7, 3)) == (0, 0, 255)
    jpeg = MS.encode(_page(8, 4, 20, 0xFFFF), geo, 'JPEG')
    assert Image.open(io.BytesIO(jpeg)).format == 'JPEG'
    bgra = dict(width=2, height=1, bpp=32, stride=8, pan_y=0)
    assert Image.open(io.BytesIO(MS.encode(bytes([10, 20, 30, 0, 1, 2, 3, 0]), bgra))).getpixel((0, 0)) == (30, 20, 10)
    with pytest.raises(MS.ScreenError, match='try again'):
        MS.encode(b'\0' * 10, geo)


class Machine:
    """A stand-in for a connected machine: answers the geometry and hands back the page asked for."""

    def __init__(self, geometry=GODZILLA, colour=0xF800, pages=None):
        self.geometry, self.colour, self.asked, self.pages, self.closed = geometry, colour, [], pages, False

    def sh(self, script, timeout=30, check=True):
        return self.geometry

    def raw(self, command):
        self.asked.append(command)
        if self.pages is not None:
            if not self.pages:
                return b''
            self.pages -= 1
        return _page(1360, 768, 2720, self.colour)

    def close(self):
        self.closed = True


def test_capture_reads_only_the_page_being_shown():
    from PIL import Image
    m = Machine()
    png, w, h = MS.capture(m)
    assert (w, h) == (1360, 768) and Image.open(io.BytesIO(png)).getpixel((700, 400)) == (255, 0, 0)
    assert 'bs=2720' in m.asked[0] and 'count=768' in m.asked[0] and '/sys/class/graphics/fb0/pan' in m.asked[0]
    assert 'of=' not in m.asked[0]                                            # it reads; it writes nothing
    with pytest.raises(MS.ScreenError):
        MS.capture(Machine(geometry='none\n'))


def test_live_view_yields_pages_until_the_machine_stops():
    view = MS.LiveView(Machine(pages=3))
    frames = list(view.frames())
    assert len(frames) == 3 and all(len(f) == view.size for f in frames) and not view.plain
    view.close()
    assert MS.frame_rate([0.0, 0.5, 1.0, 1.5], now=1.5) == pytest.approx(2.0) and MS.frame_rate([1.0], now=1.0) == 0.0
    # the machine's side cleans up after itself: its listener is stopped by pid, and ends by itself in time
    assert MS.LIVE_PIDFILE in MS.LIVE_STOP and MS.LIVE_SECONDS == 30 * 60


def _wait(w, done):
    for _ in range(300):
        w.drain()
        if done(w.state('network')):
            return
        time.sleep(0.02)
    raise AssertionError('the Machine screen card never settled: %r' % {
        k: v for k, v in w.state('network').items() if k.startswith('screen')})


def _ready(w, tmp_path, monkeypatch):
    from pinball_decryptor.core import pad_ssh_key, ssh_card
    project = tmp_path / 'project'; project.mkdir()
    image = tmp_path / 'source.raw'; image.write_bytes(b'card')
    monkeypatch.setattr(ssh_card, 'inspect_image', lambda path: dict(supported=True, reason='', platform='stern-spike2',
                                                                    enabled=False, public_keys=''))
    monkeypatch.setattr(pad_ssh_key, 'KEY_DIR', tmp_path / 'keys')
    w.run(w.window.write_assets_var.set, str(project))
    w.run(w.window.write_upd_var.set, str(image))
    svc = w.window.service('network')
    w.run(svc.on_show)
    w.call('network.set_address', '192.168.1.40')
    return svc


def test_network_tab_captures_saves_and_runs_a_live_view(tmp_path, monkeypatch):
    from PIL import Image
    from pinball_decryptor.core import remote_send
    with web_app(tmp_path, mfr='stern') as w:
        svc = _ready(w, tmp_path, monkeypatch)
        made = []

        def connect(address):
            made.append(Machine(colour=0x07E0, pages=4))
            return made[-1]
        monkeypatch.setattr(remote_send, 'connect', connect)
        assert w.call('network.capture_screen')
        _wait(w, lambda s: not s.get('screen_busy'))
        st = w.state('network')
        assert st['screen_kind'] == 'ok' and '1360 x 768' in st['screen_note'] and made[0].closed
        assert Image.open(st['screen_path']).getpixel((5, 5)) == (0, 255, 0) and st['screen_seq'] == 1

        out = tmp_path / 'kept.png'
        monkeypatch.setattr(w.window, 'ask_save', lambda *a, **k: str(out))
        assert w.call('network.save_screen')
        assert Image.open(out).size == (1360, 768) and 'Saved to' in w.state('network')['screen_note']

        # live: the frames reach the page server's stream, and when the machine's side ends the last one is kept
        assert w.call('network.start_live')
        got = svc.live_frame(0, 5.0)
        assert got and got[0] >= 1 and Image.open(io.BytesIO(got[1])).format == 'JPEG'
        _wait(w, lambda s: not s.get('screen_live'))
        st = w.state('network')
        assert made[1].closed and 'last frame is kept' in st['screen_note'] and st['screen_seq'] == 2
        assert svc.live_frame(0, 0.1) is None                                 # nothing live: the stream ends

        def refused(address):
            raise remote_send.SendError("192.168.1.40 didn't let this computer in.")
        monkeypatch.setattr(remote_send, 'connect', refused)
        assert w.call('network.capture_screen')
        _wait(w, lambda s: not s.get('screen_busy'))
        assert w.state('network')['screen_kind'] == 'err' and "didn't let" in w.state('network')['screen_note']
    js = (Path(MS.__file__).parents[1] / 'webui/static/js/tabs/network.js').read_text(encoding='utf-8')
    assert 'Machine screen' in js and '"/screen?t="' in js and 'network.start_live' in js and 'network.save_screen' in js
    server = (Path(MS.__file__).parents[1] / 'webui/server.py').read_text(encoding='utf-8')
    assert 'multipart/x-mixed-replace' in server and 'path == "/screen"' in server


def test_the_page_server_plays_the_live_frames_as_one_changing_picture():
    from pinball_decryptor.webui import server

    class Svc:
        frames = [(1, b'JPEG-ONE'), (1, None), (2, b'JPEG-TWO'), None]       # a wait with no new frame in between

        def live_frame(self, seq, timeout):
            return self.frames.pop(0)

    class App:
        class bus:
            closed = False

        class window:
            @staticmethod
            def service(ns):
                return Svc() if ns == 'network' else None

    class Handler:
        app, wfile, said, close_connection = App, io.BytesIO(), [], False

        def send_response(self, code):
            self.said.append(int(code))

        def send_header(self, k, v):
            self.said.append((k, v))

        def end_headers(self):
            pass

    h = Handler()
    server._Handler._screen(h)
    body = h.wfile.getvalue()
    assert h.said[0] == 200 and ('Content-Type', 'multipart/x-mixed-replace; boundary=padframe') in h.said
    assert body.count(b'--padframe') == 2 and b'Content-Length: 8\r\n\r\nJPEG-ONE\r\n' in body and b'JPEG-TWO' in body
    assert h.close_connection
