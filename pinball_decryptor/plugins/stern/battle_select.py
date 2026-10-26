"""PAD-707: new monsters on Godzilla's own BATTLE SELECTION screen.

David (2026-10-24): "add in a new monster to the existing menu but modify the menu to fit it elegantly". The screen
(``auto_loaded/cac32730...``, ``UIBattleSelectScreen`` in the program) draws seven places from a fixed table, two
slanted columns of tiles (four and three), the lit tile, the portrait and the name of the place under the cursor. A
card build EDITS THAT SCENE - the card's own, so a Heisei card keeps DragonRR's art and a stock card Stern's:

* the seven tiles are laid out again in two columns with room for the new ones (at most :data:`MAX_NEW`), smaller
  when they must be, each place's lit tile, state box (lock, claw, city) and "0/4" moved with its tile;
* the grey sheet (all seven grey tiles in one picture) is hidden and each grey tile is cut out of it and placed on
  its own, so a column can move;
* every new monster gets nodes of its own in the scene, named ``PadSel_<slug>_<part>``: its grey tile, its lit tile,
  its padlock and claw, and its portrait group (the place's portrait frame with the monster's picture in it and its
  name lettered in the card's style), all drawn like the game's own - and a ``PadSel_Cover<n>`` per place a new
  monster stands in, that place's grey tile drawn over its lit one.

The runtime (``pm_roster_more``, MODE_SDK.md "New monsters on the selection screen") walks the cursor over the new
tiles as well: on a new monster it parks the game's own cursor on the place the monster stands in (the hat's "in
X's place"), shows its nodes and hides nothing of the game's, so the game's timer, its pick, its intro and its
battle bookkeeping stay the game's. A new monster's battle is that place's battle (PAD-706): available when the
place is, won or lost as it.

A monster's picture is the person's (``monster.png`` in its mode's folder); nothing of a manufacturer's is drawn
here - the frames, greys and lettering are taken from the card the build is for."""
from __future__ import annotations

import colorsys
import os
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import dds as _dds
from . import scene_tree as T

SCENE_ID = "cac32730af42b9d26d26c4bb6e667b07da53113e"
REL = "assets/lcd/auto_loaded/%s/scene.radium" % SCENE_ID
#: the seven places' node names, by slot (the program's table order: Ebirah, Titanosaurus, Gigan, Megalon,
#: King Ghidorah, Megalon & Gigan, King Ghidorah & Gigan - a Heisei card keeps the names under its own art)
SLOT_NODES = ("Ebirah", "Titan", "Gigan", "Megalon", "Ghidorah", "MegalonGigan", "GhidorahGigan")
#: each place's state box (lock / claw / city) and its "n/m" words, by slot
ARTBOX = ("T1_1", "T1_2", "T1_3", "T1_4", "T2_1", "T2_2", "T2_3")
OVERLAY, CHARS = "SelectOverlay_Textbox", "CharacterSelect_Instance"
#: the runtime's paths to the nodes (the scene lookup takes the path from the root, dotted)
PATH = OVERLAY + "." + CHARS + "."
#: how many new monsters the screen takes (two columns of six)
MAX_NEW = 5
#: the glass line the tiles stay above (the screen's frame starts below it)
BOTTOM = 690.0
PREFIX = "PadSel_"
PARTS = ("Gray", "Lit", "Lock", "Done", "Portrait")
#: a few names in katakana, lettered under a new monster's name as the game letters its own (any other: none)
KATAKANA = {
    "MOTHRA": "モスラ", "RODAN": "ラドン", "ANGUIRUS": "アンギラス", "KUMONGA": "クモンガ",
    "KAMACURAS": "カマキラス", "KIRYU": "機龍", "KING CAESAR": "キングシーサー", "MINILLA": "ミニラ",
    "MECHAGODZILLA": "メカゴジラ", "BARAGON": "バラゴン", "MANDA": "マンダ", "HEDORAH": "ヘドラ",
    "ORGA": "オルガ", "ZILLA": "ジラ", "EBIRAH": "エビラ", "VARAN": "バラン", "BATTRA": "バトラ",
    "JET JAGUAR": "ジェットジャガー", "GOROSAURUS": "ゴロザウルス", "GABARA": "ガバラ",
    "MEGALON": "メガロン", "GIGAN": "ガイガン", "BIOLLANTE": "ビオランテ", "DESTOROYAH": "デストロイア",
    "SPACEGODZILLA": "スペースゴジラ", "MEGAGUIRUS": "メガギラス", "KING GHIDORAH": "キングギドラ",
    "TITANOSAURUS": "チタノザウルス", "KUMASI": "クマソ", "GODZILLA JUNIOR": "ゴジラジュニア",
    "MONSTER X": "モンスターX", "KEIZER GHIDORAH": "カイザーギドラ", "MOGUERA": "モゲラ",
}
NAME_FONTS = (r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\ariblk.ttf", r"C:\Windows\Fonts\arialbd.ttf",
              "/System/Library/Fonts/Supplemental/Impact.ttf", "/System/Library/Fonts/Supplemental/Arial Black.ttf",
              "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
KANA_FONTS = (r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\msgothic.ttc", r"C:\Windows\Fonts\meiryob.ttc",
              "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc")


class BattleSelectError(ValueError):
    """A selection screen this build cannot lay out (a card whose scene is not the one measured, too many monsters)."""


def node_names(slug):
    """A new monster's nodes in the scene, by part (the runtime adds ``PATH`` in front)."""
    return {p: "%s_%s" % (page_of(slug), p) for p in PARTS}


def page_of(slug):
    """What the mode file and the blocks' C name a new monster by: its nodes' stem (``PadSel_<slug>``)."""
    return PREFIX + re.sub(r"[^A-Za-z0-9]", "_", str(slug))


def cover_name(slot):
    return "%sCover%d" % (PREFIX, slot)


def prog_name(slug):
    """PAD-733: a new monster's count on its tile ("2/5"), a text in the overlay beside the places' own "0/4" - the
    runtime writes the count its mode reports (``pm_roster_more_progress``)."""
    return page_of(slug) + "_Prog"


def katakana(name):
    return KATAKANA.get(" ".join(str(name or "").upper().split()), "")


# ---- affine transforms: (a, b, c, d, tx, ty) with x' = a x + c y + tx, y' = b x + d y + ty ------------------------
def m6(m16):
    return (m16[0], m16[1], m16[4], m16[5], m16[12], m16[13])


def with6(m16, m):
    out = list(m16)
    out[0], out[1], out[4], out[5], out[12], out[13] = m
    return out


IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mul(p, q):
    """p after q."""
    a, b, c, d, tx, ty = p
    e, f, g, h, ux, uy = q
    return (a * e + c * f, b * e + d * f, a * g + c * h, b * g + d * h, a * ux + c * uy + tx, b * ux + d * uy + ty)


def inv(p):
    a, b, c, d, tx, ty = p
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise BattleSelectError("a node of the screen is scaled to nothing")
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(ia * tx + ic * ty), -(ib * tx + id_ * ty))


