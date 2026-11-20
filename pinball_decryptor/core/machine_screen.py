"""What a machine's own screen shows, read over remote access: one picture, or a live view (PAD-1467).

David, on seeing the capture that proved the end-to-end Send: "the remote screenshot feature is actually really
useful. can we build that into the network tab too?" and then "or even if we can do a 'screen share' live feed
that would be killer".

A Spike 2 machine draws its screen into the Linux framebuffer ``/dev/fb0``.  Its shape is in
``/sys/class/graphics/fb0``: ``virtual_size`` (on a Godzilla ``1360,1536``: two pages of 768 lines, the game flips
between them), ``bits_per_pixel`` (16: RGB565), ``stride`` (bytes a line), ``pan`` (where the page being shown
starts) and ``modes`` (the size the screen really is).  :func:`capture` reads those and then only the page being
shown; :class:`LiveView` has the machine send that page over and over.  Both only read: nothing on the machine is
changed and the game keeps running.  A frame caught while the game is drawing can show a tear.

A page is 2 MB.  Measured on a Godzilla LE on 5 GHz with a game running: 1.6 frames a second over the encrypted
connection (the machine's processor is the limit, as for Send to machine), 5 to 6.6 over a plain connection on the
home network.  So the live view uses the plain one, the way Send does for big files (``remote_send.plain_allowed``),
and the encrypted one when that cannot be made.  What crosses in the plain is the picture on the machine's screen.
"""
import io
import re
import time

FB = '/dev/fb0'
SYS = '/sys/class/graphics/fb0'
#: the five facts, one a line, in this order; a machine without the device answers ``none``
GEOMETRY = ('[ -e %s ] || { echo none; exit 0; }\n'
            'for f in virtual_size bits_per_pixel stride pan; do cat %s/$f 2>/dev/null || echo; done\n'
            'cat %s/modes 2>/dev/null | sed -n 1p\n' % (FB, SYS, SYS))
NO_SCREEN = ("This machine's screen could not be read over remote access (it has no %s). It works on Spike 2 "
             'machines.' % FB)
MAX_BYTES = 64 << 20
#: the live view's own listener on the machine: ports beside Send's, its own pid file, and how long it may run
LIVE_PORTS = (42314, 42315, 42316)
LIVE_PIDFILE = '/var/run/pad-screen.pid'
LIVE_SECONDS = 30 * 60
LIVE_STOP = ("p=$(cat {f} 2>/dev/null); if [ -n \"$p\" ] && tr '\\000' ' ' < /proc/$p/cmdline 2>/dev/null "
             "| grep -q '^nc '; then kill \"$p\" 2>/dev/null; fi; rm -f {f}").format(f=LIVE_PIDFILE)


class ScreenError(Exception):
    """Why there is no picture, in words for the user."""


def _pair(text):
    nums = [int(n) for n in re.findall(r'\d+', text or '')]
    return (nums + [0, 0])[:2]


def parse_geometry(text):
    """``dict(width, height, bpp, stride, pan_y)`` from :data:`GEOMETRY`'s answer.  *height* is the screen's own
    (from ``modes``, ``U:1360x768p-60``), not the taller virtual one; without a usable mode line it is the
    virtual height, halved when that is two pages."""
    lines = [l.strip() for l in (text or '').splitlines()]
    if not lines or lines[0] == 'none':
        raise ScreenError(NO_SCREEN)
    lines += [''] * 5
    vw, vh = _pair(lines[0])
    bpp = _pair(lines[1])[0]
    stride = _pair(lines[2])[0]
    pan_y = _pair(lines[3])[1]
    mode = re.search(r'(\d+)x(\d+)', lines[4])
    if not vw or not vh or bpp not in (16, 24, 32):
        raise ScreenError("This machine's screen is in a form this app does not read (%s, %s bits a pixel)."
                          % (lines[0] or 'no size', lines[1] or '?'))
    width, height = vw, vh
    if mode and int(mode.group(1)) == vw and 0 < int(mode.group(2)) <= vh:
        height = int(mode.group(2))
    elif vh % 2 == 0 and pan_y == vh // 2:
        height = vh // 2
    stride = stride or vw * bpp // 8
    if pan_y + height > vh:
        pan_y = 0
    return dict(width=width, height=height, bpp=bpp, stride=stride, pan_y=pan_y)


