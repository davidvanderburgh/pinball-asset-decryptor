"""Edit pixels: the Images tab's pixel editor for small pictures (PAD-1547).

Captain Gordon asked for a sprite editor for Sonic's (Jersey Jack) micro-LED
ring displays.  Each ring is a 14 x 14 grid of full-colour LEDs on its own
NeoPixel-style board (the operator manual's "Ring NEO Board 15-100633-XX": power,
one data line, ground), and the game draws it from ordinary PNG pictures in
``graphics/Mini LED``: 6,403 of them in Sonic 0.926, 6,211 a single 14 x 14
frame, the rest sheets of 14 x 14 cells (sprite_rectangles tables beside some).

So the editor works on any small PNG slot, on any manufacturer: it opens the
picture the slot has now (its replacement, else the game's own), paints it pixel
by pixel in the page, and saves the result as the slot's replacement in the
project's own "Pixel edits" folder, exactly as if the user had picked the file.

Sonic-era JJP games hold every file at its original byte length, so a save is
encoded as small as it losslessly can be (``core.png_small``) and refused, with
the numbers, when it still does not fit.
"""

import base64
import io
import os
import re

from .base import rpc

#: The biggest picture side the editor opens (a 256 x 256 picture at the
#: smallest zoom is still a 512 px canvas).
MAX_SIDE = 256

#: The most frames listed beside the picture (a folder of frames).
FRAMES_MAX = 600

_RECT_RE = re.compile(r"\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\}")