def move(tx, ty):
    return (1.0, 0.0, 0.0, 1.0, float(tx), float(ty))


def scale(k):
    return (float(k), 0.0, 0.0, float(k), 0.0, 0.0)


def apply(p, x, y):
    a, b, c, d, tx, ty = p
    return a * x + c * y + tx, b * x + d * y + ty


def rest(node):
    """The node's matrix as the screen rests (its last track; none = where it is)."""
    return m6(node.tracks[-1][1]) if node.tracks else IDENT


def track16(m):
    return with6([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], m)


def retrack(node, a):
    """Every track of ``node`` put after ``a`` (the node moves as ``a`` moves its parent's space)."""
    node.tracks = [(f, with6(m, mul(a, m6(m)))) for f, m in (node.tracks or [(1, track16(IDENT))])]


# ---- pictures --------------------------------------------------------------------------------------------------
def texture_rgba(scene, tid):
    """A texture's pixels, as the card holds them (premultiplied RGBA, uint8, its own size)."""
    t = scene.textures[tid]
    pw, ph = (t["w"] + 3) // 4 * 4, (t["h"] + 3) // 4 * 4
    if t["fmt"] == 5:
        px = _dds.decode_bc3(t["blob"], pw, ph)
    elif t["fmt"] == 4:
        px = _dds.decode_bc1(t["blob"], pw, ph)
    else:
        raise BattleSelectError("a picture of the screen is in format %d, not one this build reads" % t["fmt"])
    return np.ascontiguousarray(px[:t["h"], :t["w"]])


def bitmap_of(node):
    for c in node.components:
        if c.obj.kind == "Bitmap":
            return c.obj
    return None


def sprite_of(node):
    for c in node.components:
        if c.obj.kind == "Sprite":
            return c.obj
    return None


def warp(src, m, size):
    """``src`` (premultiplied RGBA array) drawn through ``m`` (source pixels -> output pixels) onto a clear
    ``size`` canvas."""
    w, h = size
    a, b, c, d, tx, ty = inv(m)
    img = Image.fromarray(src, "RGBA")
    out = img.transform((int(w), int(h)), Image.AFFINE, (a, c, tx, b, d, ty), Image.BILINEAR)
    return np.asarray(out)


def over(dst, src):
    """premultiplied ``src`` over ``dst`` (float arrays 0-1)"""
    return src + dst * (1.0 - src[..., 3:4])


def premultiply(img):
    arr = np.asarray(img.convert("RGBA")).astype(np.float32)
    arr[..., :3] *= arr[..., 3:4] / 255.0
    return (arr + 0.5).clip(0, 255).astype(np.uint8)