def frame_bytes(geo):
    return geo['stride'] * geo['height']


def to_image(raw, geo):
    """One page of framebuffer *raw* (``height`` lines of ``stride`` bytes) as a PIL RGB image."""
    import numpy as np
    from PIL import Image
    w, h, bpp, stride = geo['width'], geo['height'], geo['bpp'], geo['stride']
    need = stride * h
    if len(raw) < need:
        raise ScreenError('The machine sent %d of the %d bytes of its screen; try again.' % (len(raw), need))
    lines = np.frombuffer(raw[:need], dtype=np.uint8).reshape(h, stride)[:, :w * bpp // 8]
    if bpp == 16:
        px = lines.reshape(h, w, 2)
        v = px[:, :, 0].astype(np.uint16) | (px[:, :, 1].astype(np.uint16) << 8)
        rgb = np.dstack([((v >> 11) & 31).astype(np.uint16) * 255 // 31, ((v >> 5) & 63).astype(np.uint16) * 255 // 63,
                         (v & 31).astype(np.uint16) * 255 // 31])
    else:
        px = lines.reshape(h, w, bpp // 8)
        rgb = px[:, :, 2::-1]                                   # stored blue, green, red
    return Image.fromarray(np.ascontiguousarray(rgb).astype(np.uint8), 'RGB')


def encode(raw, geo, kind='PNG', quality=80):
    """The picture's file bytes: a PNG to keep, or a JPEG (a live frame: a tenth of the size, made in a moment)."""
    out = io.BytesIO()
    if kind == 'JPEG':
        to_image(raw, geo).save(out, 'JPEG', quality=quality)
    else:
        to_image(raw, geo).save(out, 'PNG')
    return out.getvalue()


def _text(answer):
    return answer[1] if isinstance(answer, tuple) else answer


def _bytes_of(machine, command, timeout=60):
    """A command's output as bytes (``SshMachine.sh`` answers text): its own session on the machine's connection."""
    if hasattr(machine, 'raw'):                                 # a stand-in machine (tests)
        return machine.raw(command)
    chan = machine.t.open_session()
    try:
        chan.settimeout(timeout)
        chan.exec_command(command)
        chan.shutdown_write()
        out = io.BytesIO()
        while out.tell() < MAX_BYTES:
            got = chan.recv(1 << 16)
            if not got:
                break
            out.write(got)
        return out.getvalue()
    finally:
        chan.close()


def geometry(machine):
    return parse_geometry(_text(machine.sh(GEOMETRY, timeout=30)))


def _page_command(geo):
    """The shell words that write the page being shown, read where ``pan`` says it is at that moment."""
    return ('p=$(cat %s/pan 2>/dev/null); p=${p#*,}; case "$p" in ""|*[!0-9]*) p=0 ;; esac; '
            'dd if=%s bs=%d skip=$p count=%d 2>/dev/null' % (SYS, FB, geo['stride'], geo['height']))


def capture(machine):
    """``(png bytes, width, height)`` of what *machine* (a connected ``remote_send`` machine) shows now."""
    geo = geometry(machine)
    raw = _bytes_of(machine, _page_command(geo))
    return encode(raw, geo), geo['width'], geo['height']


class LiveView:
    """The machine's screen, page after page, until :meth:`close`.

    ``LiveView(machine).frames()`` yields each page's raw bytes (:func:`encode` makes the picture).  The machine
    runs one small shell loop that writes the shown page again and again; when the reader stops reading, the loop
    waits, so the reader sets the pace and a slow page never piles frames up.  It ends when this side closes, and
    by itself after :data:`LIVE_SECONDS` if this side went away without saying so."""

    def __init__(self, machine, plain=None, log=None):
        from . import remote_send
        self.machine = machine
        self.geo = geometry(machine)
        self.size = frame_bytes(self.geo)
        self.plain = False
        self._sock = self._chan = None
        self._log = log or (lambda *a, **k: None)
        loop = 'while :; do %s || break; done' % _page_command(self.geo)
        want_plain = remote_send.plain_allowed() if plain is None else plain
        if want_plain and not hasattr(machine, 'raw'):
            try:
                self._open_plain(loop)
                self.plain = True
            except (OSError, ScreenError) as e:
                self._log('The live view uses the encrypted connection (slower): the plain one could not be made '
                          '(%s).' % (str(e) or type(e).__name__), 'info')
        if not self.plain:
            self._open_encrypted(loop)

    def _open_plain(self, loop):
        import socket
        port = None
        for cand in LIVE_PORTS:
            rc, out = self.machine.sh(
                # the timer stops only the listener it was started for: a later live view has another pid
                '%s; ( %s ) 2>/dev/null </dev/null | nc -l -p %d >/dev/null 2>&1 & p0=$!; echo $p0 > %s; '
                '( sleep %d; [ "$(cat %s 2>/dev/null)" = "$p0" ] && { %s; } ) >/dev/null 2>&1 </dev/null & sleep 1; '
                'kill -0 "$p0" 2>/dev/null && echo listening'
                % (LIVE_STOP, loop, cand, LIVE_PIDFILE, LIVE_SECONDS, LIVE_PIDFILE, LIVE_STOP),
                timeout=30, check=False)
            if rc == 0 and 'listening' in out:
                port = cand
                break
        if port is None:
            self.machine.sh(LIVE_STOP, timeout=20, check=False)
            raise ScreenError('the machine could not listen')
        try:
            self._sock = socket.create_connection((self.machine.host, port), timeout=8)
            self._sock.settimeout(20)
        except OSError:
            self.machine.sh(LIVE_STOP, timeout=20, check=False)
            raise

    def _open_encrypted(self, loop):
        if hasattr(self.machine, 'raw'):                        # a stand-in machine (tests): one page at a time
            return
        self._chan = self.machine.t.open_session()
        self._chan.settimeout(30)
        self._chan.exec_command(loop)
        self._chan.shutdown_write()

    def _recv(self, n):
        if self._sock is not None:
            return self._sock.recv(n)
        if self._chan is not None:
            return self._chan.recv(n)
        return b''

    def read(self):
        """The next page's raw bytes, or ``None`` when the machine's side has ended."""
        if self._sock is None and self._chan is None:
            if hasattr(self.machine, 'raw'):
                return self.machine.raw(_page_command(self.geo)) or None
            return None
        buf = bytearray()
        while len(buf) < self.size:
            got = self._recv(min(1 << 18, self.size - len(buf)))
            if not got:
                return None
            buf += got
        return bytes(buf)

    def frames(self):
        while True:
            raw = self.read()
            if raw is None:
                return
            yield raw

    def close(self):
        for thing in (self._sock, self._chan):
            if thing is not None:
                try:
                    thing.close()
                except Exception:                               # noqa: BLE001 - closing, nothing to report
                    pass
        was_plain, self._sock, self._chan = self._sock is not None, None, None
        if was_plain:
            try:
                self.machine.sh(LIVE_STOP, timeout=20, check=False)
            except Exception:                                   # noqa: BLE001 - the connection may be gone already
                pass


def frame_rate(times, now=None):
    """Frames a second over the last few seconds of *times* (monotonic stamps of frames shown)."""
    now = time.monotonic() if now is None else now
    recent = [t for t in times if now - t <= 4.0]
    if len(recent) < 2:
        return 0.0
    return (len(recent) - 1) / max(recent[-1] - recent[0], 1e-6)
