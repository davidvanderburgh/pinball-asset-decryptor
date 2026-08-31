"""Spike 1 DMD (dot-matrix display) decoder + renderer.

The Spike 1 game drives its 128x32 DMD over /dev/spi0 as a stream of 2048-byte
frames.  The capture rig (s1hwshim --capture / emu_root S1_SPI0_CAP) records
that stream; this module decodes and renders it.

Frame format (verified against a live Game of Thrones LE capture — the decoded
frames read "GAME OF THRONES LE  V1.37.0", "SERVICE MENU", "REPLAY AT
300,000,000", etc.):

  * 128 x 32 pixels, 4 bits/pixel (16 grey levels).
  * Organised as **4 bit-planes** of 512 bytes each (plane p at byte offset
    p*512).  Plane p supplies bit p of every pixel's grey value.
  * Within a plane, pixels are packed 8-per-byte, **MSB first**, row-major
    (x fastest, then y).

So pixel (x, y) grey = sum over planes p of
    bit (7 - ((y*128 + x) & 7)) of frame[p*512 + (y*128 + x)//8]  << p
"""

import os

WIDTH = 128
HEIGHT = 32
PLANES = 4
PLANE_BYTES = WIDTH * HEIGHT // 8          # 512
FRAME_BYTES = PLANE_BYTES * PLANES         # 2048


def decode_frame(frame):
    """Decode one 2048-byte DMD frame to a list of HEIGHT rows, each a list of
    WIDTH grey values 0..15."""
    if len(frame) < FRAME_BYTES:
        raise ValueError("frame is %d bytes, need %d" % (len(frame), FRAME_BYTES))
    out = [[0] * WIDTH for _ in range(HEIGHT)]
    for y in range(HEIGHT):
        row = out[y]
        for x in range(WIDTH):
            p = y * WIDTH + x
            byte_i = p >> 3
            bit = 7 - (p & 7)
            v = 0
            for plane in range(PLANES):
                v |= ((frame[plane * PLANE_BYTES + byte_i] >> bit) & 1) << plane
            row[x] = v
    return out


def frame_is_blank(frame):
    return not any(frame[:FRAME_BYTES])


def iter_frames(data):
    """Yield (index, frame_bytes) for each full frame in a capture blob."""
    for i in range(len(data) // FRAME_BYTES):
        yield i, data[i * FRAME_BYTES:(i + 1) * FRAME_BYTES]


def render_frame_png(frame, path=None, scale=4, amber=True):
    """Render one decoded-or-raw frame to a PIL image (amber DMD look)."""
    from PIL import Image
    grid = decode_frame(frame) if isinstance(frame, (bytes, bytearray)) else frame
    img = Image.new("RGB", (WIDTH, HEIGHT))
    px = img.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            c = grid[y][x] * 17            # 0..15 -> 0..255
            px[x, y] = (c, int(c * 0.55), 0) if amber else (c, c, c)
    if scale != 1:
        img = img.resize((WIDTH * scale, HEIGHT * scale), Image.NEAREST)
    if path:
        img.save(path)
    return img


def render_capture_montage(data, path, max_frames=8, scale=5, gap=14):
    """Render a montage of distinct non-blank frames from a capture blob."""
    from PIL import Image
    seen, picks = [], []
    for i, frame in iter_frames(data):
        if frame_is_blank(frame):
            continue
        head = frame[:PLANE_BYTES]
        if all(sum(a != b for a, b in zip(head, t)) > 40 for t in seen):
            seen.append(head)
            picks.append(frame)
        if len(picks) >= max_frames:
            break
    if not picks:
        raise ValueError("no non-blank frames in capture")
    tw, th = WIDTH * scale, HEIGHT * scale
    mont = Image.new("RGB", (tw, (th + gap) * len(picks)), (12, 12, 18))
    for row, frame in enumerate(picks):
        mont.paste(render_frame_png(frame, scale=scale), (0, row * (th + gap)))
    mont.save(path)
    return len(picks)


def latest_frame(path):
    """Return the newest complete frame in a (possibly growing) capture file,
    or None. The rig appends 2048-byte frames as the game draws them, so tailing
    the file and decoding the last whole frame gives a live DMD."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    n = size // FRAME_BYTES
    if n == 0:
        return None
    with open(path, "rb") as f:
        f.seek((n - 1) * FRAME_BYTES)
        frame = f.read(FRAME_BYTES)
    return frame if len(frame) == FRAME_BYTES else None


class DmdView:
    """Live Tk window over a growing /dev/spi0 capture (S1_SPI0_CAP). Renders the
    newest frame at ~20 fps. Render is delegated to render_frame_png so the pixel
    format stays single-sourced (and tested)."""

    def __init__(self, capture, scale=6, hz=20):
        import tkinter as tk
        self.tk = tk
        self.capture = capture
        self.scale = scale
        self.delay = max(1, int(1000 / hz))
        self.root = tk.Tk()
        self.root.title("Spike 1 DMD")
        # Force an on-screen position: under WSLg/Weston a window with no
        # explicit geometry lands off-screen (observed at x~4985), so it opens
        # but is never visible.
        self.root.geometry("+60+60")
        self.root.configure(bg="#000000")
        self.label = tk.Label(self.root, bg="#000000")
        self.label.pack()
        self._photo = None
        self._blank = None

    def _show(self, frame):
        from PIL import ImageTk
        if frame is None or frame_is_blank(frame):
            if self._blank is None:
                from PIL import Image
                self._blank = Image.new(
                    "RGB", (WIDTH * self.scale, HEIGHT * self.scale), (8, 4, 0))
            img = self._blank
        else:
            img = render_frame_png(frame, scale=self.scale)
        self._photo = ImageTk.PhotoImage(img)
        self.label.config(image=self._photo)

    def _tick(self):
        self._show(latest_frame(self.capture))
        self.root.after(self.delay, self._tick)

    def run(self):
        self._tick()
        self.root.mainloop()


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Spike 1 DMD decoder/renderer")
    ap.add_argument("capture", help="raw /dev/spi0 capture (2048-byte frames)")
    ap.add_argument("--png", help="render a montage of distinct frames to PNG")
    ap.add_argument("--live", action="store_true",
                    help="live Tk window tailing a growing capture (S1_SPI0_CAP)")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--scale", type=int, default=5)
    args = ap.parse_args(argv)

    if args.live:
        DmdView(args.capture, scale=max(args.scale, 6)).run()
        return 0

    if not args.png:
        ap.error("need --png (montage) or --live")
    data = open(args.capture, "rb").read()
    n = len(data) // FRAME_BYTES
    nb = sum(1 for _, f in iter_frames(data) if not frame_is_blank(f))
    print("%d frames, %d non-blank" % (n, nb))
    got = render_capture_montage(data, args.png, max_frames=args.frames,
                                 scale=args.scale)
    print("wrote %s (%d distinct frames)" % (args.png, got))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
