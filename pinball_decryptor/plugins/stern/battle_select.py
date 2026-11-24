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
here - the frames, greys and lettering are taken from the card the build is for.

PAD-1551: A CARD THAT DRAWS THE SCREEN ANOTHER WAY. Heisei V2.3 laid the screen out again: the seven places are
DIAMONDS on a checkerboard (one, two, one, two, one) and each place's portrait is ONE picture of two cards side by
side - the monster's picture card, its name and katakana lettered on it, and a facts card (BIO, POWERS, HEIGHT,
WEIGHT) with the screen's two lines of help drawn into it. Laid out as two columns, that screen came out as a pile of
tiles down the left edge with each new monster's picture over both cards (emulator, PAD-1551). Such a card is told by
where its places sit (:func:`lattice_of`) and gets a layout of its own kind:

* the places and the new monsters go on the card's own checkerboard, with more rows and columns and smaller diamonds
  when they must be, the three battles the game keeps locked above the four it opens with, as the card has them
  (:func:`_lattice_layout`);
* what is the card's FRAME and what is a monster's PICTURE is read off the card itself - a pixel most of the seven
  places agree on is the frame's (:func:`consensus`) - so a new diamond is the card's frame round the new picture
  (:func:`tile_window`), and a new portrait is the card's twin cards with the picture in the first, the name and
  katakana lettered on it, and the monster's facts lettered in the second (:func:`twin_cards`,
  :func:`_twin_portrait`; the facts are the person's, ``monster.json`` in the mode's folder)."""
from __future__ import annotations

import colorsys
import os
import re

from ...core.lazy_import import lazy_module

# numpy and PIL load on first use, not with this module (PAD-797): the
# Modes tab imports this chain at startup, on the UI loop.
np = lazy_module("numpy")
Image = lazy_module("PIL.Image")
ImageDraw = lazy_module("PIL.ImageDraw")
ImageFilter = lazy_module("PIL.ImageFilter")
ImageFont = lazy_module("PIL.ImageFont")

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


#: PAD-733: the cities a place's state box stamps on a battle held there, in the game's city order (its state box's
#: labels, frames 3-6; GODZILLA CONTROLS TOKYO, then TRAVEL TO PARIS)
CITY_LABELS = ("Tokyo", "Paris", "London", "NewYork")


def city_name(slug, c):
    """PAD-733: a new monster's stamp for city ``c`` (:data:`CITY_LABELS`): a group in the overlay with the stamp's
    word lettered in it (:func:`stamp_art`), which the runtime shows while a battle of its, lost there, is held by that
    city (as a place's own box stamps it)."""
    return "%s_City%d" % (page_of(slug), c)


def place_lock_name(slot):
    """PAD-733: place ``slot``'s own padlock, shown while a new monster's battle lost there holds the place (the
    place's own box, its city stamp, is the monster's then)."""
    return "%sLock%d" % (PREFIX, slot)


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
        #: PAD-1551: the checkerboard's steps when the places are diamonds on one (Heisei V2.3), else None
        self.lattice = lattice_of(self)
        #: one tile pixel in CharacterSelect space (the two-column screens draw theirs one to one)
        self.unit = float(self.tile_at[0][0]) if self.lattice else 1.0
        self._window = self._twin = None

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


def lattice_of(sc):
    """PAD-1551: ``(sx, sy)``, the checkerboard's steps in CharacterSelect space, when the seven places sit as
    diamonds on one (three columns or more of them: Heisei V2.3's one, two, one, two, one); None for the two
    columns every other card has. A screen that is neither is refused."""
    o = [sc.origin(s) for s in range(7)]
    tw = sc.tile[0].shape[1] * abs(sc.tile_at[0][0])

    def steps(vals):
        vals = sorted(vals)
        return [b - a for a, b in zip(vals, vals[1:]) if b - a > tw * 0.25]
    dx, dy = steps([x for x, _y in o]), steps([y for _x, y in o])
    if len(dx) < 2:
        return None
    sx, sy = min(dx), (min(dy) if dy else 0.0)
    if sy <= 0:
        raise BattleSelectError("the card's selection screen lays its places out in a way this build does not know")
    for x, y in o:
        cx, cy = (x - o[0][0]) / sx, (y - o[0][1]) / sy
        if abs(cx - round(cx)) > 0.2 or abs(cy - round(cy)) > 0.2 or (int(round(cx)) + int(round(cy))) % 2:
            raise BattleSelectError("the card's selection screen lays its places out in a way this build does not "
                                    "know")
    return sx, sy


def _lattice_layout(sc, slots):
    """PAD-1551: :func:`layout` for a screen of diamonds on a checkerboard. The board that holds every tile at the
    biggest size inside the room the card's own seven take (never bigger than the card draws them); its cells are
    filled as a page is read, the battles the game keeps locked (places 4-6, and the new monsters booked against
    them) first - above, where the card has them - then the four it opens with and theirs."""
    sx, sy = sc.lattice
    o = [sc.origin(s) for s in range(7)]
    if not slots:
        return {s: o[s] for s in range(7)}, 1.0
    tw, th = sc.tile[0].shape[1] * sc.unit, sc.tile[0].shape[0] * sc.unit
    x0, y0 = min(x for x, _y in o), min(y for _x, y in o)
    room_w, room_h = max(x for x, _y in o) + tw - x0, max(y for _x, y in o) + th - y0
    n = 7 + len(slots)
    best = None
    for cols in range(2, 10):
        for rows in range(2, 14):
            for par in (0, 1):
                cells = [(r, c) for r in range(rows) for c in range(cols) if (r + c) % 2 == par]
                if len(cells) < n:
                    continue
                k = min(1.0, room_w / ((cols - 1) * sx + tw), room_h / ((rows - 1) * sy + th))
                rank = (round(k, 4), n - len(cells), -(rows * cols), -par)
                if best is None or rank > best[0]:
                    best = (rank, k, cells[:n])
    if best is None:
        raise BattleSelectError("the selection screen has no room for %d tiles" % n)
    _rank, k, cells = best
    c0, c1 = min(c for _r, c in cells), max(c for _r, c in cells)
    r0, r1 = min(r for r, _c in cells), max(r for r, _c in cells)
    left = x0 + (room_w - ((c1 - c0) * sx + tw) * k) / 2.0
    top = y0 + (room_h - ((r1 - r0) * sy + th) * k) / 2.0
    gs = groups(slots)
    keys = [key for g in gs[4:] for key in g] + [key for g in gs[:4] for key in g]
    return {key: (left + (c - c0) * sx * k, top + (r - r0) * sy * k) for key, (r, c) in zip(keys, cells)}, k


def layout(sc, slots):
    """Each place's tile origin in CharacterSelect space and the tiles' scale: ``({place: (x, y)}, k)``."""
    if getattr(sc, "lattice", None):
        return _lattice_layout(sc, slots)
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


def consensus(stack, tol=14, need=5):
    """PAD-1551: what a card's seven pictures of one kind have in common. ``stack``: the pictures on one grid
    (n, h, w, 4). Returns ``(median picture, mask)``: the mask is where at least ``need`` of them are within ``tol``
    of the median - the frame they all wear, as against each one's own picture."""
    med = np.median(stack, axis=0)
    near = (np.abs(stack.astype(np.float32) - med[None]).max(axis=-1) <= tol).sum(axis=0)
    return (med + 0.5).clip(0, 255).astype(np.uint8), near >= need


def _mask_filter(mask, size, grow):
    img = Image.fromarray((mask * 255).astype(np.uint8), "L")
    img = img.filter(ImageFilter.MaxFilter(size) if grow else ImageFilter.MinFilter(size))
    return np.asarray(img) > 127


def tile_window(sc):
    """PAD-1551: where a lit tile shows its monster, in tile pixels - the pixels the seven lit tiles do NOT share
    (their frame is the same on all), closed over the specks where their pictures happen to agree."""
    if sc._window is None:
        h, w = sc.tile[0].shape[:2]
        stack = np.zeros((len(sc.tile), h, w, 4), np.uint8)
        for i, t in enumerate(sc.tile):
            stack[i, :min(h, t.shape[0]), :min(w, t.shape[1])] = t[:h, :w]
        _med, same = consensus(stack, 20, 5)
        win = ~same & ((stack[..., 3] > 250).sum(axis=0) >= len(sc.tile) - 1)
        win = _mask_filter(_mask_filter(win, 3, False), 3, True)              # specks outside the window go
        win = _mask_filter(_mask_filter(win, 15, True), 15, False)            # holes inside it close
        if win.mean() < 0.08:
            raise BattleSelectError("the card's lit tiles show no picture this build can tell from their frame")
        sc._window = win
    return sc._window


def framed_window(template, pic, window, centre_y):
    """PAD-1551: ``template`` (a lit tile of the card's) with ``pic`` in its ``window`` (:func:`tile_window`)."""
    ys, xs = np.nonzero(window)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    flat = np.asarray(_cover(pic, x1 - x0, y1 - y0, centre_y).convert("RGBA"))
    out = template.copy()
    sub = window[y0:y1, x0:x1]
    out[y0:y1, x0:x1][sub] = flat[sub]
    out[..., 3][window] = 255
    return out


#: PAD-1551: the facts card of a twin-card portrait, as parts of the portrait picture (measured on Heisei V2.3's
#: 821 x 588): where the BIO's lines go, the POWERS' (between the card's two emblems), and the HEIGHT and WEIGHT
#: values - (x0, y0, x1, y1)
TWIN_BIO = (0.560, 0.158, 0.958, 0.394)
TWIN_POWERS = (0.662, 0.450, 0.860, 0.592)
TWIN_HEIGHT = (0.570, 0.655, 0.735, 0.722)
TWIN_WEIGHT = (0.778, 0.655, 0.958, 0.722)
#: the picture card's lettering: the name's band (its width and height, and how far its foot is from the card's)
#: and the katakana's column (from the card's left and top, and one letter's height), as parts of the picture card
TWIN_NAME = (0.86, 0.105, 0.040)
TWIN_KANA = (0.075, 0.035, 0.072)
TEXT_FONTS = (r"C:\Windows\Fonts\bahnschrift.ttf", r"C:\Windows\Fonts\ARIALNB.TTF", r"C:\Windows\Fonts\arialbd.ttf",
              "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _text_font(size):
    f = _font(TEXT_FONTS, size)
    try:
        f.set_variation_by_name("Bold SemiCondensed")          # Bahnschrift: the nearest to the card's own letters
    except Exception:                                       # noqa: BLE001 - not a variable font: as it is
        pass
    return f


def twin_cards(sc, scene):
    """PAD-1551: the card's twin-card portrait, read off its seven: ``{"frame", "at", "med", "chrome", "left",
    "right"}`` - place 0's portrait node and its matrix in the portrait group, the seven portraits' median, where
    they agree (the two cards' frames, the facts card's headings, the help lines), and the boxes (x0, y0, x1, y1)
    of the picture card's and the facts card's insides. Raises when the portraits are not two cards."""
    if sc._twin is not None:
        return sc._twin
    found = []
    for s in range(7):
        kids = sprite_of(sc.body[s]).body["kids"]
        pics = [n for n in kids if bitmap_of(n) is not None and not n.name.startswith("PAD_")]
        if not pics:
            raise BattleSelectError("a place of the card's selection screen has no portrait")
        fr = max(pics, key=lambda n: bitmap_of(n).body["w"] * bitmap_of(n).body["h"])
        found.append((fr, texture_rgba(scene, bitmap_of(fr).body["tex"]), mul(rest(sc.body[s]), rest(fr))))
    fr0, px0, m0 = found[0]
    h, w = px0.shape[:2]
    stack = np.stack([px0] + [warp(px, mul(inv(m0), m), (w, h)) for _f, px, m in found[1:]])
    med, same = consensus(stack, 14, 5)
    var = ~same & ((stack[..., 3] > 250).sum(axis=0) >= 6)
    cols = var.mean(axis=0) > 0.3
    runs, start = [], None
    for x in range(w + 1):
        on = x < w and bool(cols[x])
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start > w * 0.2:
                runs.append((start, x))
            start = None
    if len(runs) != 2:
        raise BattleSelectError("the card's portraits are not the picture card and facts card this build knows "
                                "(%d found)" % len(runs))
    boxes = []
    for x0, x1 in runs:
        ys = np.nonzero(var[:, x0:x1].mean(axis=1) > 0.3)[0]
        boxes.append((x0, int(ys.min()), x1, int(ys.max()) + 1))
    sc._twin = dict(frame=fr0, at=rest(fr0), med=med, chrome=same & (med[..., 3] > 128), left=boxes[0],
                    right=boxes[1])
    return sc._twin


def _paste(out, px, x, y):
    """premultiplied ``px`` over ``out`` (uint8, in place) with its corner at (x, y)"""
    h, w = px.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(out.shape[1], x + w), min(out.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    src = px[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    dst = out[y0:y1, x0:x1].astype(np.float32)
    out[y0:y1, x0:x1] = (src + dst * (1.0 - src[..., 3:4] / 255.0) + 0.5).clip(0, 255).astype(np.uint8)


def kana_art(kana, size):
    """A name's katakana lettered down a column, as the Heisei V2.3 card letters its own (orange, a dark edge)."""
    f = _font(KANA_FONTS, size)
    edge = max(2, int(size) // 9)
    step = int(size * 1.04)
    w, h = int(size * 1.5) + 2 * edge, step * len(kana) + 2 * edge + int(size * 0.3)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ch in enumerate(kana):
        cw = d.textlength(ch, font=f)
        q = i / max(1, len(kana) - 1)
        fill = (255, int(176 - 70 * q), int(40 - 20 * q), 255)
        d.text(((w - cw) / 2.0, edge + i * step), ch, font=f, fill=fill, stroke_width=edge, stroke_fill=(24, 8, 0, 255))
    return premultiply(img)


def _lines_art(lines, w, h, size, pitch=1.14):
    """Lines of words centred in a ``w`` x ``h`` box, lettered as the facts card letters its own (off-white, a dark
    edge): premultiplied RGBA."""
    img = Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = _text_font(size)
    step = size * pitch
    y = (h - step * len(lines)) / 2.0
    for line in lines:
        tw = d.textlength(line, font=f)
        d.text(((w - tw) / 2.0, y), line, font=f, fill=(242, 238, 226, 255), stroke_width=max(1, int(size) // 14),
               stroke_fill=(8, 12, 18, 255))
        y += step
    return premultiply(img)


def _wrap(words, width, size):
    """``words`` in lines no wider than ``width`` at ``size`` (a word too long for a line keeps one to itself)."""
    f = _text_font(size)
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    lines, cur = [], ""
    for word in str(words).split():
        trial = (cur + " " + word).strip()
        if cur and d.textlength(trial, font=f) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def _facts(m):
    """A new monster's facts for the facts card: ``(bio, [powers], height, weight)`` - "" / [] for one not given."""
    powers = m.get("powers") or []
    if isinstance(powers, str):
        powers = [p for p in re.split(r"[\n;]+", powers)]
    powers = [" ".join(str(p).split()) for p in powers if str(p).strip()][:3]
    one = lambda key: " ".join(str(m.get(key) or "").split())
    return one("bio"), powers, one("height").upper(), one("weight").upper()


def _twin_portrait(sc, scene, m, pic, picture_node, group_node, name):
    """PAD-1551: a new monster's portrait on a card of twin cards: the card's two frames, the monster's picture in
    the first with its name and katakana lettered on it, and in the second the picture again, dark, behind the
    card's own headings and help lines and the monster's facts."""
    tc = twin_cards(sc, scene)
    med, chrome = tc["med"], tc["chrome"]
    h, w = med.shape[:2]
    out = np.zeros((h, w, 4), np.uint8)
    lx0, ly0, lx1, ly1 = tc["left"]
    rx0, ry0, rx1, ry1 = tc["right"]
    out[ly0:ly1, lx0:lx1] = np.asarray(_cover(pic, lx1 - lx0, ly1 - ly0, 0.45).convert("RGBA"))
    back = _cover(pic, rx1 - rx0, ry1 - ry0, 0.45).filter(ImageFilter.GaussianBlur(max(2, (rx1 - rx0) // 36)))
    dark = np.asarray(back.convert("RGB")).astype(np.float32) * 0.24 + np.array([5.0, 12.0, 20.0], np.float32)
    out[ry0:ry1, rx0:rx1, :3] = (dark + 0.5).clip(0, 255).astype(np.uint8)
    out[ry0:ry1, rx0:rx1, 3] = 255
    keep = chrome.copy()
    e = max(6, w // 64)
    keep[ly0 + e:ly1 - e, lx0 + e:lx1 - e] = False                 # the picture is the monster's, whole
    lum = med[..., 0] * 0.299 + med[..., 1] * 0.587 + med[..., 2] * 0.114
    inner = np.zeros_like(keep)
    inner[ry0 + e:ry1 - e, rx0 + e:rx1 - e] = True
    solid = _mask_filter(_mask_filter(chrome, 3, False), 3, True) & (lum > 56)
    keep = np.where(inner, solid, keep)                             # the facts card: its headings and lines only
    zones = {key: (int(z[0] * w), int(z[1] * h), int(z[2] * w), int(z[3] * h))
             for key, z in (("bio", TWIN_BIO), ("powers", TWIN_POWERS), ("height", TWIN_HEIGHT),
                            ("weight", TWIN_WEIGHT))}
    for x0, y0, x1, y1 in zones.values():
        keep[y0:y1, x0:x1] = False                                  # no place's own words under the new ones
    out[keep] = med[keep]
    # the name across the picture card's foot, the katakana down its left
    art = name_art(str(m["name"]).upper(), "")
    ix0, iy0, ix1, iy1 = ink_box(art)
    lw, lh = lx1 - lx0, ly1 - ly0
    k = min(TWIN_NAME[0] * lw / float(ix1 - ix0), TWIN_NAME[1] * lh / float(iy1 - iy0))
    ink = Image.fromarray(art[iy0:iy1, ix0:ix1], "RGBA").resize(
        (max(1, int(round((ix1 - ix0) * k))), max(1, int(round((iy1 - iy0) * k)))), Image.LANCZOS)
    _paste(out, np.asarray(ink), lx0 + (lw - ink.width) // 2, ly1 - int(TWIN_NAME[2] * lh) - ink.height)
    kana = m.get("kana", katakana(m["name"]))
    if kana:
        size = TWIN_KANA[2] * lh
        room = lh * 0.62
        if size * 1.04 * len(kana) > room:
            size = room / (1.04 * len(kana))
        _paste(out, kana_art(kana, size), lx0 + int(TWIN_KANA[0] * lw - size * 0.75), ly0 + int(TWIN_KANA[1] * lh))
    # the facts
    bio, powers, height, weight = _facts(m)
    if bio:
        x0, y0, x1, y1 = zones["bio"]
        size = h * 0.036
        lines = _wrap(bio, x1 - x0, size)
        while len(lines) * size * 1.14 > (y1 - y0) and size > 9:
            size -= 1
            lines = _wrap(bio, x1 - x0, size)
        _paste(out, _lines_art(lines, x1 - x0, y1 - y0, size), x0, y0)
    if powers:
        x0, y0, x1, y1 = zones["powers"]
        size = h * 0.034
        d = ImageDraw.Draw(Image.new("L", (4, 4)))
        while size > 9 and max(d.textlength(p_, font=_text_font(size)) for p_ in powers) > (x1 - x0):
            size -= 1
        _paste(out, _lines_art(powers, x1 - x0, y1 - y0, size), x0, y0)
    for key, word in (("height", height), ("weight", weight)):
        if word:
            x0, y0, x1, y1 = zones[key]
            _paste(out, _lines_art([word], x1 - x0, y1 - y0, h * 0.036), x0, y0)
    return group_node(name, [picture_node(name + "_Art", out, tc["at"])], rest(sc.body[0]))


def grey_like(sc, colour, slot=0, window=None):
    """A new tile's grey: the place ``slot``'s grey tile, its inside the new colour tile's in the card's own grey -
    the grey's light fitted to the colour tile's on that place (least squares), so a Heisei card's hard black and
    white and a stock card's soft grey both come out as the card draws its own. ``window`` (PAD-1551): where the
    tiles show their monster, when the card's frame is not a plain edge (:func:`tile_window`)."""
    g0 = sc.grey(slot).astype(np.float32)
    c0 = sc.tile[slot].astype(np.float32)
    inside = inner_mask(sc.tile[slot][..., 3], 5) if window is None else window
    lum = lambda a: a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    x, y = lum(c0)[inside], lum(g0)[inside]
    a, b = np.polyfit(x, y, 1) if len(x) > 16 and float(np.std(x)) > 1.0 else (0.8, 0.0)
    out = g0.copy()
    ins = inner_mask(colour[..., 3], 5) if window is None else window
    v = np.clip(lum(colour.astype(np.float32)) * a + b, 0, 255)
    for ch in range(3):
        if window is not None and len(x) > 16 and float(np.std(x)) > 1.0:
            # PAD-1551: such a card tints its greys (Heisei V2.3's are sepia): each colour fitted on its own
            ca, cb = np.polyfit(x, g0[..., ch][inside], 1)
            out[..., ch][ins] = np.clip(lum(colour.astype(np.float32)) * ca + cb, 0, 255)[ins]
            continue
        out[..., ch][ins] = v[ins]
    out[..., 3][ins] = 255
    return (out + 0.5).clip(0, 255).astype(np.uint8)


def stamp_art(word, w, h):
    """PAD-733: a city stamp lettered as the card's box stamps it (white, a dark edge, centred in its box): ``w`` x ``h``
    premultiplied RGBA. A picture, not the box's text: a copy of that text drawn outside its box stopped the game
    (emulator runs fb5, fb6)."""
    img = Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = _font(NAME_FONTS, h * 0.92)
    while f.size > 8 and (d.textlength(word, font=f) > w * 0.94):
        f = _font(NAME_FONTS, f.size - 2)
    edge = max(2, f.size // 12)
    bb = d.textbbox((0, 0), word, font=f, stroke_width=edge)
    x = (w - (bb[2] - bb[0])) / 2.0 - bb[0]
    y = (h - (bb[3] - bb[1])) / 2.0 - bb[1]
    d.text((x, y), word, font=f, fill=(255, 255, 255, 255), stroke_width=edge, stroke_fill=(16, 16, 16, 255))
    return premultiply(img)


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

    def copy_text(name, template, m, words=None):
        """PAD-733: a copy of a text of the card's (its font, size and box), its own words or ``words``, at ``m``"""
        comp = template.components[0]
        body = dict(comp.obj.body) if words is None else dict(comp.obj.body, text=words)
        obj = T.Obj(alloc(), "Text", body)
        scene.objects[obj.id] = obj
        return T.Node(alloc(), name, template.flag, [(1, 1)], [], [(1, track16(m))], [T.Component(comp.start, comp.cls, obj)])

    def blank_text(name, template, m):
        """PAD-733: a copy of a text of the card's, blank (its font must hold a space: the "0/4"'s does)"""
        return copy_text(name, template, m, b" ")

    at, k = layout(sc, [int(m["slot"]) for m in monsters])
    place = lambda key: mul(move(*at[key]), scale(k * sc.unit))     # tile pixels -> CharacterSelect space
    window = tile_window(sc) if sc.lattice else None                 # PAD-1551: a card of diamonds and twin cards
    greys = [sc.grey(s) for s in range(7)]
    # the padlock and the claw as they sit on place 4's tile - read BEFORE the places move: read after, the box had moved
    # and the tile it was measured against had not, and each new tile's claw sat a tile lower (David, v21: "one was way
    # too low")
    lock_px, done_px, lock_m, done_m = _state_pictures(scene, sc)
    prog_t, prog_m = _prog_template(sc)                              # PAD-733: the places' "0/4", read before they move
    cities = _city_templates(sc)                                     # PAD-733: place 4's box's city stamps, the same
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
        colour = framed(sc.tile[0], pic, 5, 0.34) if window is None else framed_window(sc.tile[0], pic, window, 0.34)
        new_kids.append(picture_node(names["Gray"], grey_like(sc, colour, window=window), place(key)))
        lits.append(shown_node(names["Lit"], colour, place(key)))
        # the padlock and the claw sit on a new tile as on place 4's (the right column's first): their pixels -> place
        # 4's tile pixels (lock_m, done_m) -> this tile's place
        if lock_px is not None:
            lits.append(shown_node(names["Lock"], lock_px, mul(place(key), lock_m)))
        if done_px is not None:
            lits.append(shown_node(names["Done"], done_px, mul(place(key), done_m)))
        portraits.append((_twin_portrait if sc.lattice else _portrait_group)(
            sc, scene, m, pic, picture_node, group_node, names["Portrait"]))
        if prog_t is not None:
            # PAD-733: its count, a copy of place 0's words placed on this tile as place 0's sits on its own; blank
            # until the runtime writes the mode's count (pm_roster_more_progress)
            progs.append(blank_text(prog_name(m["slug"]), prog_t, mul(sc.cs, mul(place(key), prog_m))))
        # PAD-733: its city stamps (place 4's box's, as its padlock and claw), for a battle of its lost and held there:
        # each a group the runtime shows and hides, the stamp's word lettered as a picture over the stamp's own box (a
        # copy of the box's TEXT drawn outside the box stopped the game - emulator runs fb5, fb6)
        for c, (node, cm) in enumerate(cities):
            if node is not None:
                body = node.components[0].obj.body
                l, t, r, b = body["rect"]
                word = bytes(body.get("text") or b"").decode("latin-1").strip() or CITY_LABELS[c].upper()
                px = stamp_art(word, (r - l) * 4, (b - t) * 4)
                progs.append(group_node(city_name(m["slug"], c),
                                        [picture_node(city_name(m["slug"], c) + "_Art", px, (0.25, 0.0, 0.0, 0.25, l, t))],
                                        mul(sc.cs, mul(place(key), cm))))
    for s in hosts:
        covers.append(shown_node(cover_name(s), greys[s], place(s)))
        if lock_px is not None:          # PAD-733: the place's own padlock, while a lost new monster holds its battle
            covers.append(shown_node(place_lock_name(s), lock_px, mul(place(s), lock_m)))
    sc.kids[at_sheet:at_sheet] = new_kids
    last_body = max(sc.kids.index(b) for b in sc.body)
    sc.kids[last_body + 1:last_body + 1] = portraits
    last_sel = max(sc.kids.index(n) for n in sc.selected)
    sc.kids[last_sel + 1:last_sel + 1] = covers + lits
    if progs:                                                        # beside the places' own, in the overlay
        at_prog = sc.overlay_kids.index(prog_t if prog_t is not None else sc.art[4])
        sc.overlay_kids[at_prog:at_prog] = progs
    return T.serialize(scene)


def _city_templates(sc):
    """PAD-733: place 4's state box's city stamps - the texts its labels :data:`CITY_LABELS` show - and where each sits
    in place 4's TILE pixels: ``[(node, m)]`` in the cities' order (``(None, None)`` for one the box does not have)."""
    box = sc.art[4]
    sp = sprite_of(box)
    out = []
    to_tile = mul(inv(sc.tile_at[4]), mul(inv(sc.cs), rest(box)))
    frames = dict(sp.body.get("labels") or [])
    for label in CITY_LABELS:
        f = frames.get(label)
        kid = None
        for k in sp.body["kids"]:
            shown = [v for kf, v in k.keyframes if kf <= f] if f is not None else []
            if shown and shown[-1] and k.components and k.components[0].obj.kind == "Text":
                kid = k
                break
        out.append((kid, mul(to_tile, rest(kid)) if kid is not None else None))
    return out


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
                if part in ("Lock", "Done") or re.fullmatch(r"Lock\d+", part):   # PAD-733: a place's own padlock too
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
