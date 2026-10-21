"""PAD-664: a one-page table as a PDF, written with the standard library only.

The Modes tab's rules sheet is printed at a cabinet, on Windows, macOS and Linux alike, so it is made without a
browser or a PDF library: the PDF's own Helvetica and Helvetica-Bold (two of the 14 fonts every PDF reader has, so
nothing is embedded), text measured with their published widths, and the page drawn as the sheet's HTML is - a
title, a line under it, a table with a dark head row and banded rows, and a foot. The table's type shrinks until
the sheet fits on one page; past the smallest size it runs on over more pages, the head row repeated.

Text is written in WinAnsiEncoding (Windows-1252), which holds the sheet's dashes, middle dots, curly quotes and
accented letters; anything else is written as its plain letter or a "?".
"""
from __future__ import annotations

import re
import unicodedata
import zlib

# Helvetica and Helvetica-Bold widths (1/1000 em) of the printable ASCII, from the Adobe AFM files
_ASCII = " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"
_REG = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
        556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500,
        667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333,
        556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500,
        722, 500, 500, 500, 334, 260, 334, 584]
_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
         556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556,
         722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333,
         556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556,
         778, 556, 556, 500, 389, 280, 389, 584]
# the rest of WinAnsi the sheet may use: (regular, bold)
_MORE = {"•": (350, 350), "–": (556, 556), "—": (1000, 1000), "‘": (222, 278),
         "’": (222, 278), "“": (333, 500), "”": (333, 500), "·": (278, 278), "×": (584, 584),
         "…": (1000, 1000), " ": (278, 278), "°": (400, 400), "÷": (584, 584)}
WIDTHS = {False: dict(zip(_ASCII, _REG)), True: dict(zip(_ASCII, _BOLD))}
for _c, (_r, _b) in _MORE.items():
    WIDTHS[False][_c], WIDTHS[True][_c] = _r, _b


def _plain(ch):
    """A character the fonts can write: itself, its base letter (é -> e for measuring), or "?"."""
    try:
        ch.encode("cp1252")
        return ch
    except UnicodeEncodeError:
        pass
    base = unicodedata.normalize("NFKD", ch)[:1]
    if base and base.isascii():
        return base
    return {"−": "-", "‑": "-", "‐": "-", "→": ">", "≤": "<=", "≥": ">="}.get(ch, "?")


def clean(text):
    return "".join(_plain(c) for c in str(text or ""))


def width(text, size, bold=False):
    table = WIDTHS[bool(bold)]
    total = 0
    for c in text:
        w = table.get(c)
        if w is None:
            base = unicodedata.normalize("NFKD", c)[:1]
            w = table.get(base, 556)
        total += w
    return total * size / 1000.0


def _pdf_text(text):
    raw = text.encode("cp1252", "replace")
    return "(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)").decode("latin-1") + ")"


def wrap(runs, size, room):
    """Runs of ``(text, style)`` broken into lines no wider than ``room``: ``[[(x, text, style)], ...]``. A "\n"
    in a run starts a new line; words with no space between them (a run's end and the next run's start: a stage's
    number and its first word) stay on one line; a word wider than the room is cut."""
    words = []                                  # [(text, style, size, bold)] with "\n" items; a word keeps its space
    for text, style in runs:
        bold = style in ("bold", "tag")
        sz = size * 0.82 if style == "tag" else size
        for pi, part in enumerate(clean(text).split("\n")):
            if pi:
                words.append(("\n", style, sz, bold))
            for w in re.findall(r"[^ ]+ *| +", part):
                words.append((w, style, sz, bold))
    groups, cur = [], []                        # words glued together (no space between them) move as one
    for w in words:
        if w[0] == "\n":
            if cur:
                groups.append(cur)
                cur = []
            groups.append([w])
            continue
        cur.append(w)
        if w[0].endswith(" "):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    lines, line, x = [], [], 0.0
    for g in groups:
        if g[0][0] == "\n":
            lines.append(line)
            line, x = [], 0.0
            continue
        gw = sum(width(t, sz, b) for t, _s, sz, b in g[:-1]) + width(g[-1][0].rstrip(" "), g[-1][2], g[-1][3])
        if x + gw > room and line:
            lines.append(line)
            line, x = [], 0.0
            if not "".join(t for t, *_r in g).strip():
                continue
        for t, style, sz, b in g:
            while width(t.rstrip(" "), sz, b) > room - x and len(t.rstrip(" ")) > 1 and not line:
                cut = len(t)
                while cut > 1 and width(t[:cut], sz, b) > room:
                    cut -= 1
                lines.append([(0.0, t[:cut], style)])
                t = t[cut:]
            line.append((x, t, style))
            x += width(t, sz, b)
    if line or not lines:
        lines.append(line)
    return [_joined(line) for line in lines]


def _joined(line):
    """A line's pieces of one style written as one (the PDF's text reads as phrases, not words)."""
    out = []
    for x, s, style in line:
        if out and out[-1][2] == style:
            out[-1] = (out[-1][0], out[-1][1] + s, style)
        else:
            out.append((x, s, style))
    return out


class _Page:
    def __init__(self):
        self.ops = []

    def rect(self, x, y, w, h, grey):
        self.ops.append("%.3f g %.2f %.2f %.2f %.2f re f" % (grey, x, y, w, h))

    def hline(self, x0, x1, y, grey, lw=0.75):
        self.ops.append("%.3f G %.2f w %.2f %.2f m %.2f %.2f l S" % (grey, lw, x0, y, x1, y))

    def text(self, x, y, s, size, bold=False, grey=0.1):
        if not s.strip():
            return
        self.ops.append("BT /%s %.2f Tf %.3f g %.2f %.2f Td %s Tj ET"
                        % ("F2" if bold else "F1", size, grey, x, y, _pdf_text(s.rstrip(" "))))


