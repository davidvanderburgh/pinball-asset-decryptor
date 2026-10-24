"""PAD-707: MORE KAIJU - a selection screen of monsters of our own behind one of Godzilla's battle slots.

The game's BATTLE SELECTION screen has seven slots compiled into its program (MODE_SDK.md, "A monster in the
roster"), so a slot can be taken but not added. MORE KAIJU puts a LIST behind one slot: every mode whose When is
"the player picks it on MORE KAIJU" is one monster on the list behind that slot, and a pick of the slot opens a
selection screen of ours (the runtime's ``pm_roster_more``): the flipper buttons move between the monsters, the
Action button (or the timer) picks, and the monster picked plays as that slot's battle.

This module draws that screen for the card build: ONE PAGE PER MONSTER (``PadMode_<slug>_More``, a screen in the
HUD scene, hidden until the runtime shows it), each the whole glass - the title, the monster's portrait and name
large, and the row of every monster's tile with this one lit - so moving the cursor is showing another page. The
page's words are the timer, which the runtime writes each second.

A monster's picture is ``monster.png`` in its mode's folder (the blocks editor's Picture… on the battle hat puts it
there), else its HUD badge's ``badge.png``, else a tile lettered with its name. Pictures the person gives are theirs;
nothing of a manufacturer's is drawn here."""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import mode_project as MP

#: a page is drawn at half the glass's size and shown at twice that (a quarter of the bytes; the HUD is 1360x768)
PAGE_W, PAGE_H = 680, 384
PAGE_SCALE = 2.0
#: the picture a monster's mode folder holds for its place on the list
PICTURE_FILE = "monster.png"
BADGE_FILE = "badge.png"
#: the most monsters on one list (the runtime's N_MORE)
MAX_MONSTERS = 16
#: the title the screen and the slot's place carry
TITLE = "MORE KAIJU"
HINT = "FLIPPERS TO CHOOSE  -  ACTION BUTTON TO PICK"
#: where the timer's words go on the page (its centre, page pixels) and their size. The HUD's font at this size is
#: about 36 page pixels high, and a line's middle sits TIMER_DROP of its size below the place the words are put
#: (measured on the glass, Premium/LE 1.16: at 1.6 the seconds were 60 px high, their middle 9.4 px below)
TIMER_AT = (612.0, 40.0)
TIMER_SCALE = 0.95
TIMER_DROP = 5.9