def new_texture(scene, alloc, px):
    """A texture of ``px`` (premultiplied RGBA uint8) in the scene, as the card's own are (BC3)."""
    h, w = px.shape[:2]
    pw, ph = (w + 3) // 4 * 4, (h + 3) // 4 * 4
    pad = np.zeros((ph, pw, 4), np.uint8)
    pad[:h, :w] = px
    tid = alloc()
    scene.textures[tid] = dict(w=w, h=h, fmt=5, name="", blob=_dds.encode_bc3(pad), data_off=None)
    return tid


# ---- the screen as the card has it -----------------------------------------------------------------------------
class Screen:
    """The selection scene's parts this build works on, found by name (the program finds them so too)."""

    def __init__(self, scene):
        self.scene = scene
        roots = {n.name: n for n in scene.root["kids"]}
        self.overlay = roots.get(OVERLAY)
        if self.overlay is None or sprite_of(self.overlay) is None:
            raise BattleSelectError("the card's selection screen has no %s - not the scene this build knows" % OVERLAY)
        okids = sprite_of(self.overlay).body["kids"]
        self.overlay_kids = okids
        byname = {n.name: n for n in okids}
        self.chars = byname.get(CHARS)
        if self.chars is None or sprite_of(self.chars) is None:
            raise BattleSelectError("the card's selection screen has no %s" % CHARS)
        self.kids = sprite_of(self.chars).body["kids"]
        ck = {n.name: n for n in self.kids}
        self.selected, self.body, self.art, self.prog = [], [], [], []
        for s, n in enumerate(SLOT_NODES):
            sel, body = ck.get(n + "_Selected_instance"), ck.get(n + "FullBody_instance")
            if sel is None or body is None:
                raise BattleSelectError("the card's selection screen has no %s place (%s)" % (n, s))
            self.selected.append(sel)
            self.body.append(body)
            self.art.append(byname.get(ARTBOX[s] + "_Artbox"))
            self.prog.append(byname.get(ARTBOX[s] + "Prog_Instance"))
        if any(a is None for a in self.art):
            raise BattleSelectError("the card's selection screen is missing a place's state box")
        sheets = [n for n in self.kids if bitmap_of(n) is not None and not n.name.startswith("PAD_")
                  and not n.name.startswith(PREFIX)]
        if not sheets:
            raise BattleSelectError("the card's selection screen has no gray tiles")
        self.sheet = max(sheets, key=lambda n: bitmap_of(n).body["w"] * bitmap_of(n).body["h"])
        if any(n.name.startswith(PREFIX) for n in self.kids):
            raise BattleSelectError("the card's selection screen already carries new monsters (a card built before: "
                                    "build from the stock card)")
        self.cs = rest(self.chars)                       # CharacterSelect space -> overlay space
        self.os = rest(self.overlay)                     # overlay space -> the glass
        self.glass = mul(self.os, self.cs)               # CharacterSelect space -> the glass
        # each place's lit tile: the picture, and where its pixels land in CharacterSelect space
        self.tile, self.tile_at = [], []
        for sel in self.selected:
            kid = sprite_of(sel).body["kids"][0]
            bm = bitmap_of(kid)
            self.tile.append(texture_rgba(scene, bm.body["tex"]))
            self.tile_at.append(mul(rest(sel), rest(kid)))
        self.sheet_px = texture_rgba(scene, bitmap_of(self.sheet).body["tex"])
        self.sheet_at = rest(self.sheet)

    def origin(self, s):
        return apply(self.tile_at[s], 0, 0)

    def grey(self, s):
        """Place ``s``'s grey tile cut out of the sheet, in its lit tile's pixels: the sheet under the lit tile's
        outline (its glow too), less the other tiles' bodies where the glows overlap them."""
        w, h = self.tile[s].shape[1], self.tile[s].shape[0]
        to_tile = mul(inv(self.tile_at[s]), self.sheet_at)            # sheet pixels -> tile s pixels
        cut = warp(self.sheet_px, to_tile, (w, h)).astype(np.float32)
        own = self.tile[s][..., 3].astype(np.float32) / 255.0
        others = np.zeros((h, w), bool)
        for t in range(len(SLOT_NODES)):
            if t == s:
                continue
            body = warp(self.tile[t], mul(inv(self.tile_at[s]), self.tile_at[t]), (w, h))[..., 3] > 200
            others |= body
        keep = np.where(own > 200 / 255.0, 1.0, own * ~others)
        return (cut * keep[..., None] + 0.5).clip(0, 255).astype(np.uint8)


# ---- the layout ------------------------------------------------------------------------------------------------
def groups(slots):
    """The screen's places in GROUPS, one per game place: the place, then the new monsters booked against it (``slots``:
    each new monster's place, in the list's order) - David: "pick A | B, C | D, E, F", the tiles that book the same
    battle together. A group is ``[slot, ("new", i), ...]``."""
    return [[s] + [("new", i) for i, h in enumerate(slots) if int(h) == s] for s in range(7)]


