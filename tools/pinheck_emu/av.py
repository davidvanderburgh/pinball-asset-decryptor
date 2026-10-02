"""The Propeller's picture, high level: videos and text on the DMD (PAD-320).

Follows the game's packets and draws the DMD from the user's own SD-card
files with the plugin's VID decoder (``pinball_decryptor/plugins/spooky/
p3_video.py``). A video named ``ZMA`` is ``DMD/_DZ/ZMA.VID``.

Two packet layouts are known:

* AMH's (github.com/benheck/AMH ``video()``), used by Domino's and Rob
  Zombie: 0x02 play, 0x06 queue after the current one (an empty name
  clears the queue); bytes 0..2 the name, byte 3 attributes (bit 7 = loop),
  byte 5 priority; a first byte of 255 only sets the priority.
* Jetsons': byte 0 a layer, bytes 1..3 the name. Layers are drawn in order,
  black is see-through. What its other bytes mean is not known yet.

Text: AMH's 0x12 (byte 0 = column << 4 | row, in 8-pixel cells; then
ASCII) and Rob Zombie's 0x0F (byte 0 = line, then ASCII, centred).
Scores: AMH's 0x03 ``SetScore`` (byte 0 the player 1..4, bytes 1..4 the
score) in every game; kept in ``scores`` - the window shows them beside the
DMD, as where the A/V chip draws them is not known yet. Text
stays until the next video starts. It is drawn with the card's own font
sprite ``DMD/_DZ/ZMF.spr`` when there is one (AMH's: a 128x32 4bpp sheet of
8x8 glyphs, ASCII 32..95), else with a small built-in font - the colour
games' ``.FNT`` fonts are not decoded yet. Scores and numbers (0x07, 0x03
...) are not drawn yet.
"""
import os

from pinball_decryptor.plugins.spooky import p3_video

VIDEO, QUEUE, TEXT, TEXT_RZ, SCORE = 0x02, 0x06, 0x12, 0x0F, 0x03
FPS = p3_video.DEFAULT_FPS


_LUTS = {}