def _draw_lines(page, lines, x0, y, size, lead, grey=0.1, colour=None):
    for line in lines:
        y -= lead
        for x, s, style in line:
            if style == "tag":
                page.text(x0 + x, y, s, size * 0.82, True, 0.4)
            else:
                page.text(x0 + x, y, s, size, style == "bold", colour if colour is not None else grey)
    return y


def table_pdf(title, intro, heads, rows, foot, page=(792.0, 612.0), widths=None, centre=(),
              margins=(32.4, 28.8), sizes=(8.6, 5.6), measure=False):
    """The PDF's bytes: ``title`` and ``intro`` over a table of ``heads`` and ``rows`` (each cell a list of runs
    ``(text, style)``, style "" / "bold" / "tag"), then ``foot``. ``widths``: each column's share of the width;
    ``centre``: the columns set centred. ``measure``: only ``(table type size, line and foot size)`` in points, the
    sizes that fit it on one page (the HTML uses them too)."""
    pw, ph = page
    mx, my = margins
    tw = pw - 2 * mx
    n = len(heads)
    widths = widths or [1.0 / n] * n
    cols = [tw * w for w in widths]
    pad_x = 7.0

    def layout(size):
        lead = size * 1.22
        out = []
        for row in rows:
            cells = [wrap(cell, size, cols[i] - 2 * pad_x) for i, cell in enumerate(row)]
            h = max(len(c) for c in cells) * lead + 6.0
            out.append((cells, h))
        return out, lead

    scale = sizes[0]
    title_size, sub_size, head_size = 22.0, 9.0, 9.0
    while True:
        laid, lead = layout(scale)
        k = scale / sizes[0]
        sub_lines = wrap([(intro, "")], sub_size * max(k, 0.85), tw)
        foot_lines = wrap([(foot, "")], 8.4 * max(k, 0.85), tw)
        head_h = head_size + 10.0
        need = (title_size + 4 + len(sub_lines) * sub_size * max(k, 0.85) * 1.25 + 9 + head_h
                + sum(h for _c, h in laid) + 7 + len(foot_lines) * 8.4 * max(k, 0.85) * 1.25)
        if need <= ph - 2 * my or scale <= sizes[1]:
            break
        scale = round(scale - 0.2, 2)
    if measure:
        return scale, round(sub_size * max(k, 0.85), 2), round(8.4 * max(k, 0.85), 2)

    pages = []
    pg = _Page()
    y = ph - my
    pg.text(mx, y - title_size, clean(title), title_size, True, 0.1)
    y -= title_size + 4
    sk = sub_size * max(k, 0.85)
    y = _draw_lines(pg, sub_lines, mx, y, sk, sk * 1.25, 0.2) - 9

    def head(pg, y):
        pg.rect(mx, y - head_h, tw, head_h, 0.133)
        x = mx
        for i, hd in enumerate(heads):
            pg.text(x + pad_x, y - head_h + 6.0, clean(hd), head_size, True, 1.0)
            x += cols[i]
        return y - head_h

    y = head(pg, y)
    for ri, (cells, h) in enumerate(laid):
        if y - h < my:
            pages.append(pg)
            pg = _Page()
            y = head(pg, ph - my)
        if ri % 2 == 1:
            pg.rect(mx, y - h, tw, h, 0.941)
        x = mx
        for i, lines in enumerate(cells):
            if i in centre:
                lines = [[(xx + (cols[i] - 2 * pad_x - _line_w(line, scale)) / 2.0, s, st) for xx, s, st in line]
                         for line in lines]
            _draw_lines(pg, lines, x + pad_x, y - 3.0 + lead * 0.22, scale, lead)
            x += cols[i]
        y -= h
        pg.hline(mx, mx + tw, y, 0.79)
    fk = 8.4 * max(k, 0.85)
    if y - 7 - len(foot_lines) * fk * 1.25 < my:
        pages.append(pg)
        pg = _Page()
        y = ph - my
    _draw_lines(pg, foot_lines, mx, y - 7, fk, fk * 1.25, 0.13)
    pages.append(pg)
    return _document(pages, pw, ph, title)


def _line_w(line, size):
    if not line:
        return 0.0
    x, s, style = line[-1]
    return x + width(s.rstrip(" "), size * (0.82 if style == "tag" else 1), style in ("bold", "tag"))


def _document(pages, pw, ph, title):
    objs = []                                           # bodies, numbered from 1

    def add(body):
        objs.append(body)
        return len(objs)

    cat = add(None)
    pages_id = add(None)
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for pg in pages:
        data = zlib.compress("\n".join(pg.ops).encode("latin-1"))
        content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
        kids.append(add(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                         "/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>"
                         % (pages_id, pw, ph, content, f1, f2)).encode("latin-1")))
    objs[cat - 1] = ("<< /Type /Catalog /Pages %d 0 R >>" % pages_id).encode("latin-1")
    objs[pages_id - 1] = ("<< /Type /Pages /Kids [%s] /Count %d >>"
                          % (" ".join("%d 0 R" % k for k in kids), len(kids))).encode("latin-1")
    info = add(("<< /Title %s /Producer (Pinball Asset Decryptor) >>" % _pdf_text(clean(title))).encode("latin-1"))
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, cat, info, xref))
    return bytes(out)