def columns(slots):
    """The two columns, each a list of groups top to bottom: the groups in their places' order, split between them where
    the taller column is shortest (no group is split; a tie keeps the game's own four and three)."""
    gs = groups(slots)
    size = [len(g) for g in gs]

    def tall(c):
        return max(sum(size[:c]), sum(size[c:]))
    best = min(range(1, 7), key=lambda c: (tall(c), abs(c - 4)))
    return gs[:best], gs[best:]


def walk(slots):
    """The cursor's order over the places (the right flipper goes on, the left back): every group in its place's order -
    the game's own 0-6, each followed by the new monsters booked against it (the runtime's more_walk)."""
    return [key for g in groups(slots) for key in g]


#: the gap between two groups when either holds a new monster, in pitches
GROUP_GAP = 0.3


def _column(gs, pitch):
    """``[(key, y)]`` down one column (y from its first tile, unscaled) and its height to the last tile's top."""
    out, y, last = [], 0.0, None
    for g in gs:
        if last is not None and (len(g) > 1 or len(last) > 1):
            y += GROUP_GAP * pitch
        for key in g:
            out.append((key, y))
            y += pitch
        last = g
    return out, (y - pitch if out else 0.0)


def layout(sc, slots):
    """Each place's tile origin in CharacterSelect space and the tiles' scale: ``({place: (x, y)}, k)``."""
    o = [sc.origin(s) for s in range(7)]
    th = float(sc.tile[0].shape[0])
    tw = float(sc.tile[0].shape[1])
    if not slots:
        return {s: o[s] for s in range(7)}, 1.0
    top = o[0][1]
    bottom = (BOTTOM - sc.glass[5]) / sc.glass[3]                 # the glass line in CharacterSelect space
    bottom = max(bottom, o[3][1] + th)
    p_left = (o[3][1] - o[0][1]) / 3.0
    p_right = (o[6][1] - o[4][1]) / 2.0
    stagger = o[4][1] - o[0][1]
    left, right = columns(slots)
    lcol, lh = _column(left, p_left)
    rcol, rh = _column(right, p_right)
    off = stagger if rh + p_right <= lh else stagger * 0.55      # the right column starts lower, as the game's does
    need = max(lh + th, off + rh + th)
    k = min(1.0, (bottom - top) / need)
    y0 = top + ((bottom - top) - need * k) / 2.0
    block = (o[4][0] + tw) - o[0][0]
    x_left = o[0][0] + block * (1.0 - k) / 2.0
    x_right = x_left + (o[4][0] - o[0][0]) * k
    at = {}
    for key, y in lcol:
        at[key] = (x_left, y0 + y * k)
    for key, y in rcol:
        at[key] = (x_right, y0 + off * k + y * k)
    return at, k


# ---- a new monster's pictures ----------------------------------------------------------------------------------
def inner_mask(alpha, grow):
    m = Image.fromarray(((alpha >= 250) * 255).astype(np.uint8), "L").filter(ImageFilter.MinFilter(2 * grow + 1))
    return np.asarray(m) == 255