def _lut_rgb332():
    """byte -> (r, g, b): the colour games' RGB332 pixels (as p3_video)."""
    if "332" not in _LUTS:
        import numpy as np
        v = np.arange(256)
        _LUTS["332"] = np.stack((((v >> 5) & 7) * 255 // 7, ((v >> 2) & 7) * 255 // 7,
                                 (v & 3) * 255 // 3), 1).astype(np.uint8)
    return _LUTS["332"]


def _lut_amber(max_brightness):
    """shade 0..15 -> (r, g, b): the 16-shade games' amber dots (as p3_video)."""
    key = ("amber", max_brightness)
    if key not in _LUTS:
        import numpy as np
        r, g, b = p3_video.DEFAULT_COLOR
        rows = []
        for s in range(16):
            k = (min(s, max_brightness) / max_brightness) ** (1 / p3_video.DEFAULT_GAMMA) if s else 0
            rows.append((int(r * k), int(g * k), int(b * k)))
        _LUTS[key] = np.array(rows, np.uint8)
    return _LUTS[key]


def _name(raw):
    s = bytes(raw).decode("latin1")
    return s if len(s) == 3 and s.isalnum() else None


class Vid:
    def __init__(self, path):
        data = open(path, "rb").read()
        body = data[512:]
        h = p3_video.parse_vid_header(data[:512], len(body), body[:4096])
        self.width, self.height, self.bpp = h["width"], h["height"], h["bpp"]
        self.sub = h["subframes"]
        self.max_brightness = h["max_brightness"]
        self.size = self.width * self.height // (1 if self.bpp == 8 else 2)
        self.body = body
        self.frames = max(1, len(body) // self.size // self.sub)

    @property
    def shape(self):
        return self.width, self.height * self.sub

    def rgb(self, n):
        """Frame ``n`` as a PIL RGB image at 1 pixel per dot."""
        import numpy as np
        from PIL import Image
        n = min(max(n, 0), self.frames - 1)
        off = n * self.sub * self.size
        raw = np.frombuffer(self.body, np.uint8, self.size * self.sub, off)
        if self.bpp == 8:
            px = _lut_rgb332()[raw]
        else:
            px = _lut_amber(self.max_brightness)[np.stack((raw >> 4, raw & 15), 1).ravel()]
        return Image.fromarray(px.reshape(self.height * self.sub, self.width, 3), "RGB")

    def image(self, n, pixel_size=4):
        """Frame ``n`` with the DMD dot look (the plugin's renderer)."""
        from PIL import Image
        n = min(max(n, 0), self.frames - 1)
        parts = []
        for k in range(self.sub):
            off = (n * self.sub + k) * self.size
            parts.append(p3_video.render_frame(
                self.body[off:off + self.size], self.width, self.height, self.bpp,
                pixel_size=pixel_size, max_brightness=self.max_brightness))
        if len(parts) == 1:
            return parts[0]
        img = Image.new("RGB", (parts[0].width, sum(p.height for p in parts)))
        y = 0
        for p in parts:
            img.paste(p, (0, y))
            y += p.height
        return img


class Font:
    """The card's 8x8 font sprite, or a built-in stand-in."""
    def __init__(self, card):
        self.sheet = None
        path = os.path.join(card, "DMD", "_DZ", "ZMF.spr")
        if os.path.isfile(path):
            data = open(path, "rb").read()
            if len(data) >= 512 + 2048:
                self.sheet = data[512:512 + 2048]       # 128x32, 4bpp
        if self.sheet is None:
            from PIL import ImageFont
            self.ttf = ImageFont.load_default(size=8)

    def draw(self, img, x, y, text, colour=(255, 140, 0)):
        if self.sheet is None:
            from PIL import ImageDraw
            d = ImageDraw.Draw(img)
            d.fontmode = "1"
            d.text((x, y - 1), text, font=self.ttf, fill=colour)
            return
        for ch in text.upper():
            c = ord(ch) - 32
            if 0 <= c < 64:
                gx, gy = (c & 15) * 8, (c >> 4) * 8
                for row in range(8):
                    for col in range(8):
                        b = self.sheet[(gy + row) * 64 + (gx + col) // 2]
                        v = (b >> 4) if col % 2 == 0 else (b & 15)
                        if v and 0 <= x + col < img.width and 0 <= y + row < img.height:
                            k = (v / 15) ** (1 / 2.2)
                            img.putpixel((x + col, y + row), tuple(int(c_ * k) for c_ in colour))
            x += 8


class Av:
    """Follows the packets; ``frame(millis)`` is the DMD at that time."""
    def __init__(self, card):
        self.card = card
        self.played = []            # (millis, name, Vid or None)
        self._cache = {}
        self.layers = {}            # layer -> [Vid, start ms, loop]
        self.queue = []             # (Vid, loop)
        self.texts = {}             # (x, y) -> str
        self.scores = {}            # player 1..4 -> score
        self.font = None
        self.size = None            # (w, h) of the display, from the first video
        self.layout = None          # "amh" or "jetsons", from the first video packet

    def path(self, name):
        return os.path.join(self.card, "DMD", "_D" + name[0], name + ".VID")

    def video_name(self, pkt):
        """(name, on the card?, layout)."""
        cands = [(n, lay) for n, lay in ((_name(pkt[1:4]), "jetsons"), (_name(pkt[0:3]), "amh")) if n]
        for n, lay in cands:
            if os.path.isfile(self.path(n)):
                return n, True, lay
        return (cands[0][0] if cands else None), False, (cands[0][1] if cands else None)

    def vid(self, name):
        if name not in self._cache:
            self._cache[name] = Vid(self.path(name))
        return self._cache[name]

    def packet(self, pkt, millis):
        cmd = pkt[15]
        if cmd == SCORE:
            if 1 <= pkt[0] <= 4:
                self.scores[pkt[0]] = int.from_bytes(pkt[1:5], "little")
            return
        if cmd in (VIDEO, QUEUE):
            if pkt[0] == 0xFF and not any(pkt[1:5]):
                if cmd == VIDEO:
                    self.played.append((millis, "priority", None))
                return
            if cmd == QUEUE and not any(pkt[0:3]):
                self.queue.clear()
                return
            name, found, lay = self.video_name(pkt)
            if self.layout is None and lay and found:
                self.layout = lay
            if not found:
                if cmd == VIDEO:
                    self.played.append((millis, "%s (not on card)" % name if name else "?", None))
                return
            v = self.vid(name)
            self.size = self.size or v.shape
            if self.layout == "jetsons":
                layer, loop = pkt[0], False
            else:
                layer, loop = 0, bool(pkt[3] & 0x80)
            if cmd == QUEUE and self.layout != "jetsons":
                self.queue.append((v, loop))
                return
            self.layers[layer] = [v, millis, loop]
            self.texts.clear()
            self.played.append((millis, name, v))
        elif cmd == TEXT or (cmd == TEXT_RZ and self.layout == "amh" and pkt[0] < 8):
            text = bytes(pkt[1:15]).split(b"\0")[0].split(b"\xff")[0].decode("latin1")
            key = ("rz", pkt[0]) if cmd == TEXT_RZ else ((pkt[0] >> 4) * 8, (pkt[0] & 15) * 8)
            self.texts[key] = text

    def frame(self, millis):
        """The DMD at ``millis`` as a PIL RGB image, 1 pixel per dot."""
        from PIL import Image
        w, h = self.size or (128, 32)
        img = Image.new("RGB", (w, h))
        for layer in sorted(self.layers):
            v, start, loop = self.layers[layer]
            n = (millis - start) * FPS // 1000
            if n >= v.frames:
                if layer == 0 and self.queue:
                    nv, nloop = self.queue.pop(0)
                    self.layers[0] = [nv, millis, nloop]
                    v, n = nv, 0
                elif loop:
                    n %= v.frames
                else:
                    n = v.frames - 1
            f = v.rgb(n)
            if f.size != (w, h):
                f = f.resize((w, h))
            mask = f.convert("L").point(lambda p: 255 if p else 0)
            img.paste(f, (0, 0), mask)
        if self.texts:
            if self.font is None:
                self.font = Font(self.card)
            for key, text in self.texts.items():
                if key[0] == "rz":
                    lines = sorted(k[1] for k in self.texts if k[0] == "rz")
                    y = (h - 8 * len(lines)) // 2 + 8 * lines.index(key[1])
                    x = max(0, (w - 8 * len(text)) // 2)
                else:
                    x, y = key
                    if y >= h:          # Jetsons' row bit 3 - a second size, not decoded
                        y = (y - 64) * 2 if y >= 64 else y % h
                self.font.draw(img, x, y, text)
        return img

    def contact_sheet(self, path, columns=4, pixel_size=3):
        """One mid-video frame per video played, captioned with its name and
        start time: the attract sequence at a glance."""
        from PIL import Image, ImageDraw
        cells = []
        for ms, name, v in self.played:
            if v is None:
                continue
            img = v.image(v.frames // 2, pixel_size)
            cells.append((img, "%s  %.1f s" % (name, ms / 1000)))
        if not cells:
            return False
        cw = max(c.width for c, _ in cells)
        ch = max(c.height for c, _ in cells) + 18
        rows = (len(cells) + columns - 1) // columns
        sheet = Image.new("RGB", (cw * min(columns, len(cells)) + 8 * columns, ch * rows + 8 * rows),
                          (24, 24, 24))
        d = ImageDraw.Draw(sheet)
        for i, (img, cap) in enumerate(cells):
            x, y = (i % columns) * (cw + 8), (i // columns) * (ch + 8)
            sheet.paste(img, (x, y))
            d.text((x + 2, y + img.height + 3), cap, fill=(230, 230, 230))
        sheet.save(path)
        return True
