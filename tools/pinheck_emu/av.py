"""The Propeller's picture, high level: which video plays, and its frames (PAD-320).

Follows the game's 0x02 (video) packets and draws the DMD from the
user's own SD-card files with the plugin's VID decoder
(``pinball_decryptor/plugins/spooky/p3_video.py``). A video named ``ZMA``
is ``DMD/_DZ/ZMA.VID``. Jetsons puts the three letters in bytes 1..3,
Domino's in bytes 0..2; the one that names a file on the card wins.

Not drawn yet: text (0x12), scores and numbers, sprites, fonts, layers.
"""
import os

from pinball_decryptor.plugins.spooky import p3_video

VIDEO = 0x02
FPS = p3_video.DEFAULT_FPS


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

    def image(self, n, pixel_size=4):
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


class Av:
    def __init__(self, card):
        self.card = card
        self.played = []            # (millis, name, Vid or None)
        self._cache = {}

    def path(self, name):
        return os.path.join(self.card, "DMD", "_D" + name[0], name + ".VID")

    def video_name(self, pkt):
        """(name, on the card?); name is None for a packet naming nothing."""
        names = [n for n in (_name(pkt[1:4]), _name(pkt[0:3])) if n]
        for n in names:
            if os.path.isfile(self.path(n)):
                return n, True
        return (names[0] if names else None), False

    def vid(self, name):
        if name not in self._cache:
            self._cache[name] = Vid(self.path(name))
        return self._cache[name]

    def packet(self, pkt, millis):
        if pkt[15] != VIDEO:
            return
        if pkt[0] == 0xFF and not any(pkt[1:15]):
            self.played.append((millis, "stop", None))      # Domino's: stop the video
            return
        name, found = self.video_name(pkt)
        if not found:
            name = "%s (not on card)" % name if name else "?"
        self.played.append((millis, name, self.vid(name) if found else None))

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