def _picture(path, name, w, h, hue):
    if path:
        try:
            return Image.open(path).convert("RGB")
        except OSError:
            pass
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    r, g, b = hue
    for y in range(h):
        q = (y / max(1, h - 1)) ** 1.6
        d.line((0, y, w, y), fill=(int(r * q * 0.8), int(g * q * 0.8), int(b * q * 0.8)))
    f = _font(NAME_FONTS, max(10, h // 6))
    tw = d.textlength(name, font=f)
    while tw > w * 0.9 and f.size > 10:
        f = _font(NAME_FONTS, f.size - 4)
        tw = d.textlength(name, font=f)
    d.text(((w - tw) / 2, h * 0.42), name, font=f, fill=(255, 255, 255), stroke_width=max(1, f.size // 14),
           stroke_fill=(0, 0, 0))
    return img


def _hue(i):
    r, g, b = colorsys.hsv_to_rgb((0.02 + i * 0.137) % 1.0, 0.85, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def _font(paths, size):
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, int(size))
            except OSError:
                continue
    return ImageFont.load_default()


def _cover(pic, w, h, centre_y=0.5):
    """``pic`` scaled to cover w x h, cut to it about the point (middle, centre_y of its height)."""
    k = max(w / pic.width, h / pic.height)
    pw, ph = max(w, int(round(pic.width * k))), max(h, int(round(pic.height * k)))
    pic = pic.resize((pw, ph), Image.LANCZOS)
    x = (pw - w) // 2
    y = int(round(min(max(0, ph * centre_y - h / 2.0), ph - h)))
    return pic.crop((x, y, x + w, y + h))


def framed(template, pic, grow, centre_y):
    """The ``template`` (a frame of the card's, premultiplied) with ``pic`` in the place of its own picture: the
    template's opaque inside, ``grow`` px in from its edge, takes the picture; a slanted tile's picture is slanted
    with it (each column moved as the inside's top edge falls)."""
    h, w = template.shape[:2]
    inside = inner_mask(template[..., 3], grow)
    ys, xs = np.nonzero(inside)
    if not len(xs):
        raise BattleSelectError("a frame of the selection screen has no inside to put a picture in")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    cols = np.arange(x0, x1)
    tops = np.array([ys[xs == x].min() if (xs == x).any() else 0 for x in cols], np.float32)
    bots = np.array([ys[xs == x].max() if (xs == x).any() else 0 for x in cols], np.float32)
    slope = float(np.polyfit(cols, tops, 1)[0]) if len(cols) > 2 else 0.0
    height = int(round(float(np.median(bots - tops)))) + 1
    y_top = float(np.polyfit(cols, tops, 1)[1]) + slope * x0 if len(cols) > 2 else float(tops.min())
    flat = _cover(pic, x1 - x0, height, centre_y)
    # the flat picture into the slant: picture (u, v) -> tile (x0 + u, y_top + v + slope * u)
    m = (1.0, slope, 0.0, 1.0, float(x0), y_top)
    slanted = warp(np.asarray(flat.convert("RGBA")), m, (w, h))
    out = template.copy()
    out[inside] = slanted[inside]
    out[inside, 3] = 255
    return out


def grey_like(sc, colour, slot=0):
    """A new tile's grey: the place ``slot``'s grey tile, its inside the new colour tile's in the card's own grey -
    the grey's light fitted to the colour tile's on that place (least squares), so a Heisei card's hard black and
    white and a stock card's soft grey both come out as the card draws its own."""
    g0 = sc.grey(slot).astype(np.float32)
    c0 = sc.tile[slot].astype(np.float32)
    inside = inner_mask(sc.tile[slot][..., 3], 5)
    lum = lambda a: a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    x, y = lum(c0)[inside], lum(g0)[inside]
    a, b = np.polyfit(x, y, 1) if len(x) > 16 and float(np.std(x)) > 1.0 else (0.8, 0.0)
    out = g0.copy()
    ins = inner_mask(colour[..., 3], 5)
    v = np.clip(lum(colour.astype(np.float32)) * a + b, 0, 255)
    for ch in range(3):
        out[..., ch][ins] = v[ins]
    out[..., 3][ins] = 255
    return (out + 0.5).clip(0, 255).astype(np.uint8)


def name_art(name, kana, w=2048, h=683):
    """A new monster's name lettered as the Heisei card letters its monsters (orange to red, a dark edge, the
    katakana below in cream): ``w`` x ``h`` premultiplied RGBA."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    f = _font(NAME_FONTS, 330)
    d = ImageDraw.Draw(img)
    while d.textlength(name, font=f) > w * 0.94 and f.size > 60:
        f = _font(NAME_FONTS, f.size - 10)
    tw = d.textlength(name, font=f)
    bb = d.textbbox((0, 0), name, font=f)
    tx, ty = (w - tw) / 2.0, 30 - bb[1]
    edge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(edge).text((tx, ty), name, font=f, fill=(40, 6, 0, 255), stroke_width=max(6, f.size // 18),
                              stroke_fill=(25, 4, 0, 255))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((tx, ty), name, font=f, fill=255)
    top, bot = ty + bb[1], ty + bb[3]
    yy = np.linspace(0, h - 1, h)[:, None]
    q = np.clip((yy - top) / max(1.0, bot - top), 0, 1)
    grad = np.zeros((h, w, 4), np.float32)
    grad[..., 0] = 255
    grad[..., 1] = np.clip(236 - 190 * q ** 1.2, 0, 255)
    grad[..., 2] = np.clip(120 - 120 * q ** 0.6, 0, 255)
    grad[..., 3] = 255
    fill = Image.fromarray(grad.astype(np.uint8), "RGBA")
    shine = Image.new("RGBA", (w, h), (255, 255, 230, 0))
    hi = Image.new("L", (w, h), 0)
    ImageDraw.Draw(hi).text((tx, ty - max(3, f.size // 40)), name, font=f, fill=90)
    hi = Image.fromarray((np.asarray(hi).astype(np.float32) * (np.asarray(mask) > 0) * (q[:, :1].repeat(w, 1) < 0.35))
                         .astype(np.uint8), "L")
    shine.putalpha(hi)
    out = Image.alpha_composite(edge, Image.composite(fill, Image.new("RGBA", (w, h), (0, 0, 0, 0)), mask))
    out = Image.alpha_composite(out, shine)
    if kana:
        kf = _font(KANA_FONTS, int(h * 0.30))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        kw = ld.textlength(kana, font=kf)
        kx, ky = min(w - kw - 40, tx + tw - kw), bot + 10
        ld.text((kx, ky), kana, font=kf, fill=(255, 244, 222, 255), stroke_width=max(4, kf.size // 10),
                stroke_fill=(20, 8, 0, 255))
        layer = layer.rotate(7, resample=Image.BICUBIC, center=(kx + kw / 2.0, ky + kf.size / 2.0))
        out = Image.alpha_composite(out, layer)
    return premultiply(out)


# ---- the build -------------------------------------------------------------------------------------------------
def check(monsters):
    """Why these new monsters cannot go on the screen (sentences; empty = fine). ``monsters``: ``[{"slug", "name",
    "slot", "picture"}]``."""
    out = []
    if len(monsters) > MAX_NEW:
        out.append("The battle selection screen takes at most %d new monsters (%d are on it)." % (MAX_NEW, len(monsters)))
    for m in monsters:
        if not 0 <= int(m.get("slot", -1)) < 7:
            out.append("%s stands in no battle's place on the selection screen." % m.get("name", m.get("slug")))
    slugs = [m["slug"] for m in monsters]
    if len(set(slugs)) != len(slugs):
        out.append("A new monster is on the selection screen twice.")
    return out


def order(monsters):
    """The new monsters in the screen's order - their names (case aside), then their folders: the runtime keeps the
    list so whatever order the modes join in (pad_mode_runtime.c ``more_before``)."""
    return sorted(monsters, key=lambda m: (str(m["name"]).upper(), page_of(m["slug"])))


def build(stock, monsters):
    """The card's selection scene (``stock`` bytes) with ``monsters`` on it. Returns the new bytes. Raises
    :class:`BattleSelectError`."""
    why = check(monsters)
    if why:
        raise BattleSelectError(" ".join(why))
    monsters = order(monsters)
    if not monsters:
        return stock
    scene = T.parse(stock)
    sc = Screen(scene)
    ids = [max([0] + [n.id for n, _p, _d in scene.walk(library=True)] + list(scene.objects) + list(scene.textures)
               + list(scene.clips) + list(scene.assets) + list(scene.markers)) + 1]

    def alloc():
        v = ids[0]
        ids[0] += 1
        return v
    cls_bitmap, cls_sprite = scene.class_id("Bitmap"), scene.class_id("Sprite")
    sym_bitmap = bitmap_of(sc.sheet).body["sym"]
    sym_sprite = sprite_of(sc.chars).body["sym"]

    def picture_node(name, px, m, visible=True):
        tid = new_texture(scene, alloc, px)
        h, w = px.shape[:2]
        obj = T.Obj(alloc(), "Bitmap", dict(sym=sym_bitmap, name="", w=w, h=h, tex=tid))
        scene.objects[obj.id] = obj
        return T.Node(alloc(), name, 1, [(1, 1 if visible else 0)], [], [(1, track16(m))],
                      [T.Component(1, cls_bitmap, obj)])

    def shown_node(name, px, m):
        """a picture the runtime shows and hides: in a group of its own - the game's node lookup finds Sprites only
        (emulator, PAD-707 run7: bare Bitmap nodes were never found, so every one stayed on the glass)"""
        return group_node(name, [picture_node(name + "_Art", px, IDENT)], m)

    def group_node(name, kids, m):
        obj = T.Obj(alloc(), "Sprite", dict(sym=sym_sprite, name="", frames=1, kids=kids, labels=[]))
        scene.objects[obj.id] = obj
        return T.Node(alloc(), name, 1, [(1, 1)], [], [(1, track16(m))], [T.Component(1, cls_sprite, obj)])

    at, k = layout(sc, [int(m["slot"]) for m in monsters])
    place = lambda key: mul(move(*at[key]), scale(k))               # tile pixels -> CharacterSelect space
    greys = [sc.grey(s) for s in range(7)]
    # the padlock and the claw as they sit on place 4's tile - read BEFORE the places move: read after, the box had moved
    # and the tile it was measured against had not, and each new tile's claw sat a tile lower (David, v21: "one was way
    # too low")
    lock_px, done_px, lock_m, done_m = _state_pictures(scene, sc)
    prog_t, prog_m = _prog_template(sc)                              # PAD-733: the places' "0/4", read before they move
    # the seven places: lit tile, state box and words moved with the tile
    for s in range(7):
        a = mul(place(s), inv(sc.tile_at[s]))                        # CharacterSelect space, old -> new
        retrack(sc.selected[s], a)
        a_overlay = mul(mul(sc.cs, a), inv(sc.cs))                   # the same, in the overlay's space
        retrack(sc.art[s], a_overlay)
        if sc.prog[s] is not None:
            retrack(sc.prog[s], a_overlay)
    # the grey tiles, each on its own, where the sheet was (under the lit ones)
    sc.sheet.keyframes = [(f, 0) for f, _v in sc.sheet.keyframes]
    at_sheet = sc.kids.index(sc.sheet) + 1
    new_kids = [picture_node("%sGray%d" % (PREFIX, s), greys[s], place(s)) for s in range(7)]
    # the new monsters' tiles
    lits, covers, portraits, progs = [], [], [], []
    hosts = sorted({int(m["slot"]) for m in monsters})
    for i, m in enumerate(monsters):
        key = ("new", i)
        names = node_names(m["slug"])
        pic = _picture(m.get("picture"), m["name"], 632, 828, _hue(i))
        colour = framed(sc.tile[0], pic, 5, 0.34)
        new_kids.append(picture_node(names["Gray"], grey_like(sc, colour), place(key)))
        lits.append(shown_node(names["Lit"], colour, place(key)))
        # the padlock and the claw sit on a new tile as on place 4's (the right column's first): their pixels -> place
        # 4's tile pixels (lock_m, done_m) -> this tile's place
        if lock_px is not None:
            lits.append(shown_node(names["Lock"], lock_px, mul(place(key), lock_m)))
        if done_px is not None:
            lits.append(shown_node(names["Done"], done_px, mul(place(key), done_m)))
        portraits.append(_portrait_group(sc, scene, m, pic, picture_node, group_node, names["Portrait"]))
        if prog_t is not None:
            # PAD-733: its count, a copy of place 0's words placed on this tile as place 0's sits on its own; blank
            # until the runtime writes the mode's count (pm_roster_more_progress)
            body = dict(prog_t.components[0].obj.body, text=b" ")
            obj = T.Obj(alloc(), "Text", body)
            scene.objects[obj.id] = obj
            progs.append(T.Node(alloc(), prog_name(m["slug"]), prog_t.flag, [(1, 1)], [],
                                [(1, track16(mul(sc.cs, mul(place(key), prog_m))))],
                                [T.Component(prog_t.components[0].start, prog_t.components[0].cls, obj)]))
    for s in hosts:
        covers.append(shown_node(cover_name(s), greys[s], place(s)))
    sc.kids[at_sheet:at_sheet] = new_kids
    last_body = max(sc.kids.index(b) for b in sc.body)
    sc.kids[last_body + 1:last_body + 1] = portraits
    last_sel = max(sc.kids.index(n) for n in sc.selected)
    sc.kids[last_sel + 1:last_sel + 1] = covers + lits
    if progs:                                                        # beside the places' own, in the overlay
        at_prog = sc.overlay_kids.index(prog_t)
        sc.overlay_kids[at_prog:at_prog] = progs
    return T.serialize(scene)


def _prog_template(sc):
    """PAD-733: place 0's count words (``T1_1Prog_Instance``, a text in the overlay the program writes "0/4" into) and
    where it sits in place 0's TILE pixels: ``(node, m)``, or ``(None, None)`` on a card without it (a text node)."""
    for s, node in enumerate(sc.prog):
        if node is not None and node.components and node.components[0].obj.kind == "Text":
            # the overlay's space -> CharacterSelect -> the tile's pixels
            return node, mul(inv(sc.tile_at[s]), mul(inv(sc.cs), rest(node)))
    return None, None


def _state_pictures(scene, sc):
    """The padlock and the claw of place 4's state box (its frames 1 and 2), and where each sits in place 4's TILE
    pixels: ``(lock px, claw px, lock m, claw m)`` (None when the box has no such picture)."""
    box = sc.art[4]
    kids = sprite_of(box).body["kids"]
    out = []
    # the box's space -> tile 4's pixels: overlay -> CharacterSelect -> the tile
    to_tile = mul(inv(sc.tile_at[4]), mul(inv(sc.cs), rest(box)))
    for kid in kids[:2]:
        bm = bitmap_of(kid)
        if bm is None:
            out.append((None, None))
            continue
        out.append((texture_rgba(scene, bm.body["tex"]), mul(to_tile, rest(kid))))
    while len(out) < 2:
        out.append((None, None))
    (lock, lock_m), (done, done_m) = out
    return lock, done, lock_m, done_m


def _portrait_group(sc, scene, m, pic, picture_node, group_node, name):
    """A new monster's portrait: a group placed as place 0's (``EbirahFullBody``), its frame with the monster's
    picture in it, and its name lettered where the place's name is."""
    body = sc.body[0]
    kids = sprite_of(body).body["kids"]
    frame = max((n for n in kids if bitmap_of(n) is not None and not n.name.startswith("PAD_")),
                key=lambda n: bitmap_of(n).body["w"] * bitmap_of(n).body["h"])
    template = texture_rgba(scene, bitmap_of(frame).body["tex"])
    portrait = framed(template, pic, 12, 0.45)
    parts = [picture_node(name + "_Art", portrait, rest(frame))]
    art = name_art(str(m["name"]).upper(), m.get("kana", katakana(m["name"])))
    box = name_box(scene, kids, frame)
    ink = ink_box(art)
    # the lettering's ink fitted to the place's own name: as tall, no wider than a fifth more, centred on it
    s = (box[3] - box[1]) / float(ink[3] - ink[1])
    s = min(s, 1.2 * (box[2] - box[0]) / float(ink[2] - ink[0]))
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    ox, oy = (ink[0] + ink[2]) / 2.0, (ink[1] + ink[3]) / 2.0
    parts.append(picture_node(name + "_Name", art, (s, 0.0, 0.0, s, cx - s * ox, cy - s * oy)))
    return group_node(name, parts, rest(body))


def ink_box(px, at=24):
    """The box of ``px``'s pixels more than ``at`` opaque: (x0, y0, x1, y1)."""
    ys, xs = np.nonzero(px[..., 3] > at)
    if not len(xs):
        return 0, 0, px.shape[1], px.shape[0]
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def name_box(scene, kids, frame):
    """Where place 0's name is drawn in its portrait group's space: the Heisei card's lettered picture's ink
    (``PAD_<NAME>4a``), else the stock card's line of words and its katakana banner together."""
    boxes = []
    for n in kids:
        if n is frame:
            continue
        bm = bitmap_of(n)
        if bm is not None:
            px = texture_rgba(scene, bm.body["tex"])
            x0, y0, x1, y1 = ink_box(px)
            corners = [apply(rest(n), x, y) for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
        else:
            text = next((c.obj for c in n.components if c.obj.kind == "Text"), None)
            if text is None:
                continue
            l, t, r, b = text.body["rect"]
            corners = [apply(rest(n), x, y) for x, y in ((l, t), (r, t), (l, b), (r, b))]
        boxes.append(corners)
        if n.name.startswith("PAD_"):        # the Heisei card's own lettering is the whole name: that alone
            boxes = [corners]
            break
    if not boxes:
        return 0.0, -460.0, 330.0, -300.0
    xs = [x for c in boxes for x, _y in c]
    ys = [y for c in boxes for _x, y in c]
    return min(xs), min(ys), max(xs), max(ys)


# ---- a picture of the screen, for the person (and the tests) -----------------------------------------------------
def preview(data, cursor=0, monsters=(), size=(1360, 768)):
    """A still of the (built) selection screen as it rests with the cursor on ``cursor`` (a slot, or a new monster's
    slug): the map, the title, the tiles, the portrait and name. The words of the screen are not drawn (the game
    letters them in its own font). Returns an RGB PIL image."""
    scene = T.parse(data)
    canvas = np.zeros((size[1], size[0], 4), np.float32)
    roots = {n.name: n for n in scene.root["kids"]}
    host = cursor
    if isinstance(cursor, str):
        host = next((int(m["slot"]) for m in monsters if m["slug"] == cursor), 0)

    def draw(node, m):
        nonlocal canvas
        if node.keyframes and node.keyframes[-1][1] == 0 and len(node.keyframes) == 1:
            return
        bm = bitmap_of(node)
        if bm is not None:
            px = texture_rgba(scene, bm.body["tex"])
            canvas = over(canvas, warp(px, m, size).astype(np.float32) / 255.0)
        for c in node.components:
            if c.obj.kind == "Shape" and c.obj.body.get("bitmap") is not None:
                b = c.obj.body
                px = texture_rgba(scene, b["bitmap"].body["tex"])
                rx, ry, rw, rh = b["rect"]
                sm = (rw / px.shape[1], 0.0, 0.0, rh / px.shape[0], rx, ry)
                canvas = over(canvas, warp(px, mul(m, sm), size).astype(np.float32) / 255.0)

    def walk_kids(kids, m, depth=0):
        for n in kids:
            name = n.name
            if name.startswith(PREFIX):
                part = name.rsplit("_", 1)[-1]
                own = isinstance(cursor, str) and name.startswith(PREFIX + cursor + "_")
                if part in ("Lit", "Portrait") and not own:
                    continue
                if part in ("Lock", "Done"):
                    continue
                if name.startswith(PREFIX + "Cover") and not (isinstance(cursor, str) and name.startswith(cover_name(host))):
                    continue
            if name.endswith("_Selected_instance") or name.endswith("FullBody_instance"):
                stem = name[:-len("_Selected_instance")] if name.endswith("_Selected_instance") else name[:-len("FullBody_instance")]
                if stem not in SLOT_NODES or SLOT_NODES.index(stem) != host:
                    continue
                if name.endswith("FullBody_instance") and isinstance(cursor, str):
                    continue                          # the runtime hides the place's portrait under a new monster's
            if name.endswith("_Artbox") or name.endswith("Prog_Instance") or name.startswith("Line"):
                continue
            nm = mul(m, rest(n))
            # the screen at rest: a node whose own timeline hides it all the time is not drawn
            if all(v == 0 for _f, v in n.keyframes) and not name.endswith("FullBody_instance") \
                    and not name.endswith("_Selected_instance"):
                continue
            draw(n, nm)
            sp = sprite_of(n)
            if sp is not None:
                walk_kids(sp.body["kids"], nm, depth + 1)
    bg = scene.root["kids"][0]
    # the map as the screen holds it while it waits for the pick (its zoom at frame 150)
    tr = [m for f, m in bg.tracks if f <= 150]
    walk_kids([T.Node(bg.id, bg.name, bg.flag, [(1, 1)], [], [(1, (tr[-1] if tr else bg.tracks[-1][1]))],
                      bg.components)], IDENT)
    walk_kids([roots[OVERLAY]], IDENT)
    rgb = canvas[..., :3] + (1.0 - canvas[..., 3:4]) * 0.0
    return Image.fromarray((rgb.clip(0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