GOLD = (255, 204, 40)
WHITE = (255, 255, 255)
FONTS = (r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\arialbd.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/System/Library/Fonts/Supplemental/Impact.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/Library/Fonts/Arial Bold.ttf")


class MoreKaijuError(ValueError):
    """A list that cannot be drawn as asked."""


def page_names(slug):
    """The page node a monster's mode gets, and its words (the runtime finds them as ``<node>.<node>_Words``)."""
    stem = MP.more_page(slug)
    return stem, stem + "." + stem + "_Words"


def _font(size):
    for path in FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _fit(draw, text, max_w, start, least=10):
    size = start
    while size > least:
        f = _font(size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(least)


def picture_of(folder, picture="", screen_art=""):
    """The picture file a monster is drawn with: the one named (in its folder), else ``monster.png``, else its own
    screen's picture, else its badge's ``badge.png``; "" when it has none (it is lettered)."""
    for name in (picture, PICTURE_FILE, screen_art, BADGE_FILE):
        if name and os.path.isfile(os.path.join(folder, name)):
            return os.path.join(folder, name)
    return ""


def _lettered(name, w, h, hue):
    """A monster with no picture of its own: a dark tile in its own colour with its name across it."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    d = ImageDraw.Draw(img)
    r, g, b = hue
    for y in range(h):                                   # a glow from the bottom
        k = (y / max(1, h - 1)) ** 1.6
        d.line((0, y, w, y), fill=(int(r * k * 0.8), int(g * k * 0.8), int(b * k * 0.8), 255))
    words = name.split() or [name]
    lines = [" ".join(words[:(len(words) + 1) // 2]), " ".join(words[(len(words) + 1) // 2:])] if len(words) > 1 else words
    lines = [s for s in lines if s]
    f = _fit(d, max(lines, key=len), int(w * 0.86), int(h * 0.30))
    lh = f.size if hasattr(f, "size") else 12
    top = (h - lh * len(lines) * 1.1) / 2
    for i, s in enumerate(lines):
        tw = d.textlength(s, font=f)
        d.text(((w - tw) / 2, top + i * lh * 1.1), s, font=f, fill=WHITE + (255,), stroke_width=max(1, lh // 14),
               stroke_fill=(0, 0, 0, 255))
    return img


def _hue(i):
    """A colour per monster for the lettered tiles (an even walk round the wheel)."""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((0.02 + i * 0.137) % 1.0, 0.85, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def _fill(img, w, h):
    """``img`` scaled to cover a w x h box and cut to it (the middle kept)."""
    img = img.convert("RGBA")
    k = max(w / img.width, h / img.height)
    img = img.resize((max(w, int(round(img.width * k))), max(h, int(round(img.height * k)))), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _portrait(m, i, w, h):
    if m.get("picture"):
        try:
            return _fill(Image.open(m["picture"]), w, h)
        except OSError:
            pass
    return _lettered(m["name"], w, h, _hue(i))


def _background():
    px = np.zeros((PAGE_H, PAGE_W, 4), dtype=np.float32)
    yy, xx = np.mgrid[0:PAGE_H, 0:PAGE_W].astype(np.float32)
    d = np.sqrt(((xx - PAGE_W * 0.32) / PAGE_W) ** 2 + ((yy - PAGE_H * 0.45) / PAGE_H) ** 2)
    k = np.clip(1.0 - d * 1.7, 0.0, 1.0) ** 1.5
    px[..., 0] = 24 + 150 * k
    px[..., 1] = 4 + 14 * k
    px[..., 2] = 6 + 10 * k
    px[..., 3] = 255
    px[::4, :, :3] *= 0.9                                # the game's screens' scan lines, faintly (still opaque)
    return Image.fromarray(px.astype(np.uint8), "RGBA")


def page_art(monsters, i):
    """Monster ``i``'s page (RGBA array, PAGE_W x PAGE_H): the title, its portrait and name, the hint, the timer's
    box (the runtime letters the seconds in it) and the row of every monster's tile with this one lit."""
    if not 0 <= i < len(monsters):
        raise MoreKaijuError("there is no monster %d on the list" % i)
    m = monsters[i]
    img = _background()
    d = ImageDraw.Draw(img)
    # the title
    tf = _font(34)
    d.text((22, 12), TITLE, font=tf, fill=GOLD + (255,), stroke_width=2, stroke_fill=(60, 0, 0, 255))
    sub = _font(15)
    d.text((24, 52), "CHOOSE YOUR OPPONENT", font=sub, fill=(255, 230, 200, 255))
    # the timer's box: the runtime writes the seconds over it
    cx, cy = TIMER_AT
    d.rounded_rectangle((cx - 40, cy - 26, cx + 40, cy + 26), radius=10, fill=(12, 0, 0, 255), outline=GOLD + (255,),
                        width=3)
    # the portrait, framed
    pw, ph = 236, 206
    px, py = 22, 76
    d.rectangle((px - 4, py - 4, px + pw + 3, py + ph + 3), fill=GOLD + (255,))
    img.paste(_portrait(m, i, pw, ph), (px, py))
    # its name, large, and the hint
    nx = px + pw + 26
    nf = _fit(d, m["name"], PAGE_W - nx - 18, 58, 18)
    d.text((nx, 96), m["name"], font=nf, fill=WHITE + (255,), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    d.text((nx, 170), "%d OF %d" % (i + 1, len(monsters)), font=_font(18), fill=GOLD + (255,))
    d.text((nx, 200), HINT, font=_fit(d, HINT, PAGE_W - nx - 18, 14, 8), fill=(255, 230, 200, 255))
    # the row of tiles: up to 8 about this one
    n = len(monsters)
    show = min(n, 8)
    first = 0 if n <= 8 else min(max(0, i - 3), n - 8)
    tw, th, gap = 66, 52, 10
    left = (PAGE_W - (show * tw + (show - 1) * gap)) // 2
    top = PAGE_H - th - 22
    for k in range(show):
        j = first + k
        x = left + k * (tw + gap)
        tile = _portrait(monsters[j], j, tw, th)
        if j != i:
            arr = np.asarray(tile).astype(np.float32)
            grey = arr[..., :3].mean(axis=2, keepdims=True)
            arr[..., :3] = grey * 0.55
            tile = Image.fromarray(arr.astype(np.uint8), "RGBA")
            d.rectangle((x - 2, top - 2, x + tw + 1, top + th + 1), fill=(70, 70, 70, 255))
        else:
            d.rectangle((x - 4, top - 4, x + tw + 3, top + th + 3), fill=GOLD + (255,))
        img.paste(tile, (x, top))
    if first > 0:
        d.text((left - 22, top + th // 2 - 10), "<", font=_font(20), fill=GOLD + (255,))
    if first + show < n:
        d.text((left + show * (tw + gap) + 4, top + th // 2 - 10), ">", font=_font(20), fill=GOLD + (255,))
    return np.asarray(img)


def page_screen(monsters, i):
    """Monster ``i``'s page as a screen for :func:`.scene_write.add_screens`: the whole glass (drawn at half size,
    shown at twice it), its words the timer (blank until the runtime writes the seconds)."""
    node, text = page_names(monsters[i]["slug"])
    ws = TIMER_SCALE
    words_at = (TIMER_AT[0] - PAGE_W * ws / 2.0, TIMER_AT[1] - TIMER_DROP * ws)
    return dict(name=node, art_rgba=page_art(monsters, i), words=" ", words_name=text.split(".", 1)[1],
                x=0.0, y=0.0, scale=PAGE_SCALE, words_at=words_at, words_scale=ws, words_rgba=(1.0, 0.85, 0.15, 1.0))


def monsters(project, code, forms=()):
    """The monsters on the project's list, in the build's order (form modes, then code modes): ``[{"slug", "name",
    "slot", "picture"}]`` from its form modes that start on a battle with ``roster_more``, and its code modes (blocks
    modes are code modes) whose assets say ``more`` (``{"slot": n, "picture": file}``). Every one must name the same
    slot: there is one list on a card."""
    out = []
    for slug, spec in forms or ():
        if not (MP.starts_on_battle(spec) and getattr(spec, "roster_more", False)):
            continue
        slot = MP._int_or_none(spec.roster_slot)
        if slot is None or slot < 0:
            continue
        folder = MP.mode_folder(project, slug) if project else ""
        out.append({"slug": slug, "name": (spec.name or slug).upper()[:40], "slot": slot,
                    "picture": picture_of(folder, "", getattr(spec, "screen_art", "") or "") if folder else ""})
    for slug, spec in code or ():
        more = getattr(spec, "more", None) or {}
        if not isinstance(more, dict) or more.get("slot") is None:
            continue
        folder = MP.mode_folder(project, slug) if project else ""
        out.append({"slug": slug, "name": (spec.name or slug).upper()[:40], "slot": int(more["slot"]),
                    "picture": picture_of(folder, str(more.get("picture") or ""),
                                          getattr(spec, "screen_art", "") or "") if folder else ""})
    return out


def list_order(found):
    """``found`` in the list's order: the monsters' names, then their pages - the runtime's (pm_roster_more keeps its
    list so, whatever order the modes join in), so a page's "n OF m" and its row of tiles are the cursor's."""
    return sorted(found, key=lambda m: (m["name"].upper(), page_names(m["slug"])[0]))


def problems(found):
    """Why the list cannot be built (sentences; empty = fine)."""
    out = []
    slots = sorted({m["slot"] for m in found})
    if len(slots) > 1:
        out.append("The MORE KAIJU monsters are behind more than one battle (%s): a card has one list, so pick the "
                   "same battle for each." % ", ".join(str(s) for s in slots))
    if len(found) > MAX_MONSTERS:
        out.append("MORE KAIJU holds at most %d monsters (%d chose it)." % (MAX_MONSTERS, len(found)))
    return out


def screens(project, code, prof, forms=()):
    """Every page of the project's list, for the build's one pass over the HUD scene ([] when nothing is on it or the
    title cannot carry screens)."""
    found = list_order(monsters(project, code, forms))
    if not found or not prof.can("screen"):
        return []
    why = problems(found)
    if why:
        raise MoreKaijuError(" ".join(why))
    return [page_screen(found, i) for i in range(len(found))]