def _natural(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def sprite_cell(folder, size, ring=False):
    """``[w, h]`` of the frames a sheet picture of *size* is cut into, or None.

    JJP ships its LED sheets with a ``sprite_rectangles`` table beside them
    (``{ x, y, w, h }, // name`` lines); when every rectangle in a table there
    is the same size and the picture divides by it, that is the cell.  A ring
    display picture without one is cut in 14 x 14, the ring's own size.
    """
    w, h = size
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    for name in names:
        if not name.lower().endswith(".txt"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                text = f.read(200000)
        except OSError:
            continue
        if "sprite_rectangles" not in text:
            continue
        sizes = {(int(m.group(3)), int(m.group(4))) for m in _RECT_RE.finditer(text)}
        if len(sizes) == 1:
            cw, ch = sizes.pop()
            if cw and ch and w % cw == 0 and h % ch == 0 and (cw, ch) != (w, h):
                return [cw, ch]
    if ring and (w, h) != (RING, RING) and w % RING == 0 and h % RING == 0:
        return [RING, RING]
    return None


#: A Sonic ring display's side, in LEDs.
RING = 14


def is_ring_picture(rel):
    """Whether *rel* is one of Sonic's ring-display pictures."""
    parts = rel.replace("\\", "/").lower().split("/")
    return "mini led" in parts[:-1]


#: Sonic's own overhead playfield picture (its service-menu test screens draw
#: on it); the ring map is marked on it, so PAD ships no picture of its own.
RING_MAP_PHOTO = "graphics/Game Tests/rip_playfield_overhead_desaturated_resized.jpg"

#: Where Sonic's five ring displays sit (PAD-1549), as fractions of
#: :data:`RING_MAP_PHOTO`'s width and height.  The game program that places
#: them is locked to Sonic's own Sentinel key, so they were measured instead:
#: each ring's centre on Jersey Jack's 2988 x 4509 overhead photo of the
#: Special Edition, carried onto the game's picture by a perspective fit of 83
#: matching features (median error 0.6 px of the 341 x 768 picture).  The
#: game's picture was taken before the rings were fitted, so they are not in
#: it.  The operator manual wires them from three connectors (Left, Center and
#: Right Ring) on the GI LED hub board; which ring hangs on which is in the
#: locked program too, so no name here claims one.
SONIC_RINGS = (
    {"n": 1, "name": "Top left", "where": "behind the Eggman sign, by the top left lane", "x": 0.3581, "y": 0.1247},
    {"n": 2, "name": "Left ramp", "where": "at the left ramp's entrance, under the Eggman sign", "x": 0.3190, "y": 0.2202},
    {"n": 3, "name": "Left orbit", "where": "in the left orbit lane", "x": 0.2103, "y": 0.3192},
    {"n": 4, "name": "Top right", "where": "at the top of the right orbit", "x": 0.9100, "y": 0.1480},
    {"n": 5, "name": "Right ramp", "where": "at the right ramp's entrance", "x": 0.7858, "y": 0.3925},
)


def decode_rgba(w, h, data):
    """The PIL picture of *w* x *h* RGBA bytes sent as base64 *data*."""
    from PIL import Image
    raw = base64.b64decode(data or "")
    if w <= 0 or h <= 0 or len(raw) != w * h * 4:
        raise ValueError("the picture sent is %d bytes, not %d x %d x 4" % (len(raw), w, h))
    return Image.frombytes("RGBA", (w, h), raw)


def same_pixels(a, b):
    """Whether two RGBA pictures show the same: every alpha equal, and every
    colour equal where it can be seen."""
    if a.size != b.size:
        return False
    if a.getchannel("A").tobytes() != b.getchannel("A").tobytes():
        return False
    from ...core.png_small import prepared
    return prepared(a).convert("RGBA").tobytes() == prepared(b).convert("RGBA").tobytes()


class PixelEditMixin:
    """The Images tab's Edit pixels window.  Needs the tab's ``_by_rel``,
    ``_assignments``, ``_scan_dir`` and its replacement bookkeeping."""

    _mfr_key = ""

    # -- what can be edited ---------------------------------------------
    def _pixel_size(self, path):
        from PIL import Image
        try:
            with Image.open(path) as im:
                return im.size
        except Exception:                                # noqa: BLE001
            return None

    def _pixel_orig_path(self, rel):
        """The game's own picture for *rel*: its pristine snapshot when an
        earlier build changed the project's copy, else the project's file."""
        from ...core import staged_originals
        snap = staged_originals.snapshot_path(self._scan_dir or None, rel)
        if snap:
            return snap
        slot = self._by_rel.get(rel)
        return slot.abs_path if slot is not None else None

    def _pixel_start_path(self, rel):
        """The picture the editor opens for *rel*: the replacement picked for
        it when that is a picture it can read, else the game's own."""
        rep = self._assignments.get(rel)
        if isinstance(rep, str) and rep.lower().endswith(".png") and os.path.isfile(rep):
            return rep
        slot = self._by_rel.get(rel)
        return slot.abs_path if slot is not None else None

    def _pixel_offered(self, rel):
        """Whether *rel* opens in the pixel editor: a PNG slot no side of
        which is over :data:`MAX_SIDE`."""
        if not rel or rel not in self._by_rel or not rel.lower().endswith(".png"):
            return False
        if isinstance(self._assignments.get(rel), (list, tuple, dict)):
            return False                                  # a theme set's picks: not one picture
        size = self._pixel_size(self._by_rel[rel].abs_path)
        return bool(size) and max(size) <= MAX_SIDE

    def _pixel_budget(self, rel):
        """The byte size *rel*'s replacement must fit in, or None where the
        game takes any size.  Jersey Jack's Sonic-era games hold every file at
        its original length; a smaller PNG is padded up to it at the Write."""
        if self._mfr_key != "jjp":
            return None
        path = self._pixel_orig_path(rel)
        try:
            return os.path.getsize(path) if path else None
        except OSError:
            return None

    def _pixel_frames(self, rel, size):
        """The PNG slots in *rel*'s folder of the same size, in name order
        (an animation's frames), each ``{rel, path}`` with the picture it
        shows now."""
        folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
        rels = [r for r in self._by_rel
                if (r.rsplit("/", 1)[0] if "/" in r else "") == folder
                and r.lower().endswith(".png")]
        rels.sort(key=lambda r: _natural(r.rsplit("/", 1)[-1]))
        out = []
        for r in rels:
            if r != rel and self._pixel_size(self._by_rel[r].abs_path) != size:
                continue
            out.append({"rel": r, "name": r.rsplit("/", 1)[-1],
                        "path": self._pixel_start_path(r) or ""})
            if len(out) >= FRAMES_MAX:
                break
        return out

    def _ring_map(self):
        """The ring map for Sonic's ring pictures: ``{photo, rings}``, the
        game's own playfield picture from this project and where the rings
        sit on it, or None when the project has no such picture."""
        path = self._pixel_orig_path(RING_MAP_PHOTO) if RING_MAP_PHOTO in self._by_rel else None
        if not path:
            base = self._scan_dir or self._assets_dir()
            path = os.path.join(base, *RING_MAP_PHOTO.split("/")) if base else None
        if not path or not os.path.isfile(path):
            return None
        return {"photo": path, "rings": [dict(r) for r in SONIC_RINGS]}

    def _pixel_edit_path(self, rel):
        from ...core.checksums import PIXEL_EDITS_DIR
        assets = self._scan_dir or self._assets_dir()
        return os.path.join(assets, PIXEL_EDITS_DIR, *rel.split("/"))

    # -- the window ------------------------------------------------------
    @rpc
    def pixel_open(self, rel):
        """What the Edit pixels window shows for slot *rel*, or None."""
        if not self._pixel_offered(rel):
            return None
        from PIL import Image
        start = self._pixel_start_path(rel)
        orig = self._pixel_orig_path(rel)
        try:
            with Image.open(start) as im:
                pic = im.convert("RGBA")
            with Image.open(orig) as im:
                stock = im.convert("RGBA")
        except Exception as e:                           # noqa: BLE001
            self.log("Edit pixels: could not open %s: %s" % (rel, e), "error")
            return None
        if pic.size != stock.size:
            pic = stock                                   # a pick of another size: start from the game's
        slot = self._by_rel[rel]
        ring = self._mfr_key == "jjp" and is_ring_picture(rel)
        frames = self._pixel_frames(rel, stock.size)
        return {
            "rel": rel, "name": rel.rsplit("/", 1)[-1],
            "w": pic.size[0], "h": pic.size[1],
            "data": base64.b64encode(pic.tobytes()).decode("ascii"),
            "orig": base64.b64encode(stock.tobytes()).decode("ascii"),
            "edited": bool(self._assignments.get(rel)),
            "budget": self._pixel_budget(rel),
            "cell": sprite_cell(os.path.dirname(slot.abs_path), stock.size, ring),
            "ring": ring,
            "ringmap": self._ring_map() if ring else None,
            "frames": frames,
            "index": next((i for i, f in enumerate(frames) if f["rel"] == rel), 0),
        }

    @rpc
    def pixel_bytes(self, w, h, data, budget=None):
        """The byte size the picture saves at (the editor's size line)."""
        from ...core.png_small import smallest_png
        try:
            return len(smallest_png(decode_rgba(int(w), int(h), data), budget))
        except Exception:                                # noqa: BLE001
            return None

    @rpc
    def pixel_save(self, rel, w, h, data):
        """Save the edited picture as *rel*'s replacement.

        Returns ``{ok, bytes, budget, msg}``.  The same picture as the game's
        own drops the replacement instead; a picture too big for a slot that
        holds its byte size is not saved."""
        if not self._pixel_offered(rel):
            return {"ok": False, "msg": "This picture can't be edited here."}
        from PIL import Image
        from ...core.png_small import smallest_png
        try:
            pic = decode_rgba(int(w), int(h), data)
            with Image.open(self._pixel_orig_path(rel)) as im:
                stock = im.convert("RGBA")
        except Exception as e:                           # noqa: BLE001
            return {"ok": False, "msg": "Could not read the picture: %s" % e}
        if pic.size != stock.size:
            return {"ok": False, "msg": "The picture is %d x %d; this slot is %d x %d."
                    % (pic.size + stock.size)}
        path = self._pixel_edit_path(rel)
        if same_pixels(pic, stock):
            if self._assignments.get(rel):
                self._clear_replacement_picks([rel], reselect=False)
            try:
                os.remove(path)
            except OSError:
                pass
            self.log("Edit pixels: %s is the game's own picture again, so it has no "
                     "replacement." % rel, "info")
            self._pixel_refresh(rel)
            return {"ok": True, "same": True, "msg": "Same as the game's own picture: no replacement."}
        budget = self._pixel_budget(rel)
        png = smallest_png(pic, budget)
        if budget is not None and len(png) > budget:
            return {"ok": False, "bytes": len(png), "budget": budget,
                    "msg": ("Too big for this slot: it saves at %s bytes and this game holds the "
                            "file at %s. Fewer colors, or larger areas of one color, make it "
                            "smaller." % (format(len(png), ","), format(budget, ",")))}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(png)
        except OSError as e:
            return {"ok": False, "msg": "Could not save the picture: %s" % e}
        self._assignments[rel] = path
        self._save_staged_changes()
        self.log("Edit pixels: %s saved (%s bytes%s) as its replacement." % (
            rel, format(len(png), ","),
            "" if budget is None else ", the slot holds %s" % format(budget, ",")), "info")
        self._pixel_refresh(rel)
        return {"ok": True, "bytes": len(png), "budget": budget, "path": path}

    def _pixel_refresh(self, rel):
        self._refresh_image_list()
        if rel == self._current_rel:
            self._render_preview(rel)
